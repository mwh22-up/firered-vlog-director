param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectPath,

    [Parameter(Mandatory = $true)]
    [int]$Version,

    [string]$BaseVideo = "output\preview.mp4",
    [string]$OutputVideo = "output\final.mp4",
    [string]$FFmpegExecutable = "ffmpeg"
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$previousPythonPath = $env:PYTHONPATH
$resolvedProject = (Resolve-Path -LiteralPath $ProjectPath).Path
$planPath = Join-Path $resolvedProject "work\enhancement\enhancement_plan.v$Version.json"
$basePath = Join-Path $resolvedProject $BaseVideo
$outputPath = Join-Path $resolvedProject $OutputVideo

try {
    $env:PYTHONPATH = Join-Path $repositoryRoot 'src'
    Push-Location $repositoryRoot
    .\scripts\guard-render.ps1 -ProjectPath $resolvedProject -Version $Version
    .\scripts\guard-enhancement.ps1 -ProjectPath $resolvedProject -Version $Version
    python -m vlog_director.cli render-enhancement `
        --project $resolvedProject `
        --base-video $basePath `
        --plan $planPath `
        --output $outputPath `
        --ffmpeg-executable $FFmpegExecutable
}
finally {
    Pop-Location
    $env:PYTHONPATH = $previousPythonPath
}
