import { isPrivateIPv4 } from './trace-lib';

/**
 * IP -> ülke/ISP zenginleştirme.
 *
 * Sıra:
 *   1) /api/trace  — kendi sunucumuz. Uygulamayı kendi bilgisayarında
 *      çalıştırıyorsan en güvenilir yol: CORS yok, tek istekte 100 IP.
 *   2) ipwho.is → ipapi.co → RIPE RDAP — tarayıcıdan doğrudan. Statik yayın
 *      (Netlify/Vercel) durumunda çalışır; rate-limit/CORS'a takılabilir.
 *
 * Hepsi başarısız olsa bile analiz çalışmaya devam eder; sadece ülke etiketi
 * boş kalır ve hostname tahmini devrede olur.
 */

const withTimeout = (promise, ms) =>
  Promise.race([promise, new Promise((_, rej) => setTimeout(() => rej(new Error('timeout')), ms))]);

async function viaLocalApi(ips) {
  const res = await withTimeout(
    fetch('/api/trace', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ips }),
    }),
    15000,
  );
  if (!res.ok) throw new Error(`yerel API ${res.status}`);
  const j = await res.json();
  if (!j || !j.results) throw new Error('yerel API: beklenmeyen yanıt');
  return j.results;
}

async function viaIpwho(ip) {
  const res = await withTimeout(fetch(`https://ipwho.is/${ip}`), 6000);
  const j = await res.json();
  if (!j || j.success === false) throw new Error('ipwho: başarısız');
  return {
    countryCode: j.country_code || null,
    country: j.country || null,
    city: j.city || null,
    isp: (j.connection && (j.connection.isp || j.connection.org)) || null,
    source: 'ipwho.is',
  };
}

async function viaIpapi(ip) {
  const res = await withTimeout(fetch(`https://ipapi.co/${ip}/json/`), 6000);
  const j = await res.json();
  if (!j || j.error) throw new Error('ipapi: başarısız');
  return {
    countryCode: j.country_code || null,
    country: j.country_name || null,
    city: j.city || null,
    isp: j.org || null,
    source: 'ipapi.co',
  };
}

async function viaRdap(ip) {
  const res = await withTimeout(fetch(`https://rdap.db.ripe.net/ip/${ip}`), 6000);
  if (!res.ok) throw new Error(`rdap: ${res.status}`);
  const j = await res.json();
  let name = null;
  const ent = (j.entities || []).find((e) => (e.roles || []).includes('registrant')) || (j.entities || [])[0];
  if (ent && ent.vcardArray && ent.vcardArray[1]) {
    const fn = ent.vcardArray[1].find((f) => f[0] === 'fn');
    if (fn) name = fn[3];
  }
  return {
    countryCode: j.country || null,
    country: j.country || null,
    city: null,
    isp: name || j.name || null,
    source: 'RIPE RDAP',
  };
}

const CHAIN = [viaIpwho, viaIpapi, viaRdap];
const cache = new Map();

async function geolocateIpViaPublic(ip) {
  if (cache.has(ip)) return cache.get(ip);
  let lastErr = null;
  for (const fn of CHAIN) {
    try {
      const r = await fn(ip);
      cache.set(ip, r);
      return r;
    } catch (e) {
      lastErr = e;
    }
  }
  const failed = { error: String((lastErr && lastErr.message) || lastErr || 'bilinmeyen hata') };
  cache.set(ip, failed);
  return failed;
}

export async function geolocateIp(ip) {
  if (!ip || isPrivateIPv4(ip)) return null;
  if (cache.has(ip)) return cache.get(ip);
  try {
    const bulk = await viaLocalApi([ip]);
    if (bulk && bulk[ip] && !bulk[ip].error) {
      cache.set(ip, bulk[ip]);
      return bulk[ip];
    }
  } catch {
    /* yerel API yok — public zincire düş */
  }
  return geolocateIpViaPublic(ip);
}

export async function geolocateIps(ips, concurrency = 4) {
  const unique = [...new Set((ips || []).filter((ip) => ip && !isPrivateIPv4(ip)))];
  const out = {};
  if (!unique.length) return out;

  const cached = unique.filter((ip) => cache.has(ip));
  for (const ip of cached) out[ip] = cache.get(ip);
  const pending = unique.filter((ip) => !cache.has(ip));

  if (pending.length) {
    let rest = pending;
    try {
      const bulk = await viaLocalApi(pending);
      for (const ip of pending) {
        const v = bulk && bulk[ip];
        if (v && !v.error) {
          cache.set(ip, v);
          out[ip] = v;
        }
      }
      rest = pending.filter((ip) => !out[ip]);
    } catch {
      rest = pending;
    }

    if (rest.length) {
      let i = 0;
      const worker = async () => {
        while (i < rest.length) {
          const idx = i;
          i += 1;
          out[rest[idx]] = await geolocateIpViaPublic(rest[idx]);
        }
      };
      await Promise.all(Array.from({ length: Math.min(concurrency, rest.length) }, worker));
    }
  }
  return out;
}
