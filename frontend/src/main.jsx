import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles/global.css";
import { isDemoMode } from "./services/demoDirector";
import { DEMO_PASSWORD, currentAccount, login } from "./services/auth";

// Voir demoOverlay.css : le vrai pointeur est masque en demonstration.
if (isDemoMode()) document.documentElement.dataset.demo = "1";

// La demonstration rejouee (?demo=1) traverse les trois espaces sans
// operateur : elle ouvre seule une session d'administration (compte de
// demonstration) avant le premier rendu.
async function start() {
  if (isDemoMode() && !currentAccount()) {
    try {
      await login("fatou.diarra", DEMO_PASSWORD);
    } catch (err) {
      console.error("[demo] connexion automatique impossible :", err);
    }
  }
  ReactDOM.createRoot(document.getElementById("root")).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>
  );
}

start();
