/**
 * Espace Admin → Conversations et Escalades (même page, deux modes).
 *
 * Supervision en lecture : toutes les conversations journalisées par le
 * moteur (`GET /admin/conversations`), ou seulement celles qui ont été
 * escaladées vers un conseiller (`escalated=true`). Le traitement lui-même
 * (prise en charge, réponse, clôture) reste dans l'espace conseiller, vers
 * lequel chaque fiche renvoie -- l'administration supervise, elle ne répond
 * pas à la place du conseiller.
 */

import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AdminShell } from "../components/layout/AdminShell";
import { Icon } from "../components/ui/Icon";
import {
  Badge,
  CONVERSATION_STATUS,
  LoadState,
  Select,
  Toolbar,
  dateLabel,
  relativeLabel,
} from "../components/admin/adminUi";
import { getConversation, getConversationContext, listConversations } from "../services/engineClient";

const POLL_INTERVAL_MS = 10000;

const STATUS_OPTIONS = [
  ["", "Tous les statuts"],
  ["BOT", "Assistant"],
  ["ESCALADE_DEMANDEE", "En attente"],
  ["PRISE_EN_CHARGE", "Prise en charge"],
  ["RESOLUE", "Résolue"],
];

const SENDER = { user: "Usager", bot: "Assistant", agent: "Conseiller" };

export function AdminConversationsPage({ mode = "all" }) {
  const escalatedOnly = mode === "escalated";
  const navigate = useNavigate();
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [status, setStatus] = useState("");
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [context, setContext] = useState(null);

  const refresh = useCallback(() => {
    listConversations({ status: status || undefined, escalated: escalatedOnly ? true : undefined, limit: 200 })
      .then((data) => {
        setRows(data);
        setError(null);
      })
      .catch((err) => {
        console.error("[AdminConversationsPage]", err);
        setError("Moteur injoignable — la liste ne peut pas être affichée.");
      });
  }, [status, escalatedOnly]);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    if (!selectedId) return undefined;
    let cancelled = false;
    setDetail(null);
    setContext(null);
    Promise.all([getConversation(selectedId), getConversationContext(selectedId)])
      .then(([conversation, conversationContext]) => {
        if (cancelled) return;
        setDetail(conversation);
        setContext(conversationContext);
      })
      .catch((err) => console.error("[AdminConversationsPage] détail :", err));
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  const waiting = (rows ?? []).filter((row) => row.status === "ESCALADE_DEMANDEE").length;
  const inProgress = (rows ?? []).filter((row) => row.status === "PRISE_EN_CHARGE").length;

  return (
    <AdminShell
      active={escalatedOnly ? "escalades" : "conversations"}
      title={escalatedOnly ? "Escalades" : "Conversations"}
      subtitle={
        escalatedOnly
          ? "Conversations transmises à un conseiller humain"
          : "Toutes les conversations journalisées par le moteur"
      }
    >
      <Toolbar>
        <Select label="Statut" value={status} onChange={setStatus} options={STATUS_OPTIONS} />
        {rows && (
          <span style={{ fontSize: "0.82rem", color: "var(--ink-muted)" }}>
            {rows.length} conversation{rows.length > 1 ? "s" : ""} · {waiting} en attente · {inProgress} prise
            {inProgress > 1 ? "s" : ""} en charge
          </span>
        )}
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          style={{ marginLeft: "auto" }}
          onClick={() => navigate(`/agent/live${escalatedOnly ? "" : "?vue=toutes"}`)}
        >
          <Icon name="headset" size={14} /> Ouvrir l'espace conseiller
        </button>
      </Toolbar>

      <LoadState
        error={error}
        loading={!error && rows === null}
        empty={rows?.length === 0}
        emptyText={escalatedOnly ? "Aucune escalade enregistrée." : "Aucune conversation enregistrée."}
      />

      {rows?.length > 0 && (
        <div className="admin-two-col">
          <div className="card card-pad">
            <div className="tickets-table-wrap">
              <table className="tickets-table">
                <thead>
                  <tr>
                    <th>Conversation</th>
                    <th>Statut</th>
                    <th>{escalatedOnly ? "Motif" : "Intention"}</th>
                    <th>Conseiller</th>
                    <th>Activité</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr
                      key={row.conversation_id}
                      onClick={() => setSelectedId(row.conversation_id)}
                      style={{
                        cursor: "pointer",
                        background: row.conversation_id === selectedId ? "var(--surface-2)" : undefined,
                      }}
                    >
                      <td>
                        <div style={{ fontWeight: 600 }}>{row.conversation_id}</div>
                        <div style={{ fontSize: "0.76rem", color: "var(--ink-faint)" }}>
                          {row.user_id ?? "usager anonyme"} · {row.message_count} msg
                        </div>
                      </td>
                      <td>
                        <Badge map={CONVERSATION_STATUS} value={row.status} />
                      </td>
                      <td style={{ fontSize: "0.82rem" }}>
                        {escalatedOnly ? row.escalation_reason ?? "—" : row.last_intent ?? "—"}
                      </td>
                      <td style={{ fontSize: "0.82rem" }}>{row.assigned_to ?? "—"}</td>
                      <td className="ticket-date">
                        {relativeLabel(escalatedOnly ? row.escalated_at ?? row.last_message_at : row.last_message_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="card card-pad" style={{ display: "grid", gap: 14 }}>
            {!selectedId ? (
              <p className="empty-hint">Sélectionnez une conversation pour lire le fil et son dossier.</p>
            ) : !detail ? (
              <p className="empty-hint">Chargement…</p>
            ) : (
              <>
                <div className="section-head">
                  <h3>#{detail.conversation_id}</h3>
                  <Badge map={CONVERSATION_STATUS} value={detail.status} />
                </div>
                <div style={{ fontSize: "0.82rem", color: "var(--ink-muted)" }}>
                  Usager {detail.user_id ?? "anonyme"} · ouverte le {dateLabel(detail.created_at)}
                  {detail.ticket_id ? ` · ticket ${detail.ticket_id}` : ""}
                  {detail.escalation_reason ? ` · escalade : ${detail.escalation_reason}` : ""}
                </div>

                {context?.diagnostic && (
                  <div className="badge badge-info" style={{ display: "block", lineHeight: 1.5 }}>
                    Diagnostic : {context.diagnostic.service} / {context.diagnostic.problem} —{" "}
                    {context.diagnostic.status}
                  </div>
                )}

                <div style={{ display: "grid", gap: 8, maxHeight: 420, overflowY: "auto" }}>
                  {detail.messages.map((message) => (
                    <div key={message.id} style={{ fontSize: "0.84rem", lineHeight: 1.45 }}>
                      <span style={{ fontWeight: 700 }}>
                        {message.sender_role === "agent" ? message.agent_id ?? SENDER.agent : SENDER[message.sender_role]}
                      </span>
                      <span style={{ color: "var(--ink-faint)" }}> · {dateLabel(message.created_at)}</span>
                      {message.intent && <span className="badge badge-neutral" style={{ marginLeft: 6 }}>{message.intent}</span>}
                      <div style={{ whiteSpace: "pre-wrap", marginTop: 2 }}>{message.text}</div>
                    </div>
                  ))}
                </div>

                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  onClick={() => {
                    const vue = detail.status === "ESCALADE_DEMANDEE" ? "attente" : "toutes";
                    navigate(`/agent/live?vue=${vue}&id=${encodeURIComponent(detail.conversation_id)}`);
                  }}
                >
                  <Icon name="forward" size={14} /> Traiter dans l'espace conseiller
                </button>
              </>
            )}
          </div>
        </div>
      )}
    </AdminShell>
  );
}
