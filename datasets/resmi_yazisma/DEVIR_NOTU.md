# Devir notu — issue #284, 240 vakalık üretim

**Dal:** `fix/284-resmi-yazisma-anonimlestirme-denetimi`
**Görev tanımı (asıl kaynak):** `datasets/resmi_yazisma/VAKA_URETIMI_240_PROMPT.md` (14 aşama)
**Son commit:** `9d95a65` — Aşama 3.2 tamamlandı
**Durum:** Aşama 0, 1, 2, 3 bitti. **Sırada Aşama 4 var.**

---

## Değişmez kurallar (bunlara uy)

1. **Push/PR/merge YOK.** Kullanıcı nihai onay verene kadar yalnız yerel commit.
   RAG'a (`ornekler.jsonl`) merge de yasak.
2. **Her tamamlanmış + test edilmiş aşama sonunda yerel commit at.** Limit
   dolduğunda başka bir ajanın kaldığı yerden devam edebilmesi için.
3. **Ham kaynaklara asla dokunma** (`00_gelen_kaynaklar/` altındaki
   PDF/HTML/DOC/DOCX ve `gib_api/*.json`). Bunlar git'ten çıkarıldı ama diskte
   duruyor; `--apply`'ı `--normalize-only` olmadan çalıştırmak bunları okur.
4. **`git checkout` / `git restore` uyarısı:** "şu veriyi geri al" ile "şu kod
   dosyasını sıfırla" niyetlerini **asla aynı komutta birleştirme**. Bu oturumda
   bir kez yapıldı ve saatlerce kod sessizce kayboldu. Herhangi bir hedefli geri
   almadan önce `git status` ve `git diff --stat` göster.
5. Her şey Docker'da çalışır. Git Bash'te `MSYS_NO_PATHCONV=1` şart, yoksa
   docker'a giden `/workspace/...` yolları bozuluyor.

---

## Nasıl çalıştırılır

```bash
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps backend python -m pytest /workspace/tests/unit/test_generate_yazisma_vaka_pilotu.py /workspace/tests/unit/test_mevzuat_dogrulama.py /workspace/tests/unit/test_prepare_resmi_yazisma_markdown.py /workspace/tests/unit/test_curate_yazisma_examples.py /workspace/tests/unit/mcp -q -p no:cacheprovider --no-cov
```

Üretim betiği (Evren + mevzuat-mcp canlı çağrı yapar):

```bash
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps backend python /workspace/scripts/generate_yazisma_vaka_pilotu.py --dry-run --max-cases 3
```

Bayraklar: `--dry-run` | `--apply` (dışlayan), `--resume`, `--max-cases N`, `--seed N`.

Notlar:
- Konteynerde `scripts/`, `datasets/`, `backend/app`, `backend/tests` bind-mount'lu;
  çalışma dizini `/workspace`. `backend/` klasörü konteynerde YOK.
- Test dosyalarında `sys.path` eklemesi **iki** seviye yukarı olmalı
  (`__file__/../../scripts`), üç değil — konteyner düzeni repo düzeninden farklı.
- `MEVZUAT_SOURCE=mcp` compose'da zaten ayarlı, mevzuat-mcp kendiliğinden kayıtlanır.
- `.env` diskte var ve `.gitignore`'da (EVREN_API_KEY dahil).

---

## Tamamlananlar

| Commit | Aşama | Ne yapıldı |
| --- | --- | --- |
| `e240bef` | 0 | OS-* kalite kapısı fail-closed yapıldı; `candidate` 63→9. Ham kaynaklar git'ten çıkarıldı (`git rm --cached` + `.gitignore`, geçmiş bozulmadı). |
| `da06726` | 1 | `itiraz` bir decision değil `incoming_type`; 8'li `ALLOWED_DECISIONS` + import-zamanı assert eklendi, pilotun 5 hatalı vakası yeniden sınıflandırıldı. |
| `d37b1ad` | 2, 3.1/3.3–3.6 | 240'lık kota tablosu, itiraz dağılımı (~%17,5, tür başına ≥3), kurum çeşitliliği (25 vaka warmup + avoid-listesi), checkpoint/resume, retry, hata günlüğü. |
| `9d95a65` | **3.2** | Tür-farkındalıklı mevzuat doğrulaması (aşağıda). |

### Aşama 3.2 — ne inşa edildi (yeni dosya: `scripts/mevzuat_dogrulama.py`)

Canlı `mevzuat-mcp` sunucusunun araç şeması sorgulanarak gerçek tür sözlüğü
alındı: `KANUN, CB_KARARNAME, YONETMELIK, CB_YONETMELIK, CB_KARAR, CB_GENELGE,
KHK, TUZUK, KKY, UY, TEBLIGLER, MULGA` (virgülle çoklu tür destekleniyor).
Sonuç satırı biçimi:
`- [4982] BİLGİ EDİNME HAKKI KANUNU (Kanunlar) | mevzuatId: 103705 | RG: 2003-10-24`

Tasarım kararları ve **gerekçeleri** (bunları bozmadan devam et):

- **Tür-farkındalıklı arama.** Tek bir "yönetmelik" kavramı sunucuda dört kovaya
  dağılmış; 2646 sayılı Resmî Yazışmalar Yönetmeliği yalnız `CB_YONETMELIK`
  altında. Bu yüzden tür başına virgülle ayrılmış **aday kümesi** gönderiliyor.
- **`resolve_and_fetch` bilerek KULLANILMADI.** O fonksiyon bulamazsa filtresiz
  tekrar arıyor; asistanın canlı aracı için doğru, burada yıkıcı: "5615 sayılı
  Sosyal Yardımlaşma Kanunu" iddiası, 5615 numaralı başka bir kanunla eşleşip
  doğrulanmış görünürdü.
- **Başlık karşılaştırması zorunlu.** Numara çözümlemesi tek başına pilotun iki
  gerçek hatasını da kaçırıyor. Kural: iddianın jenerik olmayan **her** sözcüğü
  resmî başlıkta bulunmalı (Türkçe eke toleranslı, `_ONEK_ESIK = 5`). Yön
  kasıtlı (iddia ⊆ resmî): resmî ad daha uzun olabilir, ama iddiada resmî adda
  hiç geçmeyen bir konu sözcüğü varsa ("SOSYAL YARDIMLAŞMA", "KÖY") uydurmadır.
- **Fail-closed.** Tanınmayan tür, eşleşmeyen numara, uyuşmayan başlık, metinde
  olmayan madde, mülga kayıt → hepsi ret. Mülga kayıt yedek olarak bile kabul
  edilmiyor.
- **Altyapı hatası ≠ atıf hatası.** `MevzuatAltyapiHatasi` ayrı; üst üste 5
  tanesinde tur durduruluyor (yazılmış vakalar korunur, `--resume` ile devam).
  Aksi halde sunucu düştüğünde 240 vaka sessizce mevzuatsız üretilirdi.
- **Önbellek.** 4982 onlarca vakada geçiyor; arama ve tam metin ayrı ayrı
  süreç içi önbellekleniyor.

Şema değişikliği: `legal_basis` artık `list[str]` değil, yapısal kayıt listesi
(`type`, `number`, `title`, `article`, `verification_source`,
`verification_status`). Kaydedilen `title` **modelin iddiası değil, MCP'den
gelen resmî ad**. `verification_*` alanlarını LLM doldurmuyor (kendi çıktısını
"doğrulandı" işaretlemesi doğrulamayı anlamsız kılardı). Metin bekleyen
tüketiciler için türetilmiş `legal_basis_text` eklendi.

**Canlı duman testi sonucu (3 vaka, `--dry-run`):** doğrulama gerçekten iş
gördü — 3 vakadan 2'sinde ilk deneme reddedildi (`numarasiz_atif`,
`bulunamadi`), retry'de düzeldi. Yani bu katman olmadan 240'lık turda
gerçekten onlarca hatalı atıf veri setine girecekti.

Testler: `backend/tests/unit/test_mevzuat_dogrulama.py` (34) +
`test_generate_yazisma_vaka_pilotu.py`'ye eklenen 4 sözleşme testi.
Hedefli süit toplamı: **167 geçti.**

---

## SIRADAKİ İŞ — Aşama 4 (küçük doğrulama partisi)

`VAKA_URETIMI_240_PROMPT.md` → "Aşama 4"ü oku. Özet:

1. 8–16 vakalık küçük bir parti üret (`--apply --max-cases 16`, çıktı
   `datasets/resmi_yazisma_vakalar/vakalar.jsonl`).
2. Tam hattan geçir ve **sert kalite kapısı** uygula; geçmeden 240'a ölçekleme.
3. Kontrol edilecekler: şema uygunluğu, decision–gövde tutarlılığı, itiraz
   çerçevesinin gerçekten itiraz olması, kurum çeşitliliği, anonimleştirme
   sızıntısı (ad taraması), mevzuat atıflarının doğrulanmış olması.
4. Kapı geçilirse Aşama 5 (split + tekrar/near-duplicate sızıntı kontrolü).

Sonrasındaki aşamalar: 5 (split/dedup), 6 (otomatik + insan QA + review
artifact), 7 (test/idempotence), 8–11 (tüm veri seti envanteri, RAG-only
analizi, karşılaştırma tabloları, yeterlilik değerlendirmesi), 12
(`TUM_VERI_SETI_ANALIZI.md` + `.json`), 13 (nihai rapor + **onay kapısı**).

### Aşama 4'e başlarken bilinmesi gerekenler

- `--apply` çıktıyı **satır satır** ekler (checkpoint); yarıda kesilirse
  `--resume` kaldığı yerden devam eder, `case_id`'lere göre atlar.
- Başarısızlıklar `datasets/resmi_yazisma_vakalar/vaka-hatalari.jsonl`'e
  kategori etiketiyle yazılır (ham hassas değer taşımaz).
- `--max-cases` **bu çalıştırmada üretilecek yeni vaka** sayısıdır, toplam
  değil.
- İlk 25 vaka tamamlanmadan kurum avoid-listesi devreye girmez (warmup);
  16 vakalık partide kurum çeşitliliği bu yüzden zorlanmaz — bunu kalite
  kapısında hatalı sinyal saymayın.
- İtiraz kotası her karar türünün **ilk N vakasına** yerleştirilir
  (`index <= itiraz_quota`), yani küçük bir parti orantısız çok itiraz içerir.
  Bu da beklenen davranıştır.

---

## Bilinen açık noktalar

- `datasets/sample_benchmark/` altında bu işle **ilgisiz**, önceden var olan
  silinmiş dosyalar working tree'de duruyor. Hiçbir commit'e dahil edilmedi;
  öyle kalsın, kullanıcıya sorulmadan dokunulmasın.
- `datasets/resmi_yazisma_vakalar_pilot/vakalar-taslak.jsonl` (20 vaka) eski
  şemayla üretildi, `legal_basis` orada hâlâ `list[str]`. Tarihsel referans;
  betik artık oraya yazmıyor. 240'lık üretimle karıştırma.
- İki yayımlanmış Claude Artifact var (pilot inceleme sayfası ve OS-*
  karşılaştırma sayfası); Aşama 6'nın review artifact'ı ayrı olacak.
