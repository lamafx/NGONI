import { authHeader, logout } from "./auth";

// Client HTTP vers le moteur FastAPI (:8000), via le proxy Vite `/engine`
// en developpement (voir vite.config.js). En build de production, definir
// VITE_ENGINE_URL pour pointer directement vers le moteur.
//
// Les pages d'administration branchees sur ce client lisent de VRAIES donnees
// (catalogue FAQ, tickets, journal d'audit, capacites) -- rien n'est simule.

const BASE = import.meta.env.VITE_ENGINE_URL || "/engine";

// Les routes /admin/* et « mes ... » du moteur exigent le jeton de session de
// l'utilisateur connecte (voir services/auth.js) : plus aucun secret dans le
// code de la page.
const TIMEOUT_MS = 15000;

async function request(path, { method = "GET", body, admin = false, userId, timeoutMs = TIMEOUT_MS } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${BASE}${path}`, {
      method,
      signal: controller.signal,
      headers: {
        ...(body ? { "Content-Type": "application/json" } : {}),
        // Jeton de session : il porte le role et l'identite (compte client
        // ou conseiller), verifies et signes par le moteur.
        ...authHeader(),
      },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    if (res.status === 401 && (admin || userId !== undefined)) {
      // Session expiree ou absente : retour a la page de connexion.
      logout();
      window.dispatchEvent(new CustomEvent("ngoni-session-expired"));
    }
    if (!res.ok) {
      // Le motif renvoye par le moteur (`detail`) est fait pour etre lu.
      let detail = "";
      try {
        const payload = await res.json();
        detail = typeof payload?.detail === "string" ? ` — ${payload.detail}` : "";
      } catch {
        // corps vide ou non JSON
      }
      const error = new Error(`${method} ${path} → ${res.status}${detail}`);
      error.status = res.status;
      error.detail = detail.replace(/^ — /, "");
      throw error;
    }
    return res.status === 204 ? null : await res.json();
  } finally {
    clearTimeout(timer);
  }
}

/* ---------- Base de connaissances ---------------------------------------- */

export function listFaq() {
  return request("/faq/");
}

/** Recherche semantique reelle (embeddings + pgvector), pas un filtre texte. */
export function searchFaq(question) {
  return request("/faq/search", { method: "POST", body: { question } });
}

/* ---------- Statistiques -------------------------------------------------- */

/** Vue d'ensemble agregee (GET /admin/stats/overview) -- comptages faits en
 *  SQL cote moteur. Ne PAS reconstituer ces totaux a partir de
 *  listComplaints() : cette route est plafonnee a 50 lignes par defaut, ce
 *  qui donnait des compteurs faux des que la base grossissait. */
export function getStatsOverview(days) {
  const query = days ? `?days=${encodeURIComponent(days)}` : "";
  return request(`/admin/stats/overview${query}`, { admin: true });
}

export function listComplaints({ status, category, limit } = {}) {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (category) params.set("category", category);
  if (limit) params.set("limit", String(limit));
  const query = params.toString();
  return request(`/admin/complaints/${query ? `?${query}` : ""}`, { admin: true });
}

export function listAuditActions() {
  return request("/audit/actions");
}

export function listCapabilities() {
  return request("/diagnostic/capabilities");
}

/** Score d'une phrase libre contre TOUT le catalogue diagnosticable (outil
 *  de debug du moteur) -- montre vers quel probleme une formulation part. */
export function debugClassifyDiagnostic(text) {
  return request("/diagnostic/debug/classify", { method: "POST", body: { text }, timeoutMs: 30000 });
}

/* ---------- Parametres ---------------------------------------------------- */

/** Surcharges enregistrees cote moteur (le catalogue et les valeurs par
 *  defaut, eux, vivent dans data/systemParameters.js). */
export function listParameterOverrides() {
  return request("/admin/settings/parameters", { admin: true });
}

export function updateParameter(paramId, value, changedBy) {
  return request(`/admin/settings/parameters/${encodeURIComponent(paramId)}`, {
    method: "PATCH",
    admin: true,
    body: { value, changed_by: changedBy },
  });
}

export function listParameterHistory() {
  return request("/admin/settings/parameters/history", { admin: true });
}

/** Purge le journal des modifications. Les valeurs courantes ne bougent pas :
 *  effacer la trace d'un reglage ne remet pas ce reglage a son defaut. */
export function clearParameterHistory() {
  return request("/admin/settings/parameters/history", { method: "DELETE", admin: true });
}

/* ---------- Conversations : file des conseillers ------------------------- */
/*  Ces routes remplacent ce que DemoStore simulait en localStorage : la file
 *  ci-dessous est celle du moteur, partagee par tous les postes conseillers
 *  (voir fastapi/app/domains/conversations/). */

export function listConversations({ status, assignedTo, escalated, unassigned, limit } = {}) {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (assignedTo) params.set("assigned_to", assignedTo);
  if (escalated !== undefined) params.set("escalated", String(escalated));
  if (unassigned !== undefined) params.set("unassigned", String(unassigned));
  if (limit) params.set("limit", String(limit));
  const query = params.toString();
  return request(`/admin/conversations/${query ? `?${query}` : ""}`, { admin: true });
}

export function getConversation(conversationId) {
  return request(`/admin/conversations/${encodeURIComponent(conversationId)}`, { admin: true });
}

/** Resume de reprise : pourquoi cette conversation arrive au conseiller, ce
 *  que le moteur a deja tente, quels tickets existent deja. */
export function getConversationContext(conversationId) {
  return request(`/admin/conversations/${encodeURIComponent(conversationId)}/context`, {
    admin: true,
  });
}

/** « Prendre en charge une demande » : a partir de cet appel, le bot ne
 *  repond plus sur cette conversation -- c'est le conseiller qui parle. */
export function assignConversation(conversationId, agentId, { force = false } = {}) {
  const suffix = force ? "?force=true" : "";
  return request(`/admin/conversations/${encodeURIComponent(conversationId)}/assign${suffix}`, {
    method: "POST",
    admin: true,
    body: { agent_id: agentId },
  });
}

/** `attachment` : { name, content_type, data_url } -- image ou PDF (4 Mo max). */
export function sendAgentMessage(conversationId, text, agentId, attachment) {
  return request(`/admin/conversations/${encodeURIComponent(conversationId)}/messages`, {
    method: "POST",
    admin: true,
    body: { text, agent_id: agentId, ...(attachment ? { attachment } : {}) },
    timeoutMs: 60000,
  });
}

export function resolveConversation(conversationId, agentId, note) {
  return request(`/admin/conversations/${encodeURIComponent(conversationId)}/resolve`, {
    method: "POST",
    admin: true,
    body: { agent_id: agentId, note },
  });
}

/* ---------- Conseillers --------------------------------------------------- */

export function listAgents() {
  return request("/admin/agents/", { admin: true });
}

export function createAgent(agentId, displayName, role) {
  return request("/admin/agents/", {
    method: "POST",
    admin: true,
    body: { agent_id: agentId, display_name: displayName, role },
  });
}

export function setAgentStatus(agentId, status) {
  return request(`/admin/agents/${encodeURIComponent(agentId)}/status`, {
    method: "PATCH",
    admin: true,
    body: { status },
  });
}

/* ---------- Reclamations : prise en charge -------------------------------- */

/** « Prendre en charge une reclamation » : attribue le ticket ET le passe en
 *  cours de traitement (un seul geste cote moteur, voir admin_router.py). */
export function assignComplaint(ticketId, agentId) {
  return request(`/admin/complaints/${encodeURIComponent(ticketId)}/assign`, {
    method: "POST",
    admin: true,
    body: { agent_id: agentId },
  });
}

export function updateComplaintStatus(ticketId, status) {
  return request(`/admin/complaints/${encodeURIComponent(ticketId)}`, {
    method: "PATCH",
    admin: true,
    body: { status },
  });
}

/* ---------- Usagers vus par le support ------------------------------------ */
/*  Aucun nom ni email : les profils appartiennent a ngoni-user-service, hors
 *  perimetre de ce depot (voir domains/users/service.py). */

export function listSupportUsers(limit) {
  return request(`/admin/users/${limit ? `?limit=${limit}` : ""}`, { admin: true });
}

export function getSupportUser(userId) {
  return request(`/admin/users/${encodeURIComponent(userId)}`, { admin: true });
}

/* ---------- Tableau de bord ---------------------------------------------- */

export function getDashboardSummary(days) {
  return request(`/admin/dashboard/summary${days ? `?days=${days}` : ""}`, { admin: true });
}

export function getConversationVolume(days) {
  return request(`/admin/dashboard/conversation-volume${days ? `?days=${days}` : ""}`, {
    admin: true,
  });
}

/** Repartition REELLE des intentions, mesuree sur les messages classes par le
 *  moteur au moment ou il a repondu (plus aucun pourcentage d'illustration). */
export function getIntentDistribution(days) {
  return request(`/admin/dashboard/intent-distribution${days ? `?days=${days}` : ""}`, {
    admin: true,
  });
}

export function getRecentActivity(limit) {
  return request(`/admin/dashboard/recent-activity${limit ? `?limit=${limit}` : ""}`, {
    admin: true,
  });
}

export function getDiagnosticRuns(days) {
  return request(`/admin/diagnostics/runs${days ? `?days=${days}` : ""}`, { admin: true });
}

/** Bilan par probleme diagnosticable : issues et causes les plus frequentes. */
export function getDiagnosticProblems(days) {
  return request(`/admin/diagnostics/problems${days ? `?days=${days}` : ""}`, { admin: true });
}

export function listDiagnosticSessions({ days, status, service, problem, limit, offset } = {}) {
  const params = new URLSearchParams();
  if (days) params.set("days", String(days));
  if (status) params.set("status", status);
  if (service) params.set("service", service);
  if (problem) params.set("problem", problem);
  if (limit) params.set("limit", String(limit));
  if (offset) params.set("offset", String(offset));
  const query = params.toString();
  return request(`/admin/diagnostics/sessions${query ? `?${query}` : ""}`, { admin: true });
}

export function getDiagnosticSession(sessionId) {
  return request(`/admin/diagnostics/sessions/${encodeURIComponent(sessionId)}`, { admin: true });
}

/** Sonde reelle de chaque dependance (base, Rasa, microservices du registre)
 *  -- remplace la liste codee en dur qui affichait "operational" en toutes
 *  circonstances, y compris pendant une panne. */
export function getSystemHealth() {
  return request("/admin/system/health", { admin: true });
}

/* ---------- Cote client (non-admin) --------------------------------------- */

/** Demande explicite d'un conseiller humain, depuis l'interface de chat. Ne
 *  coupe pas l'assistant : tant que personne n'a pris la conversation, il
 *  continue de repondre. */
export function requestHumanAgent(conversationId, reason) {
  return request("/conversations/escalate", {
    method: "POST",
    body: { conversation_id: conversationId, reason },
  });
}

/** Journalise un tour de dialogue quand le client a interroge Rasa
 *  directement (cas de cette interface, voir rasaClient.js) : sans cela, le
 *  conseiller qui reprend la conversation n'aurait aucun historique a lire,
 *  le tracker interne de Rasa n'etant expose par aucune API. Renvoie l'etat
 *  de prise en charge -- `handoff: true` signifie "cesse d'interroger Rasa,
 *  un humain repond desormais". */
export function recordConversationTurn(conversationId, { userText, intent, confidence, botMessages, userId }) {
  return request("/conversations/turns", {
    method: "POST",
    body: {
      conversation_id: conversationId,
      // Identite stable (voir stableUserId, chatService.js) : c'est elle qui
      // relie les conversations successives d'un meme utilisateur, base de
      // GET /conversations/memory.
      user_id: userId ?? null,
      user_text: userText,
      intent: intent ?? null,
      confidence: confidence ?? null,
      bot_messages: (botMessages ?? []).map((message) => ({
        text: message.text,
        metadata: message.buttons ? { buttons: message.buttons } : {},
      })),
    },
  });
}

/** Page « Historique » : conversations passees de ce compte. */
export function listMyConversations(userId) {
  return request("/conversations/mine", { userId });
}

export function getMyConversation(userId, conversationId) {
  return request(`/conversations/mine/${encodeURIComponent(conversationId)}`, { userId });
}

/** Reclamations du compte, toutes conversations confondues (page « Profil »). */
export function listMyTickets(userId) {
  return request("/conversations/mine/tickets", { userId });
}

/** Verification d'une piece jointe : format, puis OCR, puis filtre -- seules
 *  une carte nationale d'identite ou un passeport passent a l'extraction.
 *  `dataUrl` : le fichier tel que lu par FileReader.readAsDataURL. L'OCR
 *  prend quelques secondes, d'ou un delai plus long que les autres appels. */
export function analyzeIdentityDocument({ name, type, dataUrl, userId, conversationId }) {
  // userId : la piece est alors enregistree pour le conseiller qui devra la
  // valider (sans lui -- demonstration rejouee -- rien n'est conserve).
  return request("/identity-documents/analyze", {
    method: "POST",
    body: { filename: name, content_type: type, data_base64: dataUrl, conversation_id: conversationId ?? null },
    userId,
    timeoutMs: 60000,
  });
}

/** Pieces envoyees par ce compte et leur examen (notifications du client). */
export function listMyDocuments(userId) {
  return request("/identity-documents/mine", { userId });
}

/* ---------- Dossier client (conseiller humain) ---------------------------- */

/** `agentId` renseigne : la consultation est tracee au journal. */
export function getCustomerFile(userId, { agentId, conversationId } = {}) {
  const params = new URLSearchParams();
  if (agentId) params.set("agent_id", agentId);
  if (conversationId) params.set("conversation_id", conversationId);
  const query = params.toString();
  return request(`/admin/support/users/${encodeURIComponent(userId)}${query ? `?${query}` : ""}`, { admin: true });
}

/** Pieces d'identite en attente d'examen (file « a verifier »). */
export function listPendingDocuments() {
  return request("/admin/support/documents?status=pending", { admin: true });
}

export function decideIdentity(userId, { agentId, decision, reason, documentId, conversationId }) {
  return request(`/admin/support/users/${encodeURIComponent(userId)}/identity-decision`, {
    method: "POST",
    admin: true,
    body: {
      agent_id: agentId,
      decision,
      reason: reason || null,
      document_id: documentId || null,
      conversation_id: conversationId || null,
    },
  });
}

export function addCustomerNote(userId, { agentId, text, conversationId }) {
  return request(`/admin/support/users/${encodeURIComponent(userId)}/notes`, {
    method: "POST",
    admin: true,
    body: { agent_id: agentId, text, conversation_id: conversationId || null },
  });
}

/** Image d'une piece : route protegee par le secret, donc pas d'<img src>
 *  direct -- on la telecharge puis on en fait une URL locale (a liberer avec
 *  URL.revokeObjectURL). */
export async function fetchDocumentImage(documentId) {
  const res = await fetch(`${BASE}/admin/support/documents/${encodeURIComponent(documentId)}/image`, {
    headers: authHeader(),
  });
  if (!res.ok) throw new Error(`image ${documentId} → ${res.status}`);
  return URL.createObjectURL(await res.blob());
}

/** Rattrapage des messages ecrits hors du flux de reponse normal (reponse
 *  d'un conseiller, notamment) -- `since` est le `checked_at` renvoye par
 *  l'appel precedent. */
export function fetchConversationUpdates(conversationId, since) {
  const query = since ? `?after=${encodeURIComponent(since)}` : "";
  return request(`/conversations/${encodeURIComponent(conversationId)}/updates${query}`);
}
