#!/bin/bash
set -e

# Manually starts the LoRA training worker (Faz C3 Aşama 3, #191). Never
# started by plain `docker compose up`/`up -d` -- the `worker` service in
# compose.yml sits behind `profiles: ["training"]` specifically so it is
# not running continuously by default; this script is the one place that
# actually brings it up, on demand.
#
# A LoRA run can already be queued (POST /companies/{id}/training-runs
# ?kind=lora_sft|lora_dpo) with this worker not running at all -- the job
# just sits in Redis until something consumes it. Run this script when
# you're ready to actually process the queue (real GPU fine-tuning needs a
# CUDA-capable host, see compose.yml's `worker` service comment); stop it
# again afterwards with scripts/stop_training_worker.sh.
docker compose --profile training up -d --build worker
echo "Training worker started. Logs: docker compose logs -f worker"
