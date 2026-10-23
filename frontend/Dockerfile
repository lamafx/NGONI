# Interface web (chat client, espace conseiller, administration).
# Construite par Vite, servie par nginx -- qui joue aussi le role du proxy de
# developpement de vite.config.js : /rasa -> Rasa, /engine -> FastAPI.
FROM node:24-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Aucun secret embarque : l'interface s'authentifie par jeton de session
# (connexion sur /login, voir src/services/auth.js).
RUN npm run build

FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
