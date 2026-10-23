← [Sommaire](README.md) | [17. DevOps — flow Rasa](17-devops.md)

# 18. Rapport des compétences — classement et propositions

Ce chapitre répond à une question simple : **parmi tout ce que sait faire
l'assistant NGONI, qu'est-ce qui compte vraiment, et dans quel ordre ?** Il
classe les compétences du périmètre assistant (bot Rasa + moteur FastAPI, au
sens de [1.5](01-presentation.md#15-public-visé-par-ce-document)) du plus
important au plus mineur, puis formule des propositions concrètes,
priorisées, pour chaque zone de faiblesse identifiée.

Ce rapport ne réinvente pas ce qui existe déjà : il **s'appuie sur** et
**renvoie vers** les chapitres [13](13-limitations.md),
[14](14-evolutions.md) et [16](16-audit-faq-nlu-2026-07.md) plutôt que de
dupliquer leur contenu — il y ajoute une lecture transversale par
compétence, absente des chapitres existants (organisés par composant
technique, pas par capacité perçue par l'utilisateur).

## 18.1 Méthode de classement

Quatre signaux, tous vérifiables dans le dépôt, ont servi à établir ce
classement — aucun n'est à lui seul suffisant, d'où leur combinaison :

1. **Centralité produit** : la compétence fait-elle partie des quatre
   piliers que l'agent déclare lui-même savoir faire (`AGENT_CAPABILITIES`,
   [`rasa/actions/capabilities.py`](../rasa/actions/capabilities.py), repris
   mot pour mot dans l'accueil et dans `ask_capabilities`), ou est-ce un
   mécanisme de support à ces piliers ?
2. **Poids d'ingénierie** : volume de code dédié, nombre de règles
   `rules.yml` consacrées, complexité de dialogue (formulaire à sous-étapes,
   orchestration multi-service...) — un proxy de l'investissement réel de
   l'équipe, indépendant de ce qui est *dit* être important.
3. **Volume d'entraînement NLU** : nombre d'exemples par intention dans
   `nlu.yml` (compté ci-dessous). Un proxy de la difficulté de
   classification perçue par l'équipe — une intention dense en exemples est
   soit très fréquente, soit très disputée par des intentions voisines
   (souvent les deux à la fois, voir `diagnostic`).
4. **Maturité mesurée** : quand elle existe, la mesure réelle de l'[audit du
   2026-07-21](16-audit-faq-nlu-2026-07.md) prime sur toute impression
   subjective — cet audit est jusqu'ici la seule évaluation en conditions
   adversariales du périmètre.

**Distinction importante, valable pour tout le rapport : importance ≠
qualité.** Une compétence peut être centrale au produit et pourtant
mesurée comme peu fiable aujourd'hui — c'est précisément le constat le plus
important de ce rapport, détaillé en [18.4](#184-constat-transversal).

Comptage des exemples d'entraînement par intention (`rasa/data/nlu.yml`,
19 intentions) :

| Exemples | Intention | Exemples | Intention |
|---:|---|---:|---|
| 386 | `diagnostic` | 149 | `goodbye` |
| 172 | `ask_faq` | 140 | `bot_challenge` |
| 169 | `deny` | 138 | `out_of_scope` |
| 166 | `inappropriate_language` | 46 | `ask_capabilities` |
| 166 | `create_reclamation` | 40 | `rate_response_useful` |
| 161 | `affirm` | 30 | `rate_response_not_useful` |
| 160 | `greet` | 20 | `ask_complaint_status` |
| 158 | `plainte` | 16 | `browse_faq` |
| 153 | `suggestion` | 4 | `select_faq_category` |
| | | 2 | `select_faq_question` |

Les trois dernières lignes ne signalent pas un manque de soin : `browse_faq`,
`select_faq_category` et `select_faq_question` sont déclenchées par des
**clics sur des boutons** (payloads structurés), pas par du texte libre —
elles n'ont donc structurellement besoin que de très peu d'exemples
d'entraînement NLU. Voir la nuance apportée en
[18.5](#p1--haute-priorité-fort-impact-sur-des-compétences-mesurées-fragiles).

## 18.2 Vue d'ensemble

| Rang | Compétence | Catégorie | Maturité mesurée |
|---:|---|---|---|
| 1 | Diagnostic dynamique de problème | Cœur métier | ⚠️ Collision critique avec `ask_faq` ([16.5](16-audit-faq-nlu-2026-07.md#165-failles-identifiées-classées-par-impact) #1) |
| 2 | FAQ sémantique | Cœur métier | ⚠️ Top-1 retrieval 57,8 %, faux positifs 13,4 % ([16.1](16-audit-faq-nlu-2026-07.md#161-résultats-chiffrés)) |
| 3 | Réclamation & suivi de ticket | Cœur métier | Non auditée en conditions adversariales — voir [18.5](#p1--haute-priorité-fort-impact-sur-des-compétences-mesurées-fragiles) |
| 4 | Feedback structuré (suggestion/plainte/notation) | Cœur métier | Fonctionnelle, donnée collectée mais inexploitée ([16.7](16-audit-faq-nlu-2026-07.md#167-nouvelles-perspectives-damélioration)) |
| 5 | Accueil / clôture (`greet`, `goodbye`) | Plomberie dialogue | Robuste (durci par un test conversationnel de 505 tours) |
| 6 | Confirmation / infirmation (`affirm`, `deny`) | Plomberie dialogue | Robuste mais fragile aux références alphanumériques (voir `rules.yml`) |
| 7 | Méta-questions sur l'agent (`bot_challenge`, `ask_capabilities`) | Plomberie dialogue | Robuste, auto-descriptive (source unique) |
| 8 | Filtre hors-sujet (`out_of_scope`) | Garde-fou | Partielle — hors-domaine parfois classé en intention métier avec confiance 1.0 |
| 9 | Recadrage langage inapproprié (`inappropriate_language`) | Garde-fou | Partielle — faux positifs sur mots courts hors distribution |
| 10 | Service d'embeddings partagé | Infrastructure transverse | Stable (singleton, réutilisé par 3 consommateurs) |
| 11 | Capability Registry + résilience (circuit breaker, audit) | Infrastructure transverse | Fonctionnelle, non étendue aux vrais microservices |
| 12 | Éléments dormants / résiduels (slots morts, mappings retirés) | Résiduel | À nettoyer, voir [18.5](#p2--nettoyage-et-clarification) |

## 18.3 Détail par catégorie

### A. Compétences cœur de métier

Ce sont les quatre compétences que l'agent **déclare lui-même** savoir
faire (`AGENT_CAPABILITIES`), reprises mot pour mot dans le message
d'accueil et la réponse à `ask_capabilities` — la seule source de vérité
produit sur "ce que fait ce bot".

#### 1. Diagnostic dynamique de problème

- **Intentions** : `diagnostic` (386 exemples — la plus dense du corpus).
- **Actions** : `action_run_diagnostic_step`, `action_decide_escalation`,
  `action_reask_pending_diagnostic_field`, `action_handle_negation`,
  `action_default_fallback`, `action_out_of_scope` — toutes dans
  [`rasa/actions/diagnostic.py`](../rasa/actions/diagnostic.py), **le fichier
  le plus volumineux du serveur d'actions** ([3.2.1](03-taxonomie.md#321-rasaactions--serveur-dactions)).
- **Backend** : `fastapi/app/domains/diagnostic/` — Capability Registry,
  pipeline générique, disjoncteur, audit ([3.4](03-taxonomie.md#34-fastapiappdomainsdiagnostic-en-détail)).
- **Pourquoi rang 1** : c'est la seule compétence dont le **catalogue est
  découvert dynamiquement** ([1.4](01-presentation.md#14-fonctionnalités-principales))
  plutôt que codé en dur — architecturalement, c'est la fonctionnalité
  différenciante du projet par rapport à un chatbot FAQ classique. C'est
  aussi celle qui a reçu le plus d'investissement de calibration mesurable
  (386 exemples NLU, dizaines de commentaires d'audit qualité dans
  `wallet_service`/`user_service`/`manifest.py` documentant des corrections
  chiffrées avant/après). 8 problèmes diagnosticables aujourd'hui (3 côté
  `wallet`, 5 côté `user` — voir `services_registry.yaml` et les deux
  `manifest.py` des services).
- **Maturité mesurée** : c'est aussi la compétence au cœur du **problème le
  plus critique identifié par l'audit** — des questions FAQ légitimes
  contenant du vocabulaire "compte / mot de passe / retrait" sont
  classées `diagnostic` avec une confiance proche de 1.0
  ([16.5](16-audit-faq-nlu-2026-07.md#165-failles-identifiées-classées-par-impact) #1),
  y compris sur des messages hors-domaine ("Est-ce que tu peux commander une
  pizza pour moi ?" → `create_reclamation` à 1.000, symptôme de la même
  famille). Une tentative de correction par les données a *régressé*
  l'exactitude globale ([16.6](16-audit-faq-nlu-2026-07.md#p0--critique-bloquant-avant-toute-mise-en-production)).

#### 2. FAQ sémantique

- **Intentions** : `ask_faq` (172 exemples), `browse_faq`,
  `select_faq_category`, `select_faq_question`.
- **Actions** : `action_faq_search`, `action_browse_faq`,
  `action_select_faq_category`, `action_select_faq_question` —
  [`rasa/actions/faq.py`](../rasa/actions/faq.py).
- **Backend** : `app/domains/faq` — recherche par similarité d'embeddings
  (`intfloat/multilingual-e5-base`, pgvector), pas de correspondance exacte
  ([1.4](01-presentation.md#14-fonctionnalités-principales)).
- **Pourquoi rang 2** : premier pilier cité dans `AGENT_CAPABILITIES` et
  dans le premier cas d'usage documenté ([1.3](01-presentation.md#13-cas-dutilisation)) —
  c'est la porte d'entrée générique de l'assistant, probablement la plus
  sollicitée en usage réel (question générale avant tout problème
  spécifique).
- **Maturité mesurée** : c'est la compétence dont l'audit documente l'écart
  le plus spectaculaire entre confiance affichée et fiabilité réelle —
  **99,85 % sur le jeu de test existant vs 65,4 % sur un corpus
  adversarial** ([16.1](16-audit-faq-nlu-2026-07.md#161-résultats-chiffrés)),
  qualifié par l'audit lui-même de "résultat le plus important". Côté
  recherche (une fois l'intention `ask_faq` correctement reconnue), le
  Top-1 ne trouve la bonne réponse que 57,8 % du temps, avec 13,4 % de
  faux positifs confiants (mauvaise réponse servie comme si elle était
  bonne) — un risque plus grave qu'un simple échec silencieux.

#### 3. Réclamation & suivi de ticket

- **Intentions** : `create_reclamation` (166 exemples), `plainte` (158,
  traité séparément en catégorie feedback ci-dessous), `ask_complaint_status`
  (20).
- **Actions** : 7 actions dans
  [`rasa/actions/reclamation.py`](../rasa/actions/reclamation.py)
  (`ActionStartReclamation`, `ActionExtractReclamationEntities`,
  `ActionGenerateReclamationSummary`, `ActionRequestReclamationConfirmation`,
  `ActionCreateTicket`, `ActionCancelReclamation`,
  `ActionAskCancelClarification`) + `ActionConsultComplaints`.
- **Backend** : `app/domains/complaints` — tickets `CMP-YYYYMMDD-XXXXXXXX`.
- **Pourquoi rang 3** : deuxième pilier officiel, et **la logique de
  dialogue la plus complexe du projet** — le formulaire `reclamation_form`
  gère nativement des sous-flux (modifier un champ, annuler avec
  clarification, ré-interroger le diagnostic juste avant la création d'un
  ticket issu d'une escalade) qui représentent, à eux seuls, le bloc le
  plus dense de [`rasa/data/rules.yml`](../rasa/data/rules.yml) (guards
  répétés pour chaque intention "méta" — `bot_challenge`,
  `ask_capabilities`, `suggestion`, `plainte`, notation — pendant que le
  formulaire est actif, pour ne jamais le couper sans y revenir).
- **Maturité mesurée** : contrairement au diagnostic et à la FAQ, ce flux
  **n'a pas été couvert par l'audit adversarial du 16 juillet** (portée
  limitée à `ask_faq`/`diagnostic`) — c'est une zone d'ombre de mesure, pas
  une preuve de robustesse. Les nombreux commentaires d'audit "robustesse
  comportementale, test large 500+" dans `domain.yml`/`rules.yml`
  suggèrent un travail de durcissement réel mais non chiffré de la même
  façon que 16.1. Voir proposition en [18.5](#p1--haute-priorité-fort-impact-sur-des-compétences-mesurées-fragiles).

#### 4. Feedback structuré (suggestion, plainte, notation de réponse)

- **Intentions** : `suggestion` (153), `plainte` (158),
  `rate_response_useful` (40), `rate_response_not_useful` (30).
- **Actions** : `ActionStoreSuggestion`, `ActionAcknowledgeComplaint`,
  `ActionRecordResponseRating` —
  [`rasa/actions/feedback.py`](../rasa/actions/feedback.py).
- **Backend** : `app/domains/feedback`, capable de créer un ticket
  `complaints` associé.
- **Pourquoi rang 4** : quatrième pilier officiel, mais le plus en aval du
  parcours utilisateur (il *suit* une réponse déjà donnée plutôt que de
  répondre à un besoin initial) — logiquement la dernière priorité parmi
  les quatre piliers déclarés.
- **Maturité mesurée** : fonctionnellement correcte et durcie (distinction
  explicite entre "service indisponible" et "enregistré avec succès", pour
  ne jamais laisser croire à tort qu'une plainte a été transmise — voir
  commentaires `feedback.py`). Sa limite n'est pas la fiabilité mais
  l'**exploitation** : l'audit note explicitement que les notations
  utile/pas utile et les traces de recherche FAQ sont déjà journalisées
  mais "exploitées nulle part aujourd'hui"
  ([16.7](16-audit-faq-nlu-2026-07.md#167-nouvelles-perspectives-damélioration)).

### B. Plomberie conversationnelle

Ces compétences ne sont **pas** des piliers déclarés à l'utilisateur — mais
sans elles, aucun des quatre piliers ci-dessus ne fonctionnerait de façon
utilisable. Elles occupent une place disproportionnée dans `rules.yml`
(chaque intention "cœur métier" a sa variante "pendant que ceci est actif")
précisément parce qu'elles doivent coexister avec tous les flux ci-dessus
sans jamais les casser.

#### 5. Accueil / clôture (`greet`, `goodbye`)

Accueil contextualisé par heure de la journée (`action_greet_with_time`),
présentation dynamique des capacités et des catégories FAQ. Durci par un
test conversationnel de 505 tours (bug de relance d'accueil pendant une
confirmation en attente, corrigé et versionné dans `rules.yml`). Compétence
mature.

#### 6. Confirmation / infirmation (`affirm`, `deny`)

Pilotent la validation de réclamation et la clarification annuler/modifier.
Point de fragilité documenté : le classifieur confond parfois une référence
de transaction alphanumérique inédite (ex. `WDR-HJCOZRCVCOAY`) avec
`affirm` à confiance 0.9999 — corrigé par une règle dédiée plutôt qu'à la
source, faute de solution au niveau des données (voir commentaire de la
règle *"Ignore nlu_fallback/deny/affirm misclassification while diagnostic
dialogue is pending"*, `rules.yml`).

#### 7. Méta-questions sur l'agent (`bot_challenge`, `ask_capabilities`)

"Es-tu un bot ?" / "Que sais-tu faire ?". Notable pour sa qualité
d'implémentation : `build_capabilities_message()` interroge le Capability
Registry en direct plutôt que de réciter une liste figée — si le registre
est injoignable, le bot le dit explicitement plutôt que d'affirmer une
capacité qu'il ne peut pas confirmer (voir commentaire "même principe de
non-mensonge" dans `capabilities.py`). Un des points de code les plus
soignés du périmètre.

### C. Garde-fous

#### 8. Filtre hors-sujet (`out_of_scope`, 138 exemples)

#### 9. Recadrage langage inapproprié (`inappropriate_language`, 166 exemples)

Ces deux compétences visent à empêcher un message hors-vocabulaire ou
inapproprié d'être classé à tort dans une intention métier avec une
confiance artificiellement élevée (`components/vocabulary_guard.py`,
[1.4](01-presentation.md#14-fonctionnalités-principales)). Classées ici,
sous les compétences de dialogue, parce qu'elles restent **mesurablement
imparfaites** : l'audit montre des hors-domaine classés en intention métier
à confiance 1.0 ("Comment fait-on pour apprendre le piano rapidement ?" →
`ask_faq` 1.000), et `rules.yml` documente un cas réel où "faible" (réponse
légitime à une question d'urgence) était classé `inappropriate_language` à
confiance 1.0. Le filet de sécurité existe et fonctionne dans le cas
général, mais ses angles morts sont documentés, pas hypothétiques.

### D. Infrastructure technique transverse

Ce ne sont pas des "compétences" au sens conversationnel — l'utilisateur ne
les invoque jamais par une intention — mais des capacités système sans
lesquelles rien au-dessus ne fonctionnerait. Classées en dernier parce
qu'elles ne sont pas ce qu'on classerait/améliorerait en premier du point
de vue produit, pas parce qu'elles seraient négligeables techniquement.

#### 10. Service d'embeddings partagé

Singleton `intfloat/multilingual-e5-base`, chargé une fois par process,
réutilisé par le domaine FAQ, le Capability Registry et l'action server
([4.3](04-services.md#43-moteur-ngoni-fastapi--domaine-par-domaine)). Brique
stable, sans incident documenté.

#### 11. Capability Registry + résilience (circuit breaker, audit)

Rafraîchissement périodique des manifestes, disjoncteur partagé, journal
d'audit (`DiagnosticAuditLog`). Fonctionnel mais **jamais éprouvé au-delà de
deux services de développement** — la bascule vers les vrais
`ngoni-wallet-service`/`ngoni-user-service` reste, à ce jour, un changement
de configuration non exécuté en pratique ([14.3](14-evolutions.md#143-étendre-le-capability-registry-aux-microservices-réels)).

#### 12. Éléments dormants ou résiduels

Le classement le plus mineur du périmètre — pas des compétences actives,
mais des vestiges documentés dans le code lui-même :

- **11 slots déclarés "dormants pour le flux diagnostic"**
  (`payment_method`, `transaction_id`, `time`, `content_type`, `video_id`,
  `last_message`, `severity`, `document_type`, `country`,
  `subscription_type`, `channel`, `contact_channel` — commentaire
  `domain.yml` ligne ~365) : depuis le passage à la découverte dynamique
  des capacités, les valeurs vivent dans `diagnostic_state.confirmed`, pas
  dans ces slots individuels — conservés uniquement pour ne pas casser une
  réutilisation par le formulaire de réclamation.
- **5 entités déclarées mais jamais entraînées** (`urgency`,
  `incident_date`, `platform`, `operation_type`, `type_problem`,
  `issue_status`, `amount` pour certaines, `category`) : le commentaire
  d'audit qualité NLU en tête de `domain.yml` (ligne ~25) le dit
  explicitement — "0 exemple annoté... jamais extraites par le NLU en
  pratique", et signale lui-même le risque : "les déclarer sans jamais les
  entraîner n'est pas neutre : ça laisse croire qu'une extraction existe là
  où il n'y en a aucune."

## 18.4 Constat transversal

Le résultat le plus significatif de ce classement n'est pas l'ordre en
lui-même, mais une **coïncidence qui n'en est pas une** : les deux
compétences classées les plus importantes ici (diagnostic, FAQ) — celles
qui ont reçu le plus d'exemples d'entraînement, le plus de code, le plus de
place dans la documentation produit — sont aussi, très précisément, les
deux dont l'audit du 16 juillet a mesuré la fiabilité réelle la plus
faible, et **la même faille technique (le chevauchement de vocabulaire
`ask_faq`/`diagnostic`) explique une bonne partie des deux régressions à la
fois**. Ce n'est pas un hasard : ce sont les deux compétences dont le
périmètre sémantique est le plus large et le plus proche l'un de l'autre
("mon compte est bloqué" peut légitimement relever des deux), donc
mécaniquement les plus difficiles à séparer pour un classifieur bag-of-words.

Autrement dit : **l'effort d'ingénierie déjà investi est bien aligné avec
l'importance produit — ce n'est pas un problème de priorisation passée, mais
un problème non résolu malgré cette priorisation.** La tentative de
correction par les données a d'ailleurs été essayée et a régressé le
système ([16.6](16-audit-faq-nlu-2026-07.md#p0--critique-bloquant-avant-toute-mise-en-production)) —
la piste ouverte et non refermée (embeddings denses en complément du
bag-of-words, +1.2pt mesuré mais non industrialisé) reste la seule option
concrète documentée à ce jour pour ce problème précis.

## 18.5 Propositions

Classées par impact, en cohérence avec la numérotation P0/P1/P2 déjà
utilisée en [16.6](16-audit-faq-nlu-2026-07.md#166-plan-damélioration-priorisé).
Les points déjà couverts en détail par les chapitres 13/14/16 sont
seulement rappelés (avec renvoi) pour ne pas les dupliquer ; les points
ci-dessous **nouveaux par rapport à ces chapitres** sont ceux issus de la
lecture par compétence de ce rapport.

### P0 — Déjà documenté, rappelé ici car ce sont les deux compétences classées les plus importantes

- Chevauchement `ask_faq`/`diagnostic` : voir
  [16.6](16-audit-faq-nlu-2026-07.md#p0--critique-bloquant-avant-toute-mise-en-production)
  et [16.8](16-audit-faq-nlu-2026-07.md#168-post-scriptum--tentatives-de-correctif-expérimentées-le-soir-même).
  Reste **la** proposition la plus impactante de tout ce rapport, puisqu'elle
  touche les rangs 1 et 2 du classement simultanément.
- Jeu de test NLU non représentatif de l'usage réel : voir
  [16.6](16-audit-faq-nlu-2026-07.md#166-plan-damélioration-priorisé).

### P1 — Haute priorité (fort impact, sur des compétences mesurées fragiles)

- **Auditer la compétence Réclamation (rang 3) avec la même rigueur que
  FAQ/diagnostic (rang 1-2).** C'est la compétence cœur de métier la plus
  complexe en logique de dialogue (formulaire à sous-étapes) et pourtant la
  seule des quatre piliers à n'avoir *aucune* mesure adversariale chiffrée
  comparable à [16.1](16-audit-faq-nlu-2026-07.md#161-résultats-chiffrés).
  Un corpus construit sur le même principe (reformulations, fautes de
  frappe, registre familier, messages composites) mais ciblant
  spécifiquement `create_reclamation`/le remplissage de formulaire
  donnerait une vraie mesure là où il n'existe aujourd'hui qu'une
  impression qualitative issue des sessions de durcissement passées.
- **Couvrir `ask_complaint_status` par les mêmes gardes que les autres
  intentions "méta".** `rules.yml` note explicitement (règle *"Consult
  complaint status"*) que consulter le statut d'une réclamation pendant un
  *autre* flux en cours (formulaire actif, diagnostic en attente) "n'est
  pas un cas couvert ici" — contrairement à `bot_challenge`,
  `ask_capabilities`, `suggestion`, `plainte` et la notation de réponse, qui
  ont chacune une variante dédiée. Avec seulement 20 exemples
  d'entraînement (le plus faible volume après les intentions pilotées par
  bouton), c'est aussi l'intention la moins éprouvée du pilier
  Réclamation.
- **Clarifier si `select_faq_category`/`select_faq_question` doivent rester
  strictement pilotées par bouton.** Avec seulement 4 et 2 exemples
  d'entraînement, un utilisateur qui *taperait* le nom d'une catégorie
  plutôt que de cliquer le bouton correspondant n'a aujourd'hui presque
  aucune chance d'être classé correctement. Si le parcours est
  intentionnellement bouton-only (ce qui semble être le design actuel), le
  documenter explicitement évite qu'un futur contributeur ne perçoive ce
  faible volume comme un oubli ; sinon, enrichir ces deux intentions avec
  quelques formulations texte libre par catégorie/question.
- **Fermer la boucle de rétro-apprentissage FAQ**, déjà identifiée comme
  piste par l'audit ([16.7](16-audit-faq-nlu-2026-07.md#167-nouvelles-perspectives-damélioration)) :
  un rapport hebdomadaire simple à partir de `audit.agent_actions` et
  `response_ratings` (déjà journalisés, jamais exploités) transformerait la
  compétence Feedback (rang 4) en amélioration continue réelle pour FAQ et
  diagnostic, plutôt qu'en simple archive.

### P2 — Nettoyage et clarification

- **Statuer sur les 11 slots "dormants" et les entités jamais entraînées**
  listés en [18.3.D](#12-éléments-dormants-ou-résiduels) : soit les
  supprimer si la réutilisation par le formulaire de réclamation qui les
  justifie encore n'est plus d'actualité, soit documenter explicitement
  dans `domain.yml` (au-delà du commentaire déjà présent) qu'il s'agit d'un
  choix assumé, pour éviter qu'un futur audit ne les redécouvre comme une
  anomalie. Le commentaire déjà présent sur les entités mortes le dit bien :
  les déclarer sans jamais les entraîner "laisse croire qu'une extraction
  existe là où il n'y en a aucune" — un risque de confusion, pas seulement
  de propreté.
- Points déjà couverts, rappelés pour mémoire : service `fastapi` mort dans
  `docker-compose.yml` ([16.5](16-audit-faq-nlu-2026-07.md#165-failles-identifiées-classées-par-impact) #11),
  tableau de bord agent humain pour les tickets
  ([14.6](14-evolutions.md#146-nouvelles-fonctionnalités-envisageables)),
  sécurisation avant production ([14.1](14-evolutions.md#141-sécurisation-pour-la-production)).

## 18.6 Sources

Classement établi à partir de : `rasa/domain.yml`, `rasa/data/nlu.yml`
(comptage d'exemples par intention), `rasa/data/rules.yml`,
`rasa/actions/*.py`, `fastapi/services_registry.yaml`,
`fastapi/wallet_service/diagnostic/manifest.py`,
`fastapi/user_service/diagnostic/manifest.py`, et les chapitres
[01](01-presentation.md), [03](03-taxonomie.md), [04](04-services.md),
[06](06-api-reference.md), [13](13-limitations.md), [14](14-evolutions.md)
et [16](16-audit-faq-nlu-2026-07.md) de cette documentation. Aucune donnée
d'usage réel en production n'existe à ce jour (environnement de
développement uniquement, voir [13](13-limitations.md)) — ce classement
reflète l'importance *architecturale et documentée*, pas des statistiques
d'usage réelles, qui n'existent pas encore.

---

Fin de la documentation.
