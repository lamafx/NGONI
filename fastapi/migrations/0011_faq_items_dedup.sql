-- Migration manuelle (voir 0001-0010 pour le contexte general) :
--   psql -h 127.0.0.1 -U chatbot_user -d chatbotdb -f fastapi/migrations/0011_faq_items_dedup.sql
--
-- Contexte (docs/16-audit-faq-nlu-2026-07.md, 16.2) : 5 des 31 lignes de
-- core.faq_items sont des doublons exacts (meme question, meme reponse,
-- slug different) -- confirme ici question par question (answer =
-- (SELECT answer FROM ... WHERE question = ... AND id <> id) est vrai pour
-- les 10 lignes des 5 paires, aucune divergence de contenu). Supprime la
-- ligne la plus recente de chaque paire (created_at le plus tardif),
-- conserve l'originale. Idempotent (DELETE ... WHERE id IN (...), sans
-- effet si deja applique).

DELETE FROM core.faq_items WHERE id IN (
    'd0bf8c1f-e81e-451f-9978-bd159f96f533', -- doublon de c1b3ba23... "Comment fonctionne le systeme de dons pendant un live ?"
    'b78b1553-78ac-4623-a9d0-d65619efcd2b', -- doublon de 59102004... "Comment un createur peut-il gagner de l'argent sur la plateforme ?"
    '48296b42-e646-4509-b2c0-ad35485fe746', -- doublon de 4b11a91d... "Ou trouver la foire aux questions ?"
    'c01f82bc-390d-472e-8569-9a9a4d228bbe', -- doublon de 0b2cdc11... "Puis-je utiliser NGONI sur plusieurs appareils ?"
    '2d40583b-83d0-4b37-b7a1-efee475185a8'  -- doublon de 0cf45616... "Quels documents sont necessaires pour le KYC ?"
);
