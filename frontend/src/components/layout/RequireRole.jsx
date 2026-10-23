import { useEffect, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { ROLE_LABELS, currentAccount } from "../../services/auth";
import { isDemoMode } from "../../services/demoDirector";

/**
 * Garde d'un espace : sans session du bon role, retour a la page de connexion
 * (puis retour ici apres connexion). La demonstration rejouee (?demo=1)
 * n'est pas gardee : elle se connecte seule au demarrage (voir main.jsx).
 */
export function RequireRole({ roles, children }) {
  const location = useLocation();
  const [, setTick] = useState(0);

  // Session expiree en cours d'utilisation (401 du moteur, voir engineClient).
  useEffect(() => {
    const onExpired = () => setTick((n) => n + 1);
    window.addEventListener("ngoni-session-expired", onExpired);
    return () => window.removeEventListener("ngoni-session-expired", onExpired);
  }, []);

  if (isDemoMode()) return children;
  const account = currentAccount();
  if (account && roles.includes(account.role)) return children;
  const reason = account
    ? `Cet espace est réservé au rôle ${roles.map((r) => ROLE_LABELS[r]).join(" ou ")} : vous êtes connecté en tant que ${ROLE_LABELS[account.role]}.`
    : "Connectez-vous pour accéder à cet espace.";
  return <Navigate to="/login" replace state={{ from: location.pathname + location.search, roles, reason }} />;
}
