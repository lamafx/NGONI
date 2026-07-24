-- Migration manuelle (pas d'Alembic dans ce projet -- schema gere a la main
-- via fastapi/init_db.sql, execute une seule fois par docker-entrypoint-
-- initdb.d sur un volume vide). A executer directement contre l'instance
-- Postgres DEJA EN COURS D'EXECUTION :
--   psql -h 127.0.0.1 -U chatbot_user -d chatbotdb -f fastapi/migrations/0001_e5_base_upgrade.sql
--
-- Contexte : passage du modele d'embedding intfloat/multilingual-e5-small
-- (384 dimensions) a intfloat/multilingual-e5-base (768 dimensions) -- voir
-- app/shared/embeddings/service.py pour la justification chiffree (taux de
-- faux positifs 65% -> 10%, sur le seuil diagnostic).
--
-- Les vecteurs precalcules de core.faq_items ne sont PAS reutilisables tels
-- quels (dimension differente, et de toute facon issus d'un autre modele --
-- deux embeddings ne sont comparables que s'ils viennent du meme modele).
-- Etape 1 (ce fichier) : elargir la colonne en la videant temporairement.
-- Etape 2 (scripts/reembed_faq.py) : recalculer chaque embedding avec le
-- nouveau modele. Etape 3 (ce fichier, fin) : reverrouiller NOT NULL, executee
-- SEPAREMENT une fois l'etape 2 confirmee terminee (voir instructions en bas).

-- Etape 1 : elargir la colonne. DROP NOT NULL avant le changement de type
-- est necessaire ici : USING NULL::vector(768) videra temporairement
-- chaque ligne existante (aucun moyen de "convertir" un vecteur 384D en
-- 768D, il doit etre recalcule par le modele -- voir scripts/reembed_faq.py),
-- ce qui violerait la contrainte NOT NULL si elle restait active pendant ce
-- changement de type.
ALTER TABLE core.faq_items ALTER COLUMN embedding DROP NOT NULL;
ALTER TABLE core.faq_items ALTER COLUMN embedding TYPE vector(768) USING NULL::vector(768);

-- Etape 2 (HORS SQL) : executer maintenant, avant l'etape 3 ci-dessous :
--   cd fastapi && .venv\Scripts\python.exe scripts\reembed_faq.py
-- Le script recalcule embedding = embed_passage(question) pour chaque ligne
-- avec le nouveau modele (app.shared.embeddings, deja bascule sur e5-base),
-- via FaqRepository.update_embedding (deja prevu a cet effet, voir son
-- docstring).

-- Etape 3 : a executer SEPAREMENT une fois l'etape 2 terminee sans erreur
-- (verifie : SELECT count(*) FROM core.faq_items WHERE embedding IS NULL;
-- doit renvoyer 0) :
--   ALTER TABLE core.faq_items ALTER COLUMN embedding SET NOT NULL;
