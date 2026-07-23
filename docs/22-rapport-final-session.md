← [Sommaire](README.md) | [21. Rapport de bouclage feedback](21-rapport-feedback.md)

# 22. Rapport final de session (2026-07-23)

Session d'exécution de `docs/taches.txt` (le backlog figé issu des audits
16/18/19), en local, avec Rasa+actions en Docker, FastAPI et Postgres
natifs sur l'hôte — conformément à `docs/10-deploiement.md`. Ce chapitre
statue sur l'état final, item par item, et sert de rapport de session.

## 22.1 État final par point de `docs/taches.txt`

### P0 — le plus important

| # | Point | État |
|---|---|---|
| 1 | Sort de CamemBERT | **Tranché : abandon formel.** Voir [20.1](20-rapport-retrain-v7.md#201-décision--abandon-formel-de-camembert). `transformers`/`sentencepiece` retirés de `rasa/Dockerfile`. Modèles/config d'expérimentation conservés pour référence (`rasa/models/experiments/`, `config-embedding-experiment.yml`). |
| 2 | Réentraîner/redéployer avec les changements déjà prêts | **Fait, mesuré, puis rollback décidé.** Voir [20.3-20.4](20-rapport-retrain-v7.md#203-réentraînement-v7--résultats) : `ask_complaint_status` corrigé (0→100% recall) mais accuracy globale -4,5pt et collision `ask_faq`/`diagnostic` aggravée (diagnostic precision -33,7pt). `retrained-audit-fixes-v7.tar.gz` déplacé vers `models/experiments/`, `test-audit-quick.tar.gz` remis en service et confirmé (`GET /status`). Les changements `nlu.yml`/`rules.yml`/`domain.yml` restent dans le dépôt pour une future tentative combinée avec le point P0-2 de 20.4 (traiter le déséquilibre 387/210 en même temps). |
| 3 | Remplacer `test_nlu.yml` par un corpus indépendant permanent | **Partiellement fait.** `tests/test_nlu_adversarial.yml` (90 exemples, déjà indépendant) formalisé comme corpus de non-régression de référence pour tout futur réentraînement (utilisé pour mesurer v7). `test_nlu.yml` lui-même n'a pas été remplacé/étendu — construire un corpus encore plus large est un travail de contenu, hors de portée d'une session (voir 22.6). |

### P1

| # | Point | État |
|---|---|---|
| 4 | Recréer/reseeder `core.faq_items` | **Fait, mais le diagnostic initial était faux — corrigé en cours de session.** Les 26 lignes réelles (dédupliquées, 5 doublons retirés — [migrations/0011](../fastapi/migrations/0011_faq_items_dedup.sql)) existaient déjà, seulement introuvables via le mauvais Postgres (voir 22.4). Exportées vers `fastapi/seeds/faq_items.sql`, committé, idempotent, vérifié par exécution réelle. |
| 5 | Script de bouclage feedback hebdomadaire | **Fait.** `fastapi/scripts/weekly_feedback_report.py`. Bonus : a révélé que les deux tables sources ne sont **pas** à 0 ligne contrairement à l'hypothèse de `taches.txt` — voir [21.1](21-rapport-feedback.md#211-correction-dun-fait-supposé-par-tachestxt), signal réel déjà exploitable (candidats FAQ manquants identifiés : parrainage, désactivation des notifications). |
| 6 | Recalibrer `DEFAULT_THRESHOLD` | **Non fait, outillage prêt.** Nécessite le corpus de 306 paires de l'audit du 16 juillet, jamais committé — irréalisable telle quelle. Prérequis explicitement demandé par 16.6 ("exposer le score même sous le seuil") livré : `POST /faq/debug/search`. |
| 7 | Recherche hybride lexicale + sémantique | **Fait et vérifié en conditions réelles.** `keywords` (jamais lue avant) boost désormais le score cosinus (`+0,02/mot-clé, max +0,05`). Cas réel observé : "des questions sur mon wallet et mes pièces" passe de 0,840 (sous seuil) à 0,860 (au-dessus) grâce au mot-clé "wallet". |
| 8 | `find_closest` → Top-3 avec second seuil | **Fait et vérifié.** `find_top_matches` (seuil secondaire 0,75) + `GET /faq/by-slug/{slug}` + bouton "vouliez-vous dire..." côté Rasa. Exemple réel : "modifier" (message elliptique) → suggestion "Comment modifier mes informations personnelles ?" (score 0,809). |
| 9 | Dédupliquer le catalogue + garde-fou anti-doublon | **Fait et vérifié.** 5 doublons retirés (migration 0011). Garde-fou dans `FaqService.add_faq` (seuil 0,97) testé en conditions réelles : tentative d'ajout d'un quasi-doublon correctement rejetée (score 0,990, log confirmé). |
| 10 | Détection de message composite | **Fait.** `rasa/actions/faq.py::_has_composite_incident_signal` — propose l'ouverture d'une réclamation en plus de la réponse FAQ quand un signal d'urgence/délai anormal co-existe. Vérifié unitairement (mots-clés + `depuis X jours`). |
| 11 | Remesurer `ask_complaint_status` après réentraînement | **Fait.** Voir point P0-2 : 0 % → 100 % recall confirmé sur le corpus adversarial. |

### P2

| # | Point | État |
|---|---|---|
| 12 | Messages courts/elliptiques (< 3 mots) | **Fait, nécessite un réentraînement pour s'activer.** Nouveau composant NLU `components/short_message_router.py`, câblé dans `config.yml` juste après `VocabularyCoverageGuard`. Portée volontairement étroite (ne reroute que `diagnostic`→`ask_faq` sur message court, le seul cas mesuré en 16.4) — vérifié manuellement que `/faq/search` gère déjà bien ces messages une fois l'intention correcte ("KYC", "retrait" → réponse directe ; "modifier" → suggestion Top-3). **Pas encore actif tant qu'un nouveau `rasa train` n'a pas été fait** (le rollback vers `test-audit-quick.tar.gz` ne contient pas ce composant). |
| 13 | Index ivfflat/hnsw | Non fait, toujours prématuré (26 lignes) — inchangé depuis 16.6. |
| 14 | Non-régression automatisée FAQ | **Fait.** `fastapi/tests/test_faq_service.py` (10 tests, logique pure, sans DB) + `test_faq_repository.py` (5 tests, contre le vrai Postgres+pgvector). 15/15 verts. |
| 15 | Service `fastapi` mort dans `docker-compose.yml` | **Fait (corrigé, pas seulement documenté).** `RASA_PARSE_URL`/`RASA_WEBHOOK_URL` ajoutés (seul vrai manque, `DATABASE_URL` était déjà correct) + commentaire explicite renvoyant vers `docs/10-deploiement.md` sur le mode réel d'exécution. Validé via `docker compose config`. |
| 16 | Sécurisation avant production | **Partiellement fait.** Rate limiting basique ajouté (`app/shared/rate_limit.py`, in-memory, 30 req/60s sur `/api/chat`, `/faq/search`, `/complaints(/tickets)/create`), vérifié en conditions réelles (429 après 30 requêtes). Authentification réelle, HTTPS, gestion des secrets : **hors de portée**, décision produit sur le mécanisme d'identité (voir 22.6). |
| 17 | CI/CD | **Fait (fichier livré, non exécuté).** `.gitlab-ci.yml` (stages test/security/build), style aligné sur les services soeurs. Syntaxe YAML validée localement, séquence d'init DB rejouée manuellement (voir 22.4 pour l'incident que ce test a provoqué) — **aucun runner GitLab disponible ici pour une validation d'exécution réelle**. |
| 18 | Tableau de bord agent humain | Non fait — fonctionnalité frontend complète, plusieurs jours de travail, hors de portée. |
| 19 | Support multilingue | Non fait — nécessite une décision produit préalable (langues cibles). |

## 22.2 Décisions actées avec le mainteneur

1. **CamemBERT : abandon formel** (gain +1,2pt jugé insuffisant face au coût ~15-20x de latence).
2. **Urgence (réclamation) : automatisation complète.** Sur demande explicite en cours de session — plus jamais demandée à l'utilisateur, déduite automatiquement de la description (`_infer_urgency_from_description`, mots-clés + délai anormal détecté). Voir [20.2](20-rapport-retrain-v7.md#202-automatisation-du-niveau-durgence-réclamation).
3. **Modèle v7 : rollback**, gain localisé jugé insuffisant face à la régression sur les deux compétences les plus centrales du projet (diagnostic, FAQ).

## 22.3 Incident de session et correction

En testant la rejouabilité de la séquence d'initialisation DB pour `.gitlab-ci.yml`,
j'ai rejoué `migrations/0001_e5_base_upgrade.sql` sur la vraie base de
développement — une migration en 3 étapes documentée comme s'exécutant
**une seule fois** (elle vide délibérément la colonne `embedding` à l'étape
1/3), mais sans garde d'idempotence ni avertissement dans son nom de
fichier. Conséquence : les 26 embeddings réels sont passés à `NULL`,
provoquant des erreurs 500 aléatoires sur `/faq/search` (repérées pendant
le test du rate limiting). **Corrigé immédiatement** avec l'outil déjà
prévu à cet effet (`scripts/reembed_faq.py`, qui recalcule chaque embedding
depuis le texte de question — jamais perdu) et la contrainte `NOT NULL`
restaurée. Vérifié : les 15 tests FAQ et le rate limiting repassent au
vert. Aucune perte de contenu (question/réponse/mots-clés intacts tout du
long) — uniquement des vecteurs dérivés, entièrement recalculables.

**Leçon retenue** : les migrations `0001` (destructive, 3 étapes) diffèrent
de `0002`-`0011` (idempotentes ou sans risque de perte) sans que cela soit
visible autrement que par lecture attentive du fichier — un avertissement
explicite dans son nom ou un garde-fou SQL (`WHERE embedding IS NOT NULL`
avant l'`ALTER`, ou un simple `\prompt` de confirmation) éviterait qu'un
futur rejeu accidentel (script, nouvel arrivant suivant `migrations/*.sql`
dans l'ordre sans lire chaque commentaire) ne reproduise cet incident.

## 22.4 État de l'environnement à la fin de la session

- **Rasa** (`pfe-rasa-1`, Docker) : sert `test-audit-quick.tar.gz` (modèle
  antérieur à cette session — v7 rejeté, voir 22.1 P0-2). Les changements de
  cette session (`short_message_router`, `nlu.yml`/`rules.yml` déjà présents
  avant la session) **nécessitent un nouveau `rasa train`** pour être actifs.
- **Actions** (`pfe-actions-1`, Docker) : à jour du code (`faq.py`,
  `reclamation.py`) — un redémarrage du conteneur suffit pour charger ces
  changements Python (pas besoin de réentraîner, contrairement à Rasa NLU).
- **FastAPI** : natif sur l'hôte (`.venv`), relancé pendant la session,
  toutes les modifications actives (recherche hybride, Top-3, garde-fou
  anti-doublon, rate limiting, endpoints debug/by-slug).
- **Postgres** : natif sur l'hôte (`postgresql-x64-17`), `chatbotdb` —
  catalogue FAQ à 26 lignes réelles, embeddings intègres (vérifiés).
  Conteneur Docker `pfe-postgres-1` (service `postgres` du compose) laissé
  dans l'état où je l'ai trouvé au démarrage de la session (arrêté) — non
  utilisé en pratique, voir `docs/10-deploiement.md`.

## 22.5 Explicitement hors de portée — recommandations

- **Recalibration réelle de `DEFAULT_THRESHOLD`/`SECONDARY_THRESHOLD`** :
  l'outillage existe (`/faq/debug/search`), il manque un corpus de mesure
  bien plus large que 15+10. À planifier comme un audit dédié.
- **Corpus `test_nlu.yml` de remplacement** : travail de contenu (rédaction
  de nouveaux exemples par quelqu'un d'indépendant de l'entraînement),
  distinct du travail d'ingénierie de cette session.
- **Authentification réelle, HTTPS, gestion des secrets** : décision produit
  sur le mécanisme d'identité (JWT ? session ? fournisseur externe ?) avant
  tout travail technique — le rate limiting ajouté cette session est un
  filet, pas un substitut.
- **Tableau de bord agent humain** et **support multilingue** : fonctionnalités
  produit complètes, chacune nécessitant son propre cadrage.
- **CamemBERT, si le sujet revient** : conditions déjà posées en 16.8/20.1
  (mesurer la latence bout-en-bout réelle, traiter le déséquilibre 387/210
  en même temps, envisager `distilbert`).
- **Migrations non-idempotentes** (`0001`, et dans une moindre mesure
  `0008`/`0009` qui échouent proprement sans dégât — voir 22.3) : un garde-fou
  ou un avertissement explicite éviterait une répétition de l'incident 22.3.

## 22.6 Vérification

```bash
# Suite de tests FastAPI complète (117/118 verts — le seul echec,
# test_diagnostic_classification_quality, est pre-existant et sans rapport
# avec cette session, deja documente comme fragile par son propre message).
cd fastapi && .venv/Scripts/python.exe -m pytest tests/ -v

# Rasa : validation de coherence des donnees
docker exec pfe-rasa-1 rasa data validate

# FAQ en conditions reelles (Postgres natif, 26 lignes)
curl -X POST http://127.0.0.1:8000/faq/search -H "Content-Type: application/json" -d '{"question": "comment acheter des pieces ngoni"}'
curl -X POST "http://127.0.0.1:8000/faq/debug/search?k=5" -H "Content-Type: application/json" -d '{"question": "..."}'

# Rapport de bouclage feedback
cd fastapi && .venv/Scripts/python.exe scripts/weekly_feedback_report.py --days 7

# docker-compose : configuration resolue (sans lancer les conteneurs)
docker compose config
```

---

Fin de la documentation de session.
