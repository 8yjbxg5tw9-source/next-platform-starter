'use client';

import { useState } from 'react';
import QuickTest from './quick-test';
import Watch from './watch';
import Bufferbloat from './bufferbloat';
import Trace from './trace';
import { Badge, Panel } from './ui';

const TABS = [
  { id: 'quick', label: '1 · Hızlı test' },
  { id: 'watch', label: '2 · Nöbet' },
  { id: 'bloat', label: '3 · Bufferbloat' },
  { id: 'trace', label: '4 · Rota analizi' },
  { id: 'guide', label: '5 · Rehber' },
];

const FACTS = [
  {
    t: 'Sunucuyu seçemezsin',
    d: 'Brawl Stars Esports\u2019un resmî açıklamasına göre EMEA turnuva sunucusu Frankfurt, Almanya\u2019da (NA: Dallas, SA: São Paulo, APAC: Hong Kong). Türkiye ve Azerbaycan EMEA\u2019ya bağlanır. Oyundaki "konum" ayarı sadece liderlik tablosunu değiştirir, sunucuyu değiştirmez.',
  },
  {
    t: 'Almanya\u2019ya VPN ping\u2019i düşürmez',
    d: 'Zaten Frankfurt\u2019tasın. VPN paketi önce VPN sunucusuna götürür, yani ek ms ekler. VPN sadece ISP\u2019nin rotası bozuk olduğunda işe yarar — o yüzden ölçerek denemek gerekir.',
  },
  {
    t: 'Fiziksel taban hesaplandı',
    d: 'Frankfurt\u2019a düz-çizgi mesafe ve fiberde ışık hızı (200 km/ms) üzerinden: İstanbul ≈ 18,7 ms, Ankara ≈ 22,0 ms, Diyarbakır ≈ 28,3 ms, Bakü ≈ 33,5 ms teorik alt sınır. Gerçekte bunun 2–2,7 katı normaldir.',
  },
  {
    t: 'Asıl düşman jitter, ping değil',
    d: 'Ortalama 60 ms olup jitter 3 ms olan bir hat, ortalama 45 ms olup jitter 25 ms olan hattan daha iyidir. Bu yüzden her ölçümde jitter ve paket kaybı da gösteriliyor.',
  },
];

const STEPS = [
  {
    n: 'Ücretsiz ve en yüksek etkili',
    items: [
      'Kablolu oyna. Telefon için USB-C→Ethernet adaptör, emülatörde direkt Ethernet. Wi-Fi jitter\u2019ın bir numaralı kaynağı.',
      'Wi-Fi mecbursa: sadece 5 GHz (veya 6 GHz), router\u2019a 3–5 m, router\u2019da "band steering / smart connect" kapalı ki oyun ortasında 2,4 GHz\u2019e düşmesin.',
      'Router\u2019da QoS/SQM (CAKE + fq_codel) aç ve hızı hattının %90\u2019ına sabitle. Bunu 3. sekmedeki testle doğrula.',
      'Telefonda pil tasarrufunu, bulut yedeklemeyi ve otomatik güncellemeleri oyun saatlerinde kapat. Telefon ısınmasın — termal kısma kare düşürür, lag gibi görünür.',
      'Windows\u2019ta tools/windows-tuning.ps1 betiğini çalıştır: Wi-Fi adaptör güç tasarrufunu ve Delivery Optimization\u2019ı kapatır.',
    ],
  },
  {
    n: 'Kalıcı: ISP ve rota',
    items: [
      '4. sekmede traceroute çalıştır ve çıktıyı yapıştır. Hangi hop\u2019ta kaç ms eklendiğini ve rotanın dolanıp dolanmadığını gör.',
      'Rota Rusya/Beyaz Rusya üzerinden ya da Almanya\u2019yı geçip batıya taşıyorsa, "ISP şikayet metnini kopyala" ile hazır dilekçeyi al ve çağrı kaydı aç.',
      'CGNAT tespiti çıkarsa ISP\u2019den CGNAT dışı/statik IP iste.',
      'Cloudflare WARP (1.1.1.1, ücretsiz) kur, 1. sekmedeki testi WARP açık ve kapalı olarak tekrar çalıştır. Fark yoksa kaldır.',
    ],
  },
  {
    n: 'Sıfırlayamayacağın fark için oyun içi telafi',
    items: [
      'Timing\u2019e en duyarlı rolü (agresif giriş, flank) alma; göreli ping dezavantajı orada en çok cezalandırır.',
      '2. sekmedeki nöbet verisiyle en iyi saat dilimini bul ve antrenmanı oraya sabitle.',
      'Her zaman aynı bağlantıyı kullan. Tutarlılık, düşük ortalamadan daha değerlidir.',
      'Yedek bağlantı hazır olsun (Wi-Fi + mobil hotspot); maç ortası düşerse anında geç.',
      'Maç sırasında VPN/IP değiştirme ve aynı anda iki cihazdan girme — Supercell tarafında hesap paylaşımı şüphesi oluşturup ban riski yaratır.',
    ],
  },
  {
    n: 'Para vermene değmeyecek şeyler',
    items: [
      'DNS değiştirme (ping\u2019i etkilemez, sadece ilk bağlantı kurulumunu).',
      '"Ping düşürücü / game booster" mobil uygulamalar — hiçbiri fiziksel mesafeyi değiştirmez.',
      'Router\u2019daki "gaming modu" pazarlaması; gerçek olan tek şey SQM/QoS kuyruk yönetimidir.',
    ],
  },
];

export default function PingLabPage() {
  const [tab, setTab] = useState('quick');

  return (
    <div className="w-full py-8 space-y-6">
      <header className="space-y-3">
        <div className="flex items-center gap-2">
          <Badge tone="good">VDS yok · para yok · sunucu yok</Badge>
          <Badge tone="info">her şey tarayıcıda ölçülür</Badge>
        </div>
        <h1 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">Ping Lab — Frankfurt Gecikme Laboratuvarı</h1>
        <p className="max-w-3xl text-sm text-neutral-400">
          Brawl Stars EMEA sunucusu Frankfurt&apos;ta ve bunu değiştiremiyorsun. Bu araç değiştirebileceğin şeyleri
          ölçülebilir hale getiriyor: hattının gerçek tabanı, jitter&apos;ın, router&apos;ının şişmesi ve rotanın
          gereksiz yere dolanıp dolanmadığı. Tüm ölçümler senin cihazından yapılır, veriler cihazında kalır.
        </p>
      </header>

      <nav className="flex flex-wrap gap-2">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`px-3 py-1.5 text-sm rounded border transition ${
              tab === t.id
                ? 'border-primary text-primary bg-primary/10 font-semibold'
                : 'border-neutral-700 text-neutral-400 hover:border-neutral-500'
            }`}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {tab === 'quick' ? <QuickTest /> : null}
      {tab === 'watch' ? <Watch /> : null}
      {tab === 'bloat' ? <Bufferbloat /> : null}
      {tab === 'trace' ? <Trace /> : null}

      {tab === 'guide' ? (
        <div className="space-y-4">
          <Panel title="Önce gerçekler" subtitle="Bunları bilmeyince yanlış şey için para ve zaman harcanıyor.">
            <div className="grid gap-3 md:grid-cols-2">
              {FACTS.map((f) => (
                <div key={f.t} className="p-4 rounded border border-neutral-800 bg-neutral-950/60">
                  <div className="font-semibold text-white">{f.t}</div>
                  <p className="mt-1.5 text-sm text-neutral-400">{f.d}</p>
                </div>
              ))}
            </div>
          </Panel>

          <Panel title="Sırayla yapılacaklar" subtitle="Yukarıdan aşağı — üsttekiler ücretsiz ve en yüksek etkili.">
            <div className="space-y-5">
              {STEPS.map((s) => (
                <div key={s.n}>
                  <div className="text-sm font-semibold text-primary">{s.n}</div>
                  <ul className="mt-2 space-y-1.5 list-disc pl-5 text-sm text-neutral-300">
                    {s.items.map((it, i) => (
                      <li key={i}>{it}</li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </Panel>

          <Panel title="Bu sayfa ne ölçüyor, ne ölçmüyor">
            <ul className="space-y-1.5 text-sm text-neutral-300 list-disc pl-5">
              <li>
                Ölçülen: senin cihazından <b>AWS Frankfurt (eu-central-1)</b> bölgesel ucuna HTTP gidiş-dönüşü. Bölgesel
                S3 uçları anycast değildir, doğrudan o şehre çözümlenir.
              </li>
              <li>
                Ölçülmeyen: Brawl Stars sunucusunun kendi IP&apos;si. Oyun aynı şehirde ama farklı makinede; RTT çok yakın
                çıkar, birebir aynı olmayabilir. Karşılaştırmalar ve trendler için yeterince güvenilirdir.
              </li>
              <li>
                Her örnek DNS + TCP + TLS içerir ama bağlantı tekrar kullanıldığı için ek turlar ~1 RTT&apos;ye yaklaşır.
                Bu yüzden <b>min</b> değeri senin gerçek tabanındır.
              </li>
            </ul>
          </Panel>
        </div>
      ) : null}
    </div>
  );
}
