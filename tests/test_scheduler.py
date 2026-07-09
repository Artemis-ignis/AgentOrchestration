from src.orchestrator.scheduler import TaskScheduler


class TestTaskScheduler:
    def setup_method(self):
        self.scheduler = TaskScheduler()

    def test_enqueue_task(self):
        task_id = self.scheduler.enqueue({"type": "test", "payload": {}})
        assert task_id is not None

    def test_dequeue_task(self):
        self.scheduler.enqueue({"type": "test", "payload": {"data": 1}})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert task is not None
        assert task["type"] == "test"

    def test_enqueue_multiple_priorities(self):
        self.scheduler.enqueue({"type": "low"}, priority=1)
        self.scheduler.enqueue({"type": "high"}, priority=10)
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert task["type"] == "high"

    def test_complete_task(self):
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert self.scheduler.complete(task["id"])

    def test_fail_task_with_retry(self):
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert self.scheduler.fail(task["id"])

    def test_retry_preserves_id_and_priority(self):
        import asyncio
        task_id = self.scheduler.enqueue({"type": "test"}, priority=7)
        task = asyncio.run(self.scheduler.dequeue())
        self.scheduler.fail(task["id"])
        retried = asyncio.run(self.scheduler.dequeue())
        assert retried["id"] == task_id
        assert retried["priority"] == 7
        assert retried["retries"] == 1

    def test_retries_exhaust(self):
        import asyncio
        scheduler = TaskScheduler(max_retries=1)
        scheduler.enqueue({"type": "test"})
        task = asyncio.run(scheduler.dequeue())
        assert scheduler.fail(task["id"])  # retry 1 allowed
        task = asyncio.run(scheduler.dequeue())
        assert not scheduler.fail(task["id"])  # exhausted
        assert asyncio.run(scheduler.dequeue()) is None

    def test_schedule_delivers_task_after_delay(self):
        import asyncio
        import time
        task_id = self.scheduler.schedule({"type": "delayed"}, delay=0.05)
        assert asyncio.run(self.scheduler.dequeue()) is None
        time.sleep(0.06)
        task = asyncio.run(self.scheduler.dequeue())
        assert task is not None
        assert task["id"] == task_id
        assert task["type"] == "delayed"
