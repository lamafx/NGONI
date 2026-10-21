// Bus d'incrustations de la demonstration.
//
// POURQUOI CE MODULE
// La video ne doit pas etre montee : tout ce qu'un monteur aurait ajoute
// (badges d'intention, bascule d'etat, bandeau de rupture, chiffre dominant,
// carton final) doit apparaitre pendant que la demonstration tourne. Ces
// incrustations vivent au-dessus de l'application, hors du flux des pages,
// et survivent aux bascules chat -> conseiller -> supervision.
//
// Un simple abonnement au niveau du module : pas de contexte React a faire
// traverser trois pages qui se remplacent.

let current = null;
const listeners = new Set();

function emit() {
  listeners.forEach((fn) => fn(current));
}

export function subscribeOverlay(fn) {
  listeners.add(fn);
  fn(current);
  return () => listeners.delete(fn);
}

/**
 * Affiche une incrustation.
 *   type "badge"      { lines: ["INTENT : diagnostic"] }   pastille discrete
 *   type "state"      { before, after }                     bascule d'etat
 *   type "checks"     { items, headline }                   controles + total
 *   type "rupture"    { title, subtitle }                   bandeau plein cadre
 *   type "ticket"     { id, rows }                          carte de ticket
 *   type "stat"       { value, label }                      chiffre dominant
 *   type "narration"  { text }                              une phrase, en bas
 *   type "final"      { lines, subtitle }                   carton de fin
 */
export function showOverlay(overlay) {
  current = overlay ? { ...overlay, key: Date.now() + Math.random() } : null;
  emit();
}

export function clearOverlay() {
  current = null;
  emit();
}
