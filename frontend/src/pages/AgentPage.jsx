import { useEffect, useRef, useState } from "react";
import { Sidebar } from "../components/layout/Sidebar";
import { Avatar } from "../components/ui/Avatar";
import { Icon } from "../components/ui/Icon";
import { MessageBubble } from "../components/chat/MessageBubble";
import { ConversationStatusBadge } from "../components/ui/StatusBadge";
import { Timeline } from "../components/Timeline";
import { useDemoStore } from "../state/DemoStore";
import { AGENTS } from "../data/mockData";
import { DEMO_ID_EXTRACTION, DEMO_PROFILE } from "../data/demoScenario1";
// Repli quand la conversation ne porte pas la piece reellement soumise
// (rechargement de page, scenario rejoue) -- meme image que celle de demo/.
import cniRecto from "../assets/demo-cni-recto.png";
// Photo de profil du client, telle qu'elle figure sur son compte NGONI.
import clientPhoto from "../assets/demo-client-avatar.jpeg";
import ngoniIcon from "../assets/ngoni-support-icon.jpeg";
import { nextId, nowLabel } from "../services/mockLatency";
import { useNavigate } from "react-router-dom";
import { DemoCursor, useDemoStage } from "../components/demo/DemoStage";
import { clearOverlay, showOverlay } from "../services/demoOverlay";
import {
  agentAct,
  currentAct,
  isDemoMode,
  keystrokeDelayFor,
  setAct,
  wait,
} from "../services/demoDirector";

// Conseiller connecte a l'espace Agent. AGENTS[0] est Ibrahim Traoré, le
// meme que celui annonce au client lors de l'escalade (voir DEMO_ADVISOR) --
// sans quoi le client verrait arriver un nom et le jury un autre.
const ACTING_AGENT = AGENTS[0];

/** Duree d'attente de l'appel, au format d'un poste telephonique. */
function formatWait(seconds) {
  const m = String(Math.floor(seconds / 60)).padStart(2, "0");
  const s = String(seconds % 60).padStart(2, "0");
  return `${m}:${s}`;
}

export function AgentPage() {
  const { state, dispatch } = useDemoStore();
  const escalated = state.conversations.filter((c) => c.status === "escalated");
  const others = state.conversations.filter((c) => c.status !== "escalated");
  const defaultId = escalated[0]?.id ?? state.conversations[0]?.id;

  const [activeId, setActiveId] = useState(defaultId);
  const [reply, setReply] = useState("");

  // Le PROFIL CLIENT. Il recouvre le fil, comme une fiche qu'on ouvre par
  // dessus une conversation : le conseiller n'est plus en train de repondre,
  // il est en train de verifier. `identityValidated` est ce que le clic sur
  // « Valider l'identité » change reellement -- les champs extraits par
  // l'agent passent de « en cours de vérification » a « validé ». C'est la
  // seule ecriture humaine de tout le parcours.
  const [showProfile, setShowProfile] = useState(false);
  const [identityValidated, setIdentityValidated] = useState(false);
  const [note, setNote] = useState("");
  const threadEndRef = useRef(null);
  const replyGhostRef = useRef(null);

  useEffect(() => {
    if (escalated.length && !state.conversations.some((c) => c.id === activeId && c.status === "escalated")) {
      setActiveId(escalated[0].id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [escalated.length]);

  const active = state.conversations.find((c) => c.id === activeId) ?? state.conversations[0];

  // L'APPEL ENTRANT. Le dossier est escalade, mais personne ne l'a encore
  // accepte : tant que `assignedAgent` est vide, le conseiller n'est PAS dans
  // la conversation. Il ne lit ni le fil, ni le dossier, et ne peut pas
  // ecrire. Decrocher, c'est cliquer sur « Prise en charge » -- et c'est ce
  // clic, lui seul, qui le fait entrer dans le chat cote client.
  const pendingPickup = active?.status === "escalated" && !active.assignedAgent;

  // La piece que le client a REELLEMENT envoyee dans l'acte I : elle voyage
  // dans le fil (message de variante "attachment"), le conseiller la retrouve
  // donc telle quelle. Le repli sur l'image du depot ne sert qu'aux
  // rechargements de page, ou le fil est reconstruit sans le dataUrl.
  const submittedPiece = active?.messages?.find((m) => m.variant === "attachment" && m.attachment)?.attachment;

  // La sonnerie compte, comme sur un vrai poste : l'appel n'attend pas
  // gratuitement, on voit le temps passer tant que personne ne repond.
  const [ringSeconds, setRingSeconds] = useState(0);
  useEffect(() => {
    if (!pendingPickup) return undefined;
    setRingSeconds(0);
    const id = setInterval(() => setRingSeconds((s) => s + 1), 1000);
    return () => clearInterval(id);
  }, [pendingPickup]);

  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [active?.messages.length]);

  function sendReply() {
    const text = reply.trim();
    if (!text) return;
    dispatch({
      type: "ADD_MESSAGE",
      conversationId: active.id,
      message: { id: nextId("msg"), sender: "agent", text, time: nowLabel() },
    });
    setReply("");
  }

  /** Decrocher. Le dossier passe au nom du conseiller ET la conversation
   *  s'ouvre : c'est le seul endroit qui ecrit « a rejoint la conversation »,
   *  cette ligne remplace, cote client, la mise en relation en cours. Un
   *  dossier deja pris en charge ne la reecrit pas. */
  function acceptHandover(agentName) {
    const conv = state.conversations.find((c) => c.id === activeIdRef.current);
    if (conv?.assignedAgent) return;
    dispatch({ type: "ASSIGN_AGENT", conversationId: activeIdRef.current, agent: agentName });
    pushToThread({
      id: nextId("msg"),
      sender: "system",
      text: `${agentName} a rejoint la conversation`,
      time: nowLabel(),
    });
  }

  function takeOver() {
    acceptHandover(ACTING_AGENT.name);
  }

  /** La note interne n'est pas un champ decoratif : elle part dans le fil, ou
   *  le conseiller la relit -- et le client ne la voit jamais (voir
   *  MessageBubble, sender "note"). */
  function saveNote() {
    const text = note.trim();
    if (!text) return;
    pushToThread({
      id: nextId("msg"),
      sender: "note",
      authorName: ACTING_AGENT.name,
      text,
      time: nowLabel(),
    });
    setNote("");
  }

  function resolveConversation() {
    dispatch({ type: "SET_STATUS", conversationId: active.id, status: "resolved" });
    const ticket = state.tickets.find((t) => t.conversationId === active.id);
    if (ticket) dispatch({ type: "SET_TICKET_STATUS", ticketId: ticket.id, status: "resolu" });
  }

  // ---- Acte II de la demonstration : le conseiller reprend le dossier -----
  // Rien n'est simule cote donnees : le resume, la chronologie, la piece
  // jointe et la pre-verification viennent tous du fil produit par l'acte I.
  // La sequence ne fait que MONTRER, dans l'ordre, ce que le conseiller lit
  // puis ce qu'il fait -- camera qui cadre, curseur qui clique, saisie au
  // clavier.
  const navigate = useNavigate();
  const [demoCaption, setDemoCaption] = useState(null);
  const demoRef = useRef(false);
  const stage = useDemoStage();

  const activeIdRef = useRef(activeId);
  activeIdRef.current = active?.id ?? activeId;

  // Reperes vers lesquels la camera cadre et le curseur se rend.
  const targets = {
    header: useRef(null),
    summary: useRef(null),
    timeline: useRef(null),
    clientinfo: useRef(null),
    reply: useRef(null),
    takeover: useRef(null),
    noteBtn: useRef(null),
    sendBtn: useRef(null),
    resolveBtn: useRef(null),
    profileBtn: useRef(null),
    identity: useRef(null),
    validateIdBtn: useRef(null),
    backBtn: useRef(null),
  };

  // Le champ ne montre que trois lignes. Des que la reponse depasse, le champ
  // reel suit le curseur vers le bas pendant que le calque, lui, resterait en
  // haut : la fin de la phrase s'ecrirait alors hors du cadre visible. Les deux
  // boites sont donc tenues au meme point de defilement -- en bas, la ou est le
  // curseur, exactement ce que ferait un champ de saisie ordinaire.
  useEffect(() => {
    const field = targets.reply.current;
    if (field) field.scrollTop = field.scrollHeight;
    const ghost = replyGhostRef.current;
    if (ghost) ghost.scrollTop = ghost.scrollHeight;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reply]);

  // React.StrictMode monte le composant DEUX FOIS en developpement (montage,
  // demontage, remontage). Sans precaution, l'acte partait deux fois et
  // chaque message etait pousse en double. Le declenchement est donc differe
  // d'un tick : le nettoyage du premier montage annule ce depart, seul le
  // second aboutit -- et en production, ou il n'y a qu'un montage, le
  // comportement est identique.
  useEffect(() => {
    if (!isDemoMode() || currentAct() !== "agent") return;
    demoRef.current = true;
    const id = setTimeout(runAgentAct, 0);
    return () => {
      clearTimeout(id);
      demoRef.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** Ecrit dans la zone de reponse caractere par caractere. Le champ a deja
   *  recu le clic du curseur a ce stade -- on ne se met jamais a ecrire dans
   *  un champ que personne n'a l'air d'avoir selectionne. */
  async function typeInReply(text, profile) {
    setReply("");
    targets.reply.current?.focus();
    await wait(profile.leadIn);
    for (let i = 1; i <= text.length; i += 1) {
      if (!demoRef.current) return false;
      setReply(text.slice(0, i));
      await wait(keystrokeDelayFor(text[i - 1], profile));
    }
    return true;
  }

  function pushToThread(message) {
    dispatch({ type: "ADD_MESSAGE", conversationId: activeIdRef.current, message });
  }

  async function holdOverlay(overlay, ms) {
    if (!overlay) return;
    showOverlay(overlay);
    await wait(ms ?? overlay.ms ?? 2500);
    if (!demoRef.current) return;
    clearOverlay();
  }

  async function clickTarget(el) {
    if (!el) return;
    stage.moveCursorTo(el);
    await wait(agentAct().cursorTravelMs);
    if (!demoRef.current) return;
    await stage.clickCursor();
    el.classList?.add("demo-pressed");
    setTimeout(() => el.classList?.remove("demo-pressed"), 240);
  }

  async function runAgentAct() {
    const act = agentAct();
    await wait(700);

    for (const step of act.steps) {
      if (!demoRef.current) return;

      const el = step.target ? targets[step.target]?.current : null;
      if (el) {
        // La colonne de droite defile : on amene le bloc a l'ecran avant de
        // pointer dessus, comme le ferait quelqu'un qui lit un dossier.
        if (step.scroll) {
          el.scrollIntoView({ behavior: "smooth", block: "center" });
          await wait(700);
          if (!demoRef.current) return;
        }
        if (step.cursor === "click") {
          await clickTarget(el);
        } else {
          stage.moveCursorTo(el);
          await wait(act.cursorTravelMs);
        }
      }
      if (!demoRef.current) return;

      // Le curseur vient de cliquer sur « Prise en charge » : on emprunte
      // exactement le chemin d'un vrai clic, rien n'est simule a cote.
      if (step.action === "TAKE_OVER") acceptHandover(act.actor.name);

      if (step.action === "TYPE_AND_SEND") {
        // L'acte envoie deux messages -- l'accuse de reception puis la
        // validation : chaque etape porte son texte, `reply` n'est que le
        // defaut.
        const text = step.text ?? act.reply;
        if (!(await typeInReply(text, act.typing))) return;
        await wait(500);
        // Le message ne part jamais tout seul : on voit le curseur cliquer
        // sur Envoyer.
        await clickTarget(targets[step.sendTarget]?.current);
        if (!demoRef.current) return;
        setReply("");
        pushToThread({
          id: nextId("msg"),
          sender: "agent",
          senderName: act.actor.name,
          text,
          time: nowLabel(),
        });
      }

      if (step.action === "OPEN_PROFILE") setShowProfile(true);
      if (step.action === "VALIDATE_IDENTITY") setIdentityValidated(true);
      if (step.action === "BACK_TO_THREAD") setShowProfile(false);

      if (step.action === "RESOLVE") {
        dispatch({ type: "SET_STATUS", conversationId: activeIdRef.current, status: "resolved" });
        const ticket = state.tickets.find((t) => t.conversationId === activeIdRef.current);
        if (ticket) dispatch({ type: "SET_TICKET_STATUS", ticketId: ticket.id, status: "resolu" });
      }

      if (!demoRef.current) return;
      await holdOverlay(step.overlay);
      if (!demoRef.current) return;
      await holdOverlay(step.narration ? { type: "narration", text: step.narration.text } : null,
                        step.narration?.ms);
      await wait(step.hold);
    }

    if (!demoRef.current) return;
    stage.hideCursor();
    await wait(act.beforeAdminAct);
    if (!demoRef.current) return;
    setAct("admin");
    navigate("/admin");
  }

  return (
    <div className="app-shell">
      <Sidebar
        brand={
          <>
            <Avatar kind="agent" size={30} />
            <span>Espace Agent</span>
          </>
        }
        items={[
          { icon: "message", label: "Conversations", count: state.conversations.length },
          { icon: "clock", label: "En attente" },
          { icon: "alert", label: "Escalades", count: escalated.length, active: true },
          { icon: "folder", label: "Mes dossiers" },
          { icon: "history", label: "Historique" },
          { icon: "users", label: "Clients" },
        ]}
        footer={
          <div className="sidebar-user">
            <Avatar kind="agent" name={ACTING_AGENT.name} size={32} />
            <div className="who">
              <div className="name">{ACTING_AGENT.name}</div>
              <div className="role">{ACTING_AGENT.role}</div>
            </div>
          </div>
        }
      />

      {/* `is-uncropped` : le profil client recouvre aussi la barre de
          navigation, a gauche de la scene. Le curseur de la demonstration
          est positionne dans le repere de la scene et doit donc pouvoir en
          sortir par la gauche (coordonnee negative) pour aller cliquer sur
          « Retour a l'espace agent » -- sinon le decoupage de la scene le
          fait disparaitre en plein trajet. */}
      <div
        className={`demo-stage${showProfile ? " is-uncropped" : ""}`}
        ref={stage.stageRef}
      >
        <DemoCursor cursor={stage.cursor} />
      <div className="agent-shell">
        {/* Liste des conversations -- masquee en demonstration : elle n'en
            contient qu'une, et elle vole une colonne aux deux zones que le
            jury doit vraiment lire (le fil et le dossier). Trois sections
            restent : le conseiller, la conversation, le resume. */}
        {!isDemoMode() && (
        <div className="agent-list">
          <div className="agent-list-header">
            <div style={{ fontWeight: 700, fontSize: "0.92rem" }}>Conversations</div>
            <div style={{ fontSize: "0.78rem", color: "var(--ink-faint)", marginTop: 2 }}>
              {escalated.length} escalade{escalated.length > 1 ? "s" : ""} à traiter
            </div>
          </div>
          {[...escalated, ...others].map((c) => (
            <div
              key={c.id}
              className={`agent-conv-item ${c.id === activeId ? "active" : ""}`}
              onClick={() => setActiveId(c.id)}
            >
              <div className="row1">
                <span className="conv-id">#{c.id.toUpperCase()}</span>
                <ConversationStatusBadge status={c.status} />
              </div>
              <div className="conv-subject">{c.subject}</div>
              <div className="conv-user">
                {c.userName} · {c.updatedAt}
              </div>
            </div>
          ))}
        </div>
        )}

        <div className="agent-thread-col">
          <div className="agent-thread-header" ref={targets.header}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
              <div>
                <div style={{ fontWeight: 700, fontSize: "0.98rem" }}>{active.subject}</div>
                <div style={{ fontSize: "0.8rem", color: "var(--ink-muted)", marginTop: 2 }}>
                  {active.userName} · Utilisateur #{active.userId}
                </div>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                {/* Le profil n'est atteignable qu'une fois l'appel pris en
                    charge : avant, le conseiller n'a acces a rien du dossier
                    -- meme regle que le resume et la chronologie. */}
                {!pendingPickup && (
                  <button
                    ref={targets.profileBtn}
                    className="btn btn-secondary btn-sm"
                    type="button"
                    onClick={() => setShowProfile(true)}
                  >
                    <Icon name="users" size={14} /> Profil client
                  </button>
                )}
                <ConversationStatusBadge status={active.status} />
              </div>
            </div>
            {active.status === "escalated" && (
              <div style={{ marginTop: 10 }}>
                {pendingPickup ? (
                  <span className="badge badge-warn">Appel entrant · personne n'a encore décroché</span>
                ) : (
                  <span className="badge badge-brand">NGONI IA → Agent humain</span>
                )}
              </div>
            )}
          </div>

          {/* Le fil et la zone de reponse restent DERRIERE l'appel tant qu'il
              n'a pas ete pris en charge : on voit qu'une conversation attend,
              on ne peut ni la lire ni y ecrire. C'est toute la difference
              entre un dossier qu'on recoit et un dossier qu'on accepte. */}
          <div className="agent-thread-body">
            <div className={`agent-thread-messages${pendingPickup ? " is-locked" : ""}`}>
              {active.messages.map((m) => (
                <MessageBubble
                  key={m.id}
                  message={m}
                  agentName={ACTING_AGENT.name}
                  userAvatar={clientPhoto}
                  interactive={false}
                />
              ))}
              <div ref={threadEndRef} />
            </div>

            <div className={`agent-reply-zone${pendingPickup ? " is-locked" : ""}`}>
              {/* Le calque de frappe se superpose au champ au pixel pres : il est
                  donc son voisin direct dans un conteneur qui n'entoure qu'eux
                  deux. Le poser sur la zone de reponse entiere le decalerait de
                  toute la marge de celle-ci. */}
              <div className="agent-reply-field">
                {isDemoMode() && reply && (
                  <div className="agent-reply-ghost" ref={replyGhostRef} aria-hidden="true">
                    <span>{reply}</span>
                    <span className="ns-caret" />
                  </div>
                )}
                <textarea
                  ref={targets.reply}
                  className={`agent-reply-input ${isDemoMode() && reply ? "is-ghosted" : ""}`}
                  rows={3}
                  spellCheck={false}
                  placeholder="Écrivez votre réponse au client…"
                  value={reply}
                  onChange={(e) => setReply(e.target.value)}
                />
              </div>
              <div className="agent-reply-actions">
                <button ref={targets.sendBtn} className="btn btn-primary btn-sm" onClick={sendReply} type="button">
                  <Icon name="send" size={14} /> Envoyer
                </button>
                <button className="btn btn-secondary btn-sm" type="button">
                  <Icon name="paperclip" size={14} /> Pièce jointe
                </button>
                <button ref={targets.noteBtn} className="btn btn-secondary btn-sm" type="button">
                  <Icon name="note" size={14} /> Note interne
                </button>
                {/* Pendant l'appel, c'est le bouton de la carte qui porte la
                    cible du curseur : deux elements ne peuvent pas partager
                    une meme ref. */}
                <button
                  ref={pendingPickup ? undefined : targets.takeover}
                  className="btn btn-secondary btn-sm"
                  type="button"
                  onClick={takeOver}
                >
                  <Icon name="user-check" size={14} /> Prendre en charge
                </button>
                <button ref={targets.resolveBtn} className="btn btn-secondary btn-sm" type="button" onClick={resolveConversation}>
                  <Icon name="check-circle" size={14} /> Résoudre
                </button>
                <button className="btn btn-ghost btn-sm" type="button">
                  <Icon name="forward" size={14} /> Transférer
                </button>
              </div>
            </div>

            {pendingPickup && (
              <div className="agent-call">
                <div className="agent-call-card">
                  <div className="agent-call-tag">
                    <span className="agent-call-pulse" />
                    NGONI IA → Agent humain
                  </div>

                  <div className="agent-call-ring">
                    <Avatar name={active.userName} src={clientPhoto} size={54} />
                    <span className="agent-call-headset">
                      <Icon name="headset" size={15} />
                    </span>
                  </div>

                  <div className="agent-call-name">{active.userName}</div>
                  <div className="agent-call-subject">{active.subject}</div>
                  <div className="agent-call-meta">
                    Utilisateur #{active.userId} · escalade prioritaire · {active.messages.length} messages
                  </div>

                  <div className="agent-call-wait">
                    <span className="agent-call-wait-label">En attente depuis</span>
                    <span className="agent-call-wait-value">{formatWait(ringSeconds)}</span>
                  </div>

                  <button
                    ref={targets.takeover}
                    className="btn btn-primary agent-call-accept"
                    type="button"
                    onClick={takeOver}
                  >
                    <Icon name="user-check" size={16} /> Prise en charge
                  </button>

                  <div className="agent-call-hint">
                    Le fil de la conversation et le dossier préparé par NGONI IA s'ouvrent une fois
                    l'appel pris en charge.
                  </div>
                </div>
              </div>
            )}

          </div>
        </div>

        <div className="agent-context">
          {pendingPickup ? (
            // Le resume, la chronologie et la fiche client sont ce que le
            // conseiller vient chercher : ils s'ouvrent quand il accepte
            // l'appel, pas avant. Sans quoi la prise en charge ne serait
            // qu'un bouton de plus, sans consequence a l'ecran.
            <div>
              <h3>Dossier client</h3>
              <div className="agent-context-locked">
                <Icon name="folder" size={20} />
                <p>
                  Le résumé, la chronologie et la fiche client s'affichent dès que vous avez pris
                  l'appel en charge.
                </p>
              </div>
            </div>
          ) : (
          <>
            <div ref={targets.summary}>
              <h3>Résumé généré par NGONI IA</h3>
              <div className="ai-summary-box">
                {active.aiSummary ?? "Aucun résumé disponible pour cette conversation — elle n'a pas (encore) été escaladée."}
              </div>
            </div>

            {active.timeline && (
              <div ref={targets.timeline}>
                <h3>Chronologie</h3>
                <Timeline events={active.timeline} />
              </div>
            )}

            <div ref={targets.clientinfo}>
              <h3>Informations client</h3>
              <div className="client-info-row">
                <span className="k">Nom</span>
                <span className="v">{active.userName}</span>
              </div>
              <div className="client-info-row">
                <span className="k">ID utilisateur</span>
                <span className="v">#{active.userId}</span>
              </div>
              <div className="client-info-row">
                <span className="k">Statut</span>
                <span className="v">
                  <ConversationStatusBadge status={active.status} />
                </span>
              </div>
              <div className="client-info-row">
                <span className="k">Pris en charge par</span>
                <span className="v">{active.assignedAgent ?? "—"}</span>
              </div>
            </div>
          </>
          )}
        </div>

      </div>
      </div>
      {/* ------------------------------------------------------------------
          PROFIL CLIENT -- la fiche de l'utilisateur telle qu'elle existe sur
          la plateforme, ouverte par dessus l'espace conseiller.

          Deux origines de donnees, jamais confondues a l'ecran : le COMPTE
          (colonne de gauche, ce que l'utilisateur a declare a l'inscription)
          et la PIECE (colonne centrale, les champs lus par l'agent sur le
          document). Seuls les seconds portent un statut et sont validables
          -- c'est toute la difference entre ce qu'on sait d'un compte et ce
          qu'on a verifie d'une identite, et c'est ce que le conseiller
          tranche ici.
          ------------------------------------------------------------------ */}
      {showProfile && (
        <div className="agent-profile">
          <header className="apf-topbar">
            <button
              ref={targets.backBtn}
              className="apf-back"
              type="button"
              onClick={() => setShowProfile(false)}
            >
              <Icon name="arrow-left" size={15} /> Retour à l'espace agent
            </button>

            <div className="apf-logo">
              <img src={ngoniIcon} alt="" />
              <span>NGONI</span>
            </div>

            <div className="apf-search">
              <Icon name="search" size={16} />
              <input type="search" placeholder="Rechercher un utilisateur..." />
            </div>

            <button className="apf-bell" type="button" aria-label="Notifications">
              <Icon name="bell" size={18} />
              <span className="apf-badge">3</span>
            </button>

            <div className="apf-me">
              <Avatar kind="agent" name={ACTING_AGENT.name} size={34} />
              <Icon name="chevron-down" size={13} />
            </div>
          </header>

          <div className="apf-body">
            <aside className="apf-card apf-side">
              {/* Banniere en degrade plutot qu'une photo de couverture : la
                  demonstration n'a pas de visuel pour ce compte, et en
                  fabriquer un serait le seul element invente de l'ecran. */}
              <div className="apf-cover" />
              <div className="apf-avatar">
                <Avatar name={active.userName} src={clientPhoto} size={76} />
              </div>

              <div className="apf-side-head">
                <div className="apf-name">{active.userName}</div>
                <div className="apf-handle">{DEMO_PROFILE.handle}</div>
                <span className={`apf-kyc${identityValidated ? " is-valid" : ""}`}>
                  <Icon name={identityValidated ? "check-circle" : "clock"} size={13} />
                  {identityValidated ? "Identité validée" : "En cours de vérification"}
                </span>
                <div className="apf-since">
                  <Icon name="calendar" size={14} /> Client depuis {DEMO_PROFILE.memberSince}
                </div>
              </div>

              <div className="apf-stats">
                {DEMO_PROFILE.stats.map((stat) => (
                  <div key={stat.label}>
                    <span className="apf-stat-value">{stat.value}</span>
                    <span className="apf-stat-label">{stat.label}</span>
                  </div>
                ))}
              </div>

              <p className="apf-bio">
                {DEMO_PROFILE.bio.map((line) => (
                  <span key={line}>{line}</span>
                ))}
              </p>

              <div className="apf-side-info">
                <h3>
                  <Icon name="id-card" size={15} /> Informations du profil
                </h3>
                <div className="apf-row">
                  <Icon name="users" size={15} />
                  <span className="k">Nom complet</span>
                  <span className="v">{DEMO_PROFILE.fullName}</span>
                </div>
                <div className="apf-row">
                  <Icon name="mail" size={15} />
                  <span className="k">E-mail</span>
                  <span className="v">{DEMO_PROFILE.email}</span>
                </div>
                <div className="apf-row">
                  <Icon name="phone" size={15} />
                  <span className="k">Téléphone</span>
                  <span className="v">{DEMO_PROFILE.phone}</span>
                </div>
                <div className="apf-row">
                  <Icon name="pin" size={15} />
                  <span className="k">Localisation</span>
                  <span className="v">{DEMO_PROFILE.location}</span>
                </div>
                <div className="apf-row">
                  <Icon name="calendar" size={15} />
                  <span className="k">Date d'inscription</span>
                  <span className="v">Depuis {DEMO_PROFILE.memberSince}</span>
                </div>
              </div>

              <button className="apf-full" type="button">
                <Icon name="eye" size={15} /> Voir tout le profil
              </button>
            </aside>

            <section className="apf-main">
              {/* Onglets du profil sur la plateforme : du contexte, pas de la
                  navigation -- l'espace conseiller n'ouvre que l'Assistance. */}
              <nav className="apf-tabs" aria-label="Onglets du profil">
                <span>
                  <Icon name="grid" size={16} /> Publications
                </span>
                <span>
                  <Icon name="users" size={16} /> À propos
                </span>
                <span className="is-active">
                  <Icon name="headset" size={16} /> Assistance
                </span>
                <span>
                  <Icon name="activity" size={16} /> Activité
                </span>
              </nav>

              <div className="apf-main-body">
                <div className="apf-main-title">
                  <button
                    className="apf-back-inline"
                    type="button"
                    onClick={() => setShowProfile(false)}
                    aria-label="Retour à la conversation"
                  >
                    <Icon name="arrow-left" size={18} />
                  </button>
                  <div>
                    <h2>Demande d'assistance</h2>
                    <p>Suivez l'état de la demande de vérification de ce profil.</p>
                  </div>
                </div>

                <div className="apf-request">
                  <span className={`apf-req-chip${identityValidated ? " is-valid" : ""}`}>
                    <Icon name={identityValidated ? "check-circle" : "clock"} size={15} />
                    {identityValidated
                      ? DEMO_PROFILE.request.validatedLabel
                      : DEMO_PROFILE.request.pendingLabel}
                  </span>

                  <h3>{DEMO_PROFILE.request.title}</h3>
                  <p className="apf-sub">
                    Soumise {DEMO_PROFILE.request.submittedAt} · {DEMO_PROFILE.request.deadline}
                  </p>

                  <div className="apf-summary">
                    {active.aiSummary ??
                      "Aucun résumé disponible : cette conversation n'a pas été escaladée."}
                  </div>

                  <div className="apf-fields" ref={targets.identity}>
                    <h4>
                      <Icon name="clipboard-check" size={16} /> Éléments à vérifier
                    </h4>

                    {DEMO_ID_EXTRACTION.fields.map((f, i) => (
                      <div className="apf-field" key={f.label}>
                        <span className="k">{f.label}</span>
                        <span className="v">{f.value}</span>
                        {/* Le decalage par ligne fait basculer les champs en
                            cascade : on voit le statut changer ligne apres
                            ligne, plutot que d'un bloc illisible. */}
                        <span
                          className={`apf-state${identityValidated ? " is-valid" : ""}`}
                          style={{ transitionDelay: `${i * 70}ms` }}
                        >
                          {identityValidated ? "Validé" : "En cours de vérification"}
                        </span>
                      </div>
                    ))}

                    <p className="apf-note">{DEMO_ID_EXTRACTION.matchNote}</p>
                  </div>

                  <div className="apf-actions">
                    <button
                      ref={targets.validateIdBtn}
                      className="btn btn-primary"
                      type="button"
                      disabled={identityValidated}
                      onClick={() => setIdentityValidated(true)}
                    >
                      <Icon name="check" size={16} />
                      {identityValidated ? "Demande validée" : "Valider la demande"}
                    </button>
                    <button className="btn btn-secondary" type="button">
                      <Icon name="x" size={16} /> Refuser la demande
                    </button>
                  </div>
                </div>
              </div>
            </section>

            <aside className="apf-rail">
              <div className="apf-card apf-block">
                <h3>
                  <Icon name="clipboard-check" size={15} /> Historique de la demande
                </h3>
                {active.timeline ? (
                  <Timeline events={active.timeline} />
                ) : (
                  <p className="apf-empty">Aucun événement enregistré.</p>
                )}
              </div>

              <div className="apf-card apf-block">
                <h3>
                  <Icon name="note" size={15} /> Notes de l'agent
                </h3>
                <textarea
                  className="apf-note-input"
                  rows={3}
                  placeholder="Ajouter une note interne..."
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                />
                <div className="apf-note-actions">
                  <span className="apf-clip" aria-hidden="true">
                    <Icon name="paperclip" size={16} />
                  </span>
                  <button className="btn btn-primary btn-sm" type="button" onClick={saveNote}>
                    Enregistrer
                  </button>
                </div>
              </div>

              <div className="apf-card apf-block">
                <h3>
                  <Icon name="file" size={15} /> Photos / Documents
                </h3>
                {/* UNE seule vignette : c'est la seule piece que le client a
                    reellement envoyee. En afficher trois, comme sur une
                    maquette, reviendrait a inventer deux documents que
                    personne n'a fournis. */}
                <figure className="apf-piece">
                  <img
                    src={submittedPiece?.dataUrl || cniRecto}
                    alt="Pièce d'identité soumise par le client"
                  />
                  <figcaption>{submittedPiece?.name ?? "CNI_recto.jpeg"}</figcaption>
                </figure>
                <p className="apf-empty">
                  Le verso enregistré lors du dépôt du 25/08 reste valable : il n'a pas été redemandé.
                </p>
              </div>
            </aside>
          </div>
        </div>
      )}
    </div>
  );
}
