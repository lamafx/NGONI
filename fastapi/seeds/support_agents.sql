-- Conseillers de demonstration (voir migrations/0016_conversations_supervision.sql
-- pour la table) :
--   psql -h 127.0.0.1 -U chatbot_user -d chatbotdb -f fastapi/seeds/support_agents.sql
--
-- Volontairement SEPARE de la migration : une migration cree des structures,
-- elle n'invente pas des personnes. Une installation reelle cree ses
-- conseillers via POST /admin/agents (ou par import depuis l'annuaire de
-- l'entreprise) -- ces trois lignes n'existent que pour qu'un poste de
-- developpement ait une file utilisable immediatement.
--
-- status = 'offline' a l'insertion, y compris ici : le statut affiche est
-- derive de last_seen_at (voir app/domains/agents/service.py::effective_status),
-- declarer "online" dans un fichier de seed ne rendrait personne joignable.

INSERT INTO ia.support_agents (agent_id, display_name, role, status)
VALUES
    ('conseiller-1', 'Awa Koné', 'conseiller', 'offline'),
    ('conseiller-2', 'Yao Kouassi', 'conseiller', 'offline'),
    ('superviseur-1', 'Fatou Diarra', 'superviseur', 'offline')
ON CONFLICT (agent_id) DO NOTHING;
