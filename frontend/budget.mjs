// Modele de duree de la demonstration, reconstitue a partir des sequences
// d'await reelles de ChatPage (runAutoplay / runDemoTurn / runDemoEscalation),
// AgentPage (runAgentAct) et AdminSettingsPage (runSettingsScene).
// Les valeurs aleatoires sont remplacees par leur esperance.
import {
  DEMO_PACING as P,
  DEMO_TURNS,
  DEMO_AGENT_ACT,
  DEMO_ADMIN_ACT,
  DEMO_HANDOFF_CONNECTING_MS,
  DEMO_BEFORE_AGENT_ACT_MS,
} from "./src/data/demoScenario1.js";

const CURSOR = DEMO_AGENT_ACT.cursorTravelMs;
const CLICK = 260;
const SCROLL = 700;

/* ---- acte I : le chat ------------------------------------------------ */
// keystrokeDelay (ChatPage) : base + random*jitter  -> base + jitter/2
function typingChat(text) {
  const t = P.typing;
  let ms = t.leadIn;
  for (const c of text) {
    const base = c === " " ? t.spaceMs : ",.?!".includes(c) ? t.punctuationMs : t.charMs;
    ms += base + t.jitterMs / 2;
  }
  return ms;
}

function replyDelay(r) {
  if (typeof r.after === "number") return r.after;
  const { baseMs, perCharMs, minMs, maxMs } = P.reply;
  return Math.min(maxMs, Math.max(minMs, baseMs + (r.text?.length ?? 0) * perCharMs));
}

const act1 = [];
let first = true;
act1.push(["amorce", P.beforeFirstTurn]);
for (const turn of DEMO_TURNS) {
  const rows = [];
  if (!first) rows.push(["lecture avant le tour", turn.readBefore ?? P.betweenTurns]);
  first = false;
  if (turn.kind === "upload") {
    rows.push(["envoi manuel de la piece (temps opérateur, non compté)", 0]);
  } else {
    rows.push(["frappe du client", typingChat(turn.user)]);
    rows.push(["avant envoi", P.beforeSend]);
  }
  rows.push(["avant les trois points", P.beforeTyping]);
  const pl = turn.pipeline;
  rows.push(["pipeline (3 étapes)", pl.understandAfter + pl.actAfter + pl.resultAfter]);
  if (turn.pauseBeforeReplies) rows.push(["pause dramatique", turn.pauseBeforeReplies]);
  turn.replies.forEach((r, i) => rows.push([`réponse ${i + 1}`, replyDelay(r)]));
  if (turn.afterReplies) rows.push(["incrustation de fin de tour", turn.afterReplies.ms ?? 2500]);
  if (turn.effect?.type === "ESCALATE") {
    rows.push(["mise en relation", DEMO_HANDOFF_CONNECTING_MS]);
    rows.push(["avant bascule vers le conseiller", DEMO_BEFORE_AGENT_ACT_MS]);
  }
  act1.push([`— ${turn.id}`, rows.reduce((a, r) => a + r[1], 0), rows]);
}

/* ---- acte II : le conseiller ----------------------------------------- */
// keystrokeDelayFor (demoDirector) : rafales, respirations, hesitations
function typingAgent(text) {
  const t = DEMO_AGENT_ACT.typing;
  let ms = t.leadIn;
  for (const c of text) {
    let base = c === " " ? t.spaceMs : ",.?!;:".includes(c) ? t.punctuationMs : t.charMs;
    if (!" ,.?!;:".includes(c)) base *= 1 - 0.34 * 0.45; // 34 % des lettres a 55 %
    ms += base + t.jitterMs / 2;
    if (c === " ") ms += 0.22 * 250;
    ms += 0.045 * 200;
  }
  return ms;
}

const act2 = [["amorce", 700]];
for (const step of DEMO_AGENT_ACT.steps) {
  let ms = 0;
  const rows = [];
  if (step.target) {
    if (step.scroll) rows.push(["mise au cadre", SCROLL]);
    rows.push([step.cursor === "click" ? "curseur + clic" : "curseur", CURSOR + (step.cursor === "click" ? CLICK : 0)]);
  }
  if (step.action === "TYPE_AND_SEND") {
    const text = step.text ?? DEMO_AGENT_ACT.reply;
    rows.push([`frappe (${text.length} car.)`, typingAgent(text)]);
    rows.push(["avant clic Envoyer", 500]);
    rows.push(["clic Envoyer", CURSOR + CLICK]);
  }
  if (step.overlay) rows.push(["incrustation", step.overlay.ms ?? 2500]);
  rows.push(["attente", step.hold ?? 0]);
  ms = rows.reduce((a, r) => a + r[1], 0);
  act2.push([`— ${step.id}`, ms, rows]);
}
act2.push(["avant la supervision", DEMO_AGENT_ACT.beforeAdminAct]);

/* ---- acte III : la supervision --------------------------------------- */
const cfg = DEMO_ADMIN_ACT.settings;
const sceneRows = [
  ["descente vers le seuil", cfg.scrollToParamMs],
  ["clic sur la valeur", cfg.cursorTravelMs + CLICK],
  ["ouverture du champ", cfg.beforeEdit],
  ["frappe de la valeur", cfg.typing.leadIn + 2 * (cfg.typing.charMs + cfg.typing.jitterMs / 2)],
  ["incrustation seuil", cfg.editOverlay.ms],
  ["après frappe", cfg.afterType],
  ["clic sur la coche", cfg.cursorTravelMs + CLICK],
  ["ouverture de la modale", cfg.beforeModal],
  ["incrustation identité", cfg.confirmOverlay.ms],
  ["lecture de la modale", cfg.readModalMs],
  ["clic Confirmer", cfg.cursorTravelMs + CLICK],
  ["après confirmation", cfg.afterConfirm],
  ["descente vers le journal", cfg.scrollToHistoryMs],
  ["curseur sur la ligne", cfg.cursorTravelMs],
  ["incrustation trace", cfg.traceOverlay.ms],
  ["lecture du journal", cfg.readHistoryMs],
];
const act3 = [];
for (const p of DEMO_ADMIN_ACT.tour) {
  if (p.script) {
    act3.push([`— ${p.path} (manipulé)`, p.settle + sceneRows.reduce((a, r) => a + r[1], 0), sceneRows]);
  } else {
    act3.push([`— ${p.path}`, p.hold]);
  }
}

/* ---- restitution ------------------------------------------------------ */
const fmt = (ms) => `${Math.floor(ms / 1000 / 60)}:${String(Math.round((ms / 1000) % 60)).padStart(2, "0")}`;
const sum = (rows) => rows.reduce((a, r) => a + r[1], 0);

function show(title, rows) {
  const total = sum(rows);
  console.log(`
${title} — ${fmt(total)} (${Math.round(total / 1000)} s)`);
  for (const row of rows) {
    console.log(`   ${String(Math.round(row[1] / 1000) + " s").padStart(6)}  ${row[0]}`);
    if (row[2] && process.argv.includes("--detail")) {
      for (const [l, m] of row[2]) console.log(`            ${String(m).padStart(6)} ms  ${l}`);
    }
  }
  return total;
}

const t1 = show("ACTE I  — chat", act1);
const t2 = show("ACTE II — conseiller", act2);
const t3 = show("ACTE III— supervision", act3);
console.log(`\nTOTAL ${fmt(t1 + t2 + t3)}  (hors temps opérateur pour l'envoi de la pièce)`);
console.log(`cible 3:00, plafond 3:10 → à retirer : ${Math.round((t1 + t2 + t3 - 190000) / 1000)} s pour tenir 3:10`);
