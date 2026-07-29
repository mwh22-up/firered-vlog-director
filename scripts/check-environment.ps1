$ErrorActionPreference = 'Stop'

$requiredCommands = @('git', 'python', 'ffmpeg', 'ffprobe')
$missingCommands = @()

foreach ($commandName in $requiredCommands) {
    $command = Get-Command $commandName -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        $missingCommands += $commandName
        Write-Host "[missing] $commandName"
    }
    else {
        Write-Host "[ok] $commandName -> $($command.Source)"
    }
}

$pythonVersionOutput = python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
$pythonVersion = [version]$pythonVersionOutput
if ($pythonVersion -lt [version]'3.11' -or $pythonVersion -ge [version]'3.13') {
    Write-Host "[invalid] Python $pythonVersionOutput; expected >=3.11,<3.13"
    $missingCommands += 'python-version'
}
else {
    Write-Host "[ok] Python $pythonVersionOutput"
}

if ($missingCommands.Count -gt 0) {
    Write-Error "Environment check failed: $($missingCommands -join ', ')"
}

Write-Host '[passed] Local director-core prerequisites are available.'
