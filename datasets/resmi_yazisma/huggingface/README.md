---
license: apache-2.0
language:
- tr
pretty_name: Türkçe Resmî Yazışma Veri Seti
task_categories:
- text-generation
- text-classification
tags:
- turkish
- official-correspondence
- government
- legal
- bureaucracy
- retrieval
- rag
size_categories:
- 1K<n<10K
configs:
- config_name: default
  data_files:
  - split: ust_yazi
    path: ust_yazi.jsonl
  - split: cevap_yazisi
    path: cevap_yazisi.jsonl
  - split: bilgilendirme_metni
    path: bilgilendirme_metni.jsonl
  - split: dilekce
    path: dilekce.jsonl
  - split: diger_resmi_yazisma
    path: diger_resmi_yazisma.jsonl
---

# Türkçe Resmî Yazışma Veri Seti

Bu veri seti Teknofest 2026 KACHOW takımı için oluşturulmuştur.

Açık kaynak resmî yazışma kurumlarından derlenmiş, anonimleştirilmiş bir
Türkçe belge külliyatı. Üst yazı, cevap yazısı, bilgilendirme metni, dilekçe
ve diğer resmî yazışma türlerini kapsar; bir yazışma asistanının biçim,
üslup ve içerik yapısını öğrenmesi/başvurması için tasarlanmıştır.

## Veri seti özeti

- **1.763 belge**
- **5** yazışma kategorisi: cevap yazısı, üst yazı, bilgilendirme metni,
  dilekçe, diğer resmî yazışma
- Kaynak: resmî kurum web siteleri, açık kamu API'leri, yayımlanmış
  genelge/sirküler/tebliğ metinleri
- Her kayıt **kişisel verilerden arındırılmıştır** — ad-soyad, T.C. kimlik
  no, telefon, e-posta, IBAN gibi alanlar bağlama duyarlı yer tutucularla
  (`[KİŞİ ADI]`, `[T.C. KİMLİK NO]`, ...) değiştirilmiştir

## Kategori dağılımı

Her kategori ayrı bir dosyada / split'te:

| Kategori | Dosya | Belge |
| --- | --- | ---: |
| Diğer resmî yazışma | `diger_resmi_yazisma.jsonl` | 531 |
| Bilgilendirme metni | `bilgilendirme_metni.jsonl` | 418 |
| Cevap yazısı | `cevap_yazisi.jsonl` | 370 |
| Üst yazı | `ust_yazi.jsonl` | 330 |
| Dilekçe | `dilekce.jsonl` | 114 |
| **Toplam** | `tumu.jsonl` | **1.763** |

## Kullanım alanları

- Resmî yazışma taslağı üreten bir dil modeli için biçim/üslup referansı
  (retrieval-augmented generation)
- Yazışma türü sınıflandırması
- Türkçe bürokratik dil/kayıt üzerine araştırma

## Veri yapısı

Her kayıt bir JSON satırıdır. Alanlar:

| Alan | Açıklama |
| --- | --- |
| `id` | Kaynak kartın kimliği |
| `kategori` | `cevap_yazisi` \| `ust_yazi` \| `bilgilendirme_metni` \| `dilekce` \| `diger_resmi_yazisma` |
| `alt_kategori` | Kategori içindeki alt tür klasörü |
| `niyet` | Alt tür/amaç etiketi (ör. `egitim_mufredat_duyurusu`) |
| `baslik` | Belge başlığı |
| `kurum` | Yazışmayı yapan kurum |
| `belge_turu` | Belgenin geldiği süreç (ör. `tamamlanmis_resmi_cevap`, `resmi_sablon`) |
| `text` | Belgenin tam, anonimleştirilmiş Markdown metni |
| `char_len` | `text` uzunluğu |
| `source_path` | Repo içindeki kaynak dosya yolu |
| `source_group` | İçerik özetine dayalı, kaynağı gruplayan kimlik |

## Veri oluşturma süreci

1. **Toplama** — resmî kurum siteleri, açık kamu API'leri ve yayımlanmış
   genelge/tebliğ arşivlerinden PDF, HTML, DOCX ve API çıktısı olarak
   toplandı.
2. **Dönüştürme** — her belge OCR/parse edilerek tek biçimli Markdown'a
   çevrildi; başlık, kurum, tarih gibi alanlar yapılandırılmış metadata
   olarak ayrıştırıldı.
3. **Anonimleştirme** — bağlama duyarlı bir kural motoru; kişi adı, imza
   sahibi, vekil, T.C. kimlik no (checksum doğrulamalı), telefon, e-posta,
   IBAN ve çeşitli kayıt/sicil numaralarını tespit edip semantik yer
   tutucularla değiştirdi. Sonuç ayrıca ayrı bir denetim geçişinden
   geçirildi.

## Lisans

Bu veri setinin kodu, şeması, anonimleştirme/küratasyon işlemleri ve
derlenmiş hâli **Apache License 2.0** ile lisanslanmıştır.

Kaynak belgelerin büyük bölümü açık kaynak resmî yazışma kurumlarının resmî
olarak yayımladığı metinlerdir (genelge, tebliğ, sirküler, bilgilendirme);
5846 sayılı Fikir ve
Sanat Eserleri Kanunu'nun 30. maddesi uyarınca bu tür resmî ilan edilmiş
metinler eser sayılmaz. İçerik yayınlanmadan önce kişisel veriler
tamamen arındırılmıştır.

## Atıf

```
@misc{resmi_yazisma_2026,
  title  = {Türkçe Resmî Yazışma Veri Seti},
  author = {KACHOW Teknofest 2026 Ekibi},
  year   = {2026},
  note   = {https://huggingface.co/datasets/Ygthn/Teknofest_2026_KACHOW}
}
```
