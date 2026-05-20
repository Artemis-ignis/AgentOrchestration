import pytest

from src.agent.sidecar_compose import (
    SidecarComposeError,
    load_compose_file,
    validate_sidecar_services,
)


def test_repo_compose_sidecars_are_read_only_with_tmpfs():
    compose = load_compose_file("infra/docker-compose.yml")

    validate_sidecar_services(compose)


def test_rejects_sidecar_without_read_only_root():
    compose = {
        "services": {
            "metrics-sidecar": {
                "image": "busybox:1.36",
                "tmpfs": ["/tmp:rw,noexec,nosuid,size=8m"],
            }
        }
    }

    with pytest.raises(SidecarComposeError, match="read_only must be true"):
        validate_sidecar_services(compose)


def test_rejects_sidecar_without_writable_tmpfs():
    compose = {
        "services": {
            "log-forwarder": {
                "image": "busybox:1.36",
                "labels": {"ao.role": "sidecar"},
                "read_only": True,
            }
        }
    }

    with pytest.raises(SidecarComposeError, match="tmpfs"):
        validate_sidecar_services(compose)


def test_ignores_non_sidecar_services():
    compose = {
        "services": {
            "agent-worker": {
                "image": "python:3.11-slim",
            }
        }
    }

    validate_sidecar_services(compose)
