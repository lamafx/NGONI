-- Migration manuelle (voir 0001/0002 pour le contexte general : pas
-- d'Alembic, execution directe contre l'instance Postgres deja en cours) :
--   psql -h 127.0.0.1 -U chatbot_user -d chatbotdb -f fastapi/migrations/0003_response_ratings_table.sql
--
-- Contexte : notation utile/pas utile des reponses du bot (aujourd'hui : les
-- reponses FAQ), demandee via boutons rapides apres chaque reponse. Distincte
-- de feedback.entries (suggestion/plainte, simple message libre) : une
-- notation est toujours liee a un couple (question, reponse) precis, pour
-- pouvoir etudier ensuite QUELLES reponses sont jugees utiles ou non.

CREATE TABLE IF NOT EXISTS feedback.response_ratings (
    id UUID PRIMARY KEY,
    -- 'faq' aujourd'hui, extensible (ex. 'diagnostic_resolution') sans
    -- migration de type -- meme convention que feedback.entries.type.
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
