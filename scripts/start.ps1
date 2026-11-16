param([int]$Port=8000)
$ErrorActionPreference='Stop'
$appRoot=Split-Path -Parent $PSScriptRoot
if(-not (Test-Path -LiteralPath (Join-Path $appRoot 'frontend/dist/index.html'))){throw 'Run scripts/setup.ps1 or build the frontend first.'}
& (Join-Path $PSScriptRoot 'start-backend.ps1') -Port $Port

