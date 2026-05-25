"""기존 evidence를 현재 serialize_evidence(category 포함)로 재임베딩.

serialize_evidence에 _category_phrase를 추가(2026-05-25)한 뒤, 기존 evidence는 옛
임베딩이라 retrieve가 category(bottle/screw)를 반영하지 못한다. 전 evidence를 새 직렬화로
재임베딩해 exploit 분기 retrieve까지 카테고리를 인식하게 한다.

ingest.py의 검증된 패턴(serialize_evidence → embed → update_embedding)을 그대로 사용.
"""

import asyncio

from the_commons.api.dependencies import get_embedder, get_evidence_store
from the_commons.db.session import close_pool, init_pool
from the_commons.matchmaker.serializer import default_registry
from the_commons.settings import settings


async def main() -> None:
    await init_pool()
    embedder = await get_embedder()
    registry = default_registry()
    n = 0
    try:
        async for store in get_evidence_store():
            evidences, total = await store.list_evidence(deprecated=False, limit=500)
            print(f"re-embedding {len(evidences)}/{total} evidence (template={settings.template_version})")
            for ev in evidences:
                text = registry.serialize_evidence(ev, version=settings.template_version)
                vector = await embedder.embed(text)
                await store.update_embedding(ev.evidence_id, vector)
                n += 1
                print(f"  [{n}] {ev.evidence_id}: {text[:90]}", flush=True)
                await asyncio.sleep(5)  # Gemini embedding RPM(분당 한도) 회피
            break  # get_evidence_store는 단일 store를 yield
    finally:
        await close_pool()
    print(f"done — {n} evidence re-embedded")


if __name__ == "__main__":
    asyncio.run(main())
