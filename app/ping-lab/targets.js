/**
 * Ölçüm hedefleri.
 *
 * Neden S3 bölgesel uçları?
 *  - Brawl Stars'ın EMEA turnuva sunucusu Frankfurt, Almanya'da.
 *  - AWS'nin bölgesel uç noktaları (s3.<region>.amazonaws.com) anycast DEĞİLDİR;
 *    doğrudan o bölgedeki makinelere çözümlenir. Yani "Frankfurt'a RTT" için
 *    tarayıcıdan ölçülebilen en temiz vekildir.
 *  - Bu oyunun kendi sunucusunun IP'si değil. Aynı şehir + aynı kıta içi omurga
 *    olduğu için RTT çok yakın çıkar, ama birebir aynı olmayabilir.
 */
export const TARGETS = [
  {
    id: 'fra-s3',
    city: 'Frankfurt',
    country: 'DE',
    provider: 'AWS S3 eu-central-1',
    url: 'https://s3.eu-central-1.amazonaws.com/',
    role: 'target',
  },
  {
    id: 'fra-do',
    city: 'Frankfurt',
    country: 'DE',
    provider: 'DigitalOcean Spaces fra1',
    url: 'https://fra1.digitaloceanspaces.com/',
    role: 'target-alt',
  },
  {
    id: 'mil-s3',
    city: 'Milano',
    country: 'IT',
    provider: 'AWS S3 eu-south-1',
    url: 'https://s3.eu-south-1.amazonaws.com/',
    role: 'alt',
  },
  {
    id: 'zrh-s3',
    city: 'Zürih',
    country: 'CH',
    provider: 'AWS S3 eu-central-2',
    url: 'https://s3.eu-central-2.amazonaws.com/',
    role: 'alt',
  },
  {
    id: 'par-s3',
    city: 'Paris',
    country: 'FR',
    provider: 'AWS S3 eu-west-3',
    url: 'https://s3.eu-west-3.amazonaws.com/',
    role: 'alt',
  },
  {
    id: 'dub-s3',
    city: 'Dublin',
    country: 'IE',
    provider: 'AWS S3 eu-west-1',
    url: 'https://s3.eu-west-1.amazonaws.com/',
    role: 'alt',
  },
  {
    id: 'sto-s3',
    city: 'Stockholm',
    country: 'SE',
    provider: 'AWS S3 eu-north-1',
    url: 'https://s3.eu-north-1.amazonaws.com/',
    role: 'alt',
  },
  {
    id: 'mad-s3',
    city: 'Madrid',
    country: 'ES',
    provider: 'AWS S3 eu-south-2',
    url: 'https://s3.eu-south-2.amazonaws.com/',
    role: 'alt',
  },
  {
    id: 'dxb-s3',
    city: 'Dubai',
    country: 'AE',
    provider: 'AWS S3 me-central-1',
    url: 'https://s3.me-central-1.amazonaws.com/',
    role: 'compare',
  },
  {
    id: 'cf-popo',
    city: 'En yakın Cloudflare PoP',
    country: '??',
    provider: 'speed.cloudflare.com (anycast)',
    url: 'https://speed.cloudflare.com/__down?bytes=0',
    role: 'baseline',
  },
];

export const PRIMARY_TARGET_ID = 'fra-s3';

export function targetById(id) {
  return TARGETS.find((t) => t.id === id);
}

/** Tarayıcı önbelleğini atlamak için benzersiz sorgu parametresi ekler. */
export function cacheBust(url) {
  const sep = url.includes('?') ? '&' : '?';
  return `${url}${sep}_=${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`;
}
