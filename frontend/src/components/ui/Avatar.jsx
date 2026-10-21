import ngoniIcon from "../../assets/ngoni-support-icon.jpeg";

function initials(name) {
  const parts = name.trim().split(/\s+/);
  return parts
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? "")
    .join("");
}

// L'illustration NGONI est un personnage en PIED sur un disque orange :
// affichee entiere dans une pastille de 28 px, elle ne montrait qu'une tache
// minuscule ou le visage faisait trois pixels. C'est ce qui justifiait, avant,
// un monogramme « N » a sa place -- lisible, mais anonyme.
//
// Plutot que de choisir entre les deux, on RECADRE sur la tete : la fenetre
// visible couvre 30 %-70 % de la largeur de l'image et 4 %-44 % de sa hauteur.
// D'ou l'agrandissement a 250 % (100 / 40) et les decalages -75 % / -10 %
// (30 x 2,5 et 4 x 2,5). Le visage remplit alors la pastille a n'importe
// quelle taille, et l'assistant a un vrai visage dans le fil.
const AI_PORTRAIT = {
  position: "absolute",
  width: "250%",
  height: "250%",
  left: "-75%",
  top: "-10%",
  objectFit: "cover",
  // Les feuilles de style contraignent `img` a 100 % dans les pastilles du
  // fil (.ns-msg-avatar img) : les valeurs ci-dessus sont posees en style
  // inline, qui l'emporte, plutot que de dupliquer une exception par
  // emplacement.
  maxWidth: "none",
};

/**
 * Pastille d'identite.
 *
 * `src`  : une vraie photo de profil, quand le compte en porte une. Elle prime
 *          sur tout le reste.
 * `kind` : "ai" pour l'assistant NGONI (illustration recadree, voir plus haut).
 * sinon  : monogramme construit sur les initiales -- le repli normal pour les
 *          comptes sans photo (conseillers, autres usagers).
 */
export function Avatar({ kind, name = "", size = 36, src }) {
  const style = { width: size, height: size };

  if (src) {
    return <img src={src} alt={name || "Utilisateur"} className="avatar" style={style} />;
  }

  if (kind === "ai") {
    return (
      <span
        className="avatar"
        style={{ ...style, position: "relative", overflow: "hidden", display: "inline-block" }}
        aria-label="NGONI IA"
      >
        <img src={ngoniIcon} alt="" style={AI_PORTRAIT} />
      </span>
    );
  }

  return (
    <div className="avatar-mono" style={{ ...style, fontSize: size * 0.4 }} aria-label={name || "Utilisateur"}>
      {initials(name) || "U"}
    </div>
  );
}
