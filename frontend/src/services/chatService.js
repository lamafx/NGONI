// Couche de services -- branchée sur le vrai serveur Rasa pour tout ce qui
// relève de la compréhension du langage (FAQ, diagnostic, capacités,
// accueil, hors-sujet...), via rasaClient.js. Une seule chose reste
// simulée localement : le scénario "publier une vidéo en brouillon", qui
// n'a pas d'équivalent dans le périmètre actuel du moteur (diagnostic
// wallet/user uniquement, pas de domaine vidéo -- voir README.md et
// docs/14-evolutions.md §14.6 du dépôt principal). publishVideo,
// verifyIdentity et escalateConversation restent donc mockés ; voir
// README.md pour le détail complet du branchement.

import { delay, nextId, nowLabel } from "./mockLatency";
import { callRasa, fetchTracker, parseMessage } from "./rasaClient";
import { fetchConversationUpdates, recordConversationTurn, requestHumanAgent } from "./engineClient";

// Le tracker Rasa est persisté côté serveur (SQL, voir docker-compose.yml)
// et survit à un redémarrage de Rasa -- si on envoyait toujours "conv-1"
// comme sender, une conversation de répétition/test laisserait un état
// (slot en attente, formulaire ouvert...) qui pollue la vraie démo suivante
// sur le même identifiant. Un suffixe généré une fois par session de
// navigateur garantit un tracker Rasa neuf à chaque rechargement de page,
// sans toucher aux identifiants locaux ("conv-1"...) utilisés ailleurs.
const RASA_SESSION_SUFFIX = Math.random().toString(36).slice(2, 8);
function rasaSenderId(conversationId) {
  return `${conversationId}-${RASA_SESSION_SUFFIX}`;
}

// Identite STABLE de l'utilisateur, d'une conversation a l'autre -- a
// l'inverse de rasaSenderId ci-dessus, volontairement neuf a chaque
// rechargement. Conservee dans le navigateur (pas de compte utilisateur dans
// ce perimetre, docs/13-limitations.md 13.1) : c'est elle qui permet a
// l'assistant de se souvenir de la conversation precedente (accueil
// "Ravi de vous retrouver", voir rasa/actions/greeting.py).
//
// C'est aussi le compte NGONI transmis au Diagnostic Engine (X-User-ID, voir
// rasa/actions/diagnostic.py) : les microservices wallet/user ne connaissent
// que des UUID de compte. L'ancien identifiant genere ("user-ab12cd34")
// faisait echouer TOUT diagnostic ("Identifiant utilisateur invalide").
// Faute d'authentification, le compte par defaut est un compte reel du clone
// de base : le compte de demonstration cree par fastapi/scripts/compte_demo.py
// (VITE_CLIENT_USER_ID pour en changer). La page Profil, ou l'adresse
// /?compte=<uuid>#/chat, permettent d'en choisir un autre.
const USER_ID_STORAGE_KEY = "ngoni-user-id";
export const DEFAULT_CLIENT_USER_ID =
  import.meta.env.VITE_CLIENT_USER_ID || "a40e0e00-2006-4514-8000-000000000001";
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isAccountId(value) {
  return UUID_RE.test(String(value ?? "").trim());
}

let memoryUserId = null;
export function stableUserId() {
  if (memoryUserId) return memoryUserId;
  // ?compte=<uuid> dans l'adresse (avant le #) : choisi une fois, retenu.
  const fromUrl = new URLSearchParams(window.location.search).get("compte");
  if (fromUrl && setStableUserId(fromUrl)) return memoryUserId;
  try {
    memoryUserId = localStorage.getItem(USER_ID_STORAGE_KEY);
    // Identifiant de l'ancien format (non UUID) : remplace, il ne designait
    // aucun compte.
    if (!isAccountId(memoryUserId)) {
      memoryUserId = DEFAULT_CLIENT_USER_ID;
      localStorage.setItem(USER_ID_STORAGE_KEY, memoryUserId);
    }
  } catch {
    // Stockage indisponible (navigation privee...) : compte par defaut.
    memoryUserId = DEFAULT_CLIENT_USER_ID;
  }
  return memoryUserId;
}

/** Changement de compte depuis la page Profil. Renvoie false si l'identifiant
 *  n'est pas un UUID de compte. */
export function setStableUserId(userId) {
  const value = String(userId ?? "").trim().toLowerCase();
  if (!isAccountId(value)) return false;
  memoryUserId = value;
  try {
    localStorage.setItem(USER_ID_STORAGE_KEY, value);
  } catch {
    // Valable pour cet onglet seulement.
  }
  return true;
}

// Etat de tache transmis au classifieur : uniquement ce qui decrit la tache
// en cours, jamais les caches internes des actions (suggestions FAQ,
// candidats de diagnostic...). Le classifieur decide lui-meme quoi en faire
// (voir _context_block, rasa/components/qwen_intent_classifier.py).
const CONTEXT_SLOTS = [
  "pending_field", "requested_slot", "claim_requested", "awaiting_cancel_choice",
  "editing_field", "category", "urgency", "incident_date",
  "amount", "platform", "operation_type", "issue_status",
];
const CONTEXT_MAX_TURNS = 6;

/** Memoire de conversation envoyee avec chaque message : derniers echanges
 *  et etat de la tache, lus dans le tracker Rasa juste avant l'envoi. */
function buildDialogueContext(tracker) {
  const turns = [];
  for (const event of tracker?.events ?? []) {
    if ((event.event === "user" || event.event === "bot") && event.text) {
      turns.push({ role: event.event, text: event.text });
    }
  }
  const slots = {};
  for (const name of CONTEXT_SLOTS) {
    const value = tracker?.slots?.[name];
    if (value !== null && value !== undefined && value !== false && value !== "") slots[name] = value;
  }
  return {
    turns: turns.slice(-CONTEXT_MAX_TURNS),
    slots,
    active_loop: tracker?.active_loop?.name ?? null,
  };
}

/** Ce que Rasa a REELLEMENT compris du dernier message (intention retenue,
 *  classement, reformulation) -- lu dans le dernier evenement "user" plutot
 *  que latest_message, que le "rewind" d'un repli vide. */
function readUnderstanding(tracker) {
  const users = (tracker?.events ?? []).filter((event) => event.event === "user");
  const parse = users.length ? users[users.length - 1].parse_data ?? {} : {};
  return {
    intent: parse.intent?.name ?? "nlu_fallback",
    confidence: parse.intent?.confidence ?? 0,
    ranking: (parse.intent_ranking ?? []).slice(0, 3),
    reformulation: parse.standalone_text ?? null,
  };
}

/** Identifiant de la conversation TEL QUE LE MOTEUR LE CONNAIT : c'est le
 *  `sender` envoye a Rasa, donc aussi la cle sous laquelle FastAPI journalise
 *  la conversation (voir domains/conversations/models.py). Les identifiants
 *  locaux ("conv-1") ne veulent rien dire cote serveur -- toute route de
 *  supervision doit recevoir celui-ci. */
export function conversationKey(conversationId) {
  return rasaSenderId(conversationId);
}

/** « Escalader vers un agent humain » : place la conversation dans la file des
 *  conseillers. L'assistant continue de repondre tant que personne ne l'a
 *  prise en charge -- cote moteur, seule l'assignation le fait taire. */
export function escalateToHumanAgent(conversationId, reason) {
  return requestHumanAgent(rasaSenderId(conversationId), reason);
}

/** Messages ecrits hors du flux de reponse normal -- en pratique ceux d'un
 *  conseiller humain, qui n'arrivent JAMAIS en retour de POST /api/chat
 *  puisqu'ils sont ecrits depuis un autre poste, plus tard. */
export function pollConversation(conversationId, since) {
  return fetchConversationUpdates(rasaSenderId(conversationId), since);
}

const DIACRITICS_PATTERN = new RegExp("[\\u0300-\\u036f]", "g");
const PUNCTUATION_PATTERN = /[^a-z0-9\s]/g;

function normalize(text) {
  return text
    .toLowerCase()
    .normalize("NFD")
    .replace(DIACRITICS_PATTERN, "")
    .replace(PUNCTUATION_PATTERN, " ")
    .replace(/\s+/g, " ")
    .trim();
}


export function isLocalOnlyTrigger(text) {
  const t = normalize(text);
  return t.includes("video") && t.includes("brouillon");
}

export async function inspectIntent(text) {
  const parsed = await parseMessage(text);
  return {
    intent: parsed.intent?.name ?? "nlu_fallback",
    confidence: parsed.intent?.confidence ?? 0,
    ranking: (parsed.intent_ranking ?? []).slice(0, 3),
  };
}

const ACTION_BY_INTENT = {
  greet: "Réponse directe (dialogue)",
  goodbye: "Réponse directe (dialogue)",
  bot_challenge: "Réponse directe (dialogue)",
  ask_capabilities: "Capability Registry → capacités dynamiques",
  ask_faq: "Recherche sémantique → FAQ",
  browse_faq: "Recherche sémantique → FAQ",
  select_faq_category: "Recherche sémantique → FAQ",
  select_faq_question: "Recherche sémantique → FAQ",
  diagnostic: "Moteur de diagnostic → analyse du problème signalé",
  create_reclamation: "Formulaire de réclamation → création de ticket",
  plainte: "Formulaire de réclamation → création de ticket",
  ask_complaint_status: "Consultation du statut de réclamation",
  suggestion: "Enregistrement du retour utilisateur",
  rate_response_useful: "Enregistrement du retour utilisateur",
  rate_response_not_useful: "Enregistrement du retour utilisateur",
  affirm: "Confirmation du dialogue en cours",
  deny: "Confirmation du dialogue en cours",
  out_of_scope: "Filtre hors-sujet → recadrage",
  inappropriate_language: "Filtre de langage → recadrage",
  nlu_fallback: "Repli — confiance insuffisante, reformulation demandée",
};

/** Description de l'action déclenchée par une intention -- reflète le
 * routage réel documenté dans le dépôt principal (docs/08-pipeline-traitement.md),
 * pas une simulation : chaque libellé correspond à un composant qui existe
 * vraiment (Diagnostic Engine, FAQ, Capability Registry...). */
export function describeAction(intentName) {
  return ACTION_BY_INTENT[intentName] ?? "Dialogue général";
}

/**
 * Envoie un message utilisateur et renvoie la ou les réponses de
 * l'assistant. Le déclencheur du scénario vidéo est intercepté localement
 * avant d'atteindre Rasa (aucune intention réelle ne le couvre) ; tout le
 * reste est une vraie compréhension du message par le pipeline NLU/Core
 * de Rasa (docs/07 et docs/08 du dépôt principal).
 */
export async function sendMessage(
  conversationId,
  text,
  { intent, confidence, handoff = false, onUnderstood } = {}
) {
  const t = normalize(text);
  const userId = stableUserId();

  // Un conseiller a pris la conversation en charge : le message part dans son
  // fil, PAS vers Rasa -- sinon l'usager recevrait deux reponses concurrentes
  // (celle de l'humain et celle du bot). La reponse du conseiller arrivera par
  // pollConversation, jamais en retour de cet appel.
  if (handoff) {
    try {
      await recordConversationTurn(rasaSenderId(conversationId), { userText: text, intent, confidence, userId });
    } catch (err) {
      console.error("[chatService] message non transmis au conseiller :", err);
      return [aiMessage("Votre message n'a pas pu être transmis au conseiller. Réessayez.", undefined, "error")];
    }
    return [];
  }

  if (t.includes("video") && t.includes("brouillon")) {
    await delay(500);
    return [
      aiMessage(
        "J'ai trouvé une vidéo dans vos brouillons : « Ouverture de saison — Académie NGONI ». Souhaitez-vous que je lance sa publication ?",
        [
          { label: "Publier la vidéo", action: "PUBLISH_VIDEO" },
          { label: "Pas maintenant", action: "CANCEL" },
        ]
      ),
    ];
  }

  const sender = rasaSenderId(conversationId);
  try {
    // Memoire de conversation : etat + derniers echanges, lus dans le
    // tracker AVANT l'envoi. Best-effort : sans elle, le message part seul,
    // exactement comme avant.
    const metadata = { user_id: userId };
    try {
      metadata.dialogue_context = buildDialogueContext(await fetchTracker(sender));
    } catch (err) {
      console.warn("[chatService] contexte de conversation indisponible :", err);
    }

    const rasaMessages = await callRasa(sender, text, metadata);

    // Comprehension REELLE (celle qui a pilote la reponse, contexte
    // compris), lue apres coup dans le tracker -- remplace une seconde
    // classification separee, qui doublait l'attente sans GPU et pouvait
    // afficher une intention differente de celle utilisee.
    let understood = { intent, confidence };
    try {
      understood = readUnderstanding(await fetchTracker(sender));
      onUnderstood?.(understood);
    } catch (err) {
      console.warn("[chatService] lecture de la comprehension impossible :", err);
    }

    // Journalisation best-effort : elle alimente l'espace conseiller et la
    // volumetrie, elle ne doit jamais retarder ni faire echouer l'affichage
    // d'une reponse deja obtenue (d'ou l'absence de `await`).
    recordConversationTurn(sender, {
      userText: text,
      intent: understood.intent,
      confidence: understood.confidence,
      botMessages: rasaMessages ?? [],
      userId,
    }).catch((err) => console.error("[chatService] journalisation du tour impossible :", err));
    if (!rasaMessages || rasaMessages.length === 0) {
      return [aiMessage("Je n'ai pas de réponse à vous proposer pour cette demande.")];
    }
    return rasaMessages.map((m) => aiMessage(m.text ?? "", mapRasaButtons(m.buttons)));
  } catch (err) {
    console.error("[rasaClient] échec de l'appel à Rasa :", err);
    return [
      aiMessage(
        "Le service NGONI IA est momentanément indisponible (Rasa ne répond pas sur :5005). Vérifiez que « docker compose up -d rasa actions » tourne bien, puis réessayez.",
        undefined,
        "error"
      ),
    ];
  }
}

/**
 * Traduit les boutons Rasa (title/payload) vers nos choix rapides : un
 * clic renvoie le payload comme s'il avait été tapé au clavier, exactement
 * la convention déjà en place côté Rasa (docs/08-pipeline-traitement.md
 * §8.7 du dépôt principal).
 */
function mapRasaButtons(buttons) {
  if (!buttons || buttons.length === 0) return undefined;
  return buttons.map((b) => ({ label: b.title, action: `RASA_PAYLOAD:${b.payload}` }));
}

export async function publishVideo(_conversationId) {
  await delay(1400);
  return aiMessage("Votre vidéo a été publiée avec succès.", undefined, "success");
}

export async function verifyIdentity(_conversationId, attempt) {
  await delay(1000);
  // Toujours en échec dans cette démonstration -- le scénario du dépôt
  // (frontfolder/instruction.md) attend explicitement 3 tentatives échouées
  // suivies d'une escalade automatique.
  return {
    success: false,
    message: aiMessage(`Tentative ${attempt} — Échec de la vérification.`, undefined, "error"),
  };
}

export async function escalateConversation(conversationId, reason) {
  await delay(900);
  const ticket = {
    id: `CMP-${new Date().toISOString().slice(0, 10).replace(/-/g, "")}-${nextId("").slice(-4).toUpperCase()}`,
    subject: reason,
    conversationId,
    status: "nouveau",
    createdAt: "aujourd'hui",
  };
  const summary =
    "L'utilisateur souhaitait publier une vidéo présente dans ses brouillons. La vidéo a été publiée avec succès. " +
    "Une vérification d'identité était ensuite requise. Trois tentatives ont échoué. La procédure automatique a été " +
    "interrompue et la demande a été transmise à un conseiller.";
  const timeline = [
    { id: nextId("tl"), label: "Demande reçue", time: "09:41", state: "done" },
    { id: nextId("tl"), label: "Vidéo identifiée dans les brouillons", time: "09:41", state: "done" },
    { id: nextId("tl"), label: "Publication exécutée", time: "09:42", state: "done" },
    { id: nextId("tl"), label: "Vérification d'identité demandée", time: "09:42", state: "done" },
    { id: nextId("tl"), label: "Tentative 1 — Échec", time: "09:43", state: "failed" },
    { id: nextId("tl"), label: "Tentative 2 — Échec", time: "09:43", state: "failed" },
    { id: nextId("tl"), label: "Tentative 3 — Échec", time: "09:44", state: "failed" },
    { id: nextId("tl"), label: "Escalade vers un conseiller humain", time: "09:44", state: "active" },
  ];
  return { ticket, summary, timeline };
}

export async function getConversation(conversations, conversationId) {
  await delay(150);
  return conversations.find((c) => c.id === conversationId);
}

export async function getConversations(conversations) {
  await delay(150);
  return conversations;
}

function aiMessage(text, quickReplies, variant) {
  return {
    id: nextId("msg"),
    sender: "ai",
    text,
    time: nowLabel(),
    quickReplies,
    variant,
  };
}
