// Pilote du mode demonstration : rejoue le scenario 1 (variante 1) sans
// aucun appel a Rasa ni a Model.
//
// Actif uniquement si l'URL porte ?demo=1, ou si VITE_DEMO_MODE=1 est defini
// au build. Hors de ce mode, rien n'est modifie : chatService continue de
// parler au vrai serveur Rasa (voir rasaClient.js).
//
// Le tour courant est choisi par POSITION, pas par correspondance de texte :
// pendant un tournage, la frappe peut differer d'un accent ou d'une virgule
// sans que la demonstration deraille. Le texte de reference reste disponible
// (currentTurn().user) pour l'afficher ou le pre-remplir.

import {
  DEMO_PACING,
  DEMO_TURNS,
  DEMO_ADVISOR,
  DEMO_ADVISOR_REPLY,
  DEMO_HANDOFF_CONNECTING_MS,
  DEMO_TICKET,
  DEMO_SUMMARY,
  DEMO_TIMELINE,
  DEMO_DECLINE_REPLY,
  DEMO_AGENT_ACT,
  DEMO_ADMIN_ACT,
  DEMO_BEFORE_AGENT_ACT_MS,
} from "../data/demoScenario1";
import { SYSTEM_PARAMETERS } from "../data/systemParameters";
import { clearParameterHistory, listParameterOverrides, updateParameter } from "./engineClient";

let cursor = 0;

// Acte courant de la demonstration. Vit au niveau du module, donc survit a la
// navigation entre les pages (une seule application, un seul chargement) --
// c'est ce qui permet au parcours de continuer tout seul du chat vers l'espace
// conseiller puis vers la supervision.
//   "chat" -> "agent" -> "admin" -> "done"
let act = "chat";

// Le drapeau, une fois lu, est RETENU pour toute la session. La demonstration
// change de page trois fois (chat -> conseiller -> supervision) et chaque
// navigation reecrit le fragment : un "?demo=1" colle dans le fragment
// (/#/chat?demo=1) disparaissait des la premiere bascule, et les deux actes
// suivants ne partaient jamais -- sans la moindre erreur a l'ecran, c'est
// a dire le pire des cas au tournage. Seule la forme /?demo=1#/chat y
// survivait, et rien ne le disait.
let demoFlag = null;

export function isDemoMode() {
  if (demoFlag !== null) return demoFlag;
  if (typeof window !== "undefined") {
    // L'application utilise HashRouter (voir App.jsx) : selon l'endroit ou on
    // colle le parametre, il se retrouve AVANT le # (window.location.search,
    // ex. /?demo=1#/chat) ou APRES (dans le hash, ex. /#/chat?demo=1). Les
    // deux formes sont acceptees -- sinon la moitie des tentatives echoue
    // sans message d'erreur.
    const hashQuery = window.location.hash.includes("?")
      ? window.location.hash.slice(window.location.hash.indexOf("?"))
      : "";
    const flag =
      new URLSearchParams(window.location.search).get("demo") ??
      new URLSearchParams(hashQuery).get("demo");
    if (flag === "1") return (demoFlag = true);
    if (flag === "0") return (demoFlag = false);
  }
  return (demoFlag = import.meta.env.VITE_DEMO_MODE === "1");
}

// ?demo=1&auto=1 : la piece d'identite est jointe et envoyee par la
// demonstration elle-meme, au lieu d'attendre qu'on la choisisse dans
// l'explorateur Windows -- c'est ce qui permet de tourner la video sans
// personne devant l'ecran (scripts/enregistrer_demo.py --auto). Retenu pour
// la session, pour la meme raison que demoFlag.
let autoUploadFlag = null;

export function isAutoUploadMode() {
  if (autoUploadFlag !== null) return autoUploadFlag;
  if (typeof window === "undefined" || !isDemoMode()) return (autoUploadFlag = false);
  const hashQuery = window.location.hash.includes("?")
    ? window.location.hash.slice(window.location.hash.indexOf("?"))
    : "";
  const flag =
    new URLSearchParams(window.location.search).get("auto") ?? new URLSearchParams(hashQuery).get("auto");
  return (autoUploadFlag = flag === "1");
}

/** Remet le scenario au premier tour -- appele au montage de la page, pour
 *  qu'un simple rechargement suffise a refaire une prise. */
export function resetDemo() {
  cursor = 0;
  act = "chat";
}

// Le lancement automatique ne vaut qu'une fois par chargement de page : le
// chat est remonte a chaque retour sur /chat, et sans ce verrou la fin de la
// demonstration en relancerait une nouvelle. Un rechargement le rearme -- c'est
// ce qui suffit a refaire une prise, sans toucher la souris.
let autoStartConsumed = false;

export function consumeAutoStart() {
  if (autoStartConsumed || !isDemoMode()) return false;
  autoStartConsumed = true;
  return true;
}

// Les seuils sont persistes en base : sans remise a zero, une prise rejouee
// ouvrait l'ecran Parametres sur la valeur ecrite la fois d'avant -- badge
// « modifié » et ligne d'historique deja la AVANT la modification filmee.
// On remet donc chaque seuil a sa valeur par defaut puis on vide le journal
// au depart de la demonstration ; l'ecran Parametres attend cette promesse
// avant de lire le moteur.
let parametersReset = Promise.resolve();

export function resetDemoParameters(changedBy) {
  const defaults = Object.fromEntries(SYSTEM_PARAMETERS.flatMap((g) => g.items).map((item) => [item.id, item.value]));
  parametersReset = (async () => {
    const overrides = (await listParameterOverrides()) ?? [];
    await Promise.all(
      overrides
        .filter((o) => o.param_id in defaults && o.value !== defaults[o.param_id])
        .map((o) => updateParameter(o.param_id, defaults[o.param_id], changedBy)),
    );
    await clearParameterHistory();
  })().catch(() => {
    // Moteur injoignable : l'ecran retombera sur le magasin local, deja remis
    // a zero par l'action RESET.
  });
  return parametersReset;
}

export function demoParametersReady() {
  return parametersReset;
}

export function currentAct() {
  return act;
}

export function setAct(next) {
  act = next;
}

export function agentAct() {
  return DEMO_AGENT_ACT;
}

export function adminAct() {
  return DEMO_ADMIN_ACT;
}

export function beforeAgentActMs() {
  return DEMO_BEFORE_AGENT_ACT_MS;
}

/**
 * Delai avant le caractere suivant, pour un acteur donne.
 *
 * Un bruit uniforme autour d'une moyenne ne suffit pas : ca reste percu comme
 * mecanique. Ce qui fait la frappe humaine, ce sont les HESITATIONS -- des
 * pauses franches et irregulieres, surtout entre les mots, et des rafales
 * rapides entre elles.
 */
export function keystrokeDelayFor(char, profile) {
  const t = profile ?? DEMO_PACING.typing;
  let base = char === " " ? t.spaceMs : ",.?!;:".includes(char) ? t.punctuationMs : t.charMs;

  // Rafale : une lettre sur trois part nettement plus vite que la moyenne.
  if (!" ,.?!;:".includes(char) && Math.random() < 0.34) base *= 0.55;

  let delay = base + Math.random() * t.jitterMs;

  // Respiration entre deux mots -- la pause la plus caracteristique.
  if (char === " " && Math.random() < 0.22) delay += 120 + Math.random() * 260;

  // Hesitation ponctuelle en plein mot, rare mais decisive.
  if (Math.random() < 0.045) delay += 90 + Math.random() * 220;

  return delay;
}

export function isDemoFinished() {
  return cursor >= DEMO_TURNS.length;
}

/** Tour courant, sans avancer le curseur. */
export function currentTurn() {
  return DEMO_TURNS[Math.min(cursor, DEMO_TURNS.length - 1)] ?? null;
}

/** Texte attendu pour le tour courant -- sert a pre-remplir le champ de
 *  saisie pendant un tournage, jamais a bloquer une autre formulation. */
export function expectedUserText() {
  return currentTurn()?.user ?? "";
}

/** Avance d'un tour et renvoie ce qu'il contient. */
export function consumeTurn() {
  const turn = currentTurn();
  cursor += 1;
  return turn;
}

export function advisor() {
  return DEMO_ADVISOR;
}

export function advisorReply() {
  return DEMO_ADVISOR_REPLY;
}

export function declineReply() {
  return DEMO_DECLINE_REPLY;
}

/** Materiel d'escalade : ce que le conseiller et l'administrateur verront. */
export function escalationBundle(conversationId) {
  return {
    ticket: { ...DEMO_TICKET, conversationId },
    summary: DEMO_SUMMARY,
    timeline: DEMO_TIMELINE.map((e, i) => ({ ...e, id: `demo-tl-${i}` })),
    advisor: DEMO_ADVISOR,
  };
}

export function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function pacing() {
  return DEMO_PACING;
}

/** Duree d'attente avant le caractere suivant -- l'irregularite est ce qui
 *  distingue une frappe simulee credible d'un defilement mecanique. */
export function keystrokeDelay(char) {
  const { charMs, spaceMs, punctuationMs, jitterMs } = DEMO_PACING.typing;
  const base = char === " " ? spaceMs : ",.?!".includes(char) ? punctuationMs : charMs;
  return base + Math.random() * jitterMs;
}

/** Delai avant l'apparition d'une reponse, proportionnel a sa longueur.
 *  Une reponse peut forcer sa propre valeur via `after`. */
export function replyDelay(reply) {
  if (typeof reply.after === "number") return reply.after;
  const { baseMs, perCharMs, minMs, maxMs } = DEMO_PACING.reply;
  const raw = baseMs + (reply.text?.length ?? 0) * perCharMs;
  return Math.min(maxMs, Math.max(minMs, raw));
}

/** Temps de lecture de l'utilisateur avant d'ecrire le tour suivant. */
export function readBefore(turn) {
  return turn?.readBefore ?? DEMO_PACING.betweenTurns;
}

export function handoffConnectingMs() {
  return DEMO_HANDOFF_CONNECTING_MS;
}
