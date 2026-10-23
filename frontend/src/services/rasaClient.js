// Client HTTP vers le vrai serveur Rasa (canal REST), voir
// docs/06-api-reference.md et docs/08-pipeline-traitement.md du dépôt
// principal. En développement, les requêtes passent par le proxy Vite
// (/rasa -> http://localhost:5005, voir vite.config.js) pour éviter le CORS.
// En build de production, définir VITE_RASA_URL pour pointer directement
// vers le serveur Rasa (voir README.md).
const RASA_BASE_URL = import.meta.env.VITE_RASA_URL || "/rasa";
// Le NLU (classifieur d'intention, voir rasa/components/) prompte un LLM local
// via Model pour chaque message -- mesuré à ~7-9s en régime normal (modèle
// déjà chargé), jusqu'à ~30s si Model a déchargé le modèle entre deux
// messages (keep_alive expiré). Un timeout de 12s coupait des réponses
// pourtant valides. Sur une machine sans GPU, un message porteur d'entités a
// été mesuré à ~24s modèle chargé, et le composant NLU attend lui-même
// jusqu'à 90s (request_timeout) : 120s laisse Rasa répondre -- au pire par
// son repli -- avant que le navigateur n'abandonne.
const REQUEST_TIMEOUT_MS = 120000;

/**
 * Envoie un message au webhook REST de Rasa et renvoie la liste brute des
 * messages du bot (forme Rasa : { text?, buttons?, image? }[]).
 * `sender` identifie la conversation côté tracker Rasa -- même rôle que le
 * `sender` du corps POST /webhooks/rest/webhook documenté en 8.2.
 */
export async function callRasa(sender, message, metadata = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    // `metadata` arrive telle quelle jusqu'au classifieur NLU (Message.data,
    // voir rasa/components/qwen_intent_classifier.py) et dans
    // tracker.latest_message cote actions -- memoire de conversation et
    // identite stable de l'utilisateur, voir chatService.js.
    const response = await fetch(`${RASA_BASE_URL}/webhooks/rest/webhook`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sender, message, metadata }),
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new Error(`Rasa a répondu ${response.status}`);
    }

    return await response.json();
  } finally {
    clearTimeout(timeout);
  }
}

/**
 * Etat de la conversation tel que Rasa le connait (GET
 * /conversations/{sender}/tracker, API activee par --enable-api, voir
 * rasa/Dockerfile) : slots, formulaire actif, journal des echanges. Lecture
 * locale, quelques millisecondes -- aucun appel au LLM.
 */
export async function fetchTracker(sender) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);

  try {
    const response = await fetch(
      `${RASA_BASE_URL}/conversations/${encodeURIComponent(sender)}/tracker?include_events=AFTER_RESTART`,
      { signal: controller.signal }
    );
    if (!response.ok) {
      throw new Error(`Rasa a répondu ${response.status}`);
    }
    return await response.json();
  } finally {
    clearTimeout(timeout);
  }
}

/**
 * Classification NLU seule (POST /model/parse) -- n'affecte pas la
 * conversation, sert uniquement à exposer ce que le classifieur voit
 * réellement (panneau "sous le capot"). Passe par le même composant de classification
 * que la vraie conversation (rasa/components/),
 * donc la même latence -- ce n'est pas un raccourci ni une simulation.
 */
export async function parseMessage(text) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const response = await fetch(`${RASA_BASE_URL}/model/parse`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new Error(`Rasa a répondu ${response.status}`);
    }

    return await response.json();
  } finally {
    clearTimeout(timeout);
  }
}
