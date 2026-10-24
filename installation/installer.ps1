# Installe et lance ngoni-ia-service sur un PC neuf -- lance par INSTALLER.cmd.
#
#   1. Git et Docker Desktop (winget), WSL si absent ;
#   2. le code (clone GitHub, ou mise a jour s'il est deja la) ;
#   3. les fichiers hors depot du dossier fichiers\ (.env, export de la base) ;
#   4. les volumes Docker du dossier volumes\ (modeles qwen3) ;
#   5. docker compose up -d --build, attente du prechauffage, navigateur.
#
# Relancable sans risque : chaque etape deja faite est sautee. Apres
# l'installation de Docker ou de WSL, Windows doit redemarrer : le script
# s'arrete, il suffit de double-cliquer de nouveau sur INSTALLER.cmd.

param(
    [string]$Destination = 'C:\DEV\NGONI\ngoni-ia-service',
    [string]$Depot = 'https://github.com/lamafx/NGONI.git',
    [string]$Branche = 'opt-embedding'
)

$ErrorActionPreference = 'Stop'
$ici = $PSScriptRoot

# Cle compose de chaque volume (voir la section volumes de docker-compose.yml) :
# un volume cree avec ces etiquettes est repris par compose sans avertissement.
$volumesCompose = @{ 'pfe_ollama' = 'model'; 'pfe_pgdata' = 'pgdata' }

function Etape([string]$texte) { Write-Host ''; Write-Host "==> $texte" -ForegroundColor Cyan }
function Info([string]$texte) { Write-Host "    $texte" }
function Arret([string]$texte) { Write-Host ''; Write-Host $texte -ForegroundColor Yellow; exit 1 }

# Commande native silencieuse : vrai si elle reussit.
function Reussit([string]$ligne) { cmd /c "$ligne >nul 2>&1"; return $LASTEXITCODE -eq 0 }

# Commande native visible : arret si elle echoue.
function Lancer([string]$quoi, [scriptblock]$commande) {
    & $commande
    if ($LASTEXITCODE -ne 0) { Arret "ECHEC : $quoi (code $LASTEXITCODE). Voir les messages ci-dessus, puis relancer INSTALLER.cmd." }
}

function Rafraichir-Path {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
}

function Installer-Winget([string]$id, [string]$nom) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Arret "winget absent : installer $nom a la main, puis relancer INSTALLER.cmd."
    }
    Info "installation de $nom (une fenetre Windows peut demander l'autorisation)..."
    winget install -e --id $id --accept-package-agreements --accept-source-agreements
    # -1978335189 : aucune mise a jour applicable ; -1978335135 : deja installe.
    $code = $LASTEXITCODE
    if ($code -ne 0 -and $code -ne -1978335189 -and $code -ne -1978335135) {
        Arret "ECHEC : installation de $nom (code $code). Voir les messages ci-dessus, puis relancer INSTALLER.cmd."
    }
    Rafraichir-Path
}

# Docker Desktop.exe : emplacement par defaut, installation par utilisateur,
# ou deduit du docker.exe du PATH (...\Docker\Docker\resources\bin\docker.exe).
function Trouver-DockerDesktop {
    $candidats = @(
        (Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Docker\Docker\Docker Desktop.exe')
    )
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if ($docker) {
        $candidats += Join-Path (Split-Path (Split-Path (Split-Path $docker.Source))) 'Docker Desktop.exe'
    }
    foreach ($c in $candidats) { if (Test-Path $c) { return $c } }
    return $null
}

try { Start-Transcript -Path (Join-Path $ici 'installation.log') -Append | Out-Null } catch {}

Write-Host 'NGONI ia-service : installation automatique' -ForegroundColor Green
Write-Host 'Premier lancement : 20 a 40 min (telechargements). Ne pas fermer cette fenetre.'

# ------------------------------------------------------------------ 1. outils
Etape '1/5 Outils (Git, WSL, Docker Desktop)'
Rafraichir-Path
$redemarrer = $false

if (Get-Command git -ErrorAction SilentlyContinue) { Info 'Git : present' }
else { Installer-Winget 'Git.Git' 'Git' }

if (Reussit 'wsl --status') { Info 'WSL : present' }
else {
    Info 'installation de WSL (autorisation administrateur demandee)...'
    $p = Start-Process wsl -ArgumentList '--install', '--no-distribution' -Verb RunAs -Wait -PassThru
    if ($p.ExitCode -ne 0) { Arret "ECHEC : installation de WSL (code $($p.ExitCode))." }
    $redemarrer = $true
}

$dockerDesktop = Trouver-DockerDesktop
if ($dockerDesktop) { Info "Docker Desktop : present ($dockerDesktop)" }
elseif (Get-Command docker -ErrorAction SilentlyContinue) { Info 'Docker : present' }
else {
    Installer-Winget 'Docker.DockerDesktop' 'Docker Desktop'
    $dockerDesktop = Trouver-DockerDesktop
    $redemarrer = $true
}

if ($redemarrer) {
    Arret ("Outils installes. REDEMARRER le PC, puis double-cliquer de nouveau sur INSTALLER.cmd`n" +
           "(au premier demarrage de Docker Desktop, accepter ses conditions d'utilisation).")
}

if (-not (Reussit 'docker info')) {
    if (-not $dockerDesktop) { Arret "Docker est installe mais arrete : le demarrer a la main, attendre 'Engine running', puis relancer INSTALLER.cmd." }
    Info 'demarrage de Docker Desktop...'
    Start-Process $dockerDesktop
    $limite = (Get-Date).AddMinutes(5)
    while (-not (Reussit 'docker info')) {
        if ((Get-Date) -gt $limite) {
            Arret "Docker ne repond pas apres 5 min. Ouvrir Docker Desktop, accepter ses conditions, attendre 'Engine running', puis relancer INSTALLER.cmd."
        }
        Start-Sleep -Seconds 5
    }
}
Info 'Docker : pret'

# -------------------------------------------------------------------- 2. code
Etape '2/5 Code du projet'
$depotParent = Split-Path $ici -Parent
if (Test-Path (Join-Path $depotParent 'docker-compose.yml')) {
    # Script lance depuis un clone (dossier installation\ du depot).
    $Destination = $depotParent
    Info "depot deja present : $Destination"
}
elseif (Test-Path (Join-Path $Destination '.git')) {
    Info "mise a jour de $Destination"
    Lancer 'git pull' { git -C $Destination pull --ff-only }
}
else {
    Info "clone de $Depot ($Branche) dans $Destination"
    New-Item -ItemType Directory -Force (Split-Path $Destination -Parent) | Out-Null
    Lancer 'git clone' { git clone -b $Branche $Depot $Destination }
}

# ---------------------------------------------------- 3. fichiers hors depot
Etape '3/5 Fichiers hors depot (.env, export de la base)'
$fichiers = Join-Path $ici 'fichiers'
if (Test-Path $fichiers) {
    Get-ChildItem $fichiers -Recurse -Force -File | ForEach-Object {
        $relatif = $_.FullName.Substring($fichiers.Length + 1)
        $cible = Join-Path $Destination $relatif
        New-Item -ItemType Directory -Force (Split-Path $cible -Parent) | Out-Null
        Copy-Item -Force $_.FullName $cible
        Info $relatif
    }
}
elseif (Test-Path (Join-Path $Destination '.env')) {
    Info '.env deja present (pas de dossier fichiers\ a cote du script)'
}
else {
    # Sans le dossier de transfert : .env genere depuis le modele, base VIDE.
    $secrets = 'POSTGRES_PASSWORD', 'APP_DB_PASSWORD', 'ADMIN_INTERNAL_SECRET', 'AUTH_SECRET', 'SERVICES_INTERNAL_SECRET'
    $lignes = Get-Content (Join-Path $Destination '.env.example') | ForEach-Object {
        $cle = ($_ -split '=', 2)[0]
        if ($secrets -contains $cle) { "$cle=" + (-join ((48..57) + (65..90) + (97..122) | Get-Random -Count 24 | ForEach-Object { [char]$_ })) }
        else { $_ }
    }
    Set-Content -Encoding ascii (Join-Path $Destination '.env') $lignes
    Write-Host '    ATTENTION : pas de dossier fichiers\ -- .env genere, la base demarrera VIDE.' -ForegroundColor Yellow
}

# ----------------------------------------------------------------- 4. volumes
Etape '4/5 Volumes Docker'
$volumes = Join-Path $ici 'volumes'
$archives = @()
if (Test-Path $volumes) { $archives = @(Get-ChildItem $volumes -Filter '*.tar.gz') }
if ($archives.Count -eq 0) { Info 'aucune archive : les modeles qwen3 seront telecharges (~2 Go)' }
foreach ($archive in $archives) {
    $nom = $archive.Name -replace '\.tar\.gz$', ''
    if (Reussit "docker volume inspect $nom") { Info "$nom : existe deja, conserve"; continue }
    $etiquettes = @()
    if ($volumesCompose.ContainsKey($nom)) {
        $etiquettes = '--label', 'com.docker.compose.project=pfe', '--label', "com.docker.compose.volume=$($volumesCompose[$nom])"
    }
    Info "$nom : restauration depuis $($archive.Name)..."
    Lancer "creation du volume $nom" { docker volume create @etiquettes $nom | Out-Null }
    Lancer "restauration du volume $nom" { docker run --rm -v "${nom}:/v" -v "${volumes}:/sauvegarde:ro" alpine:3.20 tar -xzf "/sauvegarde/$($archive.Name)" -C /v }
}
Info 'la base est restauree depuis docker\postgres\chatbotdb.dump au premier demarrage de postgres'

# ----------------------------------------------------------------- 5. lancer
Etape '5/5 Construction et demarrage (le plus long)'
Push-Location $Destination
try {
    Lancer 'docker compose up' { docker compose up -d --build }
    Info 'prechauffage du modele (quelques minutes)...'
    docker compose logs -f prechauffage
    $code = docker inspect pfe-prechauffage-1 --format '{{.State.ExitCode}}'
    if ($code -ne '0') { Arret "Le prechauffage a echoue (code $code). Relancer INSTALLER.cmd ; sinon : docker compose logs rasa fastapi" }
}
finally { Pop-Location }

Write-Host ''
Write-Host 'TERMINE : ouverture de http://localhost:5173' -ForegroundColor Green
Write-Host 'Ensuite : docker compose up -d (demarrer) / docker compose down (arreter, donnees conservees).'
Start-Process 'http://localhost:5173'
