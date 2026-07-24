CREATE EXTENSION IF NOT EXISTS vector;

CREATE SCHEMA IF NOT EXISTS core AUTHORIZATION chatbot_user;
ALTER SCHEMA core OWNER TO chatbot_user;
GRANT ALL ON SCHEMA core TO chatbot_user;

DO $$ BEGIN
    CREATE TYPE core."FaqStatus" AS ENUM ('DRAFT', 'PUBLISHED', 'ARCHIVED');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE core."FaqCategory" AS ENUM (
        'ACCOUNT', 'WALLET', 'COINS', 'VPP', 'LPP', 'WITHDRAWAL',
        'NGONI_PLUS', 'KYC', 'PARENTAL_CONTROL', 'GIFTS', 'ASSISTANCE', 'GENERAL'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS core.faq_items (
    id UUID PRIMARY KEY,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    category core."FaqCategory" NOT NULL,
    keywords TEXT[] NOT NULL DEFAULT '{}',
    is_featured BOOLEAN NOT NULL DEFAULT FALSE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    locale VARCHAR(5) NOT NULL DEFAULT 'fr',
    created_at TIMESTAMP(3) NOT NULL DEFAULT now(),
    updated_at TIMESTAMP(3) NOT NULL DEFAULT now(),
    slug VARCHAR(160) NOT NULL UNIQUE,
    status core."FaqStatus" NOT NULL DEFAULT 'PUBLISHED',
    show_on_mobile BOOLEAN NOT NULL DEFAULT TRUE,
    show_on_web BOOLEAN NOT NULL DEFAULT TRUE,
    created_by UUID,
    updated_by UUID,
    -- 768 = dimension d'intfloat/multilingual-e5-base (voir
    -- app/shared/embeddings/service.py), etait vector(384) sous e5-small.
    embedding vector(768) NOT NULL
);
ALTER TABLE core.faq_items OWNER TO chatbot_user;
GRANT ALL ON TABLE core.faq_items TO chatbot_user;

CREATE SCHEMA IF NOT EXISTS complaints AUTHORIZATION chatbot_user;
ALTER SCHEMA complaints OWNER TO chatbot_user;
GRANT ALL ON SCHEMA complaints TO chatbot_user;

CREATE TABLE IF NOT EXISTS complaints.complaints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id TEXT UNIQUE NOT NULL,
    user_id TEXT,
    category TEXT NOT NULL,
    description TEXT NOT NULL,
    summary TEXT,
    urgency TEXT NOT NULL DEFAULT 'medium',
    order_number TEXT,
    incident_date TEXT,
    department TEXT,
    additional_info TEXT,
    context JSONB,
    -- Tracabilite : d'ou vient ce ticket (voir docs/diagnostic-roadmap.md
    -- Phase 3). 'user_reclamation_form' | 'user_diagnostic_escalation' |
    -- 'ai_auto_escalation' -- ce dernier signifie qu'aucun humain n'a
    -- confirme la creation (escalade automatique du Diagnostic Engine).
    -- 'ai_feedback_ticket' : ticket cree automatiquement a partir d'une
    -- suggestion ou d'une plainte (voir app/domains/feedback/service.py et
    -- migrations/0005_feedback_ticket_created_by.sql).
    created_by TEXT NOT NULL
        CONSTRAINT chk_complaints_created_by
        CHECK (created_by IN ('user_reclamation_form', 'user_diagnostic_escalation', 'ai_auto_escalation', 'ai_feedback_ticket')),
    -- Cycle de vie du ticket (voir migrations/0008_complaints_status_lifecycle.sql
    -- et app/domains/complaints/admin_router.py, PATCH /admin/complaints/{id}) :
    -- OPEN (nouveau) -> IN_PROGRESS (pris en charge) -> RESOLVED / CLOSED.
    status TEXT NOT NULL DEFAULT 'OPEN'
        CONSTRAINT chk_complaints_status
        CHECK (status IN ('OPEN', 'IN_PROGRESS', 'RESOLVED', 'CLOSED')),
    -- Identite de l'admin ayant modifie le ticket en dernier (X-User-ID,
    -- voir app/shared/admin_auth.py::get_admin_id) -- distinct de
    -- audit.agent_actions, reserve aux decisions autonomes de l'IA.
    updated_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE complaints.complaints OWNER TO chatbot_user;
GRANT ALL ON TABLE complaints.complaints TO chatbot_user;

-- Persistance des intentions Rasa `suggestion`/`plainte` (voir
-- docs/suggestion-plainte-flow.md) -- avant ce schema, ces deux intentions
-- ne declenchaient qu'une reponse statique, sans aucune trace en base.
CREATE SCHEMA IF NOT EXISTS feedback AUTHORIZATION chatbot_user;
ALTER SCHEMA feedback OWNER TO chatbot_user;
GRANT ALL ON SCHEMA feedback TO chatbot_user;

CREATE TABLE IF NOT EXISTS feedback.entries (
    id UUID PRIMARY KEY,
    -- 'suggestion' | 'complaint_sentiment' -- voir app/domains/feedback/models.py::FeedbackType.
    -- TEXT plutot qu'un ENUM Postgres natif : meme convention que
    -- complaints.created_by, un nouveau type ne doit jamais exiger de
    -- migration de type.
    type TEXT NOT NULL,
    message TEXT NOT NULL,
    -- Texte libre plutot que UUID : meme raison que complaints.user_id
    -- (tracker.sender_id cote Rasa n'est pas toujours un UUID valide).
    user_id TEXT,
    created_by TEXT NOT NULL DEFAULT 'ai_agent',
    -- Lien vers complaints.complaints.ticket_id quand ce feedback en a cree
    -- un (voir migrations/0007_ticket_links.sql et
    -- app/domains/feedback/service.py::_create_ticket_for_entry) -- jamais
    -- une cle etrangere (voir docs/15-modele-donnees.md §15.1).
    ticket_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE feedback.entries OWNER TO chatbot_user;
GRANT ALL ON TABLE feedback.entries TO chatbot_user;

-- Notation utile/pas utile des reponses du bot (aujourd'hui : reponses FAQ),
-- distincte de feedback.entries -- toujours liee a un couple (question,
-- reponse) precis, voir app/domains/feedback/models.py::ResponseRating.
CREATE TABLE IF NOT EXISTS feedback.response_ratings (
    id UUID PRIMARY KEY,
    interaction_type TEXT NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    is_useful BOOLEAN NOT NULL,
    user_id TEXT,
    created_by TEXT NOT NULL DEFAULT 'ai_agent',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE feedback.response_ratings OWNER TO chatbot_user;
GRANT ALL ON TABLE feedback.response_ratings TO chatbot_user;

CREATE INDEX IF NOT EXISTS idx_response_ratings_interaction_type ON feedback.response_ratings (interaction_type);
CREATE INDEX IF NOT EXISTS idx_response_ratings_is_useful ON feedback.response_ratings (is_useful);

CREATE INDEX IF NOT EXISTS idx_feedback_entries_type ON feedback.entries (type);

CREATE TABLE IF NOT EXISTS diagnostic_records (
    id SERIAL PRIMARY KEY,
    symptom TEXT NOT NULL,
    diagnosis TEXT NOT NULL,
    next_steps TEXT NOT NULL
);

-- Phase 6 (etape 26, voir docs/diagnostic-roadmap.md) : tracabilite du
-- Diagnostic Engine. DiagnosticSession = une ligne par session_id, mise a
-- jour a chaque tour ; DiagnosticAuditLog = une ligne par appel a
-- /diagnostic/resolve, jamais modifiee (historique complet).
CREATE SCHEMA IF NOT EXISTS diagnostic AUTHORIZATION chatbot_user;
ALTER SCHEMA diagnostic OWNER TO chatbot_user;
GRANT ALL ON SCHEMA diagnostic TO chatbot_user;

CREATE TABLE IF NOT EXISTS diagnostic.diagnostic_sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT,
    service TEXT,
    problem TEXT,
    status TEXT NOT NULL DEFAULT 'IN_PROGRESS',
    last_outcome TEXT,
    turns_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE diagnostic.diagnostic_sessions OWNER TO chatbot_user;
GRANT ALL ON TABLE diagnostic.diagnostic_sessions TO chatbot_user;

CREATE TABLE IF NOT EXISTS diagnostic.diagnostic_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    user_id TEXT,
    service TEXT NOT NULL,
    problem TEXT NOT NULL,
    called_endpoint TEXT,
    request_entities JSONB,
    outcome TEXT NOT NULL,
    outcome_detail TEXT,
    latency_ms INTEGER,
    -- Renseigne a posteriori quand une escalade SERVICE_UNAVAILABLE aboutit
    -- a un ticket automatique (voir migrations/0007_ticket_links.sql et
    -- app/domains/diagnostic/audit_repository.py::link_latest_escalation).
    related_ticket_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE diagnostic.diagnostic_audit_log OWNER TO chatbot_user;
GRANT ALL ON TABLE diagnostic.diagnostic_audit_log TO chatbot_user;
CREATE INDEX IF NOT EXISTS idx_diagnostic_audit_log_session_id ON diagnostic.diagnostic_audit_log (session_id);

-- Phase "traçabilité agent" (voir docs/15-modele-donnees.md) : trace
-- generique des decisions autonomes non couvertes par un audit specifique a
-- un domaine (reponses FAQ servies, classification diagnostic decidee cote
-- serveur d'actions Rasa). Voir app/domains/audit/ et
-- migrations/0006_agent_actions_audit.sql.
CREATE SCHEMA IF NOT EXISTS audit AUTHORIZATION chatbot_user;
ALTER SCHEMA audit OWNER TO chatbot_user;
GRANT ALL ON SCHEMA audit TO chatbot_user;

CREATE TABLE IF NOT EXISTS audit.agent_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id TEXT,
    session_id TEXT,
    user_id TEXT,
    domain TEXT NOT NULL
        CONSTRAINT chk_agent_actions_domain
        CHECK (domain IN ('faq', 'diagnostic_classification')),
    action_type TEXT NOT NULL
        CONSTRAINT chk_agent_actions_action_type
        CHECK (action_type IN ('faq_answer_served', 'faq_answer_not_found', 'problem_classified')),
    input_data JSONB,
    output_data JSONB,
    related_ticket_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE audit.agent_actions OWNER TO chatbot_user;
GRANT ALL ON TABLE audit.agent_actions TO chatbot_user;
CREATE INDEX IF NOT EXISTS idx_agent_actions_session_id ON audit.agent_actions (session_id);
CREATE INDEX IF NOT EXISTS idx_agent_actions_domain ON audit.agent_actions (domain);

CREATE SCHEMA IF NOT EXISTS wallet_stub AUTHORIZATION chatbot_user;
ALTER SCHEMA wallet_stub OWNER TO chatbot_user;
GRANT ALL ON SCHEMA wallet_stub TO chatbot_user;

CREATE TABLE IF NOT EXISTS wallet_stub.wallets (
    user_id TEXT PRIMARY KEY,
    kyc_verified BOOLEAN NOT NULL DEFAULT TRUE
);
ALTER TABLE wallet_stub.wallets OWNER TO chatbot_user;
GRANT ALL ON TABLE wallet_stub.wallets TO chatbot_user;

CREATE TABLE IF NOT EXISTS wallet_stub.withdrawals (
    user_id TEXT NOT NULL,
    reference_id TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    provider_transaction_id TEXT,
    error_code TEXT,
    completed_at TIMESTAMP,
    PRIMARY KEY (user_id, reference_id)
);
ALTER TABLE wallet_stub.withdrawals OWNER TO chatbot_user;
GRANT ALL ON TABLE wallet_stub.withdrawals TO chatbot_user;
