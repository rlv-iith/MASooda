# One-command Week 6 pipeline (workflow 14.8). Same arguments as scripts/run_all.py:
#   powershell -ExecutionPolicy Bypass -File scripts\run_all.ps1 [--quick] [--only e1,e4] [--skip-video] [--workers N] [--fresh]
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
if ($env:PYTHON) { $py = $env:PYTHON }
elseif (Test-Path ".venv\Scripts\python.exe") { $py = ".venv\Scripts\python.exe" }
else { $py = "python" }
& $py scripts/run_all.py @args
exit $LASTEXITCODE
