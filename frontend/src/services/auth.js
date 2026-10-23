// Session de l'utilisateur connecte (client, conseiller ou administrateur).
//
// Le jeton est delivre et signe par le moteur (POST /auth/login, voir
// fastapi/app/domains/auth) : l'interface ne fait que le conserver et le
// presenter. Il remplace le secret d'administration autrefois embarque dans
// le code de la page -- lisible par n'importe quel visiteur.

const BASE = import.meta.env.VITE_ENGINE_URL || "/engine";
const STORAGE_KEY = "ngoni-session";

export const ROLE_HOME = { client: "/chat", conseiller: "/agent/live", admin: "/admin" };
export const ROLE_LABELS = { client: "Client", conseiller: "Conseiller", admin: "Administration" };

// Comptes de demonstration crees par le moteur au demarrage (voir
// domains/auth/router.py) -- proposes en un clic sur la page de connexion.
export const DEMO_PASSWORD = "ngoni2026";
export const DEMO_LOGINS = [
  { login: "adou", label: "Adou Ayekoe", role: "client" },
  { login: "awa.kone", label: "Awa Koné", role: "conseiller" },
  { login: "yao.kouassi", label: "Yao Kouassi", role: "conseiller" },
  { login: "fatou.diarra", label: "Fatou Diarra", role: "admin" },
];

let session = null;

function read() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function expired(token) {
  try {
    const body = JSON.parse(atob(token.split(".")[0].replace(/-/g, "+").replace(/_/g, "/")));
    return !body.exp || body.exp * 1000 < Date.now();
  } catch {
    return true;
  }
}

export function getSession() {
  if (session === null) session = read();
  if (session && expired(session.token)) {
    logout();
    return null;
  }
  return session;
}

export function currentAccount() {
  return getSession()?.account ?? null;
}

export function authHeader() {
  const token = getSession()?.token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function login(loginName, password) {
  const res = await fetch(`${BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ login: loginName, password }),
  });
  if (!res.ok) {
    let detail = "Connexion impossible.";
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      // corps non JSON
    }
    throw new Error(detail);
  }
  session = await res.json();
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
  } catch {
    // Stockage indisponible : session valable pour cet onglet seulement.
  }
  return session.account;
}

export function logout() {
  session = null;
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // rien a effacer
  }
}

export function hasRole(...roles) {
  const account = currentAccount();
  return Boolean(account && roles.includes(account.role));
}
