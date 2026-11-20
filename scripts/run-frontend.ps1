$ErrorActionPreference = "Stop"
. "$PSScriptRoot\set-env.ps1"
$python = "$PSScriptRoot\..\.venv\Scripts\python.exe"
& $python -m streamlit run "$PSScriptRoot\..\frontend\app.py" --server.address 127.0.0.1 --server.port 8501 --server.headless true --browser.gatherUsageStats false
