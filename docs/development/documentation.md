# Documentation Standards

> Bu doküman proje genelindeki dokümantasyon standartlarını tanımlar.

Bu kurallar Backend, Frontend, AI ve tüm proje dokümantasyonu için geçerlidir.

---

# Amaç

Dokümantasyonun amacı;

* Projeyi anlaşılır hale getirmek
* Bilgi kaybını önlemek
* Yeni geliştiricilerin adaptasyonunu hızlandırmak
* AI ajanlarının projeyi doğru anlamasını sağlamaktır.

Dokümantasyon kodun yerine geçmez, kodu açıklar.

---

# Dokümantasyon İlkeleri

Her doküman;

* tek bir konuya odaklanmalıdır,
* güncel olmalıdır,
* açık bir amacı olmalıdır,
* gereksiz tekrar içermemelidir.

---

# Doküman Hiyerarşisi

```text
README.md

↓

AGENTS.md

↓

docs/architecture/

↓

docs/development/

↓

Modül dokümanları
```

Üst seviyedeki dokümanlar alt seviyedekilere referans verir.

---

# README

README yalnızca giriş noktasıdır.

README içerisinde;

* proje amacı,
* kurulum,
* mimari özeti,
* doküman bağlantıları

bulunmalıdır.

README teknik detay içermez.

---

# Architecture

Architecture klasörü sistemin nasıl tasarlandığını açıklar.

Örnekler

* Backend
* Frontend
* AI
* RAG
* MCP
* Deployment

Bu dokümanlar neden sorusunu cevaplar.

---

# Development

Development klasörü geliştirme standartlarını açıklar.

Örnekler

* Naming
* Testing
* Git Workflow
* Code Review

Bu dokümanlar nasıl sorusunu cevaplar.

---

# Kod İçi Dokümantasyon

Kod mümkün olduğunca kendi kendini açıklamalıdır.

Yorum satırları yalnızca gerekli durumlarda kullanılmalıdır.

Yorumlar kodu tekrar etmemelidir.

---

# Yeni Özellik

Yeni bir özellik geliştirildiğinde aşağıdaki kontrol yapılmalıdır.

* README etkileniyor mu?
* Mimari değişiyor mu?
* Yeni standart gerekiyor mu?
* API değişiyor mu?
* AI davranışı değişiyor mu?

Evet ise ilgili doküman güncellenmelidir.

---

# Yeni Klasör

Yeni üst seviye klasör oluşturulursa;

* amacı açıklanmalı,
* ilgili mimari doküman güncellenmelidir.

---

# Yeni API

Yeni endpoint eklendiğinde;

* API dokümanı güncellenmelidir.
* Gerekirse örnek istek ve cevap eklenmelidir.

---

# Backend Değişiklikleri

Backend mimarisini etkileyen değişikliklerde;

* architecture/backend.md
* ilgili standart dokümanları

kontrol edilmelidir.

---

# Frontend Değişiklikleri

Frontend mimarisini etkileyen değişikliklerde;

* architecture/frontend.md

güncellenmelidir.

---

# AI Değişiklikleri

Yeni Agent

Yeni Workflow

Yeni Tool

Yeni MCP

Yeni Memory

eklendiğinde ilgili AI mimari dokümanları güncellenmelidir.

---

# Diyagramlar

Mimari değişikliklerinde diyagramlar da güncellenmelidir.

Kod ile diyagramlar tutarlı olmalıdır.

---

# Örnekler

Örnek kodlar mümkün olduğunca güncel tutulmalıdır.

Çalışmayan örnekler dokümanda bırakılmamalıdır.

---

# Sürüm Uyumluluğu

Dokümantasyon mevcut kod tabanını temsil etmelidir.

Eski davranışlar "yakında güncellenecek" şeklinde bırakılmamalıdır.

---

# AI Destekli Güncelleme

AI ajanları yalnızca kod üretmekle kalmamalıdır.

Aşağıdaki durumlarda ilgili dokümanları da güncellemelidir.

* Yeni modül
* Yeni klasör
* Yeni API
* Yeni Agent
* Yeni Workflow
* Yeni Tool
* Yeni Feature

---

# Pull Request Kontrolü

PR açılmadan önce aşağıdaki soru sorulmalıdır.

> Yapılan değişiklik herhangi bir dokümanı etkiliyor mu?

Evet ise ilgili doküman güncellenmeden PR açılmamalıdır.

---

# Dokümantasyon Kalitesi

İyi bir doküman;

* kısa,
* güncel,
* örnek içeren,
* kolay okunabilir,
* tek sorumluluklu

olmalıdır.

---

# Yapılmaması Gerekenler

* Güncel olmayan doküman bırakmak
* Kod ile çelişen açıklamalar yazmak
* Aynı bilgiyi birden fazla dosyada tekrar etmek
* Mimari değiştiği halde dokümanları güncellememek

---

# İlgili Dokümanlar

* README.md
* AGENTS.md
* project-rules.md
* architecture/
* development/
