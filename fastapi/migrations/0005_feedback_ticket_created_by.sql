-- Migration manuelle (voir 0001-0004 pour le contexte general) :
--   psql -h 127.0.0.1 -U chatbot_user -d chatbotdb -f fastapi/migrations/0005_feedback_ticket_created_by.sql
--
-- Contexte : les intentions Rasa `suggestion` et `plainte` creaient
-- uniquement une entree feedback.entries (voir docs/suggestion-plainte-flow.md),
-- sans aucun ticket de suivi actionnable. Elles creent desormais aussi,
-- en plus de cette entree, un ticket dans complaints.complaints (voir
-- app/domains/feedback/service.py, FeedbackService._create_ticket_for_entry)
-- afin que chaque suggestion/plainte reste suivie par l'equipe support, pas
-- seulement consultable en base.
--
-- 'ai_feedback_ticket' distingue cette origine des 3 valeurs deja
-- existantes (formulaire de reclamation, escalade de diagnostic) --
-- CHECK plutot qu'un ENUM Postgres natif, coherent avec 0004_check_constraints.sql :
-- une nouvelle valeur reste un simple DROP/ADD CONSTRAINT, jamais une
-- migration de type.

ALTER TABLE complaints.complaints
    DROP CONSTRAINT IF EXISTS chk_complaints_created_by;

ALTER TABLE complaints.complaints
    ADD CONSTRAINT chk_complaints_created_by
    CHECK (created_by IN (
        'user_reclamation_form',
        'user_diagnostic_escalation',
        'ai_auto_escalation',
        'ai_feedback_ticket'
    ));
