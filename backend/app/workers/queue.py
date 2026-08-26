"""`arq` job çalıştırıcı bağlantısı -- Faz C3, Aşama 3 (#191).

`WorkerSettings`, süreç giriş noktasıdır (`arq app.workers.queue.
WorkerSettings`, bkz. `deploy/docker/worker.Dockerfile`'ın `CMD`'si),
yalnızca training worker container'ı içinde çalışır -- `docker compose up`
ile asla başlatılmaz (bkz. `compose.yml`'ın `worker` servisi,
`profiles: ["training"]`), yalnızca `scripts/start_training_worker.sh`
üzerinden.

`enqueue_lora_training_job` çağıran taraftır; ana backend süreci
(`app.domains.training.service`) tarafından, o anda çalışan hangi worker
süreci olursa olsun ona bir iş devretmek için import edilir ve kullanılır
-- `arq`'ın kendisi paylaşılan Redis kuyruğundan işi hangi sürecin
gerçekten aldığını umursamaz, bu yüzden API sürecinin kuyruğa eklemesi ve
ayrı bir container'ın çalıştırması normal bir durumdur, özel bir durum
değil.
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
    """Süreç genelinde, tembel bağlanan bir arq Redis havuzu --
    `app.infrastructure.cache.get_cache`'in kendi süreç-başına-tekil
    kuralını yansıtır, aynı gerekçeyle (çağrı başına bir bağlantı değil,
    tek bir havuz)."""
    global _pool
    if _pool is None:
        _pool = await create_pool(_redis_settings())
    return _pool


async def enqueue_lora_training_job(company_id: str, run_id: str) -> str:
    """Bir LoRA training run'ını kuyruğa alır. arq'ın kendi job id'sini
    döner (yalnızca loglama amaçlı -- kalıcı durum bu id'de değil,
    `GET /companies/{id}/training-runs` üzerinden sorgulanan
    `training_runs.status`'ta yaşar)."""
    pool = await get_arq_pool()
    job = await pool.enqueue_job("run_lora_training_job", company_id, run_id)
    return job.job_id if job is not None else run_id


class WorkerSettings:
    functions = [run_lora_training_job]
    redis_settings = _redis_settings()
    #: Aynı anda tek bir iş -- tek bir GPU host, iki fine-tune işlemini eş
    #: zamanlı olarak faydalı bir şekilde çalıştıramaz; sıralı çalıştırmak
    #: VRAM için çekişmeyi önler.
    max_jobs = 1
    #: Cömert bir süre: gerçek veri üzerinde tam bir LoRA run'ı gerçekten
    #: saatler sürebilir.
    job_timeout = 6 * 60 * 60
