# Prepare, sur l'ANCIEN PC, le dossier a emporter -- lance par PREPARER-TRANSFERT.cmd.
#
#   <Sortie>\INSTALLER.cmd, installer.ps1, README.md   a double-cliquer sur le nouveau PC
#   <Sortie>\fichiers\    .env et export frais de la base (hors depot : secrets, donnees reelles)
#   <Sortie>\volumes\     pfe_ollama.tar.gz, les modeles qwen3 (~2 Go), si la place le permet
#
# La pile doit tourner (docker compose up -d) : l'export de la base passe par
# le conteneur postgres. Le volume de la base n'est pas archive tel quel :
# l'export pg_dump est coherent meme base ouverte, et il est restaure tout
# seul au premier demarrage sur le nouveau PC.

param(
    # Une cle USB de preference (ex. E:\NGONI-installation) : le dossier contient des secrets.
    [string]$Sortie = 'C:\DEV\NGONI\NGONI-installation',
    [switch]$SansModeles
)

$ErrorActionPreference = 'Stop'
$depot = Split-Path $PSScriptRoot -Parent

function Etape([string]$texte) { Write-Host ''; Write-Host "==> $texte" -ForegroundColor Cyan }
function Info([string]$texte) { Write-Host "    $texte" }
function Arret([string]$texte) { Write-Host ''; Write-Host $texte -ForegroundColor Yellow; exit 1 }
function Lancer([string]$quoi, [scriptblock]$commande) {
    & $commande
    if ($LASTEXITCODE -ne 0) { Arret "ECHEC : $quoi (code $LASTEXITCODE)." }
}

Push-Location $depot
try {
    Etape '1/4 Depot git'
    $nonCommites = @(git status --porcelain)
    $nonPousses = git rev-list --count '@{u}..HEAD'
    if ($nonCommites.Count -gt 0) { Write-Host "    ATTENTION : $($nonCommites.Count) modification(s) non commitee(s) -- absentes du clone." -ForegroundColor Yellow }
    if ($nonPousses -ne '0') { Write-Host "    ATTENTION : $nonPousses commit(s) non pousse(s) -- faire git push avant de partir." -ForegroundColor Yellow }
    if ($nonCommites.Count -eq 0 -and $nonPousses -eq '0') { Info 'tout est commite et pousse' }

    Etape '2/4 Scripts d''installation'
    New-Item -ItemType Directory -Force $Sortie | Out-Null
    foreach ($f in 'INSTALLER.cmd', 'installer.ps1', 'README.md') {
        Copy-Item -Force (Join-Path $PSScriptRoot $f) $Sortie
        Info $f
    }

    Etape '3/4 Fichiers hors depot'
    Lancer 'export de la base' { docker compose exec -T postgres pg_dump -U postgres -d chatbotdb -Fc -Z 9 -f /tmp/chatbotdb.dump }
    Lancer 'copie de l''export' { docker compose cp postgres:/tmp/chatbotdb.dump docker/postgres/chatbotdb.dump }
    $fichiers = Join-Path $Sortie 'fichiers'
    foreach ($rel in '.env', 'fastapi\.env', 'rasa\.env', 'rasa\actions\.env', 'docker\postgres\chatbotdb.dump', 'docker\postgres\chatbotdb-avant-soutenance.dump') {
        $source = Join-Path $depot $rel
        if (-not (Test-Path $source)) { continue }
        $cible = Join-Path $fichiers $rel
        New-Item -ItemType Directory -Force (Split-Path $cible -Parent) | Out-Null
        Copy-Item -Force $source $cible
        Info $rel
    }

    Etape '4/4 Volume des modeles (pfe_ollama)'
    $archive = Join-Path $Sortie 'volumes\pfe_ollama.tar.gz'
    $libre = (Get-PSDrive ((Resolve-Path $Sortie).Drive.Name)).Free
    if ($SansModeles) { Info 'ignore (-SansModeles) : le nouveau PC les telechargera' }
    elseif (Test-Path $archive) { Info 'archive deja presente, conservee' }
    elseif ($libre -lt 4GB) {
        Write-Host ("    ignore : {0:N1} Go libres sur le disque de sortie (4 Go requis). Le nouveau PC telechargera les modeles," -f ($libre / 1GB)) -ForegroundColor Yellow
        Write-Host '    ou relancer avec une cle USB : PREPARER-TRANSFERT.cmd -Sortie E:\NGONI-installation' -ForegroundColor Yellow
    }
    else {
        New-Item -ItemType Directory -Force (Split-Path $archive -Parent) | Out-Null
        Info 'archivage (~2 Go, quelques minutes)...'
        Lancer 'archivage du volume' { docker run --rm -v pfe_ollama:/v:ro -v "$(Split-Path $archive -Parent):/sauvegarde" alpine:3.20 tar -czf /sauvegarde/pfe_ollama.tar.gz -C /v . }
    }
}
finally { Pop-Location }

$total = (Get-ChildItem $Sortie -Recurse -File | Measure-Object Length -Sum).Sum
Write-Host ''
Write-Host ("PRET : {0} ({1:N0} Mo)" -f $Sortie, ($total / 1MB)) -ForegroundColor Green
Write-Host 'Contient les mots de passe et des donnees reelles : cle USB ou Drive PRIVE, jamais GitHub.'
