#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fachada_remotes — política de STORAGE SOMADO (não-mirror) das fotos de fachada.

O dono usa **Cloudflare R2 + Backblaze B2 só para SOMAR capacidade** (10GB + 10GB), distribuindo
as fotos de fachada. **NÃO é redundância/mirror** — **cada foto vive em UM bucket só, nunca
duplicada**. ⚠ O R2 tem **teto rígido de 10GB**: o sistema NUNCA pode deixar o R2 passar disso
(margem segura 9,5GB). O B2 tem a mesma margem de proteção.

DESIGN:
- **R2 = primário** (egress zero): enche o R2 enquanto `uso_r2 + tamanho_foto < teto_r2`; ao chegar
  perto do teto, **transborda pro B2** (mesma regra). Se os dois estiverem cheios → degrada honesto
  (o chamador loga e segue; NÃO derruba nada).
- **Cada foto em 1 bucket** (sem duplicar). A coluna `verificacao_sede.visual_img_b2` guarda a
  **localização COMPLETA** no formato `remote:bucket/objeto`, ex.:
  `r2:jorgefelippe/fachadas/<cnpj>.jpg` OU `b2:jfn-backup-jorge/fachadas/<cnpj>.jpg`.
- **Leitura** (relatórios): lê do local EXATO gravado (um `rclone cat` no `remote:bucket/objeto`).
  SEM failover/duplicação.

Este módulo é a FONTE ÚNICA da lista de remotes, dos tetos e do parse — usado por
`tools.fachada_b2_sync` (escrita) E por `reporting.inteligencia` (leitura).

Eficiência de cota/CPU: `escolher_remote()` consulta `rclone size` **uma vez por remote por run**
(cacheado em memória) e **acumula em RAM os bytes subidos no run** — não chama `size` por foto.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

# rclone binário (override por env p/ teste/portabilidade).
_RCLONE_BIN = os.environ.get("RCLONE_BIN") or str(Path.home() / ".local" / "bin" / "rclone")

# Prefixo (pasta lógica) dos objetos de fachada dentro de cada bucket.
PREFIXO = os.environ.get("FACHADA_PREFIXO", "fachadas")

# Tetos por remote (margem SEGURA abaixo do limite real de 10GB). Override por env.
_GB = 1024 ** 3
_CAP_R2_GB = float(os.environ.get("FACHADA_R2_CAP_GB", "9.5"))
_CAP_B2_GB = float(os.environ.get("FACHADA_B2_CAP_GB", "9.5"))

# Remotes do rclone (já configurados/testados pelo dono). Override por env.
_R2_REMOTE = os.environ.get("FACHADA_R2_REMOTE", "r2")
_R2_BUCKET = os.environ.get("FACHADA_R2_BUCKET", "jorgefelippe")
_B2_REMOTE = os.environ.get("FACHADA_B2_REMOTE", "b2")
_B2_BUCKET = os.environ.get("FACHADA_B2_BUCKET", "jfn-backup-jorge")

# ORDEM DE PREENCHIMENTO: R2 primeiro (egress zero), B2 como transbordo. Cada item:
#   (remote, bucket, teto_bytes).
REMOTES: list[tuple[str, str, int]] = [
    (_R2_REMOTE, _R2_BUCKET, int(_CAP_R2_GB * _GB)),
    (_B2_REMOTE, _B2_BUCKET, int(_CAP_B2_GB * _GB)),
]

# O remote PRIMÁRIO (onde mora o índice/metadado pequeno: _index.csv/_index.html).
INDEX_REMOTE, INDEX_BUCKET = _R2_REMOTE, _R2_BUCKET


def rclone_bin() -> str:
    return _RCLONE_BIN


def _uso_bytes(remote: str, bucket: str) -> int | None:
    """Tamanho ATUAL (bytes) ocupado no `remote:bucket` via `rclone size --json`. None se falhar
    (o chamador trata como 'desconhecido' = conservador: não usa esse remote)."""
    try:
        r = subprocess.run([_RCLONE_BIN, "size", f"{remote}:{bucket}", "--json"],
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0 or not r.stdout.strip():
            return None
        return int(json.loads(r.stdout).get("bytes", 0))
    except Exception:  # noqa: BLE001
        return None


class SelecionadorRemote:
    """Escolhe o remote de destino respeitando o teto de cada um, com UMA chamada `rclone size` por
    remote por run + acúmulo em RAM dos bytes subidos no run (não chama size por foto).

    Uso:
        sel = SelecionadorRemote()
        destino = sel.escolher(tamanho_bytes)   # "remote:bucket" ou None se todos cheios
        # ... subiu a foto com sucesso ...
        sel.confirmar(destino, tamanho_bytes)    # contabiliza no run p/ a próxima escolha
    """

    def __init__(self) -> None:
        # uso[(remote,bucket)] = bytes já ocupados (size inicial + subidos no run). None = falha no size.
        self._uso: dict[tuple[str, str], int | None] = {}

    def _uso_atual(self, remote: str, bucket: str) -> int | None:
        chave = (remote, bucket)
        if chave not in self._uso:
            self._uso[chave] = _uso_bytes(remote, bucket)
        return self._uso[chave]

    def escolher(self, tamanho_bytes: int) -> str | None:
        """Devolve o "remote:bucket" do PRIMEIRO remote (na ordem R2→B2) onde a foto cabe sob o teto.
        None se nenhum couber (todos cheios) OU se o size de TODOS falhar (conservador — não estoura).
        """
        for remote, bucket, teto in REMOTES:
            uso = self._uso_atual(remote, bucket)
            if uso is None:
                # size falhou p/ este remote: não arrisca estourar o teto — pula p/ o próximo.
                continue
            if uso + max(0, int(tamanho_bytes)) < teto:
                return f"{remote}:{bucket}"
        return None

    def confirmar(self, destino: str, tamanho_bytes: int) -> None:
        """Contabiliza no run os bytes recém-subidos a `destino` ('remote:bucket') p/ a próxima escolha
        (evita chamar `rclone size` por foto)."""
        remote, bucket = parse_remote_bucket(destino)
        chave = (remote, bucket)
        atual = self._uso.get(chave)
        if atual is not None:
            self._uso[chave] = atual + max(0, int(tamanho_bytes))


def escolher_remote(tamanho_bytes: int) -> str | None:
    """Conveniência sem estado (consulta `rclone size` na hora). Para um run com MUITAS fotos, prefira
    `SelecionadorRemote` (uma chamada de size por remote + acúmulo em RAM). Devolve "remote:bucket" ou
    None se todos cheios."""
    return SelecionadorRemote().escolher(tamanho_bytes)


def parse_remote_bucket(loc: str) -> tuple[str, str]:
    """De 'remote:bucket' ou 'remote:bucket/objeto' → (remote, bucket). Ex.:
    'r2:jorgefelippe/fachadas/x.jpg' → ('r2','jorgefelippe')."""
    loc = (loc or "").strip()
    remote, _, resto = loc.partition(":")
    bucket = resto.split("/", 1)[0]
    return remote, bucket


def parse_localizacao(loc: str) -> tuple[str, str, str] | None:
    """De uma localização COMPLETA 'remote:bucket/objeto' → (remote, bucket, objeto). None se não tiver
    objeto ou estiver malformada. Tolera o legado 'fachadas/<cnpj>.jpg' (sem remote:) devolvendo None
    (o chamador trata como 'sem localização completa' e degrada honesto)."""
    loc = (loc or "").strip()
    if not loc or ":" not in loc:
        return None
    remote, _, resto = loc.partition(":")
    bucket, sep, objeto = resto.partition("/")
    if not remote or not bucket or not sep or not objeto:
        return None
    return remote, bucket, objeto


def objeto_de(cnpj_safe: str, ext: str) -> str:
    """Caminho do objeto dentro do bucket (sem remote:bucket): 'fachadas/<cnpj>.<ext>'."""
    return f"{PREFIXO}/{cnpj_safe}.{ext}"
