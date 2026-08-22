# Deterministik Karar Katmanı Değerlendirme Raporu

> Bu rapor `make eval` ile üretilir ve **hiç LLM çağrısı içermez**.
> Ölçülen, üretim kodundaki deterministik karar fonksiyonlarının kendisidir.

Policy sürümü: `3.0.0`

## Suite: `retrieval`

Altın küme: `evaluation/datasets/retrieval.jsonl` · Koşu: 2026-08-22T18:29:25 · Süre: 11.3 ms

> Qdrant kullanılmaz, yerel RRF ile ölçülür (bkz. `docs/evaluation/retrieval.md`). k=6, baseline=`recursive-1000-200` (production ChunkingPolicy varsayılanları).

### Kollar arası karşılaştırma

| Metrik | `recursive-512-128` | `recursive-1000-200` **(baseline)** | `recursive-1500-300` | `semantic-p85` |
|---|---|---|---|---|
| Precision@k | 0.3912 | 0.8421 | 1.0000 | 0.7632 |
| Recall@k | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| Hit rate@k | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| MRR | 0.8158 | 0.9211 | 1.0000 | 0.9211 |
| nDCG@k | 0.8640 | 0.9417 | 1.0000 | 0.9417 |
| Yok top-1 skoru (düşük iyi) | 0.0327 | 0.0327 | 0.0328 | 0.0328 |

### Baseline'a göre Δ (yalnızca cevaplanabilir vakalar)

| Kol | ΔPrecision@k | ΔnDCG@k | ΔMRR |
|---|---|---|---|
| `recursive-512-128` | -0.4509 | -0.0777 | -0.1053 |
| `recursive-1500-300` | +0.1579 | +0.0583 | +0.0789 |
| `semantic-p85` | -0.0789 | +0.0000 | +0.0000 |

### Korpus istatistikleri

| Kol | Chunk sayısı | Ort. uzunluk | p50 | p95 | Sayfa atıf oranı | Span bütünlüğü |
|---|---|---|---|---|---|---|
| `recursive-512-128` | 17 | 334 | 379 | 502 | 1.00 | 1.00 |
| `recursive-1000-200` | 8 | 697 | 880 | 922 | 1.00 | 1.00 |
| `recursive-1500-300` | 6 | 930 | 922 | 1172 | 1.00 | 1.00 |
| `semantic-p85` | 9 | 618 | 672 | 1078 | 0.00 | 1.00 |

### Kategori kırılımı (baseline kolu)

| Kategori | Vaka | P@k | nDCG@k | MRR |
|---|---|---|---|---|
| `madde_listesi` | 4 | 1.00 | 1.00 | 1.00 |
| `paragraf_arasi` | 2 | 0.50 | 0.82 | 0.75 |
| `sayfa_siniri` | 4 | 0.88 | 1.00 | 1.00 |
| `tek_cumle` | 6 | 0.83 | 0.94 | 0.92 |
| `uzun_baglam` | 3 | 0.83 | 0.88 | 0.83 |
| `yok` | 4 | - | - | - |

