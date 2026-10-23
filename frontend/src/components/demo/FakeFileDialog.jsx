import { forwardRef } from "react";
import "../../styles/fakeFileDialog.css";

/**
 * Fenetre « Open » de Windows 11, reproduite dans la page pour la video
 * tournee sans ecran (?demo=1&auto=1, voir autoAttachDocument dans
 * ChatPage). La vraie fenetre de fichiers n'existe que sur un bureau reel :
 * un Chrome sans affichage ne peut pas la montrer.
 *
 * Modele : la fenetre telle qu'elle apparait dans la prise manuelle
 * (Memoire/demovideo.mp4, 0:30) -- Windows en anglais, theme sombre, grandes
 * icones, ouverte en haut a gauche de la page. Ce qu'elle affiche est VRAI :
 * le chemin et le contenu du dossier demo/ du depot, filtre comme le ferait
 * le selecteur (images seulement, voir l'attribut `accept` du champ
 * fichier). Seule entorse : le nom du compte OneDrive est retire du volet de
 * navigation.
 *
 * Un decor, comme DemoCursor : elle ne pilote rien. Les refs exposent les
 * deux cibles du curseur (le fichier, le bouton Ouvrir).
 */

// C:/DEV/NGONI/ngoni-ia-service/demo. Comme Windows quand la barre d'adresse
// est trop etroite : le debut du chemin (This PC > Local Disk (C:)) se replie
// derriere « », la fin reste lisible.
const CHEMIN = ["DEV", "NGONI", "ngoni-ia-service", "demo"];

const NAVIGATION = [
  { label: "Home", icon: "home" },
  { label: "Gallery", icon: "gallery" },
  { label: "OneDrive - Personal", icon: "cloud", expand: true },
  null,
  { label: "Desktop", icon: "desktop", pinned: true },
  { label: "DEV", icon: "folder", pinned: true },
  { label: "Downloads", icon: "download", pinned: true },
  { label: "Documents", icon: "docs", pinned: true },
  { label: "Pictures", icon: "pictures", pinned: true },
  { label: "Music", icon: "music", pinned: true },
  { label: "Videos", icon: "videos", pinned: true },
  null,
  { label: "This PC", icon: "pc", expand: true },
  { label: "Network", icon: "network", expand: true },
];

function NavIcon({ name }) {
  const common = { width: 16, height: 16, viewBox: "0 0 16 16", fill: "none", "aria-hidden": true };
  switch (name) {
    case "home":
      return (
        <svg {...common}>
          <path d="M2.5 7.2 8 2.6l5.5 4.6V13a.6.6 0 0 1-.6.6H9.6V10H6.4v3.6H3.1a.6.6 0 0 1-.6-.6V7.2Z" stroke="#4f6bed" strokeWidth="1.2" />
        </svg>
      );
    case "gallery":
      return (
        <svg {...common}>
          <rect x="2" y="3" width="12" height="10" rx="1.6" stroke="#3d8bd6" strokeWidth="1.2" />
          <path d="m3.5 11.5 3-3 2 2 1.6-1.6 2.4 2.6" stroke="#3d8bd6" strokeWidth="1.2" />
        </svg>
      );
    case "desktop":
      return (
        <svg {...common}>
          <rect x="1.8" y="2.8" width="12.4" height="8.4" rx="1" fill="#3c9be6" />
          <path d="M6 13.6h4" stroke="#6b6b6b" strokeWidth="1.3" strokeLinecap="round" />
        </svg>
      );
    case "download":
      return (
        <svg {...common}>
          <path d="M8 2.5v8m0 0L4.8 7.3M8 10.5l3.2-3.2M3 13.5h10" stroke="#2c8a4c" strokeWidth="1.4" strokeLinecap="round" />
        </svg>
      );
    case "docs":
      return (
        <svg {...common}>
          <path d="M4 1.8h5.3L12.5 5v9.2H4V1.8Z" fill="#fff" stroke="#6d7bb5" strokeWidth="1.1" />
          <path d="M5.8 8h4.8M5.8 10.2h4.8" stroke="#6d7bb5" strokeWidth="1" />
        </svg>
      );
    case "pictures":
      return (
        <svg {...common}>
          <rect x="2" y="3" width="12" height="10" rx="1.2" fill="#55a9e8" />
          <path d="m3 12 3.2-3.4 2.2 2.2 1.7-1.5L13 12" fill="#2f7bc0" />
          <circle cx="10.8" cy="5.8" r="1.1" fill="#ffd55c" />
        </svg>
      );
    case "music":
      return (
        <svg {...common}>
          <path d="M6 12V3.6l6-1.2V11" stroke="#e5571f" strokeWidth="1.3" />
          <circle cx="4.6" cy="12" r="1.6" fill="#e5571f" />
          <circle cx="10.6" cy="11" r="1.6" fill="#e5571f" />
        </svg>
      );
    case "videos":
      return (
        <svg {...common}>
          <rect x="1.8" y="3.4" width="12.4" height="9.2" rx="1.2" fill="#8a57d6" />
          <path d="M6.6 6v4l3.4-2-3.4-2Z" fill="#fff" />
        </svg>
      );
    case "cloud":
      return (
        <svg {...common}>
          <path d="M4.6 12.4h7.3a2.6 2.6 0 0 0 .3-5.2 3.6 3.6 0 0 0-6.9-.9 2.9 2.9 0 0 0-.7 6.1Z" fill="#3c9be6" />
        </svg>
      );
    case "folder":
      return <FolderIcon size={16} />;
    case "pc":
      return (
        <svg {...common}>
          <rect x="1.8" y="2.6" width="12.4" height="8.6" rx="1" fill="#3c9be6" stroke="#2470b3" strokeWidth=".8" />
          <path d="M5 13.6h6M8 11.2v2.4" stroke="#6b6b6b" strokeWidth="1.2" strokeLinecap="round" />
        </svg>
      );
    default:
      return (
        <svg {...common}>
          <path d="M2.2 9.5a5.8 5.8 0 0 1 11.6 0M4.6 9.5a3.4 3.4 0 0 1 6.8 0" stroke="#3d8bd6" strokeWidth="1.2" />
          <circle cx="8" cy="10.6" r="1.2" fill="#3d8bd6" />
        </svg>
      );
  }
}

function Chevron({ dir = "right", size = 10 }) {
  const d = { right: "M3.5 1.5 7 5 3.5 8.5", left: "M6.5 1.5 3 5l3.5 3.5", up: "M1.5 6.5 5 3l3.5 3.5", down: "M1.5 3.5 5 7l3.5-3.5" }[dir];
  return (
    <svg width={size} height={size} viewBox="0 0 10 10" fill="none" aria-hidden="true">
      <path d={d} stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function FolderIcon({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true">
      <path d="M1.5 4a1 1 0 0 1 1-1h3.6l1.4 1.4h6a1 1 0 0 1 1 1V12a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1V4Z" fill="#f4bf4f" />
      <path d="M1.5 6h13v6a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1V6Z" fill="#ffd767" />
    </svg>
  );
}

/**
 * files    : [{ name, thumb, ref? }] -- dans l'ordre d'affichage.
 * selected : nom du fichier selectionne (surbrillance + champ « Nom du fichier »).
 */
export const FakeFileDialog = forwardRef(function FakeFileDialog({ files, selected, openRef }, rootRef) {
  return (
    <div className="wfd-layer" aria-hidden="true">
      <div className="wfd" ref={rootRef}>
        <div className="wfd-title">
          <span className="wfd-title-icon">
            <FolderIcon size={14} />
          </span>
          <span>Open</span>
          <span className="wfd-title-close">
            <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
              <path d="M1 1l8 8M9 1 1 9" stroke="currentColor" strokeWidth="1" />
            </svg>
          </span>
        </div>

        <div className="wfd-nav">
          <span className="wfd-nav-btn"><Chevron dir="left" size={12} /></span>
          <span className="wfd-nav-btn is-disabled"><Chevron dir="right" size={12} /></span>
          <span className="wfd-nav-btn"><Chevron dir="up" size={12} /></span>
          <div className="wfd-address">
            <span className="wfd-address-icon"><FolderIcon size={15} /></span>
            <span className="wfd-crumb wfd-crumb-fold">«</span>
            {CHEMIN.map((part) => (
              <span key={part} className="wfd-crumb">
                <Chevron size={8} />
                <span>{part}</span>
              </span>
            ))}
            <span className="wfd-address-end"><Chevron dir="down" size={9} /></span>
          </div>
          <div className="wfd-search">
            <span>Search demo</span>
            <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <circle cx="6.6" cy="6.6" r="4.6" stroke="currentColor" strokeWidth="1.3" />
              <path d="m10.2 10.2 4 4" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
            </svg>
          </div>
        </div>

        <div className="wfd-cmd">
          <span className="wfd-cmd-item">Organize <Chevron dir="down" size={8} /></span>
          <span className="wfd-cmd-item">New folder</span>
          <span className="wfd-cmd-spacer" />
          <span className="wfd-cmd-item wfd-cmd-icon">
            <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true">
              <rect x="2" y="2" width="5" height="5" rx="1" fill="currentColor" />
              <rect x="9" y="2" width="5" height="5" rx="1" fill="currentColor" />
              <rect x="2" y="9" width="5" height="5" rx="1" fill="currentColor" />
              <rect x="9" y="9" width="5" height="5" rx="1" fill="currentColor" />
            </svg>
            <Chevron dir="down" size={8} />
          </span>
          <span className="wfd-cmd-item wfd-cmd-icon">
            <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true">
              <rect x="2" y="2.5" width="12" height="11" rx="1.5" fill="none" stroke="currentColor" strokeWidth="1.2" />
              <path d="M9.5 2.5v11" stroke="currentColor" strokeWidth="1.2" />
            </svg>
          </span>
          <span className="wfd-cmd-help">?</span>
        </div>

        <div className="wfd-body">
          <nav className="wfd-side">
            {NAVIGATION.map((item, i) =>
              item ? (
                <div key={item.label} className="wfd-side-item">
                  <span className="wfd-side-chevron">{item.expand ? <Chevron size={8} /> : null}</span>
                  <NavIcon name={item.icon} />
                  <span className="wfd-side-label">{item.label}</span>
                  {item.pinned && (
                    <svg className="wfd-pin" width="11" height="11" viewBox="0 0 16 16" aria-hidden="true">
                      <path d="M9.6 1.8 14.2 6.4l-1.6.4-2.4 2.4.3 3.1-1.3 1.3-2.7-2.7-3.6 3.6-.6-.6 3.6-3.6L3.2 7.6l1.3-1.3 3.1.3L10 4.2l-.4-2.4Z" fill="currentColor" />
                    </svg>
                  )}
                </div>
              ) : (
                <div key={`sep-${i}`} className="wfd-side-sep" />
              ),
            )}
          </nav>

          <div className="wfd-files">
            {files.map((file) => (
              <div
                key={file.name}
                ref={file.ref}
                className={`wfd-file${selected === file.name ? " is-selected" : ""}`}
              >
                <span className="wfd-thumb">
                  <img src={file.thumb} alt="" />
                </span>
                <span className="wfd-file-name">{file.name}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="wfd-foot">
          <div className="wfd-foot-row">
            <span className="wfd-foot-label">File name:</span>
            <span className="wfd-field">
              <span>{selected ?? ""}</span>
              <Chevron dir="down" size={9} />
            </span>
            <span className="wfd-field wfd-field-type">
              <span>Custom Files (*.tif;*.jfif;*.pjp;*.aj…</span>
              <Chevron dir="down" size={9} />
            </span>
          </div>
          <div className="wfd-foot-row wfd-foot-actions">
            <span className="wfd-btn wfd-btn-split" ref={openRef}>
              <span>Open</span>
              <span className="wfd-btn-split-arrow"><Chevron dir="down" size={8} /></span>
            </span>
            <span className="wfd-btn">Cancel</span>
          </div>
        </div>
      </div>
    </div>
  );
});
