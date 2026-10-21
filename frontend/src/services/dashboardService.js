/**
 * Données du tableau de bord d'administration.
 *
 * Deux sources, jamais mélangées :
 *  - en mode démonstration, la série illustrative de `mockData.js`
 *    (scénario rejoué, valeurs stables et cohérentes entre elles) ;
 *  - sinon, le moteur : `GET /admin/dashboard/*` + `GET /admin/system/health`,
 *    c'est-à-dire des comptages SQL sur les tables réellement alimentées.
 *
 * Aucun repli silencieux de l'un vers l'autre : si le moteur ne répond pas
 * hors démonstration, l'appel échoue et la page le dit. Afficher des chiffres
 * inventés à la place de chiffres manquants est précisément ce que ce
 * branchement corrige.
 */

import { buildDashboardStats } from "../data/mockData";
import { delay } from "./mockLatency";
import { isDemoMode } from "./demoDirector";
import {
  getConversationVolume,
  getDashboardSummary,
  getRecentActivity,
  getSystemHealth,
} from "./engineClient";

/** « +12.4% », ou « — » quand la période précédente est vide (le moteur
 *  renvoie alors `delta_pct: null` : aucune comparaison n'a de sens). */
function formatDelta(kpi) {
  if (!kpi || kpi.delta_pct === null || kpi.delta_pct === undefined) return "—";
  return `${Math.abs(kpi.delta_pct).toFixed(1)}%`;
}

function isPositive(kpi) {
  if (!kpi || kpi.delta_pct === null || kpi.delta_pct === undefined) return true;
  return kpi.delta_pct >= 0;
}

/** Millisecondes → « 1,8 s » / « 2 min 05 s ». `null` reste « — » : aucune
 *  mesure n'est pas la même chose que zéro. */
function formatDuration(ms) {
  if (ms === null || ms === undefined) return "—";
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1).replace(".", ",")} s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes} min ${String(Math.round(seconds % 60)).padStart(2, "0")} s`;
}

function timeLabel(iso) {
  if (!iso) return "";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "";
  return `${String(at.getHours()).padStart(2, "0")}:${String(at.getMinutes()).padStart(2, "0")}`;
}

export async function getDashboardStats(escalatedCount) {
  if (isDemoMode()) {
    await delay(300);
    return buildDashboardStats(escalatedCount);
  }

  const [summary, volume, activity, health] = await Promise.all([
    getDashboardSummary(7),
    getConversationVolume(7),
    getRecentActivity(8),
    getSystemHealth(),
  ]);

  return {
    conversationsInProgress: summary.conversations_in_progress.value ?? 0,
    conversationsInProgressDelta: formatDelta(summary.conversations_in_progress),
    conversationsInProgressCompare: "par rapport à la période précédente",
    conversationsInProgressPositive: isPositive(summary.conversations_in_progress),

    ticketsTreatedToday: summary.tickets_treated.value ?? 0,
    ticketsTreatedTodayDelta: formatDelta(summary.tickets_treated),
    ticketsTreatedTodayCompare: "sur 7 jours",
    ticketsTreatedTodayPositive: isPositive(summary.tickets_treated),

    // Délai réel entre un message d'usager et la réponse qui suit, mesuré
    // sur les messages enregistrés -- pas la latence technique du pipeline
    // (celle-là vit dans /admin/stats/overview).
    avgResponseHeadline: formatDuration(summary.avg_response_time_ms.value),
    avgResponseHeadlineDelta: formatDelta(summary.avg_response_time_ms),
    avgResponseHeadlineCompare: "par rapport à la période précédente",
    // Un temps de réponse qui BAISSE est une bonne nouvelle : la convention
    // de couleur est inversée par rapport aux autres cartes.
    avgResponseHeadlinePositive: !isPositive(summary.avg_response_time_ms),

    usersHelped: summary.users_helped.value ?? 0,
    usersHelpedDelta: formatDelta(summary.users_helped),
    usersHelpedCompare: "par rapport à la période précédente",
    usersHelpedPositive: isPositive(summary.users_helped),

    conversationVolume: volume.points.map((point) => point.conversations),
    conversationVolumeLabels: volume.points.map((point) => point.label),

    escalationRate: summary.escalation_rate,
    handledByAgents: summary.handled_by_agents,
    conversationsWaiting: summary.conversations_waiting,

    recentActivity: activity.items.map((item, index) => ({
      id: `act-${index}`,
      time: timeLabel(item.at),
      label: item.detail ? `${item.label} — ${item.detail}` : item.label,
    })),

    services: health.services.map((service) => ({
      name: service.name,
      status: service.status,
    })),
    systemStatus: health.status,
  };
}
