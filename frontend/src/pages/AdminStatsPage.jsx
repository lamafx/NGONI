import { useEffect, useMemo, useState } from "react";
import { AdminShell } from "../components/layout/AdminShell";
import { AreaChart } from "../components/ui/Sparkline";
import { getStatsOverview } from "../services/engineClient";
import { useDemoAdminTour } from "../hooks/useDemoAdminTour";

/**
 * Statistiques -- tout provient de GET /admin/stats/overview, une agregation
 * SQL faite cote moteur sur les tables reellement alimentees en production :
 * tickets, journal d'audit des actions de l'agent, sessions et appels du
 * Diagnostic Engine, notations utile/pas utile, base de connaissances.
 *
 * Version precedente : la page recalculait ces totaux dans le navigateur a
 * partir de /admin/complaints/ (plafonnee a 50 lignes) et /audit/actions, et
 * chaque appel etait enveloppe dans un `.catch(() => [])`. Consequence : dès
 * que le moteur ne repondait pas -- le cas le plus courant, le service
 * n'etant pas demarre -- la page affichait des zeros partout SANS le dire,
 * ce qui se lit comme "aucune activite" alors que rien n'avait ete lu. Les
 * erreurs remontent desormais explicitement, et les compteurs sont ceux de
 * la base entiere.
 */
// Perimetre du catalogue de diagnostic ANNONCE dans cet encart.
//
// Ce ne sont PAS les chiffres du Capability Registry en cours d'execution :
// en developpement, seuls wallet_stub et user_stub sont declares dans
// services_registry.yaml, soit 8 problemes sur 2 services -- et zero quand
// ces deux processus ne tournent pas. Les valeurs ci-dessous decrivent le
// perimetre du catalogue tel qu'il est prevu, independamment de ce qui est
// demarre sur le poste au moment ou la page s'ouvre.
//
// C'est la seule paire de valeurs de cette page qui ne soit pas comptee en
// base -- l'encart et la note de bas de page le disent explicitement, pour
// qu'on ne les lise pas comme une mesure.
const CATALOGUE_PROBLEMS = 20;
const CATALOGUE_SERVICES = 6;

export function AdminStatsPage() {
  const [stats, setStats] = useState(null);
  const [error, setError] = useState(null);
  // Serie affichee dans la courbe de volume -- les trois sont renvoyees par
  // le moteur, une seule est tracee a la fois pour garder l'echelle lisible.
  const [serie, setSerie] = useState("conversations");

  useEffect(() => {
    let cancelled = false;
    setError(null);

    // UN SEUL appel, et c'est voulu. La page lisait aussi
    // /diagnostic/capabilities pour deux cases de l'inventaire : cette route
    // interroge les microservices pour reconstruire le Capability Registry et
    // coutait plusieurs secondes des qu'ils etaient eteints -- le cas courant
    // en developpement -- pendant que les compteurs, eux, etaient prets en
    // 40 ms. Ces deux cases decrivent desormais le perimetre du catalogue
    // (voir CATALOGUE_PROBLEMS / CATALOGUE_SERVICES), il n'y a donc plus rien
    // a aller chercher ailleurs qu'en base.
    getStatsOverview()
      .then((overview) => !cancelled && setStats(overview))
      .catch((e) => !cancelled && setError(e.message));

    return () => {
      cancelled = true;
    };
  }, []);

  // Cette page ne fait PLUS partie du parcours filme (voir DEMO_ADMIN_ACT :
  // tableau de bord -> base de connaissances -> parametres). Le crochet reste
  // appele, sans condition comme l'exige React : il ne declenche rien tant
  // que l'etape courante ne porte pas ce chemin, et remettre la page dans le
  // parcours ne demandera qu'une ligne dans le scenario.
  useDemoAdminTour("/admin/statistiques");

  const series = useMemo(() => {
    if (!stats) return null;
    const points = stats.timeseries ?? [];
    return {
      values: points.map((p) => p[serie] ?? 0),
      labels: points.map((p) => formatDayLabel(p.date)),
      total: points.reduce((sum, p) => sum + (p[serie] ?? 0), 0),
    };
  }, [stats, serie]);

  if (error) {
    return (
      <AdminShell active="statistiques" title="Statistiques" subtitle="Mesures issues du moteur">
        <div className="kb-error">
          Impossible de lire les compteurs du moteur ({error}).
          <br />
          Le moteur FastAPI doit être démarré sur le port 8000 (
          <code>.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000</code> depuis{" "}
          <code>fastapi/</code>) et <code>ADMIN_INTERNAL_SECRET</code> doit correspondre à{" "}
          <code>VITE_ADMIN_SECRET</code>.
        </div>
      </AdminShell>
    );
  }

  if (!stats) {
    return (
      <AdminShell active="statistiques" title="Statistiques" subtitle="Mesures issues du moteur">
        <p className="kb-empty">Lecture des données du moteur…</p>
      </AdminShell>
    );
  }

  const { kpis, period, inventory } = stats;

  return (
    <AdminShell
      active="statistiques"
      title="Statistiques"
      subtitle={
        period.start
          ? `Activité enregistrée du ${formatDate(period.start)} au ${formatDate(period.end)}`
          : "Aucune activité enregistrée à ce jour"
      }
    >
      <div className="st-kpis">
        <Kpi value={fmtNumber(kpis.conversations)} label="Conversations diagnostiquées" />
        <Kpi value={fmtNumber(kpis.tickets_total)} label="Tickets enregistrés" />
        <Kpi value={fmtPercent(kpis.faq_answer_rate)} label="Questions avec réponse FAQ" />
        <Kpi value={fmtPercent(kpis.satisfaction_rate)} label="Réponses jugées utiles" />
        <Kpi value={fmtLatency(kpis.avg_latency_ms)} label="Latence moyenne (services)" />
      </div>

      <section className="card card-pad st-chart">
        <div className="st-chart-head">
          <h3>Volume d'activité par jour</h3>
          <div className="st-serie-switch">
            {[
              ["conversations", "Conversations"],
              ["tickets", "Tickets"],
              ["faq_lookups", "Recherches FAQ"],
            ].map(([key, label]) => (
              <button
                key={key}
                type="button"
                className={`st-serie-btn${serie === key ? " active" : ""}`}
                onClick={() => setSerie(key)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        {series && series.values.length > 1 ? (
          <>
            <AreaChart values={series.values} labels={series.labels} color="var(--brand)" height={190} />
            <p className="st-chart-total">
              {fmtNumber(series.total)} sur la période affichée ({series.values.length} jours)
            </p>
          </>
        ) : (
          <p className="kb-empty">Pas encore assez de jours d'activité pour tracer une courbe.</p>
        )}
      </section>

      <div className="st-kpis">
        <Kpi value={fmtNumber(kpis.tickets_open)} label="Tickets encore ouverts" />
        <Kpi value={fmtNumber(kpis.tickets_resolved)} label="Tickets clôturés" />
        <Kpi value={fmtNumber(kpis.escalations)} label="Escalades vers un humain" />
        <Kpi value={fmtNumber(kpis.agent_actions)} label="Actions journalisées" />
        <Kpi value={fmtNumber(kpis.feedback_entries)} label="Retours utilisateurs" />
      </div>

      <div className="st-grid">
        <Panel title="Tickets par catégorie" rows={stats.tickets_by_category} />
        <Panel title="Tickets par urgence" rows={stats.tickets_by_urgency} />
        <Panel title="Origine des tickets" rows={stats.tickets_by_origin} />
        <Panel title="Statut des tickets" rows={stats.tickets_by_status} />
        <Panel title="Actions par domaine" rows={stats.actions_by_domain} />
        <Panel title="Types d'action les plus fréquents" rows={stats.actions_by_type} />
        <Panel title="Appels de diagnostic par service" rows={stats.diagnostic_by_service} />
        <Panel title="Problèmes les plus diagnostiqués" rows={stats.top_problems} />
      </div>

      <div className="st-grid">
        <section className="card card-pad">
          <h3>Réponses FAQ les plus servies</h3>
          <RankedList rows={stats.top_faq_questions} emptyLabel="Aucune réponse FAQ servie pour l'instant." />
        </section>
        <section className="card card-pad">
          <h3>Questions restées sans réponse</h3>
          <RankedList
            rows={stats.unanswered_questions}
            emptyLabel="Toutes les questions posées ont trouvé une réponse."
          />
          <p className="st-panel-note">
            Chaque ligne est une entrée de base de connaissances à écrire : la question a été posée,
            aucune entrée n'a dépassé le seuil de similarité.
          </p>
        </section>
      </div>

      <section className="card card-pad st-inventory">
        <h3>Périmètre du système</h3>
        <div className="st-inv-grid">
          <div>
            <span className="st-inv-value">{fmtNumber(inventory.faq_items)}</span>
            <span className="st-inv-label">entrées de base de connaissances</span>
          </div>
          <div>
            <span className="st-inv-value">{fmtNumber(inventory.faq_published)}</span>
            <span className="st-inv-label">entrées publiées</span>
          </div>
          <div>
            <span className="st-inv-value">{fmtNumber(CATALOGUE_PROBLEMS)}</span>
            <span className="st-inv-label">problèmes diagnosticables</span>
          </div>
          <div>
            <span className="st-inv-value">{fmtNumber(CATALOGUE_SERVICES)}</span>
            <span className="st-inv-label">services interrogés</span>
          </div>
          <div>
            <span className="st-inv-value">{fmtScore(kpis.avg_faq_score)}</span>
            <span className="st-inv-label">similarité moyenne des réponses servies</span>
          </div>
          <div>
            <span className="st-inv-value">{fmtNumber(kpis.ratings_total)}</span>
            <span className="st-inv-label">notations utile / pas utile reçues</span>
          </div>
        </div>
      </section>

      <p className="st-note">
        Ces valeurs sont comptées en base par le moteur, sur la totalité des enregistrements — à
        deux exceptions près, signalées ci-dessus : le nombre de problèmes diagnosticables et de
        services interrogés décrit le périmètre du catalogue, pas ce qui tourne à cet instant.
        La latence affichée est celle des appels du moteur de diagnostic aux microservices
        (<code>diagnostic_audit_log.latency_ms</code>), pas le temps de réponse perçu par
        l'utilisateur : celui-ci n'est journalisé nulle part. La répartition des intentions NLU n'est
        pas non plus mesurée ici, faute d'être enregistrée.
      </p>
    </AdminShell>
  );
}

function Kpi({ value, label }) {
  return (
    <div className="st-kpi">
      <span className="st-kpi-value">{value}</span>
      <span className="st-kpi-label">{label}</span>
    </div>
  );
}

function Panel({ title, rows }) {
  return (
    <section className="card card-pad">
      <h3>{title}</h3>
      <Bars rows={rows} />
    </section>
  );
}

function Bars({ rows }) {
  if (!rows?.length) return <p className="kb-empty">Aucune donnée enregistrée.</p>;
  // Barres proportionnelles a la plus GRANDE valeur, pas au total : sur une
  // repartition a forte tete de serie, un pourcentage du total rend toutes
  // les autres lignes visuellement nulles.
  const max = Math.max(...rows.map((r) => r.value));
  return (
    <div className="st-bars">
      {rows.map((row) => (
        <div className="st-bar-row" key={row.label}>
          <span className="st-bar-label" title={row.label}>
            {row.label}
          </span>
          <span className="st-bar-track">
            <span className="st-bar-fill" style={{ width: `${max ? (row.value / max) * 100 : 0}%` }} />
          </span>
          <span className="st-bar-value">{fmtNumber(row.value)}</span>
        </div>
      ))}
    </div>
  );
}

function RankedList({ rows, emptyLabel }) {
  if (!rows?.length) return <p className="kb-empty">{emptyLabel}</p>;
  return (
    <ol className="st-ranked">
      {rows.map((row) => (
        <li key={row.label}>
          <span className="st-ranked-label" title={row.label}>
            {row.label}
          </span>
          <span className="st-ranked-value">{fmtNumber(row.value)}</span>
        </li>
      ))}
    </ol>
  );
}

const NUMBER_FORMAT = new Intl.NumberFormat("fr-FR");

function fmtNumber(value) {
  return typeof value === "number" ? NUMBER_FORMAT.format(value) : "—";
}

// null cote moteur = denominateur vide (aucune mesure), a distinguer d'un
// vrai 0 % -- d'ou le tiret plutot que "0 %".
function fmtPercent(value) {
  return typeof value === "number" ? `${Math.round(value * 100)} %` : "—";
}

function fmtLatency(value) {
  if (typeof value !== "number") return "—";
  return value >= 1000 ? `${(value / 1000).toFixed(1)} s` : `${value} ms`;
}

function fmtScore(value) {
  return typeof value === "number" ? value.toFixed(2) : "—";
}

function formatDate(iso) {
  if (!iso) return "—";
  return new Date(`${iso}T00:00:00`).toLocaleDateString("fr-FR", { day: "2-digit", month: "long", year: "numeric" });
}

function formatDayLabel(iso) {
  return new Date(`${iso}T00:00:00`).toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" });
}
