param(
    [string]$PythonExecutable = 'python',
    [string]$FFmpegExecutable
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Resolve-ApplicationPath {
    param([string]$Candidate, [string]$Label)

    $containsDirectory = [System.IO.Path]::IsPathRooted($Candidate) -or
        $Candidate.Contains([System.IO.Path]::DirectorySeparatorChar) -or
        $Candidate.Contains([System.IO.Path]::AltDirectorySeparatorChar)
    if ($containsDirectory) {
        $resolved = [System.IO.Path]::GetFullPath($Candidate)
        if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
            throw "$Label executable was not found: $resolved"
        }
        return $resolved
    }

    $command = Get-Command $Candidate -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $command) {
        throw "$Label executable was not found: $Candidate"
    }
    return $command.Source
}

function Write-Utf8Json {
    param([object]$Document, [string]$Path)

    $json = $Document | ConvertTo-Json -Depth 20
    $utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText(
        $Path,
        $json + [Environment]::NewLine,
        $utf8WithoutBom
    )
}

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$python = Resolve-ApplicationPath -Candidate $PythonExecutable -Label 'Python'
if ([string]::IsNullOrWhiteSpace($FFmpegExecutable)) {
    $bundledOutput = @(
        & $python -c 'from imageio_ffmpeg import get_ffmpeg_exe; print(get_ffmpeg_exe())'
    )
    if ($LASTEXITCODE -ne 0) {
        throw 'Unable to locate bundled FFmpeg. Install the test extra or pass -FFmpegExecutable.'
    }
    $bundledCandidates = @(
        $bundledOutput | Where-Object {
            -not [string]::IsNullOrWhiteSpace([string]$_)
        }
    )
    if ($bundledCandidates.Count -eq 0) {
        throw 'Bundled FFmpeg discovery returned no executable path.'
    }
    $FFmpegExecutable = [string]$bundledCandidates[-1]
}
$ffmpeg = Resolve-ApplicationPath -Candidate $FFmpegExecutable -Label 'FFmpeg'

$filterLines = @(& $ffmpeg -hide_banner -filters)
if ($LASTEXITCODE -ne 0) {
    throw "Unable to inspect FFmpeg filters: $LASTEXITCODE"
}
$filterInventory = $filterLines -join [Environment]::NewLine

function Test-FFmpegFilter {
    param([string]$Name)

    $escaped = [regex]::Escape($Name)
    return $filterInventory -match "(?m)^\s*[TSC\.]{2,3}\s+$escaped\s"
}

$requiredFilters = @(
    'testsrc2',
    'sine',
    'loudnorm',
    'sidechaincompress',
    'aresample',
    'asplit',
    'atrim',
    'asetpts',
    'volume',
    'afade',
    'adelay',
    'amix',
    'anull'
)
$missingFilters = @($requiredFilters | Where-Object {
    -not (Test-FFmpegFilter $_)
})
if ($missingFilters.Count -gt 0) {
    throw "FFmpeg is missing required smoke filters: $($missingFilters -join ', ')"
}

$supportsOverlay = (Test-FFmpegFilter 'overlay') -and
    (Test-FFmpegFilter 'scale') -and
    (Test-FFmpegFilter 'color')
$supportsSubtitles = Test-FFmpegFilter 'subtitles'
$supportsStabilization = (Test-FFmpegFilter 'vidstabdetect') -and
    (Test-FFmpegFilter 'vidstabtransform')

Write-Host "[ready] FFmpeg executable: $ffmpeg"
Write-Host (
    '[ready] Optional filters: overlay={0}; subtitles={1}; stabilization={2}' -f
        $supportsOverlay,
        $supportsSubtitles,
        $supportsStabilization
)

$temporaryRoot = [System.IO.Path]::GetFullPath(
    [System.IO.Path]::GetTempPath()
).TrimEnd(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
)
$smokeRoot = Join-Path $temporaryRoot (
    'firered-vlog-render-smoke-' + [guid]::NewGuid().ToString('N')
)
$projectId = 'synthetic-smoke'
$projectsRoot = Join-Path $smokeRoot 'projects'
$project = Join-Path $projectsRoot $projectId
$previousPythonPath = $env:PYTHONPATH
$locationPushed = $false
$smokeRootCreated = $false

function Invoke-DirectorCli {
    param([string]$Step, [string[]]$Arguments)

    $output = @(& $python -m vlog_director.cli @Arguments)
    $exitCode = $LASTEXITCODE
    $text = $output -join [Environment]::NewLine
    if ($exitCode -ne 0) {
        throw "$Step failed with exit code $exitCode. $text"
    }
    try {
        $result = $text | ConvertFrom-Json
    }
    catch {
        throw "$Step returned invalid JSON: $text"
    }
    Write-Host "[passed] $Step"
    return $result
}

try {
    New-Item -ItemType Directory -Path $smokeRoot -Force | Out-Null
    $smokeRootCreated = $true
    $env:PYTHONPATH = Join-Path $repositoryRoot 'src'
    Push-Location $repositoryRoot
    $locationPushed = $true

    $initialized = Invoke-DirectorCli -Step 'Project initialization' -Arguments @(
        'init-project',
        '--root', $projectsRoot,
        '--project-id', $projectId
    )
    if ($initialized.status -ne 'ready') {
        throw "Project initialization returned status: $($initialized.status)"
    }

    $editPlan = @{
        schema_version = '1.0'
        project_id = $projectId
        version = 1
        chapters = @(
            @{
                id = 'ch01'
                title = 'Synthetic smoke fixture'
                segments = @(
                    @{
                        source = 'raw/synthetic.mkv'
                        in_sec = 0.0
                        out_sec = 3.0
                        keep_original_audio = $true
                    }
                )
            }
        )
    }
    $moments = @{
        schema_version = '1.0'
        project_id = $projectId
        moments = @(
            @{
                id = 'moment_locked_synthetic'
                source = 'raw/synthetic.mkv'
                start_sec = 0.0
                end_sec = 3.0
                types = @('key_event')
                importance_score = 1.0
                fun_score = 0.0
                quality_score = 1.0
                confidence = 1.0
                keep_level = 'locked'
                reason = 'Synthetic locked interval for the smoke gate.'
                evidence = @(
                    @{ type = 'user'; value = 'synthetic smoke fixture' }
                )
            }
        )
        groups = @()
    }
    $editPlanPath = Join-Path $project 'work\plans\edit_plan.v1.json'
    $momentsPath = Join-Path $project 'work\analysis\moments.json'
    Write-Utf8Json -Document $editPlan -Path $editPlanPath
    Write-Utf8Json -Document $moments -Path $momentsPath

    $renderGuard = Invoke-DirectorCli -Step 'Render protection guard' -Arguments @(
        'guard-render',
        '--project', $project,
        '--version', '1'
    )
    if ($renderGuard.status -ne 'passed') {
        throw "Render protection guard returned status: $($renderGuard.status)"
    }

    $enhancementInit = Invoke-DirectorCli -Step 'Enhancement initialization' -Arguments @(
        'init-enhancement',
        '--project', $project,
        '--version', '1'
    )
    if ($enhancementInit.status -ne 'ready') {
        throw "Enhancement initialization returned status: $($enhancementInit.status)"
    }

    $planPath = Join-Path $project 'work\enhancement\enhancement_plan.v1.json'
    $enhancementPlan = Get-Content -LiteralPath $planPath -Raw -Encoding UTF8 |
        ConvertFrom-Json
    $subtitleDirectory = Join-Path $project 'work\subtitles'
    $subtitleSource = Join-Path $subtitleDirectory 'synthetic-reviewed.json'
    $musicDirectory = Join-Path $project 'assets\music'
    $illustrationDirectory = Join-Path $project 'assets\illustrations'
    $outputDirectory = Join-Path $project 'output'
    $stabilizedDirectory = Join-Path $project 'work\stabilized'
    New-Item -ItemType Directory -Path @(
        $subtitleDirectory,
        $musicDirectory,
        $illustrationDirectory,
        $outputDirectory,
        $stabilizedDirectory
    ) -Force | Out-Null
    $music = Join-Path $musicDirectory 'bed.wav'
    $illustration = Join-Path $illustrationDirectory 'card.png'
    New-Item -ItemType Directory -Path $subtitleDirectory -Force | Out-Null
    $enhancementPlan.music.status = 'ready'
    $enhancementPlan.music | Add-Member -NotePropertyName rights_manifest -NotePropertyValue 'assets/music/rights-manifest.json' -Force
    $enhancementPlan.music | Add-Member -NotePropertyName audition_report -NotePropertyValue 'assets/music/audition-report.json' -Force
    $enhancementPlan.music.tracks = @(
        [pscustomobject]@{
            id = 'music-1'
            source = 'assets/music/bed.wav'
            start_sec = 0.0
            end_sec = 3.0
            gain_db = -20.0
            fade_in_sec = 0.25
            fade_out_sec = 0.25
        }
    )
    $enhancementPlan.music.ducking = [pscustomobject]@{
        enabled = $true
        threshold = 0.125
        ratio = 8.0
        attack_ms = 20
        release_ms = 250
    }

    if ($supportsSubtitles) {
        $enhancementPlan.subtitles.status = 'review'
        $enhancementPlan.subtitles.source = 'work/subtitles/synthetic-reviewed.json'
        $enhancementPlan.subtitles.coverage = [pscustomobject]@{
            status = 'pending'
        }
        $enhancementPlan.subtitles.cues = @(
            [pscustomobject]@{
                cue_id = 'synthetic-subtitle-1'
                start_sec = 0.4
                end_sec = 1.5
                text = 'Synthetic subtitle smoke'
                review_status = 'review_required'
            }
        )
        Write-Utf8Json -Document @{
            status = 'review_required'
            coverage = @{ status = 'pending' }
            cues = $enhancementPlan.subtitles.cues
        } -Path $subtitleSource
        $enhancementPlan.subtitles | Add-Member -NotePropertyName source_sha256 -NotePropertyValue ((Get-FileHash -LiteralPath $subtitleSource -Algorithm SHA256).Hash.ToLowerInvariant()) -Force
    }
    else {
        $enhancementPlan.subtitles.status = 'disabled'
        $enhancementPlan.subtitles.cues = @()
    }

    if ($supportsOverlay) {
        $enhancementPlan.illustration_motion.status = 'ready'
        $enhancementPlan.illustration_motion.items = @(
            [pscustomobject]@{
                id = 'overlay-1'
                type = 'callout'
                source = 'assets/illustrations/card.png'
                start_sec = 0.8
                end_sec = 2.2
                anchor = 'top_right'
                animation = 'none'
                scale_percent = 30.0
            }
        )
    }
    else {
        $enhancementPlan.illustration_motion.status = 'disabled'
        $enhancementPlan.illustration_motion.items = @()
    }

    $musicArguments = @(
        '-y', '-hide_banner', '-loglevel', 'error',
        '-f', 'lavfi', '-i', 'sine=frequency=220:sample_rate=48000:duration=3',
        '-c:a', 'pcm_s16le', $music
    )
    & $ffmpeg @musicArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Synthetic music generation failed: $LASTEXITCODE"
    }
    $musicHash = (Get-FileHash -LiteralPath $music -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Utf8Json -Document @{
        assets = @(
            @{
                id = 'music-1'
                path = 'bed.wav'
                size_bytes = [int64](Get-Item -LiteralPath $music).Length
                sha256 = $musicHash
            }
        )
        rights_approval = @{
            status = 'approved'
            rights_holder = 'synthetic smoke fixture'
            approved_by = 'smoke gate'
            approved_at = '2026-01-01T00:00:00Z'
            scopes = @('synchronize', 'modify', 'render', 'distribute_with_project')
        }
    } -Path (Join-Path $musicDirectory 'rights-manifest.json')
    Write-Utf8Json -Document @{
        status = 'passed'
        blocking_items = @()
        assets = @(
            @{ id = 'music-1'; audition_status = 'passed' }
        )
    } -Path (Join-Path $musicDirectory 'audition-report.json')

    if ($supportsOverlay) {
        $illustrationArguments = @(
            '-y', '-hide_banner', '-loglevel', 'error',
            '-f', 'lavfi', '-i', 'color=c=yellow@0.85:s=180x100:d=1',
            '-frames:v', '1', $illustration
        )
        & $ffmpeg @illustrationArguments
        if ($LASTEXITCODE -ne 0) {
            throw "Synthetic illustration generation failed: $LASTEXITCODE"
        }
    }
    Write-Utf8Json -Document $enhancementPlan -Path $planPath

    $formalSchema = Join-Path $repositoryRoot 'schemas\enhancement-plan.schema.json'
    $schemaCheckPath = Join-Path $smokeRoot 'validate-formal-schema.py'
    $schemaCheck = @'
import json
import sys
from jsonschema import Draft202012Validator

schema_path, plan_path = sys.argv[1:]
schema = json.loads(open(schema_path, encoding="utf-8").read())
plan = json.loads(open(plan_path, encoding="utf-8").read())
Draft202012Validator.check_schema(schema)
errors = sorted(
    Draft202012Validator(schema).iter_errors(plan),
    key=lambda error: tuple(str(value) for value in error.absolute_path),
)
if errors:
    raise SystemExit(
        "; ".join(f"{error.json_path}: {error.message}" for error in errors)
    )
'@
    $utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText(
        $schemaCheckPath,
        $schemaCheck + [Environment]::NewLine,
        $utf8WithoutBom
    )
    & $python $schemaCheckPath $formalSchema $planPath
    if ($LASTEXITCODE -ne 0) {
        throw 'Formal enhancement schema validation failed.'
    }
    Write-Host '[passed] Formal enhancement schema'

    $enhancementGuard = Invoke-DirectorCli -Step 'Runtime enhancement guard' -Arguments @(
        'guard-enhancement',
        '--project', $project,
        '--version', '1'
    )
    if ($enhancementGuard.status -ne 'preview_ready') {
        throw "Runtime enhancement guard returned status: $($enhancementGuard.status)"
    }

    $preview = Join-Path $outputDirectory 'preview.mkv'
    $stabilized = Join-Path $stabilizedDirectory 'preview.mp4'
    $final = Join-Path $outputDirectory 'final.mp4'
    $qaOutput = Join-Path $project 'work\qa\music-mix.json'

    $previewArguments = @(
        '-y', '-hide_banner', '-loglevel', 'error',
        '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=30:duration=3',
        '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=3',
        '-c:v', 'ffv1', '-c:a', 'pcm_s16le', '-shortest', $preview
    )
    & $ffmpeg @previewArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Synthetic preview generation failed: $LASTEXITCODE"
    }
    Write-Host '[passed] Synthetic preview generation'

    $baseVideo = $preview
    if ($supportsStabilization) {
        $stabilizeResult = Invoke-DirectorCli -Step 'Optional stabilization' -Arguments @(
            'stabilize',
            '--input', $preview,
            '--output', $stabilized,
            '--work-directory', $stabilizedDirectory,
            '--strength', '0.2',
            '--max-crop-percent', '3.0',
            '--ffmpeg-executable', $ffmpeg
        )
        if ($stabilizeResult.status -ne 'ready') {
            throw "Stabilization returned status: $($stabilizeResult.status)"
        }
        $baseVideo = $stabilized
    }
    else {
        Write-Host '[skipped] Optional stabilization filters are unavailable'
    }

    $renderResult = Invoke-DirectorCli -Step 'Enhancement render and audio QA' -Arguments @(
        'render-enhancement',
        '--project', $project,
        '--base-video', $baseVideo,
        '--plan', $planPath,
        '--output', $final,
        '--qa-output', $qaOutput,
        '--ffmpeg-executable', $ffmpeg
    )
    if ($renderResult.status -ne 'preview_ready' -or $renderResult.qa_status -ne 'passed') {
        throw "Enhancement render QA returned status: $($renderResult.qa_status)"
    }
    if ($renderResult.PSObject.Properties.Name -contains 'migrations') {
        throw 'Smoke plan unexpectedly required legacy migration.'
    }

    $qaReport = Get-Content -LiteralPath $qaOutput -Raw -Encoding UTF8 |
        ConvertFrom-Json
    if ($qaReport.status -ne 'passed') {
        throw "Audio QA report returned status: $($qaReport.status)"
    }
    Write-Host '[passed] Audio QA report'

    $decodeArguments = @(
        '-hide_banner', '-loglevel', 'error',
        '-i', $final,
        '-map', '0:v:0',
        '-map', '0:a:0',
        '-progress', 'pipe:1',
        '-nostats',
        '-f', 'null', 'NUL'
    )
    $decodeOutput = @(& $ffmpeg @decodeArguments)
    if ($LASTEXITCODE -ne 0) {
        throw "Full video/audio decode failed: $LASTEXITCODE"
    }

    [long]$decodedMicroseconds = 0
    foreach ($line in $decodeOutput) {
        if ([string]$line -match '^out_time_us=([0-9]+)$') {
            $decodedMicroseconds = [math]::Max(
                $decodedMicroseconds,
                [long]$matches[1]
            )
        }
    }
    $decodedDurationSec = $decodedMicroseconds / 1000000.0
    if ($decodedDurationSec -lt 2.8) {
        throw "Decoded smoke output is too short: $decodedDurationSec seconds"
    }
    Write-Host (
        '[passed] Full mapped video/audio decode ({0:N3} seconds)' -f
            $decodedDurationSec
    )
    Write-Host '[passed] Portable enhancement render smoke gate'
}
finally {
    if ($locationPushed) {
        Pop-Location
    }
    $env:PYTHONPATH = $previousPythonPath

    if ($smokeRootCreated -and (Test-Path -LiteralPath $smokeRoot)) {
        $resolvedSmokeRoot = [System.IO.Path]::GetFullPath($smokeRoot)
        $expectedPrefix = $temporaryRoot + [System.IO.Path]::DirectorySeparatorChar
        $leaf = Split-Path -Leaf $resolvedSmokeRoot
        $insideTemporaryRoot = $resolvedSmokeRoot.StartsWith(
            $expectedPrefix,
            [System.StringComparison]::OrdinalIgnoreCase
        )
        $expectedLeaf = $leaf.StartsWith(
            'firered-vlog-render-smoke-',
            [System.StringComparison]::Ordinal
        )
        if (-not $insideTemporaryRoot -or -not $expectedLeaf) {
            throw "Refusing to remove unexpected smoke path: $resolvedSmokeRoot"
        }
        Remove-Item -LiteralPath $resolvedSmokeRoot -Recurse -Force
    }
}
