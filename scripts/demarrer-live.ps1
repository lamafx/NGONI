# Lance toute la pile NGONI pour une demonstration EN DIRECT (pas le mode
# ?demo=1 rejoue), verifie chaque service et prechauffe les modeles.
#
#   powershell -ExecutionPolicy Bypass -File scripts\demarrer-live.ps1
#   (ou double-clic sur scripts\demarrer-live.cmd)
#
# A lancer ~10 minutes avant le passage : le premier appel au LLM sans GPU
# coute a lui seul ~1 a 2 minutes (chargement du modele), c'est ce que le
# prechauffage absorbe a la place du jury.
#
# Ce que le script NE fait PAS : demarrer PostgreSQL (service Windows natif,
# il doit deja tourner) ni entrainer le modele Rasa (voir -Entrainer).

param(
    # Reentraine le modele Rasa avant de demarrer (a faire apres toute
    # modification de rasa/data, domain.yml ou config.yml).
    [switch]$Entrainer
)

$ErrorActionPreference = "Stop"
$Racine = Split-Path -Parent $PSScriptRoot
$Etat = Join-Path $env:TEMP "ngoni-live"
New-Item -ItemType Directory -Force $Etat | Out-Null
$FichierPids = Join-Path $Etat "pids.txt"
Set-Content -Path $FichierPids -Value $null
$Bilan = [System.Collections.Generic.List[object]]::new()

function Ecrire($texte, $couleur = "Gray") { Write-Host $texte -ForegroundColor $couleur }
function Etape($texte) { Write-Host ""; Write-Host "== $texte" -ForegroundColor Cyan }
function Noter($service, $ok, $detail) {
    $Bilan.Add([pscustomobject]@{ Service = $service; Etat = $(if ($ok) { "OK" } else { "ECHEC" }); Detail = $detail })
    if ($ok) { Ecrire "   OK  $service  $detail" Green } else { Ecrire "   ECHEC  $service  $detail" Red }
}

function Port-Ouvert([int]$port) {
    $c = New-Object System.Net.Sockets.TcpClient
    try { $c.Connect("127.0.0.1", $port); return $true } catch { return $false } finally { $c.Close() }
}

function Attendre-Http($url, [int]$secondes, $entetes = @{}) {
    $fin = (Get-Date).AddSeconds($secondes)
    while ((Get-Date) -lt $fin) {
        try {
            $r = Invoke-WebRequest -Uri $url -Headers $entetes -UseBasicParsing -TimeoutSec 5
            if ($r.StatusCode -lt 500) { return $true }
        } catch { }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Poster($url, $corps, [int]$timeout) {
    $json = [System.Text.Encoding]::UTF8.GetBytes(($corps | ConvertTo-Json -Compress))
    $debut = Get-Date
    $r = Invoke-RestMethod -Uri $url -Method Post -Body $json -ContentType "application/json; charset=utf-8" -TimeoutSec $timeout
    return @{ Reponse = $r; Secondes = [math]::Round(((Get-Date) - $debut).TotalSeconds, 1) }
}

# Lance un processus en fenetre reduite, journal dans %TEMP%\ngoni-live.
function Lancer($nom, $exe, $arguments, $dossier) {
    $journal = Join-Path $Etat "$nom.log"
    $p = Start-Process -FilePath $exe -ArgumentList $arguments -WorkingDirectory $dossier `
        -RedirectStandardOutput $journal -RedirectStandardError "$journal.err" -WindowStyle Hidden -PassThru
    Add-Content -Path $FichierPids -Value "$nom=$($p.Id)"
    return $p
}

# ---------------------------------------------------------------------------
Etape "1/7  PostgreSQL (:5432)"
Noter "PostgreSQL" (Port-Ouvert 5432) $(if (Port-Ouvert 5432) { "port 5432 ouvert" } else { "demarrer le service PostgreSQL Windows" })

# ---------------------------------------------------------------------------
Etape "2/7  Ollama (:11434)"
if (-not (Attendre-Http "http://localhost:11434/api/version" 2)) {
    $ollama = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
    Ecrire "   Ollama arrete -> demarrage"
    Start-Process -FilePath $ollama -ArgumentList "serve" -WindowStyle Hidden | Out-Null
}
$ollamaOk = Attendre-Http "http://localhost:11434/api/version" 30
$modeles = if ($ollamaOk) { (Invoke-RestMethod "http://localhost:11434/api/tags").models.name } else { @() }
$manquants = @("qwen3:1.7b", "qwen3-embedding:0.6b") | Where-Object { $modeles -notcontains $_ }
Noter "Ollama" ($ollamaOk -and -not $manquants) $(if ($manquants) { "modeles manquants : $($manquants -join ', ') (ollama pull ...)" } else { "qwen3:1.7b + qwen3-embedding:0.6b" })

# ---------------------------------------------------------------------------
Etape "3/7  Docker Desktop"
function Docker-Pret { try { $v = docker info --format "{{.ServerVersion}}" 2>$null; return [bool]$v -and $LASTEXITCODE -eq 0 } catch { return $false } }
if (-not (Docker-Pret)) {
    Ecrire "   Docker arrete -> demarrage de Docker Desktop (1 a 3 min)"
    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe" | Out-Null
    $fin = (Get-Date).AddMinutes(4)
    while (-not (Docker-Pret) -and (Get-Date) -lt $fin) { Start-Sleep -Seconds 5 }
}
$dockerOk = Docker-Pret
Noter "Docker" $dockerOk $(if ($dockerOk) { "moteur pret" } else { "Docker Desktop ne repond pas" })
if (-not $dockerOk) { Ecrire "Impossible de continuer sans Docker." Red; exit 1 }

# ---------------------------------------------------------------------------
Etape "4/7  Rasa (:5005) + serveur d'actions (:5055)"
# docker-compose.local.yml et NON docker-compose.yml : ce dernier decrit la
# pile 100 % Docker (ses conteneurs Rasa visent http://fastapi:8000 et
# http://ollama:11434, et entraineraient PostgreSQL/Ollama en conteneurs).
Push-Location $Racine
try {
    if ($Entrainer) {
        Ecrire "   Entrainement du modele Rasa (plusieurs minutes)..."
        docker compose -f docker-compose.local.yml run --rm rasa python -m rasa train --out models
        if ($LASTEXITCODE -ne 0) { throw "echec de l'entrainement Rasa" }
    }
    docker compose -f docker-compose.local.yml up -d | Out-Null
} finally { Pop-Location }
# /status ne repond qu'une fois le modele charge -- c'est ce qu'on attend.
$rasaOk = Attendre-Http "http://localhost:5005/status" 300
Noter "Rasa" $rasaOk $(if ($rasaOk) { "modele : " + (Invoke-RestMethod "http://localhost:5005/status").model_file } else { "voir : docker compose logs rasa" })
$actionsOk = Attendre-Http "http://localhost:5055/health" 120
Noter "Actions" $actionsOk $(if ($actionsOk) { "serveur d'actions pret" } else { "voir : docker compose logs actions" })

# ---------------------------------------------------------------------------
Etape "5/7  Moteur FastAPI (:8000) + stubs wallet (:3103) / user (:3104)"
$fastapi = Join-Path $Racine "fastapi"
# python -m uvicorn et NON .venv\Scripts\uvicorn.exe : ce lanceur, copie
# d'un autre venv, execute le Python de C:\DEV\PFE (sans rapidocr...).
$python = Join-Path $fastapi ".venv\Scripts\python.exe"
foreach ($s in @(
        @{ Nom = "fastapi"; Module = "app.main:app"; Port = 8000 },
        @{ Nom = "wallet_stub"; Module = "wallet_stub.main:app"; Port = 3103 },
        @{ Nom = "user_stub"; Module = "user_stub.main:app"; Port = 3104 })) {
    if (Port-Ouvert $s.Port) { Ecrire "   $($s.Nom) deja en ecoute sur :$($s.Port)" }
    else { Lancer $s.Nom $python "-m uvicorn $($s.Module) --host localhost --port $($s.Port)" $fastapi | Out-Null }
    $ok = Attendre-Http "http://localhost:$($s.Port)/docs" 90
    Noter $s.Nom $ok $(if ($ok) { "http://localhost:$($s.Port)" } else { "journal : $Etat\$($s.Nom).log.err" })
}

# ---------------------------------------------------------------------------
Etape "6/7  Interface web Vite (:5173)"
$frontend = Join-Path $Racine "frontend"
if (-not (Port-Ouvert 5173)) {
    Lancer "frontend" "cmd.exe" "/c npx --no-install vite --port 5173 --strictPort" $frontend | Out-Null
}
$webOk = Attendre-Http "http://localhost:5173/" 90
Noter "Frontend" $webOk $(if ($webOk) { "http://localhost:5173" } else { "journal : $Etat\frontend.log.err" })

# ---------------------------------------------------------------------------
Etape "7/7  Prechauffage des modeles (le plus long : 1 a 3 min sans GPU)"
try {
    $e = Poster "http://localhost:8000/embeddings/query" @{ text = "bonjour" } 180
    Noter "Embeddings" $true "qwen3-embedding charge ($($e.Secondes) s)"
} catch { Noter "Embeddings" $false $_.Exception.Message }

# Deux passages par /model/parse : le premier charge qwen3:1.7b en memoire,
# le second remplit le cache du prefixe du prompt (voir
# rasa/components/qwen_intent_classifier.py) -- les messages du jury
# partiront alors du regime rapide.
foreach ($phrase in @("Bonjour", "Comment retirer mes revenus ?")) {
    try {
        $p = Poster "http://localhost:5005/model/parse" @{ text = $phrase } 300
        $intent = $p.Reponse.intent.name
        Noter "NLU '$phrase'" ($intent -and $intent -ne "nlu_fallback") "$intent ($($p.Secondes) s)"
    } catch { Noter "NLU '$phrase'" $false $_.Exception.Message }
}
try {
    $f = Poster "http://localhost:8000/faq/search" @{ question = "Comment retirer mes revenus ?" } 120
    Noter "Recherche FAQ" $true "reponse en $($f.Secondes) s"
} catch { Noter "Recherche FAQ" $false $_.Exception.Message }
# Memoire entre conversations (accueil "Ravi de vous retrouver", voir
# rasa/actions/greeting.py) : simple lecture SQL, verifie qu'elle repond.
try {
    $m = Invoke-RestMethod "http://localhost:8000/conversations/memory?user_id=prechauffage" -TimeoutSec 30
    Noter "Memoire conversations" $true "endpoint pret (found=$($m.found))"
} catch { Noter "Memoire conversations" $false $_.Exception.Message }

# ---------------------------------------------------------------------------
Etape "Bilan"
$Bilan | Format-Table -AutoSize | Out-String | Write-Host
$echecs = @($Bilan | Where-Object { $_.Etat -ne "OK" }).Count
if ($echecs -eq 0) {
    Ecrire "Tout est pret." Green
} else {
    Ecrire "$echecs point(s) en echec -- a corriger avant le passage." Red
}
Ecrire ""
Ecrire "  Chat client (EN DIRECT, sans ?demo=1) : http://localhost:5173/#/chat" White
Ecrire "  Espace conseiller                     : http://localhost:5173/#/agent" White
Ecrire "  Administration                        : http://localhost:5173/#/admin" White
Ecrire "  Journaux                              : $Etat" DarkGray
Ecrire "  Arret                                 : scripts\arreter-live.cmd" DarkGray
