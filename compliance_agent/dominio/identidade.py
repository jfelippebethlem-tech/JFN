# -*- coding: utf-8 -*-
"""Identidade CONSERVADORA de pessoa física/jurídica (plano mestre v2, §4.7 item 7 — O4.13).

Função pura: sem I/O, sem ORM, sem LLM. Dígitos e DV vêm de `dominio.digitos` (fonte única, nada duplicado aqui).

    resolver(a, b) -> Resolucao(match_level, motivo, campos_usados)
    sustenta_grave(res) -> bool        só `forte`

`a` e `b` são mapeamentos com as chaves (todas opcionais): `cpf`, `cnpj`, `matricula`, `orgao`, `nome` (ou
`razao_social`), `nascimento` (ou `data_nascimento`) e `municipio`.

Níveis, na ordem em que são decididos:
  divergente     documento completo com DV válido DIFERENTE nos dois lados (CPF ou CNPJ), raiz de CNPJ diferente,
                 ou CPF mascarado/completo com dígitos visíveis incompatíveis — prova de que NÃO é a mesma pessoa;
  forte          CNPJ completo com DV válido igual; CPF completo com DV válido igual; matrícula + órgão iguais;
  parcial        CPF mascarado compatível (≥ 5 posições visíveis em comum, todas iguais) + nome normalizado igual;
                 ou mesma raiz de CNPJ (8 dígitos) + nome igual. NUNCA sustenta grave;
  probabilistico nome igual + atributo fraco compatível (data de nascimento, mesmo que parcial; município);
  homonimo       só o nome bate;
  indeterminado  nada para comparar (ou só documento sem nome).
Documento com DV inválido é ignorado (não conta como igual nem como diferente) e o motivo diz isso.

Máscaras de CPF aceitas, pela POSIÇÃO dos dígitos visíveis: `***.123.456-**` (PAD-04, posições 4–9) e
`XX123456XXX` (folha, posições 3–8); `X`, `x`, `*` e `•` marcam dígito oculto. Formatos diferentes se comparam
pelas posições em comum (5 entre os dois acima).

`motivo` e `repr(Resolucao)` nunca contêm CPF: o texto é fixo e não cita dígitos.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Mapping

from compliance_agent.dominio.digitos import cnpj_valido, cpf_valido, so_digitos

NIVEIS = ("forte", "parcial", "probabilistico", "homonimo", "divergente", "indeterminado")
MIN_POSICOES_MASCARA = 5

_OCULTO = "Xx*•"
_PREPOSICOES = frozenset({"DE", "DA", "DO", "DOS", "DAS", "E"})
_RE_PONTUACAO_DOC = re.compile(r"[.\-/\s]")


@dataclass(frozen=True)
class Resolucao:
    match_level: str
    motivo: str
    campos_usados: tuple[str, ...] = ()


# ── normalização ─────────────────────────────────────────────────────────────────────────────────────
def normalizar_nome(nome) -> str:
    """Sem acento, caixa alta, sem pontuação, sem preposições (de/da/do/dos/das/e), espaços colapsados."""
    s = unicodedata.normalize("NFKD", str(nome or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).upper()
    s = re.sub(r"[^0-9A-Z]+", " ", s)
    return " ".join(p for p in s.split() if p not in _PREPOSICOES)


def _padrao_cpf(v) -> str | None:
    """CPF como 11 posições (dígito ou '?'); `None` se não tiver forma de CPF."""
    s = _RE_PONTUACAO_DOC.sub("", str(v or ""))
    if len(s) != 11 or any(not (c.isdigit() or c in _OCULTO) for c in s):
        return None
    return "".join(c if c.isdigit() else "?" for c in s)


def cpf_mascarado(v) -> bool:
    """True se `v` é um CPF com ao menos um dígito oculto (`XX123456XXX`, `***.123.456-**`…)."""
    p = _padrao_cpf(v)
    return p is not None and "?" in p


def _cpf(reg: Mapping) -> tuple[str, str | None]:
    """('completo'|'mascarado'|'invalido'|'', padrão). Completo = 11 dígitos com DV válido."""
    bruto = reg.get("cpf")
    if not bruto:
        return "", None
    p = _padrao_cpf(bruto)
    if p is None:
        return "invalido", None
    if "?" in p:
        return "mascarado", p
    return ("completo", p) if cpf_valido(p) else ("invalido", None)


def _cnpj(reg: Mapping) -> tuple[str, str]:
    """('completo'|'raiz'|'invalido'|'', dígitos). Raiz = 8 dígitos."""
    d = so_digitos(reg.get("cnpj"))
    if not d:
        return "", ""
    if len(d) == 14:
        return ("completo", d) if cnpj_valido(d) else ("invalido", "")
    if len(d) == 8:
        return "raiz", d
    return "invalido", ""


def _nascimento(v) -> tuple[str | None, str | None, str | None] | None:
    """(ano, mês, dia) com None no que faltar; aceita AAAA, MM/AAAA, DD/MM/AAAA e AAAA-MM-DD."""
    partes = re.findall(r"\d+", str(v or ""))
    if not partes:
        return None
    if len(partes[0]) == 4:                          # AAAA[-MM[-DD]]
        ano, resto = partes[0], partes[1:]
        mes = resto[0].zfill(2) if resto else None
        dia = resto[1].zfill(2) if len(resto) > 1 else None
    else:                                            # [DD/]MM/AAAA
        if len(partes[-1]) != 4:
            return None
        ano = partes[-1]
        mes = partes[-2].zfill(2) if len(partes) >= 2 else None
        dia = partes[-3].zfill(2) if len(partes) >= 3 else None
    return ano, mes, dia


def _nascimento_compativel(x, y) -> bool:
    a, b = _nascimento(x), _nascimento(y)
    if not a or not b:
        return False
    return all(p == q for p, q in zip(a, b) if p is not None and q is not None)


def _cpf_compativel(p: str, q: str) -> tuple[bool, int]:
    comuns = [(x, y) for x, y in zip(p, q) if x != "?" and y != "?"]
    return all(x == y for x, y in comuns), len(comuns)


def _get(reg: Mapping, *chaves):
    for k in chaves:
        v = reg.get(k)
        if v:
            return v
    return None


# ── resolução ────────────────────────────────────────────────────────────────────────────────────────
def resolver(a: Mapping | None, b: Mapping | None) -> Resolucao:
    """Nível de identidade entre os registros `a` e `b` (ver docstring do módulo)."""
    a, b = a or {}, b or {}
    obs: list[str] = []

    # documentos: divergência primeiro (qualquer documento que prova pessoas distintas vence)
    tcnpj_a, cnpj_a = _cnpj(a)
    tcnpj_b, cnpj_b = _cnpj(b)
    tcpf_a, cpf_a = _cpf(a)
    tcpf_b, cpf_b = _cpf(b)
    if "invalido" in (tcpf_a, tcpf_b):
        obs.append("CPF com DV inválido ou fora do formato ignorado")
    if "invalido" in (tcnpj_a, tcnpj_b):
        obs.append("CNPJ com DV inválido ou fora do formato ignorado")

    if tcnpj_a == tcnpj_b == "completo" and cnpj_a != cnpj_b and cnpj_a[:8] != cnpj_b[:8]:
        return Resolucao("divergente", "CNPJ completo diferente", ("cnpj",))
    if tcnpj_a in ("completo", "raiz") and tcnpj_b in ("completo", "raiz") and cnpj_a[:8] != cnpj_b[:8]:
        return Resolucao("divergente", "raiz de CNPJ diferente", ("cnpj",))
    if tcpf_a == tcpf_b == "completo" and cpf_a != cpf_b:
        return Resolucao("divergente", "CPF completo diferente", ("cpf",))
    cpf_compat, cpf_comuns = (False, 0)
    if cpf_a and cpf_b:
        cpf_compat, cpf_comuns = _cpf_compativel(cpf_a, cpf_b)
        if not cpf_compat:
            return Resolucao("divergente", "dígitos visíveis do CPF incompatíveis", ("cpf",))

    if tcnpj_a == tcnpj_b == "completo" and cnpj_a == cnpj_b:
        return Resolucao("forte", "CNPJ completo com DV válido igual", ("cnpj",))
    if tcpf_a == tcpf_b == "completo":
        return Resolucao("forte", "CPF completo com DV válido igual", ("cpf",))
    mat_a, mat_b = normalizar_nome(a.get("matricula")), normalizar_nome(b.get("matricula"))
    org_a, org_b = normalizar_nome(a.get("orgao")), normalizar_nome(b.get("orgao"))
    if mat_a and mat_a == mat_b and org_a and org_a == org_b:
        return Resolucao("forte", "matrícula e órgão iguais", ("matricula", "orgao"))

    nome_a = normalizar_nome(_get(a, "nome", "razao_social"))
    nome_b = normalizar_nome(_get(b, "nome", "razao_social"))
    nome_igual = bool(nome_a) and nome_a == nome_b
    sufixo = f" ({'; '.join(obs)})" if obs else ""

    if nome_igual and cpf_a and cpf_b and cpf_comuns >= MIN_POSICOES_MASCARA:
        return Resolucao("parcial", "CPF mascarado compatível + nome igual" + sufixo, ("cpf", "nome"))
    if nome_igual and tcnpj_a in ("completo", "raiz") and tcnpj_b in ("completo", "raiz"):
        return Resolucao("parcial", "mesma raiz de CNPJ + nome igual" + sufixo, ("cnpj", "nome"))
    if not nome_igual:
        if nome_a and nome_b:
            return Resolucao("indeterminado", "nomes diferentes sem documento conclusivo" + sufixo, ("nome",))
        return Resolucao("indeterminado", "sem documento conclusivo nem nome nos dois lados" + sufixo, ())

    fracos = []
    nasc_a, nasc_b = _get(a, "nascimento", "data_nascimento"), _get(b, "nascimento", "data_nascimento")
    if nasc_a and nasc_b and _nascimento_compativel(nasc_a, nasc_b):
        fracos.append("nascimento")
    mun_a, mun_b = normalizar_nome(a.get("municipio")), normalizar_nome(b.get("municipio"))
    if mun_a and mun_a == mun_b:
        fracos.append("municipio")
    if fracos:
        return Resolucao("probabilistico", "nome igual + " + " + ".join(fracos) + sufixo, ("nome", *fracos))
    return Resolucao("homonimo", "só o nome bate" + sufixo, ("nome",))


def sustenta_grave(res) -> bool:
    """Só identidade `forte` sustenta achado grave/alerta. Parcial, probabilístico e homônimo, nunca."""
    return isinstance(res, Resolucao) and res.match_level == "forte"
