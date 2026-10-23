# Pilote la VRAIE souris et l'explorateur de fichiers Windows pendant le
# tournage de la demonstration (appele par scripts/enregistrer_demo_bureau.mjs).
#
#   demo_souris.ps1 -Action deplacer -X 960 -Y 540
#   demo_souris.ps1 -Action cliquer  -X 960 -Y 540
#   demo_souris.ps1 -Action choisir  -Dossier C:\...\demo -Fichier CNI_recto.jpeg
#   demo_souris.ps1 -Action premier-plan -Processus 1234
#
# Coordonnees en pixels PHYSIQUES de l'ecran : le processus se declare
# DPI-aware avant tout, sans quoi Windows (affichage a 150 %) lui renverrait
# des coordonnees mises a l'echelle -- et la souris viserait a cote.

param(
    [Parameter(Mandatory = $true)][ValidateSet("deplacer", "cliquer", "choisir", "premier-plan")] [string]$Action,
    [int]$X,
    [int]$Y,
    [string]$Dossier,
    [string]$Fichier,
    [int]$Processus
)

$ErrorActionPreference = "Stop"

Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class Souris {
    [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr v);
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern bool GetCursorPos(out POINT p);
    [DllImport("user32.dll")] public static extern void mouse_event(uint f, int dx, int dy, uint d, IntPtr e);
    [DllImport("user32.dll")] public static extern IntPtr FindWindow(string cls, string titre);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
    [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint f, IntPtr e);
    [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X; public int Y; }
}
"@
# -4 = DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
[void][Souris]::SetProcessDpiAwarenessContext([IntPtr](-4))

function Deplacer([int]$cx, [int]$cy, [int]$ms = 750) {
    $p = New-Object Souris+POINT
    [void][Souris]::GetCursorPos([ref]$p)
    $etapes = [Math]::Max(12, [int]($ms / 12))
    for ($i = 1; $i -le $etapes; $i++) {
        # Acceleration puis freinage : un trajet a vitesse constante se voit
        # tout de suite comme un trajet de machine.
        $t = $i / $etapes
        $e = if ($t -lt 0.5) { 2 * $t * $t } else { 1 - [Math]::Pow(-2 * $t + 2, 2) / 2 }
        [void][Souris]::SetCursorPos([int]($p.X + ($cx - $p.X) * $e), [int]($p.Y + ($cy - $p.Y) * $e))
        Start-Sleep -Milliseconds 12
    }
}

function Clic([int]$n = 1) {
    for ($i = 0; $i -lt $n; $i++) {
        [Souris]::mouse_event(0x0002, 0, 0, 0, [IntPtr]::Zero)
        Start-Sleep -Milliseconds 60
        [Souris]::mouse_event(0x0004, 0, 0, 0, [IntPtr]::Zero)
        if ($i -lt $n - 1) { Start-Sleep -Milliseconds 90 }
    }
}

function Centre($element) {
    $r = $element.Current.BoundingRectangle
    return @([int]($r.X + [Math]::Min($r.Width / 2, 60)), [int]($r.Y + $r.Height / 2))
}

if ($Action -eq "deplacer") { Deplacer $X $Y; exit 0 }
if ($Action -eq "cliquer") { Deplacer $X $Y; Start-Sleep -Milliseconds 250; Clic; exit 0 }

# --- premier-plan : la fenetre de Chrome devant tout le reste ----------------
# Windows refuse le premier plan a une fenetre ouverte par un processus en
# arriere-plan : Chrome s'ouvrait DERRIERE ce qui etait a l'ecran (constate :
# un diaporama PowerPoint), et la video filmait le diaporama. Une frappe
# d'Alt leve ce verrou le temps de l'appel.
if ($Action -eq "premier-plan") {
    $fin = (Get-Date).AddSeconds(15)
    $hwnd = [IntPtr]::Zero
    while ($hwnd -eq [IntPtr]::Zero -and (Get-Date) -lt $fin) {
        $hwnd = (Get-Process -Id $Processus).MainWindowHandle
        if ($hwnd -eq [IntPtr]::Zero) { Start-Sleep -Milliseconds 200 }
    }
    if ($hwnd -eq [IntPtr]::Zero) { throw "fenetre de Chrome introuvable" }
    for ($essai = 0; $essai -lt 5 -and [Souris]::GetForegroundWindow() -ne $hwnd; $essai++) {
        [Souris]::keybd_event(0x12, 0, 0, [IntPtr]::Zero)
        [Souris]::keybd_event(0x12, 0, 2, [IntPtr]::Zero)
        [void][Souris]::ShowWindow($hwnd, 5)
        [void][Souris]::SetForegroundWindow($hwnd)
        Start-Sleep -Milliseconds 300
    }
    if ([Souris]::GetForegroundWindow() -ne $hwnd) { throw "Chrome n'a pas pu passer au premier plan" }
    exit 0
}

# --- choisir : la fenetre « Ouvrir » de Chrome -------------------------------
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes, System.Windows.Forms
$A = [System.Windows.Automation.AutomationElement]
$C = [System.Windows.Automation.ControlType]

$fin = (Get-Date).AddSeconds(15)
$hwnd = [IntPtr]::Zero
while ($hwnd -eq [IntPtr]::Zero -and (Get-Date) -lt $fin) {
    # « Open » si Chrome tourne en anglais malgre --lang=fr.
    $hwnd = [Souris]::FindWindow("#32770", "Ouvrir")
    if ($hwnd -eq [IntPtr]::Zero) { $hwnd = [Souris]::FindWindow("#32770", "Open") }
    if ($hwnd -eq [IntPtr]::Zero) { Start-Sleep -Milliseconds 150 }
}
if ($hwnd -eq [IntPtr]::Zero) { throw "la fenetre Ouvrir n'est pas apparue" }
[void][Souris]::SetForegroundWindow($hwnd)
$fenetre = $A::FromHandle($hwnd)
Start-Sleep -Milliseconds 900  # le temps de voir la fenetre s'ouvrir

# Champ « Nom du fichier » : on y tape le dossier, comme on le ferait a la
# main, puis Entree -- l'explorateur s'y rend et affiche son contenu.
$condEdit = New-Object System.Windows.Automation.PropertyCondition($A::ControlTypeProperty, $C::Edit)
$champ = $fenetre.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condEdit) |
    Where-Object { $_.Current.AutomationId -eq "1148" } | Select-Object -First 1
if ($null -eq $champ) { throw "champ Nom du fichier introuvable" }
$xy = Centre $champ
Deplacer $xy[0] $xy[1] 650
Start-Sleep -Milliseconds 200
Clic
Start-Sleep -Milliseconds 300
foreach ($car in $Dossier.ToCharArray()) {
    [System.Windows.Forms.SendKeys]::SendWait([string]$car)
    Start-Sleep -Milliseconds (45 + (Get-Random -Maximum 50))
}
Start-Sleep -Milliseconds 350
[System.Windows.Forms.SendKeys]::SendWait("{ENTER}")

# Le fichier, dans la liste du dossier : double-clic dessus.
$nom = [System.IO.Path]::GetFileNameWithoutExtension($Fichier)
$condItem = New-Object System.Windows.Automation.PropertyCondition($A::ControlTypeProperty, $C::ListItem)
$item = $null
$fin = (Get-Date).AddSeconds(10)
while ($null -eq $item -and (Get-Date) -lt $fin) {
    Start-Sleep -Milliseconds 250
    $item = $fenetre.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condItem) |
        Where-Object { $_.Current.Name -like "$nom*" } | Select-Object -First 1
}
if ($null -eq $item) { throw "$Fichier introuvable dans $Dossier" }
Start-Sleep -Milliseconds 900  # le contenu du dossier se lit avant qu'on choisisse
$xy = Centre $item
Deplacer $xy[0] $xy[1] 800
Start-Sleep -Milliseconds 450
Clic 2
exit 0
