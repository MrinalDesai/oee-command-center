# run.ps1 — ForgePulse local stack orchestrator.
#
# One command starts everything; Ctrl+C tears it all down.
#
# Usage (from repo root, venv NOT required to be active — script handles it):
#   .\scripts\run.ps1                  # feed + worker (the usual)
#   .\scripts\run.ps1 -Feed            # kafka + producer + consumer only
#   .\scripts\run.ps1 -Worker          # llm narrative worker only
#   .\scripts\run.ps1 -Ui              # console backend only (localhost:8000)
#   .\scripts\run.ps1 -All             # feed + worker + ui   (DEMO MODE)
#
# First-time setup: copy scripts\env.example.ps1 -> scripts\env.ps1 and fill
# in credentials. env.ps1 is git-ignored; never commit it.

param(
  [switch]$Feed,
  [switch]$Worker,
  [switch]$Ui,
  [switch]$All
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# default: feed + worker
if (-not ($Feed -or $Worker -or $Ui -or $All)) { $Feed = $true; $Worker = $true }
if ($All) { $Feed = $true; $Worker = $true; $Ui = $true }

# ── env ─────────────────────────────────────────────────────────────────────
$envFile = Join-Path $PSScriptRoot "env.ps1"
if (Test-Path $envFile) { . $envFile }
foreach ($k in "SNOWFLAKE_ACCOUNT","SNOWFLAKE_USER","SNOWFLAKE_PASSWORD") {
  if (-not (Get-Item "env:$k" -ErrorAction SilentlyContinue)) {
    Write-Host "Missing $k - create scripts\env.ps1 (see env.example.ps1)" -ForegroundColor Red
    exit 1
  }
}
if (-not $env:OLLAMA_MODEL) { $env:OLLAMA_MODEL = "mistral:7b-instruct-q8_0" }

$py = Join-Path $root ".venv\Scripts\python.exe"
$procs = @()

function Start-Bg($name, $args_) {
  $p = Start-Process -FilePath $py -ArgumentList $args_ -PassThru -NoNewWindow
  Write-Host "  started $name (pid $($p.Id))" -ForegroundColor Green
  return $p
}

Write-Host "ForgePulse stack starting..." -ForegroundColor Cyan

try {
  if ($Feed) {
    Write-Host "[feed] kafka container..." -ForegroundColor Cyan
    docker start kafka | Out-Null
    Start-Sleep -Seconds 12   # broker warm-up
    $procs += Start-Bg "producer" "src\kafka_producer.py"
    Start-Sleep -Seconds 2
    $procs += Start-Bg "consumer" "src\kafka_to_snowflake.py"
  }
  if ($Worker) {
    $procs += Start-Bg "llm_worker" "src\llm_worker.py"
    $procs += Start-Bg "enrich_worker" "src\enrich_worker.py --loop"
  }
  if ($Ui) {
    $uvicorn = Join-Path $root ".venv\Scripts\uvicorn.exe"
    $p = Start-Process -FilePath $uvicorn -ArgumentList "main:app","--port","8000" `
         -WorkingDirectory (Join-Path $root "forgepulse-ui\backend") -PassThru -NoNewWindow
    Write-Host "  started ui backend (pid $($p.Id)) -> http://localhost:8000" -ForegroundColor Green
    $procs += $p
  }

  Write-Host "`nRunning. Ctrl+C stops everything." -ForegroundColor Cyan
  while ($true) { Start-Sleep -Seconds 3600 }
}
finally {
  Write-Host "`nStopping..." -ForegroundColor Yellow
  foreach ($p in $procs) {
    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
  }
  if ($Feed) { docker stop kafka | Out-Null }
  Write-Host "All stopped. (Remember: suspend the task DAG if done for the day.)" -ForegroundColor Yellow
}
