# -*- coding: utf-8 -*-
"""Chave do CONTRATO: `(orgao, numero_normalizado, exercicio)` (plano mestre v2, §3.1).

`numero_contrato` é a normalização única do número "N/AAAA" (paridade em `tests/test_dominio_contrato_id.py`
contra `padroes._aditivos_comum.norm_contrato`, `sei.instrumento_assinatura.num_contrato` e
`sei.reuso_documento_execucao.contratos_citados`):
- zeros à esquerda do número saem ("016/2023" e "16/2023" são o MESMO contrato — 13 dos 29 falsos positivos do I5);
- ano com 2 dígitos vira "20AA" (como `norm_contrato`; `num_contrato` o deixava com 2 — divergência documentada);
- espaços em volta da barra saem; o que não é "dígitos/dígitos" devolve `None` (`norm_contrato` levantava erro).

`orgao` não é inventado aqui: vem do chamador (código da UG, CNPJ ou sigla) e só é aparado — código só de dígitos
fica só com os dígitos (UG `080001`, CNPJ sem pontuação). Contrato com ano no número diferente do `exercicio`
informado → `None` (as duas fontes discordam; nenhuma das duas vence calada).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from compliance_agent.dominio.digitos import so_digitos
from compliance_agent.dominio.processo_id import analisar

_RX_NUM = re.compile(r"^\s*0*(\d{1,6})\s*(?:/\s*(\d{4}|\d{2}))?\s*$")


@dataclass(frozen=True)
class ContratoId:
    orgao: str
    numero_normalizado: str   # "N/AAAA"
    exercicio: int

    @property
    def chave(self) -> tuple[str, str, int]:
        return (self.orgao, self.numero_normalizado, self.exercicio)


def numero_contrato(texto, exercicio: int | None = None) -> str | None:
    """'034/2026' → '34/2026'; '34/26' → '34/2026'; '34' com `exercicio=2026` → '34/2026'. Senão `None`."""
    m = _RX_NUM.match(str(texto or ""))
    if not m:
        return None
    n, ano = m.groups()
    if ano is None:
        if exercicio is None:
            return None
        ano = str(int(exercicio))
    elif len(ano) == 2:
        ano = "20" + ano
    if exercicio is not None and int(ano) != int(exercicio):
        return None
    return f"{int(n)}/{ano}"


def normalizar_orgao(orgao) -> str:
    s = re.sub(r"\s+", " ", str(orgao or "")).strip().upper()
    return so_digitos(s) if re.fullmatch(r"[\d.\-/ ]+", s or "x") else s


def contrato_id(orgao, numero, exercicio: int | None = None) -> ContratoId | None:
    """A chave do contrato; `None` se faltar órgão ou o número não for reconhecido."""
    org = normalizar_orgao(orgao)
    num = numero_contrato(numero, exercicio)
    if not org or not num:
        return None
    return ContratoId(org, num, int(num.split("/")[1]))


# ── espelho TCE-RJ: o mesmo ajuste publicado mais de uma vez ────────────────────────────────────────────────────────
# O espelho (`contratos_tcerj`, `compras_diretas_tcerj`) não traz o número "N/AAAA" do contrato: `num_contratacao` é o
# id do REGISTRO no TCE (um por republicação). O mesmo ajuste reaparece com outra grafia do processo e outro registro
# — medido no snapshot de 24/11/2026: `SEI-330003/000613/2026`, `SEI330003/000613/2026` e `330003/000613/2026`, EMOP,
# mesmo CNPJ, R$ 48.625.672,99 cada (um cancelado). A chave do espelho é então (órgão, processo canônico com o sufixo
# de desdobramento, LOTE quando o registro o declara, CNPJ, valor ao centavo) — o processo pela chave única de
# `dominio.processo_id`. Processo que a chave canônica não reconhece não casa com nada (fica como veio: nunca se funde
# por palpite). Medido no mesmo snapshot: `LOTE1-520002/001480/2026` e `LOTE3-520002/001480/2026` (mesmo valor) são
# lotes DIFERENTES do mesmo processo — o lote entra na chave.
_RX_LOTE = re.compile(r"\bLOTE\s*0*(\d{1,3})", re.I)
def chave_espelho_tcerj(unidade, processo, *, cnpj=None, valor=None) -> str | None:
    """Chave do ajuste no espelho do TCE-RJ; `None` se faltar órgão ou o processo não for reconhecido.
    `cnpj`/`valor` entram quando informados (contratos_tcerj: um processo pode ter vários contratos)."""
    org = normalizar_orgao(unidade)
    p = analisar(processo)
    if not org or p is None:
        return None
    lote = _RX_LOTE.search(str(processo or ""))
    partes = [org, p.canonica + (f"-{p.sufixo}" if p.sufixo else "") + (f"-LOTE{int(lote[1])}" if lote else "")]
    if cnpj is not None:
        partes.append(so_digitos(cnpj))
    if valor is not None:
        try:
            partes.append(f"{round(float(valor), 2):.2f}")
        except (TypeError, ValueError):
            return None
    return "|".join(partes)


def deduplicar(linhas, chave, ordem, valor=None) -> tuple[list, dict]:
    """Uma linha por chave: fica a PRIMEIRA pela `ordem` (chamável → tupla ordenável); linha com chave `None` fica
    sempre (não se funde). Devolve (linhas mantidas na ordem original, medida {grupos, removidas, valor_removido,
    exemplos[≤10]}) — `valor` (chamável) soma o que saiu."""
    linhas = list(linhas)
    por: dict = {}
    for i, r in enumerate(linhas):
        k = chave(r)
        if k is not None:
            por.setdefault(k, []).append(i)
    fora: set[int] = set()
    exemplos, removido = [], 0.0
    for k, idx in por.items():
        if len(idx) < 2:
            continue
        idx = sorted(idx, key=lambda i: ordem(linhas[i]))
        fora.update(idx[1:])
        if valor is not None:
            removido += sum(float(valor(linhas[i]) or 0) for i in idx[1:])
        if len(exemplos) < 10:
            exemplos.append({"chave": k, "linhas": len(idx)})
    grupos = sum(1 for idx in por.values() if len(idx) > 1)
    return ([r for i, r in enumerate(linhas) if i not in fora],
            {"grupos": grupos, "removidas": len(fora), "valor_removido": round(removido, 2), "exemplos": exemplos})
