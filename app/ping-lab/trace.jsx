'use client';

import { useMemo, useState } from 'react';
import { analyzeRoute, complaintTemplate, parseTraceroute } from './trace-lib';
import { geolocateIps } from './geo';
import { fmt } from './stats';
import { Badge, Btn, Panel } from './ui';

const SAMPLE = `s3.eu-central-1.amazonaws.com izleniyor, en fazla 30 atlama:

  1    <1 ms    <1 ms    <1 ms  192.168.1.1
  2     3 ms     4 ms     3 ms  100.64.0.1
  3    12 ms    11 ms    12 ms  192.0.2.9
  4    14 ms    13 ms    15 ms  host-192-0-2-25.example.tr
  5    15 ms    14 ms    15 ms  host-192-0-2-41.example.tr
  6    58 ms    57 ms    59 ms  198.51.100.17
  7    96 ms    95 ms    97 ms  198.51.100.65
  8   101 ms   100 ms   102 ms  203.0.113.12
  9   104 ms   103 ms   105 ms  fra-core-1.example.de
 10   106 ms   105 ms   107 ms  52.219.72.16

İzleme tamamlandi.`;

const COMMANDS = [
  {
    label: 'Windows (PowerShell / CMD)',
    cmd: 'tracert -d -h 30 s3.eu-central-1.amazonaws.com',
    note: '-d ters DNS çözümlemesini kapatır, çok daha hızlı biter. ISP tespiti için hostname işe yarar; vaktin varsa -d olmadan da bir kez çalıştır.',
  },
  {
    label: 'macOS / Linux',
    cmd: 'traceroute -m 30 -w 2 s3.eu-central-1.amazonaws.com',
    note: 'mtr kuruluysa daha iyisi: mtr -rwzbc 50 s3.eu-central-1.amazonaws.com',
  },
  {
    label: 'En iyisi: mtr raporu',
    cmd: 'mtr -rwzbc 100 s3.eu-central-1.amazonaws.com',
    note: 'Hem gecikme hem paket kaybı verir. Çıktının tamamını aşağıya yapıştır.',
  },
];

export default function Trace() {
  const [text, setText] = useState('');
  const [geoMap, setGeoMap] = useState({});
  const [resolving, setResolving] = useState(false);
  const [geoNote, setGeoNote] = useState(null);
  const [sourceCity, setSourceCity] = useState('');
  const [copied, setCopied] = useState(false);

  const parsedHops = useMemo(() => parseTraceroute(text), [text]);

  const enriched = useMemo(() => {
    if (!parsedHops.length) return null;
    return parsedHops.map((h) => ({ ...h, geo: h.ip && geoMap[h.ip] && !geoMap[h.ip].error ? geoMap[h.ip] : null }));
  }, [parsedHops, geoMap]);

  const analysis = useMemo(() => (enriched ? analyzeRoute(enriched) : null), [enriched]);

  async function resolveCountries() {
    if (!parsedHops.length) return;
    setResolving(true);
    setGeoNote(null);
    const ips = parsedHops.map((h) => h.ip).filter(Boolean);
    try {
      const map = await geolocateIps(ips);
      const values = Object.values(map);
      const okCount = values.filter((v) => v && v.countryCode).length;
      const failCount = values.filter((v) => v && v.error).length;
      setGeoMap((prev) => ({ ...prev, ...map }));
      setGeoNote(
        okCount
          ? `${okCount} IP çözüldü${failCount ? `, ${failCount} IP çözülemedi (rate-limit/CORS)` : ''}.`
          : failCount
            ? `Hiçbir IP çözülemedi (${failCount}). Sağlayıcılar erişilemiyor — analiz hostname tahminiyle devam ediyor.`
            : 'Çözülecek public IP bulunamadı.',
      );
    } finally {
      setResolving(false);
    }
  }

  async function copyComplaint() {
    if (!analysis) return;
    const txt = complaintTemplate({ rows: analysis.rows, findings: analysis.findings, sourceCity: sourceCity || '……' });
    try {
      await navigator.clipboard.writeText(txt);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      /* pano izni yok */
    }
  }

  return (
    <div className="space-y-4">
      <Panel
        title="4. Rota analizi"
        subtitle="traceroute çıktısını yapıştır: gecikmenin tam olarak hangi hop'ta eklendiğini, CGNAT'ta olup olmadığını ve rotanın gereksiz dolanıp dolanmadığını gösterir."
      >
        <div className="space-y-3">
          {COMMANDS.map((c) => (
            <div key={c.label} className="p-3 rounded border border-neutral-800 bg-neutral-950/60">
              <div className="text-[11px] uppercase tracking-wide text-neutral-500">{c.label}</div>
              <code className="block mt-1 px-2 py-1 rounded bg-black/50 text-primary text-xs break-all">{c.cmd}</code>
              <div className="mt-1 text-xs text-neutral-500">{c.note}</div>
            </div>
          ))}
        </div>

        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={12}
          spellCheck={false}
          placeholder="tracert çıktısının tamamını buraya yapıştır…"
          className="w-full mt-4 p-3 font-mono text-xs rounded bg-black/50 border border-neutral-700 text-neutral-200"
        />

        <div className="mt-3 flex flex-wrap gap-2 items-end">
          <label className="text-sm text-neutral-300">
            Şehrin (şikayet metni için)
            <input
              value={sourceCity}
              onChange={(e) => setSourceCity(e.target.value)}
              placeholder="Örn: Bakü / İstanbul"
              className="block w-52 mt-1 px-2 py-1.5 text-sm rounded bg-neutral-950 border border-neutral-700 text-white"
            />
          </label>
          <Btn
            variant="ghost"
            onClick={() => {
              setText(SAMPLE);
              setGeoMap({});
            }}
          >
            Örnek veri yükle
          </Btn>
          <Btn variant="ghost" onClick={resolveCountries} disabled={!parsedHops.length || resolving}>
            {resolving ? 'Çözülüyor…' : 'Ülkeleri internetten çöz'}
          </Btn>
          <Btn variant="ghost" onClick={copyComplaint} disabled={!analysis}>
            {copied ? 'Kopyalandı ✓' : 'ISP şikayet metnini kopyala'}
          </Btn>
        </div>
        {geoNote ? <p className="mt-2 text-xs text-neutral-500">{geoNote}</p> : null}
      </Panel>

      {analysis ? (
        <>
          <Panel title="Tespitler">
            <ul className="space-y-3">
              {analysis.findings.map((f, i) => (
                <li key={i} className="p-3 rounded border border-neutral-800 bg-neutral-950/60">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge
                      tone={
                        f.level === 'high' ? 'bad' : f.level === 'medium' ? 'warn' : f.level === 'info' ? 'info' : 'neutral'
                      }
                    >
                      {f.level === 'high' ? 'KRİTİK' : f.level === 'medium' ? 'ORTA' : f.level === 'info' ? 'BİLGİ' : 'DÜŞÜK'}
                    </Badge>
                    <span className="font-semibold text-white">{f.title}</span>
                  </div>
                  <p className="mt-1.5 text-sm text-neutral-400">{f.detail}</p>
                </li>
              ))}
            </ul>
          </Panel>

          <Panel
            title="Hop dökümü"
            subtitle="+ms sütunu bir önceki hop'a göre eklenen gecikme. Büyük sıçrama = sorunun kaynağı."
          >
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-[11px] uppercase tracking-wide text-neutral-500">
                  <tr className="text-left border-b border-neutral-800">
                    <th className="py-2 pr-3 text-right">#</th>
                    <th className="py-2 pr-3 text-right">en iyi</th>
                    <th className="py-2 pr-3 text-right">+eklenen</th>
                    <th className="py-2 pr-3 text-right">kayıp</th>
                    <th className="py-2 pr-3">IP</th>
                    <th className="py-2 pr-3">Ülke</th>
                    <th className="py-2 pr-3">Sağlayıcı / host</th>
                    <th className="py-2 pr-3">Etiket</th>
                  </tr>
                </thead>
                <tbody>
                  {analysis.rows.map((r) => (
                    <tr key={r.hop} className="border-b border-neutral-800/60">
                      <td className="py-1.5 pr-3 text-right tabular-nums text-neutral-500">{r.hop}</td>
                      <td className="py-1.5 pr-3 text-right tabular-nums text-neutral-200">
                        {r.best != null ? fmt(r.best) : '*'}
                      </td>
                      <td
                        className={`py-1.5 pr-3 text-right tabular-nums ${
                          r.delta > 25 ? 'text-rose-400 font-semibold' : r.delta > 10 ? 'text-amber-300' : 'text-neutral-400'
                        }`}
                      >
                        {r.delta != null ? `+${fmt(r.delta)}` : '—'}
                      </td>
                      <td
                        className={`py-1.5 pr-3 text-right tabular-nums ${
                          r.lossPct > 0 ? 'text-rose-400 font-semibold' : 'text-neutral-500'
                        }`}
                      >
                        {r.lossPct != null ? `%${fmt(r.lossPct, 1)}` : '—'}
                      </td>
                      <td className="py-1.5 pr-3 font-mono text-xs text-neutral-300">{r.ip || '—'}</td>
                      <td className="py-1.5 pr-3 text-neutral-300">{r.country || '??'}</td>
                      <td className="py-1.5 pr-3 text-neutral-400">{r.isp || r.host || '—'}</td>
                      <td className="py-1.5 pr-3 space-x-1">
                        {r.private ? <Badge>yerel ağ</Badge> : null}
                        {r.cgnat ? <Badge tone="warn">CGNAT</Badge> : null}
                        {r.timeout ? <Badge>zaman aşımı</Badge> : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-3 text-xs text-neutral-500">
              Ülke/sağlayıcı önce ters-DNS hostname&apos;inden offline tahmin edilir; &quot;Ülkeleri internetten çöz&quot;
              dersen ipwho.is → ipapi.co → RIPE RDAP sırasıyla denenir. Hiçbiri çalışmasa da diğer tüm analiz geçerlidir.
            </p>
          </Panel>
        </>
      ) : text.trim() ? (
        <Panel title="Çıktı okunamadı">
          <p className="text-sm text-neutral-400">
            Yapıştırdığın metinde &quot;hop numarası + süre (ms)&quot; biçiminde satır bulamadım. Komutun tam çıktısını
            yapıştırdığından emin ol.
          </p>
        </Panel>
      ) : null}
    </div>
  );
}
