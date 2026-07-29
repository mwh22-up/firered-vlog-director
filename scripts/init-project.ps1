param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectsRoot,

    [Parameter(Mandatory = $true)]
    [string]$ProjectId
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$previousPythonPath = $env:PYTHONPATH

try {
    $env:PYTHONPATH = Join-Path $projectRoot 'src'
    Push-Location $projectRoot
    python -m vlog_director.cli init-project `
        --root $ProjectsRoot `
        --project-id $ProjectId
}
finally {
    Pop-Location
    $env:PYTHONPATH = $previousPythonPath
}
