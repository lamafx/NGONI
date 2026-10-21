import { useEffect, useState } from "react";
import { subscribeOverlay } from "../../services/demoOverlay";

/**
 * Rend l'incrustation courante par-dessus toute l'application.
 *
 * Monte une seule fois (voir App.jsx) pour survivre aux bascules de page :
 * le carton final doit pouvoir s'afficher alors que la supervision est
 * encore a l'ecran.
 *
 * Chaque type ne repond qu'a UNE question a l'ecran -- jamais un panneau qui
 * accumule des informations. Le texte est volontairement tres court : trois a
 * six mots pour ce qui compte.
 */
export function DemoOverlay() {
  const [o, setO] = useState(null);
  useEffect(() => subscribeOverlay(setO), []);
  if (!o) return null;

  return (
    <div className={`dov dov-${o.type}`} key={o.key} aria-live="polite">
      {o.type === "badge" && (
        <div className="dov-badge">
          {o.lines.map((l) => (
            <span key={l}>{l}</span>
          ))}
        </div>
      )}

      {o.type === "state" && (
        <div className="dov-card dov-state">
          <div className="dov-state-col is-before">
            <span className="dov-k">Avant</span>
            <span className="dov-v">{o.before}</span>
          </div>
          <div className="dov-arrow" aria-hidden="true">
            <svg width="34" height="16" viewBox="0 0 34 16" fill="none">
              <path d="M1 8h30m0 0-7-6.5M31 8l-7 6.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <div className="dov-state-col is-after">
            <span className="dov-k">Après</span>
            <span className="dov-v">{o.after}</span>
          </div>
        </div>
      )}

      {o.type === "checks" && (
        <div className="dov-card dov-checks">
          <ul>
            {o.items.map((it, i) => (
              <li key={it} style={{ animationDelay: `${i * 0.42}s` }}>
                <svg width="16" height="16" viewBox="0 0 20 20" fill="none" aria-hidden="true">
                  <path d="m4 10.4 4 4 8-9" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                {it}
              </li>
            ))}
          </ul>
          {o.headline && (
            <div className="dov-headline" style={{ animationDelay: `${o.items.length * 0.42 + 0.3}s` }}>
              {o.headline}
            </div>
          )}
        </div>
      )}

      {o.type === "rupture" && (
        <div className="dov-rupture">
          <div className="dov-rupture-title">{o.title}</div>
          {o.subtitle && <div className="dov-rupture-sub">{o.subtitle}</div>}
        </div>
      )}

      {o.type === "ticket" && (
        <div className="dov-card dov-ticket">
          <div className="dov-ticket-id">{o.id}</div>
          <dl>
            {o.rows.map(([k, v]) => (
              <div key={k}>
                <dt>{k}</dt>
                <dd>{v}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      {o.type === "stat" && (
        <div className="dov-card dov-stat">
          <div className="dov-stat-value">{o.value}</div>
          <div className="dov-stat-label">{o.label}</div>
        </div>
      )}

      {o.type === "narration" && <div className="dov-narration">{o.text}</div>}

      {o.type === "final" && (
        <div className="dov-final">
          <div className="dov-final-lines">
            {o.lines.map((l, i) => (
              <div key={l} style={{ animationDelay: `${0.35 + i * 0.85}s` }}>
                {l}
              </div>
            ))}
          </div>
          <div className="dov-final-sub" style={{ animationDelay: `${0.35 + o.lines.length * 0.85 + 0.35}s` }}>
            {o.subtitle}
          </div>
        </div>
      )}
    </div>
  );
}
