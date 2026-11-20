param(
  [string]$Prompt = "上個月成本 Top 5 服務及環比",
  [string]$SessionId = "costagent-demo-session-000000000000001"
)
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\set-env.ps1"
$agentcore = "$PSScriptRoot\..\.venv\Scripts\agentcore.exe"
$python = "$PSScriptRoot\..\.venv\Scripts\python.exe"
$payload = @{ prompt = $Prompt } | ConvertTo-Json -Compress
$watch = [System.Diagnostics.Stopwatch]::StartNew()
& $agentcore invoke $payload -a costagent --session-id $SessionId
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$watch.Stop()
Write-Host "CLI turn latency: $([math]::Round($watch.Elapsed.TotalSeconds, 3)) seconds"
$watch.Restart()
& $python "$PSScriptRoot\..\invoke_runtime.py" --prompt "延續上一輪：最高成本服務是什麼？只引用上一輪口徑。" --session-id $SessionId
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$watch.Stop()
Write-Host "boto3 follow-up latency: $([math]::Round($watch.Elapsed.TotalSeconds, 3)) seconds"
