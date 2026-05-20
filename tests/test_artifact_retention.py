from datetime import datetime, timedelta, timezone

from src.storage.retention import ArtifactRecord, build_retention_cleanup_plan


def test_retention_cleanup_skips_expired_artifacts_with_holds():
    now = datetime(2026, 5, 21, tzinfo=timezone.utc)
    expired = now - timedelta(days=1)

    plan = build_retention_cleanup_plan(
        [
            ArtifactRecord("delete-me", expired),
            ArtifactRecord("legal-hold", expired, legal_hold=True),
            ArtifactRecord(
                "investigation-hold",
                expired,
                investigation_hold=True,
            ),
        ],
        now=now,
    )

    assert plan.delete_artifact_ids == ["delete-me"]
    held_ids = [
        artifact.artifact_id for artifact in plan.held_expired_artifacts
    ]
    assert held_ids == [
        "legal-hold",
        "investigation-hold",
    ]


def test_retention_cleanup_ignores_unexpired_and_never_expiring_artifacts():
    now = datetime(2026, 5, 21, tzinfo=timezone.utc)

    plan = build_retention_cleanup_plan(
        [
            ArtifactRecord("future", now + timedelta(days=1)),
            ArtifactRecord("no-expiry", None),
        ],
        now=now,
    )

    assert plan.delete_artifact_ids == []
    assert plan.held_expired_artifacts == []


def test_retention_cleanup_reports_held_expired_artifacts_separately():
    now = datetime(2026, 5, 21, tzinfo=timezone.utc)
    expired = now - timedelta(seconds=1)

    plan = build_retention_cleanup_plan(
        [
            ArtifactRecord("held", expired, legal_hold=True),
            ArtifactRecord("plain", expired),
        ],
        now=now,
    )

    assert plan.delete_artifact_ids == ["plain"]
    assert len(plan.held_expired_artifacts) == 1
    assert plan.held_expired_artifacts[0].artifact_id == "held"
    assert plan.held_expired_artifacts[0].legal_hold is True
