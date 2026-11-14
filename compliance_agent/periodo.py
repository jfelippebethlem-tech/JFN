# -*- coding: utf-8 -*-
"""Organização por ANO e MÊS — o utilitário ÚNICO do painel.

Pedido do dono (13/11/2026): "coloca em tudo organização por ano e mês também. pagamentos e
contratações etc." — e a diretriz "não pode ter margem pra erro em nada". Daí as três regras que
este módulo existe para não deixar ninguém esquecer:

1. **A data vem em formatos diferentes por fonte.** A OB do SIAFE grava ``data_emissao`` como TEXTO
   ``DD/MM/AAAA`` (ordenar/agrupar o texto cru põe 01/12/2023 antes de 02/01/2016); o PNCP grava ISO
   ``AAAA-MM-DD``; o TCE-RJ grava ISO com ``T``. ``ano_mes`` e ``sql_ano_mes`` são o único lugar que
   converte — data que não casa com nenhum formato vira "sem data", contada à parte, nunca descartada.
2. **A soma fecha.** Dinheiro é somado em CENTAVOS inteiros (SQL e Python), e a quebra devolve os
   totais já fechados: Σ meses (+ sem mês) = ano; Σ anos = total datado; datado + sem data = geral.
   ``conferir`` verifica as três igualdades e é chamado pela rota antes de responder.
3. **INDISPONÍVEL ≠ 0.** Mês sem registro só vira ``zero`` se a fonte COBRE aquele mês (está dentro
   da janela declarada e o exercício foi coletado). Fora disso é ``indisponivel``. Fonte que só
   publica acumulado anual não inventa mês: os meses saem ``indisponivel`` e o ano carrega o total.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime

MESES = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")
MESES_LONGOS = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
                "setembro", "outubro", "novembro", "dezembro")

ANO_MIN, ANO_MAX = 1990, 2100

# Situação de um mês/ano na quebra. A ordem não importa; o vocabulário é FECHADO (o front pinta por ele).
OK, PARCIAL, ZERO, INDISPONIVEL = "ok", "parcial", "zero", "indisponivel"


class PeriodoInvalido(ValueError):
    """Parâmetro ``ano``/``mes`` fora do vocabulário — a rota responde 400, nunca lista vazia."""


def validar(ano=None, mes=None) -> tuple[int | None, int | None]:
    """``ano``/``mes`` vindos da URL → inteiros validados. Vazio = sem filtro (comportamento atual).

    Mês sem ano é RECUSADO: "março" de todos os anos somados é outro número, e ninguém que clica
    "mar" sem escolher o ano está pedindo isso.
    """
    def _int(v, nome):
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        try:
            return int(str(v).strip())
        except ValueError:
            raise PeriodoInvalido(f"{nome} '{v}' não é um número") from None
    a, m = _int(ano, "ano"), _int(mes, "mês")
    if a is not None and not ANO_MIN <= a <= ANO_MAX:
        raise PeriodoInvalido(f"ano {a} fora do intervalo {ANO_MIN}–{ANO_MAX}")
    if m is not None and not 1 <= m <= 12:
        raise PeriodoInvalido(f"mês {m} não existe (use 1 a 12)")
    if m is not None and a is None:
        raise PeriodoInvalido("o mês exige o ano — escolha o ano primeiro")
    return a, m


_RX_BR = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})")
_RX_ISO = re.compile(r"^\s*(\d{4})-(\d{1,2})(?:-(\d{1,2}))?")
_RX_COMP = re.compile(r"^\s*(\d{1,2})/(\d{4})\s*$")          # competência MM/AAAA


def ano_mes(valor) -> tuple[int, int] | None:
    """Qualquer data da casa → ``(ano, mês)``; irreconhecível → ``None`` (vai para "sem data").

    Aceita ``date``/``datetime``, ``DD/MM/AAAA`` (SIAFE), ``AAAA-MM-DD`` (PNCP), ``AAAA-MM-DDTHH…``
    (TCE-RJ), ``AAAA-MM-DD HH:MM`` (``created_at``) e competência ``MM/AAAA``.
    """
    if valor is None:
        return None
    if isinstance(valor, (date, datetime)):
        return valor.year, valor.month
    s = str(valor)
    for rx, ia, im in ((_RX_BR, 3, 2), (_RX_ISO, 1, 2), (_RX_COMP, 2, 1)):
        m = rx.match(s)
        if m:
            a, mm = int(m.group(ia)), int(m.group(im))
            if ANO_MIN <= a <= ANO_MAX and 1 <= mm <= 12:
                return a, mm
            return None
    return None


def sql_ano_mes(coluna: str, formato: str) -> tuple[str, str]:
    """Expressões SQLite ``(ano, mes)`` inteiras para a coluna — NULL quando o texto não casa.

    ``formato``: ``'br'`` (DD/MM/AAAA) ou ``'iso'`` (AAAA-MM-DD…). O GLOB recusa o que não tem o
    formato; mês 00/13+ passa no GLOB e é recusado em ``quebra`` (vira "sem data").
    """
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", coluna):
        raise ValueError(f"coluna inválida: {coluna!r}")
    if formato == "br":
        g = f"{coluna} GLOB '[0-3][0-9]/[01][0-9]/[12][0-9][0-9][0-9]*'"
        return (f"(CASE WHEN {g} THEN CAST(substr({coluna},7,4) AS INTEGER) END)",
                f"(CASE WHEN {g} THEN CAST(substr({coluna},4,2) AS INTEGER) END)")
    if formato == "iso":
        g = f"{coluna} GLOB '[12][0-9][0-9][0-9]-[01][0-9]*'"
        return (f"(CASE WHEN {g} THEN CAST(substr({coluna},1,4) AS INTEGER) END)",
                f"(CASE WHEN {g} THEN CAST(substr({coluna},6,2) AS INTEGER) END)")
    raise ValueError(f"formato de data desconhecido: {formato!r}")


def sql_centavos(expr: str) -> str:
    """SOMA em centavos inteiros — float somado em reais não fecha na 2ª casa em bilhões."""
    return f"COALESCE(SUM(CAST(ROUND(COALESCE({expr},0)*100) AS INTEGER)),0)"


def centavos(v) -> int:
    return int(round(float(v or 0) * 100))


def reais(c: int) -> float:
    return round(c / 100, 2)


def rotulo(ano: int | None, mes: int | None) -> str:
    if ano is None:
        return "todo o período"
    return f"{MESES[mes - 1]}/{ano}" if mes else str(ano)


@dataclass(frozen=True)
class Cobertura:
    """O que a fonte COBRE — é o que separa ``zero`` de ``indisponivel``.

    ``inicio``/``fim``: primeiro e último mês (ano, mês) cobertos. ``anos_sem_coleta``: exercícios
    dentro da janela que a casa não coletou. ``parcial_ate``: meses até este são cobertura parcial
    (registro existe mas a fonte não é completa ali — zero vira indisponível). ``mes_corrente``: o
    mês em curso, sempre parcial.
    """
    inicio: tuple[int, int]
    fim: tuple[int, int]
    anos_sem_coleta: frozenset = field(default_factory=frozenset)
    parcial_ate: tuple[int, int] | None = None
    anos_parciais: frozenset = field(default_factory=frozenset)
    mes_corrente: tuple[int, int] | None = None
    zero_possivel: bool = True       # False: a fonte SEMPRE tem registro no período (o Estado paga todo
    nota: str = ""                   # mês) — então ausência é lacuna de coleta, nunca zero

    def situacao(self, a: int, m: int | None, tem_dado: bool) -> str:
        if m is None:                                       # granularidade anual
            dentro = self.inicio[0] <= a <= self.fim[0] and a not in self.anos_sem_coleta
            if tem_dado:
                return PARCIAL if (a in self.anos_parciais or (self.mes_corrente and a == self.mes_corrente[0])
                                   or (self.parcial_ate and a <= self.parcial_ate[0])) else OK
            return ZERO if dentro and self.zero_possivel else INDISPONIVEL
        dentro = self.inicio <= (a, m) <= self.fim and a not in self.anos_sem_coleta
        parcial = (bool(self.parcial_ate and (a, m) <= self.parcial_ate) or (a, m) == self.mes_corrente
                   or a in self.anos_parciais)
        if tem_dado:
            return PARCIAL if parcial else OK
        return ZERO if dentro and not parcial and self.zero_possivel else INDISPONIVEL

    def como_dict(self) -> dict:
        return {"inicio": "%04d-%02d" % self.inicio, "fim": "%04d-%02d" % self.fim,
                "anos_sem_coleta": sorted(self.anos_sem_coleta), "anos_parciais": sorted(self.anos_parciais),
                "parcial_ate": ("%04d-%02d" % self.parcial_ate) if self.parcial_ate else None,
                "mes_corrente": ("%04d-%02d" % self.mes_corrente) if self.mes_corrente else None,
                "zero_possivel": self.zero_possivel, "nota": self.nota}


def _vazio(medidas):
    return {"n": 0, "c": {k: 0 for k in medidas}}


def _soma(dst, n, c):
    dst["n"] += n
    for k, v in c.items():
        dst["c"][k] += v


def _saida(b, medidas):
    return {"n": b["n"], "c": dict(b["c"]), "v": {k: reais(b["c"][k]) for k in medidas}}


def quebra(linhas, *, medidas: list[str], cobertura: Cobertura, granularidade: str = "mes") -> dict:
    """Agrega ``linhas`` = iter de ``(ano|None, mes|None, n, {medida: centavos})`` em ano → mês.

    ``granularidade='ano'``: a fonte só tem acumulado anual; os meses saem ``indisponivel`` e sem
    valor (``None``), e o ano carrega o total. Registro com ano inválido → ``sem_data``.
    """
    if granularidade not in ("mes", "ano"):
        raise ValueError(granularidade)
    anos: dict[int, dict] = {}
    sem_data = _vazio(medidas)
    for a, m, n, c in linhas:
        c = {k: int(c.get(k, 0) or 0) for k in medidas}
        if a is None or not ANO_MIN <= int(a) <= ANO_MAX:
            _soma(sem_data, n, c)
            continue
        a = int(a)
        ano = anos.setdefault(a, {"tot": _vazio(medidas), "meses": {}, "sem_mes": _vazio(medidas)})
        _soma(ano["tot"], n, c)
        if granularidade == "mes" and m is not None and 1 <= int(m) <= 12:
            _soma(ano["meses"].setdefault(int(m), _vazio(medidas)), n, c)
        else:
            _soma(ano["sem_mes"], n, c)
    a_ini = min([cobertura.inicio[0], *anos]) if anos else cobertura.inicio[0]
    a_fim = max([cobertura.fim[0], *anos]) if anos else cobertura.fim[0]
    saida_anos = []
    tot = _vazio(medidas)
    for a in range(a_ini, a_fim + 1):
        ano = anos.get(a)
        tem = bool(ano and ano["tot"]["n"])
        item = {"ano": a, **_saida(ano["tot"] if ano else _vazio(medidas), medidas),
                "status": cobertura.situacao(a, None, tem) if granularidade == "ano"
                else _status_ano(cobertura, a, ano)}
        if ano:
            _soma(tot, ano["tot"]["n"], ano["tot"]["c"])
        if granularidade == "mes":
            m_fim = 12
            if a == cobertura.fim[0]:                       # não lista mês que ainda não aconteceu…
                m_fim = max(cobertura.fim[1], *((ano or {}).get("meses") or {0: 0}))   # …salvo se há registro nele
            meses = []
            for m in range(1, m_fim + 1):
                b = (ano or {}).get("meses", {}).get(m)
                meses.append({"mes": m, "rotulo": MESES[m - 1],
                              **_saida(b or _vazio(medidas), medidas),
                              "status": cobertura.situacao(a, m, bool(b and b["n"]))})
            item["meses"] = meses
            sm = ano["sem_mes"] if ano else _vazio(medidas)
            item["sem_mes"] = _saida(sm, medidas)
        else:
            item["meses"] = None                            # fonte anual: mês não existe aqui
        saida_anos.append(item)
    out = {"granularidade": granularidade, "medidas": list(medidas), "anos": saida_anos,
           "total_datado": _saida(tot, medidas), "sem_data": _saida(sem_data, medidas)}
    geral = _vazio(medidas)
    _soma(geral, tot["n"], tot["c"])
    _soma(geral, sem_data["n"], sem_data["c"])
    out["total_geral"] = _saida(geral, medidas)
    conferir(out)
    return out


def _status_ano(cob: Cobertura, a: int, ano) -> str:
    if ano and ano["tot"]["n"]:
        parcial = (a in cob.anos_parciais or (cob.mes_corrente and a == cob.mes_corrente[0])
                   or (cob.parcial_ate and a <= cob.parcial_ate[0]) or (a, 1) < cob.inicio
                   or a == cob.inicio[0] and cob.inicio[1] > 1)
        return PARCIAL if parcial else OK
    return cob.situacao(a, None, False)


class SomaNaoFecha(AssertionError):
    pass


def conferir(q: dict) -> None:
    """As três igualdades — em centavos, exatas. Quebra que não fecha não sai da rota."""
    med = q["medidas"]

    def _eq(a, b, onde):
        if a["n"] != b["n"] or any(a["c"][k] != b["c"][k] for k in med):
            raise SomaNaoFecha(f"soma não fecha em {onde}: {a} ≠ {b}")
    acc = _vazio(med)
    for ano in q["anos"]:
        if ano["meses"] is not None:
            s = _vazio(med)
            for m in ano["meses"]:
                _soma(s, m["n"], m["c"])
            _soma(s, ano["sem_mes"]["n"], ano["sem_mes"]["c"])
            _eq(s, ano, f"ano {ano['ano']} (Σ meses)")
        _soma(acc, ano["n"], ano["c"])
    _eq(acc, q["total_datado"], "total datado (Σ anos)")
    g = _vazio(med)
    _soma(g, acc["n"], acc["c"])
    _soma(g, q["sem_data"]["n"], q["sem_data"]["c"])
    _eq(g, q["total_geral"], "total geral (datado + sem data)")


def selecao(q: dict, ano: int | None, mes: int | None) -> dict:
    """O recorte pedido, tirado da MESMA quebra (o número do filtro é o número da tabela)."""
    med = q["medidas"]
    if ano is None:
        return {"rotulo": rotulo(None, None), **{k: q["total_geral"][k] for k in ("n", "c", "v")},
                "status": OK}
    a = next((x for x in q["anos"] if x["ano"] == ano), None)
    if a is None:
        return {"rotulo": rotulo(ano, mes), **_saida(_vazio(med), med), "status": INDISPONIVEL,
                "motivo": "fora do período que a fonte cobre"}
    if mes is None:
        return {"rotulo": rotulo(ano, None), **{k: a[k] for k in ("n", "c", "v")}, "status": a["status"]}
    if a["meses"] is None:
        return {"rotulo": rotulo(ano, mes), "n": None, "c": None, "v": None, "status": INDISPONIVEL,
                "motivo": "a fonte só publica o acumulado do ano — não existe valor por mês"}
    m = next((x for x in a["meses"] if x["mes"] == mes), None)
    if m is None:
        return {"rotulo": rotulo(ano, mes), **_saida(_vazio(med), med), "status": INDISPONIVEL,
                "motivo": "mês ainda não coberto pela fonte"}
    return {"rotulo": rotulo(ano, mes), **{k: m[k] for k in ("n", "c", "v")}, "status": m["status"]}


def mascarar_doc(doc) -> str:
    """CPF (11 dígitos) mascarado na saída — LGPD; CNPJ segue inteiro (é dado público da empresa)."""
    d = re.sub(r"\D", "", str(doc or ""))
    if len(d) == 11:
        return f"***.{d[3:6]}.{d[6:9]}-**"
    return str(doc or "")
