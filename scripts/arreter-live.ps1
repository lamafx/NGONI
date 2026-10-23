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

# Serveurs lances a la main (utils.txt) : reperes par leur ligne de commande,
# avec leurs processus enfants -- le rechargeur de `--reload` laisse sinon un
# processus qui garde le port 8000 ouvert.
$serveurs = @(Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -match 'uvicorn (app|wallet_stub|user_stub)\.main:app' -or
        ($_.Name -eq 'node.exe' -and $_.CommandLine -match 'vite')
    })
if ($serveurs) {
    $ids = $serveurs.ProcessId
    $enfants = @(Get-CimInstance Win32_Process | Where-Object { $ids -contains $_.ParentProcessId })
    foreach ($p in $serveurs + $enfants) {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Host "   arrete : $($p.Name) (pid $($p.ProcessId))"
    }
}

Push-Location $Racine
try { docker compose -f docker-compose.local.yml stop } finally { Pop-Location }
Write-Host "Pile NGONI arretee." -ForegroundColor Green
