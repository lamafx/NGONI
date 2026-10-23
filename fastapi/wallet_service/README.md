# wallet_service — service de test local pour le Diagnostic Engine

## Pourquoi ce dossier existe

Le vrai `ngoni-wallet-service` (PHP 8.3 + Postgres + Docker) n'est testable
que dans l'environnement de staging. Impossible donc, en local, de vérifier
que le **Diagnostic Engine** (`app/domains/diagnostic/`) sait vraiment
dialoguer en HTTP avec un service externe : appeler `GET /diagnostic/manifest`,
router vers `POST /diagnostic/withdrawal`, interpréter la réponse.

`wallet_service` est un **second processus**, totalement indépendant, qui répond
exactement aux mêmes routes avec le même contrat que le vrai wallet-service.
Il ne modifie et n'appelle **jamais** aucun fichier de `ngoni-wallet-service` :
on redirige simplement le Diagnostic Engine vers lui via une variable
d'environnement.

**Ce que ce service prouve** : que le Registry, l'Adapter et le Pipeline du
Diagnostic Engine fonctionnent correctement sur de vrais sockets HTTP, contre
de vraies données. **Ce qu'il ne prouve pas** : que `DiagnosticController.php`
est correct — ça, c'est le rôle de
`ngoni-wallet-service/tests/Feature/DiagnosticControllerTest.php`. La logique
de chaque fichier dans `diagnostic/services/` est une **copie manuelle** de ce
controller ; elle doit être mise à jour à la main si le controller PHP évolue
(seuils, nouvelles causes...).

## Organisation du code

```
wallet_service/
├── main.py                  # cree l'app FastAPI, inclut le router -- aucune logique
├── security.py              # verification du secret partage (header X-Internal-Secret)
├── outcomes.py               # construction des reponses RESOLVED / ESCALATE
├── db.py                     # modeles SQLAlchemy en LECTURE SEULE (schema `wallet`)
└── diagnostic/
    ├── manifest.py            # Capability Manifest (3 problemes)
    ├── router.py              # endpoints FastAPI, delegue tout a services/
    ├── formatting.py          # formatage de dates/durees commun
    └── services/               # un fichier par probleme, logique de resolution
        ├── withdrawal.py        # withdrawal_pending
        ├── topup.py              # topup_not_credited
        └── gift.py               # gift_not_received
```

Pour ajouter un nouveau problème diagnosticable, ajouter son entrée dans
`manifest.py`, créer `diagnostic/services/<probleme>.py` sur le modèle des
fichiers existants, et le brancher dans `router.py` — sans toucher au code
existant.

## Données : lecture seule sur un clone réel

`db.py` lit le schéma Postgres `wallet` de `chatbotdb` — un **clone** de la
vraie base de `ngoni-wallet-service`. Ce service n'écrit jamais dedans : il n'y a
pas d'endpoints de seed. Les cas de test se choisissent directement parmi les
lignes réelles déjà présentes dans le clone (voir les requêtes SQL ci-dessous).

## Lancer le service

```powershell
cd C:\DEV\PFE\fastapi
.venv\Scripts\python.exe -m uvicorn wallet_service.main:app --app-dir C:\DEV\PFE\fastapi --port 3103
```

Il écoute sur `http://127.0.0.1:3103`, exactement l'URL par défaut attendue
par `registry.py` (`WALLET_SERVICE_BASE_URL`).

## Lancer le Diagnostic Engine pointé dessus

Dans un second terminal :

```powershell
cd C:\DEV\PFE\fastapi
$env:WALLET_SERVICE_BASE_URL = "http://127.0.0.1:3103/api/v1"
$env:WALLET_SERVICE_INTERNAL_SECRET = "test-secret"
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

(`test-secret` est la valeur par défaut de `WALLET_SERVICE_INTERNAL_SECRET` côté
service — changez les deux ensemble si vous la personnalisez.)

## Trouver un cas de test dans le clone

```sql
-- Un retrait avec un statut donné, avec le user_id et la reference a utiliser
SELECT wt.user_id, wt.reference_id, wt.status, wt.created_at, w.kyc_verified
FROM wallet.wallet_transactions wt
JOIN wallet.wallets w ON w.id = wt.wallet_id
WHERE wt.type = 'WITHDRAWAL' AND wt.status = 'SUCCESS'  -- ou CANCELLED / FAILED / PENDING
LIMIT 10;
```

Puis interroger le vrai point d'entrée du Diagnostic Engine (celui que Rasa
appelle) :

```powershell
curl -X POST http://127.0.0.1:8000/diagnostic/resolve `
  -H "Content-Type: application/json" `
  -H "X-User-ID: <user_id trouvé ci-dessus>" `
  -d '{"session_id":"s1","service":"wallet","problem":"withdrawal_pending","entities":{"transaction_reference":"<reference_id trouvée ci-dessus>"}}'
```

## Scénarios couverts

| Ce que vous voulez tester | Condition en base | Résultat attendu |
|---|---|---|
| Retrait terminé | `wallet_transactions.status = SUCCESS` | `RESOLVED` / `WITHDRAWAL_COMPLETED` (avec montant, date, opérateur, numéro) |
| Retrait annulé | `status = CANCELLED` | `RESOLVED` / `WITHDRAWAL_CANCELLED_BY_USER` |
| Retrait échoué et remboursé | `status = FAILED` | `RESOLVED` / `WITHDRAWAL_FAILED_REFUNDED` |
| Retrait en cours normal | `status = PENDING`, âge < 120 min | `RESOLVED` / `PENDING_WITHIN_SLA` |
| Retrait bloqué anormalement | `status = PENDING`, âge ≥ 120 min | `ESCALATE` / `PENDING_BEYOND_SLA_NO_PROVIDER_RESPONSE` |
| Wallet inexistant | aucun wallet pour ce `user_id` | `ESCALATE` / `WALLET_NOT_FOUND` |
| Retrait jamais créé, KYC non validé | `wallets.kyc_verified = false`, aucun retrait avec cette référence | `RESOLVED` / `KYC_REQUIRED` |
| Retrait jamais créé, KYC validé | `kyc_verified = true`, aucun retrait avec cette référence | `ESCALATE` / `TRANSACTION_NOT_FOUND` |
| Plafond de retrait atteint | `total_withdrawals >= monthly_limit`, aucun retrait avec cette référence | `RESOLVED` / `LIMIT_EXCEEDED` |
| Compte gelé, aucune transaction | `wallets.status != ACTIVE`, aucun retrait avec cette référence | `ESCALATE` / `ACCOUNT_FROZEN` |
| Compte gelé, retrait déjà résolu (SUCCESS/CANCELLED/FAILED) | `status != ACTIVE` mais transaction déjà terminée | `RESOLVED` sur le vrai statut + note complémentaire sur le gel |
| Compte gelé, retrait encore PENDING | `status != ACTIVE` et transaction encore PENDING | `ESCALATE` / `ACCOUNT_FROZEN` (cause plausible ici) |

Les cas `ACCOUNT_FROZEN`/`LIMIT_EXCEEDED` ne sont pas présents nativement dans
le clone : pour les tester, modifier temporairement une ligne (`UPDATE
wallet.wallets SET status = 'FROZEN', frozen_reason = '...' WHERE user_id =
'...'`), tester, puis **restaurer immédiatement** (`status = 'ACTIVE'`).

## Tests automatisés

```powershell
.venv\Scripts\python.exe -m pytest tests\test_wallet_service.py -v
```

Ces tests ne couvrent que les cas génériques (sécurité, manifeste, wallet
introuvable, user_id invalide, champ manquant) : ils ne dépendent d'aucune
donnée précise du clone, contrairement aux scénarios du tableau ci-dessus qui
nécessitent d'aller chercher une vraie ligne à chaque fois.

## Ne jamais faire

- Ne pointez jamais ce service vers un environnement partagé/staging.
- Ne considérez pas les tests de ce service comme une validation du vrai
  `DiagnosticController.php` — seuls les tests Pest le valident réellement.
- N'écrivez jamais dans le clone autrement que temporairement pour un test,
  en restaurant systématiquement l'état d'origine juste après.
