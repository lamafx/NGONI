-- Migration manuelle (voir 0001-0014 pour le contexte general : pas
-- d'Alembic, execution directe contre l'instance Postgres deja en cours) :
--   psql -h 127.0.0.1 -U chatbot_user -d chatbotdb -f fastapi/migrations/0015_system_parameters.sql
--
-- Contexte : espace Admin, page Parametres (voir frontfolder/src/pages/
-- AdminSettingsPage.jsx et frontfolder/src/data/systemParameters.js) --
-- surcharges des seuils NLU/FAQ/diagnostic/reclamation, aujourd'hui codes en
-- dur dans rasa/config.yml, fastapi/app/domains/faq/service.py, rasa/actions/
-- diagnostic.py, rasa/actions/reclamation.py et
-- fastapi/app/domains/diagnostic/adapter.py.
--
-- IMPORTANT (voir app/domains/settings/service.py, KNOWN_PARAMETERS) : cette
-- table ne stocke QUE les surcharges explicitement ecrites depuis l'admin,
-- jamais les valeurs par defaut (qui restent les constantes Python/YAML
-- listees ci-dessus -- aucune duplication de source de verite ici). Rasa et
-- FastAPI ne relisent PAS encore cette table a chaud : l'ecrire ici trace
-- l'intention et l'identite de qui l'a demandee, mais ne change pas
-- (encore) le comportement reel du moteur tant que ce pont n'existe pas
-- (voir api_admin_a_developper.md, section 10).

CREATE TABLE IF NOT EXISTS ia.system_parameters (
    param_id TEXT PRIMARY KEY,
    value DOUBLE PRECISION NOT NULL,
    updated_by TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE ia.system_parameters OWNER TO chatbot_user;
GRANT ALL ON TABLE ia.system_parameters TO chatbot_user;

CREATE TABLE IF NOT EXISTS ia.system_parameter_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    param_id TEXT NOT NULL,
    old_value DOUBLE PRECISION,
    new_value DOUBLE PRECISION NOT NULL,
    -- Tracabilite obligatoire (nom + prenom saisis cote admin, voir
    -- TraceabilityModal dans AdminSettingsPage.jsx) -- jamais NULL,
    -- contrairement a complaints.updated_by qui reste optionnel.
    changed_by TEXT NOT NULL,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE ia.system_parameter_history OWNER TO chatbot_user;
GRANT ALL ON TABLE ia.system_parameter_history TO chatbot_user;

CREATE INDEX IF NOT EXISTS idx_system_parameter_history_param_id
    ON ia.system_parameter_history (param_id);
CREATE INDEX IF NOT EXISTS idx_system_parameter_history_changed_at
    ON ia.system_parameter_history (changed_at DESC);
