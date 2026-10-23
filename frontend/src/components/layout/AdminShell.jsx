import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import ngoniIcon from "../../assets/ngoni-support-icon.jpeg";
import { Sidebar } from "./Sidebar";
import { Avatar } from "../ui/Avatar";
import { Icon } from "../ui/Icon";
import { useDemoStore } from "../../state/DemoStore";
import { AGENTS } from "../../data/mockData";
import { getDashboardSummary } from "../../services/engineClient";
import { isDemoMode } from "../../services/demoDirector";
import { NotificationBell } from "../ui/NotificationBell";
import { useNotifications } from "../../hooks/useNotifications";
import { loadAdminNotifications } from "../../services/notificationSources";

/** Notifications de la scene rejouee : escalades et tickets du DemoStore. */
function demoAdminNotifications(state, agentRoute) {
  return [
    ...state.conversations
      .filter((c) => c.status === "escalated")
      .map((c) => ({
        id: `demo-escalade:${c.id}`,
        title: `Escalade — ${c.userName ?? c.id}`,
        body: c.subject ?? c.summary ?? undefined,
        tone: "warn",
        action: { path: agentRoute },
      })),
    ...state.tickets
      .filter((t) => t.status === "nouveau")
      .map((t) => ({
        id: `demo-ticket:${t.id}`,
        title: `Nouvelle demande ${t.id}`,
        body: [t.userName, t.subject].filter(Boolean).join(" · "),
        tone: "info",
        action: { path: "/admin" },
      })),
  ];
}

// Personne connectee a l'espace ADMINISTRATION -- distincte du conseiller qui
// traite les escalades dans l'espace Agent (Ibrahim Traoré, AGENTS[0]). Ce
// sont deux roles differents : l'un supervise, l'autre traite les dossiers.
const ADMIN_USER = { name: "Awa Koné", role: "Conseillère support" };

/**
 * Coquille commune (sidebar + en-tête) partagée par toutes les pages de
 * l'espace admin -- extraite pour eviter de dupliquer la navigation, le
 * compteur de notifications et le menu utilisateur a chaque nouvelle page
 * (voir AdminPage.jsx / AdminSettingsPage.jsx). `active` doit correspondre
 * a l'un des `key` de NAV_ITEMS ci-dessous.
 */
export function AdminShell({ active, title, subtitle, children }) {
  const { state } = useDemoStore();
  const navigate = useNavigate();
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const userMenuRef = useRef(null);
  // Compteurs de navigation. En demonstration : ceux du scenario rejoue.
  // Sinon : ceux du moteur, en UN seul appel (le resume du tableau de bord
  // porte deja ces quatre COUNT -- voir domains/stats/dashboard_service.py).
  const [counters, setCounters] = useState(null);
  const demo = isDemoMode();
  // Hors demonstration, tout ce qui ouvre une conversation pointe vers le
  // poste conseiller REEL (/agent/live) ; en demonstration, vers la scene
  // rejouee (/agent).
  const agentRoute = demo ? "/agent" : "/agent/live";

  useEffect(() => {
    if (demo) return;
    let cancelled = false;
    getDashboardSummary(7)
      .then((summary) => {
        if (!cancelled) setCounters(summary);
      })
      // Silencieux : ce sont des pastilles de navigation. Leur absence se
      // voit (aucun chiffre), et la page elle-meme dit deja si le moteur
      // est injoignable -- inutile de doubler l'alerte.
      .catch((err) => console.error("[AdminShell] compteurs :", err));
    return () => {
      cancelled = true;
    };
  }, [demo]);

  const liveEscalations = demo
    ? state.conversations.filter((c) => c.status === "escalated").length
    : counters?.conversations_waiting ?? 0;
  const pendingTickets = demo
    ? state.tickets.filter((t) => t.status === "nouveau").length
    : counters?.tickets_open ?? 0;
  const conversationsCount = demo ? state.conversations.length : counters?.conversations_total ?? 0;
  const ticketsCount = demo ? state.tickets.length : counters?.tickets_open ?? 0;
  const agentsCount = demo ? AGENTS.length : counters?.agents_online ?? 0;
  const usersCount = demo ? undefined : counters?.users_total ?? 0;
  // Hors demonstration : escalades en attente, demandes ouvertes, services
  // en panne et diagnostics escalades (moteur, voir notificationSources.js).
  const notifications = useNotifications({
    scope: demo ? "admin-demo" : "admin",
    load: demo ? async () => demoAdminNotifications(state, agentRoute) : loadAdminNotifications,
    intervalMs: demo ? 3000 : 30000,
  });

  useEffect(() => {
    function onClickOutside(e) {
      if (userMenuRef.current && !userMenuRef.current.contains(e.target)) setUserMenuOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);


  const NAV_ITEMS = [
    { key: "dashboard", icon: "grid", label: "Tableau de bord", onClick: () => navigate("/admin") },
    // En demonstration, Conversations/Escalades restent la scene rejouee de
    // l'espace Agent ; sinon, les pages de supervision branchees sur le moteur.
    { key: "conversations", icon: "message", label: "Conversations", count: conversationsCount, onClick: () => navigate(demo ? agentRoute : "/admin/conversations") },
    { key: "demandes", icon: "file", label: "Demandes", count: ticketsCount, onClick: () => navigate("/admin/demandes") },
    { key: "diagnostics", icon: "activity", label: "Diagnostics", onClick: () => navigate("/admin/diagnostics") },
    { key: "escalades", icon: "alert", label: "Escalades", count: liveEscalations || undefined, onClick: () => navigate(demo ? agentRoute : "/admin/escalades") },
    { key: "agents", icon: "user-check", label: "Agents", count: agentsCount, onClick: () => navigate("/admin/agents") },
    { key: "statistiques", icon: "bar-chart", label: "Statistiques", onClick: () => navigate("/admin/statistiques") },
    { key: "utilisateurs", icon: "users", label: "Utilisateurs", count: usersCount, onClick: () => navigate("/admin/utilisateurs") },
    { key: "base-connaissances", icon: "book", label: "Base de connaissances", onClick: () => navigate("/admin/base-connaissances") },
    { key: "settings", icon: "settings", label: "Paramètres", onClick: () => navigate("/admin/settings") },
  ];

  return (
    <div className="app-shell">
      <Sidebar
        brand={
          <>
            <div className="sidebar-brand-icon">
              <img src={ngoniIcon} alt="Ngoni" />
            </div>
            <div>
              <div className="sidebar-brand-name">Ngoni Support</div>
              <div className="sidebar-brand-sub">Espace Administration</div>
            </div>
          </>
        }
        items={NAV_ITEMS.map((item) => ({ ...item, active: item.key === active }))}
        footer={
          // L'identité (avatar/nom/rôle) et la déconnexion vivent déjà dans
          // l'en-tête (menu utilisateur, en haut à droite) -- les répéter
          // ici serait redondant. Le bas de la sidebar affiche plutôt un
          // statut plateforme, comme sur la page Chat (.ns-sidebar-status).
          <div className="sidebar-user">
            <span className="status-dot online" />
            <div className="who">
              <div className="name">En ligne</div>
              <div className="role">Plateforme opérationnelle</div>
            </div>
          </div>
        }
      />

      <div className="admin-main">
        <div className="admin-topbar">
          <div>
            <h1 className="admin-greeting">{title}</h1>
            {subtitle && <div className="admin-topbar-sub">{subtitle}</div>}
          </div>
          <div className="admin-topbar-right">
            <NotificationBell
              notifications={notifications}
              buttonClassName="btn btn-ghost btn-icon admin-notif-btn"
              emptyText="Rien à signaler : aucune escalade en attente, aucune demande ouverte, tous les services répondent."
              onSelect={(item) => item.action?.path && navigate(item.action.path)}
            />
            <div className="admin-user-menu" ref={userMenuRef}>
              <button type="button" className="admin-user-trigger" onClick={() => setUserMenuOpen((o) => !o)}>
                <Avatar name={ADMIN_USER.name} size={38} />
                <div className="who">
                  <div className="name">{ADMIN_USER.name}</div>
                  <div className="role">{ADMIN_USER.role}</div>
                </div>
                <Icon name="chevron-down" size={13} />
              </button>
              {userMenuOpen && (
                <div className="admin-user-dropdown">
                  <button type="button" onClick={() => navigate(agentRoute)}>
                    <Icon name="message" size={15} /> Espace conseiller
                  </button>
                  {/* Aucune session cote moteur (secret partage, pas de compte) :
                      « Déconnexion » quitte simplement l'espace d'administration. */}
                  <button type="button" onClick={() => navigate("/chat")}>
                    <Icon name="log-out" size={15} /> Déconnexion
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="admin-content">{children}</div>
      </div>
    </div>
  );
}

export { ADMIN_USER };
