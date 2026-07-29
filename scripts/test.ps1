$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$previousPythonPath = $env:PYTHONPATH

try {
    $env:PYTHONPATH = Join-Path $projectRoot 'src'
    Push-Location $projectRoot
    python -m unittest discover -s tests -v
}
finally {
    Pop-Location
    $env:PYTHONPATH = $previousPythonPath
}
