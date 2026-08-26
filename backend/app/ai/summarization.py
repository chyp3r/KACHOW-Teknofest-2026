"""Ayrıntılı, sınırsız uzunlukta Türkçe belge özetleme.

`document_analysis_graph.py`'nin `analyze_node`'undan bilinçli olarak bağımsız;
o, alan çıkarımına ayarlanmış bir çağrının yan ürünü olarak kendi kısa özetini
üretir (tam gerekçe için `SummaryOutput`'un kendi docstring'ine bakın). Bu
modül, o ayrı çağrının arkasındaki mantığı tutar, böylece talep üzerine
çalışabilir -- `DocumentService.generate_detailed_summary` tarafından
tetiklenir, her `analyze_document` çağrısının içinde istekli biçimde değil --
çünkü doğrudan ölçüldüğünde bu, bu projenin belge pipeline'ındaki en yavaş
tek işlemdir (gerçek belgelerde 184-288s, `analyze_node`'un kendi 26-93s'ine karşı).
"""

import logging

from pydantic import BaseModel, Field

from app.ai.agents.summarizer import SummarizerAgent
from app.ai.embeddings.chunking.recursive import RecursiveChunker

logger = logging.getLogger(__name__)

#: Özetleyici için kendi bütçesi, analyze_node'un ANALYSIS_MAX_TOKENS'ından
#: bilinçli olarak ayrı: o bütçe aynı çağrıda document_type + ~14 EvrakField
#: değeriyle paylaşılır, bu yüzden ayrıntılı bir özet yalnızca artakalan
#: küçük bir dilim alırdı.
SUMMARY_MAX_TOKENS = 1024
#: (analyze_node'un _trim_for_extraction'ının aksine kırpılmamış) metni tek
#: bir parçaya sığan bir belge tek bir çağrıda özetlenir; daha uzun belgeler
#: aşağıdaki map-reduce'dan geçer, böylece yalnızca baş+kuyruk değil belgenin
#: tamamı özeti bilgilendirir.
#:
#: Bilinçli olarak app.ai.policy.schema.ChunkingPolicy'den KAYNAKLANMAZ: o
#: politika alma (retrieval) parçalamayı (Document Q&A, mevzuat korpusu)
#: yönetir; farklı bir ayarlama hedefi (map-reduce çağrı sayısı değil, yanıt
#: aralığı yerelliği) olan farklı bir konudur. Bu çifti yerel tutmak, iki
#: ilgisiz ayarlama kararını tek bir paylaşılan değere bağlamayı önler.
SUMMARY_CHUNK_SIZE = 4000
SUMMARY_CHUNK_OVERLAP = 400
#: Map aşaması çağrıları üzerinde sert bir sınır. 50 sayfalık bir belge 50
#: LLM çağrısı olmamalıdır; bu sınırın ötesindeki kapsam sessizce
#: kırpılmak yerine düşürülür ve loglanır (bkz. build_detailed_summary). Map
#: aşaması sıralı çalıştığında (asyncio.gather()'ın burada neden yanlış
#: olduğuna dair kendi yorumuna bakın) iki gerçek belgeye karşı izole
#: düğüm-başı zamanlamayla (graph.astream(..., stream_mode="updates"))
#: doğrudan ölçüldü: CY-010 (2 map parçası) her biri 35-97s süren 3 çağrı
#: gerektirdi; CY-049 (3 map parçası) tek tek 185s'e kadar yavaş olan 4 çağrı
#: gerektirdi. Bu projenin donanımında (Ollama üzerinden qwen3.5:9b, tek bir
#: üretim slotu) çağrı başına gecikme hem yüksek hem de oldukça değişken --
#: daha yüksek değil 3'te sınırlandı, böylece DETAILED_SUMMARY_TIMEOUT_SECONDS
#: bütçesinin (bkz. core.config), kimsenin gerçek serileştirilmiş gecikmeye
#: karşı kontrol etmediği bir sayı olmak yerine en kötü durumu kapsamak için
#: gerçek bir şansı var.
SUMMARY_MAX_MAP_CHUNKS = 3


class SummaryOutput(BaseModel):
    """Belgenin tamamının veya bir parçasının ayrıntılı bir özeti.

    Bilinçli olarak açıklamasında cümle sayısı sınırı taşımaz -- bu şemanın
    DocumentClassificationOutput.summary / DocumentAnalysisOutput.summary'den
    (document_analysis_graph.py) ayrı var olmasının tüm amacı budur; ikisi de
    "en çok 3 cümle"ye sınırlandırılmıştır (oradaki kendi Field
    açıklamalarına bakın). Bir regresyon testi
    (test_summary_output_field_carries_no_sentence_cap), bu açıklamanın o
    ifadeyi asla yeniden tanıtmadığını doğrular.
    """

    detailed_summary: str = Field(
        description=(
            "Evrakın (veya verilen metin parçasının) ayrıntılı, nesnel Türkçe "
            "özeti. Cümle sayısı sınırı yok -- belgenin konusu, tarafları, "
            "talebi/kararı, gerekçesi, atıfları (sayı/tarih/ilgi) ve varsa "
            "ekleri kapsayacak kadar ayrıntılı olsun."
        )
    )


def ocr_warning(is_ocr_text: bool) -> str:
    """Metin OCR'den geldiğinde bir prompt notu döndürür.

    Args:
        is_ocr_text: Kaynak metnin OCR ile üretilip üretilmediği.

    Returns:
        Türkçe bir uyarı string'i, veya boş bir string.
    """
    if not is_ocr_text:
        return ""
    return (
        "\n\nUYARI: Bu metin taranmış bir belgeden OCR ile okunmuştur; harf "
        "hataları olabilir. Emin olmadığın alanları uydurmak yerine null bırak."
    )


async def _summarize_chunk(
    summarizer_agent: SummarizerAgent, chunk_text: str, *, is_partial: bool, is_ocr_text: bool
) -> str:
    """Bütün belge veya bir parçası üzerinde tek bir SummarizerAgent çağrısı."""
    instruction = (
        "Aşağıdaki metin, bir evrakın YALNIZCA BİR PARÇASIDIR. Yalnızca bu "
        "parçadaki bilgiyi ayrıntılı biçimde özetle."
        if is_partial
        else "Aşağıdaki evrakın tamamını ayrıntılı biçimde özetle."
    )
    prompt = f'{instruction}{ocr_warning(is_ocr_text)}\n\nMETİN:\n"""\n{chunk_text}\n"""'
    res: SummaryOutput = await summarizer_agent.run_structured(
        messages=prompt,
        response_model=SummaryOutput,
        temperature=0.0,
        max_tokens=SUMMARY_MAX_TOKENS,
    )
    return res.detailed_summary


async def _reduce_partial_summaries(summarizer_agent: SummarizerAgent, partials: list[str]) -> str:
    """Parça başına kısmi özetleri tek, tutarlı bir ayrıntılı özette birleştirir.

    Kısmi özetler zaten temiz model çıktısıdır, ham OCR metni değil, bu
    yüzden bu çağrı -- _summarize_chunk'ın çağıranlarının aksine -- hiç
    ocr_warning taşımaz.

    Yapılandırılmış çıktı değil, düz üretim (SummarizerAgent.run) kullanır --
    bilinçli olarak, bir gözden kaçırma değil. İki gerçek belge üzerinde
    (CY-034, CY-049) doğrudan ölçüldü: her map çağrısı zaten başarılı olup
    geriye yalnızca reduce çağrısı kaldığında, run_structured'ın
    method="function_calling" yolu (bu projenin o metodu neden hiç sabitlediği
    için bkz. OllamaClient.generate_structured'ın kendi docstring'i),
    qwen3.5:9b'yi daha büyük birleştirilmiş prompt üzerinde SummaryOutput
    aracını çağırmaya ikna edemedi, denemeleri tüketti -- bu, tek seferlik
    bir tesadüf değil, her iki belgede de tekrarlandığından bu model/harness
    için bu prompt şeklinde gerçek bir çağrı-başı güvenilirlik sınırıdır.
    Reduce, alan çıkarımının ihtiyaç duyduğu gibi doğrulanmış bir şemaya
    ihtiyaç duymaz; yalnızca serbest metne ihtiyaç duyar, bu yüzden run()
    hiç araç çağrısı istemeyerek tüm başarısızlık modunu atlar.

    Yine de başarısızlıkta, kendi iç "Parça N:" etiketleri OLMADAN
    birleştirilmiş kısmi özetlere düşer -- bunlar yalnızca modelin ayrı
    bölümleri birleştirdiğini anlamasına yardımcı olmak için var ve asla
    bir kullanıcının ekranına kelimesi kelimesine ulaşması amaçlanmamıştı
    (bu yedeğin daha eski bir sürümü onları doğrudan sızdırıyordu). Hata
    fırlatmak yerine hiç yedeğe düşmek başlı başına önemlidir: pahalı map
    aşamasını geçen bir belge, çağıranın dış try/except'inin
    analyze_node'un genel üç cümlelik özetine kadar düşürmesi yerine
    kazandığını korumalıdır.
    """
    labelled = "\n\n".join(
        f"Parça {index + 1}: {partial}" for index, partial in enumerate(partials)
    )
    prompt = (
        "Aşağıda bir evrakın farklı parçalarından çıkarılan kısmi özetler "
        "verilmiştir. Bunları tekrarsız, tutarlı ve akıcı TEK bir ayrıntılı "
        f"özette birleştir. Yalnızca birleştirilmiş özeti yaz; başka "
        f"açıklama, başlık veya \"Parça\" etiketi ekleme.\n\n{labelled}"
    )
    try:
        return await summarizer_agent.run(
            messages=prompt, temperature=0.0, max_tokens=SUMMARY_MAX_TOKENS
        )
    except Exception:
        logger.warning(
            "Detailed summary: reduce call failed; falling back to the "
            "joined partial summaries.",
            exc_info=True,
        )
        return "\n\n".join(partials)


async def build_detailed_summary(
    summarizer_agent: SummarizerAgent, text: str, *, is_ocr_text: bool
) -> str:
    """Bir tam belgenin ayrıntılı Türkçe özetini üretir.

    Kısa belgeler: tam (kırpılmamış -- analyze_node'un
    _trim_for_extraction'ının aksine) metin üzerinde tek bir çağrı. Uzun
    belgeler: RecursiveChunker'ın parçaları üzerinde, SUMMARY_MAX_MAP_CHUNKS
    ile sınırlandırılmış map-reduce (sınırın ötesindeki kapsamın neden
    sessizce dahil edilmek yerine düşürüldüğü için o sabitin kendi
    docstring'ine bakın).

    Args:
        summarizer_agent: Alttaki LLM çağrılarını yapan ajan.
        text: Tam belge metni (zaten çıkarılmış ve temizlenmiş).
        is_ocr_text: Kaynak metnin OCR'den gelip gelmediği; promptu bir
            uyarı notuyla eklemek için.

    Returns:
        Ayrıntılı özet metni.

    Raises:
        Exception: Tek-çağrı yolunda veya map aşamasında alttaki sağlayıcı
            çağrısının fırlattığı her ne ise -- çağıranların bunu kendi
            zaman aşımlarıyla sınırlaması ve bu modülün docstring'inin
            tanımladığı tasarımı yansıtarak hata durumunda kısa bir özete
            düşmesi beklenir. (Reduce aşaması bunun yerine dahili olarak
            düşer; nedeni için _reduce_partial_summaries'in kendi
            docstring'ine bakın.)
    """
    if len(text) <= SUMMARY_CHUNK_SIZE:
        return await _summarize_chunk(summarizer_agent, text, is_partial=False, is_ocr_text=is_ocr_text)

    chunker = RecursiveChunker(chunk_size=SUMMARY_CHUNK_SIZE, chunk_overlap=SUMMARY_CHUNK_OVERLAP)
    chunks = await chunker.split_text(text)
    if len(chunks) > SUMMARY_MAX_MAP_CHUNKS:
        logger.warning(
            "Detailed summary: document split into %d chunks, capping at %d -- "
            "coverage past the cap is dropped, not silently included.",
            len(chunks),
            SUMMARY_MAX_MAP_CHUNKS,
        )
        chunks = chunks[:SUMMARY_MAX_MAP_CHUNKS]

    # asyncio.gather() değil, sıralı: Ollama, istemci tarafı eşzamanlılıktan
    # bağımsız olarak üretimi tek bir modele karşı serileştirir (bkz.
    # vision.py'nin tam olarak bu nokta üzerine kendi belgelenmiş bulgusu).
    # Her map çağrısını aynı anda ateşlemek hiçbir şey kazandırmadı ve
    # durumu kötüleştirdi -- CY-049'a karşı doğrudan doğrulandı; burada bir
    # çağrının kendi tamamlanma log satırı, çağıranın zaten zaman aşımına
    # uğrayıp döndüğünden *sonra* göründü, çünkü dıştaki wait_for'un iptali
    # Python seviyesindeki await'i terk eder ama sunucu tarafında zaten
    # kuyruğa alınmış istekleri durdurmaz. Sıralı bir döngü, bir zaman
    # aşımının SUMMARY_MAX_MAP_CHUNKS kadarını değil yalnızca bir çağrıyı
    # yetim bırakması anlamına gelir.
    partials = [
        await _summarize_chunk(summarizer_agent, chunk.page_content, is_partial=True, is_ocr_text=is_ocr_text)
        for chunk in chunks
    ]
    return await _reduce_partial_summaries(summarizer_agent, partials)
