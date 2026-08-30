# Ping Lab — Frankfurt Gecikme Laboratuvarı

Brawl Stars EMEA sunucusu **Frankfurt, Almanya**'da ve bunu değiştirmenin yolu yok.
Bu araç değiştirebileceğin şeyleri ölçülebilir hale getiriyor. **VDS gerekmez, para
gerekmez, sunucu gerekmez** — her şey tarayıcıda ölçülür, veriler cihazında kalır.

## Çalıştırma

```bash
npm install
npm run dev          # http://localhost:3000/ping-lab
```

Telefonundan da ölçmek istersen dev sunucusunu ağa aç:

```bash
npm run dev -- -H 0.0.0.0 -p 3000
# sonra telefonda: http://<bilgisayarinin-ip-adresi>:3000/ping-lab
```

> Telefonda ölçmek önemli: telefonun Wi-Fi'ı ile bilgisayarın Ethernet'i farklı
> sonuç verir. İkisini de ölç, **"Bağlantı etiketi" verip profilleri kaydet**,
> sonra karşılaştır.

## Sekmeler

| # | Sekme | Ne işe yarar |
|---|---|---|
| 1 | **Hızlı test** | 10 hedefe (Frankfurt + diğer EMEA şehirleri + en yakın Cloudflare PoP) sırayla ölçüm atar. `min` senin fiziksel tabanın, `jitter` istikrarın. Bağlantı profillerini kaydedip karşılaştırır. |
| 2 | **Nöbet** | 5 saniyede bir ölçüp `localStorage`'a yazar. 24 saat açık bırak → **en iyi saat dilimini** veriyle bul. JSON olarak dışa/içe aktarılabilir. |
| 3 | **Bufferbloat** | Hattı doyurup RTT'nin ne kadar şiştiğini ölçer, A–F notu verir. "Biri video açınca oyun patlıyor" sorununun ölçüsüdür. |
| 4 | **Rota analizi** | `tracert`/`traceroute`/`mtr` çıktısını yapıştır: hangi hop'ta kaç ms eklendiğini, CGNAT'ta olup olmadığını, rotanın gereksiz dolanıp dolanmadığını gösterir ve **ISP'ye gönderilecek hazır şikayet metni** üretir. |
| 5 | **Rehber** | Yapılacaklar listesi ve fiziksel gerçekler. |

## Rota analizi için komutlar

```powershell
# Windows
tracert -d -h 30 s3.eu-central-1.amazonaws.com

# macOS / Linux
traceroute -m 30 -w 2 s3.eu-central-1.amazonaws.com

# En iyisi (mtr varsa): hem gecikme hem paket kaybı
mtr -rwzbc 100 s3.eu-central-1.amazonaws.com
```

Çıktının tamamını 4. sekmedeki kutuya yapıştır.

## Windows ayar betiği

`tools/windows-tuning.ps1` — ping'i sihirli şekilde düşürmez; gecikme ekleyen
gereksiz Windows davranışlarını kapatır: Wi-Fi adaptörünün güç tasarrufu için
kendini kapatması, Receive Segment Coalescing, MMCSS ağ kısıtlaması, Game DVR
arka plan kaydı, Delivery Optimization (P2P güncelleme dağıtımı).

```powershell
# Yönetici PowerShell
cd tools
.\windows-tuning.ps1 -DryRun    # önce ne yapacağını gör
.\windows-tuning.ps1            # uygula
.\windows-tuning.ps1 -Report    # mevcut durum + Frankfurt'a 100 isteklik ölçüm
.\windows-tuning.ps1 -Undo      # hepsini geri al
```

Tüm değişiklikler geri alınabilir. `-Report` ile önce/sonra `min`–`max` farkını
karşılaştır; iyileşme yoksa `-Undo` ile eski haline dön.

## Ne ölçülüyor, ne ölçülmüyor

- **Ölçülen:** senin cihazından AWS bölgesel uçlarına HTTP gidiş-dönüşü.
  `s3.eu-central-1.amazonaws.com` anycast **değildir**, doğrudan Frankfurt'a
  çözümlenir — bu yüzden "Frankfurt'a RTT" için tarayıcıdan ölçülebilen en temiz vekildir.
- **Ölçülmeyen:** Brawl Stars sunucusunun kendi IP'si. Oyun aynı şehirde ama farklı
  makinede. RTT çok yakın çıkar, birebir aynı olmayabilir. Karşılaştırmalar ve
  trendler için yeterince güvenilirdir; mutlak oyun ping'i için değil.
- İlk istek DNS + TCP + TLS içerir (sonuçlara katılmaz, `warmup` turları atılır);
  sonraki turlar bağlantıyı tekrar kullandığı için ~1 RTT'ye yaklaşır.

## Ülke/ISP çözümü

Rota analizinde ülke etiketi önce **ters-DNS hostname'inden tamamen offline** tahmin
edilir. "Ülkeleri internetten çöz" dersen şu sıra denenir:

1. `/api/trace` (kendi Node sunucun — CORS yok, tek istekte 100 IP; uygulamayı kendi
   bilgisayarında çalıştırıyorsan en güvenilir yol)
2. `ipwho.is` → `ipapi.co` → RIPE RDAP (tarayıcıdan doğrudan; statik yayında çalışır)

Hepsi başarısız olsa bile analizin geri kalanı (hop bazlı gecikme, CGNAT tespiti,
en büyük sıçrama, şikayet metni) çalışmaya devam eder.

## Bilinen sınır

`npm run build` bu depoda `app/revalidation/page.jsx` yüzünden başarısız olabilir:
o sayfa derleme sırasında Wikipedia'ya `fetch` yapıyor. Bu, Ping Lab ile ilgili
değildir; ağ erişimi olan bir makinede sorunsuz derlenir.
