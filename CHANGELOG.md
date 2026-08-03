# CHANGELOG

Tüm önemli değişiklikler bu dosyada kayıt altına alınacaktır.


## [1.32.0] - 2026-08-03
### Değiştirildi
- **Plan Yürütücüsü: Dispatch Tablosu + `StepStatus` Enum'u** (AP-5 PR-1/3, davranış-nötr): `planning_graph.py`'nin `execute_step_node`'undaki altı dallı `if/elif` zinciri, her adımın kendi `async` fonksiyonuna taşındığı bir `STEP_RUNNERS: dict[str, Callable]` dispatch tablosuna çevrildi. Bu, adım yürütmeyi bir bağımlılık grafiğine (AP-5 PR-2) oturtmanın önkoşuluydu -- dallanmış bir `if` zincirinin üzerine bağımlılık çözümlemesi kurulamaz.
  - Yeni `backend/app/core/enums/step_status.py`: `StepStatus(StrEnum)` -- `planning_graph.py`'de dağınık duran sekiz çıplak durum string'i (`FAILED`, `SKIPPED`, `COMPLETED`, `NEEDS_HUMAN_APPROVAL`, `NEEDS_INPUT`, `REVISE_REQUESTED`, `REJECTED`, `APPROVED`) artık tek bir yerde. `StrEnum` seçildi (mevcut `ReasoningLevel` ile aynı desen) çünkü `draft_graph.py` gibi henüz migrate edilmemiş modüllerin ürettiği düz string'lerle karşılaştırma otomatik çalışıyor, ve SSE üzerinden JSON'a giden değerler kendi string biçimiyle serileşmeye devam ediyor.
  - **Doğrulama:** `make eval` (`intents`: macro F1 0.9326, `drafts`: accuracy 1.0000) main'in mevcut haliyle birebir aynı; `docker compose run --rm backend pytest -q` 798 test değişmeden geçiyor; `test_event_contract.py` ve `test_hitl_flow.py` özellikle koşuldu (kaynak-metin greplemesi ve interrupt-replay davranışı bu refaktörün en kırılgan noktalarıydı).

## [1.31.0] - 2026-08-03
### Eklendi
- **Gelişmiş Sentetik PDF Veri Kümesi**: KVKK/PII ve RAG süreçlerinin testi için, 6 farklı kurum (MEB, İSKİ, SGK, YÖK, BOTAŞ, Ankara BŞB) formatına (antet, mizanpaj, Türkçe TrueType fontlar) birebir uygun ve sahte PII verileri içeren 300 adet zengin içerikli simülasyon PDF belgesi üretilerek veri setine döküldü (`scripts/generate_diverse_pdfs.py`).
- **Dilekçe Veri Kümesi Operasyonu**: Açık kaynak sitelerden (dilekceornegi.net vb.) gerçek dilekçe örnekleri kazındı. Buna ek olarak 12 farklı kategoride kurgusal sahte PII barındıran zengin dilekçe şablonları üretildi (`scripts/scrape_dilekce.py`). Veri setine 74 yeni dilekçe örneği dâhil edildi.
- **Ek Sentetik Veriler**: İhtiyaca yönelik olarak çok sayıda sentetik üst yazı dosyası oluşturuldu.

## [1.30.0] - 2026-08-03
### Eklendi
- **Sentetik RAG Veri Kümesi Genişletmesi**: Veri kümesinde eksik (0-1 adet) olan 9 farklı resmî yazışma kategorisi (İtiraz, Görüş Talebi, Ret/Kısmi Kabul, Eksik Belge, Proje Teklifi, Tekit, İade/Yetkisizlik vb.) için Şartnamenin 6.5 maddesine uygun olarak tamamen kurgusal, ancak kurumsal yapıya ve Yönetmeliğe uygun 53 adet yeni sentetik belge eklendi. Katalogdaki doğrulanmış örnek sayısı 253'e ulaştı.
- **Dataset İndeks Otomasyonu**: `scripts/update_dataset_indexes.py` adında yeni bir Python scripti eklendi. Bu script veri kümesi dizinindeki Markdown (`.md`) dosyalarını tarayıp YAML frontmatter bilgilerini otomatik okuyarak `kaynak-katalogu.jsonl`, `kaynak-ozeti.csv` ve ilgili dizinlerin alt `_indeks.csv` dosyalarını tek tuşla güncelleyerek manuel veri girişi hatalarının önüne geçmektedir.
=======
## [1.29.0] - 2026-08-03
### Düzeltildi
- **Semantik Katman Canlı Ollama'ya Karşı Ölçüldü ve Eşikleri Yeniden Kalibre Edildi**: 1.28.0'da bu katman **atıl** ve **ölçülmemiş** olarak gönderilmişti. Ollama açıldıktan sonra prototip vektörleri üretildi ve katman gerçek `nomic-embed-text` gömmeleriyle uçtan uca ölçüldü. Gönderilen `0.72` eşiğinin **gürültü bandının içinde** olduğu ortaya çıktı:

| sim | vaka | beklenen → eşleşen | |
|---|---|---|---|
| 0.880 | `held_01` | draft → draft | doğru |
| 0.859 | `held_02` | draft → draft | doğru |
| 0.758 | `held_12` | chat → **analyze** | **yanlış** |
| 0.750 | `held_13` | chat → chat | doğru |
| 0.749 | `held_08` | analyze → **draft** | **yanlış** |
| 0.747 | `held_15` | chat → **document_qa** | **yanlış** |
| 0.740 | `esc_08` | (belirsiz) | doğru şekilde kararsız |

  `0.72`'de bu **3 doğru karara karşı 3 yanlış** demek. Şansa karar veren bir katman nötr değil, bir **regresyondur**: o üç mesaj daha önce doğru bilme şansı olan bir modele eskale ediliyordu, semantik basamak bu şansı elinden aldı.
  - Eşik `0.80`'e çekildi — güvenli bandın (`0.758 → 0.859`) **ortası**, kenarı değil. Tarama `0.76`'nın da sıfır hata verdiğini gösteriyor ama bu 15 vakalık bir örneklemde son hataya `0.002` pay bırakır; bu bir eşik değil gürültüdür. Marj eşiği, benzerlik doğru ayarlandığında **hiç bağlayıcı olmuyor** (hayatta kalan iki karar 0.154 ve 0.098 ile geçiyor); yalnızca gerçekten eşit iki eşleşme yuvarlamayla ayrılmasın diye korundu.
  - **Asıl sonuç kalibrasyon değil, kalibrasyonun ortaya çıkardığı şey**: güvenli eşikte bu katman **130 mesajın 2'sini** çözüyor. Nedeni sayılarda görünüyor — resmî registerdeki Türkçe cümleler karşılıklı olarak benzer, dolayısıyla tamamen belirsiz bir mesaj bile alakasız prototiplere karşı 0.60–0.74 alıyor; bu gürültü tabanının üstünde yalnızca dar bir bant kalıyor. Plan bu katmanın eskalasyonların çoğunu soğuracağını varsayıyordu; **yedide birini** soğuruyor.
  - **Gecikme** (önceden bilinmiyordu): p50 **19.7 ms**, p95 **22.0 ms** — docstring'lerdeki 50-150 ms tahmininden belirgin şekilde iyi. Tahminler ölçümle değiştirildi.
- **Prototip Dizini Mount Edilmemiş Bir Yola Yazılıyordu**: `PROTOTYPE_DIR`, `__file__` üzerinden `parents[3].parent` ile türetiliyordu. Container'da paket kökü **çalışma dizininin kendisi** (`/workspace`) olduğu için bunun bir üstü `/` oluyordu; `build_prototypes.py` 768 boyutlu vektörleri `/datasets/prototypes/` altına "başarıyla yazdım" diyerek yazıyor, container çıkınca hepsi kayboluyordu. Betiğin başarı çıktısı gerçek bir üretimden ayırt edilemiyordu. Artık `MEVZUAT_CORPUS_DIR` ile aynı deseni izliyor: `settings` içinde göreli yol.
- **`make test` Redis'siz Koşuyordu**: Hedef `--no-deps` kullanıyordu; birim testlerinin altyapıya dokunmadığı varsayımıyla. Bu, `rate_limit()` arkasındaki yedi API testi dışında doğru — onlar Redis'e ulaşıyor ve bağlantı hatası testin beklediği 422 yerine 500 olarak yüzeye çıkıyor.
  - **Hata kipinden kötüsü, hatanın yanlış atfedilmesiydi**: bu yedi test dört ayrı PR'da "`origin/main`'de de mevcut, httpx/starlette sürüm kayması" diye raporlandı. Hikâye makuldü — çıktıda bir `StarletteDeprecationWarning` vardı ve `origin/main`'e geçip aynı yedi hata görülmüştü. Ama o kontrol de **aynı bozuk çağrıyı** kullanıyordu, dolayısıyla hipotezi değil harness hatasını doğruladı.
  - Redis ayaktayken paket **798 passed, 0 failed**. Ortada bir sürüm kayması yok ve hiç olmadı; deprecation uyarısı ilgisiz ve zararsız.
  - `make eval` `--no-deps` ile kalıyor; orada gerçekten doğru — o suite'ler saf karar fonksiyonlarını çağırıyor.

## [1.28.0] - 2026-08-03
### Eklendi
- **Semantik Prototip Katmanı** (`app/ai/semantic/`, `app/ai/policy/prototypes.py`): Karar merdiveninin 2. basamağı. Sözlüksel kurallar yüzeyleri **birebir** eşleştirir, dolayısıyla parafraza yapısal olarak kördür — "cevap hazırla"nın her yeni söyleniş biçimi elle eklenmek zorundadır. Bu katman, mesajı sınıf başına birkaç **örnek ifadeyle** anlam üzerinden karşılaştırır.
  - **Ekonomi tüm gerekçe**: kısa bir mesaj için tek `embed_query`, zaten bellekte ve sıcak duran bir modelde ~50-150 ms (`HybridRetriever` her mevzuat aramasında aynı servisi çağırıyor). Hızlı katman modelinin tek etiketlik yapılandırılmış çağrısı, JSON şeması + Pydantic doğrulama + olası retry ile ~1-3 sn. Yani burada çözülen bir parafraz, bir üst basamağın maliyetinin **yüzde birkaçına** mal olur.
  - **Değer, karar vermeyi reddetmesinde.** Aynı resmî registerdeki kısa Türkçe cümleler arasındaki kosinüs benzerliği sıkışıktır — alakasız cümleler rutin olarak 0.6 civarında oturur — dolayısıyla "en yakın prototip" neredeyse her zaman *bir* prototiptir. Bu yüzden bir eşleşme hem yüksek mutlak benzerlik hem de ikinciye net bir fark gerektirir; tek başına mutlak eşik sürekli tetiklenir, tek başına marj ise eşit derecede kötü iki eşleşme arasında farkın rastlantısal olduğu yerde tetiklenir. Herhangi biri sağlanmazsa modele düşülür.
  - Prototip vektörleri `scripts/build_prototypes.py` ile **önceden hesaplanır**; istek anında ~30 ifade gömmek, bu katmanın kaçınmak için var olduğu model çağrısından pahalı olurdu. Çalışma yolunda tek bir string gömülür: kullanıcının kendi mesajı (test bunu `embed_documents` hiç çağrılmadığını doğrulayarak kilitliyor).
  - Her vektör dosyası gömme modeli, boyutu ve policy sürümüyle **damgalıdır**; damga tutmazsa matcher kendini devre dışı bırakır. Farklı bir modelle üretilmiş vektörlerden karar vermek, bir model çağrısı ödemekten kötüdür: yavaş değil, **eminden yanlış** olur. Eksik dizin, okunamayan dosya ve gömme servisi kesintisi de aynı no-op'a düşer — betiği hiç çalıştırmamış bir kurulum, katman hiç yokmuş gibi davranır.
  - `resolve_plan` artık üç basamaklı: sözlüksel kurallar → prototipler → hızlı katman modeli. Her basamak yalnızca bir altının reddettiğini görür; kuralların çözdüğü bir mesaj **hiç gömme maliyeti ödemez** (testle kilitli).
  - `FakeEmbeddingsClient` conftest'e eklendi (`FakeLLMClient` deseniyle: gerçek alt sınıf, MagicMock değil).

### Değiştirildi
- **Held-out parafraz kümesi** (`intents.jsonl`, `heldout_paraphrase`, 16 vaka): Kurallar ayarlandıktan **sonra** yazıldı ve hiçbir kural bunlara göre değiştirilmedi. Önceki sürümdeki `1.0000` skorunun ne değerde olduğunu öğrenmenin tek dürüst yolu buydu.

| | 1.27.0 | 1.28.0 |
|---|---|---|
| Macro F1 (genel) | 1.0000 | **0.9326** |
| Eskalasyon (genel) | 0.0000 | **0.0538** |
| Held-out doğruluk | — | **0.25** (16'da 4) |

  **`1.0000` uyduruldu.** Kurallar ve eşikler o kümenin başarısızlıklarına göre ayarlanmıştı; ölçtüğü şey katmanın genelleme gücü değil, o kümeye ne kadar iyi uydurulduğuydu. Bunu bir sayıyla söylemek, 1.26.0'daki uyarı notundan daha değerlidir.

  On iki başarısızlık, farklı önem taşıyan iki sınıfa ayrılıyor:
  - **Yedisi çekimser kalıyor** — semantik katmanın tam olarak kurulduğu trafik: sözlüksel yüzeyi olmayan parafrazlar, bugün doğru davranışın eskalasyon olduğu ve bir prototip eşleşmesinin bunları model çağrısının küçük bir kesrine çözebileceği yerler.
  - **Beşi eminden yanlış** ve semantik katman bunlara **hiç yardım edemez**, çünkü yalnızca çekimserlik üzerinde çalışır. Beşin dördü `document_qa`'ya düşüyor ve bu, belirli bir karara kadar izlenebilir: `question_with_document` ipucu, "Evrakın konusu nedir?" varlık tabanını geçsin diye HINT (1.0) yerine DOMAIN (1.6) yapılmıştı. Bu düzeltme, `document_qa`'yı **belge ekliyken sorulan her soru için varsayılan** hâline getirdi — bir belge sorusu için doğru, parafraz edilmiş bir taslak/analiz/hatırlama talebi için yanlış.

  Bu bulgu **düzeltilmedi, kaydedildi**. Şimdi yapılacak herhangi bir değişiklik bu on altı vakadan haberdar olurdu ve onları bir ölçüm olarak yakardı — ki bu kümenin var olma sebebi tam olarak bu hatayı açığa çıkarmak. Düzeltme, kümeleri genişletme işiyle birlikte kalibrasyon adımına ait.

> **Semantik katman bu kurulumda atıl.** `datasets/prototypes/` altında vektör dosyası yok ve üretim betiği çalışan bir Ollama gerektiriyor. Katman testli olarak geliyor (`FakeEmbeddingsClient` ile 12 test + 5 merdiven testi) ama **gerçek gömmelerle uçtan uca ölçülmedi**: doğruluk katkısı ve `embed_query` p50/p95 gecikmesi bilinmiyor. `scripts/build_prototypes.py` canlı bir Ollama'ya karşı çalıştırılana kadar merdiven iki basamaklı kalır.

## [1.27.0] - 2026-08-03
### Düzeltildi
- **Taslak Yazarının Zaman Bütçesi Hiç Uygulanmıyordu**: `resilience.py:53` yazıldığından beri `writer: 120.0` ve `judge: 20.0` girdilerini taşıyordu ve **hiçbiri okunmuyordu** — `draft_graph.py` `node_timeout`'u import bile etmiyordu. Yani ~90 sn'lik taslak bütçesinin **en pahalı adımının** hiçbir düğüm seviyesi koruması yoktu, ama tabloda varmış gibi görünüyordu. Uygulanmayan bir bütçe, bütçesizlikten kötüdür: koruma olduğu izlenimi verir.
  - Yazarın bütçesi dekoratörle değil **düğümün içinde** uygulanıyor. Dekoratör düğümün `except` bloklarını aşarak yükselir ve taslak grafiğini düşürür; oysa bir zaman aşımının, grafiğin zaten yönlendirmeyi bildiği bir `FAILED` sonucuna dönüşmesi gerekir. Kendi `except TimeoutError` dalı var çünkü `str(TimeoutError())` boştur — kullanıcıya "Taslak üretilemedi: " diye iki nokta üst üsteden sonrası boş bir mesaj gösterilirdi. Kısmi akış korunuyor: kesilmiş bir taslak, insana boş bir taslaktan daha faydalıdır ve kullanıcı zaten yazılışını izlemiştir.
  - `judge` girdisi bağlanmak yerine **tablodan kaldırıldı**: `settings.DRAFT_JUDGE_TIMEOUT_SECONDS` o sayının zaten sahibiydi ve tek bir değer için iki sahip, bu değişikliğin ortadan kaldırmak için var olduğu sorunun ta kendisi. Yargıç çağrısı artık o ayarı seviyenin çarpanıyla ölçekliyor.
- **`reasoning_level` Düğüm Bütçelerine Hiç Ulaşmıyordu**: `reasoning_levels.py`, özellik eklendiğinden beri bir `timeout_multiplier` taşıyor (fast 0.6, deep 1.8) ama bu yalnızca **servis katmanının** dış zaman aşımına ulaşıyordu. Düğüm bütçeleri sabit kalıyordu; yani `deep` bir koşuya genel olarak 1.8× duvar saati veriliyor, ama fazladan işin yapıldığı yerde bu bütçe **harcanamıyordu**.
  - Kök neden: `@node_timeout(NODE_TIMEOUT_SECONDS["analyze"])` bir float alıyordu ve bu ifade graf **derlenirken** değerlendiriliyor; graf süreçte bir kez derlendiği için istek başına hiçbir değer oraya ulaşamazdı. Dekoratör artık düğüm **adı** alıyor ve bütçeyi çağrı anında state'teki `reasoning_level`'dan çözüyor.
  - `DocumentAnalysisState` ve `RoutingState` bu alanı taşımıyor (CHANGELOG 1.22.0 bunları kapsam dışı bırakmıştı), dolayısıyla dengeli seviyeye düşüyorlar — davranış değişmiyor, kablo alan eklendiğinde hazır.
  - Sonuç: `deep` yazara 216 sn (dengeli 120 sn'ye karşı), `fast` 72 sn veriyor. **Hiçbir seviye, hiçbir düğüm için dengeli seviyenin bugünkü sınırından dar değil.**

### Eklendi
- **Bildirimsel, Sürümlenmiş Policy Katmanı** (`app/ai/policy/`): Deterministik karar katmanının üzerinde hareket ettiği her eşik, onu okuyan kodun yanında yaşıyordu — `draft_verifier`'da `70.0`, `routing_graph`'ta `50.0`, `llm_judge`'da `0.6/0.4`, `planning_graph`'ta `12`/`40`/`4`, `intent_scorer`'da marj tabanları. Tek tek makul, toplu hâlde **incelenemez** — ve bunlardan ikisi, aralarındaki ilişki hiçbir yerde yazılmamış hâlde **aynı kavramın** iki şiddet derecesiydi.
  - **YAML değil, dondurulmuş dataclass** — bilinçli. Bir yapılandırma dosyası, bir eşiği kod değiştirmeden değiştirme yeteneği satın alır; burada istenmeyen tam olarak budur. Bu sayılar `evaluation/datasets` üzerinde kalibre ediliyor, dolayısıyla birini oynatmak bir CHANGELOG kaydı ve bir eval koşusu gerektirmeli, bir yeniden dağıtım değil. Tipli dataclass'lar ayrıca invaryantlara yaşayacak bir yer veriyor ve üretimle testin sapabileceği bir ayrıştırma yolu bırakmıyor.
  - **Asıl ürün invaryantlar.** Daha önce yalnızca tesadüfen doğru olan ilişkileri kodluyorlar: yönlendirme eşiği otomasyon eşiğinin **altında kalmalı** (70 "incelemesiz gönderilebilir", 50 "hiç yönlendirilemez"; ters çevirmek, yönlendirilemeyecek kadar zayıf bir taslağı aynı anda gönderilebilecek kadar iyi yapardı); yargıç harman ağırlıkları 1.0'a toplanmalı; bileşik taban varlık tabanının altına inemez (bileşik bir okuma, tekil bir okumadan daha az kanıta ihtiyaç duyamaz); ham geçmiş sınırı birebir pencereyi aşmalı; hiçbir düğüm bütçesi iş akışı tavanını geçemez. **Import anında** çalışıyorlar — kendisiyle çelişen bir policy, üretimde sessizce yanlış karar üretmek yerine süreci düşürüyor.
  - Tüketen modüller kendi modül seviyesi isimlerini koruyor ama policy'den **türetiyor**; mevcut 750 testin tamamı dokunulmadan geçiyor ve diff bir davranış değişikliği değil bir yönlendirme. Testler türetmenin kendisini doğruluyor: biri yeniden sabit kodlansa import'lar yine çalışırdı, yalnızca sapma görünürdü.
  - `ROUTING_UNITS` ile `RouteOutput.destination` Literal'ını hizada tutan bir test eklendi. Daha önce bu işi yapan tek şey "birbirinden sapamaz" diyen bir yorum satırıydı.
- **Policy Sürüm Damgası**: `DRAFT_SCORE` veya `CLAIM_MATCH`'teki bir kayma, "trafik değişti" ile "biz bir eşiği oynattık" arasında belirsizdi ve bu ikisi zıt tepkiler gerektirir. Prometheus'a `Info` olarak ekleniyor (mevcut koleksiyonerlere etiket olarak değil — kardinalite maliyeti sıfır), değerlendirme raporuna hem JSON yüküne hem Markdown başlığına yazılıyor.

> Bu sürüm **davranış-nötr**dür: `make eval` policy düzenlemesinden önceki ile birebir aynı `1.0000 / 1.0000` sonucunu üretiyor. Kanıt commit'lenmiş raporda.

## [1.26.0] - 2026-08-03
### Değiştirildi
- **Niyet Çözümleme: Sıralı Anahtar Kelime Şelalesi → Kanıt Skorlaması**: `planner.py` anahtar kelime gruplarını sabit sırayla kontrol edip ilk eşleşmede dönüyordu; bu, **sırayı** kararın kendisi hâline getiriyordu ve yeniden sıralamayla düzeltilemezdi (taslak önce kontrol edilince "Resmi yazı ne demek?" üç adımlı taslak hattını başlatıyor; analiz önce kontrol edilince "analiz sonrası taslak hazırla" analize düşüyor). 1.25.0'daki ölçüm iki kategoriyi **0.00** ile raporladı — zayıf değil, sıfır, sekiz vakanın sekizi. Artık mesaj bildirimsel bir kanıt tablosuna (`intent_rules.py`) karşı skorlanıyor ve karar, ilk eşleşen kural değil **ilk iki niyet arasındaki marj**. Kanıt kısa devre yapmak yerine biriktiği için çekişmeli bir mesaj görünür şekilde çekişmeli kalıyor; bu da onun bileşik plana yönlendirilmesini ya da dürüstçe eskale edilmesini mümkün kılıyor. Model çağrısı yok, hâlâ milisaniye altı.
  - **Ölçüm** (`evaluation/reports/all-scored-canonical.md`): macro F1 **0.7289 → 1.0000**, eskalasyon oranı **0.1842 → 0.0000**, kalibrasyon hatası **0.3011 → 0.0702**. Kabul kriterinin iki yarısı da doğru yönde: doğruluk artarken model çağrısı **azalıyor**.
  - Üç mekanizma ağırlığı taşıyor ve üçü de daha büyük bir sayı değil **karşı sinyal**: (a) *tanım sorusu sayacı* — "Üst yazı ne demek?" taslaktan söz eder, talep etmez; domain isminin ağırlığını düşürmek yerine çıkarma yapmak her gerçek talebi tam güçte bırakır. (b) *hafıza-hatırlama sayacı* — bu bir tercih değil, zorunluluk: deponun hâlihazırda dayandığı iki kural tek bir ağırlıkla **birlikte sağlanamıyor** (hatırlama `document_qa`'yı yenmeli → kural 4.4 üstünde olmalı; açık taslak talebi hatırlamayı yenmeli → 3.4 altında olmalı). Geçersiz kanıtı kaldırmak ikisini aynı anda sağlıyor. (c) *veda koruması* — "İyi akşamlar, yarın devam ederiz" "devam" içerir ve şimdi devam etmenin tersini söyler.
  - Belge durumu artık baştan sona bir **ağırlık**, asla bir kapı. Selamlama kuralının `document_id is None` koşuluna bağlı olması, belge ekliyken "Merhaba"yı çözülemez yapan şeydi.
  - **Bileşik niyet** marjdan *önce* kontrol ediliyor: "Uygunluk denetimi yap, sonra cevabı kaleme al" her iki okuma için de açık kanıt taşır ama dengesiz skorlar; marj testi bunu tek başına analize çözer ve talebin taslak yarısını sessizce düşürürdü. Yalnızca draft+analyze birleşiyor; `chat`'i `draft`'a katmak hem sohbet cevabı verip hem taslak üretmek olurdu ki bu iki okumadan hiçbirinin istediği değil.
  - `PlanDecision` artık `confidence`, `evidence` ve `alternatives` taşıyor. Eski çözümleyici yalnızca hangi dala girdiğini bildiriyordu; üretimdeki yanlış bir karar geriye dönük açıklanamıyordu.
  - **Yakalanan regresyon**: "evet, hazırla" hiçbir şeye çözülmüyordu — süreklilik sinyali ile kısa-mesaj ipucu aynı kanıtı iki kez sayıyor (kısa bir onay, *onay olduğu için* kısadır) ve iki skor karar verilemeyecek kadar yakın kalıyordu. Süreklilik tetiklendiğinde ipucu bastırılıyor. Bu regresyonu mevcut `test_planner.py` yakaladı.
  - `test_planner.py`'deki `source` doğrulamaları güncellendi: `keyword`/`short_message`/`memory_recall` artık var olmayan bir şelalenin dallarını adlandırıyordu ve `source` tek bir logger çağrısı dışında tüketicisi olmayan tanılama etiketidir. Her `intent` ve `steps` doğrulaması **değişmeden geçiyor** — 1.24.0'ın hafıza-hatırlama önceliği ve süreklilik uzunluk sınırı dâhil.

### Düzeltildi
- **Taslak Doğrulamada Biçim Kaynaklı Yanlış Pozitifler**: `verify_draft` bir iddiayı kaynakla karşılaştırırken her iki tarafı küçük harf ASCII'ye katlayıp birinin diğerini içerip içermediğine bakıyordu. Bu düzyazı için çalışır, **tipli değerler** için çalışmaz: aynı olgunun iki yazımı farklı dizgelere katlanır (`01.03.2026` ↔ `1 Mart 2026`, `Madde 11` ↔ `m. 11`, `125.000,00 TL` ↔ `125.000 TL`, `E-44444444-841-77` ↔ `E-44444444/841/77`). Jeton örtüşmesi geri düşüşü de kurtaramıyordu — "12 Mart 2026" ile "12 03 2026" kısa jetonlar atıldıktan sonra yalnızca yılı paylaşır, 0.75 eşiğine karşı 0.50. 1.25.0 ölçümü, kapının ürettiği **her** yanlış pozitifin bu sınıftan olduğunu gösterdi ve `draft_graph.py` bunu bir HITL kesintisine çevirdiği için her biri doğru bir taslakta gereksiz bir kullanıcı kesintisiydi.
  - Yeni `app/ai/verification/normalizers.py`: `canonical_date`, `canonical_document_number`, `canonical_amount`, `canonical_legislation`. Bu **kayıpsız normalleştirmedir, bulanık eşleştirme değil** — kanonik biçim bir değerin nasıl yazıldığını değiştirir, ne anlama geldiğini asla. Ay tablosu tam, imkânsız tarihler kırpılmak yerine reddediliyor, kanun ve madde ayrı ad alanlarında (`kanun:4982` ≠ `madde:4982`), ayrıştırılamayan değer tahmin üretmek yerine `None` dönüyor. Her kanonikleştiricinin eşlenik bir "farklı değerler farklı kalır" testi var; başarısızlığı bir uydurmayı dayanaklı bir iddiaya çevirecek olan özellik budur.
  - Destek merdiveni tür-farkında: `exact → canonical → token_overlap → none`. Kanonik, jeton örtüşmesinden **önce** deneniyor; tipli bir değer için kanonik eşitlik tam ve nihaidir, ve eşleşmiyorsa iki farklı tarih arasındaki kısmi jeton örtüşmesi hiçbir şeyin kanıtı değildir.
  - `UnsupportedClaim` artık `canonical` (kaynakta gerçekten aranan biçim) ve `best_overlap` (en iyi metinsel eşleşmenin ne kadar yaklaştığı) taşıyor. Eskiden bir bulgu yalnızca "bu dayanaksız" diyordu; bu, uydurma bir belge sayısını farklı ayırıcılarla yazılmış gerçek birinden ayırt edemiyordu.
  - **Ölçüm**: doğruluk **0.9000 → 1.0000**, yanlış pozitif oranı **0.2353 → 0.0000**, yanlış negatif oranı **0.0000 → 0.0000** (yeni kaçak yok), ve dayanaksız ifade sayımı 40 vakanın tamamında **birebir doğru**.
- **`LEGISLATION_PATTERN` Belge Sayısının Kuyruğunu Kanun Numarası Sanıyordu**: `E-22222222-903-118 sayılı yazınız` ifadesinde `\d{3,5}\s+sayılı` kalıbı belge sayısının kuyruğuna eşleşip hayalet bir `118 sayılı` atfı üretiyordu; bu atıf sonra taslağın gerçekten andığı mevzuata karşı denetleniyordu. Bugün bu hayalet yalnızca bağlamda **başka** bir "N sayılı" atfı bulunduğunda jeton örtüşmesi tarafından yutuluyor — hiç kanun atfı içermeyen bir bağlamda dayanaklı bir taslağın kendi referans numarası uydurma yasal atıf olarak raporlanırdı. `[-/\d]` için olumsuz geriye bakış hem bunu hem de "12345 sayılı"nın ayrıca "2345 sayılı" olarak eşleşmesini engelliyor. **Denetimle değil, değerlendirme koşumuyla bulundu.**

### Eklendi
- `CLAIM_MATCH{kind, method}` Prometheus sayacı: `DRAFT_SCORE` kapının ürettiği sayıyı kaydediyordu ama **nasıl** ürettiğini hiçbir şey kaydetmiyordu, dolayısıyla bir groundedness regresyonu tek bir iddia türüne indirgenemiyordu. İki etiket de kapalı küme — serbest metin Prometheus kardinalitesini patlatırdı.

> **Aşırı uyum uyarısı**: Her iki suite'in de 1.0000 alması, kuralların ve eşiklerin bu altın kümenin başarısızlıklarına bakılarak ayarlanmış olmasını yansıtır. Altın kümeler uygulamadan **önce** yazıldı ve mevcut 30 `test_planner.py` testi (bu değişiklikle yazılmadı, eski uygulamaya karşı yazılmıştı) değişmeden geçiyor — bunlar bağımsız kontrollerdir. Yine de bu sayılar "gerçek dünyada %100 doğruluk" iddiası değildir; koşumun asıl değeri regresyonları önlemesi ve baseline karşılaştırmasıdır. Kümenin genişletilmesi ve eşiklerin plato ortasına kalibre edilmesi sonraki iştir.

## [1.25.0] - 2026-08-03
### Eklendi
- **Deterministik Karar Katmanı için Değerlendirme Koşumu**: Sistemin LLM olmayan karar fonksiyonları (`resolve_plan_deterministic`, `verify_draft`) doğru çalışıp çalışmadığı ölçülemez durumdaydı — `evaluation/metrics.py` ve `evaluation/generate_report.py` **0 byte**, `evaluation/` altındaki sekiz klasör boş `.gitkeep` idi. Bu yüzden `draft_verifier.py:88`'deki `UNSUPPORTED_CLAIM_PENALTY=12.0`'ın 10 veya 15 olmasının daha iyi olup olmadığını, ya da `planner.py`'ye eklenen bir anahtar kelimenin başka bir vakayı bozup bozmadığını söyleyecek hiçbir mekanizma yoktu; her eşik sezgiyle seçilmişti. Artık `make eval` ile koşan, **hiç LLM çağrısı içermeyen** bir ölçüm katmanı var.
  - `evaluation/metrics.py`: `accuracy`, `macro_f1`, `confusion_matrix`, `abstention_rate`, `risk_coverage_curve`, `expected_calibration_error`, `precision_at_k`/`recall_at_k`, `binary_rates`. Metrikler baştan sona **abstention-farkında**: ölçülen katman çekimser kalıp işi model katmanına devredebildiği için kalite, birbiriyle takas eden iki eksene bölünür — karar verdiğinde ne sıklıkla haklı olduğu, ve yanılacağı vakalarda çekimser kalıp kalmadığı. Yalnızca birincisini iyileştirmek her şeye kendinden emin ve yanlış cevap veren bir katman üretir; yalnızca ikincisini iyileştirmek tüm yükü modele yıkan bir katman üretir. Yalnızca standart kütüphane kullanıldı.
  - `evaluation/harness/runner.py`: hangi kararı ölçtüğünü bilmeyen jenerik koşucu; suite bir JSONL altın küme ve bir çağrılabilir verir. Karar fonksiyonundan gelen istisnayı **bilinçle yakalamaz** — çökme bir kusurdur, yanlış sınıflandırma değil; ikisini birleştirmek bozuk bir üretim fonksiyonunun makul bir doğruluk düşüşü gibi okunmasına yol açardı.
  - `evaluation/harness/intent_suite.py` ve `draft_suite.py`: her ikisi de kapının **LLM'siz yarısına** bağlanır (`resolve_plan` değil `resolve_plan_deterministic`; yargıçsız `verify_draft`) — aksi hâlde koşum yavaş ve tekrarlanamaz olur, üstelik asıl aranan sayıyı gizlerdi: deterministik katman ne sıklıkla eskale etmek zorunda kalıyor.
  - `evaluation/datasets/intents.jsonl` (114 vaka) ve `drafts.jsonl` (40 vaka). Kategoriler trafiğin tarafsız örneklemi değil, mevcut katmanın **bilinen kusur sınıflarıdır** (`inversion`, `compound`, `precedence`, `paraphrase_*`, `escalation`); `keyword_*`/`continuation`/`document_question` ise kontrol grubudur. Şartname 6.5: tüm vakalar kurgudur.
  - `evaluation/generate_report.py`: JSON + Markdown rapor, `--baseline` ile karşılaştırma. Delta yönü metrik başına belirlenir — macro F1'in yükselmesi iyi, eskalasyon veya yanlış pozitif oranının yükselmesi kötüdür; tek bir "yüksek iyidir" kuralı bunların yarısını ters raporlardı.
  - `Makefile`: `make eval`, `make eval-baseline`, `make test`. Koşum `make test`ten **bilinçle ayrı**: başarısız bir altın küme vakası ölçümdür, kırmızı build'e çevrilmesi kodu değil altın kümeyi zayıflatma baskısı yaratır; ayrıca tam koşum pytest'in 60 sn zaman aşımına sığmaz.
- **Baseline raporu** (`evaluation/reports/all-baseline.{json,md}`) commit'lendi — sonraki her değişikliğin kabul kriteri bu sayılarla karşılaştırmadır, ve her koşuda değişen bir referans noktası referans noktası değildir. Ölçüm, deterministik katmanın **tasarlandığı alanda kusursuz, tasarlanmadığı alanda tamamen kör** olduğunu gösteriyor:
  - Niyet kapısı (114 vaka): macro F1 **0.7289**, eskalasyon **0.1842**. Kontrol kategorilerinin tamamı 1.00. Buna karşılık `inversion` **0.00** (8/8) — hepsi `source=keyword` ile `draft`'a düşüyor, çünkü `DRAFT_KEYWORDS` her şeyden önce kontrol ediliyor ve "taslak"/"resmi yazi"/"ust yazi" taslak *hakkındaki* sorularda da tetikleniyor; bugün "Resmi yazı ne demek?" üç adımlı taslak hattını başlatıyor. `precedence` **0.00** (6/6) — belge ekliyken "Merhaba" çekimser kalıyor (selamlama dalı `document_id is None` koşuluna bağlı), ve taslak turundan sonra "İyi akşamlar, yarın devam ederiz" süreklilik kuralı "devam" üzerinden tetiklendiği için `draft`'a düşüyor. `paraphrase_memory` 0.10, `paraphrase_analyze` 0.00, `paraphrase_draft` 0.12, `compound` 0.50.
  - Taslak kapısı (40 vaka): doğruluk **0.9000**, **yanlış pozitif oranı 0.2353**. `grounded`, `hallucinated`, `structural`, `placeholder` ve `other_official` kategorilerinin tamamı 1.00 — doğrulayıcı kümedeki her uydurma sayıyı, tarihi, kurumu ve atfı yakalıyor. Hata kütlesinin tamamı `paraphrased_grounded` (0.60) içinde ve dördü de saf biçim uyuşmazlığı: `1 Mart 2026` ↔ `01.03.2026`, `15 Nisan 2026` ↔ `15.04.2026`, `5 Şubat 2026` ↔ `05.02.2026`, `m. 11` ↔ `Madde 11`. Dördü de 88.0 puan alıyor — 70.0 otomasyon eşiğinin üstünde — ama `strict` herhangi bir dayanaksız ifadede onayı zorladığı için yine de işaretleniyor. **Her biri, doğru bir taslakta gereksiz bir HITL kesintisi.**

### Düzeltildi
- `evaluation/` klasörü `compose.yml`'de mount edilmiyor ve imaja kopyalanmıyordu; `tests/unit/evaluation/` bu hâliyle toplanamazdı bile. Mount, altın küme düzenlemelerinin yeniden build gerektirmemesi için ayrıca korundu.
- **Bilgi notu (bu sürümde çözülmedi)**: `resilience.py:53`'teki `NODE_TIMEOUT_SECONDS`'ın `writer: 120.0` ve `judge: 20.0` girdileri hiçbir yerde okunmuyor — `draft_graph.py` `node_timeout`'u import bile etmiyor, yani ~90 sn'lik taslak bütçesinin en pahalı adımının hiçbir düğüm seviyesi koruması yok. Tespit kaybolmasın diye kayda geçirildi.

## [1.24.0] - 2026-08-02
### Düzeltildi
- **Hafıza Sorusu → Belge Soru-Cevabına Yanlış Yönlendirme**: `planner.py`'deki `resolve_plan_deterministic`, bir belge eklenmişken "az önce ne sordum" gibi konuşmanın kendisine dair soruları salt "soru gibi görünüyor + belge var" sezgisiyle `document_qa`'ya yönlendiriyordu; bu akış sistem promptunda yalnızca belge bağlamına dayanmayı zorunlu kılıyor, konuşma hafızasını "kapsam dışı" sayıyordu. Yeni `MEMORY_RECALL_MARKERS`/`_is_memory_recall_question()` bu tür mesajları belge durumundan bağımsız olarak `chat`'e yönlendiriyor.
- **Asistan Cevapları Checkpoint'lenmiş Hafızaya Hiç Yazılmıyordu**: `execute_step_node`, `_run_chat`/`_run_document_qa`'nın döndürdüğü `history` girdisini (asistanın kendi cevabı) `chat_result`/`document_qa_result` içine gömüp hiçbir zaman üst seviye bir state güncellemesine yükseltmiyordu; bu yüzden `history` reducer'ı bunu hiç görmüyor, konuşma hafızasında yalnızca kullanıcı mesajları birikiyordu. Artık `history` her iki adımda da üst seviyeye taşınıyor.
### Eklendi
- **Kayan Pencere + Özet Hafıza**: `PlanningState`'e `history_summary`/`history_summarized_through` alanları eklendi; `consolidate_memory_node`, pencerenin (`HISTORY_WINDOW=12`) dışına yeteri kadar (`CONSOLIDATION_BATCH_SIZE=4`) tur çıktığında hızlı katman modeliyle (`MemorySummarizerAgent`) bu turları özetler. Ayrı bir depo/servis eklenmedi — aynı checkpoint'lenmiş state'in bir alanı (`HISTORY_RAW_CAP=40` ham tutma sınırı).
- `document_qa.md`/`chat.md` prompt şablonlarına, konuşma özetini belge bağlamından açıkça ayıran yeni bir bölüm eklendi (`{{history_summary}}`); `TEMPLATE_CONTRACTS` ve yeni `memory_summary` şablonu/ajanı (`MemorySummarizerAgent`) eklendi.
- Frontend: `localStorage`'da kalıcılaştırılan anonim istemci kimliği (`crypto.randomUUID()`), sayfa yenileme/yeni sekmede aynı checkpoint thread'inin (ve özetinin) yeniden kullanılmasını sağlıyor — gerçek kullanıcı kimlik doğrulaması değil, tarayıcıya özgü bir süreklilik.
### Değiştirildi
- `attachActiveDoc` varsayılanı `false` oldu; aktif belge artık her sohbet turuna varsayılan olarak eklenmiyor, kullanıcı onay kutusuyla açıyor.

## [1.23.0] - 2026-08-02
### Değiştirildi
- **Tek Docker Compose Dosyası**: Kökteki `compose.yml` ile `deploy/docker/docker-compose.dev.yml` aynı geliştirme ortamını tanımlayan, zamanla birbirinden sapmış iki ayrı dosyaydı (ör. `deploy/docker/docker-compose.dev.yml`'de `frontend` servisi ve `alembic`/`pyproject.toml` mount'ları hiç yoktu, `langfuse` imaj etiketi ise iki dosyada farklıydı). Artık tek ve kanonik dosya kökteki `compose.yml`; `docker compose` bu dosyayı ekstra bir `-f` bayrağına gerek kalmadan otomatik bulur ve `Makefile` zaten bunu varsayıyordu.
  - `langfuse` servis imajı `:2`den `:3`e hizalandı — backend'in kullandığı `langfuse` Python SDK'sı (v4) `:2` sunucusuyla uyumsuz.
  - Postgres kullanıcı adı/şifre/veritabanı adı, Grafana admin şifresi ve Langfuse `NEXTAUTH_SECRET`/`SALT`/`ENCRYPTION_KEY` değerleri artık sabit kodlanmış değil, `.env`'den `${VAR:-varsayılan}` deseniyle okunuyor; backend'in `DATABASE_URL`'i de aynı `POSTGRES_*` değerlerinden türetiliyor ki iki servis birbirinden sapmasın.
  - Kök `.env.example` bu değişkenlerin tamamını (daha önce yalnızca üç Ollama değişkeni ve eski bir `OLLAMA_MAX_TOKENS=1024` içeriyordu) güncel varsayılanlarla ve açıklayıcı yorumlarla kapsayacak şekilde yeniden yazıldı.
### Kaldırıldı
- `deploy/docker/docker-compose.dev.yml` (kökteki `compose.yml` ile tekilleştirildi) ve içeriği hiç doldurulmamış `deploy/docker/docker-compose.prod.yml` silindi.

## [1.22.0] - 2026-08-02
### Eklendi
- **Agent Düşünme Seviyeleri (Hızlı / Dengeli / Derin)**: Kullanıcının her istekte hız/kalite tercihini seçebilmesini sağlayan `reasoning_level` alanı eklendi (Claude'daki hızlı/derin düşünme modlarının eşdeğeri).
  - `app/core/enums/reasoning_level.py` (`ReasoningLevel`: `fast`/`balanced`/`deep`) ve `app/ai/reasoning_levels.py` (`get_reasoning_level_preset()`): her seviyenin model katmanı, Ollama "thinking mode" (`reasoning`), taslak deneme sayısı, kalite yargıcı açık/kapalı ve zaman aşımı çarpanını tek noktadan tanımlayan preset tablosu.
  - `draft_graph.py`'deki reflexion loop (writer → verify → judge → revise) artık `reasoning_level`'a göre davranıyor: `fast` tek denemede durur ve yargıcı atlar (zaten sıcak duran hızlı-katman modelini writer/reviser için de kullanarak), `deep` aynı kalite modelini "thinking mode" açık şekilde 3 denemeye kadar çalıştırır ve yargıcı zorunlu kılar. `balanced`, bugüne kadarki sabit davranışla (2 deneme, judge ayarına bağlı, thinking mode kapalı) birebir aynı — üçüncü bir model eklenmedi, 16GB RAM'li makinelerde zaten eşzamanlı yüklü iki model (kalite+hızlı) yeniden kullanıldı.
  - `planning_graph.py`, `chat_service.py`, `draft_service.py`: `reasoning_level` sohbet ve taslak uç noktalarından graph state'ine ve zaman aşımı hesaplamalarına taşınıyor; HITL "revise" aşamasında seviye yükseltme (ör. hızlıdan derine geçiş) desteği.
  - `ChatMessageRequest`, `ChatResumeRequest`, `DraftRequestSchema`: yeni opsiyonel/varsayılanlı `reasoning_level` alanı.
  - Frontend: sohbet girişi ve taslak formu yanında "Düşünme Seviyesi" seçici (`<select>`), mevcut yazışma-türü seçici deseniyle aynı stilde.
  - Kapsam dışı bırakılanlar (sonraki iş): `document_analysis_graph`/`routing_graph` seviyelendirmesi, best-of-N örnekleme, "otomatik" adaptif seviye, `/chat/resume` seviye-yükseltme arayüzü.

## [1.21.0] - 2026-08-01
### Değiştirildi
- **Docker Geliştirme Ortamı**: `backend.Dockerfile` artık `requirements.txt` yerine `requirements-dev.txt` kuruyor (yeni HITL entegrasyon testinin ihtiyaç duyduğu `pytest-cov`/`pytest-timeout`/`langgraph-checkpoint` imajda hiç yoktu) ve `alembic/`, `alembic.ini`, `pyproject.toml` dosyalarını imaja kopyalıyor. `compose.yml` aynı yolları `app/`/`tests/` ile aynı desende canlı volume olarak da bağlıyor; migration veya pytest yapılandırması değişiklikleri artık yeniden build gerektirmiyor.

### Düzeltildi
- **Docker İçinde Tam Test Koşusu**: Backend imajı build edilip `db`/`redis`/`qdrant`/`backend` servisleri ayağa kaldırılarak paket ilk kez uçtan uca `python -m pytest tests/` ile Docker içinde çalıştırıldı. Süreçte ortaya çıkan gerçek hatalar giderildi:
  - `RedisCache.close()` içinde artık deprecated olan `redis.asyncio.Redis.close()` çağrısı `.aclose()` ile değiştirildi. `warnings=error` politikası altında bu tek uyarı, `/documents/analyze` gibi `rate_limit()` arkasındaki herhangi bir uç nokta tetiklendiği an sonraki **tüm** testlerin teardown'ında art arda patlıyordu (227 hata).
  - `tests/conftest.py`'ye her testten sonra process-genelindeki Redis istemci referansını **kapatmadan** bırakan bir `autouse` fixture eklendi: bağlantının bağlı olduğu event loop (TestClient'in kısa ömürlü anyio-portal loop'u) teardown anında zaten kapanmış oluyor; kapatmayı denemek "Event loop is closed" hatasını "farklı loop'a bağlı" hatasıyla değiştirmekten öteye geçmiyordu.
  - `test_ollama.py`, `test_base_agent.py`, `test_qdrant.py`, `test_retrieval.py`, `test_user_router.py` içindeki, kodun güncel davranışından (num_ctx/keep_alive parametreleri, `{{çift parantez}}` prompt biçimi, koleksiyon boyutu doğrulaması, `datetime.utcnow()` deprecation, silinmiş `LLMReranker` testinden kalan ölü kod parçası) sapmış eski varsayımlar güncellendi.
  - `document_analysis_graph.py`'nin artık tek bir birleşik sınıflandırma+alan-çıkarım çağrısı yapması nedeniyle `test_document_analysis.py` tamamen bu tek çağrı etrafında yeniden yazıldı; iki ayrı ajanı (`ClassifierAgent`+`MetadataAgent`) mock'layan eski testler koleksiyonda hiç eşleşmiyordu.
  - `alembic upgrade head` ve `GET /api/v1/health?deep=true` (postgres/redis/qdrant/ollama/checkpointer hepsi `ok`) Docker içinde doğrulandı.
  - Sonuç: **621/621 test geçti.**

## [1.20.0] - 2026-08-01
### Eklendi
- **Görev 2 Uç Noktaları ve Ölü Kod Temizliği**:
  - `POST /api/v1/routing/suggest`: `POST /documents/draft`'tan bağımsız, sadece taslak metni + güven skoru okuyan tek başına birim-yönlendirme uç noktası. İnsan bir taslağı elle düzenledikten sonra yeni bir üretim ödemeden yönlendirme kararını tazeleyebilir.
  - `frontend/src/App.tsx` içine `judge`, `revise` ve `human_gate` düğümleri SVG aşama grafiğine eklendi; her biri artık kendi gerçek `node_start`/`node_end`/`interrupt` olaylarıyla besleniyor. Taslak oluşturma formu (`POST /documents/draft`'ı önceden hiç çağırmıyordu) ve eksik-bilgi/onay kesintileri için devam formu eklendi.
  - Sidebar artık `EvrakField`'in **15 alanının tamamını**, `missing_fields` listesini (önem derecesi + mevzuat atfıyla) ve `mevzuat_references`'ı gösteriyor — önceden yalnızca `tarih`/`sayı` görünüyordu.

### Kaldırıldı
- Hiçbir yerde kurulmayan `editor`/`evaluator`/`metadata`/`orchestrator`/`reflection` ajanları, `workflows/system_graph.py`, `infrastructure/providers/vllm.py` (LLM fabrikasındaki kayıtsız `"vllm"` dalıyla birlikte), `core/permissions/role_checker.py` (hiçbir middleware'in hiç doldurmadığı `request.state.user_role`'e bağımlıydı), sıfır route'lu `evaluation`/`feedback`/`settings` domain iskeletleri (9 dosya) ve iki 0 byte'lık worker betiği (`workers/cleanup.py`, `workers/embedding.py`) silindi.
- `ai/retrieval/reranker.py` (`LLMReranker`) kaldırıldı: ~90 sn'lik taslak gecikme bütçesinin kritik yolunda, bu küçüklükteki bir korpusta 3 sonucu yeniden sıralamak hiçbir zaman kalitenin belirleyicisi olmadı.
- İlk EventBus abonesi (`document.analyzed` → yapılandırılmış log satırı) kaydedildi; `DocumentService`/`DraftService`'in `publish()` çağrılarının artık gerçek bir dinleyicisi var.

## [1.19.0] - 2026-08-01
### Eklendi
- **Tipli SSE Olay Sözleşmesi ve Gözlemlenebilirlik**:
  - `emit_node_error`/`emit_node_skipped`/`emit_interrupt` ve kuyruk başına monotonik bir `seq` sayacı eklendi; istemci olayları sıralayabiliyor ve `interrupt()` içeren bir düğümü resume ederken oluşan tekrar (replay) olayını tekilleştirebiliyor.
  - `event_schema.py`: on SSE olay tipinin şeklini bir kez, Pydantic modelleriyle yazan sözleşme dosyası; `test_event_contract.py` sıfır kod üretimi (codegen) kurmadan bu sözleşmeyi doğruluyor.
  - `CorrelationIdMiddleware` (en dıştaki middleware, `X-Request-ID`) eklendi ve bir `ContextVar` aracılığıyla `JSONFormatter`'a bağlandı; yapılandırılmış loglar artık gerçekten yapılandırılmış (tek bir önceden biçimlendirilmiş mesaj string'i değil).
  - `observability/ai_metrics.py`: düğüm/LLM süresi, token sayımı, taslak skorları, revizyon sayısı, yargıç hataları, HITL kesinti/devam sayaçları, yapılandırılmış-çıktı yeniden deneme sayaçları — `BaseAgent` ve olay yayıcılarına bağlandı.
  - `GET /api/v1/health?deep=true`: Postgres/Redis/Qdrant/Ollama/checkpointer'ı zaman aşımı altında sınayan, hiçbir şeyi kontrol etmeyen eski kimliksiz `/health`'in yerini alan birleşik derin sağlık kontrolü.
  - `build_trace_config()`: üç yerde birebir kopyalanmış `_trace_config` mantığını tek noktaya topladı.
- **Prompt Enjeksiyonu Guardrail'leri ve Sınır Doğrulaması**:
  - `scrub_extracted_text()`: çıkarılan evrak metninden sıfır-genişlikli/bidi kontrol karakterlerini ve Türkçe/İngilizce talimat-geçersizleştirme satırlarını temizler; çıkarımdan hemen sonra, `char_count` eşiği çalışmadan önce uygulanır — yüklenen bir PDF sistemin bakış açısından saldırgan kontrolündeki bir girdidir.
  - `assert_no_prompt_leak()` artık `BaseAgent.run_structured()`'da da çalışıyor (önceden bu yolda ölüydü); yazar/revizör/sınıflandırıcı ajanları görünür bir sızıntıda denemeyi kapalı şekilde başarısız sayıp otomatik bir revizyon yerine insan incelemesine yönlendiriyor.
  - `validate_storage_path()`: kimlik doğrulaması gerektirmeyen bir uç noktada, istemcinin verdiği `storage_path` ile `storage.get_file(...)` arasında başka hiçbir engel yoktu — biçimsel olmayan bir path-traversal okuma ilkelliğiydi.
  - `DraftClassificationSchema`: `DraftRequestSchema.classification` artık prompt'a doğrudan giden serbest bir `dict` değil, taslak akışının gerçekten tükettiği dar ve tipli bir alan kümesi.
  - `_read_bounded()`: yükleme 1 MiB'lik parçalar hâlinde okunuyor ve çalışan toplam limiti aştığı an reddediliyor; önceden tüm gövde boyut kontrolü hiç çalışmadan belleğe alınıyordu.
  - `BaseAgent.__init__`'ten ölü `tools` parametresi kaldırıldı — saklanıyordu, hiç okunmuyordu, bu kod tabanındaki hiçbir ajan tool-calling kullanmıyor.

## [1.18.0] - 2026-08-01
### Eklendi
- **Postgres Checkpointer Üzerinde HITL (Human-in-the-Loop) Kesinti/Devam**:
  - Eksik Alembic iskeleti tamamlandı: `alembic.ini` hiç yoktu, `env.py`/`script.py.mako` 0 byte'tı, `users`/`invited_emails` tabloları için bile bir baseline migration yoktu. `env.py`, `checkpoint%` tablolarını `include_object` ile dışlıyor; bu tabloları `AsyncPostgresSaver.setup()` kendi `CREATE TABLE IF NOT EXISTS` mantığıyla yönetiyor.
  - `infrastructure/checkpointing/` eklendi: en-iyi-çaba (best-effort) init/close bir `AsyncExitStack` etrafında — `AsyncPostgresSaver.from_conn_string()` kendisi bir async context manager olduğu için doğrudan `await` edilip bir kenara bırakılamaz.
  - `planning_graph`'a, taslak adımını çalıştıran `executor` düğümünden **ayrı** yeni bir `human_gate` düğümü eklendi: `interrupt()` kendi düğümünü resume'da baştan tekrar çalıştırır; `execute_step_node` içinde olsaydı resume, executor'ın state'e zaten yazdığı ~30 sn'lik taslak üretimini tekrarlardı.
  - `thread_id = session_id` `chat_service`/`chat` router'ı boyunca bağlandı; `POST /chat/resume`, `POST /chat/resume/sync`, `GET /chat/sessions/{id}/state` ve `ChatResumeRequest` (`answer`/`approve`/`revise`/`reject`) eklendi.
  - Yalnızca `planning_graph` bir checkpointer alıyor — dört alt graf `execute_step_node` içinden `.ainvoke()` ile çağrılıyor, düğüm olarak kayıtlı değiller; üzerlerine checkpointer koymak ilgisiz, öksüz checkpoint soyağaçları başlatırdı.
- **Checkpoint'lenmiş Graf State'i Üzerinden Konuşma Hafızası**:
  - `CheckpointMemory`: `planning_graph.aget_state()` üzerine ince, salt-okunur bir görünüm. `thread_id` zaten `session_id`'ye eşit ve checkpointer geçmişi, kesinti payload'ını ve her şeyi zaten tutarlı biçimde saklıyor.
  - Planlayıcıya kısa-onay devam kuralı eklendi: bir taslak/analiz teklifinden sonra "evet, hazırla" artık düz sohbete düşmek yerine o niyeti sürdürüyor; 6 kelimelik bir mesaj sınırı ve yalnızca belirsiz olmayan bir devam eylemi olan iki niyetle (`draft`/`analyze`) sınırlı.

### Kaldırıldı
- `ConversationWindowMemory`/`SummaryMemory`/`VectorMemory` kaldırıldı: checkpointer'ın yanında ikinci bir Redis tabanlı depo, çökme anında ikisi arasında bölünen bir yazma riski taşıyordu ve periyodik özet üretimi ~90 sn'lik bütçeyi zorlardı.

## [1.17.0] - 2026-08-01
### Eklendi
- **Hibrit Kalite Kapısı ve Sınırlı Taslak Reflexion Döngüsü**:
  - `judge_draft()`/`merge_verdicts()`: regex'in göremediği şeyler (talebe uygunluk, arz/rica yönü, resmî üslup, muhatap tutarlılığı) için deterministik doğrulayıcının üzerine hızlı-katman bir LLM yargıcı eklendi. Birleşik skor `0.6*deterministik + 0.4*yargıç`; herhangi bir kritik bulgu veya "talebi karşılamıyor" kararı skoru otomasyon eşiğinin altına sabitliyor.
  - `build_missing_info_request()`/`apply_answers()`: bir taslağın `[...]` yer tutucularının deterministik, LLM'siz biçimde insan tarafından cevaplanabilir sorulara dönüştürülmesi ve taslağı yeniden üretmeden cevaplandıktan sonra devam edilmesi.
  - `draft_graph` yeniden kuruldu: `validate_input → writer → verify → revise → writer`, `MAX_DRAFT_ATTEMPTS=2` ile sınırlı. Düzeltilebilir kusurlar (eksik yapı, doğrulanamayan iddialar, düzeltilebilir yargıç bulguları) yeni bir `ReviserAgent` üzerinden döngüye giriyor; kalan bir yer tutucu veya çözülememiş bir yazışma türü aynı boşluğa tekrar denemek yerine doğrudan insan incelemesine gidiyor.
  - `_build_repair_prompt` her zaman brief'in tamamını + önceki taslağı + numaralı kusur listesini gönderiyor — `num_ctx` içinde rahatça kalıyor, yazar zaten ham `source_document`'i hiç görmüyordu.
- **Yeniden Deneme/Zaman Aşımı Politikası ve Üçüncü Katman Analiz Yedeği**:
  - `resilience.py`: `RetryPolicy`'yi import eden tek yer (sürümler arası `langgraph.pregel`↔`langgraph.types` taşınmasına karşı), `LLM_RETRY`/`IO_RETRY` ve `node_timeout()`. Bilerek `writer`/`revise` düğümlerine uygulanmıyor — zaten token yayınlamış bir düğümü yeniden denemek bunları UI'a tekrar oynatırdı.
  - `document_analysis_graph` artık isteğe bağlı bir `fast_llm_client` alıyor: kalite katmanı hem birleşik hem yalnız-sınıflandırma çağrısında başarısız olursa, `DocumentType.OTHER`'a düşmeden önce hızlı katmanda bir kez daha deneniyor.
  - `retrieve_mevzuat_node` artık `"rag"` id'si altında gerçek `node_start`/`node_end` yayıyor (getirilen belgeler ve render edilmiş bağlamla birlikte) — önceden hiçbir şey yaymıyordu ve bu, frontend'in Mevzuat panelinin hep boş kalmasının kök nedeniydi.

## [1.16.0] - 2026-08-01
### Değiştirildi
- **Bağımlılık ve Araç Zinciri Yükseltmesi**: `langgraph`, `interrupt`/`Command`/`RetryPolicy` garanti eden bir sürüm aralığına sabitlendi; `langgraph-checkpoint-postgres`, `psycopg[binary,pool]`, `prometheus-client` eklendi. `pytest-cov`/`pytest-timeout` ve tutarlı async test davranışı için `[tool.pytest.ini_options]` (asyncio_mode=auto, testpaths, timeout) eklendi. Frontend'e eslint + typescript-eslint, vitest + testing-library eklendi (`npm run lint` daha önce çalışacağı bir yapılandırmaya bile sahip değildi).
- **Prompt Yöneticisi ve Şablon Seti Konsolidasyonu**:
  - Modül seviyesi `prompt_manager` tekil örneği kaldırıldı; `get_prompt_manager()` artık tek giriş noktası. `TEMPLATE_CONTRACTS` + `declared_placeholders()` eklendi; her şablonun `{{placeholder}}` kümesi, ilgili ajanın gerçekten sağladığıyla karşılaştırılıyor.
  - `orchestrator.md`/`metadata.md`/`editor.md`/`evaluator.md`/`reflection.md` şablonları silindi (hiçbir ajan tarafından referans verilmiyorlardı ya da artık çalışmayan bir akışı tanımlıyorlardı); `judge.md` ve `reviser.md` eklendi. `chat.md`'nin kaldırılmış bir "editör ve kendini denetleme" aşamasını kullanıcıya duyuran metni düzeltildi.
  - Yeni `test_prompt_templates.py`: her şablonun deklare edilip edilmediğini, diskte var olup olmadığını ve tam olarak bir ajan modülü tarafından referans verilip verilmediğini doğrulayan iki yönlü sözleşme testi — beş öksüz şablonu tam olarak yakalayacak türden bir kontrol.

## [1.15.0] - 2026-07-31
### Eklendi
- **SparseBM25Encoder**: Türkçe karakter duyarlı ve CRC32 hash tabanlı, yerel olarak çalışan matematiksel bir BM25 Sparse Vector Encoder eklendi (`app/ai/retrieval/sparse_encoder.py`).

### Değiştirildi
- **Yazım Akışının Sadeleştirilmesi**: `draft_graph.py` içindeki hantal ve yavaş döngüsel `Writer -> Editor -> Reflection -> Evaluator` yapısı kaldırıldı. Bunun yerine Editor ajanı `final_draft`, `confidence_score` ve `requires_human_approval` değerlerini tek bir Structured Output olarak döndürecek şekilde güçlendirildi ve akış `Writer -> Editor -> END` doğrusal yapısına sadeleştirildi. Ajan sayısının azaltılmasıyla taslak oluşturmadaki LLM gecikmesi yarı yarıya düşürüldü.
- **Strict Yönlendirme (Routing) Sınırlandırması**: `routing_graph.py` içindeki `destination` alanı serbest metinden `Literal` enum tipine dönüştürülerek modelin uydurma birim isimleri üretmesi (halüsinasyon) engellendi.
- **Qdrant Native Hybrid Search**: Python tarafında yavaş çalışan ve API başlangıcında tüm mevzuat korpusunu diskten okuyup tokenleştiren eski BM25 mekanizması tamamen kaldırıldı. Bunun yerine Qdrant'ın native **Prefetch** ve **RRF (Reciprocal Rank Fusion)** arama yetenekleri entegre edildi. Arama hızı artırıldı ve API/worker başlangıç süresi milisaniyeler seviyesine düşürüldü.

### Düzeltildi
- **Birim Testleri ve İçe Aktarma Hataları**: Yeni akışlara ve HybridRetriever/QdrantStore imzalarına uygun şekilde `test_retrieval.py` ve `test_workflows.py` güncellendi; tüm testler (`446 passed`) başarıyla tamamlandı.

## [1.14.0] - 2026-07-31
### Eklendi
- **Geçici Karar Destek Arayüzü ve LangGraph Canlı Akış Görselleştirme**:
  - **Canlı Grafik Akışı (Graph Visualizer)**: Karar verici Master Planning Graph (Supervisor, Sınıflandırma, RAG, Taslak, Yönlendirme vb. düğümleriyle) akışının anlık durumunun (çalışıyor, tamamlandı, atlandı) SVG grafiği üzerinden canlı takibi sağlandı. Çakışmayan simetrik grid yerleşimi, durum duyarlı (glowing green/pulsing orange) dinamik bağlantı çizgileri, metin hizalamaları ve düğümlere tıklandığında (çalışma tamamlanmasa bile) durum ve açıklamalarını gösteren interaktif detay paneli eklendi.
  - **Dosya Yükleme ve Yönetimi**: Drag-and-drop / tıklayarak dosya yükleme (`/documents/analyze`), yüklü evrakların listelenmesi (`GET /documents`) ve yerel json tabanlı metadata persistence sistemi kuruldu.
  - **Sohbet ve SSE Akışı**: `/chat/stream` SSE uç noktası eklenerek arayüzün sohbet ederken karar akışını anlık izleyebilmesi ve log konsolunda durum güncellemelerini yazdırabilmesi sağlandı.
  - **Frontend Dockerization**: React + TS + Vite frontend uygulaması için `frontend.Dockerfile` ve `nginx.conf` oluşturuldu; `compose.yml` dosyasına HMR uyumlu `frontend` servisi eklendi.
  - **Yazım Akış ve Ajan Mimari Optimizasyonu**:
    - **Briefing Agent / Context Builder Pattern**: Taslak yazma grafiğinde (`draft_graph.py`) **Writer'a tüm OCR veya ham doküman içeriğini doğrudan geçme** yapısı değiştirildi. `validate_input_node` içinde deterministik olarak hazırlanan ve sadece gerekli özet, çıkarılan kritik NER verileri, mevzuat ve kullanıcı yönergelerini barındıran **temiz bir 'Brief'** oluşturuldu. Writer, Editor, Reflection ve Evaluator ajanlarının tamamı ham metin yerine sadece bu temiz brief'i girdi alacak şekilde güncellendi.
    - **Yazım Akış Sadeleştirmesi**: Gereksiz LLM döngüleri azaltıldı. Editör onaylarsa `reflection` düğümü atlanarak doğrudan değerlendirmeye gidilir, reddedilirse editör geri bildirimiyle tek bir revizyon yapılıp değerlendirilir. LLM girdi boyutu ve çağrı sayısı azaltılarak işlem süreleri dramatik ölçüde düşürüldü ve doğruluk arttırıldı.

    - Konsol Düzeni İyileştirmesi: Karar akış konsolu sohbet akışı içerisinden çıkarılarak sohbet giriş alanının hemen üstüne sabitlendi. Böylece iç içe kaydırma (nested scrollbar) ve konsolun en altta sıkışıp okunamaz hale gelmesi sorunu giderildi.
    - Chat Asistanı Odaklanması: Chat ajanı (`chat.md` şablonu) KACHOW EKDS yeteneklerini (sınıflandırma, mevzuat, taslak, sevk, soru-cevap) tanıtacak ve sistemle ilgili soruları yanıtlayacak şekilde kurumsallaştırıldı. Sistem dışı soruları reddetmesi sağlandı.

### Değiştirildi
- **Doğrulama Ajanı (Verifier Agent) İş Akışından Çıkarıldı**:
  - `rag_graph.py` içindeki `verify_node` LLM tabanlı doğrulama yapmak yerine doğrudan `SUFFICIENT` durumu döndürecek şekilde güncellendi. Bu sayede gereksiz LLM doğrulama adımları ve sorgu tekrar yazma/arama döngüleri bypass edilerek RAG gecikmesi (latency) azaltıldı.
  - Ajan sınıfları (`verifier.py`) ve şablonları (`verifier.md`) dosya sisteminde korunmaya devam edildi.
  - RAG birim testi (`test_workflows.py`), verifier agent bypass edilerek tek bir `run_structured` (sorgu zenginleştirme) çağrısı bekleyecek şekilde güncellendi ve `BaseAgent.run_structured` doğrudan mock'landı.

### Düzeltildi
- **Serileştirme Hatası**: LangGraph'in `draft` adımında mevzuat `Document` nesnelerinin JSON serileştirilememesinden kaynaklanan `TypeError` hatası, `_format_classification` fonksiyonu içinde nesnelerin önceden temizlenmesi mantığı eklenerek giderildi.
- **Arayüz Kaydırma Hatası**: Karar akışı log konsolu büyürken chat alanının otomatik olarak en alta kaydırılmaması ve logların sıkışık kalması sorunu, `App.tsx` içindeki useEffect bağımlılık dizisine `currentLogs` eklenerek çözüldü.
- **Zaman Aşımı ve Performans İyileştirmeleri**:
  - Uzun evraklarda LLM bağlam şişmesini önlemek için `draft_graph` yazıcısına giden kaynak evrak metni başından 3500 ve sonundan 1500 karakter kalacak şekilde (toplam max 5000 karakter) otomatik kırpılacak şekilde optimize edildi.
  - Backend içindeki `AI_WORKFLOW_TIMEOUT_SECONDS` sabiti 300 saniyeye çıkarıldı.
  - `nginx.conf` proxy zaman aşımı süreleri (`proxy_read_timeout`) 600 saniyeye yükseltildi ve SSE (Server-Sent Events) akışının anlık iletilmesi için Nginx tamponlaması (`proxy_buffering off`) kapatıldı.

## [1.13.0] - 2026-07-30
### Eklendi
- **Deterministik Alan Ayrıştırıcı (`ai/compliance/field_parser.py`)**: Resmî Yazışmalar Yönetmeliği evrak başlığının biçimini zorunlu kıldığı için, etiketli alanlar (`Sayı:` m.11, `Tarih:` m.12, `Konu:` m.13, `İlgi:` m.15, `Ek:` m.18, `Adres:`, `Gizlilik Derecesi:`, `İvedilik:`) ve konumla belirlenen alanlar (başlık m.10, muhatap m.14, imza bloğu m.17) düzenli ifadelerle okunur. Ayrıştırılan değerler model çıktısını ezer.
- **Alan Çıkarımı Değerlendirme Betiği**: `scripts/evaluate_extraction.py`, alan bazında `correct` / `missed` / `wrong` / `spurious` dağılımını raporlar.

### Değişti
- **Alan Çıkarımı Düğümü**: Artık önce deterministik ayrıştırma çalışır, model yalnızca kalan alanlarla ilgilenir ve sonuçlar birleştirilirken ayrıştırılan değer öncelik alır. Model çağrısı hata verse bile ayrıştırılan alanlar korunur.

### Düzeltildi
- **Alan Çıkarımı Doğruluğu**: `qwen3:8b` ölçümünde tek alan istendiğinde `sayi` doğru dönerken üç alan birlikte istendiğinde `null` dönüyor, başka bir alan ise üretim bütçesi bitene kadar tekrar eden belirteç döngüsüne giriyordu; model şema genişledikçe bozuluyordu. Etiketli ve konumsal alanların modelden alınmasıyla:
  - genel çıkarım doğruluğu **%28,4 → %98,5**
  - kayıp alan sayısı **48 → 0** (yanlış "eksik bilgi" uyarısı üretmeyen ilk sürüm)
  - `sayi`, `muhatap`, `imza_sahibi`, `imza_unvani` alanları **%0 → %100**
- **Gerçek Türkçe Belgelerle Doğrulama (OCRTurk)**: `scripts/evaluate_ocr_benchmark.py` eklendi; 180 gerçek Türkçe belgeden oluşan [OCRTurk](https://github.com/metunlp/ocrturk) kıyaslama kümesi (tez, dergi, EBA, TCMB, SBB kaynaklı) üzerinde çıkarım zincirini ölçer. Küme lisans dosyası içermediği için **depoya eklenmemiştir**; betik harici bir kopyayı işaret eder.
  - Born-digital çıkarım (180 belge): `opendataloader` NED 0,162 / TRchar 0,795 (42 sn), `pdfium` NED 0,167 / TRchar 0,738 (1 sn). Zincirdeki mevcut sıralama (opendataloader önce) Türkçe karakter sadakati bakımından doğrulandı.
  - Bozulmuş tarama (8 belge): `tesseract` NED 0,474 / tokF1 0,411, `glm-ocr` NED 0,207 / tokF1 0,789. Okunabilirlik eşiği **8/8 belgede** doğru biçimde yükseltme tetikledi (tesseract kalite 0,41–0,58 < 0,60). Sentetik veriyle ayarlanan eşik gerçek belgelerde de geçerli.
  - **Sıradan bağımsız metrik eklendi**: NED ve TRchar sıra duyarlıdır; çok sütunlu bir sayfada doğru okunmuş metin farklı sırada olduğu için NED 0,63 ve TRchar 0,00 alabiliyor. Aynı çıktının token örtüşmesi (tokF1 0,886) rakip motordan daha iyiydi. Bu nedenle betik tokF1'i birlikte raporlar.
- **Görsel Dil Modeli ile OCR (`infrastructure/extractors/vision.py`)**: Bozulmuş taramalar için Ollama üzerinden `glm-ocr` kullanan `OllamaVisionExtractor` eklendi ve zincire Tesseract'tan sonra yerleştirildi. Ölçüm: temiz 300 DPI çıktıda Tesseract hem daha doğru hem ~67 kat hızlı (alan geri çağırma %100 / %98,3; 4 sn / 269 sn). Fotokopi benzeri bozulmuş taramada ise Tesseract çöküyor (karakter doğruluğu %43,6, alan geri çağırma **0/29**) buna karşılık `glm-ocr` ayakta kalıyor (%97,4, **29/29**). Bu nedenle Tesseract hız için önde tutuldu, görsel model yalnızca okunabilirlik denetimi başarısız olduğunda devreye giriyor.
- **Okunabilirlik Sinyali**: `ExtractedDocument.quality_ratio` (üç ve daha uzun belirteçlerin oranı) eklendi ve `FallbackDocumentExtractor` artık hem uzunluk hem okunabilirlik eşiğini arıyor. Yalnızca karakter sayısına bakmak yetersizdi: bozulmuş bir taramada Tesseract 758 karakterlik anlamsız çıktı üretiyor, 200 karakter eşiğini rahatça geçiyor ve zincir orada durup hiçbir başlık alanı bulamıyordu. Yeni sinyalle aynı belge görsel modele yükseltiliyor ve 8/8 alan kurtarılıyor; temiz taramalar 0,5 sn'de Tesseract'ta kalmaya devam ediyor.
- **Ayrıştırıcı Yetkisi Çift Yönlü Hâle Getirildi**: Mevzuatın biçimini zorunlu kıldığı alanlarda (`sayi`, `tarih`, `konu`, `ilgi`, `ekler`, `muhatap`, `gonderen_kurum`, `imza_sahibi`, `imza_unvani`) ayrıştırıcı bir değer bulamadıysa alan gerçekten yok demektir; modelin bu alan için ürettiği değer artık atılır. Önceden yalnızca ayrıştırıcının *bulduğu* değer modeli eziyordu. Sonuç: uydurulan alan sayısı `qwen3.5:9b` üzerinde **2 → 0**, `qwen3:8b` üzerinde **8 → 0**. Sunumu mevzuatça belirlenmemiş alanlar (`adres`, `iletisim`, `gizlilik_derecesi`, `ivedilik`, `basvuran_adi`) kapsam dışıdır; bunlarda ayrıştırıcının bulamaması 'yok' değil 'bilinmiyor' anlamına gelir.
- **Varsayılan Model Üzerinde Doğrulama**: Ölçümler projenin varsayılan modeli `qwen3.5:9b` ile yinelendi. Tür doğruluğu **%91,7**, uçtan uca eksik alan eşleşmesi **%75,0** (`qwen3:8b` üzerinde sırasıyla %83,3 ve %25,0). Tek sınıflandırma hatası `circular → official_letter` olup aynı kural tablosu kullanıldığı için uygunluk sonucunu etkilemez. Ayrıştırıcı bu modelde de kazanç sağlar: yalnız model %94,0, ayrıştırıcıyla %97,0; `muhatap` %60 → %100 ve çıkarım süresi yaklaşık üçte bir kısalır. Uçtan uca gecikme 37,6 sn/belge.
- **Boş Etiket Yakalaması**: Boş bir `Konu :` satırı, sonraki satırın metnini değer olarak yakalıyordu; iki nokta çevresinde yalnızca boşluk ve sekme kabul edilerek giderildi.
- **Tarih İçeren Liste Ayrıştırması**: `İlgi : 01.01.2026 ...` değerinde `01.` bir madde işareti sanılıp tarihin günü kaybediliyordu.
- **Langfuse Sürüm Uyumsuzluğu**: `observability/tracer.py` v3 içe aktarma yolunu (`langfuse.langchain`) kullanırken `requirements.txt` hâlâ `<3.0.0` sınırını taşıyordu; bu nedenle `main` üzerinde test paketi toplama aşamasında `ModuleNotFoundError` ile kırılıyordu. Bağımlılık `langfuse>=3.0.0` olarak güncellendi ve v3 SDK'nın v2 sunucusuyla desteklenmemesi nedeniyle `compose.yml` ile `docker-compose.dev.yml` içindeki sunucu imajı `langfuse/langfuse:3` olarak hizalandı.
- **İmzasız Dilekçe**: Belgenin sonundaki yalın ad, imza sayılıp gerçek bir 3071 s.K. m.4 eksikliğini gizliyordu. Artık imza için doğrulayıcı kanıt (unvan satırı, açık `İmza` ibaresi veya kurum anteti) aranır. Türkçe büyük İ harfinin `lower()` sonucu `imza` olmadığı için karşılaştırma katlama ile yapılır.

## [1.12.0] - 2026-07-30
### Eklendi
- **Genişletilmiş Birim Test Kapsamı ve Hata Düzeltmeleri** (#51):
  - MCP Modülü, Kullanıcı Alanı (Repository, Service, Router), Altyapı Modülleri (Redis, S3, Qdrant), Gözlemlenebilirlik (Tracer, Logger, Metrics) ve Paylaşılan Olay/Doğrulama (Event Bus, Publisher, Subscriber, Pagination DTO, Validators) katmanları için kapsamlı unit testleri yazıldı.
  - Langfuse `CallbackHandler` başlatma sırasında ortaya çıkan ve `secret_key` parametresini geçersiz kabul eden bir hata giderildi. Artık anahtarlar `os.environ` üzerinden yönetiliyor.
  - Davetiyeler oluşturulduktan sonra `SuccessResponse` dönerken kaynak kodunda yer alan `message` parametresi hatası giderildi.
  - `requirements.txt` dosyasına `fastmcp` ve `langchain` bağımlılıkları eklendi.

## [1.11.0] - 2026-07-30
### Eklendi
- **Görev 2: Resmî Yazı Taslaklama ve Birim Yönlendirme**:
  - `DraftService` oluşturularak RAG'den gelen bağlam üzerinden uygun resmi yazı taslağının oluşturulması sağlandı.
  - Taslak onayı gerektirmeyen durumlarda `RoutingGraph` üzerinden doğru birim ve kişilere yönlendirme önerisi sunulması altyapısı kuruldu.
  - İlgili servis için `POST /api/v1/documents/draft` uç noktası eklendi ve bağımlılıkları `dependency.py` üzerinden yapılandırıldı.
- **Görev 3: Chat Arayüzü ve Planlama Orkestratörü**:
  - Kullanıcı ile doğrudan iletişime geçebilmesi için basit `ChatAgent` ve `chat.md` sistem promptu eklendi.
  - Gelen taleplerin, basit bir soru mu yoksa evrak/mevzuat işi mi olduğuna karar veren Ana Orkestratör (`planning_graph.py`) devreye alındı. Orkestratöre `chat` yeteneği kazandırıldı.
  - `ChatService` ve `POST /api/v1/chat/message` uç noktası eklenerek uçtan uca LangGraph entegrasyonu tamamlandı.

### Kaldırıldı
- Miadını doldurmuş olan eski `classification_graph.py` iş akışı silindi ve bağımlılıkları temizlendi. (`ner.py` istisna olarak korundu).

## [1.10.0] - 2026-07-30
### Eklendi
- **Görev 1: Evrak Sınıflandırma ve İçerik Analizi** (#41):
  - **Metin Çıkarma Katmanı (`infrastructure/extractors/`)**: `BaseDocumentExtractor` soyutlaması ve `ExtractedDocument` sözleşmesi eklendi. Dört uygulama: `OpenDataLoaderExtractor` (birincil, Apache-2.0, düzen/tablo farkındalıklı, Java 11+ gerektirir), `PdfiumExtractor` (Java gerektirmeyen yedek), `TesseractExtractor` (Türkçe OCR, 300 DPI, `--psm 6`) ve `PlainTextExtractor`. `FallbackDocumentExtractor` eşik altı sonuçlarda zinciri ilerletir; `supports()` denetimi düz metin çıkarıcısının PDF baytlarını bozuk karaktere çevirip eşiği geçmesini engeller.
  - **Evrak Alanları ve Uygunluk Denetimi (`ai/compliance/`)**: Resmî evrak üstveri alanları (`EvrakField`: sayı, tarih, konu, muhatap, gönderen kurum, ilgi, ekler, imza sahibi/unvanı, gizlilik derecesi, ivedilik, başvuran, adres, iletişim) ve evrak türüne göre zorunlu/önerilen alan kural tablosu (`REQUIRED_FIELD_RULES`) eklendi. Eksik bilgi tespiti tamamen deterministik Python ile yapılır; LLM yalnızca alan çıkarımından sorumludur. `BLANK_VALUE_MARKER`, modelin `null` yerine yazdığı "Belirtilmemiş", "Yok", "-" gibi değerleri Türkçe karakter katlaması ile yakalar.
  - **Madde Atıfları**: Kural tablosundaki madde numaraları mevzuat.gov.tr üzerindeki resmî Yönetmelik metninden doğrulandı (Başlık m.10, Sayı m.11, Tarih m.12, Konu m.13, Muhatap m.14, İlgi m.15, İmza m.17, Ek m.18).
  - **Yeni Enum'lar**: Gelen evrak taksonomisi için `DocumentType` (10 üye) ve uygunluk durumu için `ComplianceStatus` eklendi. `DocumentType`, üretilen yazışma türünü modelleyen mevcut `CorrespondenceType`'tan kasıtlı olarak ayrı tutulmuştur.
  - **Evrak Analiz İş Akışı (`ai/workflows/document_analysis_graph.py`)**: `classify → extract_field → check_compliance → retrieve_mevzuat → suggest_mevzuat`. Mevcut `classification_graph.py` değiştirilmedi; retriever isteğe bağlıdır ve verilmediğinde mevzuat düğümleri devre dışı kalır.
  - **`ComplianceAgent`**: 11. uzman ajan ve Türkçe `compliance.md` şablonu eklendi; şablon yalnızca sunulan alıntılara dayanmayı zorunlu kılar.
  - **Mevzuat Korpusu (`datasets/mevzuat/`)**: Resmî Yazışmalarda Uygulanacak Usul ve Esaslar Hakkında Yönetmelik (18 madde), 3071 sayılı Dilekçe Hakkı Kanunu ve 4982 sayılı Bilgi Edinme Hakkı Kanunu metinleri eklendi.
  - **Korpus Yükleyici ve İndeksleme**: `retrieval/corpus_loader.py`, `workers/indexing.py` ve `scripts/index_mevzuat.py` eklendi. Yükleyici, indeksleme worker'ı ile BM25 bağımlılığı arasında paylaşılır; RRF tam `page_content` eşitliğine göre tekilleştirdiği için iki yolun birebir aynı parçaları üretmesi zorunludur.
  - **Uç Nokta**: `POST /api/v1/documents/analyze` (multipart) eklendi. Mevcut `validate_file_extension`, `ALLOWED_FILE_TYPES`, `MAX_FILE_SIZE_BYTES`, `BaseStorage` ve `event_bus` altyapısı yeniden kullanıldı; `DocumentUploadedEvent` ve `DocumentAnalyzedEvent` yayımlanır.
  - **Sentetik Evrak Veri Kümesi (`datasets/sample/`)**: 12 kurgu evrak; her biri `.txt` (kaynak metin), `.json` (beklenen tür, alanlar ve eksik alanlar) ve `.pdf` üçlüsü olarak eklendi. `evrak_11` alanların biçimsel olarak var ama içerik olarak boş olduğu (`Belirtilmemiş`, `-`) durumu, `evrak_12` ise metin katmanı bulunmayan taranmış görüntü ile OCR yolunu sınar. Küme üç uygunluk durumunun tamamını kapsar. Şartname 6.5 uyarınca gerçek kamu verisi kullanılmamıştır; tüm kişi, adres ve sayı bilgileri açıkça sentetiktir.
  - **PDF Üretici**: `scripts/generate_sample_evrak.py`, `.txt` kaynaklarından PDF üretir; Türkçe karakterlerin boş görünmemesi için Unicode TTF kaydı zorunludur ve font bulunamazsa betik hata verir.
  - **Biçimsel İşaret Tespiti (`ai/compliance/signal.py`)**: Belgenin kurum tarafından düzenlendiğini gösteren yapısal işaretler (T.C. anteti, `Sayı:` alanı, `İlgi:` alanı, `DAĞITIM` bölümü, imza bölümünde kurumsal unvan) regex ile deterministik olarak tespit edilir ve sınıflandırma istemine olgu olarak eklenir. Model kararını ezmez, yalnızca bilgilendirir. `qwen3:8b` üzerinde ölçülen etki: tür doğruluğu %66,7 → %83,3; resmî yazıyı dilekçe sanma hatası (yanlış kural tablosunun uygulanmasına yol açan zararlı hata biçimi) ortadan kalktı.
  - **Sınıflandırma Değerlendirme Betiği**: `scripts/evaluate_classification.py`, sentetik küme üzerinde tür doğruluğunu ve uçtan uca eksik alan eşleşmesini ölçer.
  - **Birim Testleri**: 180 yeni test eklendi (`test_extractor.py`, `test_compliance.py`, `test_document_analysis.py`, `test_document_service.py`, `test_document_endpoint.py`). Toplam 285 testin tamamı geçiyor. Veri kümesi güdümlü parametrik testler, taahhüt edilen beklenen sonuçları kural tablosuyla her çalıştırmada karşılaştırır.

### Değişti
- **`core/constants/system.py`**: OCR ve metin çıkarma sabitleri (`MIN_EXTRACTED_CHAR_COUNT`, `OCR_LANGUAGE`, `OCR_RENDER_DPI`, `OCR_PAGE_SEGMENTATION_MODE`, `ALLOWED_DOCUMENT_EXTENSIONS`) eklendi. Taranmış/fotoğraflanmış evrakın OCR yoluna ulaşabilmesi için `ALLOWED_FILE_TYPES` listesine `image/png`, `image/jpeg` ve `image/tiff` eklendi.
- **`core/config.py`**: `MEVZUAT_CORPUS_DIR` ve `MEVZUAT_COLLECTION_NAME` ayarları eklendi.
- **`core/__init__.py`**: Eksik olan `CorrespondenceType` dışa aktarımı ile birlikte yeni enum'lar tek noktadan erişilebilir hâle getirildi.
- **`api/dependency.py`**: Evrak analizi için tembel tekil bağımlılıklar (`get_mevzuat_retriever`, `get_document_analysis_graph`, `get_document_analysis_service`) eklendi.
- **`requirements.txt`**: `python-multipart`, `opendataloader-pdf`, `langchain-opendataloader-pdf`, `pypdfium2`, `pytesseract` ve `pillow` eklendi. `langfuse` bağımlılığı `<3.0.0` olarak sınırlandırıldı: `observability/tracer.py` yalnızca v2'de bulunan `langfuse.callback` içe aktarma yolunu kullanıyor ve `compose.yml` sunucu imajını `langfuse/langfuse:2` olarak sabitliyor. Ayrıca `requirements-dev.txt` (reportlab) oluşturuldu.

### Düzeltildi
- **Satır Yapısının Korunması**: `OpenDataLoader` varsayılan olarak satır sonlarını birleştiriyordu. Resmî yazıda satır yapısı anlam taşıdığı için (Sayı/Tarih aynı satırda, Konu bir alt satırda) alan çıkarımı tarih ve konuyu göremiyordu; `keep_line_breaks=True` ile giderildi.

## [1.9.0] - 2026-07-30
### Eklendi
- **SOTA Güvenlik ve Olay Tabanlı Haberleşme Entegrasyonu**:
  - **Kullanıcı Olayları**: `UserDeletedEvent` ve `UserPasswordChangedEvent` olayları `events/event.py` ve `events/__init__.py` içerisine eklendi.
  - **Asenkron Olay Yayımı**: Kullanıcı kayıt (`user.created`), silme (`user.deleted`) ve şifre değiştirme (`user.password_changed`) işlemlerinde `EventBus` üzerinden asenkron event yayımı aktifleştirildi.
  - **Redis Kara Liste (Token Blacklist)**: Çıkış yapan kullanıcının JWT access token'ının kalan süresi kadar Redis üzerinde bloke edilmesini sağlayan `/auth/logout` (POST) uç noktası geliştirildi.
  - **Güvenlik Bağımlılığı**: `get_current_user` bağımlılığı güncellenerek gelen isteklerin token kara liste kontrolü Redis üzerinden doğrulanmaya başlandı.
  - **Birim Testleri**: `/auth/logout` rotası ve Redis kara liste kontrolünü doğrulayan 2 yeni birim testi `tests/unit/domains/test_auth.py` dosyasına eklendi. Toplam 84 testin tamamı başarıyla geçti.

## [1.8.1] - 2026-07-30
### Değişti
- Paylaşılan Ollama fallback modeli `qwen3.5:9b` olarak korundu; geliştiricilerin kendi modellerini Git'e eklenmeyen `.env` dosyalarında `OLLAMA_MODEL` ile seçebilmesi hem yerel hem de Docker Compose çalıştırmalarında standartlaştırıldı.
- Ollama düşünme modu varsayılan olarak kapatıldı ve `OLLAMA_REASONING` ile yapılandırılabilir hale getirildi.
- Metin, akış ve yapılandırılmış çıktı çağrıları aynı reasoning ve token sınırı ayarlarını kullanacak şekilde birleştirildi.
- Varsayılan çıktı sınırı `OLLAMA_MAX_TOKENS=1024` olarak eklendi; çağrı bazında geçersiz kılma desteği korundu.

### Test
- Ollama varsayılanları, üç üretim yöntemi ve çağrı bazlı geçersiz kılmalar için provider/factory testleri genişletildi.

## [1.8.0] - 2026-07-30
### Eklendi
- **E-posta Davetiye / Whitelist Tabanlı Kayıt Sistemi**:
  - **Davetiye Modeli**: Yöneticilerin e-postaları önceden ekleyebilmesi için `InvitedEmailModel` ve ilgili doğrulamalar (`InvitedEmailCreate`, `InvitedEmailResponse`) eklendi.
  - **Davet Etme Uç Noktası**: `/users/invitations` (POST) ucu geliştirildi. Yalnızca Admin ve Manager'ların e-posta adresi ve önceden atanmış rol bilgisi ile davetiye oluşturabilmesi sağlandı.
  - **Güvenli Kayıt Eşleme**: `/users` (POST) kayıt ucu güncellenerek yalnızca sistemde kullanılmamış aktif davetiyeye sahip olan e-postaların kayıt olmasına izin verildi. Kayıt sonrasında kullanıcının rolü, davetiyedeki rol ile otomatik eşlendi.
  - **Birim Testleri**: Davetiye oluşturma, davetsiz kayıt engelleme, davetli başarılı kayıt ve rol atama senaryolarını test eden 5 adet yeni birim testi `tests/unit/domains/test_invite.py` altına eklendi. `test_user.py` testleri güncellendi ve tüm testler başarıyla çalıştırıldı.

## [1.7.0] - 2026-07-30
### Eklendi
- **Kullanıcı Yönetimi CRUD Uç Noktaları**:
  - **Kullanıcı Listeleme**: `/users` (GET) ucu sayfalama, arama ve rol bazlı filtreleme parametreleriyle eklendi. (Admin ve Manager yetkili).
  - **Tekil Kullanıcı Detayı**: `/users/{user_id}` (GET) ucu ile detaylı profil getirme eklendi (Kullanıcının kendisi veya Admin/Manager yetkili).
  - **Profil Güncelleme**: `/users/{user_id}` (PUT) ucu eklendi. Rol veya hesap aktiflik durumunu değiştirmek yalnızca Admin'lerle sınırlandırıldı.
  - **Şifre Değiştirme**: Giriş yapan kullanıcının kendi şifresini güvenli bir şekilde güncelleyebilmesi için `/users/me/password` (POST) ucu geliştirildi.
  - **Soft Delete**: Kullanıcıyı kalıcı olarak silmeden `is_deleted=True` ve `is_active=False` yapmak için `/users/{user_id}/soft` (DELETE) ucu eklendi (Yalnızca Admin yetkili).
  - **Hard Delete**: Kullanıcı kaydını veritabanından kalıcı olarak silmek için `/users/{user_id}/hard` (DELETE) ucu eklendi (Yalnızca Admin yetkili).
  - **Birim Testleri**: Silme (soft/hard), listeleme, şifre değiştirme ve güncelleme senaryolarını doğrulayan 5 yeni birim testi `tests/unit/domains/test_user.py` dosyasına eklendi. Tüm testler başarıyla geçti.
## [1.6.0] - 2026-07-30
### Eklendi
- **Rol Tabanlı Kullanıcı ve Yetkilendirme Sistemi (RBAC)**:
  - **Kullanıcı Rolleri**: `admin`, `manager`, `employee` ve `auditor` rolleri `UserRole` enum modülüne eklendi.
  - **Şifreleme**: `bcrypt` paketi entegre edilerek şifre hash'leme ve doğrulama işlevleri `core/security.py` altında aktifleştirildi.
  - **JWT Token Yönetimi**: `pyjwt` ile access token ve refresh token üretimi ve doğrulaması tamamlandı.
  - **Kullanıcı Kaydı ve Giriş**: `/users` (kullanıcı kaydı) ve `/auth/login` (kullanıcı girişi) API uç noktaları geliştirildi.
  - **Erişim ve Yetki Kontrolü**: Uç noktalar için token doğrulaması yapan `get_current_user` ve rol yetkilerini kontrol eden `@require_roles` bağımlılık sarmalayıcısı `api/dependency.py` dosyasına eklendi.
  - **Birim Testleri**: Yeni sistemin doğruluğunu test eden 9 adet pytest birim testi `tests/unit/core/test_security.py` ve `tests/unit/domains/` klasörleri altına eklendi. Tüm testler başarıyla çalıştırıldı.
- **API Temizliği ve Health Rotası Refaktörü**:
  - `app/api/v1/` klasörü altındaki tüm atıl ve kullanılmayan placeholder dosyalar silindi.
  - Aktif çalışan `/health` uç noktası `system` domain'i altına (`app/domains/system/router.py`) taşındı.
  - `/health` rotasının prefix'siz olarak `/api/v1/health` şeklinde sunulması sağlandı.

## [1.5.0] - 2026-07-30
### Eklendi
- **Gözlemlenebilirlik Altyapısı (Observability)**:
  - **Prometheus Entegrasyonu**: `prometheus-fastapi-instrumentator` ile `/metrics` uç noktası FastAPI uygulamasına entegre edildi.
  - **Langfuse Entegrasyonu**: LLM aramalarını, ajanları ve iş akışlarını izlemek için Langfuse `CallbackHandler` sağlayıcısı (`tracer.py`) eklendi.
  - **Docker Compose Servisleri**: `prometheus`, `grafana` ve `langfuse` servisleri `compose.yml` ve `deploy/docker/docker-compose.dev.yml` dosyalarına eklenerek otomatik başlatılacak şekilde yapılandırıldı.
  - **Grafana Paneli (ID: 22676)**: `prometheus-fastapi-instrumentator` için hazır FastAPI Observability dashboard şablonu (`fastapi_dashboard.json`) otomatik yüklenecek şekilde projelendirildi.
  - **Veritabanı Başlatma Betiği**: Langfuse için PostgreSQL üzerinde `langfuse` veritabanını otomatik oluşturan `scripts/init-db.sh` betiği eklendi.
  - **Makefile Komutları**: Konteyner çalışırken veritabanını oluşturmak için `make setup-db` hedefi ve temel docker-compose komutları eklendi.
  - **Yapılandırılmış Loglama**: `observability/logger.py` oluşturularak JSON formatında loglama ve clean development formatı entegre edildi.
- **Shared Modülü Refaktörü**:
  - Son harfi "s" olan dosya yasağı kapsamında `types.py`, `dto.py` ve `validators.py` silindi.
  - `shared/type/`, `shared/dto/` ve `shared/validator/` alt klasörleri oluşturularak tipler, DTO'lar (Pagination, Search) ve doğrulayıcılar bağımsız dosyalar olarak modüler hale getirildi.
- **Sadeleştirilmiş MCP Yapısı**:
  - `tools/` altındaki tüm placeholder dosyalar temizlendi.
  - `client.py` ve `manager.py` eklenerek dış MCP sunucularına stdio üzerinden asenkron bağlantı kurabilen ve bunları yöneten merkezi altyapı oluşturuldu.
  - `server.py` sadeleştirilerek FastMCP sunucusu için minimum bir taban haline getirildi.
- **SOTA Domain ve Events Yapısı**:
  - `auth`, `chat`, `documents`, `evaluation`, `feedback`, `settings`, `system`, `users` olmak üzere tüm domainlerdeki boş `models.py` ve `schemas.py` dosyaları silinerek yerlerine `model/` ve `schema/` klasörleri oluşturuldu.
  - `documents` domain'i, Görev 1 (Sınıflandırma/Analiz) ve Görev 2 (Taslaklama/Yönlendirme) verilerini/şemalarını barındıracak şekilde iskelet halinde güncellendi.
  - Tüm domainlerin `router.py` dosyaları `api/router.py` (ana API yönlendiricisi) altına `/api/v1/...` rotasıyla bağlanarak FastAPI uygulamasına entegre edildi.
  - `events/events.py` silinerek yerine `events/event.py` oluşturuldu. Olay tabanlı gevşek bağlı mimari için asenkron `EventBus`, `EventPublisher` ve `EventSubscriber` iskeletleri yazıldı.

- **Kaynağa Bağlı Taslak Üretimi**: Draft Graph state yapısına gelen evrak, sınıflandırma sonucu, doğrulanmış RAG bağlamı, durum ve insan onayı alanları eklendi.
- **Resmî Yazışma Türleri**: Üst yazı, cevap yazısı, bilgilendirme metni ve diğer/alternatif resmî yazışma için `CorrespondenceType` sözleşmesi, Türkçe/İngilizce alias normalizasyonu ve türe özel üretim kuralları eklendi.
- **Güvenli Girdi ve Hata Yönetimi**: Eksik evrak, Writer/Editor/Evaluator hataları ve yetersiz bağlam artık sahte başarı üretmeden açık durum ve insan onayı sinyali döndürüyor.
- **Workflow Testleri**: Kaynak koruma, dört yazışma türü, çözümleme önceliği, Türkçe alias normalizasyonu, belirsiz tür fallback'i, editör revizyonu, eksik evrak, LLM/structured-output hatası, yetersiz bağlam, revizyon sınırı ve güven skoru doğrulaması testleri eklendi; toplam test sayısı 78'e çıkarıldı.

### Değişti
- Writer, Editor, Reflection ve Evaluator adımları gelen evrak ile doğrulanmış bağlamı tüm revizyon döngüsü boyunca koruyacak şekilde güncellendi.
- Writer sistem yönergesi, kaynaklarda bulunmayan kişi, kurum, tarih, mevzuat, tutar veya olayların üretilmesini engelleyen kurallarla güçlendirildi.
- Planning Graph, sınıflandırma ve RAG sonuçlarını Draft Graph'a aktarıyor; insan onayı gereken taslaklar Routing Graph üzerinden güvenli biçimde `HumanApproval` hedefine yönlendiriliyor.
- Classification ve Planning Graph, açıkça istenen yazışma türünü metadata üzerinden Draft Graph'a kayıpsız aktarıyor.

---

## [1.4.0] - 2026-07-29
### Eklendi
- **`core/enums/` Klasörü**: Son harfi "s" olan dosya yasağı gereği `enums.py` silindi; yerine `user_role.py` (`UserRole` StrEnum) ve `document_status.py` (`DocumentStatus` StrEnum) modülleri oluşturuldu.
- **`core/constants/` Klasörü**: `constants.py` silindi; sistem geneli sabitler (`MAX_FILE_SIZE_BYTES`, `ALLOWED_FILE_TYPES`, `DEFAULT_PAGE_SIZE`, `MAX_PAGE_SIZE`, `AI_WORKFLOW_TIMEOUT_SECONDS`, `CORS_ORIGINS`, `CACHE_TTL_SECONDS`) `constants/system.py` içine taşındı.
- **`core/permissions/` Klasörü**: `permissions.py` silindi; FastAPI `Depends` olarak çalışan rol tabanlı erişim denetleyicisi `RoleChecker` sınıfı `permissions/role_checker.py` içine yerleştirildi.
- **`core/security.py` İskeleti**: JWT erişim/yenileme jetonu üretimi (`create_access_token`, `create_refresh_token`, `decode_token`) ve bcrypt parola hashing (`hash_password`, `verify_password`) için hazır-aktive edilebilir iskelet fonksiyonlar yazıldı.
- **Core Birim Testleri**: `tests/unit/core/test_core.py` eklenerek toplam test sayısı 63'e çıkarıldı.

### Değişti
- `core/exceptions.py` silindi (`api/exceptions/` ile çakışmaması için).
- `core/__init__.py` tüm yeni modülleri tek noktadan dışa aktaracak şekilde güncellendi.
- Tüm kod içi yorum ve docstring'ler İngilizce'ye çevrildi ve `Args/Returns/Raises` biçimli Google-style docstring standardına uyarlandı.

---

## [1.3.0] - 2026-07-29
### Eklendi
- **SOTA API Core Yanıt Yapısı (`api/responses/`)**: Tüm uç noktaların tek tip JSON döndürmesini sağlayan `APIResponse[T]` Pydantic şeması, `APIErrorDetail` hata modeli, `SuccessResponse` ve `ErrorResponse` yardımcı fonksiyonları eklendi.
- **Modüler Özel İstisna Hiyerarşisi (`api/exceptions/`)**: `BaseAppException` taban sınıfından türeyen `NotFoundException` (404), `ValidationException` (422), `AuthenticationException` (401), `AuthorizationException` (403), `ConflictException` (409) ve `AIException` (502) sınıfları kendi bağımsız dosyalarında tanımlandı.
- **Küresel Hata Yakalayıcılar**: `app_exception_handler`, `validation_exception_handler`, `http_exception_handler` ve `generic_exception_handler` fonksiyonları `exceptions/handlers.py` içine eklendi.
- **Performans Middleware'leri (`api/middleware/`)**:
  - `ResponseTimeMiddleware`: Yanıt süresini `X-Response-Time-Ms` header'ına ve JSON meta alanına ekler.
  - `StructuredLoggingMiddleware`: Yöntem, yol, durum kodu ve gecikme süresini yapılandırılmış biçimde loglar.
- **`api/v1/health.py`**: `/health` ucu birleşik `SuccessResponse` formatına taşındı.
- **API Core Birim Testleri**: `tests/unit/api/test_core.py` eklenerek 6 yeni test senaryosu yazıldı.

### Değişti
- Eski boş `api/exceptions.py`, `api/responses.py` ve `api/middleware.py` dosyaları silindi; hepsi birer modüler klasöre dönüştürüldü.
- `backend/app/main.py` middleware ve küresel handler kayıtlarını içerecek şekilde güncellendi.

---

## [1.2.0] - 2026-07-29
### Eklendi
- **Reflection & Evaluator Ajanları**: Taslak parlatma ve kalite denetimi için `ReflectionAgent` (`reflection.py`) ve `EvaluatorAgent` (`evaluator.py`) sınıfları ile Türkçe `.md` şablonları eklendi.
- **Master Planning & Supervisor**: Kullanıcı isteğine göre çalıştırılacak alt akışları dinamik planlayan master grafik (`planning_graph.py`) kodlandı.
- **Gelişmiş LangGraph Alt Akışları**:
  - `classification_graph.py` (Classifier -> NER -> Metadata)
  - `rag_graph.py` (Query Rewrite -> Hybrid Retrieve -> Verify -> Loop)
  - `draft_graph.py` (Writer -> Editor -> Reflection -> Evaluator -> Loop)
  - `routing_graph.py` (Güven skoruna göre departmana veya `HumanApproval`'a yönlendirme)
  - `system_graph.py` (Arka plan önbellek ve günlük temizliği)
- **Kapsamlı Birim Testleri**: 5 iş akışını ve master grafiği kapsayan 6 yeni test senaryosu eklenerek toplam test sayısı 43'e çıkarıldı.
- **Paket Dışa Aktarımları**: Modüle kolay erişim sağlamak amacıyla `backend/app/ai/__init__.py` dosyası dolduruldu.

### Değişti
- **Dinamik Prompt Yükleme**: Tüm 10 uzman ajanın sistem yönergeleri (system prompts), `PromptManager` üzerinden Türkçe şablonlardan dinamik okunacak şekilde güncellendi.
- **Draft Akışı**: Eski geçici `EditorAgent` yerine asıl `ReflectionAgent` ve `EvaluatorAgent` entegre edildi.

---

## [1.1.0] - 2026-07-29
### Eklendi
- **Hibrid Arama (Hybrid Retrieval)**: Paralel Dense (Qdrant) ve Sparse (Türkçe tokenized BM25) aramayı birleştiren `HybridRetriever` eklendi.
- **Rank Fusion (RRF)**: Arama skorlarını birleştirmek için Reciprocal Rank Fusion algoritması kodlandı.
- **LLM Reranker**: Aday belgeleri alaka düzeyine göre sıralayan Pydantic tabanlı `LLMReranker` entegre edildi.
- **Arama Testleri**: `test_retrieval.py` birim test dosyası eklendi.

---

## [1.0.0] - 2026-07-29
### Eklendi
- **Temel Mimari**: Ajanlar (`BaseAgent` + Uzmanlar), hafıza katmanları (Redis, Mem0), LLM sağlayıcıları (Ollama, vLLM) ve önbellek/veritabanı altyapısı kuruldu.
