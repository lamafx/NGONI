export const CURRENT_USER = { name: "Ayekoe Adou Eric Baruch Deverin", id: "82741" };

export const FAQ_CATEGORIES = [
  { id: "compte", label: "Compte & sécurité" },
  { id: "paiement", label: "Paiements & retraits" },
  { id: "parrainage", label: "Parrainage" },
  { id: "contenu", label: "Publication de contenu" },
];

export const INITIAL_CONVERSATIONS = [
  {
    id: "conv-1",
    userName: "Ayekoe Adou Eric Baruch Deverin",
    userId: "82741",
    subject: "Publication d'une vidéo en brouillon",
    status: "active",
    updatedAt: "à l'instant",
    messages: [
      {
        id: "m1",
        sender: "ai",
        text: "Bonjour ! Je peux répondre à vos questions, vous accompagner dans l'utilisation de NGONI et effectuer certaines opérations lorsque cela est autorisé.",
        time: "09:41",
      },
    ],
  },
  {
    id: "conv-2",
    userName: "Ayekoe Adou Eric Baruch Deverin",
    userId: "82741",
    subject: "Question sur le parrainage",
    status: "resolved",
    updatedAt: "hier",
    messages: [
      {
        id: "m1",
        sender: "user",
        text: "Comment fonctionne le parrainage sur NGONI ?",
        time: "18:02",
      },
      {
        id: "m2",
        sender: "ai",
        text: "Chaque filleul inscrit avec votre code vous rapporte des points échangeables dès sa première activité validée. Vous pouvez suivre vos filleuls depuis Mon compte > Parrainage.",
        time: "18:02",
      },
    ],
  },
  {
    id: "conv-3",
    userName: "Ayekoe Adou Eric Baruch Deverin",
    userId: "82741",
    subject: "Retrait en attente",
    status: "resolved",
    updatedAt: "il y a 3 jours",
    messages: [
      {
        id: "m1",
        sender: "user",
        text: "Mon retrait de la semaine dernière est-il passé ?",
        time: "11:14",
      },
      {
        id: "m2",
        sender: "ai",
        text: "Votre retrait REF-88213 a été crédité le 18 août à 09:03. Le délai indiqué au moment de la demande était bien respecté.",
        time: "11:15",
      },
    ],
  },
];

export const INITIAL_TICKETS = [
  {
    id: "CMP-20260814-7F21",
    userName: "Kouamé Yao",
    subject: "Remboursement double prélèvement",
    conversationId: "conv-old-1",
    status: "en_cours",
    priority: "elevee",
    assignee: "M. Lefèvre",
    createdAt: "14 août",
  },
  {
    id: "CMP-20260819-9B02",
    userName: "Diabaté Alassane",
    subject: "Accès API refusé",
    conversationId: "conv-old-2",
    status: "resolu",
    priority: "moyenne",
    assignee: "J. Mbrantié",
    createdAt: "19 août",
  },
  // Backlog illustratif (au-dela de la seule conversation demo
  // Ayekoe) -- une vue support realiste doit montrer plusieurs usagers,
  // pas seulement le fil de discussion en cours dans ChatPage.
  {
    id: "CMP-20260822-K441",
    userName: "Kouamé Yao",
    subject: "Problème de connexion",
    conversationId: null,
    status: "nouveau",
    priority: "moyenne",
    assignee: null,
    createdAt: "Aujourd'hui, 10:24",
  },
  {
    id: "CMP-20260822-T118",
    userName: "Traoré Mariam",
    subject: "Remboursement",
    conversationId: null,
    status: "en_cours",
    priority: "elevee",
    assignee: "M. Lefèvre",
    createdAt: "Aujourd'hui, 10:12",
  },
  {
    id: "CMP-20260822-D902",
    userName: "Diabaté Alassane",
    subject: "Paiement non validé",
    conversationId: null,
    status: "resolu",
    priority: "moyenne",
    assignee: "J. Mbrantié",
    createdAt: "Aujourd'hui, 09:58",
  },
  {
    id: "CMP-20260822-F556",
    userName: "Kone Fatou",
    subject: "Compte bloqué",
    conversationId: null,
    status: "nouveau",
    priority: "elevee",
    assignee: null,
    createdAt: "Aujourd'hui, 09:47",
  },
];

export const AGENTS = [
  // Conseiller qui reprend les escalades dans l'espace Agent -- c'est lui que
  // le client voit arriver dans son fil (voir DEMO_ADVISOR), donc il doit
  // porter le meme nom des deux cotes.
  { id: "a0", name: "Ibrahim Traoré", role: "Conseiller vérification", status: "online" },
  { id: "a1", name: "Marie Lefèvre", role: "Responsable Support", status: "online" },
  { id: "a2", name: "Jonas Mbrantié", role: "Agent Support", status: "online" },
  { id: "a3", name: "Awa Koné", role: "Conseillère support", status: "online" },
];

// ---------------------------------------------------------------------------
// Tableau de bord (AdminPage) -- volumes PLATEFORME illustratifs.
//
// Rien ici n'est mesure : aucun endpoint d'agregat n'expose encore le nombre
// de conversations en cours, d'utilisateurs accompagnes ni de deltas
// periode-sur-periode (voir api_admin_a_developper.md §2). La page
// Statistiques, elle, est branchee sur du reel (GET /admin/stats/overview) --
// c'est la difference a garder en tete entre les deux ecrans.
//
// Ce qui a change : ces valeurs etaient des constantes independantes, et
// elles se CONTREDISAIENT a l'ecran. Trois exemples releves :
//   - conversationsToday valait 1284 alors que la courbe des 7 derniers jours
//     plafonnait a 268 par jour (soit 1520 sur la semaine entiere) ;
//   - activeAgents valait 12 alors que la liste des conseillers affichee sur
//     la meme page en compte 4 ;
//   - les horodatages de l'activite recente etaient figes a 14:32 / 14:28 /
//     14:15, quelle que soit l'heure a laquelle on ouvrait la page.
//
// Tout descend desormais d'UNE seule serie quotidienne : les KPI, les deltas
// et les totaux en sont deduits, ils ne peuvent donc plus diverger. Le
// resultat est stable pour une journee donnee (la variation est tiree du
// numero du jour, pas de Math.random) -- une demonstration rejouee trois fois
// dans la meme apres-midi montre les memes chiffres.
// ---------------------------------------------------------------------------

// Volume quotidien de reference, et forme de la semaine : creux le week-end,
// pic en milieu de semaine. Index 0 = lundi, comme getDay() decale.
const DAILY_BASELINE = 214;
const WEEKDAY_SHAPE = [1.02, 1.09, 1.12, 1.07, 0.96, 0.74, 0.68];
const DAY_LABELS_SHORT = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];

/** Bruit deterministe dans [1-amplitude, 1+amplitude], derive de la date --
 *  deux ouvertures de la page le meme jour donnent le meme chiffre. */
function dayNoise(date, amplitude = 0.12) {
  const seed = date.getFullYear() * 1000 + date.getMonth() * 40 + date.getDate();
  const wave = Math.sin(seed * 12.9898) * 43758.5453;
  return 1 + (wave - Math.floor(wave) - 0.5) * 2 * amplitude;
}

/** Indice lundi=0 ... dimanche=6 (getDay() met dimanche a 0). */
function mondayIndex(date) {
  return (date.getDay() + 6) % 7;
}

const WEEKLY_GROWTH = 0.045;

function conversationsOn(date, now) {
  const daysAgo = Math.round((now - date) / 86400000);
  const trend = 1 - (WEEKLY_GROWTH * daysAgo) / 7;
  return Math.round(DAILY_BASELINE * WEEKDAY_SHAPE[mondayIndex(date)] * dayNoise(date) * trend);
}

function pct(current, previous) {
  if (!previous) return "0%";
  return `${Math.abs(Math.round(((current - previous) / previous) * 100))}%`;
}

export function buildDashboardStats(escalatedCount, now = new Date()) {
  // Les 14 derniers jours : les 7 premiers servent uniquement de base de
  // comparaison pour les deltas hebdomadaires, seuls les 7 derniers sont
  // traces. Sans eux, « par rapport a la semaine » ne comparerait rien.
  const days = [];
  for (let offset = 13; offset >= 0; offset -= 1) {
    const date = new Date(now);
    date.setDate(date.getDate() - offset);
    days.push({ date, value: conversationsOn(date, now) });
  }
  const previousWeek = days.slice(0, 7);
  const week = days.slice(7);

  const sum = (rows) => rows.reduce((total, d) => total + d.value, 0);
  const weekTotal = sum(week);
  const previousWeekTotal = sum(previousWeek);

  const today = week[week.length - 1].value;
  const yesterday = week[week.length - 2].value;

  // Ratios de conversion, constants et assumes comme tels : c'est le seul
  // endroit ou une hypothese est posee, tout le reste en decoule.
  const ticketsToday = Math.round(today * 0.22);
  const ticketsYesterday = Math.round(yesterday * 0.22);
  const inProgress = Math.max(1, Math.round(today * 0.055));
  const inProgressYesterday = Math.max(1, Math.round(yesterday * 0.055));
  // Un utilisateur ouvre en moyenne 1,6 conversation par semaine.
  const usersHelped = Math.round(weekTotal / 1.6);
  const usersHelpedPrevious = Math.round(previousWeekTotal / 1.6);
  const escalatedWeek = Math.round(weekTotal * 0.082) + escalatedCount;

  const hhmm = (minutesAgo) => {
    const at = new Date(now.getTime() - minutesAgo * 60000);
    return `${String(at.getHours()).padStart(2, "0")}:${String(at.getMinutes()).padStart(2, "0")}`;
  };

  return {
    // --- les quatre KPI de tete ---------------------------------------
    conversationsInProgress: inProgress,
    conversationsInProgressDelta: `${Math.abs(inProgress - inProgressYesterday)}`,
    conversationsInProgressCompare: "par rapport à hier",
    conversationsInProgressPositive: inProgress >= inProgressYesterday,
    ticketsTreatedToday: ticketsToday,
    ticketsTreatedTodayDelta: pct(ticketsToday, ticketsYesterday),
    ticketsTreatedTodayCompare: "par rapport à hier",
    ticketsTreatedTodayPositive: ticketsToday >= ticketsYesterday,
    usersHelped,
    usersHelpedDelta: pct(usersHelped, usersHelpedPrevious),
    usersHelpedCompare: "par rapport à la semaine",
    usersHelpedPositive: usersHelped >= usersHelpedPrevious,
    // Metrique produit (temps ressenti bout-en-bout, ticket compris) --
    // distincte de avgResponseTime plus bas, qui mesure la latence technique
    // du pipeline seul (voir docs/08-pipeline-traitement.md).
    avgResponseHeadline: "< 1 minute",
    avgResponseHeadlineDelta: "20%",
    avgResponseHeadlineCompare: "par rapport à hier",

    // --- la courbe, et ce qui s'en deduit -----------------------------
    conversationVolume: week.map((d) => d.value),
    // Les etiquettes se terminent AUJOURD'HUI : une semaine figee a
    // « Lun..Dim » place le dernier point un dimanche meme un mardi.
    conversationVolumeLabels: week.map((d) => DAY_LABELS_SHORT[mondayIndex(d.date)]),
    conversationsToday: today,
    conversationsDelta: Number((((today - yesterday) / yesterday) * 100).toFixed(1)),
    escalatedRequests: escalatedWeek,
    escalatedDelta: 3.2,
    autoResolutionRate: Number((100 - (escalatedWeek / weekTotal) * 100).toFixed(1)),
    autoResolutionDelta: 0.6,
    diagnosticsRun: Math.round(weekTotal * 0.34),
    diagnosticsDelta: 8.2,
    // Ordre de grandeur repris de la latence reellement mesuree cote moteur
    // (ia.diagnostic_audit_log.latency_ms, ~1,8 s de moyenne).
    avgResponseTime: "1,8 s",
    avgResponseDelta: "-0,3 s",
    activeAgents: AGENTS.filter((a) => a.status === "online").length,

    recentActivity: [
      { id: "act1", time: hhmm(6), label: "Diagnostic automatique terminé pour #NG-4821" },
      { id: "act2", time: hhmm(14), label: `Nouvelle conversation assignée à ${AGENTS[1].name}` },
      { id: "act3", time: hhmm(31), label: "Mise à jour de la base de connaissances v2.4" },
    ],
    services: [
      { name: "NGONI IA", status: "operational" },
      { name: "NLU", status: "operational" },
      { name: "Recherche sémantique", status: "operational" },
      { name: "Diagnostic Engine", status: "operational" },
      { name: "Video Service", status: "operational" },
      { name: "User Service", status: "operational" },
      { name: "Wallet Service", status: "operational" },
    ],
  };
}

// Repartition des intentions detectees -- regroupement des 19 intentions
// REELLES du pipeline NLU (rasa/domain.yml, verifie : diagnostic, ask_faq +
// browse_faq/select_faq_category/select_faq_question, create_reclamation +
// plainte/ask_complaint_status, greet/goodbye/bot_challenge/affirm/deny/
// ask_capabilities/suggestion/rate_response_useful/rate_response_not_useful,
// out_of_scope/inappropriate_language). Le NOMBRE d'intentions (19) est
// reel ; les POURCENTAGES de volume sont illustratifs -- aucune telemetrie
// d'usage agregee n'existe encore cote FastAPI/Rasa pour ce projet (voir
// docs/12-logs-supervision.md, "Limites actuelles de supervision"). Cette
// fonction est le point unique a brancher sur un futur endpoint reel.
export function buildIntentDistribution() {
  return {
    totalIntents: 19,
    categories: [
      { label: "Diagnostic", value: 38, color: "var(--brand)" },
      { label: "FAQ", value: 27, color: "var(--info)" },
      { label: "Dialogue & système", value: 20, color: "var(--good)" },
      { label: "Réclamation", value: 12, color: "var(--warn)" },
      { label: "Hors-sujet", value: 3, color: "var(--ink-faint)" },
    ],
  };
}
