import pytest

from src.release.multiarch import (
    ArchitectureValidation,
    ManifestValidationError,
    build_manifest_publication_plan,
)


def test_manifest_includes_only_validated_architecture_digests():
    plan = build_manifest_publication_plan(
        [
            ArchitectureValidation(
                "linux/amd64",
                "sha256:amd64",
                tests_passed=True,
                scan_passed=True,
                test_result_id="test-amd64",
                scan_result_id="scan-amd64",
            ),
            ArchitectureValidation(
                "linux/arm64",
                "sha256:arm64",
                tests_passed=True,
                scan_passed=True,
                test_result_id="test-arm64",
                scan_result_id="scan-arm64",
            ),
        ],
        required_architectures=["linux/amd64", "linux/arm64"],
    )

    assert plan.digests == {
        "linux/amd64": "sha256:amd64",
        "linux/arm64": "sha256:arm64",
    }
    assert plan.release_summary == [
        {
            "architecture": "linux/amd64",
            "digest": "sha256:amd64",
            "status": "validated",
            "test_result_id": "test-amd64",
            "scan_result_id": "scan-amd64",
        },
        {
            "architecture": "linux/arm64",
            "digest": "sha256:arm64",
            "status": "validated",
            "test_result_id": "test-arm64",
            "scan_result_id": "scan-arm64",
        },
    ]


def test_missing_architecture_validation_fails_manifest_publication():
    with pytest.raises(ManifestValidationError) as error:
        build_manifest_publication_plan(
            [
                ArchitectureValidation(
                    "linux/amd64",
                    "sha256:amd64",
                    tests_passed=True,
                    scan_passed=True,
                ),
            ],
            required_architectures=["linux/amd64", "linux/arm64"],
        )

    assert error.value.release_summary == [
        {
            "architecture": "linux/amd64",
            "digest": "sha256:amd64",
            "status": "validated",
            "test_result_id": "",
            "scan_result_id": "",
        },
        {
            "architecture": "linux/arm64",
            "digest": "",
            "status": "missing-validation",
            "test_result_id": "",
            "scan_result_id": "",
        },
    ]


def test_missing_scan_or_test_result_blocks_manifest_push():
    with pytest.raises(ManifestValidationError) as error:
        build_manifest_publication_plan(
            [
                ArchitectureValidation(
                    "linux/amd64",
                    "sha256:amd64",
                    tests_passed=False,
                    scan_passed=True,
                ),
                ArchitectureValidation(
                    "linux/arm64",
                    "sha256:arm64",
                    tests_passed=True,
                    scan_passed=False,
                ),
            ],
            required_architectures=["linux/amd64", "linux/arm64"],
        )

    assert [row["status"] for row in error.value.release_summary] == [
        "missing-test",
        "missing-scan",
    ]
