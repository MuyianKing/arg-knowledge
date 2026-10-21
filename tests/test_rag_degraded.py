from app.api.schemas import AskRequest
from app.core.context import EngineContext
from app.core.llm import LLMUnavailable
from app.core.retrieval import Chunk
from app.services.rag import RAGService


class FakeRetrieval:
    async def search(self, *args, **kwargs):
        return [
            Chunk(
                id="c1",
                text="市内交通费每日上限 80 元。",
                source="差旅管理制度.md",
                page=None,
                version="v1",
                score=0.9,
            )
        ]

    async def rerank(self, query, chunks, top_k=None):
        return chunks


class FakeLLM:
    async def generate(self, query, chunks):
        raise LLMUnavailable("simulated outage")


class FakeCache:
    async def get(self, key):
        return None

    async def set(self, key, value):
        return None

    async def close(self):
        return None


async def test_llm_outage_returns_degraded_with_citations() -> None:
    service = RAGService(FakeRetrieval(), FakeLLM(), FakeCache())
    response = await service.answer(
        AskRequest(query="差旅报销标准是多少"),
        EngineContext(tenant_id="acme", acl=("internal",)),
        request_id="test-request",
    )
    assert response.degraded is True
    assert response.refused is False
    assert len(response.citations) == 1
    assert response.citations[0].id == "S1"
    assert "未生成答案" in response.answer
