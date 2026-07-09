"""Task Scheduler — Priority-based task queuing and dispatch."""

import heapq
import time
from typing import Any, Dict, Optional, Tuple
from uuid import uuid4


class PriorityQueue:
    def __init__(self):
        self._queue = []
        self._counter = 0

    def push(self, item: Any, priority: int = 0) -> None:
        heapq.heappush(self._queue, (-priority, self._counter, item))
        self._counter += 1

    def pop(self) -> Optional[Any]:
        if self._queue:
            return heapq.heappop(self._queue)[2]
        return None

    def peek(self) -> Optional[Any]:
        if self._queue:
            return self._queue[0][2]
        return None

    def __len__(self) -> int:
        return len(self._queue)


class TaskScheduler:
    def __init__(self, max_retries: int = 3):
        self._queues: Dict[str, PriorityQueue] = {}
        # task_id -> (due_at, task, queue, priority)
        self._scheduled: Dict[str, Tuple[float, Dict, str, int]] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._max_retries = max_retries

    def enqueue(self, task: Dict, queue: str = "default", priority: int = 0) -> str:
        task_id = task.get("id") or str(uuid4())
        task["id"] = task_id
        task["queue"] = queue
        task["priority"] = priority
        task.setdefault("enqueued_at", time.time())
        task.setdefault("retries", 0)

        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()
        self._queues[queue].push(task, priority)
        return task_id

    def schedule(self, task: Dict, delay: float, queue: str = "default", priority: int = 0) -> str:
        task_id = task.get("id") or str(uuid4())
        task["id"] = task_id
        self._scheduled[task_id] = (time.time() + delay, task, queue, priority)
        return task_id

    def _promote_due_tasks(self) -> None:
        now = time.time()
        due = [tid for tid, (due_at, _, _, _) in self._scheduled.items() if due_at <= now]
        for tid in due:
            _, task, queue, priority = self._scheduled.pop(tid)
            self.enqueue(task, queue, priority)

    async def dequeue(self, queue: str = "default") -> Optional[Dict]:
        self._promote_due_tasks()
        q = self._queues.get(queue)
        if q and len(q) > 0:
            task = q.pop()
            if task:
                self._in_flight[task["id"]] = task
                return task
        return None

    def complete(self, task_id: str) -> bool:
        return self._in_flight.pop(task_id, None) is not None

    def fail(self, task_id: str) -> bool:
        """Mark an in-flight task as failed. Re-enqueues it for retry and
        returns True while retries remain; returns False once exhausted."""
        task = self._in_flight.pop(task_id, None)
        if not task:
            return False
        task["retries"] = task.get("retries", 0) + 1
        if task["retries"] <= self._max_retries:
            self.enqueue(task, task.get("queue", "default"), task.get("priority", 0))
            return True
        return False

    def pending_count(self, queue: str = "default") -> int:
        q = self._queues.get(queue)
        return len(q) if q else 0

    def in_flight_count(self) -> int:
        return len(self._in_flight)
