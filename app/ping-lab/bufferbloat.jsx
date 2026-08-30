'use client';

import { useRef, useState } from 'react';
import { PRIMARY_TARGET_ID, targetById } from './targets';
import { runBufferbloat } from './probe';
import { bufferbloatGrade, fmt } from './stats';
import { Badge, Btn, Panel, Stat, toneFor } from './ui';

/**
 * "Biri video açınca oyun patlıyor" sorununun ölçümü.
 * Boş hat RTT'si ile doygun hat RTT'sini karşılaştırır.
 * Not: bu test gerçek veri indirir.
 */
export default function Bufferbloat() {
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [seconds, setSeconds] = useState(12);
  const [mb, setMb] = useState(24);
  const abortRef = useRef(null);

  async function start() {
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setRunning(true);
    setResult(null);
    try {
      const r = await runBufferbloat({
        target: targetById(PRIMARY_TARGET_ID),
        seconds,
        mbPerStream: mb,
        signal: ctrl.signal,
      });
      setResult(r);
    } finally {
      setRunning(false);
      abortRef.current = null;
    }
  }

  const grade = result ? bufferbloatGrade(result.ratio) : null;
  const tone = grade && grade.grade === 'A' ? 'good' : grade && grade.grade === 'B' ? 'default' : grade && (grade.grade === 'C' || grade.grade === 'D') ? 'warn' : 'bad';

  return (
    <div className="space-y-4">
      <Panel
        title="3. Bufferbloat testi"
        subtitle="Ping'in düşük ama oyun oynanmaz oluyorsa sebep genelde budur: router tamponu doluyor."
        right={running ? <Btn variant="danger" onClick={() => abortRef.current?.abort()}>Durdur</Btn> : <Btn onClick={start}>Testi başlat</Btn>}
      >
        <div className="p-3 mb-4 text-xs rounded border border-amber-700/60 bg-amber-950/20 text-amber-200">
          ⚠️ Bu test yaklaşık <b>{mb * 3} MB</b> veri indirir. Mobil verideysen dikkat. Test bitince indirme otomatik iptal edilir.
        </div>

        <div className="flex flex-wrap gap-4 items-end">
          <label className="text-sm text-neutral-300">
            Yük süresi: {seconds} sn
            <input type="range" min="6" max="30" value={seconds} onChange={(e) => setSeconds(Number(e.target.value))} className="block w-44 mt-2" />
          </label>
          <label className="text-sm text-neutral-300">
            Akış başına: {mb} MB
            <input type="range" min="8" max="100" step="4" value={mb} onChange={(e) => setMb(Number(e.target.value))} className="block w-44 mt-2" />
          </label>
        </div>

        {running ? <p className="mt-4 text-sm text-neutral-400 animate-pulse">Hat doyuruluyor ve ölçülüyor…</p> : null}

        {result ? (
          <div className="mt-4">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Stat label="Boş hat RTT" value={fmt(result.baseAvg)} tone="good" hint={`${result.baseSamples} örnek`} />
              <Stat label="Yük altında ortalama" value={fmt(result.loadAvg)} tone={toneFor(result.loadAvg)} hint={`${result.loadSamples} örnek`} />
              <Stat label="Yük altında en kötü" value={fmt(result.loadMax)} tone={toneFor(result.loadMax)} />
              <Stat label="Şişme oranı" value={result.ratio ? `${fmt(result.ratio, 2)}×` : '—'} unit="" tone={tone} />
            </div>
            {grade ? (
              <p className="mt-4 text-sm text-neutral-300">
                <Badge tone={tone === 'good' ? 'good' : tone === 'bad' ? 'bad' : 'warn'}>Not: {grade.grade}</Badge>{' '}
                {grade.note}
              </p>
            ) : null}
            <div className="mt-4 p-4 rounded border border-neutral-800 bg-neutral-950/60 text-sm text-neutral-300">
              <div className="font-semibold text-white mb-2">Not C veya daha kötüyse yapılacaklar (sırayla):</div>
              <ol className="list-decimal pl-5 space-y-1.5">
                <li>Router arayüzünde <b>QoS / SQM (CAKE veya fq_codel)</b> özelliğini aç; yükleme/indirme hızını hattının %90&apos;ına sabitle.</li>
                <li>Router firmware&apos;i desteklemiyorsa OpenWrt kurulabilen bir model düşün — bu tek değişiklik çoğu ev hattında p95&apos;i yarıya indirir.</li>
                <li>Evin internetini paylaşan cihazlarda otomatik güncelleme ve bulut yedeklemeyi oyun saatlerinde kapat.</li>
                <li>Windows&apos;ta <code>tools/windows-tuning.ps1</code> betiğini çalıştır (Delivery Optimization&aposı kapatır).</li>
              </ol>
            </div>
          </div>
        ) : null}
      </Panel>
    </div>
  );
}
