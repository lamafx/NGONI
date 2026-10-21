import { useCallback, useRef, useState } from "react";

/**
 * Outillage commun aux actes filmes hors du chat (espace conseiller,
 * supervision) : un curseur simule qui se deplace et clique.
 *
 * Aucun effet de zoom : la scene reste a l'echelle 1. Ce qui guide le
 * spectateur, c'est le deplacement du curseur, la legende en bas d'ecran et,
 * sur les pages qui defilent, l'amenee de la zone au centre de l'ecran.
 *
 * Le curseur vit DANS la scene, en position absolue : c'est ce qui permet de
 * calculer ses coordonnees a partir des elements cibles sans se soucier du
 * defilement de la page.
 */
export function useDemoStage() {
  const stageRef = useRef(null);
  const [cursor, setCursor] = useState({ x: 0, y: 0, visible: false, clicking: false });

  /** Coordonnees du centre d'un element dans le repere de la scene. */
  const pointOf = useCallback((el) => {
    const stage = stageRef.current;
    if (!stage || !el) return null;
    const r = el.getBoundingClientRect();
    const s = stage.getBoundingClientRect();
    return {
      x: r.left + r.width / 2 - s.left,
      y: r.top + r.height / 2 - s.top,
    };
  }, []);

  /** Deplace le curseur sur un element -- la transition CSS fait le trajet. */
  const moveCursorTo = useCallback((el) => {
    const p = pointOf(el);
    if (!p) return;
    setCursor((c) => ({ ...c, x: p.x, y: p.y, visible: true }));
  }, [pointOf]);

  const hideCursor = useCallback(() => {
    setCursor((c) => ({ ...c, visible: false }));
  }, []);

  /** Anime un clic. Le declenchement de l'action reste a l'appelant : le
   *  curseur est un decor, il ne pilote rien. */
  const clickCursor = useCallback(async (durationMs = 260) => {
    setCursor((c) => ({ ...c, clicking: true }));
    await new Promise((r) => setTimeout(r, durationMs));
    setCursor((c) => ({ ...c, clicking: false }));
  }, []);

  return { stageRef, cursor, moveCursorTo, hideCursor, clickCursor, pointOf };
}

/** Curseur simule. A rendre A L'INTERIEUR de la scene. */
export function DemoCursor({ cursor }) {
  if (!cursor?.visible) return null;
  return (
    <div
      className={`demo-cursor ${cursor.clicking ? "is-clicking" : ""}`}
      style={{ transform: `translate(${cursor.x}px, ${cursor.y}px)` }}
      aria-hidden="true"
    >
      <svg width="22" height="26" viewBox="0 0 22 26" fill="none">
        <path
          d="M3 2.2 18.3 12.4l-6.6.9-3.5 6.1L3 2.2Z"
          fill="#fff"
          stroke="#1b1b1b"
          strokeWidth="1.6"
          strokeLinejoin="round"
        />
      </svg>
    </div>
  );
}
