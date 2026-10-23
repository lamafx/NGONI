# Interface web (chat client, espace conseiller, administration).
# Construite par Vite, servie par nginx -- qui joue aussi le role du proxy de
# developpement de vite.config.js : /rasa -> Rasa, /engine -> FastAPI.
FROM node:24-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Lu par Vite AU MOMENT DU BUILD (import.meta.env) : doit valoir
# ADMIN_INTERNAL_SECRET cote FastAPI, sinon les pages d'administration sont
# refusees (401). Passe par docker-compose.yml depuis le .env racine.
ARG VITE_ADMIN_SECRET=dev-admin-secret-change-me
ENV VITE_ADMIN_SECRET=$VITE_ADMIN_SECRET

RUN npm run build

FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
