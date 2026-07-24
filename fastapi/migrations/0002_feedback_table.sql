-- Migration manuelle (pas d'Alembic dans ce projet -- voir 0001_e5_base_upgrade.sql
-- pour le contexte general). A executer directement contre l'instance Postgres
-- DEJA EN COURS D'EXECUTION :
--   psql -h 127.0.0.1 -U chatbot_user -d chatbotdb -f fastapi/migrations/0002_feedback_table.sql
--
-- Contexte : persistance reelle pour les intentions Rasa `suggestion` et
-- `plainte` (voir docs/suggestion-plainte-flow.md) -- jusqu'ici de simples
-- reponses statiques sans aucune trace en base.

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
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE feedback.entries OWNER TO chatbot_user;
GRANT ALL ON TABLE feedback.entries TO chatbot_user;

CREATE INDEX IF NOT EXISTS idx_feedback_entries_type ON feedback.entries (type);
