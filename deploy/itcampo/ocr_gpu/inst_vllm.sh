set -e
cd ~/jfn-gpu
export PATH=$HOME/.local/bin:$PATH
[ -d vllm-env ] || uv venv -p 3.12 --seed vllm-env
. vllm-env/bin/activate
uv pip install vllm 2>&1 | tail -3
python -c "import vllm, torch; print('vllm', vllm.__version__, 'torch', torch.__version__, torch.cuda.is_available())"
ln -sf ~/jfn-gpu/vllm-env/bin/vllm ~/.local/bin/vllm
echo VLLM_OK
