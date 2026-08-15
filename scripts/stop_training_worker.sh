#!/bin/bash
set -e

# Stops and removes the LoRA training worker started by
# scripts/start_training_worker.sh (Faz C3 Aşama 3, #191). Any job already
# picked up mid-run is interrupted -- training_runs.status stays "running"
# for it (there is no separate liveness signal to mark it "failed" from
# outside the worker process itself); re-running scripts/
# start_training_worker.sh does not resume it, a fresh run has to be
# triggered again.
docker compose --profile training stop worker
docker compose --profile training rm -f worker
echo "Training worker stopped."
