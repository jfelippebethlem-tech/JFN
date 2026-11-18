set -e
mkdir -p ~/jfn-gpu ~/.local/bin && cd ~/jfn-gpu
[ -x boot/bin/uv ] || { python3 -m venv boot && boot/bin/pip -q install uv; }
ln -sf ~/jfn-gpu/boot/bin/uv ~/.local/bin/uv
export PATH=$HOME/.local/bin:$PATH
[ -d .venv ] || uv venv -p 3.12 --seed .venv
. .venv/bin/activate
uv pip install --index-url https://download.pytorch.org/whl/cu128 torch torchvision
uv pip install surya-ocr pymupdf rapidfuzz numpy pandas pyarrow sentence-transformers faiss-cpu unidecode
python - <<'P'
import torch;print("torch",torch.__version__,"cuda",torch.cuda.is_available(),torch.cuda.get_device_name(0))
x=torch.randn(4096,4096,device="cuda");print("matmul ok",float((x@x).sum())!=0)
P
echo SETUP_OK
