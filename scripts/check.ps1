$ErrorActionPreference='Stop'
$appRoot=Split-Path -Parent $PSScriptRoot
$appPython=Join-Path $appRoot '.venv\Scripts\python.exe'
Push-Location $appRoot
try {
    & $appPython -m pipeline.verify
    if($LASTEXITCODE -ne 0){throw 'Dataset verification failed.'}
    & $appPython -m unittest discover -s tests -q
    if($LASTEXITCODE -ne 0){throw 'Backend tests failed.'}
    Push-Location (Join-Path $appRoot 'frontend')
    try {
        & npm.cmd test
        if($LASTEXITCODE -ne 0){throw 'Frontend tests failed.'}
        & npm.cmd run build
        if($LASTEXITCODE -ne 0){throw 'Frontend build failed.'}
    } finally {Pop-Location}
} finally {Pop-Location}
