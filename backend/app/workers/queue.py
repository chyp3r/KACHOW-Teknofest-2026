"""`arq` job runner wiring -- Faz C3, Aşama 3 (#191).

`WorkerSettings` is the process entrypoint (`arq app.workers.queue.
WorkerSettings`, see `deploy/docker/worker.Dockerfile`'s `CMD`), run only
inside the training worker container -- never started by `docker compose
up` (see `compose.yml`'s `worker` service, `profiles: ["training"]`), only
via `scripts/start_training_worker.sh`.

`enqueue_lora_training_job` is the caller side, imported and used by the
main backend process (`app.domains.training.service`) to hand a job to
whichever worker process happens to be running -- `arq` itself doesn't
care which process actually picks a job off the shared Redis queue, so the
API process enqueueing and a separate container executing is the normal
shape, not a special case.
"""

from typing import Optional

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.core.config import settings
from app.workers.training import run_lora_training_job

_pool: Optional[ArqRedis] = None


def _redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(settings.REDIS_URL)


async def get_arq_pool() -> ArqRedis:
    """A process-wide, lazily-connected arq Redis pool -- mirrors
    `app.infrastructure.cache.get_cache`'s own singleton-per-process
    convention, same reasoning (one pool, not one connection per call)."""
    global _pool
    if _pool is None:
        _pool = await create_pool(_redis_settings())
    return _pool


async def enqueue_lora_training_job(company_id: str, run_id: str) -> str:
    """Queue one LoRA training run. Returns arq's own job id (for logging
    only -- the durable status lives on `training_runs.status`, polled via
    `GET /companies/{id}/training-runs`, not this id)."""
    pool = await get_arq_pool()
    job = await pool.enqueue_job("run_lora_training_job", company_id, run_id)
    return job.job_id if job is not None else run_id


class WorkerSettings:
    functions = [run_lora_training_job]
    redis_settings = _redis_settings()
    #: One job at a time -- a single GPU host cannot usefully run two
    #: fine-tunes concurrently, and serializing avoids fighting over VRAM.
    max_jobs = 1
    #: Generous: a full LoRA run can genuinely take hours on real data.
    job_timeout = 6 * 60 * 60
