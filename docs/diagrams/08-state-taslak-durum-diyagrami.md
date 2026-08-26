# Taslak Durum Diyagramı

Bir resmî yazı taslağının, `draft_graph` içinde oluşturulmasından nihai olarak birime yönlendirilip paylaşılmasına kadar geçirdiği durumlar.

```mermaid
stateDiagram-v2
    [*] --> OnBilgiBekleniyor: Taslak talebi geldi

    OnBilgiBekleniyor --> Yaziliyor: writing_brief.py<br/>yeterli bilgi onaylandı
    OnBilgiBekleniyor --> OnBilgiBekleniyor: Kullanıcıdan<br/>ek bilgi isteniyor

    Yaziliyor --> Dogrulaniyor: WriterAgent taslağı üretti

    Dogrulaniyor --> RevizeEdiliyor: Düzeltilebilir kusur bulundu
    RevizeEdiliyor --> Dogrulaniyor: ReviserAgent<br/>hedefli düzeltme yaptı

    Dogrulaniyor --> EksikBilgiBekleniyor: Doldurulmamış<br/>placeholder tespit edildi
    EksikBilgiBekleniyor --> EksikBilgiBekleniyor: Postgres checkpoint'te<br/>askıda bekliyor
    EksikBilgiBekleniyor --> Dogrulaniyor: Kullanıcı cevapladı<br/>apply_answers() ile devam

    Dogrulaniyor --> YonlendirmeBekleniyor: Doğrulama başarılı

    YonlendirmeBekleniyor --> InsanOnayiBekleniyor: confidence_score<br/>eşiğin altında
    YonlendirmeBekleniyor --> OtomatikOnaylandi: confidence_score<br/>eşiğin üstünde

    InsanOnayiBekleniyor --> Tamamlandi: Yetkili kullanıcı onayladı
    OtomatikOnaylandi --> Tamamlandi

    Tamamlandi --> Yonlendirildi: Önerilen birime iletildi
    Yonlendirildi --> Paylasildi: draft_shares /<br/>artifact_transfers ile paylaşıldı

    Paylasildi --> [*]
    Yonlendirildi --> [*]
```

## Notlar

- **`EksikBilgiBekleniyor`** durumu, bellekte bekleyen bir işlem değildir — LangGraph *interrupt* mekanizmasıyla Postgres'e checkpoint'lenir; sunucu yeniden başlasa bile taslak kaldığı yerden devam edebilir.
- **`RevizeEdiliyor` ↔ `Dogrulaniyor`** döngüsü sınırsız değildir; `reasoning_levels.py`'deki taslak-deneme sayısı ayarına göre üst sınırlıdır (fast/balanced/deep profillerine göre değişir).
- **`InsanOnayiBekleniyor`**, Görev 2'nin "gerekli durumlarda eksik bilgi talep edebilme" ve şeffaflık maddelerinin bir uzantısıdır — düşük güven skorlu taslaklar otomatik gönderilmez, bir insanın onayını bekler.
