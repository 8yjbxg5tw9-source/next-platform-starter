/** Küçük sunum bileşenleri. Starter'ın Tailwind temasını kullanır. */

export function Panel({ title, subtitle, children, right }) {
  return (
    <section className="w-full p-6 border rounded-lg bg-neutral-900/60 border-neutral-700">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-xl font-bold text-white">{title}</h3>
          {subtitle ? <p className="mt-1 text-sm text-neutral-400">{subtitle}</p> : null}
        </div>
        {right}
      </div>
      <div className="mt-4">{children}</div>
    </section>
  );
}

export function Stat({ label, value, unit = 'ms', tone = 'default', hint }) {
  const tones = {
    default: 'text-white',
    good: 'text-primary',
    warn: 'text-amber-300',
    bad: 'text-rose-400',
  };
  return (
    <div className="p-3 border rounded bg-neutral-950/60 border-neutral-800">
      <div className="text-[11px] uppercase tracking-wide text-neutral-500">{label}</div>
      <div className={`mt-1 text-2xl font-bold tabular-nums ${tones[tone] || tones.default}`}>
        {value}
        {value !== '—' && value != null ? <span className="ml-1 text-sm font-normal text-neutral-500">{unit}</span> : null}
      </div>
      {hint ? <div className="mt-1 text-[11px] text-neutral-500">{hint}</div> : null}
    </div>
  );
}

export function Btn({ children, onClick, disabled, variant = 'primary', ...rest }) {
  const base = 'px-4 py-2 text-sm font-semibold rounded transition disabled:opacity-40 disabled:cursor-not-allowed';
  const styles = {
    primary: 'bg-primary text-primary-content hover:opacity-90',
    ghost: 'border border-neutral-600 text-neutral-200 hover:bg-neutral-800',
    danger: 'border border-rose-700 text-rose-300 hover:bg-rose-950/40',
  };
  return (
    <button type="button" onClick={onClick} disabled={disabled} className={`${base} ${styles[variant]}`} {...rest}>
      {children}
    </button>
  );
}

export function toneFor(ms) {
  if (ms == null) return 'default';
  if (ms < 45) return 'good';
  if (ms < 80) return 'default';
  if (ms < 130) return 'warn';
  return 'bad';
}

/** El yapımı SVG çizgi grafiği — dışa bağımlılık yok. */
export function Sparkline({ data, height = 64, className = '', color = '#2bdcd2' }) {
  if (!data || data.length < 2) {
    return <div className="text-xs text-neutral-500" style={{ height }}>Henüz yeterli veri yok</div>;
  }
  const w = 600;
  const vals = data.filter((n) => Number.isFinite(n));
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const span = Math.max(1, max - min);
  const pts = data
    .map((v, i) => {
      if (!Number.isFinite(v)) return null;
      const x = (i / (data.length - 1)) * w;
      const y = height - ((v - min) / span) * (height - 8) - 4;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .filter(Boolean)
    .join(' ');
  return (
    <svg viewBox={`0 0 ${w} ${height}`} preserveAspectRatio="none" className={`w-full ${className}`} style={{ height }}>
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export function Badge({ children, tone = 'neutral' }) {
  const tones = {
    neutral: 'border-neutral-700 text-neutral-300',
    good: 'border-primary text-primary',
    warn: 'border-amber-600 text-amber-300',
    bad: 'border-rose-700 text-rose-300',
    info: 'border-sky-700 text-sky-300',
  };
  return (
    <span className={`inline-block px-2 py-0.5 text-[11px] rounded border ${tones[tone] || tones.neutral}`}>{children}</span>
  );
}
