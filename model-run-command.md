cd /home/aximsoft-dgx/spark-vllm-docker

sudo systemctl stop dgx-qwen38-flash-next.service 2>/dev/null || true
./launch-cluster.sh stop

./launch-cluster.sh --no-ray \
  -t vllm/vllm-openai:qwen38-flash-next \
  -v /opt/models:/models \
  -e HF_HUB_OFFLINE=1 \
  -e TRANSFORMERS_OFFLINE=1 \
  -e CUTE_DSL_ARCH=sm_121a \
  exec vllm serve /models/Ornith-1.5-35B-A3B-NVFP4 \
    --served-model-name /models/Ornith-1.5-35B-A3B-NVFP4 \
    --host 0.0.0.0 \
    --port 8000 \
    --trust-remote-code \
    --tensor-parallel-size 2 \
    --enable-expert-parallel \
    --all2all-backend allgather_reducescatter \
    --load-format safetensors \
    --safetensors-load-strategy lazy \
    --kv-cache-dtype fp8 \
    --max-model-len 262144 \
    --max-num-seqs 16 \
    --max-num-batched-tokens 16384 \
    --gpu-memory-utilization 0.85 \
    --enable-chunked-prefill \
    --enable-prefix-caching \
    --async-scheduling \
    --reasoning-parser qwen3 \
    --tool-call-parser qwen3_xml \
    --enable-auto-tool-choice \
    --speculative-config '{"method":"mtp","num_speculative_tokens":3}' \
    --compilation-config '{"cudagraph_mode":"FULL_AND_PIECEWISE"}'


    ./launch-cluster.sh stop

./launch-cluster.sh --no-ray \
  -t vllm/vllm-openai:qwen38-flash-next \
  -v /opt/models:/models \
  -e HF_HUB_OFFLINE=1 \
  -e TRANSFORMERS_OFFLINE=1 \
  -e CUTE_DSL_ARCH=sm_121a \
  exec vllm serve /models/Ornith-1.5-35B-A3B \
    --served-model-name /models/Ornith-1.5-35B-A3B \
    --host 0.0.0.0 \
    --port 8000 \
    --trust-remote-code \
    --tensor-parallel-size 2 \
    --enable-expert-parallel \
    --all2all-backend allgather_reducescatter \
    --dtype bfloat16 \
    --load-format safetensors \
    --safetensors-load-strategy lazy \
    --kv-cache-dtype fp8 \
    --max-model-len 262144 \
    --max-num-seqs 16 \
    --max-num-batched-tokens 16384 \
    --gpu-memory-utilization 0.85 \
    --enable-chunked-prefill \
    --enable-prefix-caching \
    --async-scheduling \
    --reasoning-parser qwen3 \
    --tool-call-parser qwen3_xml \
    --enable-auto-tool-choice \
    --speculative-config '{"method":"mtp","num_speculative_tokens":3}' \
    --compilation-config '{"cudagraph_mode":"FULL_AND_PIECEWISE"}'

    ./launch-cluster.sh --no-ray \
  -t vllm/vllm-openai:qwen38-flash-next \
  -v /opt/models:/models \
  -e HF_HUB_OFFLINE=1 \
  -e TRANSFORMERS_OFFLINE=1 \
  -e CUTE_DSL_ARCH=sm_121a \
  exec vllm serve /models/Qwen3.6-35B-A3B-NVFP4 \
    --served-model-name /models/Qwen3.6-35B-A3B-NVFP4 \
    --host 0.0.0.0 \
    --port 8000 \
    --trust-remote-code \
    --tensor-parallel-size 2 \
    --enable-expert-parallel \
    --all2all-backend allgather_reducescatter \
    --load-format safetensors \
    --safetensors-load-strategy lazy \
    --kv-cache-dtype fp8 \
    --max-model-len 262144 \
    --max-num-seqs 16 \
    --max-num-batched-tokens 16384 \
    --gpu-memory-utilization 0.85 \
    --enable-chunked-prefill \
    --enable-prefix-caching \
    --async-scheduling \
    --reasoning-parser qwen3 \
    --tool-call-parser qwen3_xml \
    --enable-auto-tool-choice \
    --speculative-config '{"method":"mtp","num_speculative_tokens":3}' \
    --compilation-config '{"cudagraph_mode":"FULL_AND_PIECEWISE"}'


    ./launch-cluster.sh --no-ray \
  -t vllm/vllm-openai:qwen38-flash-next \
  -v /opt/models:/models \
  -e HF_HUB_OFFLINE=1 \
  -e TRANSFORMERS_OFFLINE=1 \
  -e CUTE_DSL_ARCH=sm_121a \
  exec vllm serve /models/Qwen3.8-27B-FP8 \
    --served-model-name /models/Qwen3.8-27B-FP8 \
    --host 0.0.0.0 \
    --port 8000 \
    --trust-remote-code \
    --tensor-parallel-size 2 \
    --load-format safetensors \
    --safetensors-load-strategy lazy \
    --kv-cache-dtype fp8 \
    --max-model-len 262144 \
    --max-num-seqs 16 \
    --max-num-batched-tokens 16384 \
    --gpu-memory-utilization 0.85 \
    --enable-chunked-prefill \
    --enable-prefix-caching \
    --async-scheduling \
    --reasoning-parser qwen3 \
    --tool-call-parser qwen3_coder \
    --enable-auto-tool-choice \
    --speculative-config '{"method":"mtp","num_speculative_tokens":3}' \
    --compilation-config '{"cudagraph_mode":"FULL_AND_PIECEWISE"}'


  ./launch-cluster.sh --no-ray \
  -t vllm/vllm-openai:latest \
  -v /opt/models:/models \
  -e HF_HUB_OFFLINE=1 \
  -e TRANSFORMERS_OFFLINE=1 \
  exec vllm serve /models/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4 \
    --served-model-name /models/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4 \
    --host 0.0.0.0 \
    --port 8000 \
    --trust-remote-code \
    --tensor-parallel-size 1 \
    --data-parallel-size 2 \
    --moe-backend marlin \
    --kv-cache-dtype fp8 \
    --max-model-len 65536 \
    --max-num-seqs 8 \
    --max-num-batched-tokens 16384 \
    --gpu-memory-utilization 0.85 \
    --enable-chunked-prefill \
    --enable-prefix-caching \
    --async-scheduling \
    --mamba-backend flashinfer \
    --mamba-cache-mode align \
    --reasoning-parser nemotron_v3 \
    --tool-call-parser qwen3_coder \
    --enable-auto-tool-choice