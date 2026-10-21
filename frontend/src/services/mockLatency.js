// Simule la latence réseau d'un vrai backend -- à retirer telle quelle quand
// ces fonctions seront remplacées par de vrais appels fetch() vers le moteur
// FastAPI / Rasa (voir README.md, section "Connecter le backend réel").
export function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

let counter = 0;
export function nextId(prefix) {
  counter += 1;
  return `${prefix}-${Date.now().toString(36)}-${counter}`;
}

export function nowLabel() {
  return new Date().toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
}
