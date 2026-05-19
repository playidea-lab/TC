"""L1 evidence corpus export / import — content-hash 무결성 검증.

정전(canonical)은 PG가 아니라 content-hash 주소화된 L1 레코드다. PG는
serving 매체일 뿐. export는 store 없이 L1 전체를 재구성 가능한 자기완결
NDJSON을 만들고, import는 모든 레코드의 content_hash를 재검증한 뒤에만
적재한다 (L1 변조 거부 = 거버넌스 신뢰의 토대).

NDJSON 한 줄 = compute_content_hash와 동일한 canonical JSON 직렬화 →
TC 코드 버전과 무관하게 재현 가능.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
from collections.abc import AsyncIterator

import structlog

from the_commons.library.content_hash import compute_integrity, verify_integrity
from the_commons.library.models import Evidence
from the_commons.library.store import (
    EvidenceAlreadyExistsError,
    EvidenceStore,
)

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_PAGE = 200


class CorpusIntegrityError(RuntimeError):
    """import 레코드의 content_hash가 재계산과 불일치 — L1 변조 감지."""


def _canonical_record(evidence: Evidence) -> dict:
    """corpus의 canonical envelope 형태 (pcq 2.x 정본).

    envelope을 model_dump하고, pcq_record 위에 정본 byte-parity hash를
    재스탬프해 pcq_record.integrity에 둔다 — dump가 자기일관·변조탐지·
    운영자독립 재현 가능. (ingestion이 부착한 integrity가 그대로 보존되는
    happy path도 동일 결과.)
    """
    record = evidence.model_dump(mode="json")
    pcq = record.get("pcq_record")
    if isinstance(pcq, dict):
        pcq["integrity"] = compute_integrity(pcq)
        record["pcq_record"] = pcq
    return record


def _canonical_line(record: dict) -> str:
    """compute_content_hash와 동일한 canonical 직렬화 (재현 가능)."""
    return json.dumps(
        record, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


async def export_corpus(store: EvidenceStore) -> AsyncIterator[str]:
    """L1 전체(deprecated 포함 — 불변·audit 보존)를 NDJSON 라인으로 산출."""
    offset = 0
    seen = 0
    while True:
        page, total = await store.list_evidence(
            deprecated=None, limit=_PAGE, offset=offset
        )
        if not page:
            break
        for ev in page:
            yield _canonical_line(_canonical_record(ev))
        seen += len(page)
        offset += len(page)
        if seen >= total:
            break


async def import_corpus(store: EvidenceStore, lines: list[str]) -> int:
    """NDJSON 라인을 검증 후 적재. 반환: 신규 삽입 건수 (중복 idempotent skip).

    각 레코드는 attribution.content_hash가 재계산과 일치해야 한다 —
    불일치 시 CorpusIntegrityError (적재 거부).
    """
    inserted = 0
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        record = json.loads(raw)
        pcq = record.get("pcq_record") or {}
        integrity = pcq.get("integrity") or {}
        declared = integrity.get("content_hash") if isinstance(integrity, dict) else None
        if not declared or not verify_integrity(pcq, declared):
            raise CorpusIntegrityError(
                f"content_hash 불일치 — L1 변조 의심: "
                f"evidence_id={record.get('evidence_id')}"
            )
        evidence = Evidence.model_validate(record)
        try:
            await store.insert(evidence)
            inserted += 1
        except EvidenceAlreadyExistsError:
            # 이미 존재 — idempotent (재실행 안전)
            continue
    return inserted


# ----------------------------------------------------------------------------
# CLI — migrate.py 패턴 (python -m the_commons.corpus.export ...)
# ----------------------------------------------------------------------------


async def _cli_export(out_path: str | None) -> None:
    from the_commons.db.session import get_connection
    from the_commons.library.store import PostgresEvidenceStore

    sink_cm = (
        open(out_path, "w", encoding="utf-8")  # noqa: SIM115 — 아래 `with`로 관리
        if out_path
        else contextlib.nullcontext(sys.stdout)
    )
    async with get_connection() as conn:
        store = PostgresEvidenceStore(conn)
        count = 0
        with sink_cm as sink:
            async for line in export_corpus(store):
                sink.write(line + "\n")
                count += 1
    logger.info("corpus_exported", records=count, out=out_path or "stdout")


async def _cli_import(in_path: str) -> None:
    from the_commons.db.session import get_connection
    from the_commons.library.store import PostgresEvidenceStore

    with open(in_path, encoding="utf-8") as f:
        lines = f.readlines()
    async with get_connection() as conn:
        store = PostgresEvidenceStore(conn)
        n = await import_corpus(store, lines)
    logger.info("corpus_imported", inserted=n, source=in_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="the_commons.corpus.export")
    sub = parser.add_subparsers(dest="cmd", required=True)
    pe = sub.add_parser("export", help="L1 corpus → NDJSON")
    pe.add_argument("--out", default=None, help="출력 파일 (없으면 stdout)")
    pi = sub.add_parser("import", help="NDJSON → store (hash 검증)")
    pi.add_argument("--in", dest="in_path", required=True, help="입력 NDJSON")
    args = parser.parse_args(argv)

    if args.cmd == "export":
        asyncio.run(_cli_export(args.out))
    else:
        asyncio.run(_cli_import(args.in_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
