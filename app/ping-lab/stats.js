/** İstatistik yardımcıları. Saf fonksiyonlar — test edilebilir. */

export function percentile(sortedAsc, p) {
  if (!sortedAsc.length) return null;
  const idx = Math.min(sortedAsc.length - 1, Math.max(0, Math.ceil((p / 100) * sortedAsc.length) - 1));
  return sortedAsc[idx];
}

export function mean(xs) {
  if (!xs.length) return null;
  return xs.reduce((a, b) => a + b, 0) / xs.length;
}

export function stddev(xs) {
  if (xs.length < 2) return 0;
  const m = mean(xs);
  return Math.sqrt(xs.reduce((a, b) => a + (b - m) ** 2, 0) / (xs.length - 1));
}

/**
 * Oyunlar için en anlamlı istikrar metriği: ardışık ölçümler arasındaki
 * ortalama mutlak fark. Ortalama ping aynı kalıp jitter ikiye katlanabilir;
 * Brawl Stars'ta "vuruş gecikti" hissini yaratan şey budur.
 */
export function jitter(xs) {
  if (xs.length < 2) return 0;
  let sum = 0;
  for (let i = 1; i < xs.length; i += 1) sum += Math.abs(xs[i] - xs[i - 1]);
  return sum / (xs.length - 1);
}

export function summarize(samples, fails) {
  const ok = samples.filter((n) => Number.isFinite(n));
  const sorted = [...ok].sort((a, b) => a - b);
  const total = ok.length + (fails || 0);
  return {
    n: ok.length,
    fails: fails || 0,
    lossPct: total ? ((fails || 0) / total) * 100 : null,
    min: sorted.length ? sorted[0] : null,
    max: sorted.length ? sorted[sorted.length - 1] : null,
    avg: mean(ok),
    p50: percentile(sorted, 50),
    p95: percentile(sorted, 95),
    stddev: stddev(ok),
    jitter: jitter(ok),
  };
}

/**
 * Bufferbloat notu: yük altındaki RTT / boş hattaki RTT.
 * <1.3x = A ... 3x üzeri = F. Bu, "biri video açınca oyun patlıyor" sorununun ölçüsü.
 */
export function bufferbloatGrade(ratio) {
  if (!Number.isFinite(ratio) || ratio == null) return { grade: '?', note: 'ölçülemedi' };
  if (ratio < 1.3) return { grade: 'A', note: 'harika — yük altında neredeyse hiç şişme yok' };
  if (ratio < 1.6) return { grade: 'B', note: 'iyi — hafif şişme' };
  if (ratio < 2.0) return { grade: 'C', note: 'fena değil — router\'da QoS/SQM açmayı dene' };
  if (ratio < 3.0) return { grade: 'D', note: 'kötü — belirgin bufferbloat, QoS şart' };
  return { grade: 'F', note: 'çok kötü — hat doyduğunda oyun oynanmaz hale geliyor' };
}

export function fmt(ms, digits = 1) {
  if (ms == null || !Number.isFinite(ms)) return '—';
  return ms.toFixed(digits);
}

/** Saate göre ısı haritası: { hour: { sum, count, jitSum } } -> [24] dizi */
export function hourBuckets(entries) {
  const buckets = Array.from({ length: 24 }, () => ({ sum: 0, count: 0, worst: null, jitterSum: 0, jitterN: 0 }));
  for (const e of entries) {
    const h = new Date(e.t).getHours();
    const b = buckets[h];
    b.sum += e.ms;
    b.count += 1;
    if (b.worst == null || e.ms > b.worst) b.worst = e.ms;
    if (Number.isFinite(e.dt)) {
      b.jitterSum += e.dt;
      b.jitterN += 1;
    }
  }
  return buckets.map((b) => ({
    count: b.count,
    avg: b.count ? b.sum / b.count : null,
    worst: b.worst,
    jitter: b.jitterN ? b.jitterSum / b.jitterN : null,
  }));
}
