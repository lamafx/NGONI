/**
 * Poste de travail du conseiller, branché sur le MOTEUR -- à ne pas
 * confondre avec AgentPage.jsx, qui rejoue le scénario filmé de la
 * démonstration depuis DemoStore/localStorage et reste inchangé.
 *
 * Ici, rien n'est simulé : la file vient de `GET /admin/conversations`, la
 * prise en charge écrit réellement en base (le bot cesse alors de répondre
 * à cet usager, voir domains/conversations/service.py), et la réponse du
 * conseiller arrive chez le client par sa propre boucle de rattrapage.
 *
 * La liste est rafraîchie périodiquement (POLL_INTERVAL_MS) faute
 * d'infrastructure temps réel côté moteur -- choix assumé et documenté dans
 * domains/conversations/router.py.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Sidebar } from "../components/layout/Sidebar";
import { Avatar } from "../components/ui/Avatar";
import { Icon } from "../components/ui/Icon";
import { MessageBubble } from "../components/chat/MessageBubble";
import { CustomerFile } from "../components/agent/CustomerFile";
import { NotificationBell } from "../components/ui/NotificationBell";
import { useNotifications } from "../hooks/useNotifications";
import { loadAgentNotifications } from "../services/notificationSources";
import {
  assignConversation,
  getConversation,
  getConversationContext,
  listAgents,
  listConversations,
  resolveConversation,
  sendAgentMessage,
  setAgentStatus,
} from "../services/engineClient";

const POLL_INTERVAL_MS = 5000;

// Identifiant du conseiller connecté. Constante tant qu'aucune
// authentification n'existe côté moteur (voir api_admin_a_developper.md §1 :
// pas de session, pas de rôle, pas d'identité vérifiée) -- surchargeable par
// variable d'environnement pour qu'un second poste de démonstration puisse
// se présenter sous un autre nom sans modifier le code.
const ACTING_AGENT_ID = import.meta.env.VITE_AGENT_ID || "conseiller-1";

const STATUS_LABELS = {
  BOT: { label: "Assistant", tone: "badge-neutral" },
  ESCALADE_DEMANDEE: { label: "En attente", tone: "badge-warn" },
  PRISE_EN_CHARGE: { label: "Prise en charge", tone: "badge-brand" },
  RESOLUE: { label: "Résolue", tone: "badge-good" },
};

// Vues de la barre laterale -- aussi lisibles dans l'URL (#/agent/live?vue=attente),
// pour que l'espace Admin puisse ouvrir directement la bonne file.
const VIEWS = {
  toutes: "Toutes les conversations",
  attente: "En attente d'un conseiller",
  mes: "Mes dossiers",
  conseillers: "Conseillers",
};

const AGENT_STATUS = {
  online: { label: "En ligne", tone: "badge-good" },
  away: { label: "Absent", tone: "badge-warn" },
  offline: { label: "Hors ligne", tone: "badge-neutral" },
};

function StatusBadge({ status }) {
  const tone = STATUS_LABELS[status] ?? { label: status, tone: "badge-neutral" };
  return (
    <span className={`badge ${tone.tone}`}>
      <span className="badge-dot" />
      {tone.label}
    </span>
  );
}

function timeLabel(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
}

function relativeLabel(iso) {
  if (!iso) return "—";
  const elapsedMs = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(elapsedMs)) return "—";
  const minutes = Math.floor(elapsedMs / 60000);
  if (minutes < 1) return "à l'instant";
  if (minutes < 60) return `il y a ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `il y a ${hours} h`;
  return `il y a ${Math.floor(hours / 24)} j`;
}

/** Les rôles du moteur (user/bot/agent) vers ceux de MessageBubble. */
function toBubble(message) {
  return {
    id: message.id,
    sender: message.sender_role === "bot" ? "ai" : message.sender_role,
    senderName: message.agent_id ?? undefined,
    text: message.text,
    time: timeLabel(message.created_at),
  };
}

export function AgentLivePage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const view = VIEWS[searchParams.get("vue")] ? searchParams.get("vue") : "attente";
  const setView = (next) => setSearchParams(next === "attente" ? {} : { vue: next }, { replace: true });
  const [conversations, setConversations] = useState([]);
  // Nouvelles escalades en attente et messages d'usagers dans mes dossiers.
  const notifications = useNotifications({
    scope: `agent:${ACTING_AGENT_ID}`,
    load: () => loadAgentNotifications(ACTING_AGENT_ID),
    intervalMs: 10000,
  });
  // ?id= : conversation ouverte depuis l'espace Admin.
  const [activeId, setActiveId] = useState(() => searchParams.get("id"));
  const [detail, setDetail] = useState(null);
  const [context, setContext] = useState(null);
  const [agents, setAgents] = useState([]);
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);
  // Conversation dont le dossier client est ouvert (null = ferme). Par
  // conversation et non par compte : le dossier s'ouvre une fois le detail
  // charge, y compris depuis une notification « piece a verifier ».
  const [fileFor, setFileFor] = useState(null);
  const [error, setError] = useState(null);
  const threadEndRef = useRef(null);
  const activeIdRef = useRef(null);

  activeIdRef.current = activeId;

  const refreshQueue = useCallback(async () => {
    try {
      const rows = await listConversations({ limit: 100 });
      setConversations(rows);
      setError(null);
      if (!activeIdRef.current && rows.length) {
        // Priorité à ce qui attend réellement quelqu'un.
        const waiting = rows.find((row) => row.status === "ESCALADE_DEMANDEE");
        setActiveId((waiting ?? rows[0]).conversation_id);
      }
    } catch (err) {
      setError(
        "Moteur injoignable (:8000). Vérifiez qu'il tourne et que VITE_ADMIN_SECRET correspond à ADMIN_INTERNAL_SECRET."
      );
      console.error("[AgentLivePage] file des conversations :", err);
    }
  }, []);

  const refreshActive = useCallback(async (conversationId) => {
    if (!conversationId) return;
    try {
      const [conversation, conversationContext] = await Promise.all([
        getConversation(conversationId),
        getConversationContext(conversationId),
      ]);
      // La réponse d'une requête lancée avant un changement de sélection ne
      // doit jamais écraser la conversation désormais affichée.
      if (activeIdRef.current !== conversationId) return;
      setDetail(conversation);
      setContext(conversationContext);
    } catch (err) {
      console.error("[AgentLivePage] détail de la conversation :", err);
    }
  }, []);

  const refreshAgents = useCallback(
    () =>
      listAgents()
        .then(setAgents)
        .catch((err) => console.error("[AgentLivePage] conseillers :", err)),
    []
  );

  useEffect(() => {
    refreshQueue();
    refreshAgents();
    const timer = setInterval(() => {
      refreshQueue();
      refreshAgents();
    }, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [refreshQueue, refreshAgents]);

  useEffect(() => {
    refreshActive(activeId);
    const timer = setInterval(() => refreshActive(activeIdRef.current), POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [activeId, refreshActive]);

  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [detail?.messages?.length]);

  const waiting = conversations.filter((row) => row.status === "ESCALADE_DEMANDEE");
  const mine = conversations.filter(
    (row) => row.status === "PRISE_EN_CHARGE" && row.assigned_to === ACTING_AGENT_ID
  );
  const isMine = detail?.status === "PRISE_EN_CHARGE" && detail?.assigned_to === ACTING_AGENT_ID;
  const heldBySomeoneElse =
    detail?.status === "PRISE_EN_CHARGE" && detail?.assigned_to !== ACTING_AGENT_ID;

  async function run(action) {
    setBusy(true);
    try {
      await action();
      await Promise.all([refreshQueue(), refreshActive(activeIdRef.current)]);
      setError(null);
    } catch (err) {
      setError(err.message ?? String(err));
      console.error("[AgentLivePage] action :", err);
    } finally {
      setBusy(false);
    }
  }

  function takeOver(force = false) {
    return run(() => assignConversation(activeIdRef.current, ACTING_AGENT_ID, { force }));
  }

  function submitReply() {
    const text = reply.trim();
    if (!text) return;
    setReply("");
    return run(() => sendAgentMessage(activeIdRef.current, text, ACTING_AGENT_ID));
  }

  function closeConversation() {
    return run(() => resolveConversation(activeIdRef.current, ACTING_AGENT_ID));
  }

  const onlineAgents = agents.filter((agent) => agent.status !== "offline");
  const me = agents.find((agent) => agent.agent_id === ACTING_AGENT_ID);

  // La liste affichee suit la vue choisie dans la barre laterale.
  const listed =
    view === "attente"
      ? waiting
      : view === "mes"
        ? mine
        : conversations;

  function changeMyStatus(status) {
    setAgentStatus(ACTING_AGENT_ID, status)
      .then(refreshAgents)
      .catch((err) => {
        console.error("[AgentLivePage] statut :", err);
        setError("Impossible de changer votre statut (conseiller inconnu du moteur ?).");
      });
  }

  return (
    <div className="app-shell">
      <Sidebar
        brand={
          <>
            <Avatar kind="agent" size={30} />
            <span>Espace Agent</span>
          </>
        }
        items={[
          { icon: "message", label: "Conversations", count: conversations.length, active: view === "toutes", onClick: () => setView("toutes") },
          { icon: "clock", label: "En attente", count: waiting.length, active: view === "attente", onClick: () => setView("attente") },
          { icon: "folder", label: "Mes dossiers", count: mine.length, active: view === "mes", onClick: () => setView("mes") },
          { icon: "users", label: "Conseillers en ligne", count: onlineAgents.length, active: view === "conseillers", onClick: () => setView("conseillers") },
          { icon: "grid", label: "Administration", onClick: () => navigate("/admin") },
        ]}
        footer={
          <div className="sidebar-user">
            <Avatar kind="agent" name={ACTING_AGENT_ID} size={32} />
            <div className="who">
              <div className="name">{ACTING_AGENT_ID}</div>
              <div className="role">conseiller</div>
            </div>
          </div>
        }
      />

      <div className="agent-shell">
        <div className="agent-list">
          <div className="agent-list-header">
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
              <div style={{ fontWeight: 700, fontSize: "0.92rem" }}>{VIEWS[view]}</div>
              <NotificationBell
                notifications={notifications}
                buttonClassName="btn btn-ghost btn-icon btn-sm admin-notif-btn"
                align="left"
                emptyText="Aucun usager en attente, aucun nouveau message dans vos dossiers."
                onSelect={(item) => {
                  if (item.action?.view) setView(item.action.view);
                  if (item.action?.conversationId) setActiveId(item.action.conversationId);
                  if (item.action?.openFile) setFileFor(item.action.conversationId);
                }}
              />
            </div>
            <div style={{ fontSize: "0.78rem", color: "var(--ink-faint)", marginTop: 2 }}>
              {view === "conseillers"
                ? `${onlineAgents.length} en ligne sur ${agents.length}`
                : `${waiting.length} en attente · ${mine.length} à moi`}
            </div>
          </div>

          {error && (
            <div className="badge badge-risk" style={{ margin: 12, display: "block", lineHeight: 1.4 }}>
              {error}
            </div>
          )}

          {view === "conseillers" && (
            <div style={{ display: "grid", gap: 8, padding: 12 }}>
              {me && (
                <div className="card card-pad" style={{ display: "grid", gap: 8 }}>
                  <div style={{ fontSize: "0.8rem", fontWeight: 700 }}>Mon statut</div>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    {Object.entries(AGENT_STATUS).map(([status, meta]) => (
                      <button
                        key={status}
                        type="button"
                        className={`btn btn-sm ${me.declared_status === status ? "btn-primary" : "btn-secondary"}`}
                        onClick={() => changeMyStatus(status)}
                      >
                        {meta.label}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {agents.length === 0 && (
                <div style={{ fontSize: "0.82rem", color: "var(--ink-faint)" }}>Aucun conseiller enregistré.</div>
              )}
              {agents.map((agent) => {
                const meta = AGENT_STATUS[agent.status] ?? AGENT_STATUS.offline;
                return (
                  <div key={agent.agent_id} className="agent-conv-item" style={{ cursor: "default" }}>
                    <div className="row1">
                      <span className="conv-id">
                        {agent.display_name}
                        {agent.agent_id === ACTING_AGENT_ID ? " (vous)" : ""}
                      </span>
                      <span className={`badge ${meta.tone}`}>
                        <span className="badge-dot" />
                        {meta.label}
                      </span>
                    </div>
                    <div className="conv-user">
                      {agent.role} · {agent.active_conversations} conversation
                      {agent.active_conversations > 1 ? "s" : ""} · {agent.assigned_tickets} ticket
                      {agent.assigned_tickets > 1 ? "s" : ""} · vu {relativeLabel(agent.last_seen_at)}
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {view !== "conseillers" && listed.length === 0 && !error && (
            <div style={{ padding: 16, fontSize: "0.82rem", color: "var(--ink-faint)" }}>
              {view === "attente"
                ? "Personne n'attend de conseiller pour l'instant."
                : view === "mes"
                  ? "Vous n'avez aucun dossier en cours. Prenez une conversation en charge depuis « En attente »."
                  : "Aucune conversation enregistrée pour l'instant. Écrivez un message depuis l'espace client : il apparaîtra ici."}
            </div>
          )}

          {view !== "conseillers" && listed.map((row) => (
            <div
              key={row.conversation_id}
              className={`agent-conv-item ${row.conversation_id === activeId ? "active" : ""}`}
              onClick={() => setActiveId(row.conversation_id)}
            >
              <div className="row1">
                <span className="conv-id">#{row.conversation_id}</span>
                <StatusBadge status={row.status} />
              </div>
              <div className="conv-subject">{row.last_message ?? "—"}</div>
              <div className="conv-user">
                {row.last_intent ?? "intention inconnue"} · {relativeLabel(row.last_message_at)}
                {row.assigned_to ? ` · ${row.assigned_to}` : ""}
              </div>
            </div>
          ))}
        </div>

        <div className="agent-thread-col">
          <div className="agent-thread-header">
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 12,
              }}
            >
              <div>
                <div style={{ fontWeight: 700, fontSize: "0.98rem" }}>
                  {detail ? `#${detail.conversation_id}` : "Aucune conversation sélectionnée"}
                </div>
                <div style={{ fontSize: "0.8rem", color: "var(--ink-muted)", marginTop: 2 }}>
                  {detail?.user_id ? `Usager ${detail.user_id}` : "Usager non identifié"}
                  {detail?.ticket_id ? ` · Ticket ${detail.ticket_id}` : ""}
                </div>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                {detail?.user_id && (
                  <button
                    className="btn btn-secondary btn-sm"
                    type="button"
                    onClick={() => setFileFor(detail.conversation_id)}
                    title="Compte, pièce d'identité, portefeuille et historique de l'usager"
                  >
                    <Icon name="id-card" size={14} /> Dossier client
                  </button>
                )}
                {detail && !isMine && (
                  <button
                    className="btn btn-primary btn-sm"
                    type="button"
                    disabled={busy}
                    onClick={() => takeOver(heldBySomeoneElse)}
                  >
                    <Icon name="users" size={14} />{" "}
                    {heldBySomeoneElse ? "Reprendre à " + detail.assigned_to : "Prendre en charge"}
                  </button>
                )}
                {isMine && (
                  <button
                    className="btn btn-secondary btn-sm"
                    type="button"
                    disabled={busy}
                    onClick={closeConversation}
                  >
                    <Icon name="check" size={14} /> Clore
                  </button>
                )}
                {detail && <StatusBadge status={detail.status} />}
              </div>
            </div>
            {detail?.escalation_reason && (
              <div style={{ marginTop: 10 }}>
                <span className="badge badge-warn">Escalade : {detail.escalation_reason}</span>
              </div>
            )}
          </div>

          <div className="agent-thread-body">
            <div className="agent-thread-messages">
              {(detail?.messages ?? []).map((message) => (
                <MessageBubble
                  key={message.id}
                  message={toBubble(message)}
                  agentName={message.agent_id ?? "Conseiller"}
                  interactive={false}
                />
              ))}
              <div ref={threadEndRef} />
            </div>

            <div className={`agent-reply-zone${isMine ? "" : " is-locked"}`}>
              <div className="agent-reply-field">
                <textarea
                  className="agent-reply-input"
                  rows={3}
                  spellCheck={false}
                  placeholder={
                    isMine
                      ? "Écrivez votre réponse au client…"
                      : "Prenez la conversation en charge pour pouvoir répondre."
                  }
                  value={reply}
                  disabled={!isMine || busy}
                  onChange={(event) => setReply(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      submitReply();
                    }
                  }}
                />
              </div>
              <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 8 }}>
                <button
                  className="btn btn-primary btn-sm"
                  type="button"
                  disabled={!isMine || busy || !reply.trim()}
                  onClick={submitReply}
                >
                  <Icon name="send" size={14} /> Envoyer
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Meme colonne que l'espace Agent de la demonstration
            (.agent-context), mais son contenu est ici reconstitue depuis les
            traces reelles du moteur -- jamais un resume redige d'avance. */}
        <div className="agent-context">
          <div>
            <h3>Dossier</h3>
            <div style={{ fontSize: "0.78rem", color: "var(--ink-faint)" }}>
              Reconstitué depuis les traces réelles du moteur
            </div>
          </div>

          {!context && (
            <div style={{ fontSize: "0.82rem", color: "var(--ink-faint)" }}>
              Sélectionnez une conversation.
            </div>
          )}

          {context && (
            <div style={{ display: "grid", gap: 14 }}>
              <div>
                <h3>Intentions détectées</h3>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
                  {context.intents_seen.length ? (
                    context.intents_seen.map((intent) => (
                      <span key={intent} className="badge badge-neutral">
                        {intent}
                      </span>
                    ))
                  ) : (
                    <span style={{ fontSize: "0.82rem", color: "var(--ink-faint)" }}>—</span>
                  )}
                </div>
              </div>

              <div>
                <h3>Échanges</h3>
                <div style={{ fontSize: "0.84rem", marginTop: 4 }}>
                  {context.user_messages} usager · {context.bot_messages} assistant ·{" "}
                  {context.agent_messages} conseiller
                </div>
              </div>

              {context.diagnostic && (
                <div>
                  <h3>Diagnostic automatique</h3>
                  <div style={{ fontSize: "0.84rem", marginTop: 4 }}>
                    {context.diagnostic.service} / {context.diagnostic.problem} —{" "}
                    {context.diagnostic.status} ({context.diagnostic.turns_count} tour
                    {context.diagnostic.turns_count > 1 ? "s" : ""})
                  </div>
                </div>
              )}

              {context.tickets.length > 0 && (
                <div>
                  <h3>Tickets liés</h3>
                  <div style={{ display: "grid", gap: 6, marginTop: 6 }}>
                    {context.tickets.map((ticket) => (
                      <div key={ticket.ticket_id} style={{ fontSize: "0.82rem" }}>
                        <strong>{ticket.ticket_id}</strong> · {ticket.category} · {ticket.status}
                        {ticket.assigned_to ? ` · ${ticket.assigned_to}` : ""}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div>
                <h3>Chronologie</h3>
                <div style={{ display: "grid", gap: 8, marginTop: 6 }}>
                  {context.timeline.map((entry, index) => (
                    <div key={`${entry.kind}-${index}`} style={{ fontSize: "0.82rem" }}>
                      <span style={{ color: "var(--ink-faint)" }}>{timeLabel(entry.at)}</span>{" "}
                      {entry.label}
                      {entry.detail ? (
                        <span style={{ color: "var(--ink-muted)" }}> — {entry.detail}</span>
                      ) : null}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {detail && fileFor === detail.conversation_id && detail.user_id && (
        <CustomerFile
          userId={detail.user_id}
          conversationId={detail.conversation_id}
          agentId={ACTING_AGENT_ID}
          onClose={() => setFileFor(null)}
          onDecided={(decision, reason) =>
            // Reponse proposee au client -- le conseiller la relit et l'envoie
            // lui-meme (rien ne part sans lui).
            setReply(
              decision === "approved"
                ? "Bonne nouvelle : votre pièce d'identité est validée, votre compte est maintenant vérifié. Vous pouvez de nouveau recevoir des cadeaux sur vos lives."
                : `Votre pièce d'identité n'a pas pu être validée (${reason}). Pouvez-vous en envoyer une nouvelle photo, nette et en entier ?`
            )
          }
        />
      )}
    </div>
  );
}
