. "$PSScriptRoot\set-env.ps1"
& "$PSScriptRoot\..\.venv\Scripts\python.exe" "$PSScriptRoot\..\check_env.py"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& "$PSScriptRoot\..\.venv\Scripts\python.exe" -m agent.direct_agent --prompt "上個月成本 Top 5 服務及環比"
