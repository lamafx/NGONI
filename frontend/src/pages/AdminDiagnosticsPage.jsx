/**
 * Espace Admin → Diagnostics : supervision du Diagnostic Engine.
 *
 *  - Chiffres de la période (`/admin/diagnostics/runs`) ;
 *  - Bilan PAR PROBLÈME (`/admin/diagnostics/problems`) : où le diagnostic
 *    aboutit, où il escalade, et pour quelle cause. C'est cette vue qui a
 *    révélé que les retraits escaladaient à 99 % sur « portefeuille
 *    introuvable » : le chat transmettait un identifiant de conversation au
 *    lieu d'un compte (corrigé, voir rasa/actions/diagnostic.py) ;
 *  - Sessions récentes et le détail de chaque appel au microservice ;
 *  - Catalogue des problèmes diagnosticables (`/diagnostic/capabilities`) et
 *    test de classification d'une phrase libre (`/diagnostic/debug/classify`).
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { AdminShell } from "../components/layout/AdminShell";
import { Icon } from "../components/ui/Icon";
import { AreaChart } from "../components/ui/Sparkline";
import { Kpi, LoadState, Select, Toolbar, dateLabel, percent, relativeLabel } from "../components/admin/adminUi";
import {
  debugClassifyDiagnostic,
  getDiagnosticProblems,
  getDiagnosticRuns,
  getDiagnosticSession,
  getSystemHealth,
  listCapabilities,
  listDiagnosticSessions,
} from "../services/engineClient";

const PERIODS = [
  ["7", "7 derniers jours"],
  ["30", "30 derniers jours"],
  ["90", "90 derniers jours"],
  ["365", "12 derniers mois"],
];

const SESSION_STATUS = {
  IN_PROGRESS: { label: "En cours", tone: "badge-info" },
  RESOLVED: { label: "Résolu", tone: "badge-good" },
  ESCALATED: { label: "Escaladé", tone: "badge-warn" },
};

const OUTCOME = {
  RESOLVED: { label: "Résolu", tone: "badge-good" },
  ESCALATE: { label: "Escalade", tone: "badge-warn" },
  NEED_MORE_INFO: { label: "Infos manquantes", tone: "badge-info" },
};

// Causes renvoyees par les microservices (outcome_detail), en clair.
const CAUSES = {
  WALLET_NOT_FOUND: "Portefeuille introuvable pour ce compte",
  USER_NOT_FOUND: "Compte utilisateur introuvable",
  TRANSACTION_NOT_FOUND: "Transaction introuvable",
  MULTIPLE_TRANSACTIONS_MATCH: "Plusieurs transactions possibles",
  AMBIGUOUS_DATE_OR_AMOUNT: "Date ou montant ambigu",
  SERVICE_UNAVAILABLE: "Microservice injoignable",
  PENDING_WITHIN_SLA: "En attente, dans les délais",
  PENDING_BEYOND_SLA_NO_PROVIDER_RESPONSE: "En attente au-delà du délai, sans réponse du prestataire",
  WITHDRAWAL_COMPLETED: "Retrait effectué",
  WITHDRAWAL_FAILED_REFUNDED: "Retrait échoué, solde restauré",
  WITHDRAWAL_CANCELLED_BY_USER: "Retrait annulé par l'usager",
  TOPUP_COMPLETED: "Recharge créditée",
  TOPUP_FAILED_NOT_DEBITED: "Recharge échouée, non débitée",
  GIFT_DELIVERED: "Cadeau livré",
  SENT_WITHOUT_RECEIVED_PAIR: "Cadeau envoyé mais non reçu",
  KYC_ALREADY_VERIFIED: "KYC déjà validé",
  KYC_UNDER_REVIEW: "KYC en cours d'examen",
  KYC_REJECTED: "KYC refusé",
  KYC_NOT_STARTED: "KYC non commencé",
  KYC_STATUS_MISMATCH: "Statut KYC incohérent entre services",
  ACCOUNT_SUSPENDED: "Compte suspendu",
  ACCOUNT_BANNED: "Compte banni",
  HOLD_ACTIVE: "Blocage de conformité actif",
  NO_ACTIVE_HOLD: "Aucun blocage actif",
  UNKNOWN_STATUS: "Statut inconnu",
};

// Causes qui trahissent un probleme d'IDENTITE transmise, pas un vrai
// probleme de l'usager : si elles dominent, c'est la chaine qui est en cause.
const IDENTITY_CAUSES = new Set(["WALLET_NOT_FOUND", "USER_NOT_FOUND"]);

function cause(code) {
  if (!code) return "—";
  return CAUSES[code] ?? code;
}

function Tag({ map, value }) {
  const entry = map[value] ?? { label: value ?? "—", tone: "badge-neutral" };
  return (
    <span className={`badge ${entry.tone}`}>
      <span className="badge-dot" />
      {entry.label}
    </span>
  );
}

function RateBar({ ratio }) {
  if (ratio === null || ratio === undefined) return <span style={{ color: "var(--ink-faint)" }}>—</span>;
  const color = ratio >= 0.6 ? "var(--good)" : ratio >= 0.3 ? "var(--warn)" : "var(--risk)";
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
      <span style={{ width: 70, height: 6, borderRadius: 4, background: "var(--surface-2)", overflow: "hidden" }}>
        <span style={{ display: "block", width: `${Math.round(ratio * 100)}%`, height: "100%", background: color }} />
      </span>
      <span style={{ fontWeight: 700, color }}>{percent(ratio)}</span>
    </span>
  );
}

export function AdminDiagnosticsPage() {
  const [days, setDays] = useState("30");
  const [runs, setRuns] = useState(null);
  const [problems, setProblems] = useState(null);
  const [capabilities, setCapabilities] = useState(null);
  const [health, setHealth] = useState(null);
  const [error, setError] = useState(null);

  const [sessionStatus, setSessionStatus] = useState("");
  const [problemFilter, setProblemFilter] = useState("");
  const [sessions, setSessions] = useState(null);
  const [openSession, setOpenSession] = useState(null);

  const [probe, setProbe] = useState("");
  const [probeResult, setProbeResult] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    Promise.all([getDiagnosticRuns(days), getDiagnosticProblems(days)])
      .then(([runData, problemData]) => {
        if (cancelled) return;
        setRuns(runData);
        setProblems(problemData.problems);
      })
      .catch((err) => {
        console.error("[AdminDiagnosticsPage]", err);
        if (!cancelled) setError("Moteur injoignable — les diagnostics ne peuvent pas être affichés.");
      });
    return () => {
      cancelled = true;
    };
  }, [days]);

  useEffect(() => {
    listCapabilities()
      .then((data) => setCapabilities(data.problems))
      .catch((err) => console.error("[AdminDiagnosticsPage] catalogue :", err));
    getSystemHealth()
      .then(setHealth)
      .catch((err) => console.error("[AdminDiagnosticsPage] santé :", err));
  }, []);

  const refreshSessions = useCallback(() => {
    const [service, problem] = problemFilter ? problemFilter.split("/") : [];
    listDiagnosticSessions({ days, status: sessionStatus || undefined, service, problem, limit: 50 })
      .then(setSessions)
      .catch((err) => console.error("[AdminDiagnosticsPage] sessions :", err));
  }, [days, sessionStatus, problemFilter]);

  useEffect(() => {
    refreshSessions();
  }, [refreshSessions]);

  function showSession(sessionId) {
    setOpenSession({ session_id: sessionId, loading: true });
    getDiagnosticSession(sessionId)
      .then(setOpenSession)
      .catch((err) => {
        console.error("[AdminDiagnosticsPage] session :", err);
        setOpenSession(null);
      });
  }

  async function runProbe(event) {
    event.preventDefault();
    const text = probe.trim();
    if (!text) return;
    setProbeResult({ loading: true });
    try {
      setProbeResult(await debugClassifyDiagnostic(text));
    } catch (err) {
      console.error("[AdminDiagnosticsPage] classification :", err);
      setProbeResult({ failed: true });
    }
  }

  const labels = useMemo(() => {
    const map = {};
    (capabilities ?? []).forEach((c) => {
      map[`${c.service}/${c.id}`] = c.label;
    });
    return map;
  }, [capabilities]);

  const totals = useMemo(() => {
    const list = problems ?? [];
    const resolved = list.reduce((n, p) => n + p.resolved, 0);
    const escalated = list.reduce((n, p) => n + p.escalated, 0);
    let identity = 0;
    list.forEach((p) =>
      p.top_details.forEach((d) => {
        if (d.outcome === "ESCALATE" && IDENTITY_CAUSES.has(d.detail)) identity += d.count;
      })
    );
    return {
      resolved,
      escalated,
      rate: resolved + escalated ? resolved / (resolved + escalated) : null,
      identityShare: escalated ? identity / escalated : 0,
    };
  }, [problems]);

  const microservices = (health?.services ?? []).filter((s) => s.name.endsWith(" service"));

  return (
    <AdminShell active="diagnostics" title="Diagnostics" subtitle="Ce que le Diagnostic Engine a vérifié, résolu ou transmis">
      <Toolbar>
        <Select label="Période" value={days} onChange={setDays} options={PERIODS} />
        {microservices.map((service) => (
          <span
            key={service.name}
            className={`badge ${service.status === "operational" ? "badge-good" : service.status === "degraded" ? "badge-warn" : "badge-risk"}`}
            title={service.detail ?? ""}
          >
            <span className="badge-dot" />
            {service.name} · {service.status === "operational" ? "opérationnel" : service.status}
            {service.latency_ms !== null && service.latency_ms !== undefined ? ` · ${service.latency_ms} ms` : ""}
          </span>
        ))}
      </Toolbar>

      <LoadState error={error} loading={!error && runs === null} />

      {runs && (
        <div className="kpi-grid">
          <Kpi label="Diagnostics exécutés" value={runs.runs_total} sub={`sur ${runs.period_days} jours`} />
          <Kpi
            label="Taux de résolution automatique"
            value={percent(totals.rate)}
            sub={`${totals.resolved} résolus · ${totals.escalated} escaladés`}
            tone={totals.rate === null ? undefined : totals.rate >= 0.5 ? "good" : "risk"}
          />
          <Kpi
            label="Latence moyenne"
            value={runs.avg_latency_ms !== null ? `${runs.avg_latency_ms} ms` : "—"}
            sub="appel au microservice compris"
          />
          <Kpi
            label="Problèmes au catalogue"
            value={capabilities ? capabilities.length : "—"}
            sub={capabilities ? `${new Set(capabilities.map((c) => c.service)).size} microservices` : ""}
          />
        </div>
      )}

      {totals.escalated >= 5 && totals.identityShare >= 0.5 && (
        <div className="card card-pad" style={{ borderColor: "var(--warn)", background: "var(--warn-soft)" }}>
          <strong>
            <Icon name="alert" size={15} /> {percent(totals.identityShare)} des escalades viennent d'un compte introuvable.
          </strong>
          <div style={{ fontSize: "0.84rem", marginTop: 6, lineHeight: 1.5 }}>
            Le microservice ne reconnaît pas l'identifiant reçu : ce n'est pas un problème de l'usager mais de
            l'identité transmise par le chat (X-User-ID). Vérifiez que l'usager est rattaché à un compte Ngoni
            existant (page Profil de l'espace client).
          </div>
        </div>
      )}

      {runs && runs.points.length > 1 && runs.runs_total > 0 && (
        <div className="card card-pad">
          <div className="section-head">
            <h3>Volume quotidien</h3>
          </div>
          <AreaChart
            values={runs.points.map((p) => p.runs)}
            labels={runs.points.map((p) => p.date.slice(5).split("-").reverse().join("/"))}
            color="var(--brand)"
          />
        </div>
      )}

      {problems && (
        <div className="card card-pad">
          <div className="section-head">
            <h3>Problèmes de diagnostic</h3>
          </div>
          <LoadState empty={problems.length === 0} emptyText="Aucun diagnostic exécuté sur la période." />
          {problems.length > 0 && (
            <div className="tickets-table-wrap">
              <table className="tickets-table">
                <thead>
                  <tr>
                    <th>Problème</th>
                    <th>Exécutions</th>
                    <th>Résolution</th>
                    <th>Causes principales</th>
                    <th>Latence</th>
                    <th>Dernier</th>
                  </tr>
                </thead>
                <tbody>
                  {problems.map((p) => (
                    <tr
                      key={`${p.service}/${p.problem}`}
                      style={{ cursor: "pointer" }}
                      onClick={() => setProblemFilter(`${p.service}/${p.problem}`)}
                      title="Afficher les sessions de ce problème"
                    >
                      <td>
                        <div style={{ fontWeight: 600 }}>{labels[`${p.service}/${p.problem}`] ?? p.problem}</div>
                        <div style={{ fontSize: "0.74rem", color: "var(--ink-faint)" }}>
                          {p.service} / {p.problem}
                        </div>
                      </td>
                      <td>
                        {p.runs}
                        <div style={{ fontSize: "0.74rem", color: "var(--ink-faint)" }}>
                          {p.resolved} ok · {p.escalated} esc.{p.need_more_info ? ` · ${p.need_more_info} infos` : ""}
                        </div>
                      </td>
                      <td>
                        <RateBar ratio={p.resolution_rate} />
                      </td>
                      <td style={{ fontSize: "0.78rem" }}>
                        {p.top_details.slice(0, 3).map((d) => (
                          <div key={`${d.outcome}-${d.detail}`}>
                            <span style={{ color: d.outcome === "RESOLVED" ? "var(--good)" : "var(--ink)" }}>
                              {cause(d.detail)}
                            </span>{" "}
                            <span style={{ color: "var(--ink-faint)" }}>× {d.count}</span>
                          </div>
                        ))}
                      </td>
                      <td className="ticket-date">{p.avg_latency_ms !== null ? `${p.avg_latency_ms} ms` : "—"}</td>
                      <td className="ticket-date">{relativeLabel(p.last_run_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      <div className="admin-two-col">
        <div className="card card-pad">
          <div className="section-head">
            <h3>Sessions récentes</h3>
          </div>
          <Toolbar>
            <Select
              label="Issue"
              value={sessionStatus}
              onChange={setSessionStatus}
              options={[["", "Toutes"], ["RESOLVED", "Résolues"], ["ESCALATED", "Escaladées"], ["IN_PROGRESS", "En cours"]]}
            />
            <Select
              label="Problème"
              value={problemFilter}
              onChange={setProblemFilter}
              options={[
                ["", "Tous"],
                ...(capabilities ?? []).map((c) => [`${c.service}/${c.id}`, c.label]),
              ]}
            />
            {sessions && (
              <span style={{ fontSize: "0.8rem", color: "var(--ink-muted)" }}>
                {sessions.total} session{sessions.total > 1 ? "s" : ""}
              </span>
            )}
          </Toolbar>
          <LoadState loading={sessions === null} empty={sessions?.items.length === 0} emptyText="Aucune session pour ce filtre." />
          {sessions?.items.length > 0 && (
            <div className="tickets-table-wrap" style={{ marginTop: 10 }}>
              <table className="tickets-table">
                <thead>
                  <tr>
                    <th>Session</th>
                    <th>Problème</th>
                    <th>Issue</th>
                    <th>Cause</th>
                    <th>Quand</th>
                  </tr>
                </thead>
                <tbody>
                  {sessions.items.map((s) => (
                    <tr
                      key={s.session_id}
                      onClick={() => showSession(s.session_id)}
                      style={{
                        cursor: "pointer",
                        background: openSession?.session_id === s.session_id ? "var(--surface-2)" : undefined,
                      }}
                    >
                      <td style={{ fontSize: "0.8rem", fontWeight: 600 }}>{s.session_id}</td>
                      <td style={{ fontSize: "0.8rem" }}>{labels[`${s.service}/${s.problem}`] ?? s.problem}</td>
                      <td>
                        <Tag map={SESSION_STATUS} value={s.status} />
                      </td>
                      <td style={{ fontSize: "0.78rem" }}>{cause(s.last_outcome_detail ?? s.last_outcome)}</td>
                      <td className="ticket-date">{relativeLabel(s.updated_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="card card-pad" style={{ display: "grid", gap: 12 }}>
          {!openSession ? (
            <p className="empty-hint">Sélectionnez une session pour voir chaque appel au microservice.</p>
          ) : openSession.loading ? (
            <p className="empty-hint">Chargement…</p>
          ) : (
            <>
              <div className="section-head">
                <h3 style={{ wordBreak: "break-all" }}>{openSession.session_id}</h3>
                <Tag map={SESSION_STATUS} value={openSession.status} />
              </div>
              <div style={{ fontSize: "0.82rem", color: "var(--ink-muted)", lineHeight: 1.6 }}>
                {labels[`${openSession.service}/${openSession.problem}`] ?? openSession.problem} ({openSession.service})
                <br />
                Compte transmis : <code>{openSession.user_id ?? "—"}</code>
                <br />
                {openSession.turns_count} appel{openSession.turns_count > 1 ? "s" : ""} · ouverte le{" "}
                {dateLabel(openSession.created_at)}
              </div>
              <div style={{ display: "grid", gap: 10 }}>
                {openSession.calls.map((call) => (
                  <div key={call.trace_id} style={{ borderTop: "1px solid var(--line)", paddingTop: 10, fontSize: "0.8rem" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center" }}>
                      <Tag map={OUTCOME} value={call.outcome} />
                      <span style={{ color: "var(--ink-faint)" }}>
                        {dateLabel(call.created_at)}
                        {call.latency_ms !== null ? ` · ${call.latency_ms} ms` : ""}
                      </span>
                    </div>
                    <div style={{ marginTop: 6, fontWeight: 600 }}>{cause(call.outcome_detail)}</div>
                    {call.called_endpoint && (
                      <div style={{ color: "var(--ink-faint)", marginTop: 2, wordBreak: "break-all" }}>{call.called_endpoint}</div>
                    )}
                    {call.request_entities && Object.keys(call.request_entities).length > 0 && (
                      <div style={{ marginTop: 4, color: "var(--ink-muted)" }}>
                        {Object.entries(call.request_entities)
                          .map(([key, value]) => `${key} = ${value}`)
                          .join(" · ")}
                      </div>
                    )}
                    {call.related_ticket_id && <div style={{ marginTop: 4 }}>Ticket créé : {call.related_ticket_id}</div>}
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>

      <div className="admin-two-col">
        <div className="card card-pad">
          <div className="section-head">
            <h3>Catalogue diagnosticable</h3>
          </div>
          <LoadState loading={capabilities === null} empty={capabilities?.length === 0} emptyText="Aucun microservice n'expose de manifeste." />
          {capabilities?.length > 0 && (
            <div style={{ display: "grid", gap: 10 }}>
              {capabilities.map((c) => (
                <div key={`${c.service}/${c.id}`} style={{ borderBottom: "1px solid var(--line)", paddingBottom: 10 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                    <strong style={{ fontSize: "0.86rem" }}>{c.label}</strong>
                    <span className="badge badge-neutral">{c.service}</span>
                  </div>
                  <div style={{ fontSize: "0.8rem", color: "var(--ink-muted)", marginTop: 4, lineHeight: 1.5 }}>{c.description}</div>
                  <div style={{ fontSize: "0.76rem", color: "var(--ink-faint)", marginTop: 4 }}>
                    Champs requis : {c.required_fields.length ? c.required_fields.map((f) => f.name).join(", ") : "aucun"}
                    {c.fallback_fields?.length ? ` · à défaut : ${c.fallback_fields.map((f) => f.name).join(", ")}` : ""}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="card card-pad" style={{ display: "grid", gap: 10, alignContent: "start" }}>
          <div className="section-head">
            <h3>Tester la classification</h3>
          </div>
          <div style={{ fontSize: "0.8rem", color: "var(--ink-muted)" }}>
            Vers quel problème une phrase d'usager est-elle orientée ? Score de similarité contre tout le catalogue.
          </div>
          <form onSubmit={runProbe} style={{ display: "flex", gap: 8 }}>
            <input
              value={probe}
              onChange={(event) => setProbe(event.target.value)}
              placeholder="ex. : mon retrait est bloqué depuis hier"
              spellCheck={false}
              style={{
                flex: 1,
                padding: "8px 12px",
                borderRadius: 10,
                border: "1px solid var(--line)",
                fontFamily: "inherit",
                fontSize: "0.84rem",
                background: "var(--surface)",
                color: "var(--ink)",
              }}
            />
            <button type="submit" className="btn btn-primary btn-sm" disabled={!probe.trim() || probeResult?.loading}>
              <Icon name="search" size={14} /> Tester
            </button>
          </form>
          {probeResult?.loading && <p className="empty-hint">Calcul des similarités…</p>}
          {probeResult?.failed && <p className="empty-hint">Le test a échoué (moteur injoignable ?).</p>}
          {probeResult?.candidates && (
            <div style={{ display: "grid", gap: 6 }}>
              {probeResult.candidates.slice(0, 6).map((candidate, index) => (
                <div key={`${candidate.service}/${candidate.problem_id}`} style={{ fontSize: "0.82rem" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                    <span style={{ fontWeight: index === 0 ? 700 : 500 }}>{candidate.label}</span>
                    <span style={{ fontVariantNumeric: "tabular-nums" }}>{candidate.score.toFixed(3)}</span>
                  </div>
                  <div style={{ height: 5, borderRadius: 4, background: "var(--surface-2)", overflow: "hidden", marginTop: 3 }}>
                    <div
                      style={{
                        width: `${Math.max(0, Math.min(1, candidate.score)) * 100}%`,
                        height: "100%",
                        background: index === 0 ? "var(--brand)" : "var(--line-strong)",
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </AdminShell>
  );
}
