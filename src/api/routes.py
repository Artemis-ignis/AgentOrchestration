"""API route definitions."""

from typing import Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.agent import AgentStatus
from src.common.errors import AgentNotFoundError
from src.common.metrics import metrics

router = APIRouter()


class AgentCreate(BaseModel):
    name: str
    agent_type: str
    config: Dict = Field(default_factory=dict)


class TaskSubmit(BaseModel):
    target_agent: str
    payload: Dict = Field(default_factory=dict)
    priority: int = 0
    queue: str = "default"


def _engine(request: Request):
    return request.app.state.engine


@router.get("/agents/count")
async def agent_count(request: Request):
    return {"count": _engine(request).registry.count()}


@router.get("/agents")
async def list_agents(request: Request, status: Optional[str] = None, group: Optional[str] = None):
    status_filter = None
    if status:
        try:
            status_filter = AgentStatus(status)
        except ValueError:
            valid = ", ".join(s.value for s in AgentStatus)
            raise HTTPException(status_code=422, detail=f"Invalid status '{status}'. Valid values: {valid}")
    return {"agents": _engine(request).registry.list(status=status_filter, group=group)}


@router.post("/agents", status_code=201)
async def register_agent(request: Request, body: AgentCreate):
    agent_id = _engine(request).registry.register(body.name, body.agent_type, body.config)
    return {"agent_id": agent_id, "status": "registered"}


@router.get("/agents/{agent_id}")
async def get_agent(request: Request, agent_id: str):
    agent = _engine(request).registry.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.delete("/agents/{agent_id}")
async def delete_agent(request: Request, agent_id: str):
    if not _engine(request).registry.delete(agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "deleted"}


@router.post("/agents/{agent_id}/start")
async def start_agent(request: Request, agent_id: str):
    if not _engine(request).registry.update_status(agent_id, AgentStatus.RUNNING):
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "started"}


@router.post("/agents/{agent_id}/stop")
async def stop_agent(request: Request, agent_id: str):
    if not _engine(request).registry.update_status(agent_id, AgentStatus.PAUSED):
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "stopped"}


@router.post("/tasks", status_code=201)
async def submit_task(request: Request, body: TaskSubmit):
    try:
        task_id = _engine(request).submit_task(
            body.target_agent,
            payload=body.payload,
            priority=body.priority,
            queue=body.queue,
        )
    except AgentNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent not found: {body.target_agent}")
    return {"task_id": task_id, "status": "queued"}


@router.get("/tasks")
async def list_tasks(request: Request, limit: int = 50):
    return {"tasks": _engine(request).list_tasks(limit=max(1, min(limit, 500)))}


@router.get("/tasks/{task_id}")
async def get_task(request: Request, task_id: str):
    task = _engine(request).get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/stats")
async def get_stats(request: Request):
    return _engine(request).stats()


@router.get("/metrics")
async def get_metrics():
    return metrics.snapshot()
