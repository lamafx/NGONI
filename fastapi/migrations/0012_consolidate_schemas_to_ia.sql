-- Consolidation de tous les schemas du domaine ia-service (core, complaints,
-- feedback, diagnostic, audit, + la table historique non schema-qualifiee
-- public.diagnostic_records) dans un schema unique "ia".
--
-- Objectif : ce service partage potentiellement une base Postgres avec
-- d'autres microservices (voir docs/02-architecture.md, base "ngoni"
-- partagee) -- des schemas generiques comme "core" ou "audit" risquent une
-- collision de nom avec le schema d'un autre service. Regrouper sous "ia"
-- namespace clairement tout ce qui appartient a ce service.
--
-- ALTER ... SET SCHEMA plutot qu'un DROP/CREATE : preserve les donnees et
-- les eventuelles connexions/vues existantes, sans dependre de l'ordre
-- d'execution -- ce fichier s'applique apres init_db.sql et
-- migrations/0001-0011 (voir .gitlab-ci.yml, boucle "for f in
-- fastapi/migrations/*.sql"), qui ont deja cree ces tables dans les
-- anciens schemas.

CREATE SCHEMA IF NOT EXISTS ia AUTHORIZATION chatbot_user;
ALTER SCHEMA ia OWNER TO chatbot_user;
GRANT ALL ON SCHEMA ia TO chatbot_user;

-- Types (core.faq_items en depend, doivent migrer avant la table)
ALTER TYPE core."FaqStatus" SET SCHEMA ia;
ALTER TYPE core."FaqCategory" SET SCHEMA ia;

-- Tables
ALTER TABLE core.faq_items SET SCHEMA ia;
ALTER TABLE complaints.complaints SET SCHEMA ia;
ALTER TABLE feedback.entries SET SCHEMA ia;
ALTER TABLE feedback.response_ratings SET SCHEMA ia;
ALTER TABLE diagnostic.diagnostic_sessions SET SCHEMA ia;
ALTER TABLE diagnostic.diagnostic_audit_log SET SCHEMA ia;
ALTER TABLE audit.agent_actions SET SCHEMA ia;

-- Table historique jamais schema-qualifiee (voir init_db.sql, utilisee par
-- GET/POST /diagnostic/search dans app/domains/diagnostic/router.py) --
-- rejoint le meme schema pour ne plus laisser de table de ce service en
-- dehors de "ia".
ALTER TABLE public.diagnostic_records SET SCHEMA ia;

-- Les anciens schemas sont maintenant vides, on les retire.
DROP SCHEMA core;
DROP SCHEMA complaints;
DROP SCHEMA feedback;
DROP SCHEMA diagnostic;
DROP SCHEMA audit;
