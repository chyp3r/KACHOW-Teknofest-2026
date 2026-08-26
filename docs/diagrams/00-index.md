# Sistem Diyagramları

Bu klasör, KACHOW platformunun uçtan uca mimarisini — Görev 1 (Evrak Sınıflandırma ve İçerik Analizi) ile Görev 2 (Resmî Yazı Taslaklama ve Birim Yönlendirme) dahil — Mermaid diyagramları üzerinden anlatır. Diyagramlar gerçek kod tabanındaki modül, servis ve tablo adlarına dayanır; jenerik/kurgusal isim kullanılmamıştır.

Okuma sırası önerisi (yukarıdan aşağı, genelden özele):

1. [Use Case Diyagramı](01-use-case-diyagrami.md) — Sistemi kim, ne amaçla kullanıyor?
2. [Görev 1 Sıra Diyagramı — Evrak Analizi](02-sequence-gorev1-evrak-analizi.md) — Yükleme → OCR → sınıflandırma → mevzuat → özet.
3. [Görev 2 Sıra Diyagramı — Taslak & Yönlendirme](03-sequence-gorev2-taslak-yonlendirme.md) — Yazma → doğrulama → revizyon → birim yönlendirme, insan onayı dahil.
4. [Aktivite Diyagramı — Evrak Yaşam Döngüsü](04-activity-evrak-yasam-dongusu.md) — Uçtan uca karar noktalarıyla birlikte tüm süreç.
5. [Dağıtım (Deployment) Diyagramı](05-deployment-diyagrami.md) — Docker Compose / Kubernetes servis topolojisi.
6. [Bileşen / Mimari Diyagramı](06-bilesen-mimari-diyagrami.md) — Katmanlar arası bağımlılıklar (API, domains, ai, infrastructure, frontend).
7. [Veri Modeli — ER Diyagramı](07-veri-modeli-er-diyagrami.md) — Ana Postgres tabloları ve ilişkileri.
8. [Taslak Durum Diyagramı](08-state-taslak-durum-diyagrami.md) — Bir taslağın oluşturulmasından yönlendirilmesine kadar geçirdiği durumlar.

## Nasıl görüntülenir?

Tüm diyagramlar standart [Mermaid](https://mermaid.js.org/) sözdizimiyle yazılmıştır. GitHub, GitLab ve çoğu modern Markdown görüntüleyici bu blokları otomatik olarak render eder; ek bir araç kurmaya gerek yoktur.

## Kapsam notu

Bu klasördeki diyagramlar sistemin **tamamını** (backend + frontend) yansıtır. Diğer temizlik/Türkçeleştirme çalışmaları yalnızca backend kapsamında yürütülmüştür; diyagramlar istisnadır çünkü bütünü doğru anlatabilmek için frontend'i de içermeleri gerekir.
