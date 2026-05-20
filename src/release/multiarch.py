"""Multi-architecture manifest validation before release publication."""

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence


@dataclass(frozen=True)
class ArchitectureValidation:
    """Validation result for one architecture-specific image digest."""

    architecture: str
    digest: Optional[str]
    tests_passed: bool
    scan_passed: bool
    test_result_id: Optional[str] = None
    scan_result_id: Optional[str] = None

    @property
    def status(self) -> str:
        if not self.digest:
            return "missing-digest"
        if not self.tests_passed:
            return "missing-test"
        if not self.scan_passed:
            return "missing-scan"
        return "validated"

    @property
    def can_publish(self) -> bool:
        return self.status == "validated"


@dataclass(frozen=True)
class ManifestPublicationPlan:
    """Validated architecture digests plus release summary rows."""

    digests: Dict[str, str]
    release_summary: List[Dict[str, str]]


class ManifestValidationError(ValueError):
    """Raised when a multi-arch manifest is not safe to publish."""

    def __init__(self, release_summary: List[Dict[str, str]]):
        self.release_summary = release_summary
        failures = [
            row["architecture"]
            for row in release_summary
            if row["status"] != "validated"
        ]
        super().__init__(
            "Cannot publish multi-arch manifest; validation incomplete for: "
            + ", ".join(failures)
        )


def build_manifest_publication_plan(
    validations: Iterable[ArchitectureValidation],
    required_architectures: Sequence[str],
) -> ManifestPublicationPlan:
    """Build a manifest plan or fail before an unsafe manifest push.

    Only architectures with digest, test, and scan validation are included in
    the manifest digest map. Missing architectures or incomplete validation
    results are listed in the release summary and block publication.
    """

    required = _dedupe(required_architectures)
    by_architecture = {
        validation.architecture: validation for validation in validations
    }
    digests: Dict[str, str] = {}
    summary: List[Dict[str, str]] = []

    for architecture in required:
        validation = by_architecture.get(architecture)
        if validation is None:
            summary.append(
                {
                    "architecture": architecture,
                    "digest": "",
                    "status": "missing-validation",
                    "test_result_id": "",
                    "scan_result_id": "",
                }
            )
            continue

        status = validation.status
        digest = validation.digest or ""
        if validation.can_publish:
            digests[architecture] = digest

        summary.append(
            {
                "architecture": architecture,
                "digest": digest,
                "status": status,
                "test_result_id": validation.test_result_id or "",
                "scan_result_id": validation.scan_result_id or "",
            }
        )

    if len(digests) != len(required):
        raise ManifestValidationError(summary)

    return ManifestPublicationPlan(
        digests=digests,
        release_summary=summary,
    )


def _dedupe(values: Sequence[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
