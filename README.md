# AWS China Cost Analysis Agent

Account-scoped cost analysis agent for Amazon Bedrock AgentCore in `cn-north-1`. It uses Zhipu GLM through Strands `OpenAIModel`, an AWS_IAM AgentCore Gateway, Lambda cost tools, AgentCore Code Interpreter, S3 short-term sessions, and DynamoDB long-term findings.

See the [interactive architecture report](docs/architecture.html), the [Kimi high baseline and GLM benchmark](docs/architecture.html#flow), and [provider notes and rollback](docs/architecture.html#ops).

## Security and scope

- Every Cost Explorer request is forced through `LINKED_ACCOUNT=<deploying account>`. Caller filters can only narrow that scope.
- Credit and Refund records are excluded from cost totals by default.
- Cost Explorer uses `https://ce.cn-northwest-1.amazonaws.com.cn`.
- Pricing uses `https://api.pricing.cn-northwest-1.amazonaws.com.cn` and returns only CNY dimensions.
- Local model credentials come only from the user-owned, gitignored `.env`.
- Runtime reads the secret named by `LLM_SECRET_NAME` from Secrets Manager at process startup. The current value is `cost-agent/glm-api-key`; `cost-agent/llm-api-key` remains authorized for rollback. Keys are never passed to toolkit commands, code, or logs.
- Gateway inbound authorization is `AWS_IAM`; MCP requests use fresh Runtime role credentials for each SigV4 signature.

## Architecture

```text
User -> Cost Agent (Strands + OpenAI-compatible model)
          |-- ReasoningSafeS3SessionManager -> cost-agent-mem-<account>-cn-north-1/sessions/
          |-- run_python -> AgentCore Code Interpreter
          `-- SigV4 MCP -> AgentCore Gateway (AWS_IAM)
                              `-- cost-agent-tools Lambda
                                   |-- Cost Explorer (account filter, 6h cache)
                                   |-- Pricing API (CNY)
                                   |-- cost-agent-ce-cache DynamoDB
                                   `-- cost-agent-knowledge DynamoDB
```

The Runtime constructs a new `Agent` for every request. No Agent instance is shared across sessions. AgentCore Memory is disabled because it is unavailable in AWS China. `ReasoningSafeS3SessionManager` removes `reasoningContent`, `reasoning_content`, `reasoning`, and complete `<think>...</think>` traces when writing and replaying session messages, while retaining text and tool-use blocks. Long-term findings are background only: except when a user explicitly requests no re-query, current answer numbers must come from current-turn cost tools.

The current provider is Zhipu Coding Plan: `glm-5.3-flash` at `https://open.bigmodel.cn/api/coding/paas/v4`. `LLM_TEMPERATURE` and `LLM_REASONING_EFFORT` are optional; when unset, those fields are not sent. GLM then uses its documented defaults: temperature 1, top_p 0.95, thinking enabled, and reasoning effort max. `LLM_MAX_TOKENS` defaults to 8192, below GLM-5.3-Flash's 128K output limit. `VerifiedOpenAIModel` logs and validates the provider-returned model ID.

## Prerequisites

- Windows PowerShell and AWS CLI v2 profile `default`
- Python 3.12
- AWS China credentials for `cn-north-1`
- A local `.env` created by the user from the safe template:

```powershell
Copy-Item .\config.example.env .\.env
# Edit .env locally and replace LLM_API_KEY; never commit it.
```

```dotenv
LLM_API_KEY=<your key>
LLM_MODEL=glm-5.3-flash
LLM_BASE_URL=https://open.bigmodel.cn/api/coding/paas/v4
LLM_SECRET_NAME=cost-agent/glm-api-key
LLM_MAX_TOKENS=8192
```

Never commit `.env` or paste its value into commands, logs, or chat.

Activate the fixed China endpoints in every shell before toolkit commands:

```powershell
. .\scripts\set-env.ps1
```

## Install

The requested versions were checked on the package index before installation.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Quick start for a new AWS China account

Run P0 through P3 in order. `setup_p1.py` writes the git-ignored live `resource_config.json`; `resource_config.example.json` documents its public-safe shape.

## P0: direct local prototype

```powershell
.\scripts\test-p0.ps1
```

This checks Python and pinned packages, confirms the STS ARN uses `arn:aws-cn:`, calls the China Cost Explorer endpoint, checks the configured OpenAI-compatible LLM without printing the key, and tests:

```text
上個月成本 Top 5 服務及環比
```

P0 calls Cost Explorer directly and therefore is not covered by the P1 cache.

## P1: Lambda, DynamoDB cache, and AWS_IAM Gateway

```powershell
. .\scripts\set-env.ps1
.\.venv\Scripts\python.exe .\setup_p1.py
.\scripts\test-p1.ps1
```

`verify_p1.py` invokes the same CE request twice and requires `cache_hit=true` on the second response. It also lists all nine MCP tools. The local agent then answers the P0 test through Gateway.

The China Gateway inline schema model only accepts `type`, `properties`, `required`, `items`, and `description`. Keywords such as `enum`, `default`, `minimum`, and `maximum` must be enforced in Lambda validation rather than included in `toolSchema.inlinePayload`.

Created names:

- Lambda: `cost-agent-tools`
- DynamoDB: `cost-agent-ce-cache`, `cost-agent-knowledge`
- Gateway: `CostAgentGateway`, target `CostAgentTools`
- IAM: `CostAgentToolsLambdaRole`, `CostAgentGatewayRole`

## P2: S3 sessions and DynamoDB findings

```powershell
. .\scripts\set-env.ps1
.\.venv\Scripts\python.exe .\setup_p2.py
.\scripts\test-p2.ps1
```

The verification runs an initial analysis and a follow-up using one S3 session ID, then starts a second session and recalls findings through DynamoDB. It checks that S3 objects and knowledge rows exist.

## P3 checkpoint: create the secret yourself

Do not put the key on a command line shared with another user or in shell history. At the explicit checkpoint, the user runs this command in their own PowerShell, replacing the placeholder locally:

```powershell
aws secretsmanager create-secret --name cost-agent/glm-api-key --secret-string '<KEY>' --region cn-north-1 --profile default
```

If the secret already exists, update it with `aws secretsmanager put-secret-value` rather than creating another secret.

## P3: Runtime

After the secret checkpoint is confirmed:

```powershell
.\scripts\deploy-runtime.ps1
.\scripts\invoke-runtime.ps1 -Prompt "上個月成本 Top 5 服務及環比" -SessionId "costagent-demo-session-000000000000001"
.\.venv\Scripts\python.exe .\verify_p3.py
```

`deploy-runtime.ps1` handles the five integration risks from the workshop:

1. Creates `CostAgentRuntimeRole` with Gateway invoke, Code Interpreter, S3, DynamoDB, secret-read, and logging permissions.
2. Uses `FreshSigV4Auth`, which obtains and freezes credentials separately for every HTTP request.
3. Injects `GATEWAY_URL` as Runtime configuration.
4. Deploys pinned `requirements-runtime.txt` through `direct_code_deploy` on Python 3.12, without Docker. The resulting deployment package is about 43.59 MB and excludes `.env`.
5. Sets a 900-second idle timeout, a 28,800-second maximum lifetime, 60-second MCP startup timeout, and 120-second Lambda timeout. Verification scripts report end-to-end request latency.

### Windows direct-deploy zip check

Starter toolkit `0.3.14` refuses direct-code configuration unless `shutil.which("zip")` succeeds, even though its packager uses Python `zipfile` for all archive operations. `scripts/zip.cmd` is a project-local compatibility marker, and `deploy-runtime.ps1` prepends that directory to `PATH`. It does not package files or replace the installed toolkit.

The configure command uses the required shape:

```powershell
agentcore configure -e runtime_entry.py -r cn-north-1 -dm -dt direct_code_deploy -rt PYTHON_3_12 -n costagent -ni
agentcore deploy -a costagent -auc -env "LLM_SECRET_NAME=cost-agent/glm-api-key" -env "LLM_MODEL=glm-5.3-flash" -env "LLM_BASE_URL=https://open.bigmodel.cn/api/coding/paas/v4"
```

Runtime invocation is tested through both `agentcore invoke --session-id` and `invoke_runtime.py` (`boto3`). `verify_p3.py` requires Runtime `READY` and recent CloudWatch events.

### Verified P3 deployment

- Runtime ARN: `arn:aws-cn:bedrock-agentcore:cn-north-1:<ACCOUNT_ID>:runtime/costagent-<RUNTIME_SUFFIX>`
- Runtime version: `9`, status: `READY`
- Runtime model: `glm-5.3-flash`; returned model ID verified as `glm-5.3-flash`
- Selected reasoning variant: `LLM_REASONING_EFFORT=low` (unset remains supported and uses GLM default max)
- Execution role: `arn:aws-cn:iam::<ACCOUNT_ID>:role/CostAgentRuntimeRole`
- Runtime log group: `/aws/bedrock-agentcore/runtimes/costagent-<RUNTIME_SUFFIX>-DEFAULT`
- Deployment bucket: `cost-agent-deploy-<ACCOUNT_ID>-cn-north-1`

Verified test prompts:

```text
Turn 1: 上個月成本 Top 5 服務及環比。
Turn 2: 剛才第一名的服務再按 USAGE_TYPE 拆，列出 Top 5，並按每日平均成本與前一個月比較。
Turn 3 via CLI: 延續剛才的 USAGE_TYPE 拆分：只告訴我第一名及其日均環比，不要重新查詢成本。
```

The final same-session test stored 48 message files with zero `reasoningContent` blocks. End-to-end latencies were 111.000 seconds, 105.555 seconds, and 28.187 seconds. Returned tool metrics are the authoritative per-invocation counts; Logs Insights provides aggregate counts for the selected time window.

Known deployment diagnostics:

- The first Windows configure attempt returned `Direct Code Deploy deployment unavailable (zip utility not found)`; the project-local compatibility marker described above resolved the toolkit-only check.
- The initial boto3 response reader decoded each stream chunk independently and returned `UnicodeDecodeError: 'utf-8' codec can't decode byte 0xe5 in position 1023: unexpected end of data`; it now joins bytes before UTF-8 decoding.
- The toolkit could not enable Transaction Search because X-Ray lacked `PutLogEvents` on `aws/spans`. Runtime logs and structured Lambda logs are available and verified; Transaction Search remains disabled.

### Historical Kimi low-reasoning benchmark

Historical Runtime version 3 used `k3.1-pro` with `reasoning_effort=low`. A simple local request returned `model=k3.1-pro`, while tool-capable requests received an upstream Kimi error before a complete answer:

```text
openai.InternalServerError: Error code: 500 -
{'error': {'message': 'The server had an error while processing your request',
'type': 'server_error'}}
```

The same error was reproduced through Runtime, the local Gateway agent, a direct typed `reasoning_effort` request, and `extra_body`. That historical Kimi test used the typed SDK parameter; the current GLM configuration omits reasoning effort. The earlier high-effort baseline completed in 111.0 seconds and 105.6 seconds. Low-effort turn 1 failed after 20.393 seconds on its first attempt; a second attempt failed after 35.706 seconds after calling `recall_context`, two `get_cost` calls, `run_python`, and `save_finding`. Its saved finding exactly matched CNY 5,889.38, -1.92%, and EC2 Compute CNY 1,715.12. Low-effort turn 2 in the same session failed after 18.433 seconds after `recall_context` and two `USAGE_TYPE` `get_cost` calls. Those tool results matched `CNW1-BoxUsage:m8i-flex.xlarge` at CNY 1,056.27168; no final model answer or `run_python` percentage was produced. Therefore final-answer quality and the +0.16% presentation cannot be assessed. No cost-analysis tools ran in the failed frontend smoke-test sessions.

## GLM-5.3-Flash quality-fix benchmark (2026-11-23)

All tests used fresh GUID session IDs and returned `glm-5.3-flash`. The fixed policy made memory background-only and required current-turn cost tools unless the user explicitly asks not to query again.

| Variant / Runtime | T1 latency and tools | T2 latency and tools | Ground truth / quality |
|---|---|---|---|
| Default unset → max, v5 | 173.645s; recall, get_cost ×2, compare, run_python, save | 297.559s; recall, get_cost ×2, run_python, save | numbers matched; T1 reversed compare-period direction, detected the sign mismatch, then corrected it with Python |
| High, v6 | 114.032s; recall, compare, get_cost ×2, run_python, save | 60.180s; recall, get_cost ×2, run_python, save | numbers matched; live queries used; no unsupported EC2-Other composition |
| Low, v7 | **54.745s**; recall, compare, get_cost ×2, run_python, save | **33.475s**; recall, get_cost ×2, run_python, save | numbers matched; live queries used; no missing required tools or unsupported causal claims |

Ground truth matched in every variant: October total CNY 5,889.38, daily-average MoM −1.92%, EC2 Compute CNY 1,715.12, and `CNW1-BoxUsage:m8i-flex.xlarge` CNY 1,056.27 at +0.16%.

Low was selected because it was correct and compliant, then fastest. Runtime v9 contains the explicit requirement to validate date-window arithmetic with `run_python` and remains deployed with `LLM_REASONING_EFFORT=low`. A final fresh-session T1 sanity check on v9 took 49.319s and called recall ×1, compare ×1, get_cost ×2, run_python ×2, and save ×1; all ground-truth values matched.

| Low quick prompt | Latency | Tool calls | Result |
|---|---:|---|---|
| Month-to-date and forecast | 37.520s | recall, get_forecast ×1, get_cost ×2, run_python, save | completed; forecast needed no invalid retry |
| RI/SP coverage and utilization | 25.428s | recall, RI/SP ×1, run_python, save | RI values returned; unavailable SP utilization returned as structured `unavailable` |
| Last 30 days anomalies, final v9 | 63.735s | recall ×1, run_python ×2, get_anomalies ×1, get_cost ×1, save ×1 | zero anomalies; date window verified with Python; rolling-window total also queried live |

The first v7 anomaly check took 20.313s but omitted `run_python`; v8 fixed and retested it, and the final v9 verification expanded the analysis with one live `get_cost` call. The forecast tool now clamps past starts to current UTC date and returns `start_adjusted`, `end_adjusted`, and `start_adjusted_note`. Live verification adjusted 2026-11-01 to 2026-11-23. RI/SP now returns `partial_unavailable` with `sp_utilization.status=unavailable` instead of raising `DataUnavailableException`.

Quality findings: the fixed prompt prevented stale answers despite earlier `save_finding` records. Current-turn T1/T2 cost tools were used in all variants; arithmetic used `run_python`; no invented dimension or EC2-Other composition was observed; hypotheses remained in `待確認`; recall/save were present. The max variant's reversed comparison arguments were the only benchmark tool-parameter issue and were corrected before reporting.

Official GLM documentation: [GLM-5.3-Flash](https://docs.bigmodel.cn/cn/guide/models/vlm/glm-5.3-flash.md), [thinking modes](https://docs.bigmodel.cn/cn/guide/capabilities/thinking-mode.md), and [function calling](https://docs.bigmodel.cn/cn/guide/capabilities/function-calling.md). The model accepts direct `reasoning_effort=low|high|max`, defaults to max, requires thinking enabled, and returns streamed `reasoning_content`. Content was rephrased for compliance with licensing restrictions.

## Roll back to Kimi

The old `cost-agent/llm-api-key` secret remains unchanged and authorized alongside the GLM secret. One command restores the prior high-effort Kimi configuration and redeploys:

```powershell
.\scripts\deploy-kimi-rollback.ps1
```

The rollback script selects `k3.1-pro`, `https://api.kimi.com/coding/v1`, temperature 1, reasoning effort `high`, and `max_tokens=8192`. It does not copy or expose either key.

## Local frontend

The Streamlit UI binds only to `127.0.0.1`, uses local AWS profile `default`, and invokes the AgentCore China data-plane endpoint with a 600-second boto3 read timeout. It contains no AWS keys or LLM key. It provides Markdown chat, switchable UI session history, new-session IDs of at least 33 characters, latency and tool metrics, five quick prompts, optional date range and grouping, and friendly timeout/throttling/not-ready errors.

Pinned frontend dependencies are `streamlit==1.67.0` and `boto3==1.43.110`.

Install and run:

```powershell
.\.venv\Scripts\python.exe -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r .\frontend\requirements.txt
.\scripts\run-frontend.ps1
```

Open `http://127.0.0.1:8501`. The health endpoint and root page both returned HTTP 200 while bound to `127.0.0.1`; the test process was stopped afterward.

Quick prompts:

- `上月 Top 5 服務及環比`
- `本月至今成本與預測`
- `RI·SP 覆蓋率與使用率`
- `最近 30 天成本異常`
- `指定服務按 USAGE_TYPE 拆分`

Programmatic smoke test:

```powershell
.\.venv\Scripts\python.exe .\frontend\smoke_test.py
```

The current GLM forecast, RI/SP, and anomaly smoke-test results are documented in the GLM benchmark section below.

## Tool behavior

- `get_cost`: Top-N, Others, total, periods, 6-hour cache marker.
- `compare_periods`: daily-average normalized period and service deltas.
- `get_forecast`: account-scoped unblended-cost forecast; past starts clamp to current UTC date and return adjustment fields.
- `get_ri_sp_coverage_utilization`: RI and Savings Plans totals; unavailable components return structured status instead of failing.
- `get_anomalies`: only anomalies with root causes attributed to the deploying account.
- `get_dimension_values`: account-scoped CE dimension values.
- `get_price`: compact CNY on-demand Pricing API results.
- `recall_context`: dated background findings only; current numbers require current-turn cost tools unless the user explicitly forbids re-querying.
- `save_finding`: DynamoDB long-term findings.
- `run_python`: AgentCore Code Interpreter; relative file paths only.

Gateway prefixes names as `CostAgentTools___<tool>`. Lambda dispatch deliberately uses `endswith`.

## Observability

Lambda and `run_python` emit one compact JSON record per call:

```json
{"event":"tool_call","tool":"get_cost","duration_ms":123.45,"ok":true}
```

Runtime logs are under `/aws/bedrock-agentcore/runtimes/`; Lambda logs are under `/aws/lambda/cost-agent-tools`.

## Cost notes

Cost Explorer charges per API request, so identical CE calls are cached for six hours. AgentCore Runtime and Gateway remain deployed and can continue generating charges even while this project is not being edited; run the guarded cleanup when they are no longer needed. Other possible charges include Code Interpreter active time, Lambda, DynamoDB, S3, CloudWatch Logs, and external-model tokens. GLM Coding Plan and Kimi rollback charges do not appear on the AWS bill. `code_session` stops Code Interpreter sessions after each call.

## Cleanup

`cleanup.py` is intentionally guarded and is never run automatically. It covers every Runtime version and endpoint, the Runtime execution role, deployment bucket, S3 session bucket, both DynamoDB tables, Gateway target and Gateway, Lambda, project IAM roles, and CloudWatch log groups. Both model secrets are preserved by default. `--delete-secret` deletes only the current secret recorded in `resource_config.json`; the Kimi rollback secret remains untouched unless separately removed by its owner.

```powershell
. .\scripts\set-env.ps1
.\.venv\Scripts\python.exe .\cleanup.py --dry-run
.\.venv\Scripts\python.exe .\cleanup.py --confirm DELETE
# Also permanently delete the current GLM secret only when explicitly intended:
.\.venv\Scripts\python.exe .\cleanup.py --confirm DELETE --delete-secret
```

Review the dry-run listing first. `--delete-secret` uses immediate secret deletion and cannot be undone. Do not run cleanup while the agent is still needed.
