param([string]$Python='')
$ErrorActionPreference='Stop'
$appRoot=Split-Path -Parent $PSScriptRoot
Push-Location $appRoot
try {
    $appPython=Join-Path $appRoot '.venv\Scripts\python.exe'
    if(-not (Test-Path -LiteralPath $appPython)){
        $bootstrapPython=$Python
        $bootstrapArgs=@()
        if(-not $bootstrapPython){
            $candidates=@(
                [pscustomobject]@{Name='py'; Arguments=@('-3.12')},
                [pscustomobject]@{Name='python3.12'; Arguments=@()},
                [pscustomobject]@{Name='python'; Arguments=@()},
                [pscustomobject]@{Name='python3'; Arguments=@()}
            )
            foreach($candidate in $candidates){
                $candidateCommand=Get-Command $candidate.Name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
                if(-not $candidateCommand -or $candidateCommand.Source -like '*\Microsoft\WindowsApps\*'){continue}
                $candidateArgs=@($candidate.Arguments)
                try {
                    & $candidateCommand.Source @candidateArgs -c 'import sys; sys.exit(sys.version_info[:2] != (3, 12))' *> $null
                    if($LASTEXITCODE -eq 0){
                        $bootstrapPython=$candidateCommand.Source
                        $bootstrapArgs=$candidateArgs
                        break
                    }
                } catch {continue}
            }
        }
        if(-not $bootstrapPython){throw 'Python 3.12 was not found. Install it, or pass -Python with its interpreter path.'}
        & $bootstrapPython @bootstrapArgs scripts/check_runtime.py
        if($LASTEXITCODE -ne 0){throw 'Runtime prerequisites are not satisfied.'}
        & $bootstrapPython @bootstrapArgs -m venv .venv
        if($LASTEXITCODE -ne 0){throw 'Cannot create the Python 3.12 environment. Pass -Python with the installed interpreter path.'}
    } else {
        & $appPython scripts/check_runtime.py
        if($LASTEXITCODE -ne 0){throw 'Runtime prerequisites are not satisfied.'}
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

