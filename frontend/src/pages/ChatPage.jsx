import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import ngoniIcon from "../assets/ngoni-support-icon.jpeg";
import "../styles/ngoniSupportTheme.css";
import { useDemoStore } from "../state/DemoStore";
import { Avatar } from "../components/ui/Avatar";
import { AGENTS } from "../data/mockData";
import { DemoCursor, useDemoStage } from "../components/demo/DemoStage";
import { FakeFileDialog } from "../components/demo/FakeFileDialog";
import {
  describeAction,
  escalateConversation,
  escalateToHumanAgent,
  pollConversation,
  isLocalOnlyTrigger,
  publishVideo,
  sendMessage,
  verifyIdentity,
} from "../services/chatService";
import { delay, nextId, nowLabel } from "../services/mockLatency";
import {
  consumeTurn as demoConsumeTurn,
  currentTurn as demoCurrentTurn,
  declineReply as demoDeclineReply,
  escalationBundle as demoEscalationBundle,
  expectedUserText,
  handoffConnectingMs,
  beforeAgentActMs,
  consumeAutoStart,
  isDemoFinished,
  isAutoUploadMode,
  isDemoMode,
  setAct,
  keystrokeDelay,
  pacing,
  readBefore,
  replyDelay,
  resetDemo,
  resetDemoParameters,
  wait,
} from "../services/demoDirector";
import { DEMO_ATTACHMENT, DEMO_ID_EXTRACTION, DEMO_PRECHECK } from "../data/demoScenario1";
import { clearOverlay, showOverlay } from "../services/demoOverlay";
import { resetAdminTour } from "../hooks/useDemoAdminTour";
// Piece d'identite fournie dans demo/, copiee dans les assets pour etre
// bundlee par Vite (une image servie depuis demo/ ne le serait pas).
import cniRecto from "../assets/demo-cni-recto.png";
// Photo de profil du client, telle qu'elle figure sur son compte NGONI.
import clientPhoto from "../assets/demo-client-avatar.jpeg";

// Réponses d'accusé de réception une fois la conversation escaladée : un
// conseiller humain a repris la main, plus aucun message ne doit repasser
// par le pipeline NLU pour cette conversation (voir handleSend) -- ce ne sont
// jamais des réponses génératives, juste un accusé de lecture simulé.
const HANDOFF_REPLIES = [
  "Je regarde votre dossier, un instant…",
  "Merci, je vérifie ça de mon côté.",
  "C'est noté, je reviens vers vous très vite.",
];

const CONVERSATION_ID = "conv-1";

const NAV_ITEMS = [
  { key: "chat", label: "Chat", active: true, icon: "M2.5 4.5h15v10h-9L4.5 17.5v-3H2.5v-10Z" },
  { key: "historique", label: "Historique", icon: "M4 10a6 6 0 1 0 1.8-4.3M4 10V5m0 5H2M10 7v3.3l2.3 1.3" },
  { key: "faq", label: "FAQ", icon: "M10 18a8 8 0 1 0 0-16 8 8 0 0 0 0 16Zm0-5v-.5c0-1 .6-1.4 1.3-1.9.7-.5 1.2-1 1.2-1.9A2.5 2.5 0 0 0 10 6a2.5 2.5 0 0 0-2.45 2M10 14.2h.01" },
  { key: "profil", label: "Profil", icon: "M10 6.6a3.2 3.2 0 1 0 0 6.4 3.2 3.2 0 0 0 0-6.4ZM3.8 17c.7-3.2 3.2-5 6.2-5s5.5 1.8 6.2 5" },
];

const SERVICES = [
  { key: "connexion", label: "Problème de connexion", prompt: "J'ai un problème de connexion à mon compte", icon: "M3 8.2a10 10 0 0 1 14 0M5.8 11a6.2 6.2 0 0 1 8.4 0M8.6 13.8a2.4 2.4 0 0 1 2.8 0M10 16.2h.01" },
  { key: "remboursement", label: "Remboursement", prompt: "Je voudrais un remboursement", icon: "M4 10a6 6 0 1 0 1.8-4.3M4 10V5m0 5H2" },
  { key: "paiement", label: "Paiement", prompt: "J'ai un problème de paiement", icon: "M2.5 5h15v10.5h-15V5Zm0 3.5h15" },
  { key: "compte", label: "Compte & Profil", prompt: "J'ai une question sur mon compte", icon: "M10 6.8a3 3 0 1 0 0 6 3 3 0 0 0 0-6ZM4 17c.6-3 3-4.8 6-4.8s5.4 1.8 6 4.8" },
  { key: "autre", label: "Autres demandes", prompt: "Que sais-tu faire ?", icon: "M4 6.5h12M4 10h12M4 13.5h8" },
];

function StrokeIcon({ d, size = 18, ...rest }) {
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" {...rest}>
      <path d={d} />
    </svg>
  );
}

export function ChatPage() {
  const { state, dispatch } = useDemoStore();
  const navigate = useNavigate();
  const [draft, setDraft] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [verifyAttempt, setVerifyAttempt] = useState(0);
  // "idle" | "running" | "done" -- deroulement automatique de la demonstration
  const [autoplayState, setAutoplayState] = useState("idle");
  // Piece jointe en cours de selection/televersement, affichee au-dessus du
  // champ de saisie -- null le reste du temps.
  const [upload, setUpload] = useState(null);
  // Soumission MANUELLE de la piece d'identite : le deroulement s'arrete et
  // n'avance que lorsqu'un vrai fichier a ete choisi puis envoye.
  const [awaitingUpload, setAwaitingUpload] = useState(false);
  const [pickedFile, setPickedFile] = useState(null);
  const fileInputRef = useRef(null);
  // Envoi de la piece sans operateur (?demo=1&auto=1) : curseur simule et
  // fenetre « Open » reproduite (voir autoAttachDocument). null = fermee,
  // sinon { selected } -- le fichier en surbrillance.
  const [explorer, setExplorer] = useState(null);
  const stage = useDemoStage();
  const uploadPromptRef = useRef(null);
  const sendBtnRef = useRef(null);
  const explorerFileRef = useRef(null);
  const explorerOpenRef = useRef(null);
  const uploadResolveRef = useRef(null);
  // Image reellement soumise -- reutilisee par l'animation de scan, pour que
  // ce soit bien LA piece envoyee qui soit analysee a l'ecran.
  const uploadedImageRef = useRef(null);
  // null = panneau normal (Ngoni Support / services) ; sinon { phase,
  // text, intent, confidence, ranking, action, latencyMs } -- alimenté par
  // de vrais appels réseau (voir handleSend), jamais de valeur inventée.
  const [inspector, setInspector] = useState(null);
  const threadEndRef = useRef(null);
  // Champ de saisie : on lui donne le focus pendant la frappe simulee, pour
  // que le curseur de texte clignote comme dans une vraie conversation.
  const composerRef = useRef(null);

  const active = state.conversations.find((c) => c.id === CONVERSATION_ID) ?? state.conversations[0];
  const assignedAdvisor = AGENTS.find((a) => a.name === active.assignedAgent);

  // "idle" | "connecting" | "connected" -- ne rejoue l'animation qu'une
  // fois par escalade réelle dans cette session ; si la conversation est
  // déjà escaladée au chargement (rechargement de page, état persisté en
  // localStorage), on affiche directement la carte, sans repasser par
  // l'animation de connexion.
  const [handoffPhase, setHandoffPhase] = useState(() => (active?.status === "escalated" ? "connected" : "idle"));

  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [active?.messages.length, isTyping]);

  // Etat de prise en charge tel que le MOTEUR le connait (pas l'etat local) :
  // c'est lui qui decide si le prochain message part vers Rasa ou vers le fil
  // du conseiller. Dans une ref, pour que handleSend lise toujours la derniere
  // valeur sans se re-creer a chaque sondage.
  const handoffActiveRef = useRef(false);
  // Point de depart du rattrapage : l'instant du montage. Les messages
  // anterieurs sont deja affiches (etat local persiste), les renvoyer les
  // ferait apparaitre en double.
  const lastCheckRef = useRef(new Date().toISOString());

  useEffect(() => {
    // Le mode demonstration rejoue un scenario fige : aucun conseiller reel
    // n'ecrit dedans, sonder le moteur n'aurait aucun sens.
    if (isDemoMode()) return undefined;
    let stopped = false;

    async function pull() {
      try {
        const updates = await pollConversation(CONVERSATION_ID, lastCheckRef.current);
        if (stopped) return;
        lastCheckRef.current = updates.checked_at;
        handoffActiveRef.current = updates.handoff;
        updates.messages
          .filter((message) => message.sender_role === "agent")
          .forEach((message) =>
            pushMessage({
              id: message.id,
              sender: "agent",
              senderName: message.agent_id ?? "Conseiller",
              text: message.text,
              time: nowLabel(),
            })
          );
        if (updates.handoff) {
          setHandoffPhase("connected");
          if (active.status !== "escalated") {
            dispatch({ type: "SET_STATUS", conversationId: active.id, status: "escalated" });
          }
          if (updates.assigned_to && active.assignedAgent !== updates.assigned_to) {
            dispatch({ type: "ASSIGN_AGENT", conversationId: active.id, agent: updates.assigned_to });
          }
        } else if (active.status === "escalated" && updates.status === "BOT") {
          // La demande a ete retiree (« finalement, pas besoin de
          // conseiller » -- voir action_cancel_human_agent_request cote Rasa)
          // ou la conversation a ete close par le conseiller : l'assistant
          // reprend la main, l'interface doit le refleter tout de suite.
          setHandoffPhase("idle");
          dispatch({ type: "SET_STATUS", conversationId: active.id, status: "active" });
        }
      } catch {
        // 404 tant que le moteur n'a jamais entendu parler de cette
        // conversation (aucun message envoye encore) : cas normal, rien a
        // signaler a l'utilisateur.
      }
    }

    const timer = setInterval(pull, 5000);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [active.id, active.status, active.assignedAgent]);

  function pushMessage(message) {
    dispatch({ type: "ADD_MESSAGE", conversationId: active.id, message });
  }

  // Mode demonstration : un rechargement de page suffit a repartir du premier
  // tour, sans vider le stockage local (voir demoDirector.resetDemo).
  useEffect(() => {
    if (isDemoMode()) resetDemo();
  }, []);

  // Deroulement automatique : une fois lance, plus aucune intervention.
  // autoplayRef sert a interrompre proprement les boucles d'attente si la page
  // est demontee au milieu d'une prise (sinon setState apres demontage).
  const autoplayRef = useRef(false);
  useEffect(() => () => { autoplayRef.current = false; }, []);

  // Lancement automatique en demonstration : aucun clic sur « Démo » ne doit
  // ouvrir la video. Le depart passe par un minuteur, pour que le double
  // montage de React.StrictMode l'annule une fois et n'en arme qu'un, et par
  // une ref, pour jouer la fermeture du rendu courant comme le ferait un clic.
  const runAutoplayRef = useRef(null);
  runAutoplayRef.current = runAutoplay;
  useEffect(() => {
    if (!isDemoMode()) return undefined;
    const timer = setTimeout(() => {
      if (consumeAutoStart()) runAutoplayRef.current?.();
    }, 600);
    return () => clearTimeout(timer);
  }, []);

  /** Ecrit un texte dans le champ de saisie caractere par caractere, comme le
   *  ferait quelqu'un au clavier -- jamais un collage instantane, qui se voit
   *  immediatement a l'image. Renvoie false si la sequence a ete interrompue. */
  async function typeIntoComposer(text) {
    setDraft("");
    composerRef.current?.focus();
    await wait(pacing().typing.leadIn);
    for (let i = 1; i <= text.length; i += 1) {
      if (!autoplayRef.current) return false;
      setDraft(text.slice(0, i));
      await wait(keystrokeDelay(text[i - 1]));
    }
    return true;
  }

  function formatFileSize(bytes) {
    if (bytes < 1024) return `${bytes} o`;
    if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} Ko`;
    return `${(bytes / (1024 * 1024)).toFixed(1).replace(".", ",")} Mo`;
  }

  function openFilePicker() {
    fileInputRef.current?.click();
  }

  /** Lecture du fichier choisi : on garde une data URL pour l'afficher dans
   *  le fil ET dans l'animation de scan -- c'est la piece reellement soumise
   *  qui doit apparaitre a l'ecran, pas une image de remplacement. */
  function handleFilePicked(event) {
    const file = event.target.files?.[0];
    // Permet de rechoisir le meme fichier apres une annulation.
    event.target.value = "";
    if (!file) return;

    const reader = new FileReader();
    reader.onload = () => {
      setPickedFile({
        name: file.name,
        size: formatFileSize(file.size),
        kind: file.type === "application/pdf" ? "Document · PDF" : "Image · JPEG",
        dataUrl: String(reader.result),
      });
    };
    reader.readAsDataURL(file);
  }

  /** Envoi effectif de la piece choisie : pousse le message et debloque le
   *  deroulement automatique, qui reprend a partir de la. Le fichier peut
   *  etre passe explicitement (envoi automatique, voir autoAttachDocument) :
   *  depuis la boucle de demonstration, l'etat `pickedFile` lu ici serait
   *  celui du rendu ou la boucle a demarre, donc toujours vide. */
  function sendPickedAttachment(file = pickedFile) {
    if (!file) return;
    uploadedImageRef.current = file.dataUrl;
    pushMessage({
      id: nextId("msg"),
      sender: "user",
      variant: "attachment",
      attachment: file,
      text: file.name,
      time: nowLabel(),
    });
    setPickedFile(null);
    setAwaitingUpload(false);
    const resolve = uploadResolveRef.current;
    uploadResolveRef.current = null;
    resolve?.(true);
  }

  /** Variante sans operateur (?demo=1&auto=1) : le meme geste qu'un envoi a
   *  la main -- clic sur l'invitation, fenetre « Open » sur le dossier
   *  demo/, selection de la piece, Open, puis envoi -- joue par le curseur
   *  de la demonstration. La fenetre est reproduite dans la page : la vraie
   *  n'existe que sur un bureau reel (voir FakeFileDialog). Renvoie false si
   *  la sequence a ete interrompue. */
  async function autoAttachDocument(turn) {
    const p = pacing().upload.explorer;
    setAwaitingUpload(true);
    await wait(p.beforeClickMs);
    if (!autoplayRef.current) return false;

    // Le curseur apparait sur le champ de saisie, la ou se trouve la main
    // de quelqu'un qui vient d'ecrire, puis part vers l'invitation.
    stage.moveCursorTo(composerRef.current);
    await wait(120);
    if (!(await clickWithCursor(uploadPromptRef.current, p.cursorTravelMs))) return false;

    setExplorer({ selected: null });
    await wait(p.readFolderMs);
    if (!(await clickWithCursor(explorerFileRef.current, p.cursorTravelMs))) return false;
    setExplorer({ selected: turn.attachment.name });
    await wait(p.afterSelectMs);
    if (!(await clickWithCursor(explorerOpenRef.current, p.cursorTravelMs))) return false;

    setExplorer(null);
    const file = { ...turn.attachment, dataUrl: cniRecto };
    setPickedFile(file);
    await wait(p.readyMs);
    if (!(await clickWithCursor(sendBtnRef.current, p.cursorTravelMs))) return false;
    stage.hideCursor();
    sendPickedAttachment(file);
    return true;
  }

  async function clickWithCursor(el, travelMs) {
    if (!el) return autoplayRef.current;
    stage.moveCursorTo(el);
    await wait(travelMs);
    if (!autoplayRef.current) return false;
    await stage.clickCursor();
    return autoplayRef.current;
  }

  // Le vrai pointeur reapparait le temps de joindre la piece (voir
  // demoOverlay.css) : c'est la seule etape ou une main agit a l'ecran.
  useEffect(() => {
    if (!isDemoMode()) return undefined;
    const root = document.documentElement;
    if (awaitingUpload || pickedFile) root.dataset.demoPointer = "1";
    else delete root.dataset.demoPointer;
    return () => {
      delete root.dataset.demoPointer;
    };
  }, [awaitingUpload, pickedFile]);

  /** Met le deroulement en pause jusqu'a l'envoi de la piece. */
  function waitForManualUpload() {
    setAwaitingUpload(true);
    return new Promise((resolve) => {
      uploadResolveRef.current = resolve;
    });
  }

  /** Affiche une incrustation et la retire apres coup, en bloquant. */
  async function holdOverlay(overlay, ms) {
    if (!overlay) return;
    showOverlay(overlay);
    await wait(ms ?? overlay.ms ?? 2500);
    if (!autoplayRef.current) return;
    clearOverlay();
  }

  /** Affiche une incrustation et la retire plus tard, sans bloquer -- pour
   *  les pastilles qui doivent vivre par-dessus la suite du tour. */
  function flashOverlay(overlay) {
    if (!overlay) return;
    showOverlay(overlay);
    setTimeout(() => {
      if (autoplayRef.current) clearOverlay();
    }, overlay.ms ?? 2200);
  }

  /** Envoi d'une piece jointe : selection du fichier, puis barre de
   *  progression. Repli automatique -- utilise seulement si un tour d'envoi
   *  n'est PAS marque `manual`. */
  async function simulateUpload(turn) {
    setUpload({ ...turn.attachment, progress: 0 });
    await wait(pacing().upload.pickMs);

    const steps = 16;
    const stepMs = pacing().upload.transferMs / steps;
    for (let i = 1; i <= steps; i += 1) {
      if (!autoplayRef.current) {
        setUpload(null);
        return false;
      }
      setUpload((u) => (u ? { ...u, progress: Math.round((i / steps) * 100) } : u));
      await wait(stepMs);
    }
    await wait(260);
    setUpload(null);
    return true;
  }

  /** Joue le scenario entier : frappe, envoi, reflexion, reponses, escalade. */
  async function runAutoplay() {
    if (autoplayRef.current) return;
    autoplayRef.current = true;
    setAutoplayState("running");

    // Repart toujours d'une conversation vierge, meme apres une prise
    // precedente conservee dans le stockage local.
    dispatch({ type: "RESET" });
    setHandoffPhase("idle");
    setInspector(null);
    setExplorer(null);
    stage.hideCursor();
    resetDemo();
    resetAdminTour();
    // Les seuils du moteur repartent eux aussi de leur valeur par defaut :
    // l'ecran Parametres doit s'ouvrir sans badge « modifié » ni historique.
    resetDemoParameters("Démonstration");
    await wait(pacing().beforeFirstTurn);

    let firstTurn = true;
    while (!isDemoFinished() && autoplayRef.current) {
      // Temps de lecture de la reponse precedente avant de repondre -- c'est
      // le silence entre deux tours qui donne le rythme d'une vraie
      // conversation, pas la vitesse de frappe.
      if (!firstTurn) await wait(readBefore(demoCurrentTurn()));
      firstTurn = false;
      if (!autoplayRef.current) break;

      const turn = demoCurrentTurn();
      dispatch({ type: "CLEAR_QUICK_REPLIES", conversationId: CONVERSATION_ID });

      if (turn?.kind === "upload") {
        if (turn.manual && isAutoUploadMode()) {
          if (!(await autoAttachDocument(turn))) break;
        } else if (turn.manual) {
          // La demonstration s'arrete ici. Elle ne reprend qu'apres l'envoi
          // d'une vraie piece (voir sendPickedAttachment), qui pousse
          // elle-meme le message dans le fil.
          await waitForManualUpload();
          if (!autoplayRef.current) break;
        } else {
          if (!(await simulateUpload(turn))) break;
          pushMessage({
            id: nextId("msg"),
            sender: "user",
            variant: "attachment",
            attachment: turn.attachment,
            text: turn.attachment.name,
            time: nowLabel(),
          });
        }
      } else {
        if (!(await typeIntoComposer(expectedUserText()))) break;
        await wait(pacing().beforeSend);
        setDraft("");
        pushMessage({ id: nextId("msg"), sender: "user", text: turn.user, time: nowLabel() });
      }

      // Battement avant que les trois points apparaissent : ils ne doivent
      // pas surgir dans le meme souffle que le message envoye.
      await wait(pacing().beforeTyping);
      setIsTyping(true);
      await runDemoTurn();
      setIsTyping(false);
    }

    autoplayRef.current = false;
    setAutoplayState("done");
  }

  /**
   * Rejoue un tour du scenario de demonstration : le panneau "sous le capot"
   * avance etape par etape (perception -> comprehension -> action -> resultat)
   * puis les reponses de l'agent arrivent. Aucun appel reseau, donc aucune
   * attente -- les durees viennent de turn.pipeline, ce sont des durees
   * d'AFFICHAGE, pas des mesures (le temps de calcul reel du modele est
   * conserve dans turn.nlu.capturedMs).
   */
  async function runDemoTurn() {
    const turn = demoConsumeTurn();
    if (!turn) return;

    const { nlu, pipeline } = turn;
    setInspector({ phase: "perceiving", text: turn.perception ?? turn.user, demo: true });

    await wait(pipeline.understandAfter);
    setInspector({
      phase: "understanding",
      text: turn.perception ?? turn.user,
      demo: true,
      // Un envoi de fichier n'a pas de texte a classer : la couche
      // comprehension decrit alors le document, pas une intention.
      ...(nlu
        ? {
            intent: nlu.intent,
            confidence: nlu.confidence,
            ranking: nlu.ranking,
            entities: nlu.entities,
            capturedWith: nlu.capturedWith,
            capturedMs: nlu.capturedMs,
          }
        : {
            understandingLabel: turn.understanding?.label,
            understandingDetail: turn.understanding?.detail,
          }),
    });

    // La pastille remplace le panneau technique : elle dit l'intention et
    // l'action en trois mots, puis disparait.
    flashOverlay(turn.badge ? { type: "badge", lines: turn.badge.lines, ms: turn.badge.ms } : null);

    await wait(pipeline.actAfter);
    setInspector((prev) => (prev ? { ...prev, phase: "acting", action: turn.action } : prev));

    await wait(pipeline.resultAfter);
    setInspector((prev) => (prev ? { ...prev, result: turn.result } : prev));

    if (turn.pauseBeforeReplies) await wait(turn.pauseBeforeReplies);

    for (const reply of turn.replies) {
      // Le delai suit la longueur du message : une reponse de trois lignes
      // ne peut pas arriver aussi vite qu'une reponse d'une ligne.
      await wait(replyDelay(reply));
      pushMessage({
        id: nextId("msg"),
        sender: "ai",
        text: reply.text,
        time: nowLabel(),
        variant: reply.variant,
        quickReplies: reply.quickReplies,
        // L'analyse porte sur la piece reellement soumise.
        image: reply.variant === "scan" ? uploadedImageRef.current : undefined,
      });
    }

    if (!autoplayRef.current) return;
    await holdOverlay(turn.afterReplies);
    if (!autoplayRef.current) return;
    await holdOverlay(turn.narration ? { type: "narration", text: turn.narration.text } : null,
                      turn.narration?.ms);

    if (turn.effect?.type === "ESCALATE") await runDemoEscalation();
  }

  /** Passage a l'humain : ticket, synthese et chronologie -- exactement ce que
   *  l'espace Agent affichera dans l'acte suivant.
   *
   *  Le dossier part SANS conseiller assigne, et aucun message de conseiller
   *  n'est ecrit ici : le client en reste a "mise en relation en cours". La
   *  prise en charge est un acte humain, elle appartient a l'acte II -- c'est
   *  le conseiller qui l'accepte, depuis son espace, avant de se presenter.
   *  Envoyer son "bonjour" depuis le chat reviendrait a faire passer pour une
   *  intervention humaine ce qui ne serait qu'une reponse automatique de plus. */
  async function runDemoEscalation() {
    const { ticket, summary, timeline } = demoEscalationBundle(active.id);
    setHandoffPhase("connecting");
    dispatch({ type: "ADD_TICKET", ticket });
    dispatch({ type: "SET_SUMMARY", conversationId: active.id, summary });
    dispatch({ type: "SET_TIMELINE", conversationId: active.id, timeline });
    dispatch({ type: "SET_STATUS", conversationId: active.id, status: "escalated" });

    await wait(handoffConnectingMs());

    // Acte II : on passe de l'autre cote du guichet, pendant que la mise en
    // relation tourne encore a l'ecran du client.
    if (isDemoMode() && autoplayRef.current) {
      await wait(beforeAgentActMs());
      setAct("agent");
      navigate("/agent");
    }
  }

  async function handleSend(rawText, displayText) {
    const text = (rawText ?? draft).trim();
    if (!text || isTyping) return;
    setDraft("");
    // displayText : ce que l'utilisateur a réellement vu et cliqué (le
    // libellé du bouton), distinct du payload technique envoyé à Rasa
    // ("/select_faq_question{...}") -- n'afficher jamais ce payload brut
    // dans la bulle utilisateur.
    pushMessage({ id: nextId("msg"), sender: "user", text: displayText ?? text, time: nowLabel() });

    // Une fois la conversation escaladée, un conseiller humain a repris la
    // main : plus aucun message ne doit repartir vers le pipeline NLU (ni le
    // panneau "sous le capot", qui n'a plus de sens ici -- il n'y a plus de
    // classification à montrer). Simple accusé de réception simulé.
    //
    // Réservé au mode démonstration : hors démonstration, le message part
    // réellement dans le fil du conseiller (voir plus bas, `handoff`) et
    // c'est une VRAIE personne qui répond, pas cet accusé de lecture.
    if (isDemoMode() && active.status === "escalated") {
      setIsTyping(true);
      await delay(1100 + Math.random() * 700);
      pushMessage({
        id: nextId("msg"),
        sender: "agent",
        senderName: active.assignedAgent,
        text: HANDOFF_REPLIES[Math.floor(Math.random() * HANDOFF_REPLIES.length)],
        time: nowLabel(),
      });
      setIsTyping(false);
      return;
    }

    // Mode demonstration : le tour est rejoue depuis demoScenario1.js, aucun
    // appel a Rasa ni a Ollama. C'est ce qui rend le parcours testable et
    // filmable -- les memes trois messages coutent plusieurs minutes de calcul
    // en conditions reelles (voir capturedMs dans le fichier de donnees).
    if (isDemoMode() && !isDemoFinished()) {
      setIsTyping(true);
      await runDemoTurn();
      setIsTyping(false);
      return;
    }

    setIsTyping(true);

    // Panneau "sous le capot" : uniquement pour les messages qui passent
    // réellement par Rasa -- jamais pour le scénario vidéo local, qui
    // n'implique aucune classification NLU réelle (voir isLocalOnlyTrigger).
    const local = isLocalOnlyTrigger(text);
    setInspector(local ? null : { phase: "perceiving", text });

    const t0 = performance.now();
    // Plus de classification separee AVANT l'envoi : elle doublait l'attente
    // (deux appels au LLM sans GPU) et ignorait la memoire de conversation.
    // Le panneau affiche desormais ce que Rasa a REELLEMENT compris, lu dans
    // son tracker juste apres la reponse (voir sendMessage, chatService.js).
    const replies = await sendMessage(active.id, text, {
      handoff: handoffActiveRef.current,
      onUnderstood: local
        ? undefined
        : ({ intent, confidence, ranking, reformulation }) =>
            setInspector({ phase: "understanding", text, intent, confidence, ranking, reformulation }),
    });
    const latencyMs = Math.round(performance.now() - t0);

    replies.forEach(pushMessage);
    setIsTyping(false);

    if (!local) {
      // Reste affiché tant que l'utilisateur ne le ferme pas lui-même
      // (bouton de fermeture du panneau) -- plus de disparition automatique.
      setInspector((prev) => (prev ? { ...prev, phase: "acting", action: describeAction(prev.intent), latencyMs } : prev));
    }
  }

  async function handleQuickReply(action, label) {
    if (isTyping) return;
    dispatch({ type: "CLEAR_QUICK_REPLIES", conversationId: active.id });

    // Boutons du mode demonstration. DEMO_NEXT envoie le texte du tour suivant
    // plutot que le libelle du bouton, pour que la bulle affichee et la ligne
    // "Perception" du panneau montrent exactement la meme phrase.
    if (action === "DEMO_NEXT") {
      await handleSend(expectedUserText());
      return;
    }
    if (action === "DEMO_DECLINE") {
      pushMessage({ id: nextId("msg"), sender: "ai", text: demoDeclineReply(), time: nowLabel() });
      return;
    }

    if (action.startsWith("RASA_PAYLOAD:")) {
      await handleSend(action.slice("RASA_PAYLOAD:".length), label);
      return;
    }

    if (action === "CANCEL") {
      pushMessage({ id: nextId("msg"), sender: "ai", text: "D'accord, dites-le-moi si vous changez d'avis.", time: nowLabel() });
      return;
    }

    if (action === "PUBLISH_VIDEO") {
      setIsTyping(true);
      pushMessage({ id: nextId("msg"), sender: "ai", text: "Publication en cours…", time: nowLabel(), variant: "loading" });
      const success = await publishVideo(active.id);
      pushMessage(success);
      pushMessage({
        id: nextId("msg"),
        sender: "ai",
        text: "Une vérification d'identité est requise pour poursuivre.",
        time: nowLabel(),
        variant: "verification",
        quickReplies: [{ label: "Vérifier mon identité", action: "VERIFY_IDENTITY" }],
      });
      setIsTyping(false);
      return;
    }

    if (action === "VERIFY_IDENTITY") {
      const attempt = verifyAttempt + 1;
      setVerifyAttempt(attempt);
      setIsTyping(true);
      pushMessage({ id: nextId("msg"), sender: "ai", text: `Vérification en cours (tentative ${attempt}/3)…`, time: nowLabel(), variant: "loading" });
      const result = await verifyIdentity(active.id, attempt);
      pushMessage(result.message);

      if (attempt < 3) {
        pushMessage({
          id: nextId("msg"),
          sender: "ai",
          text: "Souhaitez-vous réessayer ?",
          time: nowLabel(),
          quickReplies: [{ label: "Réessayer", action: "VERIFY_IDENTITY" }],
        });
        setIsTyping(false);
        return;
      }

      pushMessage({
        id: nextId("msg"),
        sender: "ai",
        text: "La procédure automatique est interrompue après 3 tentatives. Je transmets votre demande à un conseiller…",
        time: nowLabel(),
      });
      setHandoffPhase("connecting");
      const { ticket, summary, timeline } = await escalateConversation(active.id, "Échec de vérification d'identité après publication");
      const advisor = AGENTS.find((a) => a.role.toLowerCase().includes("conseil")) ?? AGENTS[AGENTS.length - 1];
      dispatch({ type: "ADD_TICKET", ticket });
      dispatch({ type: "SET_SUMMARY", conversationId: active.id, summary });
      dispatch({ type: "SET_TIMELINE", conversationId: active.id, timeline });
      dispatch({ type: "SET_STATUS", conversationId: active.id, status: "escalated" });
      dispatch({ type: "ASSIGN_AGENT", conversationId: active.id, agent: advisor.name });
      pushMessage({
        id: nextId("msg"),
        sender: "ai",
        text: `Ticket ${ticket.id} créé. ${advisor.name} reprend votre demande — vous pouvez suivre son évolution depuis « Mes demandes ».`,
        time: nowLabel(),
      });
      setIsTyping(false);
      setVerifyAttempt(0);
      // Petit délai avant de révéler la carte de mise en relation -- laisse
      // le temps à l'animation de connexion (voir HandoffPanel) de se voir,
      // plutôt qu'un simple remplacement instantané peu crédible.
      await delay(1500);
      setHandoffPhase("connected");
      pushMessage({
        id: nextId("msg"),
        sender: "system",
        text: `${advisor.name} a rejoint la conversation`,
        time: nowLabel(),
      });
    }
  }

  function handleCancelHandoff() {
    dispatch({ type: "SET_STATUS", conversationId: active.id, status: "active" });
    setHandoffPhase("idle");
    pushMessage({
      id: nextId("msg"),
      sender: "ai",
      text: "Votre demande de mise en relation a été annulée. Je reste disponible si vous avez besoin d'autre chose.",
      time: nowLabel(),
    });
  }

  return (
    <div className="ns-app">
      {isAutoUploadMode() && (
        <>
          {explorer && (
            <FakeFileDialog
              selected={explorer.selected}
              openRef={explorerOpenRef}
              files={[
                // Contenu reel de demo/, filtre comme le selecteur (images).
                { name: DEMO_ATTACHMENT.name, thumb: cniRecto, ref: explorerFileRef },
                { name: "profil.jpeg", thumb: clientPhoto },
              ]}
            />
          )}
          <div className="demo-stage-fixed" ref={stage.stageRef}>
            <DemoCursor cursor={stage.cursor} />
          </div>
        </>
      )}
      {/* SIDEBAR -- masquee en mode demonstration : la navigation (Chat,
          Historique, FAQ, Profil) ne sert a rien pendant la video et vole de
          la largeur au fil et au panneau "sous le capot", qui sont les deux
          seules choses que le jury doit lire. */}
      {!isDemoMode() && (
      <aside className="ns-sidebar">
        <div className="ns-brand">
          <div className="ns-brand-mark"><img src={ngoniIcon} alt="Ngoni" /></div>
          <span className="ns-brand-name">Ngoni Support</span>
        </div>
        <nav className="ns-nav">
          {NAV_ITEMS.map((item) => (
            <button key={item.key} type="button" className={`ns-nav-item ${item.active ? "active" : ""}`}>
              <StrokeIcon d={item.icon} />
              {item.label}
            </button>
          ))}
        </nav>
        <div className="ns-sidebar-status">
          <span className="ns-dot" />
          <div className="ns-lines">
            <span className="ns-t1">En ligne</span>
            <span className="ns-t2">Nous sommes là pour vous aider</span>
          </div>
        </div>
      </aside>
      )}

      {/* CENTER */}
      <main className="ns-chat-col">
        <header className="ns-chat-header">
          {active.status === "escalated" ? (
            <div className="ns-status-line">
              <span className="ns-dot ns-dot-human" />
              <b>{active.assignedAgent}</b>
              <span className="ns-dot-sep" />
              <span>{assignedAdvisor?.role ?? "Conseiller support"} · en direct</span>
            </div>
          ) : (
            <div className="ns-status-line">
              <span className="ns-dot" />
              <b>En ligne</b>
              <span className="ns-dot-sep" />
              <span>Notre équipe est disponible</span>
            </div>
          )}
          <div className="ns-header-actions">
            {isDemoMode() && (
              <button
                type="button"
                className={`ns-demo-btn ${autoplayState === "running" ? "is-running" : ""}`}
                onClick={runAutoplay}
                disabled={autoplayState === "running"}
                title="Lancer la démonstration — le scénario se déroule seul"
              >
                {autoplayState === "running" ? (
                  <span className="ns-demo-pulse" aria-hidden="true" />
                ) : (
                  <StrokeIcon d="M7 4.4v11.2L16 10 7 4.4Z" size={12} strokeWidth="1.6" />
                )}
                {autoplayState === "running" ? "En cours" : autoplayState === "done" ? "Rejouer" : "Démo"}
              </button>
            )}
            <button type="button" className="ns-icon-btn" aria-label="Notifications">
              <StrokeIcon d="M6 8a4 4 0 0 1 8 0c0 4 1.5 5 1.5 5h-11S6 12 6 8Z" size={17} />
            </button>
            {active.status !== "escalated" && (
              <button type="button" className="ns-btn-outline" onClick={() => handleSend("Je veux parler à un conseiller humain", "Contactez-nous")}>
                <StrokeIcon d="M2.5 5.5h15v10h-15v-10Zm0 1 7.5 5.5 7.5-5.5" size={15} />
                Contactez-nous
              </button>
            )}
          </div>
        </header>

        <div className="ns-chat-scroll">
          <div className="ns-assistant-hero">
            <div className="ns-assistant-portrait"><img src={ngoniIcon} alt="Assistant Ngoni" /></div>
            <span className="ns-status-line"><span className="ns-dot" /><b>En ligne</b></span>
          </div>

          <div className="ns-thread">
            {active.messages.map((m) => {
              if (m.sender === "system") {
                return (
                  <div key={m.id} className="ns-handoff-divider">
                    <span>{m.text}</span>
                  </div>
                );
              }
              const isUser = m.sender === "user";
              const isAgentMsg = m.sender === "agent";
              return (
              <div key={m.id} className={`ns-msg-row ${isUser ? "ns-user" : "ns-ai"}`}>
                {/* Les deux cotes du fil portent desormais un visage : le
                    client sa photo de profil, l'assistant l'illustration NGONI.
                    La rangee est en `row-reverse` cote client (voir
                    .ns-msg-row.ns-user), la pastille se place donc d'elle-meme
                    a droite, sans markup distinct. */}
                <div className="ns-msg-avatar">
                  {isUser ? (
                    <Avatar name={active.userName} src={clientPhoto} size={28} />
                  ) : isAgentMsg ? (
                    <Avatar name={m.senderName} size={28} />
                  ) : (
                    <Avatar kind="ai" size={28} />
                  )}
                </div>
                <div className="ns-bubble-col">
                  {!isUser && <span className="ns-sender-name">{isAgentMsg ? m.senderName : "Ngoni"}</span>}
                  <div className="ns-bubble">
                    {m.variant === "loading" && (
                      <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
                        <span className="ns-typing"><span /><span /><span /></span> {m.text}
                      </span>
                    )}
                    {m.variant === "success" && (
                      <span style={{ display: "inline-flex", alignItems: "center", gap: 8, color: "var(--ns-good)" }}>
                        <StrokeIcon d="M17.5 10a7.5 7.5 0 1 1-15 0 7.5 7.5 0 0 1 15 0Zm-11-.2 2.3 2.3 4.7-4.7" size={15} /> {m.text}
                      </span>
                    )}
                    {m.variant === "error" && (
                      <span style={{ display: "inline-flex", alignItems: "center", gap: 8, color: "#C24B3A" }}>
                        <StrokeIcon d="M10 2.5 18 16.5H2L10 2.5Zm0 5.5v3.5m0 2.5h.01" size={15} /> {m.text}
                      </span>
                    )}
                    {m.variant === "attachment" && m.attachment && (
                      <span className="ns-file-card">
                        <span className="ns-file-thumb">
                          <img src={m.attachment.dataUrl || cniRecto} alt="Pièce d'identité envoyée" />
                        </span>
                        <span className="ns-file-meta">
                          <span className="ns-file-name">{m.attachment.name}</span>
                          <span className="ns-file-sub">
                            {m.attachment.kind} · {m.attachment.size}
                          </span>
                        </span>
                      </span>
                    )}
                    {m.variant === "scan" && (
                      <span className="ns-scan">
                        <span className="ns-scan-head">
                          <span className="ns-scan-dot" />
                          Lecture du document…
                        </span>
                        <span className="ns-scan-frame">
                          <img src={m.image || cniRecto} alt="Pièce d'identité en cours d'analyse" />
                          <span className="ns-scan-beam" />
                          <span className="ns-scan-corner tl" />
                          <span className="ns-scan-corner tr" />
                          <span className="ns-scan-corner bl" />
                          <span className="ns-scan-corner br" />
                          {/* Les contrôles se posent SUR l'image, discrètement,
                              au rythme du balayage -- plutôt qu'en carte
                              centrale qui vole l'attention à la pièce. */}
                          <span className="ns-scan-checks">
                            {DEMO_PRECHECK.items.map((it, i) => (
                              <span key={it.label} style={{ animationDelay: `${0.7 + i * 0.62}s` }}>
                                <svg width="11" height="11" viewBox="0 0 20 20" fill="none" aria-hidden="true">
                                  <path d="m4 10.4 4 4 8-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
                                </svg>
                                {it.label}
                              </span>
                            ))}
                          </span>
                        </span>
                        <span className="ns-scan-foot">5 contrôles techniques · conformes</span>
                      </span>
                    )}
                    {/* Lecture du document : les champs se posent un a un, au
                        rythme d'une extraction, plutot que d'apparaitre d'un
                        bloc. Le jury a l'image juste au-dessus dans le fil et
                        peut confronter chaque valeur a la piece. */}
                    {m.variant === "extraction" && (
                      <span className="ns-extract">
                        <span className="ns-extract-head">{DEMO_ID_EXTRACTION.title}</span>
                        <span className="ns-extract-grid">
                          {DEMO_ID_EXTRACTION.fields.map((f, i) => (
                            <span
                              key={f.label}
                              className={`ns-extract-row${f.matched ? " is-matched" : ""}`}
                              style={{ animationDelay: `${i * 0.18}s` }}
                            >
                              <span className="ns-extract-label">{f.label}</span>
                              <span className="ns-extract-value">
                                {f.value}
                                {f.matched && (
                                  <StrokeIcon
                                    className="ns-extract-tick"
                                    d="M17.5 10a7.5 7.5 0 1 1-15 0 7.5 7.5 0 0 1 15 0Zm-11-.2 2.3 2.3 4.7-4.7"
                                    size={13}
                                  />
                                )}
                              </span>
                            </span>
                          ))}
                        </span>
                        <span
                          className="ns-extract-match"
                          style={{ animationDelay: `${DEMO_ID_EXTRACTION.fields.length * 0.18 + 0.2}s` }}
                        >
                          {DEMO_ID_EXTRACTION.matchNote}
                        </span>
                        <span className="ns-extract-foot">{DEMO_ID_EXTRACTION.footnote}</span>
                      </span>
                    )}
                    {m.variant === "precheck" && (
                      <span className="ns-precheck">
                        <span className="ns-precheck-head">{DEMO_PRECHECK.title}</span>
                        {DEMO_PRECHECK.items.map((it) => (
                          <span key={it.label} className="ns-precheck-row">
                            <StrokeIcon
                              className="ns-precheck-tick"
                              d="M17.5 10a7.5 7.5 0 1 1-15 0 7.5 7.5 0 0 1 15 0Zm-11-.2 2.3 2.3 4.7-4.7"
                              size={14}
                            />
                            <span className="ns-precheck-label">{it.label}</span>
                            <span className="ns-precheck-value">
                              {it.value}
                              {it.note && <em> — {it.note}</em>}
                            </span>
                          </span>
                        ))}
                        <span className="ns-precheck-foot">{DEMO_PRECHECK.footnote}</span>
                      </span>
                    )}
                    {(!m.variant || m.variant === "verification" || m.variant === "default") && m.text}
                  </div>
                  {m.quickReplies && m.quickReplies.length > 0 && (
                    <div className="ns-quick-replies">
                      {m.quickReplies.map((qr) => (
                        <button key={qr.action} type="button" className="ns-qr-btn" onClick={() => handleQuickReply(qr.action, qr.label)}>
                          {qr.label}
                        </button>
                      ))}
                    </div>
                  )}
                  <span className="ns-msg-meta">
                    {m.time}
                    {isUser && (
                      <StrokeIcon d="M2 10.5 6 14l4-8M9 10.5 13 14l6-10" size={13} stroke="var(--ns-orange)" strokeWidth="1.8" />
                    )}
                  </span>
                </div>
              </div>
              );
            })}
            {isTyping && (
              <div className="ns-msg-row ns-ai">
                <div className="ns-msg-avatar">
                  {active.status === "escalated" ? <Avatar name={active.assignedAgent} size={28} /> : <Avatar kind="ai" size={28} />}
                </div>
                <div className="ns-bubble-col">
                  <span className="ns-sender-name">{active.status === "escalated" ? active.assignedAgent : "Ngoni"}</span>
                  <div className="ns-bubble"><span className="ns-typing"><span /><span /><span /></span></div>
                </div>
              </div>
            )}
            <div ref={threadEndRef} />
          </div>
        </div>

        <div className="ns-composer-wrap">
          {/* Selecteur de fichier reel -- masque, ouvert par le trombone. */}
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*,application/pdf"
            onChange={handleFilePicked}
            style={{ display: "none" }}
            tabIndex={-1}
          />

          {/* Le déroulement est en pause : on attend la vraie pièce. */}
          {awaitingUpload && !pickedFile && (
            <button type="button" className="ns-upload-prompt" ref={uploadPromptRef} onClick={openFilePicker}>
              <StrokeIcon d="M10 14V4m0 0L6.5 7.5M10 4l3.5 3.5M3.5 13v2a1.5 1.5 0 0 0 1.5 1.5h10a1.5 1.5 0 0 0 1.5-1.5v-2" size={17} />
              Joignez votre pièce d'identité pour continuer
            </button>
          )}

          {/* Piece choisie manuellement, en attente d'envoi. */}
          {pickedFile && (
            <div className="ns-composer-attachment">
              <span className="ns-file-thumb">
                <img src={pickedFile.dataUrl} alt="" />
              </span>
              <span className="ns-file-meta" style={{ flex: 1 }}>
                <span className="ns-file-name">{pickedFile.name}</span>
                <span className="ns-file-sub">
                  {pickedFile.kind} · {pickedFile.size} — prêt à envoyer
                </span>
              </span>
              <button
                type="button"
                className="ns-attach-remove"
                onClick={() => setPickedFile(null)}
                aria-label="Retirer la pièce jointe"
              >
                <StrokeIcon d="M5 5l10 10M15 5 5 15" size={14} strokeWidth="2" />
              </button>
            </div>
          )}

          {/* Envoi automatique (repli, hors soumission manuelle). */}
          {upload && (
            <div className="ns-composer-attachment">
              <span className="ns-file-thumb">
                <img src={cniRecto} alt="" />
              </span>
              <span className="ns-file-meta" style={{ flex: 1 }}>
                <span className="ns-file-name">{upload.name}</span>
                <span className="ns-file-sub">
                  {upload.progress === 0 ? "Sélection du fichier…" : `Envoi ${upload.progress} %`}
                </span>
                <span className="ns-upload-track">
                  <span className="ns-upload-fill" style={{ width: `${upload.progress}%` }} />
                </span>
              </span>
            </div>
          )}
          <div className={`ns-composer ${autoplayState === "running" ? "is-ghosted" : ""}`}>
            {/* Trombone cliquable : il ouvre le vrai selecteur de fichier, et
                pulse tant que la piece attendue n'a pas ete jointe. */}
            <button
              type="button"
              className={`ns-clip-btn ${awaitingUpload && !pickedFile ? "is-waiting" : ""}`}
              onClick={openFilePicker}
              aria-label="Joindre un document"
            >
              <StrokeIcon
                className={`ns-clip ${upload && upload.progress === 0 ? "is-picking" : ""}`}
                d="M12.5 6.5 7.8 11.2a2 2 0 1 0 2.8 2.8l5-5a3.5 3.5 0 1 0-5-5l-5.3 5.4a5 5 0 0 0 7 7l4.7-4.6"
                size={18}
              />
            </button>
            {/* Pendant la frappe simulee, le texte est double par un calque qui
                porte une barre clignotante. Le caret natif d'un champ en
                lecture seule n'est pas affiche par tous les navigateurs : ce
                calque garantit qu'on voit toujours le trait. */}
            {autoplayState === "running" && (
              <div className="ns-composer-ghost" aria-hidden="true">
                <span>{draft}</span>
                <span className="ns-caret" />
              </div>
            )}
            <input
              ref={composerRef}
              spellCheck={false}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleSend();
              }}
              placeholder={active.status === "escalated" ? `Écrivez à ${active.assignedAgent}...` : "Écrivez votre message..."}
              // Pendant le deroulement automatique le champ reste actif a
              // l'oeil (readOnly plutot que disabled) : un champ grise pendant
              // qu'un texte s'y ecrit se voit immediatement a l'image.
              readOnly={autoplayState === "running"}
              disabled={autoplayState === "running" ? false : isTyping}
            />
            <button
              className="ns-send-btn"
              ref={sendBtnRef}
              type="button"
              onClick={() => (pickedFile ? sendPickedAttachment() : handleSend())}
              disabled={pickedFile ? false : isTyping}
              aria-label={pickedFile ? "Envoyer la pièce jointe" : "Envoyer"}
            >
              <StrokeIcon d="M4 10h11m0 0-4.5-4.5M15 10l-4.5 4.5" size={17} stroke="#ffffff" strokeWidth="1.9" />
            </button>
          </div>
        </div>
      </main>

      {/* RIGHT PANEL -- prise en charge humaine (prioritaire, persiste tant
          que la conversation reste escaladée), sinon panneau normal, ou
          "sous le capot" pendant qu'un message passe réellement par
          le pipeline NLU (voir handleSend).

          En démonstration, ce panneau reste masqué : le catalogue de services
          et l'encart d'assistance n'apportent rien au récit et volent de la
          largeur au fil. Il réapparaît au moment de l'escalade -- c'est là
          qu'il porte enfin quelque chose, la mise en relation puis la carte
          du conseiller. */}
      {(!isDemoMode() || active.status === "escalated") && (
      <aside className="ns-right-panel">
        {active.status === "escalated" ? (
          <HandoffPanel phase={handoffPhase} advisorName={active.assignedAgent} onCancel={handleCancelHandoff} />
        ) : inspector && !isDemoMode() ? (
          /* Panneau technique masque pendant la demonstration : ce sont les
             pastilles qui portent l'intention et l'action, brievement. */
          <InspectorPanel inspector={inspector} onClose={() => setInspector(null)} />
        ) : (
          <>
            <div>
              <div className="ns-panel-title">Ngoni Support</div>
              <div className="ns-panel-subtitle">Agent virtuel</div>
              <p className="ns-panel-desc">Je suis votre agent virtuel. Posez-moi vos questions, je suis là pour vous aider rapidement et efficacement.</p>
            </div>

            <div className="ns-card ns-quick-card">
              <div className="ns-quick-icon">
                <StrokeIcon d="M11 2 3.5 11.5H9L8.2 18l7.3-9.5H10L11 2Z" size={19} />
              </div>
              <div>
                <div className="ns-quick-label">Réponse rapide</div>
                <div className="ns-quick-value">Temps de réponse moyen &lt; 1 minute</div>
              </div>
            </div>

            <div>
              <div className="ns-section-label">Services populaires</div>
              <div>
                {SERVICES.map((s) => (
                  <button key={s.key} type="button" className="ns-service-row" onClick={() => handleSend(s.prompt)} disabled={isTyping}>
                    <span className="ns-service-icon"><StrokeIcon d={s.icon} size={16} /></span>
                    <span className="ns-service-name">{s.label}</span>
                    <StrokeIcon className="ns-chev" d="M7.5 4.5 13 10l-5.5 5.5" size={14} strokeWidth="1.8" />
                  </button>
                ))}
              </div>
            </div>

            <div className="ns-card ns-escalate-card">
              <div className="ns-escalate-title">Besoin d'une assistance humaine ?</div>
              <div className="ns-escalate-text">Notre équipe est prête à vous aider.</div>
              <button type="button" className="ns-escalate-btn" onClick={() => {
                // Deux gestes distincts : la phrase part dans la conversation
                // (l'assistant demande la raison, comme avant), et la
                // conversation entre REELLEMENT dans la file des conseillers.
                // Sans le second, la demande n'existait que dans le dialogue :
                // aucun poste conseiller ne la voyait jamais.
                if (!isDemoMode()) {
                  escalateToHumanAgent(CONVERSATION_ID, "demande_utilisateur").catch((err) =>
                    console.error("[ChatPage] escalade vers un conseiller :", err)
                  );
                }
                handleSend("Je veux parler à un conseiller humain", "Contactez un conseiller");
              }}>
                <StrokeIcon d="M4.5 10.5v-1a5.5 5.5 0 0 1 11 0v1M3.8 10.5h1.7a1 1 0 0 1 1 1v3a1 1 0 0 1-1 1H3.8a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1Zm10.7 0h1.7a1 1 0 0 1 1 1v3a1 1 0 0 1-1 1h-1.7a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1ZM14.5 15.5v.5a2 2 0 0 1-2 2h-2.3" size={16} stroke="#ffffff" strokeWidth="1.8" />
                Contactez un conseiller
              </button>
            </div>
          </>
        )}
      </aside>
      )}
    </div>
  );
}

function HandoffPanel({ phase, advisorName, onCancel }) {
  const advisor = AGENTS.find((a) => a.name === advisorName);
  return (
    <div className="ns-handoff-wrap">
      <div>
        <div className="ns-panel-title">Assistance humaine</div>
        <p className="ns-panel-desc">
          {phase === "connecting"
            ? "Nous recherchons un conseiller disponible pour prendre le relais."
            : "Un conseiller a pris connaissance de votre dossier."}
        </p>
      </div>

      {phase === "connecting" ? (
        <div className="ns-handoff-connecting">
          <div className="ns-handoff-ring">
            <StrokeIcon d="M4.5 10.5v-1a5.5 5.5 0 0 1 11 0v1M3.8 10.5h1.7a1 1 0 0 1 1 1v3a1 1 0 0 1-1 1H3.8a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1Zm10.7 0h1.7a1 1 0 0 1 1 1v3a1 1 0 0 1-1 1h-1.7a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1Z" size={22} />
          </div>
          <div className="ns-handoff-connecting-text">Mise en relation en cours…</div>
          <div className="ns-handoff-connecting-sub">Cela ne prend que quelques secondes</div>
        </div>
      ) : (
        <div className="ns-card ns-handoff-card">
          <div className="ns-handoff-top">
            <span className="ns-handoff-title">Assistance humaine</span>
            <span className="ns-handoff-status">En attente</span>
          </div>

          <div className="ns-handoff-person">
            <div className="ns-handoff-avatar">
              <Avatar name={advisorName} size={46} />
              <span className="ns-handoff-online-dot" />
            </div>
            <div>
              <div className="ns-handoff-name">{advisorName}</div>
              <div className="ns-handoff-role">
                <span className="ns-dot" />
                {advisor?.role ?? "Conseiller support"} · En ligne
              </div>
            </div>
          </div>

          <p className="ns-handoff-text">
            Votre demande a été transmise à un conseiller. Vous allez être mis en relation sous peu.
          </p>

          <div className="ns-handoff-wait">
            <span className="ns-handoff-wait-label">Temps d'attente estimé</span>
            <span className="ns-handoff-wait-value">2-3 minutes</span>
          </div>

          <button type="button" className="ns-handoff-cancel" onClick={onCancel}>
            Annuler la demande
          </button>
        </div>
      )}
    </div>
  );
}

function InspectorPanel({ inspector, onClose }) {
  const {
    phase,
    text,
    intent,
    confidence,
    action,
    latencyMs,
    entities,
    reformulation,
    result,
    demo,
    capturedWith,
    capturedMs,
    understandingLabel,
    understandingDetail,
  } = inspector;
  const understood = phase === "understanding" || phase === "acting";
  const acted = phase === "acting";

  return (
    <div className="ns-inspector-wrap">
      <div className="ns-inspector-header">
        <div className="ns-inspector-title">
          <span className="ns-live-dot" />
          Sous le capot
        </div>
        <button type="button" className="ns-inspector-close" onClick={onClose} aria-label="Fermer">
          <StrokeIcon d="M5 5l10 10M15 5 5 15" size={15} strokeWidth="2" />
        </button>
      </div>
      <p className="ns-inspector-sub">Ce que fait réellement l'agent sur ce message, en direct.</p>

      <div className="ns-pipeline">
        <div className="ns-pipe-step done">
          <div className="ns-pipe-rail">
            <div className="ns-pipe-icon">
              <StrokeIcon d="M2 10s2.8-5.5 8-5.5S18 10 18 10s-2.8 5.5-8 5.5S2 10 2 10Z" size={18} />
            </div>
            <div className="ns-pipe-line" />
          </div>
          <div className="ns-pipe-body">
            <div className="ns-pipe-label">Perception</div>
            <div className="ns-pipe-value">« {text} »</div>
          </div>
        </div>

        <div className={`ns-pipe-step ${understood ? "done" : "active"}`}>
          <div className="ns-pipe-rail">
            <div className="ns-pipe-icon">
              <StrokeIcon d="M7 3.5A2.8 2.8 0 0 0 4.2 6.3v.4a2.6 2.6 0 0 0-1.2 2.2c0 .8.4 1.5 1 2a2.6 2.6 0 0 0 2.3 3.8H7m0-11.2A2.8 2.8 0 0 1 9.8 6v7.6A2.6 2.6 0 0 1 7.3 16.2M7 3.5v11.7" size={18} />
            </div>
            <div className="ns-pipe-line" />
          </div>
          <div className="ns-pipe-body">
            <div className="ns-pipe-label">Compréhension</div>
            {understood ? (
              <>
                {intent ? (
                  <div className="ns-pipe-value">
                    <code>{intent}</code>
                    {/* Le pourcentage est masque en demonstration : ce n'est pas
                        une probabilite calculee mais un nombre auto-declare par
                        le LLM, qui vaut 0.95 sur 35 mesures sur 36. Cinq tours
                        affichant "95 %" a l'identique appellent une question a
                        laquelle la valeur ne sait pas repondre. */}
                    {!demo && (
                      <span className="ns-pipe-confidence">{Math.round(confidence * 100)}%</span>
                    )}
                  </div>
                ) : (
                  // Envoi de fichier : rien a classer, la couche comprehension
                  // decrit le document recu.
                  <>
                    <div className="ns-pipe-value">{understandingLabel}</div>
                    {understandingDetail && <div className="ns-pipe-sub">{understandingDetail}</div>}
                  </>
                )}
                {reformulation && (
                  // Memoire de conversation a l'oeuvre : le message ne se
                  // comprenait qu'avec ce qui precedait.
                  <div className="ns-pipe-sub">Compris grâce au contexte : « {reformulation} »</div>
                )}
                {entities && entities.length > 0 && (
                  <div className="ns-entity-row">
                    {entities.map((e) => (
                      <span key={e.entity} className="ns-entity-chip">
                        <code>{e.entity}</code>
                        {e.value}
                      </span>
                    ))}
                  </div>
                )}
              </>
            ) : (
              <div className="ns-pipe-loading">
                <span className="ns-typing"><span /><span /><span /></span> classification en cours…
              </div>
            )}
          </div>
        </div>

        <div className={`ns-pipe-step ${acted ? "done" : understood ? "active" : ""}`}>
          <div className="ns-pipe-rail">
            <div className="ns-pipe-icon">
              <StrokeIcon d="M10 12.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5ZM16.2 12.3l1.4 1-1 1.7-1.6-.5c-.4.4-.9.7-1.4.9l-.3 1.6h-2l-.3-1.6c-.5-.2-1-.5-1.4-.9l-1.6.5-1-1.7 1.4-1a5.4 5.4 0 0 1 0-1.7l-1.4-1 1-1.7 1.6.5c.4-.4.9-.7 1.4-.9l.3-1.6h2l.3 1.6c.5.2 1 .5 1.4.9l1.6-.5 1 1.7-1.4 1a5.4 5.4 0 0 1 0 1.7Z" size={18} />
            </div>
            {result && <div className="ns-pipe-line" />}
          </div>
          <div className="ns-pipe-body">
            <div className="ns-pipe-label">Action</div>
            {acted ? (
              <>
                <div className="ns-pipe-value">{action}</div>
                {/* En rejeu, un compteur de millisecondes ne mesurerait rien de
                    reel : on ne l'affiche pas plutot que d'afficher un chiffre
                    faux (le temps de calcul reellement mesure est rappele en
                    bas du panneau). */}
                {!demo && <div className="ns-pipe-sub">{latencyMs} ms</div>}
              </>
            ) : (
              <div className="ns-pipe-loading">en attente…</div>
            )}
          </div>
        </div>

        {acted && result && (
          <div className="ns-pipe-step done">
            <div className="ns-pipe-rail">
              <div className="ns-pipe-icon">
                <StrokeIcon d="M17.5 10a7.5 7.5 0 1 1-15 0 7.5 7.5 0 0 1 15 0Zm-11-.2 2.3 2.3 4.7-4.7" size={18} />
              </div>
            </div>
            <div className="ns-pipe-body">
              <div className="ns-pipe-label">Résultat</div>
              <div className="ns-pipe-value">{result.label}</div>
              <div className="ns-pipe-sub">
                <code>{result.code}</code>
                {result.detail ? ` · ${result.detail}` : ""}
              </div>
            </div>
          </div>
        )}
      </div>

      {acted && (
        <div className="ns-card ns-recap-card">
          <div className="ns-recap-label">En clair</div>
          <p className="ns-recap-text">
            {intent ? (
              <>
                Le message a été compris comme une demande de type <code>{intent}</code>
                {demo ? "" : `, avec une confiance de ${Math.round(confidence * 100)}%`}. Cela a déclenché :{" "}
                <strong>{action}</strong>
                {demo ? "." : `, en ${latencyMs} ms.`}
              </>
            ) : (
              <>
                Le fichier reçu a été identifié comme <strong>{understandingLabel}</strong>. Cela a déclenché :{" "}
                <strong>{action}</strong>.
              </>
            )}
          </p>
          {demo && intent && capturedMs != null && (
            <p className="ns-recap-source">
              Intention et entités produites par {capturedWith}, capturées lors d'une exécution réelle
              — qui a demandé {(capturedMs / 1000).toFixed(1)} s de calcul. Ce parcours les rejoue sans l'attente.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
