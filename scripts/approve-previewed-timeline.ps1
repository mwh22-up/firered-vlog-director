param(
    [Parameter(Mandatory = $true)] [string]$ProjectPath,
    [Parameter(Mandatory = $true)] [int]$Version,
    [Parameter(Mandatory = $true)] [string]$Candidate,
    [Parameter(Mandatory = $true)] [string]$ReviewPack,
    [Parameter(Mandatory = $true)] [string]$Selection,
    [Parameter(Mandatory = $true)] [string]$ApprovedBy
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$project = (Resolve-Path -LiteralPath $ProjectPath).Path
$candidatePath = (Resolve-Path -LiteralPath $Candidate).Path
$reviewPackPath = (Resolve-Path -LiteralPath $ReviewPack).Path
$selectionPath = (Resolve-Path -LiteralPath $Selection).Path
$plan = Join-Path $project "work\plans\edit_plan.v$Version.json"
$receipt = Join-Path $project "work\qa\edit_plan.v$Version.approval.json"
$previousPythonPath = $env:PYTHONPATH

try {
    $env:PYTHONPATH = Join-Path $root 'src'
    Push-Location $root
    python -m vlog_director.cli approve-previewed-timeline `
        --project $project `
        --candidate $candidatePath `
        --review-pack $reviewPackPath `
        --selection $selectionPath `
        --output $plan `
        --receipt $receipt `
        --approved-by $ApprovedBy
    if ($LASTEXITCODE -ne 0) {
        throw "Previewed timeline approval failed with exit code $LASTEXITCODE"
    }
    Write-Output "Approved timeline: $plan"
    Write-Output "Approval receipt: $receipt"
}
finally {
    Pop-Location
    $env:PYTHONPATH = $previousPythonPath
}
