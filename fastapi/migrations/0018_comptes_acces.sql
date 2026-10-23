-- Migration manuelle (meme convention que 0001-0017) :
--   docker compose exec -T postgres psql -U chatbot_user -d chatbotdb < fastapi/migrations/0018_comptes_acces.sql
--
-- Comptes de connexion aux interfaces (client, conseiller, administration).
-- Mot de passe : empreinte PBKDF2-SHA256 salee, jamais le mot de passe en
-- clair (voir app/domains/auth/passwords.py).
CREATE TABLE IF NOT EXISTS ia.app_accounts (
    login TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    -- Compte NGONI de l'usager (role client) : c'est lui que l'assistant et
    -- le diagnostic interrogent.
    user_id TEXT,
    -- Identifiant de conseiller (ia.support_agents) pour les roles conseiller / admin.
    agent_id TEXT,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    last_login_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_app_accounts_role CHECK (role IN ('client', 'conseiller', 'admin'))
);
