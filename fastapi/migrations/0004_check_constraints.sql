-- Migration manuelle (voir 0001-0003 pour le contexte general) :
--   psql -h 127.0.0.1 -U chatbot_user -d chatbotdb -f fastapi/migrations/0004_check_constraints.sql
--
-- Contexte : plusieurs colonnes de provenance/categorie sont en TEXT libre,
-- sans aucune contrainte en base -- leur coherence depend entierement du
-- code applicatif (FeedbackType, RatingInteractionType, cf. models.py).
-- Une valeur erronee inseree directement en base (script ponctuel, requete
-- manuelle) ne serait aujourd'hui jamais detectee. CHECK plutot qu'un ENUM
-- Postgres natif : coherent avec le choix deja fait pour ces memes colonnes
-- (voir commentaires models.py) -- une nouvelle valeur reste un simple ALTER
-- TABLE ... DROP/ADD CONSTRAINT, jamais une migration de type.
--
-- Verifie avant application (aucune ligne existante ne violerait ces
-- contraintes, cf. session de developpement du 2026-07-14) :
--   complaints.created_by      : 'user_reclamation_form' | 'ai_auto_escalation' (observes)
--   feedback.entries.type      : 'suggestion' | 'complaint_sentiment' (observes)
--   feedback.response_ratings  : 'faq' (observe)

ALTER TABLE complaints.complaints
    ADD CONSTRAINT chk_complaints_created_by
    CHECK (created_by IN ('user_reclamation_form', 'user_diagnostic_escalation', 'ai_auto_escalation'));

ALTER TABLE feedback.entries
    ADD CONSTRAINT chk_feedback_entries_type
    CHECK (type IN ('suggestion', 'complaint_sentiment'));

ALTER TABLE feedback.response_ratings
    ADD CONSTRAINT chk_response_ratings_interaction_type
    CHECK (interaction_type IN ('faq'));
