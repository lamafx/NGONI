/**
 * Cloche + panneau de notifications, commun aux espaces client, conseiller et
 * administration. Les donnees viennent de useNotifications (voir
 * hooks/useNotifications.js) ; ce composant ne fait qu'afficher et router.
 *
 * `buttonClassName` / `badgeClassName` : la cloche garde l'apparence propre a
 * chaque espace (theme du chat ou theme Agent/Admin).
 */

import { useEffect, useRef, useState } from "react";
import { Icon } from "./Icon";

function relativeLabel(iso) {
  if (!iso) return "";
  const elapsedMs = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(elapsedMs)) return "";
  const minutes = Math.floor(elapsedMs / 60000);
  if (minutes < 1) return "à l'instant";
  if (minutes < 60) return `il y a ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `il y a ${hours} h`;
  return `il y a ${Math.floor(hours / 24)} j`;
}

const TONE_ICON = {
  risk: "alert",
  warn: "clock",
  good: "check-circle",
  info: "message",
};

export function NotificationBell({
  notifications,
  onSelect,
  buttonClassName = "btn btn-ghost btn-icon",
  badgeClassName = "notif-count",
  iconSize = 18,
  emptyText = "Aucune notification.",
  align = "right",
}) {
  const { items, unreadCount, isUnread, markRead, markAllRead, error, loaded, desktop } = notifications;
  const [open, setOpen] = useState(false);
  const rootRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    function onClickOutside(event) {
      if (rootRef.current && !rootRef.current.contains(event.target)) setOpen(false);
    }
    function onKey(event) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClickOutside);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  function select(item) {
    markRead(item.id);
    setOpen(false);
    onSelect?.(item);
  }

  return (
    <div className="notif-root" ref={rootRef}>
      <button
        type="button"
        className={buttonClassName}
        style={{ position: "relative" }}
        aria-label={unreadCount ? `Notifications : ${unreadCount} non lue(s)` : "Notifications"}
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <Icon name="bell" size={iconSize} />
        {unreadCount > 0 && <span className={badgeClassName}>{unreadCount > 9 ? "9+" : unreadCount}</span>}
      </button>

      {open && (
        <div className={`notif-panel notif-panel-${align}`} role="dialog" aria-label="Notifications">
          <div className="notif-head">
            <strong>Notifications</strong>
            {unreadCount > 0 && (
              <button type="button" className="notif-link" onClick={markAllRead}>
                Tout marquer comme lu
              </button>
            )}
          </div>

          <div className="notif-list">
            {error && <div className="notif-empty">{error}</div>}
            {!error && !loaded && <div className="notif-empty">Chargement…</div>}
            {!error && loaded && items.length === 0 && <div className="notif-empty">{emptyText}</div>}
            {items.map((item) => (
              <button
                key={item.id}
                type="button"
                className={`notif-item ${isUnread(item.id) ? "is-unread" : ""} notif-tone-${item.tone ?? "info"}`}
                onClick={() => select(item)}
              >
                <span className="notif-icon">
                  <Icon name={TONE_ICON[item.tone] ?? "bell"} size={15} />
                </span>
                <span className="notif-text">
                  <span className="notif-title">{item.title}</span>
                  {item.body && <span className="notif-body">{item.body}</span>}
                  <span className="notif-time">{relativeLabel(item.at)}</span>
                </span>
                {isUnread(item.id) && <span className="notif-dot" aria-label="non lue" />}
              </button>
            ))}
          </div>

          {desktop?.supported && (
            <div className="notif-foot">
              {desktop.denied ? (
                <span>Notifications du navigateur bloquées (réglages du site).</span>
              ) : (
                <label className="notif-toggle">
                  <input type="checkbox" checked={desktop.enabled} onChange={desktop.toggle} />
                  M'avertir aussi quand l'onglet est en arrière-plan
                </label>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
