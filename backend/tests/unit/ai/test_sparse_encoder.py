"""Unit tests for the offline BM25 sparse vector encoder.

`SparseBM25Encoder` produces Qdrant-compatible sparse vectors without a
network call or a heavy embedding model -- pure arithmetic over token
frequencies, hashed to indices with CRC32. These tests exercise that
arithmetic directly rather than mocking anything, since there is nothing
here to mock.
"""

import json
import zlib

import pytest
from langchain_core.documents import Document

from app.ai.retrieval.sparse_encoder import SparseBM25Encoder


# ==========================================
# fit()
# ==========================================
def test_fit_on_an_empty_corpus_leaves_the_encoder_cold():
    encoder = SparseBM25Encoder()
    encoder.fit([])

    assert encoder.total_docs == 0
    assert encoder.avg_doc_len == 0.0
    assert encoder.idf == {}


def test_fit_computes_average_document_length_and_idf():
    documents = [
        Document(page_content="kedi köpek kuş"),
        Document(page_content="kedi araba"),
    ]
    encoder = SparseBM25Encoder()
    encoder.fit(documents)

    assert encoder.total_docs == 2
    # "kedi köpek kuş" -> 3 tokens, "kedi araba" -> 2 tokens.
    assert encoder.avg_doc_len == pytest.approx(2.5)

    # "kedi" appears in both documents (freq=2); "köpek"/"kuş"/"araba" each
    # appear in exactly one (freq=1) -- a rarer term must score a strictly
    # higher IDF than a term that appears in every document.
    assert set(encoder.idf) == {"kedi", "köpek", "kuş", "araba"}
    assert encoder.idf["araba"] > encoder.idf["kedi"]
    assert encoder.idf["köpek"] == encoder.idf["araba"]  # both freq=1


def test_fit_folds_turkish_casing_the_same_way_bm25_tokenization_does():
    """`tokenize_turkish` (shared with `BM25Retriever`) lowercases with
    Turkish-aware casing before this encoder ever sees a token."""
    encoder = SparseBM25Encoder()
    encoder.fit([Document(page_content="İstanbul istanbul")])

    assert list(encoder.idf) == ["istanbul"]


# ==========================================
# encode_document()
# ==========================================
def test_encode_document_on_empty_text_returns_no_indices():
    encoder = SparseBM25Encoder()
    encoder.fit([Document(page_content="dolgu metni")])

    assert encoder.encode_document("") == ([], [])
    assert encoder.encode_document("   ") == ([], [])


def test_encode_document_produces_one_index_and_value_per_unique_token():
    encoder = SparseBM25Encoder()
    encoder.fit([Document(page_content="kedi köpek kedi araba")])

    indices, values = encoder.encode_document("kedi köpek kedi araba")

    assert len(indices) == len(values) == 3  # unique tokens: kedi, köpek, araba
    assert all(isinstance(i, int) for i in indices)
    assert all(v > 0 for v in values)
    # The index is a deterministic CRC32 hash of the token -- not an
    # arbitrary vocabulary position -- so the same token always lands on
    # the same index regardless of fit order.
    assert zlib.crc32("kedi".encode("utf-8")) in indices


def test_encode_document_scales_term_frequency_by_bm25():
    """A token repeated more often within one document must score a
    strictly higher weight than a token appearing once -- that is the
    entire point of the TF half of BM25."""
    encoder = SparseBM25Encoder()
    encoder.fit([Document(page_content="kedi kedi kedi köpek")])

    indices, values = encoder.encode_document("kedi kedi kedi köpek")
    weight_by_index = dict(zip(indices, values))

    assert (
        weight_by_index[zlib.crc32("kedi".encode("utf-8"))]
        > weight_by_index[zlib.crc32("köpek".encode("utf-8"))]
    )


def test_encode_document_before_fit_still_works_via_unfit_average_length():
    """`avg_doc_len` defaults to 0.0 before `fit()`; the `or 1.0` fallback in
    the TF-scaling denominator must keep this from dividing by zero."""
    encoder = SparseBM25Encoder()

    indices, values = encoder.encode_document("hiç fit edilmemiş metin")

    assert len(indices) == len(values) == 4
    assert all(v > 0 for v in values)


# ==========================================
# encode_query()
# ==========================================
def test_encode_query_on_empty_text_returns_no_indices():
    encoder = SparseBM25Encoder()
    assert encoder.encode_query("") == ([], [])
    assert encoder.encode_query("   ") == ([], [])


def test_encode_query_weights_by_idf_not_query_term_frequency():
    encoder = SparseBM25Encoder()
    encoder.fit(
        [
            Document(page_content="kedi köpek"),
            Document(page_content="kedi araba"),
            Document(page_content="kedi ev"),
        ]
    )

    indices, values = encoder.encode_query("araba araba araba")
    # A query is scored by IDF alone (how rare the term is in the corpus),
    # never by how many times the user happened to type it.
    assert values == [encoder.idf["araba"]]


def test_encode_query_defaults_out_of_vocabulary_tokens_to_one():
    encoder = SparseBM25Encoder()
    encoder.fit([Document(page_content="kedi köpek")])

    indices, values = encoder.encode_query("hiç görülmemiş kelime")

    assert values == [1.0, 1.0, 1.0]


# ==========================================
# save() / load()
# ==========================================
def test_save_writes_the_fitted_state_as_json(tmp_path):
    encoder = SparseBM25Encoder()
    encoder.fit([Document(page_content="kedi köpek")])

    target = tmp_path / "nested" / "vocab.json"
    encoder.save(str(target))

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["total_docs"] == 1
    assert payload["avg_doc_len"] == encoder.avg_doc_len
    assert payload["idf"] == encoder.idf


def test_load_on_a_missing_file_reports_failure_without_raising(tmp_path):
    encoder = SparseBM25Encoder()

    assert encoder.load(str(tmp_path / "does-not-exist.json")) is False
    # Untouched -- a missing vocabulary must not silently reset a caller
    # that already fit or loaded one.
    assert encoder.total_docs == 0


def test_load_restores_a_previously_saved_encoder(tmp_path):
    fitted = SparseBM25Encoder()
    fitted.fit([Document(page_content="kedi köpek kuş")])
    target = tmp_path / "vocab.json"
    fitted.save(str(target))

    restored = SparseBM25Encoder()
    assert restored.load(str(target)) is True
    assert restored.total_docs == fitted.total_docs
    assert restored.avg_doc_len == fitted.avg_doc_len
    assert restored.idf == fitted.idf


def test_load_on_a_corrupt_file_reports_failure_without_raising(tmp_path):
    target = tmp_path / "corrupt.json"
    target.write_text("{not valid json", encoding="utf-8")

    encoder = SparseBM25Encoder()
    assert encoder.load(str(target)) is False


def test_load_on_a_file_missing_expected_keys_reports_failure_without_raising(tmp_path):
    target = tmp_path / "incomplete.json"
    target.write_text(json.dumps({"total_docs": 1}), encoding="utf-8")

    encoder = SparseBM25Encoder()
    assert encoder.load(str(target)) is False
