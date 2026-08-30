'use client';

import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import { PRIMARY_TARGET_ID, targetById } from './targets';
import { probeOnce } from './probe';
import { fmt, hourBuckets, summarize } from './stats';
import { Badge, Btn, Panel, Sparkline, Stat, toneFor } from './ui';
import { appendWatch, clearWatch, getWatchServerSnapshot, getWatchSnapshot, subscribeWatch } from './store';

const INTERVAL_MS = 5000;

/**
 * Nöbet modu: 5 saniyede bir Frankfurt'u yoklar ve localStorage'a yazar.
 * 24 saat açık bırak → hangi saatlerde hattın iyi olduğunu veriyle görürsün.
 * Antrenman saatini buna göre sabitlemek, pahalı bir VPN'den daha çok işe yarar.
 */
export default function Watch() {
  const [running, setRunning] = useState(false);
  const [last, setLast] = useState(null);
  const prevRef = useRef(null);
  const timerRef = useRef(null);

  const entries = useSyncExternalStore(subscribeWatch, getWatchSnapshot, getWatchServerSnapshot);

  useEffect(() => () => clearInterval(timerRef.current), []);

  useEffect(() => {
    if (!running) {
      clearInterval(timerRef.current);
      return undefined;
    }
    const target = targetById(PRIMARY_TARGET_ID);
    const tick = async () => {
      const r = await probeOnce(target);
      const now = Date.now();
      if (r.ok) {
        const dt = prevRef.current != null ? Math.abs(r.ms - prevRef.current) : undefined;
        prevRef.current = r.ms;
        setLast({ t: now, ms: r.ms });
        appendWatch([{ t: now, ms: r.ms, dt }]);
      } else {
        setLast({ t: now, ms: null });
      }
    };
    tick();
    timerRef.current = setInterval(tick, INTERVAL_MS);
    return () => clearInterval(timerRef.current);
  }, [running]);

  const stats = useMemo(() => summarize(entries.filter((e) => e.ms != null).map((e) => e.ms), 0), [entries]);
  const buckets = useMemo(() => hourBuckets(entries.filter((e) => e.ms != null)), [entries]);
  const recent = useMemo(() => entries.slice(-120).map((e) => e.ms), [entries]);
  const worstHour = useMemo(() => {
    let idx = null;
    let best = Infinity;
    buckets.forEach((b, i) => {
      if (b.avg != null && b.avg < best && b.count >= 3) {
        best = b.avg;
        idx = i;
      }
    });
    return idx == null ? null : { hour: idx, avg: best, count: buckets[idx].count };
  }, [buckets]);
  const maxAvg = Math.max(1, ...buckets.map((b) => b.avg || 0));

  function exportJson() {
    const blob = new Blob([JSON.stringify(entries, null, 0)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `pinglab-watch-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  function importJson(file) {
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const parsed = JSON.parse(String(reader.result));
        if (Array.isArray(parsed)) appendWatch(parsed);
      } catch {
        /* geçersiz dosya */
      }
    };
    reader.readAsText(file);
  }

  const span = entries.length > 1 ? (entries[entries.length - 1].t - entries[0].t) / 3600000 : 0;

  return (
    <div className="space-y-4">
      <Panel
        title="2. Nöbet — 24 saatlik gözlem"
        subtitle="Sekmeyi açık bırak, 5 saniyede bir ölçsün. Sonra hangi saat diliminde düşük ping aldığını gör."
        right={
          <Btn variant={running ? 'danger' : 'primary'} onClick={() => setRunning((r) => !r)}>
            {running ? 'Durdur' : 'Nöbeti başlat'}
          </Btn>
        }
      >
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Son ölçüm" value={last && last.ms != null ? fmt(last.ms) : '—'} tone={toneFor(last && last.ms)} />
          <Stat label="Toplam ortalama" value={fmt(stats.avg)} hint={`${stats.n} örnek`} />
          <Stat label="En kötü" value={fmt(stats.max)} tone={toneFor(stats.max)} />
          <Stat label="Kapsanan süre" value={fmt(span, 1)} unit="saat" />
        </div>

        <div className="mt-4">
          <div className="text-xs uppercase tracking-wide text-neutral-500">Son 120 ölçüm</div>
          <Sparkline data={recent} height={80} />
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          <Btn variant="ghost" onClick={exportJson} disabled={!entries.length}>JSON indir</Btn>
          <label className="px-4 py-2 text-sm font-semibold rounded border border-neutral-600 text-neutral-200 hover:bg-neutral-800 cursor-pointer">
            JSON yükle
            <input type="file" accept="application/json" className="hidden" onChange={(e) => e.target.files?.[0] && importJson(e.target.files[0])} />
          </label>
          <Btn variant="danger" onClick={() => clearWatch()} disabled={!entries.length}>Veriyi sıfırla</Btn>
        </div>
      </Panel>

      {worstHour ? (
        <Panel title="En iyi saat dilimin">
          <p className="text-sm text-neutral-300">
            <Badge tone="good">öneri</Badge> {String(worstHour.hour).padStart(2, '0')}:00 civarında ortalaman{' '}
            <span className="text-primary font-semibold">{fmt(worstHour.avg)} ms</span> ({worstHour.count} örnek).
            Antrenman ve sıralama maçlarını bu pencereye sabitle. En az {24} saat veri biriktirirsen bu tablo
            çok daha güvenilir olur.
          </p>
        </Panel>
      ) : null}

      <Panel title="Saat bazlı ısı haritası" subtitle="Her sütun bir saat. Uzun olan = yüksek ping. Boş olan = veri yok.">
        <div className="flex items-end gap-1" style={{ height: 140 }}>
          {buckets.map((b, i) => {
            const h = b.avg ? (b.avg / maxAvg) * 120 : 0;
            const tone = b.avg == null ? 'bg-neutral-800' : b.avg < 45 ? 'bg-primary' : b.avg < 80 ? 'bg-sky-500' : b.avg < 130 ? 'bg-amber-400' : 'bg-rose-500';
            return (
              <div key={i} className="flex-1 flex flex-col items-center justify-end gap-1" title={`${String(i).padStart(2, '0')}:00 — ${b.avg != null ? `${fmt(b.avg)} ms (${b.count} örnek)` : 'veri yok'}`}>
                <div className={`w-full rounded-t ${tone}`} style={{ height: Math.max(2, h) }} />
                <div className="text-[9px] text-neutral-500 tabular-nums">{i % 3 === 0 ? i : ''}</div>
              </div>
            );
          })}
        </div>
        <div className="mt-3 flex flex-wrap gap-3 text-[11px] text-neutral-500">
          <span><i className="inline-block w-2.5 h-2.5 rounded-sm bg-primary align-middle" /> &lt;45 ms</span>
          <span><i className="inline-block w-2.5 h-2.5 rounded-sm bg-sky-500 align-middle" /> 45–80</span>
          <span><i className="inline-block w-2.5 h-2.5 rounded-sm bg-amber-400 align-middle" /> 80–130</span>
          <span><i className="inline-block w-2.5 h-2.5 rounded-sm bg-rose-500 align-middle" /> &gt;130</span>
        </div>
      </Panel>
    </div>
  );
}
