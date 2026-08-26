# Veri Modeli — ER Diyagramı

Ana Postgres tabloları arasındaki ilişkiler (28 Alembic migration'ının vardığı şema). Şirket/birim bazlı çok kiracılılık (multi-tenancy) ve Row-Level Security (RLS), `company_id` üzerinden neredeyse tüm tablolara yayılır.

```mermaid
erDiagram
    COMPANIES ||--o{ UNITS : "birimlere sahiptir"
    COMPANIES ||--o{ USERS : "kullanıcılara sahiptir"
    COMPANIES ||--o{ DOCUMENTS : "kiracısıdır"
    COMPANIES ||--o{ DRAFTS : "kiracısıdır"

    USERS ||--o{ DOCUMENTS : "yükler"
    USERS ||--o{ DRAFTS : "oluşturur"
    USERS ||--o{ AUDIT_LOG : "eylemleri kaydedilir"
    USERS ||--o{ NOTIFICATIONS : "alır"
    USERS ||--o{ FEEDBACK : "gönderir"

    UNITS ||--o{ DRAFTS : "yönlendirme hedefidir"
    UNITS ||--o{ POOLS : "havuzlara sahiptir"

    DOCUMENTS ||--o{ DRAFTS : "taslak üretilir"
    DOCUMENTS ||--o{ TRANSFERS : "transfer edilir"

    DRAFTS ||--o{ DRAFT_SHARES : "paylaşılır"
    DRAFTS ||--o{ ARTIFACT_TRANSFERS : "başka birime aktarılır"
    DRAFTS ||--o{ AUDIT_LOG : "değişiklikleri izlenir"

    POOLS ||--o{ POOL_ITEM_SNAPSHOT : "anlık görüntü tutar"

    TRAINING_RUN }o--|| COMPANIES : "şirkete özel eğitim"

    COMPANIES {
        uuid id PK
        string name
        jsonb correspondence_rules
        jsonb default_sensitivity
    }
    UNITS {
        uuid id PK
        uuid company_id FK
        string name
        string destination_unit
    }
    USERS {
        uuid id PK
        uuid company_id FK
        string role
        jsonb permission_grants
    }
    DOCUMENTS {
        uuid id PK
        uuid company_id FK
        uuid uploaded_by FK
        string document_type
        jsonb extracted_fields
        string compliance_status
        boolean is_ocr_text
    }
    DRAFTS {
        uuid id PK
        uuid document_id FK
        uuid company_id FK
        string correspondence_type
        text content
        float confidence_score
        boolean requires_human_approval
        uuid destination_unit_id FK
    }
    DRAFT_SHARES {
        uuid id PK
        uuid draft_id FK
        uuid shared_with_user_id FK
    }
    TRANSFERS {
        uuid id PK
        uuid document_id FK
        uuid target_unit_id FK
    }
    AUDIT_LOG {
        uuid id PK
        uuid user_id FK
        string action
        jsonb applied_rules
        timestamp created_at
    }
    POOLS {
        uuid id PK
        uuid unit_id FK
    }
    TRAINING_RUN {
        uuid id PK
        uuid company_id FK
        string status
    }
```

## Notlar

- **Row-Level Security (RLS)**, `0013_rls.py` ve `0016_recorder_tables_rls.py` migration'larıyla `company_id` üzerinden aktif edilir — bağlantıyı yapan rol (`kachow_app`) RLS'i atlayamayan kısıtlı bir roldür, bu yüzden izolasyon uygulama koduna değil veritabanı seviyesine dayanır.
- **`DRAFTS.confidence_score`** ve **`requires_human_approval`**, Görev 2'nin "kullanıcıya açık bilgilendirme" ve "insan onayı" maddelerinin veritabanı karşılığıdır; `AUDIT_LOG.applied_rules` bu skorun arkasındaki kural dökümünü saklar.
- Şema, 0001 (baseline) ile 0028 (drafts unique constraint) arasındaki migration geçmişinde kademeli olarak genişlemiştir: guardrail alanları, kullanıcı yetki seviyesi (user_clearance), sohbet geçmişi, kotalar, geri bildirim, eğitim koşuları (training runs), mesajlaşma ve favoriler zamanla eklenmiştir.
