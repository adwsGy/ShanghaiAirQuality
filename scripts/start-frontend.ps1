param([int]$Port=5173,[int]$ApiPort=8000)
$ErrorActionPreference='Stop'
$appRoot=Split-Path -Parent $PSScriptRoot
$previousApiTarget=$env:AIR_API_TARGET
Push-Location (Join-Path $appRoot 'frontend')
try {
    $env:AIR_API_TARGET="http://127.0.0.1:$ApiPort"
    & npm.cmd run dev -- --port $Port
    if($LASTEXITCODE -ne 0){throw 'Frontend exited with an error.'}
} finally {
    $env:AIR_API_TARGET=$previousApiTarget
    Pop-Location
}

