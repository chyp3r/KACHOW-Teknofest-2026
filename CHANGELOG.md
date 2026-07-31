# CHANGELOG

Tüm önemli değişiklikler bu dosyada kayıt altına alınacaktır.

## [1.16.0] - 2026-08-01
### Eklendi
- **Sentetik RAG Veri Kümesi Genişletmesi**: Veri kümesinde eksik (0-1 adet) olan 9 farklı resmî yazışma kategorisi (İtiraz, Görüş Talebi, Ret/Kısmi Kabul, Eksik Belge, Proje Teklifi, Tekit, İade/Yetkisizlik vb.) için Şartnamenin 6.5 maddesine uygun olarak tamamen kurgusal, ancak kurumsal yapıya ve Yönetmeliğe uygun 53 adet yeni sentetik belge eklendi. Katalogdaki doğrulanmış örnek sayısı 253'e ulaştı.
- **Dataset İndeks Otomasyonu**: `scripts/update_dataset_indexes.py` adında yeni bir Python scripti eklendi. Bu script veri kümesi dizinindeki Markdown (`.md`) dosyalarını tarayıp YAML frontmatter bilgilerini otomatik okuyarak `kaynak-katalogu.jsonl`, `kaynak-ozeti.csv` ve ilgili dizinlerin alt `_indeks.csv` dosyalarını tek tuşla güncelleyerek manuel veri girişi hatalarının önüne geçmektedir.

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
