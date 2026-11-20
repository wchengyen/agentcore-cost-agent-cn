. "$PSScriptRoot\set-env.ps1"
& "$PSScriptRoot\..\.venv\Scripts\python.exe" "$PSScriptRoot\..\verify_p1.py"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& "$PSScriptRoot\..\.venv\Scripts\python.exe" -m agent.local_gateway --no-s3 --prompt "上個月成本 Top 5 服務及環比"
