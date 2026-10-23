// Enregistre la video de demonstration SANS PERSONNE devant l'ecran.
//
//   node scripts/enregistrer_demo_auto.mjs
//   node scripts/enregistrer_demo_auto.mjs --sortie demo/ma-video.mp4
//
// Difference avec enregistrer_demo.py (capture du bureau Windows) : ici Chrome
// tourne en mode headless, a 1920x1080, et ce sont les images de la page
// elle-meme qui sont enregistrees (Page.startScreencast, protocole DevTools).
// Rien n'apparait a l'ecran, aucune notification Windows ne peut s'inviter
// dans la video, et le PC reste utilisable pendant le tournage.
//
// La piece d'identite est envoyee par la demonstration elle-meme (?auto=1,
// voir isAutoUploadMode dans frontend/src/services/demoDirector.js), et la
// fin est signalee par la page (data-demo-done, AdminSettingsPage) : la coupe
// ne depend plus du journal du moteur.
//
// Prerequis : la pile lancee (scripts/demarrer-live.ps1), Chrome, ffmpeg.
// Node 22+ (WebSocket natif), aucune dependance npm.

import { spawn, spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { attendre, attendreFichier, clientCdp } from "./cdp.mjs";

const RACINE = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const URL_DEMO = "http://localhost:5173/?demo=1&auto=1#/chat";
const LARGEUR = 1920;
const HAUTEUR = 1080;
// La page est mise en page a 1280x720 puis rendue a l'echelle 1,5 -- soit
// 1920x1080 en sortie. C'est la geometrie de demo-ngoni.mp4 (ecran Windows a
// 150 %) : a l'echelle 1, tout le texte sortait deux tiers plus petit.
const ECHELLE = 1.5;
const VUE_L = LARGEUR / ECHELLE;
const VUE_H = HAUTEUR / ECHELLE;
const IPS = 30;
const DUREE_MAX_S = 480;
// Derniere image tenue apres la fin signalee : le journal des modifications
// reste lisible un instant au lieu d'etre coupe net.
const QUEUE_S = 1.5;

const args = process.argv.slice(2);
const iSortie = args.indexOf("--sortie");
const sortie = resolve(RACINE, iSortie >= 0 && args[iSortie + 1] ? args[iSortie + 1] : "demo/demo-ngoni-v3.mp4");

async function main() {
  const travail = mkdtempSync(join(tmpdir(), "ngoni-demo-"));
  const images = join(travail, "images");
  const profil = join(travail, "profil");
  mkdirSync(images);

  console.log("\n== Enregistrement automatique de la demonstration NGONI ==\n");
  const chrome = spawn(CHROME, [
    "--headless=new",
    "--remote-debugging-port=0",
    `--user-data-dir=${profil}`,
    `--window-size=${VUE_L},${VUE_H}`,
    "--hide-scrollbars",
    "--mute-audio",
    "--no-first-run",
    "--no-default-browser-check",
    "about:blank",
  ], { stdio: "ignore" });

  try {
    const port = (await attendreFichier(join(profil, "DevToolsActivePort"), 20000)).split("\n")[0];
    const cibles = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
    const page = cibles.find((c) => c.type === "page");
    const cdp = clientCdp(page.webSocketDebuggerUrl);
    await cdp.ouvert;

    // Horodatage reel de chaque image : le screencast n'emet qu'aux
    // changements d'affichage, c'est la duree entre deux images qui donne le
    // rythme -- jamais une cadence supposee.
    const trames = [];
    let chargee = false;
    cdp.sur("Page.loadEventFired", () => {
      chargee = true;
    });
    cdp.sur("Page.screencastFrame", ({ data, metadata, sessionId }) => {
      cdp.envoyer("Page.screencastFrameAck", { sessionId }).catch(() => {});
      if (!chargee) return;
      const fichier = join(images, `${String(trames.length).padStart(6, "0")}.jpg`);
      writeFileSync(fichier, Buffer.from(data, "base64"));
      trames.push({ fichier, t: metadata.timestamp });
    });

    await cdp.envoyer("Page.enable");
    await cdp.envoyer("Runtime.enable");
    await cdp.envoyer("Emulation.setDeviceMetricsOverride", {
      width: VUE_L, height: VUE_H, deviceScaleFactor: ECHELLE, mobile: false,
    });
    await cdp.envoyer("Page.startScreencast", {
      format: "jpeg", quality: 92, maxWidth: LARGEUR, maxHeight: HAUTEUR, everyNthFrame: 1,
    });
    await cdp.envoyer("Page.navigate", { url: URL_DEMO });
    console.log(`  Demo lancee : ${URL_DEMO}`);

    const debut = Date.now();
    let derniereAnnonce = 0;
    for (;;) {
      await attendre(500);
      const { result } = await cdp.envoyer("Runtime.evaluate", {
        expression: "[document.documentElement.dataset.demoDone || '', location.hash]",
        returnByValue: true,
      });
      const [fini, ecran] = result.value;
      const ecoule = (Date.now() - debut) / 1000;
      if (ecoule - derniereAnnonce >= 15) {
        derniereAnnonce = ecoule;
        console.log(`  ${Math.round(ecoule)} s  ${ecran}  (${trames.length} images)`);
      }
      if (fini === "1") break;
      if (ecoule > DUREE_MAX_S) throw new Error("fin de demonstration jamais signalee (arret de securite)");
    }
    await attendre(QUEUE_S * 1000);
    await cdp.envoyer("Page.stopScreencast");
    cdp.fermer();
    console.log(`  Fin de la demonstration detectee -- ${trames.length} images capturees.`);
    // Le screencast n'envoie rien quand rien ne bouge : un ecart long n'est
    // donc un probleme que s'il tombe pendant une animation. On l'affiche
    // pour pouvoir le verifier a l'image.
    const ecarts = trames.slice(1).map((t, i) => ({ dt: t.t - trames[i].t, a: t.t - trames[0].t }));
    const longs = ecarts.filter((e) => e.dt > 0.5).sort((x, y) => y.dt - x.dt).slice(0, 8);
    console.log(`  Images vides de changement > 0,5 s : ${longs.map((e) => `${e.dt.toFixed(1)} s a ${e.a.toFixed(0)} s`).join(", ") || "aucune"}`);

    // Liste concat : chaque image tenue jusqu'a l'arrivee de la suivante.
    const lignes = ["ffconcat version 1.0"];
    trames.forEach((trame, i) => {
      const suivante = trames[i + 1]?.t ?? trame.t + QUEUE_S;
      lignes.push(`file '${trame.fichier.replaceAll("\\", "/")}'`, `duration ${(suivante - trame.t).toFixed(4)}`);
    });
    lignes.push(`file '${trames.at(-1).fichier.replaceAll("\\", "/")}'`);
    const liste = join(travail, "liste.txt");
    writeFileSync(liste, lignes.join("\n"));

    mkdirSync(dirname(sortie), { recursive: true });
    console.log("  Encodage...");
    const enc = spawnSync("ffmpeg", [
      "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", liste,
      "-vf", `scale=${LARGEUR}:${HAUTEUR}:flags=lanczos,format=yuv420p`,
      "-fps_mode", "cfr", "-r", String(IPS),
      "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-movflags", "+faststart", "-an", sortie,
    ], { stdio: "inherit" });
    if (enc.status !== 0) throw new Error("echec de l'encodage ffmpeg");

    const duree = Number(spawnSync("ffprobe", [
      "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", sortie,
    ], { encoding: "utf8" }).stdout.trim());
    console.log(`\n  Video prete : ${sortie}  (${Math.floor(duree / 60)}:${String(Math.round(duree % 60)).padStart(2, "0")})`);
  } finally {
    chrome.kill();
    await attendre(500);
    rmSync(travail, { recursive: true, force: true });
  }
}

main().catch((e) => {
  console.error(`\n  ECHEC : ${e.message}`);
  process.exit(1);
});
