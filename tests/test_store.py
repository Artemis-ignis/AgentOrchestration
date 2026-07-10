import asyncio

from src.orchestrator.engine import OrchestrationEngine
from src.orchestrator.workflow import WorkflowStep


class TestPersistence:
    def test_agents_survive_restart(self, tmp_path):
        db = str(tmp_path / "ao.db")
        engine = OrchestrationEngine(db_path=db)
        agent_id = engine.registry.register("keeper", "worker.keeper", {"k": 1})
        engine.store.close()

        reborn = OrchestrationEngine(db_path=db)
        agent = reborn.registry.get(agent_id)
        assert agent is not None
        assert agent["name"] == "keeper"
        assert agent["config"] == {"k": 1}
        assert len(reborn.registry.list(group="worker")) == 1
        reborn.store.close()

    def test_completed_tasks_and_metrics_survive_restart(self, tmp_path):
        db = str(tmp_path / "ao.db")
        engine = OrchestrationEngine(db_path=db)
        agent_id = engine.registry.register("worker", "worker.echo")
        task_id = engine.submit_task(agent_id, payload={"n": 1})

        async def run():
            loop_task = asyncio.create_task(engine.start())
            try:
                while engine.get_task(task_id)["status"] != "completed":
                    await asyncio.sleep(0.02)
            finally:
                engine.stop()
                await asyncio.wait_for(loop_task, timeout=2)

        asyncio.run(asyncio.wait_for(run(), timeout=5))
        engine.store.close()

        reborn = OrchestrationEngine(db_path=db)
        task = reborn.get_task(task_id)
        assert task["status"] == "completed"
        assert task["result"]["echo"] == {"n": 1}
        assert reborn.registry.get(agent_id)["metrics"]["tasks_completed"] == 1
        reborn.store.close()

    def test_unfinished_tasks_requeue_on_restart(self, tmp_path):
        db = str(tmp_path / "ao.db")
        engine = OrchestrationEngine(db_path=db)
        agent_id = engine.registry.register("worker", "worker.echo")
        # submit without running the engine loop -> stays queued
        task_id = engine.submit_task(agent_id, payload={"n": 7}, priority=3)
        engine.store.close()

        reborn = OrchestrationEngine(db_path=db)
        assert reborn.get_task(task_id)["status"] == "queued"
        assert reborn.scheduler.pending_count() == 1

        async def run():
            loop_task = asyncio.create_task(reborn.start())
            try:
                while reborn.get_task(task_id)["status"] != "completed":
                    await asyncio.sleep(0.02)
            finally:
                reborn.stop()
                await asyncio.wait_for(loop_task, timeout=2)

        asyncio.run(asyncio.wait_for(run(), timeout=5))
        assert reborn.get_task(task_id)["result"]["echo"] == {"n": 7}
        reborn.store.close()

    def test_workflows_survive_restart(self, tmp_path):
        db = str(tmp_path / "ao.db")
        engine = OrchestrationEngine(db_path=db)
        agent_id = engine.registry.register("worker", "worker.echo")
        wf = engine.workflows.create_workflow("persisted", "desc")
        wf.add_step(WorkflowStep("one", target_agent=agent_id, payload={"s": 1}))
        wf.add_step(WorkflowStep("two", target_agent=agent_id, payload={"s": 2}))
        engine.persist_workflow(wf)
        engine.store.close()

        reborn = OrchestrationEngine(db_path=db)
        loaded = reborn.workflows.get_workflow(wf.id)
        assert loaded is not None
        assert [s.name for s in loaded.steps] == ["one", "two"]
        assert loaded.steps[1].payload == {"s": 2}

        async def run():
            loop_task = asyncio.create_task(reborn.start())
            try:
                ok = await asyncio.wait_for(reborn.run_workflow(wf.id), timeout=5)
            finally:
                reborn.stop()
                await asyncio.wait_for(loop_task, timeout=2)
            return ok

        assert asyncio.run(run())
        reborn.store.close()

    def test_no_db_means_no_store(self):
        engine = OrchestrationEngine(db_path="")
        assert engine.store is None
