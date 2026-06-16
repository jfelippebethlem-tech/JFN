#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""anexos_remotes — política GENÉRICA de STORAGE SOMADO (R2→B2) para ANEXOS grandes.

Generaliza a política já provada da fachada (`fachada_remotes`) para QUALQUER anexo grande que o
ecossistema produz e que não cabe/convém manter local na VM: dossiês SEI volumosos, PDFs/recortes da
PESQUISA do Lex (Fase 5), scans de documentos. **Reusa** a lista de remotes, os tetos e o
`SelecionadorRemote` da fachada — FONTE ÚNICA, sem duplicar regra de transbordo.

DESIGN (idêntico à fachada — leia `fachada_remotes`):
  • **R2 = primário** (egress zero) → transborda pro **B2** ao chegar perto do teto (margem 9,5GB).
  • **Cada anexo em 1 bucket só** (não-mirror); a LOCALIZAÇÃO COMPLETA `remote:bucket/objeto` é o ponteiro
    canônico — guardado numa COLUNA da tabela do dono do anexo (ex.: `sei_arvore.anexo_b2`,
    `lex_pesquisa.fontes_b2`), exatamente como `verificacao_sede.visual_img_b2`.
  • **Leitura** = `rclone cat` no caminho EXATO gravado (NUNCA listar o bucket às cegas).
  • Degrada HONESTO: se os dois remotes estão cheios ou o rclone falha, retorna None — o chamador loga e
    segue (mantém o arquivo local; nunca derruba nada, nunca inventa ponteiro).

Os objetos de anexo moram sob o prefixo `anexos/<categoria>/...` (separado de `fachadas/`), p/ não
colidir com as fotos. Override do prefixo por env `ANEXOS_PREFIXO`.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from compliance_agent import fachada_remotes as _fr

# Prefixo (pasta lógica) dos anexos dentro de cada bucket — separado das fachadas.
PREFIXO = os.environ.get("ANEXOS_PREFIXO", "anexos")


def _safe(nome: str) -> str:
    """Normaliza um nome p/ caminho de objeto seguro (sem barras/espaços/acentos problemáticos)."""
    return re.sub(r"[^0-9A-Za-z._-]", "_", (nome or "").strip()) or "sem_nome"


def objeto_anexo(categoria: str, nome: str, ext: str) -> str:
    """Caminho do objeto dentro do bucket (sem `remote:bucket`): 'anexos/<categoria>/<nome>.<ext>'.
    Ex.: objeto_anexo('dossies', 'SEI-330003_002534_2024', 'txt') → 'anexos/dossies/SEI-330003_002534_2024.txt'."""
    cat = _safe(categoria)
    nome_s = _safe(nome)
    ext_s = _safe(ext).lstrip(".") or "bin"
    return f"{PREFIXO}/{cat}/{nome_s}.{ext_s}"


def subir_anexo(local_path: str | Path, objeto_rel: str, *,
                sel: "_fr.SelecionadorRemote | None" = None) -> str | None:
    """Sobe um arquivo LOCAL p/ o remote escolhido (R2→B2, respeitando o teto) e devolve a LOCALIZAÇÃO
    COMPLETA `remote:bucket/objeto_rel` (o ponteiro p/ gravar na coluna). None se: arquivo inexistente,
    todos os remotes cheios, ou `rclone copyto` falhar (degrada honesto). Passe um `SelecionadorRemote`
    compartilhado p/ um run com muitos anexos (1 `rclone size` por remote em vez de por arquivo)."""
    p = Path(local_path)
    if not p.exists() or not p.is_file():
        return None
    try:
        tamanho = p.stat().st_size
    except OSError:
        return None
    sel = sel or _fr.SelecionadorRemote()
    destino_rb = sel.escolher(tamanho)        # "remote:bucket" ou None se todos cheios
    if not destino_rb:
        return None
    destino = f"{destino_rb}/{objeto_rel}"     # remote:bucket/anexos/...
    try:
        # copyto copia p/ o caminho EXATO do objeto (copy usaria o basename do arquivo local).
        r = subprocess.run([_fr.rclone_bin(), "copyto", str(p), destino],
                           capture_output=True, text=True, timeout=300)
    except Exception:  # noqa: BLE001 — rclone ausente/timeout: degrada honesto
        return None
    if r.returncode != 0:
        return None
    sel.confirmar(destino_rb, tamanho)         # contabiliza no run p/ a próxima escolha
    return destino


def ler_anexo(loc: str) -> bytes | None:
    """Lê os BYTES de um anexo do caminho EXATO gravado (`remote:bucket/objeto`) via `rclone cat`. None se
    a localização é incompleta/legada (sem `remote:`) ou o rclone falha. NUNCA lista o bucket às cegas."""
    if not _fr.parse_localizacao(loc):
        return None
    try:
        r = subprocess.run([_fr.rclone_bin(), "cat", loc.strip()],
                           capture_output=True, timeout=300)
    except Exception:  # noqa: BLE001
        return None
    if r.returncode != 0:
        return None
    return r.stdout or b""


def existe_anexo(loc: str) -> bool:
    """True se o objeto existe no remote (checa o caminho EXATO via `rclone lsf`). Conservador: na dúvida
    (loc incompleta/erro) retorna False."""
    pl = _fr.parse_localizacao(loc)
    if not pl:
        return False
    remote, bucket, objeto = pl
    try:
        r = subprocess.run([_fr.rclone_bin(), "lsf", f"{remote}:{bucket}/{objeto}"],
                           capture_output=True, text=True, timeout=60)
    except Exception:  # noqa: BLE001
        return False
    return r.returncode == 0 and bool((r.stdout or "").strip())
