param(
    [Parameter(Mandatory = $true)] [string]$ProjectPath,
    [Parameter(Mandatory = $true)] [string]$ParentPlan,
    [Parameter(Mandatory = $true)] [string]$Profile,
    [Parameter(Mandatory = $true)] [string]$Moments,
    [Parameter(Mandatory = $true)] [int]$Version,
    [Parameter(Mandatory = $true)] [double]$TargetDurationSec,
    [string]$Feedback,
    [string]$AsrModel = 'small'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$project = (Resolve-Path -LiteralPath $ProjectPath).Path
$parent = (Resolve-Path -LiteralPath $ParentPlan).Path
$profilePath = (Resolve-Path -LiteralPath $Profile).Path
$momentsPath = (Resolve-Path -LiteralPath $Moments).Path
$analysisDirectory = Join-Path $project "work\director\target-analysis"
$proposalDirectory = Join-Path $project "work\director\v$Version-proposal"
$previousPythonPath = $env:PYTHONPATH

try {
    $env:PYTHONPATH = Join-Path $root 'src'
    Push-Location $root
    python -m vlog_director.cli analyze-project `
        --project $project `
        --output-directory $analysisDirectory `
        --asr-provider faster-whisper `
        --asr-model $AsrModel
    if ($LASTEXITCODE -ne 0) { throw "Target analysis failed with exit code $LASTEXITCODE" }

    $directorArgs = @(
        '-m', 'vlog_director.cli', 'direct-timeline',
        '--parent', $parent,
        '--analysis-directory', $analysisDirectory,
        '--profile', $profilePath,
        '--moments', $momentsPath,
        '--version', $Version,
        '--target-duration-sec', $TargetDurationSec,
        '--output-directory', $proposalDirectory
    )
    if ($Feedback) {
        $feedbackPath = (Resolve-Path -LiteralPath $Feedback).Path
        $directorArgs += @('--feedback', $feedbackPath)
    }
    python @directorArgs
    if ($LASTEXITCODE -notin @(0, 2)) { throw "Director proposal failed with exit code $LASTEXITCODE" }
    if ($LASTEXITCODE -eq 2) { throw "Director proposal was blocked; inspect director_report.json" }
    Write-Output "Director proposal ready for human review: $proposalDirectory"
}
finally {
    Pop-Location
    $env:PYTHONPATH = $previousPythonPath
}
