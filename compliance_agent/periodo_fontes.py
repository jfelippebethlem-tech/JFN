# -*- coding: utf-8 -*-
"""As FONTES datadas do painel, cada uma com o seu campo de data, a sua medida e a sua cobertura.

Uma entrada por (fonte × esfera). Estado e Prefeitura nunca dividem uma entrada: a esfera de
contrato/aditivo do PNCP é a esfera OFICIAL do ente (``classificar_esfera`` — a mesma régua das abas
Aditivos, Conluio e Sobrepreço), porque ``pcrj_contratos``, apesar do nome, guarda TODOS os entes.

Vocabulário das medidas (nunca trocar um pelo outro — regra absoluta nº 2 da casa):
- ``pago``          OB do SIAFE com status **Contabilizado** — o único "pago" desta casa;
- ``pago_relatorio`` "Valor Pago" do relatório anual de execução (TFE/ContasRio) — acumulado do
                    exercício, não é OB;
- ``empenhado``/``liquidado`` — reserva e reconhecimento da dívida; não é pagamento;
- ``valor_inicial``/``valor_global``/``valor_contrato`` — valor CONTRATADO, não pago;
- ``valor_acrescido`` — o que o termo aditivo declara; ``valor_publicado`` — o que o extrato do
  DOERJ declara.

Cada fonte devolve linhas ``(ano, mes, n, {medida: centavos})`` para ``periodo.quebra`` e, para o
recorte filtrado, os maiores registros do período (``itens``).
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import date
from typing import Callable

from compliance_agent import periodo as P

TOP = 15


@dataclass(frozen=True)
class Fonte:
    id: str
    esfera: str                    # estado | prefeitura | transversal
    rotulo: str
    medidas: tuple                 # ids das medidas, na ordem de exibição
    rotulos_medidas: dict
    campo_data: str                # o que a data É (vai para a tela)
    origem: str                    # tabela/fonte citada
    granularidade: str             # mes | ano
    agregar: Callable              # con, hoje -> (linhas, Cobertura, extra)
    itens: Callable                # con, ano, mes -> list[dict]


def _mes_corrente(hoje: date) -> tuple[int, int]:
    return hoje.year, hoje.month


def _ym_max(con, sql) -> tuple[int, int] | None:
    v = con.execute(sql).fetchone()
    return P.ano_mes(v[0]) if v and v[0] else None


# ── OB SIAFE (Estado) ────────────────────────────────────────────────────────────────────────────
_OB_A, _OB_M = P.sql_ano_mes("data_emissao", "br")


def _ob_agregar(con, hoje):
    linhas = [(a, m, n, {"pago": c}) for a, m, n, c in con.execute(
        f"SELECT {_OB_A}, {_OB_M}, COUNT(*), {P.sql_centavos('valor')} FROM ob_orcamentaria_siafe "
        f"WHERE status='Contabilizado' GROUP BY 1, 2")]
    anos = {a for a, *_ in linhas if a}
    fim = max(((a, m) for a, m, *_ in linhas if a and m and 1 <= m <= 12), default=_mes_corrente(hoje))
    fim = min(fim, _mes_corrente(hoje))
    inicio = (2016, 1)
    # O que NÃO é pago, declarado ao lado (não entra em nenhuma soma da quebra).
    fora = [{"status": s, "n": n, "valor": P.reais(c)} for s, n, c in con.execute(  # ob-qualquer-status
        f"SELECT status, COUNT(*), {P.sql_centavos('valor')} FROM ob_orcamentaria_siafe "
        "WHERE status IS NOT 'Contabilizado' GROUP BY 1 ORDER BY 3 DESC")]
    cob = P.Cobertura(
        inicio=inicio, fim=fim, anos_sem_coleta=frozenset(set(range(inicio[0], fim[0] + 1)) - anos),
        # 2016–2020: ~2,2 mil OB/ano coletadas contra ~180 mil+ a partir de 2021
        # (medido em 14/11/2026). Ano assim não pode sair "ok" ao lado dos completos — sai PARCIAL.
        anos_parciais=frozenset(range(2016, 2021)),
        mes_corrente=_mes_corrente(hoje), zero_possivel=False,
        nota=("SIAFE-Rio 1 (2016–2023) e SIAFE-Rio 2 (2021+); 2016–2020 com coleta mínima (~2,2 mil OB por ano). "
              "A coleta é PARCIAL por unidade gestora: todo "
              "valor é PISO do que o Estado pagou, e mês sem OB coletada é lacuna de coleta (INDISPONÍVEL), "
              "não mês sem pagamento."))
    return linhas, cob, {"fora_do_pago": fora}


def _ob_itens(con, ano, mes):
    cond, par = "exercicio=?", [ano]
    if mes:
        cond += " AND substr(data_emissao,4,2)=?"
        par.append("%02d" % mes)
    return [{"doc": P.mascarar_doc(d), "nome": nm or "—", "n": n, "valor": P.reais(c), "ugs": u}
            for d, nm, n, c, u in con.execute(
                f"SELECT credor, MAX(nome_credor), COUNT(*), {P.sql_centavos('valor')}, COUNT(DISTINCT ug_emitente) "
                f"FROM ob_orcamentaria_siafe WHERE status='Contabilizado' AND {cond} GROUP BY credor ORDER BY 4 DESC LIMIT {TOP}", par)]


# ── Execução orçamentária anual (Estado — TFE; Prefeitura — ContasRio) ──────────────────────────
def _exec_estado_agregar(con, hoje):
    linhas, pos = [], {}
    for ex, posicao, n, e, li, pg in con.execute(
            f"SELECT exercicio, MAX(posicao), COUNT(*), {P.sql_centavos('empenhado')}, {P.sql_centavos('liquidado')}, "
            f"{P.sql_centavos('pago')} FROM despesa_execucao GROUP BY exercicio"):
        a = int(ex)
        linhas.append((a, None, n, {"empenhado": e, "liquidado": li, "pago_relatorio": pg}))
        pos[a] = posicao
    anos = sorted(pos) or [hoje.year]
    parciais = frozenset(a for a, p in pos.items() if not str(p or "").startswith("12/"))
    cob = P.Cobertura(inicio=(anos[0], 1), fim=(anos[-1], 12), anos_parciais=parciais, zero_possivel=False,
                      nota=("Relatório anual de execução da despesa (Transparência Fiscal do Estado). A fonte publica "
                            "o ACUMULADO na posição indicada — não existe valor por mês. Ano com posição antes de "
                            "dezembro é parcial."))
    return linhas, cob, {"posicao_por_ano": {str(a): p for a, p in sorted(pos.items())}}


def _exec_estado_itens(con, ano, mes):
    if mes:
        return []
    return [{"nome": o or "—", "n": n, "valor": P.reais(pg), "empenhado": P.reais(e)}
            for o, n, e, pg in con.execute(
                f"SELECT orgao, COUNT(*), {P.sql_centavos('empenhado')}, {P.sql_centavos('pago')} "
                f"FROM despesa_execucao WHERE exercicio=? GROUP BY orgao ORDER BY 4 DESC LIMIT {TOP}", (str(ano),))]


def _exec_pref_agregar(con, hoje):
    linhas = [(int(ex), None, n, {"empenhado": e, "liquidado": li, "pago_relatorio": pg})
              for ex, n, e, li, pg in con.execute(
                  f"SELECT exercicio, COUNT(*), {P.sql_centavos('empenhado')}, {P.sql_centavos('liquidado')}, "
                  f"{P.sql_centavos('pago')} FROM pcrj_despesa GROUP BY exercicio")]
    anos = sorted(a for a, *_ in linhas) or [hoje.year]
    cob = P.Cobertura(inicio=(anos[0], 1), fim=(anos[-1], 12), zero_possivel=False,
                      nota=("ContasRio — despesa do Município por credor, acumulada no exercício (2019–2023 na base). "
                            "A fonte não traz a data do pagamento: não existe valor por mês."))
    return linhas, cob, {}


def _exec_pref_itens(con, ano, mes):
    if mes:
        return []
    return [{"doc": P.mascarar_doc(d), "nome": nm or "—", "n": n, "valor": P.reais(pg), "empenhado": P.reais(e)}
            for d, nm, n, e, pg in con.execute(
                f"SELECT credor_documento, MAX(credor_nome), COUNT(*), {P.sql_centavos('empenhado')}, "
                f"{P.sql_centavos('pago')} FROM pcrj_despesa WHERE exercicio=? GROUP BY credor_documento "
                f"ORDER BY 5 DESC LIMIT {TOP}", (ano,))]


# ── PNCP: contratos e aditivos, separados por esfera ─────────────────────────────────────────────
def _classificador(con):
    from compliance_agent.collectors.pncp_resultados import classificar_esfera, esferas_por_ente
    oficial = esferas_por_ente(con)

    def esfera_de(cc, orgao_nome, unidade):
        cnpj_ente = re.sub(r"\D", "", str(cc or "").split("-")[0])[:14]
        return classificar_esfera({"orgao_cnpj": cnpj_ente, "orgao_nome": orgao_nome or "",
                                   "unidade_nome": unidade or "", "municipio": ""}, oficial)
    return esfera_de


def _contratos_agregar_de(esfera):
    def agregar(con, hoje):
        esf = _classificador(con)
        acc: dict = {}
        futuras = 0
        for cc, org, uni, dt, vi, vg in con.execute(
                "SELECT numero_controle_pncp, orgao_nome, unidade, data_assinatura, valor_inicial, valor_global "
                "FROM pcrj_contratos"):
            if esf(cc, org, uni) != esfera:
                continue
            am = P.ano_mes(dt)
            if am and am > _mes_corrente(hoje):
                futuras += 1
            k = am or (None, None)
            b = acc.setdefault(k, [0, 0, 0])
            b[0] += 1
            b[1] += P.centavos(vi)
            b[2] += P.centavos(vg)
        linhas = [(a, m, n, {"valor_inicial": ci, "valor_global": cg}) for (a, m), (n, ci, cg) in acc.items()]
        datas = [k for k in acc if k[0]]
        inicio = min(datas, default=_mes_corrente(hoje))
        cob = P.Cobertura(inicio=inicio, fim=_mes_corrente(hoje), mes_corrente=_mes_corrente(hoje),
                          nota=("PNCP (Lei 14.133/2021), contratos coletados pela casa desde "
                                f"{P.MESES[inicio[1] - 1]}/{inicio[0]}. Data = assinatura do contrato. Valor = "
                                "CONTRATADO (inicial e global com aditivos), não pago."))
        return linhas, cob, {"datas_futuras": futuras}
    return agregar


def _contratos_itens_de(esfera):
    def itens(con, ano, mes):
        esf = _classificador(con)
        pref = f"{ano:04d}-{mes:02d}" if mes else f"{ano:04d}"
        out = []
        for cc, org, uni, forn, doc, obj, vi, vg, dt in con.execute(
                "SELECT numero_controle_pncp, orgao_nome, unidade, fornecedor_nome, fornecedor_documento, objeto, "
                "valor_inicial, valor_global, data_assinatura FROM pcrj_contratos WHERE substr(data_assinatura,1,?)=?",
                (len(pref), pref)):
            if esf(cc, org, uni) == esfera:
                out.append({"id": cc, "nome": forn or "—", "doc": P.mascarar_doc(doc), "orgao": uni or org or "—",
                            "objeto": (obj or "")[:160], "data": dt, "valor": P.reais(P.centavos(vg)),
                            "valor_inicial": P.reais(P.centavos(vi))})
        out.sort(key=lambda x: -x["valor"])
        return out[:TOP]
    return itens


def _aditivos_rows(con, where="", par=()):
    return con.execute(
        "SELECT a.numero_controle_pncp, c.orgao_nome, c.unidade, a.data_assinatura, a.valor_acrescido, "
        "c.fornecedor_nome, c.fornecedor_documento, a.objeto, a.numero_termo, a.tipo_termo "
        "FROM contrato_aditivo a LEFT JOIN pcrj_contratos c ON c.numero_controle_pncp=a.numero_controle_pncp "
        + where, par)


def _aditivos_agregar_de(esfera):
    def agregar(con, hoje):
        esf = _classificador(con)
        acc: dict = {}
        for cc, org, uni, dt, va, *_ in _aditivos_rows(con):
            if esf(cc, org, uni) != esfera:
                continue
            b = acc.setdefault(P.ano_mes(dt) or (None, None), [0, 0])
            b[0] += 1
            b[1] += P.centavos(va)
        linhas = [(a, m, n, {"valor_acrescido": c}) for (a, m), (n, c) in acc.items()]
        inicio = min((k for k in acc if k[0]), default=_mes_corrente(hoje))
        cob = P.Cobertura(inicio=inicio, fim=_mes_corrente(hoje), mes_corrente=_mes_corrente(hoje),
                          nota=("Termos aditivos publicados no PNCP. Data = assinatura do termo; termo sem data "
                                "publicada fica em \"sem data\". Valor = acréscimo declarado no termo (pode incluir "
                                "reajuste quando o órgão lança assim) — não é pagamento."))
        return linhas, cob, {}
    return agregar


def _aditivos_itens_de(esfera):
    def itens(con, ano, mes):
        esf = _classificador(con)
        pref = f"{ano:04d}-{mes:02d}" if mes else f"{ano:04d}"
        out = []
        for cc, org, uni, dt, va, forn, doc, obj, nt, tt in _aditivos_rows(
                con, "WHERE substr(a.data_assinatura,1,?)=?", (len(pref), pref)):
            if esf(cc, org, uni) == esfera:
                out.append({"id": cc, "nome": forn or "—", "doc": P.mascarar_doc(doc), "orgao": uni or org or "—",
                            "objeto": (obj or "")[:160], "data": dt, "valor": P.reais(P.centavos(va)),
                            "termo": nt or tt or ""})
        out.sort(key=lambda x: -x["valor"])
        return out[:TOP]
    return itens


# ── TCE-RJ: contratações do Estado ──────────────────────────────────────────────────────────────
_TC_A, _TC_M = P.sql_ano_mes("data_contratacao", "iso")


def _tcerj_agregar(con, hoje):
    linhas = [(a, m, n, {"valor_contrato": c}) for a, m, n, c in con.execute(
        f"SELECT {_TC_A}, {_TC_M}, COUNT(*), {P.sql_centavos('valor_contrato')} FROM contratos_tcerj "
        "WHERE status IS NOT 'Cancelado' GROUP BY 1, 2")]
    canc = con.execute("SELECT COUNT(*) FROM contratos_tcerj WHERE status='Cancelado'").fetchone()[0]
    fim = _ym_max(con, "SELECT MAX(substr(data_contratacao,1,10)) FROM contratos_tcerj") or _mes_corrente(hoje)
    cob = P.Cobertura(inicio=(2023, 1), fim=min(fim, _mes_corrente(hoje)), mes_corrente=_mes_corrente(hoje),
                      nota=("Espelho de contratações do TCE-RJ (2023+). Data = data da contratação. Valor = "
                            "CONTRATADO, não pago. Canceladas ficam fora da soma."))
    return linhas, cob, {"canceladas_fora": canc}


def _tcerj_itens(con, ano, mes):
    pref = f"{ano:04d}-{mes:02d}" if mes else f"{ano:04d}"
    return [{"id": i, "nome": f or "—", "doc": P.mascarar_doc(d), "orgao": u or "—", "objeto": (o or "")[:160],
             "data": (dt or "")[:10], "valor": P.reais(c)}
            for i, f, d, u, o, dt, c in con.execute(
                "SELECT processo, fornecedor, cnpj, unidade, objeto, data_contratacao, "
                "CAST(ROUND(COALESCE(valor_contrato,0)*100) AS INTEGER) FROM contratos_tcerj "
                f"WHERE status IS NOT 'Cancelado' AND substr(data_contratacao,1,?)=? ORDER BY 7 DESC LIMIT {TOP}",
                (len(pref), pref))]


# ── TAC do DOERJ (Estado) ────────────────────────────────────────────────────────────────────────
_TAC_A, _TAC_M = P.sql_ano_mes("data_doe", "iso")


def _tac_agregar(con, hoje):
    linhas = [(a, m, n, {"valor_publicado": c}) for a, m, n, c in con.execute(
        f"SELECT {_TAC_A}, {_TAC_M}, COUNT(*), {P.sql_centavos('valor')} FROM doerj_tac GROUP BY 1, 2")]
    inicio = min(((a, m) for a, m, *_ in linhas if a), default=_mes_corrente(hoje))
    fim = _ym_max(con, "SELECT MAX(data_doe) FROM doerj_tac") or _mes_corrente(hoje)
    sem_valor = con.execute("SELECT COUNT(*) FROM doerj_tac WHERE valor IS NULL").fetchone()[0]
    cob = P.Cobertura(inicio=inicio, fim=fim, parcial_ate=(2026, 8), mes_corrente=_mes_corrente(hoje),
                      nota=("Extratos de Termo de Ajuste de Contas no DOERJ. Data = publicação no Diário Oficial. "
                            "Leitura do PDF INTEGRAL só desde 09/09/2026 — antes disso a captura é parcial. "
                            "Valor = PUBLICADO no extrato, não OB."))
    return linhas, cob, {"sem_valor_legivel": sem_valor}


def _tac_itens(con, ano, mes):
    pref = f"{ano:04d}-{mes:02d}" if mes else f"{ano:04d}"
    return [{"nome": f or "(fornecedor não lido)", "doc": P.mascarar_doc(d), "n": n, "valor": P.reais(c), "orgaos": o}
            for f, d, n, c, o in con.execute(
                f"SELECT fornecedor, MAX(cnpj), COUNT(*), {P.sql_centavos('valor')}, COUNT(DISTINCT orgao) FROM doerj_tac "
                f"WHERE substr(data_doe,1,?)=? GROUP BY fornecedor ORDER BY 4 DESC LIMIT {TOP}", (len(pref), pref))]


# ── Sanções (CEIS/CNEP) e alertas (transversal) ─────────────────────────────────────────────────
_ALVO = {"estado": ("estadual", "RJ"), "prefeitura": ("municipal", "RJ")}


def _sancoes_que_alcancam(con, esfera, where="", par=()):
    """Sanções CEIS/CNEP que VEDAM contratar com o ente (régua única: ``sancao_abrangencia.veda_ente``, a mesma das
    abas Sancionadas). Sanção de outro ente ou restrita a outro órgão não entra — CNF-03."""
    from compliance_agent.sancao_abrangencia import sql_campos_ceis, veda_ente
    esf_alvo, uf_alvo = _ALVO[esfera]
    cols = ("cadastro", "cpf_cnpj", "nome", "categoria", "data_inicio", "data_fim", "orgao", "uf", "fundamentacao",
            "abrangencia", "esfera_sancionador", "data_publicacao")
    sql = (f"SELECT cadastro, cpf_cnpj, nome, categoria, data_inicio, data_fim, orgao, uf, fundamentacao, "
           f"{sql_campos_ceis(con)} FROM sancoes_federais {where}")
    dentro, fora = [], 0
    for r in con.execute(sql, par):
        s = dict(zip(cols, r))
        if veda_ente(s, esf_alvo, uf_alvo)["veda"]:
            dentro.append(s)
        else:
            fora += 1
    return dentro, fora


def _sanc_agregar_de(esfera):
    def agregar(con, hoje):
        dentro, fora = _sancoes_que_alcancam(con, esfera)
        acc: dict = {}
        for s in dentro:
            k = P.ano_mes(s["data_inicio"]) or (None, None)
            acc[k] = acc.get(k, 0) + 1
        linhas = [(a, m, n, {}) for (a, m), n in acc.items()]
        inicio = min((k for k in acc if k[0]), default=_mes_corrente(hoje))
        cob = P.Cobertura(inicio=inicio, fim=_mes_corrente(hoje), mes_corrente=_mes_corrente(hoje),
                          nota=("Cadastros federais CEIS/CNEP (CGU), espelho completo. Data = início da vigência da "
                                "sanção. Conta só a sanção que VEDA contratar com "
                                + ("o Estado do RJ" if esfera == "estado" else "o Município do Rio")
                                + " (abrangência pela lei e pela esfera do sancionador). Quem contratou durante a "
                                  "vigência está na lista da aba."))
        return linhas, cob, {"sem_alcance_fora": fora}
    return agregar


def _sanc_itens_de(esfera):
    def itens(con, ano, mes):
        pref = f"{ano:04d}-{mes:02d}" if mes else f"{ano:04d}"
        dentro, _ = _sancoes_que_alcancam(con, esfera, "WHERE substr(data_inicio,1,?)=?", (len(pref), pref))
        dentro.sort(key=lambda s: s["data_inicio"] or "", reverse=True)
        return [{"nome": s["nome"] or "—", "doc": P.mascarar_doc(s["cpf_cnpj"]), "orgao": (s["orgao"] or "—")[:80],
                 "data": s["data_inicio"], "objeto": f"{s['cadastro']} · {(s['categoria'] or '')[:80]}",
                 "fim": s["data_fim"]} for s in dentro[:TOP]]
    return itens


_AL_A, _AL_M = P.sql_ano_mes("created_at", "iso")


def _alertas_agregar(con, hoje):
    linhas = [(a, m, n, {}) for a, m, n in con.execute(
        f"SELECT {_AL_A}, {_AL_M}, COUNT(*) FROM alertas WHERE status IS NOT 'descartado' GROUP BY 1, 2")]
    inicio = min(((a, m) for a, m, *_ in linhas if a), default=_mes_corrente(hoje))
    desc = con.execute("SELECT COUNT(*) FROM alertas WHERE status='descartado'").fetchone()[0]
    cob = P.Cobertura(inicio=inicio, fim=_mes_corrente(hoje), mes_corrente=_mes_corrente(hoje),
                      nota=("Alertas em aberto ou confirmados (descartados pela triagem ficam fora). Data = quando o "
                            "SISTEMA gerou o alerta, não a data do ato: a tabela não guarda a data do fato."))
    return linhas, cob, {"descartados_fora": desc}


def _alertas_itens(con, ano, mes):
    pref = f"{ano:04d}-{mes:02d}" if mes else f"{ano:04d}"
    return [{"nome": t or "—", "n": n, "objeto": f"🔴 {a} · 🟡 {n - a}"}
            for t, n, a in con.execute(
                "SELECT tipo, COUNT(*), SUM(severidade='alta') FROM alertas WHERE status IS NOT 'descartado' "
                f"AND substr(created_at,1,?)=? GROUP BY tipo ORDER BY 2 DESC LIMIT {TOP}", (len(pref), pref))]


_R_CONTR = {"valor_inicial": "Valor inicial contratado", "valor_global": "Valor global (com aditivos)"}
_R_EXEC = {"empenhado": "Empenhado", "liquidado": "Liquidado", "pago_relatorio": "Pago (relatório anual)"}

FONTES: dict[str, Fonte] = {f.id: f for f in (
    Fonte("ob_siafe", "estado", "Pagamentos — OB Contabilizada (SIAFE)", ("pago",),
          {"pago": "Pago (OB Contabilizada)"}, "data de emissão da OB", "SIAFE-Rio · ob_orcamentaria_siafe",
          "mes", _ob_agregar, _ob_itens),
    Fonte("execucao_estado", "estado", "Execução orçamentária anual — empenho, liquidação, pagamento",
          ("empenhado", "liquidado", "pago_relatorio"), _R_EXEC, "exercício (posição acumulada)",
          "Transparência Fiscal RJ · despesa_execucao", "ano", _exec_estado_agregar, _exec_estado_itens),
    Fonte("contratos_estado", "estado", "Contratos do Estado (PNCP)", ("valor_inicial", "valor_global"), _R_CONTR,
          "data de assinatura do contrato", "PNCP · pcrj_contratos (esfera oficial do ente)", "mes",
          _contratos_agregar_de("estado"), _contratos_itens_de("estado")),
    Fonte("contratacoes_tcerj", "estado", "Contratações do Estado (TCE-RJ)", ("valor_contrato",),
          {"valor_contrato": "Valor contratado"}, "data da contratação", "TCE-RJ · contratos_tcerj", "mes",
          _tcerj_agregar, _tcerj_itens),
    Fonte("aditivos_estado", "estado", "Termos aditivos — Estado (PNCP)", ("valor_acrescido",),
          {"valor_acrescido": "Acréscimo declarado no termo"}, "data de assinatura do termo aditivo",
          "PNCP · contrato_aditivo", "mes", _aditivos_agregar_de("estado"), _aditivos_itens_de("estado")),
    Fonte("tac_estado", "estado", "TAC publicados no DOERJ", ("valor_publicado",),
          {"valor_publicado": "Valor publicado no extrato"}, "data de publicação no DOERJ", "DOERJ · doerj_tac",
          "mes", _tac_agregar, _tac_itens),
    Fonte("contratos_prefeitura", "prefeitura", "Contratos da Prefeitura do Rio (PNCP)",
          ("valor_inicial", "valor_global"), _R_CONTR, "data de assinatura do contrato",
          "PNCP · pcrj_contratos (esfera oficial do ente)", "mes",
          _contratos_agregar_de("prefeitura"), _contratos_itens_de("prefeitura")),
    Fonte("aditivos_prefeitura", "prefeitura", "Termos aditivos — Prefeitura do Rio (PNCP)", ("valor_acrescido",),
          {"valor_acrescido": "Acréscimo declarado no termo"}, "data de assinatura do termo aditivo",
          "PNCP · contrato_aditivo", "mes", _aditivos_agregar_de("prefeitura"), _aditivos_itens_de("prefeitura")),
    Fonte("despesa_prefeitura", "prefeitura", "Despesa da Prefeitura por exercício (ContasRio)",
          ("empenhado", "liquidado", "pago_relatorio"), _R_EXEC, "exercício (acumulado anual)",
          "ContasRio · pcrj_despesa", "ano", _exec_pref_agregar, _exec_pref_itens),
    Fonte("sancoes_estado", "estado", "Sanções que impedem contratar com o Estado (CEIS/CNEP)", (), {},
          "início da vigência da sanção", "CGU · sancoes_federais", "mes",
          _sanc_agregar_de("estado"), _sanc_itens_de("estado")),
    Fonte("sancoes_prefeitura", "prefeitura", "Sanções que impedem contratar com o Município do Rio (CEIS/CNEP)",
          (), {}, "início da vigência da sanção", "CGU · sancoes_federais", "mes",
          _sanc_agregar_de("prefeitura"), _sanc_itens_de("prefeitura")),
    Fonte("alertas", "transversal", "Alertas de auditoria por mês de detecção", (), {},
          "data em que o sistema gerou o alerta", "JFN · alertas", "mes", _alertas_agregar, _alertas_itens),
)}


def calcular(con: sqlite3.Connection, fonte_id: str, hoje: date | None = None) -> dict:
    """Quebra completa (todos os anos e meses) de uma fonte — é o que a rota põe em cache."""
    f = FONTES[fonte_id]
    hoje = hoje or date.today()
    linhas, cob, extra = f.agregar(con, hoje)
    q = P.quebra(linhas, medidas=list(f.medidas), cobertura=cob, granularidade=f.granularidade)
    return {"fonte": meta(f), "cobertura": cob.como_dict(), "quebra": q, "extra": extra,
            "calculado_em": hoje.isoformat()}


def meta(f: Fonte) -> dict:
    return {"id": f.id, "esfera": f.esfera, "rotulo": f.rotulo, "medidas": list(f.medidas),
            "rotulos_medidas": f.rotulos_medidas, "campo_data": f.campo_data, "origem": f.origem,
            "granularidade": f.granularidade}
