# Varlık-İlişki (ERD) Diyagramları

## 1. Varlık İlişki Diyagramı 1

```mermaid
erDiagram
    COMPANY ||--o{ USER : "has"
    USER ||--o{ DOCUMENT : "uploads"
    DOCUMENT ||--|{ DRAFT : "generates"
    DRAFT ||--o{ REVISION_0 : "has" 
```

## 2. Varlık İlişki Diyagramı 2

```mermaid
erDiagram
    COMPANY ||--o{ USER : "has"
    USER ||--o{ DOCUMENT : "uploads"
    DOCUMENT ||--|{ DRAFT : "generates"
    DRAFT ||--o{ REVISION_1 : "has" 
```

## 3. Varlık İlişki Diyagramı 3

```mermaid
erDiagram
    COMPANY ||--o{ USER : "has"
    USER ||--o{ DOCUMENT : "uploads"
    DOCUMENT ||--|{ DRAFT : "generates"
    DRAFT ||--o{ REVISION_2 : "has" 
```

## 4. Varlık İlişki Diyagramı 4

```mermaid
erDiagram
    COMPANY ||--o{ USER : "has"
    USER ||--o{ DOCUMENT : "uploads"
    DOCUMENT ||--|{ DRAFT : "generates"
    DRAFT ||--o{ REVISION_3 : "has" 
```

## 5. Varlık İlişki Diyagramı 5

```mermaid
erDiagram
    COMPANY ||--o{ USER : "has"
    USER ||--o{ DOCUMENT : "uploads"
    DOCUMENT ||--|{ DRAFT : "generates"
    DRAFT ||--o{ REVISION_4 : "has" 
```

