from fastapi.testclient import TestClient

from src.api.server import create_app


def make_client(**config):
    return TestClient(create_app(config or None))


class TestAgentRoutes:
    def setup_method(self):
        self.client = make_client()
        self.client.__enter__()

    def teardown_method(self):
        self.client.__exit__(None, None, None)

    def _register(self, name="test-agent", agent_type="worker.processor"):
        resp = self.client.post("/api/v2/agents", json={"name": name, "agent_type": agent_type})
        assert resp.status_code == 201
        return resp.json()["agent_id"]

    def test_health(self):
        resp = self.client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "healthy"
        assert body["engine_running"] is True

    def test_register_and_get_agent(self):
        agent_id = self._register()
        resp = self.client.get(f"/api/v2/agents/{agent_id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "test-agent"

    def test_agent_count_not_shadowed_by_agent_id_route(self):
        self._register()
        resp = self.client.get("/api/v2/agents/count")
        assert resp.status_code == 200
        assert resp.json()["count"] == 1

    def test_list_agents_invalid_status(self):
        resp = self.client.get("/api/v2/agents", params={"status": "bogus"})
        assert resp.status_code == 422

    def test_get_missing_agent(self):
        resp = self.client.get("/api/v2/agents/nonexistent")
        assert resp.status_code == 404

    def test_start_stop_delete_agent(self):
        agent_id = self._register()
        assert self.client.post(f"/api/v2/agents/{agent_id}/start").status_code == 200
        assert self.client.get(f"/api/v2/agents/{agent_id}").json()["status"] == "running"
        assert self.client.post(f"/api/v2/agents/{agent_id}/stop").status_code == 200
        assert self.client.delete(f"/api/v2/agents/{agent_id}").status_code == 200
        assert self.client.get(f"/api/v2/agents/{agent_id}").status_code == 404

    def test_submit_task_and_get_result(self):
        agent_id = self._register()
        resp = self.client.post("/api/v2/tasks", json={
            "target_agent": agent_id,
            "payload": {"msg": "hello"},
        })
        assert resp.status_code == 201
        task_id = resp.json()["task_id"]

        # The engine loop runs inside the TestClient's lifespan; poll until done.
        import time
        for _ in range(100):
            task = self.client.get(f"/api/v2/tasks/{task_id}").json()
            if task["status"] == "completed":
                break
            time.sleep(0.05)
        assert task["status"] == "completed"
        assert task["result"]["echo"] == {"msg": "hello"}

    def test_submit_task_unknown_agent(self):
        resp = self.client.post("/api/v2/tasks", json={"target_agent": "ghost"})
        assert resp.status_code == 404

    def test_metrics_endpoint(self):
        resp = self.client.get("/api/v2/metrics")
        assert resp.status_code == 200
        assert "counters" in resp.json()


class TestAuth:
    def test_auth_disabled_without_key(self):
        with make_client() as client:
            assert client.get("/api/v2/agents").status_code == 200

    def test_auth_rejects_missing_and_wrong_token(self):
        with make_client(api_key="sekrit") as client:
            assert client.get("/api/v2/agents").status_code == 401
            assert client.get(
                "/api/v2/agents", headers={"Authorization": "Bearer wrong"}
            ).status_code == 401
            assert client.get("/health").status_code == 200

    def test_auth_accepts_valid_token(self):
        with make_client(api_key="sekrit") as client:
            resp = client.get("/api/v2/agents", headers={"Authorization": "Bearer sekrit"})
            assert resp.status_code == 200
