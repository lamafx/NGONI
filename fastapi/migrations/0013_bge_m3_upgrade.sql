-- Migration manuelle (pas d'Alembic dans ce projet), meme procedure que
-- 0001_e5_base_upgrade.sql. A executer directement contre l'instance
-- Postgres DEJA EN COURS D'EXECUTION :
--   psql -h 127.0.0.1 -U chatbot_user -d chatbotdb -f fastapi/migrations/0013_bge_m3_upgrade.sql
--
-- Contexte : passage du modele d'embedding intfloat/multilingual-e5-base
-- (768 dimensions) a BAAI/bge-m3 (1024 dimensions) -- unifie sur le meme
-- modele que celui utilise par les classifieurs d'intention BGE-M3 (voir
-- app/shared/embeddings/service.py et app/domains/nlu/), un seul modele
-- d'embedding pour toute la plateforme au lieu de deux copies differentes.
--
-- Les vecteurs precalcules de ia.faq_items ne sont PAS reutilisables tels
-- quels (dimension differente, et de toute facon issus d'un autre modele --
-- deux embeddings ne sont comparables que s'ils viennent du meme modele).
-- Etape 1 (ce fichier) : elargir la colonne en la videant temporairement.
-- Etape 2 (scripts/reembed_faq.py) : recalculer chaque embedding avec le
-- nouveau modele. Etape 3 (ce fichier, fin) : reverrouiller NOT NULL, executee
-- SEPAREMENT une fois l'etape 2 confirmee terminee (voir instructions en bas).
--
-- Note schema : ia.faq_items (pas core.faq_items) depuis la consolidation
-- des schemas, voir migrations/0012_consolidate_schemas_to_ia.sql.

-- Etape 1 : elargir la colonne. DROP NOT NULL avant le changement de type
-- est necessaire ici : USING NULL::vector(1024) videra temporairement
-- chaque ligne existante (aucun moyen de "convertir" un vecteur 768D en
-- 1024D, il doit etre recalcule par le modele -- voir scripts/reembed_faq.py),
-- ce qui violerait la contrainte NOT NULL si elle restait active pendant ce
-- changement de type.
ALTER TABLE ia.faq_items ALTER COLUMN embedding DROP NOT NULL;
ALTER TABLE ia.faq_items ALTER COLUMN embedding TYPE vector(1024) USING NULL::vector(1024);

-- Etape 2 (HORS SQL) : executer maintenant, avant l'etape 3 ci-dessous :
--   cd fastapi && .venv\Scripts\python.exe scripts\reembed_faq.py
-- Le script recalcule embedding = embed_passage(question) pour chaque ligne
-- avec le nouveau modele (app.shared.embeddings, deja bascule sur BGE-M3),
-- via FaqRepository.update_embedding (deja prevu a cet effet, voir son
-- docstring).

-- Etape 3 : a executer SEPAREMENT une fois l'etape 2 terminee sans erreur
-- (verifie : SELECT count(*) FROM ia.faq_items WHERE embedding IS NULL;
-- doit renvoyer 0) :
--   ALTER TABLE ia.faq_items ALTER COLUMN embedding SET NOT NULL;
