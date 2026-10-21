// Tons alignés sur dashbord.jpeg : "En cours" est corail, "Résolu" est vert
// émeraude -- pas de troisième teinte inventée, "Nouveau"/"En attente"
// restent neutres (gris ardoise).
const CONVERSATION_LABELS = {
  active: { label: "En cours", tone: "badge-risk" },
  escalated: { label: "Escaladée", tone: "badge-risk" },
  resolved: { label: "Résolue", tone: "badge-good" },
  pending: { label: "En attente", tone: "badge-warn" },
};

// "nouveau" -> "En attente" : un ticket qui n'a pas encore ete pris en main
// se lit mieux ainsi, et ca aligne le vocabulaire sur la carte "Assistance
// humaine" cote client (voir ChatPage.jsx / HandoffPanel). "en_cours" passe
// au bleu (badge-info) pour ne plus se confondre avec le rouge des priorites
// elevees dans le tableau des demandes (voir AdminPage.jsx).
const TICKET_LABELS = {
  nouveau: { label: "En attente", tone: "badge-brand" },
  en_cours: { label: "En cours", tone: "badge-info" },
  resolu: { label: "Résolu", tone: "badge-good" },
};

const PRIORITY_LABELS = {
  elevee: { label: "Élevée", tone: "badge-risk" },
  moyenne: { label: "Moyenne", tone: "badge-warn" },
  basse: { label: "Basse", tone: "badge-neutral" },
};

export function ConversationStatusBadge({ status }) {
  const s = CONVERSATION_LABELS[status];
  return (
    <span className={`badge ${s.tone}`}>
      <span className="badge-dot" />
      {s.label}
    </span>
  );
}

export function TicketStatusBadge({ status }) {
  const s = TICKET_LABELS[status];
  return (
    <span className={`badge ${s.tone}`}>
      <span className="badge-dot" />
      {s.label}
    </span>
  );
}

export function TicketPriorityBadge({ priority }) {
  const s = PRIORITY_LABELS[priority] ?? PRIORITY_LABELS.moyenne;
  return <span className={`badge ${s.tone}`}>{s.label}</span>;
}

export function ServiceStatusBadge({ status }) {
  const map = {
    operational: { label: "Opérationnel", tone: "badge-good" },
    degraded: { label: "Dégradé", tone: "badge-warn" },
    down: { label: "Indisponible", tone: "badge-risk" },
  };
  const s = map[status];
  return (
    <span className={`badge ${s.tone}`}>
      <span className="badge-dot" />
      {s.label}
    </span>
  );
}
