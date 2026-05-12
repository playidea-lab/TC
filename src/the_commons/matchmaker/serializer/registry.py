"""Template registry — version별 serializer 함수 매핑.

v1만 등록. v2가 추가되면 같은 인터페이스로 등록하고, 기존 evidence는
re-embed batch job으로 새 template으로 재직렬화한다.
"""

from collections.abc import Callable
from typing import Final

from the_commons.library.models import Evidence
from the_commons.matchmaker.serializer import templates_v1
from the_commons.matchmaker.serializer.types import QueryFeatures

QuerySerializer = Callable[[QueryFeatures], str]
EvidenceSerializer = Callable[[Evidence], str]


class SerializerRegistry:
    """version → (query_fn, evidence_fn) 매핑. 기본은 v1만 등록."""

    def __init__(self) -> None:
        self._query: dict[str, QuerySerializer] = {}
        self._evidence: dict[str, EvidenceSerializer] = {}

    def register(
        self,
        version: str,
        *,
        query: QuerySerializer,
        evidence: EvidenceSerializer,
    ) -> None:
        self._query[version] = query
        self._evidence[version] = evidence

    def serialize_query(self, query: QueryFeatures, version: str) -> str:
        fn = self._query.get(version)
        if fn is None:
            raise ValueError(f"unknown serializer version: {version}")
        return fn(query)

    def serialize_evidence(self, evidence: Evidence, version: str) -> str:
        fn = self._evidence.get(version)
        if fn is None:
            raise ValueError(f"unknown serializer version: {version}")
        return fn(evidence)

    @property
    def known_versions(self) -> list[str]:
        return sorted(self._query.keys())


_DEFAULT_REGISTRY: Final[SerializerRegistry] = SerializerRegistry()
_DEFAULT_REGISTRY.register(
    templates_v1.TEMPLATE_VERSION,
    query=templates_v1.serialize_query,
    evidence=templates_v1.serialize_evidence,
)


def default_registry() -> SerializerRegistry:
    """모듈 전역 registry — production·test 공용."""
    return _DEFAULT_REGISTRY
