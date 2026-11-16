$ErrorActionPreference='Stop'
$appRoot=Split-Path -Parent $PSScriptRoot
$appPython=Join-Path $appRoot '.venv\Scripts\python.exe'
if(-not (Test-Path -LiteralPath $appPython)){throw 'Run scripts/setup.ps1 first.'}
Push-Location $appRoot
try {
    & $appPython scripts/check_runtime.py
    if($LASTEXITCODE -ne 0){throw 'Runtime prerequisites are not satisfied.'}
    & $appPython -m pipeline.verify
    if($LASTEXITCODE -ne 0){throw 'Dataset verification failed.'}
    Push-Location (Join-Path $appRoot 'frontend')
    try {
        & npm.cmd test
        if($LASTEXITCODE -ne 0){throw 'Frontend tests failed.'}
        & npm.cmd run build
        if($LASTEXITCODE -ne 0){throw 'Frontend build failed.'}
    } finally {Pop-Location}
    & $appPython -m unittest discover -s tests -q
    if($LASTEXITCODE -ne 0){throw 'Backend tests failed.'}
} finally {Pop-Location}
