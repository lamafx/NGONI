"""Dossier client (confrontation piece / compte) et diagnostics ajoutes aux
services wallet et user. Les diagnostics sont testes contre une session
simulee : chaque requete SQL renvoie la ligne prevue par le test, ce qui
verifie la DECISION (code renvoye) independamment de la base."""

import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domains.support.comparison import compare  # noqa: E402
from user_service.diagnostic.services import account_extras  # noqa: E402
from wallet_service.diagnostic.services import wallet_extras  # noqa: E402

USER_ID = str(uuid.uuid4())

CNI_FIELDS = [
    {"key": "surname", "label": "Nom", "value": "AYEKOE"},
    {"key": "given_names", "label": "Prénom(s)", "value": "ADOU ERIC BARUCH DEVERIN"},
    {"key": "birth_date", "label": "Date de naissance", "value": "14/05/2006"},
    {"key": "nationality", "label": "Nationalité", "value": "IVOIRIENNE"},
    {"key": "expiry_date", "label": "Date d'expiration", "value": "01/10/2031"},
]
ACCOUNT = {"display_name": "Adou Eric Baruch Deverin AYEKOE", "date_of_birth": "2006-05-14", "country": "Cote d'Ivoire"}


def _verdicts(rows):
    return {row["label"]: row["verdict"] for row in rows}


def test_matching_card_and_account():
    assert set(_verdicts(compare(CNI_FIELDS, ACCOUNT)).values()) == {"ok"}


def test_name_and_birth_mismatch_are_flagged():
    other = {**ACCOUNT, "display_name": "Kouassi Jean", "date_of_birth": "1990-01-01"}
    verdicts = _verdicts(compare(CNI_FIELDS, other))
    assert verdicts["Nom et prénoms"] == "ko"
    assert verdicts["Date de naissance"] == "ko"


def test_expired_card_is_flagged():
    fields = [f if f["key"] != "expiry_date" else {**f, "value": "01/01/2020"} for f in CNI_FIELDS]
    assert _verdicts(compare(fields, ACCOUNT))["Validité de la pièce"] == "ko"


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


class FakeSession:
    """Renvoie, dans l'ordre, les jeux de lignes fournis a chaque execute()."""

    def __init__(self, *answers):
        self._answers = list(answers)

    def execute(self, *_args, **_kwargs):
        return _Result(self._answers.pop(0))


def _user(**overrides):
    row = {
        "id": uuid.UUID(USER_ID), "username": "u", "status": "ACTIVE", "kyc_status": "VERIFIED",
        "phone_number": "+2250700000000", "phone_verified_at": datetime(2026, 1, 1), "is_certified": False,
        "is_ngoni_plus": True, "ngoni_plus_plan": "annual", "ngoni_plus_status": "active",
        "ngoni_plus_end_date": None, "strike_count": 0, "payout_method": None,
    }
    row.update(overrides)
    return row


def _code(outcome):
    return outcome.get("resolution_code") or outcome.get("escalation_reason")


def test_ngoni_plus_active_and_cancelled():
    future = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=30)
    active = FakeSession([_user()], [{"plan_type": "annual", "status": "active", "expires_at": future, "cancelled_at": None}])
    assert _code(account_extras.resolve_ngoni_plus(active, USER_ID)) == "NGONI_PLUS_ACTIVE"
    cancelled = FakeSession([_user()], [{"plan_type": "monthly", "status": "cancelled", "expires_at": None,
                                         "cancelled_at": datetime(2026, 9, 1)}])
    assert _code(account_extras.resolve_ngoni_plus(cancelled, USER_ID)) == "NGONI_PLUS_CANCELLED"


def test_phone_and_strikes():
    assert _code(account_extras.resolve_phone_verification(
        FakeSession([_user(phone_verified_at=None)]), USER_ID)) == "PHONE_NOT_VERIFIED"
    assert _code(account_extras.resolve_account_warnings(FakeSession([_user(strike_count=1)]), USER_ID)) == "STRIKES_WARNING"
    assert _code(account_extras.resolve_account_warnings(
        FakeSession([_user(strike_count=3)]), USER_ID)) == "STRIKES_THRESHOLD_REACHED"


def test_payout_requires_verified_identity():
    session = FakeSession([_user(kyc_status="PENDING")], [])
    assert _code(account_extras.resolve_payout_destination(session, USER_ID)) == "PAYOUT_REQUIRES_KYC"


def test_unknown_account_escalates():
    assert _code(account_extras.resolve_certification(FakeSession([]), USER_ID)) == "USER_NOT_FOUND"
    assert _code(account_extras.resolve_certification(FakeSession(), "pas-un-uuid")) == "USER_NOT_FOUND"


def _wallet(**overrides):
    row = {"id": uuid.uuid4(), "balance": 45000, "pending_balance": 0, "currency": "XOF", "status": "ACTIVE",
           "frozen_reason": None, "frozen_at": None}
    row.update(overrides)
    return row


def test_wallet_frozen_escalates_and_active_reassures():
    assert _code(wallet_extras.resolve_wallet_frozen(FakeSession([_wallet()]), USER_ID)) == "WALLET_ACTIVE"
    frozen = FakeSession([_wallet(status="FROZEN", frozen_reason="Contrôle de conformité")])
    assert _code(wallet_extras.resolve_wallet_frozen(frozen, USER_ID)) == "WALLET_FROZEN"


def test_pending_balance_and_coin_purchase():
    assert _code(wallet_extras.resolve_pending_balance(FakeSession([_wallet(pending_balance=12000)]), USER_ID)) == "PENDING_FUNDS"
    failed = FakeSession([_wallet()], [{"reference_id": "COIN-1", "status": "FAILED", "amount": 2000,
                                        "created_at": datetime(2026, 10, 1), "completed_at": None}])
    assert _code(wallet_extras.resolve_coin_purchase(failed, USER_ID)) == "COIN_PURCHASE_FAILED"
