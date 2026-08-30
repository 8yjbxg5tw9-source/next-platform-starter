'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { PRIMARY_TARGET_ID, TARGETS } from './targets';
import { runTest } from './probe';
import { summarize, fmt } from './stats';
import { Badge, Btn, Panel, Sparkline, Stat, toneFor } from './ui';
import { loadProfiles, loadSettings, saveProfile, saveSettings, deleteProfile } from './store';

export default function QuickTest() {
  const [settings, setSettings] = useState({ profile: 'Ev Wi-Fi', rounds: 15 });
  const [selected, setSelected] = useState(() => TARGETS.map((t) => t.id));
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [rows, setRows] = useState(null);
  const [live, setLive] = useState({});
  const [profiles, setProfiles] = useState({});
  const [copied, setCopied] = useState(false);
  const abortRef = useRef(null);

  useEffect(() => {
    setSettings(loadSettings());
    setProfiles(loadProfiles());
  }, []);

  const toggle = (id) =>
    setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));

  async function start() {
    const targets = TARGETS.filter((t) => selected.includes(t.id));
    if (!targets.length) return;
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setRunning(true);
    setRows(null);
    setLive({});
    setCopied(false);
    const rounds = Number(settings.rounds) || 15;
    setProgress({ done: 0, total: rounds });
    try {
      const { results } = await runTest({
        targets,
        rounds,
        signal: ctrl.signal,
        onRound: (done, total, partial) => {
          setProgress({ done, total });
          setLive(partial);
        },
      });
      setRows(results);
      setLive(results);
    } finally {
      setRunning(false);
      abortRef.current = null;
    }
  }

  function stop() {
    if (abortRef.current) abortRef.current.abort();
  }

  function persistSettings(patch) {
    const next = { ...settings, ...patch };
    setSettings(next);
    saveSettings(next);
  }

  const data = rows || live;
  const summary = useMemo(() => {
    if (!data) return null;
    const out = {};
    for (const t of TARGETS) {
      if (!data[t.id]) continue;
      out[t.id] = summarize(data[t.id].samples, data[t.id].fails);
    }
    return out;
  }, [data]);

  const ranked = useMemo(() => {
    if (!summary) return [];
    return TARGETS.filter((t) => summary[t.id] && summary[t.id].n > 0)
      .map((t) => ({ t, s: summary[t.id] }))
      .sort((a, b) => (a.s.min ?? 1e9) - (b.s.min ?? 1e9));
  }, [summary]);

  const verdict = useMemo(() => {
    if (!summary) return null;
    const fra = summary[PRIMARY_TARGET_ID];
    const base = summary['cf-popo'];
    if (!fra || fra.min == null) return null;
    const transit = base && base.min != null ? fra.min - base.min : null;
    let grade = 'good';
    let text = '';
    if (fra.min < 45) {
      grade = 'good';
      text = 'Frankfurt için çok iyi. Kalan fark fiziksel mesafe — zorlama, jitter\'a odaklan.';
    } else if (fra.min < 80) {
      grade = 'default';
      text = 'TR/AZ için normal bant. Oynanabilir; rakiple fark 25 ms altındaysa sorun değil.';
    } else if (fra.min < 130) {
      grade = 'warn';
      text = 'Yüksek. Rota Analizi sekmesinde traceroute çalıştır — genelde gereksiz bir dolanma vardır.';
    } else {
      grade = 'bad';
      text = 'Çok yüksek. Ya hat doygun ya rota çok dolanıyor. Önce Bufferbloat testini çalıştır.';
    }
    return { fra, base, transit, grade, text };
  }, [summary]);

  async function saveCurrent() {
    if (!summary) return;
    const all = saveProfile(settings.profile || 'Profil', { summary, rounds: settings.rounds });
    setProfiles(all);
  }

  async function copyReport() {
    if (!summary) return;
    const lines = [
      `Ping Lab raporu — ${new Date().toLocaleString('tr-TR')}`,
      `Bağlantı profili: ${settings.profile} | tur: ${settings.rounds}`,
      '',
      ranked
        .map(
          ({ t, s }) =>
            `${t.city.padEnd(22)} ${t.provider.padEnd(26)} min=${fmt(s.min)} ms  ort=${fmt(s.avg)}  p95=${fmt(s.p95)}  ` +
            `jitter=${fmt(s.jitter)}  kayıp=%${fmt(s.lossPct)}  n=${s.n}`,
        )
        .join('\n'),
      '',
      verdict ? `Frankfurt taban (min): ${fmt(verdict.fra.min)} ms` : '',
      verdict && verdict.transit != null ? `Omurga maliyeti (Frankfurt - en yakın PoP): ${fmt(verdict.transit)} ms` : '',
    ].filter(Boolean);
    try {
      await navigator.clipboard.writeText(lines.join('\n'));
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      /* pano izni yok */
    }
  }

  return (
    <div className="space-y-4">
      <Panel
        title="1. Hızlı test"
        subtitle="Her hedefe sırayla, önbellek atlanarak küçük istekler atılır. min = senin gerçek tabanın, jitter = istikrarın."
        right={
          <div className="flex gap-2">
            {running ? <Btn variant="danger" onClick={stop}>Durdur</Btn> : <Btn onClick={start}>Testi başlat</Btn>}
          </div>
        }
      >
        <div className="flex flex-wrap gap-4 items-end">
          <label className="text-sm text-neutral-300">
            Bağlantı etiketi
            <input
              value={settings.profile}
              onChange={(e) => persistSettings({ profile: e.target.value })}
              className="block w-48 mt-1 px-2 py-1.5 text-sm rounded bg-neutral-950 border border-neutral-700 text-white"
              placeholder="Örn: Ev Wi-Fi 5GHz"
            />
          </label>
          <label className="text-sm text-neutral-300">
            Tur sayısı: {settings.rounds}
            <input
              type="range"
              min="5"
              max="60"
              value={settings.rounds}
              onChange={(e) => persistSettings({ rounds: Number(e.target.value) })}
              className="block w-48 mt-2"
            />
          </label>
          <Btn variant="ghost" onClick={saveCurrent} disabled={!summary}>Bu profili kaydet</Btn>
          <Btn variant="ghost" onClick={copyReport} disabled={!summary}>{copied ? 'Kopyalandı ✓' : 'Raporu kopyala'}</Btn>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          {TARGETS.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => toggle(t.id)}
              className={`px-2.5 py-1 text-xs rounded border transition ${
                selected.includes(t.id)
                  ? 'border-primary text-primary bg-primary/10'
                  : 'border-neutral-700 text-neutral-500 hover:border-neutral-500'
              }`}
            >
              {t.city}
            </button>
          ))}
        </div>

        {running ? (
          <div className="mt-4 text-sm text-neutral-400">
            Ölçülüyor… tur {progress.done}/{progress.total}
            <div className="mt-2 h-1.5 rounded bg-neutral-800 overflow-hidden">
              <div
                className="h-full bg-primary transition-all"
                style={{ width: `${progress.total ? (progress.done / progress.total) * 100 : 0}%` }}
              />
            </div>
          </div>
        ) : null}
      </Panel>

      {summary && ranked.length === 0 ? (
        <Panel title="Hiçbir hedef ölçülemedi" subtitle="İstekler tarayıcından hiç çıkamadı.">
          <p className="text-sm text-neutral-300">Olası sebepler ve çözümleri:</p>
          <ul className="mt-2 space-y-1.5 text-sm text-neutral-400 list-disc pl-5">
            <li>Cihaz çevrimdışı ya da bir VPN/proxy tüm dış trafiği kesiyor.</li>
            <li>Kurumsal/okul ağı <code>amazonaws.com</code> ve <code>digitaloceanspaces.com</code> adreslerini engelliyor — mobil veriye geçip tekrar dene.</li>
            <li>
              Tarayıcı eklentisi (reklam engelleyici, gizlilik eklentisi) istekleri iptal ediyor — bu sekme için
              eklentileri kapat.
            </li>
          </ul>
          {Object.entries(data)
            .filter(([, v]) => v.error)
            .slice(0, 3)
            .map(([id, v]) => (
              <p key={id} className="mt-2 font-mono text-xs text-rose-300 break-all">
                {id}: {v.error}
              </p>
            ))}
        </Panel>
      ) : null}

      {verdict ? (
        <Panel title="Sonuç" subtitle="Brawl Stars EMEA sunucusu Frankfurt'ta. Senin için referans değer o.">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="Frankfurt taban (min)" value={fmt(verdict.fra.min)} tone={toneFor(verdict.fra.min)} hint="en iyi tur — fiziksel tabanın" />
            <Stat label="Frankfurt p95" value={fmt(verdict.fra.p95)} tone={toneFor(verdict.fra.p95)} hint="kötü anların" />
            <Stat label="Jitter" value={fmt(verdict.fra.jitter)} tone={verdict.fra.jitter > 12 ? 'bad' : verdict.fra.jitter > 6 ? 'warn' : 'good'} hint="ardışık fark ort. — hedef <10 ms" />
            <Stat
              label="Omurga maliyeti"
              value={verdict.transit != null ? fmt(verdict.transit) : '—'}
              tone={verdict.transit > 45 ? 'warn' : 'default'}
              hint="Frankfurt − en yakın PoP"
            />
          </div>
          <p className="mt-4 text-sm text-neutral-300">
            <Badge tone={verdict.grade === 'good' ? 'good' : verdict.grade === 'warn' ? 'warn' : verdict.grade === 'bad' ? 'bad' : 'info'}>
              değerlendirme
            </Badge>{' '}
            {verdict.text}
          </p>
        </Panel>
      ) : null}

      {ranked.length ? (
        <Panel title="Hedef hedef karşılaştırma" subtitle="min'e göre sıralı. En üstteki sana en hızlı EMEA şehri.">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-[11px] uppercase tracking-wide text-neutral-500">
                <tr className="text-left border-b border-neutral-800">
                  <th className="py-2 pr-3">Şehir</th>
                  <th className="py-2 pr-3">Sağlayıcı</th>
                  <th className="py-2 pr-3 text-right">min</th>
                  <th className="py-2 pr-3 text-right">ort</th>
                  <th className="py-2 pr-3 text-right">p95</th>
                  <th className="py-2 pr-3 text-right">jitter</th>
                  <th className="py-2 pr-3 text-right">kayıp</th>
                  <th className="py-2 pr-3 text-right">n</th>
                </tr>
              </thead>
              <tbody>
                {ranked.map(({ t, s }) => (
                  <tr key={t.id} className={`border-b border-neutral-800/60 ${t.id === PRIMARY_TARGET_ID ? 'bg-primary/5' : ''}`}>
                    <td className="py-2 pr-3 text-white">
                      {t.city} {t.id === PRIMARY_TARGET_ID ? <Badge tone="good">HEDEF</Badge> : null}
                      {t.role === 'baseline' ? <Badge tone="info">TABAN</Badge> : null}
                    </td>
                    <td className="py-2 pr-3 text-neutral-400">{t.provider}</td>
                    <td className={`py-2 pr-3 text-right tabular-nums font-semibold ${toneFor(s.min) === 'good' ? 'text-primary' : toneFor(s.min) === 'warn' ? 'text-amber-300' : toneFor(s.min) === 'bad' ? 'text-rose-400' : 'text-white'}`}>{fmt(s.min)}</td>
                    <td className="py-2 pr-3 text-right tabular-nums text-neutral-300">{fmt(s.avg)}</td>
                    <td className="py-2 pr-3 text-right tabular-nums text-neutral-300">{fmt(s.p95)}</td>
                    <td className="py-2 pr-3 text-right tabular-nums text-neutral-300">{fmt(s.jitter)}</td>
                    <td className="py-2 pr-3 text-right tabular-nums text-neutral-300">
                      {s.lossPct != null ? `%${fmt(s.lossPct, 0)}` : '—'}
                    </td>
                    <td className="py-2 pr-3 text-right tabular-nums text-neutral-500">{s.n}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      ) : null}

      {Object.keys(profiles).length ? (
        <Panel title="Kayıtlı profiller" subtitle="Wi-Fi / hotspot / Ethernet'i ayrı ayrı ölçüp burada karşılaştır.">
          <div className="space-y-2">
            {Object.entries(profiles).map(([name, p]) => {
              const fra = p.summary && p.summary[PRIMARY_TARGET_ID];
              return (
                <div key={name} className="flex flex-wrap items-center gap-3 p-3 border rounded bg-neutral-950/60 border-neutral-800">
                  <span className="font-semibold text-white">{name}</span>
                  <span className="text-sm text-neutral-400">
                    Frankfurt min {fra && fra.min != null ? `${fmt(fra.min)} ms` : '—'} · jitter{' '}
                    {fra && fra.jitter != null ? `${fmt(fra.jitter)} ms` : '—'} ·{' '}
                    {new Date(p.savedAt).toLocaleString('tr-TR')}
                  </span>
                  <div className="ml-auto flex gap-2">
                    <Btn
                      variant="ghost"
                      onClick={() => {
                        persistSettings({ profile: name });
                      }}
                    >
                      Bunu kullan
                    </Btn>
                    <Btn
                      variant="danger"
                      onClick={() => setProfiles(deleteProfile(name))}
                    >
                      Sil
                    </Btn>
                  </div>
                </div>
              );
            })}
          </div>
        </Panel>
      ) : null}

      {summary && summary[PRIMARY_TARGET_ID] && data[PRIMARY_TARGET_ID]?.samples?.length > 1 ? (
        <Panel title="Frankfurt örnek dağılımı" subtitle="Çizgi düz olmalı. Aşağı-yukarı zıplıyorsa sorun jitter'dır, ping değildir.">
          <Sparkline data={data[PRIMARY_TARGET_ID].samples} height={90} />
          <div className="mt-2 flex justify-between text-[11px] text-neutral-500 tabular-nums">
            <span>min {fmt(summary[PRIMARY_TARGET_ID].min)}</span>
            <span>max {fmt(summary[PRIMARY_TARGET_ID].max)}</span>
          </div>
        </Panel>
      ) : null}
    </div>
  );
}
