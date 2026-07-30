# CHANGELOG

Tüm önemli değişiklikler bu dosyada kayıt altına alınacaktır.

## [1.8.1] - 2026-07-30
### Değişti
- Paylaşılan Ollama fallback modeli `qwen3.5:9b` olarak korundu; geliştiricilerin kendi modellerini Git'e eklenmeyen `.env` dosyalarında `OLLAMA_MODEL` ile seçebilmesi hem yerel hem de Docker Compose çalıştırmalarında standartlaştırıldı.
- Ollama düşünme modu varsayılan olarak kapatıldı ve `OLLAMA_REASONING` ile yapılandırılabilir hale getirildi.
- Metin, akış ve yapılandırılmış çıktı çağrıları aynı reasoning ve token sınırı ayarlarını kullanacak şekilde birleştirildi.
- Varsayılan çıktı sınırı `OLLAMA_MAX_TOKENS=1024` olarak eklendi; çağrı bazında geçersiz kılma desteği korundu.

### Test
- Ollama varsayılanları, üç üretim yöntemi ve çağrı bazlı geçersiz kılmalar için provider/factory testleri genişletildi.

---

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
