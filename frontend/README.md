# KACHOW Frontend

React, TypeScript ve Vite tabanlı istemci; gerçek backend sözleşmesini servisler ve feature hook'ları üzerinden tüketir.

## Geliştirme

```bash
npm install
npm run dev
```

Vite, `/api` isteklerini geliştirme ortamında backend'e yönlendirir. Uygulama rotaları React Router ile yönetilir; sunucu verileri TanStack Query cache'inde tutulur.

## Kalite komutları

```bash
npm run typecheck
npm run lint
npm run test
npm run build
```

## API tipleri

Backend `http://localhost:8000/openapi.json` adresinde çalışırken:

```bash
npm run api:types
npm run api:types:check
```

Üretilen dosya `src/api/generated.ts` altında commit edilir. Backend şeması değiştiğinde bu dosya yeniden üretilmeli ve kullanılan sözleşme alias'ları güncellenmelidir. OpenAPI'nin tarif etmediği SSE olayları `src/types/chat.ts` içinde, backend event modelleriyle ayrı olarak eşleştirilir.

## Durum ve güvenlik

- Access/refresh token'ları sekme ömrüyle sınırlı `sessionStorage` içinde tutulur.
- Eşzamanlı `401` yanıtları tek refresh isteğinde birleştirilir; başarısız refresh güvenli çıkış üretir.
- Belge, sohbet, mesaj ve taslaklar için backend tek doğruluk kaynağıdır; kalıcı iş verisi `localStorage` içinde tutulmaz.
- `localStorage` yalnızca görsel tema tercihi için kullanılır.
- Rol kontrolleri kullanıcı deneyimini düzenler; gerçek yetkilendirme backend tarafından uygulanır.

## Katmanlar

`pages → hooks → services → backend` yönü korunur. `query/queryKeys.ts` cache anahtarlarını merkezileştirir; ortak sağlayıcılar `main.tsx`, uygulama rotaları `App.tsx` içindedir.

## Tasarım sistemi

Spacing, control, icon, radius, border, focus ve elevation tokenları `src/styles/design-system.css` içindedir. Sayfalar ortak `src/components` primitive/composite/layout bileşenlerini compose eder; feature stilleri bu bileşenlerin iç geometrisini yeniden tanımlamaz. Denetim envanteri, kullanım sözleşmesi ve istisnalar `docs/development/frontend-design-system.md` dosyasında belgelenmiştir.
