"""Capability Manifest du service wallet -- identique a
DiagnosticController::manifest() cote ngoni-wallet-service."""

from app.domains.diagnostic.contracts import (
    CapabilityManifest,
    DiagnosticEndpoint,
    FieldSpec,
    ProblemDefinition,
    ResolutionCause,
)

MANIFEST = CapabilityManifest(
    service="wallet",
    manifest_version="1.0.0",
    base_url="http://127.0.0.1:3103/api/v1",
    protocol="REST",
    problems=[
        ProblemDefinition(
            id="withdrawal_pending",
            label="Retrait bloqué ou en attente",
            description=(
                "L'utilisateur a demandé un retrait d'argent depuis son portefeuille "
                "NGONI, mais l'argent n'a jamais été crédité, la transaction reste en "
                "attente, semble bloquée, annulée ou refusée."
            ),
            # Formulations plus proches de la maniere dont un utilisateur reel
            # se plaint (familier, indirect), en plus de la description
            # formelle ci-dessus -- voir ProblemDefinition.example_phrases.
            #
            # Audit qualite du code, cas classification "retrait bloque" :
            # aucune des phrases ci-dessus (avant ajout) n'employait le mot
            # "bloqué", pourtant la facon la plus naturelle dont un
            # utilisateur decrit ce probleme -- au point que "mon retrait est
            # bloqué" se rapprochait plus, par embedding, de 3 problemes
            # SANS RAPPORT cote service user (compliance_hold_blocking,
            # account_access_blocked, account_deletion_status) dont les
            # example_phrases utilisent, elles, explicitement "compte
            # bloqué". Mesure avant/apres cet ajout (similarite cosinus au
            # meilleur exemple, meme message test) :
            #   avant  : withdrawal_pending 0.8552 < compliance_hold_blocking 0.8855 (gagnant FAUX)
            #   apres  : withdrawal_pending 0.9284 > compliance_hold_blocking 0.8855 (gagnant CORRECT)
            # Correction a la source (corpus de reference sous-representatif)
            # plutot que par seuil/mot-cle cote classification -- voir
            # rasa/actions/diagnostic.py pour l'historique des tentatives
            # rejetees a ce niveau-la (_apply_keyword_tiebreak).
            example_phrases=[
                "Mon argent n'est jamais arrivé après mon retrait.",
                "J'attends toujours la somme que je devais recevoir après avoir retiré de l'argent.",
                "Ça fait plusieurs jours que rien n'a été crédité sur mon compte après ma demande de retrait.",
                "Mon retrait est bloqué depuis hier.",
                "Ça reste bloqué, je n'arrive pas à retirer mon argent.",
                "Mon retrait est resté bloqué, pourquoi ?",
                "Je veux retirer de l'argent mais mon retrait n'a jamais été crédité.",
                "J'ai demandé un retrait et la somme n'a toujours pas été créditée sur mon compte bancaire.",
                "Mon retrait ne passe toujours pas, ça bloque depuis ce matin.",
                "Ça coince, impossible de retirer mon argent depuis hier.",
            ],
            # "bloqué" retire (2026-07, cause #3) : redondant pour ce
            # probleme (embedding deja fort, 0.9284, voir mesure ci-dessus)
            # et CAUSE directe d'une collision -- _apply_keyword_tiebreak
            # promeut le SEUL candidat a mot-cle present, et ce mot generique
            # faisait gagner withdrawal_pending sur des messages
            # account_access_blocked reels ("compte est bloqué", verbe
            # intercale) qui n'avaient eux-memes aucun mot-cle present. Deja
            # la 2e fois qu'un mot-cle generique ajoute reactivement cree une
            # nouvelle collision ailleurs (voir commentaire ci-dessus) --
            # cette fois-ci retire plutot que reproduit ailleurs.
            keywords=["retrait", "withdrawal", "argent pas reçu"],
            endpoint=DiagnosticEndpoint(method="POST", path="/diagnostic/withdrawal"),
            required_fields=[
                FieldSpec(
                    name="transaction_reference",
                    type="string",
                    description="Référence du retrait, ex: WITHDRAW-xxxx",
                    pattern="^[A-Za-z0-9_-]{3,64}$",
                )
            ],
            optional_fields=[],
            # Groupe de repli (rapport utilisateur, "champs alternatifs") :
            # utilise a la place de transaction_reference quand l'utilisateur
            # indique explicitement ne pas l'avoir (intent
            # cannot_provide_field, rasa/actions/diagnostic.py) -- voir
            # services/withdrawal.py::_resolve_by_date_amount. Noms alignes
            # sur les entites NLU deja entrainees (incident_date/amount, voir
            # nlu.yml), pas de traduction cote Rasa necessaire.
            fallback_fields=[
                FieldSpec(
                    name="incident_date",
                    type="string",
                    description="Date du retrait (ex: hier, 21/07/2026)",
                ),
                FieldSpec(
                    name="amount",
                    type="string",
                    description="Montant du retrait",
                ),
            ],
            resolution_causes=[
                ResolutionCause(code="KYC_REQUIRED", action="redirect_kyc"),
                ResolutionCause(code="LIMIT_EXCEEDED", action="inform_limit"),
                ResolutionCause(code="PENDING_WITHIN_SLA", action="reassure_wait"),
                ResolutionCause(code="WITHDRAWAL_COMPLETED", action="confirm_delivered"),
                ResolutionCause(code="WITHDRAWAL_CANCELLED_BY_USER", action="confirm_cancelled"),
                ResolutionCause(code="WITHDRAWAL_FAILED_REFUNDED", action="confirm_refunded"),
            ],
            escalation_causes=[
                "WALLET_NOT_FOUND",
                "ACCOUNT_FROZEN",
                "TRANSACTION_NOT_FOUND",
                "PENDING_BEYOND_SLA_NO_PROVIDER_RESPONSE",
                "UNKNOWN_STATUS",
                "AMBIGUOUS_DATE_OR_AMOUNT",
                "MULTIPLE_TRANSACTIONS_MATCH",
            ],
        ),
        ProblemDefinition(
            id="topup_not_credited",
            label="Recharge non créditée",
            description=(
                "L'utilisateur a rechargé son portefeuille NGONI via un moyen de "
                "paiement mobile, mais la somme n'a jamais été créditée sur son "
                "solde, la recharge semble bloquée, échouée ou en attente."
            ),
            # Audit qualite du code, meme methode que withdrawal_pending
            # ci-dessus : "ma recharge n'apparaît pas sur mon compte"
            # perdait face a account_deletion_status/account_access_blocked
            # (vocabulaire "compte" trop generique partage entre problemes),
            # et cette entree n'employait jamais "bloquée" bien que ce soit
            # le mot de la description formelle. Mesure avant/apres (marge
            # relative sur ce message-test) : 0.85% (gagnant FAUX) -> 1.8-5%
            # (gagnant correct) apres les 5 ajouts ci-dessous.
            #
            # Ajout complementaire suite a la mise en place de la suite de
            # non-regression (fonctionnalite #1, test_diagnostic_classification_quality.py) :
            # "j'ai credite mon wallet mais ca ne montre rien sur mon compte"
            # gagnait bien vers ce probleme mais avec une marge de 1.82% --
            # sous le seuil de 2% (CLASSIFICATION_RELATIVE_MARGIN cote Rasa),
            # risque de bascule au moindre futur changement de manifeste.
            # La phrase "J'ai crédité mon wallet..." ci-dessous fait remonter
            # la marge a 5.4%.
            # Ajout suite a la grande vague de tests conversationnels (2026-07) :
            # "ma recharge de ce matin n'a toujours pas ete creditee" se
            # verrouillait A TORT sur withdrawal_pending (gagnant net, pas
            # meme une egalite) -- aucune formulation de reference n'utilisait
            # jusque-la "toujours pas ete creditee", pourtant tres proche de
            # la description formelle de ce probleme.
            example_phrases=[
                "J'ai rechargé mon compte mais mon solde n'a pas bougé.",
                "Ma recharge Orange Money n'apparaît toujours pas sur mon wallet.",
                "J'ai payé pour recharger mais je n'ai rien reçu depuis.",
                "Ma recharge n'apparaît pas sur mon solde, l'argent n'a pas été ajouté.",
                "J'ai fait une recharge qui n'apparaît nulle part sur mon compte NGONI.",
                "Ma recharge mobile money est introuvable sur mon wallet.",
                "Ma recharge ne s'affiche pas sur mon compte NGONI.",
                "J'ai crédité mon wallet mais mon compte ne montre rien de nouveau.",
                "Ma recharge est restée bloquée, l'argent n'a pas été crédité sur mon wallet.",
                "Ma recharge de ce matin n'a toujours pas été créditée sur mon compte.",
            ],
            keywords=["recharge", "topup", "rechargé", "solde pas crédité"],
            endpoint=DiagnosticEndpoint(method="POST", path="/diagnostic/topup"),
            required_fields=[
                FieldSpec(
                    name="transaction_reference",
                    type="string",
                    description="Référence de la recharge, ex: TOPUP-20260708153045-A1B2C3D4",
                    pattern="^[A-Za-z0-9_-]{3,64}$",
                )
            ],
            optional_fields=[],
            resolution_causes=[
                ResolutionCause(code="PENDING_WITHIN_SLA", action="reassure_wait"),
                ResolutionCause(code="TOPUP_COMPLETED", action="confirm_credited"),
                ResolutionCause(code="TOPUP_FAILED_NOT_DEBITED", action="confirm_not_debited"),
            ],
            escalation_causes=[
                "WALLET_NOT_FOUND",
                "ACCOUNT_FROZEN",
                "TRANSACTION_NOT_FOUND",
                "PENDING_BEYOND_SLA_NO_PROVIDER_RESPONSE",
                "UNKNOWN_STATUS",
            ],
        ),
        ProblemDefinition(
            id="gift_not_received",
            label="Cadeau envoyé mais non reçu",
            description=(
                "L'utilisateur a envoyé un cadeau (pièces) à un autre utilisateur "
                "NGONI, mais le destinataire indique ne jamais l'avoir reçu."
            ),
            example_phrases=[
                "J'ai envoyé un cadeau mais la personne dit ne rien avoir reçu.",
                "Mon cadeau a débité mes pièces mais n'est jamais arrivé chez le destinataire.",
                "J'ai offert des pièces à quelqu'un et il ne les a pas reçues.",
                "Le cadeau que j'ai envoyé n'est jamais arrivé chez mon ami.",
                "J'ai envoyé des pièces en cadeau, jamais reçues par le destinataire.",
            ],
            keywords=["cadeau", "gift", "non reçu", "pièces envoyées"],
            endpoint=DiagnosticEndpoint(method="POST", path="/diagnostic/gift"),
            required_fields=[
                FieldSpec(
                    name="gift_reference",
                    type="string",
                    description="Référence du cadeau envoyé, ex: GFT-XXXXXXXXXXXX",
                    pattern="^[A-Za-z0-9_-]{3,64}$",
                )
            ],
            optional_fields=[],
            resolution_causes=[
                ResolutionCause(code="GIFT_DELIVERED", action="confirm_delivered"),
            ],
            escalation_causes=[
                "TRANSACTION_NOT_FOUND",
                "SENT_WITHOUT_RECEIVED_PAIR",
                "UNKNOWN_STATUS",
            ],
        ),
    ],
)
