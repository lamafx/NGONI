/**
 * Espace Admin → Capacités : ce que l'assistant comprend et résout, et ce que
 * le conseiller humain peut faire. Les listes viennent des sources vivantes --
 * les intentions du modèle Rasa chargé (GET /rasa/domain) et le catalogue du
 * Diagnostic Engine (GET /diagnostic/capabilities, agrégé depuis les
 * manifestes des services wallet et user) : ajouter un problème à un
 * manifeste le fait apparaître ici sans modifier cette page.
 */

import { useEffect, useMemo, useState } from "react";
import { AdminShell } from "../components/layout/AdminShell";
import { Icon } from "../components/ui/Icon";
import { Kpi, LoadState } from "../components/admin/adminUi";
import { debugClassifyDiagnostic, listCapabilities } from "../services/engineClient";

const RASA_BASE = import.meta.env.VITE_RASA_URL || "/rasa";

// Ce que chaque intention declenche cote assistant (rasa/domain.yml, actions).
const INTENTS = {
  greet: ["Accueil", "Salutation", "Accueille l'usager, rappelle sa dernière demande s'il revient (mémoire entre conversations)."],
  goodbye: ["Accueil", "Au revoir", "Clôt poliment l'échange."],
  bot_challenge: ["Accueil", "« Es-tu un robot ? »", "Se présente comme assistant virtuel et propose un conseiller humain."],
  ask_capabilities: ["Accueil", "Capacités", "Explique ce que l'assistant sait faire."],
  ask_faq: ["Information", "Question fréquente", "Recherche sémantique dans la FAQ publiée, propose les questions proches."],
  browse_faq: ["Information", "Parcourir la FAQ", "Affiche les catégories de la FAQ."],
  select_faq: ["Information", "Choix d'un thème ou d'une question", "Liste les questions du thème choisi, ou donne la réponse de la question choisie."],
  diagnostic: ["Diagnostic", "Problème à résoudre", "Identifie le problème parmi le catalogue, collecte les informations utiles, interroge le service concerné et explique la cause."],
  create_reclamation: ["Réclamation", "Ouvrir une réclamation", "Formulaire guidé (catégorie, urgence, date, description) puis création du ticket."],
  plainte: ["Réclamation", "Mécontentement", "Accuse réception du mécontentement et propose une réclamation."],
  ask_complaint_status: ["Réclamation", "Suivi d'une réclamation", "Retrouve les tickets du compte et leur statut."],
  suggestion: ["Réclamation", "Suggestion", "Enregistre la suggestion de l'usager."],
  request_human_agent: ["Conseiller", "Demander un conseiller", "Place la conversation dans la file des conseillers humains."],
  cancel_human_agent_request: ["Conseiller", "Annuler la demande", "Retire la conversation de la file : l'assistant garde la main."],
  rate_response: ["Qualité", "Avis sur une réponse", "Enregistre l'avis, utile ou pas utile (statistiques de qualité)."],
  out_of_scope: ["Garde-fous", "Hors sujet", "Recentre poliment sur le support NGONI."],
  inappropriate_language: ["Garde-fous", "Langage inapproprié", "Rappelle les règles de courtoisie sans couper l'échange."],
  affirm: ["Confirmation", "Oui", "Confirme l'étape en cours (diagnostic, réclamation...)."],
  deny: ["Confirmation", "Non", "Refuse ou corrige l'étape en cours."],
};
const CONFIRMATIONS = new Set(["affirm", "deny"]);

const SERVICE_LABELS = { wallet: "Portefeuille (wallet service)", user: "Compte (user service)" };

const AGENT_ACTIONS = [
  ["Prendre en charge", "Le bot se tait sur la conversation : le conseiller répond à sa place.", "Poste conseiller"],
  ["Répondre", "Message en direct dans le chat du client (relevé toutes les 5 s).", "Poste conseiller"],
  ["Envoyer une pièce jointe", "Image ou PDF transmis au client dans la conversation.", "Poste conseiller"],
  ["Transférer", "Confie la conversation à un autre conseiller.", "Poste conseiller"],
  ["Clore", "Termine l'échange : l'assistant reprend la main.", "Poste conseiller"],
  ["Consulter le dossier client", "Compte, historique KYC, portefeuille, pièces, échanges — consultation tracée.", "Dossier client"],
  ["Confronter pièce et compte", "Nom, date de naissance, nationalité, validité — lus par OCR et comparés automatiquement.", "Dossier client"],
  ["Valider l'identité", "Met le compte en « vérifié » (user service), trace la décision, notifie le client.", "Dossier client"],
  ["Refuser une pièce", "Refus motivé, compte « refusé », client notifié avec le motif.", "Dossier client"],
  ["Note interne", "Visible des seuls conseillers, tracée au journal.", "Dossier client"],
  ["Envoyer et clore le dossier", "Réponse proposée, clôture de la conversation et des réclamations ouvertes en un geste.", "Dossier client"],
  ["Attribuer / changer le statut d'une demande", "Réclamations : attribution à un conseiller, en cours, résolue, clôturée.", "Administration → Demandes"],
];

export function AdminCapabilitiesPage() {
  const [intents, setIntents] = useState(null);
  const [problems, setProblems] = useState(null);
  const [error, setError] = useState(null);
  const [probe, setProbe] = useState({});

  useEffect(() => {
    fetch(`${RASA_BASE}/domain`, { headers: { Accept: "application/json" } })
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`Rasa ${res.status}`))))
      .then((domain) => setIntents(domain.intents.map((i) => (typeof i === "string" ? i : Object.keys(i)[0]))))
      .catch((err) => {
        console.error("[AdminCapabilitiesPage] intentions :", err);
        setError("Rasa injoignable : les intentions ne peuvent pas être listées.");
      });
    listCapabilities()
      .then((data) => setProblems(data.problems))
      .catch((err) => {
        console.error("[AdminCapabilitiesPage] problèmes :", err);
        setError("Moteur injoignable : le catalogue de diagnostic ne peut pas être affiché.");
      });
  }, []);

  const groupedIntents = useMemo(() => {
    const groups = new Map();
    (intents ?? []).forEach((name) => {
      const [group] = INTENTS[name] ?? ["Autres"];
      groups.set(group, [...(groups.get(group) ?? []), name]);
    });
    return [...groups.entries()];
  }, [intents]);

  const byService = useMemo(() => {
    const groups = new Map();
    (problems ?? []).forEach((p) => groups.set(p.service, [...(groups.get(p.service) ?? []), p]));
    return [...groups.entries()];
  }, [problems]);

  async function test(problem) {
    const phrase = problem.example_phrases?.[0] ?? problem.label;
    setProbe((prev) => ({ ...prev, [problem.id]: { loading: true } }));
    try {
      const result = await debugClassifyDiagnostic(phrase);
      const top = result.candidates[0];
      setProbe((prev) => ({ ...prev, [problem.id]: { phrase, top, ok: top.problem_id === problem.id } }));
    } catch {
      setProbe((prev) => ({ ...prev, [problem.id]: { failed: true } }));
    }
  }

  const requestIntents = (intents ?? []).filter((i) => !CONFIRMATIONS.has(i)).length;

  return (
    <AdminShell active="capacites" title="Capacités" subtitle="Ce que l'assistant comprend et résout, et ce que le conseiller peut faire">
      <LoadState error={error} loading={!error && (intents === null || problems === null)} />

      <div className="kpi-grid">
        <Kpi
          label="Intentions comprises"
          value={intents ? intents.length : "—"}
          sub={intents ? `${requestIntents} demandes + ${intents.length - requestIntents} confirmations (oui / non)` : ""}
        />
        <Kpi
          label="Problèmes résolus automatiquement"
          value={problems ? problems.length : "—"}
          sub={byService.map(([service, list]) => `${list.length} ${service}`).join(" · ")}
        />
        <Kpi label="Actions du conseiller humain" value={AGENT_ACTIONS.length} sub="dossier client compris" />
        <Kpi label="Sources" value="en direct" sub="modèle Rasa chargé + manifestes des services" />
      </div>

      {intents && (
        <div className="card card-pad">
          <div className="section-head">
            <h3>Intentions de l'assistant</h3>
          </div>
          <div className="tickets-table-wrap">
            <table className="tickets-table">
              <thead>
                <tr>
                  <th>Famille</th>
                  <th>Intention</th>
                  <th>Ce que fait l'assistant</th>
                </tr>
              </thead>
              <tbody>
                {groupedIntents.flatMap(([group, names]) =>
                  names.map((name, index) => (
                    <tr key={name}>
                      <td style={{ fontWeight: 600, fontSize: "0.8rem" }}>{index === 0 ? group : ""}</td>
                      <td>
                        <div style={{ fontWeight: 600 }}>{INTENTS[name]?.[1] ?? name}</div>
                        <code style={{ fontSize: "0.72rem", color: "var(--ink-faint)" }}>{name}</code>
                      </td>
                      <td style={{ fontSize: "0.82rem" }}>{INTENTS[name]?.[2] ?? "—"}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {byService.map(([service, list]) => (
        <div key={service} className="card card-pad">
          <div className="section-head">
            <h3>
              Problèmes résolus — {SERVICE_LABELS[service] ?? service} ({list.length})
            </h3>
          </div>
          <div className="tickets-table-wrap">
            <table className="tickets-table">
              <thead>
                <tr>
                  <th>Problème</th>
                  <th>Exemple de demande</th>
                  <th>Informations demandées</th>
                  <th>Vérifier le routage</th>
                </tr>
              </thead>
              <tbody>
                {list.map((problem) => {
                  const state = probe[problem.id];
                  return (
                    <tr key={problem.id}>
                      <td>
                        <div style={{ fontWeight: 600 }}>{problem.label}</div>
                        <div style={{ fontSize: "0.76rem", color: "var(--ink-muted)", maxWidth: 380 }}>{problem.description}</div>
                      </td>
                      <td style={{ fontSize: "0.8rem", fontStyle: "italic" }}>« {problem.example_phrases?.[0] ?? "—"} »</td>
                      <td style={{ fontSize: "0.8rem" }}>
                        {problem.required_fields.length
                          ? problem.required_fields.map((f) => f.name).join(", ")
                          : "aucune (compte de l'usager)"}
                      </td>
                      <td style={{ fontSize: "0.78rem", minWidth: 150 }}>
                        {!state && (
                          <button type="button" className="btn btn-secondary btn-sm" onClick={() => test(problem)}>
                            <Icon name="search" size={13} /> Tester
                          </button>
                        )}
                        {state?.loading && "…"}
                        {state?.failed && <span style={{ color: "var(--risk)" }}>échec du test</span>}
                        {state?.top && (
                          <span style={{ color: state.ok ? "var(--good)" : "var(--risk)", fontWeight: 600 }}>
                            {state.ok ? "✓ reconnu" : `✗ → ${state.top.problem_id}`} ({state.top.score.toFixed(2)})
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      ))}

      <div className="card card-pad">
        <div className="section-head">
          <h3>Ce que le conseiller humain peut faire</h3>
        </div>
        <div className="tickets-table-wrap">
          <table className="tickets-table">
            <thead>
              <tr>
                <th>Action</th>
                <th>Effet</th>
                <th>Où</th>
              </tr>
            </thead>
            <tbody>
              {AGENT_ACTIONS.map(([action, effect, where]) => (
                <tr key={action}>
                  <td style={{ fontWeight: 600 }}>{action}</td>
                  <td style={{ fontSize: "0.82rem" }}>{effect}</td>
                  <td style={{ fontSize: "0.78rem", color: "var(--ink-muted)" }}>{where}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </AdminShell>
  );
}
