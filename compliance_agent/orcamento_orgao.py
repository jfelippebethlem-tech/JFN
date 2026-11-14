# -*- coding: utf-8 -*-
"""Orçamento por órgão — Estado › Orçamento por órgão (pedido do dono, 14/11/2026).

"quais órgãos têm orçamento e quanto executou… tem orçamento, tem empenho e tem execução (pagamento), assim
sabemos quais órgãos performam."

Por órgão (e por UG), em cada exercício: dotação inicial, dotação atualizada, empenhado, liquidado, pago, e as
taxas empenhado ÷ dotação atualizada, pago ÷ dotação atualizada e pago ÷ empenhado. Determinístico; só leitura.

DE ONDE VEM CADA COLUNA (medido em 14/11/2026)
  · Dotação inicial e atualizada, empenhado, liquidado e "pago" do balancete: dados abertos do Estado
    (dadosabertos.rj.gov.br, conjunto `tfe-despesa`) → `data/dadosabertos_rj.db`, tabela `da_despesa`. É posição
    ANUAL acumulada (12/2016 … 12/2024; 2025 parou em 07/2025 — o portal não publica desde 14/07/2025).
  · Movimento MENSAL (só Poder Executivo, 2024–2026): painel da CGE → `cge_execucao_despesa`. Traz a dotação
    inicial (LOA); a coluna "dotação atualizada" de lá REPETE a inicial (2024: R$ 97,26 bi nas duas, contra
    R$ 113,56 bi de dotação atualizada do Executivo no TFE) — por isso não é usada como dotação atualizada.
    O mês em que a CGE atualizou o painel vem pela metade e fica fora.
  · Pago (principal): Ordem Bancária do SIAFE (`ob_orcamentaria_siafe`), status Contabilizado, com número, fora a
    devolvida pelo banco (`status_envio = 'Erro no Pagamento'`) e a de devolução parcial sem valor conhecido (Guia
    de Devolução) — regra de `pericia_contabil.valor_efetivo_ob`. Só o tipo "Orçamentária" é pagamento do orçamento
    do exercício; RPP/RPNP são restos a pagar e vão em coluna própria. Antes de 2024 a coleta não traz o tipo da OB:
    o pago do exercício fica INDISPONÍVEL e a tela mostra o total de OB contra o total desembolsado do balancete.

REGRAS (docs/REGRAS-DE-QUALIDADE.md)
  · Empenho ≠ liquidação ≠ pagamento (CNF-01); pago = OB do SIAFE (CNF-02). O "pago" do balancete é referência,
    rotulada, e a diferença entre os dois aparece em toda linha — nunca escondida.
  · INDISPONÍVEL ≠ 0 (PAD-02): coluna que a fonte não tem vem `None` com o motivo; nenhuma dotação é estimada.
  · VERIFICADO só quando duas publicações independentes dão o mesmo número (COR-02); fonte única é PENDENTE.
  · Períodos alinhados: as OB são cortadas no mesmo mês em que termina a execução publicada; balancete em posição
    parcial (2025: arquivo de 14/07/2025) não é comparado com OB; dotação atualizada publicada antes do fim do
    período da execução não serve de denominador.
  · UMA fonte de execução por tabela (`escolher_fonte`): o TFE dá a visão ORÇAMENTÁRIA (órgão = classificação do
    crédito; a dotação mora na unidade orçamentária, e qualquer UG pode executá-la); a CGE dá a visão por UNIDADE
    EXECUTORA (órgão = dono da UG, `comissao_orcamento.ug_para_orgao`).
  · As OB seguem a UG e não dizem de qual órgão é o crédito. Por isso a taxa de pago por OB só sai onde o crédito
    que cruza de órgão (descentralização) fica dentro da tolerância; no nível da UG não há taxa sobre dotação.
  · Soma com parcela faltando declara quantas faltam (`faltam`) e não gera taxa.
"""
from __future__ import annotations

import re
import sqlite3
import time
from collections import defaultdict
from pathlib import Path

from compliance_agent.pericia_contabil import fmt_brl

RAIZ = Path(__file__).resolve().parents[1]
DB = RAIZ / "data" / "compliance.db"
DB_ABERTOS = RAIZ / "data" / "dadosabertos_rj.db"

VERSAO = 1                    # entra na chave do cache da rota: lógica nova não serve número antigo (CST-07)
PISO_RANKING = 1_000_000.00   # dotação atualizada mínima para entrar no ranking (denominador pequeno distorce a taxa)
TOL_REAIS = 0.01              # duas fontes "conferem" quando batem no centavo
TOL_PAGO_PCT = 1.0            # OB do SIAFE × pago do balancete: confere até 1% de diferença
TOL_CRUZADO_PCT = 1.0         # crédito que cruza de órgão: até 1% do empenhado, OB e dotação se comparam
N_RANKING = 10

V, P, I = "VERIFICADO", "PENDENTE", "INDISPONIVEL"
_PIOR = {V: 0, P: 1, I: 2}
MESES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
         "novembro", "dezembro")


def _ro(caminho) -> sqlite3.Connection | None:
    if not Path(caminho).exists():
        return None
    return sqlite3.connect(f"file:{caminho}?mode=ro", uri=True, timeout=30)


def _tem(con: sqlite3.Connection | None, tabela: str) -> bool:
    return con is not None and con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                                           (tabela,)).fetchone() is not None


def _r2(x):
    return None if x is None else round(float(x), 2)


def _taxa(num, den):
    """Percentual com 1 casa; `None` quando falta um dos termos ou o denominador é zero (nunca 0% inventado)."""
    if num is None or not den:
        return None
    return round(100.0 * num / den, 1)


def _data_br(iso) -> str:
    """'2026-07-15 17:11:36' → '15/07/2026' (PAD-09: data legível e rotulada pelo que é)."""
    t = str(iso or "")[:10]
    return f"{t[8:10]}/{t[5:7]}/{t[0:4]}" if len(t) == 10 and t[4] == "-" else "—"


def _pct_br(v: float) -> str:
    return f"{v:.1f}".replace(".", ",") + "%"


def _pior(*estados: str) -> str:
    return max(estados, key=lambda e: _PIOR[e])


# ── exercícios disponíveis ─────────────────────────────────────────────────────────────────────────────────────
def _mes_completo_cge(con_ab: sqlite3.Connection | None, ano: int) -> tuple[int, str | None]:
    """(último mês COMPLETO do painel da CGE no exercício, data de atualização da fonte). O mês da atualização vem
    pela metade (medido: julho/2026 com 15 dias fazia o pago do semestre cair 6,7% em termos reais)."""
    if not _tem(con_ab, "cge_execucao_despesa"):
        return 0, None
    ult = con_ab.execute("SELECT MAX(mes) FROM cge_execucao_despesa WHERE ano=?", (ano,)).fetchone()[0]
    if not ult:
        return 0, None
    atual = None
    if _tem(con_ab, "cge_coleta"):
        r = con_ab.execute("SELECT atualizado_fonte FROM cge_coleta WHERE tabela='cge_execucao_despesa'").fetchone()
        atual = r[0] if r else None
    if atual and str(atual)[:4].isdigit() and int(str(atual)[:4]) == ano:
        return max(0, min(int(ult), int(str(atual)[5:7]) - 1)), atual
    if atual and str(atual)[:4].isdigit() and int(str(atual)[:4]) < ano:
        return 0, atual
    return int(ult), atual


def exercicios(db=None, db_abertos=None) -> list[dict]:
    """Exercícios que a base tem, do mais recente ao mais antigo, com o alcance de cada fonte."""
    con, con_ab = _ro(db or DB), _ro(db_abertos or DB_ABERTOS)
    try:
        anos: dict[int, dict] = defaultdict(dict)
        if _tem(con_ab, "da_despesa"):
            for (pos,) in con_ab.execute("SELECT DISTINCT posicao FROM da_despesa"):
                a, m = int(str(pos)[3:]), int(str(pos)[:2])
                if m >= anos[a].get("tfe_mes", 0):
                    anos[a].update(tfe_mes=m, tfe_posicao=pos)
        if _tem(con_ab, "cge_execucao_despesa"):
            for (a,) in con_ab.execute("SELECT DISTINCT ano FROM cge_execucao_despesa"):
                mc, atual = _mes_completo_cge(con_ab, int(a))
                anos[int(a)].update(cge_mes=mc, cge_atualizado=atual)
        if _tem(con, "ob_orcamentaria_siafe"):
            for a, n in con.execute("SELECT exercicio, COUNT(DISTINCT ug_emitente) FROM ob_orcamentaria_siafe "
                                    "WHERE status='Contabilizado' GROUP BY 1"):
                if a in anos:
                    anos[a]["ob_ugs"] = n
        return [{"ano": a, "tfe_posicao": d.get("tfe_posicao"), "tfe_mes": d.get("tfe_mes"),
                 "cge_mes": d.get("cge_mes") or None, "cge_atualizado": d.get("cge_atualizado"),
                 "ob_ugs": d.get("ob_ugs", 0), "dotacao_atualizada": "tfe_posicao" in d}
                for a, d in sorted(anos.items(), reverse=True)]
    finally:
        for x in (con, con_ab):
            if x is not None:
                x.close()


def exercicio_padrao(exs: list[dict]) -> int | None:
    """O exercício FECHADO mais recente (posição de dezembro no TFE): é onde dotação, empenho e pagamento cobrem o
    ano inteiro de todos os Poderes — a comparação justa entre órgãos. Sem nenhum fechado, o mais recente."""
    for e in exs:
        if e["tfe_mes"] == 12:
            return e["ano"]
    return exs[0]["ano"] if exs else None


# ── leitura das três fontes ────────────────────────────────────────────────────────────────────────────────────
_TFE_VAZIO = {"posicao": None, "publicado_em": None, "pares": [], "uos": [], "donos": {}, "nomes_ug": {},
              "nomes_orgao": {}}


def _posicoes(con_ab: sqlite3.Connection | None) -> list[str]:
    """Posições 'MM/AAAA' publicadas no TFE, da mais antiga à mais recente."""
    if not _tem(con_ab, "da_despesa"):
        return []
    return sorted((str(r[0]) for r in con_ab.execute("SELECT DISTINCT posicao FROM da_despesa") if r[0]),
                  key=lambda p: (int(p[3:]), int(p[:2])))


def _ler_tfe(con_ab: sqlite3.Connection | None, posicao: str | None) -> dict:
    """Balancete do TFE numa posição, por PAR (UG executora, órgão do crédito). O órgão é a classificação
    orçamentária da própria linha; a UG que executa crédito de outro órgão aparece nos dois (medido em 2024:
    R$ 1,14 bi, 1,07% do empenhado). `donos` = órgão que concentra a dotação + o empenho da UG — serve para as OB,
    que não dizem de qual órgão é o crédito."""
    if not posicao:
        return dict(_TFE_VAZIO)
    pares, nomes_ug, nomes_org = [], {}, {}
    pesos: dict[str, dict[str, float]] = defaultdict(dict)
    recurso = None
    for (ug, org, nome_ug, nome_org, poder, di, da, emp, liq, pg, rpp, res, intra, rec) in con_ab.execute(
            "SELECT ug, orgao, MAX(nome_ug), MAX(nome_orgao), MAX(poder), SUM(valor_dotacao_inicial), "
            "SUM(valor_dotado_atual), SUM(valor_empenhado), SUM(valor_liquidado), SUM(valor_pago), "
            "SUM(valor_rp_pago), SUM(CASE WHEN modalidade_aplicacao='99' THEN valor_dotado_atual ELSE 0 END), "
            "SUM(CASE WHEN modalidade_aplicacao='91' THEN valor_empenhado ELSE 0 END), MAX(recurso_id) "
            "FROM da_despesa WHERE posicao=? GROUP BY ug, orgao", (posicao,)):
        ug, org = str(ug or "").strip(), str(org or "").strip()
        recurso = recurso or rec
        if not ug or not org:
            continue
        nums = [round(float(v or 0), 2) for v in (di, da, emp, liq, pg, rpp, res, intra)]
        pares.append({"ug": ug, "orgao": org, "executivo": str(poder) == "1", "dot_ini": nums[0], "dot_atual": nums[1],
                      "emp": nums[2], "liq": nums[3], "pago": nums[4], "rp_pago": nums[5], "reserva": nums[6],
                      "intra_emp": nums[7]})
        nomes_ug[ug] = (nome_ug or "").strip()
        if (nome_org or "").strip():
            nomes_org[org] = nome_org.strip()
        pesos[ug][org] = abs(nums[2]) + abs(nums[1])
    donos = {}
    for ug, p in pesos.items():
        o, peso = max(p.items(), key=lambda kv: (kv[1], kv[0]))
        if peso:                                  # UG só com linhas zeradas não tem dono neste exercício
            donos[ug] = o
    publicado = None
    if recurso and _tem(con_ab, "da_recurso"):
        r = con_ab.execute("SELECT modificado_portal FROM da_recurso WHERE recurso_id=?", (recurso,)).fetchone()
        publicado = str(r[0])[:10] if r and r[0] else None
    # a dotação mora na UNIDADE ORÇAMENTÁRIA (UO); qualquer UG pode executar o crédito dela. Medido em 2024: 188 UO,
    # 153 UG, 461 combinações; toda UO pertence a um só órgão (os dois primeiros dígitos).
    uos = [{"uo": str(uo), "nome": (nome or "").strip(), "orgao": str(org),
            **dict(zip(("dot_ini", "dot_atual", "emp", "liq", "pago"), (round(float(v or 0), 2) for v in vals)))}
           for uo, nome, org, *vals in con_ab.execute(
               "SELECT codigo_uo, MAX(nome_uo), MAX(orgao), SUM(valor_dotacao_inicial), SUM(valor_dotado_atual), "
               "SUM(valor_empenhado), SUM(valor_liquidado), SUM(valor_pago) FROM da_despesa WHERE posicao=? "
               "GROUP BY codigo_uo", (posicao,)) if uo]
    return {"posicao": posicao, "publicado_em": publicado, "pares": pares, "uos": uos, "donos": donos,
            "nomes_ug": nomes_ug, "nomes_orgao": nomes_org}


def _ler_cge(con_ab: sqlite3.Connection | None, ano: int) -> dict:
    mes_completo, atual = _mes_completo_cge(con_ab, ano)
    if not mes_completo:
        return {"mes_completo": 0, "atualizado": atual, "ugs": {}}
    ugs: dict[str, dict] = {}
    for ug, nome, mes, di, emp, liq, pg, rpp in con_ab.execute(
            "SELECT ug, MAX(unidade_gestora), mes, SUM(dotacao_inicial), SUM(despesas_empenhadas), "
            "SUM(despesas_liquidadas), SUM(despesas_orcamentarias_pagas), SUM(restos_a_pagar_pagos) "
            "FROM cge_execucao_despesa WHERE ano=? GROUP BY ug, mes", (ano,)):
        if not ug or not mes:
            continue
        u = ugs.setdefault(str(ug), {"nome": str(nome or "").split(" - ", 1)[-1].strip(), "dot_ini": 0.0, "m": {}})
        u["dot_ini"] = round(u["dot_ini"] + float(di or 0), 2)      # a dotação inicial entra nos primeiros meses
        if int(mes) <= mes_completo:
            u["m"][str(int(mes))] = [round(float(x or 0), 2) for x in (emp, liq, pg, rpp)]
    return {"mes_completo": mes_completo, "atualizado": atual, "ugs": ugs}


# `pericia_contabil.situacao_devolucao` só reconhece UMA guia no campo (`^AAAAGDnnnnn$`). Medido em 14/11/2026 contra
# soma independente em SQL: a OB com DUAS OU MAIS guias ("2024GD00010,2024GD00017") passava como pagamento integral —
# 331 OB e R$ 983,76 mi só em 2024. Aqui qualquer guia no campo marca a devolução.
_RE_GUIA = re.compile(r"\d{4}GD\d+")

_OB_ZERO = {"orc": 0.0, "rp": 0.0, "st": 0.0, "n": 0, "dev_n": 0, "dev_v": 0.0, "desc_n": 0, "desc_v": 0.0}


def _ler_ob(con: sqlite3.Connection | None, ano: int) -> dict:
    """OB Contabilizada do exercício por UG emitente e mês de emissão, já com a regra de devolução da casa."""
    if not _tem(con, "ob_orcamentaria_siafe"):
        return {"ugs": {}, "max_data": None, "sem_numero": [0, 0.0], "disponivel": False}
    from compliance_agent.pericia_contabil import (DEVOLVIDA, DEVOLVIDA_SEM_VALOR, situacao_devolucao,
                                                   valor_efetivo_ob)
    from compliance_agent.siafe_gd import devolvido_por_ob
    cols = {r[1] for r in con.execute("PRAGMA table_info(ob_orcamentaria_siafe)")}
    c_gd = "gd" if "gd" in cols else "''"
    c_env = "status_envio" if "status_envio" in cols else "''"
    c_tipo = "tipo_ob" if "tipo_ob" in cols else "''"
    devolvido = devolvido_por_ob(con)            # {} sem a tabela `gd_siafe`: vale a regra de piso
    ugs: dict[str, dict] = {}
    sem_numero = [0, 0.0]
    max_data = ""
    for ug, num, data, tipo, valor, gd, env in con.execute(
            f"SELECT ug_emitente, numero_ob, data_emissao, {c_tipo}, valor, {c_gd}, {c_env} "
            "FROM ob_orcamentaria_siafe WHERE exercicio=? AND status='Contabilizado'", (ano,)):
        valor = float(valor or 0)
        num = str(num or "").strip()
        if not num:                              # linha-fantasma da coleta: repete uma OB numerada — fora
            sem_numero[0] += 1
            sem_numero[1] += valor
            continue
        d = str(data or "")
        mes = int(d[3:5]) if len(d) == 10 and d[3:5].isdigit() and 1 <= int(d[3:5]) <= 12 else 0
        if mes:
            max_data = max(max_data, f"{d[6:10]}-{d[3:5]}-{d[0:2]}")
        ug = str(ug or "").strip()
        b = ugs.setdefault(ug, {}).setdefault(str(mes), dict(_OB_ZERO))   # mês "0" = data ilegível: conta sempre
        sit = situacao_devolucao(gd, env) or ("gd" if _RE_GUIA.search(str(gd or "")) else "")
        efetivo, marca = valor_efetivo_ob(valor, sit, devolvido=devolvido.get((num, ug)))
        t = str(tipo or "").strip()
        b["orc" if t == "Orçamentária" else "rp" if t.startswith("RP") else "st"] += efetivo
        b["n"] += 1
        if marca == DEVOLVIDA:
            b["dev_n"] += 1
            b["dev_v"] += valor - efetivo
        elif marca == DEVOLVIDA_SEM_VALOR:
            b["desc_n"] += 1
            b["desc_v"] += valor
    for meses in ugs.values():
        for b in meses.values():
            for k in ("orc", "rp", "st", "dev_v", "desc_v"):
                b[k] = round(b[k], 2)
    return {"ugs": ugs, "max_data": max_data or None, "sem_numero": [sem_numero[0], round(sem_numero[1], 2)],
            "disponivel": True}


def carregar(ano: int, db=None, db_abertos=None) -> dict:
    """Base do exercício (as três fontes agregadas) — é a parte pesada; a rota guarda em cache. Só tipos de JSON,
    para o cache em disco devolver exatamente o que foi gravado."""
    con, con_ab = _ro(db or DB), _ro(db_abertos or DB_ABERTOS)
    try:
        posicoes = _posicoes(con_ab)
        do_ano = [p for p in posicoes if int(p[3:]) == int(ano)]
        tfe = _ler_tfe(con_ab, do_ano[-1] if do_ano else None)
        cge, ob = _ler_cge(con_ab, int(ano)), _ler_ob(con, int(ano))
        # exercício sem TFE: o crédito que cruza de órgão é medido na posição mais recente publicada (referência)
        ref = {"posicao": tfe["posicao"], "pares": [[p["ug"], p["orgao"], p["emp"]] for p in tfe["pares"]]}
        if not tfe["pares"] and posicoes:
            r = _ler_tfe(con_ab, posicoes[-1])
            ref = {"posicao": r["posicao"], "pares": [[p["ug"], p["orgao"], p["emp"]] for p in r["pares"]]}
        mapa, nomes = {}, {}
        # o cadastro de todos os exercícios só é lido quando falta dono a alguma UG (exercício sem TFE, UG nova)
        if (set(cge["ugs"]) | set(ob["ugs"])) - set(tfe["donos"]) and _tem(con_ab, "da_despesa"):
            from compliance_agent.comissao_orcamento import nomes_orgao, ug_para_orgao
            mapa, nomes = ug_para_orgao(con_ab), nomes_orgao(con_ab)
        return {"versao": VERSAO, "ano": int(ano), "tfe": tfe, "cge": cge, "ob": ob, "ref_cruzado": ref,
                "mapa_global": mapa, "nomes_global": nomes, "gerado_em": time.strftime("%Y-%m-%d %H:%M")}
    finally:
        for x in (con, con_ab):
            if x is not None:
                x.close()


# ── montagem ───────────────────────────────────────────────────────────────────────────────────────────────────
_SOMAVEIS = ("dotacao_inicial", "dotacao_atualizada", "empenhado", "liquidado", "pago_balancete",
             "rp_pago_balancete")
_ESTADOS = ("dotacao_inicial", "dotacao_atualizada", "empenhado", "liquidado", "pago_balancete", "pago_siafe")
_FONTE_NOME = {"TFE": "dados abertos do TFE", "CGE": "painel da CGE"}


def _confere(a, b) -> bool:
    return a is not None and b is not None and round(abs(a - b), 2) <= TOL_REAIS


def escolher_fonte(base: dict, mes: int | None) -> tuple[str | None, int | None]:
    """(fonte da execução, mês até onde ela vai). UMA fonte para a tabela inteira: misturar balancete anual por órgão
    com movimento mensal por UG na mesma tabela compararia períodos e universos diferentes.
    Sem mês pedido: o TFE (todos os Poderes, órgão do crédito); se o TFE não publicou o exercício, a CGE.
    Com mês pedido: o TFE só se a posição dele é exatamente aquele mês; senão a CGE (Executivo), se alcança."""
    tfe_mes = int(base["tfe"]["posicao"][:2]) if base["tfe"]["posicao"] else 0
    cge_mes = base["cge"]["mes_completo"] if base["cge"]["ugs"] else 0
    if mes is None:
        return ("TFE", tfe_mes) if tfe_mes else (("CGE", cge_mes) if cge_mes else (None, None))
    if tfe_mes == mes:
        return "TFE", mes
    return ("CGE", mes) if cge_mes >= mes else (None, None)


class _Ctx:
    """O que as linhas precisam da base, já no recorte do pedido."""

    def __init__(self, base: dict, mes: int | None):
        self.base, self.ano, self.mes = base, base["ano"], mes
        self.fonte, self.ate = escolher_fonte(base, mes)
        self.corte = self.ate or mes or 12                      # as OB param no mesmo mês da execução publicada
        self.cge, self.tfe = base["cge"], base["tfe"]
        # posição do TFE fora de dezembro é do DIA em que o arquivo foi publicado, não do fim do mês: as OB (cortadas
        # por mês) não se comparam com esse balancete
        self.parcial = self.fonte == "TFE" and self.ate != 12
        # dotação atualizada publicada ANTES do fim do período da execução (2025: dotação de julho, execução da CGE
        # até dezembro) não serve de denominador: crédito aberto depois faria a taxa passar de 100%
        tfe_mes = int(self.tfe["posicao"][:2]) if self.tfe["posicao"] else 0
        self.dot_defasada = bool(self.fonte == "CGE" and tfe_mes and tfe_mes < self.ate)
        self.tfe_ug: dict[str, dict] = {}
        for p in self.tfe["pares"]:
            u = self.tfe_ug.setdefault(p["ug"], dict.fromkeys(("dot_ini", "dot_atual", "emp", "liq", "pago",
                                                               "rp_pago"), 0.0) | {"n_pares": 0, "executivo": True})
            for k in ("dot_ini", "dot_atual", "emp", "liq", "pago", "rp_pago"):
                u[k] = round(u[k] + p[k], 2)
            u["n_pares"] += 1 if (p["emp"] or p["dot_atual"]) else 0
            u["executivo"] = u["executivo"] and p["executivo"]

    def cge_ate(self, ug: str, m: int) -> list[float] | None:
        c = self.cge["ugs"].get(ug)
        if not c or self.cge["mes_completo"] < m:
            return None
        return [round(sum(c["m"].get(str(i), [0, 0, 0, 0])[k] for i in range(1, m + 1)), 2) for k in range(4)]

    def ob_ate(self, ug: str) -> dict:
        ob = dict(_OB_ZERO)
        for m, b in (self.base["ob"]["ugs"].get(ug) or {}).items():
            if int(m) <= self.corte:
                for k in ob:
                    ob[k] += b[k]
        return ob

    def dono(self, ug: str) -> tuple[str, bool]:
        """(órgão dono da UG, inferido?) — exercício → cadastro de todos os exercícios → dois primeiros dígitos."""
        o = self.tfe["donos"].get(ug) or self.base["mapa_global"].get(ug)
        return (o, False) if o else (ug[:2], True)

    def nome_ug(self, ug: str) -> str:
        return self.tfe["nomes_ug"].get(ug) or (self.cge["ugs"].get(ug) or {}).get("nome") or f"UG {ug}"

    def estados_ug(self, ug: str) -> tuple[dict, dict]:
        """Estado de cada coluna de balancete da UG: VERIFICADO quando TFE e CGE dão o mesmo número no período."""
        est, mot = dict.fromkeys(_ESTADOS, I), {}
        t, c = self.tfe_ug.get(ug), self.cge["ugs"].get(ug)
        if t:
            est["dotacao_inicial"] = V if (c and _confere(t["dot_ini"], c["dot_ini"])) else P
            est["dotacao_atualizada"] = P
            mot["dotacao_atualizada"] = f"fonte única (dados abertos do TFE, posição {self.tfe['posicao']})"
            if est["dotacao_inicial"] == P:
                mot["dotacao_inicial"] = ("TFE e painel da CGE diferem" if c else
                                          "fonte única (dados abertos do TFE)")
        elif c:
            est["dotacao_inicial"] = P
            mot["dotacao_inicial"] = "fonte única (painel da CGE)"
            mot["dotacao_atualizada"] = ("o TFE não publicou este exercício e o painel da CGE repete a dotação "
                                         "inicial na coluna de dotação atualizada")
        else:
            mot["dotacao_atualizada"] = "UG sem linha de dotação nas fontes publicadas deste exercício"
        ex = ([t["emp"], t["liq"], t["pago"]] if (self.fonte == "TFE" and t) else
              (self.cge_ate(ug, self.ate) if self.fonte == "CGE" else None))
        if ex:
            outra = self.cge_ate(ug, self.ate) if self.fonte == "TFE" else None
            for i, k in enumerate(("empenhado", "liquidado", "pago_balancete")):
                est[k] = V if (outra and _confere(ex[i], outra[i])) else P
                if est[k] == P:
                    mot[k] = (f"TFE e painel da CGE diferem em R$ {fmt_brl(abs(ex[i] - outra[i]))}" if outra else
                              f"fonte única ({_FONTE_NOME[self.fonte]}), sem segunda publicação neste período")
        else:
            alvo = f"até {MESES[self.mes - 1]}/{self.ano}" if self.mes else f"em {self.ano}"
            mot["execucao"] = f"nenhuma fonte publica a execução desta UG {alvo}"
        return est, mot


def _linha(cx: _Ctx, ug: str, orgao: str, *, dot: tuple, ex: list | None, com_ob: bool, ref_pago: tuple,
           inferido: bool = False, reserva: float = 0.0) -> dict:
    """Uma linha da tabela: UG × órgão do crédito (visão do TFE) ou UG inteira (visão da CGE).
    `ref_pago` = (pago, restos pagos) do balancete DA UG INTEIRA, contra o que as OB da UG se comparam."""
    est, mot = cx.estados_ug(ug)
    emp, liq, pago_b, rp_b = ex if ex else (None, None, None, None)
    dono, _ = cx.dono(ug)
    notas = []
    r = {"ug": ug, "nome": cx.nome_ug(ug), "orgao": orgao, "orgao_dono_ug": dono, "orgao_inferido": inferido,
         "credito_de_outro_orgao": dono != orgao,
         "dotacao_inicial": _r2(dot[0]), "dotacao_atualizada": _r2(dot[1]),
         "empenhado": _r2(emp), "liquidado": _r2(liq), "pago_balancete": _r2(pago_b), "rp_pago_balancete": _r2(rp_b),
         "pago_siafe": None, "rp_pago_siafe": None, "ob_total": None, "ob_sem_tipo": False, "ob": dict(
             n=0, devolvidas_n=0, devolvidas_valor=0.0, devolucao_sem_valor_n=0, devolucao_sem_valor_bruto=0.0),
         "ref_pago_balancete": None, "divergencia": None, "divergencia_pct": None, "divergencia_base": None,
         "espera_ob": com_ob, "pago_balancete_ug": _r2(ref_pago[0])}
    if not com_ob:
        mot["pago_siafe"] = (f"as OB desta UG estão no órgão {dono}, dono da UG: a OB não diz de qual órgão é o "
                             "crédito")
    else:
        ob = cx.ob_ate(ug)
        tem, sem_tipo = ob["n"] > 0, ob["st"] > 0.005
        r["ob"] = dict(n=ob["n"], devolvidas_n=ob["dev_n"], devolvidas_valor=round(ob["dev_v"], 2),
                       devolucao_sem_valor_n=ob["desc_n"], devolucao_sem_valor_bruto=round(ob["desc_v"], 2))
        r["ob_sem_tipo"] = tem and sem_tipo
        if tem:
            r["ob_total"] = round(ob["orc"] + ob["rp"] + ob["st"], 2)
        if tem and not sem_tipo:
            r["pago_siafe"], r["rp_pago_siafe"] = round(ob["orc"], 2), round(ob["rp"], 2)
        ref, ref_rp = (None, None) if cx.parcial else ref_pago
        r["ref_pago_balancete"] = _r2(ref)
        if not cx.base["ob"]["disponivel"]:
            mot["pago_siafe"] = "tabela de OB do SIAFE ausente na base"
        elif not tem:
            mot["pago_siafe"] = ("nenhuma OB orçamentária contabilizada desta UG na base do SIAFE neste período — "
                                 "não é zero pago")
        elif sem_tipo:
            mot["pago_siafe"] = ("a coleta deste exercício não traz o tipo da OB (orçamentária × restos a pagar); "
                                 "a tela compara o total de OB com o total desembolsado do balancete")
            if ref is not None:
                desem = ref + (ref_rp or 0)
                r.update(divergencia=round(r["ob_total"] - desem, 2), divergencia_base="total_com_restos",
                         divergencia_pct=_taxa(r["ob_total"] - desem, desem), ref_pago_balancete=_r2(desem))
        else:
            if ref is not None:
                r.update(divergencia=round(r["pago_siafe"] - ref, 2), divergencia_base="orcamentaria",
                         divergencia_pct=_taxa(r["pago_siafe"] - ref, ref))
            confere = r["divergencia"] is not None and (abs(r["divergencia"]) <= TOL_REAIS or (
                r["divergencia_pct"] is not None and abs(r["divergencia_pct"]) <= TOL_PAGO_PCT))
            est["pago_siafe"] = V if confere else P
            if not confere:
                mot["pago_siafe"] = (_SEM_BALANCETE[cx.parcial] if r["divergencia"] is None else
                                     f"OB do SIAFE e pago do balancete da UG diferem em R$ {fmt_brl(abs(r['divergencia']))}")
        if ob["desc_n"]:
            notas.append(f"{ob['desc_n']} OB com devolução parcial de valor não coletado (R$ {fmt_brl(ob['desc_v'])} "
                         "brutos) fora do pago — o pago do SIAFE é piso")
    if reserva > 0:
        notas.append(f"R$ {fmt_brl(reserva)} da dotação atualizada é reserva de contingência (modalidade 99), que não "
                     "se empenha")
    if dot[1] is not None and not dot[1] and (emp or 0) > 0:
        notas.append("sem dotação nesta linha: executa crédito cuja dotação está em outra unidade")
    if r["credito_de_outro_orgao"]:
        notas.append(f"UG do órgão {dono} executando crédito deste órgão (descentralização)")
    if inferido:
        notas.append("UG fora do cadastro do TFE: órgão inferido pelos dois primeiros dígitos da UG")
    # taxa de pago da linha só quando as OB da UG e a dotação da linha falam do mesmo universo
    r["pago_comparavel"] = com_ob and not cx.parcial and (
        cx.fonte != "TFE" or (cx.tfe_ug.get(ug) or {}).get("n_pares", 0) <= 1)
    r["dot_defasada"] = cx.dot_defasada
    # a dotação é da unidade orçamentária, não da UG que executa: taxa sobre dotação no nível da UG daria 8.827% numa
    # UG que executa crédito do fundo do próprio órgão (medido, UG 293100 em 2024). No nível da UG só pago ÷ empenhado.
    r["sem_taxa_dotacao"] = True
    r["estados"], r["motivos"], r["notas"] = est, mot, notas
    return r


_SEM_BALANCETE = {False: "sem balancete do mesmo período para conferir",
                  True: "balancete em posição parcial (dia de corte dentro do mês): as OB, cortadas por mês, não se "
                        "comparam com ele"}


def _linhas(cx: _Ctx) -> list[dict]:
    com_tfe, com_cge, com_ob = set(cx.tfe_ug), set(cx.cge["ugs"]), set(cx.base["ob"]["ugs"])
    out = []
    if cx.fonte == "TFE":
        for p in cx.tfe["pares"]:
            ug, t = p["ug"], cx.tfe_ug[p["ug"]]
            dono, _ = cx.dono(ug)
            e_dono = dono == p["orgao"]
            if not e_dono and not any(p[k] for k in ("dot_ini", "dot_atual", "emp", "liq", "pago", "rp_pago")):
                continue                                         # par zerado de órgão alheio: não é linha
            out.append(_linha(cx, ug, p["orgao"], dot=(p["dot_ini"], p["dot_atual"]),
                              ex=[p["emp"], p["liq"], p["pago"], p["rp_pago"]], com_ob=e_dono,
                              ref_pago=(t["pago"], t["rp_pago"]), reserva=p["reserva"]))
            out[-1]["executivo"] = p["executivo"]
        resto = com_ob - com_tfe
    else:
        resto = com_tfe | com_cge | com_ob
    for ug in sorted(resto):
        if not ug:
            continue
        t, c = cx.tfe_ug.get(ug), cx.cge["ugs"].get(ug)
        ex = cx.cge_ate(ug, cx.ate) if cx.fonte == "CGE" else None
        dot = (t["dot_ini"], t["dot_atual"]) if t else ((c["dot_ini"], None) if c else (None, None))
        dono, inferido = cx.dono(ug)
        reserva = sum(p["reserva"] for p in cx.tfe["pares"] if p["ug"] == ug) if t else 0.0
        out.append(_linha(cx, ug, dono, dot=dot, ex=ex, com_ob=True, ref_pago=(ex[2], ex[3]) if ex else (None, None),
                          inferido=inferido, reserva=reserva))
        out[-1]["executivo"] = t["executivo"] if t else (True if c else None)
    return out


def _taxas(x: dict) -> None:
    """Taxas da linha. Termo com parcela faltando (`faltam`) não gera taxa — soma incompleta no numerador ou no
    denominador daria um percentual errado com cara de medido. As taxas com OB do SIAFE exigem ainda que OB e
    dotação falem do mesmo universo (`pago_comparavel`)."""
    f = x.get("faltam") or {}

    def t(num: str, den: str):
        if x.get("sem_taxa") or f.get(num) or f.get(den) or (den == "dotacao_atualizada" and x.get("dot_defasada")):
            return None
        if x.get("sem_taxa_dotacao") and den.startswith("dotacao"):
            return None
        return _taxa(x[num], x[den])
    x["taxa_empenho"] = t("empenhado", "dotacao_atualizada")
    x["taxa_pago_balancete"] = t("pago_balancete", "dotacao_atualizada")
    x["taxa_empenho_inicial"] = t("empenhado", "dotacao_inicial")
    ok = x.get("pago_comparavel", True)
    x["taxa_pago"] = t("pago_siafe", "dotacao_atualizada") if ok else None
    x["taxa_pago_empenhado"] = t("pago_siafe", "empenhado") if ok else None


def _somar(linhas: list[dict]) -> dict:
    """Soma de linhas (de um órgão ou do Estado). Cada coluna soma o que existe e DECLARA em `faltam` quantas
    linhas ficaram de fora — parcela ausente não vira zero, e a taxa que dependeria dela não é calculada."""
    r: dict = {}
    faltam: dict[str, int] = {}
    for k in _SOMAVEIS:
        vals = [x[k] for x in linhas if x[k] is not None]
        r[k] = round(sum(vals), 2) if vals else None
        if vals and len(vals) < len(linhas):
            faltam[k] = len(linhas) - len(vals)
    esperam = [x for x in linhas if x["espera_ob"]]
    com_ob = [x for x in esperam if x["pago_siafe"] is not None]
    r["pago_siafe"] = round(sum(x["pago_siafe"] for x in com_ob), 2) if com_ob else None
    r["rp_pago_siafe"] = round(sum(x["rp_pago_siafe"] or 0 for x in com_ob), 2) if com_ob else None
    # UG sem OB só "falta" se o balancete registra pagamento nela (ou não diz): com pago zero no balancete, nada falta
    sem_ob = [x["ug"] for x in esperam if x["pago_siafe"] is None and x["pago_balancete_ug"] != 0]
    if com_ob and sem_ob:
        faltam["pago_siafe"] = len(sem_ob)
    r["ugs_sem_ob"] = sem_ob
    tot = [x for x in esperam if x["ob_total"] is not None]
    r["ob_total"] = round(sum(x["ob_total"] for x in tot), 2) if tot else None
    r["ob_sem_tipo"] = any(x["ob_sem_tipo"] for x in linhas)
    r["ob"] = {k: (round(sum(x["ob"][k] for x in linhas), 2) if k.endswith(("valor", "bruto"))
                   else sum(x["ob"][k] for x in linhas)) for k in linhas[0]["ob"]}
    # diferença SIAFE × balancete só entre as UG que têm os dois no mesmo período (mesmo universo — CST-13)
    r.update(divergencia=None, divergencia_pct=None, divergencia_base=None, divergencia_n=0, ref_pago_balancete=None)
    for base_div in ("orcamentaria", "total_com_restos"):
        par = [x for x in esperam if x["divergencia"] is not None and x["divergencia_base"] == base_div]
        if par:
            ref = round(sum(x["ref_pago_balancete"] for x in par), 2)
            r.update(divergencia=round(sum(x["divergencia"] for x in par), 2), divergencia_base=base_div,
                     divergencia_n=len(par), ref_pago_balancete=ref)
            r["divergencia_pct"] = _taxa(r["divergencia"], ref)
            break
    r["faltam"] = faltam
    r["estados"] = {k: _pior(*(x["estados"][k] for x in (esperam if k == "pago_siafe" and esperam else linhas)))
                    for k in _ESTADOS}
    r["n_ugs"] = len({x["ug"] for x in linhas})
    return r


def _cruzado(cx: _Ctx) -> dict[str, tuple[float, float | None]]:
    """Por órgão, (R$ do empenhado que CRUZA de órgão, % sobre o empenhado do órgão): crédito dele executado por UG
    de outro dono + crédito alheio executado pelas UG dele. As OB e o painel da CGE seguem a UG; o orçamento segue o
    órgão do crédito — onde o cruzamento passa da tolerância, juntar os dois compararia universos diferentes.
    Medido nos pares do TFE do próprio exercício; sem eles, na posição mais recente publicada (referência)."""
    cz: dict[str, float] = defaultdict(float)
    emp: dict[str, float] = defaultdict(float)
    for ug, org, e in cx.base["ref_cruzado"]["pares"]:
        emp[org] += e
        dono, _ = cx.dono(ug)
        if dono != org:
            cz[org] += abs(e)
            cz[dono] += abs(e)
    return {o: (round(cz.get(o, 0.0), 2), (_taxa(cz[o], emp[o]) if cz.get(o) else 0.0) if o in emp else None)
            for o in set(emp) | set(cz)}


def _ranking(orgaos: list[dict], criterio: str) -> dict:
    """Maiores e menores taxas entre os órgãos que TÊM a taxa (nenhuma parcela faltando) e dotação a partir do
    piso. Quem fica de fora é contado (N de M)."""
    den = "dotacao_inicial" if criterio == "taxa_empenho_inicial" else "dotacao_atualizada"
    eleg = [o for o in orgaos if o.get(criterio) is not None and (o[den] or 0) >= PISO_RANKING]

    def item(o: dict) -> dict:
        return {"orgao": o["orgao"], "nome": o["nome"], "taxa": o[criterio], "notas": o["notas"][:2]}
    return {"criterio": criterio, "elegiveis": len(eleg), "total_orgaos": len(orgaos),
            "mais": [item(o) for o in sorted(eleg, key=lambda o: (-o[criterio], o["orgao"]))[:N_RANKING]],
            "menos": [item(o) for o in sorted(eleg, key=lambda o: (o[criterio], o["orgao"]))[:N_RANKING]]}


COLUNAS = {
    "dotacao_inicial": "Dotação inicial (LOA) — dados abertos do Estado, conjunto tfe-despesa (posição anual); em "
                       "exercício que o TFE não publicou, painel da CGE (só Executivo).",
    "dotacao_atualizada": "Dotação atualizada (inicial + créditos adicionais − anulações) na posição publicada — "
                          "dados abertos do Estado, tfe-despesa. Sem publicação do TFE = INDISPONÍVEL.",
    "empenhado": "Empenhado no período — TFE (posição anual, por órgão do crédito) ou painel da CGE (movimento "
                 "mensal, só Executivo, por UG). Empenho é reserva de dotação, não é pagamento.",
    "liquidado": "Liquidado no período — mesmas fontes do empenhado. Liquidação reconhece a entrega, não é pagamento.",
    "pago_siafe": "Pago — soma das Ordens Bancárias do SIAFE-Rio do tipo Orçamentária, status Contabilizado, emitidas "
                  "pelas UG do órgão no período; fora a devolvida pelo banco e a de devolução parcial sem valor "
                  "conhecido.",
    "pago_balancete": "Pago do balancete (referência) — coluna \"valor pago\" do TFE ou do painel da CGE. Não é soma "
                      "de OB: é o registro contábil do estágio do pagamento.",
    "divergencia": "Pago por OB do SIAFE menos pago do balancete, só nas UG que têm os dois no mesmo período.",
}

RESSALVA = ("Taxa baixa de execução não é irregularidade: dotação contingenciada, receita vinculada que não entrou, "
            "reserva de contingência, crédito aberto no fim do ano e obra plurianual reduzem a taxa sem ato ilícito. "
            "O pago por OB do SIAFE fica abaixo do pago do balancete na maioria das unidades; a explicação provável "
            "— NÃO conferida documento a documento — é o que o balancete registra como pago sem OB orçamentária ao "
            "credor (retenções e consignações da folha, serviço da dívida, transferências), que o SIAFE guarda em "
            "telas não coletadas (OB de Retenção, de Transferência e Extraorçamentária).")

_VISAO = {"TFE": ("orcamentaria", "por órgão do crédito (classificação orçamentária do TFE), todos os Poderes"),
          "CGE": ("unidade_executora", "por unidade executora (painel da CGE, só Poder Executivo); o órgão é o dono "
                                       "da UG e crédito descentralizado pode levar a taxa acima de 100%"),
          None: ("so_ob", "sem execução publicada neste período: só dotação e OB do SIAFE")}


def montar(base: dict, mes: int | None = None, exs: list[dict] | None = None) -> dict:
    """Payload da aba para o exercício de `base`; `mes` = acumulado de janeiro até o mês."""
    ano = base["ano"]
    mes = mes if (mes and 1 <= mes <= 12) else None
    cx = _Ctx(base, mes)
    linhas = _linhas(cx)
    for x in linhas:
        _taxas(x)
    nomes = {**base["nomes_global"], **base["tfe"]["nomes_orgao"]}
    cruz = _cruzado(cx)
    ref_pos = base["ref_cruzado"]["posicao"]
    por_orgao: dict[str, list] = defaultdict(list)
    for x in linhas:
        por_orgao[x["orgao"]].append(x)
    orgaos = []
    for cod, ls in por_orgao.items():
        vivas = [x for x in ls if any(x[k] for k in ("dotacao_inicial", "dotacao_atualizada", "empenhado", "liquidado",
                                                     "pago_balancete", "rp_pago_balancete", "ob_total"))]
        if not vivas:                    # órgão que só aparece com linhas zeradas (extinto, renomeado): não é linha
            continue
        o = _somar(vivas)
        exe = {x["executivo"] for x in vivas}
        o.update(orgao=cod, nome=nomes.get(cod) or (vivas[0]["nome"] if o["n_ugs"] == 1 else f"Órgão {cod}"),
                 executivo=exe.pop() if len(exe) == 1 else None,
                 orgao_inferido=any(x["orgao_inferido"] for x in vivas), execucao_ate=cx.ate if o["empenhado"]
                 is not None else None)
        o["cruzado"], o["cruzado_pct"] = cruz.get(cod, (None, None))
        cruza = o["cruzado_pct"] is None or o["cruzado_pct"] > TOL_CRUZADO_PCT
        o["pago_comparavel"] = not cruza and not cx.parcial
        o["sem_taxa"] = cruza and cx.fonte != "TFE"     # visão por UG: dotação e empenho também trocam de órgão
        o["dot_defasada"] = cx.dot_defasada
        _taxas(o)
        o["notas"] = []
        do_orgao = {x["ug"] for x in vivas}
        reserva = sum(p["reserva"] for p in base["tfe"]["pares"]
                      if (p["orgao"] == cod if cx.fonte == "TFE" else p["ug"] in do_orgao))
        if reserva > 0:
            o["notas"].append(f"R$ {fmt_brl(reserva)} da dotação atualizada é reserva de contingência (não se empenha)")
        if cruza:
            quanto = ("o cadastro do TFE não tem este órgão para medir quanto do crédito cruza de órgão"
                      if o["cruzado_pct"] is None else
                      f"crédito que cruza de órgão por descentralização: R$ {fmt_brl(o['cruzado'])}, o equivalente a "
                      f"{_pct_br(o['cruzado_pct'])} do empenhado do órgão (medido no TFE, posição {ref_pos})")
            o["notas"].append(quanto + ("; a OB não diz de qual órgão é o crédito — sem taxa de pago por OB neste "
                                        "nível (ver por UG e a taxa do balancete)" if cx.fonte == "TFE" else
                                        "; nesta visão a execução segue a UG e a dotação segue o órgão — sem taxa "
                                        "neste nível (ver por UG)"))
        elif cx.parcial:
            o["notas"].append("balancete em posição parcial: sem taxa de pago por OB (períodos não se alinham)")
        if o["faltam"].get("pago_siafe"):
            o["notas"].append(f"{o['faltam']['pago_siafe']} UG com pagamento no balancete e sem OB orçamentária na "
                              "base do SIAFE neste período — pago do SIAFE incompleto, sem taxa")
        for k, rot in (("dotacao_atualizada", "dotação atualizada"), ("empenhado", "execução publicada")):
            if o["faltam"].get(k):
                o["notas"].append(f"{o['faltam'][k]} de {len(vivas)} linha(s) sem {rot} neste período — soma "
                                  "incompleta, sem taxa")
        if o["orgao_inferido"]:
            o["notas"].append("órgão inferido pelos dois primeiros dígitos da UG (UG fora do cadastro do TFE)")
        o["ugs"] = sorted(vivas, key=lambda x: (-(x["empenhado"] or x["dotacao_atualizada"] or x["dotacao_inicial"]
                                                  or x["ob_total"] or 0), x["ug"]))
        o["uos"] = sorted(({"uo": u["uo"], "nome": u["nome"], "dotacao_inicial": u["dot_ini"],
                            "dotacao_atualizada": u["dot_atual"], "empenhado": u["emp"], "liquidado": u["liq"],
                            "pago_balancete": u["pago"], "taxa_empenho": _taxa(u["emp"], u["dot_atual"]),
                            "taxa_pago_balancete": _taxa(u["pago"], u["dot_atual"])}
                           for u in base["tfe"]["uos"] if u["orgao"] == cod and cx.fonte == "TFE"
                           and any(u[k] for k in ("dot_ini", "dot_atual", "emp", "liq", "pago"))),
                          key=lambda u: (-u["dotacao_atualizada"], u["uo"]))
        orgaos.append(o)
    orgaos.sort(key=lambda o: (-(o["dotacao_atualizada"] or o["dotacao_inicial"] or o["empenhado"]
                                 or o["ob_total"] or 0), o["orgao"]))
    todas = [x for o in orgaos for x in o["ugs"]]
    total = _somar(todas) if todas else {}
    if total:
        total["pago_comparavel"] = not cx.parcial    # no Estado inteiro o crédito cruzado se cancela
        total["dot_defasada"] = cx.dot_defasada
        _taxas(total)
        total["n_orgaos"] = len(orgaos)

    tem_taxa = any(o["taxa_empenho"] is not None for o in orgaos)
    rankings = {k: _ranking(orgaos, k) for k in
                (("taxa_empenho", "taxa_pago_balancete", "taxa_pago", "taxa_pago_empenhado") if tem_taxa
                 else ("taxa_empenho_inicial",))}

    tfe_pos, cge = base["tfe"]["posicao"], base["cge"]
    fontes = []
    if tfe_pos:
        fontes.append(f"dados abertos do Estado, tfe-despesa, posição {tfe_pos}")
    if cge["ugs"]:
        fontes.append(f"painel da CGE (Executivo), meses 1 a {cge['mes_completo']} de {ano}, fonte atualizada em "
                      f"{_data_br(cge['atualizado'])}")
    if base["ob"]["max_data"]:
        fontes.append(f"SIAFE-Rio, OB orçamentária contabilizada emitida até {_data_br(base['ob']['max_data'])}")
    sem_exec = [o["orgao"] for o in orgaos if o["empenhado"] is None]
    cont: dict[str, dict[str, int]] = {k: defaultdict(int) for k in _ESTADOS}
    vistos: set[str] = set()
    for x in todas:                      # estado é da UG: conta cada UG uma vez
        if x["ug"] in vistos and not x["espera_ob"]:
            continue
        for k in _ESTADOS:
            if k == "pago_siafe" and not x["espera_ob"]:
                continue
            if k != "pago_siafe" and x["ug"] in vistos:
                continue
            cont[k][x["estados"][k]] += 1
        vistos.add(x["ug"])
    if mes:
        periodo = f"janeiro a {MESES[mes - 1]} de {ano}" if mes > 1 else f"janeiro de {ano}"
    elif cx.parcial:
        periodo = (f"{ano}, posição {tfe_pos} do TFE (arquivo publicado em {_data_br(base['tfe']['publicado_em'])}: "
                   f"{MESES[cx.ate - 1]} incompleto)")
    elif cx.ate and cx.ate < 12:
        periodo = f"{ano}, janeiro a {MESES[cx.ate - 1]} (até onde a fonte publicou)"
    else:
        periodo = f"exercício de {ano}"
    visao, visao_txt = _VISAO[cx.fonte]
    return {
        "ok": True, "versao": VERSAO, "exercicio": ano, "mes": mes, "periodo": periodo,
        "execucao_fonte": cx.fonte, "execucao_ate": cx.ate, "execucao_parcial": cx.parcial,
        "ob_ate_mes": cx.corte, "visao": visao, "cruzado_posicao_ref": ref_pos,
        "dotacao_defasada": cx.dot_defasada, "dotacao_posicao": tfe_pos,
        "visao_descricao": visao_txt, "exercicios": exs or [],
        "meses_com_execucao": sorted(set(range(1, (cge["mes_completo"] if cge["ugs"] else 0) + 1))
                                     | ({int(tfe_pos[:2])} if tfe_pos else set())),
        "proveniencia": {
            "fonte": "; ".join(fontes) or "nenhuma fonte com este exercício",
            "data_ref": periodo,
            "cobertura": (f"{len(orgaos)} órgãos e {total.get('n_ugs', 0)} UG com dotação, execução ou OB; visão "
                          f"{visao_txt}" + (f"; {len(sem_exec)} órgão(s) sem execução publicada neste período "
                                            "(INDISPONÍVEL, não zero)" if sem_exec else "")),
            "estado": _pior(*(o["estados"]["empenhado"] for o in orgaos)) if orgaos else I,
            "natureza": "indice", "esfera": "estadual",
        },
        "colunas": COLUNAS, "ressalva": RESSALVA, "piso_ranking": PISO_RANKING,
        "tolerancias": {"reais": TOL_REAIS, "pago_pct": TOL_PAGO_PCT, "cruzado_pct": TOL_CRUZADO_PCT},
        "total": total, "orgaos": orgaos, "rankings": rankings,
        "estados_por_coluna": {k: dict(v) for k, v in cont.items()},
        "controles": {
            "empenhado_que_cruza_de_orgao": round(sum(abs(e) for ug, org, e in base["ref_cruzado"]["pares"]
                                                      if cx.dono(ug)[0] != org), 2) if ref_pos else None,
            "intraorcamentario_empenhado": round(sum(p["intra_emp"] for p in base["tfe"]["pares"]), 2)
            if tfe_pos else None,
            "ob_sem_numero_fora": {"n": base["ob"]["sem_numero"][0], "valor": base["ob"]["sem_numero"][1]},
            "ob_emitida_ate": base["ob"]["max_data"],
        },
        "gerado_em": base.get("gerado_em"),
    }


def calcular(ano: int | None = None, mes: int | None = None, db=None, db_abertos=None) -> dict:
    """Atalho sem cache (linha de comando e testes): lê a base e monta."""
    exs = exercicios(db, db_abertos)
    ano = ano or exercicio_padrao(exs)
    if ano is None or ano not in {e["ano"] for e in exs}:
        return {"ok": False, "erro": f"exercício {ano} não está na base", "exercicios": exs}
    return montar(carregar(ano, db, db_abertos), mes, exs)


if __name__ == "__main__":     # pragma: no cover — conferência à mão
    import json
    import sys
    d = calcular(int(sys.argv[1]) if len(sys.argv) > 1 else None, int(sys.argv[2]) if len(sys.argv) > 2 else None)
    for o in d.get("orgaos", []):
        o.pop("ugs", None)
    print(json.dumps(d, ensure_ascii=False, indent=1))
