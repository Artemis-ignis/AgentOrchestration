"""Validation helpers for hardened sidecar compose services."""

from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml


class SidecarComposeError(ValueError):
    """Raised when a sidecar service is missing required hardening."""


def load_compose_file(path: str) -> Mapping[str, Any]:
    with Path(path).open() as compose_file:
        data = yaml.safe_load(compose_file)
    if not isinstance(data, Mapping):
        raise SidecarComposeError("compose file must be a mapping")
    return data


def validate_sidecar_services(compose: Mapping[str, Any]) -> None:
    """Reject sidecar services without read-only roots and writable tmpfs."""

    services = compose.get("services", {})
    if not isinstance(services, Mapping):
        raise SidecarComposeError("compose services must be a mapping")

    violations = []
    for name, service in services.items():
        if not _is_sidecar(name, service):
            continue
        if not isinstance(service, Mapping):
            violations.append(f"{name}: service must be a mapping")
            continue
        if service.get("read_only") is not True:
            violations.append(f"{name}: read_only must be true")
        if not _has_writable_tmpfs(service.get("tmpfs")):
            violations.append(f"{name}: tmpfs must declare writable paths")

    if violations:
        raise SidecarComposeError("; ".join(violations))


def validate_sidecar_compose_file(path: str) -> None:
    validate_sidecar_services(load_compose_file(path))


def _is_sidecar(name: str, service: Any) -> bool:
    if "sidecar" in name:
        return True
    if not isinstance(service, Mapping):
        return False
    labels = service.get("labels", {})
    if isinstance(labels, Mapping):
        return labels.get("ao.role") == "sidecar"
    if isinstance(labels, Iterable) and not isinstance(labels, (str, bytes)):
        return "ao.role=sidecar" in labels
    return False


def _has_writable_tmpfs(tmpfs: Any) -> bool:
    if isinstance(tmpfs, str):
        return bool(tmpfs.strip())
    if isinstance(tmpfs, list):
        return any(isinstance(item, str) and item.strip() for item in tmpfs)
    return False
