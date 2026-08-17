"""Detailed, unbounded-length Turkish document summarization.

Deliberately independent of `document_analysis_graph.py`'s `analyze_node`, which
produces its own short summary as a byproduct of a call tuned for field
extraction (see `SummaryOutput`'s own docstring for the full reasoning). This
module holds the logic behind that separate call so it can run on-demand --
triggered by `DocumentService.generate_detailed_summary`, not eagerly inside
every `analyze_document` call -- since it is, measured directly, the single
slowest operation in this project's document pipeline (184-288s on real
documents, against `analyze_node`'s own 26-93s).
"""

import logging

from pydantic import BaseModel, Field

from app.ai.agents.summarizer import SummarizerAgent
from app.ai.embeddings.chunking.recursive import RecursiveChunker

logger = logging.getLogger(__name__)

#: Own budget for the summarizer, deliberately separate from analyze_node's
#: ANALYSIS_MAX_TOKENS: that budget is shared with document_type + ~14
#: EvrakField values in the same call, so a detailed summary would only ever
#: get whatever sliver was left over.
SUMMARY_MAX_TOKENS = 1024
#: A document whose (untrimmed, unlike analyze_node's _trim_for_extraction)
#: text fits in one chunk is summarised in a single call; longer documents go
#: through map-reduce below so the whole document -- not just head+tail --
#: informs the summary.
SUMMARY_CHUNK_SIZE = 4000
SUMMARY_CHUNK_OVERLAP = 400
#: Hard cap on map-stage calls. A 50-page document must not become 50 LLM
#: calls; coverage past this cap is dropped and logged rather than silently
#: truncated (see build_detailed_summary). Measured directly with isolated
#: per-node timing (graph.astream(..., stream_mode="updates")) against two
#: real documents once the map stage ran sequentially (see its own comment on
#: why asyncio.gather() was wrong here): CY-010 (2 map chunks) needed 3 calls
#: at 35-97s each; CY-049 (3 map chunks) needed 4 calls, individually as slow
#: as 185s. On this project's hardware (qwen3.5:9b over Ollama, one
#: generation slot) per-call latency is both high and highly variable --
#: capped at 3, not higher, so the DETAILED_SUMMARY_TIMEOUT_SECONDS budget
#: (see core.config) has a real chance of covering the worst case instead of
#: being a number nobody checked against actual serialized latency.
SUMMARY_MAX_MAP_CHUNKS = 3


class SummaryOutput(BaseModel):
    """A detailed summary, of either the whole document or one chunk of it.

    Deliberately carries no sentence-count cap in its description -- that is
    the entire point of this schema existing separately from
    DocumentClassificationOutput.summary / DocumentAnalysisOutput.summary
    (document_analysis_graph.py), both of which are capped at "en çok 3
    cümle" (see their own Field descriptions there). A regression test
    (test_summary_output_field_carries_no_sentence_cap) asserts this
    description never reintroduces that phrase.
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
    """Return a prompt note when the text came from OCR.

    Args:
        is_ocr_text: Whether the source text was produced by OCR.

    Returns:
        A Turkish caution string, or an empty string.
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
    """One SummarizerAgent call over either the whole document or one chunk of it."""
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
    """Combine per-chunk partial summaries into one coherent detailed summary.

    The partials are already-clean model output, not raw OCR text, so this
    call carries no ocr_warning -- unlike _summarize_chunk's callers.

    Uses plain generation (SummarizerAgent.run), not structured output --
    deliberately, not an oversight. Measured directly on two real documents
    (CY-034, CY-049): with every map call already succeeded and the reduce
    call the only thing left, run_structured's method="function_calling"
    path (see OllamaClient.generate_structured's own docstring for why this
    project pins that method at all) failed to get qwen3.5:9b to invoke the
    SummaryOutput tool on the larger combined prompt, exhausting retries --
    a real per-call reliability limit on this model/harness for this prompt
    shape, not a one-off fluke, since it reproduced on both documents.
    Reduce doesn't need a validated schema the way field extraction does; it
    only needs free text, so run() sidesteps the whole failure mode by never
    asking for a tool call in the first place.

    On failure even so, falls back to the partials themselves, joined
    WITHOUT their internal "Parça N:" labels -- those exist only to help the
    model understand it is combining separate sections, and were never meant
    to reach a user's screen verbatim (an earlier version of this fallback
    leaked them straight through). Falling back at all, rather than raising,
    matters on its own: a document that made it through the expensive map
    stage should keep what it earned instead of the caller's outer
    try/except degrading all the way to analyze_node's generic
    three-sentence summary.
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
    """Produce a detailed Turkish summary of a full document.

    Short documents: one call over the full (untrimmed -- unlike
    analyze_node's _trim_for_extraction) text. Long documents: map-reduce
    over RecursiveChunker's chunks, capped at SUMMARY_MAX_MAP_CHUNKS (see
    that constant's own docstring for why coverage past the cap is dropped
    rather than silently included).

    Args:
        summarizer_agent: The agent making the underlying LLM calls.
        text: The full document text (already extracted and scrubbed).
        is_ocr_text: Whether the source text came from OCR, to add a caution
            note to the prompt.

    Returns:
        The detailed summary text.

    Raises:
        Exception: Whatever the underlying provider call raised, on the
            single-call path or the map stage -- callers are expected to
            bound this with their own timeout and degrade to a short summary
            on failure, mirroring the design this module's docstring
            describes. (The reduce stage degrades internally instead; see
            _reduce_partial_summaries's own docstring for why.)
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

    # Sequential, not asyncio.gather(): Ollama serialises generation against
    # one model regardless of client-side concurrency (see vision.py's own
    # documented finding on this exact point). Firing every map call at once
    # bought nothing and made it worse -- verified directly against CY-049,
    # where a call's own completion log line appeared *after* the caller had
    # already timed out and returned, because the outer wait_for's
    # cancellation abandons the Python-level await but does not stop
    # requests already queued server-side. A sequential loop means a timeout
    # only ever leaves one call orphaned, not up to SUMMARY_MAX_MAP_CHUNKS of
    # them.
    partials = [
        await _summarize_chunk(summarizer_agent, chunk.page_content, is_partial=True, is_ocr_text=is_ocr_text)
        for chunk in chunks
    ]
    return await _reduce_partial_summaries(summarizer_agent, partials)
