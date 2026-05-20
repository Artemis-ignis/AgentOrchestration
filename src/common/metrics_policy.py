"""Metrics label cardinality policy checks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set


DEFAULT_ALLOWED_LABEL_VALUES: Dict[str, Sequence[str]] = {
    "deployment.stage": ("dev", "staging", "prod"),
    "deployment.result": ("success", "failure", "rolled_back"),
    "task.priority": ("low", "normal", "high", "critical"),
    "task.queue": ("default", "batch", "realtime"),
    "task.status": ("queued", "running", "succeeded", "failed", "cancelled"),
    "worker.pool": ("default", "cpu", "gpu", "io"),
    "worker.region": ("local", "us-east", "us-west", "eu", "apac"),
    "worker.state": ("idle", "busy", "draining", "offline"),
}


@dataclass(frozen=True)
class MetricLabelViolation:
    metric: str
    label: str
    reason: str


class MetricsLabelPolicyError(ValueError):
    """Raised when a deploy manifest violates the metrics label policy."""

    def __init__(self, violations: Sequence[MetricLabelViolation]):
        self.violations = list(violations)
        details = "; ".join(
            f"{item.metric}.{item.label}: {item.reason}"
            for item in self.violations
        )
        super().__init__(f"metrics label policy violation: {details}")


@dataclass(frozen=True)
class MetricsLabelPolicy:
    allowed_label_values: Mapping[str, Sequence[str]]
    max_allowed_values: int = 50

    @classmethod
    def default(cls) -> "MetricsLabelPolicy":
        return cls(DEFAULT_ALLOWED_LABEL_VALUES)


def load_deploy_manifest(path: str) -> Mapping[str, Any]:
    """Load a JSON or YAML deploy manifest."""

    manifest_path = Path(path)
    raw = manifest_path.read_text(encoding="utf-8")
    if manifest_path.suffix.lower() == ".json":
        loaded = json.loads(raw)
    else:
        import yaml

        loaded = yaml.safe_load(raw)
    if loaded is None:
        return {}
    if not isinstance(loaded, Mapping):
        raise ValueError("deploy manifest must be a mapping")
    return loaded


def validate_deploy_metrics(
    manifest: Mapping[str, Any],
    policy: Optional[MetricsLabelPolicy] = None,
) -> List[MetricLabelViolation]:
    """Return policy violations for metrics declared by a deploy manifest."""

    active_policy = policy or MetricsLabelPolicy.default()
    metrics = _metrics_from_manifest(manifest)
    exceptions = _approved_exceptions_from_manifest(manifest)
    violations: List[MetricLabelViolation] = []

    for metric in metrics:
        name = str(metric.get("name") or "<unnamed>")
        labels = metric.get("labels") or {}
        for label, spec in _iter_labels(labels):
            if (name, label) in exceptions:
                continue
            reason = _label_violation_reason(label, spec, active_policy)
            if reason:
                violations.append(MetricLabelViolation(name, label, reason))

    return violations


def enforce_deploy_metrics_policy(
    manifest: Mapping[str, Any],
    policy: Optional[MetricsLabelPolicy] = None,
) -> None:
    """Raise if deploy metrics violate the active label policy."""

    violations = validate_deploy_metrics(manifest, policy)
    if violations:
        raise MetricsLabelPolicyError(violations)


def format_policy_violations(
    violations: Sequence[MetricLabelViolation],
) -> List[str]:
    return [
        f"{item.metric}.{item.label}: {item.reason}"
        for item in violations
    ]


def _metrics_from_manifest(
    manifest: Mapping[str, Any],
) -> List[Mapping[str, Any]]:
    candidates: List[Any] = []
    if "metrics" in manifest:
        candidates.append(manifest.get("metrics"))
    observability = manifest.get("observability")
    if isinstance(observability, Mapping) and "metrics" in observability:
        candidates.append(observability.get("metrics"))

    metrics: List[Mapping[str, Any]] = []
    for candidate in candidates:
        if isinstance(candidate, Mapping):
            if "name" in candidate and "labels" in candidate:
                metrics.append(candidate)
                continue
            candidate = (
                candidate.get("definitions")
                or candidate.get("items")
                or []
            )
        if not isinstance(candidate, Iterable) or isinstance(
            candidate,
            (str, bytes),
        ):
            continue
        for item in candidate:
            if isinstance(item, Mapping):
                metrics.append(item)
    return metrics


def _approved_exceptions_from_manifest(
    manifest: Mapping[str, Any],
) -> Set[tuple]:
    exceptions: Set[tuple] = set()
    sources: List[Any] = [
        manifest.get("metrics_label_exceptions"),
    ]
    observability = manifest.get("observability")
    if isinstance(observability, Mapping):
        sources.append(observability.get("metrics_label_exceptions"))

    for source in sources:
        if not isinstance(source, Iterable) or isinstance(
            source,
            (str, bytes),
        ):
            continue
        for item in source:
            if not isinstance(item, Mapping):
                continue
            metric = item.get("metric")
            label = item.get("label")
            approved_by = item.get("approved_by")
            reason = item.get("reason")
            if metric and label and approved_by and reason:
                exceptions.add((str(metric), str(label)))
    return exceptions


def _iter_labels(labels: Any) -> Iterable[tuple]:
    if isinstance(labels, Mapping):
        for label, spec in labels.items():
            yield str(label), spec
    elif isinstance(labels, Iterable) and not isinstance(labels, (str, bytes)):
        for label in labels:
            yield str(label), None


def _label_violation_reason(
    label: str,
    spec: Any,
    policy: MetricsLabelPolicy,
) -> Optional[str]:
    allowed_values = _allowed_values_from_spec(spec)
    unbounded = _is_unbounded_spec(spec)

    if allowed_values is None and label in policy.allowed_label_values:
        allowed_values = list(policy.allowed_label_values[label])

    if unbounded or allowed_values is None:
        return "unbounded label requires approved exception"

    if len(allowed_values) == 0:
        return "label must declare at least one bounded value"

    if len(allowed_values) > policy.max_allowed_values:
        return (
            f"label declares {len(allowed_values)} values; "
            f"maximum is {policy.max_allowed_values}"
        )

    documented_values = policy.allowed_label_values.get(label)
    if documented_values is not None:
        unknown_values = sorted(set(allowed_values) - set(documented_values))
        if unknown_values:
            return (
                "label declares undocumented values: "
                f"{', '.join(unknown_values)}"
            )

    return None


def _allowed_values_from_spec(spec: Any) -> Optional[List[str]]:
    if spec is None:
        return None
    if isinstance(spec, Mapping):
        values = spec.get("allowed_values", spec.get("values"))
        if isinstance(values, Iterable) and not isinstance(
            values,
            (str, bytes),
        ):
            return [str(value) for value in values]
        return None
    if isinstance(spec, Iterable) and not isinstance(spec, (str, bytes)):
        return [str(value) for value in spec]
    return None


def _is_unbounded_spec(spec: Any) -> bool:
    if spec is None:
        return False
    if isinstance(spec, str):
        return spec.lower() in {"*", "any", "unbounded"}
    if isinstance(spec, Mapping):
        for key in ("cardinality", "max_cardinality"):
            value = spec.get(key)
            if (
                isinstance(value, str)
                and value.lower() in {"*", "any", "unbounded"}
            ):
                return True
        return spec.get("bounded") is False
    return False
