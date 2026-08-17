"""Rapport de qualite FAQ sur un corpus de ~200 requetes -- mesure le taux de
faux positifs/negatifs de DEFAULT_THRESHOLD (et SECONDARY_THRESHOLD) sur un
corpus bien plus large que le calibrage historique (15+10, voir le
commentaire de DEFAULT_THRESHOLD dans app/domains/faq/service.py), pour
recalibrer serieusement le seuil provisoire pose lors du passage a BGE-M3
(2026-07-30).

Corpus : pour chacune des 26 questions reelles du catalogue (ia.faq_items),
6 paraphrases tenues a l'ecart du texte exact en base (POSITIVE_CASES,
~156 requetes) -- le but est de mesurer une generalisation reelle, pas de
reverifier qu'un exemple retrouve son propre vecteur (meme principe que
fastapi/tests/test_diagnostic_classification_quality.py). Complete par des
messages qui ne doivent PAS declencher de reponse FAQ (NEGATIVE_CASES,
~44 requetes : salutations, hors-sujet, diagnostic/reclamation) pour mesurer
le taux de faux positifs, pas seulement le rappel.

Lancement (necessite Postgres + le catalogue FAQ seede, voir
docs/10-deploiement.md) :
    cd fastapi
    .venv\\Scripts\\python.exe scripts\\faq_test_report.py [chemin_rapport.md]

Produit un rapport Markdown (scripts/faq_test_report.md par defaut) : un
sweep de seuils (comme le calibrage historique, mais sur ~200 requetes) et
le detail de chaque cas mal classe au seuil actuellement configure.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Execute directement par chemin (python scripts\faq_test_report.py), pas
# comme module -- voir scripts/reembed_faq.py, meme raison.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal  # noqa: E402
from app.domains.faq.repository import FaqRepository  # noqa: E402
from app.domains.faq.service import DEFAULT_THRESHOLD, SECONDARY_THRESHOLD, FaqService  # noqa: E402
from app.shared.embeddings import embed_query  # noqa: E402

# ---------------------------------------------------------------------------
# Corpus positif : (paraphrase, slug ia.faq_items attendu). Un slug par
# question reelle du catalogue (voir `SELECT slug, question FROM
# ia.faq_items` pour la liste a jour si le catalogue change).
# ---------------------------------------------------------------------------
POSITIVE_CASES: list[tuple[str, str]] = [
    # ACCOUNT
    ("comment je fais pour créer un compte NGONI", "creer-compte-ngoni"),
    ("je veux m'inscrire sur l'application, comment on fait ?", "creer-compte-ngoni"),
    ("procédure pour ouvrir un compte", "creer-compte-ngoni"),
    ("koman on crée un compte ngoni", "creer-compte-ngoni"),
    ("j'aimerais m'inscrire, quelle est la démarche ?", "creer-compte-ngoni"),
    ("comment on ouvre un compte sur ngoni ?", "creer-compte-ngoni"),
    ("je veux changer ma photo de profil", "modifier-informations-personnelles"),
    ("comment mettre à jour mes infos perso", "modifier-informations-personnelles"),
    ("où est-ce que je peux modifier mon profil ?", "modifier-informations-personnelles"),
    ("comment éditer mes informations de compte", "modifier-informations-personnelles"),
    ("je veux changer mon nom d'utilisateur", "modifier-informations-personnelles"),
    ("comment mettre à jour ma photo et mes infos", "modifier-informations-personnelles"),
    ("est-ce que je peux utiliser mon compte sur deux téléphones ?", "puis-je-utiliser-ngoni-sur-plusieurs-appareils-ea01f558"),
    ("je peux me connecter depuis plusieurs appareils ?", "puis-je-utiliser-ngoni-sur-plusieurs-appareils-ea01f558"),
    ("ngoni marche sur plusieurs téléphones en même temps ?", "puis-je-utiliser-ngoni-sur-plusieurs-appareils-ea01f558"),
    ("mon compte fonctionne sur tablette et mobile ?", "puis-je-utiliser-ngoni-sur-plusieurs-appareils-ea01f558"),
    ("peut-on utiliser le meme compte sur plusieurs smartphones", "puis-je-utiliser-ngoni-sur-plusieurs-appareils-ea01f558"),
    ("connexion multi-appareils possible ?", "puis-je-utiliser-ngoni-sur-plusieurs-appareils-ea01f558"),
    ("j'ai oublié mon mot de passe, comment le changer", "reinitialiser-mot-de-passe"),
    ("comment récupérer l'accès à mon compte si j'ai perdu mon mot de passe", "reinitialiser-mot-de-passe"),
    ("procédure pour réinitialiser mon mot de passe", "reinitialiser-mot-de-passe"),
    ("jai zapé mon mdp koman on fé", "reinitialiser-mot-de-passe"),
    ("comment changer mon code d'accès oublié", "reinitialiser-mot-de-passe"),
    ("mot de passe perdu, que faire ?", "reinitialiser-mot-de-passe"),
    ("comment obtenir le badge de vérification sur mon compte", "verification-compte"),
    ("comment faire vérifier mon compte", "verification-compte"),
    ("procédure de vérification de profil", "verification-compte"),
    ("comment avoir le badge vérifié", "verification-compte"),
    ("je veux faire certifier mon compte", "verification-compte"),
    ("comment obtenir la certification du compte", "verification-compte"),
    # WALLET
    ("comment un créateur de contenu gagne de l'argent sur la plateforme", "comment-un-cr-ateur-peut-il-gagner-de-l-argent-sur-la-plateforme-97c1ea25"),
    ("quelles sont les façons de monétiser mon contenu", "comment-un-cr-ateur-peut-il-gagner-de-l-argent-sur-la-plateforme-97c1ea25"),
    ("comment je peux générer des revenus en tant que créateur", "comment-un-cr-ateur-peut-il-gagner-de-l-argent-sur-la-plateforme-97c1ea25"),
    ("koman 1 createur i gagne des sous sur ngoni", "comment-un-cr-ateur-peut-il-gagner-de-l-argent-sur-la-plateforme-97c1ea25"),
    ("les créateurs sont payés comment sur l'appli", "comment-un-cr-ateur-peut-il-gagner-de-l-argent-sur-la-plateforme-97c1ea25"),
    ("comment monétiser mon audience sur ngoni", "comment-un-cr-ateur-peut-il-gagner-de-l-argent-sur-la-plateforme-97c1ea25"),
    ("c'est quoi le principe du programme de récompenses", "programme-recompenses"),
    ("comment marche le système de récompenses pour les créateurs", "programme-recompenses"),
    ("explique-moi les récompenses ngoni", "programme-recompenses"),
    ("koman sa march le program de recompense", "programme-recompenses"),
    ("les récompenses ça fonctionne comment exactement", "programme-recompenses"),
    ("comment sont attribuées les récompenses", "programme-recompenses"),
    # COINS
    ("où est-ce que j'achète des pièces sur l'application", "acheter-pieces-ngoni"),
    ("comment je fais pour acheter des coins ngoni", "acheter-pieces-ngoni"),
    ("procédure d'achat de pièces", "acheter-pieces-ngoni"),
    ("koman on ash7t des piece sur ngoni", "acheter-pieces-ngoni"),
    ("je veux acheter des pièces, comment on fait ?", "acheter-pieces-ngoni"),
    ("comment recharger en pièces sur l'appli", "acheter-pieces-ngoni"),
    ("explique-moi à quoi servent les pièces sur ngoni", "fonctionnement-pieces-ngoni"),
    ("c'est quoi le principe des pièces NGONI", "fonctionnement-pieces-ngoni"),
    ("les pièces ça sert à quoi exactement", "fonctionnement-pieces-ngoni"),
    ("koman marsh le systeme de piece", "fonctionnement-pieces-ngoni"),
    ("je comprends pas comment fonctionnent les coins", "fonctionnement-pieces-ngoni"),
    ("les pièces NGONI, comment ça marche ?", "fonctionnement-pieces-ngoni"),
    ("quels modes de paiement je peux utiliser", "moyens-paiement-disponibles"),
    ("est-ce que je peux payer par mobile money", "moyens-paiement-disponibles"),
    ("quelles cartes bancaires sont acceptées", "moyens-paiement-disponibles"),
    ("koman on pe paye sur ngoni, kel moyen", "moyens-paiement-disponibles"),
    ("orange money ça marche pour payer sur ngoni ?", "moyens-paiement-disponibles"),
    ("liste des moyens de paiement acceptés", "moyens-paiement-disponibles"),
    ("comment je peux soutenir financièrement un créateur que j'aime", "soutenir-createur"),
    ("de quelle façon on peut aider un créateur avec des pièces", "soutenir-createur"),
    ("comment envoyer un don à un créateur", "soutenir-createur"),
    ("koman on fé pr soutenir 1 creatur", "soutenir-createur"),
    ("je veux supporter un créateur, comment faire", "soutenir-createur"),
    ("comment donner des pièces à un créateur", "soutenir-createur"),
    # WITHDRAWAL
    ("comment je récupère l'argent que j'ai gagné", "comment-retirer-revenus"),
    ("procédure pour retirer mes gains", "comment-retirer-revenus"),
    ("comment retirer l'argent de mon wallet", "comment-retirer-revenus"),
    ("koman on retir sé revenu", "comment-retirer-revenus"),
    ("je veux sortir mes revenus de l'application", "comment-retirer-revenus"),
    ("comment encaisser mes gains sur ngoni", "comment-retirer-revenus"),
    ("un retrait prend combien de temps en général", "delai-retrait"),
    ("quel est le délai normal pour un retrait", "delai-retrait"),
    ("en combien de temps j'aurai mon argent après un retrait", "delai-retrait"),
    ("sa pran combien de tem 1 retré normalman", "delai-retrait"),
    ("délai habituel de traitement d'un retrait", "delai-retrait"),
    ("combien de jours pour recevoir un retrait", "delai-retrait"),
    # NGONI_PLUS
    ("comment je démarre un live privé payant", "live-prive-payant"),
    ("procédure pour lancer un live payant", "live-prive-payant"),
    ("comment créer un live privé avec paiement", "live-prive-payant"),
    ("koman on lans 1 live prive payan", "live-prive-payant"),
    ("comment organiser un live réservé aux abonnés payants", "live-prive-payant"),
    ("comment démarrer un stream privé payant", "live-prive-payant"),
    ("c'est quoi l'abonnement ngoni plus", "ngoni-plus"),
    ("explique-moi ngoni plus", "ngoni-plus"),
    ("à quoi sert l'abonnement premium ngoni plus", "ngoni-plus"),
    ("koman marsh ngoni plus", "ngoni-plus"),
    ("qu'est-ce que m'apporte ngoni plus", "ngoni-plus"),
    ("ngoni plus c'est quoi comme fonctionnalité", "ngoni-plus"),
    ("comment je publie une vidéo privée payante", "video-privee-payante"),
    ("procédure pour poster une vidéo payante", "video-privee-payante"),
    ("comment mettre en ligne une vidéo privée avec paiement", "video-privee-payante"),
    ("koman on publi 1 video prive payante", "video-privee-payante"),
    ("comment monétiser une vidéo privée", "video-privee-payante"),
    ("comment créer une vidéo payante sur mon profil", "video-privee-payante"),
    # KYC
    ("quels papiers il me faut pour la vérification d'identité", "quels-documents-sont-n-cessaires-pour-le-kyc-cbf8a9ce"),
    ("quels documents fournir pour le kyc", "quels-documents-sont-n-cessaires-pour-le-kyc-cbf8a9ce"),
    ("liste des pièces à fournir pour vérifier mon identité", "quels-documents-sont-n-cessaires-pour-le-kyc-cbf8a9ce"),
    ("kel doc i fo pr le kyc", "quels-documents-sont-n-cessaires-pour-le-kyc-cbf8a9ce"),
    ("est-ce qu'il faut un passeport pour le kyc ?", "quels-documents-sont-n-cessaires-pour-le-kyc-cbf8a9ce"),
    ("quels justificatifs sont demandés pour la vérification d'identité", "quels-documents-sont-n-cessaires-pour-le-kyc-cbf8a9ce"),
    # PARENTAL_CONTROL
    ("comment activer le contrôle parental pour mon enfant", "controle-parental"),
    ("c'est quoi le contrôle parental sur l'application", "controle-parental"),
    ("comment je paramètre le contrôle parental", "controle-parental"),
    ("koman on activ le controle parental", "controle-parental"),
    ("à quoi sert le contrôle parental sur ngoni", "controle-parental"),
    ("comment protéger le compte de mon enfant", "controle-parental"),
    # GIFTS
    ("comment fonctionnent les dons pendant un live", "comment-fonctionne-le-syst-me-de-dons-pendant-un-live-76fd5fc0"),
    ("comment envoyer un cadeau pendant un live", "comment-fonctionne-le-syst-me-de-dons-pendant-un-live-76fd5fc0"),
    ("explique-moi le système de dons en direct", "comment-fonctionne-le-syst-me-de-dons-pendant-un-live-76fd5fc0"),
    ("koman on fé 1 don pandan 1 live", "comment-fonctionne-le-syst-me-de-dons-pendant-un-live-76fd5fc0"),
    ("comment offrir un cadeau à un créateur en direct", "comment-fonctionne-le-syst-me-de-dons-pendant-un-live-76fd5fc0"),
    ("les dons en live ça marche comment", "comment-fonctionne-le-syst-me-de-dons-pendant-un-live-76fd5fc0"),
    # ASSISTANCE
    ("comment je fais pour joindre le support", "contacter-support"),
    ("quel est le moyen de contacter l'assistance", "contacter-support"),
    ("comment parler à quelqu'un du support", "contacter-support"),
    ("koman on join le support ngoni", "contacter-support"),
    ("comment contacter le service client", "contacter-support"),
    ("où trouver les coordonnées du support", "contacter-support"),
    ("comment ça fonctionne la notation des réponses de l'assistant", "notation-reponses-assistant"),
    ("à quoi sert le système d'évaluation des réponses", "notation-reponses-assistant"),
    ("comment je note une réponse du bot", "notation-reponses-assistant"),
    ("koman on not le réponse de lasistan", "notation-reponses-assistant"),
    ("pourquoi on me demande de noter les réponses", "notation-reponses-assistant"),
    ("comment fonctionne le système de feedback sur les réponses", "notation-reponses-assistant"),
    ("où est la liste des questions fréquentes", "o-trouver-la-foire-aux-questions-a039612a"),
    ("où puis-je consulter la FAQ", "o-trouver-la-foire-aux-questions-a039612a"),
    ("comment accéder à la foire aux questions", "o-trouver-la-foire-aux-questions-a039612a"),
    ("ou ge trouv la faq stp", "o-trouver-la-foire-aux-questions-a039612a"),
    ("où sont les questions les plus posées", "o-trouver-la-foire-aux-questions-a039612a"),
    ("comment voir toutes les questions fréquentes", "o-trouver-la-foire-aux-questions-a039612a"),
    ("comment je propose une idée d'amélioration", "proposer-amelioration"),
    ("où soumettre une suggestion pour l'application", "proposer-amelioration"),
    ("comment envoyer une idée à l'équipe ngoni", "proposer-amelioration"),
    ("koman on propoz 1 amelioration", "proposer-amelioration"),
    ("je veux suggérer une nouvelle fonctionnalité, comment faire", "proposer-amelioration"),
    ("comment faire remonter une idée d'amélioration", "proposer-amelioration"),
    # GENERAL
    ("comment je change la langue de l'appli", "changer-langue-application"),
    ("où modifier la langue utilisée sur ngoni", "changer-langue-application"),
    ("comment passer l'application en anglais", "changer-langue-application"),
    ("koman on chanj la lang de lapli", "changer-langue-application"),
    ("l'application est disponible en plusieurs langues ?", "changer-langue-application"),
    ("comment configurer la langue de mon profil", "changer-langue-application"),
    ("pourquoi certaines fonctions ne sont pas encore actives", "fonctionnalites-non-disponibles"),
    ("pourquoi il manque des fonctionnalités sur l'application", "fonctionnalites-non-disponibles"),
    ("certaines options sont grisées, pourquoi ?", "fonctionnalites-non-disponibles"),
    ("pk certain fonctionalite son pa dispo", "fonctionnalites-non-disponibles"),
    ("pourquoi je ne trouve pas certaines fonctions annoncées", "fonctionnalites-non-disponibles"),
    ("pourquoi tout n'est pas encore disponible sur l'appli", "fonctionnalites-non-disponibles"),
    ("c'est quoi exactement l'application NGONI", "quest-ce-que-ngoni"),
    ("tu peux me présenter NGONI", "quest-ce-que-ngoni"),
    ("à quoi sert cette application", "quest-ce-que-ngoni"),
    ("c'est koi ngoni en fet", "quest-ce-que-ngoni"),
    ("présente-moi la plateforme NGONI", "quest-ce-que-ngoni"),
    ("explique-moi ce qu'est NGONI en quelques mots", "quest-ce-que-ngoni"),
]

# ---------------------------------------------------------------------------
# Corpus negatif : messages qui ne doivent renvoyer AUCUNE reponse FAQ --
# salutations/remerciements, hors-sujet, et messages diagnostic/reclamation
# qui partagent du vocabulaire avec le catalogue (compte, pieces, retrait)
# mais decrivent un INCIDENT concret, pas une question generale.
# ---------------------------------------------------------------------------
NEGATIVE_CASES: list[str] = [
    # Salutations / small talk
    "bonjour",
    "salut ça va ?",
    "bonsoir tout le monde",
    "hello",
    "coucou",
    "merci beaucoup, au revoir",
    "ok merci bye",
    "à bientôt",
    "bonne journée",
    "je vous remercie pour votre aide",
    # Hors-sujet
    "quelle est la météo aujourd'hui",
    "raconte-moi une blague",
    "qui a gagné le match hier",
    "quelle est la capitale du Mali",
    "combien font douze fois douze",
    "peux-tu m'aider en mathématiques",
    "je m'ennuie",
    "quelle est la meilleure recette de riz",
    "parle-moi de l'espace",
    "tu es un robot ou un humain",
    # Diagnostic / incidents concrets (vocabulaire proche mais PAS une question generale)
    "mon compte est bloqué depuis hier",
    "je n'arrive plus à retirer mon argent, ça coince depuis ce matin",
    "j'ai acheté des pièces mais elles n'apparaissent pas sur mon compte",
    "mon retrait est en attente depuis trois jours",
    "j'ai fait une recharge mais mon solde n'a pas changé",
    "mon KYC est bloqué depuis une semaine, personne ne répond",
    "l'application plante à chaque fois que je l'ouvre",
    "je ne reçois plus aucune notification depuis hier",
    "mon paiement a été débité mais je n'ai rien reçu",
    "des pièces ont disparu de mon compte",
    "mon compte a été suspendu sans explication",
    # Reclamation explicite
    "je veux déposer une réclamation officielle",
    "ouvrez-moi un ticket pour ce problème",
    "je veux parler à un conseiller humain",
    "je souhaite porter plainte concernant ce service",
    "créez un dossier de réclamation pour moi",
    # Feedback / suggestion (autres intentions, pas FAQ)
    "vous devriez ajouter un mode sombre",
    "ce serait bien d'avoir un chat en direct avec un conseiller",
    "cette application est vraiment nulle en ce moment",
    "je suis très déçu par le service client",
    # Gibberish / test
    "azerty qwerty 12345",
    "test test 123 ignore ce message",
    "blablabla je disais ça comme ça",
    "une phrase random sans queue ni tête",
]


@dataclass
class CaseResult:
    query: str
    expected_slug: Optional[str]
    predicted_slug: Optional[str]
    predicted_question: Optional[str]
    score: float


def _top_candidate(service: FaqService, query: str):
    normalized = query.strip().lower()
    embedding = embed_query(query)
    candidates = service._ranked_candidates(embedding, normalized, "fr", k=1)  # noqa: SLF001 -- script d'audit, acces direct assume
    if not candidates:
        return None, None, 0.0
    item, score, _semantic = candidates[0]
    return item.slug, item.question, score


def run_corpus(service: FaqService) -> list[CaseResult]:
    results: list[CaseResult] = []
    total = len(POSITIVE_CASES) + len(NEGATIVE_CASES)
    done = 0
    started = time.perf_counter()

    for query, expected_slug in POSITIVE_CASES:
        slug, question, score = _top_candidate(service, query)
        results.append(CaseResult(query, expected_slug, slug, question, score))
        done += 1
        if done % 20 == 0:
            print(f"  ... {done}/{total} requetes traitees")

    for query in NEGATIVE_CASES:
        slug, question, score = _top_candidate(service, query)
        results.append(CaseResult(query, None, slug, question, score))
        done += 1
        if done % 20 == 0:
            print(f"  ... {done}/{total} requetes traitees")

    elapsed = time.perf_counter() - started
    print(f"Corpus complet traite en {elapsed:.1f}s ({total} requetes, {elapsed / total * 1000:.0f}ms/requete)")
    return results


def metrics_at_threshold(results: list[CaseResult], threshold: float) -> dict:
    tp = fp = fn = tn = 0
    for r in results:
        crosses = r.score >= threshold
        if r.expected_slug is not None:
            if crosses and r.predicted_slug == r.expected_slug:
                tp += 1
            else:
                fn += 1
        else:
            if crosses:
                fp += 1
            else:
                tn += 1
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    accuracy = (tp + tn) / len(results) if results else 0.0
    return {
        "threshold": threshold, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": precision, "recall": recall, "f1": f1, "accuracy": accuracy,
    }


def build_report(results: list[CaseResult]) -> str:
    lines: list[str] = []
    lines.append("# Rapport de qualite FAQ -- corpus de {} requetes\n".format(len(results)))
    lines.append(f"Positifs : {len(POSITIVE_CASES)} (paraphrases des 26 questions du catalogue) -- "
                  f"Negatifs : {len(NEGATIVE_CASES)} (salutations, hors-sujet, diagnostic/reclamation)\n")
    lines.append(f"Genere le {time.strftime('%Y-%m-%d %H:%M:%S')} -- modele d'embedding : voir "
                  "app/shared/embeddings/service.py (MODEL_NAME)\n")

    lines.append("## Seuils actuellement configures\n")
    for name, value in (("DEFAULT_THRESHOLD", DEFAULT_THRESHOLD), ("SECONDARY_THRESHOLD", SECONDARY_THRESHOLD)):
        m = metrics_at_threshold(results, value)
        lines.append(
            f"- **{name} = {value}** : TP={m['tp']} FP={m['fp']} FN={m['fn']} TN={m['tn']} -- "
            f"precision={m['precision']:.3f} rappel={m['recall']:.3f} F1={m['f1']:.3f} "
            f"accuracy={m['accuracy']:.3f}"
        )
    lines.append("")

    lines.append("## Balayage de seuils (0.30 a 0.80, pas de 0.05)\n")
    lines.append("| Seuil | TP | FP | FN | TN | Precision | Rappel | F1 | Accuracy |")
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    best_f1 = None
    for i in range(30, 81, 5):
        threshold = i / 100
        m = metrics_at_threshold(results, threshold)
        marker = ""
        if best_f1 is None or m["f1"] > best_f1["f1"]:
            best_f1 = m
        lines.append(
            f"| {threshold:.2f} | {m['tp']} | {m['fp']} | {m['fn']} | {m['tn']} | "
            f"{m['precision']:.3f} | {m['recall']:.3f} | {m['f1']:.3f} | {m['accuracy']:.3f} |"
        )
    lines.append("")
    if best_f1:
        lines.append(f"**Meilleur F1 sur ce balayage : seuil={best_f1['threshold']:.2f} (F1={best_f1['f1']:.3f})** "
                      "-- point de depart pour un nouveau DEFAULT_THRESHOLD, a confirmer par relecture manuelle "
                      "des cas ci-dessous avant d'etre adopte.\n")

    lines.append("## Cas mal classes au seuil DEFAULT_THRESHOLD actuel\n")
    fps = [r for r in results if r.expected_slug is None and r.score >= DEFAULT_THRESHOLD]
    fns = [r for r in results if r.expected_slug is not None
           and not (r.score >= DEFAULT_THRESHOLD and r.predicted_slug == r.expected_slug)]

    lines.append(f"### Faux positifs ({len(fps)}) -- ne devraient renvoyer aucune reponse FAQ\n")
    if fps:
        lines.append("| Requete | Score | Reponse renvoyee a tort |")
        lines.append("|---|---:|---|")
        for r in fps:
            lines.append(f"| {r.query!r} | {r.score:.4f} | {r.predicted_question!r} |")
    else:
        lines.append("Aucun.")
    lines.append("")

    lines.append(f"### Faux negatifs ({len(fns)}) -- auraient du matcher la bonne question\n")
    if fns:
        lines.append("| Requete | Attendu | Obtenu | Score |")
        lines.append("|---|---|---|---:|")
        for r in fns:
            lines.append(f"| {r.query!r} | {r.expected_slug} | {r.predicted_slug or '(aucun)'} | {r.score:.4f} |")
    else:
        lines.append("Aucun.")
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    output_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "faq_test_report.md"

    session = SessionLocal()
    try:
        repository = FaqRepository(session)
        service = FaqService(repository)
        print(f"Lancement du corpus ({len(POSITIVE_CASES)} positifs + {len(NEGATIVE_CASES)} negatifs)...")
        results = run_corpus(service)
        report = build_report(results)
        output_path.write_text(report, encoding="utf-8")
        print(f"Rapport ecrit dans {output_path}")

        m = metrics_at_threshold(results, DEFAULT_THRESHOLD)
        print(
            f"\nDEFAULT_THRESHOLD={DEFAULT_THRESHOLD} -> "
            f"precision={m['precision']:.3f} rappel={m['recall']:.3f} F1={m['f1']:.3f} "
            f"({m['fp']} faux positifs, {m['fn']} faux negatifs sur {len(results)} requetes)"
        )
    finally:
        session.close()


if __name__ == "__main__":
    main()
