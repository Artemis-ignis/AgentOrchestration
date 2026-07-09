"""Orchestration Engine — Core execution and coordination logic."""

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional

from src.agent import AgentRegistry, AgentStatus
from src.common.errors import AgentNotFoundError
from src.orchestrator.scheduler import TaskScheduler

logger = logging.getLogger(__name__)


class OrchestrationEngine:
    def __init__(
        self,
        max_workers: int = 10,
        agent_timeout: int = 300,
        registry: Optional[AgentRegistry] = None,
        scheduler: Optional[TaskScheduler] = None,
    ):
        self.registry = registry or AgentRegistry()
        self.scheduler = scheduler or TaskScheduler()
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.agent_timeout = agent_timeout
        self._running = False
        self._handlers: Dict[str, Callable] = {}
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._hooks: Dict[str, List[Callable]] = {
            "pre_execute": [],
            "post_execute": [],
            "on_error": [],
            "on_complete": [],
        }

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
            "status": "queued",
            "result": None,
            "error": None,
            "submitted_at": time.time(),
        }
        return task_id

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        return self._tasks.get(task_id)

    def list_tasks(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Most recently submitted tasks first."""
        tasks = sorted(self._tasks.values(), key=lambda t: t.get("submitted_at", 0), reverse=True)
        return tasks[:limit]

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
            "engine_running": self._running,
        }

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        self._running = True
        logger.info("Orchestration engine started")
        while self._running:
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
            agent["metrics"]["tasks_completed"] += 1

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
