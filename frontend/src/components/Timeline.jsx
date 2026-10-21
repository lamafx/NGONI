export function Timeline({ events }) {
  return (
    <div className="timeline-v">
      {events.map((e, i) => (
        <div className="timeline-v-item" key={e.id}>
          <div className="timeline-v-rail">
            <div className={`timeline-v-dot ${e.state}`} />
            {i < events.length - 1 && <div className="timeline-v-line" />}
          </div>
          <div className="timeline-v-content">
            <div className="t-label">{e.label}</div>
            <div className="t-time">{e.time}</div>
          </div>
        </div>
      ))}
    </div>
  );
}
