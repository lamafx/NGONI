/**
 * Connexion aux trois espaces. Le moteur verifie l'identifiant et le mot de
 * passe (empreinte PBKDF2) puis delivre un jeton signe qui porte le role :
 * client -> chat, conseiller -> poste conseiller, admin -> administration.
 */

import { useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import ngoniIcon from "../assets/ngoni-support-icon.jpeg";
import { DEMO_LOGINS, DEMO_PASSWORD, ROLE_HOME, ROLE_LABELS, currentAccount, login } from "../services/auth";

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [loginName, setLoginName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const wanted = location.state?.from;
  const reason = location.state?.reason;

  const account = currentAccount();
  if (account && !wanted) return <Navigate to={ROLE_HOME[account.role]} replace />;

  async function submit(name = loginName, secret = password) {
    setBusy(true);
    setError(null);
    try {
      const signedIn = await login(name, secret);
      const allowed = location.state?.roles;
      const target = wanted && (!allowed || allowed.includes(signedIn.role)) ? wanted : ROLE_HOME[signedIn.role];
      navigate(target, { replace: true });
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-page">
      <form
        className="login-card"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <div className="login-brand">
          <img src={ngoniIcon} alt="" />
          <div>
            <div className="login-title">Ngoni Support</div>
            <div className="login-sub">Connexion à votre espace</div>
          </div>
        </div>

        {reason && <div className="login-info">{reason}</div>}

        <label className="login-label" htmlFor="login-name">Identifiant</label>
        <input
          id="login-name"
          className="login-input"
          value={loginName}
          onChange={(e) => setLoginName(e.target.value)}
          autoComplete="username"
          autoFocus
        />
        <label className="login-label" htmlFor="login-password">Mot de passe</label>
        <input
          id="login-password"
          className="login-input"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
        />
        {error && <div className="login-error">{error}</div>}
        <button type="submit" className="btn btn-primary login-submit" disabled={busy || !loginName || !password}>
          {busy ? "Connexion…" : "Se connecter"}
        </button>

        <div className="login-demo">
          <div className="login-demo-title">Comptes de démonstration (mot de passe « {DEMO_PASSWORD} »)</div>
          <div className="login-demo-list">
            {DEMO_LOGINS.map((demo) => (
              <button
                key={demo.login}
                type="button"
                className="login-demo-btn"
                disabled={busy}
                onClick={() => {
                  setLoginName(demo.login);
                  setPassword(DEMO_PASSWORD);
                  submit(demo.login, DEMO_PASSWORD);
                }}
              >
                <strong>{demo.label}</strong>
                <span>
                  {ROLE_LABELS[demo.role]} · {demo.login}
                </span>
              </button>
            ))}
          </div>
        </div>
      </form>
    </div>
  );
}
