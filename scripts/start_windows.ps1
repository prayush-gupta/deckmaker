$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)

function Find-Python312 {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        & $py.Source -3.12 --version *> $null
        if ($LASTEXITCODE -eq 0) { return @($py.Source, '-3.12') }
    }
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:ProgramFiles\Python312\python.exe",
        'C:\Python312\python.exe'
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) { return @($candidate) }
    }
    return $null
}

$python = Find-Python312
if (-not $python) {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        Write-Host 'Python 3.12 was not found. Installing it with winget...' -ForegroundColor Cyan
        & $winget.Source install --id Python.Python.3.12 -e --source winget --accept-package-agreements --accept-source-agreements
        $python = Find-Python312
    }
}
if (-not $python) {
    Write-Host 'Python 3.12 is required. Install it from https://www.python.org/downloads/ and rerun start_windows.bat.' -ForegroundColor Red
    exit 2
}

$git = Get-Command git -ErrorAction SilentlyContinue
if (-not $git) {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        Write-Host 'Git was not found. Installing it with winget...' -ForegroundColor Cyan
        & $winget.Source install --id Git.Git -e --source winget --accept-package-agreements --accept-source-agreements
        foreach ($candidate in @('C:\Program Files\Git\cmd\git.exe', "$env:LOCALAPPDATA\Programs\Git\cmd\git.exe")) {
            if (Test-Path $candidate) { $env:PATH = (Split-Path $candidate) + ';' + $env:PATH; break }
        }
    }
}

$exe = $python[0]
$arguments = @()
if ($python.Length -gt 1) { $arguments += $python[1..($python.Length - 1)] }
$arguments += (Join-Path (Get-Location) 'setup_environment.py')
& $exe @arguments
exit $LASTEXITCODE
