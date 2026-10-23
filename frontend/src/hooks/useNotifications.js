/**
 * Notifications d'un espace (client, conseiller, administration).
 *
 * Une notification est un objet { id, at, title, body?, tone?, action? }
 * reconstruit a chaque sondage depuis l'etat REEL du moteur (statut d'un
 * ticket, escalade en attente, service en panne...) : aucun stockage cote
 * moteur, aucun evenement invente. L'`id` encode l'etat (ex.
 * « ticket:CMP-1:IN_PROGRESS ») : un nouvel etat = une nouvelle notification.
 *
 * Seul l'etat « lu » est conserve, dans le navigateur (localStorage, par
 * espace). Notifications du systeme (bulle Windows) en option, uniquement
 * quand l'onglet est en arriere-plan -- sinon le panneau suffit.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

const MAX_READ_IDS = 300;

function storageGet(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw === null ? fallback : JSON.parse(raw);
  } catch {
    return fallback;
  }
}

function storageSet(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Stockage indisponible : l'etat « lu » vaut pour cette session seulement.
  }
}

const desktopSupported = typeof window !== "undefined" && "Notification" in window;

export function useNotifications({ scope, load, intervalMs = 20000, enabled = true }) {
  const readKey = `ngoni-notif-read:${scope}`;
  const desktopKey = `ngoni-notif-desktop:${scope}`;
  const [remote, setRemote] = useState([]);
  const [local, setLocal] = useState([]);
  const [readIds, setReadIds] = useState(() => new Set(storageGet(readKey, [])));
  const [error, setError] = useState(null);
  const [loaded, setLoaded] = useState(false);
  const [desktopEnabled, setDesktopEnabled] = useState(
    () => desktopSupported && Notification.permission === "granted" && storageGet(desktopKey, false)
  );

  const loadRef = useRef(load);
  loadRef.current = load;
  const readRef = useRef(readIds);
  readRef.current = readIds;
  const desktopRef = useRef(desktopEnabled);
  desktopRef.current = desktopEnabled;
  // Identifiants deja vus : une bulle systeme seulement pour ce qui APPARAIT,
  // jamais pour l'etat trouve au chargement de la page.
  const seenRef = useRef(null);

  const announce = useCallback((fresh) => {
    if (!fresh.length || !desktopRef.current || !document.hidden) return;
    try {
      const first = fresh[0];
      const extra = fresh.length > 1 ? ` (+${fresh.length - 1})` : "";
      new Notification(`Ngoni Support — ${first.title}${extra}`, { body: first.body ?? "", tag: `ngoni-${scope}` });
    } catch {
      // Certains navigateurs refusent le constructeur hors service worker.
    }
  }, [scope]);

  const refresh = useCallback(async () => {
    try {
      const next = await loadRef.current();
      setRemote(next);
      setError(null);
      setLoaded(true);
      if (seenRef.current) {
        announce(next.filter((n) => !seenRef.current.has(n.id) && !readRef.current.has(n.id)));
      }
      seenRef.current = new Set(next.map((n) => n.id));
    } catch (err) {
      console.error(`[notifications:${scope}]`, err);
      setError("Notifications indisponibles (service injoignable).");
      setLoaded(true);
    }
  }, [scope, announce]);

  useEffect(() => {
    if (!enabled) return undefined;
    refresh();
    const timer = setInterval(refresh, intervalMs);
    return () => clearInterval(timer);
  }, [enabled, refresh, intervalMs]);

  const items = useMemo(() => {
    const byId = new Map();
    [...local, ...remote].forEach((n) => byId.set(n.id, n));
    return [...byId.values()].sort((a, b) => String(b.at ?? "").localeCompare(String(a.at ?? "")));
  }, [local, remote]);

  const unreadCount = items.filter((n) => !readIds.has(n.id)).length;

  const persistRead = useCallback(
    (next) => {
      setReadIds(next);
      storageSet(readKey, [...next].slice(-MAX_READ_IDS));
    },
    [readKey]
  );

  const markRead = useCallback(
    (id) => {
      if (readRef.current.has(id)) return;
      persistRead(new Set([...readRef.current, id]));
    },
    [persistRead]
  );

  const markAllRead = useCallback(() => {
    persistRead(new Set([...readRef.current, ...items.map((n) => n.id)]));
  }, [persistRead, items]);

  /** Notification nee dans la page (ex. message d'un conseiller recu par le
   *  sondage du chat) plutot que d'un appel au moteur. */
  const push = useCallback(
    (notification) => {
      setLocal((prev) => (prev.some((n) => n.id === notification.id) ? prev : [notification, ...prev].slice(0, 30)));
      announce([notification]);
    },
    [announce]
  );

  const toggleDesktop = useCallback(async () => {
    if (!desktopSupported) return;
    if (desktopRef.current) {
      setDesktopEnabled(false);
      storageSet(desktopKey, false);
      return;
    }
    const permission =
      Notification.permission === "granted" ? "granted" : await Notification.requestPermission();
    const on = permission === "granted";
    setDesktopEnabled(on);
    storageSet(desktopKey, on);
  }, [desktopKey]);

  return {
    items,
    unreadCount,
    isUnread: (id) => !readIds.has(id),
    markRead,
    markAllRead,
    push,
    refresh,
    error,
    // Desactive (ex. chat en demonstration) : rien a attendre.
    loaded: loaded || !enabled,
    desktop: {
      supported: desktopSupported,
      enabled: desktopEnabled,
      denied: desktopSupported && Notification.permission === "denied",
      toggle: toggleDesktop,
    },
  };
}
