param(
    [Parameter(Mandatory = $true)]
    [string]$InputVideo,

    [Parameter(Mandatory = $true)]
    [string]$OutputVideo,

    [double]$Strength = 0.35,
    [double]$MaxCropPercent = 8.0,
    [string]$FFmpegExecutable = "ffmpeg"
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$previousPythonPath = $env:PYTHONPATH
$workDirectory = Join-Path ([System.IO.Path]::GetDirectoryName((Resolve-Path -LiteralPath $InputVideo).Path)) '.vidstab'

try {
    $env:PYTHONPATH = Join-Path $repositoryRoot 'src'
    Push-Location $repositoryRoot
    python -m vlog_director.cli stabilize `
        --input $InputVideo `
        --output $OutputVideo `
        --work-directory $workDirectory `
        --strength $Strength `
        --max-crop-percent $MaxCropPercent `
        --ffmpeg-executable $FFmpegExecutable
}
finally {
    Pop-Location
    $env:PYTHONPATH = $previousPythonPath
}
