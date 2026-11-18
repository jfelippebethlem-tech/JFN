"""v68 · ABERTURA EM VÍDEO gerada LOCALMENTE (sem Higgsfield) — LTX-Video 2B 0.9.8 distilled, image-to-video,
no it-campo (RTX 5070 Laptop, 8 GB). Roda no venv C:\\up\\v68\\venv.

Duas etapas (+ transformer em fp8 de armazenamento), para caber em 8 GB de VRAM com pouca RAM livre (o OCR do outro nó ocupa a máquina):
  embed   codifica os prompts com o T5 NA CPU, uma vez, e grava os tensores (o T5-XXL não cabe junto na GPU);
  gerar   carrega só o transformer 2B + VAE na GPU e gera cada (estratégia, semente) a partir dos embeddings.

Estratégias (quadro de referência = reator_r1.png, recorte quadrado do centro):
  ini   a imagem é o 1º quadro: anéis giram, núcleo pulsa ciano-branco, anel se expande;
  fim   a imagem é o ÚLTIMO quadro: fitas de luz convergem e o reator acende — o roteiro do brief.

Uso: python v68_abertura_ltx.py embed
     python v68_abertura_ltx.py gerar <estrategia> <semente> [semente...]
Saída: C:\\up\\v68\\ltx\\<estrategia>_<semente>.mp4 (24 fps, 97 quadros ≈ 4 s, 704×704)
"""
import sys
import time
import torch
from pathlib import Path
OUT = Path(r'C:\up\v68\ltx'); OUT.mkdir(parents=True, exist_ok=True)
BASE = 'Lightricks/LTX-Video-0.9.5'
TRANSF = 'https://huggingface.co/Lightricks/LTX-Video/blob/main/ltxv-2b-0.9.8-distilled.safetensors'
REF = r'C:\up\v68\reator_r1.png'
W = H = 704; NF = 97

PROMPTS = {
    'ini': ("A futuristic energy reactor made of thin glowing blue light rings floating in a bright white minimal "
            "room. The concentric rings rotate smoothly in opposite directions, the glass core ignites with a soft "
            "cyan-white pulse, then the outer ring expands outward. Fine luminous blue filaments swirl around it. "
            "Clean, elegant, high detail, cinematic, smooth motion, static camera."),
    'fim': ("Thin glowing blue light filaments stream in from the edges of a bright white minimal room and spiral "
            "inward, converging into a ring. The ring forms a futuristic reactor of concentric blue light rings that "
            "start rotating; the glass core ignites with a soft cyan-white pulse. Clean, elegant, high detail, "
            "cinematic, smooth motion, static camera."),
}
NEG = "worst quality, inconsistent motion, blurry, jittery, distorted, text, watermark, logo, people, dark background"

def embed():
    from transformers import T5EncoderModel, T5TokenizerFast
    tok = T5TokenizerFast.from_pretrained(BASE, subfolder='tokenizer')
    enc = T5EncoderModel.from_pretrained(BASE, subfolder='text_encoder', torch_dtype=torch.bfloat16, low_cpu_mem_usage=True)
    enc.eval()
    def um(txt):
        t = tok(txt, padding='max_length', max_length=128, truncation=True, return_tensors='pt')
        with torch.no_grad():
            e = enc(t.input_ids, attention_mask=t.attention_mask)[0]
        return e.to(torch.bfloat16), t.attention_mask
    d = {}
    for k, p in PROMPTS.items():
        d[k] = um(p)
    d['neg'] = um(NEG)
    torch.save(d, OUT / 'embeds.pt'); print('EMBED-OK', list(d))

def referencia():
    from PIL import Image
    im = Image.open(REF).convert('RGB'); w, h = im.size; s = min(w, h)
    return im.crop(((w - s) // 2, (h - s) // 2, (w + s) // 2, (h + s) // 2)).resize((W, H), Image.LANCZOS)

def gerar(estr, sementes):
    from diffusers import LTXConditionPipeline, LTXVideoTransformer3DModel
    from diffusers.pipelines.ltx.pipeline_ltx_condition import LTXVideoCondition
    from diffusers.utils import export_to_video
    tr = LTXVideoTransformer3DModel.from_single_file(TRANSF, torch_dtype=torch.bfloat16)
    pipe = LTXConditionPipeline.from_pretrained(BASE, transformer=tr, text_encoder=None, tokenizer=None, torch_dtype=torch.bfloat16)
    # VRAM dividida com o vLLM do OCR (WSL) e o Blender: pesos do transformer guardados em fp8 e calculados em bf16
    tr.enable_layerwise_casting(storage_dtype=torch.float8_e4m3fn, compute_dtype=torch.bfloat16)
    pipe.to('cuda'); pipe.vae.enable_tiling()
    d = torch.load(OUT / 'embeds.pt')
    pe, pm = d[estr]; ne, nm = d['neg']
    img = referencia()
    cond = LTXVideoCondition(image=img, frame_index=0 if estr == 'ini' else NF - 1)
    for s in sementes:
        dst = OUT / f'{estr}_{s}.mp4'
        if dst.exists(): continue
        t0 = time.time()
        fr = pipe(conditions=[cond], prompt_embeds=pe.cuda(), prompt_attention_mask=pm.cuda(),
                  negative_prompt_embeds=ne.cuda(), negative_prompt_attention_mask=nm.cuda(),
                  width=W, height=H, num_frames=NF, num_inference_steps=8, guidance_scale=1.0,
                  decode_timestep=0.05, decode_noise_scale=0.025, image_cond_noise_scale=0.0,
                  generator=torch.Generator('cuda').manual_seed(int(s)), output_type='pil').frames[0]
        export_to_video(fr, str(dst), fps=24)
        print('GEROU', dst.name, f'{time.time() - t0:.0f} s', f'vram_pico={torch.cuda.max_memory_allocated() / 2**30:.1f} GB', flush=True)

if __name__ == '__main__':
    if sys.argv[1] == 'embed': embed()
    else: gerar(sys.argv[2], sys.argv[3:])
