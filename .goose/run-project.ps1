param(
    [ValidateSet('init','status','plan','apply','run','recover','pause','prepare-main','publish-main','console','follow','overview')][string]$Action = 'status',
    [string]$GooseExe = $env:GOOSE_EXE,
    [ValidateRange(1, 2147483647)][int]$Jobs = 2,
    [string]$PlanFile,
    [string]$Task,
    [string]$Target = 'master',
    [int]$Port = 8766,
    [ValidateSet('summary','plain','quiet')][string]$OutputMode = 'summary'
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Repository Python 3.8 is required.' }
if (-not $GooseExe) {
    $command = Get-Command goose.exe -ErrorAction SilentlyContinue
    if ($command) { $GooseExe = $command.Source }
    else { $GooseExe = Join-Path $env:USERPROFILE 'Downloads\github.com\Goose-win32-x64\dist-windows\resources\bin\goose.exe' }
}
$originalUrl = $env:OPENAI_BASE_URL
$originalShell = $env:GOOSE_SHELL
$originalOutput = $env:GOOSE_PROJECT_OUTPUT
Push-Location $root
try {
    if ($env:OPENAI_BASE_URL -match '^\[([^\]]+)\]\((https://[^)]+)\)$') { $env:OPENAI_BASE_URL = $Matches[2] }
    # Keep model-authored redirects like "> $null" from becoming literal files (cmd default).
    $env:GOOSE_SHELL = 'powershell.exe'
    $env:GOOSE_PROJECT_OUTPUT = $OutputMode
    if (@('console', 'follow', 'overview') -contains $Action) {
        $consoleArgs = @((Join-Path $PSScriptRoot 'project_console.py'))
        if ($Action -eq 'follow') {
            if (-not $Task) { throw 'follow requires -Task' }
            $consoleArgs += @('--follow', $Task)
        } elseif ($Action -eq 'overview') { $consoleArgs += '--overview' }
        else { $consoleArgs += @('--port', "$Port") }
        & $python @consoleArgs
        exit $LASTEXITCODE
    }
    if ($Action -eq 'pause') {
        New-Item -ItemType File -Path (Join-Path $root '.goose\runs\project\pause.flag') -Force | Out-Null
        Write-Output 'Pause requested; the scheduler will park running groups and exit cleanly.'
        exit 0
    }
    $arguments = @((Join-Path $PSScriptRoot 'project_runner.py'), $Action, '--goose', $GooseExe, '--jobs', "$Jobs")
    if ($PlanFile) { $arguments += @('--file', $PlanFile) }
    if ($Task) { $arguments += @('--task', $Task) }
    if ($Action -eq 'prepare-main') { $arguments += @('--target', $Target) }
    & $python @arguments
    if ($LASTEXITCODE -ne 0) { throw 'Project needs attention; inspect .goose/runs/project/index.html and task errors.' }
} finally {
    $env:OPENAI_BASE_URL = $originalUrl
    $env:GOOSE_SHELL = $originalShell
    $env:GOOSE_PROJECT_OUTPUT = $originalOutput
    Pop-Location
}
