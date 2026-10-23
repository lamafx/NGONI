/**
 * Petits elements partages par les pages d'administration branchees sur le
 * moteur (Conversations, Demandes, Diagnostics, Agents) : etats de
 * chargement/erreur, tuiles de chiffres, formats de date.
 */

export function relativeLabel(iso) {
  if (!iso) return "—";
  const elapsedMs = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(elapsedMs)) return "—";
  const minutes = Math.floor(elapsedMs / 60000);
  if (minutes < 1) return "à l'instant";
  if (minutes < 60) return `il y a ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `il y a ${hours} h`;
  return `il y a ${Math.floor(hours / 24)} j`;
}

export function dateLabel(iso) {
  if (!iso) return "—";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "—";
  return at.toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function percent(ratio) {
  if (ratio === null || ratio === undefined) return "—";
  return `${(ratio * 100).toFixed(1).replace(".", ",")} %`;
}

export function LoadState({ error, loading, empty, emptyText }) {
  if (error) {
    return (
      <span className="status-line">
        <span className="status-dot" style={{ background: "var(--risk)" }} /> {error}
      </span>
    );
  }
  if (loading) {
    return (
      <span className="status-line">
        <span className="status-dot online" /> Chargement…
      </span>
    );
  }
  if (empty) return <p className="empty-hint">{emptyText}</p>;
  return null;
}

export function Kpi({ label, value, sub, tone }) {
  return (
    <div className="card card-pad">
      <div style={{ fontSize: "0.78rem", color: "var(--ink-muted)", fontWeight: 600 }}>{label}</div>
      <div
        style={{
          fontSize: "1.6rem",
          fontWeight: 800,
          marginTop: 6,
          color: tone === "risk" ? "var(--risk)" : tone === "good" ? "var(--good)" : "var(--ink)",
        }}
      >
        {value}
      </div>
      {sub && <div style={{ fontSize: "0.76rem", color: "var(--ink-faint)", marginTop: 4 }}>{sub}</div>}
    </div>
  );
}

export function Toolbar({ children }) {
  return <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>{children}</div>;
}

export function Select({ value, onChange, options, label }) {
  return (
    <label style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: "0.8rem", color: "var(--ink-muted)" }}>
      {label}
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        style={{
          padding: "7px 10px",
          borderRadius: 10,
          border: "1px solid var(--line)",
          background: "var(--surface)",
          color: "var(--ink)",
          fontFamily: "inherit",
          fontSize: "0.82rem",
        }}
      >
        {options.map(([optionValue, optionLabel]) => (
          <option key={optionValue} value={optionValue}>
            {optionLabel}
          </option>
        ))}
      </select>
    </label>
  );
}

export const CONVERSATION_STATUS = {
  BOT: { label: "Assistant", tone: "badge-neutral" },
  ESCALADE_DEMANDEE: { label: "En attente", tone: "badge-warn" },
  PRISE_EN_CHARGE: { label: "Prise en charge", tone: "badge-brand" },
  RESOLUE: { label: "Résolue", tone: "badge-good" },
};

export const TICKET_STATUS = {
  OPEN: { label: "Ouverte", tone: "badge-warn" },
  IN_PROGRESS: { label: "En cours", tone: "badge-brand" },
  RESOLVED: { label: "Résolue", tone: "badge-good" },
  CLOSED: { label: "Clôturée", tone: "badge-neutral" },
};

export function Badge({ map, value }) {
  const entry = map[value] ?? { label: value ?? "—", tone: "badge-neutral" };
  return (
    <span className={`badge ${entry.tone}`}>
      <span className="badge-dot" />
      {entry.label}
    </span>
  );
}
