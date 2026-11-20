$env:AWS_PROFILE = "default"
$env:AWS_REGION = "cn-north-1"
$env:AWS_DEFAULT_REGION = "cn-north-1"
$env:AGENTCORE_SUPPRESS_RECOMMENDATION = "1"
$env:BEDROCK_AGENTCORE_CP_ENDPOINT = "https://bedrock-agentcore-control.cn-north-1.amazonaws.com.cn"
$env:BEDROCK_AGENTCORE_DP_ENDPOINT = "https://bedrock-agentcore.cn-north-1.amazonaws.com.cn"
if (-not $env:LLM_REASONING_EFFORT) { $env:LLM_REASONING_EFFORT = "low" }
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [Console]::OutputEncoding
Write-Host "AWS China AgentCore environment configured."
