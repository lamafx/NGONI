import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Le serveur Rasa (docker compose up -d rasa actions, voir README.md) tourne
// sur :5005 et n'autorise pas forcément les requêtes cross-origin depuis
// :5173 -- ce proxy de développement évite le problème sans toucher à la
// configuration Rasa. En production (npm run build / preview), il n'existe
// plus : voir VITE_RASA_URL dans README.md.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/rasa": {
        target: "http://localhost:5005",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/rasa/, ""),
      },
      // Meme principe pour le moteur FastAPI (:8000) : les pages
      // d'administration (statistiques, base de connaissances, parametres)
      // lisent de vraies donnees, et passer par le proxy evite le CORS.
      "/engine": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/engine/, ""),
      },
    },
  },
});
