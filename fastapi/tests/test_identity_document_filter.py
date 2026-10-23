"""Filtre des pieces d'identite (app/domains/identity_documents/analyzer.py).

Teste la DECISION sur des lignes OCR deja lues -- pas le modele OCR lui-meme :
ces tests tournent sans RapidOCR ni image. Les lignes de la CNI reprennent
exactement ce que l'OCR lit sur demo/carteIDFront.png (y compris l'erreur
"C1" pour "CI" du numero)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domains.identity_documents.analyzer import (  # noqa: E402
    NATIONAL_ID,
    PASSPORT,
    OcrLine,
    analyze_lines,
    _mrz_check_digit,
)


def _line(text, x, y, w=200, h=16, score=0.98):
    return OcrLine(text=text, score=score, x0=x, y0=y, x1=x + w, y1=y + h)


DEMO_CNI = [
    _line("RÉPUBLIQUE DE CÔTE D'IVOIRE", 180, 23, 400, 24),
    _line("CARTE NATIONALE DIDENTITÉ", 284, 61),
    _line("n° C1002356144", 283, 96),
    _line("Prenom(s)", 278, 129, 70, 12),
    _line("ADOU ERIC BARUCH DEVERIN", 278, 150, 320, 18),
    _line("Nom", 277, 178, 30, 12),
    _line("AYEKOE", 278, 197, 90, 18),
    _line("Date de Naissance", 279, 256, 120, 12),
    _line("Sexe", 423, 258, 35, 12),
    _line("Taille", 479, 256, 40, 12),
    _line("Nationalité", 551, 256, 80, 12),
    _line("14/05/2006 M", 278, 271, 170, 18),
    _line("1,65", 476, 272, 45, 18),
    _line("IVOIRIENNE", 549, 271, 130, 18),
    _line("Lieu de Naissance", 278, 302, 120, 12),
    _line("COCODY (CIV)", 278, 324, 150, 18),
    _line("Signature du titulaire", 31, 366, 160, 12),
    _line("Date d'expiration", 278, 382, 110, 12),
    _line("01/10/2031", 278, 403, 130, 18),
    _line("354107", 557, 400, 110, 18),
]


def _fields(analysis):
    return {field["key"]: field["value"] for field in analysis.fields}


def test_demo_identity_card_is_accepted_with_all_fields():
    analysis = analyze_lines(DEMO_CNI)
    assert analysis.accepted
    assert analysis.document_type == NATIONAL_ID
    fields = _fields(analysis)
    assert fields["document_number"] == "CI002356144"
    assert fields["surname"] == "AYEKOE"
    assert fields["given_names"] == "ADOU ERIC BARUCH DEVERIN"
    assert fields["birth_date"] == "14/05/2006"
    assert fields["sex"] == "M"
    assert fields["nationality"] == "IVOIRIENNE"
    assert fields["birth_place"] == "COCODY (CIV)"
    assert fields["expiry_date"] == "01/10/2031"
    assert fields["issuing_country"] == "République de Côte d'Ivoire"


def test_photo_without_text_is_refused():
    analysis = analyze_lines([_line("C", 209, 0, 10, 10, 0.9)])
    assert not analysis.accepted
    assert analysis.document_type is None
    assert analysis.fields == []


def test_driving_licence_is_refused_by_name():
    lines = [
        _line("RÉPUBLIQUE DE CÔTE D'IVOIRE", 40, 30, 400, 24),
        _line("PERMIS DE CONDUIRE", 40, 80, 300, 24),
        _line("Nom", 300, 150, 40, 14),
        _line("KOUASSI", 300, 174, 120, 20),
        _line("Date de naissance", 300, 220, 140, 14),
        _line("01/01/1990", 300, 244, 140, 20),
    ]
    analysis = analyze_lines(lines)
    assert not analysis.accepted
    assert "permis de conduire" in analysis.reason
    assert analysis.fields == []


def test_text_document_is_refused():
    lines = [
        _line(text, 40, 40 + i * 70, 500, 30)
        for i, text in enumerate(
            ["Facture n° 2026-118", "Client : Société Alpha", "Montant total : 45 000 FCFA"]
        )
    ]
    analysis = analyze_lines(lines)
    assert not analysis.accepted
    assert analysis.document_type is None


def test_card_with_unreadable_identity_fields_is_refused_with_guidance():
    lines = [line for line in DEMO_CNI if line.text not in ("AYEKOE", "14/05/2006 M")]
    analysis = analyze_lines(lines)
    assert not analysis.accepted
    assert analysis.document_type == NATIONAL_ID
    assert "plus nette" in analysis.reason


def _td3(surname, given, number, nationality, dob, sex, expiry):
    first = f"P<{nationality}{surname}<<{given.replace(' ', '<')}".ljust(44, "<")
    second = (
        number + _mrz_check_digit(number) + nationality + dob + _mrz_check_digit(dob)
        + sex + expiry + _mrz_check_digit(expiry)
    ).ljust(44, "<")
    return first, second


def test_passport_mrz_is_parsed_and_validated():
    first, second = _td3("DIOP", "AMINATA FATOU", "A12345678", "SEN", "950203", "F", "300912")
    lines = [
        _line("PASSEPORT / PASSPORT", 40, 60, 300, 24),
        _line(first, 30, 520, 800, 26),
        _line(second, 30, 560, 800, 26),
    ]
    analysis = analyze_lines(lines)
    assert analysis.accepted
    assert analysis.document_type == PASSPORT
    assert analysis.mrz_valid is True
    fields = _fields(analysis)
    assert fields["surname"] == "DIOP"
    assert fields["given_names"] == "AMINATA FATOU"
    assert fields["birth_date"] == "03/02/1995"
    assert fields["expiry_date"] == "12/09/2030"


def test_passport_mrz_with_wrong_check_digit_is_flagged():
    first, second = _td3("DIOP", "AMINATA", "A12345678", "SEN", "950203", "F", "300912")
    second = second[:9] + str((int(second[9]) + 1) % 10) + second[10:]
    analysis = analyze_lines(
        [_line("PASSPORT", 40, 60), _line(first, 30, 520, 800, 26), _line(second, 30, 560, 800, 26)]
    )
    assert analysis.mrz_valid is False
    assert any(check["label"] == "Bande MRZ" and not check["ok"] for check in analysis.checks)
