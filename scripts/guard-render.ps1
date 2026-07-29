param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectPath,

    [Parameter(Mandatory = $true)]
    [int]$Version
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$previousPythonPath = $env:PYTHONPATH

try {
    $env:PYTHONPATH = Join-Path $projectRoot 'src'
    Push-Location $projectRoot
    python -m vlog_director.cli guard-render `
        --project $ProjectPath `
        --version $Version `
        --policy (Join-Path $projectRoot 'policies\moment-protection.json')
    if ($LASTEXITCODE -ne 0) {
        throw "Protection guard blocked render with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
    $env:PYTHONPATH = $previousPythonPath
}
