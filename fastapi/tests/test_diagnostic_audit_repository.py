"""Tests de DiagnosticAuditRepository (Phase 6, etape 26, voir
docs/diagnostic-roadmap.md) avec une fausse Session SQLAlchemy en memoire --
meme convention que tests/test_ticket_creation.py (FakeSession) : ces tests
verifient la LOGIQUE d'upsert/ecriture, pas la connectivite Postgres reelle
(deja couverte par tests/test_wallet_stub.py, qui touche une vraie base)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domains.diagnostic.audit_repository import DiagnosticAuditRepository  # noqa: E402
from app.domains.diagnostic.models import DiagnosticSession  # noqa: E402


class _FakeQuery:
    def __init__(self, sessions_by_id: dict, model) -> None:
        self._sessions_by_id = sessions_by_id
        self._model = model
        self._session_id = None

    def filter_by(self, **kwargs):
        self._session_id = kwargs.get("session_id")
        return self

    def first(self):
        if self._model is not DiagnosticSession:
            return None
        return self._sessions_by_id.get(self._session_id)


class FakeDiagnosticDBSession:
    """Simule juste assez de l'API SQLAlchemy (add/commit/query().filter_by().first())
    pour exercer _upsert_session : un objet ajoute puis commit() devient
    ensuite trouvable par query(DiagnosticSession).filter_by(session_id=...),
    et reste le MEME objet Python (mutation en place, comme le vrai ORM)."""

    def __init__(self) -> None:
        self.added: list = []
        self.audit_logs: list = []
        self._sessions_by_id: dict[str, DiagnosticSession] = {}

    def add(self, obj) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        for obj in self.added:
            if isinstance(obj, DiagnosticSession):
                self._sessions_by_id[obj.session_id] = obj
            else:
                self.audit_logs.append(obj)
        self.added = []

    def query(self, model):
        return _FakeQuery(self._sessions_by_id, model)


def test_record_writes_one_audit_log_entry():
    db = FakeDiagnosticDBSession()
    repo = DiagnosticAuditRepository(db)

    repo.record(
        trace_id="trace-1", session_id="sess-1", user_id="usr_123",
        service="wallet", problem="withdrawal_pending", called_endpoint="http://wallet/api/v1/diagnostic/withdrawal",
        entities={"transaction_reference": "WITHDRAW-abc"}, outcome="RESOLVED",
        outcome_detail="WITHDRAWAL_COMPLETED", latency_ms=120,
    )

    assert len(db.audit_logs) == 1
    entry = db.audit_logs[0]
    assert entry.trace_id == "trace-1"
    assert entry.outcome == "RESOLVED"
    assert entry.outcome_detail == "WITHDRAWAL_COMPLETED"
    assert entry.latency_ms == 120


def test_record_creates_session_on_first_call():
    db = FakeDiagnosticDBSession()
    repo = DiagnosticAuditRepository(db)

    repo.record(
        trace_id="trace-1", session_id="sess-1", user_id="usr_123",
        service="wallet", problem="withdrawal_pending", called_endpoint=None,
        entities={}, outcome="NEED_MORE_INFO", outcome_detail="transaction_reference", latency_ms=None,
    )

    session = repo.get_session("sess-1")
    assert session is not None
    assert session.status == "IN_PROGRESS"
    assert session.turns_count == 1
    assert session.last_outcome == "transaction_reference"


def test_record_updates_existing_session_and_increments_turns():
    db = FakeDiagnosticDBSession()
    repo = DiagnosticAuditRepository(db)

    repo.record(
        trace_id="trace-1", session_id="sess-1", user_id="usr_123",
        service="wallet", problem="withdrawal_pending", called_endpoint=None,
        entities={}, outcome="NEED_MORE_INFO", outcome_detail="transaction_reference", latency_ms=None,
    )
    repo.record(
        trace_id="trace-2", session_id="sess-1", user_id="usr_123",
        service="wallet", problem="withdrawal_pending", called_endpoint="http://wallet/api/v1/diagnostic/withdrawal",
        entities={"transaction_reference": "WITHDRAW-abc"}, outcome="RESOLVED",
        outcome_detail="WITHDRAWAL_COMPLETED", latency_ms=88,
    )

    session = repo.get_session("sess-1")
    assert session.turns_count == 2
    assert session.status == "RESOLVED"
    assert session.last_outcome == "WITHDRAWAL_COMPLETED"
    assert len(db.audit_logs) == 2


def test_escalate_outcome_maps_to_escalated_status():
    db = FakeDiagnosticDBSession()
    repo = DiagnosticAuditRepository(db)

    repo.record(
        trace_id="trace-1", session_id="sess-1", user_id="usr_123",
        service="wallet", problem="withdrawal_pending", called_endpoint="http://wallet/api/v1/diagnostic/withdrawal",
        entities={}, outcome="ESCALATE", outcome_detail="SERVICE_UNAVAILABLE", latency_ms=5000,
    )

    session = repo.get_session("sess-1")
    assert session.status == "ESCALATED"


def test_sessions_are_isolated_by_session_id():
    db = FakeDiagnosticDBSession()
    repo = DiagnosticAuditRepository(db)

    repo.record(
        trace_id="t1", session_id="sess-1", user_id="usr_1", service="wallet", problem="withdrawal_pending",
        called_endpoint=None, entities={}, outcome="RESOLVED", outcome_detail="WITHDRAWAL_COMPLETED", latency_ms=10,
    )
    repo.record(
        trace_id="t2", session_id="sess-2", user_id="usr_2", service="user", problem="kyc_status_issue",
        called_endpoint=None, entities={}, outcome="RESOLVED", outcome_detail="KYC_ALREADY_VERIFIED", latency_ms=10,
    )

    assert repo.get_session("sess-1").problem == "withdrawal_pending"
    assert repo.get_session("sess-2").problem == "kyc_status_issue"
