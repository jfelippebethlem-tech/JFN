#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LOTE de entrega VM-2 → VM-1 (lado VM-2). Nada que a VM-2 produz entra no acervo da VM-1 sem passar pela
conferência de `tools/vm2_conferencia.py`.

Um lote é uma pasta `data/vm2_lotes/<lote>/` com os arquivos nos caminhos que a conferência espera
(`arquivo/<tag>/…`, `cache/integra_<tag>/…`, `cache/cdp_*.json`) e um `MANIFESTO.json` com o md5 de cada
arquivo, o status de cada processo e o JUÍZO do Claude da VM-2 sobre uma amostra de texto. O lote vai por
rsync para `data/vm2_entrega/<lote>/` da VM-1 e a VM-1 confere e importa (`vm2_conferencia importar`). Lote
que não chegou (rede, VM-1 fora) fica aqui e é reenviado antes do próximo.

O juízo usa o Claude Code da VM-2 pela ASSINATURA (`compliance_agent.llm.claude_motor`, backend `cli` —
nunca a API paga), com teto próprio: `JFN_CLAUDE_MAX_CONFERENCIA_VM2` (padrão do script: 40/dia).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
LOTES = RAIZ / "data" / "vm2_lotes"
VM1 = os.environ.get("JFN_VM1_SSH", "vm1-ts")
VM1_JFN = os.environ.get("JFN_VM1_DIR", "/home/ubuntu/JFN")
TAREFA_JUIZO = "conferencia_vm2"

_PROMPT = """Você confere a qualidade de uma captura automática do SEI-RJ (processo administrativo público).
Processo: {proc}
Título do documento na árvore do SEI: {titulo}

Texto extraído (pode estar truncado):
<<<
{texto}
>>>

Julgue SÓ a captura, não o mérito: (a) o texto é legível (português, não é lixo de OCR, menu do sistema,
tela de login/erro ou página de escolha de unidade)? (b) o conteúdo é compatível com o título do documento?"""

_SCHEMA = {"legivel": True, "corresponde": True, "motivo": "frase curta"}


def _md5(p: Path) -> str:
    h = hashlib.md5()
    with p.open("rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def julgar(proc: str, titulo: str, texto: str) -> dict | None:
    """Juízo do Claude sobre UMA amostra. None = motor indisponível/teto (a conferência segue sem ele)."""
    if not (texto or "").strip():
        return None
    try:
        from compliance_agent.llm import claude_motor as cm
        r = cm.pensar(TAREFA_JUIZO, _PROMPT.format(proc=proc, titulo=titulo[:200], texto=texto[:6000]),
                      schema=_SCHEMA, modelo=cm.MODELO_VOLUME, timeout=150.0, backend="cli", espera=60.0)
    except Exception:  # noqa: BLE001 — juízo é camada extra: nunca derruba a entrega
        return None
    if r is None or not isinstance(r.dados, dict):
        return None
    d = dict(r.dados)
    d["modelo"] = r.modelo
    return d


def montar(tipo: str, itens: dict[str, Path], processos: dict, extra: dict | None = None) -> Path:
    """Copia `itens` ({caminho no lote: origem local}) para um lote novo e grava o MANIFESTO."""
    lote = f"{tipo}-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
    base = LOTES / lote
    arquivos: dict[str, str] = {}
    for rel, origem in itens.items():
        destino = base / rel
        if origem.is_dir():
            shutil.copytree(origem, destino)
            for f in destino.rglob("*"):
                if f.is_file():
                    arquivos[str(f.relative_to(base))] = _md5(f)
        elif origem.exists():
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origem, destino)
            arquivos[rel] = _md5(destino)
    man = {"lote": lote, "tipo": tipo, "origem": os.uname().nodename, "criado_em": time.strftime("%F %T"),
           "arquivos": arquivos, "processos": processos, **(extra or {})}
    base.mkdir(parents=True, exist_ok=True)
    (base / "MANIFESTO.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    return base


def enviar(base: Path) -> dict | None:
    """rsync do lote para a VM-1 + importação conferida lá. None = não chegou (o lote fica para reenvio)."""
    destino = f"{VM1}:{VM1_JFN}/data/vm2_entrega/{base.name}/"
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", VM1,
                        f"mkdir -p {VM1_JFN}/data/vm2_entrega"], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        return None
    r = subprocess.run(["rsync", "-a", "--partial", f"{base}/", destino], capture_output=True, text=True,
                       timeout=3600)
    if r.returncode != 0:
        return None
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", VM1,
                        f"cd {VM1_JFN} && PYTHONPATH=. nice -n 10 .venv/bin/python -m tools.vm2_conferencia "
                        f"importar {base.name}"], capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        return None
    try:
        res = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None
    shutil.rmtree(base, ignore_errors=True)       # conferido lá (aprovado OU em quarentena): sai daqui
    return res


def reenviar_pendentes() -> list[dict]:
    out = []
    for base in sorted(LOTES.glob("*")) if LOTES.is_dir() else []:
        if base.is_dir() and (base / "MANIFESTO.json").exists():
            res = enviar(base)
            if res is None:
                break
            out.append(res)
    return out
