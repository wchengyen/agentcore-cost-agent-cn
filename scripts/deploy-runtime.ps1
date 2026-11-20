$ErrorActionPreference = "Stop"
$env:PATH = "$PSScriptRoot;$env:PATH"
. "$PSScriptRoot\set-env.ps1"
$python = "$PSScriptRoot\..\.venv\Scripts\python.exe"
$agentcore = "$PSScriptRoot\..\.venv\Scripts\agentcore.exe"
& $python "$PSScriptRoot\..\setup_p3_role.py"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$config = Get-Content "$PSScriptRoot\..\resource_config.json" -Raw | ConvertFrom-Json
& $agentcore configure -e runtime_entry.py -r cn-north-1 -dm -dt direct_code_deploy -rt PYTHON_3_12 -n costagent -ni -er $config.runtime_role_arn -rf requirements-runtime.txt -s3 $config.deployment_bucket --idle-timeout 900 --max-lifetime 28800
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $agentcore deploy -a costagent -auc -env "LLM_SECRET_NAME=cost-agent/llm-api-key" -env "LLM_MODEL=k3.1-pro" -env "LLM_BASE_URL=https://api.kimi.com/coding/v1" -env "LLM_REASONING_EFFORT=low" -env "GATEWAY_URL=$($config.gateway_url)" -env "SESSION_BUCKET=$($config.session_bucket)" -env "DEPLOYING_ACCOUNT_ID=$($config.account_id)" -env "AWS_REGION=cn-north-1" -env "BEDROCK_AGENTCORE_CP_ENDPOINT=https://bedrock-agentcore-control.cn-north-1.amazonaws.com.cn" -env "BEDROCK_AGENTCORE_DP_ENDPOINT=https://bedrock-agentcore.cn-north-1.amazonaws.com.cn"
