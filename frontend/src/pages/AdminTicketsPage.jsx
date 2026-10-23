/**
 * Espace Admin → Demandes : les réclamations (tickets) du moteur
 * (`GET /admin/complaints`), avec filtres, détail, attribution à un
 * conseiller et changement de statut -- les mêmes routes que la carte
 * « Tickets » du tableau de bord, sur la liste complète.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { AdminShell } from "../components/layout/AdminShell";
import { Icon } from "../components/ui/Icon";
import {
  Badge,
  LoadState,
  Select,
  TICKET_STATUS,
  Toolbar,
  dateLabel,
  relativeLabel,
} from "../components/admin/adminUi";
import { assignComplaint, listAgents, listComplaints, updateComplaintStatus } from "../services/engineClient";

const STATUS_OPTIONS = [
  ["", "Tous les statuts"],
  ["OPEN", "Ouvertes"],
  ["IN_PROGRESS", "En cours"],
  ["RESOLVED", "Résolues"],
  ["CLOSED", "Clôturées"],
];

const URGENCY = {
  high: { label: "Haute", tone: "badge-risk" },
  medium: { label: "Moyenne", tone: "badge-warn" },
  low: { label: "Basse", tone: "badge-neutral" },
};

const ORIGIN = {
  user_reclamation_form: "Formulaire de réclamation",
  ai_auto_escalation: "Escalade automatique du diagnostic",
  diagnostic_escalation: "Escalade de diagnostic confirmée",
};

export function AdminTicketsPage() {
  const [tickets, setTickets] = useState(null);
  const [agents, setAgents] = useState([]);
  const [error, setError] = useState(null);
  const [status, setStatus] = useState("");
  const [category, setCategory] = useState("");
  const [selectedId, setSelectedId] = useState(null);
  const [assignee, setAssignee] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState(null);

  const refresh = useCallback(
    () =>
      listComplaints({ status: status || undefined, category: category || undefined, limit: 200 })
        .then((rows) => {
          setTickets(rows);
          setError(null);
        })
        .catch((err) => {
          console.error("[AdminTicketsPage]", err);
          setError("Moteur injoignable — les demandes ne peuvent pas être affichées.");
        }),
    [status, category]
  );

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    listAgents()
      .then((rows) => {
        setAgents(rows);
        if (rows.length) setAssignee(rows[0].agent_id);
      })
      .catch((err) => console.error("[AdminTicketsPage] conseillers :", err));
  }, []);

  // Les categories proposees sont celles reellement presentes, pas une liste figee.
  const [knownCategories, setKnownCategories] = useState([]);
  useEffect(() => {
    if (!tickets || category) return;
    setKnownCategories([...new Set(tickets.map((t) => t.category))].sort());
  }, [tickets, category]);

  const selected = useMemo(() => tickets?.find((t) => t.ticket_id === selectedId) ?? null, [tickets, selectedId]);

  async function act(action) {
    setBusy(true);
    setActionError(null);
    try {
      await action();
      await refresh();
    } catch (err) {
      console.error("[AdminTicketsPage] action :", err);
      setActionError("L'action a échoué : " + (err.message ?? String(err)));
    } finally {
      setBusy(false);
    }
  }

  const counts = (tickets ?? []).reduce((acc, t) => ({ ...acc, [t.status]: (acc[t.status] ?? 0) + 1 }), {});

  return (
    <AdminShell active="demandes" title="Demandes" subtitle="Réclamations ouvertes par les usagers ou par le diagnostic">
      <Toolbar>
        <Select label="Statut" value={status} onChange={setStatus} options={STATUS_OPTIONS} />
        <Select
          label="Catégorie"
          value={category}
          onChange={setCategory}
          options={[["", "Toutes"], ...knownCategories.map((c) => [c, c])]}
        />
        {tickets && (
          <span style={{ fontSize: "0.82rem", color: "var(--ink-muted)" }}>
            {tickets.length} demande{tickets.length > 1 ? "s" : ""}
            {!status && ` · ${counts.OPEN ?? 0} ouvertes · ${counts.IN_PROGRESS ?? 0} en cours`}
            {tickets.length === 200 ? " (200 plus récentes)" : ""}
          </span>
        )}
      </Toolbar>

      <LoadState error={error} loading={!error && tickets === null} empty={tickets?.length === 0} emptyText="Aucune demande pour ce filtre." />

      {tickets?.length > 0 && (
        <div className="admin-two-col">
          <div className="card card-pad">
            <div className="tickets-table-wrap">
              <table className="tickets-table">
                <thead>
                  <tr>
                    <th>Demande</th>
                    <th>Catégorie</th>
                    <th>Urgence</th>
                    <th>Statut</th>
                    <th>Créée</th>
                  </tr>
                </thead>
                <tbody>
                  {tickets.map((ticket) => (
                    <tr
                      key={ticket.ticket_id}
                      onClick={() => setSelectedId(ticket.ticket_id)}
                      style={{ cursor: "pointer", background: ticket.ticket_id === selectedId ? "var(--surface-2)" : undefined }}
                    >
                      <td>
                        <div style={{ fontWeight: 600 }}>{ticket.ticket_id}</div>
                        <div
                          style={{
                            fontSize: "0.76rem",
                            color: "var(--ink-faint)",
                            maxWidth: 280,
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                          }}
                        >
                          {ticket.summary || ticket.description}
                        </div>
                      </td>
                      <td style={{ fontSize: "0.82rem" }}>{ticket.category}</td>
                      <td>
                        <Badge map={URGENCY} value={ticket.urgency} />
                      </td>
                      <td>
                        <Badge map={TICKET_STATUS} value={ticket.status} />
                      </td>
                      <td className="ticket-date">{relativeLabel(ticket.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="card card-pad" style={{ display: "grid", gap: 12 }}>
            {!selected ? (
              <p className="empty-hint">Sélectionnez une demande pour la traiter.</p>
            ) : (
              <>
                <div className="section-head">
                  <h3>{selected.ticket_id}</h3>
                  <Badge map={TICKET_STATUS} value={selected.status} />
                </div>
                <div style={{ fontSize: "0.82rem", color: "var(--ink-muted)", lineHeight: 1.6 }}>
                  {selected.category} · urgence {URGENCY[selected.urgency]?.label.toLowerCase() ?? selected.urgency}
                  <br />
                  {ORIGIN[selected.created_by] ?? selected.created_by} · créée le {dateLabel(selected.created_at)}
                  {selected.incident_date ? ` · incident du ${selected.incident_date}` : ""}
                  <br />
                  {selected.user_id ? `Usager ${selected.user_id}` : "Usager non renseigné"}
                  {selected.assigned_to ? ` · suivie par ${selected.assigned_to}` : " · non attribuée"}
                </div>
                {selected.summary && (
                  <div>
                    <h4 style={{ fontSize: "0.8rem", marginBottom: 4 }}>Résumé</h4>
                    <div style={{ fontSize: "0.86rem" }}>{selected.summary}</div>
                  </div>
                )}
                <div>
                  <h4 style={{ fontSize: "0.8rem", marginBottom: 4 }}>Description</h4>
                  <div style={{ fontSize: "0.86rem", whiteSpace: "pre-wrap" }}>{selected.description}</div>
                </div>
                {selected.context && Object.keys(selected.context).length > 0 && (
                  <div>
                    <h4 style={{ fontSize: "0.8rem", marginBottom: 4 }}>Contexte transmis</h4>
                    <div style={{ display: "grid", gap: 3, fontSize: "0.8rem" }}>
                      {Object.entries(selected.context).map(([key, value]) => (
                        <div key={key}>
                          <span style={{ color: "var(--ink-faint)" }}>{key} :</span>{" "}
                          {typeof value === "object" ? JSON.stringify(value) : String(value)}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <div style={{ display: "grid", gap: 8, borderTop: "1px solid var(--line)", paddingTop: 12 }}>
                  <Toolbar>
                    <Select
                      label="Conseiller"
                      value={assignee}
                      onChange={setAssignee}
                      options={agents.map((agent) => [agent.agent_id, agent.display_name])}
                    />
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      disabled={busy || !assignee}
                      onClick={() => act(() => assignComplaint(selected.ticket_id, assignee))}
                    >
                      <Icon name="user-check" size={14} /> Attribuer
                    </button>
                  </Toolbar>
                  <Toolbar>
                    {["IN_PROGRESS", "RESOLVED", "CLOSED", "OPEN"]
                      .filter((next) => next !== selected.status)
                      .map((next) => (
                        <button
                          key={next}
                          type="button"
                          className="btn btn-secondary btn-sm"
                          disabled={busy}
                          onClick={() => act(() => updateComplaintStatus(selected.ticket_id, next))}
                        >
                          {next === "OPEN" ? "Rouvrir" : `Passer « ${TICKET_STATUS[next].label} »`}
                        </button>
                      ))}
                  </Toolbar>
                  {actionError && <span style={{ fontSize: "0.8rem", color: "var(--risk)" }}>{actionError}</span>}
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </AdminShell>
  );
}
