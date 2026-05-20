"""Retention cleanup planning for stored artifacts."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, List, Optional


@dataclass(frozen=True)
class ArtifactRecord:
    """Retention metadata needed before an artifact can be deleted."""

    artifact_id: str
    expires_at: Optional[datetime]
    legal_hold: bool = False
    investigation_hold: bool = False

    @property
    def is_held(self) -> bool:
        return self.legal_hold or self.investigation_hold

    def is_expired(self, now: datetime) -> bool:
        if self.expires_at is None:
            return False
        return _normalize(self.expires_at) <= _normalize(now)


@dataclass(frozen=True)
class RetentionCleanupPlan:
    """Artifacts split into safe deletion and hold-report buckets."""

    delete_artifact_ids: List[str]
    held_expired_artifacts: List[ArtifactRecord]


def build_retention_cleanup_plan(
    artifacts: Iterable[ArtifactRecord],
    now: Optional[datetime] = None,
) -> RetentionCleanupPlan:
    """Return expired artifacts to delete and expired held artifacts to report.

    Held artifacts are never returned for deletion, even when their retention
    window has expired. They are reported separately so operators can see which
    records remain because of legal or investigation holds.
    """

    current_time = _normalize(now or datetime.now(timezone.utc))
    delete_artifact_ids: List[str] = []
    held_expired_artifacts: List[ArtifactRecord] = []

    for artifact in artifacts:
        if not artifact.is_expired(current_time):
            continue
        if artifact.is_held:
            held_expired_artifacts.append(artifact)
            continue
        delete_artifact_ids.append(artifact.artifact_id)

    return RetentionCleanupPlan(
        delete_artifact_ids=delete_artifact_ids,
        held_expired_artifacts=held_expired_artifacts,
    )


def _normalize(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
