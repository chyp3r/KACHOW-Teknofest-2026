# Frontend Design System

Bu doküman frontend ölçü, yüzey ve etkileşim sisteminin uygulama sözleşmesini tanımlar. Tek kaynak `frontend/src/styles/design-system.css`; ortak React bileşenleri `frontend/src/components/` altındadır.

## Geçiş öncesi denetim özeti

Denetim `App.css`, `integration.css`, `typography.css` ve üretim TSX dosyalarının tamamında padding, margin, gap, boyut, border, radius, shadow, inline style ve yerel kontrol uygulamalarını taradı. Aşağıdaki tablo en sık tekrarlanan değerleri gösterir; sayılar geçiş öncesi kaynak durumuna aittir.

| Mevcut değer | Kullanım | Adet | Başlıca kullanan alanlar | Hedef token | Geçiş |
| --- | --- | ---: | --- | --- | --- |
| `gap: 8px` | gap | 35 | shell, toolbar, form, composer, drawer | `--space-2` | Ortak layout/control gap'i |
| `gap: 9px` | gap | 14 | navigation, session/draft rows | `--space-2` | 4 px ölçeğine yuvarlandı |
| `gap: 10px` | gap | 15 | card grids, lists, workflow | `--space-3` | 12 px semantik gap |
| `gap: 12px` | gap | 14 | form actions, panels, rows | `--space-3` | Tokenlaştırıldı |
| `padding: 12px` | padding | 8 | fields, cards, rows | `--space-3` | Primitive/composite içinde merkezileştirildi |
| `padding: 20px` | padding | 8 | default cards/panels | `--space-5` | `Card` default padding |
| `padding: 14px` | padding | 7 | lists, drawers, cards | `--space-4` | 16 px ölçeğine taşındı |
| `border-radius: 9px` | radius | 16 | buttons, rows, cards | `--radius-md` | 8 px kontrol radius'u |
| `border-radius: 10px` | radius | 12 | cards, rows | `--radius-md` / `--radius-lg` | Role göre 8/12 px |
| `border-radius: 8px` | radius | 13 | inputs, buttons, search | `--radius-md` | Primitive içinde merkezileştirildi |
| `1px solid var(--border-glass)` | border | 30 | cards, forms, rows, overlays | `--border-default` | Semantik border tokenı |
| `width: 44px` | width | 11 | mobile/sidebar/icon actions | `--touch-target` | 44×44 erişilebilir hedef |
| `height: 44px` | height | 8 | mobile/sidebar/icon actions | `--touch-target` | `IconButton lg`/touch hedefi |
| `min-height: 40px` | height | 4 | input/select/search | `--control-md` | Varsayılan kontrol yüksekliği |
| `36×36px` | icon container | 5 | evrak/taslak/interrupt ikonları | `--icon-container-sm/md` | 32 veya 40 px role göre |

Tek üretim inline style istisnası teknik SVG grafiğinin veri kaynaklı koordinat değişkenleridir. Bu değerler görsel spacing değil, çizge geometrisidir.

## Tokenlar

- Spacing: `--space-0`, `--space-1`, `--space-2`, `--space-3`, `--space-4`, `--space-5`, `--space-6`, `--space-8`, `--space-10`, `--space-12`, `--space-16`.
- Controls: `--control-sm`, `--control-md`, `--control-lg`, `--touch-target`.
- Icons: `--icon-xs`…`--icon-xl`; containerlar 32, 40 ve 48 pikseldir.
- Radius: `--radius-sm`, `--radius-md`, `--radius-lg`, `--radius-xl`, `--radius-full`.
- Borders/elevation: default, strong, interactive, focus, error, disabled border; subtle ve overlay shadow.
- Surface rolleri: app, sidebar, content, panel, interactive, elevated ve input. Açık/koyu tema yalnız token değerlerini değiştirir; bileşenler tema adına göre özel renk seçmez.
- Shell rolleri: geniş sidebar 248 piksel, dar sidebar 76 pikseldir; teknik grafik açıldığında üçüncü kolon bu roller korunarak genişler.
- Responsive gutter: desktop 32, tablet 24, mobile 16 pikseldir.

## Bileşen sözleşmesi

Primitive katman: `Button`, `IconButton`, `Input`, `Select`, `Textarea`, `FormField`, `Card`, `StatusBadge`, `Alert`, `Divider`, `Spinner`, `Skeleton`.

Composite katman: `PageHeader`, `SectionHeader`, `EmptyState`, `ErrorState`, `ApiErrorNotice`, `ListRow`, `Drawer`, `Dialog`, `ConfirmationDialog`, `FormActions`.

Feature composite katmanı: `WorkflowStepper`, `DocumentListItem` ve `DraftTable`. Bu üç bileşen aynı primitive ve tokenları kullanır; ancak bilgi mimarileri farklı olduğu için genel `ListRow` içine zorlanmaz. Workflow marker rail ve durum akışını, evrak satırı özet+metadata ilişkisini, taslak tablosu ise kolon ve responsive alan etiketlerini kendi feature sınırında sahiplenir.

Layout katmanı: `Stack`, `Inline`, `Cluster`, `Grid`. Gap prop'ları yalnız token anahtarlarını kabul eder; raw piksel prop'u yoktur.

Sayfalar yalnız `variant`, `size`, `status`, `loading`, `error` ve `selected` gibi semantik prop'larla bu bileşenleri oluşturur. `className` yalnız feature yerleşim bağlantısı içindir; primitive iç padding, border, radius veya state'leri değiştirmek için kullanılmaz.

## State ve erişilebilirlik

Button ve form kontrolleri default, hover, active, focus-visible, disabled ve loading/error durumlarını paylaşır. Focus halkası iki piksel ve iki piksel offset'tir. Loading button label'ı DOM'da tutarak genişliği korur. Icon-only eylemler TypeScript seviyesinde `aria-label` zorunlu kılar.

`FormField`, label/description/helper/error ilişkilerini `htmlFor`, `aria-describedby` ve `aria-invalid` ile kurar. `Drawer` ve `Dialog` Escape, focus trap, scroll lock ve kapanışta focus dönüşünü merkezileştirir.

## İstisnalar

- Teknik iş-akışı SVG'sindeki `viewBox`, node/edge koordinatları ve veri kaynaklı CSS değişkenleri graf geometrisidir; spacing tokenına dönüştürülmez.
- Chat composer tek satırdan büyüyen içerik tabanlı textarea kullanır; genel 80/96/120 px textarea minimumları yerine `--control-lg` başlangıç yüksekliğine sahiptir.
- Range input native semantiğini korur; label ve dikey ritim `FormField` tarafından sağlanır.
- Sidebar, drawer ve okunabilir sohbet genişlikleri ürün yerleşim geometrisidir; spacing tokenı değildir ve mimari dokümanda kayıtlıdır.
