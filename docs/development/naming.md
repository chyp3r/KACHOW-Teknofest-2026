# Naming Standards

> Bu doküman proje genelinde kullanılacak isimlendirme standartlarını tanımlar.

Bu kurallar Backend, Frontend, AI ve gelecekte eklenecek tüm modüller için geçerlidir.

---

# Amaç

İsimlendirme standartlarının amacı;

* Kod okunabilirliğini artırmak
* Tutarlılığı sağlamak
* Arama yapılabilirliği artırmak
* AI destekli geliştirmede tahmin edilebilirliği sağlamaktır.

---

# Genel İlkeler

İsimler;

* açık olmalıdır,
* kısa olmalıdır,
* tek anlam taşımalıdır,
* teknik borç oluşturmamalıdır.

Kısaltmalardan mümkün olduğunca kaçınılmalıdır.

---

# Dil

Kaynak kodunun tamamı İngilizce yazılır.

Yorumlar ve dokümantasyon Türkçe olabilir.

---

# Dosya İsimleri

Dosya isimleri **snake_case** kullanır.

Doğru örnekler

```text
chat_service.py
document_router.py
workflow_manager.py
vector_store.py
```

Yanlış örnekler

```text
ChatService.py
Chat-Service.py
chatService.py
```

---

# Klasör İsimleri

Klasör isimleri çoğul ve snake_case olmalıdır.

Örnekler

```text
agents/
documents/
workflows/
components/
services/
hooks/
```

---

# Python

## Değişken

snake_case

```python
user_name
chat_session
workflow_result
```

---

## Fonksiyon

snake_case

```python
create_session()
generate_embedding()
execute_workflow()
```

---

## Class

PascalCase

```python
ChatService
DocumentRepository
WorkflowManager
PlanningAgent
```

---

## Constant

UPPER_SNAKE_CASE

```python
MAX_RETRY_COUNT
DEFAULT_TIMEOUT
MAX_CONTEXT_LENGTH
```

---

## Private

Tek alt çizgi

```python
_build_context()

_validate_input()
```

---

# TypeScript

## Component

PascalCase

```text
ChatWindow.tsx

Sidebar.tsx

DocumentCard.tsx
```

---

## Hook

camelCase ve use ile başlamalıdır.

```text
useChat.ts

useTheme.ts

useDocuments.ts
```

---

## Utility

camelCase

```text
formatDate()

truncateText()

buildPrompt()
```

---

## Type

PascalCase

```typescript
ChatMessage

DocumentChunk

WorkflowState
```

---

## Enum

PascalCase

```typescript
MessageRole

ThemeMode
```

---

# API

Endpoint isimleri

* küçük harf
* çoğul
* kaynak odaklı

Doğru

```text
/api/v1/chats

/api/v1/documents

/api/v1/users
```

Yanlış

```text
/GetUser

/CreateChat

/doLogin
```

---

# Database

Tablolar çoğul isim kullanır.

```text
users

documents

chat_sessions

embeddings
```

Kolonlar snake_case kullanır.

```text
created_at

updated_at

document_id
```

---

# AI

## Agent

PascalCase

```text
PlanningAgent

ChatAgent

DocumentAgent

SystemAgent
```

---

## Workflow

snake_case

```text
chat_workflow

rag_workflow

planning_workflow

system_workflow
```

---

## Tool

İsim fiille başlamalıdır.

```text
read_file

write_file

search_documents

execute_terminal

run_python
```

---

## Prompt

Görev odaklı isimlendirilmelidir.

```text
summarization_prompt

planning_prompt

system_prompt

retrieval_prompt
```

---

## Memory

Amacı belirtmelidir.

```text
short_term_memory

conversation_memory

semantic_memory
```

---

# Frontend

## Feature

Kısa ve açıklayıcı olmalıdır.

```text
chat

documents

settings

authentication
```

---

## Component

Bileşenin ne olduğunu anlatmalıdır.

```text
ChatMessage

ChatInput

Sidebar

DocumentList

UserAvatar
```

---

## Service

"...Service" ile bitmelidir.

```text
ChatService

AuthService

DocumentService
```

---

# Git

## Branch

```text
feature/chat

feature/rag

feature/mcp

fix/login

refactor/backend

docs/readme

test/chat
```

---

## Commit

Conventional Commits standardı kullanılmalıdır.

```text
feat(chat): add streaming support

fix(auth): resolve token refresh issue

docs(ai): update workflow documentation

refactor(frontend): simplify sidebar

test(rag): add retrieval tests
```

---

# Kaçınılması Gereken İsimler

```text
temp

new

test

test2

aaa

abc

final

helper

manager2

service_new
```

İsim görevini anlatmalıdır.

---

# Kısaltmalar

Yaygın teknik kısaltmalar kullanılabilir.

```text
API

JWT

MCP

LLM

RAG

URL

JSON

SQL

UUID
```

Proje içerisinde yeni kısaltma üretilmemelidir.

---

# Son Kural

Kod okunurken isim tek başına amacını açıklayabilmelidir.

Bir isim yorum gerektiriyorsa yeterince iyi değildir.
