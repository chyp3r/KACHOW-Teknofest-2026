# İsimlendirme Standartları (Naming Standards)

> **NOT:**
> Bu doküman proje genelinde klasör, dosya, değişken ve fonksiyon isimlendirmeleri için temel kuralları belirler. İsimlerin; açık, kısa, tek anlam taşıması ve teknik borç oluşturmaması hedeflenmektedir.

## Genel Kurallar

- **Dil:** Kaynak kodunun (değişkenler, fonksiyonlar) tamamı İngilizce olmalıdır. Dokümantasyon ve yorum satırları Türkçe olabilir.
- **Açıklayıcılık:** Kod okunurken ismin tek başına amacını açıklaması gerekir. Kısaltmalardan (ör. `usr_nm`, `tmp_cnt`) kaçınılmalıdır.
- **Kaçınılması Gerekenler:** `temp`, `new`, `test1`, `test2`, `abc`, `final`, `manager2` gibi anlamsız isimlendirmeler kesinlikle kullanılamaz.

## Klasör ve Dosya İsimlendirmeleri

| Katman | Kural | Örnek |
| :--- | :--- | :--- |
| **Klasörler** | Çoğul ve `snake_case` | `agents/`, `documents/`, `components/` |
| **Python Dosyaları** | `snake_case` | `chat_service.py`, `workflow_manager.py` |
| **TS/React Bileşenleri** | `PascalCase` | `ChatWindow.tsx`, `Sidebar.tsx` |

## Python Kod Standartları

| Tür | Kural | Doğru Örnek |
| :--- | :--- | :--- |
| **Sınıf (Class)** | `PascalCase` | `ChatService`, `PlanningAgent` |
| **Fonksiyon / Metot** | `snake_case` | `create_session()`, `generate_embedding()` |
| **Değişken** | `snake_case` | `user_name`, `chat_session` |
| **Sabit (Constant)** | `UPPER_SNAKE_CASE` | `MAX_RETRY_COUNT`, `DEFAULT_TIMEOUT` |
| **Gizli (Private)** | Önünde tek alt çizgi | `_build_context()`, `_validate_input()` |

## TypeScript & React Kod Standartları

| Tür | Kural | Doğru Örnek |
| :--- | :--- | :--- |
| **React Component** | `PascalCase` | `DocumentCard`, `UserAvatar` |
| **React Hook** | `camelCase` (use ile başlar) | `useChat`, `useTheme` |
| **Yardımcı (Utility)** | `camelCase` | `formatDate()`, `buildPrompt()` |
| **Type / Interface** | `PascalCase` | `ChatMessage`, `WorkflowState` |
| **Enum** | `PascalCase` | `MessageRole`, `ThemeMode` |

## Veritabanı ve API Standartları

- **Veritabanı Tabloları:** Çoğul isim kullanır (`users`, `documents`, `chat_sessions`).
- **Veritabanı Kolonları:** `snake_case` kullanır (`created_at`, `document_id`).
- **API Endpointleri:** Küçük harf, çoğul ve kaynak (resource) odaklıdır.
  - *Doğru:* `/api/v1/chats`, `/api/v1/documents`
  - *Yanlış:* `/CreateChat`, `/doLogin`

## AI Spesifik Standartlar

| Alan | Kural | Örnek |
| :--- | :--- | :--- |
| **Agent** | `PascalCase` | `PlanningAgent`, `SystemAgent` |
| **Workflow** | `snake_case` | `chat_workflow`, `rag_workflow` |
| **Tool** | İsim fiille başlamalıdır | `read_file`, `search_documents` |
| **Prompt** | Görev odaklı (`snake_case`) | `summarization_prompt`, `planning_prompt` |

> **ÖNEMLİ:**
> Kısaltma kullanımı sadece yaygın teknik terimler (API, JWT, MCP, LLM, RAG, JSON, SQL, UUID) için serbesttir. Proje içinde ekibe özel yepyeni ve anlaşılmaz kısaltmalar türetilmemelidir.
