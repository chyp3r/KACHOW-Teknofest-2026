# Gelen Evrak–Karar–Cevap Vaka Üretimi — Uygulama Rehberi

> Şema ve gerekçe için önce [GELEN_EVRAK_KARAR_CEVAP_VERI_PLANI.md](GELEN_EVRAK_KARAR_CEVAP_VERI_PLANI.md)
> okunmalı. Bu doküman o planı **nasıl** yürüteceğini anlatır: adım adım,
> kim ne yapar, hangi kapıdan geçmeden bir sonrakine geçilmez.

Bu, `scripts/scrape_open_sources.py`'nin (OS-* serisi) tekrarı **olmamalı**.
O betik `random.choice()` ile kurum/konu/cümle havuzlarını rastgele
birleştiriyordu — üretim sırasında hiçbir gerçek belgeye bakmıyordu. Sonuç:
800 karttan yalnız 63'ü (%7,9) kalite kapısından geçti, geri kalanı ya
şablon tekrarı ya başlık-gövde uyumsuzluğuydu. Bu rehberdeki yöntem
**gerçek anonimleştirilmiş belgeleri few-shot örnek olarak LLM'e verir**,
rastgele birleştirme yapmaz.

---

## Ön koşullar

- `.env`'de `LOCAL_MODE=false` ve geçerli bir `EVREN_API_KEY` (takım
  bearer token'ı) tanımlı olmalı. Betik `EVREN_LLM_LARGE_MODEL` (`llm-large`)
  kullanır — karar mantığı ve mevzuat dayanağı üretimi için gereken model
  kalitesi budur, hızlı/küçük model bu iş için yeterli değildir.
- `docker compose up -d` ile backend servisi ayakta olmalı (betik container
  içinde çalışır, tıpkı `prepare_resmi_yazisma_markdown.py` gibi).

## Aşama 0 — Hedef belirle (karar zaten verildi, burada kayıtlı)

Mevcut korpusun ölçülen açığı ([bkz. plan §1](GELEN_EVRAK_KARAR_CEVAP_VERI_PLANI.md#1-neden-ayrı-bir-küme-gerekiyor)):
`yetkisizlik` kararı `eksik_belge` ile karışık etiketlenmiş, `belirsiz_basvuru`
ve `coklu_talep` pratikte yok, `itiraz`/`itiraz_cevabi` neredeyse hiç yok.

Pilot hedefi: **20 vaka**, 4 karar türünden 5'er tane:

| Karar türü | Adet | Neden bu öncelik |
| --- | --- | --- |
| `yetkisizlik` (eksik belgeden ayrı) | 5 | Şu an hiç ayrı örneği yok |
| `belirsiz_basvuru` | 5 | Modelin "soru sor" davranışını hiç görmediği tek boşluk |
| `coklu_talep` | 5 | Aynı yazıda farklı sonuçlanan talep — hiç örneği yok |
| `itiraz` + `itiraz_cevabi` | 5 | Gerçek korpusta pratikte sıfır |

## Aşama 1 — Üretim (betik)

```powershell
docker compose run --rm --no-deps backend `
  python scripts/generate_yazisma_vaka_pilotu.py --dry-run
```

`--dry-run` hiçbir dosya yazmaz, yalnız üretilen vakaların önizlemesini
konsola basar — Evren'e gerçek çağrı yapar (üretim maliyetsiz değil) ama
diski değiştirmez. Önizleme makul görünüyorsa:

```powershell
docker compose run --rm --no-deps backend `
  python scripts/generate_yazisma_vaka_pilotu.py --apply
```

Betiğin yaptığı, sırayla:

1. Hedef karar türü başına gerçek korpustan 2-3 **few-shot örnek** seçer
   (üslup/biçim referansı; içerik kopyalanmaz, yalnız kalıp gösterilir).
2. Evren'e (`llm-large`) yapılandırılmış bir istek gönderir —
   `generate_structured` ile Pydantic şemasına karşı doğrulanmış çıktı
   alır (serbest metin ayrıştırma yok, format hatası riski yok).
3. Üretilen `incoming_document` ve `gold_draft` metinlerini **aynı
   anonimleştirme/denetim hattından** geçirir
   (`prepare_resmi_yazisma_markdown.semantic_anonymize` +
   `_audit_privacy_findings`) — sentetik olsa da gerçekçi isim/kurum
   üretmiş olabilir, bu güvenlik ağı atlanmaz.
4. Otomatik-düzeltilebilir bir bulgu kalan vakayı **reddeder** (yazmaz),
   nedenini konsola basar.
5. Kalanları `datasets/resmi_yazisma_vakalar_pilot/vakalar-taslak.jsonl`'e
   yazar — **ayrı klasör**, üretim `ornekler.jsonl`'e hiç dokunmaz.
   Her kayıt `review_status: "taslak"` ile başlar.

## Aşama 2 — Yapısal ön inceleme (ben yaparım)

Betik bittiğinde ben `vakalar-taslak.jsonl`'i okuyup her vaka için:

- Şema alanlarının doldurulmuş ve tutarlı olduğunu (`must_not_invent`
  listesinin gerçekten `gold_draft`'ta geçmediğini, `decision` ile
  `decision_reason`'ın çeliştiğini) kontrol ederim.
- Anonimleştirme denetiminden geçtiğini (Aşama 1.4) doğrularım.
- Aynı normalleştirilmiş şablona yakınsayan tekrarları işaretlerim.

Bunun sonucu bir **öneri** listesidir (`review_status: "on_incelemeden_gecti"`
veya `"reddedildi"` + gerekçe) — nihai onay değil.

## Aşama 3 — Senin onayın (zorunlu kapı)

Ön incelemeden geçen vakaları örnekleriyle sana gösteririm. Her vaka için:

- **Onay** → `review_status: "uzman_onayli"`.
- **Ret** → `review_status: "reddedildi"`, kısa gerekçeyle.
- **Revizyon iste** → belirttiğin değişiklikle yeniden üretilir (Aşama 1'e
  döner, tek vaka için).

Onaylanmamış hiçbir vaka bir sonraki aşamaya geçmez.

## Aşama 4 — Ölçüm ve karar

Pilot vakaların geçiş oranı ([plan §7](GELEN_EVRAK_KARAR_CEVAP_VERI_PLANI.md#7-değerlendirme-metrikleri)ndeki
metriklerle) ölçülür:

- **Geçiş oranı ≥ %60** → yöntem çalışıyor demektir, ölçeği 20 → 240'a
  (tam plan) büyütmeyi öneririm.
- **Geçiş oranı %20-60** → prompt/few-shot seçimi iyileştirilip ikinci bir
  20'lik pilot denenir.
- **Geçiş oranı < %20** → OS-* ile aynı akıbete uğruyoruz demektir,
  yöntemi (few-shot seçimi, model, prompt yapısı) kökten gözden
  geçiririz — büyütmeyiz.

## Aşama 5 — Birleştirme (yalnız açık onayınla)

Pilot veya büyütülmüş küme ne kadar iyi olursa olsun,
`datasets/resmi_yazisma_vakalar_pilot/` içeriği **otomatik olarak**
`ornekler.jsonl`/üretim RAG'ına karışmaz. Birleştirme ayrı bir karardır ve
yalnız senin açık onayınla, ayrı bir işlemle yapılır (plan dokümanının
kapanış maddesi).

---

## Kontrol listesi (özet)

- [ ] `.env`: `LOCAL_MODE=false`, `EVREN_API_KEY` dolu
- [ ] `--dry-run` ile önizleme makul görünüyor
- [ ] `--apply` çalıştırıldı, `vakalar-taslak.jsonl` üretildi
- [ ] Anonimleştirme denetimi: 0 otomatik-düzeltilebilir bulgu
- [ ] Ben yapısal ön incelemeyi tamamladım
- [ ] Sen her vakayı tek tek onayladın/reddettin
- [ ] Geçiş oranı ölçüldü, Aşama 4 kararı verildi
- [ ] Birleştirme kararı senin açık onayınla, ayrı adımda
