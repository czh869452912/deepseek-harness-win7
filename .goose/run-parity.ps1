param(
    [string]$MigrationUnit,
    [switch]$Smoke,
    [string]$GooseExe = $env:GOOSE_EXE,
    [string]$PythonExe,
    [ValidateRange(0, 2147483647)][int]$MaxRounds = 0,
    [ValidateRange(0, 2147483647)][int]$MaxTurns = 0,
    [ValidateRange(0, 2147483647)][int]$PhaseTimeoutSeconds = 0,
    [switch]$NoCommit,
    [switch]$AdoptExisting
)
$ErrorActionPreference = 'Stop'
if (-not $Smoke -and [string]::IsNullOrWhiteSpace($MigrationUnit)) {
    throw 'Specify -MigrationUnit <unit> or -Smoke.'
}
if (-not $GooseExe) {
    $command = Get-Command goose.exe -ErrorAction SilentlyContinue
    if ($command) { $GooseExe = $command.Source }
}
if (-not $GooseExe) {
    $GooseExe = Join-Path $env:USERPROFILE 'Downloads\github.com\Goose-win32-x64\dist-windows\resources\bin\goose.exe'
}
if (-not (Test-Path -LiteralPath $GooseExe -PathType Leaf)) {
    throw 'Goose CLI not found. Supply -GooseExe or set GOOSE_EXE.'
}
foreach ($name in @('GOOSE_SUBAGENT_PROVIDER', 'GOOSE_SUBAGENT_MODEL')) {
    if ([Environment]::GetEnvironmentVariable($name)) {
        throw "$name overrides role routing. Clear it before running this workflow."
    }
}
$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not $PythonExe) { $PythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe' }
$recipe = '.goose/recipes/parity-unit.yaml'
if ($Smoke) { $recipe = '.goose/recipes/parity-smoke.yaml' }
Push-Location $repoRoot
$originalBaseUrl = $env:OPENAI_BASE_URL
try {
    # Existing terminals can retain a Markdown URL even after config.yaml is fixed.
    if ($env:OPENAI_BASE_URL -match '^\[([^\]]+)\]\((https://[^)]+)\)$') {
        $env:OPENAI_BASE_URL = $Matches[2]
    }
    & $GooseExe recipe validate $recipe
    if ($LASTEXITCODE -ne 0) { throw 'Recipe validation failed.' }
    $runArgs = @('run', '--recipe', $recipe)
    if (-not $Smoke) { $runArgs += @('--params', "migration_unit=$MigrationUnit") }
    if ($Smoke) {
        $smokeOutput = & $GooseExe @runArgs | Out-String
        $gooseExitCode = $LASTEXITCODE
        Write-Output $smokeOutput
        if ($gooseExitCode -ne 0) { throw "Goose failed with exit code $gooseExitCode." }
        if ($smokeOutput -notmatch '(?m)^\s*\*{0,2}SMOKE_PASS\*{0,2}\s*$') {
            throw 'Smoke check did not return SMOKE_PASS. Inspect the agent results above.'
        }
    } else {
        if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
            throw 'Repository Python not found. Supply -PythonExe (Python 3.8).'
        }
        $controllerArgs = @((Join-Path $PSScriptRoot 'parity_runner.py'),
            '--unit', $MigrationUnit, '--goose', $GooseExe,
            '--max-rounds', "$MaxRounds", '--max-turns', "$MaxTurns",
            '--phase-timeout', "$PhaseTimeoutSeconds")
        if ($NoCommit) { $controllerArgs += '--no-commit' }
        if ($AdoptExisting) { $controllerArgs += '--adopt-existing' }
        & $PythonExe @controllerArgs
        if ($LASTEXITCODE -ne 0) {
            throw 'Parity did not complete. See the final status and .goose/runs/ artifacts.'
        }
    }
} finally {
    $env:OPENAI_BASE_URL = $originalBaseUrl
    Pop-Location
}
