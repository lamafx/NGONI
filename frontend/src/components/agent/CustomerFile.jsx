/**
 * Dossier client du conseiller humain (poste /agent/live).
 *
 * Tout vient du moteur (GET /admin/support/users/{id}), qui assemble ce qui
 * appartient a chaque service : le compte et son historique KYC (user
 * service), le portefeuille (wallet service), la piece d'identite envoyee
 * dans le chat et sa lecture OCR, les conversations, reclamations et le
 * journal des actions. Le conseiller confronte la piece au compte puis
 * decide ; sa decision met reellement a jour le compte (KYC), et chaque
 * ouverture du dossier comme chaque decision est tracee.
 */

import { useCallback, useEffect, useState } from "react";
import { Icon } from "../ui/Icon";
import { Avatar } from "../ui/Avatar";
import { addCustomerNote, decideIdentity, fetchDocumentImage, getCustomerFile } from "../../services/engineClient";

const REFUSAL_REASONS = [
  "Photo floue : mentions illisibles",
  "Pièce expirée",
  "Nom différent de celui du compte",
  "Date de naissance différente de celle du compte",
  "Document non conforme ou altéré",
];

const KYC_STATUS = {
  VERIFIED: { label: "Vérifiée", tone: "badge-good" },
  REJECTED: { label: "Refusée", tone: "badge-risk" },
  SUBMITTED: { label: "Pièce en examen", tone: "badge-warn" },
  PENDING: { label: "Non vérifiée", tone: "badge-neutral" },
};

const SUBMISSION_STATUS = {
  approved: { label: "approuvée", tone: "badge-good" },
  rejected: { label: "refusée", tone: "badge-risk" },
  pending: { label: "en attente", tone: "badge-warn" },
};

const REVIEW_STATUS = {
  pending: { label: "À vérifier", tone: "badge-warn" },
  approved: { label: "Validée", tone: "badge-good" },
  rejected: { label: "Refusée", tone: "badge-risk" },
  not_applicable: { label: "Refusée par le filtre", tone: "badge-neutral" },
};

const ACTION_LABELS = {
  dossier_consulte: "a consulté le dossier",
  identite_validee: "a validé l'identité",
  identite_refusee: "a refusé la pièce",
  note_interne: "a ajouté une note",
};

const VERDICT = {
  ok: { icon: "check-circle", label: "concordant", className: "cf-ok" },
  ko: { icon: "alert", label: "différent", className: "cf-ko" },
  na: { icon: "help", label: "non vérifiable", className: "cf-na" },
};

function Badge({ map, value }) {
  const entry = map[value] ?? { label: value ?? "—", tone: "badge-neutral" };
  return (
    <span className={`badge ${entry.tone}`}>
      <span className="badge-dot" />
      {entry.label}
    </span>
  );
}

function when(iso, withTime = true) {
  if (!iso) return "—";
  // Les dates du schema `users` sont en UTC sans fuseau : sans le « Z », le
  // navigateur les lirait comme heure locale (2 h d'ecart).
  const at = new Date(/T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(iso) ? `${iso}Z` : iso);
  if (Number.isNaN(at.getTime())) return "—";
  return at.toLocaleString("fr-FR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
  });
}

function money(amount, currency) {
  if (amount === null || amount === undefined) return "—";
  return `${Number(amount).toLocaleString("fr-FR")} ${currency === "XOF" ? "FCFA" : currency ?? ""}`;
}

function Field({ label, children }) {
  return (
    <div className="cf-field">
      <span className="cf-field-label">{label}</span>
      <span className="cf-field-value">{children ?? "—"}</span>
    </div>
  );
}

export function CustomerFile({ userId, conversationId, agentId, onClose, onDecided }) {
  const [file, setFile] = useState(null);
  const [error, setError] = useState(null);
  const [imageUrl, setImageUrl] = useState(null);
  const [busy, setBusy] = useState(false);
  const [refusing, setRefusing] = useState(false);
  const [reason, setReason] = useState(REFUSAL_REASONS[0]);
  const [otherReason, setOtherReason] = useState("");
  const [note, setNote] = useState("");
  const [actionError, setActionError] = useState(null);

  // Ouverture = consultation nominative : tracee une fois, a l'ouverture.
  useEffect(() => {
    let cancelled = false;
    getCustomerFile(userId, { agentId, conversationId })
      .then((data) => !cancelled && setFile(data))
      .catch((err) => {
        console.error("[CustomerFile]", err);
        if (!cancelled) setError(err.status === 404 ? "Aucun compte NGONI ne correspond à cet usager." : "Dossier indisponible (moteur injoignable).");
      });
    return () => {
      cancelled = true;
    };
  }, [userId, agentId, conversationId]);

  const document = file?.documents.find((d) => d.document_id === file.compared_document_id) ?? null;

  useEffect(() => {
    if (!document?.has_image) {
      setImageUrl(null);
      return undefined;
    }
    let url = null;
    let cancelled = false;
    fetchDocumentImage(document.document_id)
      .then((objectUrl) => {
        url = objectUrl;
        if (!cancelled) setImageUrl(objectUrl);
      })
      .catch((err) => console.error("[CustomerFile] image :", err));
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [document?.document_id, document?.has_image]);

  useEffect(() => {
    function onKey(event) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const act = useCallback(async (action) => {
    setBusy(true);
    setActionError(null);
    try {
      setFile(await action());
      return true;
    } catch (err) {
      console.error("[CustomerFile] action :", err);
      setActionError(err.detail || err.message);
      return false;
    } finally {
      setBusy(false);
    }
  }, []);

  async function decide(decision) {
    const motive = decision === "rejected" ? (reason === "Autre" ? otherReason.trim() : reason) : null;
    if (decision === "rejected" && !motive) {
      setActionError("Indiquez le motif du refus.");
      return;
    }
    const ok = await act(() =>
      decideIdentity(userId, {
        agentId,
        decision,
        reason: motive,
        documentId: document?.document_id,
        conversationId,
      })
    );
    if (ok) {
      setRefusing(false);
      onDecided?.(decision, motive);
    }
  }

  async function saveNote() {
    const text = note.trim();
    if (!text) return;
    if (await act(() => addCustomerNote(userId, { agentId, text, conversationId }))) setNote("");
  }

  const account = file?.account;
  const wallet = file?.wallet;
  const comparison = file?.comparison ?? [];
  const mismatches = comparison.filter((row) => row.verdict === "ko").length;

  return (
    <div className="cf-overlay" role="dialog" aria-label="Dossier client" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="cf-drawer">
        <header className="cf-head">
          <div className="cf-head-who">
            <Avatar name={account?.display_name ?? userId} size={44} />
            <div>
              <div className="cf-head-name">{account?.display_name ?? "Usager"}</div>
              <div className="cf-head-sub">
                {account?.username ? `@${account.username} · ` : ""}
                <code>{userId}</code>
              </div>
            </div>
            {account && <Badge map={KYC_STATUS} value={account.kyc_status} />}
          </div>
          <button type="button" className="btn btn-ghost btn-icon" onClick={onClose} aria-label="Fermer le dossier">
            <Icon name="x" size={18} />
          </button>
        </header>

        <div className="cf-trace">
          <Icon name="eye" size={14} /> Consultation tracée au journal : {agentId}, {when(new Date().toISOString())}.
        </div>

        {error && <div className="cf-error">{error}</div>}
        {!error && !file && <div className="cf-loading">Chargement du dossier…</div>}

        {file && (
          <div className="cf-body">
            {/* ---------------- Colonne gauche : la piece et la decision -------- */}
            <section className="cf-col">
              <div className="card card-pad cf-card">
                <div className="cf-card-title">
                  <span>Pièce d'identité</span>
                  {document && <Badge map={REVIEW_STATUS} value={document.review_status} />}
                </div>
                {!document ? (
                  <p className="empty-hint">Aucune pièce d'identité reçue pour ce compte.</p>
                ) : (
                  <>
                    <div className="cf-doc-image">
                      {imageUrl ? <img src={imageUrl} alt="Pièce d'identité envoyée par l'usager" /> : <span>Image indisponible</span>}
                    </div>
                    <div className="cf-doc-meta">
                      {document.filename} · reçue le {when(document.created_at)}
                      {document.mrz_valid !== null && ` · MRZ ${document.mrz_valid ? "valide" : "incohérente"}`}
                    </div>
                    <div className="cf-grid">
                      {document.fields.map((field) => (
                        <Field key={field.key} label={field.label}>
                          {field.value}
                        </Field>
                      ))}
                    </div>
                  </>
                )}
              </div>

              {document && (
                <div className="card card-pad cf-card">
                  <div className="cf-card-title">
                    <span>Confrontation pièce ↔ compte</span>
                    <span className={mismatches ? "cf-ko" : "cf-ok"}>
                      {mismatches ? `${mismatches} écart${mismatches > 1 ? "s" : ""}` : "aucun écart"}
                    </span>
                  </div>
                  <table className="cf-compare">
                    <thead>
                      <tr>
                        <th />
                        <th>Pièce</th>
                        <th>Compte NGONI</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {comparison.map((row) => {
                        const verdict = VERDICT[row.verdict] ?? VERDICT.na;
                        return (
                          <tr key={row.label}>
                            <th>{row.label}</th>
                            <td>{row.document}</td>
                            <td>{row.account}</td>
                            <td className={verdict.className} title={verdict.label}>
                              <Icon name={verdict.icon} size={15} /> {verdict.label}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                  <p className="cf-hint">
                    Confrontation automatique : elle prépare la décision, elle ne la prend pas.
                  </p>

                  {document.review_status === "pending" ? (
                    <div className="cf-decision">
                      {!refusing ? (
                        <div className="cf-decision-actions">
                          <button type="button" className="btn btn-primary" disabled={busy} onClick={() => decide("approved")}>
                            <Icon name="check" size={15} /> Valider l'identité
                          </button>
                          <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => setRefusing(true)}>
                            <Icon name="x" size={15} /> Refuser la pièce
                          </button>
                        </div>
                      ) : (
                        <div className="cf-refuse">
                          <label className="cf-field-label" htmlFor="cf-reason">Motif du refus</label>
                          <select id="cf-reason" value={reason} onChange={(e) => setReason(e.target.value)} className="cf-input">
                            {[...REFUSAL_REASONS, "Autre"].map((r) => (
                              <option key={r}>{r}</option>
                            ))}
                          </select>
                          {reason === "Autre" && (
                            <input
                              className="cf-input"
                              value={otherReason}
                              onChange={(e) => setOtherReason(e.target.value)}
                              placeholder="Précisez le motif"
                            />
                          )}
                          <div className="cf-decision-actions">
                            <button type="button" className="btn btn-primary" disabled={busy} onClick={() => decide("rejected")}>
                              Confirmer le refus
                            </button>
                            <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => setRefusing(false)}>
                              Annuler
                            </button>
                          </div>
                        </div>
                      )}
                      <p className="cf-hint">
                        La décision met à jour la vérification d'identité du compte (user service), est tracée au
                        journal et notifiée à l'usager.
                      </p>
                    </div>
                  ) : (
                    <div className={`cf-decided ${document.review_status === "approved" ? "cf-ok" : "cf-ko"}`}>
                      <Icon name={document.review_status === "approved" ? "check-circle" : "alert"} size={16} />
                      {document.review_status === "approved" ? "Identité validée" : "Pièce refusée"} par{" "}
                      {document.reviewed_by} le {when(document.reviewed_at)}
                      {document.review_reason ? ` — ${document.review_reason}` : ""}
                    </div>
                  )}
                  {actionError && <div className="cf-error">{actionError}</div>}
                </div>
              )}
            </section>

            {/* ---------------- Colonne droite : le compte -------------------- */}
            <section className="cf-col">
              <div className="card card-pad cf-card">
                <div className="cf-card-title">
                  <span>Compte NGONI</span>
                  <span className="cf-source">user service</span>
                </div>
                {file.account_error && <div className="cf-error">{file.account_error}</div>}
                {account && (
                  <div className="cf-grid">
                    <Field label="Nom affiché">{account.display_name}</Field>
                    <Field label="Date de naissance">{account.date_of_birth?.split("-").reverse().join("/")}</Field>
                    <Field label="Téléphone">{account.phone_number}</Field>
                    <Field label="Ville / pays">{[account.city, account.country].filter(Boolean).join(", ")}</Field>
                    <Field label="Statut du compte">{account.status}</Field>
                    <Field label="Vérification">
                      {KYC_STATUS[account.kyc_status]?.label ?? account.kyc_status} (niveau {account.kyc_level})
                    </Field>
                    <Field label="Membre depuis">{when(account.created_at, false)}</Field>
                    <Field label="Dernière activité">{when(account.last_active_at)}</Field>
                    <Field label="Audience">
                      {account.followers_count} abonnés · {account.videos_count} vidéos
                    </Field>
                    <Field label="Ngoni+">{account.is_ngoni_plus ? "oui" : "non"}</Field>
                  </div>
                )}
                {account?.kyc_submissions?.length > 0 && (
                  <>
                    <div className="cf-subtitle">Historique de vérification</div>
                    <ul className="cf-list">
                      {account.kyc_submissions.map((s) => (
                        <li key={s.id}>
                          <span>{when(s.created_at)}</span>
                          <Badge map={SUBMISSION_STATUS} value={s.status} />
                          {s.rejection_reason && <span className="cf-muted">{s.rejection_reason}</span>}
                        </li>
                      ))}
                    </ul>
                  </>
                )}
              </div>

              <div className="card card-pad cf-card">
                <div className="cf-card-title">
                  <span>Portefeuille</span>
                  <span className="cf-source">wallet service</span>
                </div>
                {wallet ? (
                  <>
                    <div className="cf-grid">
                      <Field label="Solde">{money(wallet.balance, wallet.currency)}</Field>
                      <Field label="Statut">{wallet.status}{wallet.frozen_reason ? ` — ${wallet.frozen_reason}` : ""}</Field>
                    </div>
                    <ul className="cf-list">
                      {wallet.transactions.map((t) => (
                        <li key={t.reference}>
                          <span>{when(t.created_at, false)}</span>
                          <span>{t.type}</span>
                          <span>{money(t.amount, t.currency)}</span>
                          <span className={t.status === "FAILED" ? "cf-ko" : "cf-muted"}>{t.status}</span>
                        </li>
                      ))}
                    </ul>
                  </>
                ) : (
                  <p className="empty-hint">{file.wallet_error ?? "Aucun portefeuille pour ce compte."}</p>
                )}
              </div>

              <div className="card card-pad cf-card">
                <div className="cf-card-title">
                  <span>Échanges avec le support</span>
                </div>
                <ul className="cf-list">
                  {file.conversations.map((c) => (
                    <li key={c.conversation_id}>
                      <span>{when(c.last_message_at)}</span>
                      <span>#{c.conversation_id}</span>
                      <span className="cf-muted">{c.status}</span>
                    </li>
                  ))}
                  {file.tickets.map((t) => (
                    <li key={t.ticket_id}>
                      <span>{when(t.created_at)}</span>
                      <span>{t.ticket_id}</span>
                      <span className="cf-muted">{t.status}</span>
                    </li>
                  ))}
                  {!file.conversations.length && !file.tickets.length && <li className="cf-muted">Aucun échange.</li>}
                </ul>
              </div>

              <div className="card card-pad cf-card">
                <div className="cf-card-title">
                  <span>Note interne et journal</span>
                </div>
                <textarea
                  className="cf-input"
                  rows={2}
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="Note visible des seuls conseillers…"
                />
                <div style={{ display: "flex", justifyContent: "flex-end" }}>
                  <button type="button" className="btn btn-secondary btn-sm" disabled={busy || !note.trim()} onClick={saveNote}>
                    <Icon name="note" size={14} /> Ajouter la note
                  </button>
                </div>
                <ul className="cf-list cf-journal">
                  {file.actions.map((a, index) => (
                    <li key={`${a.at}-${index}`}>
                      <span>{when(a.at)}</span>
                      <span>
                        <strong>{a.agent_id ?? "—"}</strong> {ACTION_LABELS[a.action_type] ?? a.action_type}
                        {a.detail ? ` : ${a.detail}` : ""}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            </section>
          </div>
        )}
      </div>
    </div>
  );
}
