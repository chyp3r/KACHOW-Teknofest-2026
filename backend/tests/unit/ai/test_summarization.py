"""Unit tests for on-demand detailed document summarization.

Calls `build_detailed_summary` directly rather than driving a whole
LangGraph run through `create_document_analysis_graph` -- this pipeline is
no longer a graph node (see `create_document_analysis_graph`'s own
docstring for why: measured directly, it was the slowest branch in the
graph by a wide margin, and every upload paid its cost whether or not
anyone read the result). It is on-demand now, triggered by
`DocumentService.generate_detailed_summary`, which is tested separately in
`tests/unit/domains/test_document_service.py` for the cache-mutation and
timeout-handling behaviour around this module's pure functions.
"""

import asyncio
import re
from unittest.mock import MagicMock, patch

import pytest

from app.ai.agents.summarizer import SummarizerAgent
from app.ai.llms.base import BaseLLMClient
from app.ai.prompts.manager import get_prompt_manager
from app.ai.summarization import SummaryOutput, build_detailed_summary

OFFICIAL_LETTER_TEXT = (
    "T.C.\nÖRNEK BAKANLIĞI\nSayı: E-123-456\nTarih: 30.07.2026\n"
    "Konu: Yıllık İzin Talebi\nİLGİLİ MAKAMA\nMehmet Öztürk\nGenel Müdür"
)


def _agent() -> SummarizerAgent:
    return SummarizerAgent(MagicMock(spec=BaseLLMClient))


@pytest.mark.asyncio
@patch("app.ai.agents.summarizer.SummarizerAgent.run_structured")
async def test_short_documents_get_a_detailed_summary_from_one_call(mock_summarize):
    """A document under the map-reduce threshold is summarised in a single
    call over the full text -- no chunking needed."""
    mock_summarize.return_value = SummaryOutput(
        detailed_summary="Bu yazı, personelin yıllık izin talebini konu almaktadır. "
        "Talep eden Mehmet Öztürk, Genel Müdür sıfatıyla imzalamıştır. "
        "Yazıda 30.07.2026 tarihi ve E-123-456 sayısı yer almaktadır."
    )

    result = await build_detailed_summary(_agent(), OFFICIAL_LETTER_TEXT, is_ocr_text=False)

    assert result.startswith("Bu yazı, personelin")
    mock_summarize.assert_called_once()


@pytest.mark.asyncio
@patch("app.ai.agents.summarizer.SummarizerAgent.run_structured")
async def test_single_call_failure_propagates(mock_summarize):
    """Unlike the old summarize_node, which swallowed a failure and degraded
    to analyze_node's short summary, build_detailed_summary itself does no
    such thing on the single-call path -- it raises, per its own docstring's
    contract. Degrading is the caller's job now: generate_detailed_summary
    (DocumentService) turns this into an AIException a user actually sees,
    since they explicitly asked for this result (see that method's own
    docstring for why silent degradation would be wrong here)."""
    mock_summarize.side_effect = Exception("provider unavailable")

    with pytest.raises(Exception, match="provider unavailable"):
        await build_detailed_summary(_agent(), OFFICIAL_LETTER_TEXT, is_ocr_text=False)


@pytest.mark.asyncio
@patch("app.ai.agents.summarizer.SummarizerAgent.run")
@patch("app.ai.agents.summarizer.SummarizerAgent.run_structured")
async def test_long_documents_are_summarised_via_map_reduce(mock_map, mock_reduce):
    """A document over the map-reduce threshold is chunked, each chunk gets a
    partial summary (map, structured), then one final call combines them
    (reduce, plain text -- see _reduce_partial_summaries's own docstring for
    why) -- more than one SummarizerAgent call, not one call over trimmed
    text."""
    # A sized side_effect, not a fixed return_value: SUMMARY_MAX_MAP_CHUNKS=3
    # caps this fixture at exactly 3 map calls. If reduce were still routed
    # through the same run_structured mock (map and reduce sharing one
    # method, the pre-fix shape), a 4th consumption here would raise
    # StopIteration -- this is what makes the test fail for the right reason
    # against unfixed code rather than passing by coincidence on a shared
    # fixed return value.
    mock_map.side_effect = [
        SummaryOutput(detailed_summary="Parça A metni."),
        SummaryOutput(detailed_summary="Parça B metni."),
        SummaryOutput(detailed_summary="Parça C metni."),
    ]
    mock_reduce.return_value = "Birleştirilmiş ayrıntılı özet."

    long_text = OFFICIAL_LETTER_TEXT + "\n\n" + ("Gövde metni cümlesi. " * 2000)
    result = await build_detailed_summary(_agent(), long_text, is_ocr_text=False)

    assert result == "Birleştirilmiş ayrıntılı özet."
    assert mock_map.call_count == 3
    assert mock_reduce.call_count == 1  # exactly 1 reduce call, a distinct method
    reduce_prompt = mock_reduce.call_args.kwargs["messages"]
    assert "farklı parçalarından" in reduce_prompt


@pytest.mark.asyncio
@patch("app.ai.agents.summarizer.SummarizerAgent.run_structured")
async def test_map_stage_calls_are_never_concurrent(mock_summarize):
    """Ollama serialises generation against one model regardless of client-side
    concurrency (see vision.py's own documented finding on this exact point).
    Dispatching map calls via asyncio.gather() buys nothing there and risks
    something worse: if the outer wait_for times out and abandons the gather,
    requests already queued server-side keep running, orphaned -- this is
    what a real run against CY-049 showed directly (a call's completion log
    line appeared *after* the caller had already given up and returned).
    The map stage must therefore await each chunk's summary sequentially, one
    in flight at a time, so a timeout only ever abandons a single call."""
    in_flight = 0
    max_in_flight = 0

    async def _fake_summarize(*, messages, **_kwargs):
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return SummaryOutput(detailed_summary="Parça özeti.")

    mock_summarize.side_effect = _fake_summarize

    long_text = OFFICIAL_LETTER_TEXT + "\n\n" + ("Gövde metni cümlesi. " * 2000)
    with patch("app.ai.agents.summarizer.SummarizerAgent.run", return_value="Birleştirilmiş özet."):
        await build_detailed_summary(_agent(), long_text, is_ocr_text=False)

    assert max_in_flight == 1


@pytest.mark.asyncio
@patch("app.ai.agents.summarizer.SummarizerAgent.run")
@patch("app.ai.agents.summarizer.SummarizerAgent.run_structured")
async def test_reduce_failure_falls_back_to_joined_partials(mock_map, mock_reduce):
    """Real example (CY-049, 4pp/10002 chars): every map call succeeded --
    three good partial summaries -- but the reduce call that merges them
    failed even on the plain-text run() path (see _reduce_partial_summaries's
    own docstring for why reduce prefers run() over run_structured() in the
    first place -- this test covers the residual failure case where even
    that fails). Losing all three partials for that would be the wrong
    trade -- a document that made it through the expensive map stage should
    keep what it earned. The reduce step falls back to the partials
    themselves, joined WITHOUT their internal 'Parça N:' labels -- those are
    prompt-shaping text meant for the reduce call itself, not something a
    real user should ever see verbatim in a finished summary (an earlier
    version of this fallback leaked them straight through)."""
    # Sized side_effect, same reasoning as the map-reduce test above.
    mock_map.side_effect = [
        SummaryOutput(detailed_summary="Parça A metni."),
        SummaryOutput(detailed_summary="Parça B metni."),
        SummaryOutput(detailed_summary="Parça C metni."),
    ]
    mock_reduce.side_effect = Exception("provider unavailable")

    long_text = OFFICIAL_LETTER_TEXT + "\n\n" + ("Gövde metni cümlesi. " * 2000)
    result = await build_detailed_summary(_agent(), long_text, is_ocr_text=False)

    assert "Parça A metni." in result
    assert "Parça B metni." in result
    assert "Parça C metni." in result
    assert "Parça 1" not in result
    assert "Parça 2" not in result


#: The actual shape of the cap this project is guarding against -- "en çok 3
#: cümle" / "en fazla 3 cümle" -- a digit immediately preceding "cümle".
#: Matching the bare word "cümle" would false-positive on legitimate text
#: like summarizer.md's own "cümle sayısını sınırlama" ("don't limit sentence
#: count"), which contains the word specifically to disclaim a cap.
_SENTENCE_CAP_PATTERN = re.compile(r"\d+\s*cümle", re.IGNORECASE)


def test_summary_output_field_carries_no_sentence_cap():
    """analyze_node's own summary is capped at 3 sentences by design (both
    DocumentClassificationOutput.summary's and DocumentAnalysisOutput's Field
    description in document_analysis_graph.py say "en çok 3 cümle") -- the
    entire reason SummaryOutput and SummarizerAgent exist separately is to
    escape that cap. A future edit that copy-pastes the capped description
    onto this schema would silently reintroduce the exact bug this module
    exists to fix, so this is a tripwire, not a feature test."""
    description = SummaryOutput.model_fields["detailed_summary"].description
    assert not _SENTENCE_CAP_PATTERN.search(description)


def test_summarizer_template_carries_no_sentence_cap():
    """classifier.md's system prompt hard-codes "Özet en fazla 3 cümle olsun"
    -- a second, independent source of the cap alongside the schema
    description above (see SummarizerAgent's own docstring). summarizer.md
    must never gain the same instruction."""
    template = get_prompt_manager().get_template("summarizer")
    assert not _SENTENCE_CAP_PATTERN.search(template)
