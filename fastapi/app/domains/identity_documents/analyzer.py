"""Classification et extraction d'une piece d'identite a partir des lignes
lues par l'OCR (voir ocr.py) -- fonctions PURES, sans I/O, testables sans
modele OCR.

Regle du filtre : seules une CARTE NATIONALE D'IDENTITE ou un PASSEPORT
passent a l'extraction. Tout autre fichier (photo, capture d'ecran, facture,
permis de conduire...) est refuse avec une raison lisible -- jamais de champs
"extraits" d'un document qui n'en contient pas.

Deux sources de champs, par ordre de confiance :
  1. la bande MRZ (passeports, cartes au format TD1), dont les cles de
     controle ICAO 9303 prouvent que la lecture est exacte ;
  2. a defaut, les mentions imprimees ("Nom", "Date de naissance"...), dont
     la valeur est la ligne situee juste en dessous (ou a droite) du libelle.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Tuple

NATIONAL_ID = "national_id"
PASSPORT = "passport"

DOCUMENT_LABELS = {
    NATIONAL_ID: "Carte nationale d'identité",
    PASSPORT: "Passeport",
}

# Mentions qui designent le TYPE de piece (texte normalise : majuscules, sans
# accents ni apostrophes).
_TYPE_MARKERS = {
    NATIONAL_ID: (
        "CARTE NATIONALE DIDENTITE",
        "CARTE NATIONALE D IDENTITE",
        "CARTE DIDENTITE",
        "CARTE D IDENTITE",
        "NATIONAL IDENTITY CARD",
        "IDENTITY CARD",
        "CNI",
    ),
    PASSPORT: ("PASSEPORT", "PASSPORT", "PASAPORTE", "REISEPASS"),
}

# Pieces reconnues mais NON acceptees : on le dit nommement, plutot qu'un
# "document non reconnu" qui laisserait l'usager deviner.
_REFUSED_MARKERS = (
    ("PERMIS DE CONDUIRE", "un permis de conduire"),
    ("DRIVING LICENCE", "un permis de conduire"),
    ("DRIVER LICENSE", "un permis de conduire"),
    ("CARTE DE SEJOUR", "un titre de séjour"),
    ("TITRE DE SEJOUR", "un titre de séjour"),
    ("CARTE GRISE", "une carte grise"),
    ("CERTIFICAT DIMMATRICULATION", "une carte grise"),
    ("ACTE DE NAISSANCE", "un acte de naissance"),
    ("EXTRAIT DE NAISSANCE", "un acte de naissance"),
    ("CARTE CONSULAIRE", "une carte consulaire"),
    ("CARTE ELECTORALE", "une carte d'électeur"),
    ("CARTE DELECTEUR", "une carte d'électeur"),
    ("FACTURE", "une facture"),
    ("RELEVE", "un relevé"),
    ("ATTESTATION", "une attestation"),
)

# Libelles imprimes -> champ. Ordre = ordre d'affichage.
FIELD_LABELS: List[Tuple[str, str, Tuple[str, ...]]] = [
    ("document_number", "N° du document", ("N", "NO", "NUMERO", "DOCUMENT NO", "PASSPORT NO", "NO DU PASSEPORT", "NO DE LA CARTE")),
    ("surname", "Nom", ("NOM", "SURNAME", "NOM SURNAME", "NOM DE FAMILLE")),
    ("given_names", "Prénom(s)", ("PRENOM", "PRENOMS", "PRENOM S", "GIVEN NAMES", "PRENOMS GIVEN NAMES")),
    ("birth_date", "Date de naissance", ("DATE DE NAISSANCE", "DATE OF BIRTH", "NE LE", "NEE LE")),
    ("birth_place", "Lieu de naissance", ("LIEU DE NAISSANCE", "PLACE OF BIRTH", "A")),
    ("sex", "Sexe", ("SEXE", "SEX")),
    ("nationality", "Nationalité", ("NATIONALITE", "NATIONALITY")),
    ("issue_date", "Date de délivrance", ("DATE DE DELIVRANCE", "DATE OF ISSUE", "DELIVRE LE", "DELIVREE LE")),
    ("expiry_date", "Date d'expiration", ("DATE DEXPIRATION", "DATE D EXPIRATION", "DATE OF EXPIRY", "EXPIRE LE", "VALABLE JUSQUAU")),
]
_FIELD_DISPLAY = {key: label for key, label, _ in FIELD_LABELS}
_ALL_LABELS = {alias for _, _, aliases in FIELD_LABELS for alias in aliases if len(alias) > 2}
_ALL_LABELS |= {"TAILLE", "HEIGHT", "SIGNATURE", "SIGNATURE DU TITULAIRE", "TYPE", "CODE", "AUTORITE"}

_DATE_RE = re.compile(r"(\d{2})[./\- ](\d{2})[./\- ](\d{4})")
_MRZ_CHARS = re.compile(r"^[A-Z0-9<]+$")

# Champs sans lesquels on ne parle pas d'une piece d'identite exploitable.
REQUIRED_FIELDS = ("surname", "given_names", "birth_date")


@dataclass
class OcrLine:
    text: str
    score: float
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def height(self) -> float:
        return max(1.0, self.y1 - self.y0)

    @property
    def norm(self) -> str:
        return normalize(self.text)


@dataclass
class Analysis:
    accepted: bool
    document_type: Optional[str]
    reason: Optional[str]
    fields: List[Dict[str, str]]
    checks: List[Dict[str, object]]
    mrz_valid: Optional[bool]


def normalize(text: str) -> str:
    """Majuscules, sans accents, apostrophes/ponctuation retirees, espaces
    compactes -- "Prénom(s)" -> "PRENOM S", "D'IDENTITÉ" -> "DIDENTITE"."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.upper().replace("'", "").replace("’", "").replace("°", " ")
    text = re.sub(r"[^A-Z0-9<]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# MRZ (ICAO 9303)
# ---------------------------------------------------------------------------

def _mrz_check_digit(data: str) -> str:
    weights = (7, 3, 1)
    total = 0
    for i, char in enumerate(data):
        if char.isdigit():
            value = int(char)
        elif char.isalpha():
            value = ord(char) - 55
        else:
            value = 0
        total += value * weights[i % 3]
    return str(total % 10)


def _mrz_date(yymmdd: str, future: bool) -> Optional[str]:
    if not yymmdd.isdigit():
        return None
    yy, mm, dd = int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:])
    current = date.today().year % 100
    century = 2000 if (future or yy <= current) else 1900
    try:
        return date(century + yy, mm, dd).strftime("%d/%m/%Y")
    except ValueError:
        return None


def _mrz_names(segment: str) -> Tuple[str, str]:
    surname, _, given = segment.partition("<<")
    return surname.replace("<", " ").strip(), given.replace("<", " ").strip()


def _mrz_candidates(lines: List[OcrLine]) -> List[str]:
    candidates = []
    for line in lines:
        compact = line.text.upper().replace(" ", "").replace("«", "<").replace("‹", "<")
        if len(compact) >= 28 and compact.count("<") >= 2 and _MRZ_CHARS.match(compact):
            candidates.append(compact)
    return candidates


def parse_mrz(lines: List[OcrLine]) -> Optional[Tuple[str, Dict[str, str], bool]]:
    """(type, champs, cles_valides) ou None si aucune MRZ lisible."""
    rows = _mrz_candidates(lines)
    # TD3 -- passeport : 2 lignes de 44 caracteres.
    for i in range(len(rows) - 1):
        first, second = rows[i], rows[i + 1]
        if first.startswith("P") and len(second) >= 44:
            first, second = first[:44].ljust(44, "<"), second[:44]
            surname, given = _mrz_names(first[5:])
            checks = [
                _mrz_check_digit(second[0:9]) == second[9],
                _mrz_check_digit(second[13:19]) == second[19],
                _mrz_check_digit(second[21:27]) == second[27],
            ]
            fields = {
                "document_number": second[0:9].replace("<", ""),
                "issuing_country": first[2:5].replace("<", ""),
                "surname": surname,
                "given_names": given,
                "nationality": second[10:13].replace("<", ""),
                "birth_date": _mrz_date(second[13:19], future=False) or "",
                "sex": second[20].replace("<", ""),
                "expiry_date": _mrz_date(second[21:27], future=True) or "",
            }
            return PASSPORT, {k: v for k, v in fields.items() if v}, all(checks)
    # TD1 -- carte d'identite : 3 lignes de 30 caracteres.
    for i in range(len(rows) - 2):
        first, second, third = rows[i], rows[i + 1], rows[i + 2]
        if first[:1] in ("I", "A", "C") and len(first) >= 30 and len(second) >= 30:
            first, second = first[:30], second[:30]
            surname, given = _mrz_names(third[:30])
            checks = [
                _mrz_check_digit(first[5:14]) == first[14],
                _mrz_check_digit(second[0:6]) == second[6],
                _mrz_check_digit(second[8:14]) == second[14],
            ]
            fields = {
                "document_number": first[5:14].replace("<", ""),
                "issuing_country": first[2:5].replace("<", ""),
                "surname": surname,
                "given_names": given,
                "birth_date": _mrz_date(second[0:6], future=False) or "",
                "sex": second[7].replace("<", ""),
                "expiry_date": _mrz_date(second[8:14], future=True) or "",
                "nationality": second[15:18].replace("<", ""),
            }
            return NATIONAL_ID, {k: v for k, v in fields.items() if v}, all(checks)
    return None


# ---------------------------------------------------------------------------
# Mentions imprimees
# ---------------------------------------------------------------------------

def _match_label(norm: str) -> Optional[Tuple[str, str]]:
    """(champ, reste_de_la_ligne) si la ligne commence par un libelle connu."""
    best: Optional[Tuple[str, str, int]] = None
    for key, _, aliases in FIELD_LABELS:
        for alias in aliases:
            if norm == alias or norm.startswith(alias + " "):
                if best is None or len(alias) > best[2]:
                    best = (key, norm[len(alias):].strip(), len(alias))
    if best is None:
        return None
    key, rest, length = best
    # Libelles d'une lettre ("N", "A") : seulement s'ils sont suivis d'une valeur
    # plausible sur la meme ligne, sinon "A" capturerait n'importe quoi.
    if length <= 2 and not rest:
        return None
    if key == "birth_place" and length <= 2:
        return None
    return key, rest


def _is_label(norm: str) -> bool:
    if _match_label(norm) is not None and len(norm.split()) <= 4:
        return True
    return any(norm == label or norm.startswith(label + " ") for label in _ALL_LABELS)


def _value_below(label: OcrLine, lines: List[OcrLine]) -> Optional[OcrLine]:
    """Ligne la plus proche SOUS le libelle, alignee sur lui (meme colonne)."""
    best = None
    best_distance = None
    for line in lines:
        if line is label or _is_label(line.norm):
            continue
        dy = line.y0 - label.y0
        if dy <= label.height * 0.4 or dy > label.height * 3.2:
            continue
        overlaps = line.x0 <= label.x1 + label.height and line.x1 >= label.x0 - label.height
        if not overlaps:
            continue
        distance = dy + abs(line.x0 - label.x0) * 0.5
        if best_distance is None or distance < best_distance:
            best, best_distance = line, distance
    return best


def _clean(key: str, raw: str, issuing: Optional[str]) -> Optional[str]:
    raw = raw.strip(" :.-")
    if not raw:
        return None
    if key in ("birth_date", "issue_date", "expiry_date"):
        match = _DATE_RE.search(raw)
        return f"{match.group(1)}/{match.group(2)}/{match.group(3)}" if match else None
    if key == "sex":
        match = re.search(r"\b([MF])\b", normalize(raw))
        return match.group(1) if match else None
    if key == "document_number":
        token = re.sub(r"[^A-Z0-9]", "", normalize(raw).replace("NO ", "").replace("N ", ""))
        # "CI" est souvent lu "C1" : le prefixe pays des cartes ivoiriennes.
        if issuing == "CIV" and re.fullmatch(r"C1\d{9}", token):
            token = "CI" + token[2:]
        return token if len(token) >= 6 else None
    return raw.upper() if key in ("surname", "given_names", "nationality", "birth_place") else raw


def _issuing_country(text: str) -> Optional[str]:
    if "COTE DIVOIRE" in text or "COTE D IVOIRE" in text:
        return "CIV"
    return None


def extract_printed_fields(lines: List[OcrLine], issuing: Optional[str]) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    birth_row: Optional[str] = None
    for line in lines:
        matched = _match_label(line.norm)
        if matched is None:
            continue
        key, rest = matched
        if key in fields:
            continue
        # Valeur sur la meme ligne ("Nom : AYEKOE"), sinon juste en dessous.
        value = _clean(key, rest, issuing) if rest else None
        below = _value_below(line, lines)
        if value is None and below is not None:
            value = _clean(key, below.text, issuing)
        if key == "birth_date" and below is not None:
            birth_row = below.text
        if value is not None:
            fields[key] = value
    # Rangee "Date de naissance | Sexe" : le sexe est souvent lu dans la meme
    # boite que la date ("14/05/2006 M").
    if "sex" not in fields and birth_row:
        sex = _clean("sex", birth_row, issuing)
        if sex:
            fields["sex"] = sex
    # Numero imprime derriere un simple "n°" ("n° CI002356144").
    if "document_number" not in fields:
        for line in lines:
            match = re.search(r"\bN\s*O?\s+([A-Z0-9]{8,})", line.norm)
            if match:
                value = _clean("document_number", match.group(1), issuing)
                if value:
                    fields["document_number"] = value
                    break
    return fields


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------

def _detect_type(full_text: str) -> Optional[str]:
    padded = f" {full_text} "
    for doc_type in (PASSPORT, NATIONAL_ID):
        for marker in _TYPE_MARKERS[doc_type]:
            if f" {marker} " in padded:
                return doc_type
    return None


def _refused_kind(full_text: str) -> Optional[str]:
    padded = f" {full_text} "
    for marker, label in _REFUSED_MARKERS:
        if f" {marker} " in padded:
            return label
    return None


def _expiry_check(expiry: Optional[str]) -> Optional[Dict[str, object]]:
    if not expiry:
        return None
    try:
        day, month, year = (int(part) for part in expiry.split("/"))
        expires = date(year, month, day)
    except ValueError:
        return None
    if expires < date.today():
        return {"label": "Validité", "value": f"expirée depuis le {expiry}", "ok": False}
    return {"label": "Validité", "value": f"jusqu'au {expiry}", "ok": True}


def _country_title(text: str) -> str:
    """"RÉPUBLIQUE DE CÔTE D'IVOIRE" -> "République de Côte d'Ivoire"."""
    small = {"De", "Du", "Des", "La", "Le", "Et", "D'Ivoire"}
    words = [word if word not in small else word.lower() for word in text.title().split()]
    return " ".join(words).replace("d'ivoire", "d'Ivoire")


def analyze_lines(lines: List[OcrLine]) -> Analysis:
    full_text = " ".join(line.norm for line in lines)
    avg_score = sum(line.score for line in lines) / len(lines) if lines else 0.0
    checks: List[Dict[str, object]] = []

    if len(lines) < 3 or len(full_text) < 25:
        return Analysis(
            accepted=False,
            document_type=None,
            reason=(
                "Aucun texte de pièce d'identité n'a pu être lu sur cette image : "
                "ce n'est ni une carte d'identité ni un passeport."
            ),
            fields=[],
            checks=[{"label": "Texte lisible", "value": "aucun", "ok": False}],
            mrz_valid=None,
        )

    checks.append(
        {
            "label": "Lisibilité des mentions",
            "value": f"{len(lines)} lignes lues · confiance {round(avg_score * 100)} %",
            "ok": avg_score >= 0.75,
        }
    )

    mrz = parse_mrz(lines)
    doc_type = mrz[0] if mrz else _detect_type(full_text)
    refused = _refused_kind(full_text)

    if doc_type is None:
        reason = (
            f"Il ressemble à {refused} : ce type de document n'est pas accepté. "
            if refused
            else "Ce n'est ni une carte nationale d'identité ni un passeport. "
        )
        checks.append({"label": "Type de document", "value": refused or "non reconnu", "ok": False})
        return Analysis(False, None, reason + "Seules ces deux pièces permettent la vérification.", [], checks, None)

    issuing = mrz[1].get("issuing_country") if mrz else _issuing_country(full_text)
    fields = extract_printed_fields(lines, issuing)
    if mrz:
        # La MRZ fait foi quand ses cles de controle sont valides ; sinon elle
        # ne fait que completer ce que les mentions n'ont pas donne.
        for key, value in mrz[1].items():
            if key == "issuing_country":
                continue
            if mrz[2] or key not in fields:
                fields[key] = value

    checks.append({"label": "Type de document", "value": DOCUMENT_LABELS[doc_type].lower(), "ok": True})
    if mrz:
        checks.append(
            {
                "label": "Bande MRZ",
                "value": "clés de contrôle valides" if mrz[2] else "clés de contrôle incohérentes",
                "ok": mrz[2],
            }
        )

    missing = [_FIELD_DISPLAY[key] for key in REQUIRED_FIELDS if not fields.get(key)]
    checks.append(
        {
            "label": "Champs d'identité",
            "value": "nom, prénoms et date de naissance lus" if not missing else "manquants : " + ", ".join(missing).lower(),
            "ok": not missing,
        }
    )
    expiry = _expiry_check(fields.get("expiry_date"))
    if expiry:
        checks.append(expiry)

    ordered = [{"key": "document_type", "label": "Type de document", "value": DOCUMENT_LABELS[doc_type]}]
    country_line = next((line.text for line in lines if line.norm.startswith("REPUBLIQUE")), None)
    if country_line:
        ordered.append({"key": "issuing_country", "label": "Pays émetteur", "value": _country_title(country_line)})
    ordered += [
        {"key": key, "label": label, "value": fields[key]} for key, label, _ in FIELD_LABELS if fields.get(key)
    ]

    if missing:
        return Analysis(
            accepted=False,
            document_type=doc_type,
            reason=(
                f"{DOCUMENT_LABELS[doc_type]} reconnu(e), mais certaines mentions sont illisibles "
                f"({', '.join(missing).lower()}). Merci d'envoyer une photo plus nette, prise à plat, "
                "sans reflet et avec la pièce entière dans le cadre."
            ),
            fields=ordered,
            checks=checks,
            mrz_valid=mrz[2] if mrz else None,
        )

    return Analysis(True, doc_type, None, ordered, checks, mrz[2] if mrz else None)
