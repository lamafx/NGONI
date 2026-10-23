# Arrete toute la pile NGONI (les donnees sont conservees).
#   double-clic sur scripts\arreter-live.cmd

Set-Location (Split-Path -Parent $PSScriptRoot)
docker compose stop
Write-Host "Pile NGONI arretee." -ForegroundColor Green
