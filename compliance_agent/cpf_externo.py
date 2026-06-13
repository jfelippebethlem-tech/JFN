#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cpf_externo — desmasca o CPF de um sócio do QSA cruzando a máscara pública com uma fonte EXTERNA
nome↔CPF (Receita/situação-cadastral, Justiça do Trabalho/judicial). Quebra a parede dos ~96% que o
corpus interno não resolve. **DORMENTE e GATED**: roda só por ALVO, disparado pelo dono — nunca em sweep.

Como funciona (motor já existente em `resolucao_cpf`):
  1. `gerar_cpfs_da_mascara(doc)` → os 1.000 CPFs válidos possíveis (posições 1-3 × 6 do meio × 2 DVs).
     Se a **fusão folha×QSA** já deu as posições 3-9 (`cpf_pos3a9`), o espaço cai p/ ~100 (menos consultas).
  2. para cada candidato, a FONTE EXTERNA devolve o NOME → casa com o nome do sócio (anti-homônimo).
  3. `confirmar_cpf(nome, candidato, doc)` valida o middle6 contra a máscara → veredito 1:1 honesto.

Dois MODOS de fonte (provider):
  • `cpf→nome` (ex.: situação-cadastral / Receita): consulta cada candidato (até `max_consultas`).
  • `nome→cpf` (ex.: Escavador/Jusbrasil/PJe-TRT — registros judiciais com CPF completo): UMA busca por
    nome devolve candidato(s); `confirmar_cpf` filtra pela máscara. Mais limpo quando a pessoa tem processo.

HONESTIDADE/LGPD (regra-mãe): CPF resolvido é uso INTERNO (consulta de fontes), produto mascara; resultado
sem confirmação 1:1 = INDISPONÍVEL (nunca chute); o provider degrada honesto (captcha/bloqueio/sem rede →
ok=False, motivo). ToS: consultar respeitando o termo de cada site; volume baixo (por alvo), com pausa.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Protocol

from compliance_agent.resolucao_cpf import (
    _digitos,
    _dv_cpf,
    _norm,
    confirmar_cpf,
    gerar_cpfs_da_mascara,
    middle6,
)


# ───────────────────────────── providers (interface) ─────────────────────────────
class ProviderCpfNome(Protocol):
    """Fonte que, dado um CPF completo, devolve o nome do titular (modo cpf→nome)."""
    nome: str

    def nome_por_cpf(self, cpf: str) -> dict:
        """Retorna {ok: bool, nome: str, motivo: str}. ok=False = indisponível/bloqueio (honesto)."""
        ...


class ProviderNomeCpf(Protocol):
    """Fonte que, dado um nome, devolve CPF(s) candidato(s) (modo nome→cpf, ex.: judicial)."""
    nome: str

    def cpfs_por_nome(self, nome: str) -> dict:
        """Retorna {ok: bool, cpfs: list[str], motivo: str}."""
        ...


def candidatos_estreitados(doc_mascarado: str, cpf_pos3a9: str | None = None) -> list[str]:
    """Candidatos válidos da máscara, ESTREITADOS pela fusão folha×QSA quando disponível (pos.3-9 conhecidas
    → varia só posições 1-2 = ~100 candidatos em vez de 1.000)."""
    p = _digitos(cpf_pos3a9 or "")
    if len(p) == 7 and middle6(doc_mascarado) and p[1:7] == middle6(doc_mascarado):
        # p = posições 3..9 ; falta 1-2 (00..99) ; DV calculado
        out = []
        for ini2 in range(100):
            base9 = f"{ini2:02d}{p}"          # pos1-2 + pos3-9
            out.append(base9 + _dv_cpf(base9))
        return out
    return gerar_cpfs_da_mascara(doc_mascarado)


# ───────────────────────────── orquestração (motor) ─────────────────────────────
@dataclass
class Resultado:
    resolvido: bool
    cpf: str
    fonte: str
    consultas: int
    motivo: str


def desmascarar_cpf_nome(nome: str, doc_mascarado: str, provider: ProviderCpfNome, *,
                         cpf_pos3a9: str | None = None, max_consultas: int = 0,
                         pausa: float = 1.0, log: Callable[[str], None] | None = None) -> Resultado:
    """Modo cpf→nome: itera os candidatos consultando o provider até o NOME bater + confirmar 1:1.

    `max_consultas=0` = sem teto (cuidado: até 1.000); use o teto + a fusão p/ poucos hits. Degrada honesto.
    """
    nome_n = _norm(nome)
    cands = candidatos_estreitados(doc_mascarado, cpf_pos3a9)
    if not cands:
        return Resultado(False, "", provider.nome, 0, "sem máscara válida (6 díg do meio)")
    teto = max_consultas or len(cands)
    consultas = 0
    for cpf in cands:
        if consultas >= teto:
            return Resultado(False, "", provider.nome, consultas,
                             f"teto de {teto} consultas atingido sem match (espaço={len(cands)})")
        r = provider.nome_por_cpf(cpf)
        consultas += 1
        if log:
            log(f"  [{consultas}/{teto}] {cpf}: {'ok ' + r.get('nome','') if r.get('ok') else 'x ' + r.get('motivo','')}")
        if not r.get("ok"):
            if "captcha" in (r.get("motivo") or "").lower() or "bloque" in (r.get("motivo") or "").lower():
                return Resultado(False, "", provider.nome, consultas,
                                 f"provider bloqueado ({r.get('motivo')}) — INDISPONÍVEL")
            time.sleep(pausa)
            continue
        nm = _norm(r.get("nome", ""))
        if nome_n and nm and (nome_n == nm or (len(nome_n) >= 6 and nome_n in nm) or nm in nome_n):
            conf = confirmar_cpf(nome, cpf, doc_mascarado)
            if conf.get("confirmado"):
                return Resultado(True, cpf, provider.nome, consultas,
                                 "nome confere na fonte externa + middle6 bate a máscara (1:1)")
        time.sleep(pausa)
    return Resultado(False, "", provider.nome, consultas, "nenhum candidato confere o nome na fonte")


def desmascarar_nome_cpf(nome: str, doc_mascarado: str, provider: ProviderNomeCpf,
                         log: Callable[[str], None] | None = None) -> Resultado:
    """Modo nome→cpf (judicial): UMA busca por nome → candidato(s); confirma cada um pela máscara (1:1)."""
    r = provider.cpfs_por_nome(nome)
    if not r.get("ok"):
        return Resultado(False, "", provider.nome, 1, f"fonte indisponível: {r.get('motivo', '')}")
    for cpf in r.get("cpfs", []):
        conf = confirmar_cpf(nome, cpf, doc_mascarado)
        if log:
            log(f"  candidato {cpf}: {'CONFIRMA' if conf.get('confirmado') else conf.get('motivo','')}")
        if conf.get("confirmado"):
            return Resultado(True, _digitos(cpf), provider.nome, 1,
                             "CPF de registro judicial confere a máscara do QSA (1:1, anti-homônimo)")
    return Resultado(False, "", provider.nome, 1, "nenhum CPF da fonte bate a máscara (homônimo/sem registro)")


# ───────────────────────────── provider de referência (situação-cadastral) ─────────────────────────────
class ProviderSituacaoCadastral:
    """Provider cpf→nome via situacao-cadastral.com (espelho de situação cadastral da Receita; método do
    osint-brazuca). **Best-effort e honesto**: muitos espelhos têm Cloudflare/captcha → retorna ok=False com
    motivo (NÃO inventa nome). Respeitar o ToS do site; volume baixo. Sem rede/bloqueio → INDISPONÍVEL."""
    nome = "situacao_cadastral"

    def __init__(self, base: str = "https://www.situacao-cadastral.com", timeout: float = 20.0):
        self.base = base.rstrip("/")
        self.timeout = timeout

    def nome_por_cpf(self, cpf: str) -> dict:
        import re
        try:
            import httpx
        except Exception:
            return {"ok": False, "nome": "", "motivo": "httpx ausente"}
        try:
            r = httpx.get(f"{self.base}/consulta/{_digitos(cpf)}",
                          headers={"User-Agent": "Mozilla/5.0"}, timeout=self.timeout,
                          follow_redirects=True)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "nome": "", "motivo": f"rede: {str(e)[:50]}"}
        if r.status_code in (403, 429) or "captcha" in r.text.lower() or "cf-challenge" in r.text.lower():
            return {"ok": False, "nome": "", "motivo": f"bloqueio/captcha (HTTP {r.status_code})"}
        if r.status_code != 200:
            return {"ok": False, "nome": "", "motivo": f"HTTP {r.status_code}"}
        m = re.search(r'class="dados nome"[^>]*>([^<]+)<', r.text)
        if m:
            return {"ok": True, "nome": m.group(1).strip(), "motivo": ""}
        return {"ok": False, "nome": "", "motivo": "nome não encontrado na resposta"}
