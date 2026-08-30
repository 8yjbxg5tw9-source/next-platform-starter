/**
 * Traceroute / mtr çıktısını ayrıştırır + AĞ OLMADAN çalışan analiz.
 *
 * Tasarım kararı: coğrafi etiketleme (ülke/ISP) online API gerektirir ve
 * tarayıcıda CORS/rate-limit yüzünden her zaman çalışmaz. Bu yüzden analizin
 * tamamı offline çalışır: hop bazlı gecikme farkı, CGNAT tespiti, ters-DNS
 * hostname'inden ISP tahmini, ve en çok ms ekleyen hop. Online zenginleştirme
 * sadece bonus.
 */

const IPV4 = /\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b/;
const IPV4_BRACKET = /\[(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\]/;
const TIME_MS = /(?:<\s*(\d+(?:[.,]\d+)?)|(\d+(?:[.,]\d+)?))\s*ms/gi;
// mtr -rw biçimi:  "  5.|-- host.name  0.0%   100   46.1  46.3  44.9  97.2   5.4"
const MTR_LINE =
  /^\s*(\d{1,2})\.\|--\s+(\S+)\s+([\d.]+)\s*%\s+(\d+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*$/;

function parseMtrLine(line) {
  const m = line.match(MTR_LINE);
  if (!m) return null;
  const name = m[2];
  const ipMatch = name === '???' ? null : name.match(IPV4);
  // Sütunlar: Loss% Snt Last Avg Best Wrst StDev
  return {
    hop: Number(m[1]),
    times: [Number(m[7])],
    best: Number(m[7]), // Best
    avg: Number(m[6]), // Avg
    worst: Number(m[8]), // Wrst
    stddev: Number(m[9]), // StDev
    lossPct: Number(m[3]),
    ip: ipMatch ? ipMatch[0] : (IPV4.test(name) ? name : null),
    host: ipMatch ? null : name === '???' ? null : name,
    timeout: name === '???',
    mtr: true,
  };
}

export function parseTraceroute(text) {
  const hops = [];
  const lines = String(text || '').split(/\r?\n/);
  for (const raw of lines) {
    const line = raw.trim();
    if (!line) continue;

    const asMtr = parseMtrLine(line);
    if (asMtr) {
      hops.push(asMtr);
      continue;
    }

    const hopMatch = line.match(/^(\d{1,2})[\s.|]+/);
    if (!hopMatch) continue;
    const hop = Number(hopMatch[1]);
    if (!Number.isFinite(hop) || hop < 1 || hop > 64) continue;

    const times = [];
    let m;
    TIME_MS.lastIndex = 0;
    while ((m = TIME_MS.exec(line)) !== null) {
      const v = m[1] != null ? m[1] : m[2];
      times.push(parseFloat(String(v).replace(',', '.')));
    }

    let ip = null;
    let host = null;
    // Süreleri temizle, sonra hop numarasını düşür; kalan "kuyruk" IP + hostname'dir.
    const afterTimes = line.replace(TIME_MS, ' ');
    const tail = afterTimes.replace(/^\s*\d{1,2}[\s.|]+/, '').trim();

    const bracket = tail.match(IPV4_BRACKET);
    if (bracket) {
      ip = bracket[1];
      const before = tail.slice(0, tail.indexOf('[')).trim();
      host = before ? before.split(/\s+/)[0] : null;
    } else {
      const plain = tail.match(IPV4);
      if (plain) ip = plain[1];
      // IP'ler [a-z]{2,} ile eşleşmez, o yüzden bu desen sadece hostname yakalar.
      const candidate = tail.split(/\s+/).find((t) => /^[a-z0-9][a-z0-9.\-_]*\.[a-z]{2,}$/i.test(t));
      if (candidate) host = candidate;
    }
    hops.push({
      hop,
      times,
      best: times.length ? Math.min(...times) : null,
      ip,
      host,
      timeout: times.length === 0,
    });
  }
  return hops;
}

export function isPrivateIPv4(ip) {
  if (!ip) return false;
  const [a, b] = ip.split('.').map(Number);
  return a === 10 || a === 127 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168) || (a === 169 && b === 254);
}

/** 100.64.0.0/10 = operatör NAT'ı. Rotta görünüyorsa CGNAT arkasındasın. */
export function isCGNAT(ip) {
  if (!ip) return false;
  const [a, b] = ip.split('.').map(Number);
  return a === 100 && b >= 64 && b <= 127;
}

const ISP_KEYWORDS = [
  ['turktelekom', 'Türk Telekom', 'TR'],
  ['ttnet', 'Türk Telekom', 'TR'],
  ['superonline', 'Turkcell Superonline', 'TR'],
  ['turkcell', 'Turkcell', 'TR'],
  ['turknet', 'TurkNet', 'TR'],
  ['tellcom', 'Turkcell Superonline', 'TR'],
  ['vodafone.com.tr', 'Vodafone TR', 'TR'],
  ['avea', 'Türk Telekom (Avea)', 'TR'],
  ['millenicom', 'Millenicom', 'TR'],
  ['netspeed', 'Netspeed', 'TR'],
  ['dsmart', 'D-Smart', 'TR'],
  ['turksat', 'Türksat Kablo', 'TR'],
  ['kablonet', 'Türksat Kablo', 'TR'],
  ['azertelekom', 'AzərTelecom', 'AZ'],
  ['azertelecom', 'AzərTelecom', 'AZ'],
  ['azercell', 'Azercell', 'AZ'],
  ['bakcell', 'Bakcell', 'AZ'],
  ['nar.az', 'Nar (Azerfon)', 'AZ'],
  ['azerfon', 'Nar (Azerfon)', 'AZ'],
  ['delta-telecom', 'Delta Telecom', 'AZ'],
  ['connect.az', 'Connect AZ', 'AZ'],
  ['online.az', 'Online AZ', 'AZ'],
  ['dtag', 'Deutsche Telekom', 'DE'],
  ['vodafone.de', 'Vodafone DE', 'DE'],
  ['telefonica.de', 'O2/Telefónica DE', 'DE'],
  ['hetzner', 'Hetzner', 'DE'],
  ['amazonaws', 'AWS', null],
  ['de-cix', 'DE-CIX (Frankfurt IX)', 'DE'],
  ['ams-ix', 'AMS-IX', 'NL'],
  ['telia', 'Telia (transit)', null],
  ['lumen', 'Lumen/Level3 (transit)', null],
  ['level3', 'Lumen/Level3 (transit)', null],
  ['zayo', 'Zayo (transit)', null],
  ['gtt', 'GTT (transit)', null],
  ['cogent', 'Cogent (transit)', null],
  ['ntt', 'NTT (transit)', null],
  ['retn', 'RETN (transit)', null],
  ['seabone', 'Sparkle/Seabone (transit)', null],
  ['rostelecom', 'Rostelecom (RU transit)', 'RU'],
  ['transtelecom', 'TransTeleCom (RU transit)', 'RU'],
  ['tatneft', 'RU transit', 'RU'],
];

const TLD_COUNTRY = {
  tr: 'TR', az: 'AZ', de: 'DE', it: 'IT', ch: 'CH', fr: 'FR', ie: 'IE', se: 'SE',
  es: 'ES', at: 'AT', hu: 'HU', ro: 'RO', bg: 'BG', gr: 'GR', rs: 'RS', ge: 'GE',
  ru: 'RU', ua: 'UA', nl: 'NL', pl: 'PL', cz: 'CZ', sk: 'SK', si: 'SI', hr: 'HR',
  md: 'MD', by: 'BY', kz: 'KZ', uk: 'GB', gb: 'GB',
};

/** Ters-DNS hostname'inden ISP + ülke tahmini. Tamamen offline. */
export function guessFromHostname(host) {
  if (!host) return { isp: null, country: null };
  const h = host.toLowerCase();
  let isp = null;
  for (const [kw, name] of ISP_KEYWORDS) {
    if (h.includes(kw)) {
      isp = name;
      break;
    }
  }
  let country = null;
  const tld = h.split('.').filter(Boolean).pop();
  if (tld && TLD_COUNTRY[tld]) country = TLD_COUNTRY[tld];
  for (const [kw, , c] of ISP_KEYWORDS) {
    if (c && h.includes(kw)) {
      country = country || c;
      break;
    }
  }
  return { isp, country };
}

/**
 * Rota koridoru değerlendirmesi.
 * TR/AZ -> DE için makul koridor doğu->batı ilerler. Rusya/Beyaz Rusya üzerinden
 * dolanma ya da Almanya'yı geçip Fransa/Hollanda/İngiltere'ye kadar gidip geri
 * gelme, gereksiz 20-60 ms demektir.
 */
const WEST_OF_DE = ['FR', 'GB', 'NL', 'BE', 'LU', 'IE', 'ES', 'PT', 'NO', 'DK', 'SE', 'FI', 'IS'];
const DETOUR_COUNTRIES = ['RU', 'BY', 'KZ', 'TM', 'IR'];

export function analyzeRoute(hops) {
  const findings = [];
  const rows = [];
  let prev = 0;
  let reachedDE = false;
  let overshoot = null;
  let biggest = null;
  let cgnat = null;

  hops.forEach((h, i) => {
    const guess = guessFromHostname(h.host);
    // Öncelik: online çözüm > satırda zaten taşınan değer > hostname tahmini
    const country = h.geo?.countryCode || h.country || guess.country || null;
    const isp = h.geo?.isp || h.isp || guess.isp || null;
    const delta = h.best != null && Number.isFinite(h.best) ? h.best - prev : null;
    if (h.best != null && Number.isFinite(h.best)) prev = h.best;

    if (isCGNAT(h.ip) && !cgnat) cgnat = { hop: h.hop, ip: h.ip };
    if (country === 'DE') reachedDE = true;
    if (!reachedDE && country && WEST_OF_DE.includes(country) && !overshoot) {
      overshoot = { hop: h.hop, country, isp };
    }
    if (country && DETOUR_COUNTRIES.includes(country) && !reachedDE) {
      findings.push({
        level: 'high',
        title: `Rota ${country} üzerinden dolanıyor (hop ${h.hop})`,
        detail:
          'TR/AZ → Almanya trafiğinin Rusya/Beyaz Rusya üzerinden geçmesi için hiçbir coğrafi sebep yok. ' +
          'Bu tipik olarak 20-60 ms ekler. Bu hop listesini ekran görüntüsüyle ISP\'ne gönderip ' +
          '"Frankfurt/DE-CIX yönünde doğrudan transit istiyorum" de.',
      });
    }
    if (delta != null && (!biggest || delta > biggest.delta) && i > 0) {
      biggest = { hop: h.hop, delta, ip: h.ip, isp, country };
    }

    rows.push({ ...h, country, isp, delta, private: isPrivateIPv4(h.ip), cgnat: isCGNAT(h.ip) });
  });

  if (cgnat) {
    findings.push({
      level: 'medium',
      title: `CGNAT tespit edildi (hop ${cgnat.hop}: ${cgnat.ip})`,
      detail:
        '100.64.0.0/10 aralığı operatör NAT\'ıdır. Ping\'e doğrudan büyük etkisi yoktur ama port/NAT ' +
        'sorunları ve bazı jitter\'lara yol açar. Çoğu TR/AZ ISP\'si ücretsiz olarak CGNAT\'tan çıkarır — ' +
        '"statik IP / CGNAT dışı IP istiyorum" diye çağrı kaydı aç.',
    });
  }
  if (overshoot) {
    findings.push({
      level: 'high',
      title: `Almanya'yı geçip ${overshoot.country} yönüne taştı (hop ${overshoot.hop})`,
      detail:
        'Paket Almanya\'yı geçip batıya devam ettiyse, rotalama politikası yanlış. ' +
        'Bu, ölçtüğün RTT\'nin fiziksel minimumdan neden uzak olduğunu açıklar.',
    });
  }
  if (biggest && biggest.delta > 15) {
    findings.push({
      level: biggest.delta > 35 ? 'high' : 'low',
      title: `En büyük gecikme sıçraması hop ${biggest.hop}: +${biggest.delta.toFixed(1)} ms`,
      detail: biggest.isp
        ? `Bu sıçrama "${biggest.isp}" üzerinde oluyor. Sorunu ISP'ne bildirirken tam olarak bu hop'u göster.`
        : `Bu sıçramanın olduğu IP: ${biggest.ip || '?'}. Sorunu ISP'ne bildirirken tam olarak bu hop'u göster.`,
    });
  }
  const firstPrivateIdx = rows.findIndex((r) => r.private);
  const firstPublic = rows.find((r) => r.ip && !r.private && !r.cgnat);
  if (firstPublic) {
    findings.push({
      level: 'info',
      title: `Ev ağından çıkış: hop ${firstPublic.hop}${firstPublic.isp ? ` — ${firstPublic.isp}` : ''}`,
      detail: 'Bu noktadan öncesi senin modem/router\'ın; sonrası ISP sorumluluğunda.',
    });
  }
  if (!findings.length) {
    findings.push({
      level: 'low',
      title: 'Bariz bir dolanma tespit edilmedi',
      detail: 'Rota makul görünüyor. Kalan gecikme büyük olasılıkla fiziksel mesafe — yani değiştirilemez.',
    });
  }
  if (firstPrivateIdx === 0) {
    /* ilk hop'un private olması normal, bulgu üretme */
  }

  return { rows, findings, biggest, cgnat, overshoot };
}

/** ISP'ye gönderilecek şikayet metni (Türkçe). */
export function complaintTemplate({ rows, findings, sourceCity = '……' }) {
  const last = rows[rows.length - 1];
  const suspicious = rows.filter((r) => r.country && (DETOUR_COUNTRIES.includes(r.country) || WEST_OF_DE.includes(r.country)));
  const lines = [
    'Konu: Almanya (Frankfurt) yönünde gecikme/rotalama sorunu — düzeltme talebi',
    '',
    `Abone/şehir: ${sourceCity}`,
    `Tarih: ${new Date().toLocaleString('tr-TR')}`,
    '',
    'Profesyonel espor oyuncusuyum ve oyun sunucularım Frankfurt, Almanya\'da (EMEA bölgesi).',
    `traceroute sonucunda toplam gecikme ${last && last.best != null ? `${last.best.toFixed(1)} ms` : '—'}.`,
    suspicious.length
      ? `Trafik şu ülkeler üzerinden dolanıyor: ${suspicious.map((r) => `${r.country} (hop ${r.hop})`).join(', ')}.`
      : 'Belirgin bir ülke dolanması görülmedi ancak gecikme fiziksel minimumun çok üzerinde.',
    '',
    'Talep:',
    '1) Frankfurt / DE-CIX yönünde doğrudan transit veya daha kısa BGP rotası sağlanması.',
    '2) Mümkünse CGNAT dışı (statik) IP tanımlanması.',
    '3) Hattımın uluslararası çıkışında kuyruklama/bufferbloat kontrolü.',
    '',
    'Hop bazlı ölçüm:',
    ...rows.map(
      (r) =>
        `${String(r.hop).padStart(2, ' ')}. ${r.best != null ? `${r.best.toFixed(1).padStart(7)} ms` : '      *'}  ` +
        `${(r.ip || '?').padEnd(16)} ${r.country || '??'} ${r.isp || r.host || ''}` +
        (r.delta != null ? `  (+${r.delta.toFixed(1)} ms)` : ''),
    ),
    '',
    findings.length ? 'Tespitler:' : '',
    ...findings.map((f) => `- ${f.title}`),
  ];
  return lines.filter((l, i) => !(l === '' && i === lines.length - 1)).join('\n');
}
