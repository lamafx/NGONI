"""Capability Manifest du service user -- couvre les 5 problemes les mieux
etayes par le code de ngoni-user-service (voir l'audit : state machine +
codes d'erreur deja explicites cote controllers/services PHP). Les 5 autres
candidats identifies (certification, NgoniCard, quota de contenu, retrait via
payout_destination, confusion de role) sont volontairement laisses de cote --
preuve plus faible ou chevauchement avec un manifeste existant (voir
README.md).

Contrairement au wallet (une reference par transaction), ces problemes sont
tous resolubles a partir du seul user_id, deja connu du Diagnostic Engine
via le contexte de la conversation : aucun champ n'est donc a collecter
aupres de l'utilisateur (required_fields=[] partout)."""

from app.domains.diagnostic.contracts import (
    CapabilityManifest,
    DiagnosticEndpoint,
    ProblemDefinition,
    ResolutionCause,
)

MANIFEST = CapabilityManifest(
    service="user",
    manifest_version="1.0.0",
    base_url="http://127.0.0.1:3104/api/v1",
    protocol="REST",
    problems=[
        ProblemDefinition(
            id="kyc_status_issue",
            label="Vérification d'identité (KYC) refusée ou bloquée",
            description=(
                "L'utilisateur a soumis une vérification d'identité (KYC) mais elle est refusée, "
                "reste bloquée en attente d'examen, ou il ne comprend pas où en est son dossier."
            ),
            # Ajouts suite a la grande vague de tests conversationnels (2026-07) :
            # "j'ai soumis mes documents d'identite mais rien ne se passe" et
            # "mon kyc est bloque depuis longtemps" diluaient (egalite a 3
            # avec topup_not_credited/compliance_hold_blocking), faute de
            # formulation de reference assez proche dans ce manifeste.
            example_phrases=[
                "Pourquoi mon KYC est refusé ?",
                "Je n'arrive pas à valider mon identité.",
                "Ça fait longtemps que ma vérification d'identité est en attente.",
                "Mon dossier d'identité est refusé, je ne comprends pas pourquoi.",
                "Mon dossier KYC a été rejeté.",
                "Pourquoi mon dossier de vérification d'identité est-il refusé ?",
                "J'ai soumis mes documents d'identité mais rien ne se passe depuis.",
                "Mon KYC est bloqué depuis longtemps, toujours pas de nouvelles.",
                "Mes documents d'identité sont en attente d'examen depuis trop longtemps.",
                # Questions de SUIVI (2026-10-23) : posees apres l'envoi d'une
                # nouvelle piece, sans le mot « identite » -- « ou en est ma
                # verification ? » partait vers account_deletion_status.
                "Où en est ma vérification ?",
                "Est-ce que mon compte est vérifié maintenant ?",
                "Mon KYC est-il validé ?",
                "Ma vérification est-elle terminée ?",
            ],
            keywords=["kyc", "vérification d'identité", "identité refusée", "document refusé"],
            endpoint=DiagnosticEndpoint(method="POST", path="/diagnostic/kyc_status"),
            required_fields=[],
            optional_fields=[],
            resolution_causes=[
                ResolutionCause(code="KYC_ALREADY_VERIFIED", action="reassure_verified"),
                ResolutionCause(code="KYC_NOT_STARTED", action="guide_to_kyc_form"),
                ResolutionCause(code="KYC_UNDER_REVIEW", action="reassure_wait"),
                ResolutionCause(code="KYC_REJECTED", action="explain_rejection"),
            ],
            escalation_causes=["USER_NOT_FOUND", "KYC_STATUS_MISMATCH", "UNKNOWN_STATUS"],
        ),
        ProblemDefinition(
            id="account_access_blocked",
            label="Compte suspendu ou banni",
            description=(
                "L'utilisateur n'arrive plus à utiliser son compte NGONI et pense qu'il a été "
                "suspendu, bloqué ou banni, sans en connaître la raison."
            ),
            # Audit qualite du code : symetrique du fix applique a
            # withdrawal_pending (wallet_service) -- ces exemples disaient
            # "suspendu"/"banni" mais jamais "bloqué", pourtant la
            # formulation la plus naturelle ("mon compte est bloqué"),
            # ce qui le faisait perdre face a compliance_hold_blocking
            # (dont les exemples utilisent, eux, "compte bloqué"
            # explicitement). Voir wallet_service/diagnostic/manifest.py pour
            # le detail chiffre de la mesure avant/apres sur ce meme type
            # de correction.
            # Ajouts suite a la grande vague de tests conversationnels (2026-07) :
            # "mon acces a ete coupe sans prevenir" et "suspendu du jour au
            # lendemain" diluaient (egalite avec account_deletion_status/
            # topup_not_credited), le vocabulaire "acces coupe" n'etant
            # jusque-la couvert par aucune formulation de reference.
            # Ajouts suite au test de 97 explications directes (2026-07,
            # cause #3) : 3 messages reels ("compte EST bloque"/"compte est
            # reste bloque", verbe intercale) verrouillaient a tort sur
            # withdrawal_pending (wallet), qui avait recu "bloque" comme
            # mot-cle lors d'un correctif anterieur -- ce probleme n'avait
            # ZERO mot-cle present sur ces 3 messages (son propre mot-cle
            # "compte bloqué" exige les deux mots adjacents). Verifie via
            # /diagnostic/debug/classify avant ajout.
            example_phrases=[
                "Pourquoi je ne peux plus utiliser mon compte ?",
                "Mon compte a été suspendu, je ne sais pas pourquoi.",
                "On m'a banni sans explication.",
                "Je n'arrive plus à me connecter à mon compte, il semble bloqué.",
                "Mon compte est bloqué et je ne comprends pas pourquoi.",
                "Impossible d'accéder à mon compte depuis ce matin, il est bloqué.",
                "Mon accès à mon compte a été coupé sans prévenir.",
                "Mon compte a été suspendu du jour au lendemain sans raison.",
                "Je n'arrive plus à me connecter, mon accès est bloqué.",
                "Mon compte est bloqué depuis hier soir et l'application refuse toute connexion, même avec le bon mot de passe.",
                "Depuis une mise à jour, mon compte est resté bloqué et je ne peux plus du tout me connecter.",
            ],
            keywords=["suspendu", "banni", "compte bloqué", "restriction compte", "connecter", "connexion", "accès"],
            endpoint=DiagnosticEndpoint(method="POST", path="/diagnostic/account_status"),
            required_fields=[],
            optional_fields=[],
            resolution_causes=[
                ResolutionCause(code="ACCOUNT_NOT_RESTRICTED", action="reassure_active"),
                ResolutionCause(code="ACCOUNT_SUSPENDED", action="explain_suspension"),
            ],
            escalation_causes=["USER_NOT_FOUND", "ACCOUNT_BANNED", "UNKNOWN_STATUS"],
        ),
        ProblemDefinition(
            id="compliance_hold_blocking",
            label="Blocage de conformité (compliance)",
            description=(
                "L'utilisateur ne peut plus effectuer certaines actions (retrait, abonnement...) "
                "et voit un message évoquant un contrôle ou blocage de conformité."
            ),
            # Ajout suite a la grande vague de tests conversationnels (2026-07) :
            # "bloque par un controle conformite depuis hier" diluait
            # (egalite avec withdrawal_pending/account_access_blocked).
            example_phrases=[
                "Ça dit que mon compte est bloqué pour conformité, je ne comprends pas.",
                "Je ne peux plus rien faire, c'est écrit compliance hold.",
                "Pourquoi mon compte est sous contrôle ?",
                "Un contrôle de conformité bloque mes actions.",
                "Je ne peux plus rien faire sur mon compte, un message parle de conformité.",
                "Mon compte est en attente de vérification conformité (compliance hold).",
                "Mon compte est bloqué par un contrôle de conformité depuis hier.",
            ],
            keywords=["compliance", "conformité", "blocage compte", "contrôle compte"],
            endpoint=DiagnosticEndpoint(method="POST", path="/diagnostic/compliance_hold"),
            required_fields=[],
            optional_fields=[],
            resolution_causes=[
                ResolutionCause(code="NO_ACTIVE_HOLD", action="reassure_no_hold"),
                ResolutionCause(code="HOLD_ACTIVE_WITH_DEADLINE", action="inform_deadline"),
                ResolutionCause(code="HOLD_ACTIVE", action="inform_generic"),
            ],
            escalation_causes=[
                "USER_NOT_FOUND",
                "HOLD_REQUIRES_MANUAL_REVIEW",
                "HOLD_ESCALATED_TO_SUSPENSION",
                "UNKNOWN_STATUS",
            ],
        ),
        ProblemDefinition(
            id="account_deletion_status",
            label="Suppression de compte ou confusion GDPR",
            description=(
                "L'utilisateur a supprimé son compte par erreur, veut savoir s'il peut encore le "
                "récupérer, ou ne comprend pas l'état de sa demande de suppression."
            ),
            # Audit qualite du code : "Je n'arrive pas à réactiver mon
            # compte." (seule, sans contexte de suppression) etait trop
            # generique -- sa structure ("je n'arrive pas a ... mon
            # compte") ressemblait a n'importe quelle plainte negative sur
            # un compte, au point de gagner a tort face a topup_not_credited
            # sur "ma recharge n'apparaît pas sur mon compte" (aucun rapport
            # reel). Ancree au contexte suppression ci-dessous.
            # Ajouts suite a la grande vague de tests conversationnels (2026-07) :
            # "traine depuis des semaines", "aucune nouvelle depuis" et
            # "annuler la suppression" diluaient (egalite avec kyc_status_issue/
            # withdrawal_pending/compliance_hold_blocking).
            # Tentative 2026-07 (test de 97 explications directes, cause #3) :
            # densifier le vocabulaire "suppression"/RGPD pour corriger 3 cas
            # ou ce probleme perdait/etait dilue sur ses PROPRES messages.
            # REVERTEE apres mesure : a bien corrige ces 3 cas, mais a
            # deplace la collision plutot que la resoudre (+1 nouvelle
            # regression sur parental_consent_status, aucune amelioration
            # sur les 5 collisions ou ce probleme reste un faux candidat
            # pour topup_not_credited/kyc_status_issue/parental_consent_status
            # -- renforcer son embedding le rend aussi plus "attirant" pour
            # les messages voisins). Confirme empiriquement que ce levier
            # (patch de vocabulaire) est a bout de souffle ici : le reste de
            # la dilution intra-service necessite une vraie discussion
            # d'architecture (ex. classification en 2 temps au sein meme du
            # service "user"), pas un nouveau patch ponctuel.
            example_phrases=[
                "J'ai supprimé mon compte par erreur, comment le récupérer ?",
                "Mon compte affiche encore comme supprimé.",
                "Je n'arrive pas à réactiver mon compte après l'avoir supprimé.",
                "Je ne sais pas où en est ma demande de suppression de compte.",
                "Quel est le statut de la suppression de mon compte ?",
                "J'ai demandé la suppression de mon compte, ça en est où ?",
                "Ma demande de suppression de compte traîne depuis des semaines.",
                "J'ai fait une demande de suppression de compte, aucune nouvelle depuis.",
                "Je veux annuler la suppression de mon compte.",
            ],
            keywords=["compte supprimé", "suppression compte", "réactiver compte", "gdpr"],
            endpoint=DiagnosticEndpoint(method="POST", path="/diagnostic/account_deletion"),
            required_fields=[],
            optional_fields=[],
            resolution_causes=[
                ResolutionCause(code="NOT_DELETED", action="reassure_not_deleted"),
                ResolutionCause(code="WITHIN_GRACE_PERIOD", action="explain_grace_period"),
                ResolutionCause(code="CANNOT_REACTIVATE", action="confirm_permanent"),
            ],
            escalation_causes=["USER_NOT_FOUND", "GRACE_EXPIRED_PENDING_PURGE"],
        ),
        ProblemDefinition(
            id="parental_consent_status",
            label="Consentement parental bloqué, rejeté ou expiré",
            description=(
                "Un compte mineur reste verrouillé car le consentement parental n'a jamais été "
                "traité, a expiré, ou a été rejeté par le parent renseigné."
            ),
            # Ajouts suite a la grande vague de tests conversationnels (2026-07) :
            # ce manifeste n'avait que 3 example_phrases (le plus faible du
            # catalogue) -- plusieurs formulations realistes diluaient
            # (egalite avec account_access_blocked/compliance_hold_blocking).
            example_phrases=[
                "Le compte de mon enfant est toujours bloqué, le parent n'a rien reçu.",
                "La demande de consentement parental a expiré.",
                "Le consentement de mes parents a été refusé.",
                "Le consentement parental de mon fils traîne depuis des semaines.",
                "L'accord de mes parents pour le compte de ma fille est bloqué.",
                "Mon enfant ne peut pas utiliser son compte, le consentement parental n'avance pas.",
                "Le compte de mon fils attend toujours un accord parental.",
            ],
            keywords=["consentement parental", "compte mineur bloqué", "autorisation parent"],
            endpoint=DiagnosticEndpoint(method="POST", path="/diagnostic/parental_consent"),
            required_fields=[],
            optional_fields=[],
            resolution_causes=[
                ResolutionCause(code="NO_CONSENT_REQUEST_FOUND", action="guide_new_request"),
                ResolutionCause(code="CONSENT_ALREADY_VERIFIED", action="reassure_verified"),
                ResolutionCause(code="CONSENT_PENDING", action="reassure_wait"),
                ResolutionCause(code="CONSENT_REJECTED", action="explain_rejection"),
                ResolutionCause(code="CONSENT_EXPIRED", action="guide_new_request"),
            ],
            escalation_causes=["USER_NOT_FOUND", "UNKNOWN_STATUS"],
        ),
        ProblemDefinition(
            id="certification_status",
            label='Badge de certification absent ou refusé',
            description=(
                "L'utilisateur a demandé le badge certifié (compte officiel, créateur reconnu) pour son profil et ne l'a pas obtenu, ne sait pas où en est sa demande, ou sa demande de badge a été refusée."
            ),
            example_phrases=[
                "Je n'ai toujours pas le badge certifié sur mon profil.",
                'Ma demande de badge officiel a été refusée.',
                'Où en est ma demande de certification de compte créateur ?',
                "Pourquoi je n'ai pas le badge bleu de certification ?",
                "J'ai demandé la certification de mon profil il y a longtemps.",
            ],
            keywords=['badge certifié', 'certification', 'badge officiel', 'badge bleu'],
            endpoint=DiagnosticEndpoint(method="POST", path="/diagnostic/certification"),
            required_fields=[],
            optional_fields=[],
            resolution_causes=[
                ResolutionCause(code="CERTIFICATION_ACTIVE", action="reassure_active"),
                ResolutionCause(code="CERTIFICATION_NOT_REQUESTED", action="guide_request"),
                ResolutionCause(code="CERTIFICATION_UNDER_REVIEW", action="reassure_wait"),
                ResolutionCause(code="CERTIFICATION_REJECTED", action="explain_rejection"),
            ],
            escalation_causes=['USER_NOT_FOUND', 'CERTIFICATION_BADGE_MISSING'],
        ),
        ProblemDefinition(
            id="ngoni_plus_subscription",
            label='Abonnement Ngoni+ inactif ou avantages absents',
            description=(
                "L'utilisateur s'est abonné à Ngoni+ (offre premium) mais l'abonnement n'apparaît pas, les avantages premium ne sont pas actifs, ou il ne comprend pas pourquoi son abonnement s'est arrêté."
            ),
            example_phrases=[
                "J'ai payé Ngoni+ mais je n'ai pas les avantages premium.",
                "Mon abonnement Ngoni+ s'est arrêté tout seul.",
                "Pourquoi mon abonnement premium Ngoni plus n'est plus actif ?",
                'Je ne vois pas mon abonnement Ngoni+ sur mon compte.',
                'Mon Ngoni plus a été annulé sans que je le demande.',
            ],
            keywords=['ngoni+', 'ngoni plus', 'abonnement premium', 'premium'],
            endpoint=DiagnosticEndpoint(method="POST", path="/diagnostic/ngoni_plus"),
            required_fields=[],
            optional_fields=[],
            resolution_causes=[
                ResolutionCause(code="NGONI_PLUS_NONE", action="guide_subscribe"),
                ResolutionCause(code="NGONI_PLUS_ACTIVE", action="reassure_active"),
                ResolutionCause(code="NGONI_PLUS_CANCELLED", action="explain_cancellation"),
                ResolutionCause(code="NGONI_PLUS_EXPIRED", action="guide_renew"),
            ],
            escalation_causes=['USER_NOT_FOUND', 'NGONI_PLUS_EXPIRED_BUT_ACTIVE', 'NGONI_PLUS_BENEFITS_MISSING'],
        ),
        ProblemDefinition(
            id="phone_verification",
            label='Numéro de téléphone non confirmé (code SMS)',
            description=(
                "L'utilisateur ne reçoit pas le code SMS de confirmation de son numéro de téléphone, ou son numéro de téléphone n'est pas confirmé sur son compte."
            ),
            example_phrases=[
                'Je ne reçois pas le code SMS pour confirmer mon numéro.',
                "Mon numéro de téléphone n'est pas confirmé.",
                "Le code de confirmation par SMS n'arrive jamais.",
                "Je n'arrive pas à valider mon numéro de téléphone avec le code.",
                "On me demande de confirmer mon téléphone mais je n'ai pas de SMS.",
            ],
            keywords=['code sms', 'numéro de téléphone', 'code de confirmation', 'otp'],
            endpoint=DiagnosticEndpoint(method="POST", path="/diagnostic/phone"),
            required_fields=[],
            optional_fields=[],
            resolution_causes=[
                ResolutionCause(code="PHONE_MISSING", action="guide_add_phone"),
                ResolutionCause(code="PHONE_NOT_VERIFIED", action="guide_resend_code"),
                ResolutionCause(code="PHONE_VERIFIED", action="reassure_verified"),
            ],
            escalation_causes=['USER_NOT_FOUND'],
        ),
        ProblemDefinition(
            id="payout_destination_status",
            label='Moyen de retrait impossible à ajouter ou refusé',
            description=(
                "L'utilisateur n'arrive pas à ajouter ou faire accepter son moyen de retrait (compte Mobile Money, Orange Money, Wave, compte bancaire) pour recevoir ses gains."
            ),
            example_phrases=[
                "Je n'arrive pas à ajouter mon numéro Orange Money pour retirer mes gains.",
                'Mon compte Wave pour les retraits a été refusé.',
                "Impossible d'enregistrer mon Mobile Money comme moyen de retrait.",
                'Mon moyen de paiement pour retirer est toujours en attente.',
                'Je ne peux pas ajouter mon compte bancaire pour recevoir mon argent.',
            ],
            keywords=['moyen de retrait', 'mobile money', 'orange money', 'wave', 'ajouter compte'],
            endpoint=DiagnosticEndpoint(method="POST", path="/diagnostic/payout_destination"),
            required_fields=[],
            optional_fields=[],
            resolution_causes=[
                ResolutionCause(code="PAYOUT_REQUIRES_KYC", action="explain_kyc_prerequisite"),
                ResolutionCause(code="PAYOUT_NOT_CONFIGURED", action="guide_add_payout"),
                ResolutionCause(code="PAYOUT_UNDER_REVIEW", action="reassure_wait"),
                ResolutionCause(code="PAYOUT_REJECTED", action="explain_rejection"),
                ResolutionCause(code="PAYOUT_ACTIVE", action="reassure_active"),
            ],
            escalation_causes=['USER_NOT_FOUND'],
        ),
        ProblemDefinition(
            id="ngoni_card_status",
            label='Carte NGONI non reçue ou expirée',
            description=(
                "L'utilisateur attend sa carte NGONI (carte de membre avec QR code) qu'il n'a pas reçue, ou sa carte est expirée."
            ),
            example_phrases=[
                "Je n'ai pas reçu ma carte NGONI.",
                'Ma carte NGONI avec le QR code a expiré.',
                'Où est ma carte de membre NGONI ?',
                "Ma carte NGONI n'apparaît pas dans l'application.",
                'Comment obtenir la carte NGONI ?',
            ],
            keywords=['carte ngoni', 'carte de membre', 'qr code'],
            endpoint=DiagnosticEndpoint(method="POST", path="/diagnostic/ngoni_card"),
            required_fields=[],
            optional_fields=[],
            resolution_causes=[
                ResolutionCause(code="NGONI_CARD_NOT_ISSUED", action="explain_eligibility"),
                ResolutionCause(code="NGONI_CARD_EXPIRED", action="guide_renew"),
                ResolutionCause(code="NGONI_CARD_ACTIVE", action="reassure_active"),
            ],
            escalation_causes=['USER_NOT_FOUND'],
        ),
        ProblemDefinition(
            id="referral_reward_missing",
            label='Récompense de parrainage non reçue',
            description=(
                "L'utilisateur a parrainé des amis avec son code de parrainage et n'a pas reçu la récompense promise."
            ),
            example_phrases=[
                "J'ai parrainé un ami mais je n'ai pas eu ma récompense.",
                "Mon bonus de parrainage n'est pas arrivé.",
                "Mes filleuls se sont inscrits avec mon code mais rien n'est crédité.",
                'Où est la prime de parrainage ?',
                "Le code de parrainage n'a rien rapporté.",
            ],
            keywords=['parrainage', 'filleul', 'code de parrainage', 'bonus de parrainage'],
            endpoint=DiagnosticEndpoint(method="POST", path="/diagnostic/referral"),
            required_fields=[],
            optional_fields=[],
            resolution_causes=[
                ResolutionCause(code="REFERRAL_NONE", action="guide_share_code"),
                ResolutionCause(code="REFERRAL_PENDING", action="explain_conditions"),
                ResolutionCause(code="REFERRAL_REWARDED", action="reassure_credited"),
            ],
            escalation_causes=['USER_NOT_FOUND'],
        ),
        ProblemDefinition(
            id="account_warnings",
            label='Avertissements reçus sur le compte',
            description=(
                "L'utilisateur a reçu un avertissement (strike) de modération sur son compte et veut savoir combien il en a et ce qu'il risque."
            ),
            example_phrases=[
                "J'ai reçu un avertissement sur mon compte, pourquoi ?",
                "Combien d'avertissements j'ai sur mon compte ?",
                "J'ai eu un strike, est-ce que mon compte va être suspendu ?",
                "On m'a envoyé un avertissement de modération.",
                'Je risque quoi avec mes avertissements ?',
            ],
            keywords=['avertissement', 'strike', 'modération'],
            endpoint=DiagnosticEndpoint(method="POST", path="/diagnostic/warnings"),
            required_fields=[],
            optional_fields=[],
            resolution_causes=[
                ResolutionCause(code="NO_STRIKES", action="reassure_clean"),
                ResolutionCause(code="STRIKES_WARNING", action="explain_policy"),
            ],
            escalation_causes=['USER_NOT_FOUND', 'STRIKES_THRESHOLD_REACHED'],
        ),
    ],
)
