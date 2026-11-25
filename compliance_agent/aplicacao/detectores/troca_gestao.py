# -*- coding: utf-8 -*-
"""E10 · detectores genéricos de TROCA DE GESTÃO, com DATA DE CORTE parametrizada (SOMBRA ⚖️, O5.3 fatia 2).

Porta as regras de `compliance_agent/governo_couto_regras.py` que comparam uma janela depois do corte com o mesmo
intervalo do ano anterior (ou com a véspera do corte). A data deixa de ser a constante da gestão Couto: é o
parâmetro `corte` (padrão = `governo_couto.INICIO`, a constante única da lente Couto — plano §3.6/§6.3 da fatia 1).
Os auxiliares de fato (data do ATO pelo DOERJ, regime próprio do contratado, rótulo de consórcio) são os canônicos
do módulo antigo, chamados sem cópia; a régua (agregação, limiares, comparação) mora aqui.

  e10.tg_direta_salto            D01 · unidade com ≥ R$ 10 mi em contratação direta, ≥ 50% do valor contratado e
                                 +20 p.p. sobre o ano anterior (regime próprio fora da conta)          ⚪ INCERTO
  e10.tg_emergencial_incumbente  D02 · contrato emergencial assinado depois do corte ao fornecedor que já tinha
                                 contrato na MESMA unidade antes dele                                   INDICIO
  e10.tg_concentracao            D05 · credor PJ com ≥ 30% do pago da UG (UG ≥ R$ 10 mi, credor ≥ R$ 5 mi)  INDICIO
  e10.tg_pico_vespera            D09 · credor com ≥ R$ 3 mi pagos na última semana antes do corte e ≥ 5× a média
                                 semanal desde 1º de janeiro                                            INDICIO
  e10.tg_credor_estreante        D10 · raiz de CNPJ sem nenhuma OB desde 2021 até a véspera e ≥ R$ 5 mi depois do
                                 corte (consórcio e grupo com histórico à parte)                       INDICIO
  e10.tg_ob_anulada              D20 · OB anulada/excluída por UG depois do corte × ano anterior (contexto:
                                 reemissão?) — NÃO é pagamento                                          ⚪ INCERTO
  e10.tg_tac_aceleracao          D16 · fornecedor que estreia em Termo de Ajuste de Contas depois do corte com
                                 ≥ R$ 1 mi reconhecidos (valor do TAC, NÃO é OB)                        INDICIO

Pago (invariante 1): `pago="canonico"` (padrão do estágio) usa `dominio.pagamento.ob_paga_sql`; `pago="antigo"`
reproduz a régua do módulo antigo (status Contabilizado com número, devolução abatida pelo valor efetivo) e só existe
para a paridade medir a régua separada do predicado. Elegibilidade (invariante 3): só item com veredito 'E'.
Indisponível ≠ 0: sem `despesa_execucao` nenhuma UG é do Executivo (declarado no resumo); sem a Receita no E10 o
rótulo "grupo com histórico" do D10 fica INDISPONÍVEL (só consórcio pelo nome) — o antigo, sem a Receita, faz o mesmo.
"""
from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal

from compliance_agent import governo_couto_regras as GC
from compliance_agent.aplicacao.detectores import Carga, Disparo, elegivel
from compliance_agent.cpf_cnpj import digitos as dig
from compliance_agent.dominio.achado import Fato, Papel
from compliance_agent.dominio.contrato_id import chave_espelho_tcerj, deduplicar
from compliance_agent.dominio.pagamento import ob_paga_sql
from compliance_agent.governo_couto import INICIO as CORTE
from compliance_agent.pericia_contabil import situacao_devolucao, valor_efetivo_ob
from compliance_agent.reporting.intel_base import reais

ANO_MIN = 2021                   # o histórico do módulo antigo começa em 2021 (revisão cética de 13/11/2026)
_DT = "substr(data_emissao,7,4)||'-'||substr(data_emissao,4,2)||'-'||substr(data_emissao,1,2)"
_ANULADA = ("Anulado", "Excluído")


# ── janelas e fatos comuns ──────────────────────────────────────────────────────────────────────────────────────
def janelas(con: sqlite3.Connection, corte: str = CORTE) -> dict:
    """corte → fim (última OB contabilizada), g1 (fim do último mês completo), b0/b1 (o mesmo intervalo um ano
    antes), p0/p1 (1º de janeiro do ano do corte → véspera do corte)."""
    gfim = con.execute(f"SELECT max({_DT}) FROM ob_orcamentaria_siafe WHERE status='Contabilizado' AND exercicio >= ? "
                       "AND trim(coalesce(numero_ob,'')) <> ''", (ANO_MIN,)).fetchone()[0]
    g1 = GC.fim_mes_anterior(gfim)
    return {"corte": corte, "gfim": gfim, "g1": g1, "b0": GC.menos_um_ano(corte), "b1": GC.menos_um_ano(g1),
            "p0": f"{corte[:4]}-01-01", "p1": (date.fromisoformat(corte) - timedelta(days=1)).isoformat()}


class _Fonte:
    """O que os auxiliares canônicos de `governo_couto_regras` esperam de um contexto: `W` com a fonte anexada como
    `m` (só leitura), sem a Receita (`tem_receita=False`: o E10 lê só a coleta bruta)."""
    tem_receita = False

    def __init__(self, con: sqlite3.Connection):
        arq = next(r[2] for r in con.execute("PRAGMA database_list") if r[1] == "main")
        self.W = sqlite3.connect(":memory:", uri=True)
        self.W.execute("ATTACH ? AS m", (f"file:{arq}?mode=ro&immutable=1",))

    def fechar(self) -> None:
        self.W.close()


_SEM_RECEITA = _Fonte.__new__(_Fonte)       # rotulo_estreia sem a Receita: só consórcio pelo nome


def _nomes_ug(con: sqlite3.Connection) -> dict:
    try:
        return {str(ug).zfill(6): n for ug, n in con.execute("SELECT ug, max(nome_ug) FROM despesa_execucao GROUP BY ug")}
    except sqlite3.OperationalError:
        return {}                                          # declarado no resumo: Executivo INDISPONÍVEL


def _executivo(nomes: dict, ug) -> bool:
    n = nomes.get(str(ug).zfill(6), "?")
    return n != "?" and not GC._OUTRO_PODER.search(n)


def _filtro_pago(con, pago: str) -> str:
    return ob_paga_sql(con) if pago == "canonico" else "status='Contabilizado'"


def _obs(con: sqlite3.Connection, d0: str, d1: str, pago: str, *, anuladas: bool = False, ug: str | None = None):
    cols = {r[1] for r in con.execute("PRAGMA table_info(ob_orcamentaria_siafe)")}
    gd = "gd" if "gd" in cols else "''"
    env = "status_envio" if "status_envio" in cols else "''"
    filtro = "status IN (?, ?)" if anuladas else _filtro_pago(con, pago)
    par = (*(_ANULADA if anuladas else ()), ANO_MIN, d0, d1, *((ug,) if ug else ()))
    # ob-qualquer-status: `filtro` é o predicado de paga (canônico, ou o antigo só na paridade) ou o de anulada (D20)
    sql = (f"SELECT numero_ob, ug_emitente, exercicio, {_DT}, credor, nome_credor, valor, processo, {gd}, {env} "
           f"FROM ob_orcamentaria_siafe WHERE {filtro} AND exercicio >= ? AND trim(coalesce(numero_ob,'')) <> '' "
           f"AND {_DT} BETWEEN ? AND ?" + (" AND ug_emitente = ?" if ug else ""))
    for num, u, ex, dt, cr, nm, v, pr, g, e in con.execute(sql, par):
        v = float(v or 0)
        if pago == "antigo" and not anuladas and (sit := situacao_devolucao(g, e)):
            v = float(valor_efetivo_ob(v, sit)[0] or 0)
        yield {"chave_e9": f"{u}|{num}|{ex}", "numero_ob": num, "ug": u, "exercicio": ex, "dt": dt, "credor": cr,
               "cnpj": dig(cr), "nome": nm, "valor": v, "processo": pr}


def _fato_ob(c: dict) -> Fato:
    return Fato(papel=Papel.SUPORTE, tipo="ob", fonte="ob_orcamentaria_siafe", referencia=str(c["numero_ob"]),
                valor=Decimal(str(round(c["valor"], 2))), descricao=f"OB da UG {c['ug']} de {c['dt']}",
                dados={"ug": c["ug"], "exercicio": c["exercicio"], "data": c["dt"], "processo": c["processo"],
                       "veredito_e9": c.get("e9")})


def _situacao(itens: list[dict]) -> str:
    """'E' (todos os itens do grupo elegíveis), 'I' (algum inelegível) ou '?' (algum indeterminado)."""
    vs = [c.get("e9") or "?" for c in itens]
    if any(v.startswith("I") for v in vs):
        return "I"
    return "E" if all(v == "E" for v in vs) else "?"


def _por_veredito(itens: list[dict]) -> dict:
    return dict(sorted(Counter(c.get("e9") or "?:SEM_LINHA_E9" for c in itens).items()))


class _Regra:
    """Contrato de detector do E10 (ver `aplicacao/detectores/__init__`) para regras de janela: `carregar` lê tudo
    uma vez por conexão (a conferência de amostra relê da fonte, uma vez, e filtra o grupo)."""
    ID = UNIDADE = VERSAO = ""

    def __init__(self, corte: str = CORTE, pago: str = "canonico"):
        self.corte, self.pago = corte, pago
        self._memo: tuple | None = None

    def _ler(self, con: sqlite3.Connection, exercicio: int | None) -> Carga:
        raise NotImplementedError

    def carregar(self, con: sqlite3.Connection, exercicio: int | None = None) -> Carga:
        carga = self._ler(con, exercicio)
        carga.contexto.update(corte=self.corte, pago=self.pago)
        return carga

    def grupo_de(self, d: Disparo) -> str:
        return d.grupo

    def carregar_grupo(self, con: sqlite3.Connection, grupo: str, exercicio: int | None = None) -> Carga:
        chave = (id(con), exercicio)
        if not self._memo or self._memo[0] != chave:
            self._memo = (chave, self.carregar(con, exercicio))
        carga = self._memo[1]
        return Carga(itens=[c for c in carga.itens if self.no_grupo(c, grupo)], contexto=carga.contexto)

    def no_grupo(self, c: dict, grupo: str) -> bool:
        return c["grupo"] == grupo


# ── D01 / D02: contratos do espelho TCE-RJ ──────────────────────────────────────────────────────────────────────
def _diretas(con) -> dict:
    out: dict[str, list] = defaultdict(list)
    for sei, ano, val, obj, af, enq, uni, forn in con.execute(
            "SELECT sei_norm, ano_processo, valor, objeto, afastamento, enquadramento_legal, unidade, fornecedor "
            "FROM compras_diretas_tcerj"):
        out[sei].append((ano, val, obj, af, enq, uni, forn))
    return out


_SQL_CT = ("SELECT processo, num_contratacao, sei_norm, valor_contrato, unidade, data_contratacao, objeto, status, cnpj, "
           "fornecedor FROM contratos_tcerj")


def contratos_espelho(con) -> tuple[list[tuple], dict]:
    """Linhas de `contratos_tcerj` (colunas de `_SQL_CT`) com o MESMO ajuste publicado mais de uma vez reduzido a uma
    linha pela chave canônica do espelho (`dominio.contrato_id.chave_espelho_tcerj`: órgão, processo canônico, CNPJ,
    valor). Fica o registro mais antigo que não está cancelado. Devolve (linhas, medida da deduplicação)."""
    linhas = con.execute(_SQL_CT).fetchall()
    return deduplicar(linhas, chave=lambda r: chave_espelho_tcerj(r[4], r[0], cnpj=r[8], valor=r[3]),
                      ordem=lambda r: (str(r[7] or "").strip() == "Cancelado", str(r[5] or ""), str(r[0]), str(r[1])),
                      valor=lambda r: r[3])


def _contrato(r, ato: dict) -> dict:
    proc, num, sei, val, uni, dc, obj, st, cnpj, forn = r
    return {"chave_e9": f"{proc}|{num}", "processo": proc, "sei": sei, "valor": float(val or 0), "unidade": uni,
            "registro": str(dc or "")[:10], "data": ato["data"], "fonte_data": ato["fonte"], "objeto": obj,
            "cnpj": dig(cnpj), "fornecedor": forn}


def _fato_ct(c: dict) -> Fato:
    return Fato(papel=Papel.SUPORTE, tipo="contrato", fonte="contratos_tcerj", referencia=str(c["processo"]),
                valor=Decimal(str(round(c["valor"], 2))), descricao=str(c["objeto"] or "")[:240],
                dados={"unidade": c["unidade"], "data_ato": c["data"], "fonte_data": c["fonte_data"],
                       "fornecedor": c["fornecedor"], "veredito_e9": c.get("e9")})


class _DiretaSalto(_Regra):
    ID, UNIDADE, VERSAO = "e10.tg_direta_salto", "contrato_tcerj", "e10-tg-d01-2"   # 2: espelho deduplicado
    MIN_DIRETA, MIN_SHARE, MIN_SALTO = 10e6, 0.5, 0.2

    def _ler(self, con, exercicio):
        jn, diretas, f = janelas(con, self.corte), _diretas(con), _Fonte(con)
        try:
            ult = (con.execute("SELECT max(substr(ingerido_em,1,10)) FROM compras_diretas_tcerj").fetchone()[0]
                   or jn["g1"])[:10]
            fim = min(GC.fim_mes_anterior(ult), jn["g1"])
            fim_b = GC.menos_um_ano(fim)
            itens, fora, desc = [], Counter(), Counter()
            fora_valor = 0.0
            linhas, dedup = contratos_espelho(con)
            for jan, d0, d1 in (("G", self.corte, fim), ("B", jn["b0"], fim_b)):
                for r in (r for r in linhas if d0 <= str(r[5] or "")[:10] <= d1):
                    proc, _, sei, val, _, dc, obj, st, cnpj, forn = r
                    ato = GC.ato_do_contrato(f, sei, proc, dc, obj, st)
                    if ato["cancelado"] or ato["nao_contrato"] or not (d0 <= ato["data"] <= d1):
                        desc[jan] += 1
                        continue
                    mot = GC._direta_de_regime_proprio(cnpj, forn, diretas.get(sei) or [])
                    if mot:
                        if jan == "G":
                            fora[mot] += 1
                            fora_valor += float(val or 0)
                        continue
                    c = _contrato(r, ato)
                    itens.append({**c, "janela": jan, "grupo": c["unidade"], "direta": sei in diretas})
        finally:
            f.fechar()
        return Carga(itens=itens, contexto={**jn, "fim": fim, "fim_b": fim_b, "ingestao_diretas": ult,
                                            "fora_da_conta": {"n": sum(fora.values()), "valor": round(fora_valor, 2),
                                                              "motivos": dict(fora)},
                                            "descartados_ato": dict(desc), "dedup_espelho": dedup})

    def detectar(self, itens, contexto=None):
        t: dict = defaultdict(lambda: {"G": [0, 0.0, 0, 0.0], "B": [0, 0.0, 0, 0.0]})
        for c in itens:
            if not elegivel(c):
                continue
            a = t[c["unidade"]][c["janela"]]
            a[0] += 1
            a[1] += c["valor"]
            if c["direta"]:
                a[2] += 1
                a[3] += c["valor"]
        out = []
        for uni in sorted(t, key=str):
            (n, v, nd, vd), (nb, vb, ndb, vdb) = t[uni]["G"], t[uni]["B"]
            sh = vd / v if v else 0
            shb = vdb / vb if vb else None
            if not (vd >= self.MIN_DIRETA and sh >= self.MIN_SHARE and (shb is None or sh - shb >= self.MIN_SALTO)):
                continue
            ms = sorted((c for c in itens if c["unidade"] == uni and c["janela"] == "G" and c["direta"] and elegivel(c)),
                        key=lambda c: (-c["valor"], str(c["processo"])))
            out.append(Disparo(
                chave=str(uni), grupo=str(uni), estado="INCERTO", motivo_estado="sinal de contexto (⚪): salto de "
                "contratação direta, sem ler o processo",
                observacao=(f"Unidade {uni}: {reais(vd)} em contratação direta ({sh:.0%} do valor contratado) entre "
                            f"{(contexto or {}).get('corte')} e {(contexto or {}).get('fim')}, contra "
                            f"{'—' if shb is None else f'{shb:.0%}'} no mesmo intervalo do ano anterior. Concessionária, "
                            "ente público contratado e estatal pela Lei das Estatais ficam fora da conta. Fonte: contratos_tcerj "
                            "× compras_diretas_tcerj."),
                entradas={"unidade": uni, "G": [n, round(v, 2), nd, round(vd, 2)], "B": [nb, round(vb, 2), ndb, round(vdb, 2)],
                          "diretos": [c["chave_e9"] for c in ms]},
                valores={"n": n, "valor": round(v, 2), "n_direta": nd, "valor_direta": round(vd, 2),
                         "share_direta": round(sh, 4), "share_direta_ano_anterior": None if shb is None else round(shb, 4),
                         "valor_direta_ano_anterior": round(vdb, 2)},
                processo=str(ms[0]["processo"]) if ms else None, evidencias=[_fato_ct(c) for c in ms[:30]]))
        return out

    def resumo(self, itens, disparos):
        return {"contratos": len(itens), "por_veredito": _por_veredito(itens),
                "por_janela": dict(Counter(c["janela"] for c in itens)), "disparos": len(disparos),
                "cobertura": _cobertura(itens),
                "soma_disparos": round(sum(d.valores["valor_direta"] for d in disparos), 2)}


class _EmergencialIncumbente(_Regra):
    ID, UNIDADE, VERSAO = "e10.tg_emergencial_incumbente", "contrato_tcerj", "e10-tg-d02-2"   # 2: espelho deduplicado

    def _ler(self, con, exercicio):
        from compliance_agent.fracionamento_emergencia import eh_emergencial
        diretas, f = _diretas(con), _Fonte(con)
        try:
            antes: dict = defaultdict(set)
            for uni, forn, cnpj in con.execute("SELECT unidade, fornecedor, cnpj FROM contratos_tcerj "
                                               "WHERE substr(data_contratacao,1,10) < ?", (self.corte,)):
                antes[uni].add(dig(cnpj) or GC.norm_nome(forn))
            itens, n_emerg_fora = [], 0
            linhas, dedup = contratos_espelho(con)
            for r in (r for r in linhas if str(r[5] or "")[:10] >= self.corte):
                proc, _, sei, _, uni, dc, obj, st, cnpj, forn = r
                if sei not in diretas or not any(eh_emergencial(o, e) for (_, _, o, _, e, _, _) in diretas[sei]):
                    continue
                ato = GC.ato_do_contrato(f, sei, proc, dc, obj, st)
                if ato["cancelado"] or ato["nao_contrato"] or not ato["data"] or ato["data"] < self.corte:
                    n_emerg_fora += 1                 # transição decidida antes do corte não é ato posterior a ele
                    continue
                c = _contrato(r, ato)
                itens.append({**c, "grupo": c["chave_e9"],
                              "incumbente": (dig(cnpj) or GC.norm_nome(forn)) in antes[uni]})
        finally:
            f.fechar()
        return Carga(itens=itens, contexto={"emergenciais_assinadas_antes_do_corte": n_emerg_fora,
                                            "dedup_espelho": dedup})

    def detectar(self, itens, contexto=None):
        out = []
        for c in sorted(itens, key=lambda c: (-c["valor"], c["chave_e9"])):
            if not (elegivel(c) and c["incumbente"]):
                continue
            out.append(Disparo(
                chave=c["chave_e9"], grupo=c["chave_e9"], estado="INDICIO", processo=str(c["processo"]),
                observacao=(f"Contrato emergencial {c['processo']} ({reais(c['valor'])}), assinado em {c['data']} "
                            f"({c['fonte_data']}), na unidade {c['unidade']}, ao fornecedor {c['fornecedor']}, que já "
                            "tinha contrato na mesma unidade antes do corte. Fonte: contratos_tcerj × "
                            "compras_diretas_tcerj (enquadramento emergencial)."),
                entradas={k: c[k] for k in ("chave_e9", "processo", "unidade", "valor", "data", "cnpj", "fornecedor")}
                | {"e9": c.get("e9")},
                valores={"valor_contrato": round(c["valor"], 2), "data_ato": c["data"]}, evidencias=[_fato_ct(c)]))
        return out

    def resumo(self, itens, disparos):
        return {"emergenciais_posteriores": len(itens), "incumbentes": sum(c["incumbente"] for c in itens),
                "por_veredito": _por_veredito(itens), "cobertura": _cobertura(itens), "disparos": len(disparos),
                "soma_disparos": round(sum(d.valores["valor_contrato"] for d in disparos), 2)}


# ── D05 / D09 / D10 / D20: OB do SIAFE ──────────────────────────────────────────────────────────────────────────
class _Concentracao(_Regra):
    ID, UNIDADE, VERSAO = "e10.tg_concentracao", "ob_siafe", "e10-tg-d05-1"
    MIN_UG, MIN_CREDOR, MIN_SHARE, NOVA, SUBIU = 10e6, 5e6, 0.30, 0.10, 0.15

    def _ler(self, con, exercicio):
        jn, nomes = janelas(con, self.corte), _nomes_ug(con)
        itens, fora = [], Counter()
        for jan, d0, d1 in (("G", self.corte, jn["g1"]), ("B", jn["b0"], jn["b1"])):
            for c in _obs(con, d0, d1, self.pago):
                if not GC.Ctx.fornecedor(c["credor"], c["nome"]):
                    fora["nao_fornecedor"] += 1
                elif not _executivo(nomes, c["ug"]):
                    fora["fora_do_executivo"] += 1
                else:
                    itens.append({**c, "janela": jan, "grupo": f"{c['ug']}"})
        return Carga(itens=itens, contexto={**jn, "fora": dict(fora), "nomes_ug_disponiveis": bool(nomes)})

    def no_grupo(self, c, grupo):
        return str(c["ug"]) == grupo.split("|", 1)[0]

    def detectar(self, itens, contexto=None):
        tot, por, nome = Counter(), Counter(), {}
        for c in itens:
            if elegivel(c):
                tot[(c["janela"], c["ug"])] += c["valor"]
                por[(c["janela"], c["ug"], c["cnpj"])] += c["valor"]
                nome[c["cnpj"]] = c["nome"]
        out = []
        for (jan, ug, cr), v in sorted(por.items(), key=lambda x: (str(x[0][1]), x[0][2])):
            tg = tot[("G", ug)]
            if jan != "G" or tg < self.MIN_UG or v < self.MIN_CREDOR or v / tg < self.MIN_SHARE:
                continue
            sh, tb = v / tg, tot.get(("B", ug))
            shb = por.get(("B", ug, cr), 0) / tb if tb else None
            tipo = "NOVA" if (shb is None or shb < self.NOVA) else ("SUBIU" if sh - shb >= self.SUBIU else "PERSISTENTE")
            ms = sorted((c for c in itens if c["janela"] == "G" and c["ug"] == ug and c["cnpj"] == cr and elegivel(c)),
                        key=lambda c: (-c["valor"], str(c["numero_ob"])))
            chave = f"{ug}|{cr}"
            out.append(Disparo(
                chave=chave, grupo=chave, estado="INDICIO",
                observacao=(f"O credor {nome[cr]} recebeu {reais(v)} ({sh:.0%}) dos {reais(tg)} pagos pela UG {ug} a "
                            f"fornecedores entre {(contexto or {}).get('corte')} e {(contexto or {}).get('g1')} "
                            f"({tipo}; {'—' if shb is None else f'{shb:.0%}'} no mesmo intervalo do ano anterior). "
                            "Concentração não é irregularidade por si: o instrumento (contrato, concessão, programa) "
                            "precisa ser lido. Fonte: ob_orcamentaria_siafe."),
                entradas={"ug": ug, "cnpj": cr, "pago": round(v, 2), "total_ug": round(tg, 2),
                          "pago_b": round(por.get(("B", ug, cr), 0), 2), "total_ug_b": round(tb or 0, 2),
                          "n_ob": len(ms)},
                valores={"pago_ob": round(v, 2), "total_ug": round(tg, 2), "share": round(sh, 4),
                         "share_ano_anterior": None if shb is None else round(shb, 4), "tipo": tipo},
                evidencias=[_fato_ob(c) for c in ms[:30]]))
        return out

    def resumo(self, itens, disparos):
        return _resumo_ob(itens, disparos, "pago_ob")


class _PicoVespera(_Regra):
    ID, UNIDADE, VERSAO = "e10.tg_pico_vespera", "ob_siafe", "e10-tg-d09-1"
    MIN_SEMANA, VEZES = 3e6, 5

    def _ler(self, con, exercicio):
        jn = janelas(con, self.corte)
        ini = (date.fromisoformat(jn["p1"]) - timedelta(days=6)).isoformat()
        itens, fora = [], 0
        for c in _obs(con, jn["p0"], jn["p1"], self.pago):
            if not GC.Ctx.fornecedor(c["credor"], c["nome"]):
                fora += 1
                continue
            itens.append({**c, "janela": "ULT" if c["dt"] >= ini else "BASE", "grupo": c["cnpj"]})
        semanas = (date.fromisoformat(ini) - date.fromisoformat(jn["p0"])).days / 7
        return Carga(itens=itens, contexto={**jn, "ini_ultima_semana": ini, "semanas_base": semanas,
                                            "nao_fornecedor": fora})

    def detectar(self, itens, contexto=None):
        semanas = (contexto or {}).get("semanas_base") or 1
        base, ult, ugv = Counter(), Counter(), defaultdict(Counter)
        nome = {}
        for c in itens:
            if elegivel(c):
                (ult if c["janela"] == "ULT" else base)[c["cnpj"]] += c["valor"]
                nome[c["cnpj"]] = c["nome"]
                if c["janela"] == "ULT":
                    ugv[c["cnpj"]][c["ug"]] += c["valor"]
        out = []
        for d, v in sorted(ult.items()):
            mw = base[d] / semanas
            if not (v >= self.MIN_SEMANA and v >= self.VEZES * max(mw, 1)):
                continue
            ms = sorted((c for c in itens if c["cnpj"] == d and c["janela"] == "ULT" and elegivel(c)),
                        key=lambda c: (-c["valor"], str(c["numero_ob"])))
            ug = ugv[d].most_common(1)[0][0]
            out.append(Disparo(
                chave=d, grupo=d, estado="INDICIO",
                observacao=(f"O credor {nome[d]} recebeu {reais(v)} na última semana antes do corte "
                            f"({(contexto or {}).get('ini_ultima_semana')} → {(contexto or {}).get('p1')}), "
                            f"{'∞' if not mw else f'{v / mw:.1f}×'} a média semanal desde 1º de janeiro "
                            f"({reais(mw)}). Pode ser obrigação vencida paga antes da troca. Fonte: ob_orcamentaria_siafe."),
                entradas={"cnpj": d, "pago_semana": round(v, 2), "base": round(base[d], 2), "semanas": semanas,
                          "obs": [c["chave_e9"] for c in ms]},
                valores={"pago_semana": round(v, 2), "media_semanal_antes": round(mw, 2),
                         "x": round(v / mw, 1) if mw else None, "ug_principal": ug},
                evidencias=[_fato_ob(c) for c in ms[:30]]))
        return out

    def resumo(self, itens, disparos):
        return _resumo_ob(itens, disparos, "pago_semana")


class _CredorEstreante(_Regra):
    ID, UNIDADE, VERSAO = "e10.tg_credor_estreante", "ob_siafe", "e10-tg-d10-1"
    MIN_CREDOR = 5e6

    def _hist(self, con) -> set:
        """Raízes (8 dígitos) com alguma OB paga de valor > 0 desde ANO_MIN até a véspera do corte."""
        vespera = (date.fromisoformat(self.corte) - timedelta(days=1)).isoformat()
        return {c["cnpj"][:8] for c in _obs(con, f"{ANO_MIN}-01-01", vespera, self.pago)
                if c["valor"] > 0 and len(c["cnpj"]) == 14}

    def _ler(self, con, exercicio):
        jn, nomes = janelas(con, self.corte), _nomes_ug(con)
        hist = self._hist(con)
        itens, fora = [], Counter()
        for c in _obs(con, self.corte, jn["gfim"], self.pago):
            if not GC.Ctx.fornecedor(c["credor"], c["nome"]):
                fora["nao_fornecedor"] += 1
            elif c["cnpj"][:8] in hist:
                fora["com_historico"] += 1
            elif not _executivo(nomes, c["ug"]):
                fora["fora_do_executivo"] += 1
            else:
                itens.append({**c, "grupo": c["cnpj"]})
        return Carga(itens=itens, contexto={**jn, "raizes_com_historico": len(hist), "fora": dict(fora),
                                            "nomes_ug_disponiveis": bool(nomes),
                                            "rotulo_grupo_receita": "INDISPONIVEL (Receita fora da fonte do E10)"})

    def detectar(self, itens, contexto=None):
        agg: dict = defaultdict(list)
        for c in itens:
            if elegivel(c):
                agg[c["cnpj"]].append(c)
        out = []
        for cr, obs in sorted(agg.items()):
            v = sum(c["valor"] for c in obs)
            if v < self.MIN_CREDOR:
                continue
            nm = obs[-1]["nome"]
            rot, base = GC.rotulo_estreia(_SEM_RECEITA, cr, nm, set())
            ugs = Counter()
            for c in obs:
                ugs[c["ug"]] += c["valor"]
            obs = sorted(obs, key=lambda c: (-c["valor"], str(c["numero_ob"])))
            prim = min(c["dt"] for c in obs)
            if rot != "estreia":
                continue                               # consórcio: à parte, contado no resumo
            out.append(Disparo(
                chave=cr, grupo=cr, estado="INDICIO",
                observacao=(f"O CNPJ {cr} ({nm}) não tem nenhuma OB paga desde {ANO_MIN} até a véspera do corte "
                            f"(raiz de 8 dígitos: matriz e filiais) e recebeu {reais(v)} em {len(obs)} OB desde "
                            f"{prim}. Empresa nova de grupo antigo (cisão, SPE) não é testada sem a Receita. Fonte: "
                            "ob_orcamentaria_siafe."),
                entradas={"cnpj": cr, "pago": round(v, 2), "n_ob": len(obs), "primeira_ob": prim,
                          "ugs": {str(k): round(x, 2) for k, x in sorted(ugs.items(), key=str)}},
                valores={"pago_ob": round(v, 2), "n_ob": len(obs), "primeira_ob": prim,
                         "ug_principal": ugs.most_common(1)[0][0], "n_ugs": len(ugs), "rotulo": rot},
                evidencias=[_fato_ob(c) for c in obs[:30]]))
        return out

    def resumo(self, itens, disparos):
        agg: dict = defaultdict(float)
        nome = {}
        for c in itens:
            if elegivel(c):
                agg[c["cnpj"]] += c["valor"]
                nome[c["cnpj"]] = c["nome"]
        cons = [cr for cr, v in agg.items() if v >= self.MIN_CREDOR
                and GC.rotulo_estreia(_SEM_RECEITA, cr, nome[cr], set())[0] == "consorcio"]
        return {**_resumo_ob(itens, disparos, "pago_ob"), "consorcio_a_parte": len(cons),
                "consorcio_a_parte_valor": round(sum(agg[c] for c in cons), 2)}


class _ObAnulada(_Regra):
    ID, UNIDADE, VERSAO = "e10.tg_ob_anulada", "ob_siafe", "e10-tg-d20-1"

    def _ler(self, con, exercicio):
        jn = janelas(con, self.corte)
        itens = [{**c, "janela": jan, "grupo": str(c["ug"])}
                 for jan, d0, d1 in (("G", self.corte, jn["g1"]), ("B", jn["b0"], jn["b1"]))
                 for c in _obs(con, d0, d1, self.pago, anuladas=True)]
        return Carga(itens=itens, contexto=jn)

    def detectar(self, itens, contexto=None):
        t: dict = defaultdict(lambda: {"G": [0, 0.0], "B": [0, 0.0]})
        for c in itens:
            if elegivel(c):
                a = t[str(c["ug"])][c["janela"]]
                a[0] += 1
                a[1] += c["valor"]
        out = []
        for ug in sorted(t):
            (n, v), (nb, vb) = t[ug]["G"], t[ug]["B"]
            if not n:
                continue
            ms = sorted((c for c in itens if str(c["ug"]) == ug and c["janela"] == "G" and elegivel(c)),
                        key=lambda c: (-c["valor"], str(c["numero_ob"])))
            out.append(Disparo(
                chave=ug, grupo=ug, estado="INCERTO", motivo_estado="contexto (⚪): OB anulada não é pagamento",
                observacao=(f"UG {ug}: {n} OB anulada(s)/excluída(s) ({reais(v)}) entre {(contexto or {}).get('corte')} "
                            f"e {(contexto or {}).get('g1')}, contra {nb} ({reais(vb)}) no mesmo intervalo do ano "
                            "anterior. OB anulada NÃO é pagamento; o passo é conferir a reemissão correspondente. "
                            "Fonte: ob_orcamentaria_siafe (status Anulado/Excluído)."),
                entradas={"ug": ug, "G": [n, round(v, 2)], "B": [nb, round(vb, 2)], "obs": [c["chave_e9"] for c in ms]},
                valores={"n": n, "valor": round(v, 2), "n_ano_anterior": nb, "valor_ano_anterior": round(vb, 2),
                         "diferenca": round(v - vb, 2)},
                evidencias=[Fato(papel=Papel.CONTEXTO, tipo="ob_anulada", fonte="ob_orcamentaria_siafe",
                                 referencia=str(c["numero_ob"]), valor=Decimal(str(round(c["valor"], 2))),
                                 descricao=f"OB anulada/excluída da UG {ug} de {c['dt']} (não é pagamento)",
                                 dados={"veredito_e9": c.get("e9")}) for c in ms[:30]]))
        return out

    def resumo(self, itens, disparos):
        e = [c for c in itens if elegivel(c)]
        tot = {j: [sum(1 for c in e if c["janela"] == j), round(sum(c["valor"] for c in e if c["janela"] == j), 2)]
               for j in ("G", "B")}
        return {"anuladas": len(itens), "por_veredito": _por_veredito(itens), "cobertura": _cobertura(itens),
                "n": tot["G"][0], "valor": tot["G"][1], "n_ano_anterior": tot["B"][0],
                "valor_ano_anterior": tot["B"][1], "disparos": len(disparos),
                "soma_disparos": round(sum(d.valores["valor"] for d in disparos), 2)}


# ── D16: TAC (DOERJ) ────────────────────────────────────────────────────────────────────────────────────────────
class _TacAceleracao(_Regra):
    """O TAC não é unidade da E9: o veredito `fornecedor` é do CREDOR e é lido na maior OB paga do mesmo CNPJ
    (`chave_e9` dela); TAC sem CNPJ, ou CNPJ sem OB, fica sem linha na E9 → INDETERMINADO, contado."""
    ID, UNIDADE, VERSAO = "e10.tg_tac_aceleracao", "ob_siafe", "e10-tg-d16-1"
    MIN_NOVO = 1e6

    def _ler(self, con, exercicio):
        jn = janelas(con, self.corte)
        rows = con.execute("SELECT data_doe, orgao, fornecedor, cnpj, valor, numero_tac, processo FROM doerj_tac "
                           "WHERE data_doe >= ?", (jn["p0"],)).fetchall()
        docs = sorted({dig(r[3]) for r in rows if len(dig(r[3])) == 14})
        rep: dict = {}
        for d in docs:
            r = con.execute(f"SELECT ug_emitente, numero_ob, exercicio FROM ob_orcamentaria_siafe WHERE credor = ? "
                            f"AND {ob_paga_sql(con)} ORDER BY valor DESC LIMIT 1", (d,)).fetchone()
            if r:
                rep[d] = f"{r[0]}|{r[1]}|{r[2]}"
        itens = [{"chave_e9": rep.get(dig(cj)), "data": d, "orgao": o, "fornecedor": f, "cnpj": dig(cj),
                  "valor": float(v or 0), "numero_tac": nt, "processo": pr, "grupo": GC.norm_nome(f),
                  "janela": "POS" if d >= self.corte else "PRE"} for d, o, f, cj, v, nt, pr in rows]
        ult = max((r[0] for r in rows), default=None)
        dias_pre = (date.fromisoformat(jn["p1"]) - date.fromisoformat(jn["p0"])).days + 1
        dias_pos = max(1, (date.fromisoformat(ult) - date.fromisoformat(self.corte)).days + 1) if ult else None
        vpre = sum(c["valor"] for c in itens if c["janela"] == "PRE")
        vpos = sum(c["valor"] for c in itens if c["janela"] == "POS")
        taxa = {"valor_dia_pre": round(vpre / dias_pre, 2), "valor_dia_pos": round(vpos / dias_pos, 2) if dias_pos else None}
        taxa["variacao_dia"] = (round(taxa["valor_dia_pos"] / taxa["valor_dia_pre"] - 1, 4)
                                if taxa["valor_dia_pre"] and taxa["valor_dia_pos"] is not None else None)
        return Carga(itens=itens, contexto={**jn, **taxa, "ultima_tac": ult, "tac_com_cnpj": sum(1 for c in itens if c["cnpj"]),
                                            "tac_com_ob_do_credor": sum(1 for c in itens if c["chave_e9"])})

    def detectar(self, itens, contexto=None):
        pre = {c["grupo"] for c in itens if c["janela"] == "PRE"}
        novos: dict = defaultdict(list)
        for c in itens:
            if c["janela"] == "POS" and c["grupo"] not in pre:
                novos[c["grupo"]].append(c)
        out = []
        for g, ts in sorted(novos.items()):
            v = sum(c["valor"] for c in ts)
            if v < self.MIN_NOVO or _situacao(ts) != "E":
                continue
            ts = sorted(ts, key=lambda c: (c["data"], str(c["numero_tac"])))
            orgaos = sorted({(c["orgao"] or "")[:60] for c in ts})
            out.append(Disparo(
                chave=g, grupo=g, estado="INDICIO",
                observacao=(f"{ts[0]['fornecedor']}: {len(ts)} Termo(s) de Ajuste de Contas publicados no DOERJ depois "
                            f"do corte ({reais(v)} reconhecidos; valor do TAC, NÃO é OB), sem nenhum TAC antes dele no "
                            f"ano; órgão(s): {'; '.join(orgaos)}. TAC é pagamento de serviço sem cobertura contratual — "
                            "pode ser continuidade de serviço essencial durante a licitação. Fonte: doerj_tac."),
                entradas={"grupo": g, "tacs": [{"data": c["data"], "numero": c["numero_tac"], "valor": round(c["valor"], 2),
                                                "orgao": c["orgao"], "e9": c.get("e9")} for c in ts]},
                valores={"n_tac": len(ts), "valor_tac": round(v, 2), "orgaos": orgaos},
                processo=str(ts[0]["processo"] or "") or None,
                evidencias=[Fato(papel=Papel.SUPORTE, tipo="tac", fonte="doerj_tac", referencia=str(c["numero_tac"]),
                                 valor=Decimal(str(round(c["valor"], 2))), descricao=f"TAC de {c['data']} ({c['orgao']})",
                                 dados={"processo": c["processo"], "veredito_e9": c.get("e9")}) for c in ts[:30]]))
        return out

    def resumo(self, itens, disparos):
        pre = [c for c in itens if c["janela"] == "PRE"]
        pos = [c for c in itens if c["janela"] == "POS"]
        sit = Counter(_situacao(ts) for ts in _agrupar(pos).values())
        return {"tac": len(itens), "n_pre": len(pre), "valor_pre": round(sum(c["valor"] for c in pre), 2),
                "n_pos": len(pos), "valor_pos": round(sum(c["valor"] for c in pos), 2),
                "por_veredito": _por_veredito(itens), "fornecedores_pos_por_situacao_e9": dict(sit),
                "cobertura": _cobertura(itens), "disparos": len(disparos),
                "soma_disparos": round(sum(d.valores["valor_tac"] for d in disparos), 2)}


def _agrupar(itens):
    g: dict = defaultdict(list)
    for c in itens:
        g[c["grupo"]].append(c)
    return g


def _cobertura(itens) -> float | None:
    indet = sum(1 for c in itens if not str(c.get("e9") or "?").startswith(("E", "I")))
    return round(1 - indet / len(itens), 4) if itens else None


def _resumo_ob(itens, disparos, campo) -> dict:
    val = Counter()
    for c in itens:
        val[c.get("e9") or "?:SEM_LINHA_E9"] += c["valor"]
    return {"obs": len(itens), "por_veredito": _por_veredito(itens),
            "valor_por_veredito": {k: round(v, 2) for k, v in sorted(val.items())}, "cobertura": _cobertura(itens),
            "disparos": len(disparos), "soma_disparos": round(sum(float(d.valores[campo]) for d in disparos), 2)}


DIRETA_SALTO = _DiretaSalto()
EMERGENCIAL_INCUMBENTE = _EmergencialIncumbente()
CONCENTRACAO = _Concentracao()
PICO_VESPERA = _PicoVespera()
CREDOR_ESTREANTE = _CredorEstreante()
OB_ANULADA = _ObAnulada()
TAC_ACELERACAO = _TacAceleracao()
