/**
 * Ce qui merite une notification, espace par espace -- reconstruit a chaque
 * sondage depuis l'etat reel du moteur (voir hooks/useNotifications.js).
 * L'`id` de chaque notification encode l'etat observe : quand un ticket
 * change de statut, c'est une NOUVELLE notification (non lue), l'ancienne
 * disparait d'elle-meme.
 */

import {
  getSystemHealth,
  listComplaints,
  listConversations,
  listDiagnosticSessions,
  listMyConversations,
  listMyDocuments,
  listMyTickets,
  listPendingDocuments,
} from "./engineClient";

const TICKET_TEXT = {
  OPEN: { title: "Réclamation enregistrée", tone: "info" },
  IN_PROGRESS: { title: "Votre réclamation est en cours de traitement", tone: "warn" },
  RESOLVED: { title: "Votre réclamation est résolue", tone: "good" },
  CLOSED: { title: "Votre réclamation est clôturée", tone: "good" },
};

/* ---------- Espace client ------------------------------------------------- */

export async function loadClientNotifications(userId) {
  const [tickets, conversations, documents] = await Promise.all([
    listMyTickets(userId),
    listMyConversations(userId),
    listMyDocuments(userId),
  ]);
  const items = [];

  // Examen de la piece d'identite par un conseiller humain.
  documents.slice(0, 5).forEach((document) => {
    const label = document.document_type === "passport" ? "passeport" : "pièce d'identité";
    if (document.review_status === "approved") {
      items.push({
        id: `doc:${document.document_id}:approved`,
        at: document.reviewed_at,
        title: "Votre identité a été vérifiée par un conseiller",
        body: `Votre ${label} est validée : votre compte est désormais vérifié.`,
        tone: "good",
        action: { view: "profil" },
      });
    } else if (document.review_status === "rejected") {
      items.push({
        id: `doc:${document.document_id}:rejected`,
        at: document.reviewed_at,
        title: "Votre pièce d'identité a été refusée",
        body: document.review_reason ? `Motif : ${document.review_reason}` : undefined,
        tone: "risk",
        action: { view: "chat" },
      });
    } else if (document.review_status === "pending") {
      items.push({
        id: `doc:${document.document_id}:pending`,
        at: document.created_at,
        title: "Pièce d'identité reçue",
        body: "Un conseiller va la vérifier.",
        tone: "warn",
        action: { view: "chat" },
      });
    }
  });

  tickets.slice(0, 15).forEach((ticket) => {
    const text = TICKET_TEXT[ticket.status] ?? { title: `Réclamation : ${ticket.status}`, tone: "info" };
    items.push({
      id: `ticket:${ticket.ticket_id}:${ticket.status}`,
      at: ticket.updated_at ?? ticket.created_at,
      title: text.title,
      body: `${ticket.ticket_id} · ${ticket.summary || ticket.description}`,
      tone: text.tone,
      action: { view: "profil" },
    });
  });

  conversations.slice(0, 15).forEach((conversation) => {
    if (conversation.status === "PRISE_EN_CHARGE") {
      items.push({
        id: `conv:${conversation.conversation_id}:assigned:${conversation.assigned_to}`,
        at: conversation.assigned_at ?? conversation.last_message_at,
        title: "Un conseiller a pris votre demande en charge",
        body: conversation.assigned_to ? `Conseiller : ${conversation.assigned_to}` : undefined,
        tone: "good",
        action: { view: "chat" },
      });
    } else if (conversation.status === "ESCALADE_DEMANDEE") {
      items.push({
        id: `conv:${conversation.conversation_id}:waiting`,
        at: conversation.escalated_at ?? conversation.last_message_at,
        title: "Votre demande de conseiller est transmise",
        body: "Un conseiller va reprendre la conversation.",
        tone: "warn",
        action: { view: "chat" },
      });
    } else if (conversation.status === "RESOLUE" && conversation.resolved_by) {
      items.push({
        id: `conv:${conversation.conversation_id}:resolved`,
        at: conversation.resolved_at,
        title: "Conversation clôturée par le conseiller",
        body: conversation.last_message ?? undefined,
        tone: "good",
        action: { view: "historique" },
      });
    }
  });

  return items;
}

/* ---------- Espace conseiller --------------------------------------------- */

export async function loadAgentNotifications(agentId) {
  const [waiting, mine, documents] = await Promise.all([
    listConversations({ status: "ESCALADE_DEMANDEE", limit: 30 }),
    listConversations({ status: "PRISE_EN_CHARGE", assignedTo: agentId, limit: 30 }),
    listPendingDocuments(),
  ]);
  return [
    ...documents.map((document) => ({
      id: `doc-pending:${document.document_id}`,
      at: document.created_at,
      title: "Pièce d'identité à vérifier",
      body: `Compte ${document.user_id}${document.conversation_id ? ` · conversation #${document.conversation_id}` : ""}`,
      tone: "warn",
      action: document.conversation_id
        ? { conversationId: document.conversation_id, view: "toutes", openFile: true }
        : undefined,
    })),
    ...waiting.map((row) => ({
      id: `waiting:${row.conversation_id}:${row.escalated_at}`,
      at: row.escalated_at ?? row.last_message_at,
      title: `Un usager attend un conseiller — #${row.conversation_id}`,
      body: row.escalation_reason ? `Motif : ${row.escalation_reason}` : row.last_message ?? undefined,
      tone: "warn",
      action: { conversationId: row.conversation_id, view: "attente" },
    })),
    // Seul un message de l'USAGER merite d'alerter : les reponses du
    // conseiller lui-meme ne sont pas une nouveaute pour lui.
    ...mine.filter((row) => row.last_message_role === "user").map((row) => ({
      id: `mine:${row.conversation_id}:${row.last_message_at}`,
      at: row.last_message_at,
      title: `Nouveau message de l'usager — #${row.conversation_id}`,
      body: row.last_message ?? undefined,
      tone: "info",
      action: { conversationId: row.conversation_id, view: "mes" },
    })),
  ];
}

/* ---------- Administration ------------------------------------------------- */

export async function loadAdminNotifications() {
  // allSettled : une source en echec (ex. sonde de sante lente) ne doit pas
  // vider tout le panneau.
  const [waiting, tickets, health, diagnostics] = await Promise.allSettled([
    listConversations({ status: "ESCALADE_DEMANDEE", limit: 20 }),
    listComplaints({ status: "OPEN", limit: 8 }),
    getSystemHealth(),
    listDiagnosticSessions({ days: 1, status: "ESCALATED", limit: 5 }),
  ]);
  if ([waiting, tickets, health, diagnostics].every((r) => r.status === "rejected")) {
    throw waiting.reason;
  }
  const items = [];

  if (waiting.status === "fulfilled") {
    waiting.value.forEach((row) =>
      items.push({
        id: `escalade:${row.conversation_id}:${row.escalated_at}`,
        at: row.escalated_at ?? row.last_message_at,
        title: `Escalade en attente — #${row.conversation_id}`,
        body: row.escalation_reason ? `Motif : ${row.escalation_reason}` : "Aucun conseiller ne l'a encore prise.",
        tone: "warn",
        action: { path: `/agent/live?vue=attente&id=${encodeURIComponent(row.conversation_id)}` },
      })
    );
  }
  if (tickets.status === "fulfilled") {
    tickets.value.forEach((ticket) =>
      items.push({
        id: `ticket:${ticket.ticket_id}:OPEN`,
        at: ticket.created_at,
        title: `Nouvelle demande ${ticket.ticket_id}`,
        body: `${ticket.category} · ${ticket.summary || ticket.description}`,
        tone: ticket.urgency === "high" ? "risk" : "info",
        action: { path: "/admin/demandes" },
      })
    );
  }
  if (health.status === "fulfilled") {
    health.value.services
      .filter((service) => service.status !== "operational")
      .forEach((service) =>
        items.push({
          id: `sante:${service.name}:${service.status}`,
          at: health.value.checked_at,
          title: `${service.name} : ${service.status === "down" ? "injoignable" : "dégradé"}`,
          body: service.detail || "Vérifier que le serveur est démarré (utils.txt).",
          tone: "risk",
          action: { path: "/admin" },
        })
      );
  }
  if (diagnostics.status === "fulfilled") {
    diagnostics.value.items.forEach((session) =>
      items.push({
        id: `diag:${session.session_id}:${session.updated_at}`,
        at: session.updated_at,
        title: `Diagnostic escaladé — ${session.problem ?? "problème inconnu"}`,
        body: session.last_outcome_detail ? `Cause : ${session.last_outcome_detail}` : undefined,
        tone: "warn",
        action: { path: "/admin/diagnostics" },
      })
    );
  }
  return items;
}
