param([int]$Port=8000,[switch]$Reload)
$ErrorActionPreference='Stop'
$appRoot=Split-Path -Parent $PSScriptRoot
$appPython=Join-Path $appRoot '.venv\Scripts\python.exe'
if(-not (Test-Path -LiteralPath $appPython)){throw 'Run scripts/setup.ps1 first.'}
Push-Location $appRoot
try {
    $appArgs=@('-m','uvicorn','api.app:app','--host','127.0.0.1','--port',"$Port")
    if($Reload){$appArgs+='--reload'}
    & $appPython @appArgs
    if($LASTEXITCODE -ne 0){throw 'Backend exited with an error.'}
} finally {Pop-Location}

