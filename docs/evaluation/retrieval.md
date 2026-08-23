# Retrieval Değerlendirmesi

`evaluation.harness.retrieval_suite`, chunk yapılandırmalarını (`RecursiveChunker`
parametreleri ve bir keşif kolu olarak `SemanticChunker`) `precision@k`, `recall@k`,
`hit_rate@k`, `MRR` ve `nDCG@k` üzerinden karşılaştırır. `evaluation/metrics.py`'de
uzun süredir yazılı olan `precision_at_k`/`recall_at_k`'ın nihayet bir çağıranı bu
suite'tir.

`evaluation/README.md`'nin RAGAS/LLM-as-judge'ı reddettiği gerekçe (yerel Ollama
~28 tok/s'de ölçüm aletinin kendisi en gürültülü terim olur) burada da geçerli:
bu suite **deterministik ve LLM'siz**.

## Neden Qdrant değil

`make eval-retrieval` `--no-deps` ile çalışır ve hiçbir altyapıya dokunmaz — bu,
`Makefile`'daki `eval` hedefinin de dayandığı aynı ilke. `evaluation.harness.
in_memory_store.InMemoryHybridStore`, gerçek `app.ai.retrieval.hybrid.
HybridRetriever`'a `vector_store` olarak enjekte edilen, yalnızca `hybrid_search`
uygulayan bir stand-in'dir. Dense sıralama cache'li vektörler üzerinde cosine
similarity, sparse sıralama **gerçek** `SparseBM25Encoder`, füzyon **gerçek**
`reciprocal_rank_fusion` (Python) ile yapılır.

**Dürüst sınır:** production Qdrant'ın native `models.Fusion.RRF`'ini (Rust)
kullanır; burada Python implementasyonu kullanılır. İkisi aynı formülü uygular
ama skor eşitliklerinde tie-breaking ve float sıralaması marjinal ayrışabilir.
Bu suite **chunk'lama şeklini** ölçer (chunk boyutu, korpus içeriği, sorgu
formülasyonu) — serving stack'in bit-bit aynısını ölçmez.

## Etiketleme: answer span containment

Alaka etiketleri **chunker'dan bağımsız** olmalı — "chunk #7 alakalı" farklı
chunk sınırları üreten kollar arasında anlamsızlaşır. Bunun yerine bir chunk,
gold `answer_spans` listesindeki en az bir span'i **birebir** (whitespace/casefold
normalizasyonu sonrası) içeriyorsa alakalı sayılır. Span'in kendisi etikettir;
annotator anlaşmazlığı yok, model çağrısı yok.

**Türkçe casefold tuzağı:** `str.lower()` `İ`'yi iki kod noktalı `'i̇'`'ye,
`I`'yı düz ASCII `'i'`'ye çevirir — ikisi de Türkçe küçük harf karşılığı değil
(`İ`→`i`, `I`→`ı` olmalı). `retrieval_suite._normalize` bu dört çifti
(`İ/I/Ş/Ğ/Ü/Ö/Ç`) elle eşleyip ardından `str.lower()` çağırıyor.

Containment **literal substring** kontrolüdür, token overlap veya fuzzy match
değil — bir cevabın iki cümleye bölünmüş hali "bütün" sayılmamalı; bu suite'in
`answer_span_intactness` istatistiğinin ölçmek istediği tam olarak bu.

## Kategoriler

| Kategori | Ne test ediyor |
|---|---|
| `tek_cumle` | Cevap tek bir cümlede |
| `paragraf_arasi` | Cevap sabit pencerenin kestiği yerde — küçük `chunk_size`'ın acı çektiği kategori |
| `uzun_baglam` | Cevap çevresini gerektiriyor — büyük `chunk_size`'ın kazandığı yer |
| `sayfa_siniri` | Cevap belirli bir sayfada — sayfa atıfı testi |
| `madde_listesi` | Numaralı mevzuat maddeleri |
| `yok` | Cevapsız sorgu — sahte güven ölçümü (aşağıya bakın) |

`paragraf_arasi` ile `uzun_baglam` bilerek **karşıt yönde** çekiyor: chunk
boyutunda bir trade-off olduğunu tek bir ortalama sayı gizlemesin diye.

## "yok" kategorisi ve `mean_yok_top1_score`

Cevapsız sorgular `precision_at_k`/`recall_at_k`/`MRR`/`nDCG` toplamından
**hariç tutulur** — bu metrikler boş bir relevant-set üzerinde tanımsızdır
ve anlamsız bir 0.0 katkısı yaparlardı. Bunun yerine `mean_yok_top1_score`
ayrı bir teşhis: korpusun hiç cevaplamadığı bir soruya yüksek-skorlu sonuç
döndüren bir yapılandırma gerçek bir başarısızlık modudur, precision/recall
bunu göremez.

## Kollar (Arms)

`evaluation.harness.retrieval_suite.ARMS`:

- `recursive-512-128`, `recursive-1000-200`, `recursive-1500-300`
  (**baseline** — `ChunkingPolicy` varsayılanları; bu suite'in kendi ilk
  ölçümü `1000/200`'ün her metrikte kaybettiğini gösterdikten sonra
  varsayılan buraya çekildi, bkz. `retrieval-baseline.md`): parametre
  süpürmesi. Asıl ayarlanabilir kaldıraç bu — bu belge türünde `chunk_size`
  stratejiden çok daha fazla oynatır.
- `semantic-p85`: **yalnızca keşif kolu.** Production'a bağlı değil (bkz.
  `SemanticChunker`'ın kendi docstring'i). Bu suite tam da onu ölçmek/kanıtlamak
  için var. `page_attribution_rate=0.0` okuması beklenir — `start_index`
  üretmediğinin sayısal kanıtı.

`k=6`, `DraftPolicy.source_chunk_count` ile aynı — manşet sayı, taslak
yazarının gerçekten aldığı şeyi tarif eder. `--retrieval-k` ile değiştirilebilir.

## Korpus ve gold set

`evaluation/datasets/retrieval_corpus/*.md` — altı Türkçe resmi yazışma örneği
(görevlendirme, izin onayı, satın alma, mevzuat maddeleri, uyarı cezası, toplantı
tutanağı), her biri `app.ai.documents.anchors.PAGE_SEPARATOR` (`"\n\n"`) ile
production'ın sayfaları birleştirme şekliyle birebir uyumlu sayfa ayraçları
taşıyor — `build_page_map` gerçekten sınanıyor.

`evaluation/datasets/retrieval.jsonl` — 23 vaka, her biri `{id, category,
document, query, expected: {answer_spans, page}}`.

## Yeniden koşma

```bash
make eval-retrieval
```

Korpus veya gold set değiştiğinde embedding cache'i yeniden üretilmeli:

```bash
docker compose run --rm --no-deps backend python scripts/build_eval_embeddings.py --target retrieval
```

Bu, `evaluation.harness.retrieval_suite.ARMS`'taki **her kolu** canlı Ollama
üzerinden bir "recording" client ile koşturur (`scripts/build_eval_embeddings.py`
docstring'i) — böylece her kolun ürettiği chunk metinleri, `semantic-p85`'in
kendi iç cümle-sınırı bölmesinin ihtiyaç duyduğu cümle metinleri ve her gold-set
sorgusu tek seferde cache'lenir. Cache miss'i eval zamanında gürültülü bir
`KeyError`'dır (`cached_embeddings.py` politikası) — bayat bir cache sessizce
degrade etmez.

## Vaka ekleme

1. `evaluation/datasets/retrieval_corpus/`'a yeni bir `.md` ekleyin veya
   mevcut birini genişletin — sayfalar arasına `\n\n` koyun.
2. `evaluation/datasets/retrieval.jsonl`'a yeni bir satır ekleyin;
   `answer_spans`'in ilgili belgede **birebir** (whitespace/casefold sonrası)
   geçtiğinden emin olun.
3. `scripts/build_eval_embeddings.py --target retrieval`'ı yeniden çalıştırın.
4. `make eval-retrieval` ile doğrulayın.

## Bu suite'in gelecekteki tek müşterisi değil

Chunk karşılaştırması bu suite'in ilk kullanım alanı, tek kullanım alanı değil.
Bir cross-encoder reranker eklenirse (bkz. proje planındaki J7), aynı suite
onun nDCG/MRR üzerindeki etkisini ölçecek alettir — kabul kriteri baseline'a
göre anlamlı bir artış olmalı.
