#!/bin/bash
# Premier demarrage du conteneur postgres (volume vide) UNIQUEMENT : l'image
# officielle n'execute /docker-entrypoint-initdb.d qu'a l'initialisation du
# volume. Ensuite, les donnees vivent dans le volume `pgdata` et survivent a
# `docker compose down` / `up` (seul `down -v` les efface).
#
# 1. compte applicatif (APP_DB_USER / APP_DB_PASSWORD, voir .env racine) ;
# 2. base APP_DB_NAME et extensions -- un export limite a certains schemas
#    (voir README, « Sauvegarder la base ») ne les contient pas ;
# 3. restauration de /seed/chatbotdb.dump s'il est present.
#
# Les objets du dump appartiennent a `postgres` ou au compte applicatif :
# POSTGRES_USER doit donc rester `postgres` (voir docker-compose.yml).
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
    --set=app_user="$APP_DB_USER" --set=app_pass="$APP_DB_PASSWORD" --set=app_db="$APP_DB_NAME" <<'SQL'
CREATE ROLE :"app_user" LOGIN PASSWORD :'app_pass';
CREATE DATABASE :"app_db" OWNER :"app_user";
SQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$APP_DB_NAME" <<'SQL'
CREATE EXTENSION IF NOT EXISTS vector SCHEMA public;
CREATE EXTENSION IF NOT EXISTS pgcrypto SCHEMA public;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp" SCHEMA public;
SQL

DUMP=/seed/chatbotdb.dump
if [ -f "$DUMP" ]; then
    # Le schema public existe deja dans toute base neuve : son entree est
    # retiree de la liste, sans quoi --exit-on-error s'arreterait dessus.
    pg_restore -l "$DUMP" | grep -v -e 'SCHEMA - public ' -e 'COMMENT - SCHEMA public ' > /tmp/restauration.list
    pg_restore --username "$POSTGRES_USER" --dbname "$APP_DB_NAME" --exit-on-error \
        -L /tmp/restauration.list "$DUMP"
    rm -f /tmp/restauration.list
    echo "[ngoni] $APP_DB_NAME restauree depuis $DUMP"
else
    echo "[ngoni] ATTENTION : $DUMP absent -- base $APP_DB_NAME creee VIDE (voir README, « Base de donnees »)."
fi
