$ErrorActionPreference = 'Stop'

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$smokeRoot = Join-Path $env:TEMP 'firered-vlog-render-smoke'
$previousPythonPath = $env:PYTHONPATH

if (Test-Path -LiteralPath $smokeRoot) {
    Remove-Item -LiteralPath $smokeRoot -Recurse -Force
}

$project = Join-Path $smokeRoot 'project'
$directories = @(
    (Join-Path $project 'assets\music'),
    (Join-Path $project 'assets\illustrations'),
    (Join-Path $project 'output'),
    (Join-Path $project 'work\stabilized')
)
New-Item -ItemType Directory -Path $directories -Force | Out-Null

$preview = Join-Path $project 'output\preview.mp4'
$music = Join-Path $project 'assets\music\bed.wav'
$illustration = Join-Path $project 'assets\illustrations\card.png'
$stabilized = Join-Path $project 'work\stabilized\preview.mp4'
$final = Join-Path $project 'output\final.mp4'
$plan = Join-Path $project 'enhancement-plan.json'

ffmpeg -y -hide_banner -loglevel error `
    -f lavfi -i 'testsrc2=size=640x360:rate=30:duration=3' `
    -f lavfi -i 'sine=frequency=440:sample_rate=48000:duration=3' `
    -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest $preview
if ($LASTEXITCODE -ne 0) { throw "Synthetic preview generation failed: $LASTEXITCODE" }

ffmpeg -y -hide_banner -loglevel error `
    -f lavfi -i 'sine=frequency=220:sample_rate=48000:duration=3' `
    -c:a pcm_s16le $music
if ($LASTEXITCODE -ne 0) { throw "Synthetic music generation failed: $LASTEXITCODE" }

ffmpeg -y -hide_banner -loglevel error `
    -f lavfi -i 'color=c=yellow@0.85:s=180x100:d=1' `
    -frames:v 1 $illustration
if ($LASTEXITCODE -ne 0) { throw "Synthetic illustration generation failed: $LASTEXITCODE" }

$enhancementPlan = @{
    schema_version = '1.0'
    project_id = 'smoke-vlog'
    version = 1
    edit_plan_version = 1
    timeline_duration_sec = 3.0
    render_stages = @(
        'stabilize_and_reframe'
        'assemble_continuity'
        'normalize_dialogue'
        'mix_music_with_ducking'
        'compose_illustration_motion'
        'burn_subtitles'
        'final_encode'
    )
    video_treatments = @()
    music = @{
        status = 'ready'
        tracks = @(
            @{
                id = 'music-1'
                source = 'assets/music/bed.wav'
                start_sec = 0.0
                end_sec = 3.0
                gain_db = -20.0
            }
        )
        ducking = @{
            enabled = $true
            dialogue_gain_db = -22.0
            attack_ms = 120
            release_ms = 450
        }
    }
    subtitles = @{
        status = 'ready'
        language = 'zh-CN'
        source = 'synthetic'
        cues = @(
            @{ start_sec = 0.4; end_sec = 1.5; text = '合成字幕测试' }
        )
        style = @{
            max_lines = 2
            safe_margin_percent = 8.0
            position = 'bottom_center'
        }
    }
    illustration_motion = @{
        status = 'ready'
        subtitle_safe_zone = $true
        items = @(
            @{
                id = 'overlay-1'
                type = 'callout'
                source = 'assets/illustrations/card.png'
                start_sec = 0.8
                end_sec = 2.2
                anchor = 'top_right'
                animation = 'none'
                scale_percent = 50.0
            }
        )
    }
}
$enhancementPlan | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $plan -Encoding utf8

try {
    $env:PYTHONPATH = Join-Path $repositoryRoot 'src'
    Push-Location $repositoryRoot
    python -m vlog_director.cli stabilize `
        --input $preview `
        --output $stabilized `
        --work-directory (Join-Path $project 'work\stabilized') `
        --strength 0.2 `
        --max-crop-percent 3.0
    if ($LASTEXITCODE -ne 0) { throw "Stabilization smoke step failed: $LASTEXITCODE" }
    python -m vlog_director.cli render-enhancement `
        --project $project `
        --base-video $stabilized `
        --plan $plan `
        --output $final
    if ($LASTEXITCODE -ne 0) { throw "Enhancement smoke step failed: $LASTEXITCODE" }
}
finally {
    Pop-Location
    $env:PYTHONPATH = $previousPythonPath
}

$probe = ffprobe -v error -show_entries stream=codec_type -show_entries format=duration -of json $final | ConvertFrom-Json
$streamTypes = @($probe.streams | ForEach-Object { $_.codec_type })
if ('video' -notin $streamTypes -or 'audio' -notin $streamTypes) {
    throw 'Smoke output must contain both video and audio streams.'
}
if ([double]$probe.format.duration -lt 2.8) {
    throw "Smoke output is too short: $($probe.format.duration) seconds"
}

Write-Host "[passed] Render smoke test: $final"
