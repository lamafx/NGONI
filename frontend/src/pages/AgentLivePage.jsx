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
import { Sidebar } from "../components/layout/Sidebar";
import { Avatar } from "../components/ui/Avatar";
import { Icon } from "../components/ui/Icon";
import { MessageBubble } from "../components/chat/MessageBubble";
import {
  assignConversation,
  getConversation,
  getConversationContext,
  listAgents,
  listConversations,
  resolveConversation,
  sendAgentMessage,
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
  const [conversations, setConversations] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [context, setContext] = useState(null);
  const [agents, setAgents] = useState([]);
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);
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

  useEffect(() => {
    refreshQueue();
    listAgents()
      .then(setAgents)
      .catch((err) => console.error("[AgentLivePage] conseillers :", err));
    const timer = setInterval(refreshQueue, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [refreshQueue]);

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
          { icon: "message", label: "Conversations", count: conversations.length },
          { icon: "clock", label: "En attente", count: waiting.length, active: true },
          { icon: "folder", label: "Mes dossiers", count: mine.length },
          { icon: "users", label: "Conseillers en ligne", count: onlineAgents.length },
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
            <div style={{ fontWeight: 700, fontSize: "0.92rem" }}>File d'attente</div>
            <div style={{ fontSize: "0.78rem", color: "var(--ink-faint)", marginTop: 2 }}>
              {waiting.length} en attente · {mine.length} à moi
            </div>
          </div>

          {error && (
            <div className="badge badge-risk" style={{ margin: 12, display: "block", lineHeight: 1.4 }}>
              {error}
            </div>
          )}

          {conversations.length === 0 && !error && (
            <div style={{ padding: 16, fontSize: "0.82rem", color: "var(--ink-faint)" }}>
              Aucune conversation enregistrée pour l'instant. Écrivez un message depuis l'espace
              client : il apparaîtra ici.
            </div>
          )}

          {conversations.map((row) => (
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
    </div>
  );
}
