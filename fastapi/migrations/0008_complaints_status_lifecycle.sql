-- Migration manuelle (voir 0001-0007 pour le contexte general) :
--   psql -h 127.0.0.1 -U chatbot_user -d chatbotdb -f fastapi/migrations/0008_complaints_status_lifecycle.sql
--
-- Contexte : premiere route admin du moteur (GET/PATCH /admin/complaints,
-- voir app/domains/complaints/admin_router.py) -- jusqu'ici, `status` etait
-- un TEXT libre, toujours cree a 'OPEN' en dur, sans aucune suite possible
-- ni contrainte. Introduit un cycle a 4 etats (OPEN -> IN_PROGRESS ->
-- RESOLVED / CLOSED) avec contrainte CHECK, meme convention que
-- chk_complaints_created_by (0004/0005). Ajoute aussi `updated_by`
-- (identite de l'admin ayant modifie le ticket, via X-User-ID/get_admin_id)
-- -- distinct de audit.agent_actions (migrations/0006), reserve aux
-- decisions autonomes de l'IA, jamais aux actions humaines d'un admin.

ALTER TABLE complaints.complaints
    ADD CONSTRAINT chk_complaints_status
    CHECK (status IN ('OPEN', 'IN_PROGRESS', 'RESOLVED', 'CLOSED'));

ALTER TABLE complaints.complaints ADD COLUMN IF NOT EXISTS updated_by TEXT;
