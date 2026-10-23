// Enregistre la video de demonstration sur l'ECRAN REEL, avec le vrai
// explorateur de fichiers Windows pour joindre la piece d'identite -- sans
// personne aux commandes : la souris et l'explorateur sont pilotes par
// scripts/demo_souris.ps1.
//
//   node scripts/enregistrer_demo_bureau.mjs
//   node scripts/enregistrer_demo_bureau.mjs --sortie demo/ma-video.mp4 --delai 10
//
// A la difference d'enregistrer_demo_auto.mjs (Chrome invisible), ce qui est
// filme est le bureau lui-meme : pendant ~3 minutes, ne plus toucher a la
// souris ni au clavier, et activer « Ne pas deranger » (une notification
// Windows tomberait dans la video).
//
// Prerequis : la pile lancee (scripts/demarrer-live.ps1), Chrome, ffmpeg.

import { spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { attendre, attendreFichier, clientCdp } from "./cdp.mjs";

const RACINE = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
// Sans auto=1 : la demonstration s'arrete et attend la piece, comme au
// tournage manuel -- c'est l'explorateur qui la fournit.
const URL_DEMO = "http://localhost:5173/?demo=1#/chat";
const DOSSIER_PIECE = join(RACINE, "demo");
const PIECE = "carteIDFront.png";
const SOURIS = join(RACINE, "scripts", "demo_souris.ps1");
const DUREE_MAX_S = 480;
const QUEUE_S = 1.5;

const args = process.argv.slice(2);
const option = (nom, defaut) => {
  const i = args.indexOf(nom);
  return i >= 0 && args[i + 1] ? args[i + 1] : defaut;
};
const sortie = resolve(RACINE, option("--sortie", "demo/demo-ngoni-v4.mp4"));
const brut = sortie.replace(/\.mp4$/, "-brut.mp4");
const delai = Number(option("--delai", "20"));

function executer(cmd, params, { entree } = {}) {
  return new Promise((ok, ko) => {
    // windowsHide : une console PowerShell qui s'ouvre une fraction de
    // seconde se verrait dans la video.
    const p = spawn(cmd, params, { windowsHide: true, stdio: [entree ? "pipe" : "ignore", "ignore", "pipe"] });
    let erreurs = "";
    p.stderr.on("data", (d) => (erreurs += d));
    p.on("error", ko);
    p.on("close", (code) => (code === 0 ? ok() : ko(new Error(`${cmd} : ${erreurs.trim() || `code ${code}`}`))));
  });
}

const souris = (action, params = []) =>
  executer("powershell", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", SOURIS, "-Action", action, ...params]);

const cliquer = ([x, y]) => souris("cliquer", ["-X", String(Math.round(x)), "-Y", String(Math.round(y))]);

// Centre d'un element en pixels PHYSIQUES de l'ecran : Chrome est en mode
// kiosque (page a l'origine de l'ecran), devicePixelRatio porte l'echelle
// d'affichage de Windows.
const CENTRE = (selecteur) => `(() => {
  const el = document.querySelector(${JSON.stringify(selecteur)});
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return [(r.left + r.width / 2) * devicePixelRatio, (r.top + r.height / 2) * devicePixelRatio];
})()`;

async function main() {
  const travail = mkdtempSync(join(tmpdir(), "ngoni-demo-"));
  const profil = join(travail, "profil");

  console.log("\n== Enregistrement de la demonstration NGONI (ecran reel) ==\n");
  console.log("  Ne touchez plus a la souris ni au clavier jusqu'a la fin (~3 min).");
  console.log("  Activez « Ne pas deranger » si ce n'est pas deja fait.");
  for (let s = delai; s > 0; s -= 5) {
    console.log(`  Debut dans ${s} s...`);
    await attendre(Math.min(5, s) * 1000);
  }

  const ffmpeg = spawn("ffmpeg", [
    "-v", "error", "-y", "-f", "gdigrab", "-framerate", "30", "-draw_mouse", "1", "-i", "desktop",
    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "16", "-pix_fmt", "yuv420p", brut,
  ], { windowsHide: true, stdio: ["pipe", "ignore", "inherit"] });
  const t0 = Date.now();
  const depuis = () => (Date.now() - t0) / 1000;
  await attendre(800);

  const chrome = spawn(CHROME, [
    "--remote-debugging-port=0",
    `--user-data-dir=${profil}`,
    "--no-first-run",
    "--no-default-browser-check",
    // Kiosque plutot que --start-fullscreen : pas de bandeau « Appuyez sur
    // F11 pour quitter le plein ecran » pendant les premieres secondes.
    "--kiosk",
    // Interface en francais : la fenetre de fichiers s'intitule alors
    // « Ouvrir », et Chrome ne propose plus de traduire la page (bandeau qui
    // tombait dans la video).
    "--lang=fr",
    "--disable-features=Translate,CalculateNativeWinOcclusion",
    // Chrome se croyait masque (ecran gris fige pendant ~90 s) et ralentissait
    // ses minuteurs : la demonstration avancait trois fois moins vite.
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--disable-background-timer-throttling",
    URL_DEMO,
  ], { stdio: "ignore" });

  let tDebut;
  let tFin;
  try {
    const port = (await attendreFichier(join(profil, "DevToolsActivePort"), 20000)).split("\n")[0];
    let page;
    while (!page) {
      const cibles = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      page = cibles.find((c) => c.type === "page" && c.url.startsWith("http://localhost:5173"));
      if (!page) await attendre(200);
    }
    const cdp = clientCdp(page.webSocketDebuggerUrl);
    await cdp.ouvert;
    // Rien n'est garanti a l'ecran tant que Chrome n'est pas devant : une
    // fenetre deja ouverte (diaporama, explorateur...) le recouvrait.
    await souris("premier-plan", ["-Processus", String(chrome.pid)]);
    const evaluer = async (expression) =>
      (await cdp.envoyer("Runtime.evaluate", { expression, returnByValue: true })).result.value;
    const finVisible = Date.now() + 10000;
    while ((await evaluer("document.visibilityState")) !== "visible") {
      if (Date.now() > finVisible) throw new Error("Chrome est ouvert mais la page reste masquee");
      await attendre(200);
    }

    while (!(await evaluer("document.readyState === 'complete' && !!document.querySelector('.ns-composer')"))) {
      await attendre(100);
    }
    // Le pointeur attend au milieu de l'ecran, invisible au-dessus de la
    // page (voir demoOverlay.css) jusqu'a l'etape de la piece d'identite.
    // AVANT de marquer le debut de la video : Windows ne masque le pointeur
    // qu'au premier mouvement, il restait visible sur les premieres images.
    await souris("deplacer", ["-X", "1100", "-Y", "560"]);
    tDebut = depuis();
    console.log(`  Demo lancee (${tDebut.toFixed(1)} s)`);

    let pieceEnvoyee = false;
    for (;;) {
      await attendre(300);
      if (depuis() > DUREE_MAX_S) throw new Error("fin de demonstration jamais signalee (arret de securite)");
      if (await evaluer("document.documentElement.dataset.demoDone === '1'")) break;
      if (pieceEnvoyee) continue;

      const invitation = await evaluer(CENTRE(".ns-upload-prompt"));
      if (!invitation) continue;
      console.log(`  Piece d'identite demandee (${depuis().toFixed(1)} s) : ouverture de l'explorateur`);
      await attendre(1200);
      await cliquer(invitation);
      await souris("choisir", ["-Dossier", DOSSIER_PIECE, "-Fichier", PIECE]);

      let envoi = null;
      while (!envoi) {
        await attendre(150);
        envoi = await evaluer(CENTRE('button[aria-label="Envoyer la pièce jointe"]'));
      }
      await attendre(900);
      await cliquer(envoi);
      pieceEnvoyee = true;
      console.log(`  Piece envoyee (${depuis().toFixed(1)} s)`);
    }
    tFin = depuis();
    console.log(`  Fin de la demonstration (${tFin.toFixed(1)} s)`);
    await attendre(QUEUE_S * 1000);
    cdp.fermer();
  } finally {
    ffmpeg.stdin.write("q");
    await new Promise((r) => ffmpeg.on("close", r));
    await executer("taskkill", ["/PID", String(chrome.pid), "/T", "/F"]).catch(() => {});
    await attendre(500);
    rmSync(travail, { recursive: true, force: true });
  }

  const debut = Math.max(0, tDebut - 0.3);
  const fin = tFin + QUEUE_S;
  console.log(`  Coupe de ${debut.toFixed(1)} s a ${fin.toFixed(1)} s, encodage...`);
  await executer("ffmpeg", [
    "-v", "error", "-y", "-ss", debut.toFixed(2), "-to", fin.toFixed(2), "-i", brut,
    "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-r", "30", "-pix_fmt", "yuv420p",
    "-movflags", "+faststart", "-an", sortie,
  ]);
  const d = fin - debut;
  console.log(`\n  Video prete : ${sortie}  (${Math.floor(d / 60)}:${String(Math.round(d % 60)).padStart(2, "0")})`);
  console.log(`  Brut non coupe : ${brut}`);
}

main().catch((e) => {
  console.error(`\n  ECHEC : ${e.message}`);
  process.exit(1);
});
