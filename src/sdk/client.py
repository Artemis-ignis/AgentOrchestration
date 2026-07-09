"""Orchestrator API client SDK."""

import os
from typing import Dict, Optional

import httpx


class OrchestratorClient:
    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None, timeout: float = 10.0):
        self.base_url = (base_url or os.getenv("AO_API_URL", "http://127.0.0.1:8000")).rstrip("/")
        self.api_key = api_key or os.getenv("AO_API_KEY", "")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        self._client = httpx.Client(base_url=self.base_url, headers=headers, timeout=timeout)

    def _request(self, method: str, path: str, json: Optional[Dict] = None, params: Optional[Dict] = None) -> Dict:
        try:
            resp = self._client.request(method, f"/api/v2{path}", json=json, params=params)
        except httpx.HTTPError as e:
            return {"error": "connection", "message": str(e)}

        try:
            data = resp.json()
        except ValueError:
            data = {"detail": resp.text}

        if resp.status_code >= 400:
            detail = data.get("detail", resp.reason_phrase) if isinstance(data, dict) else resp.reason_phrase
            return {"error": resp.status_code, "message": detail}
        return data

    # -- Agents ------------------------------------------------------------

    def register_agent(self, name: str, agent_type: str, config: Optional[Dict] = None) -> Dict:
        return self._request("POST", "/agents", json={
            "name": name,
            "agent_type": agent_type,
            "config": config or {},
        })

    def list_agents(self, status: Optional[str] = None, group: Optional[str] = None) -> Dict:
        params = {}
        if status:
            params["status"] = status
        if group:
            params["group"] = group
        return self._request("GET", "/agents", params=params or None)

    def get_agent(self, agent_id: str) -> Dict:
        return self._request("GET", f"/agents/{agent_id}")

    def delete_agent(self, agent_id: str) -> Dict:
        return self._request("DELETE", f"/agents/{agent_id}")

    def start_agent(self, agent_id: str) -> Dict:
        return self._request("POST", f"/agents/{agent_id}/start")

    def stop_agent(self, agent_id: str) -> Dict:
        return self._request("POST", f"/agents/{agent_id}/stop")

    def count_agents(self) -> Dict:
        return self._request("GET", "/agents/count")

    # -- Tasks -------------------------------------------------------------

    def submit_task(self, target_agent: str, payload: Optional[Dict] = None,
                    priority: int = 0, queue: str = "default") -> Dict:
        return self._request("POST", "/tasks", json={
            "target_agent": target_agent,
            "payload": payload or {},
            "priority": priority,
            "queue": queue,
        })

    def get_task(self, task_id: str) -> Dict:
        return self._request("GET", f"/tasks/{task_id}")

    def list_tasks(self, limit: int = 50) -> Dict:
        return self._request("GET", "/tasks", params={"limit": limit})

    # -- Platform ----------------------------------------------------------

    def get_metrics(self) -> Dict:
        return self._request("GET", "/metrics")

    def get_stats(self) -> Dict:
        return self._request("GET", "/stats")

    def health(self) -> Dict:
        try:
            resp = self._client.get("/health")
            return resp.json()
        except (httpx.HTTPError, ValueError) as e:
            return {"error": "connection", "message": str(e)}

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "OrchestratorClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
