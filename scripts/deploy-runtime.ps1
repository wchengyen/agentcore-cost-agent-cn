$ErrorActionPreference = "Stop"
$env:PATH = "$PSScriptRoot;$env:PATH"
. "$PSScriptRoot\set-env.ps1"
$python = "$PSScriptRoot\..\.venv\Scripts\python.exe"
$agentcore = "$PSScriptRoot\..\.venv\Scripts\agentcore.exe"
$dotenv = "$PSScriptRoot\..\.env"

function Get-ConfigValue([string]$Name, [string]$Default = "") {
    $processValue = [Environment]::GetEnvironmentVariable($Name, "Process")
    if ($processValue) { return $processValue }
    $match = Select-String -Path $dotenv -Pattern ("^\s*" + [regex]::Escape($Name) + "\s*=") | Select-Object -Last 1
    if (-not $match) { return $Default }
    return (($match.Line -split "=", 2)[1]).Trim().Trim('"').Trim("'")
}

$model = Get-ConfigValue "LLM_MODEL" "glm-5.3-flash"
$baseUrl = Get-ConfigValue "LLM_BASE_URL" "https://open.bigmodel.cn/api/coding/paas/v4"
$secretName = Get-ConfigValue "LLM_SECRET_NAME" "cost-agent/glm-api-key"
$temperature = Get-ConfigValue "LLM_TEMPERATURE"
$reasoningEffort = Get-ConfigValue "LLM_REASONING_EFFORT"
$maxTokens = Get-ConfigValue "LLM_MAX_TOKENS" "8192"
$env:LLM_SECRET_NAME = $secretName

& $python "$PSScriptRoot\..\setup_p3_role.py"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$config = Get-Content "$PSScriptRoot\..\resource_config.json" -Raw | ConvertFrom-Json
& $agentcore configure -e runtime_entry.py -r cn-north-1 -dm -dt direct_code_deploy -rt PYTHON_3_12 -n costagent -ni -er $config.runtime_role_arn -rf requirements-runtime.txt -s3 $config.deployment_bucket --idle-timeout 900 --max-lifetime 28800
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$deployArgs = @(
    "deploy", "-a", "costagent", "-auc",
    "-env", "LLM_SECRET_NAME=$secretName",
    "-env", "LLM_MODEL=$model",
    "-env", "LLM_BASE_URL=$baseUrl",
    "-env", "LLM_MAX_TOKENS=$maxTokens",
    "-env", "GATEWAY_URL=$($config.gateway_url)",
    "-env", "SESSION_BUCKET=$($config.session_bucket)",
    "-env", "DEPLOYING_ACCOUNT_ID=$($config.account_id)",
    "-env", "AWS_REGION=cn-north-1",
    "-env", "BEDROCK_AGENTCORE_CP_ENDPOINT=https://bedrock-agentcore-control.cn-north-1.amazonaws.com.cn",
    "-env", "BEDROCK_AGENTCORE_DP_ENDPOINT=https://bedrock-agentcore.cn-north-1.amazonaws.com.cn"
)
if ($temperature) { $deployArgs += @("-env", "LLM_TEMPERATURE=$temperature") }
if ($reasoningEffort) { $deployArgs += @("-env", "LLM_REASONING_EFFORT=$reasoningEffort") }
& $agentcore @deployArgs
