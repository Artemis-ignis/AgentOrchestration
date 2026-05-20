"""Deployment rollout gate that runs migrations before traffic moves."""

import json
import shlex
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, List, Mapping, Optional, Sequence

import yaml


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
    run: Optional[Callable[[], bool]] = None
    compatibility: MigrationCompatibility = MigrationCompatibility.UNKNOWN
    command: Optional[Sequence[str]] = None
    required: bool = True
    timeout_seconds: Optional[float] = None


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
            MigrationCompatibility.UNKNOWN,
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

        required_migrations = [
            migration
            for migration in migration_list
            if migration.required
        ]
        migration_results = self._run_migrations(required_migrations)
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
            results.append(self._run_migration(migration))
        return results

    def _run_migration(self, migration: MigrationJob) -> MigrationResult:
        try:
            if migration.run is not None:
                return MigrationResult(
                    name=migration.name,
                    succeeded=bool(migration.run()),
                )

            if migration.command is None:
                return MigrationResult(
                    name=migration.name,
                    succeeded=False,
                    error="missing migration command",
                )

            completed = subprocess.run(
                list(migration.command),
                check=False,
                capture_output=True,
                text=True,
                timeout=migration.timeout_seconds,
            )
            if completed.returncode == 0:
                return MigrationResult(name=migration.name, succeeded=True)
            return MigrationResult(
                name=migration.name,
                succeeded=False,
                error=(
                    "migration command exited with status "
                    f"{completed.returncode}"
                ),
            )
        except subprocess.TimeoutExpired:
            return MigrationResult(
                name=migration.name,
                succeeded=False,
                error="migration command timed out",
            )
        except Exception as exc:
            return MigrationResult(
                name=migration.name,
                succeeded=False,
                error=str(exc),
            )


def rollout_from_manifest(path: str) -> DeploymentResult:
    current_version, target_version, migrations = load_rollout_manifest(path)
    controller = DeploymentController(
        InMemoryTrafficRouter(active_version=current_version)
    )
    return controller.rollout(target_version, migrations)


def load_rollout_manifest(
    path: str,
) -> tuple[str, str, Sequence[MigrationJob]]:
    raw = _read_manifest(path)
    release = _mapping(raw.get("release", {}))
    deployment = _mapping(raw.get("deployment", {}))
    app = _mapping(raw.get("app", {}))

    current_version = (
        _first_string(raw, release, deployment, app, key="current_version")
        or _first_string(raw, release, deployment, app, key="previous_version")
        or "current"
    )
    target_version = (
        _first_string(raw, release, deployment, app, key="target_version")
        or _first_string(raw, release, deployment, app, key="version")
        or "candidate"
    )
    migrations_raw = (
        _first_value(raw, release, deployment, key="migrations")
        or []
    )
    return (
        current_version,
        target_version,
        tuple(_parse_migrations(migrations_raw)),
    )


def _read_manifest(path: str) -> Mapping[str, Any]:
    manifest_path = Path(path)
    with manifest_path.open() as manifest:
        if manifest_path.suffix.lower() == ".json":
            data = json.load(manifest)
        else:
            data = yaml.safe_load(manifest)
    if not isinstance(data, Mapping):
        raise ValueError("deployment manifest must be a mapping")
    return data


def _parse_migrations(raw: Any) -> Sequence[MigrationJob]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError("migrations must be a list")

    migrations: List[MigrationJob] = []
    for index, item in enumerate(raw):
        data = _mapping(item)
        name = data.get("name") or data.get("id")
        if not isinstance(name, str) or not name:
            raise ValueError(f"migration {index} is missing a name")

        compatibility = _parse_compatibility(data)
        migrations.append(
            MigrationJob(
                name=name,
                compatibility=compatibility,
                command=_parse_command(data.get("command")),
                required=bool(data.get("required", True)),
                timeout_seconds=data.get("timeout_seconds"),
            )
        )
    return tuple(migrations)


def _parse_compatibility(data: Mapping[str, Any]) -> MigrationCompatibility:
    value = data.get("compatibility")
    if value is None:
        value = data.get("backward_compatible")
    if value is True:
        return MigrationCompatibility.BACKWARD_COMPATIBLE
    if value is False:
        return MigrationCompatibility.DESTRUCTIVE
    if isinstance(value, str):
        normalized = value.lower().replace("-", "_")
        for member in MigrationCompatibility:
            if member.value == normalized:
                return member
    return MigrationCompatibility.UNKNOWN


def _parse_command(raw: Any) -> Optional[Sequence[str]]:
    if raw is None:
        return None
    if isinstance(raw, str):
        return tuple(shlex.split(raw))
    if isinstance(raw, list) and all(isinstance(item, str) for item in raw):
        return tuple(raw)
    raise ValueError("migration command must be a string or string list")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _first_string(*sections: Mapping[str, Any], key: str) -> Optional[str]:
    for section in sections:
        value = section.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _first_value(*sections: Mapping[str, Any], key: str) -> Any:
    for section in sections:
        if key in section:
            return section[key]
    return None
