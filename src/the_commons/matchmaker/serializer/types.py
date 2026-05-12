"""Serializer 입력 타입 — query는 evidence와 구조가 다름."""

from pydantic import BaseModel, ConfigDict

from the_commons.library.models import DataFingerprint, Intent, WorkerSpec


class QueryFeatures(BaseModel):
    """매치메이커가 받는 query — evidence보다 가벼움.

    config·metrics가 없다 (아직 실행 안 함).
    """

    model_config = ConfigDict(extra="forbid")

    worker_spec: WorkerSpec
    data_fingerprint: DataFingerprint
    intent: Intent
