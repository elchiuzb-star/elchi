<#
.SYNOPSIS
  Run the PostgreSQL 16 + PostGIS test suite (tests/pg) against docker-compose.test.yml.

.EXAMPLE
  .\scripts\test-pg.ps1                 # up (if needed), wait healthy, pytest -m pg, leave stack running
  .\scripts\test-pg.ps1 -Down           # ... and tear the stack down afterwards
  .\scripts\test-pg.ps1 -- -k harness   # extra pytest arguments after --
  $env:PYTHON = "C:\path\to\venv\Scripts\python.exe"; .\scripts\test-pg.ps1

  Works on Windows PowerShell 5.1 and PowerShell 7.
#>
[CmdletBinding()]
param(
    [switch]$Down,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PytestArgs
)

# 'Continue', not 'Stop': docker compose writes progress to stderr, which
# Windows PowerShell 5.1 would otherwise turn into a terminating
# NativeCommandError. Failures are detected via $LASTEXITCODE instead.
$ErrorActionPreference = 'Continue'
$repoRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $repoRoot 'docker-compose.test.yml'
$project = 'elchi-test'

if (-not $env:ELCHI_TEST_PG_URL) {
    # Port 45432 (Q76): 55432 sat inside a Windows excluded TCP range (`netsh
    # interface ipv4 show excludedportrange protocol=tcp`), which made the
    # postgis container fail with "access permissions".
    $env:ELCHI_TEST_PG_URL = 'postgresql+psycopg://elchi_test:elchi_test@127.0.0.1:45432/elchi_test'
}
# The stack was just started: an unreachable server must fail loudly, never skip.
$env:ELCHI_TEST_PG_REQUIRED = '1'

if ($env:PYTHON) { $python = @($env:PYTHON) }
elseif (Get-Command py -ErrorAction SilentlyContinue) { $python = @('py') }
else { $python = @('python') }

$null = docker info --format '{{.ServerVersion}}'
if ($LASTEXITCODE -ne 0) { throw 'Docker daemon is not reachable. Start Docker Desktop first.' }

Write-Host "==> docker compose up ($project)"
docker compose -p $project -f $composeFile up -d --wait
if ($LASTEXITCODE -ne 0) { throw 'docker compose up --wait failed' }

$extra = @($PytestArgs | Where-Object { $_ -ne '--' })
$exitCode = 1
Push-Location $repoRoot
try {
    Write-Host "==> ELCHI_TEST_PG_REQUIRED=1 $($python -join ' ') -m pytest -m pg tests/pg $($extra -join ' ')"
    & $python[0] @($python | Select-Object -Skip 1) -m pytest -m pg tests/pg @extra
    $exitCode = $LASTEXITCODE
}
finally {
    Pop-Location
    if ($Down) {
        Write-Host "==> docker compose down ($project)"
        docker compose -p $project -f $composeFile down -v --remove-orphans
    }
}
exit $exitCode
