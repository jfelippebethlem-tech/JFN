# -*- coding: utf-8 -*-
"""Gera os locks com hashes de `requirements*.txt` (O9.3).

Por que não `uv lock`: o `pyproject.toml` só carrega configuração de ferramenta (ruff/pytest/coverage), sem tabela
`[project]` — o `uv lock` rodado nele produz um `uv.lock` de 52 bytes sem nenhum pacote (era o "uv.lock vazio" do
plano, §2). As dependências moram nos `requirements*.txt`, que o CI, a VM-2 e o Dockerfile já instalam; o lock acompanha
esses arquivos, um por camada:

    requirements-sei.lock  <- requirements.txt + requirements-sei.txt   (nós de OCR/CDP do SEI)
    requirements-dev.lock  <- requirements.txt + requirements-dev.txt   (o venv da suíte/CI)
    requirements.lock      <- requirements.txt                          (só produção)

A do SEI sai primeiro, livre, e é a base: as outras duas são resolvidas com `-c requirements-sei.lock`, então um pacote
comum às camadas tem a MESMA versão em todas (instalar `-r requirements-dev.lock -r requirements-sei.lock` juntos não
conflita). A base é a do SEI porque é a mais apertada: `paddleocr`/`paddlex` só convivem com numpy 2.5 numa faixa
estreita de versões — resolvida a suíte primeiro, o numpy dela tornava o SEI insolúvel (medido 25/11/2026).

Torch: o CI instala torch CPU pelo índice do PyTorch e o resto SÓ do PyPI, porque `--extra-index-url` do PyTorch vale
para todo pacote (dependency confusion; ver .github/workflows/testes.yml). Aqui o PyTorch entra por `--find-links` das
páginas de `torch` e `torchvision` apenas — nenhum outro nome ganha candidato fora do PyPI — e a versão `+cpu` é fixada
por restrição. O lock leva as linhas `--find-links`, então `pip install --require-hashes -r <lock>` acha o wheel CPU
sozinho, sem as duas etapas.

Resolução `--universal` (marcadores): o mesmo arquivo serve VM-1/VM-2 (aarch64) e o it-campo WSL (x86_64), com os
hashes dos wheels de cada plataforma.

Reprodutível: o lock existente é a preferência do uv (só muda o que a mudança no requirements exige); `--upgrade`
atualiza tudo. O cabeçalho registra o sha256 de cada entrada — `tests/test_lock_dependencias.py` falha se um
requirements mudar sem o lock ser regenerado.

    python tools/lock_dependencias.py            # regenera os três
    python tools/lock_dependencias.py --upgrade  # idem, puxando as versões novas
"""
from __future__ import annotations

import hashlib
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

RAIZ = pathlib.Path(__file__).resolve().parent.parent

# Fixada à versão do venv da suíte na VM-2 (~/JFN-suite-venv, torch CPU do índice do PyTorch) em 25/11/2026.
TORCH_CPU = ("torch==2.15.0+cpu", "torchvision==0.29.2+cpu")
FIND_LINKS = ("https://download.pytorch.org/whl/torch/", "https://download.pytorch.org/whl/torchvision/")

# (lock, entradas, restringe pelo lock-base?) — a ordem importa: o lock-base sai primeiro.
BASE = "requirements-sei.lock"
CAMADAS = (
    (BASE, ("requirements.txt", "requirements-sei.txt"), False),
    ("requirements-dev.lock", ("requirements.txt", "requirements-dev.txt"), True),
    ("requirements.lock", ("requirements.txt",), True),
)
MARCA = "# entrada: "


def sha256(caminho: pathlib.Path) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


def cabecalho(entradas: tuple[str, ...]) -> str:
    linhas = ["# LOCK GERADO por tools/lock_dependencias.py — não editar à mão; regenerar: python tools/lock_dependencias.py",
              "# Instalar: pip install --require-hashes -r <este arquivo>   (torch CPU vem pelos --find-links abaixo)"]
    linhas += [f"{MARCA}{e} sha256={sha256(RAIZ / e)}" for e in entradas]
    return "\n".join(linhas) + "\n"


def _hashes_find_links(nome: str, versao: str) -> list[str]:
    """sha256 dos wheels cp312/py3 de `nome==versao` nas páginas `FIND_LINKS`. O uv não emite hash para candidato de
    `--find-links` (medido 25/11/2026: `torch==2.15.0+cpu` saía sem `--hash`, e `pip --require-hashes` recusaria o lock
    inteiro); a página do PyTorch publica o sha256 de cada wheel no fragmento `#sha256=` — o mesmo servidor de onde o pip
    baixa."""
    import urllib.request
    arq = re.escape(f"{nome}-{versao.replace('+', '%2B')}-") + r"(?:cp312-cp312|py3-none)-"
    achados: set[str] = set()
    for fl in FIND_LINKS:
        with urllib.request.urlopen(fl, timeout=60) as r:  # noqa: S310 — URL fixa do PyTorch
            html = r.read().decode("utf-8", "replace")
        achados |= set(re.findall(arq + r'[^"#]*\.whl#sha256=([0-9a-f]{64})', html))
    if not achados:
        sys.exit(f"[lock] nenhum sha256 de {nome}=={versao} (cp312/py3) em {FIND_LINKS} — lock NÃO gravado")
    return sorted(achados)


def _pos_processar(texto: str, restr: str) -> str:
    """Tira o caminho temporário da restrição dos comentários, deduplica `--find-links` (o `-c <lock-base>` traz as
    mesmas linhas) e põe hash nos pins do PyTorch."""
    texto = texto.replace(restr, "torch CPU (tools/lock_dependencias.py)")
    saida, vistos = [], set()
    for ln in texto.splitlines():
        if ln.startswith("--find-links"):
            if ln in vistos:
                continue
            vistos.add(ln)
        m = re.match(r"^(torch|torchvision)==(\S+)$", ln)
        if m:
            hs = _hashes_find_links(m.group(1), m.group(2))
            saida.append(ln + " \\")
            saida += [f"    --hash=sha256:{h}" + (" \\" if i < len(hs) - 1 else "") for i, h in enumerate(hs)]
            continue
        saida.append(ln)
    return "\n".join(saida) + "\n"


def gerar(upgrade: bool = False) -> None:
    uv = shutil.which("uv")
    if not uv:
        sys.exit("uv não encontrado no PATH (https://docs.astral.sh/uv/)")
    with tempfile.TemporaryDirectory() as tmp:
        restr = pathlib.Path(tmp) / "torch_cpu.txt"
        restr.write_text("\n".join(TORCH_CPU) + "\n", encoding="utf-8")
        for lock, entradas, com_base in CAMADAS:
            cmd = [uv, "pip", "compile", *entradas, "-o", lock, "--universal", "--python-version", "3.12",
                   "--generate-hashes", "--emit-find-links", "--no-header", "-c", str(restr)]
            for fl in FIND_LINKS:
                cmd += ["--find-links", fl]
            if com_base:
                cmd += ["-c", BASE]
            if upgrade and not com_base:
                cmd.append("--upgrade")
            subprocess.run(cmd, cwd=RAIZ, check=True)
            alvo = RAIZ / lock
            corpo = "".join(ln for ln in alvo.read_text(encoding="utf-8").splitlines(keepends=True)
                            if not ln.startswith(("# LOCK GERADO", "# Instalar:", MARCA)))
            alvo.write_text(cabecalho(entradas) + _pos_processar(corpo, str(restr)), encoding="utf-8")
            print(f"[lock] {lock} <- {' + '.join(entradas)}")


if __name__ == "__main__":
    gerar(upgrade="--upgrade" in sys.argv[1:])
