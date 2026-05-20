import importlib.util
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "check_pinned_actions.py"
)
SPEC = importlib.util.spec_from_file_location(
    "check_pinned_actions",
    SCRIPT_PATH,
)
check_pinned_actions = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(check_pinned_actions)


PINNED_SHA = "34e114876b0b11c390a56381ad16ebd13914f8d5"


def write_workflow(tmp_path, content):
    workflow = tmp_path / "ci.yml"
    workflow.write_text(content, encoding="utf-8")
    return workflow


def test_accepts_full_commit_sha(tmp_path):
    workflow = write_workflow(
        tmp_path,
        f"""
name: CI
jobs:
  test:
    steps:
      - uses: actions/checkout@{PINNED_SHA}
""",
    )

    assert check_pinned_actions.find_mutable_refs(workflow) == []


def test_rejects_mutable_tag(tmp_path):
    workflow = write_workflow(
        tmp_path,
        """
name: CI
jobs:
  test:
    steps:
      - uses: actions/checkout@v4
""",
    )

    violations = check_pinned_actions.find_mutable_refs(workflow)
    assert "mutable action ref" in violations[0]


def test_ignores_local_actions(tmp_path):
    workflow = write_workflow(
        tmp_path,
        """
name: CI
jobs:
  test:
    steps:
      - uses: ./.github/actions/bootstrap
""",
    )

    assert check_pinned_actions.find_mutable_refs(workflow) == []


def test_rejects_mutable_reusable_workflow_ref(tmp_path):
    workflow = write_workflow(
        tmp_path,
        """
name: CI
jobs:
  test:
    uses: owner/repo/.github/workflows/reusable.yml@main
""",
    )

    violations = check_pinned_actions.find_mutable_refs(workflow)
    assert "mutable action ref" in violations[0]
