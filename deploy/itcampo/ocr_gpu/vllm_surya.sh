#!/bin/bash
# Sobe o vLLM nativo (sem docker) com o checkpoint do Surya na porta 8790 e espera ficar pronto.
cd ~/jfn-gpu
CK=$(.venv/bin/python -c "from surya.settings import settings; print(settings.SURYA_MODEL_CHECKPOINT)")
echo "checkpoint: $CK"
if ! curl -s -m3 http://127.0.0.1:8790/v1/models >/dev/null; then
  CC=gcc nohup setsid vllm-env/bin/vllm serve "$CK" --port 8790 --host 127.0.0.1 --dtype bfloat16 \
     --max-model-len 24576 --gpu-memory-utilization 0.80 --served-model-name "$CK" \
     > vllm_surya.log 2>&1 < /dev/null &
fi
for i in $(seq 1 100); do
  curl -s -m3 http://127.0.0.1:8790/v1/models >/dev/null && { echo "VLLM_PRONTO em $((i*5))s"; break; }
  sleep 5
done
tail -5 vllm_surya.log
nvidia-smi --query-gpu=memory.used,memory.total --format=csv
