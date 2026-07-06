# Local pilot launcher: Postgres + Redis (Docker), the FastAPI service and the
# Discord bot - everything the hosted stack will run, on this machine.
# Usage:  powershell -ExecutionPolicy Bypass -File run_stack.ps1 [-Stop]
param([switch]$Stop)

$svc = $PSScriptRoot

if ($Stop) {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -match 'app\.bot|app\.main:app' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    docker compose -f "$svc\docker-compose.yml" stop
    Write-Host "stack stopped"
    exit 0
}

docker compose -f "$svc\docker-compose.yml" up -d --wait

# API (port 8090) and bot, minimized, logging next to this script
Start-Process python -WorkingDirectory $svc -WindowStyle Minimized `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--port", "8090" `
    -RedirectStandardOutput "$svc\api.log" -RedirectStandardError "$svc\api.err.log"
Start-Process python -WorkingDirectory $svc -WindowStyle Minimized `
    -ArgumentList "-m", "app.bot" `
    -RedirectStandardOutput "$svc\bot.log" -RedirectStandardError "$svc\bot.err.log"

Start-Sleep -Seconds 6
try {
    $h = Invoke-RestMethod "http://localhost:8090/healthz" -TimeoutSec 10
    Write-Host "API: OK ($($h.status)) - http://localhost:8090"
} catch { Write-Host "API: not responding yet - check api.err.log" }
Write-Host "Bot: log at bot.log / bot.err.log"
Write-Host "Desktop app uses this stack when SYLQON_META_URL=http://localhost:8090 is set."
