-- Migration manuelle (meme convention que 0001-0016) :
--   docker compose exec -T postgres psql -U chatbot_user -d chatbotdb < fastapi/migrations/0017_dossier_client.sql
--
-- Contexte : le conseiller humain doit pouvoir TRAITER les donnees d'un
-- usager -- consulter son compte, la piece d'identite qu'il a envoyee,
-- confronter les deux, puis valider ou refuser sa verification d'identite.
-- Chaque consultation et chaque decision est tracee (ia.agent_actions).

-- Pieces d'identite envoyees dans le chat (voir
-- app/domains/identity_documents). L'image n'est conservee que pour les
-- pieces ACCEPTEES par le filtre (CNI / passeport) : c'est elle que le
-- conseiller compare au compte.
CREATE TABLE IF NOT EXISTS ia.identity_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT,
    conversation_id TEXT,
    filename TEXT,
    content_type TEXT,
    image BYTEA,
    accepted BOOLEAN NOT NULL,
    document_type TEXT,
    reason TEXT,
    fields JSONB NOT NULL DEFAULT '[]'::jsonb,
    checks JSONB NOT NULL DEFAULT '[]'::jsonb,
    mrz_valid BOOLEAN,
    -- Soumission KYC ouverte cote user_service a la reception de la piece.
    kyc_submission_id UUID,
    review_status TEXT NOT NULL DEFAULT 'pending',
    reviewed_by TEXT,
    reviewed_at TIMESTAMPTZ,
    review_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_identity_documents_review_status
        CHECK (review_status IN ('pending', 'approved', 'rejected', 'not_applicable'))
);
CREATE INDEX IF NOT EXISTS idx_identity_documents_user ON ia.identity_documents (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_identity_documents_conversation ON ia.identity_documents (conversation_id);

-- Journal des actions : nouveau domaine « support_humain ».
ALTER TABLE ia.agent_actions DROP CONSTRAINT IF EXISTS chk_agent_actions_domain;
ALTER TABLE ia.agent_actions ADD CONSTRAINT chk_agent_actions_domain
    CHECK (domain IN ('faq', 'diagnostic_classification', 'diagnostic_superagent', 'support_humain'));
ALTER TABLE ia.agent_actions DROP CONSTRAINT IF EXISTS chk_agent_actions_action_type;
ALTER TABLE ia.agent_actions ADD CONSTRAINT chk_agent_actions_action_type
    CHECK (action_type IN (
        'faq_answer_served', 'faq_answer_not_found', 'problem_classified',
        'withdrawal_force_refunded', 'kyc_fast_tracked',
        'dossier_consulte', 'identite_validee', 'identite_refusee', 'note_interne'
    ));
CREATE INDEX IF NOT EXISTS idx_agent_actions_user ON ia.agent_actions (user_id, created_at DESC);
