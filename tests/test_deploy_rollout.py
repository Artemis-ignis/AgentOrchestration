from src.deploy import (
    DeploymentController,
    InMemoryTrafficRouter,
    MigrationCompatibility,
    MigrationJob,
    ReleaseCheck,
)


def test_rollout_routes_traffic_only_after_migrations_pass():
    router = InMemoryTrafficRouter(active_version="v1")
    controller = DeploymentController(router)
    observed_versions = []

    def migrate():
        observed_versions.append(router.active_version)
        assert "v2" not in router.known_versions
        return True

    result = controller.rollout(
        "v2",
        [
            MigrationJob(
                "add_task_state_column",
                migrate,
                MigrationCompatibility.BACKWARD_COMPATIBLE,
            )
        ],
    )

    assert observed_versions == ["v1"]
    assert result.ready_for_traffic is True
    assert result.active_version == "v2"
    assert router.active_version == "v2"
    assert result.reason == "migrations completed before traffic activation"


def test_migration_failure_keeps_prior_version_serving():
    router = InMemoryTrafficRouter(active_version="v1")
    controller = DeploymentController(router)

    result = controller.rollout(
        "v2",
        [
            MigrationJob(
                "add_task_state_column",
                lambda: False,
                MigrationCompatibility.BACKWARD_COMPATIBLE,
            )
        ],
    )

    assert result.ready_for_traffic is False
    assert result.previous_version == "v1"
    assert result.active_version == "v1"
    assert router.active_version == "v1"
    assert result.migration_results[0].succeeded is False
    assert result.reason == "migration failure stopped rollout"


def test_migration_exception_keeps_prior_version_serving():
    router = InMemoryTrafficRouter(active_version="v1")
    controller = DeploymentController(router)

    def explode():
        raise RuntimeError("database unavailable")

    result = controller.rollout(
        "v2",
        [
            MigrationJob(
                "backfill_task_state",
                explode,
                MigrationCompatibility.BACKWARD_COMPATIBLE,
            )
        ],
    )

    assert result.ready_for_traffic is False
    assert router.active_version == "v1"
    assert result.migration_results[0].error == "database unavailable"


def test_release_check_identifies_backward_compatible_migrations():
    check = ReleaseCheck.from_migrations(
        [
            MigrationJob(
                "expand_state_table",
                lambda: True,
                MigrationCompatibility.BACKWARD_COMPATIBLE,
            ),
            MigrationJob(
                "drop_old_state_column",
                lambda: True,
                MigrationCompatibility.DESTRUCTIVE,
            ),
        ]
    )

    assert check.backward_compatible is False
    assert check.blocking_migrations == ["drop_old_state_column"]


def test_incompatible_release_is_blocked_before_migrations_run():
    router = InMemoryTrafficRouter(active_version="v1")
    controller = DeploymentController(router)
    ran = []

    result = controller.rollout(
        "v2",
        [
            MigrationJob(
                "drop_old_state_column",
                lambda: ran.append(True) or True,
                MigrationCompatibility.DESTRUCTIVE,
            )
        ],
    )

    assert ran == []
    assert result.ready_for_traffic is False
    assert result.release_check.blocking_migrations == [
        "drop_old_state_column"
    ]
    assert router.active_version == "v1"
