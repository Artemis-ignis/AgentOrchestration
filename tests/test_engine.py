import asyncio

from src.orchestrator.engine import OrchestrationEngine


async def _run_engine_until(engine, condition, timeout=5.0):
    """Run the engine loop until condition() is true, then stop it."""
    engine_task = asyncio.create_task(engine.start())
    try:
        deadline = asyncio.get_event_loop().time() + timeout
        while not condition():
            assert asyncio.get_event_loop().time() < deadline, "engine test timed out"
            await asyncio.sleep(0.02)
    finally:
        engine.stop()
        await asyncio.wait_for(engine_task, timeout=2)


class TestOrchestrationEngine:
    def test_submit_task_unknown_agent(self):
        engine = OrchestrationEngine()
        try:
            engine.submit_task("no-such-agent")
            assert False, "expected AgentNotFoundError"
        except Exception as e:
            assert "no-such-agent" in str(e)

    def test_task_executes_with_default_handler(self):
        engine = OrchestrationEngine()
        agent_id = engine.registry.register("echo-agent", "demo.echo")
        task_id = engine.submit_task(agent_id, payload={"msg": "hi"})

        asyncio.run(_run_engine_until(
            engine, lambda: engine.get_task(task_id)["status"] == "completed"
        ))

        task = engine.get_task(task_id)
        assert task["result"]["echo"] == {"msg": "hi"}
        assert engine.registry.get(agent_id)["metrics"]["tasks_completed"] == 1

    def test_task_executes_with_registered_handler(self):
        engine = OrchestrationEngine()
        agent_id = engine.registry.register("worker", "worker.doubler")
        engine.register_handler("worker.doubler", lambda agent, task: task["payload"]["n"] * 2)
        task_id = engine.submit_task(agent_id, payload={"n": 21})

        asyncio.run(_run_engine_until(
            engine, lambda: engine.get_task(task_id)["status"] == "completed"
        ))

        assert engine.get_task(task_id)["result"] == 42

    def test_failing_task_retries_then_fails(self):
        engine = OrchestrationEngine(registry=None, scheduler=None)
        engine.scheduler._max_retries = 1
        agent_id = engine.registry.register("worker", "worker.broken")

        def broken(agent, task):
            raise RuntimeError("boom")

        engine.register_handler("worker.broken", broken)
        task_id = engine.submit_task(agent_id)

        asyncio.run(_run_engine_until(
            engine, lambda: engine.get_task(task_id)["status"] == "failed"
        ))

        task = engine.get_task(task_id)
        assert task["error"] == "boom"
        assert engine.registry.get(agent_id)["metrics"]["errors"] >= 1
