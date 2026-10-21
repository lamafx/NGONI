# Arrete ce que scripts\demarrer-live.ps1 a lance : FastAPI, stubs, Vite et
# les conteneurs rasa/actions. PostgreSQL, Ollama et Docker Desktop restent
# en marche (ils servent aussi en dehors de la demonstration).

$Racine = Split-Path -Parent $PSScriptRoot
$FichierPids = Join-Path $env:TEMP "ngoni-live\pids.txt"

if (Test-Path $FichierPids) {
    foreach ($ligne in Get-Content $FichierPids | Where-Object { $_ -match "=" }) {
        $nom, $id = $ligne -split "=", 2
        # /T : Vite tourne sous cmd.exe -> npx -> node, il faut tout l'arbre.
        taskkill /PID $id /T /F 2>$null | Out-Null
        Write-Host "   arrete : $nom (pid $id)"
    }
    Remove-Item $FichierPids
} else {
    Write-Host "   aucun processus enregistre par demarrer-live.ps1"
}

Push-Location $Racine
try { docker compose stop rasa actions } finally { Pop-Location }
Write-Host "Pile NGONI arretee." -ForegroundColor Green
