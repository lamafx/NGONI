import { useEffect, useRef, useState } from "react";
import { AdminShell, ADMIN_USER } from "../components/layout/AdminShell";
import { Icon } from "../components/ui/Icon";
import { useDemoStore } from "../state/DemoStore";
import { SYSTEM_PARAMETERS } from "../data/systemParameters";
import {
  clearParameterHistory,
  listParameterHistory,
  listParameterOverrides,
  updateParameter,
} from "../services/engineClient";
import { useDemoAdminTour } from "../hooks/useDemoAdminTour";
import { DemoCursor, useDemoStage } from "../components/demo/DemoStage";
import { clearOverlay, showOverlay } from "../services/demoOverlay";
import { adminAct, demoParametersReady, isDemoMode, wait } from "../services/demoDirector";

const PARAM_BY_ID = Object.fromEntries(SYSTEM_PARAMETERS.flatMap((g) => g.items).map((item) => [item.id, item]));

const [DEFAULT_FIRST_NAME, DEFAULT_LAST_NAME = ""] = ADMIN_USER.name.split(" ");

function formatValue(value, format) {
  if (format === "pct") return `${Math.round(value * 100)} %`;
  if (format === "seconds") return `${value} s`;
  return String(value);
}

function toEditableNumber(value, format) {
  return format === "pct" ? Math.round(value * 100) : value;
}

function fromEditableNumber(input, format) {
  const n = Number(input);
  return format === "pct" ? n / 100 : n;
}

export function AdminSettingsPage() {
  const { state, dispatch } = useDemoStore();
  const [editingId, setEditingId] = useState(null);
  const [draftValue, setDraftValue] = useState("");
  const [pendingChange, setPendingChange] = useState(null);

  // Surcharges et historique lus DEPUIS LE MOTEUR : ces valeurs sont
  // persistees en base (ia.system_parameters / ia.system_parameter_history),
  // elles ne vivent plus seulement dans le navigateur.
  const [remote, setRemote] = useState({ overrides: {}, history: [], loaded: false, error: null });

  useEffect(() => {
    let cancelled = false;
    // En demonstration, la lecture attend la remise a zero lancee au depart
    // (voir demoDirector.resetDemoParameters) : lue trop tot, elle
    // afficherait encore le seuil et le journal de la prise precedente.
    demoParametersReady()
      .then(() => Promise.all([listParameterOverrides(), listParameterHistory()]))
      .then(([ov, hist]) => {
        if (cancelled) return;
        const map = {};
        (ov ?? []).forEach((o) => {
          map[o.param_id] = o.value;
        });
        setRemote({ overrides: map, history: hist ?? [], loaded: true, error: null });
      })
      .catch((e) => !cancelled && setRemote((r) => ({ ...r, loaded: true, error: e.message })));
    return () => {
      cancelled = true;
    };
  }, []);

  function currentValue(item) {
    // La valeur du moteur fait foi ; le magasin local ne sert que de repli si
    // le moteur est injoignable.
    return remote.overrides[item.id] ?? state.parameterOverrides[item.id] ?? item.value;
  }

  function startEdit(item) {
    setEditingId(item.id);
    setDraftValue(String(toEditableNumber(currentValue(item), item.format)));
  }

  function cancelEdit() {
    setEditingId(null);
    setDraftValue("");
  }

  function confirmDraft(item) {
    const newValue = fromEditableNumber(draftValue, item.format);
    if (Number.isNaN(newValue)) return;
    const oldValue = currentValue(item);
    setEditingId(null);
    if (newValue === oldValue) return;
    // La saisie du nom/prénom (voir TraceabilityModal) est un prealable
    // obligatoire a l'ecriture, pas une formalite optionnelle -- rien n'est
    // dispatché tant que ce n'est pas confirmé.
    setPendingChange({ id: item.id, label: item.label, oldValue, newValue });
  }

  async function applyPendingChange({ firstName, lastName }) {
    const changedBy = `${firstName} ${lastName}`.trim();
    const { id, label, oldValue, newValue } = pendingChange;
    setPendingChange(null);

    // Rien a ecrire si la valeur ne bouge pas. `confirmDraft` filtre deja ce
    // cas pour une saisie humaine, mais la scene de demonstration appelle
    // cette fonction DIRECTEMENT : c'est par la qu'un « 75 % → 75 % » se
    // retrouvait dans le journal, presente comme une modification. Le
    // garde-fou est donc ici, au dernier point de passage commun.
    if (newValue === oldValue) return;

    // Le journal local d'abord, l'ecriture distante ensuite. La ligne doit
    // apparaitre a l'instant ou l'on confirme : c'est ce que l'oeil attend, et
    // le moteur peut mettre plusieurs secondes a repondre -- ou ne pas
    // repondre du tout. L'ecriture distante fait toujours foi : au retour,
    // l'historique du moteur remplace celui-ci (voir le rendu plus bas).
    dispatch({
      type: "UPDATE_PARAMETER",
      id,
      label,
      oldValue,
      value: newValue,
      changedBy,
      changedAt: new Date().toISOString(),
    });

    try {
      await updateParameter(id, newValue, changedBy);
      const [ov, hist] = await Promise.all([listParameterOverrides(), listParameterHistory()]);
      const map = {};
      (ov ?? []).forEach((o) => {
        map[o.param_id] = o.value;
      });
      setRemote({ overrides: map, history: hist ?? [], loaded: true, error: null });
    } catch (e) {
      setRemote((r) => ({ ...r, error: e.message }));
    }
  }

  const [clearingHistory, setClearingHistory] = useState(false);

  /** Vide le journal des modifications -- cote moteur ET cote magasin local
   *  (ce dernier sert de repli quand le moteur ne repond pas ; le laisser
   *  plein afficherait des lignes fantomes apres la purge). Les valeurs
   *  courantes ne sont pas touchees : effacer une trace ne remet pas le
   *  reglage qu'elle documente a sa valeur par defaut. */
  async function purgeHistory() {
    if (!window.confirm("Vider définitivement l'historique des modifications ? Les seuils en vigueur ne changent pas.")) {
      return;
    }
    setClearingHistory(true);
    try {
      await clearParameterHistory();
      dispatch({ type: "CLEAR_PARAMETER_HISTORY" });
      setRemote((r) => ({ ...r, history: [], error: null }));
    } catch (e) {
      setRemote((r) => ({ ...r, error: e.message }));
    } finally {
      setClearingHistory(false);
    }
  }

  // ---- Acte III, derniere scene : la main reste humaine -------------------
  // Deux actes viennent de montrer un agent qui comprend, agit et sait
  // s'arreter. Reste la question que le jury va poser : qui le regle, et
  // qu'est-ce qui en garde la trace ? On modifie donc un seuil du moteur a
  // l'ecran -- celui qui arbitre entre l'agent et le conseiller -- on le
  // confirme sous une identite, et on va relire la ligne dans le journal.
  const stage = useDemoStage();
  const sceneRef = useRef(false);

  // Reperes de la scene : la ligne du seuil, sa valeur, la coche de
  // validation, le bouton de la modale, le journal.
  const demoRow = useRef(null);
  const demoValueBtn = useRef(null);
  const demoOkBtn = useRef(null);
  const demoModalConfirm = useRef(null);
  const historyCard = useRef(null);

  // La scene est armee une seule fois (voir useDemoAdminTour) : elle ne verrait
  // donc que l'etat du premier rendu. Ce relais est reecrit a chaque rendu --
  // c'est par lui, et jamais par la fermeture, qu'elle lit la valeur courante
  // du seuil et declenche l'ecriture.
  const latest = useRef(null);
  latest.current = { currentValue, applyPendingChange };

  async function clickTarget(el, travelMs) {
    if (!el) return;
    stage.moveCursorTo(el);
    await wait(travelMs);
    await stage.clickCursor();
    el.classList?.add("demo-pressed");
    setTimeout(() => el.classList?.remove("demo-pressed"), 240);
  }

  async function flashOverlay(overlay) {
    if (!overlay) return;
    showOverlay(overlay);
    await wait(overlay.ms ?? 2400);
    clearOverlay();
  }

  async function runSettingsScene(tourState) {
    const cfg = adminAct().settings;
    const item = PARAM_BY_ID[cfg.paramId];
    if (!item) return;
    sceneRef.current = true;
    const alive = () => !tourState.cancelled && sceneRef.current;

    // 1. Le seuil est amene au centre de l'ecran avant qu'on le touche.
    demoRow.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    await wait(cfg.scrollToParamMs);
    if (!alive()) return;

    // 2. Clic sur la valeur : le champ s'ouvre.
    const oldValue = latest.current.currentValue(item);
    await clickTarget(demoValueBtn.current, cfg.cursorTravelMs);
    if (!alive()) return;
    setEditingId(item.id);
    setDraftValue(String(toEditableNumber(oldValue, item.format)));
    await wait(cfg.beforeEdit);
    if (!alive()) return;

    // 3. La nouvelle valeur se tape chiffre par chiffre -- on doit voir une
    //    main derriere le changement, pas une valeur qui se substitue.
    //
    //    Le seuil etant persiste en base, une demonstration rejouee retrouve
    //    la valeur ecrite la fois d'avant : taper 75 sur un seuil deja a 75
    //    n'aurait rien change, tout en l'annoncant comme une modification. On
    //    prend donc celle des deux valeurs du scenario qui n'est pas la
    //    valeur courante -- il y a toujours un vrai changement a montrer.
    const displayedOld = toEditableNumber(oldValue, item.format);
    const target = displayedOld === cfg.newValue ? cfg.altValue ?? cfg.newValue : cfg.newValue;
    const typed = String(target);
    setDraftValue("");
    await wait(cfg.typing.leadIn);
    for (let i = 1; i <= typed.length; i += 1) {
      if (!alive()) return;
      setDraftValue(typed.slice(0, i));
      await wait(cfg.typing.charMs + Math.random() * cfg.typing.jitterMs);
    }
    // Les valeurs reelles complètent l'incrustation : ecrites en dur, elles
    // mentaient des que la valeur de depart n'etait plus celle attendue.
    await flashOverlay({
      ...cfg.editOverlay,
      lines: [...cfg.editOverlay.lines, `${displayedOld} % → ${target} %`],
    });
    if (!alive()) return;
    await wait(cfg.afterType);
    if (!alive()) return;

    // 4. Clic sur la coche : rien n'est ecrit, la modale d'identite s'ouvre.
    const newValue = fromEditableNumber(typed, item.format);
    await clickTarget(demoOkBtn.current, cfg.cursorTravelMs);
    if (!alive()) return;
    setEditingId(null);
    setPendingChange({ id: item.id, label: item.label, oldValue, newValue });
    await wait(cfg.beforeModal);
    if (!alive()) return;

    // 5. C'est le point de la scene : on ne change pas un seuil anonymement.
    await flashOverlay(cfg.confirmOverlay);
    if (!alive()) return;
    await wait(cfg.readModalMs);
    if (!alive()) return;

    // 6. Confirmation. L'ecriture part avec le nom de la personne connectee.
    await clickTarget(demoModalConfirm.current, cfg.cursorTravelMs);
    if (!alive()) return;
    latest.current.applyPendingChange({ firstName: DEFAULT_FIRST_NAME, lastName: DEFAULT_LAST_NAME });
    await wait(cfg.afterConfirm);
    if (!alive()) return;

    // 7. Et la trace : qui, quoi, quand -- relue dans le journal. Le curseur
    //    suit jusqu'a la ligne : laisse la ou la modale se trouvait, il
    //    designerait le vide.
    historyCard.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    await wait(cfg.scrollToHistoryMs);
    if (!alive()) return;
    stage.moveCursorTo(historyCard.current?.querySelector(".history-row") ?? historyCard.current);
    await wait(cfg.cursorTravelMs);
    if (!alive()) return;
    await flashOverlay(cfg.traceOverlay);
    if (!alive()) return;
    await wait(cfg.readHistoryMs);
    stage.hideCursor();
  }

  // Derniere etape du parcours d'administration en demonstration : cet ecran
  // n'est pas parcouru, il est manipule.
  useDemoAdminTour("/admin/settings", runSettingsScene);

  useEffect(() => () => {
    sceneRef.current = false;
  }, []);

  const demoParamId = isDemoMode() ? adminAct().settings?.paramId : null;

  return (
    <AdminShell active="settings" title="Paramètres" subtitle="Seuils et réglages actuels du moteur Ngoni">
      <div className="settings-notice">
        <Icon name="alert" size={16} />
        <span>
          Ces valeurs partent de la configuration réelle du backend, mais une modification ici reste locale à cette
          démo (aucune route n'existe encore côté FastAPI/Rasa pour les réécrire — voir{" "}
          <code>api_admin_a_developper.md</code>). Chaque changement exige votre identité et reste tracé dans
          l'historique ci-dessous.
        </span>
      </div>

      <div className="settings-groups">
        {SYSTEM_PARAMETERS.map((group) => (
          <div className="card card-pad settings-group" key={group.group}>
            <h3 className="settings-group-title">{group.group}</h3>
            <p className="settings-group-desc">{group.description}</p>
            <div className="settings-items">
              {group.items.map((item) => {
                const value = currentValue(item);
                const isEditing = editingId === item.id;
                const isModified = currentValue(item) !== item.value;

                const isDemoTarget = item.id === demoParamId;

                return (
                  <div className="settings-item" key={item.id} ref={isDemoTarget ? demoRow : undefined}>
                    <div className="settings-item-head">
                      <span className="settings-item-label">
                        {item.label}
                        {isModified && <span className="settings-item-badge">modifié</span>}
                      </span>

                      {isEditing ? (
                        <div className="settings-item-edit">
                          <input
                            type="number"
                            className="settings-item-input"
                            value={draftValue}
                            onChange={(e) => setDraftValue(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") confirmDraft(item);
                              if (e.key === "Escape") cancelEdit();
                            }}
                            step={item.format === "pct" ? 1 : item.step}
                            min={0}
                            max={item.format === "pct" ? 100 : undefined}
                            autoFocus
                          />
                          <span className="settings-item-unit">
                            {item.format === "pct" ? "%" : item.format === "seconds" ? "s" : ""}
                          </span>
                          <button
                            type="button"
                            className="settings-icon-btn"
                            ref={isDemoTarget ? demoOkBtn : undefined}
                            onClick={() => confirmDraft(item)}
                            aria-label="Valider"
                          >
                            <Icon name="check" size={13} />
                          </button>
                          <button type="button" className="settings-icon-btn" onClick={cancelEdit} aria-label="Annuler">
                            <Icon name="x" size={13} />
                          </button>
                        </div>
                      ) : (
                        <button
                          type="button"
                          className="settings-item-value"
                          ref={isDemoTarget ? demoValueBtn : undefined}
                          onClick={() => startEdit(item)}
                        >
                          {formatValue(value, item.format)}
                          <Icon name="edit" size={12} />
                        </button>
                      )}
                    </div>

                    {item.format === "pct" && (
                      <div className="settings-value-bar">
                        <div className="settings-value-fill" style={{ width: `${Math.round(value * 100)}%` }} />
                      </div>
                    )}
                    <div className="settings-item-source">{item.source}</div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      <div className="card card-pad" ref={historyCard}>
        <div className="history-head">
          <div>
            <h3 style={{ fontSize: "0.95rem", fontWeight: 700, marginBottom: 4 }}>Historique des modifications</h3>
            <p className="settings-group-desc">
              Chaque changement de seuil, avec l'identité de la personne qui l'a effectué.
            </p>
          </div>
          {(remote.history.length ? remote.history : state.parameterHistory).length > 0 && (
            <button
              type="button"
              className="btn btn-ghost btn-sm history-purge"
              onClick={purgeHistory}
              disabled={clearingHistory}
            >
              <Icon name="x" size={14} /> {clearingHistory ? "Suppression…" : "Vider l'historique"}
            </button>
          )}
        </div>
        {(remote.history.length ? remote.history : state.parameterHistory).length === 0 ? (
          <p className="empty-hint">Aucune modification pour le moment.</p>
        ) : (
          <div className="history-list">
            {(remote.history.length ? remote.history : state.parameterHistory).map((raw) => {
              // Le moteur renvoie ses champs en snake_case, le magasin local
              // en camelCase : on ramene les deux a une seule forme.
              const h = {
                id: raw.id,
                paramId: raw.paramId ?? raw.param_id,
                oldValue: raw.oldValue ?? raw.old_value,
                newValue: raw.newValue ?? raw.new_value,
                changedBy: raw.changedBy ?? raw.changed_by,
                changedAt: raw.changedAt ?? raw.changed_at,
                label: raw.label,
              };
              const param = PARAM_BY_ID[h.paramId];
              h.label = h.label ?? param?.label ?? h.paramId;
              return (
                <div className="history-row" key={h.id}>
                  <div className="history-main">
                    <span className="history-label">{h.label}</span>
                    <span className="history-change">
                      {param ? formatValue(h.oldValue, param.format) : h.oldValue} →{" "}
                      <strong>{param ? formatValue(h.newValue, param.format) : h.newValue}</strong>
                    </span>
                  </div>
                  <div className="history-meta">
                    <span className="history-author">
                      <Icon name="user-check" size={13} /> {h.changedBy}
                    </span>
                    <span className="history-date">{h.changedAt ? new Date(h.changedAt).toLocaleString("fr-FR") : "—"}</span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {pendingChange && (
        <TraceabilityModal
          change={pendingChange}
          format={PARAM_BY_ID[pendingChange.id]?.format}
          confirmRef={demoModalConfirm}
          onCancel={() => setPendingChange(null)}
          onConfirm={applyPendingChange}
        />
      )}

      {/* Scene de la demonstration : plein cadre et fixe, pour que le curseur
          reste juste au-dessus de sa cible meme quand la page defile, et
          par-dessus la modale -- sinon le clic de confirmation se jouerait
          derriere elle, invisible. */}
      {isDemoMode() && (
        <div className="demo-stage-admin" ref={stage.stageRef}>
          <DemoCursor cursor={stage.cursor} />
        </div>
      )}
    </AdminShell>
  );
}

function TraceabilityModal({ change, format, confirmRef, onCancel, onConfirm }) {
  const [firstName, setFirstName] = useState(DEFAULT_FIRST_NAME ?? "");
  const [lastName, setLastName] = useState(DEFAULT_LAST_NAME ?? "");
  const canSubmit = firstName.trim().length > 0 && lastName.trim().length > 0;

  return (
    <div
      className="modal-overlay"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <div className="modal-card">
        <h3 className="modal-title">Confirmer la modification</h3>
        <p className="modal-summary">
          <strong>{change.label}</strong>
          <br />
          {formatValue(change.oldValue, format)} → <strong>{formatValue(change.newValue, format)}</strong>
        </p>
        <p className="modal-hint">Ce changement est tracé — merci d'indiquer votre identité avant de valider.</p>
        <div className="modal-field-row">
          <label className="modal-field">
            Prénom
            <input value={firstName} onChange={(e) => setFirstName(e.target.value)} autoFocus />
          </label>
          <label className="modal-field">
            Nom
            <input value={lastName} onChange={(e) => setLastName(e.target.value)} />
          </label>
        </div>
        <div className="modal-actions">
          <button type="button" className="btn btn-secondary" onClick={onCancel}>
            Annuler
          </button>
          <button
            type="button"
            className="btn btn-primary"
            ref={confirmRef}
            disabled={!canSubmit}
            onClick={() => onConfirm({ firstName: firstName.trim(), lastName: lastName.trim() })}
          >
            Confirmer la modification
          </button>
        </div>
      </div>
    </div>
  );
}
