import { Icon } from "../ui/Icon";

export function Sidebar({ brand, items, footer }) {
  return (
    <aside className="app-sidebar">
      <div className="app-sidebar-brand">{brand}</div>
      <nav className="app-sidebar-nav">
        {items.map((item) => (
          <button
            key={item.label}
            className={`nav-item ${item.active ? "active" : ""}`}
            onClick={item.onClick}
            type="button"
          >
            <Icon name={item.icon} size={17} />
            <span>{item.label}</span>
            {typeof item.count === "number" && <span className="count">{item.count}</span>}
          </button>
        ))}
      </nav>
      {footer && <div className="app-sidebar-footer">{footer}</div>}
    </aside>
  );
}
