"""Serializer — Evidence/Query → 자연어 description 변환.

매치메이커 quality의 root. template은 versioned, 변경 시 re-embed 필요.
"""

from the_commons.matchmaker.serializer.registry import (
    SerializerRegistry,
    default_registry,
)
from the_commons.matchmaker.serializer.types import QueryFeatures

__all__ = ["QueryFeatures", "SerializerRegistry", "default_registry"]
