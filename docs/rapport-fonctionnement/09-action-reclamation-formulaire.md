← [8. Diagnostic — exécution de l'action](08-action-diagnostic-execution.md) | → [10. FAQ — recherche sémantique](10-action-faq.md)

# 9. Réclamations — le formulaire

> **Rôle de ce document** : le parcours `reclamation_form`, de son
> déclenchement à la création du ticket — un chemin entièrement distinct du
> Diagnostic Engine (chapitres 7-8), pour les cas où l'utilisateur veut
> directement ouvrir une réclamation plutôt que diagnostiquer un problème
> connu.

## Ordre des champs : description d'abord

`reclamation_form.required_slots` (défaut) : `description`, `category`,
`incident_date`, puis `cancel_choice`/`field_to_edit` en sous-étapes (voir
[6. Rasa Core, policies, domaine](06-rasa-core-policies-domain.md)).
**La description est demandée en premier** — changement fait suite à un
retour utilisateur (2026-07 : "quel est le service concerné, ça n'aide pas
pour un public qui ne maîtrise pas la plateforme"). `validate_description`
tente de déduire la catégorie automatiquement à partir de ce que
l'utilisateur vient de décrire dans ses propres mots ; si ça réussit,
`category` est déjà rempli et n'est jamais redemandé.

## Validation de la description

`ValidateReclamationForm.validate_description` :

- Rejette une description vide ou trop courte, avec des messages
  **distincts** (`utter_wrong_description` vs `utter_description_too_short`
  — une description non vide mais trop vague comme "mon solde est faux"
  recevait auparavant le même message que "vide", ce qui ne veut rien dire
  pour l'utilisateur).
- **Tronque plutôt que de rejeter** au-delà de `MAX_DESCRIPTION_LENGTH`
  (2000 caractères) : un utilisateur qui colle un gros pavé de texte (SMS,
  email, capture convertie) a fait l'effort de tout fournir — le renvoyer
  au point de départ serait punitif pour rien. Le plafond protège contre
  l'épuisement de ressources, sans autre limite haute avant ce correctif.
- Déduit l'**urgence** automatiquement (`_infer_urgency_from_description`,
  mots-clés `URGENCY_HIGH_KEYWORDS`/etc.) — **jamais demandée à
  l'utilisateur** depuis un retour utilisateur (2026-07) : ce jugement doit
  être déduit du problème décrit, pas délégué à qui le décrit.

## Validation de la catégorie

`validate_category` accepte les codes bruts (`KYC`, `Wallet`, `Video`,
`Auth`, `Chat`, `Safety`) **et** leurs synonymes français courants
("portefeuille", "connexion", "identité"...) via `ALLOWED_CATEGORIES` — la
même table sert à reformuler `utter_ask_category`/`utter_wrong_category` en
langage naturel plutôt qu'en noms de service bruts. Un garde structurel
(`if set(ALLOWED_CATEGORIES.values()) != _DOMAIN_CATEGORY_VALUES: raise`)
empêche cette table de diverger silencieusement des valeurs déclarées dans
`rasa/domain.yml` — une erreur au chargement du module plutôt qu'une
incohérence silencieuse en production.

## Modifier ou annuler

Un "non" à la confirmation finale ne dit pas si l'utilisateur veut tout
abandonner ou juste corriger un champ — `ActionAskCancelClarification`
demande explicitement "modifier ou annuler ?" (`cancel_choice`), puis
`field_to_edit` si modification. Ces deux sous-étapes remplacent
temporairement la liste `required_slots` habituelle (voir
[6. Rasa Core](06-rasa-core-policies-domain.md)). Interprétation par
mots-clés bruts (`best_keyword_match`), pas par intent : des intents dédiés
(`modify_reclamation`/`confirm_full_cancel`) ont été tentés puis abandonnés
— leur vocabulaire, une fois entraîné, chevauchait fortement celui de `deny`
("annule", "corrige" y figurent déjà comme exemples), ce qui faisait dériver
la classification du simple "non" lui-même.

## Création du ticket (`ActionCreateTicket`)

`POST /tickets/create` (`TICKET_SERVICE_URL`) avec le résumé généré, la
catégorie, l'urgence déduite, `confirmation: "oui"`. Robustesse :

- Un **disjoncteur dédié** (`_TicketServiceCircuitBreaker`, état en mémoire
  du process actions) s'ouvre après plusieurs échecs consécutifs.
- Seul un **5xx** (ou une vraie panne réseau) compte comme un échec pour ce
  disjoncteur — un 4xx est traité comme un bug côté action server lui-même,
  jamais comme une preuve que le service de tickets est en panne
  (l'assimiler à une panne aurait ouvert le disjoncteur pour **tous** les
  utilisateurs à cause d'un seul payload invalide).
- Une réponse HTTP 200 mais sans `ticket_id`/`status` exploitable est
  traitée comme une erreur explicite plutôt que d'afficher silencieusement
  "None" à l'utilisateur.
- Voir [16. Domaines admin](16-domaines-admin-complaints-feedback-audit.md)
  pour la déduplication côté FastAPI par `idempotency_key` (une relance
  après timeout ne crée pas un second ticket).

## Consulter ses réclamations

`ActionConsultComplaints` (intent `ask_complaint_status`) répond à "où en
est ma réclamation ?" via `GET /complaints/mine` — ajouté suite à un retour
utilisateur, aucune action n'existait avant pour cette question pourtant
naturelle une fois un ticket créé.
