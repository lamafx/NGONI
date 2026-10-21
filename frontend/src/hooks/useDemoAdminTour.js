import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { adminAct, currentAct, isDemoMode, setAct } from "../services/demoDirector";

/**
 * Parcours automatique de l'espace administration pendant la demonstration :
 * tableau de bord, puis statistiques, puis configuration.
 *
 * Chaque page appelle ce crochet avec SON chemin. Si c'est son tour, elle est
 * parcourue de haut en bas puis passe la main a la suivante -- l'etape
 * courante vit au niveau du module, donc elle survit aux changements de page.
 *
 * Un ecran peut aussi etre MANIPULE plutot que simplement parcouru : il passe
 * alors une fonction `script` en second argument (voir AdminSettingsPage, ou
 * un seuil est modifie puis retrouve dans le journal). Sa duree est celle de
 * la scene, pas un `hold` fixe.
 *
 * React.StrictMode monte deux fois en developpement : le depart est differe
 * d'un tick pour que le nettoyage du premier montage l'annule, et que seul le
 * second arme reellement la suite.
 */
let tourIndex = 0;

export function resetAdminTour() {
  tourIndex = 0;
}

/**
 * Fait defiler lentement une page de haut en bas.
 *
 * Une page qui reste figee douze secondes ressemble a une capture d'ecran ;
 * en la parcourant, on montre qu'il y a du contenu sous la ligne de
 * flottaison. Le defilement part lentement, accelere au milieu et ralentit a
 * l'arrivee -- comme une molette qu'on pousse, pas comme un saut.
 *
 * La hauteur n'est pas mesuree une fois pour toutes : les pages branchees sur
 * le moteur (statistiques) s'allongent quand leurs donnees arrivent, et une
 * mesure prise trop tot conclurait qu'il n'y a rien a parcourir. On reessaie
 * donc jusqu'a `maxWaitMs` avant d'abandonner -- c'est ce qui manquait pour
 * que la page Statistiques defile elle aussi.
 */
function autoScroll(el, duration, state, { maxWaitMs = 6000, pollMs = 500 } = {}) {
  if (!el || state.cancelled) return;

  const waitedFrom = performance.now();
  const start = () => {
    if (state.cancelled) return;
    const max = el.scrollHeight - el.clientHeight;
    if (max <= 8) {
      if (performance.now() - waitedFrom < maxWaitMs) {
        state.timers.push(setTimeout(start, pollMs));
      }
      return;
    }

    const started = performance.now();
    const step = (now) => {
      if (state.cancelled) return;
      const p = Math.min(1, (now - started) / duration);
      const eased = p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2;
      // La hauteur est relue a chaque image : si une carte arrive en cours de
      // route, le parcours va jusqu'en bas de la page reelle, pas jusqu'au bas
      // qu'elle avait au depart.
      el.scrollTop = (el.scrollHeight - el.clientHeight) * eased;
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  };
  start();
}

export function useDemoAdminTour(path, script) {
  const navigate = useNavigate();

  useEffect(() => {
    if (!isDemoMode() || currentAct() !== "admin") return;

    const tour = adminAct().tour;
    const step = tour[tourIndex];
    if (!step || step.path !== path) return;

    const state = { cancelled: false, timers: [] };

    function advance() {
      if (state.cancelled) return;
      tourIndex += 1;
      const next = tour[tourIndex];
      if (next) navigate(next.path);
      else setAct("done");
    }

    state.timers.push(
      setTimeout(() => {
        // Le defilement demarre apres un temps de lecture du haut de page, et
        // une fois les donnees du moteur arrivees : mesurer la hauteur trop
        // tot donnerait celle de l'ecran de chargement.
        const settle = step.settle ?? 1500;

        if (step.script) {
          // Ecran manipule : la scene mene la danse et rend la main quand elle
          // a fini. Si la page n'a pas fourni de script (montage partiel,
          // rechargement), on ne bloque pas le parcours.
          state.timers.push(
            setTimeout(() => {
              if (state.cancelled) return;
              if (typeof script !== "function") return advance();
              Promise.resolve(script(state)).then(() => {
                if (!state.cancelled) advance();
              });
            }, settle)
          );
          return;
        }

        state.timers.push(
          setTimeout(() => {
            if (state.cancelled) return;
            autoScroll(
              document.querySelector(".admin-main"),
              step.scrollMs ?? Math.max(2200, step.hold - settle - 1400),
              state
            );
          }, settle)
        );

        state.timers.push(setTimeout(advance, step.hold));
      }, 0)
    );

    return () => {
      state.cancelled = true;
      state.timers.forEach(clearTimeout);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path]);
}
