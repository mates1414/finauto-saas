from abc import ABC, abstractmethod
from typing import Optional
from arq import create_pool
from arq.connections import RedisSettings
from ..config import Settings

class JobQueue(ABC):
    @abstractmethod
    async def enqueue_extraction(self, job_id: str) -> None:
        """Enqueue a PDF extraction job."""
        pass

    @abstractmethod
    async def enqueue_report(self, job_id: str) -> None:
        """Enqueue a strategic report generation job."""
        pass


class ArqQueue(JobQueue):
    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self._pool = None

    async def get_pool(self):
        if self._pool is None:
            self._pool = await create_pool(RedisSettings.from_dsn(self.redis_url))
        return self._pool

    async def enqueue_extraction(self, job_id: str) -> None:
        pool = await self.get_pool()
        await pool.enqueue_job("extract_task", job_id)

    async def enqueue_report(self, job_id: str) -> None:
        pool = await self.get_pool()
        await pool.enqueue_job("report_task", job_id)


class InMemoryQueue(JobQueue):
    async def enqueue_extraction(self, job_id: str) -> None:
        # Import dynamically to avoid circular dependencies
        from .tasks import run_extraction_task
        import asyncio
        asyncio.create_task(run_extraction_task(job_id))

    async def enqueue_report(self, job_id: str) -> None:
        from .tasks import run_report_task
        import asyncio
        asyncio.create_task(run_report_task(job_id))


_queue_instance: Optional[JobQueue] = None

def get_job_queue(settings: Settings) -> JobQueue:
    global _queue_instance
    if _queue_instance is None:
        if settings.queue_provider == "arq" and settings.redis_url:
            _queue_instance = ArqQueue(settings.redis_url)
        else:
            _queue_instance = InMemoryQueue()
    return _queue_instance
