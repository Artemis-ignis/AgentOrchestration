import sys
import time

from src.orchestrator.engine import OrchestrationEngine


def make_engine(tmp_path, monkeypatch):
    monkeypatch.setenv("AO_LOG_DIR", str(tmp_path / "logs"))
    return OrchestrationEngine()


class TestAgentRuntimeIntegration:
    def test_start_and_stop_process_agent(self, tmp_path, monkeypatch):
        engine = make_engine(tmp_path, monkeypatch)
        agent_id = engine.registry.register("sleeper", "proc.sleeper", {
            "command": [sys.executable, "-c", "import time; time.sleep(60)"],
        })

        assert engine.start_agent(agent_id)
        assert engine.registry.get(agent_id)["status"] == "running"
        info = engine.runtime_info(agent_id)
        assert info["state"] == "running"
        assert isinstance(info["pid"], int)

        assert engine.stop_agent(agent_id)
        assert engine.registry.get(agent_id)["status"] == "paused"
        assert not engine.runtime.is_running(agent_id)

    def test_start_agent_without_command_just_marks_running(self, tmp_path, monkeypatch):
        engine = make_engine(tmp_path, monkeypatch)
        agent_id = engine.registry.register("plain", "worker.plain")
        assert engine.start_agent(agent_id)
        assert engine.registry.get(agent_id)["status"] == "running"
        assert engine.runtime_info(agent_id) is None

    def test_failed_launch_marks_agent_failed(self, tmp_path, monkeypatch):
        engine = make_engine(tmp_path, monkeypatch)
        agent_id = engine.registry.register("broken", "proc.broken", {
            "command": ["/nonexistent/binary-xyz"],
        })
        assert not engine.start_agent(agent_id)
        assert engine.registry.get(agent_id)["status"] == "failed"

    def test_reconcile_flags_crashed_process(self, tmp_path, monkeypatch):
        engine = make_engine(tmp_path, monkeypatch)
        agent_id = engine.registry.register("crasher", "proc.crasher", {
            "command": [sys.executable, "-c", "import sys; sys.exit(1)"],
        })
        assert engine.start_agent(agent_id)
        # wait for the short-lived process to exit
        for _ in range(100):
            if not engine.runtime.is_running(agent_id):
                break
            time.sleep(0.05)
        engine.reconcile_runtimes()
        agent = engine.registry.get(agent_id)
        assert agent["status"] == "failed"
        assert agent["metrics"]["errors"] == 1

    def test_agent_log_tail_captures_output(self, tmp_path, monkeypatch):
        engine = make_engine(tmp_path, monkeypatch)
        agent_id = engine.registry.register("talker", "proc.talker", {
            "command": [sys.executable, "-u", "-c", "print('hello from agent')"],
        })
        assert engine.start_agent(agent_id)
        for _ in range(100):
            log = engine.agent_log_tail(agent_id)
            if log and "hello from agent" in log:
                break
            time.sleep(0.05)
        assert "hello from agent" in engine.agent_log_tail(agent_id)

    def test_command_string_is_split(self, tmp_path, monkeypatch):
        engine = make_engine(tmp_path, monkeypatch)
        agent_id = engine.registry.register("stringcmd", "proc.stringcmd", {
            "command": f'"{sys.executable}" -c "import time; time.sleep(60)"',
        })
        assert engine.start_agent(agent_id)
        assert engine.runtime.is_running(agent_id)
        engine.stop_agent(agent_id)

    def test_status_flip_status_only_when_status_running_without_process(self, tmp_path, monkeypatch):
        engine = make_engine(tmp_path, monkeypatch)
        agent_id = engine.registry.register("plain", "worker.plain")
        engine.start_agent(agent_id)
        engine.reconcile_runtimes()  # must not flag a non-process agent
        assert engine.registry.get(agent_id)["status"] == "running"
