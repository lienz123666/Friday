"""AD-015: multi-user / multi-profile external memory isolation regressions."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from personal_agent.gateway.session_router import GatewaySessionRouter
from personal_agent.memory.archive import MemoryArchive
from personal_agent.memory.external import ExternalMemoryRouter, FallbackMemoryProvider
from personal_agent.memory.manager import MemoryManager, _user_id_from_session
from personal_agent.memory.models import (
    MemoryRecord,
    MemoryReviewResult,
    MemoryScope,
    Observation,
    ObservationKind,
    ProviderReadiness,
)
from personal_agent.memory.provider_registry import MemoryProviderRegistry
from personal_agent.plugins.builtin.memory.lumora.qdrant_store import QdrantMemoryIndex

_SHARED_PHRASE = "AD015 cross-user favorite color is ultramarine cyan"


class _LLM:
    async def extract_observations(self, messages):
        return ()


class _ArchivePrimary:
    """Primary provider backed by the same archive + BM25 as production fallback."""

    name = "primary"

    def __init__(self, archive: MemoryArchive) -> None:
        self._fallback = FallbackMemoryProvider(archive, _LLM())

    async def review(self, messages, scope) -> MemoryReviewResult:
        return MemoryReviewResult(provider=self.name)

    async def migrate(self, observations, scope) -> MemoryReviewResult:
        return await self._fallback.migrate(observations, scope)

    async def search(self, query: str, scope: MemoryScope, *, limit: int = 5):
        return await self._fallback.search(query, scope, limit=limit)

    async def list(self, scope: MemoryScope, *, limit: int = 100):
        return await self._fallback.list(scope, limit=limit)

    async def delete(self, memory_id: str, scope: MemoryScope) -> bool:
        return await self._fallback.delete(memory_id, scope)

    def health_snapshot(self) -> dict:
        return {"available": True}

    async def close(self) -> None:
        pass


async def _router_with_archive(tmp_path) -> tuple[MemoryArchive, ExternalMemoryRouter]:
    archive = MemoryArchive(tmp_path / "memory.db")
    await archive.initialize()
    fallback = FallbackMemoryProvider(archive, _LLM())
    registry = MemoryProviderRegistry()
    registry.register(
        name="primary",
        plugin_key="memory/primary",
        factory=lambda **kwargs: _ArchivePrimary(archive),
        validator=lambda **kwargs: ProviderReadiness("primary", True),
    )
    context = SimpleNamespace(requested_provider="primary")
    router = ExternalMemoryRouter(
        context=context, archive=archive, fallback=fallback, registry=registry
    )
    await router.initialize()
    return archive, router


def _source(chat_id: str, user_id: str):
    return SimpleNamespace(platform="telegram", chat_id=chat_id, user_id=user_id)


@pytest.mark.asyncio
async def test_archive_bm25_does_not_leak_across_user_id(tmp_path) -> None:
    archive = MemoryArchive(tmp_path / "memory.db")
    await archive.initialize()
    scope_a = MemoryScope(user_id="user-a")
    scope_b = MemoryScope(user_id="user-b")
    record = MemoryRecord(
        id="mem-a",
        content=_SHARED_PHRASE,
        kind=ObservationKind.FACT,
        provider="fallback",
        scope=scope_a,
    )
    await archive.upsert_memory(scope_a, record)

    assert [item.id for item in await archive.search_bm25(scope_a, "ultramarine")] == ["mem-a"]
    assert await archive.search_bm25(scope_b, "ultramarine") == []
    assert await archive.get_memory("mem-a", scope_b) is None
    await archive.close()


@pytest.mark.asyncio
async def test_archive_bm25_does_not_leak_across_profile(tmp_path) -> None:
    archive = MemoryArchive(tmp_path / "memory.db")
    await archive.initialize()
    scope_default = MemoryScope(user_id="u1", profile="default")
    scope_work = MemoryScope(user_id="u1", profile="work")
    await archive.upsert_memory(
        scope_work,
        MemoryRecord(
            id="work-only",
            content="AD015 profile work secret phrase",
            provider="fallback",
            scope=scope_work,
        ),
    )

    assert await archive.search_bm25(scope_work, "profile work secret")
    assert await archive.search_bm25(scope_default, "profile work secret") == []
    await archive.close()


@pytest.mark.asyncio
async def test_router_search_isolated_for_similar_content(tmp_path) -> None:
    archive, router = await _router_with_archive(tmp_path)

    obs = Observation(kind=ObservationKind.FACT, content=_SHARED_PHRASE)
    await router.migrate((obs,), MemoryScope(user_id="user-a"))

    hits_a = await router.search("ultramarine AD015", MemoryScope(user_id="user-a"))
    hits_b = await router.search("ultramarine AD015", MemoryScope(user_id="user-b"))

    assert len(hits_a) == 1
    assert hits_a[0].content == _SHARED_PHRASE
    assert hits_b == []
    await archive.close()


@pytest.mark.asyncio
async def test_manager_prefetch_uses_session_key_user_id(tmp_path) -> None:
    archive, router = await _router_with_archive(tmp_path)
    manager = MemoryManager(router=router, archive=archive)

    await router.migrate(
        (Observation(kind=ObservationKind.FACT, content=_SHARED_PHRASE),),
        MemoryScope(user_id="user-a"),
    )

    session_a = GatewaySessionRouter().base_key(_source("chat-1", "user-a"))
    session_b = GatewaySessionRouter().base_key(_source("chat-1", "user-b"))

    prefetch_a = await manager.prefetch("ultramarine AD015", session_key=session_a)
    prefetch_b = await manager.prefetch("ultramarine AD015", session_key=session_b)

    assert prefetch_a
    assert _SHARED_PHRASE in prefetch_a[0]["content"][0]["text"]
    assert prefetch_b == []
    await archive.close()


def test_gateway_session_keys_resolve_to_platform_user_id() -> None:
    router = GatewaySessionRouter()
    source_a = _source("group-a", "alice")
    source_b = _source("group-b", "bob")

    keys = [
        router.base_key(source_a),
        router.named_key(source_a, "work"),
        router.base_key(source_b),
        router.named_key(source_b, "work"),
    ]
    expected = ["alice", "alice", "bob", "bob"]

    for key, user_id in zip(keys, expected, strict=True):
        assert _user_id_from_session(key) == user_id
        assert MemoryScope(user_id=_user_id_from_session(key)).user_id == user_id


@pytest.mark.asyncio
async def test_qdrant_vector_search_filters_by_user_id_and_profile() -> None:
    pytest.importorskip("qdrant_client")
    captured: dict[str, object] = {}

    class SpyClient:
        async def collection_exists(self, collection: str) -> bool:
            return True

        async def get_collection(self, collection: str):
            vectors = SimpleNamespace(size=3)
            params = SimpleNamespace(vectors=vectors)
            config = SimpleNamespace(params=params)
            return SimpleNamespace(config=config, payload_schema={})

        async def create_payload_index(self, **kwargs) -> None:
            pass

        async def query_points(self, collection, *, query, query_filter, limit):
            captured["query_filter"] = query_filter
            return SimpleNamespace(points=[])

        async def close(self) -> None:
            pass

    client = SpyClient()
    index = QdrantMemoryIndex(
        SimpleNamespace(collection="test_memories"), dimensions=3, client=client
    )
    await index.search([0.1, 0.2, 0.3], user_id="user-z", profile="work", limit=5)

    query_filter = captured.get("query_filter")
    assert query_filter is not None
    must = getattr(query_filter, "must", None) or query_filter.get("must")
    serialized = str(must)
    assert "user-z" in serialized
    assert "work" in serialized
