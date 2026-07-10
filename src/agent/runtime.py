"""Agent Runtime — Manages agent process lifecycle."""

import os
import signal
import subprocess
import logging
from enum import Enum
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class RuntimeState(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    CRASHED = "crashed"


class AgentRuntime:
    def __init__(self):
        self._processes: Dict[str, subprocess.Popen] = {}
        self._states: Dict[str, RuntimeState] = {}
        self._log_files: Dict[str, str] = {}

    def start(self, agent_id: str, command: list,
              env: Optional[Dict] = None, log_path: Optional[str] = None) -> bool:
        if agent_id in self._processes and self._processes[agent_id].poll() is None:
            logger.warning(f"Agent {agent_id} is already running")
            return False

        self._states[agent_id] = RuntimeState.STARTING
        process_env = os.environ.copy()
        if env:
            process_env.update(env)
        process_env["AO_AGENT_ID"] = agent_id

        # Stdout/stderr go to a log file rather than pipes — nobody drains a
        # pipe here, and a full pipe buffer would block the agent process.
        log_handle = open(log_path, "ab") if log_path else subprocess.DEVNULL

        try:
            proc = subprocess.Popen(
                command,
                env=process_env,
                stdout=log_handle,
                stderr=subprocess.STDOUT if log_path else subprocess.DEVNULL,
            )
            self._processes[agent_id] = proc
            self._states[agent_id] = RuntimeState.RUNNING
            if log_path:
                self._log_files[agent_id] = log_path
            logger.info(f"Agent {agent_id} started (PID: {proc.pid})")
            return True
        except Exception as e:
            self._states[agent_id] = RuntimeState.CRASHED
            logger.error(f"Failed to start agent {agent_id}: {e}")
            return False
        finally:
            if log_path:
                log_handle.close()

    def stop(self, agent_id: str, timeout: int = 10) -> bool:
        proc = self._processes.get(agent_id)
        if not proc or proc.poll() is not None:
            return False

        self._states[agent_id] = RuntimeState.STOPPING
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

        self._states[agent_id] = RuntimeState.STOPPED
        logger.info(f"Agent {agent_id} stopped")
        return True

    def get_state(self, agent_id: str) -> RuntimeState:
        proc = self._processes.get(agent_id)
        if proc and proc.poll() is not None:
            self._states[agent_id] = RuntimeState.CRASHED
        return self._states.get(agent_id, RuntimeState.STOPPED)

    def is_running(self, agent_id: str) -> bool:
        proc = self._processes.get(agent_id)
        return proc is not None and proc.poll() is None

    def pid(self, agent_id: str) -> Optional[int]:
        proc = self._processes.get(agent_id)
        return proc.pid if proc and proc.poll() is None else None

    def log_path(self, agent_id: str) -> Optional[str]:
        return self._log_files.get(agent_id)

    def stop_all(self) -> None:
        for agent_id in list(self._processes):
            self.stop(agent_id)
