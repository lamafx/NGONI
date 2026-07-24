-- Migration manuelle (voir 0001-0005 pour le contexte general : pas
-- d'Alembic, execution directe contre l'instance Postgres deja en cours) :
--   psql -h 127.0.0.1 -U chatbot_user -d chatbotdb -f fastapi/migrations/0006_agent_actions_audit.sql
--
-- Contexte : trace generique des decisions autonomes du systeme non deja
-- couvertes par un audit specifique a un domaine (voir
-- diagnostic.diagnostic_audit_log pour /diagnostic/resolve, qui reste
-- inchange) -- reponses FAQ servies, classification d'un probleme
-- diagnostique decidee cote serveur d'actions Rasa. Voir
-- app/domains/audit/ et docs/15-modele-donnees.md.

CREATE SCHEMA IF NOT EXISTS audit AUTHORIZATION chatbot_user;
ALTER SCHEMA audit OWNER TO chatbot_user;
GRANT ALL ON SCHEMA audit TO chatbot_user;

CREATE TABLE IF NOT EXISTS audit.agent_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id TEXT,
    session_id TEXT,
    user_id TEXT,
    -- TEXT + CHECK plutot qu'ENUM Postgres (meme convention que
    -- complaints.created_by) : une nouvelle valeur reste un simple
    -- DROP/ADD CONSTRAINT, jamais une migration de type.
    domain TEXT NOT NULL
        CONSTRAINT chk_agent_actions_domain
        CHECK (domain IN ('faq', 'diagnostic_classification')),
    action_type TEXT NOT NULL
        CONSTRAINT chk_agent_actions_action_type
        CHECK (action_type IN ('faq_answer_served', 'faq_answer_not_found', 'problem_classified')),
    input_data JSONB,
    output_data JSONB,
    -- Renseigne a posteriori quand une escalade/un feedback aboutit a un
    -- ticket -- jamais une cle etrangere (aucune FK inter-schema dans ce
    -- projet, voir 15.1 de la documentation).
    related_ticket_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE audit.agent_actions OWNER TO chatbot_user;
GRANT ALL ON TABLE audit.agent_actions TO chatbot_user;

CREATE INDEX IF NOT EXISTS idx_agent_actions_session_id ON audit.agent_actions (session_id);
CREATE INDEX IF NOT EXISTS idx_agent_actions_domain ON audit.agent_actions (domain);
