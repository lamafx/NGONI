-- Migration manuelle (voir 0001-0009 pour le contexte general) :
--   psql -h 127.0.0.1 -U chatbot_user -d chatbotdb -f fastapi/migrations/0010_missing_indexes.sql
--
-- Contexte (audit robustesse) : ces colonnes sont filtrees a chaque requete
-- admin ou de tracabilite (voir complaints/repository.py::list_tickets,
-- diagnostic/audit_repository.py, audit/repository.py) mais aucune n'etait
-- indexee -- scan sequentiel systematique, degradation croissante avec le
-- volume de tickets/sessions.

CREATE INDEX IF NOT EXISTS idx_complaints_user_id ON complaints.complaints (user_id);
CREATE INDEX IF NOT EXISTS idx_complaints_category ON complaints.complaints (category);
CREATE INDEX IF NOT EXISTS idx_complaints_status ON complaints.complaints (status);
CREATE INDEX IF NOT EXISTS idx_complaints_urgency ON complaints.complaints (urgency);

CREATE INDEX IF NOT EXISTS idx_diagnostic_audit_log_session_id ON diagnostic.diagnostic_audit_log (session_id);

CREATE INDEX IF NOT EXISTS idx_agent_actions_session_id ON audit.agent_actions (session_id);
CREATE INDEX IF NOT EXISTS idx_agent_actions_domain ON audit.agent_actions (domain);
