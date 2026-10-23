/**
 * Espace Admin → Agents : les conseillers connus du moteur
 * (`GET /admin/agents`), leur statut effectif (dérivé de leur dernière
 * activité, pas seulement déclaré) et leur charge réelle, comptée en base.
 * Création d'un conseiller et changement de statut via les routes existantes.
 */

import { useCallback, useEffect, useState } from "react";
import { AdminShell } from "../components/layout/AdminShell";
import { Avatar } from "../components/ui/Avatar";
import { Icon } from "../components/ui/Icon";
import { Kpi, LoadState, relativeLabel } from "../components/admin/adminUi";
import { createAgent, listAgents, setAgentStatus } from "../services/engineClient";

const STATUS = {
  online: { label: "En ligne", tone: "badge-good" },
  away: { label: "Absent", tone: "badge-warn" },
  offline: { label: "Hors ligne", tone: "badge-neutral" },
};

const inputStyle = {
  padding: "8px 12px",
  borderRadius: 10,
  border: "1px solid var(--line)",
  fontFamily: "inherit",
  fontSize: "0.84rem",
  background: "var(--surface)",
  color: "var(--ink)",
  minWidth: 0,
};

export function AdminAgentsPage() {
  const [agents, setAgents] = useState(null);
  const [error, setError] = useState(null);
  const [form, setForm] = useState({ agentId: "", displayName: "", role: "Conseiller support" });
  const [formError, setFormError] = useState(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(
    () =>
      listAgents()
        .then((rows) => {
          setAgents(rows);
          setError(null);
        })
        .catch((err) => {
          console.error("[AdminAgentsPage]", err);
          setError("Moteur injoignable — les conseillers ne peuvent pas être affichés.");
        }),
    []
  );

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 15000);
    return () => clearInterval(timer);
  }, [refresh]);

  async function changeStatus(agentId, status) {
    try {
      await setAgentStatus(agentId, status);
      await refresh();
    } catch (err) {
      console.error("[AdminAgentsPage] statut :", err);
      setError("Le changement de statut a échoué.");
    }
  }

  async function submit(event) {
    event.preventDefault();
    const agentId = form.agentId.trim();
    const displayName = form.displayName.trim();
    if (!/^[a-z0-9][a-z0-9._-]{1,63}$/i.test(agentId)) {
      setFormError("Identifiant invalide : lettres, chiffres, « . », « _ » ou « - » (2 à 64 caractères).");
      return;
    }
    if (!displayName) {
      setFormError("Le nom affiché est obligatoire.");
      return;
    }
    setBusy(true);
    setFormError(null);
    try {
      await createAgent(agentId, displayName, form.role.trim() || "Conseiller support");
      setForm({ agentId: "", displayName: "", role: "Conseiller support" });
      await refresh();
    } catch (err) {
      console.error("[AdminAgentsPage] création :", err);
      setFormError("L'enregistrement a échoué.");
    } finally {
      setBusy(false);
    }
  }

  const online = (agents ?? []).filter((a) => a.status === "online").length;
  const load = (agents ?? []).reduce((n, a) => n + a.active_conversations, 0);
  const tickets = (agents ?? []).reduce((n, a) => n + a.assigned_tickets, 0);

  return (
    <AdminShell active="agents" title="Agents" subtitle="Les conseillers humains qui reprennent les conversations escaladées">
      <LoadState error={error} loading={!error && agents === null} />

      {agents && (
        <div className="kpi-grid">
          <Kpi label="Conseillers" value={agents.length} />
          <Kpi label="En ligne" value={online} tone={online ? "good" : "risk"} sub={online ? undefined : "personne pour reprendre une escalade"} />
          <Kpi label="Conversations en charge" value={load} />
          <Kpi label="Tickets attribués" value={tickets} />
        </div>
      )}

      {agents && (
        <div className="admin-two-col">
          <div className="card card-pad">
            <LoadState empty={agents.length === 0} emptyText="Aucun conseiller enregistré : créez-en un ci-contre." />
            {agents.length > 0 && (
              <div className="tickets-table-wrap">
                <table className="tickets-table">
                  <thead>
                    <tr>
                      <th>Conseiller</th>
                      <th>Statut</th>
                      <th>Charge</th>
                      <th>Vu</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {agents.map((agent) => {
                      const meta = STATUS[agent.status] ?? STATUS.offline;
                      return (
                        <tr key={agent.agent_id}>
                          <td>
                            <div className="ticket-user">
                              <Avatar name={agent.display_name} size={26} />
                              <div>
                                <div style={{ fontWeight: 600 }}>{agent.display_name}</div>
                                <div style={{ fontSize: "0.74rem", color: "var(--ink-faint)" }}>
                                  {agent.agent_id} · {agent.role}
                                </div>
                              </div>
                            </div>
                          </td>
                          <td>
                            <span className={`badge ${meta.tone}`}>
                              <span className="badge-dot" />
                              {meta.label}
                            </span>
                            {agent.declared_status !== agent.status && (
                              <div style={{ fontSize: "0.72rem", color: "var(--ink-faint)", marginTop: 3 }}>
                                déclaré « {STATUS[agent.declared_status]?.label ?? agent.declared_status} »
                              </div>
                            )}
                          </td>
                          <td style={{ fontSize: "0.82rem" }}>
                            {agent.active_conversations} conv. · {agent.assigned_tickets} tickets
                          </td>
                          <td className="ticket-date">{relativeLabel(agent.last_seen_at)}</td>
                          <td>
                            <select
                              value={agent.declared_status}
                              onChange={(event) => changeStatus(agent.agent_id, event.target.value)}
                              style={{ ...inputStyle, padding: "5px 8px", fontSize: "0.78rem" }}
                              aria-label={`Statut de ${agent.display_name}`}
                            >
                              {Object.entries(STATUS).map(([value, entry]) => (
                                <option key={value} value={value}>
                                  {entry.label}
                                </option>
                              ))}
                            </select>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <form className="card card-pad" style={{ display: "grid", gap: 10 }} onSubmit={submit}>
            <div className="section-head">
              <h3>Ajouter un conseiller</h3>
            </div>
            <input
              style={inputStyle}
              placeholder="Identifiant (ex. conseiller-2)"
              value={form.agentId}
              onChange={(event) => setForm({ ...form, agentId: event.target.value })}
              spellCheck={false}
            />
            <input
              style={inputStyle}
              placeholder="Nom affiché"
              value={form.displayName}
              onChange={(event) => setForm({ ...form, displayName: event.target.value })}
            />
            <input
              style={inputStyle}
              placeholder="Rôle"
              value={form.role}
              onChange={(event) => setForm({ ...form, role: event.target.value })}
            />
            {formError && <span style={{ fontSize: "0.8rem", color: "var(--risk)" }}>{formError}</span>}
            <button type="submit" className="btn btn-primary btn-sm" disabled={busy}>
              <Icon name="plus" size={14} /> Créer
            </button>
            <p className="empty-hint" style={{ margin: 0 }}>
              Un identifiant existant met à jour la fiche (nom, rôle). Le poste conseiller s'identifie par
              VITE_AGENT_ID (par défaut « conseiller-1 »).
            </p>
          </form>
        </div>
      )}
    </AdminShell>
  );
}
