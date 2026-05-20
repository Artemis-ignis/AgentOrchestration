import sys

import pytest

from src.cli.main import cli
from src.common.metrics_policy import (
    MetricsLabelPolicyError,
    enforce_deploy_metrics_policy,
    validate_deploy_metrics,
)


def test_deploy_metrics_allow_bounded_task_and_worker_labels():
    manifest = {
        "metrics": [
            {
                "name": "task.events",
                "labels": {
                    "task.status": [
                        "queued",
                        "running",
                        "succeeded",
                        "failed",
                    ],
                    "worker.pool": ["cpu", "gpu"],
                },
            }
        ]
    }

    assert validate_deploy_metrics(manifest) == []


def test_deploy_metrics_block_unbounded_label_without_exception():
    manifest = {
        "metrics": [
            {
                "name": "task.events",
                "labels": {
                    "task.id": {"cardinality": "unbounded"},
                    "task.status": ["queued", "running"],
                },
            }
        ]
    }

    violations = validate_deploy_metrics(manifest)

    assert len(violations) == 1
    assert violations[0].metric == "task.events"
    assert violations[0].label == "task.id"


def test_deploy_metrics_reject_unknown_documented_label_value():
    manifest = {
        "metrics": [
            {
                "name": "task.events",
                "labels": {
                    "task.status": ["queued", "timed_out"],
                },
            }
        ]
    }

    violations = validate_deploy_metrics(manifest)

    assert violations[0].label == "task.status"
    assert "timed_out" in violations[0].reason


def test_deploy_metrics_allow_approved_exception():
    manifest = {
        "metrics": [
            {
                "name": "task.events",
                "labels": {
                    "task.id": {"cardinality": "unbounded"},
                },
            }
        ],
        "metrics_label_exceptions": [
            {
                "metric": "task.events",
                "label": "task.id",
                "approved_by": "observability-owner",
                "reason": "short-lived debugging rollout",
            }
        ],
    }

    enforce_deploy_metrics_policy(manifest)


def test_deploy_metrics_accept_single_metric_mapping():
    manifest = {
        "metrics": {
            "name": "worker.events",
            "labels": {
                "worker.state": ["idle", "busy"],
            },
        }
    }

    assert validate_deploy_metrics(manifest) == []


def test_cli_deploy_blocks_manifest_with_unbounded_label(
    tmp_path,
    monkeypatch,
    capsys,
):
    manifest = tmp_path / "agent.yaml"
    manifest.write_text(
        "\n".join(
            [
                "metrics:",
                "  - name: worker.events",
                "    labels:",
                "      worker.id:",
                "        cardinality: unbounded",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "argv", ["ao", "deploy", str(manifest)])

    with pytest.raises(SystemExit) as exc_info:
        cli()

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "Deployment blocked by metrics label policy" in captured.err
    assert "worker.events.worker.id" in captured.err


def test_policy_error_includes_violations():
    manifest = {
        "observability": {
            "metrics": [
                {
                    "name": "deployment.rollout",
                    "labels": {
                        "request.path": {"bounded": False},
                    },
                }
            ]
        }
    }

    with pytest.raises(MetricsLabelPolicyError) as exc_info:
        enforce_deploy_metrics_policy(manifest)

    assert exc_info.value.violations[0].label == "request.path"
