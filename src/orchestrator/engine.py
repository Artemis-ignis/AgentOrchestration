"""Orchestration Engine — Core execution and coordination logic."""

import asyncio
import logging
import os
import shlex
import tempfile
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from src.agent import AgentRegistry, AgentStatus
from src.agent.runtime import AgentRuntime, RuntimeState
from src.common.errors import AgentNotFoundError
from src.common.store import SqliteStore
from src.orchestrator.scheduler import TaskScheduler
from src.orchestrator.workflow import StepStatus, Workflow, WorkflowManager

logger = logging.getLogger(__name__)


class OrchestrationEngine:
    def __init__(
        self,
        max_workers: int = 10,
        agent_timeout: int = 300,
        registry: Optional[AgentRegistry] = None,
        scheduler: Optional[TaskScheduler] = None,
        db_path: Optional[str] = None,
    ):
        db_path = db_path if db_path is not None else os.getenv("AO_DB_PATH", "")
        self.store = SqliteStore(db_path) if db_path else None
        self.registry = registry or AgentRegistry(store=self.store)
        self.scheduler = scheduler or TaskScheduler()
        self.workflows = WorkflowManager()
        self.runtime = AgentRuntime()
        self._log_dir = Path(os.getenv("AO_LOG_DIR") or Path(tempfile.gettempdir()) / "ao-agent-logs")
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._last_reconcile = 0.0
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.agent_timeout = agent_timeout
        self._running = False
        self._handlers: Dict[str, Callable] = {}
        self._tasks: Dict[str, Dict[str, Any]] = {}
        # (timestamp, "completed" | "failed") outcomes for throughput history
        self._outcomes: deque = deque(maxlen=5000)
        self._hooks: Dict[str, List[Callable]] = {
            "pre_execute": [],
            "post_execute": [],
            "on_error": [],
            "on_complete": [],
        }
        if self.store:
            self._restore_state()

    def _restore_state(self) -> None:
        """Reload persisted tasks and workflows, re-enqueueing work that never
        finished (queued/retrying/running at the time of shutdown)."""
        requeued = 0
        for record in self.store.load_tasks():
            self._tasks[record["id"]] = record
            if record["status"] in ("queued", "retrying", "running"):
                record["status"] = "queued"
                task = {
                    "id": record["id"],
                    "target_agent": record["target_agent"],
                    "payload": record.get("payload") or {},
                }
                self.scheduler.enqueue(
                    task,
                    queue=record.get("queue", "default"),
                    priority=record.get("priority", 0),
                )
                requeued += 1
        for data in self.store.load_workflows():
            workflow = Workflow.from_dict(data)
            # a workflow mid-run at shutdown can simply be re-run
            if workflow.status == StepStatus.RUNNING:
                workflow.status = StepStatus.PENDING
            self.workflows.add_workflow(workflow)
        if self._tasks or self.workflows.list_workflows():
            logger.info(
                f"Restored {len(self._tasks)} tasks "
                f"({requeued} re-enqueued) and "
                f"{len(self.workflows.list_workflows())} workflows from {self.store.path}"
            )

    def _persist_task(self, record: Dict[str, Any]) -> None:
        if self.store:
            self.store.upsert_task(record)

    def persist_workflow(self, workflow) -> None:
        if self.store:
            self.store.upsert_workflow(workflow.to_dict())

    def register_hook(self, event: str, callback: Callable) -> None:
        if event in self._hooks:
            self._hooks[event].append(callback)

    def register_handler(self, agent_type: str, handler: Callable) -> None:
        """Register a callable to execute tasks for a given agent type.

        The handler receives (agent, task) and returns the task result.
        """
        self._handlers[agent_type] = handler

    def submit_task(
        self,
        target_agent: str,
        payload: Optional[Dict] = None,
        priority: int = 0,
        queue: str = "default",
    ) -> str:
        if not self.registry.get(target_agent):
            raise AgentNotFoundError(target_agent)
        task = {"target_agent": target_agent, "payload": payload or {}}
        task_id = self.scheduler.enqueue(task, queue=queue, priority=priority)
        self._tasks[task_id] = {
            "id": task_id,
            "target_agent": target_agent,
            "payload": task["payload"],
            "queue": queue,
            "priority": priority,
            "status": "queued",
            "result": None,
            "error": None,
            "submitted_at": time.time(),
        }
        self._persist_task(self._tasks[task_id])
        return task_id

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        return self._tasks.get(task_id)

    def list_tasks(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Most recently submitted tasks first."""
        tasks = sorted(self._tasks.values(), key=lambda t: t.get("submitted_at", 0), reverse=True)
        return tasks[:limit]

    async def run_workflow(self, workflow_id: str, step_timeout: float = 60.0) -> bool:
        """Execute a workflow's steps in order.

        Task steps are submitted to their agent and awaited; handler steps run
        in the worker pool. Stops at the first failed step.
        """
        workflow = self.workflows.get_workflow(workflow_id)
        if not workflow:
            return False

        workflow.status = StepStatus.RUNNING
        self.persist_workflow(workflow)
        for step in workflow.steps:
            step.status = StepStatus.RUNNING
            step.error = None
            self.persist_workflow(workflow)
            try:
                if step.target_agent:
                    task_id = self.submit_task(step.target_agent, payload=dict(step.payload))
                    step.result = {"task_id": task_id}
                    deadline = time.time() + step_timeout
                    while time.time() < deadline:
                        record = self._tasks[task_id]
                        if record["status"] == "completed":
                            step.result = record["result"]
                            break
                        if record["status"] == "failed":
                            raise RuntimeError(record["error"] or "task failed")
                        await asyncio.sleep(0.05)
                    else:
                        raise TimeoutError(f"step timed out after {step_timeout}s")
                else:
                    loop = asyncio.get_event_loop()
                    step.result = await loop.run_in_executor(self.executor, step.handler)
                step.status = StepStatus.COMPLETED
                self.persist_workflow(workflow)
            except Exception as e:
                step.error = str(e)
                step.status = StepStatus.FAILED
                workflow.status = StepStatus.FAILED
                self.persist_workflow(workflow)
                return False

        workflow.status = StepStatus.COMPLETED
        self.persist_workflow(workflow)
        return True

    def throughput(self, window: int = 300, bucket: int = 10) -> List[Dict[str, Any]]:
        """Task outcomes bucketed over the trailing window, oldest bucket first.

        Returns one entry per bucket: {"t": bucket_start, "completed": n, "failed": n},
        including empty buckets so the series is contiguous.
        """
        now = time.time()
        start = now - window
        buckets: List[Dict[str, Any]] = []
        edge = start - (start % bucket)
        while edge < now:
            buckets.append({"t": edge, "completed": 0, "failed": 0})
            edge += bucket
        for ts, outcome in self._outcomes:
            if ts < start:
                continue
            idx = int((ts - buckets[0]["t"]) // bucket)
            if 0 <= idx < len(buckets):
                buckets[idx][outcome] += 1
        return buckets

    def stats(self) -> Dict[str, Any]:
        agents_by_status: Dict[str, int] = {}
        for agent in self.registry.list():
            agents_by_status[agent["status"]] = agents_by_status.get(agent["status"], 0) + 1
        tasks_by_status: Dict[str, int] = {}
        for task in self._tasks.values():
            tasks_by_status[task["status"]] = tasks_by_status.get(task["status"], 0) + 1
        return {
            "agents": {"total": self.registry.count(), "by_status": agents_by_status},
            "tasks": {"total": len(self._tasks), "by_status": tasks_by_status},
            "queue": {
                "pending": self.scheduler.pending_count(),
                "in_flight": self.scheduler.in_flight_count(),
            },
            "throughput": self.throughput(),
            "engine_running": self._running,
        }

    @property
    def is_running(self) -> bool:
        return self._running

    # -- agent process lifecycle ------------------------------------------

    def _agent_command(self, agent: Dict[str, Any]) -> Optional[List[str]]:
        command = (agent.get("config") or {}).get("command")
        if not command:
            return None
        return shlex.split(command) if isinstance(command, str) else list(command)

    def start_agent(self, agent_id: str) -> bool:
        """Mark an agent running; if its config declares a `command`, launch
        the process too. Returns False when the process fails to launch."""
        agent = self.registry.get(agent_id)
        if not agent:
            raise AgentNotFoundError(agent_id)
        command = self._agent_command(agent)
        if command and not self.runtime.is_running(agent_id):
            log_path = str(self._log_dir / f"{agent_id}.log")
            if not self.runtime.start(agent_id, command, log_path=log_path):
                self.registry.update_status(agent_id, AgentStatus.FAILED)
                return False
        self.registry.update_status(agent_id, AgentStatus.RUNNING)
        return True

    def stop_agent(self, agent_id: str) -> bool:
        agent = self.registry.get(agent_id)
        if not agent:
            raise AgentNotFoundError(agent_id)
        self.runtime.stop(agent_id)
        self.registry.update_status(agent_id, AgentStatus.PAUSED)
        return True

    def runtime_info(self, agent_id: str) -> Optional[Dict[str, Any]]:
        agent = self.registry.get(agent_id)
        if not agent or not self._agent_command(agent):
            return None
        return {
            "state": self.runtime.get_state(agent_id).value,
            "pid": self.runtime.pid(agent_id),
        }

    def agent_log_tail(self, agent_id: str, lines: int = 50) -> Optional[str]:
        log_path = self.runtime.log_path(agent_id) or str(self._log_dir / f"{agent_id}.log")
        try:
            with open(log_path, "rb") as f:
                content = f.read().decode(errors="replace")
        except OSError:
            return None
        return "\n".join(content.splitlines()[-lines:])

    def reconcile_runtimes(self) -> None:
        """Flag process-backed agents whose process died as failed."""
        for agent in self.registry.list(status=AgentStatus.RUNNING):
            if not self._agent_command(agent):
                continue
            if self.runtime.get_state(agent["id"]) == RuntimeState.CRASHED:
                logger.warning(f"Agent {agent['id']} process crashed")
                agent["metrics"]["errors"] += 1
                self.registry.update_status(agent["id"], AgentStatus.FAILED)

    async def start(self) -> None:
        self._running = True
        logger.info("Orchestration engine started")
        while self._running:
            now = time.time()
            if now - self._last_reconcile >= 2.0:
                self._last_reconcile = now
                self.reconcile_runtimes()
            task = await self.scheduler.dequeue()
            if task:
                asyncio.create_task(self._execute_task(task))
            else:
                await asyncio.sleep(0.05)
        logger.info("Orchestration engine stopped")

    def stop(self) -> None:
        self._running = False

    async def _execute_task(self, task: Dict[str, Any]) -> None:
        task_id = task["id"]
        agent_id = task["target_agent"]
        record = self._tasks.setdefault(task_id, dict(task, status="queued", result=None, error=None))
        record["status"] = "running"
        logger.info(f"Executing task {task_id} on agent {agent_id}")

        for hook in self._hooks["pre_execute"]:
            await hook(task)

        agent = self.registry.get(agent_id)
        try:
            if not agent:
                raise AgentNotFoundError(agent_id)

            previous_status = agent["status"]
            self.registry.update_status(agent_id, AgentStatus.RUNNING)
            try:
                result = await asyncio.wait_for(
                    self._run_agent_task(agent, task),
                    timeout=self.agent_timeout,
                )
            finally:
                self.registry.update_status(agent_id, AgentStatus(previous_status))

            self.scheduler.complete(task_id)
            record["status"] = "completed"
            record["result"] = result
            record["completed_at"] = time.time()
            self._outcomes.append((record["completed_at"], "completed"))
            agent["metrics"]["tasks_completed"] += 1
            self._persist_task(record)
            self.registry.touch(agent_id)

            for hook in self._hooks["post_execute"]:
                await hook(task, result)
            for hook in self._hooks["on_complete"]:
                await hook(task, result)

            logger.info(f"Task {task_id} completed successfully")

        except Exception as e:
            logger.error(f"Task {task_id} failed: {e}")
            if agent:
                agent["metrics"]["errors"] += 1
            will_retry = self.scheduler.fail(task_id)
            record["error"] = str(e)
            record["status"] = "retrying" if will_retry else "failed"
            if not will_retry:
                self._outcomes.append((time.time(), "failed"))
            self._persist_task(record)
            if agent:
                self.registry.touch(agent_id)
            for hook in self._hooks["on_error"]:
                await hook(task, e)

    async def _run_agent_task(self, agent: Dict, task: Dict) -> Any:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor,
            self._execute_in_thread,
            agent,
            task,
        )

    def _execute_in_thread(self, agent: Dict, task: Dict) -> Any:
        handler = self._handlers.get(agent["type"])
        if handler:
            return handler(agent, task)
        # Default echo handler for agent types without a registered handler.
        return {
            "status": "completed",
            "agent": agent["name"],
            "echo": task.get("payload", {}),
        }
