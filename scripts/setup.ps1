param([string]$Python='python')
$ErrorActionPreference='Stop'
$appRoot=Split-Path -Parent $PSScriptRoot
Push-Location $appRoot
try {
    $appPython=Join-Path $appRoot '.venv\Scripts\python.exe'
    if(-not (Test-Path -LiteralPath $appPython)){
        & $Python -m venv .venv
        if($LASTEXITCODE -ne 0){throw 'Cannot create the Python 3.12 environment. Pass -Python with the installed interpreter path.'}
    }
    & $appPython -m pip install --disable-pip-version-check -r requirements-lock.txt
    if($LASTEXITCODE -ne 0){throw 'Python dependency installation failed.'}
    Push-Location (Join-Path $appRoot 'frontend')
    try {
        & npm.cmd ci
        if($LASTEXITCODE -ne 0){throw 'Frontend dependency installation failed.'}
        & npm.cmd run build
        if($LASTEXITCODE -ne 0){throw 'Frontend build failed.'}
    } finally {Pop-Location}
    & $appPython -m pipeline.verify
    if($LASTEXITCODE -ne 0){throw 'The bundled dataset failed verification.'}
    Write-Host 'Ready. Start the backend and frontend, or run scripts/start.ps1.'
} finally {Pop-Location}

