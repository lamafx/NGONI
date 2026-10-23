// Client minimal du protocole DevTools de Chrome, partage par les deux
// enregistreurs de la demonstration (enregistrer_demo_auto.mjs, invisible ;
// enregistrer_demo_bureau.mjs, ecran reel). Node 22+ : WebSocket natif, aucune
// dependance npm.

import { existsSync, readFileSync } from "node:fs";

export const attendre = (ms) => new Promise((r) => setTimeout(r, ms));

export async function attendreFichier(chemin, ms) {
  const fin = Date.now() + ms;
  while (Date.now() < fin) {
    if (existsSync(chemin)) {
      const contenu = readFileSync(chemin, "utf8").trim();
      if (contenu) return contenu;
    }
    await attendre(100);
  }
  throw new Error(`Chrome n'a pas ouvert son port de debogage (${chemin})`);
}

export function clientCdp(urlWs) {
  const ws = new WebSocket(urlWs);
  let id = 0;
  const enAttente = new Map();
  const ecouteurs = new Map();
  ws.addEventListener("message", (e) => {
    const msg = JSON.parse(e.data);
    if (msg.id && enAttente.has(msg.id)) {
      const { ok, ko } = enAttente.get(msg.id);
      enAttente.delete(msg.id);
      msg.error ? ko(new Error(msg.error.message)) : ok(msg.result);
    } else if (msg.method) {
      ecouteurs.get(msg.method)?.(msg.params);
    }
  });
  return {
    ouvert: new Promise((ok, ko) => {
      ws.addEventListener("open", ok);
      ws.addEventListener("error", ko);
    }),
    envoyer(method, params = {}) {
      id += 1;
      ws.send(JSON.stringify({ id, method, params }));
      return new Promise((ok, ko) => enAttente.set(id, { ok, ko }));
    },
    sur(method, fn) {
      ecouteurs.set(method, fn);
    },
    fermer: () => ws.close(),
  };
}
