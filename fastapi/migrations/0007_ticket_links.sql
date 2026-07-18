-- Migration manuelle (voir 0001-0006 pour le contexte general) :
--   psql -h 127.0.0.1 -U chatbot_user -d chatbotdb -f fastapi/migrations/0007_ticket_links.sql
--
-- Contexte : jusqu'ici, un ticket cree automatiquement par une escalade
-- SERVICE_UNAVAILABLE (diagnostic.diagnostic_audit_log) ou par un feedback
-- suggestion/plainte (feedback.entries, voir migrations/0005) n'etait jamais
-- relie a sa ligne d'origine en base -- le lien n'existait que dans la
-- reponse API le temps de la requete (voir app/domains/feedback/service.py
-- et app/domains/diagnostic/router.py). Ajoute la colonne de lien
-- manquante des deux cotes ; aucune contrainte de cle etrangere (coherent
-- avec le reste du projet, voir docs/15-modele-donnees.md §15.1/15.8).

ALTER TABLE feedback.entries ADD COLUMN IF NOT EXISTS ticket_id TEXT;

ALTER TABLE diagnostic.diagnostic_audit_log ADD COLUMN IF NOT EXISTS related_ticket_id TEXT;
