param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectPath,

    [Parameter(Mandatory = $true)]
    [int]$Version,

    [ValidateSet('preview', 'release')]
    [string]$Mode = 'preview'
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$previousPythonPath = $env:PYTHONPATH

try {
    $env:PYTHONPATH = Join-Path $projectRoot 'src'
    Push-Location $projectRoot
    python -m vlog_director.cli guard-enhancement `
        --project $ProjectPath `
        --version $Version `
        --mode $Mode
    if ($LASTEXITCODE -ne 0) {
        throw "Enhancement guard blocked final render with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
    $env:PYTHONPATH = $previousPythonPath
}
