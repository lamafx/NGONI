-- Migration manuelle (voir 0001-0013 pour le contexte general : pas
-- d'Alembic, execution directe contre l'instance Postgres deja en cours) :
--   psql -h 127.0.0.1 -U chatbot_user -d chatbotdb -f fastapi/migrations/0014_superagent_audit_domain.sql
--
-- Contexte : le mode Super-Agent (rasa/actions/diagnostic.py::is_superagent_mode)
-- trace ses deux decisions autonomes (remboursement de retrait bloque,
-- acceleration KYC) via _report_agent_action(domain="diagnostic_superagent"),
-- deja ajoute a ALLOWED_DOMAINS cote app/domains/audit/service.py -- mais les
-- CHECK constraints poses par la migration 0006 (jamais etendus depuis)
-- rejettent encore ce domaine et ces action_type au niveau de la base
-- (CheckViolation constate en pratique : POST /audit/actions renvoyait 500,
-- aucune trace ecrite malgre l'appel best-effort cote serveur d'actions).

ALTER TABLE ia.agent_actions DROP CONSTRAINT chk_agent_actions_domain;
ALTER TABLE ia.agent_actions ADD CONSTRAINT chk_agent_actions_domain
    CHECK (domain IN ('faq', 'diagnostic_classification', 'diagnostic_superagent'));

ALTER TABLE ia.agent_actions DROP CONSTRAINT chk_agent_actions_action_type;
ALTER TABLE ia.agent_actions ADD CONSTRAINT chk_agent_actions_action_type
    CHECK (action_type IN (
        'faq_answer_served',
        'faq_answer_not_found',
        'problem_classified',
        'withdrawal_force_refunded',
        'kyc_fast_tracked'
    ));
