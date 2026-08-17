← [15. Diagnostic Engine — adapter et disjoncteur](15-diagnostic-engine-adapter-circuit-breaker.md) | → [17. Retour jusqu'à l'utilisateur](17-retour-reponse-utilisateur.md)

# 16. Les domaines simples derrière l'admin

> **Rôle de ce document** : les trois domaines FastAPI nettement plus
> simples que le Diagnostic Engine (chapitres 13-15) — CRUD classiques,
> mais c'est exactement ce que consomme le tableau de bord admin.

## Réclamations (`app/domains/complaints`, `ComplaintService`)

- `create_ticket` : exige une confirmation (`"oui"/"yes"/"o"/"y"`) et un
  résumé non vide. **Déduplication serveur** par `idempotency_key` — une
  relance après un commit réussi mais réponse perdue (timeout réseau côté
  appelant) renvoie le ticket **déjà créé** plutôt que d'en générer un
  second pour la même réclamation.
- ID de ticket : format `CMP-YYYYMMDD-XXXXXXXX` (préfixe date lisible/triable
  + suffixe hexadécimal de 8 caractères, >4 milliards de combinaisons) —
  remplace un ancien format `TCK-XXXX` qui bouclait toutes les ~2h45 et
  pouvait entrer en collision.
- `list_tickets`/`update_status` : ce que consomme directement l'admin
  (filtres statut/catégorie/urgence/créateur/utilisateur, pagination).

## Feedback (`app/domains/feedback`, `FeedbackService`)

- `create_entry` : valide le type (`suggestion`/`complaint_sentiment`),
  rejette un message vide, tronque à 2000 caractères (voir
  [11. Feedback](11-action-feedback.md)).
- **Suggestion et plainte créent chacune, en plus de leur entrée
  `feedback.entries`, un ticket de suivi** dans `complaints.complaints` —
  catégorie et urgence dédiées par type
  (`FEEDBACK_TICKET_CATEGORY`/`FEEDBACK_TICKET_URGENCY`), `created_by`
  dédié (`ai_feedback_ticket`) pour distinguer cette origine d'une
  réclamation classique (formulaire) ou d'une escalade de diagnostic.
- Ordre des écritures dans `create_entry` : les valeurs de l'entrée
  fraîchement créée sont capturées en variables Python simples **avant**
  tout appel DB supplémentaire (création du ticket) — un flush en échec sur
  cet appel suivant laisserait sinon la Session SQLAlchemy partagée dans un
  état "pending rollback", et toute relecture d'attribut ORM après coup
  échouerait avec `PendingRollbackError`, transformant un échec déjà géré
  en 500 brut.

## Audit (`app/domains/audit`, `AgentActionService`)

Liste blanche fermée des domaines valides :
`{"faq", "diagnostic_classification", "diagnostic_superagent"}` — pas un
ENUM Postgres, pour qu'une faute de frappe côté appelant (le serveur
d'actions Rasa) ne pollue jamais silencieusement la table avec des valeurs
incohérentes. `diagnostic_superagent` (2026-07-30) trace spécifiquement les
décisions du Mode Super-Agent (voir
[8. Diagnostic — exécution](08-action-diagnostic-execution.md)) — un
domaine distinct de `diagnostic_classification` car ce ne sont pas des
décisions de classification mais des décisions **d'action**, avec un
niveau de risque différent.

`record_faq_lookup` : fonction best-effort partagée entre `POST /faq/search`
et le raccourci `/api/chat` (voir [chapitre 3](03-api-chat.md)) — les deux
appellent `FaqService.find_best_answer` et doivent produire le même
événement d'audit. Ne lève jamais : une panne d'écriture ne doit pas faire
échouer la réponse FAQ déjà calculée.

## Ce que le dashboard affiche réellement

`frontend/modules/admin/controllers/dashboard.controller.js` appelle
`fetchComplaints`, `fetchRatings`, `fetchRecentActions` **en parallèle**
(`Promise.allSettled` — une panne individuelle n'empêche jamais les autres
cartes de s'afficher, chaque échec devient une alerte "service
indisponible" dédiée plutôt qu'un plantage global), puis
`buildDashboardViewModel` calcule les KPI affichés. Vérifié en conditions
réelles (2026-07-31, backend complet démarré) : "Réclamations ouvertes 199",
"Réclamations résolues 1", "Satisfaction utilisateur 60 %" — données réelles
de la base, pas des valeurs figées.
