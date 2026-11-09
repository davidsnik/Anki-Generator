"""Validate the real SDK transport used by packaged desktop integration tests."""

from support.desktop_provider_server import TEST_KEY, ControlledResponsesServer

from anki_generator.llm import OpenAIProvider
from anki_generator.processing.contracts import DocumentKnowledge


def test_desktop_fixture_uses_real_responses_and_embedding_sdk(monkeypatch):
    with ControlledResponsesServer() as server:
        monkeypatch.setenv("OPENAI_BASE_URL", f"{server.origin}/v1/")
        provider = OpenAIProvider(TEST_KEY)
        try:
            assert provider.test()["connected"]
            result = provider.structured(
                "knowledge",
                {
                    "document_id": "synthetic-document",
                    "page_number": 1,
                    "text": "For a right triangle, a^2 + b^2 = c^2.",
                    "role": "lecture",
                },
                DocumentKnowledge,
                model="gpt-6-astra",
            )
            assert result.data.concepts[0].sources[0].document_id == "synthetic-document"
            embedded = provider.embed(["Synthetic target"], model="test-embedding", dimensions=16)
            assert len(embedded.vectors[0]) == 16
            assert server.snapshot()["calls"] == {
                "connection": 1,
                "knowledge": 1,
                "embeddings": 1,
            }
        finally:
            provider.close_owned_client()
