"""Rapport de qualite du matching de probleme diagnostic sur un corpus de
paraphrases -- meme methodologie que scripts/faq_test_report.py (corpus +
balayage de seuils + detail des cas mal classes), applique cette fois a la
classification semantique du Diagnostic Engine (8 problemes, wallet+user).

IMPORTANT (limite assumee, comme fastapi/tests/test_diagnostic_classification_quality.py
et POST /diagnostic/debug/classify eux-memes le documentent) : ce rapport
mesure uniquement le score d'embedding BRUT (meme calcul que
_score_capabilities_embeddings cote rasa/actions/diagnostic.py), PAS le
pipeline complet de desambiguisation (repli par clause, tiebreak mots-cles,
repechage par mot-cle unique -- _apply_keyword_tiebreak,
_apply_service_family_tiebreak, _rescue_unique_keyword_match), qui vit
cote Rasa/actions (rasa_sdk, non installe dans ce venv) et depend de l'etat
de conversation. Un message signale ici comme "mal classe" peut tres bien
etre corrige en aval par ce pipeline -- ce rapport sert a mesurer la solidite
de la PREMIERE ligne de defense (l'embedding seul), exactement comme le fait
deja MIN_EMBEDDING_SIMILARITY.

Interroge le vrai Diagnostic Engine en cours d'execution (POST
/diagnostic/debug/classify) plutot que de recalculer les embeddings
localement : mesure le comportement REEL du CapabilityRegistry (manifestes
wallet_service/user_service charges via HTTP, comme en production), pas une
reimplementation separee qui pourrait diverger.

Prerequis : FastAPI + wallet_service + user_service demarres (voir
docs/10-deploiement.md) -- le registre doit avoir charge les 8 problemes
(verifier : curl http://localhost:8000/diagnostic/capabilities).

Lancement :
    cd fastapi
    .venv\\Scripts\\python.exe scripts\\diagnostic_test_report.py [url_base] [chemin_rapport.md]
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx

# ---------------------------------------------------------------------------
# Corpus positif : (paraphrase, problem_id attendu). Cible en priorite les
# collisions DEJA documentees dans les manifestes eux-memes (voir
# wallet_service/diagnostic/manifest.py et user_service/diagnostic/manifest.py,
# commentaires "Audit qualite du code") : le vocabulaire "bloque"/"compte"
# est partage entre withdrawal_pending, account_access_blocked,
# compliance_hold_blocking, account_deletion_status et kyc_status_issue --
# la zone la plus fragile du catalogue.
# ---------------------------------------------------------------------------
POSITIVE_CASES: list[tuple[str, str]] = [
    # withdrawal_pending
    ("mon retrait est bloqué depuis ce matin", "withdrawal_pending"),
    ("j'ai demandé un retrait et je n'ai toujours rien reçu", "withdrawal_pending"),
    ("ça fait deux jours que mon retrait reste en attente", "withdrawal_pending"),
    ("impossible de retirer mon argent, ça coince", "withdrawal_pending"),
    ("mon retrait a été refusé sans raison", "withdrawal_pending"),
    ("je n'arrive pas à récupérer l'argent de mon retrait", "withdrawal_pending"),
    ("ma demande de retrait ne progresse plus du tout", "withdrawal_pending"),
    ("l'argent de mon retrait n'est jamais arrivé sur mon compte bancaire", "withdrawal_pending"),
    # topup_not_credited
    ("j'ai rechargé mais mon solde n'a pas bougé", "topup_not_credited"),
    ("ma recharge orange money n'apparaît nulle part", "topup_not_credited"),
    ("j'ai payé pour recharger mon wallet mais rien n'a été ajouté", "topup_not_credited"),
    ("ma recharge de ce matin n'a toujours pas été créditée", "topup_not_credited"),
    ("j'ai fait un dépôt qui n'apparaît pas sur mon compte NGONI", "topup_not_credited"),
    ("ma recharge mobile money reste introuvable", "topup_not_credited"),
    # gift_not_received
    ("j'ai envoyé un cadeau mais mon ami dit ne rien avoir reçu", "gift_not_received"),
    ("mon cadeau a débité mes pièces mais n'est jamais arrivé", "gift_not_received"),
    ("j'ai offert des pièces à quelqu'un et il ne les a pas reçues", "gift_not_received"),
    ("le cadeau envoyé n'est jamais arrivé chez le destinataire", "gift_not_received"),
    # kyc_status_issue
    ("pourquoi mon dossier KYC est refusé", "kyc_status_issue"),
    ("je n'arrive pas à valider mon identité", "kyc_status_issue"),
    ("ma vérification d'identité est en attente depuis trop longtemps", "kyc_status_issue"),
    ("mes documents d'identité ont été rejetés", "kyc_status_issue"),
    ("j'ai envoyé mes papiers pour le KYC mais rien ne se passe", "kyc_status_issue"),
    ("où en est ma vérification d'identité ?", "kyc_status_issue"),
    ("mon KYC est bloqué depuis longtemps, toujours pas de réponse", "kyc_status_issue"),
    ("pourquoi ma pièce d'identité a été refusée", "kyc_status_issue"),
    # account_access_blocked
    ("je n'arrive plus à me connecter à mon compte, il semble bloqué", "account_access_blocked"),
    ("mon compte a été suspendu et je ne sais pas pourquoi", "account_access_blocked"),
    ("on m'a banni sans aucune explication", "account_access_blocked"),
    ("impossible d'accéder à mon compte depuis ce matin", "account_access_blocked"),
    ("mon accès a été coupé sans prévenir", "account_access_blocked"),
    ("mon compte est bloqué et je ne comprends pas pourquoi", "account_access_blocked"),
    ("je ne peux plus du tout utiliser mon compte", "account_access_blocked"),
    ("pourquoi je n'arrive plus à me connecter à mon compte", "account_access_blocked"),
    # compliance_hold_blocking
    ("mon compte est bloqué pour conformité, je ne comprends pas", "compliance_hold_blocking"),
    ("un contrôle de conformité empêche mes actions", "compliance_hold_blocking"),
    ("ça dit compliance hold sur mon compte", "compliance_hold_blocking"),
    ("je ne peux plus rien faire, ça parle de conformité", "compliance_hold_blocking"),
    ("mon compte est sous contrôle de conformité depuis hier", "compliance_hold_blocking"),
    ("pourquoi mon compte est-il sous contrôle conformité ?", "compliance_hold_blocking"),
    # account_deletion_status
    ("j'ai supprimé mon compte par erreur, comment le récupérer", "account_deletion_status"),
    ("je ne sais pas où en est ma demande de suppression de compte", "account_deletion_status"),
    ("ma demande de suppression traîne depuis des semaines", "account_deletion_status"),
    ("je veux annuler la suppression de mon compte", "account_deletion_status"),
    ("mon compte affiche encore comme supprimé", "account_deletion_status"),
    ("j'ai demandé la suppression de mon compte, ça en est où", "account_deletion_status"),
    # parental_consent_status
    ("le compte de mon fils est toujours bloqué, on attend l'accord du parent", "parental_consent_status"),
    ("le consentement parental n'a jamais été traité", "parental_consent_status"),
    ("l'accord de mes parents pour mon compte a été refusé", "parental_consent_status"),
    ("le consentement de mes parents traîne depuis des semaines", "parental_consent_status"),
    ("mon enfant ne peut pas utiliser son compte, le consentement n'avance pas", "parental_consent_status"),
    ("pourquoi le compte de ma fille reste verrouillé faute d'accord parental", "parental_consent_status"),
]

# ---------------------------------------------------------------------------
# Corpus negatif : messages qui ne devraient matcher AUCUN probleme
# diagnostic -- salutations, questions FAQ generales (memes concepts :
# "compte", "retrait", "pieces", mais formulees comme une question generale,
# pas un incident concret), hors-sujet.
# ---------------------------------------------------------------------------
NEGATIVE_CASES: list[str] = [
    "bonjour",
    "salut ça va ?",
    "merci beaucoup, bonne journée",
    "au revoir",
    "comment créer un compte NGONI ?",
    "comment fonctionne le système de pièces ?",
    "quels documents faut-il pour le KYC ?",
    "combien de temps prend un retrait en général ?",
    "comment acheter des pièces sur l'application ?",
    "c'est quoi NGONI ?",
    "comment contacter le support ?",
    "quels moyens de paiement sont acceptés ?",
    "comment fonctionne le contrôle parental ?",
    "je veux faire une suggestion d'amélioration",
    "cette application est vraiment nulle",
    "quelle est la météo aujourd'hui",
    "raconte-moi une blague",
    "tu es un robot ?",
    "peux-tu m'aider en mathématiques",
    "je veux parler à un conseiller humain",
]


@dataclass
class CaseResult:
    query: str
    expected_id: Optional[str]
    predicted_id: Optional[str]
    predicted_label: Optional[str]
    score: float


def classify(client: httpx.Client, base_url: str, text: str) -> tuple[Optional[str], Optional[str], float]:
    response = client.post(f"{base_url}/diagnostic/debug/classify", json={"text": text}, timeout=15.0)
    response.raise_for_status()
    data = response.json()
    candidates = data.get("candidates") or []
    if not candidates:
        return None, None, 0.0
    top = candidates[0]
    return top["problem_id"], top["label"], top["score"]


def run_corpus(base_url: str) -> list[CaseResult]:
    results: list[CaseResult] = []
    total = len(POSITIVE_CASES) + len(NEGATIVE_CASES)
    started = time.perf_counter()

    with httpx.Client() as client:
        for i, (query, expected_id) in enumerate(POSITIVE_CASES, start=1):
            problem_id, label, score = classify(client, base_url, query)
            results.append(CaseResult(query, expected_id, problem_id, label, score))
            if i % 15 == 0:
                print(f"  ... {i}/{total} requetes traitees")

        for j, query in enumerate(NEGATIVE_CASES, start=len(POSITIVE_CASES) + 1):
            problem_id, label, score = classify(client, base_url, query)
            results.append(CaseResult(query, None, problem_id, label, score))
            if j % 15 == 0:
                print(f"  ... {j}/{total} requetes traitees")

    elapsed = time.perf_counter() - started
    print(f"Corpus complet traite en {elapsed:.1f}s ({total} requetes, {elapsed / total * 1000:.0f}ms/requete)")
    return results


def metrics_at_threshold(results: list[CaseResult], threshold: float) -> dict:
    tp = fp = fn = tn = 0
    for r in results:
        crosses = r.score >= threshold
        if r.expected_id is not None:
            if crosses and r.predicted_id == r.expected_id:
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


# Seuil reellement utilise en production, voir rasa/actions/diagnostic.py.
CURRENT_MIN_EMBEDDING_SIMILARITY = 0.75


def build_report(results: list[CaseResult]) -> str:
    lines: list[str] = []
    lines.append(f"# Rapport de qualite du matching diagnostic -- corpus de {len(results)} requetes\n")
    lines.append(
        f"Positifs : {len(POSITIVE_CASES)} (paraphrases des 8 problemes wallet+user, cible sur les "
        f"collisions deja documentees dans les manifestes) -- Negatifs : {len(NEGATIVE_CASES)} "
        "(salutations, questions FAQ generales, hors-sujet)\n"
    )
    lines.append(f"Genere le {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    lines.append(
        "**Limite assumee** : mesure le score d'embedding brut via POST /diagnostic/debug/classify, "
        "PAS le pipeline complet de desambiguisation (tiebreak mots-cles, repechage, repli par clause) "
        "qui vit cote rasa/actions/diagnostic.py et peut corriger certains cas signales ici. Voir le "
        "docstring de ce script.\n"
    )

    lines.append(f"## Seuil actuellement configure (MIN_EMBEDDING_SIMILARITY = {CURRENT_MIN_EMBEDDING_SIMILARITY})\n")
    m = metrics_at_threshold(results, CURRENT_MIN_EMBEDDING_SIMILARITY)
    lines.append(
        f"TP={m['tp']} FP={m['fp']} FN={m['fn']} TN={m['tn']} -- "
        f"precision={m['precision']:.3f} rappel={m['recall']:.3f} F1={m['f1']:.3f} accuracy={m['accuracy']:.3f}\n"
    )

    lines.append("## Balayage de seuils (0.40 a 0.90, pas de 0.05)\n")
    lines.append("| Seuil | TP | FP | FN | TN | Precision | Rappel | F1 | Accuracy |")
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    best = None
    for i in range(40, 91, 5):
        threshold = i / 100
        mm = metrics_at_threshold(results, threshold)
        if best is None or mm["f1"] > best["f1"]:
            best = mm
        lines.append(
            f"| {threshold:.2f} | {mm['tp']} | {mm['fp']} | {mm['fn']} | {mm['tn']} | "
            f"{mm['precision']:.3f} | {mm['recall']:.3f} | {mm['f1']:.3f} | {mm['accuracy']:.3f} |"
        )
    lines.append("")
    if best:
        lines.append(f"**Meilleur F1 sur ce balayage : seuil={best['threshold']:.2f} (F1={best['f1']:.3f})**\n")

    lines.append("## Confusions (collisions inter-problemes) au seuil actuel\n")
    confusions = [r for r in results if r.expected_id is not None and r.predicted_id is not None
                  and r.predicted_id != r.expected_id and r.score >= CURRENT_MIN_EMBEDDING_SIMILARITY]
    if confusions:
        lines.append("| Requete | Attendu | Obtenu a la place | Score |")
        lines.append("|---|---|---|---:|")
        for r in confusions:
            lines.append(f"| {r.query!r} | {r.expected_id} | {r.predicted_id} | {r.score:.4f} |")
    else:
        lines.append("Aucune confusion nette (candidat errone au-dessus du seuil) sur ce corpus.")
    lines.append("")

    lines.append("## Faux positifs (negatifs matches a tort) au seuil actuel\n")
    fps = [r for r in results if r.expected_id is None and r.score >= CURRENT_MIN_EMBEDDING_SIMILARITY]
    if fps:
        lines.append("| Requete | Probleme declenche a tort | Score |")
        lines.append("|---|---|---:|")
        for r in fps:
            lines.append(f"| {r.query!r} | {r.predicted_label} | {r.score:.4f} |")
    else:
        lines.append("Aucun.")
    lines.append("")

    lines.append("## Faux negatifs (score sous le seuil alors que le probleme est le bon candidat) au seuil actuel\n")
    fns = [r for r in results if r.expected_id is not None
           and r.predicted_id == r.expected_id and r.score < CURRENT_MIN_EMBEDDING_SIMILARITY]
    if fns:
        lines.append("| Requete | Probleme attendu (bon candidat, score trop bas) | Score |")
        lines.append("|---|---|---:|")
        for r in fns:
            lines.append(f"| {r.query!r} | {r.expected_id} | {r.score:.4f} |")
    else:
        lines.append("Aucun.")
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parent / "diagnostic_test_report.md"

    print(f"Verification du registre ({base_url}/diagnostic/capabilities)...")
    with httpx.Client() as client:
        caps = client.get(f"{base_url}/diagnostic/capabilities", timeout=10.0).json()
    n_problems = len(caps.get("problems") or [])
    print(f"  -> {n_problems} problemes charges")
    if n_problems == 0:
        print("ERREUR : le registre est vide -- verifier que wallet_service/user_service tournent (voir docs/10-deploiement.md)")
        sys.exit(1)

    print(f"Lancement du corpus ({len(POSITIVE_CASES)} positifs + {len(NEGATIVE_CASES)} negatifs)...")
    results = run_corpus(base_url)
    report = build_report(results)
    output_path.write_text(report, encoding="utf-8")
    print(f"Rapport ecrit dans {output_path}")

    m = metrics_at_threshold(results, CURRENT_MIN_EMBEDDING_SIMILARITY)
    print(
        f"\nMIN_EMBEDDING_SIMILARITY={CURRENT_MIN_EMBEDDING_SIMILARITY} -> "
        f"precision={m['precision']:.3f} rappel={m['recall']:.3f} F1={m['f1']:.3f} "
        f"({m['fp']} faux positifs, {m['fn']} faux negatifs sur {len(results)} requetes)"
    )


if __name__ == "__main__":
    main()
