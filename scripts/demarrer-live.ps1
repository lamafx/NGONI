# Demarre toute la pile NGONI sous Docker et attend qu'elle soit prete.
#   double-clic sur scripts\demarrer-live.cmd

$Racine = Split-Path -Parent $PSScriptRoot
Set-Location $Racine

function Docker-Pret { docker info --format "{{.ServerVersion}}" *> $null; return $LASTEXITCODE -eq 0 }

if (-not (Docker-Pret)) {
    Write-Host "Demarrage de Docker Desktop (1 a 3 min)..."
    docker desktop start *> $null
    $fin = (Get-Date).AddMinutes(4)
    while (-not (Docker-Pret) -and (Get-Date) -lt $fin) { Start-Sleep -Seconds 5 }
    if (-not (Docker-Pret)) { Write-Host "Docker Desktop ne repond pas." -ForegroundColor Red; exit 1 }
}

docker compose up -d
Write-Host "Prechauffage des modeles (3 a 6 min)..."
while ((docker inspect pfe-prechauffage-1 --format "{{.State.Status}}" 2>$null) -ne "exited") { Start-Sleep -Seconds 10 }
docker logs pfe-prechauffage-1 2>&1 | Select-Object -Last 6
docker compose ps --format "table {{.Service}}\t{{.Status}}"

Write-Host ""
Write-Host "Pret." -ForegroundColor Green
Write-Host "  Connexion      http://localhost:5173  (adou / awa.kone / fatou.diarra, mot de passe ngoni2026)"
Write-Host "  Conseiller     http://localhost:5173/#/agent/live"
Write-Host "  Administration http://localhost:5173/#/admin"
