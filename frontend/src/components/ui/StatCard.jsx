import { Sparkline } from "./Sparkline";

export function StatCard({ icon, label, value, delta, positive, compareLabel, trend }) {
  const color = positive ? "var(--good)" : "var(--risk)";
  return (
    <div className="card card-pad stat-card">
      <div className="stat-icon">{icon}</div>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      <div className={`stat-delta ${positive ? "up" : "down"}`}>
        {positive ? "▲" : "▼"} {delta}
        {compareLabel && <span className="stat-compare"> {compareLabel}</span>}
      </div>
      {trend && trend.length > 1 && <Sparkline values={trend} color={color} />}
    </div>
  );
}
