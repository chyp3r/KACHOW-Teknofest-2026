# Resmî Kaynak Araştırması

Bu belge yeni veriyi doğrudan üretim RAG'ına almak için değil, kaynak edinme
kararını izlenebilir kılmak için tutulur. Ayrıntılı sıra `kaynak-adaylari.csv`
dosyasındadır.

## Sonuç

- TÜRKPATENT'in iki ilanen tebligat bülteni kaynak PDF olarak değişmeden
  saklandı. Belge sınırlandırma, semantik anonimleştirme ve şablon ailesi
  tekilleştirmesinden sonra 22 farklı gerçek eksik-belge/yetkisizlik bildirimi
  kaldı. Aynı metnin yalnız başvuru numarası değişen yüzlerce kopyası kota
  doldurmak için çoğaltılmadı.
- GİB'in resmî genel yazı, sirküler, iç genelge ve özelge API uçlarından 200
  gerçek kayıt kaynak JSON anlık görüntüsü ve SHA-256 iziyle alındı. Özelgelerde
  20 olumlu, 20 ret ve 15 kısmi/karma cevap seçildi; kurumca kullanılan `…`
  maskeleri semantik yer tutuculara çevrildi.
- Bu eklemelerle kalite kapısını geçen gerçek/resmî veri 231'den 453'e, gerçek
  veri oranı %66,6'dan %79,6'ya çıktı. Dört ana yazı türünün her biri en az 100
  gerçek/resmî örneğe ulaştı.
- KDK yıllık raporu ve SHGM talimatı tekil yazışma örneği değil, karar senaryosu
  ve değerlendirme kuralı kaynağıdır; yalnız `reference_only` olabilir.
- Sağlık, engellilik veya benzeri özel nitelikli kişisel veri bağlamı taşıyan
  kaynak, adı kurumca maskelenmiş olsa bile few-shot RAG'a alınmaz.

## Edinme kapısı

Bir aday ancak aşağıdaki koşulların tamamı sağlanınca aktif veri kartına dönüşür:

1. Resmî kaynak URL'si ve erişim tarihi kaydedilir.
2. Ham dosyanın SHA-256 izi alınır; ham kaynak değiştirilmez.
3. Kullanım/lisans kararı kaydedilir. İnsan onayı tamamlanmadıysa kayıt
   `usage_review_required` olarak işaretlenir; açık lisans iddiasında bulunulmaz.
4. Belge sınırları ve şablon ailesi çıkarılır; aynı şablon çoğaltılmaz.
5. PII ve özel nitelikli veri taraması geçer.
6. Retrieval/dev/heldout ayrımı kaynak veya şablon ailesi düzeyinde yapılır.

Bu nedenle ham aday/bildirim sayısı üretim veri sayısı olarak raporlanmaz;
yalnız kalite kapısını geçen tekil şablon aileleri sayılır.
