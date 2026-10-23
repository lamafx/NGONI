import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles/global.css";
import { isDemoMode } from "./services/demoDirector";

// Voir demoOverlay.css : le vrai pointeur est masque en demonstration.
if (isDemoMode()) document.documentElement.dataset.demo = "1";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
