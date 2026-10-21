/**
 * Anneau de repartition -- segments empiles via stroke-dasharray (technique
 * SVG classique, aucune dependance de charting a ajouter au projet). `slices`
 * : [{ label, value, color }], `value` en pourcentage (somme = 100).
 */
export function DonutChart({ slices, centerValue, centerLabel, size = 148, thickness = 20 }) {
  const radius = (size - thickness) / 2;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;

  return (
    <div className="donut-wrap" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label="Répartition des intentions détectées">
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="var(--surface-2)" strokeWidth={thickness} />
        {slices.map((slice) => {
          const dash = (slice.value / 100) * circumference;
          const circle = (
            <circle
              key={slice.label}
              cx={size / 2}
              cy={size / 2}
              r={radius}
              fill="none"
              stroke={slice.color}
              strokeWidth={thickness}
              strokeDasharray={`${dash} ${circumference - dash}`}
              strokeDashoffset={-offset}
              transform={`rotate(-90 ${size / 2} ${size / 2})`}
              strokeLinecap={slices.length > 1 ? "butt" : "round"}
            />
          );
          offset += dash;
          return circle;
        })}
      </svg>
      <div className="donut-center">
        <span className="donut-center-value">{centerValue}</span>
        <span className="donut-center-label">{centerLabel}</span>
      </div>
    </div>
  );
}

export function Sparkline({ values, color, width = 100, height = 28 }) {
  if (values.length < 2) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const step = width / (values.length - 1);
  const points = values.map((v, i) => {
    const x = i * step;
    const y = height - ((v - min) / range) * height;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      <polyline
        points={points.join(" ")}
        fill="none"
        stroke={color}
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function AreaChart({ values, labels, color, height = 180 }) {
  const width = 640;
  const paddingBottom = 22;
  const chartHeight = height - paddingBottom;
  const min = Math.min(...values, 0);
  const max = Math.max(...values);
  const range = max - min || 1;
  const step = width / (values.length - 1);

  const points = values.map((v, i) => {
    const x = i * step;
    const y = chartHeight - ((v - min) / range) * chartHeight;
    return { x, y };
  });

  const linePath = points.map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
  const areaPath = `${linePath} L${points[points.length - 1].x.toFixed(1)},${chartHeight} L0,${chartHeight} Z`;
  const gradientId = "area-fill-gradient";

  return (
    <svg
      width="100%"
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      role="img"
      aria-label="Volume des conversations sur la période"
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.28" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={areaPath} fill={`url(#${gradientId})`} />
      <path d={linePath} fill="none" stroke={color} strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={points[points.length - 1].x} cy={points[points.length - 1].y} r={4} fill={color} />
      {labels.map((label, i) => {
        if (i % Math.ceil(labels.length / 7) !== 0 && i !== labels.length - 1) return null;
        const x = i * step;
        const anchor = i === 0 ? "start" : i === labels.length - 1 ? "end" : "middle";
        return (
          <text key={label + i} x={x} y={height - 4} fontSize="10" fill="var(--ink-faint)" textAnchor={anchor}>
            {label}
          </text>
        );
      })}
    </svg>
  );
}
