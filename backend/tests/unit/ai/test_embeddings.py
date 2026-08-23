from unittest.mock import MagicMock, AsyncMock, patch
import pytest
from pydantic import BaseModel

from app.ai.embeddings import (
    OllamaEmbeddingsClient,
    get_embeddings_client,
    EmbeddingService,
)
from app.core.config import settings
from app.ai.embeddings.chunking import (
    CharacterChunker,
    RecursiveChunker,
    SemanticChunker,
    AgenticChunker,
)
from app.ai.agents.base import BaseAgent
from app.ai.embeddings.chunking.agentic import AgenticChunksResponse, SemanticSection


@pytest.fixture
def mock_embeddings():
    return MagicMock()


@pytest.mark.asyncio
@patch("app.ai.embeddings.models.OllamaEmbeddings")
async def test_ollama_embeddings_client(mock_ollama_class):
    mock_instance = MagicMock()
    mock_instance.aembed_documents = AsyncMock(return_value=[[0.1, 0.2], [0.3, 0.4]])
    mock_instance.aembed_query = AsyncMock(return_value=[0.1, 0.2])
    mock_ollama_class.return_value = mock_instance

    client = get_embeddings_client(provider="ollama", base_url="http://localhost:11434", model="nomic")
    
    docs_vectors = await client.embed_documents(["doc1", "doc2"])
    query_vector = await client.embed_query("query")

    assert docs_vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert query_vector == [0.1, 0.2]
    mock_instance.aembed_documents.assert_called_once_with(["doc1", "doc2"])
    # get_embeddings_client's own factory wires settings.
    # OLLAMA_EMBEDDING_INSTRUCT_PREFIX into every query embedding (harrier-
    # oss-v1-0.6b's own model card: query embeddings need it, document
    # embeddings do not -- see OLLAMA_EMBEDDING_INSTRUCT_PREFIX's docstring).
    mock_instance.aembed_query.assert_called_once_with(
        settings.OLLAMA_EMBEDDING_INSTRUCT_PREFIX + "query"
    )


@pytest.mark.asyncio
@patch("app.ai.embeddings.models.OllamaEmbeddings")
async def test_instruct_prefix_applies_only_to_queries_not_documents(mock_ollama_class):
    """OllamaEmbeddingsClient's own contract, independent of the factory
    default above -- an explicit instruct_prefix must never leak into
    embed_documents, which harrier-oss-v1-0.6b's model card says needs
    none."""
    mock_instance = MagicMock()
    mock_instance.aembed_documents = AsyncMock(return_value=[[0.1, 0.2]])
    mock_instance.aembed_query = AsyncMock(return_value=[0.1, 0.2])
    mock_ollama_class.return_value = mock_instance

    client = OllamaEmbeddingsClient(
        base_url="http://localhost:11434", model="harrier", instruct_prefix="Instruct: x\nQuery: "
    )

    await client.embed_documents(["plain document text"])
    await client.embed_query("plain query text")

    mock_instance.aembed_documents.assert_called_once_with(["plain document text"])
    mock_instance.aembed_query.assert_called_once_with("Instruct: x\nQuery: plain query text")


@pytest.mark.asyncio
@patch("app.ai.embeddings.models.OllamaEmbeddings")
async def test_empty_instruct_prefix_reproduces_pre_existing_behaviour(mock_ollama_class):
    mock_instance = MagicMock()
    mock_instance.aembed_query = AsyncMock(return_value=[0.1])
    mock_ollama_class.return_value = mock_instance

    client = OllamaEmbeddingsClient(base_url="http://localhost:11434", model="m")
    await client.embed_query("bare query")

    mock_instance.aembed_query.assert_called_once_with("bare query")


@pytest.mark.asyncio
async def test_character_chunker():
    chunker = CharacterChunker(separator="\n", chunk_size=10, chunk_overlap=2)
    text = "line1\nline2\nline3"
    docs = await chunker.split_text(text)

    assert len(docs) > 0
    assert all(isinstance(doc.page_content, str) for doc in docs)


@pytest.mark.asyncio
async def test_recursive_chunker():
    chunker = RecursiveChunker(chunk_size=15, chunk_overlap=2)
    text = "This is a long sentence for recursive chunking."
    docs = await chunker.split_text(text)

    assert len(docs) > 0
    assert all(isinstance(doc.page_content, str) for doc in docs)


@pytest.mark.asyncio
async def test_recursive_chunker_tags_each_chunk_with_its_source_offset():
    """start_index is what lets a chunk be mapped back to a page number via
    PageMap (see app.ai.documents.anchors) -- without it every chunk's
    metadata is empty and document search can't cite a page."""
    chunker = RecursiveChunker(chunk_size=15, chunk_overlap=2)
    text = "This is a long sentence for recursive chunking."
    docs = await chunker.split_text(text)

    assert all("start_index" in doc.metadata for doc in docs)
    assert text[docs[1].metadata["start_index"]:].startswith(docs[1].page_content)


@pytest.mark.asyncio
async def test_semantic_chunker():
    mock_client = MagicMock()
    # Sentence 1 and 2 will be close; sentence 3 will be far away (semantically different)
    mock_client.embed_documents = AsyncMock(
        return_value=[
            [1.0, 0.0, 0.0],  # Sentence 1: "Apple is great."
            [0.9, 0.1, 0.0],  # Sentence 2: "I love Apple."
            [0.0, 0.0, 1.0],  # Sentence 3: "Nuclear physics is complex."
        ]
    )

    chunker = SemanticChunker(
        embeddings_client=mock_client,
        threshold_type="static",
        threshold_value=0.3,
    )
    
    text = "Apple is great. I love Apple. Nuclear physics is complex."
    docs = await chunker.split_text(text)

    # Sentence 1 and 2 should be in Chunk 1. Sentence 3 should be in Chunk 2.
    assert len(docs) == 2
    assert "Apple is great. I love Apple." in docs[0].page_content
    assert "Nuclear physics is complex." in docs[1].page_content


@pytest.mark.asyncio
async def test_semantic_chunker_does_not_emit_start_index():
    """Counter-intuitive on purpose: this pins today's contract so nobody
    wires SemanticChunker into DocumentService._index_for_qa believing page
    citations survive the switch. _index_for_qa reads start_index to look
    up a chunk's page via build_page_map (see
    app.ai.documents.anchors and RecursiveChunker's own
    test_recursive_chunker_tags_each_chunk_with_its_source_offset for the
    contrast) -- SemanticChunker does not provide it. If this test starts
    failing because start_index support was added, that's good; update it
    to assert the offset is correct (see SemanticChunker's class docstring
    for what "correct" requires), not just present, and only then consider
    wiring this chunker into production."""
    mock_client = MagicMock()
    mock_client.embed_documents = AsyncMock(
        return_value=[[1.0, 0.0, 0.0], [0.9, 0.1, 0.0], [0.0, 0.0, 1.0]]
    )

    chunker = SemanticChunker(
        embeddings_client=mock_client, threshold_type="static", threshold_value=0.3
    )
    text = "Apple is great. I love Apple. Nuclear physics is complex."
    docs = await chunker.split_text(text)

    assert docs, "fixture must produce at least one chunk for this assertion to mean anything"
    assert all("start_index" not in doc.metadata for doc in docs)


@pytest.mark.asyncio
async def test_agentic_chunker_success():
    mock_agent = MagicMock(spec=BaseAgent)
    mock_response = AgenticChunksResponse(
        sections=[
            SemanticSection(
                title="Apple Intro",
                summary="Introduction to Apple fruits.",
                content="Apple is a red fruit. It is delicious.",
            ),
            SemanticSection(
                title="Banana Details",
                summary="Details about Bananas.",
                content="Banana is yellow. Monkeys like it.",
            ),
        ]
    )
    mock_agent.run_structured = AsyncMock(return_value=mock_response)

    chunker = AgenticChunker(agent=mock_agent)
    text = "Apple is a red fruit. It is delicious. Banana is yellow. Monkeys like it."
    docs = await chunker.split_text(text)

    assert len(docs) == 2
    assert docs[0].page_content == "Apple is a red fruit. It is delicious."
    assert docs[0].metadata["title"] == "Apple Intro"
    assert docs[0].metadata["summary"] == "Introduction to Apple fruits."
    assert docs[1].page_content == "Banana is yellow. Monkeys like it."
    assert docs[1].metadata["title"] == "Banana Details"


@pytest.mark.asyncio
async def test_agentic_chunker_fallback():
    mock_agent = MagicMock(spec=BaseAgent)
    # Simulate LLM failing
    mock_agent.run_structured = AsyncMock(side_effect=Exception("LLM Timeout"))

    chunker = AgenticChunker(agent=mock_agent)
    text = "Paragraph 1 content.\n\nParagraph 2 content."
    docs = await chunker.split_text(text)

    # Should fallback to paragraph splitting
    assert len(docs) == 2
    assert docs[0].page_content == "Paragraph 1 content."
    assert docs[0].metadata["fallback"] is True
    assert docs[1].page_content == "Paragraph 2 content."


@pytest.mark.asyncio
async def test_embedding_service():
    mock_client = MagicMock()
    mock_client.embed_documents = AsyncMock(return_value=[[0.1, 0.2], [0.3, 0.4]])

    service = EmbeddingService(embeddings_client=mock_client)
    
    mock_chunker = MagicMock()
    from langchain_core.documents import Document
    mock_chunker.split_text = AsyncMock(
        return_value=[
            Document(page_content="chunk1", metadata={"index": 0}),
            Document(page_content="chunk2", metadata={"index": 1}),
        ]
    )

    result = await service.process_text("text input", chunker=mock_chunker)

    assert len(result) == 2
    assert result[0].text == "chunk1"
    assert result[0].vector == [0.1, 0.2]
    assert result[0].metadata["index"] == 0
    assert result[1].text == "chunk2"
    assert result[1].vector == [0.3, 0.4]
