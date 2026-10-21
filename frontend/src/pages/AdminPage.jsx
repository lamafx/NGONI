import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AdminShell, ADMIN_USER } from "../components/layout/AdminShell";
import { Avatar } from "../components/ui/Avatar";
import { Icon } from "../components/ui/Icon";
import { StatCard } from "../components/ui/StatCard";
import { AreaChart, DonutChart } from "../components/ui/Sparkline";
import { ServiceStatusBadge, TicketPriorityBadge, TicketStatusBadge } from "../components/ui/StatusBadge";
import { useDemoStore } from "../state/DemoStore";
import { getDashboardStats } from "../services/dashboardService";
import {
  assignComplaint,
  getIntentDistribution,
  listAgents,
  listComplaints,
  updateComplaintStatus,
} from "../services/engineClient";
import { AGENTS, buildIntentDistribution } from "../data/mockData";
import { useDemoAdminTour } from "../hooks/useDemoAdminTour";
import { clearOverlay, showOverlay } from "../services/demoOverlay";
import {
  adminAct,
  currentAct,
  isDemoMode,
  setAct,
  wait,
} from "../services/demoDirector";

// Repartition des intentions. En demonstration : la repartition illustrative
// de mockData.js. Hors demonstration : GET /admin/dashboard/intent-distribution,
// c'est-a-dire le VOLUME REEL par intention, mesure sur les messages classes
// par le moteur (voir ia.conversation_messages.intent). Les pourcentages
// illustratifs de mockData ne sont donc plus affiches ailleurs qu'en
// demonstration.
const DEMO_INTENT_DISTRIBUTION = buildIntentDistribution();

// Teintes du donut, reprises des variables de theme -- reutilisees en boucle
// quand le moteur renvoie plus d'intentions que de couleurs.
const DONUT_COLORS = [
  "var(--brand)",
  "var(--info)",
  "var(--good)",
  "var(--warn)",
  "var(--risk)",
  "var(--ink-faint)",
];

// Statuts et urgences du moteur vers le vocabulaire des badges de cette page
// (voir components/ui/StatusBadge.jsx).
const TICKET_STATUS_FROM_ENGINE = {
  OPEN: "nouveau",
  IN_PROGRESS: "en_cours",
  RESOLVED: "resolu",
  CLOSED: "resolu",
};
const TICKET_PRIORITY_FROM_ENGINE = { high: "elevee", medium: "moyenne", low: "basse" };

function ticketFromEngine(complaint) {
  return {
    id: complaint.ticket_id,
    // Aucun nom d'usager n'existe dans le schema `ia` (les profils vivent
    // dans ngoni-user-service, hors perimetre) : on affiche l'identifiant
    // reel plutot qu'un nom invente.
    userName: complaint.user_id ?? "Usager inconnu",
    subject: complaint.summary || complaint.description || complaint.category,
    status: TICKET_STATUS_FROM_ENGINE[complaint.status] ?? "nouveau",
    priority: TICKET_PRIORITY_FROM_ENGINE[complaint.urgency] ?? "moyenne",
    createdAt: complaint.created_at ? new Date(complaint.created_at).toLocaleDateString("fr-FR") : "—",
    assignedTo: complaint.assigned_to,
  };
}

export function AdminPage() {
  const { state, dispatch } = useDemoStore();
  const navigate = useNavigate();
  const [stats, setStats] = useState(null);
  const [loadError, setLoadError] = useState(null);
  // Donnees moteur, uniquement hors demonstration (null = pas encore chargees
  // ou mode demonstration : on retombe alors sur les donnees du scenario).
  const [engineTickets, setEngineTickets] = useState(null);
  const [engineAgents, setEngineAgents] = useState(null);
  const [engineIntents, setEngineIntents] = useState(null);
  const liveEscalations = state.conversations.filter((c) => c.status === "escalated").length;

  const demo = isDemoMode();
  const tickets = demo ? state.tickets : engineTickets ?? [];
  const agents = demo
    ? AGENTS
    : (engineAgents ?? []).map((agent) => ({
        id: agent.agent_id,
        name: agent.display_name,
        role: agent.role,
        status: agent.status,
      }));
  const onlineAgents = agents.filter((a) => a.status === "online");
  const intentDistribution = demo ? DEMO_INTENT_DISTRIBUTION : engineIntents;

  useEffect(() => {
    let cancelled = false;
    getDashboardStats(liveEscalations)
      .then((s) => {
        if (!cancelled) {
          setStats(s);
          setLoadError(null);
        }
      })
      .catch((err) => {
        console.error("[AdminPage] tableau de bord :", err);
        // Pas de repli sur des valeurs illustratives : une page vide qui dit
        // pourquoi vaut mieux qu'un tableau de bord credible et faux.
        if (!cancelled) setLoadError("Moteur injoignable — aucun chiffre ne peut être affiché.");
      });
    return () => {
      cancelled = true;
    };
  }, [liveEscalations]);

  const reloadTickets = useCallback(() => {
    if (isDemoMode()) return Promise.resolve();
    return listComplaints()
      .then((rows) => setEngineTickets(rows.map(ticketFromEngine)))
      .catch((err) => console.error("[AdminPage] tickets :", err));
  }, []);

  useEffect(() => {
    if (demo) return;
    reloadTickets();
    listAgents()
      .then(setEngineAgents)
      .catch((err) => console.error("[AdminPage] conseillers :", err));
    getIntentDistribution(7)
      .then((distribution) =>
        setEngineIntents({
          totalIntents: distribution.distinct_intents,
          categories: distribution.categories.map((slice, index) => ({
            label: slice.intent,
            value: slice.value_pct,
            color: DONUT_COLORS[index % DONUT_COLORS.length],
          })),
        })
      )
      .catch((err) => console.error("[AdminPage] répartition des intentions :", err));
  }, [demo, reloadTickets]);

  // Pendant la demonstration, cette page est la premiere etape du parcours
  // d'administration : elle reste affichee le temps prevu, puis passe la main
  // aux statistiques (voir useDemoAdminTour).
  useDemoAdminTour("/admin");

  return (
    <AdminShell
      active="dashboard"
      title={
        <>
          Bonjour, {ADMIN_USER.name} <span aria-hidden="true">👋</span>
        </>
      }
      subtitle="Voici un aperçu de l'activité Ngoni Support"
    >
      {loadError ? (
        <span className="status-line">
          <span className="status-dot" style={{ background: "var(--risk)" }} /> {loadError}
        </span>
      ) : !stats ? (
        <span className="status-line">
          <span className="status-dot online" /> Chargement du tableau de bord…
        </span>
      ) : (
        <>
          {/* Statut reel, issu de la sonde (GET /admin/system/health) --
              plus un libelle fixe qui affichait "opérationnel" pendant une
              panne. */}
          <div className="status-line">
            <span
              className={`status-dot ${stats.systemStatus === "operational" ? "online" : ""}`}
              style={
                stats.systemStatus && stats.systemStatus !== "operational"
                  ? { background: stats.systemStatus === "down" ? "var(--risk)" : "var(--warn)" }
                  : undefined
              }
            />
            {stats.systemStatus === "down"
              ? "Une dépendance est indisponible"
              : stats.systemStatus === "degraded"
                ? "Système dégradé"
                : "Système opérationnel"}
          </div>

          <div className="kpi-grid">
            <StatCard
              icon={<Icon name="message" size={16} />}
              label="Conversations en cours"
              value={stats.conversationsInProgress}
              delta={stats.conversationsInProgressDelta}
              compareLabel={stats.conversationsInProgressCompare}
              positive={stats.conversationsInProgressPositive}
            />
            <StatCard
              icon={<Icon name="check-circle" size={16} />}
              label="Tickets traités aujourd'hui"
              value={stats.ticketsTreatedToday}
              delta={stats.ticketsTreatedTodayDelta}
              compareLabel={stats.ticketsTreatedTodayCompare}
              positive={stats.ticketsTreatedTodayPositive}
            />
            <StatCard
              icon={<Icon name="clock" size={16} />}
              label="Temps de réponse moyen"
              value={stats.avgResponseHeadline}
              delta={stats.avgResponseHeadlineDelta}
              compareLabel={stats.avgResponseHeadlineCompare}
              // Un delai qui baisse est une bonne nouvelle : le service
              // inverse deja le signe, on ne force plus `positive`.
              positive={stats.avgResponseHeadlinePositive ?? true}
            />
            <StatCard
              icon={<Icon name="users" size={16} />}
              label="Utilisateurs accompagnés"
              value={stats.usersHelped}
              delta={stats.usersHelpedDelta}
              compareLabel={stats.usersHelpedCompare}
              positive={stats.usersHelpedPositive}
            />
          </div>

          <div className="admin-two-col">
            <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
              <div className="card card-pad">
                <div className="chart-card-head">
                  <h3>Évolution des demandes</h3>
                  <div className="period-select">
                    7 derniers jours <Icon name="chevron-down" size={12} />
                  </div>
                </div>
                <AreaChart
                  values={stats.conversationVolume}
                  labels={stats.conversationVolumeLabels}
                  color="var(--brand)"
                />
              </div>

              <div className="card card-pad">
                <div className="section-head">
                  <h3>Tickets récents</h3>
                  <button
                    type="button"
                    className="link-more"
                    onClick={() => navigate(demo ? "/agent" : "/agent/live")}
                  >
                    Voir tout
                  </button>
                </div>
                {tickets.length === 0 ? (
                  <p className="empty-hint">Aucun ticket pour le moment.</p>
                ) : (
                  <div className="tickets-table-wrap">
                    <table className="tickets-table">
                      <thead>
                        <tr>
                          <th>Utilisateur</th>
                          <th>Objet</th>
                          <th>Statut</th>
                          <th>Priorité</th>
                          <th>Date</th>
                          <th aria-hidden="true" />
                        </tr>
                      </thead>
                      <tbody>
                        {tickets.slice(0, 6).map((t) => (
                          <TicketRow
                            key={t.id}
                            ticket={t}
                            dispatch={dispatch}
                            navigate={navigate}
                            demo={demo}
                            onChanged={reloadTickets}
                          />
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              <div className="card card-pad">
                <h3 style={{ fontSize: "0.95rem", fontWeight: 700, marginBottom: 8 }}>Activité récente</h3>
                {stats.recentActivity.map((a) => (
                  <div className="activity-row" key={a.id}>
                    <span className="a-time">{a.time}</span>
                    <span>{a.label}</span>
                  </div>
                ))}
              </div>

              <div className="card card-pad">
                <h3 style={{ fontSize: "0.95rem", fontWeight: 700, marginBottom: 12 }}>État des services</h3>
                <div className="service-grid">
                  {stats.services.map((s) => (
                    <div className="service-row" key={s.name}>
                      <span>{s.name}</span>
                      <ServiceStatusBadge status={s.status} />
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
              <div className="card card-pad">
                <h3 style={{ fontSize: "0.95rem", fontWeight: 700, marginBottom: 14 }}>Répartition des intentions</h3>
                {!intentDistribution ? (
                  <p className="empty-hint">Chargement…</p>
                ) : intentDistribution.categories.length === 0 ? (
                  <p className="empty-hint">
                    Aucun message classé sur les 7 derniers jours.
                  </p>
                ) : (
                  <div className="donut-row">
                    <DonutChart
                      slices={intentDistribution.categories}
                      centerValue={intentDistribution.totalIntents}
                      centerLabel="intentions détectées"
                    />
                    <ul className="donut-legend">
                      {intentDistribution.categories.map((c) => (
                        <li key={c.label}>
                          <span className="legend-dot" style={{ background: c.color }} />
                          <span className="legend-label">{c.label}</span>
                          <span className="legend-pct">{c.value}%</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>

              <div className="card card-pad">
                <h3 style={{ fontSize: "0.95rem", fontWeight: 700 }}>Conseillers en ligne</h3>
                <div className="online-count">
                  <span className="status-dot online" /> {onlineAgents.length} conseillers disponibles
                </div>
                <div className="online-agents-list">
                  {onlineAgents.map((a) => (
                    <div className="online-agent-row" key={a.id}>
                      <Avatar name={a.name} size={34} />
                      <div className="who">
                        <div className="name">{a.name}</div>
                        <div className="role">{a.role}</div>
                      </div>
                      <span className="badge badge-good">
                        <span className="badge-dot" />
                        En ligne
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="card card-pad admin-assist-card">
                <div className="assist-icon">
                  <Icon name="headset" size={19} />
                </div>
                <div className="assist-title">Besoin d'une assistance humaine ?</div>
                <div className="assist-text">Notre équipe est prête à vous aider.</div>
                <button type="button" className="btn btn-primary assist-btn" onClick={() => navigate("/agent")}>
                  <Icon name="headset" size={15} /> Contacter un conseiller
                </button>
              </div>
            </div>
          </div>
        </>
      )}
    </AdminShell>
  );
}

// Conseiller effectuant l'action, tant qu'aucune authentification n'existe
// cote moteur (voir api_admin_a_developper.md section 1) -- meme constante et
// meme raison que dans AgentLivePage.jsx.
const ACTING_AGENT_ID = import.meta.env.VITE_AGENT_ID || "conseiller-1";

function TicketRow({ ticket, dispatch, navigate, demo = true, onChanged }) {
  const [open, setOpen] = useState(false);
  // Message d'echec affiche sur la ligne elle-meme : une prise en charge qui
  // n'a pas atteint le moteur ne doit PAS ressembler a une reussite cote
  // interface, le ticket resterait attribue a personne pour les autres postes.
  const [actionError, setActionError] = useState(null);
  const menuRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    function onClickOutside(e) {
      if (menuRef.current && !menuRef.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [open]);

  return (
    <tr>
      <td>
        <div className="ticket-user">
          <Avatar name={ticket.userName ?? "Utilisateur"} size={26} />
          {ticket.userName ?? "—"}
        </div>
      </td>
      <td className="ticket-subject">
        {ticket.subject}
        {ticket.assignedTo && (
          <div style={{ color: "var(--ink-faint)", fontSize: "0.76rem", marginTop: 2 }}>
            Pris en charge par {ticket.assignedTo}
          </div>
        )}
        {actionError && (
          <div style={{ color: "var(--danger, #c0392b)", fontSize: "0.76rem", marginTop: 4 }}>
            {actionError}
          </div>
        )}
      </td>
      <td>
        <TicketStatusBadge status={ticket.status} />
      </td>
      <td>
        <TicketPriorityBadge priority={ticket.priority} />
      </td>
      <td className="ticket-date">{ticket.createdAt}</td>
      <td>
        <div className="ticket-actions" ref={menuRef}>
          <button type="button" className="btn btn-ghost btn-icon btn-sm" onClick={() => setOpen((o) => !o)} aria-label="Actions">
            <Icon name="more-horizontal" size={16} />
          </button>
          {open && (
            <div className="ticket-actions-menu">
              <button
                type="button"
                onClick={() => {
                  setOpen(false);
                  navigate("/agent");
                }}
              >
                Voir la conversation
              </button>
              {ticket.status === "nouveau" && (
                <button
                  type="button"
                  onClick={async () => {
                    setOpen(false);
                    setActionError(null);
                    if (demo) {
                      // Scenario rejoue : aucun de ces tickets n'existe cote
                      // moteur, l'appel echouerait forcement.
                      dispatch({ type: "SET_TICKET_STATUS", ticketId: ticket.id, status: "en_cours" });
                      return;
                    }
                    try {
                      // « Prendre en charge une reclamation » : le moteur
                      // attribue le ticket ET le passe en cours (un seul
                      // geste, voir complaints/admin_router.py).
                      await assignComplaint(ticket.id, ACTING_AGENT_ID);
                      await onChanged?.();
                    } catch (err) {
                      console.error("[AdminPage] prise en charge du ticket :", err);
                      setActionError("Prise en charge impossible — moteur injoignable.");
                    }
                  }}
                >
                  Prendre en charge
                </button>
              )}
              {ticket.status !== "resolu" && (
                <button
                  type="button"
                  onClick={async () => {
                    setOpen(false);
                    setActionError(null);
                    if (demo) {
                      dispatch({ type: "SET_TICKET_STATUS", ticketId: ticket.id, status: "resolu" });
                      return;
                    }
                    try {
                      await updateComplaintStatus(ticket.id, "RESOLVED");
                      await onChanged?.();
                    } catch (err) {
                      console.error("[AdminPage] clôture du ticket :", err);
                      setActionError("Changement de statut impossible — moteur injoignable.");
                    }
                  }}
                >
                  Marquer comme résolu
                </button>
              )}
            </div>
          )}
        </div>
      </td>
    </tr>
  );
}
