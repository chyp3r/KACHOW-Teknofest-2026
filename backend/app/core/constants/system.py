"""Uygulamanın tamamında paylaşılan sistem geneli sabit değerler.

Ortama özel veya dağıtımla yapılandırılabilir değerler için bunun yerine
core/config.py kullanın.
"""

# ---------- Dosya Yüklemeleri ----------
MAX_FILE_SIZE_BYTES: int = 50 * 1024 * 1024  # 50 MB
ALLOWED_FILE_TYPES: list[str] = [
    "application/pdf",
    "text/plain",
    "application/msword",
    # Fotoğraflanmış veya taranmış evrak görüntü olarak gelir ve OCR yoluna ulaşmalıdır.
    "image/png",
    "image/jpeg",
    "image/tiff",
]
ALLOWED_DOCUMENT_EXTENSIONS: list[str] = [
    "pdf",
    "txt",
    "doc",
    "png",
    "jpg",
    "jpeg",
    "tif",
    "tiff",
]

# ---------- Belge Metin Çıkarma ----------
# Bu kadar karakterin altında bir çıkarma sonucu başarısızlık olarak ele
# alınır ve zincirdeki bir sonraki çıkarıcı denenir (taranmış bir PDF
# neredeyse hiç metin vermez).
MIN_EXTRACTED_CHAR_COUNT: int = 200
# Türkçe OCR için kullanılan Tesseract dil paketi (`tesseract --list-langs`).
OCR_LANGUAGE: str = "tur"
# OCR için rasterizasyon yoğunluğu; düşük ölçeklendirme zayıf Türkçe
# karakter tanımanın başlıca nedenidir.
OCR_RENDER_DPI: int = 300
# Kelime uzunluğundaki jetonların bu oranının altında bir çıkarma
# okunamaz olarak ele alınır ve zincir yükselir. Yalnızca karakter sayısı
# OCR çöpünü tespit edemez: bozuk bir tarama bolca karakter verir, sadece
# yanlış olanlarını.
MIN_TEXT_QUALITY_RATIO: float = 0.6
# Tesseract sayfa segmentasyon modu 6 = tek biçimli bir metin bloğu
# varsayılır, ki bu resmi yazışmanın blok düzenine uyar.
OCR_PAGE_SEGMENTATION_MODE: int = 6
# Bir PDF'in hiç metin katmanı olduğunu saymak için gereken minimum
# gömülü metin karakteri (ilk birkaç sayfa boyunca), OpenDataLoaderExtractor
# ve PdfiumExtractor'ı kapılar. Bilinçli olarak MIN_EXTRACTED_CHAR_COUNT'un
# çok altında: bu bir kalite çıtası değil, ucuz bir "burada bir şey var mı"
# sondasıdır -- gerçek bir tarama ~0 karakter okur (belki gömülü bir
# filigrandan birkaç tane), oysa dijital doğan herhangi bir sayfada
# neredeyse anında gerçek metin vardır.
TEXT_LAYER_PROBE_MIN_CHARS: int = 20
# Metin katmanı sondasının karar vermeden önce okuduğu önde gelen sayfa
# sayısı. Bir taramanın hiçbir sayfasında metin katmanı yoktur, bu yüzden
# ilk birkaçını kontrol etmek, belge çok daha uzun sürse bile onu dijital
# doğan bir PDF'den ayırt etmek için yeterlidir.
TEXT_LAYER_PROBE_MAX_PAGES: int = 3
# OllamaVisionExtractor.transcribe_header_band için "başlık bandı" olarak
# ele alınan taranmış ilk sayfanın yüksekliğinin oranı -- bunun ölçüldüğü
# korpusta (datasets/resmi_yazisma/00_gelen_kaynaklar/cevap_yazisi/ altındaki
# 45 taranmış CY-*.pdf) antetten Konu satırına kadar kapsar. Hiçbir kalite
# sinyali (başlık-gürültü yoğunluğu, quality_ratio) bu onarıma hangi
# taramaların ihtiyaç duyduğunu güvenilir biçimde tahmin edemez -- bunu tam
# korpusa karşı kalibre etmek, bilinen ayrıştırıcı boşlukları kontrol
# edildiğinde bile gerçek sonuçla temelde hiçbir korelasyon bulmadı
# (Pearson r=0.036). Bunun yerine her OCR sonucuna koşulsuz uygulanır;
# küçük bir kırpım her zaman ödenen maliyeti sınırlı tutar (~12.6s ölçüldü,
# aynı model üzerinden tam bir sayfa için ~26s'ye karşı).
HEADER_BAND_FRACTION: float = 0.28
# Vision modelinin daha temiz transkripsiyonunu geri birleştirmek için,
# bir sayfanın OCR metninin başlık bandının kapsadığı varsayılan önde
# gelen satır sayısı. Bu boru hattında metnin piksel koordinatları yoktur
# (ExtractedDocument.pages düz bir list[str]'dir), bu yüzden bu, yukarıdaki
# HEADER_BAND_FRACTION'ı kalibre etmek için kullanılan aynı satır sayısı
# yaklaşımıdır, kesin bir eşleme değil.
HEADER_REPAIR_LINE_COUNT: int = 14
# Kapanış formülünden (Arz/Rica ederim, m.17) sonra `_parse_signature`'ın
# isim/unvan satırları için ileriye doğru kaç satır aradığı. Gerçek bir
# imza bloğu kapanış formülünün hemen ardından oturur ve gerçek antetli
# kaşe şablonlarında bir antet altbilgisi (adres, santral, faks, web)
# tarafından takip edilir -- bu altbilgi, sayfa sonundan *geriye* doğru bir
# pencerenin bunun yerine yakaladığı şeydir, imzayı tamamen kaçırarak (bu
# sabit var olmadan önce gerçek taranmış korpusta 0/23 ölçüldü). Aynı
# korpusa karşı kalibre edildi (23 belgeden 21'i bir kapanış formülü
# taşır; diğer 2'si formül-yok kuyruk yoluna düşer, bu sabitten
# etkilenmez): isim satırı kapanış formülünden 0-3 satır sonra, unvan
# satırı ise 1-4 satır sonra iniyor -- en geniş durum (imza mürekkebi
# ismi kısmen gizleyen CY-050), unvanı +4'e koyuyor. 6, o gözlemlenen
# maksimumun üzerinde iki satır tolerans verir.
#
# Pencerenin altbilgisiz olacağı GARANTİ EDİLMEZ -- unvan satırı ile ilk
# altbilgi satırı (Santral/Tel/Bilgi için/İnternet Adresi) arasındaki
# ölçülen minimum boşluk aynı korpusta 0'dır, bu yüzden 6-boyutlu bir
# pencere rutin olarak bir veya iki satır altbilgi içerir. Zararsız:
# `_parse_signature`, isim-şeklindeki ilk adayı ve ondan sonraki ilk
# unvan-ipucu eşleşmesini alır, ikisi de belge sırasında her zaman
# altbilgiden önce gelir, bu yüzden penceredeki fazladan sondaki altbilgi
# içeriğine asla ulaşılmaz.
SIGNATURE_WINDOW_LINES: int = 6
# FallbackDocumentExtractor'ın bir çıkarmayı doğrudan kabul etmesi için
# çıkarmanın 1. sayfasındaki minimum `count_header_fields` sayısı (5
# üzerinden: sayi/tarih/konu/muhatap/gonderen_kurum). Yalnızca
# `quality_ratio`/`char_count` bu başarısızlığı yakalayamaz -- bir belge,
# başlık bloğu bozuk veya ayrışamaz olsa bile genel olarak iyi Türkçe
# düzyazı gibi okunabilir (gerçek CY-050'de gözlemlendi: 0.85
# quality_ratio, 3316 karakter, beş başlık alanından sıfırı kurtarıldı).
# Keyfi bir hedef değil, gerçek belgelerin sağlayabileceği TAVANA karşı
# kalibre edildi: 19 elle etiketlenmiş ground-truth belgesinin hepsinin
# clean_text'ini parse_labelled_fields'tan geçirmek, belge başına
# {2: 2 belge, 4: 13, 5: 4} alan sayısı dağılımı verir -- `tarih` tek
# başına yalnızca 19'da 6'sından kurtarılabilir (birçok resmi antet
# şablonu basitçe hiç "Tarih" etiketi taşımaz). 2'den fazlasını istemek,
# çıkarması zaten doğru olan belgeler üzerinde pahalı OCR yükselmesini
# zorlardı. 2, metni gerçekten iyi olan bir belgeyi reddedemeyen en
# yüksek tabandır.
MIN_HEADER_FIELD_COUNT: int = 2
# FallbackDocumentExtractor'ın *tam sayfa* vision-model yükselmesini
# atladığı sayfa sayısı eşiği (başlık bandı onarımı sayfa sayısından
# bağımsız olarak her zaman çalışır -- yalnızca 1. sayfaya dokunur). Yeni
# alan-tetiklemeli yükselmenin en kötü durumunu, sınırsız yerine kabaca
# bir sayfalık OCR süresiyle sınırlar: uzun bir ek paketi, yalnızca 1.
# sayfada yaşayan başlık alanlarını düzeltmek için tam belge vision
# maliyetini ödememelidir.
MAX_OCR_PAGES: int = 3
# Bir PDF sayfasının görüntü-hakim olarak ele alınması için tek bir gömülü
# görüntü nesnesinin kapladığı sayfa alanının minimum oranı -- gerçekten
# dijital doğan bir sayfa (gerçek vektör/metin içeriği, tam sayfa görüntü
# yok) ile aslında bir PDF'e sarılmış taranmış bir raster olan bir sayfa
# ("Class A": bir tarayıcının kendi gömülü OCR geçişi, orijinal taramanın
# tam sayfa bir görüntüsünün üzerine çöp bir gömülü metin katmanı yazar,
# bu yüzden `has_pdf_text_layer` tek başına onu gerçek bir metin
# katmanından ayırt edemez) arasındaki discriminator. 86 gerçek PDF
# üzerinde ölçüldü (50 korpus taraması + 36 canlı yükleme): bu projenin
# tarayıcı boru hattından (`PFUPDF Engine`) gelen her metin-katmanı
# sayfası tam olarak 1.0 görüntü kapsamasına iner, ve gerçekten dijital
# doğan her sayfa (`ReportLab`) tam olarak 0.0'a iner -- hiçbir belge
# ikisi arasına düşmez, bu yüzden ince kalibrasyona gerek yoktu.
FULL_PAGE_IMAGE_MIN_COVERAGE: float = 0.5

# ---------- Sayfalama ----------
DEFAULT_PAGE_SIZE: int = 20
MAX_PAGE_SIZE: int = 100

# ---------- AI İş Akışı ----------
# AI_WORKFLOW_TIMEOUT_SECONDS, core/config.py'de (Settings) yaşar -- bu
# dosyadaki sabitlerin aksine dağıtımla yapılandırılabilir.
MAX_RETRY_ATTEMPTS: int = 3

# ---------- CORS ----------
CORS_ORIGINS: list[str] = [
    "http://localhost:3000",
    "http://localhost:5173",
]

# ---------- Önbellek ----------
CACHE_TTL_SECONDS: int = 60 * 60  # 1 saat
