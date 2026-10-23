
export const DEMO_PACING = {
  // RESSERRE pour la structure imposee (3:00 maximum, 3:10 en tolerance).
  // Le budget se verifie avec frontend/budget.mjs, qui rejoue les memes
  // sequences d'attente que ChatPage / AgentPage / AdminSettingsPage.
  // Le panneau technique permanent est masque en demonstration : ce sont les
  // incrustations qui portent l'information, et elles sont breves.
  beforeFirstTurn: 1200,

  typing: { charMs: 26, spaceMs: 20, punctuationMs: 110, jitterMs: 34, leadIn: 220 },

  beforeSend: 800,
  beforeTyping: 700,
  betweenTurns: 1400,

  // Une reponse longue met plus de temps a arriver qu'une reponse courte,
  // mais l'ecart reste contenu : le rythme prime.
  reply: { baseMs: 1100, perCharMs: 7, minMs: 1400, maxMs: 3400 },

  upload: {
    pickMs: 1600,
    transferMs: 1800,
    transferManualMs: 1200,
    // Envoi sans operateur (?demo=1&auto=1) : invitation -> fenetre
    // « Open » -> selection -> Open -> envoi, au curseur (ChatPage,
    // autoAttachDocument). cursorTravelMs couvre la transition CSS du
    // curseur (.demo-cursor, 0,85 s).
    explorer: { beforeClickMs: 900, cursorTravelMs: 900, readFolderMs: 1100, afterSelectMs: 600, readyMs: 700 },
  },
};

// L'identite affichee est celle qui figure REELLEMENT sur la piece fournie
// dans demo/ : sans quoi la ligne "Correspondance avec le compte" de la
// pre-verification serait contredite a l'ecran par la carte elle-meme, sous
// les yeux du jury.
export const DEMO_ACCOUNT = {
  displayName: "Ayekoe Adou Eric Baruch Deverin",
  firstName: "Adou",
  handle: "@adou.creator",
  frontendUserId: "82741",

  // Identifiant technique reellement porte par X-User-ID vers le moteur
  backendUserId: "44444444-aaaa-4444-aaaa-444444444444",

  before: {
    kyc_status: "PENDING",
    kyc_level: "none",
    giftsEnabled: false,
    resubmissionLocked: true,
  },
  afterUnlock: {
    kyc_status: "PENDING",
    kyc_level: "none",
    giftsEnabled: false,
    resubmissionLocked: false,
  },
  afterAdvisor: {
    kyc_status: "VERIFIED",
    kyc_level: "level_1",
    giftsEnabled: true,
    resubmissionLocked: false,
  },
};

export const DEMO_SUBMISSION = {
  id: "44444444-bbbb-4444-bbbb-444444444444",
  level: "level_1",
  status: "rejected",
  // Motif EXACT stocke en base -- l'agent le cite tel quel.
  rejectionReasonInDb: "Document d'identité illisible ou expiré",
  // Precision que le manifeste ne porte pas encore (voir en-tete).
  refinedReason: "recto illisible — photo floue",
  rejectedAtLabel: "25 août",
};

// Reponse REELLE du moteur pour ce compte aujourd'hui.
export const DEMO_ENGINE_TODAY = {
  outcome: "RESOLVED",
  message:
    "Votre dernière demande de vérification d'identité a été refusée. " +
    "Motif indiqué : Document d'identité illisible ou expiré. " +
    "Vous pouvez soumettre une nouvelle demande en corrigeant le document concerné.",
  resolution_code: "KYC_REJECTED",
  data: { kyc_level: "level_1", rejection_reason: "Document d'identité illisible ou expiré" },
};

export const DEMO_ADVISOR = { name: "Ibrahim Traoré", role: "Conseiller vérification" };

export const DEMO_TICKET = {
  id: "CMP-20260828-4417",
  subject: "Vérification d'identité — revue prioritaire avant un live",
  status: "nouveau",
  priority: "haute",
  createdAt: "aujourd'hui",
};

export const DEMO_SUMMARY =
  "Vérification refusée le 25/08 (document illisible). Le dépôt était resté verrouillé après le refus : " +
  "l'agent l'a rouvert, le client a renvoyé son recto. Pré-vérification automatique passée — netteté, " +
  "type de document, lisibilité des mentions et correspondance au compte tous conformes, validité jusqu'au " +
  "01/10/2031. Les 10 champs d'identité ont été extraits de la pièce et rattachés au dossier ; ils attendent " +
  "votre validation. Il ne reste que la validation humaine. Échéance : live prévu à 20 h ce soir.";

export const DEMO_TIMELINE = [
  { label: "Demande reçue", time: "18:02", state: "done" },
  { label: "Dossier KYC consulté", time: "18:02", state: "done" },
  { label: "Refus du 25/08 retrouvé", time: "18:03", state: "done" },
  { label: "Dépôt déverrouillé", time: "18:03", state: "done" },
  { label: "Nouveau document reçu", time: "18:05", state: "done" },
  { label: "Pré-vérification automatique — conforme", time: "18:05", state: "done" },
  { label: "Données d'identité extraites — 10 champs", time: "18:05", state: "done" },
  { label: "Champs rattachés au dossier de vérification", time: "18:06", state: "done" },
  { label: "Validation humaine requise", time: "18:06", state: "failed" },
  { label: "Escalade prioritaire — live à 20:00", time: "18:06", state: "active" },
];

// La piece jointe envoyee au tour 3 : demo/carteIDFront.png, TELLE QU'ELLE
// EST sur le disque (nom, poids, dimensions) -- c'est elle que la fenetre
// « Open » montre dans le dossier et qu'on choisit (voir FakeFileDialog).
// Bundlee par Vite depuis src/assets (voir import dans ChatPage.jsx).
export const DEMO_ATTACHMENT = {
  name: "carteIDFront.png",
  size: "655 Ko",
  kind: "Image · PNG",
  width: 759,
  height: 457,
};

// Duree de l'animation de scan avant que les resultats s'affichent.
export const DEMO_SCAN_MS = 4200;

// Resultat de la pre-verification automatique, affiche en carte dans le fil.
// Chaque valeur correspond a ce qui est REELLEMENT lisible sur la piece
// fournie -- rien ici ne peut etre contredit par l'image a l'ecran.
// Le numero de la carte est volontairement absent : il est deja visible sur
// l'image, inutile de le redoubler en texte.
export const DEMO_PRECHECK = {
  title: "Pré-vérification automatique",
  items: [
    { label: "Netteté de l'image", value: "conforme", ok: true, note: "le flou du 25/08 a disparu" },
    { label: "Type de document", value: "carte nationale d'identité", ok: true },
    { label: "Lisibilité des mentions", value: "conforme", ok: true },
    { label: "Correspondance avec le compte", value: "AYEKOE Adou Eric Baruch Deverin", ok: true },
    { label: "Validité", value: "jusqu'au 01/10/2031", ok: true },
  ],
  footnote: "Contrôles techniques uniquement — la validation d'identité reste une décision humaine.",
};

// Lecture du document : ce que l'agent EXTRAIT de la piece, par opposition a
// DEMO_PRECHECK qui ne dit que si elle est exploitable. Les deux etapes sont
// distinctes et c'est le propos : une image nette n'est pas une identite, il
// faut encore en tirer des champs, et ce sont ces champs -- pas l'image --
// qui alimentent le dossier de verification.
//
// CHAQUE VALEUR EST LISIBLE SUR LA PIECE FOURNIE dans demo/ (meme regle que
// DEMO_PRECHECK) : le jury a l'image sous les yeux pendant que les champs
// s'affichent, la moindre valeur inventee se verrait immediatement.
//
// `matched` : le champ a ete confronte aux donnees du compte NGONI. Seuls le
// nom et les prenoms peuvent l'etre -- le compte ne stocke ni lieu de
// naissance ni numero de piece. Ne pas cocher les autres est deliberé :
// pretendre avoir recoupe ce qu'on n'a pas serait le seul mensonge de la
// demonstration.
export const DEMO_ID_EXTRACTION = {
  title: "Données extraites du document",
  fields: [
    { label: "Type de document", value: "Carte nationale d'identité" },
    { label: "Pays émetteur", value: "République de Côte d'Ivoire" },
    { label: "N° du document", value: "CI002356144" },
    { label: "Nom", value: "AYEKOE", matched: true },
    { label: "Prénom(s)", value: "ADOU ERIC BARUCH DEVERIN", matched: true },
    { label: "Date de naissance", value: "14/05/2006" },
    { label: "Lieu de naissance", value: "COCODY (CIV)" },
    { label: "Sexe", value: "M" },
    { label: "Nationalité", value: "IVOIRIENNE" },
    { label: "Date d'expiration", value: "01/10/2031" },
  ],
  matchNote: "Nom et prénoms confrontés au compte NGONI — concordants.",
  footnote:
    "Champs lus automatiquement puis rattachés au dossier de vérification. " +
    "Ils restent « en cours de vérification » tant qu'un conseiller ne les a pas validés.",
};

// Duree du deroule des champs extraits (10 champs, ~180 ms chacun + marge).
export const DEMO_EXTRACTION_MS = 2400;

// ---------------------------------------------------------------------------
// La fiche PROFIL telle que le conseiller la voit dans son espace (voir
// AgentPage, ecran « Profil client »).
//
// Deux origines, jamais melangees a l'ecran :
//   - le COMPTE NGONI (ci-dessous) : ce que la plateforme sait deja de
//     l'utilisateur, saisi par lui a l'inscription. Aucune de ces valeurs ne
//     figure sur la piece d'identite, elles ne peuvent donc pas la
//     contredire -- mais elles ne la prouvent pas non plus, et l'ecran ne
//     leur donne jamais le statut de champ verifie.
//   - la PIECE (DEMO_ID_EXTRACTION) : les 10 champs lus par l'agent. Ce sont
//     les SEULS que le conseiller valide, et les seuls a porter un statut.
//
// Le nom complet est repris tel qu'il est ecrit sur la carte (NOM en tete,
// prenoms ensuite) : c'est la forme que le conseiller doit pouvoir comparer
// d'un coup d'oeil avec la piece affichee a cote.
export const DEMO_PROFILE = {
  fullName: "AYEKOE Adou Eric Baruch Deverin",
  handle: DEMO_ACCOUNT.handle,
  // Deux lignes, comme sur la fiche de la plateforme. Rattachees au scenario
  // (le live du soir est l'echeance du dossier) plutot qu'a une biographie
  // decorative : tout ce qui est ecrit ici doit rester vrai dans le recit.
  bio: [
    "Créateur de contenu sur NGONI, en direct plusieurs fois par semaine.",
    "Vérification demandée avant le live de ce soir.",
  ],
  email: "adou.ayekoe@gmail.com",
  phone: "+225 07 58 14 97 88",
  location: "Abidjan, Côte d'Ivoire",
  memberSince: "2026",

  // Audience du compte : c'est elle qui donne son enjeu au dossier -- la
  // reception des cadeaux pendant les lives est reservee aux comptes
  // verifies, et le client a un live a 20 h.
  stats: [
    { value: "6", label: "Publications" },
    { value: "1 240", label: "Abonnés" },
    { value: "87", label: "Abonnements" },
  ],

  // Onglets du profil sur la plateforme. Volontairement NON cliquables ici :
  // l'espace conseiller n'ouvre que l'onglet Assistance, et une navigation
  // qui ne mene nulle part se remarquerait pendant la demonstration.
  tabs: ["Publications", "À propos", "Assistance", "Activité"],
  activeTab: "Assistance",

  request: {
    title: "Demande de vérification d'identité",
    reference: DEMO_TICKET.id,
    submittedAt: "aujourd'hui · 18:05",
    deadline: "live prévu à 20:00",
    // Etat de la demande, tel qu'il s'affiche en tete de la carte. Il bascule
    // avec la validation humaine -- c'est le seul endroit de l'ecran ou le
    // conseiller change quelque chose.
    pendingLabel: "En attente de validation",
    validatedLabel: "Demande validée",
  },
};

// ---------------------------------------------------------------------------
// Le parcours, tour par tour.
//
// kind       : "message" (par defaut) ou "upload" (envoi de piece jointe).
// nlu        : sortie du classifieur pour ce message (capturee). null pour un
//              envoi de fichier -- il n'y a pas de texte a classer.
// pipeline   : rythme d'avancement du panneau "sous le capot", en ms. Ce sont
//              des durees d'AFFICHAGE, pas des mesures (le temps de calcul
//              reel figure dans nlu.capturedMs).
// readBefore : temps de lecture avant que l'utilisatrice reponde.
// ---------------------------------------------------------------------------

export const DEMO_TURNS = [
  {
    id: "t1-constat",
    // Ce que le jury doit lire : demande naturelle -> intention -> diagnostic.
    badge: { lines: ["INTENT : diagnostic", "ACTION : diagnostic KYC"], ms: 2400 },
    // FORMULATION CONTRAINTE PAR LE CLASSIFIEUR -- ne pas rallonger.
    // Mesure du 28/08, prompt exact du classifieur d'intention :
    //   "bonjour, ma verification ... et du coup je peux plus recevoir
    //    de cadeaux sur mes lives"            -> greet    (le "bonjour" domine)
    //   "ma verification ... et je ne recois plus de cadeaux"
    //                                          -> plainte  (la consequence
    //                                             cadeaux fait basculer)
    //   "ma verification d'identite est bloquee depuis 3 jours"
    //                                          -> diagnostic  OK
    // La consequence (plus de cadeaux) est donc portee par la REPONSE de
    // l'agent, ce qui est de toute facon plus fort : c'est lui qui la connait.
    user: "ma vérification d'identité est bloquée depuis 3 jours",
    nlu: {
      intent: "diagnostic",
      confidence: 0.95,
      ranking: [{ name: "diagnostic", confidence: 0.95 }],
      entities: [{ entity: "issue_status", value: "bloquée" }],
      capturedWith: "le modèle de classification",
      capturedMs: 45312,
    },
    // Premier tour : c'est ici que le jury decouvre le panneau "sous le
    // capot". Chaque etape doit rester lisible avant que la suivante s'allume.
    pipeline: { understandAfter: 700, actAfter: 500, resultAfter: 500 },
    action: "Moteur de diagnostic → user-service",
    result: {
      label: "Refus retrouvé, dépôt verrouillé",
      code: "KYC_REJECTED",
      detail: "refusée le 25/08 · nouveau dépôt bloqué",
    },
    replies: [
      { text: "Bonjour Adou. Je regarde tout de suite où en est votre vérification d'identité." },
      {
        text:
          "Votre demande n'est pas en attente : elle a été refusée le 25 août. " +
          "Le motif enregistré est « recto de la pièce illisible — photo floue ». " +
          "C'est pour ça que vous ne pouvez plus recevoir de cadeaux sur vos lives — " +
          "la fonction est réservée aux comptes vérifiés. Le verso, lui, a été accepté : " +
          "vous n'avez pas à tout recommencer.",
      },
      {
        text:
          "Il y a un second point, et c'est celui qui vous bloquait vraiment : votre dossier est resté " +
          "verrouillé après le refus, donc vous ne pouviez envoyer aucun nouveau document. Je le rouvre ?",
        quickReplies: [
          { label: "Oui, rouvrir mon dossier", action: "DEMO_NEXT" },
          { label: "Voir les critères de photo", action: "DEMO_DECLINE" },
        ],
      },
    ],
  },

  {
    id: "t2-reouverture",
    badge: { lines: ["AFFIRM", "KYC_RESUBMISSION_UNLOCKED"], ms: 2200 },
    // Pastille discrete plutot qu'une carte centrale : l'information compte,
    // pas la mise en scene.
    afterReplies: { type: "badge", lines: ["DOSSIER ROUVERT"], ms: 2400 },
    user: "oui vas-y",
    nlu: {
      intent: "affirm",
      confidence: 0.95,
      ranking: [{ name: "affirm", confidence: 0.95 }],
      entities: [],
      capturedWith: "le modèle de classification",
      capturedMs: 49150,
    },
    pipeline: { understandAfter: 700, actAfter: 500, resultAfter: 500 },
    readBefore: 1800,
    action: "Écriture → user-service (déverrouillage du dépôt)",
    result: {
      label: "Dépôt rouvert",
      code: "KYC_RESUBMISSION_UNLOCKED",
      detail: "recto seul · verso conservé",
    },
    replies: [
      {
        text:
          "C'est fait. Votre dossier est rouvert, et seul le recto est à renvoyer — le verso enregistré " +
          "reste valable. Vous pouvez l'envoyer ici directement, en pièce jointe.",
        variant: "success",
      },
    ],
    effect: { type: "DEPOSIT_REOPENED" },
  },

  {
    id: "t3-envoi",
    badge: { lines: ["DOCUMENT REÇU", "PRÉ-VÉRIFICATION"], ms: 2000 },
    kind: "upload",
    // SOUMISSION MANUELLE : la demonstration s'arrete ici et n'avance que
    // lorsque la vraie piece a ete choisie puis envoyee. C'est le seul moment
    // du parcours ou une action humaine est attendue -- tout le reste se
    // deroule seul apres le clic sur "Démo".
    manual: true,
    user: DEMO_ATTACHMENT.name,
    attachment: DEMO_ATTACHMENT,
    nlu: null,
    pipeline: { understandAfter: 700, actAfter: 500, resultAfter: 500 },
    readBefore: 1800,
    perception: `Pièce jointe reçue — ${DEMO_ATTACHMENT.name}`,
    understanding: { label: "Carte nationale d'identité", detail: "image · PNG · 759 × 457" },
    action: "Analyse automatique du document",
    result: {
      label: "Document conforme",
      code: "DOC_PRECHECK_PASSED",
      detail: "5 contrôles techniques sur 5",
    },
    replies: [
      { text: "Bien reçu. Je lance l'analyse du document…" },
      // Le scan s'affiche AVANT les resultats : on voit la carte etre lue,
      // puis ce que la lecture a produit.
      { variant: "scan", text: "Analyse du document" },
      {
        // La lecture des champs ne commence qu'une fois le balayage ACHEVE :
        // sans ce delai explicite, la carte des donnees extraites tombait
        // alors que la piece etait encore en train d'etre parcourue.
        after: DEMO_SCAN_MS + 600,
        variant: "extraction",
        text: "Données extraites du document",
      },
      {
        // Et la conclusion, elle, attend que les champs aient fini de
        // s'afficher : c'est la lecture qui justifie la phrase, pas l'inverse.
        after: DEMO_EXTRACTION_MS + 600,
        text:
          "Sur les critères techniques, votre document est conforme — la photo est nette cette fois. " +
          "J'en ai extrait vos informations d'identité et je les ai rattachées à votre dossier de vérification.",
      },
    ],
  },

  {
    id: "t4-limite",
    badge: { lines: ["INTENT : diagnostic"], ms: 1600 },
    // Le point dramatique. Une pause AVANT la reponse, puis le bandeau.
    pauseBeforeReplies: 1600,
    afterReplies: { type: "badge", lines: ["VALIDATION HUMAINE REQUISE"], ms: 2600 },
    // FORMULATION CONTRAINTE PAR LE CLASSIFIEUR -- ne pas remettre "super."
    // en tete. Mesure du 28/08 :
    //   "super. et du coup c'est valide ? j'ai un live ce soir a 20h"
    //                              -> rate_response         (le "super." lu
    //                                 comme un retour positif)
    //   "c'est valide maintenant ? j'ai un live ce soir a 20h"
    //                              -> affirm
    //   "mon compte est verifie maintenant ? j'ai un live ce soir a 20h"
    //                              -> diagnostic  OK
    user: "mon compte est vérifié maintenant ? j'ai un live ce soir à 20h",
    nlu: {
      intent: "diagnostic",
      confidence: 0.95,
      ranking: [{ name: "diagnostic", confidence: 0.95 }],
      entities: [],
      capturedWith: "le modèle de classification",
      capturedMs: 47920,
    },
    pipeline: { understandAfter: 700, actAfter: 500, resultAfter: 500 },
    readBefore: 1800,
    action: "Limite réglementaire → proposition d'escalade",
    result: {
      label: "Validation humaine requise",
      code: "HUMAN_VALIDATION_REQUIRED",
      detail: "l'agent n'a pas droit d'écriture sur le statut KYC",
    },
    replies: [
      {
        text:
          "Pas encore. Je peux contrôler votre document, mais la validation finale reste humaine. " +
          "Je transmets votre dossier en priorité, avec les contrôles déjà effectués. Je le fais ?",
      },
    ],
  },

  {
    id: "t5-escalade",
    // Plus de carte "ticket" (CMP-..., priorite, echeance) en fin de tour :
    // 3,4 s d'arret sur image juste avant la bascule, ressenties comme une
    // latence au visionnage (2026-10-21). La reference reste lisible dans la
    // reponse de l'agent et dans le panneau de droite.
    user: "oui s'il te plaît",
    nlu: {
      intent: "affirm",
      confidence: 0.95,
      ranking: [{ name: "affirm", confidence: 0.95 }],
      entities: [],
      capturedWith: "le modèle de classification",
      capturedMs: 35804,
    },
    pipeline: { understandAfter: 700, actAfter: 500, resultAfter: 500 },
    readBefore: 1800,
    action: "Création du ticket → escalade prioritaire",
    result: {
      label: "Dossier transmis",
      code: "CMP-20260828-4417",
      detail: "priorité haute · échéance 20:00",
    },
    replies: [
      {
        text:
          "C'est transmis — référence CMP-20260828-4417. Un conseiller reprend la conversation ici même ; " +
          "il a déjà votre document et ma pré-vérification, vous n'aurez rien à réexpliquer.",
      },
    ],
    effect: { type: "ESCALATE" },
  },
];

// Le conseiller prend connaissance du dossier avant d'ecrire : ce temps mort
// est ce qui rend la reprise humaine credible.
export const DEMO_HANDOFF_CONNECTING_MS = 2200;

// Le premier message du conseiller au client. Il n'est PAS envoye depuis le
// chat : le client en reste a "mise en relation en cours", on bascule dans
// l'espace du conseiller, il DECROCHE l'appel (prise en charge), lit le
// dossier, et ecrit alors seulement -- sous nos yeux. Un message qui tomberait
// avant que quiconque ait decroche ne serait qu'une reponse automatique de
// plus : c'est exactement ce que la demonstration doit eviter de montrer.
//
// Le texte porte la preuve qu'il a lu : il a tout sous les yeux, il ne fait
// rien reexpliquer au client.
export const DEMO_ADVISOR_REPLY = {
  text:
    "Bonjour Adou, Ibrahim du service vérification. J'ai tout votre dossier sous les yeux. " +
    "Je vérifie une dernière chose.",
};

// Temps d'attente cote client, apres la mise en relation, avant la bascule
// vers l'espace conseiller.
export const DEMO_BEFORE_AGENT_ACT_MS = 2400;

// ---------------------------------------------------------------------------
// ACTE II -- l'espace du conseiller.
//
// Ce que la sequence doit demontrer : le conseiller ne refait RIEN. Il ouvre
// un dossier deja instruit (resume, chronologie, piece jointe, pre-verification
// dans le fil), et son intervention se resume a confirmer ce que l'agent a
// prepare. La note interne le dit explicitement -- c'est la replique la plus
// importante de l'acte, et le client ne la voit jamais.
// ---------------------------------------------------------------------------

export const DEMO_AGENT_ACT = {
  actor: DEMO_ADVISOR,

  // L'ORDRE EST LE PROPOS DE L'ACTE. Le dossier arrive comme un APPEL : il
  // sonne dans l'espace du conseiller, sans personne dessus -- cote client, on
  // en est encore a "mise en relation en cours". Tant que l'appel n'est pas
  // decroche, le conseiller ne voit ni le fil ni le dossier : la carte d'appel
  // les recouvre (voir AgentPage, `pendingPickup`).
  //
  // DECROCHER -- LIRE -- REPONDRE, dans cet ordre :
  //   1. il accepte la prise en charge, ce qui le fait entrer dans la
  //      conversation (cote client, "X a rejoint la conversation") ;
  //   2. il lit ce que l'agent a prepare : le resume, la chronologie, la
  //      fiche client -- ces trois blocs ne s'affichent qu'apres la prise en
  //      charge, il ne peut donc pas les avoir lus avant ;
  //   3. et il ecrit alors seulement au client.
  //
  // Un "bonjour, je prends votre dossier" envoye avant d'avoir decroche, ou
  // avant d'avoir rien lu, ne serait qu'une reponse automatique de plus --
  // exactement ce que la demonstration cherche a distinguer.
  steps: [
    {
      id: "arrivee",
      target: "header",
      // L'appel sonne un instant sans que personne ne decroche : ce temps
      // mort fait exister la prise en charge comme une decision. Il tenait
      // 7 s au total, puis ~4 s ; les incrustations "APPEL ENTRANT" et
      // "APPEL DECROCHE" sont retirees (2026-10-21) -- la carte d'appel et le
      // clic sur "Prise en charge" disent deja la meme chose, et ces 3,8 s
      // retardaient la lecture du resume, ressenties comme une latence.
      hold: 300,
    },

    {
      id: "prise-en-charge",
      target: "takeover",
      cursor: "click",
      action: "TAKE_OVER",
      hold: 600,
    },

    // Le conseiller parcourt la colonne de droite de haut en bas, comme il le
    // ferait vraiment : le resume, puis la chronologie. La fiche client n'est
    // plus parcourue ici -- elle est devenue le PROFIL, ouvert plus bas, ou
    // les champs extraits de la piece sont reellement validables.
    {
      id: "resume",
      target: "summary",
      scroll: true,
      hold: 3200,
    },
    { id: "chronologie", target: "timeline", scroll: true, hold: 2800 },

    {
      id: "accuse-reception",
      target: "reply",
      cursor: "click",
      action: "TYPE_AND_SEND",
      sendTarget: "sendBtn",
      // Le texte du step prime sur `reply` : cet acte envoie DEUX messages,
      // le premier mot au client puis la validation.
      text: DEMO_ADVISOR_REPLY.text,
      hold: 1200,
    },

    // ---- La verification proprement dite ------------------------------
    // Le conseiller vient d'annoncer "je verifie une derniere chose" : il va
    // donc le faire, sous nos yeux. C'est le coeur de l'acte -- le seul
    // moment ou une decision humaine est prise, et le seul endroit ou la
    // demonstration peut montrer a quoi ont servi les champs extraits par
    // l'agent : ils sont deja la, remplis, en attente de validation. Le
    // conseiller ne saisit rien, il confirme.
    {
      id: "profil",
      target: "profileBtn",
      cursor: "click",
      action: "OPEN_PROFILE",
      overlay: { type: "badge", lines: ["PROFIL CLIENT", "CHAMPS EXTRAITS DE LA PIÈCE"], ms: 2000 },
      hold: 1800,
    },
    // Lecture des champs : ils portent tous la mention "en cours de
    // verification" a cet instant.
    { id: "lecture-identite", target: "identity", scroll: true, hold: 3000 },
    {
      id: "validation-identite",
      target: "validateIdBtn",
      // `scroll` est indispensable ici : le bouton est en bas d'une fiche
      // qui defile, donc hors cadre a ce moment du parcours. Sans lui, le
      // curseur partait bien vers ses coordonnees -- mais sous la ligne de
      // flottaison, et le clic le plus important de l'acte ne se voyait pas.
      scroll: true,
      cursor: "click",
      action: "VALIDATE_IDENTITY",
      // Plus d'incrustation "En cours de verification -> Valide" (2026-10-21) :
      // les pastilles des champs passent elles-memes au vert "Valide" sous
      // les yeux du jury, la carte centrale les masquait 2,6 s.
      hold: 2000,
    },
    {
      id: "retour",
      target: "backBtn",
      cursor: "click",
      action: "BACK_TO_THREAD",
      hold: 1000,
    },

    {
      id: "validation",
      target: "reply",
      cursor: "click",
      action: "TYPE_AND_SEND",
      sendTarget: "sendBtn",
      overlay: { type: "badge", lines: ["VALIDATION KYC NIVEAU 1"], ms: 2400 },
      hold: 1600,
    },
    {
      id: "resolution",
      target: "resolveBtn",
      cursor: "click",
      action: "RESOLVE",
      overlay: { type: "badge", lines: ["TICKET → RÉSOLU"], ms: 2000 },
      hold: 900,
    },
    // Le clic sur « Résoudre » se voyait, sa CONSEQUENCE non : le statut du
    // dossier vit dans la colonne de droite, hors cadre depuis le bas de la
    // zone de reponse. On y amene donc la vue, et l'incrustation « avant /
    // apres » nomme le changement pendant qu'on le regarde.
    {
      id: "statut",
      target: "clientinfo",
      scroll: true,
      overlay: { type: "state", before: "Escaladée", after: "Résolue", ms: 2200 },
      hold: 1200,
    },
  ],


  // Courte, comme demande : le client n'a pas besoin d'un paragraphe.
  reply:
    "C'est validé. Votre compte passe en niveau 1 et la réception des cadeaux est réactivée.",

  // Meme rythme que la frappe du client, deja validee au tournage.
  // Plus posee que celle du client : le conseiller redige, il ne repond pas
  // dans l'urgence -- et le texte doit rester lisible pendant qu'il s'ecrit.
  typing: { charMs: 30, spaceMs: 24, punctuationMs: 110, jitterMs: 34, leadIn: 320 },
  cursorTravelMs: 700,
  beforeAdminAct: 2200,
};

// ---------------------------------------------------------------------------
// ACTE III -- la supervision, en trois ecrans reellement branches sur le
// moteur. Le parcours s'enchaine tout seul : tableau de bord, puis
// statistiques, puis configuration de l'agent.
//
// Les metriques de classification (macro F1, accuracy, weighted F1) ne sont
// affichees nulle part : ce sont les seules valeurs qu'on ne pouvait pas
// sourcer dans le depot. Tout ce qui reste a l'ecran est lu en direct.
//
// settle   : temps de lecture du haut de page AVANT que le defilement parte.
//            Il sert aussi de delai de grace pour les donnees du moteur --
//            mesurer la hauteur d'une page encore en chargement donnerait
//            celle de l'ecran d'attente.
// scrollMs : duree du parcours de haut en bas. C'est un temps de LECTURE, pas
//            un deplacement : trop court, la page defile sous les yeux du jury
//            sans qu'il ait le temps de lire une seule carte.
// hold     : duree totale de l'ecran, defilement compris.
// script   : l'ecran n'est pas seulement parcouru, il est MANIPULE (voir
//            AdminSettingsPage) -- sa duree est alors celle de la scene, pas
//            un `hold` fixe.
export const DEMO_ADMIN_ACT = {
  // Tableau de bord (les statistiques : volumes, tickets, temps de reponse,
  // evolution des demandes, repartition des intentions), puis parametres du
  // modele. La base de connaissances est sortie du parcours (2026-10-21) pour
  // raccourcir la video ; elle reste accessible, elle n'est simplement plus
  // filmee.
  tour: [
    { path: "/admin", settle: 1800, scrollMs: 7600, hold: 9600 },
    { path: "/admin/settings", settle: 1400, script: true },
  ],

  // La derniere scene : un seuil du moteur est modifie sous les yeux du jury,
  // confirme avec l'identite de la personne, puis retrouve dans le journal.
  // C'est la reponse a la seule question qui reste apres deux actes d'agent
  // autonome : qui garde la main, et comment le prouve-t-on ?
  //
  // Le seuil choisi est celui qui decide si un message est compris ou renvoye
  // vers un humain (rasa/config.yml -- FallbackClassifier.threshold) : le plus
  // parlant des sept, parce que c'est lui qui arbitre entre l'agent et le
  // conseiller.
  //
  // Le depart de la demonstration remet les seuils a leur valeur par defaut
  // et vide le journal (voir demoDirector.resetDemoParameters) : l'ecran
  // s'ouvre sans badge « modifié » ni historique, et la scene filme toujours
  // le resserrement 70 -> 75 % (on demande a l'agent d'etre plus prudent).
  settings: {
    paramId: "nlu.confidence_threshold",
    // Valeurs telles qu'elles se saisissent dans le champ, en pourcentage.
    //
    // DEUX valeurs, et non une seule : le seuil est persiste en base
    // (ia.system_parameters), donc une demonstration rejouee retrouvait la
    // valeur ecrite la fois precedente. La scene tapait alors 75 sur un
    // seuil deja a 75 et l'annoncait comme une modification -- « 75 % →
    // 75 % » dans l'incrustation, et une ligne de plus dans le journal pour
    // un changement qui n'a pas eu lieu. La scene bascule desormais vers
    // celle des deux valeurs qui n'est pas la valeur courante : il y a
    // toujours un vrai changement a montrer, dans un sens ou dans l'autre.
    newValue: 75,
    altValue: 70,
    typing: { charMs: 160, jitterMs: 80, leadIn: 420 },
    // Trajets plus courts que dans l'espace conseiller (700 ms) : ici le
    // curseur ne traverse pas l'ecran, il descend une liste de reglages --
    // trois deplacements courts, pas trois voyages.
    cursorTravelMs: 550,

    // Temps de lecture resserres une seconde fois pour tenir le format (voir
    // frontend/budget.mjs). La modale reste a l'ecran 4,0 s au total
    // (ouverture + incrustation + lecture) et le journal 5,5 s : de quoi lire
    // deux champs et une ligne, pas de quoi s'y installer.
    scrollToParamMs: 900,
    beforeEdit: 700,
    afterType: 500,
    beforeModal: 700,
    readModalMs: 1800,
    afterConfirm: 800,
    scrollToHistoryMs: 900,
    readHistoryMs: 2400,

    // Les lignes de cette incrustation sont completees a l'execution avec
    // les valeurs reelles (voir AdminSettingsPage, runSettingsScene) : les
    // ecrire en dur ici les faisait mentir des que la valeur de depart
    // n'etait plus celle attendue.
    editOverlay: { type: "badge", lines: ["SEUIL DU MOTEUR"], ms: 1600 },
    confirmOverlay: { type: "badge", lines: ["IDENTITÉ EXIGÉE", "AVANT ÉCRITURE"], ms: 1600 },
    traceOverlay: { type: "badge", lines: ["MODIFICATION TRACÉE"], ms: 1600 },
  },
};

export const DEMO_DECLINE_REPLY =
  "Bien sûr : la photo doit être nette, prise à plat, sans reflet ni doigt sur le document, " +
  "et les quatre coins doivent être visibles. Dites-moi quand vous voulez que je rouvre votre dépôt.";
