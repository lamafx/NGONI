import { useEffect, useMemo, useState } from "react";
import { AdminShell } from "../components/layout/AdminShell";
import { Icon } from "../components/ui/Icon";
import { listFaq, searchFaq } from "../services/engineClient";
import { useDemoAdminTour } from "../hooks/useDemoAdminTour";

/**
 * Base de connaissances -- branchee sur le VRAI catalogue FAQ du moteur
 * (GET /faq/). La recherche passe par POST /faq/search, c'est-a-dire la
 * recherche semantique par embeddings reellement utilisee par l'agent, pas
 * un filtre texte cote navigateur : on voit donc exactement ce que l'agent
 * verrait pour la meme question.
 */
export function AdminKnowledgePage() {
  const [entries, setEntries] = useState(null);
  const [error, setError] = useState(null);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState(null);
  const [searching, setSearching] = useState(false);
  const [openId, setOpenId] = useState(null);

  useEffect(() => {
    let cancelled = false;
    listFaq()
      .then((d) => !cancelled && setEntries(Array.isArray(d) ? d : []))
      .catch((e) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, []);

  // Deuxieme etape du parcours d'administration en demonstration (elle a
  // remplace les statistiques). L'appel est ici, AVANT les retours anticipes
  // du rendu : un crochet ne peut pas etre conditionnel -- sans quoi la page
  // ne defilerait pas et, surtout, ne passerait jamais la main aux
  // parametres, le parcours s'arretant sur elle.
  useDemoAdminTour("/admin/base-connaissances");

  const categories = useMemo(() => {
    if (!entries) return [];
    const counts = new Map();
    entries.forEach((e) => counts.set(e.category ?? "—", (counts.get(e.category ?? "—") ?? 0) + 1));
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [entries]);

  async function runSearch(e) {
    e?.preventDefault();
    const q = query.trim();
    if (!q) {
      setResults(null);
      return;
    }
    setSearching(true);
    try {
      const d = await searchFaq(q);
      setResults(d);
    } catch (err) {
      setError(err.message);
    } finally {
      setSearching(false);
    }
  }

  const shown = results?.results ?? results?.matches ?? null;

  return (
    <AdminShell active="base-connaissances" title="Base de connaissances" subtitle="Catalogue interrogé par l'agent">
      {error && (
        <div className="kb-error">
          Le moteur ne répond pas ({error}). Vérifiez qu'il tourne sur le port 8000.
        </div>
      )}

      <form className="kb-search" onSubmit={runSearch}>
        <Icon name="search" size={16} />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Poser une question comme le ferait un utilisateur…"
        />
        <button type="submit" className="btn btn-primary btn-sm" disabled={searching}>
          {searching ? "Recherche…" : "Rechercher"}
        </button>
        {results && (
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => {
              setResults(null);
              setQuery("");
            }}
          >
            Effacer
          </button>
        )}
      </form>
      <p className="kb-hint">
        Recherche sémantique par embeddings — la même que celle utilisée par l'agent en conversation.
      </p>

      {entries && (
        <div className="kb-summary">
          <div>
            <span className="kb-num">{entries.length}</span>
            <span className="kb-num-label">entrées publiées</span>
          </div>
          <div className="kb-cats">
            {categories.map(([c, n]) => (
              <span className="kb-cat" key={c}>
                {c} <b>{n}</b>
              </span>
            ))}
          </div>
        </div>
      )}

      {results && (
        <section className="kb-results">
          <h3>Ce que l'agent répondrait</h3>
          <div className={`kb-answer status-${results.flow?.status ?? "unknown"}`}>
            <div className="kb-answer-head">
              <span className="kb-answer-status">
                {results.flow?.status === "matched" ? "Réponse trouvée" : "Aucune correspondance suffisante"}
              </span>
              {results.flow?.note && <span className="kb-score">{results.flow.note}</span>}
            </div>
            {results.flow?.matched_question && (
              <div className="kb-answer-q">{results.flow.matched_question}</div>
            )}
            {results.answer && <p className="kb-answer-body">{results.answer}</p>}
            {results.flow?.route && <span className="kb-route">{results.flow.route}</span>}
          </div>

          {results.suggestions?.length > 0 && (
            <div className="kb-suggestions">
              <span className="kb-sugg-label">Suggestions proposées</span>
              {results.suggestions.map((sg, i) => (
                <span className="kb-sugg" key={sg.question ?? sg.slug ?? i}>
                  {sg.question ?? sg}
                </span>
              ))}
            </div>
          )}
        </section>
      )}

      <section className="kb-list">
        {!entries && !error && <p className="kb-empty">Chargement du catalogue…</p>}
        {entries?.map((e) => (
          <article className={`kb-item ${openId === e.id ? "is-open" : ""}`} key={e.id}>
            <button type="button" className="kb-item-head" onClick={() => setOpenId(openId === e.id ? null : e.id)}>
              <span className="kb-item-cat">{e.category}</span>
              <span className="kb-item-q">{e.question}</span>
              <Icon name="chevron-down" size={14} />
            </button>
            {openId === e.id && <div className="kb-item-a">{e.answer}</div>}
          </article>
        ))}
      </section>
    </AdminShell>
  );
}
