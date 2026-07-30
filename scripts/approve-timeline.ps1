param(
    [Parameter(Mandatory = $true)] [string]$ProjectPath,
    [Parameter(Mandatory = $true)] [int]$Version,
    [Parameter(Mandatory = $true)] [string]$Candidate,
    [Parameter(Mandatory = $true)] [string]$ApprovedBy
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$project = (Resolve-Path -LiteralPath $ProjectPath).Path
$candidatePath = (Resolve-Path -LiteralPath $Candidate).Path
$plan = Join-Path $project "work\plans\edit_plan.v$Version.json"
$receipt = Join-Path $project "work\plans\edit_plan.v$Version.approval.json"
$previousPythonPath = $env:PYTHONPATH

try {
    $env:PYTHONPATH = Join-Path $root 'src'
    Push-Location $root
    python -m vlog_director.cli approve-timeline `
        --candidate $candidatePath `
        --output $plan `
        --receipt $receipt `
        --approved-by $ApprovedBy
    if ($LASTEXITCODE -ne 0) { throw "Timeline approval failed with exit code $LASTEXITCODE" }
    Write-Output "Approved timeline: $plan"
}
finally {
    Pop-Location
    $env:PYTHONPATH = $previousPythonPath
}
