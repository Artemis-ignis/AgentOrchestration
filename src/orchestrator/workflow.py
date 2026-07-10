"""Workflow Manager — Defines and executes multi-step agent workflows."""

from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkflowStep:
    """A workflow step: either a Python callable (`handler`) or a task
    dispatched to an agent (`target_agent` + `payload`)."""

    def __init__(
        self,
        name: str,
        handler: Optional[Callable] = None,
        retries: int = 0,
        timeout: int = 300,
        target_agent: Optional[str] = None,
        payload: Optional[Dict] = None,
    ):
        if handler is None and target_agent is None:
            raise ValueError("WorkflowStep needs a handler or a target_agent")
        self.id = str(uuid4())
        self.name = name
        self.handler = handler
        self.retries = retries
        self.timeout = timeout
        self.target_agent = target_agent
        self.payload = payload or {}
        self.status = StepStatus.PENDING
        self.result: Any = None
        self.error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "kind": "task" if self.target_agent else "handler",
            "target_agent": self.target_agent,
            "payload": self.payload,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
        }


class Workflow:
    def __init__(self, name: str, description: str = ""):
        self.id = str(uuid4())
        self.name = name
        self.description = description
        self.steps: List[WorkflowStep] = []
        self._step_map: Dict[str, WorkflowStep] = {}
        self.status = StepStatus.PENDING

    def add_step(self, step: WorkflowStep) -> "Workflow":
        self.steps.append(step)
        self._step_map[step.id] = step
        return self

    def get_step(self, step_id: str) -> Optional[WorkflowStep]:
        return self._step_map.get(step_id)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "status": self.status.value,
            "steps": [s.to_dict() for s in self.steps],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Workflow":
        """Rebuild a persisted workflow. Only task steps survive a reload —
        handler callables cannot be serialized."""
        workflow = cls(data["name"], data.get("description", ""))
        workflow.id = data["id"]
        workflow.status = StepStatus(data.get("status", "pending"))
        for s in data.get("steps", []):
            if not s.get("target_agent"):
                continue
            step = WorkflowStep(s["name"], target_agent=s["target_agent"], payload=s.get("payload") or {})
            step.id = s["id"]
            step.status = StepStatus(s.get("status", "pending"))
            step.result = s.get("result")
            step.error = s.get("error")
            workflow._step_map[step.id] = step
            workflow.steps.append(step)
        return workflow


class WorkflowManager:
    def __init__(self):
        self._workflows: Dict[str, Workflow] = {}

    def create_workflow(self, name: str, description: str = "") -> Workflow:
        workflow = Workflow(name, description)
        self._workflows[workflow.id] = workflow
        return workflow

    def add_workflow(self, workflow: Workflow) -> None:
        self._workflows[workflow.id] = workflow

    def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        return self._workflows.get(workflow_id)

    def list_workflows(self) -> List[Workflow]:
        return list(self._workflows.values())

    def delete_workflow(self, workflow_id: str) -> bool:
        return self._workflows.pop(workflow_id, None) is not None

    def execute_workflow(self, workflow_id: str) -> bool:
        workflow = self._workflows.get(workflow_id)
        if not workflow:
            return False

        workflow.status = StepStatus.RUNNING
        for step in workflow.steps:
            if step.handler is None:
                step.status = StepStatus.FAILED
                step.error = "task steps require OrchestrationEngine.run_workflow"
                workflow.status = StepStatus.FAILED
                return False
            step.status = StepStatus.RUNNING
            attempts = step.retries + 1
            for attempt in range(1, attempts + 1):
                try:
                    step.result = step.handler()
                    step.error = None
                    step.status = StepStatus.COMPLETED
                    break
                except Exception as e:
                    step.error = str(e)
                    if attempt >= attempts:
                        step.status = StepStatus.FAILED
                        workflow.status = StepStatus.FAILED
                        return False

        workflow.status = StepStatus.COMPLETED
        return True
