/**
 * Vues secondaires de l'espace client (barre latérale du chat) : Historique,
 * FAQ, Profil. Toutes lisent le moteur -- aucune donnée d'illustration :
 *  - Historique : GET /conversations/mine (+ /mine/{id} pour le fil) ;
 *  - FAQ        : GET /faq/ (catalogue publié) + POST /faq/search (recherche
 *                 sémantique, la même que celle de l'assistant) ;
 *  - Profil     : compte utilisé par le chat et le diagnostic, et ses
 *                 réclamations (GET /conversations/mine/tickets).
 */

import { useEffect, useMemo, useState } from "react";
import { Avatar } from "../ui/Avatar";
import {
  getMyConversation,
  listFaq,
  listMyConversations,
  listMyTickets,
  searchFaq,
} from "../../services/engineClient";
import { DEFAULT_CLIENT_USER_ID, isAccountId } from "../../services/chatService";

const FAQ_CATEGORY_LABELS = {
  ACCOUNT: "Compte",
  WALLET: "Portefeuille",
  COINS: "Coins",
  VPP: "VPP",
  LPP: "LPP",
  WITHDRAWAL: "Retraits",
  NGONI_PLUS: "Ngoni+",
  KYC: "Vérification d'identité",
  PARENTAL_CONTROL: "Contrôle parental",
  GIFTS: "Cadeaux",
  ASSISTANCE: "Assistance",
  GENERAL: "Général",
};

const CONVERSATION_STATUS = {
  BOT: { label: "Assistant", tone: "neutral" },
  ESCALADE_DEMANDEE: { label: "Conseiller demandé", tone: "warn" },
  PRISE_EN_CHARGE: { label: "Avec un conseiller", tone: "brand" },
  RESOLUE: { label: "Résolue", tone: "good" },
};

const TICKET_STATUS = {
  OPEN: { label: "Ouverte", tone: "warn" },
  IN_PROGRESS: { label: "En cours", tone: "brand" },
  RESOLVED: { label: "Résolue", tone: "good" },
  CLOSED: { label: "Clôturée", tone: "neutral" },
};

function Pill({ map, value }) {
  const entry = map[value] ?? { label: value ?? "—", tone: "neutral" };
  return <span className={`ns-pill ns-pill-${entry.tone}`}>{entry.label}</span>;
}

function fold(text) {
  return text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

function dateLabel(iso) {
  if (!iso) return "—";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "—";
  return at.toLocaleString("fr-FR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

function ViewHeader({ title, subtitle, children }) {
  return (
    <header className="ns-view-header">
      <div>
        <h1 className="ns-view-title">{title}</h1>
        {subtitle && <p className="ns-view-sub">{subtitle}</p>}
      </div>
      {children}
    </header>
  );
}

function Notice({ tone = "muted", children }) {
  return <div className={`ns-notice ns-notice-${tone}`}>{children}</div>;
}

/* ---------------------------------------------------------------- Historique */

export function HistoryView({ userId, onNewChat }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);

  useEffect(() => {
    let cancelled = false;
    listMyConversations(userId)
      .then((data) => {
        if (cancelled) return;
        setRows(data);
        if (data.length) setSelectedId(data[0].conversation_id);
      })
      .catch((err) => {
        console.error("[HistoryView]", err);
        if (!cancelled) setError("Impossible de charger votre historique : le service ne répond pas.");
      });
    return () => {
      cancelled = true;
    };
  }, [userId]);

  useEffect(() => {
    if (!selectedId) return undefined;
    let cancelled = false;
    setDetail(null);
    getMyConversation(userId, selectedId)
      .then((data) => !cancelled && setDetail(data))
      .catch((err) => console.error("[HistoryView] fil :", err));
    return () => {
      cancelled = true;
    };
  }, [userId, selectedId]);

  return (
    <div className="ns-view">
      <ViewHeader title="Historique" subtitle="Vos échanges précédents avec le support Ngoni">
        <button type="button" className="ns-btn-primary" onClick={onNewChat}>
          Nouvelle conversation
        </button>
      </ViewHeader>

      {error && <Notice tone="error">{error}</Notice>}
      {!error && rows === null && <Notice>Chargement…</Notice>}
      {rows?.length === 0 && (
        <Notice>Aucune conversation pour l'instant. Vos échanges apparaîtront ici dès votre premier message.</Notice>
      )}

      {rows?.length > 0 && (
        <div className="ns-history">
          <div className="ns-history-list">
            {rows.map((row) => (
              <button
                key={row.conversation_id}
                type="button"
                className={`ns-history-item ${row.conversation_id === selectedId ? "active" : ""}`}
                onClick={() => setSelectedId(row.conversation_id)}
              >
                <span className="ns-history-row1">
                  <span className="ns-history-date">{dateLabel(row.last_message_at ?? row.created_at)}</span>
                  <Pill map={CONVERSATION_STATUS} value={row.status} />
                </span>
                <span className="ns-history-preview">{row.last_message ?? "—"}</span>
                <span className="ns-history-meta">
                  {row.message_count} message{row.message_count > 1 ? "s" : ""}
                  {row.ticket_id ? ` · réclamation ${row.ticket_id}` : ""}
                </span>
              </button>
            ))}
          </div>

          <div className="ns-history-thread">
            {!detail ? (
              <Notice>Chargement du fil…</Notice>
            ) : (
              <>
                <div className="ns-history-thread-head">
                  <span>Conversation du {dateLabel(detail.created_at)}</span>
                  <Pill map={CONVERSATION_STATUS} value={detail.status} />
                </div>
                <div className="ns-history-messages">
                  {detail.messages.map((message) => (
                    <div
                      key={message.id}
                      className={`ns-history-msg ${message.sender_role === "user" ? "is-user" : "is-other"}`}
                    >
                      <span className="ns-history-msg-who">
                        {message.sender_role === "user"
                          ? "Vous"
                          : message.sender_role === "agent"
                            ? message.agent_id ?? "Conseiller"
                            : "Ngoni"}
                        {" · "}
                        {dateLabel(message.created_at)}
                      </span>
                      <span className="ns-history-msg-text">{message.text}</span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/* ----------------------------------------------------------------------- FAQ */

export function FaqView({ onAsk }) {
  const [items, setItems] = useState(null);
  const [error, setError] = useState(null);
  const [category, setCategory] = useState("ALL");
  const [filter, setFilter] = useState("");
  const [openId, setOpenId] = useState(null);
  const [search, setSearch] = useState(null);

  useEffect(() => {
    listFaq()
      .then((data) => setItems(data.filter((item) => item.status === "PUBLISHED" && item.show_on_web !== false)))
      .catch((err) => {
        console.error("[FaqView]", err);
        setError("La FAQ est momentanément indisponible.");
      });
  }, []);

  const categories = useMemo(() => {
    const seen = new Map();
    (items ?? []).forEach((item) => seen.set(item.category, (seen.get(item.category) ?? 0) + 1));
    return [...seen.entries()];
  }, [items]);

  const visible = useMemo(() => {
    // Mots significatifs (4 lettres et plus), sans accents : une phrase entiere
    // (« mon retrait est bloqué ») doit retrouver les questions sur les retraits.
    const words = fold(filter)
      .split(/[^a-z0-9]+/)
      .filter((word) => word.length >= 4);
    return (items ?? [])
      .filter((item) => category === "ALL" || item.category === category)
      .filter((item) => {
        if (!words.length) return true;
        const haystack = fold(`${item.question} ${item.answer} ${item.keywords.join(" ")}`);
        return words.some((word) => haystack.includes(word));
      })
      .sort((a, b) => Number(b.is_featured) - Number(a.is_featured) || a.sort_order - b.sort_order);
  }, [items, category, filter]);

  async function runSearch(event) {
    event.preventDefault();
    const question = filter.trim();
    if (!question) return;
    setSearch({ loading: true, question });
    try {
      const result = await searchFaq(question);
      setSearch({ question, ...result });
    } catch (err) {
      console.error("[FaqView] recherche :", err);
      setSearch({ question, failed: true });
    }
  }

  return (
    <div className="ns-view">
      <ViewHeader title="Questions fréquentes" subtitle="Les réponses de l'équipe Ngoni, mises à jour en continu" />

      <form className="ns-faq-search" onSubmit={runSearch}>
        <input
          value={filter}
          onChange={(event) => {
            setFilter(event.target.value);
            setSearch(null);
          }}
          placeholder="Rechercher une question (ex. : mon retrait est bloqué)"
          spellCheck={false}
        />
        <button type="submit" className="ns-btn-primary" disabled={!filter.trim()}>
          Demander
        </button>
      </form>

      {search && (
        <div className="ns-faq-answer">
          {search.loading ? (
            <span className="ns-view-sub">Recherche de la meilleure réponse…</span>
          ) : search.failed ? (
            <span className="ns-view-sub">La recherche n'a pas abouti. Réessayez dans un instant.</span>
          ) : search.answer ? (
            <>
              <div className="ns-faq-answer-label">Meilleure réponse</div>
              <p>{search.answer}</p>
            </>
          ) : (
            <>
              <div className="ns-faq-answer-label">Pas de réponse exacte</div>
              {search.suggestions?.length > 0 ? (
                <p>Questions proches : {search.suggestions.map((s) => s.question).join(" · ")}</p>
              ) : (
                <p>Aucune question de la FAQ ne correspond.</p>
              )}
            </>
          )}
          {!search.loading && (
            <button type="button" className="ns-btn-outline" onClick={() => onAsk(search.question)}>
              Poser la question à l'assistant
            </button>
          )}
        </div>
      )}

      {error && <Notice tone="error">{error}</Notice>}
      {!error && items === null && <Notice>Chargement…</Notice>}

      {items && (
        <>
          <div className="ns-chips">
            <button
              type="button"
              className={`ns-chip ${category === "ALL" ? "active" : ""}`}
              onClick={() => setCategory("ALL")}
            >
              Toutes <span>{items.length}</span>
            </button>
            {categories.map(([key, count]) => (
              <button
                key={key}
                type="button"
                className={`ns-chip ${category === key ? "active" : ""}`}
                onClick={() => setCategory(key)}
              >
                {FAQ_CATEGORY_LABELS[key] ?? key} <span>{count}</span>
              </button>
            ))}
          </div>

          {visible.length === 0 && <Notice>Aucune question ne correspond à ce filtre.</Notice>}
          <div className="ns-faq-list">
            {visible.map((item) => (
              <div key={item.id} className={`ns-faq-item ${openId === item.id ? "open" : ""}`}>
                <button
                  type="button"
                  className="ns-faq-q"
                  onClick={() => setOpenId(openId === item.id ? null : item.id)}
                  aria-expanded={openId === item.id}
                >
                  <span>{item.question}</span>
                  <span className="ns-faq-cat">{FAQ_CATEGORY_LABELS[item.category] ?? item.category}</span>
                </button>
                {openId === item.id && (
                  <div className="ns-faq-a">
                    <p>{item.answer}</p>
                    <button type="button" className="ns-link-btn" onClick={() => onAsk(item.question)}>
                      Je n'ai pas trouvé ma réponse — en parler à l'assistant
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------- Profil */

export function ProfileView({ userId, photo, onChangeAccount, onOpenHistory }) {
  const [tickets, setTickets] = useState(null);
  const [conversations, setConversations] = useState(null);
  const [error, setError] = useState(null);
  const [draft, setDraft] = useState(userId);
  const [formError, setFormError] = useState(null);

  useEffect(() => {
    setDraft(userId);
    let cancelled = false;
    Promise.all([listMyTickets(userId), listMyConversations(userId)])
      .then(([ticketRows, conversationRows]) => {
        if (cancelled) return;
        setTickets(ticketRows);
        setConversations(conversationRows);
        setError(null);
      })
      .catch((err) => {
        console.error("[ProfileView]", err);
        if (!cancelled) setError("Impossible de charger votre dossier : le service ne répond pas.");
      });
    return () => {
      cancelled = true;
    };
  }, [userId]);

  function submit(event) {
    event.preventDefault();
    if (!isAccountId(draft)) {
      setFormError("Identifiant invalide : un identifiant de compte Ngoni a la forme xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx.");
      return;
    }
    setFormError(null);
    onChangeAccount(draft.trim().toLowerCase());
  }

  const openTickets = (tickets ?? []).filter((t) => t.status === "OPEN" || t.status === "IN_PROGRESS").length;

  return (
    <div className="ns-view">
      <ViewHeader title="Profil" subtitle="Le compte Ngoni utilisé par l'assistant pour vos démarches" />

      <div className="ns-profile-card">
        <Avatar name="Compte Ngoni" src={photo} size={64} />
        <div className="ns-profile-who">
          <div className="ns-profile-name">Compte Ngoni connecté</div>
          <code className="ns-profile-id">{userId}</code>
          <div className="ns-view-sub">
            C'est ce compte que l'assistant interroge lorsqu'il vérifie un retrait, une recharge ou votre statut KYC.
          </div>
        </div>
      </div>

      {error && <Notice tone="error">{error}</Notice>}

      <div className="ns-stat-row">
        <button type="button" className="ns-stat" onClick={onOpenHistory}>
          <span className="ns-stat-value">{conversations?.length ?? "—"}</span>
          <span className="ns-stat-label">conversations</span>
        </button>
        <div className="ns-stat">
          <span className="ns-stat-value">{tickets?.length ?? "—"}</span>
          <span className="ns-stat-label">réclamations</span>
        </div>
        <div className="ns-stat">
          <span className="ns-stat-value">{tickets ? openTickets : "—"}</span>
          <span className="ns-stat-label">en cours de traitement</span>
        </div>
      </div>

      <section className="ns-section">
        <h2 className="ns-section-title">Mes réclamations</h2>
        {tickets === null && !error && <Notice>Chargement…</Notice>}
        {tickets?.length === 0 && <Notice>Aucune réclamation enregistrée pour ce compte.</Notice>}
        {tickets?.length > 0 && (
          <div className="ns-ticket-list">
            {tickets.map((ticket) => (
              <div key={ticket.ticket_id} className="ns-ticket">
                <div className="ns-ticket-row1">
                  <strong>{ticket.ticket_id}</strong>
                  <Pill map={TICKET_STATUS} value={ticket.status} />
                </div>
                <div className="ns-ticket-desc">{ticket.summary || ticket.description}</div>
                <div className="ns-history-meta">
                  {ticket.category} · créée le {dateLabel(ticket.created_at)}
                  {ticket.assigned_to ? ` · suivie par ${ticket.assigned_to}` : ""}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="ns-section">
        <h2 className="ns-section-title">Changer de compte</h2>
        <form className="ns-account-form" onSubmit={submit}>
          <input value={draft} onChange={(event) => setDraft(event.target.value)} spellCheck={false} />
          <button type="submit" className="ns-btn-primary" disabled={draft.trim().toLowerCase() === userId}>
            Utiliser ce compte
          </button>
          {userId !== DEFAULT_CLIENT_USER_ID && (
            <button type="button" className="ns-btn-outline" onClick={() => onChangeAccount(DEFAULT_CLIENT_USER_ID)}>
              Compte par défaut
            </button>
          )}
        </form>
        {formError && <Notice tone="error">{formError}</Notice>}
        <p className="ns-view-sub">
          Aucune authentification dans cet environnement : le compte se choisit ici. Changer de compte démarre une nouvelle
          conversation.
        </p>
      </section>
    </div>
  );
}
