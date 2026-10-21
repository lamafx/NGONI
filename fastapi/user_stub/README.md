# user_stub — stub de test local pour le Diagnostic Engine

## Pourquoi ce dossier existe

Le vrai `ngoni-user-service` (Laravel 11 + Postgres + Docker) n'est testable
que dans son propre environnement. Impossible donc, en local, de vérifier
que le **Diagnostic Engine** (`app/domains/diagnostic/`) sait vraiment
dialoguer en HTTP avec lui : appeler `GET /diagnostic/manifest`, router vers
`POST /diagnostic/kyc_status` (et les 4 autres), interpréter la réponse.

`user_stub` est un **second processus**, totalement indépendant, qui répond
avec le même contrat que le vrai `ngoni-user-service` sur les 5 problèmes
diagnosticables couverts. Il ne modifie et n'appelle **jamais** aucun
fichier de `ngoni-user-service` : on redirige simplement le Diagnostic
Engine vers lui via des variables d'environnement.

**Ce que ce stub prouve** : que le Registry, l'Adapter et le Pipeline du
Diagnostic Engine savent router vers un deuxième service (pas seulement
`wallet`), sur de vrais sockets HTTP, contre de vraies données. **Ce qu'il
ne prouve pas** : que les controllers PHP concernés sont corrects — la
logique de chaque `service_*.py` est une **copie manuelle** de leur
comportement ; elle doit être mise à jour à la main si le code PHP évolue.

## Pourquoi seulement 5 problèmes sur les 10 identifiés

Un audit du code de `ngoni-user-service` a identifié 10 problèmes candidats.
Seuls les 5 les mieux étayés (state machine complète + codes d'erreur déjà
explicites côté PHP) sont implémentés ici :

| Problème | Confiance | Raison |
|---|---|---|
| `kyc_status_issue` | Haute | `KycController`/`KycService`, statuts + `rejection_reason` déjà stockés |
| `account_access_blocked` | Haute | migration `006_add_suspension_fields`, raison + date + acteur admin stockés |
| `compliance_hold_blocking` | Haute | `ComplianceService` + `RequireNoHold`, codes d'erreur déjà explicites |
| `account_deletion_status` | Haute | `ProfileController::deleteAccount/reactivateAccount`, codes `NOT_DELETED`/`CANNOT_REACTIVATE` déjà en place |
| `parental_consent_status` | Haute | `ParentalConsentService`, state machine complète (pending/verified/rejected/expired) |

Écartés pour l'instant (voir l'audit complet pour le détail) :
- **Certification**, **NgoniCard**, **quota de contenu** — endpoints
  plausibles mais enum de statuts non vérifié en détail.
- **Retrait via destination de paiement non vérifiée** — chevauche
  potentiellement `wallet_stub` (`withdrawal_pending`) ; à trancher avec
  l'équipe avant d'ajouter un 6e problème ici.
- **Confusion de rôle/accès** — surtout une opération admin, rarement un
  motif d'appel spontané côté utilisateur.

## Organisation du code

```
user_stub/
├── main.py                  # cree l'app FastAPI, inclut le router -- aucune logique
├── security.py              # verification du secret partage (header X-Internal-Secret)
├── outcomes.py               # construction des reponses RESOLVED / ESCALATE
├── db.py                     # modeles SQLAlchemy en LECTURE SEULE (schema `users`)
└── diagnostic/
    ├── manifest.py            # Capability Manifest (5 problemes)
    ├── router.py              # endpoints FastAPI, delegue tout a services/
    ├── formatting.py          # formatage de dates commun
    └── services/               # un fichier par probleme, logique de resolution
        ├── kyc.py                # kyc_status_issue
        ├── account_status.py     # account_access_blocked
        ├── compliance.py         # compliance_hold_blocking
        ├── deletion.py           # account_deletion_status
        └── parental_consent.py   # parental_consent_status
```

## Données : lecture seule sur un clone réel

`db.py` lit le schéma Postgres `users` de `chatbotdb` — un **clone** de la
vraie base de `ngoni-user-service`. Ce stub n'écrit jamais dedans : il n'y a
pas d'endpoints de seed. Les cas de test se choisissent directement parmi les
lignes réelles déjà présentes dans le clone (voir les requêtes SQL ci-dessous).

Contrairement à `wallet_stub` (une référence de transaction par problème),
aucun de ces 5 problèmes ne demande de champ à l'utilisateur : tout se
résout à partir du seul `user_id`, déjà connu du Diagnostic Engine via le
contexte de la conversation (`required_fields=[]` partout dans le manifeste).

### ⚠️ Prérequis unique : droits sur le schéma `users`

Contrairement au schéma `wallet` (déjà accordé), `chatbot_user` n'a pas
encore de droit de lecture sur le schéma `users` du clone. À exécuter une
seule fois, avec un rôle disposant des droits nécessaires (propriétaire des
tables ou superutilisateur) :

```sql
GRANT USAGE ON SCHEMA users TO chatbot_user;
GRANT SELECT ON ALL TABLES IN SCHEMA users TO chatbot_user;
```

Sans ça, chaque appel échoue avec `psycopg.errors.InsufficientPrivilege:
droit refusé pour la table users` (constaté en testant ce stub).

## Lancer le stub

```powershell
cd C:\DEV\PFE\fastapi
.venv\Scripts\python.exe -m uvicorn user_stub.main:app --app-dir C:\DEV\PFE\fastapi --port 3104
```

Il écoute sur `http://127.0.0.1:3104`, exactement l'URL par défaut attendue
par `registry.py` (`USER_SERVICE_BASE_URL`) -- le Diagnostic Engine le
détecte donc automatiquement au démarrage, sans configuration
supplémentaire (comme pour `wallet`).

## Lancer le Diagnostic Engine pointé dessus

Dans un second terminal (les deux stubs peuvent tourner ensemble) :

```powershell
cd C:\DEV\PFE\fastapi
$env:WALLET_SERVICE_BASE_URL = "http://127.0.0.1:3103/api/v1"
$env:WALLET_SERVICE_INTERNAL_SECRET = "test-secret"
$env:USER_SERVICE_BASE_URL = "http://127.0.0.1:3104/api/v1"
$env:USER_SERVICE_INTERNAL_SECRET = "test-secret"
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

(`test-secret` est la valeur par défaut de `USER_STUB_INTERNAL_SECRET` côté
stub — changez les deux ensemble si vous la personnalisez.)

## Trouver un cas de test dans le clone

```sql
-- Utilisateurs avec un statut de compte ou KYC interessant
SELECT id, username, status, kyc_status, kyc_level, compliance_hold
FROM users.users
WHERE status != 'ACTIVE' OR kyc_status != 'PENDING' OR compliance_hold = true
LIMIT 10;

-- Demandes de suppression de compte en cours
SELECT user_id, soft_deleted_at, hard_delete_scheduled_for, hard_deleted_at
FROM users.account_deletions;

-- Demandes de consentement parental
SELECT child_id, parent_id, status, requested_at, request_expires_at
FROM users.parental_consents;
```

Puis interroger le vrai point d'entrée du Diagnostic Engine (celui que Rasa
appelle) :

```powershell
curl -X POST http://127.0.0.1:8000/diagnostic/resolve `
  -H "Content-Type: application/json" `
  -H "X-User-ID: <user_id trouvé ci-dessus>" `
  -d '{"session_id":"s1","service":"user","problem":"kyc_status_issue","entities":{}}'
```

## Scénarios couverts

| Problème | Condition en base | Résultat attendu |
|---|---|---|
| KYC déjà vérifié | `users.kyc_status IN ('VERIFIED','APPROVED')` | `RESOLVED` / `KYC_ALREADY_VERIFIED` |
| KYC jamais démarré | pas de ligne dans `kyc_submissions` | `RESOLVED` / `KYC_NOT_STARTED` |
| KYC en cours d'examen | dernière soumission `status='pending'` | `RESOLVED` / `KYC_UNDER_REVIEW` |
| KYC refusé | dernière soumission `status='rejected'` | `RESOLVED` / `KYC_REJECTED` |
| Compte actif | `users.status='ACTIVE'` | `RESOLVED` / `ACCOUNT_NOT_RESTRICTED` |
| Compte suspendu | `users.status='SUSPENDED'` | `RESOLVED` / `ACCOUNT_SUSPENDED` |
| Compte banni | `users.status='BANNED'` | `ESCALATE` / `ACCOUNT_BANNED` |
| Pas de blocage compliance | `compliance_hold=false` | `RESOLVED` / `NO_ACTIVE_HOLD` |
| Blocage avec échéance | `compliance_hold=true` + `compliance_hold_until` futur | `RESOLVED` / `HOLD_ACTIVE_WITH_DEADLINE` |
| Blocage nécessitant une revue | dernier `compliance_events.action IN ('manual_review','enhanced_kyc')` | `ESCALATE` / `HOLD_REQUIRES_MANUAL_REVIEW` |
| Compte non supprimé | pas de ligne dans `account_deletions` | `RESOLVED` / `NOT_DELETED` |
| Suppression en délai de grâce | `hard_delete_scheduled_for` futur, `hard_deleted_at` NULL | `RESOLVED` / `WITHIN_GRACE_PERIOD` |
| Suppression définitive | `hard_deleted_at` renseigné | `RESOLVED` / `CANNOT_REACTIVATE` |
| Consentement déjà vérifié | `parental_consents.status='verified'` | `RESOLVED` / `CONSENT_ALREADY_VERIFIED` |
| Consentement rejeté | `status='rejected'` | `RESOLVED` / `CONSENT_REJECTED` |
| Consentement expiré | `status='expired'` ou `request_expires_at` passé | `RESOLVED` / `CONSENT_EXPIRED` |

Ces scénarios ont été vérifiés (voir historique de session) contre le clone
réel une fois les droits accordés : les 8 problèmes (3 wallet + 5 user)
apparaissent bien dans `GET /diagnostic/capabilities`.

## Tests automatisés

Aucun test automatisé dédié pour l'instant (contrairement à
`wallet_stub/tests/test_wallet_stub.py`) — à ajouter si ce stub est amené à
vivre durablement plutôt que servir de preuve de branchement initiale.

## Ne jamais faire

- Ne pointez jamais ce stub vers un environnement partagé/staging.
- Ne considérez pas les tests de ce stub comme une validation du vrai code
  PHP de `ngoni-user-service` — seule sa propre suite de tests le valide
  réellement.
- N'écrivez jamais dans le clone autrement que temporairement pour un test,
  en restaurant systématiquement l'état d'origine juste après.
