import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { useDemoStore } from "../../state/DemoStore";

const PAGES = [
  { path: "/chat", label: "Chat" },
  { path: "/agent", label: "Espace agent" },
  // Le meme poste conseiller, mais sur les donnees reelles du moteur (file
  // d'attente, prise en charge, reponse humaine) -- voir AgentLivePage.jsx.
  { path: "/agent/live", label: "Espace agent (données réelles)" },
  { path: "/admin", label: "Administration" },
];

// Point de bascule discret entre les trois interfaces de démonstration --
// volontairement peu visible (un simple point, pas une barre "DÉMO") pour
// ne pas casser l'illusion d'un vrai produit pendant une présentation.
export function DiscreetSwitcher() {
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const { dispatch } = useDemoStore();
  const wrapRef = useRef(null);

  useEffect(() => {
    function onPointerDown(e) {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false);
    }
    function onKeyDown(e) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, []);

  const others = PAGES.filter((p) => p.path !== location.pathname);

  return (
    <div className="discreet-switcher" ref={wrapRef}>
      {open && (
        <div className="discreet-switcher-menu" role="menu">
          {others.map((p) => (
            <Link key={p.path} to={p.path} onClick={() => setOpen(false)} role="menuitem">
              {p.label}
            </Link>
          ))}
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              if (confirm("Réinitialiser le scénario de démonstration ?")) {
                dispatch({ type: "RESET" });
              }
              setOpen(false);
            }}
          >
            Réinitialiser le scénario
          </button>
        </div>
      )}
      <button
        type="button"
        className="discreet-switcher-dot"
        aria-label="Basculer entre les interfaces de démonstration"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      />
    </div>
  );
}
