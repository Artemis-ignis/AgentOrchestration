import pytest

from src.sdk.decorators import agent


def test_agent_decorator_accepts_semantic_versions():
    @agent("worker", version="2.4.1-alpha.1+build.7", description="test")
    class Worker:
        pass

    assert Worker.__agent_config__ == {
        "name": "worker",
        "version": "2.4.1-alpha.1+build.7",
        "description": "test",
    }


@pytest.mark.parametrize(
    "version",
    [
        "",
        "1",
        "1.2",
        "v1.2.3",
        "1.02.3",
        "1.2.3.4",
        "latest",
        123,
    ],
)
def test_agent_decorator_rejects_malformed_versions(version):
    with pytest.raises(ValueError, match="semantic version format"):
        agent("worker", version=version)
