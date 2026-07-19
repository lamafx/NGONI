-- Migration manuelle (voir 0001-0008 pour le contexte general) :
--   psql -h 127.0.0.1 -U chatbot_user -d chatbotdb -f fastapi/migrations/0009_complaints_idempotency_key.sql
--
-- Contexte : rasa/actions/reclamation.py genere deja une idempotency_key par
-- reclamation (voir ActionExtractReclamationEntities), documentee comme
-- "cote client uniquement pour l'instant... pas encore le cas cote
-- fastapi/tickets/create". Sans dedoublonnage serveur, une relance reseau
-- apres un commit reussi mais reponse perdue cree un vrai doublon de ticket.
-- Colonne NULLABLE : une contrainte UNIQUE Postgres autorise plusieurs NULL
-- (aucune valeur ne s'egale a une autre NULL), donc les tickets crees sans
-- cle (anciens appelants, appels directs de l'API) restent inchanges.

ALTER TABLE complaints.complaints ADD COLUMN IF NOT EXISTS idempotency_key TEXT;

ALTER TABLE complaints.complaints
    ADD CONSTRAINT uq_complaints_idempotency_key UNIQUE (idempotency_key);
