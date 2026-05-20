"""Deployment rollout gate that runs migrations before traffic moves."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Iterable, List, Optional, Sequence


class MigrationCompatibility(Enum):
    """Compatibility class for release-order checks."""

    BACKWARD_COMPATIBLE = "backward_compatible"
    FORWARD_ONLY = "forward_only"
    DESTRUCTIVE = "destructive"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class MigrationJob:
    """A migration that must pass before traffic moves."""

    name: str
    run: Callable[[], bool]
    compatibility: MigrationCompatibility = MigrationCompatibility.UNKNOWN


@dataclass(frozen=True)
class MigrationResult:
    name: str
    succeeded: bool
    error: Optional[str] = None


@dataclass(frozen=True)
class ReleaseCheck:
    backward_compatible: bool
    blocking_migrations: List[str] = field(default_factory=list)

    @classmethod
    def from_migrations(
        cls,
        migrations: Sequence[MigrationJob],
    ) -> "ReleaseCheck":
        unsafe = {
            MigrationCompatibility.FORWARD_ONLY,
            MigrationCompatibility.DESTRUCTIVE,
        }
        blocking = [
            migration.name
            for migration in migrations
            if migration.compatibility in unsafe
        ]
        return cls(
            backward_compatible=not blocking,
            blocking_migrations=blocking,
        )


@dataclass(frozen=True)
class DeploymentResult:
    ready_for_traffic: bool
    active_version: str
    previous_version: str
    target_version: str
    release_check: ReleaseCheck
    migration_results: List[MigrationResult]
    reason: str


class InMemoryTrafficRouter:
    """Small routing boundary used by deploy code and tests."""

    def __init__(self, active_version: str):
        self.active_version = active_version
        self.known_versions = {active_version}

    def register_version(self, version: str) -> None:
        self.known_versions.add(version)

    def route_to(self, version: str) -> None:
        if version not in self.known_versions:
            raise ValueError(f"version is not registered: {version}")
        self.active_version = version


class DeploymentController:
    """Coordinates release checks, migrations, and traffic activation."""

    def __init__(self, router: InMemoryTrafficRouter):
        self._router = router

    def rollout(
        self,
        target_version: str,
        migrations: Iterable[MigrationJob],
        *,
        require_backward_compatible: bool = True,
    ) -> DeploymentResult:
        migration_list = list(migrations)
        previous_version = self._router.active_version
        release_check = ReleaseCheck.from_migrations(migration_list)

        backward_blocked = (
            require_backward_compatible
            and not release_check.backward_compatible
        )
        if backward_blocked:
            return DeploymentResult(
                ready_for_traffic=False,
                active_version=self._router.active_version,
                previous_version=previous_version,
                target_version=target_version,
                release_check=release_check,
                migration_results=[],
                reason=(
                    "release contains migrations that are not "
                    "backward compatible"
                ),
            )

        migration_results = self._run_migrations(migration_list)
        failed = [
            result
            for result in migration_results
            if not result.succeeded
        ]
        if failed:
            return DeploymentResult(
                ready_for_traffic=False,
                active_version=self._router.active_version,
                previous_version=previous_version,
                target_version=target_version,
                release_check=release_check,
                migration_results=migration_results,
                reason="migration failure stopped rollout",
            )

        self._router.register_version(target_version)
        self._router.route_to(target_version)
        return DeploymentResult(
            ready_for_traffic=True,
            active_version=self._router.active_version,
            previous_version=previous_version,
            target_version=target_version,
            release_check=release_check,
            migration_results=migration_results,
            reason="migrations completed before traffic activation",
        )

    def _run_migrations(
        self,
        migrations: Sequence[MigrationJob],
    ) -> List[MigrationResult]:
        results: List[MigrationResult] = []
        for migration in migrations:
            try:
                succeeded = bool(migration.run())
            except Exception as exc:
                results.append(
                    MigrationResult(
                        name=migration.name,
                        succeeded=False,
                        error=str(exc),
                    )
                )
                continue
            results.append(
                MigrationResult(
                    name=migration.name,
                    succeeded=succeeded,
                )
            )
        return results
