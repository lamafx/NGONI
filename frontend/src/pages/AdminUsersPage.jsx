/**
 * Espace Admin → Utilisateurs. L'entrée de navigation existait déjà mais
 * n'ouvrait rien.
 *
 * Ce que cette page montre, et ce qu'elle ne montre pas : les usagers **vus
 * par le support** (identifiant de contact, volume d'échanges, tickets,
 * dernière activité), lus depuis `GET /admin/users`. Ni nom, ni email, ni
 * donnée de profil : ces informations appartiennent à `ngoni-user-service`
 * (hors périmètre de ce dépôt, voir `docs/03-taxonomie.md`) et ce dépôt ne
 * les invente pas.
 */

import { useEffect, useState } from "react";
import { AdminShell } from "../components/layout/AdminShell";
import { Avatar } from "../components/ui/Avatar";
import { Icon } from "../components/ui/Icon";
import { getSupportUser, listSupportUsers } from "../services/engineClient";

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

export function AdminUsersPage() {
  const [users, setUsers] = useState(null);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    listSupportUsers()
      .then(setUsers)
      .catch((err) => {
        console.error("[AdminUsersPage] usagers :", err);
        setError("Moteur injoignable — la liste des usagers ne peut pas être affichée.");
      });
  }, []);

  function openUser(userId) {
    setSelected({ user_id: userId, loading: true });
    getSupportUser(userId)
      .then((detail) => setSelected(detail))
      .catch((err) => {
        console.error("[AdminUsersPage] détail usager :", err);
        setSelected(null);
      });
  }

  return (
    <AdminShell
      active="utilisateurs"
      title="Utilisateurs"
      subtitle="Les usagers ayant contacté le support, tels que le moteur les connaît"
    >
      {error && (
        <span className="status-line">
          <span className="status-dot" style={{ background: "var(--risk)" }} /> {error}
        </span>
      )}

      {!error && users === null && (
        <span className="status-line">
          <span className="status-dot online" /> Chargement…
        </span>
      )}

      {users?.length === 0 && (
        <p className="empty-hint">
          Aucun usager n'a encore contacté le support depuis ce moteur.
        </p>
      )}

      {users?.length > 0 && (
        <div className="admin-two-col">
          <div className="card card-pad">
            <div className="section-head">
              <h3>{users.length} usager{users.length > 1 ? "s" : ""}</h3>
            </div>
            <div className="tickets-table-wrap">
              <table className="tickets-table">
                <thead>
                  <tr>
                    <th>Identifiant</th>
                    <th>Conversations</th>
                    <th>Escalades</th>
                    <th>Tickets</th>
                    <th>Dernière activité</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((user) => (
                    <tr
                      key={user.user_id}
                      onClick={() => openUser(user.user_id)}
                      style={{ cursor: "pointer" }}
                    >
                      <td>
                        <div className="ticket-user">
                          <Avatar name={user.user_id} size={26} />
                          {user.user_id}
                        </div>
                      </td>
                      <td>{user.conversations}</td>
                      <td>{user.escalations}</td>
                      <td>
                        {user.tickets}
                        {user.open_tickets > 0 && (
                          <span className="badge badge-warn" style={{ marginLeft: 8 }}>
                            {user.open_tickets} en cours
                          </span>
                        )}
                      </td>
                      <td className="ticket-date">{relativeLabel(user.last_activity)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="card card-pad">
            {!selected ? (
              <p className="empty-hint">Sélectionnez un usager pour voir son historique.</p>
            ) : selected.loading ? (
              <p className="empty-hint">Chargement…</p>
            ) : (
              <>
                <div className="section-head">
                  <h3>{selected.user_id}</h3>
                </div>
                <div style={{ fontSize: "0.84rem", color: "var(--ink-muted)", marginBottom: 14 }}>
                  {selected.messages_sent} message{selected.messages_sent > 1 ? "s" : ""} envoyé
                  {selected.messages_sent > 1 ? "s" : ""} · {selected.conversations} conversation
                  {selected.conversations > 1 ? "s" : ""} · dernière activité{" "}
                  {relativeLabel(selected.last_activity)}
                </div>

                <h4 style={{ fontSize: "0.82rem", marginBottom: 8 }}>Conversations</h4>
                <div style={{ display: "grid", gap: 6, marginBottom: 16 }}>
                  {selected.conversation_list.map((conversation) => (
                    <div key={conversation.conversation_id} style={{ fontSize: "0.82rem" }}>
                      <Icon name="message" size={13} /> {conversation.conversation_id} ·{" "}
                      {conversation.status}
                      {conversation.last_intent ? ` · ${conversation.last_intent}` : ""}
                      {conversation.assigned_to ? ` · ${conversation.assigned_to}` : ""}
                    </div>
                  ))}
                </div>

                <h4 style={{ fontSize: "0.82rem", marginBottom: 8 }}>Tickets</h4>
                {selected.ticket_list.length === 0 ? (
                  <p className="empty-hint">Aucun ticket.</p>
                ) : (
                  <div style={{ display: "grid", gap: 6 }}>
                    {selected.ticket_list.map((ticket) => (
                      <div key={ticket.ticket_id} style={{ fontSize: "0.82rem" }}>
                        <strong>{ticket.ticket_id}</strong> · {ticket.category} · {ticket.status}
                        {ticket.assigned_to ? ` · ${ticket.assigned_to}` : ""}
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </AdminShell>
  );
}
