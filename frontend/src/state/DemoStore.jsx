import { createContext, useContext, useEffect, useMemo, useReducer } from "react";
import { INITIAL_CONVERSATIONS, INITIAL_TICKETS } from "../data/mockData";

const STORAGE_KEY = "ngoni-ia-demo-store-v1";

function initialState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    // `?? {}`/`?? []` : un localStorage ecrit avant l'ajout de ces deux
    // champs (parametres editables, historique) n'en contient pas -- sans
    // ce filet, un ancien visiteur reprendrait un state avec ces cles
    // `undefined`, faisant planter la page Parametres au premier rendu.
    if (raw) {
      const parsed = JSON.parse(raw);
      return { parameterOverrides: {}, parameterHistory: [], ...parsed };
    }
  } catch {
    /* ignore corrupted/unavailable storage, fall back to seed data */
  }
  return { conversations: INITIAL_CONVERSATIONS, tickets: INITIAL_TICKETS, parameterOverrides: {}, parameterHistory: [] };
}

function reducer(state, action) {
  switch (action.type) {
    case "ADD_MESSAGE":
      return {
        ...state,
        conversations: state.conversations.map((c) =>
          c.id === action.conversationId
            ? { ...c, messages: [...c.messages, action.message], updatedAt: "à l'instant" }
            : c
        ),
      };
    case "CLEAR_QUICK_REPLIES":
      return {
        ...state,
        conversations: state.conversations.map((c) =>
          c.id === action.conversationId
            ? { ...c, messages: c.messages.map((m) => ({ ...m, quickReplies: undefined })) }
            : c
        ),
      };
    case "SET_STATUS":
      return {
        ...state,
        conversations: state.conversations.map((c) =>
          c.id === action.conversationId ? { ...c, status: action.status } : c
        ),
      };
    case "SET_TIMELINE":
      return {
        ...state,
        conversations: state.conversations.map((c) =>
          c.id === action.conversationId ? { ...c, timeline: action.timeline } : c
        ),
      };
    case "SET_SUMMARY":
      return {
        ...state,
        conversations: state.conversations.map((c) =>
          c.id === action.conversationId ? { ...c, aiSummary: action.summary } : c
        ),
      };
    case "ASSIGN_AGENT":
      return {
        ...state,
        conversations: state.conversations.map((c) =>
          c.id === action.conversationId ? { ...c, assignedAgent: action.agent } : c
        ),
      };
    case "ADD_TICKET":
      return { ...state, tickets: [action.ticket, ...state.tickets] };
    case "SET_TICKET_STATUS":
      return {
        ...state,
        tickets: state.tickets.map((t) => (t.id === action.ticketId ? { ...t, status: action.status } : t)),
      };
    case "UPDATE_PARAMETER":
      return {
        ...state,
        parameterOverrides: { ...state.parameterOverrides, [action.id]: action.value },
        parameterHistory: [
          {
            id: `hist-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`,
            paramId: action.id,
            label: action.label,
            oldValue: action.oldValue,
            newValue: action.value,
            changedBy: action.changedBy,
            changedAt: action.changedAt,
          },
          ...state.parameterHistory,
        ],
      };
    // Le journal local est le repli quand le moteur ne repond pas : il doit
    // donc pouvoir etre vide, lui aussi, sans quoi une purge cote moteur
    // laisserait des lignes fantomes a l'ecran.
    case "CLEAR_PARAMETER_HISTORY":
      return { ...state, parameterHistory: [] };
    case "RESET":
      return { conversations: INITIAL_CONVERSATIONS, tickets: INITIAL_TICKETS, parameterOverrides: {}, parameterHistory: [] };
    default:
      return state;
  }
}

const DemoContext = createContext(null);

export function DemoStoreProvider({ children }) {
  const [state, dispatch] = useReducer(reducer, undefined, initialState);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch {
      /* storage unavailable (private browsing, quota) -- demo continues in-memory */
    }
  }, [state]);

  const value = useMemo(() => ({ state, dispatch }), [state]);

  return <DemoContext.Provider value={value}>{children}</DemoContext.Provider>;
}

export function useDemoStore() {
  const ctx = useContext(DemoContext);
  if (!ctx) throw new Error("useDemoStore must be used within DemoStoreProvider");
  return ctx;
}
