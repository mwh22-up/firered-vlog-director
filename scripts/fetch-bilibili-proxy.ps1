[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^BV[A-Za-z0-9]+$')]
    [string]$Bvid,

    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,

    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$outputPath = [System.IO.Path]::GetFullPath($OutputDirectory)
$proxyPath = Join-Path $outputPath 'proxy.mp4'
$videoPath = Join-Path $outputPath 'video.m4s'
$audioPath = Join-Path $outputPath 'audio.m4s'
$metadataPath = Join-Path $outputPath 'metadata.json'
$sourceUrl = "https://www.bilibili.com/video/$Bvid/"

foreach ($commandName in @('curl.exe', 'ffmpeg', 'ffprobe')) {
    if (-not (Get-Command $commandName -ErrorAction SilentlyContinue)) {
        throw "Required command was not found: $commandName"
    }
}

New-Item -ItemType Directory -Force -Path $outputPath | Out-Null
if ((Test-Path -LiteralPath $proxyPath) -and -not $Force) {
    Write-Host "[ready] Existing proxy: $proxyPath"
    exit 0
}

$headers = @{
    'User-Agent' = 'Mozilla/5.0'
    'Referer' = $sourceUrl
}
$view = Invoke-RestMethod `
    -Headers $headers `
    -Uri "https://api.bilibili.com/x/web-interface/view?bvid=$Bvid"
if ($view.code -ne 0) {
    throw "Unable to read video metadata: code=$($view.code)"
}

$cid = [string]$view.data.cid
$play = Invoke-RestMethod `
    -Headers $headers `
    -Uri "https://api.bilibili.com/x/player/playurl?bvid=$Bvid&cid=$cid&qn=32&fnval=16"
if ($play.code -ne 0 -or -not $play.data.dash) {
    throw "Unable to read anonymous DASH streams."
}

$video = $play.data.dash.video |
    Sort-Object height, bandwidth |
    Select-Object -First 1
$audio = $play.data.dash.audio |
    Sort-Object bandwidth |
    Select-Object -First 1

curl.exe -L --fail --retry 2 --silent --show-error `
    -A 'Mozilla/5.0' `
    -e $sourceUrl `
    -o $videoPath `
    $video.baseUrl
if ($LASTEXITCODE -ne 0) {
    throw 'Video stream download failed.'
}

curl.exe -L --fail --retry 2 --silent --show-error `
    -A 'Mozilla/5.0' `
    -e $sourceUrl `
    -o $audioPath `
    $audio.baseUrl
if ($LASTEXITCODE -ne 0) {
    throw 'Audio stream download failed.'
}

ffmpeg -hide_banner -loglevel error -y `
    -i $videoPath `
    -i $audioPath `
    -map 0:v:0 `
    -map 1:a:0 `
    -c copy `
    $proxyPath
if ($LASTEXITCODE -ne 0) {
    throw 'Proxy mux failed.'
}

$metadata = [ordered]@{
    schema_version = '1.0'
    bvid = $Bvid
    title = $view.data.title
    owner = $view.data.owner.name
    duration_sec = $view.data.duration
    cid = $cid
    source_url = $sourceUrl
    proxy_path = $proxyPath
    created_at = [DateTimeOffset]::UtcNow.ToString('o')
}
$metadata |
    ConvertTo-Json -Depth 4 |
    Set-Content -Encoding UTF8 -LiteralPath $metadataPath

$probe = ffprobe -v error -show_entries format=duration,size -of json $proxyPath
Write-Host "[ready] Proxy: $proxyPath"
Write-Host $probe
