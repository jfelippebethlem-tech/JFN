# -*- coding: utf-8 -*-
"""streetview_embed_proto — PROTÓTIPO ISOLADO (Fase 1): renderiza o Street View do **Maps Embed API**
(GRÁTIS/ilimitada) via Playwright/Chromium headless e screenshota → salva um JPG temp.

⚠ PROTEÇÃO MÁXIMA DA VM (2 vCPU, 7,8GB, SEM SWAP — render WebGL já travou esta VM antes):
  - Gate ANTES de renderizar: aborta se mem livre < 1,5GB OU load(1m) > 3.0.
  - O render roda em SUBPROCESSO com CAP DE RAM REAL via cgroup-v2 (systemd-run --user --scope):
        timeout 30  systemd-run --user --scope -p MemoryMax=2G -p MemorySwapMax=0 \
                    nice -n10 python THIS --render ...
    → `MemoryMax=2G` OOM-mata SÓ o cgroup do Chromium se ele estourar 2GB de RAM REAL (não afeta o resto
      da VM); `timeout` mata se travar; `nice -n10` cede CPU ao sweep SEI. UM render só, headless.
    ⚠ NÃO se usa `ulimit -v` aqui: o Chromium (PartitionAlloc) RESERVA dezenas de GB de ESPAÇO DE
      ENDEREÇAMENTO VIRTUAL no boot (não é RAM commitada) e `ulimit -v` o mata na hora
      (`FATAL:partition_address_space.cc`). O cap de RAM real do cgroup é o equivalente correto e seguro.
  - Mede load+mem ANTES, (best-effort) DURANTE e DEPOIS.

Uso:
  python tools/streetview_embed_proto.py            # roda IDESI + 2 urbanos, com gate+subprocesso+medição
  python tools/streetview_embed_proto.py --render <lat> <lon> <out.jpg>   # USO INTERNO (já dentro do cap)

A key vem de GOOGLE_MAPS_KEY no ambiente (.env). A Embed API pode precisar estar HABILITADA no projeto GCP;
se o render mostrar erro de API-não-habilitada, o validador detecta e o relatório aponta a ação do dono.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# ── Parâmetros de proteção da VM ──────────────────────────────────────────────
MEM_LIVRE_MIN_MB = 1500      # aborta se mem livre < isto
LOAD_MAX = 3.0               # aborta se load(1m) > isto
MEM_MAX = "2G"               # cap de RAM REAL do cgroup (systemd MemoryMax) — OOM-mata só o Chromium
RENDER_TIMEOUT_S = 30        # `timeout` do subprocesso de render
NICE = 10                    # `nice -n`
VIEWPORT = (640, 480)        # screenshot pequeno (menos RAM/menos pixels)

IDESI = (-21.8698059, -43.3453055)
URBANOS = [
    (-22.8956481, -43.1855748),   # Rio de Janeiro (verificacao_sede)
    (-15.8240141, -47.9010812),   # Brasília/DF (verificacao_sede)
]


def _embed_url(lat: float, lon: float, key: str) -> str:
    return (f"https://www.google.com/maps/embed/v1/streetview?key={key}"
            f"&location={lat},{lon}&fov=90&pitch=0")


# ════════════════════════════════════════════════════════════════════════════
#  MODO RENDER (interno) — roda JÁ DENTRO do cap (timeout+ulimit+nice).
#  Faz UM render só e sai. Nada aqui deve rodar fora do subprocesso protegido.
# ════════════════════════════════════════════════════════════════════════════
def _render_one(lat: float, lon: float, out: Path) -> int:
    key = os.environ.get("GOOGLE_MAPS_KEY", "").strip()
    if not key:
        print("ERRO: GOOGLE_MAPS_KEY ausente no ambiente", file=sys.stderr)
        return 3
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:  # noqa: BLE001
        print(f"ERRO: playwright indisponível: {e}", file=sys.stderr)
        return 4
    url = _embed_url(lat, lon, key)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",          # /dev/shm pequeno → usa /tmp
                "--disable-gpu",                     # sem GPU real na VM (Street View cai p/ canvas/software)
                "--disable-software-rasterizer",
                "--disable-extensions",
                "--js-flags=--max-old-space-size=512",
            ],  # NÃO usar --single-process/--no-zygote: instáveis aqui e sem ganho (o cap de RAM é o cgroup)
        )
        try:
            page = browser.new_page(viewport={"width": VIEWPORT[0], "height": VIEWPORT[1]})
            # networkidle pode nunca chegar (tiles streaming) → usa load + espera curta fixa.
            page.goto(url, wait_until="load", timeout=20000)
            page.wait_for_timeout(6000)   # deixa o panorama do Street View desenhar
            page.screenshot(path=str(out), type="jpeg", quality=80)
        finally:
            browser.close()
    return 0


# ════════════════════════════════════════════════════════════════════════════
#  VALIDAÇÃO DA IMAGEM — Street View real vs tela de erro/cinza/API-off.
# ════════════════════════════════════════════════════════════════════════════
def _validar_jpg(path: Path) -> dict:
    """Heurística leve (sem libs pesadas, sem rede): tamanho + variância de cor amostrada.
    Tela de erro/cinza tende a ser pequena e/ou monocromática; Street View real tem cor variada."""
    if not path.exists():
        return {"ok": False, "motivo": "arquivo não gerado"}
    n = path.stat().st_size
    if n < 4096:
        return {"ok": False, "motivo": f"muito pequeno ({n} B) — provável tela de erro/vazia"}
    head = path.read_bytes()[:3]
    if head != b"\xff\xd8\xff":
        return {"ok": False, "motivo": "não é JPEG válido"}
    # Variância de cor — tenta Pillow (já no projeto p/ imagem); se faltar, fica no critério de tamanho.
    try:
        import io

        from PIL import Image
        im = Image.open(io.BytesIO(path.read_bytes())).convert("RGB")
        im = im.resize((64, 64))
        px = list(im.getdata())
        media = tuple(sum(c[i] for c in px) / len(px) for i in range(3))
        var = sum((c[0] - media[0]) ** 2 + (c[1] - media[1]) ** 2 + (c[2] - media[2]) ** 2
                  for c in px) / len(px)
        # A tela de erro "API não habilitada" = card BRANCO com texto preto no topo: a esmagadora maioria
        # dos pixels é branco puro e há pouca cor (sem fotos). Street View real é colorido e raramente
        # majoritariamente branco. → reprova se >70% branco OU variância baixa OU quase-cinza.
        branco = sum(1 for c in px if c[0] > 240 and c[1] > 240 and c[2] > 240) / len(px)
        cinza = abs(media[0] - media[1]) < 8 and abs(media[1] - media[2]) < 8  # sem dominância de cor
        if branco > 0.70:
            return {"ok": False, "bytes": n, "var": round(var, 1), "branco": round(branco, 2),
                    "motivo": f"{branco:.0%} de pixels brancos — tela de ERRO/card (provável "
                              "API-não-habilitada/consent), NÃO é Street View"}
        if var < 120 or (cinza and var < 400):
            return {"ok": False, "bytes": n, "var": round(var, 1), "branco": round(branco, 2),
                    "motivo": f"imagem monocromática/cinza (var={var:.0f}) — provável tela de erro/cinza"}
        return {"ok": True, "bytes": n, "var": round(var, 1), "branco": round(branco, 2),
                "motivo": "Street View plausível (colorido, não-branco)"}
    except Exception:  # noqa: BLE001
        return {"ok": n > 20000, "motivo": f"sem Pillow; só tamanho ({n} B)", "bytes": n}


# ════════════════════════════════════════════════════════════════════════════
#  MEDIÇÃO DA VM
# ════════════════════════════════════════════════════════════════════════════
def _mem_livre_mb() -> int:
    for ln in Path("/proc/meminfo").read_text().splitlines():
        if ln.startswith("MemAvailable:"):
            return int(ln.split()[1]) // 1024
    return -1


def _load1() -> float:
    return os.getloadavg()[0]


def _snap() -> str:
    return f"load1={_load1():.2f} mem_livre={_mem_livre_mb()}MB"


# ════════════════════════════════════════════════════════════════════════════
#  ORQUESTRADOR (modo default) — gate + subprocesso protegido + medição.
# ════════════════════════════════════════════════════════════════════════════
def _render_protegido(lat: float, lon: float, out: Path) -> dict:
    """Lança o render num subprocesso com timeout+ulimit+nice. Mede VM antes/depois.
    NÃO importa playwright no processo-pai (mantém o pai leve; tudo pesado fica no cap)."""
    antes = _snap()
    livre = _mem_livre_mb()
    load = _load1()
    if livre >= 0 and livre < MEM_LIVRE_MIN_MB:
        return {"ok": False, "skip": True, "motivo": f"GATE: mem livre {livre}MB < {MEM_LIVRE_MIN_MB}MB",
                "antes": antes}
    if load > LOAD_MAX:
        return {"ok": False, "skip": True, "motivo": f"GATE: load {load:.2f} > {LOAD_MAX}", "antes": antes}

    py = sys.executable
    script = str(Path(__file__).resolve())
    # timeout 30  systemd-run --user --scope -p MemoryMax=2G -p MemorySwapMax=0  nice -n10  PY SCRIPT --render ...
    # --scope: roda em foreground no nosso cgroup; MemoryMax/MemorySwapMax = cap de RAM REAL (sem swap → 0).
    cmd = ["timeout", str(RENDER_TIMEOUT_S),
           "systemd-run", "--user", "--scope", "--quiet",
           "-p", f"MemoryMax={MEM_MAX}", "-p", "MemorySwapMax=0",
           "nice", f"-n{NICE}",
           py, script, "--render", str(lat), str(lon), str(out)]

    rc, err = None, ""
    try:
        # timeout do wait um pouco acima do `timeout` externo (margem p/ teardown).
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=RENDER_TIMEOUT_S + 8)
        rc, err = proc.returncode, (proc.stderr or "")[-400:]
    except subprocess.TimeoutExpired:
        rc, err = 124, "subprocess.run estourou (teardown lento)"
    depois = _snap()

    res = {"antes": antes, "depois": depois, "rc": rc, "stderr": err.strip()}
    if rc == 124:
        res.update(ok=False, motivo="RENDER MATADO pelo `timeout 30` (travou/lento) — PROTEÇÃO ATUOU")
        return res
    if rc != 0:
        # rc 137 = morto por sinal 9 (provável OOM do ulimit -v) ; outros = erro interno
        oom = " (provável estouro do ulimit -v → morto)" if rc in (137, 139) else ""
        res.update(ok=False, motivo=f"render rc={rc}{oom}")
        return res
    val = _validar_jpg(out)
    res.update(ok=val.get("ok"), validacao=val)
    return res


def main() -> int:
    # modo interno de render (chamado de dentro do cap)
    if len(sys.argv) >= 2 and sys.argv[1] == "--render":
        lat, lon, out = float(sys.argv[2]), float(sys.argv[3]), Path(sys.argv[4])
        return _render_one(lat, lon, out)

    # carrega .env (key) se houver python-dotenv; senão confia no ambiente já exportado
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    except Exception:  # noqa: BLE001
        pass
    if not os.environ.get("GOOGLE_MAPS_KEY", "").strip():
        print("ABORTA: GOOGLE_MAPS_KEY ausente (.env / os.environ).")
        return 2

    tmp = Path("tmp"); tmp.mkdir(exist_ok=True)
    alvos = [("IDESI", *IDESI)] + [(f"URBANO{i+1}", la, lo) for i, (la, lo) in enumerate(URBANOS)]

    print(f"== streetview_embed_proto :: {_snap()} (gate: mem≥{MEM_LIVRE_MIN_MB}MB, load≤{LOAD_MAX}) ==")
    falhou_critico = False
    for nome, la, lo in alvos:
        out = tmp / f"sv_embed_{nome}.jpg"
        if out.exists():
            out.unlink()
        print(f"\n-- {nome}  ({la}, {lo}) --")
        r = _render_protegido(la, lo, out)
        print(f"   antes : {r.get('antes')}")
        print(f"   depois: {r.get('depois')}")
        print(f"   rc={r.get('rc')}  ok={r.get('ok')}  motivo={r.get('motivo', '')}")
        if r.get("validacao"):
            print(f"   validação: {r['validacao']}")
        if r.get("stderr"):
            print(f"   stderr(tail): {r['stderr'][:200]}")
        if r.get("ok") and out.exists():
            print(f"   JPG salvo: {out}  ({out.stat().st_size} B)")
        if r.get("motivo", "").startswith("RENDER MATADO") or r.get("rc") in (137, 139):
            falhou_critico = True
            print("   ⚠ SINAL DE TRAVAMENTO/ESTOURO — abortando o resto por segurança.")
            break

    print("\n== fim ==")
    return 1 if falhou_critico else 0


if __name__ == "__main__":
    raise SystemExit(main())
