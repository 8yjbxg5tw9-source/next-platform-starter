import { cacheBust } from './targets';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * Tek bir ölçüm. mode:'no-cors' kullandığımız için yanıt "opaque" döner;
 * gövdeyi okuyamayız ama isteğin tamamlanma süresini ölçebiliriz — RTT için
 * gereken tek şey bu. 403/404 dönmesi önemli değil, TCP+TLS gidiş-dönüşü yaşandı.
 */
export async function probeOnce(target, signal) {
  const url = cacheBust(target.url);
  const t0 = performance.now();
  try {
    await fetch(url, { mode: 'no-cors', cache: 'no-store', credentials: 'omit', signal });
    return { ok: true, ms: performance.now() - t0 };
  } catch (err) {
    if (signal && signal.aborted) return { ok: false, ms: null, aborted: true };
    return { ok: false, ms: null, error: String((err && err.message) || err) };
  }
}

/**
 * Turlar halinde ölçüm: her turda tüm hedefler sırayla yoklanır.
 * Sıralı olması önemli — aynı anda ateşlersek kendi trafiğimiz ölçümü kirletir.
 * İlk `warmup` tur DNS+TLS el sıkışmasını bitirir ve sonuçlara katılmaz.
 */
export async function runTest({ targets, rounds = 15, warmup = 2, gapMs = 40, onRound, signal }) {
  const results = {};
  for (const t of targets) results[t.id] = { samples: [], fails: 0, error: null };

  for (let r = 0; r < warmup + rounds; r += 1) {
    for (const t of targets) {
      if (signal && signal.aborted) return { aborted: true, results };
      const res = await probeOnce(t, signal);
      if (r >= warmup) {
        if (res.ok) {
          results[t.id].samples.push(res.ms);
        } else {
          results[t.id].fails += 1;
          if (res.error && !results[t.id].error) results[t.id].error = res.error;
        }
      }
    }
    if (onRound) onRound(r - warmup + 1, rounds, results);
    if (r < warmup + rounds - 1) await sleep(gapMs);
  }
  return { aborted: false, results };
}

/** Yük oluştur: iptal edilene kadar büyük dosyalar indir. */
function startLoadStreams(controllers, bytes) {
  for (let i = 0; i < 3; i += 1) {
    const ctrl = new AbortController();
    controllers.push(ctrl);
    (async () => {
      while (!ctrl.signal.aborted) {
        try {
          await fetch(cacheBust(`https://speed.cloudflare.com/__down?bytes=${bytes}`), {
            cache: 'no-store',
            signal: ctrl.signal,
          });
        } catch {
          /* iptal edildi ya da kısa kesinti — döngü aborted kontrolüyle çıkacak */
        }
        await sleep(10);
      }
    })();
  }
}

/**
 * Bufferbloat testi: boş hattın RTT'sini ölç, sonra hattı doyur ve tekrar ölç.
 * Oran = yükAltında / boş. Router tamponu şişiyorsa bu oran 2-5x'e fırlar.
 * DİKKAT: gerçek veri indirir (varsayılan ~3 x 24 MB).
 */
export async function runBufferbloat({ target, seconds = 12, mbPerStream = 24, onTick, signal }) {
  const base = [];
  for (let i = 0; i < 4; i += 1) {
    const r = await probeOnce(target, signal);
    if (r.ok) base.push(r.ms);
    await sleep(60);
  }
  const baseAvg = base.length ? base.reduce((a, b) => a + b, 0) / base.length : null;

  const controllers = [];
  startLoadStreams(controllers, Math.round(mbPerStream * 1024 * 1024));

  const loaded = [];
  const end = Date.now() + seconds * 1000;
  try {
    while (Date.now() < end) {
      if (signal && signal.aborted) break;
      const r = await probeOnce(target, signal);
      if (r.ok) loaded.push(r.ms);
      if (onTick) onTick({ loadedCount: loaded.length, last: r.ms, remainingMs: end - Date.now() });
      await sleep(120);
    }
  } finally {
    controllers.forEach((c) => c.abort());
  }

  const loadAvg = loaded.length ? loaded.reduce((a, b) => a + b, 0) / loaded.length : null;
  const loadMax = loaded.length ? Math.max(...loaded) : null;
  return {
    baseAvg,
    baseSamples: base.length,
    loadAvg,
    loadMax,
    loadSamples: loaded.length,
    ratio: baseAvg && loadAvg ? loadAvg / baseAvg : null,
  };
}
