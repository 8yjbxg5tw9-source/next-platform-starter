/**
 * Sunucu taraflı IP coğrafya çözümü.
 *
 * Neden var? Tarayıcıdan ip-api.com'a gidilemez (ücretsiz katmanı HTTP-only ve
 * CORS yok). Uygulamayı kendi bilgisayarında `npm run dev` ile çalıştırdığında
 * Node isteği sunucudan yapar; CORS ve mixed-content diye bir sorun kalmaz ve
 * dakikada 45 istek hakkı tek çağrıda 100 IP için kullanılır.
 *
 * Ağ yoksa/erişilemezse 502 döner; istemci bunu görüp public sağlayıcılara düşer.
 */
const IPV4_RE = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/;

function validIp(ip) {
  const m = String(ip || '').match(IPV4_RE);
  if (!m) return false;
  const o = m.slice(1).map(Number);
  if (!o.every((n) => n >= 0 && n <= 255)) return false;
  // Yerel/özel aralıkları ele — ip-api bunlar için zaten hata döndürür, kota harcamaya gerek yok.
  const [a, b] = o;
  if (a === 10 || a === 127 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168)) return false;
  if (a === 169 && b === 254) return false;
  if (a === 100 && b >= 64 && b <= 127) return false; // CGNAT
  return true;
}

export async function POST(request) {
  let body;
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: 'geçersiz JSON gövde' }, { status: 400 });
  }
  const ips = [...new Set((body?.ips || []).filter(validIp))].slice(0, 100);
  if (!ips.length) {
    return Response.json({ error: 'çözülecek public IPv4 yok (özel/CGNAT aralıkları elendi)' }, { status: 400 });
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 12000);
  try {
    const upstream = await fetch('http://ip-api.com/batch?fields=query,status,country,countryCode,city,isp,as,org', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(ips),
      signal: controller.signal,
    });
    if (!upstream.ok) throw new Error(`ip-api ${upstream.status}`);
    const arr = await upstream.json();
    const results = {};
    for (const r of arr || []) {
      if (!r || !r.query) continue;
      if (r.status !== 'success') {
        results[r.query] = { error: r.message || 'ip-api: başarısız' };
        continue;
      }
      results[r.query] = {
        countryCode: r.countryCode || null,
        country: r.country || null,
        city: r.city || null,
        isp: r.isp || r.org || (r.as ? String(r.as).replace(/^AS\d+\s*/, '') : null),
        source: 'ip-api.com (sunucu)',
      };
    }
    return Response.json({ results });
  } catch (err) {
    return Response.json({ error: String((err && err.message) || err) }, { status: 502 });
  } finally {
    clearTimeout(timer);
  }
}
