-- Migration manuelle (meme convention que 0001-0015 : pas d'Alembic,
-- execution directe contre l'instance Postgres deja en cours) :
--   psql -h 127.0.0.1 -U chatbot_user -d chatbotdb -f fastapi/migrations/0016_conversations_supervision.sql
--
-- Contexte : cas d'utilisation "agent humain" du diagramme (prendre en
-- charge une demande / une reclamation) et "escalader vers un agent humain"
-- cote client. Jusqu'ici, rien n'existait cote moteur pour les porter :
-- l'historique de dialogue vivait uniquement dans le tracker store interne
-- de Rasa (non expose), et l'espace Agent du frontend tournait a 100% sur
-- DemoStore/localStorage (voir api_admin_a_developper.md section 4).
--
-- Choix d'architecture tranche ici (la question restee ouverte dans
-- api_admin_a_developper.md section 4) : option (b) -- une table
-- `conversations`/`conversation_messages` PROPRE cote FastAPI, alimentee par
-- POST /api/chat a chaque tour, plutot qu'une lecture directe du tracker
-- store Rasa. Raison : le schema interne du tracker Rasa n'est pas un
-- contrat public (il change entre versions mineures), et la prise en charge
-- humaine a besoin d'ecrire (assignation, messages du conseiller), pas
-- seulement de lire -- ecrire dans le tracker d'un moteur tiers est un
-- couplage qu'on ne veut pas. Consequence assumee : ces tables ne
-- contiennent QUE ce qui transite par POST /api/chat (le seul chemin
-- reellement utilise par le frontend), pas les eventuels autres canaux Rasa.

CREATE TABLE IF NOT EXISTS ia.conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- = sender_id Rasa = user_id envoye par le frontend a POST /api/chat.
    -- Texte libre et non UUID pour la meme raison que complaints.user_id
    -- ("frontend_user" pour la page /chat sans utilisateur reel).
    conversation_id TEXT NOT NULL UNIQUE,
    user_id TEXT,
    channel TEXT NOT NULL DEFAULT 'web',
    -- BOT (l'assistant repond seul) -> ESCALADE_DEMANDEE (un ticket a ete
    -- cree ou l'utilisateur a demande un humain, personne ne l'a encore
    -- prise) -> PRISE_EN_CHARGE (un conseiller l'a assignee : le bot se tait,
    -- voir app/domains/conversations/service.py::is_muted) -> RESOLUE.
    status TEXT NOT NULL DEFAULT 'BOT',
    escalated BOOLEAN NOT NULL DEFAULT FALSE,
    escalation_reason TEXT,
    escalated_at TIMESTAMPTZ,
    -- Identifiant du conseiller (ia.support_agents.agent_id). Pas de cle
    -- etrangere : un conseiller supprime ne doit pas effacer l'historique de
    -- qui a traite la conversation.
    assigned_to TEXT,
    assigned_at TIMESTAMPTZ,
    -- Ticket cree depuis cette conversation, s'il y en a un (lien faible
    -- vers ia.complaints.ticket_id, meme raison que ci-dessus).
    ticket_id TEXT,
    last_intent TEXT,
    last_message_at TIMESTAMPTZ,
    message_count INTEGER NOT NULL DEFAULT 0,
    resolved_at TIMESTAMPTZ,
    resolved_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT conversations_status_check
        CHECK (status IN ('BOT', 'ESCALADE_DEMANDEE', 'PRISE_EN_CHARGE', 'RESOLUE'))
);
ALTER TABLE ia.conversations OWNER TO chatbot_user;
GRANT ALL ON TABLE ia.conversations TO chatbot_user;

CREATE INDEX IF NOT EXISTS idx_conversations_status ON ia.conversations (status);
CREATE INDEX IF NOT EXISTS idx_conversations_assigned_to ON ia.conversations (assigned_to);
CREATE INDEX IF NOT EXISTS idx_conversations_last_message_at ON ia.conversations (last_message_at DESC);

CREATE TABLE IF NOT EXISTS ia.conversation_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id TEXT NOT NULL REFERENCES ia.conversations (conversation_id) ON DELETE CASCADE,
    -- 'user' | 'bot' | 'agent' (voir SENDER_ROLES cote Python).
    sender_role TEXT NOT NULL,
    -- Renseigne uniquement pour sender_role='agent' : QUI a repondu.
    agent_id TEXT,
    text TEXT NOT NULL,
    -- Intention NLU + confiance du message utilisateur, telles que
    -- classifiees par POST /api/chat. C'est la telemetrie qui manquait pour
    -- GET /admin/dashboard/intent-distribution (voir
    -- api_admin_a_developper.md section 3 : "aucune donnee n'existe pour
    -- calculer ceci"). NULL pour les messages bot/agent et pour les
    -- payloads structures ("/select_faq_question{...}"), jamais classifies.
    intent TEXT,
    confidence DOUBLE PRECISION,
    -- Boutons Rasa, score de similarite FAQ, trace_id... jamais interprete.
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT conversation_messages_sender_role_check
        CHECK (sender_role IN ('user', 'bot', 'agent'))
);
ALTER TABLE ia.conversation_messages OWNER TO chatbot_user;
GRANT ALL ON TABLE ia.conversation_messages TO chatbot_user;

CREATE INDEX IF NOT EXISTS idx_conversation_messages_conversation_id
    ON ia.conversation_messages (conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_conversation_messages_intent
    ON ia.conversation_messages (intent) WHERE intent IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_conversation_messages_created_at
    ON ia.conversation_messages (created_at DESC);

CREATE TABLE IF NOT EXISTS ia.support_agents (
    agent_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'conseiller',
    -- 'online' | 'away' | 'offline'. Modifiable a la main (PATCH) ET derive
    -- automatiquement : toute action d'un conseiller met a jour last_seen_at,
    -- et un conseiller sans activite depuis AGENT_PRESENCE_TIMEOUT_MINUTES
    -- est presente comme 'offline' quel que soit le champ (voir
    -- app/domains/agents/service.py::effective_status) -- un statut declare
    -- "en ligne" une fois pour toutes ne reflete aucune realite.
    status TEXT NOT NULL DEFAULT 'offline',
    last_seen_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT support_agents_status_check CHECK (status IN ('online', 'away', 'offline'))
);
ALTER TABLE ia.support_agents OWNER TO chatbot_user;
GRANT ALL ON TABLE ia.support_agents TO chatbot_user;

-- "Prendre en charge une reclamation" (cas d'utilisation agent humain) :
-- jusqu'ici un ticket pouvait changer de STATUT (PATCH /admin/complaints/{id})
-- mais jamais etre attribue a quelqu'un -- rien ne distinguait "en cours,
-- par personne" de "en cours, par Awa".
ALTER TABLE ia.complaints ADD COLUMN IF NOT EXISTS assigned_to TEXT;
ALTER TABLE ia.complaints ADD COLUMN IF NOT EXISTS assigned_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_complaints_assigned_to ON ia.complaints (assigned_to);
