# -*- coding: utf-8 -*-
"""cruzamentos_intel — os 3 cruzamentos de inteligência pedidos pelo dono (2026-07-17):

1. SANCIONADAS CONTRATADAS — empresas em sanção impeditiva (CEIS/CNEP, `sancoes_federais`)
   que receberam pagamento do Estado (OB SIAFE) ou venceram certame (PNCP), com o teste
   temporal "À ÉPOCA": o ato (OB/homologação) caiu DENTRO da vigência [data_inicio, data_fim]?
   Sanção posterior ao ato NÃO macula o ato (mesma regra do nucleo/adaptador_db).

2. PERDEDORAS CONTUMAZES ("nunca ganharam") — licitantes que aparecem em ≥K atas e nunca
   vencem (candidatas a proposta de cobertura/OCDE), com quem "perdem junto" (beneficiário
   provável). Fonte: corpus de atas (`edital_documento`) → rodizio_grafo.detectar_padroes.

3. FANTASMAS EM ESCALA — score /fantasma (8 sinais determinísticos, empresa_fantasma) aplicado
   ao conjunto-ALVO (vencedoras de captura/rodízio + perdedoras contumazes + sancionadas
   contratadas + top favorecidos SIAFE), persistido em `fantasma_score`. Sem cadastro local
   → `sem_cadastro` (INDISPONÍVEL ≠ 0; a fila de enriquecimento resolve depois).

Tudo determinístico (sem IA). Indício ≠ acusação — cada saída carrega a ressalva.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from pathlib import Path
from compliance_agent.reporting.intel_base import SQL_FAVORECIDO_PJ, moeda

_REPO = Path(__file__).resolve().parent.parent
_DB = str(_REPO / "data" / "compliance.db")
_CACHE_DIR = _REPO / "data" / "cache"

logger = logging.getLogger(__name__)

# mesma régua do nucleo/adaptador_db._tem_sancao_vigente: só sanção IMPEDITIVA conta
# a régua do que VEDA contratar mora em `sancao_impeditiva` — multa e publicação extraordinária
# são penalidades reais que NÃO impedem contratação, e a distinção estava replicada em SQL aqui e
# no `nucleo/adaptador_db`. Cópias idênticas hoje; este import existe para que continuem idênticas.
from compliance_agent.sancao_impeditiva import SQL_IMPEDITIVA as _SQL_IMPEDITIVA

# OB SIAFE guarda data DD/MM/AAAA (string) — converter p/ ISO na consulta
_OB_ISO = "substr(data_emissao,7,4)||'-'||substr(data_emissao,4,2)||'-'||substr(data_emissao,1,2)"

RESSALVA = ("Indício para apuração interna, não acusação. Sanção impeditiva vigente à época do ato "
            "é vedação legal (Lei 14.133, art. 156 §1º; Lei 8.666, arts. 87-88) — confirmar no "
            "cadastro-fonte (Portal da Transparência/CGU) antes de qualquer uso externo.")


# Teto de dispensa de licitação por ano (Lei 14.133 art. 75-II, compras/serviços comuns).
# Abaixo dele o gestor pode contratar SEM licitação — o incentivo a "fatiar" a despesa para
# caber embaixo é o vetor clássico de fracionamento (Lei 14.133 art. 75 §1º).
# Fonte única verificada nos decretos (Planalto): compliance_agent/limites_dispensa.py.
from compliance_agent.limites_dispensa import LIMITES as _LIMITES_DISP, LIMITES_8666 as _LIMITES_8666

# exercício anterior à 14.133 usa o teto da Lei 8.666 (art. 24, II) — sem isso o CASE caía no ELSE (teto de 2026)
_TETO_DISPENSA = {a: v["compras"] for a, v in {**_LIMITES_8666, **_LIMITES_DISP}.items()}
_TETO_DEFAULT = _TETO_DISPENSA[max(_TETO_DISPENSA)]


def _ro(db_path: str | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{db_path or _DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=30000")
    registrar_peneira(con)
    return con


def registrar_peneira(con: sqlite3.Connection) -> None:
    """Registra na conexão a função SQL `jfn_eh_publico(nome, credor)` que `_SQL_NAO_PUBLICO` usa: 1 se o credor é
    ENTE PÚBLICO — pela peneira canônica de nome (`entidades_gov.eh_nao_fornecedor`) OU pela natureza jurídica 1xxx
    da Receita (`empresas_cadastro`, quando a base a tem). Conexão que use `_SQL_NAO_PUBLICO` sem passar por aqui
    falha alto ("no such function"), em vez de filtrar em silêncio com uma cópia velha."""
    from compliance_agent.entidades_gov import eh_administracao_publica, eh_nao_fornecedor
    publicos: set = set()
    try:
        if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='empresas_cadastro'").fetchone():
            publicos = {r[0] for r in con.execute("SELECT cnpj_basico, natureza_cod FROM empresas_cadastro "
                                                  "WHERE natureza_cod LIKE '1%'") if eh_administracao_publica(r[1])}
    except sqlite3.Error:
        logging.getLogger(__name__).debug("empresas_cadastro ilegível — só a peneira de nome", exc_info=True)
    cache: dict = {}

    def _eh_publico(nome, credor) -> int:
        if credor and str(credor)[:8] in publicos:
            return 1
        n = nome or ""
        if n not in cache:
            cache[n] = 1 if (eh_nao_fornecedor(n) or _RX_BANCO_OU_PUBLICO_LEGADO.search(n)) else 0
        return cache[n]
    con.create_function("jfn_eh_publico", 2, _eh_publico, deterministic=True)


def classificador_credor(con: sqlite3.Connection):
    """FORNECEDOR × OUTRO CREDOR para ranking de PAGAMENTO (painel, 24/11/2026): devolve `f(nome, credor)` → motivo
    (str) quando o credor NÃO é fornecedor — tributo, folha, encargo, repasse, ente público, banco de repasse — ou
    None quando é. Mesmas peneiras canônicas de `registrar_peneira` (natureza 1xxx da Receita, `eh_nao_fornecedor`,
    banco/previdência) + a família de encargo/ente de `fracionamento_siafe` (sem a de concessionária: Light e CEDAE
    VENDEM ao Estado, só não por dispensa). A família de encargo casa por NOME e tem palavras de uso comum
    ("pessoal", "diária", "contribuição"): quando a Receita diz que o CNPJ é empresa/entidade privada (natureza
    2xxx/3xxx/4xxx), o nome sozinho não o tira dos fornecedores. Medido no painel em 24/11/2026: 1º e 2º do ranking
    eram 'MINISTÉRIO DA FAZENDA' (R$ 7,46 bi, tributo retido) e 'Banco do Brasil' (R$ 5,93 bi, repasse/consignado)."""
    from compliance_agent.entidades_gov import eh_administracao_publica, eh_nao_fornecedor
    from compliance_agent.fracionamento_siafe import _CREDOR_ENCARGO_OU_ENTE
    natureza: dict = {}
    try:
        if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='empresas_cadastro'").fetchone():
            natureza = {r[0]: str(r[1] or "") for r in con.execute(
                "SELECT cnpj_basico, natureza_cod FROM empresas_cadastro WHERE natureza_cod IS NOT NULL")}
    except sqlite3.Error:
        logging.getLogger(__name__).debug("empresas_cadastro ilegível — só a peneira de nome", exc_info=True)

    def _motivo(nome, credor) -> str | None:
        doc = str(credor or "")
        nat = natureza.get(doc[:8], "") if len(doc) == 14 else ""
        if nat and eh_administracao_publica(nat):
            return "ente público (natureza jurídica 1xxx na Receita)"
        n = nome or ""
        if eh_nao_fornecedor(n):
            return "transferência, tributo ou ente público"
        if _RX_BANCO_OU_PUBLICO_LEGADO.search(n):
            return "banco, previdência ou órgão (repasse, consignado, encargo)"
        if _CREDOR_ENCARGO_OU_ENTE.search(n) and not (nat[:1] in ("2", "3", "4") if nat else False):
            return "folha, tributo, encargo ou repasse"
        return None
    return _motivo


# ── 1. SANCIONADAS CONTRATADAS ───────────────────────────────────────────────

def sancionadas_contratadas(db_path: str | None = None, min_valor: float = 0.0) -> dict:
    """Cruza sanções impeditivas × OB SIAFE (Estado) × vitórias PNCP do ESCOPO DA CASA (Estado do RJ e
    Prefeitura do Rio — federal, outros municípios e outros estados ficam fora e são contados em
    `pncp_fora_do_escopo`). Por empresa: sanções, pagamentos/vitórias TOTAIS e os DURANTE a vigência ("à época").

    20/11/2026: a parte PNCP testava a esfera no vocabulário errado (`classificar_esfera` devolve "estado"/
    "prefeitura"; o teste aceitava "federal"/"estadual"/"municipal") — só órgão FEDERAL casava. As 5 empresas
    "à época" só-PNCP da base eram todas da Marinha e afins, e vitória no Estado/Prefeitura sob sanção com
    alcance nunca era marcada. Agora: Estado → `veda_ente(estadual, RJ)`; Prefeitura → só sanção do próprio
    Município do Rio (`_alcanca_o_municipio_do_rio`, a de Niterói não vale).

    "À época" (revisão cética 13/11/2026) exige as DUAS coisas: a sanção VIGENTE na data do ato
    (`sancao_abrangencia.vigente_em` — "com prazo determinado" sem fim não se afirma) **e** com ALCANCE
    sobre o ente pagador/comprador (`veda_ente`: abrangência declarada no CEIS, esfera do sancionador,
    fundamentação antes da categoria). Vigente sem alcance é contado à parte (`*_vigente_sem_alcance`):
    risco reputacional, não vedação — 56% do "sancionada paga" do D14 era isso."""
    from compliance_agent.sancao_abrangencia import sql_campos_ceis, veda_ente, vigente_em
    con = _ro(db_path)
    try:
        # sanções impeditivas de PJ (14 dígitos; CPF sancionado não contrata como empresa)
        sanc: dict[str, list] = {}
        for r in con.execute(
                f"SELECT cpf_cnpj, nome, cadastro, categoria, data_inicio, data_fim, orgao, uf, fundamentacao, "
                f"{sql_campos_ceis(con)} "
                f"FROM sancoes_federais WHERE length(cpf_cnpj)=14 AND {_SQL_IMPEDITIVA}"):
            sanc.setdefault(r["cpf_cnpj"], []).append(dict(r))

        achados: dict[str, dict] = {}

        def _base(cnpj: str, nome: str) -> dict:
            return achados.setdefault(cnpj, {
                "cnpj": cnpj, "nome": nome, "sancoes": sanc.get(cnpj, []),
                "estado": {"obs": 0, "valor": 0.0, "obs_durante": 0, "valor_durante": 0.0,
                           "exemplos_durante": [], "obs_vigente_sem_alcance": 0,
                           "valor_vigente_sem_alcance": 0.0},
                "pncp": {"vitorias": 0, "valor": 0.0, "vitorias_durante": 0, "valor_durante": 0.0,
                         "esferas": {}, "exemplos_durante": [], "vitorias_vigente_sem_alcance": 0},
            })

        # Estado: OBs SIAFE pagas a CNPJ sancionado (total e durante a vigência)
        q_ob = (f"SELECT credor, nome_credor, numero_ob, valor, {_OB_ISO} AS dt "
                f"FROM ob_orcamentaria_siafe WHERE {_ob_paga(con)} AND length(credor)=14 AND credor IN "
                f"({','.join('?' * len(sanc))})")
        if sanc:
            for r in con.execute(q_ob, list(sanc)):
                a = _base(r["credor"], r["nome_credor"])
                a["estado"]["obs"] += 1
                a["estado"]["valor"] += r["valor"] or 0.0
                vigentes = [s for s in a["sancoes"] if vigente_em(s, r["dt"])]
                com_alcance = [s for s in vigentes if veda_ente(s, "estadual", "RJ")["veda"]]
                if vigentes and not com_alcance:
                    a["estado"]["obs_vigente_sem_alcance"] += 1
                    a["estado"]["valor_vigente_sem_alcance"] += r["valor"] or 0.0
                if com_alcance:
                    s = com_alcance[0]
                    ini, fim = s.get("data_inicio") or "?", s.get("data_fim") or "sem prazo"
                    a["estado"]["obs_durante"] += 1
                    a["estado"]["valor_durante"] += r["valor"] or 0.0
                    if len(a["estado"]["exemplos_durante"]) < 5:
                        a["estado"]["exemplos_durante"].append(
                            {"ob": r["numero_ob"], "data": r["dt"], "valor": r["valor"],
                             "sancao": s["cadastro"], "vigencia": f"{ini}→{fim}"})

        # PNCP: vitórias homologadas de CNPJ sancionado (com esfera oficial do ente)
        try:
            from compliance_agent.collectors.pncp_resultados import (
                classificar_esfera, esferas_por_ente)
            oficial = esferas_por_ente(con)
        except Exception:
            oficial, classificar_esfera = {}, None
        fora_do_escopo: dict[str, int] = {}
        if sanc:
            q_pncp = ("SELECT certame, orgao_cnpj, orgao_nome, unidade_nome, municipio, uf, "
                      "fornecedor_cnpj, fornecedor_nome, data_pub, SUM(valor_homologado) v "
                      "FROM pncp_resultado WHERE ordem_classificacao=1 AND fornecedor_cnpj IN "
                      f"({','.join('?' * len(sanc))}) GROUP BY certame, fornecedor_cnpj")
            for r in con.execute(q_pncp, list(sanc)):
                esf = classificar_esfera(dict(r), oficial) if classificar_esfera else "?"
                if esf not in ("estado", "prefeitura"):      # escopo da casa: só RJ (federal e demais fora)
                    fora_do_escopo[esf] = fora_do_escopo.get(esf, 0) + 1
                    continue
                a = _base(r["fornecedor_cnpj"], r["fornecedor_nome"])
                a["pncp"]["vitorias"] += 1
                a["pncp"]["valor"] += r["v"] or 0.0
                a["pncp"]["esferas"][esf] = a["pncp"]["esferas"].get(esf, 0) + 1
                dt = (r["data_pub"] or "")[:10]
                vigentes = [s for s in a["sancoes"] if vigente_em(s, dt)]
                if esf == "estado":
                    com_alcance = [s for s in vigentes if veda_ente(s, "estadual", "RJ")["veda"]]
                else:                                        # Prefeitura do Rio: sanção de outro município não alcança
                    com_alcance = [s for s in vigentes if _alcanca_o_municipio_do_rio(s, veda_ente)]
                if vigentes and not com_alcance:
                    a["pncp"]["vitorias_vigente_sem_alcance"] += 1
                if com_alcance:
                    s = com_alcance[0]
                    ini, fim = s.get("data_inicio") or "?", s.get("data_fim") or "sem prazo"
                    a["pncp"]["vitorias_durante"] += 1
                    a["pncp"]["valor_durante"] += r["v"] or 0.0
                    if len(a["pncp"]["exemplos_durante"]) < 5:
                        a["pncp"]["exemplos_durante"].append(
                            {"certame": r["certame"], "orgao": r["unidade_nome"] or r["orgao_nome"],
                             "esfera": esf, "data": dt, "valor": r["v"],
                             "sancao": s["cadastro"], "vigencia": f"{ini}→{fim}"})

        lista = [a for a in achados.values()
                 if (a["estado"]["valor"] + a["pncp"]["valor"]) >= min_valor]
        # gravidade primeiro: quem tem ato DURANTE a sanção; depois por valor
        lista.sort(key=lambda a: (-(a["estado"]["valor_durante"] + a["pncp"]["valor_durante"]),
                                  -(a["estado"]["valor"] + a["pncp"]["valor"])))
        n_epoca = sum(1 for a in lista
                      if a["estado"]["obs_durante"] or a["pncp"]["vitorias_durante"])
        return {"ok": True, "empresas": lista, "n": len(lista), "n_a_epoca": n_epoca,
                "escopo": "Estado do RJ (OB do SIAFE e PNCP) e Prefeitura do Rio (PNCP), contados em separado "
                          "por empresa; federal, outros municípios e outros estados fora",
                "pncp_fora_do_escopo": fora_do_escopo,
                "ressalva": RESSALVA}
    finally:
        con.close()


from compliance_agent.sancao_abrangencia import RX_MUNICIPIO_DO_RIO as _RX_MUNICIPIO_DO_RIO  # noqa: E402 — régua única


def _alcanca_o_municipio_do_rio(sancao: dict, veda_ente) -> bool:
    """A sanção alcança contrato da Prefeitura do Rio? Alcance total sempre; alcance de ENTE (impedimento,
    suspensão de parceria) só quando o sancionador é o próprio Município do Rio — `veda_ente` compara esfera e UF,
    e outro município do mesmo Estado passaria."""
    v = veda_ente(sancao, "municipal", "RJ")
    if not v["veda"]:
        return False
    if v.get("abrangencia") == "total":
        return True
    return bool(_RX_MUNICIPIO_DO_RIO.search(sancao.get("orgao") or ""))


def sancionadas_municipio(db_path: str | None = None, min_valor: float = 0.0) -> dict:
    """Sanção impeditiva × CONTRATO da Prefeitura do Rio (análogo municipal do
    ``sancionadas_contratadas``, que só cobre SIAFE-Estado + PNCP).

    Fonte: ``pcrj_contratos`` (só ``fonte='pncp'`` = município do Rio, IBGE 3304557 —
    exclui as linhas ``pncp_estado`` que contaminam a tabela) × ``sancoes_federais``.
    Teste "à época": o contrato foi ASSINADO dentro da vigência [data_inicio, data_fim]
    de uma sanção impeditiva? Contrato fora da janela NÃO macula (mesma régua do Estado).
    Guarda extra: corrobora a esfera do órgão via ``pcrj.esfera.classificar_esfera``.

    Verificação de 13/11/2026: a função contava QUALQUER sanção impeditiva na janela — sem alcance (suspensão de
    um instituto federal "maculava" contrato da Prefeitura) e com "prazo determinado" sem data final lido como
    eterno. Agora a régua é a do Estado: `vigente_em` + `veda_ente(municipal, RJ)`; e, como impedimento/suspensão
    de ente municipal só vale no PRÓPRIO município, exige-se que o sancionador seja o Município do Rio (a de
    Niterói não alcança a Prefeitura do Rio). Vigente sem alcance é contado à parte — não é vedação.
    """
    from compliance_agent.sancao_abrangencia import sql_campos_ceis, veda_ente, vigente_em
    try:
        from compliance_agent.pcrj.esfera import classificar_esfera as _cls
    except Exception:                       # pragma: no cover
        _cls = None
    con = _ro(db_path)
    try:
        sanc: dict[str, list] = {}
        cols = {r[1] for r in con.execute("PRAGMA table_info(sancoes_federais)")}
        extras = ", ".join(c if c in cols else f"NULL AS {c}" for c in ("uf", "fundamentacao"))
        for r in con.execute(
                f"SELECT cpf_cnpj, nome, cadastro, categoria, data_inicio, data_fim, orgao, {extras}, "
                f"{sql_campos_ceis(con)} "
                f"FROM sancoes_federais WHERE length(cpf_cnpj)=14 AND {_SQL_IMPEDITIVA}"):
            sanc.setdefault(r["cpf_cnpj"], []).append(dict(r))
        if not sanc or not _tabela_existe(con, "pcrj_contratos"):
            return {"ok": True, "empresas": [], "n": 0, "n_a_epoca": 0, "ressalva": RESSALVA}

        achados: dict[str, dict] = {}
        descartados = {"federal": 0, "estadual-rj": 0}   # honestidade: reporta o que saiu e por quê
        q = ("SELECT fornecedor_documento c, fornecedor_nome, orgao_cnpj, orgao_nome, "
             "numero_controle_pncp, objeto, valor_global, valor_inicial, data_assinatura "
             "FROM pcrj_contratos WHERE fonte='pncp' AND length(fornecedor_documento)=14 "
             f"AND fornecedor_documento IN ({','.join('?' * len(sanc))})")
        for r in con.execute(q, list(sanc)):
            # SÓ município do Rio (competência TCM-RJ). A fonte='pncp' colhe pelo território (IBGE
            # 3304557) e arrasta órgão FEDERAL sediado no Rio (ex.: Fiocruz) e, raramente, estadual —
            # jurisdição de outro tribunal. Descarta e contabiliza (não some com o dado em silêncio).
            esf = _cls(r["orgao_nome"] or "", r["orgao_cnpj"] or "") if _cls else "municipal-rio"
            if esf != "municipal-rio":      # lista BRANCA: outro município e "indefinido" também não são a Prefeitura
                descartados[esf] = descartados.get(esf, 0) + 1
                continue
            a = achados.setdefault(r["c"], {
                "cnpj": r["c"], "nome": r["fornecedor_nome"], "sancoes": sanc.get(r["c"], []),
                "contratos": 0, "valor": 0.0, "contratos_durante": 0, "valor_durante": 0.0,
                "contratos_vigente_sem_alcance": 0, "valor_vigente_sem_alcance": 0.0,
                "exemplos_durante": []})
            val = r["valor_global"] or r["valor_inicial"] or 0.0
            dt = (r["data_assinatura"] or "")[:10]
            a["contratos"] += 1
            a["valor"] += val
            vigentes = [s for s in a["sancoes"] if vigente_em(s, dt)]
            com_alcance = [s for s in vigentes if _alcanca_o_municipio_do_rio(s, veda_ente)]
            if vigentes and not com_alcance:
                a["contratos_vigente_sem_alcance"] += 1
                a["valor_vigente_sem_alcance"] += val
            if com_alcance:
                s = com_alcance[0]
                ini, fim = s.get("data_inicio") or "?", s.get("data_fim") or "sem prazo"
                a["contratos_durante"] += 1
                a["valor_durante"] += val
                if len(a["exemplos_durante"]) < 5:
                    a["exemplos_durante"].append(
                        {"contrato": r["numero_controle_pncp"], "orgao": r["orgao_nome"],
                         "objeto": (r["objeto"] or "")[:120], "data": dt, "valor": val,
                         "sancao": s["cadastro"], "vigencia": f"{ini}→{fim}"})

        lista = [a for a in achados.values() if a["valor"] >= min_valor]
        lista.sort(key=lambda a: (-a["valor_durante"], -a["valor"]))
        n_epoca = sum(1 for a in lista if a["contratos_durante"])
        return {"ok": True, "empresas": lista, "n": len(lista), "n_a_epoca": n_epoca,
                "valor_durante_total": round(sum(a["valor_durante"] for a in lista), 2),
                "n_vigente_sem_alcance": sum(1 for a in lista if a["contratos_vigente_sem_alcance"]),
                "valor_vigente_sem_alcance_total": round(sum(a["valor_vigente_sem_alcance"] for a in lista), 2),
                "descartados_outra_esfera": descartados, "ressalva": RESSALVA}
    finally:
        con.close()


def concentracao_municipio(db_path: str | None = None, min_contratos_orgao: int = 8,
                           limite: int = 60) -> dict:
    """Concentração de fornecedor por RAMO DE OBJETO no município do Rio (HHI + top-share)
    sobre ``pcrj_contratos`` — análogo municipal do cartel/concentração do Estado
    (grafo_cartel, que lê OB SIAFE e por isso nunca cobriu a PCRJ).

    Por que RAMO e não órgão: o dado municipal vem TODO agregado numa unidade única
    ("PREFEITURA MUNICIPAL DO RIO DE JANEIRO" — sem secretaria); share sobre o agregado
    diluiria qualquer captura. O mercado relevante é o ramo (limpeza, TI, saúde…), mesma
    taxonomia `_ramo_objeto` do R2/fracionamento do Lex.

    METODOLOGIA (ressalva obrigatória no produto): base = valor **CONTRATADO**
    (valor_global), não PAGO — a PCRJ não tem OB aberta por credor 2024+. Concentração de
    contrato ≠ concentração de pagamento; é screen de captura (R8), não medida de execução.
    Régua do R8 do Lex: top-share ≥60% = forte (grav 4) · ≥40% = médio (grav 3).
    HHI (0-10.000): >2.500 = mercado altamente concentrado (referência CADE/DOJ).
    Gate de esfera idêntico ao sancionadas_municipio (fonte='pncp' + classificar_esfera).
    """
    from compliance_agent.lex_redflags import _RAMOS, _ramo_objeto
    ramos_canonicos = set(_RAMOS)   # dict nome→keywords; fora dele = agrupamento heurístico
    try:
        from compliance_agent.pcrj.esfera import classificar_esfera as _cls
    except ImportError:                     # pragma: no cover
        _cls = None
    con = _ro(db_path)
    try:
        if not _tabela_existe(con, "pcrj_contratos"):
            return {"ok": True, "orgaos": [], "n": 0, "ressalva": RESSALVA}
        por_orgao: dict[str, dict] = {}
        descartados = {"federal": 0, "estadual-rj": 0}
        for r in con.execute(
                "SELECT orgao_cnpj, orgao_nome, objeto, fornecedor_documento c, "
                "fornecedor_nome, valor_global, valor_inicial FROM pcrj_contratos "
                "WHERE fonte='pncp' AND length(fornecedor_documento)=14"):
            esf = _cls(r["orgao_nome"] or "", r["orgao_cnpj"] or "") if _cls else "municipal-rio"
            if esf != "municipal-rio":      # lista BRANCA: outro município e "indefinido" também não são a Prefeitura
                descartados[esf] = descartados.get(esf, 0) + 1
                continue
            chave = _ramo_objeto(r["objeto"] or "") or "objeto não classificado"
            o = por_orgao.setdefault(chave, {"orgao": chave, "total": 0.0, "n_contratos": 0,
                                             "fornecedores": {}})
            val = r["valor_global"] or r["valor_inicial"] or 0.0
            o["total"] += val
            o["n_contratos"] += 1
            f = o["fornecedores"].setdefault(r["c"], {"cnpj": r["c"], "nome": r["fornecedor_nome"],
                                                      "valor": 0.0, "n": 0})
            f["valor"] += val
            f["n"] += 1
        orgaos = []
        for o in por_orgao.values():
            if o["n_contratos"] < min_contratos_orgao or o["total"] <= 0:
                continue  # amostra rasa: share de 2 contratos não é concentração, é acaso
            forns = sorted(o["fornecedores"].values(), key=lambda f: -f["valor"])
            shares = [f["valor"] / o["total"] for f in forns]
            hhi = round(sum(s * s for s in shares) * 10000)
            top = forns[0]
            top_share = round(shares[0] * 100, 1)
            grav = 4 if top_share >= 60 else (3 if top_share >= 40 else 0)
            orgaos.append({"orgao": o["orgao"], "total": o["total"], "n_contratos": o["n_contratos"],
                           "n_fornecedores": len(forns), "hhi": hhi, "top_share": top_share,
                           "grav": grav, "ramo_canonico": o["orgao"] in ramos_canonicos,
                           "top_fornecedor": {"cnpj": top["cnpj"], "nome": top["nome"],
                                              "valor": top["valor"], "n": top["n"]},
                           "top3": [{"cnpj": f["cnpj"], "nome": f["nome"], "valor": f["valor"],
                                     "share": round(fs * 100, 1)}
                                    for f, fs in list(zip(forns, shares))[:3]]})
        orgaos.sort(key=lambda o: (-o["grav"], -o["hhi"]))
        n_criticos = sum(1 for o in orgaos if o["grav"] >= 3)
        return {"ok": True, "orgaos": orgaos[:limite], "n": len(orgaos), "n_criticos": n_criticos,
                "descartados_outra_esfera": descartados,
                "ressalva": RESSALVA + " Base = valor CONTRATADO (PNCP municipal), não pago — "
                "a PCRJ não publica pagamento por credor 2024+ (INDISPONÍVEL ≠ 0). Mercado = ramo "
                "de objeto; ramos SEM selo canônico são agrupamento heurístico de 2 palavras "
                "(conferir o objeto real antes de concluir — ex.: clínica pode cair em "
                "'vigilância' por 'segurança do paciente')."}
    finally:
        con.close()


# ── 2. PERDEDORAS CONTUMAZES (nunca ganharam) ────────────────────────────────

def perdedoras_contumazes(db_path: str | None = None, min_certames: int = 3,
                          limite_atas: int = 8000) -> dict:
    """Licitantes que participam de ≥K certames (nas atas) e NUNCA vencem — candidatas a
    proposta de cobertura. Enriquecidas com nome e com quem 'perdem junto'."""
    from compliance_agent.rodizio_grafo import analisar_atas, coletar_atas_do_corpus
    atas = coletar_atas_do_corpus(db_path or _DB, limite=limite_atas)
    res = analisar_atas(atas, min_certames=min_certames)
    con = _ro(db_path)
    try:
        nomes: dict[str, str] = {}
        for r in con.execute("SELECT DISTINCT fornecedor_cnpj, fornecedor_nome FROM pncp_resultado "
                             "WHERE fornecedor_nome IS NOT NULL"):
            nomes.setdefault(r["fornecedor_cnpj"], r["fornecedor_nome"])
        for r in con.execute("SELECT favorecido_cpf, favorecido_nome FROM favorecido_resumo"):
            nomes.setdefault(r["favorecido_cpf"], r["favorecido_nome"])
    finally:
        con.close()

    def _fmt(c: str) -> str:
        return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}" if len(c) == 14 else c

    cobertura = []
    for c in res.get("cobertura", []):
        cid = c["licitante"]
        cobertura.append({
            "cnpj": cid, "cnpj_fmt": _fmt(cid), "nome": nomes.get(cid, "—"),
            "participou": c["participou"], "venceu": 0,
            "perde_junto_com": [{"cnpj": _fmt(co), "nome": nomes.get(co, "—"), "vezes": n}
                                for co, n in c.get("co_frequentes", [])],
        })
    return {"ok": True, "perdedoras": cobertura, "n": len(cobertura),
            "cobertura_extracao": res.get("cobertura_extracao", {}),
            "explicacao": ("Empresa que compete 'sempre' e nunca vence é o perfil clássico de "
                           "PROPOSTA DE COBERTURA (OCDE bid rigging): existe para dar aparência "
                           "de disputa e legitimar o vencedor combinado. Quanto mais vezes perde "
                           "junto do MESMO vencedor, mais forte o indício."),
            "ressalva": "Indício estatístico das atas — corroborar QSA, endereços e propostas. "
                        "Indício ≠ acusação; pode haver azar competitivo legítimo."}


# ── 3. FANTASMAS EM ESCALA ───────────────────────────────────────────────────

def init_fantasma_schema(con: sqlite3.Connection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS fantasma_score (
            cnpj          TEXT PRIMARY KEY,
            razao_social  TEXT,
            score         INTEGER,
            classificacao TEXT,               -- alto | medio | baixo | sem_cadastro
            sinais_json   TEXT,
            origem        TEXT,               -- por que entrou no alvo (captura/cover/sancionada/top_favorecido)
            avaliado_em   TEXT DEFAULT (datetime('now'))
        )""")
    con.commit()


def alvos_fantasma(db_path: str | None = None, top_favorecidos: int = 300) -> dict[str, str]:
    """Conjunto-ALVO {cnpj: origem}: vencedoras de captura/rodízio + perdedoras contumazes +
    sancionadas contratadas + top favorecidos SIAFE por valor."""
    alvos: dict[str, str] = {}
    con = _ro(db_path)
    try:
        from compliance_agent.collectors.pncp_resultados import conluio_enriquecido
        pad = conluio_enriquecido(con, min_certames=4)
        for cap in pad.get("captura", []):
            alvos.setdefault(cap["vencedor"], "captura")
        for rod in pad.get("rodizio_vencedores", []):
            for c in rod.get("grupo", []):
                alvos.setdefault(c, "rodizio")
        for r in con.execute(
                "SELECT favorecido_cpf c, SUM(total_pago) t FROM favorecido_resumo "
                f"WHERE {SQL_FAVORECIDO_PJ} GROUP BY 1 ORDER BY t DESC LIMIT ?",
                (top_favorecidos,)):
            alvos.setdefault(r["c"], "top_favorecido")
    except Exception as exc:
        logger.warning("alvos de conluio/favorecidos parciais: %s", exc)
    finally:
        con.close()
    try:
        for p in perdedoras_contumazes(db_path).get("perdedoras", []):
            alvos.setdefault(p["cnpj"], "perdedora_contumaz")
    except Exception as exc:
        logger.warning("perdedoras contumazes fora do alvo: %s", exc)
    try:
        for e in sancionadas_contratadas(db_path).get("empresas", []):
            alvos.setdefault(e["cnpj"], "sancionada_contratada")
    except Exception as exc:
        logger.warning("sancionadas fora do alvo: %s", exc)
    return alvos


def avaliar_fantasmas(db_path: str | None = None, alvos: dict[str, str] | None = None) -> dict:
    """Aplica os 8 sinais (/fantasma) ao conjunto-alvo e persiste em fantasma_score.
    CNPJ sem cadastro local → 'sem_cadastro' (não é 'baixo'; INDISPONÍVEL ≠ 0)."""
    from compliance_agent.empresa_fantasma import avaliar_cnpj
    from compliance_agent.nucleo.telegram_nucleo import _sessao
    alvos = alvos or alvos_fantasma(db_path)
    wcon = sqlite3.connect(db_path or _DB, timeout=60)
    wcon.execute("PRAGMA busy_timeout=60000")
    init_fantasma_schema(wcon)
    session = _sessao()
    n_aval = n_sem = 0
    try:
        for cnpj, origem in alvos.items():
            try:
                r = avaliar_cnpj(session, cnpj)
            except Exception as exc:
                logger.debug("avaliar_cnpj falhou p/ %s: %s", cnpj, exc)
                r = None
            # sem linha em `empresas` = sem cadastro → não dá para afirmar score
            tem_cadastro = bool(r and (r.get("razao_social") or any(
                s.get("id") not in (None, "sancionada") for s in r.get("sinais", []))))
            if r and tem_cadastro:
                wcon.execute(
                    "INSERT OR REPLACE INTO fantasma_score(cnpj,razao_social,score,classificacao,"
                    "sinais_json,origem) VALUES(?,?,?,?,?,?)",
                    (cnpj, r.get("razao_social"), r.get("score"), r.get("classificacao"),
                     json.dumps(r.get("sinais", []), ensure_ascii=False), origem))
                n_aval += 1
            else:
                wcon.execute(
                    "INSERT OR REPLACE INTO fantasma_score(cnpj,razao_social,score,classificacao,"
                    "sinais_json,origem) VALUES(?,?,NULL,'sem_cadastro','[]',?)",
                    (cnpj, (r or {}).get("razao_social"), origem))
                n_sem += 1
        wcon.commit()
    finally:
        session.close()
        wcon.close()
    return {"ok": True, "avaliados": n_aval, "sem_cadastro": n_sem, "alvo": len(alvos)}


def ranking_fantasmas(db_path: str | None = None, limite: int = 50) -> dict:
    """Lê fantasma_score (gerado por avaliar_fantasmas/tools.intel_sweep) — ranking p/ o painel."""
    con = _ro(db_path)
    try:
        try:
            rows = [dict(r) for r in con.execute(
                "SELECT cnpj, razao_social, score, classificacao, sinais_json, origem, avaliado_em "
                "FROM fantasma_score ORDER BY (score IS NULL), score DESC LIMIT ?", (limite,))]
        except sqlite3.OperationalError:
            return {"ok": False, "erro": "fantasma_score ainda não gerado — rodar tools/intel_sweep.py"}
        sem = con.execute("SELECT COUNT(*) FROM fantasma_score WHERE classificacao='sem_cadastro'").fetchone()[0]
        tot = con.execute("SELECT COUNT(*) FROM fantasma_score").fetchone()[0]
        for r in rows:
            r["sinais"] = json.loads(r.pop("sinais_json") or "[]")
        return {"ok": True, "empresas": rows, "total_alvo": tot, "sem_cadastro": sem,
                "explicacao": ("Score 0-100 por 8 sinais objetivos (situação cadastral irregular, "
                               "capital incompatível, endereço-ninho, endereço residencial, aberta às "
                               "vésperas do contrato, sócio único + capital baixo, CNAE incompatível, "
                               "sanção CEIS/CNEP). 'sem_cadastro' = Receita ainda não consultada — "
                               "não significa regular NEM fantasma."),
                "ressalva": "Triagem determinística; indício ≠ acusação."}
    finally:
        con.close()


# ── RADAR DE RISCO composto (funde os detectores num ranking único) ──────────

_RADAR_PESOS = {
    "conluio_forte": 30, "conluio_medio": 15,
    "sancao_a_epoca": 25, "sancao_fora_vigencia": 10,
    "fantasma_alto": 20, "fantasma_medio": 10,
    "socio_servidor": 15, "perdedora_contumaz": 10, "fenix": 10,
    "capital_irrisorio": 15,
    "hub_massa": 12,   # membro de ninho 'alto' do hub_compartilhado (via cache — Task 1.7)
}


def radar_risco(db_path: str | None = None, limite: int = 100) -> dict:
    """RADAR: score composto 0-100 por fornecedor, somando os sinais dos detectores já
    existentes (pesos em _RADAR_PESOS; escala explícita no retorno). Um fornecedor que
    acende VÁRIOS detectores ao mesmo tempo sobe ao topo — é o "onde olhar primeiro".
    Determinístico; lê caches quando o cruzamento é pesado (perdedoras/conluio)."""
    sin: dict[str, list] = {}

    def _add(cnpj, sinal, detalhe=""):
        if cnpj and len(cnpj) == 14:
            sin.setdefault(cnpj, []).append(
                {"sinal": sinal, "peso": _RADAR_PESOS[sinal], "detalhe": (detalhe or "")[:60]})

    # conluio direto (cache → cálculo rápido sem atas)
    try:
        d = (ler_cache_intel("conluio_qsa") if db_path is None else None) \
            or conluio_qsa(db_path, incluir_atas=False)
        for p in d.get("pares", []):
            forte = p["tier"] in ("MESMA_EMPRESA", "ALTA")
            for lado in ("vencedor", "perdedora"):
                _add(p[lado]["cnpj"], "conluio_forte" if forte else "conluio_medio",
                     f"{p['tier']} com {p['perdedora' if lado == 'vencedor' else 'vencedor']['nome']}")
    except Exception as exc:
        logger.warning("radar sem conluio: %s", exc)
    # sancionadas contratadas
    try:
        d = (ler_cache_intel("sancionadas_contratadas") if db_path is None else None) \
            or sancionadas_contratadas(db_path)
        for e in d.get("empresas", []):
            epoca = e["estado"]["obs_durante"] or e["pncp"]["vitorias_durante"]
            _add(e["cnpj"], "sancao_a_epoca" if epoca else "sancao_fora_vigencia",
                 (e["sancoes"][0].get("cadastro", "") if e.get("sancoes") else ""))
    except Exception as exc:
        logger.warning("radar sem sancionadas: %s", exc)
    con = _ro(db_path)
    try:
        # fantasma + sócio-servidor direto das tabelas persistidas
        for r in con.execute("SELECT cnpj, classificacao, razao_social FROM fantasma_score "
                             "WHERE classificacao IN ('alto','medio')"):
            _add(r["cnpj"], f"fantasma_{r['classificacao']}", r["razao_social"])
        for r in con.execute("SELECT DISTINCT cnpj, socio_nome FROM socios_fornecedor "
                             "WHERE socio_servidor=1"):
            _add(r["cnpj"], "socio_servidor", r["socio_nome"])
    except sqlite3.OperationalError as exc:
        logger.debug("radar: %s", exc)
    finally:
        con.close()
    # perdedoras contumazes e hub-ninho (só cache — cruzamentos de minutos) e fênix (rápido)
    if db_path is None:
        for p in (ler_cache_intel("perdedoras_contumazes") or {}).get("perdedoras", []):
            _add(p["cnpj"], "perdedora_contumaz", f"participou {p['participou']}x, venceu 0")
        for g in (ler_cache_intel("hub_compartilhado") or {}).get("grupos", []):
            if g.get("risco") == "alto":
                for c in g.get("cnpjs", []):
                    _add(c, "hub_massa", f"{g.get('n_cnpjs')} CNPJs no mesmo {g.get('chave')}")
    try:
        # revisão 13/11/2026 (D1/D2): só pagamento DEPOIS da baixa confirmada é sinal; a lista inteira
        # (o corte em 120 deixava de fora quem vinha depois na ordenação por valor)
        for a in empresa_fenix(db_path, limite=None).get("achados", []):
            if a.get("pagou_apos_baixa") is True:
                _add(a.get("cnpj"), "fenix", a.get("situacao") or a.get("motivo") or "")
    except Exception as exc:
        logger.warning("radar sem fênix: %s", exc)
    try:
        for a in capital_incompativel(db_path).get("achados", []):
            _add(a.get("cnpj"), "capital_irrisorio", f"cap R${a.get('capital'):,.0f}, {a.get('razao')}x")
    except Exception as exc:
        logger.warning("radar sem capital: %s", exc)

    # nomes + montagem
    con = _ro(db_path)
    try:
        nomes = {r["favorecido_cpf"]: r["favorecido_nome"] for r in con.execute(
            "SELECT favorecido_cpf, favorecido_nome FROM favorecido_resumo")} \
            if _tabela_existe(con, "favorecido_resumo") else {}
        if _tabela_existe(con, "pncp_resultado"):
            for r in con.execute("SELECT DISTINCT fornecedor_cnpj, fornecedor_nome "
                                 "FROM pncp_resultado WHERE fornecedor_nome IS NOT NULL"):
                nomes.setdefault(r["fornecedor_cnpj"], r["fornecedor_nome"])
    finally:
        con.close()
    achados = []
    for cnpj, sinais in sin.items():
        vistos, uniq = set(), []
        for s in sinais:                      # mesmo sinal 2x (ex.: 2 pares) conta 1x
            if s["sinal"] not in vistos:
                vistos.add(s["sinal"])
                uniq.append(s)
        score = min(sum(s["peso"] for s in uniq), 100)
        achados.append({
            "cnpj": cnpj,
            "cnpj_fmt": f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}",
            "nome": nomes.get(cnpj, "—"), "score": score,
            "rating": "🔴" if score >= 50 else ("🟡" if score >= 25 else "🟢"),
            "n_sinais": len(uniq), "sinais": uniq})
    achados.sort(key=lambda a: (-a["score"], -a["n_sinais"]))
    return {"ok": True, "achados": achados[:limite], "n": len(achados),
            "n_vermelho": sum(1 for a in achados if a["score"] >= 50),
            "escala": ("Score 0-100 somando sinais independentes (cada tipo conta 1x): "
                       + ", ".join(f"{k} +{v}" for k, v in _RADAR_PESOS.items())
                       + ". 🔴 ≥50 · 🟡 25-49 · 🟢 <25."),
            "explicacao": ("Um detector isolado é indício fraco; vários detectores acesos no "
                           "MESMO fornecedor raramente são coincidência. O radar prioriza a "
                           "fila de apuração."),
            "ressalva": RESSALVA}


def _tabela_existe(con, nome: str) -> bool:
    return bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                            (nome,)).fetchone())


# ── cache p/ endpoints (perdedoras varre 8k atas — não roda no request) ──────

def fracionamento(db_path: str | None = None, min_obs: int = 5, min_colado: int = 3,
                  banda: float = 0.85, limite: int = 120) -> dict:
    """Possível FRACIONAMENTO de despesa: mesmo favorecido + mesma UG + mesmo MÊS com muitas OBs,
    várias delas "coladas no teto" de dispensa (85-100% do limite do ano) — padrão de fatiar a
    compra para caber embaixo do limite e fugir da licitação (Lei 14.133 art. 75 §1º).
    Ordena pela CONCENTRAÇÃO colada no teto (separa dodging deliberado de fornecimento contínuo:
    utilidade/combustível tem valores variados, baixa concentração)."""
    con = _ro(db_path)
    try:
        iso_mes = "substr(data_emissao,7,4)||'-'||substr(data_emissao,4,2)"
        ano = "CAST(substr(data_emissao,7,4) AS INT)"
        # teto do ano via CASE (SQLite não tem dict); banda = 85% do teto
        casos_teto = " ".join(f"WHEN {a} THEN {t}" for a, t in _TETO_DISPENSA.items())
        teto_expr = f"(CASE {ano} {casos_teto} ELSE {_TETO_DEFAULT} END)"
        # 23/11/2026 — medido nos 542 grupos: 250 sem processo na OB, 3 de processo único (parcelas de UM contrato),
        # 27 ente público (natureza 1xxx), 9 OS/OSC, 17 DEA/indenização (NE 339092/93); nenhum verificável como
        # fracionamento. Parcelas do MESMO processo não são contratações distintas: exige-se ≥ `min_colado`
        # processos distintos entre as OBs coladas (mesma régua da triagem SIAFE). Ainda assim o processo da OB é,
        # na SES, o processo de PAGAMENTO (um por fatura) — a lista é SINAL DE ONDE PUXAR, nunca achado.
        # favorecido que é ENTE PÚBLICO = repasse/transferência (fundo-a-fundo, parcelas iguais),
        # não compra fatiada — fora do detector (senão vira falso-positivo).
        # a cópia local divergente saiu: uma fonte só (_SQL_NAO_PUBLICO), definida abaixo.
        publico = _SQL_NAO_PUBLICO
        # O4.9 — RESTOS A PAGAR fora: a OB de RP paga despesa empenhada em exercício anterior (Lei 4.320 arts. 35, II, e
        # 36); somá-la ao mês do pagamento contra o teto do ano da OB mistura exercícios. Sem o ano do empenho na OB, sai.
        from compliance_agent.dominio.pagamento import TIPO_OB_RP
        if "tipo_ob" in {r[1] for r in con.execute("PRAGMA table_info(ob_orcamentaria_siafe)")}:
            nao_rp = "COALESCE(tipo_ob,'') NOT IN (" + ",".join("'" + t.replace("'", "''") + "'"
                                                              for t in sorted(TIPO_OB_RP)) + ")"
            publico = f"{publico} AND {nao_rp}"
        q = f"""
        SELECT credor, MAX(nome_credor) nome, ug_emitente, {iso_mes} mes,
               COUNT(*) n, SUM(valor) soma, MAX(valor) maior,
               SUM(CASE WHEN valor >= {banda}*{teto_expr} AND valor < {teto_expr} THEN 1 ELSE 0 END) n_colado,
               MAX({teto_expr}) teto, COUNT(DISTINCT NULLIF(processo,'')) n_processos
        FROM ob_orcamentaria_siafe
        WHERE {_ob_paga(con)} AND length(credor)=14 AND valor>0 AND valor < {teto_expr} AND {publico}
        GROUP BY credor, ug_emitente, {iso_mes}
        HAVING n >= ? AND n_colado >= ? AND n_processos >= ?
        ORDER BY (CAST(n_colado AS REAL)/n) DESC, soma DESC
        LIMIT ?"""
        rows = [dict(r) for r in con.execute(q, (min_obs, min_colado, min_colado, limite))]
        for r in rows:
            r["concentracao"] = round(r["n_colado"] / r["n"], 2) if r["n"] else 0
            r["cnpj_fmt"] = (f"{r['credor'][:2]}.{r['credor'][2:5]}.{r['credor'][5:8]}/"
                             f"{r['credor'][8:12]}-{r['credor'][12:]}") if len(r["credor"] or "") == 14 else r["credor"]
        # total (sem limite) p/ KPI
        total = con.execute(f"""SELECT COUNT(*) FROM (
            SELECT credor FROM ob_orcamentaria_siafe
            WHERE {_ob_paga(con)} AND length(credor)=14 AND valor>0 AND valor < {teto_expr} AND {publico}
            GROUP BY credor, ug_emitente, {iso_mes}
            HAVING COUNT(*) >= ? AND
              SUM(CASE WHEN valor >= {banda}*{teto_expr} AND valor < {teto_expr} THEN 1 ELSE 0 END) >= ? AND
              COUNT(DISTINCT NULLIF(processo,'')) >= ?)""",
            (min_obs, min_colado, min_colado)).fetchone()[0]
        return {"ok": True, "grupos": rows, "n": total, "mostrados": len(rows),
                "natureza": "sinal de onde puxar — agrega PAGAMENTO por credor/mês, não lê contratação",
                "explicacao": ("SINAL, não achado: mesmo favorecido, mesma unidade gestora e mesmo mês, com "
                               "várias OBs logo abaixo do teto de dispensa, em processos distintos. Pode ser o "
                               "padrão de fatiar a compra (Lei 14.133 art. 75 §1º), mas também parcela mensal de "
                               "contrato contínuo, indenização (DEA) ou processo de pagamento por fatura — só a "
                               "leitura das CONTRATAÇÕES (objeto, modalidade, data) separa."),
                "ressalva": ("OB é PAGAMENTO, não empenho/contrato — o fracionamento se prova no "
                             "processo de contratação. Cruzar com os empenhos/processos do mês antes de "
                             "concluir; fornecimento contínuo (água, energia, combustível) pode explicar "
                             "o volume. Indício ≠ acusação.")}
    finally:
        con.close()


def aditivos_estouro(db_path: str | None = None, limite: int = 120,
                     esfera: str | None = None) -> dict:
    """Aditivos que estouram o limite legal de acréscimo (Lei 14.133 art. 125; Lei 8.666 art. 65 §1º
    — 25% p/ compras/serviços/obras, 50% p/ reforma). Usa pcrj_contratos (valor_inicial × valor_global)
    e cruza com contrato_aditivo p/ separar ACRÉSCIMO real de reajuste (qualif_acrescimo). Também
    marca CHANGE ORDERS EM SÉRIE (≥3 aditivos — red-flag OCDE/Banco Mundial), mesmo sem estouro de valor.

    `esfera`: "estado" | "prefeitura" | … (vocabulário de `pncp_resultados.ESFERAS`); None = ESCOPO DA CASA
    (Estado do RJ + Prefeitura do Rio, com `por_esfera`); "todas" = opt-in explícito de quem pesquisa fora.
    Até 20/11/2026 None varria a tabela inteira: 68 dos 120 achados servidos eram de órgão FEDERAL."""
    # PARÂMETRO PRIMEIRO, banco depois. Rótulo fora do vocabulário não pode virar lista vazia:
    # "estadual" (em vez de "estado") devolvia ZERO achados sobre uma base com 260 — o filtro mentia
    # com cara de resposta. E validar antes de abrir conexão faz a recusa valer também sobre base
    # vazia, que é justamente onde o zero engana mais.
    if esfera and esfera != "todas":
        from compliance_agent.collectors.pncp_resultados import ESFERAS as _ESFERAS
        if esfera not in _ESFERAS:
            return {"ok": False, "achados": [], "n": 0,
                    "erro": (f"esfera '{esfera}' não existe — use uma de {list(_ESFERAS)} ou "
                             "'todas'. Lista vazia aqui seria NÃO MEDIDO, não 'nada a apurar'.")}
    con = _ro(db_path)
    try:
        # acréscimos reais (não reajuste) por contrato, do contrato_aditivo (fonte granular)
        # A natureza de cada termo vem de `limites_aditivo.classificar_natureza` — a MESMA régua
        # do X1, do thoughts e da varredura de execução. Antes, o filtro era
        # `qualif_acrescimo='1'`, campo que a própria casa já havia declarado inútil em
        # `contratos/thoughts` ("vem '1' para quase tudo"): prorrogação e reequilíbrio entravam
        # como acréscimo. Foi o mesmo erro que produziu 45% de falso positivo na estreia da
        # varredura de execução (2026-07-29), lá com R$ 40,6 mi de revisão do art. 124.
        # 2026-11-19: a DECISÃO também é única — `limites_aditivo.avaliar_contrato`, a mesma do
        # D11 da Prefeitura. Antes, termos lidos sem nenhum acréscimo caíam no `vg − vi` (o global
        # que a coleta estadual reescreve como inicial + Σ termos de QUALQUER natureza) e saíam
        # como estouro: medido, 169 "estouros" do Estado, 167 deles sem um termo de acréscimo.
        from compliance_agent.limites_aditivo import avaliar_contrato
        por_contrato: dict[str, list[dict]] = {}
        try:
            # A lista de colunas é montada a partir do schema REAL. Pedir uma coluna que não
            # existe levantaria OperationalError e o `except` engoliria a tabela inteira — todos
            # os contratos cairiam em vg−vi silenciosamente, que é justamente o número que não
            # se pode usar. Schema parcial degrada campo a campo, não de uma vez.
            existentes = {r[1] for r in con.execute("PRAGMA table_info(contrato_aditivo)")}
            uteis = [c for c in ("objeto", "valor_acrescido", "prazo_aditado_dias",
                                 "qualif_acrescimo", "qualif_vigencia", "qualif_reajuste",
                                 "fundamento_legal", "valor_global", "sequencial_termo",
                                 "data_assinatura", "tipo_termo") if c in existentes]
            for r in con.execute(
                    f"SELECT numero_controle_pncp c{',' if uteis else ''}{','.join(uteis)} "
                    "FROM contrato_aditivo"):
                por_contrato.setdefault(r["c"], []).append(dict(r))
        except sqlite3.OperationalError:
            logging.getLogger(__name__).debug("exceção tolerada em cruzamentos_intel", exc_info=True)
        _cols_c = {r[1] for r in con.execute("PRAGMA table_info(pcrj_contratos)")}
        _chk = "aditivos_checados" if "aditivos_checados" in _cols_c else "NULL"
        # sanity: exclui valor_global lixo (> R$ 1 bi quase sempre é erro de coleta do PNCP)
        rows = con.execute(
            "SELECT numero_controle_pncp cc, fornecedor_nome, fornecedor_documento, orgao_nome, "
            f"unidade, objeto, valor_inicial vi, valor_global vg, num_aditivos, vigencia_fim, "
            f"{_chk} chk FROM pcrj_contratos WHERE valor_inicial>1000 AND valor_global>0 "
            "AND valor_global<1e9 AND valor_inicial<1e9").fetchall()
        # esfera do CONTRATO = esfera oficial do ENTE dono (CNPJ embutido no nº de controle PNCP);
        # a tabela pcrj_contratos, apesar do nome, guarda contratos de TODOS os entes coletados.
        esfera_de = None
        alvo: set = set()
        if esfera != "todas":
            from compliance_agent.collectors.pncp_resultados import (
                ESFERAS_RJ, classificar_esfera, esferas_por_ente)
            oficial = esferas_por_ente(con)
            alvo = {esfera} if esfera else set(ESFERAS_RJ)

            def esfera_de(cc, orgao_nome, unidade):  # noqa: E306
                cnpj_ente = re.sub(r"\D", "", str(cc or "").split("-")[0])[:14]
                reg = {"orgao_cnpj": cnpj_ente, "orgao_nome": orgao_nome,
                       "unidade_nome": unidade, "municipio": ""}
                return classificar_esfera(reg, oficial)
        achados = []
        fora_do_escopo: dict[str, int] = {}
        n_universo = 0   # o "de quantos?" é o da ESFERA pedida, não a tabela inteira (antes: 90.905
        for r in rows:   # contratos "analisados" na aba da Prefeitura, que tem 2,6 mil)
            esf_r = esfera_de(r["cc"], r["orgao_nome"], r["unidade"]) if esfera_de else None
            if esfera_de and esf_r not in alvo:
                fora_do_escopo[esf_r] = fora_do_escopo.get(esf_r, 0) + 1
                continue
            n_universo += 1
            vi, vg, nad = r["vi"], r["vg"], r["num_aditivos"] or 0
            ads = por_contrato.get(r["cc"]) or []
            av = avaliar_contrato(vi, ads, r["objeto"], valor_global=vg,
                                  termos_coletados=None if r["chk"] is None else bool(r["chk"]))
            # VERIFICADO = acréscimo computável NOS TERMOS acima do teto (inclusivo), sem
            # incoerência de base; PENDENTE = há sinal, a prova não fecha (motivo declarado).
            estouro = av["estado"] == "VERIFICADO"
            pendente = av["estado"] == "PENDENTE"
            # SÉRIE de acréscimos, não de termos: prorrogação de contínuo e reajuste também são "aditivo". Com os
            # termos lidos, contam só os de natureza VALOR em datas distintas (24/11/2026: dos 138 contratos com termos
            # lidos, 100 não tinham nenhum termo de acréscimo e só 5 tinham 3+). Sem termos lidos, fica o
            # `num_aditivos` do PNCP, com a natureza declarada INDETERMINADA no item.
            if ads:
                n_acresc = len({t.get("data") or t.get("seq") for t in av["termos"] if t.get("natureza") == "valor"})
                serie = n_acresc >= 3
            else:
                n_acresc = None
                serie = nad >= 3
            if not (estouro or pendente or serie):
                continue
            pct = av["pct"] if av["pct"] is not None else (av["pct_global"] or 0)
            cnpj = re.sub(r"\D", "", r["fornecedor_documento"] or "")
            achados.append({
                "contrato": r["cc"], "fornecedor": r["fornecedor_nome"], "esfera": esf_r,
                "cnpj": cnpj, "cnpj_fmt": (f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}"
                                           if len(cnpj) == 14 else cnpj),
                "orgao": r["unidade"] or r["orgao_nome"], "objeto": (r["objeto"] or "")[:160],
                "valor_inicial": vi, "valor_global": vg, "acrescimo": round(vg - vi, 2),
                "pct": round(pct * 100, 1), "num_aditivos": nad, "teto_pct": av["teto_pct"],
                "n_termos_acrescimo": n_acresc,
                "serie_natureza": ("termos de acréscimo" if n_acresc is not None
                                   else "indeterminada — termos não lidos (pode ser prorrogação/reajuste)"),
                # O art. 125 mede sobre o "valor inicial ATUALIZADO", e aqui a base é o inicial CRU:
                # a varredura roda sobre todo o PNCP, onde não há índice nem data-base para corrigir.
                # O efeito é superestimar. Medido em 2026-08-10 no caso VR Benefícios: o termo declara
                # "acréscimo de 25%" e R$ 20.000 é exatamente 25% de R$ 80.000 — a unidade usou o
                # valor atualizado, e o nosso 26,4% acusava estouro num aditivo LÍCITO. Quem tem o
                # índice é o `x1_crescimento_aditivo` (recebe `indice_atualizacao` do contexto dos
                # autos); aqui a base sai DECLARADA para ninguém ler o percentual como definitivo.
                "base_do_percentual": "valor_inicial (NÃO atualizado — o art. 125 mede sobre o "
                                      "atualizado; percentual rente ao teto pode ser lícito)",
                "estoura_teto": estouro,
                "acrescimo_real": (round(av["acrescimo"], 2) if av["acrescimo"] else None),
                "acrescimo_confirmado": bool(ads) and bool(av["acrescimo"]),
                "lacunas_aditivo": av["lacunas"],
                "estado": av["estado"], "motivos": av["motivos"], "resumo": av["resumo"],
                "termos": av["termos"],
                "tipo": ("estouro" if estouro else "pendente" if pendente else "serie"),
                "vigencia_fim": r["vigencia_fim"]})
        # ranking: estoura o teto legal primeiro, acréscimo CONFIRMADO antes do não confirmado
        # (vg−vi pode ser só reajuste), depois maior %/mais aditivos
        achados.sort(key=lambda a: ({"estouro": 0, "pendente": 1}.get(a["tipo"], 2),
                                    not a["acrescimo_confirmado"],
                                    -(a["pct"] or 0), -(a["num_aditivos"] or 0)))
        n_estouro = sum(1 for a in achados if a["estoura_teto"])
        n_pendente = sum(1 for a in achados if a["tipo"] == "pendente")
        n_serie = sum(1 for a in achados if a["tipo"] == "serie")
        por_esfera: dict[str, int] = {}
        for a in achados:
            if a["esfera"]:
                por_esfera[a["esfera"]] = por_esfera.get(a["esfera"], 0) + 1
        return {"ok": True, "achados": achados[:limite], "n": len(achados),
                "n_estoura_teto": n_estouro, "n_pendente": n_pendente, "n_serie": n_serie,
                "contratos_analisados": n_universo,
                "escopo": ("todas as esferas (pesquisa)" if esfera == "todas" else esfera
                           or "Estado do RJ + Prefeitura do Rio (ver por_esfera; nunca somar as duas)"),
                "por_esfera": por_esfera, "fora_do_escopo": fora_do_escopo,
                "explicacao": ("VERIFICADO = soma dos acréscimos quantitativos NOS TERMOS ADITIVOS "
                               "acima do teto do art. 125 da Lei 14.133 (25%; 50% só para reforma de "
                               "edifício ou equipamento; até o teto é lícito). Reajuste, repactuação, "
                               "reequilíbrio (arts. 124 II-d, 134, 135), prorrogação e supressão não "
                               "entram. PENDENTE = há sinal mas a prova não fecha (termo não coletado, "
                               "percentual declarado no termo dentro do teto, base incompatível, excesso "
                               "que a atualização do inicial explica). Também marca CHANGE ORDERS EM "
                               "SÉRIE (≥3 aditivos, red-flag OCDE/Banco Mundial). Régua única: "
                               "limites_aditivo.avaliar_contrato."),
                "ressalva": ("PENDENTE não é estouro: valor global − inicial NÃO é acréscimo (o global "
                             "do PNCP cobre o período e inclui reajuste e prorrogação). Base do "
                             "percentual = valor inicial publicado, não atualizado. Pagamento por "
                             "contrato INDISPONÍVEL (sem ponte contrato↔OB). Indício ≠ acusação.")}
    finally:
        con.close()


def _norm_nome(s: str) -> str:
    """Normaliza nome de pessoa p/ casar sócio×servidor: maiúsculas, sem acento, só letras."""
    import unicodedata
    s = unicodedata.normalize("NFKD", (s or "").upper())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z ]", " ", s)).strip()


def _frag6(doc: str) -> str:
    """Os 6 dígitos visíveis de um CPF mascarado (senão '')."""
    d = re.sub(r"\D", "", doc or "")
    return d if len(d) == 6 else ""


# favorecido NÃO-comercial: servidor é membro/dirigente pela profissão, não dono-fornecedor
_RX_NAOCOM = re.compile(
    r"MUTUA|\bFUND\b|FUNDAC|INSTITUTO|ASSOCIA|CAIXA DE ASSIST|CAIXA ESCOLAR|COOPERATIVA|SINDICATO|"
    r"CONSELHO|FEDERAC|CONFEDERAC|\bOAB\b|IGREJA|PARTIDO|VIVA RIO|CRUZ VERMELHA|APAE|SANTA CASA|"
    r"OSCIP|\bONG\b|\bAAE\b|\bAEE\b|GREMIO|\bCLUBE\b|CARTORIO|SERVICO NOTARIAL|SOCIEDADE BENEF|"
    r"\bFORUM\b|ESCOLA SUP|CENTRO ACAD|DIRETORIO|CAMARA DOS|ORDEM DOS")
# qualificação de DONO/gerência (servidor-administrador de empresa privada = vedação estatutária)
_RX_DONO = re.compile(r"SOCIO|ADMINISTRADOR|TITULAR|EMPRESARIO|PROPRIET|PRESIDENTE|DIRETOR")
_RX_GERENCIA = re.compile(r"ADMINISTRADOR|PRESIDENTE|DIRETOR|TITULAR|GERENTE")


def socio_servidor(db_path: str | None = None, limite: int = 150) -> dict:
    """Servidor público (folha) que é SÓCIO-dono de empresa paga pelo Estado — Lei 14.133 art. 9 e vedação
    estatutária de gerência. Delegado a `socio_na_folha` (19/11/2026): identidade desambiguada em camadas
    por `identidade_pessoa` (CPF na janela AFERIDA de cada folha — GESPERJ 4–9, DPRJ 3–8 —, prevalência do
    nome, faixa etária da Receita), uma linha por pessoa, OB paga do SIAFE por UG e art. 9 com o mapa
    órgão→UG conferido. A versão anterior presumia a janela 3–8 para toda folha: 911 "homônimos" e 0
    casamento no Executivo. Par só-por-nome não entra em `achados` (vai para `indeterminados`)."""
    from compliance_agent import socio_na_folha
    return socio_na_folha.para_api(socio_na_folha.calcular(db_path), limite=limite)


def _norm_item(desc: str) -> str:
    """Normaliza a descrição do item p/ agrupar compras comparáveis: minúsculas, sem acento,
    sem plural simples, sem pontuação/números soltos. 'Ventiladores' e 'VENTILADOR' → 'ventilador'."""
    import unicodedata
    s = unicodedata.normalize("NFKD", (desc or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    toks = []
    for t in s.split():
        if len(t) < 3 or t.isdigit():
            continue
        t = re.sub(r"(es|s)$", "", t) if len(t) > 4 else t  # plural simples
        toks.append(t)
    return " ".join(sorted(set(toks)))  # ordem-insensível: "caneta azul" == "azul caneta"


TOKENS_ITEM_COMPARAVEL = 3   # descrição com <3 tokens úteis não sustenta comparação de preço


def comparabilidade_item(desc: str) -> tuple[str, str]:
    """Diz se a descrição do item sustenta comparação de PREÇO entre certames.

    `_norm_item` casa descrições idênticas token a token — o casamento é exato, não por
    substring. O problema não é o casamento: é a POBREZA da descrição. "Seringa",
    "INSULINA", "Ração animal" casam com outros itens de mesmo nome que podem ser produtos
    inteiramente distintos (seringa descartável × seringa de bomba de infusão; insulina NPH ×
    análoga de ação prolongada). A razão contra a mediana então mede heterogeneidade de
    produto, não sobrepreço.

    Medido em 30/08/2026 sobre os 488 flags `sobrepreco_vs_mediana` do índice: **62,9%
    nasciam de descrições com ≤2 tokens.**

    NÃO cortamos esses flags. O controle positivo mostrou que 41 deles têm razão ≥10× —
    entre eles "Agulha Hipodérmica" a 74× — e um corte seco os perderia. Declaramos a
    fragilidade e deixamos o exame humano decidir, que é a doutrina da casa: INDISPONÍVEL e
    FRÁGIL se declaram, não se apagam.

    Devolve ("FORTE"|"FRACA", motivo por extenso)."""
    toks = _norm_item(desc).split()
    if len(toks) < TOKENS_ITEM_COMPARAVEL:
        return ("FRACA", f"descrição com {len(toks)} token(s) úteis: itens de nome igual e "
                         f"especificação distinta caem na mesma mediana — a razão pode medir "
                         f"produto diferente, não preço fora de curva")
    return ("FORTE", f"descrição com {len(toks)} tokens úteis")


def _mediana(xs: list) -> float:
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def sobrepreco(db_path: str | None = None, min_amostra: int = 5, min_certames: int = 4,
               fator: float = 2.0, limite: int = 120, esfera: str | None = None,
               min_orgaos: int = 3, verificacao: dict | None = None) -> dict:
    """Sobrepreço por MEDIANA do MESMO item, na MESMA unidade e apresentação.

    Refeito em 2026-11-13 (dono: "não pode comparar itens de unidades métricas diferentes [...]
    não pode ter margem pra erro em nada"). Medido no dado real antes da correção: o topo da aba
    era 'Água Destilada / Ampola 10 ML' a R$ 140,00 contra mediana R$ 0,21 ("666×" — preço de
    caixa lançado como ampola, TCE-RJ), copo de água a R$ 26,00 (caixa de copos registrada como
    copo) e 'Desinfetante / Litro' num grupo que ia de R$ 1,32 a R$ 296,55 (saneante hospitalar
    e de limpeza sob o mesmo nome). Nenhum era sobrepreço.

    Agora (base única em comparador_precos.comparacao_homogenea + preco_normalizado):
      · preço NORMALIZADO pela unidade comprovada (campo do PNCP ou texto explícito por regra);
        unidade ambígua → INDETERMINADO, fora da mediana e da lista;
      · grupo = mesma descrição + mesma unidade canônica + mesma apresentação + mesmas medidas;
        salto ≥4× separa faixas; dispersão p90/p10 > 4 → grupo heterogêneo, sem achado;
      · inexigibilidade, agricultura familiar e marca exigida ficam fora (preço não é de mercado);
      · achado = preço normalizado ≥ `fator`× a mediana E z robusto ≥ 3,5, com o GRUPO DE
        COMPARAÇÃO, o link do PNCP e o estado da conferência (VERIFICADO/PENDENTE/DIVERGENTE)."""
    from compliance_agent import comparador_precos as CP
    from compliance_agent import verificacao_pncp as V
    con = _ro(db_path)
    try:
        from compliance_agent.collectors.pncp_resultados import certames_da_esfera
        certs = certames_da_esfera(con, esfera)   # mediana GLOBAL; achado restrito à esfera da aba
        g = CP.comparacao_homogenea(con, min_amostra=min_amostra, min_certames=min_certames,
                                    min_orgaos=min_orgaos)
        n_linhas = con.execute(
            "SELECT COUNT(*) FROM pncp_resultado WHERE ordem_classificacao=1 AND valor_unitario>0 "
            "AND quantidade>=2").fetchone()[0]
    finally:
        con.close()
    verif = verificacao if verificacao is not None else V.estados(db_path)
    info = V.info_certames(db_path) if verificacao is None else {}
    achados = []
    for grp in g["grupos"]:
        resumo = None
        for r, z in CP.achados_do_grupo(grp, fator=fator):
            if certs is not None and r["certame"] not in certs:
                continue                       # compra de outra esfera não entra na aba
            resumo = resumo or CP.resumo_grupo(grp)
            nz = r["_norm"]
            ev = V.estado_de(verif, r["certame"], r.get("item"), r["fornecedor_cnpj"])
            srp = (info.get(r["certame"]) or {}).get("srp")
            med = grp["mediana"]
            achados.append({
                "item": r["d"], "unidade_medida": r["un"], "grupo": grp["desc"],
                "unidade_normalizada": nz["rotulo"], "fator_unidade": nz["fator"],
                "trecho_unidade": nz["trecho"],
                "preco": r["vu"], "preco_normalizado": round(r["pn"], 4),
                "mediana": round(med, 4), "razao": round(r["pn"] / med, 1),
                "z_robusto": round(z, 1), "amostra": grp["n"], "certames": grp["n_certames"],
                "quantidade": r.get("quantidade"),
                "quantidade_normalizada": r.get("qn"),
                "orgao": r.get("unidade_nome") or r.get("orgao_nome"), "municipio": r.get("municipio"),
                "fornecedor": r["fornecedor_nome"], "fornecedor_cnpj": r["fornecedor_cnpj"],
                "certame": r["certame"], "item_n": r.get("item"), "data": (r.get("data_pub") or "")[:10],
                "link_pncp": V.link_pncp(r["certame"]),
                "api_pncp": V.url_api_item(r["certame"], r["item"]) if r.get("item") else None,
                "verificacao": ev["estado"], "verificacao_detalhe": ev["divergencias"],
                "verificado_em": ev["verificado_em"],
                "ata_registro_precos": srp,
                "sobrepreco_est": round(r["pn"] - med, 4),
                "excesso_total_est": (round((r["pn"] - med) * r["qn"], 2) if r.get("qn") else None),
                "grupo_comparacao": resumo})
    achados.sort(key=lambda a: -a["razao"])
    ind = CP.resumo_indeterminados(g["indeterminados"], certs)
    return {"ok": True, "achados": achados[:limite], "n": len(achados),
            "n_verificados": sum(1 for a in achados if a["verificacao"] == V.VERIFICADO),
            "n_divergentes": sum(1 for a in achados if a["verificacao"] == V.DIVERGENTE),
            "grupos_comparaveis": len(g["grupos"]), "itens_com_preco": n_linhas,
            "indeterminados": ind, "sem_par": g["sem_par"],
            "explicacao": ("Mesmo item, MESMA unidade e MESMA apresentação, comprado por vários "
                           "órgãos: sinaliza quem pagou preço unitário normalizado ≥ 2× a mediana do "
                           "grupo (e fora da banda robusta mediana±3,5·MAD). Grupo só existe se for "
                           "homogêneo (sem salto ≥4× e com p90/p10 ≤ 4). Fonte: preço unitário "
                           "homologado do PNCP."),
            "ressalva": ("Item com unidade ambígua, embalagem sem quantidade declarada ou grupo "
                         "heterogêneo fica INDETERMINADO e fora da conta — não foi absolvido, ficou "
                         "sem comparação segura. VERIFICADO = descrição, unidade, quantidade e preço "
                         "conferidos no PNCP; não dispensa o termo de referência. Indício ≠ acusação.")}



def escalada_preco(db_path: str | None = None, min_compras: int = 3, fator: float = 3.0,
                   min_span_dias: int = 45, limite: int = 120, esfera: str | None = None) -> dict:
    """ESCALADA de preço unitário do MESMO fornecedor para o MESMO item ao longo do tempo — a
    empresa vende o item Y ao poder público por preços cada vez MAIORES (aprende que o comprador
    paga qualquer coisa; preço dirigido, captura). Distinto do `sobrepreco` (que é transversal,
    entre órgãos): aqui é LONGITUDINAL, o fornecedor contra a própria série.

    Sinal: ≥`min_compras` vitórias do mesmo (fornecedor, item, unidade) em datas distintas cobrindo
    ≥`min_span_dias` dias (da 1ª à última), com preço final > inicial e razão máx/mín ≥ `fator`
    (default 3× em ≥45 dias — nenhum reajuste/inflação legítimo triplica preço nessa janela).
    Corrobora com a mediana de MERCADO do item (outros fornecedores): se o preço final também está
    muito acima do mercado, o indício é mais forte.

    Guardas anti-FP: quantidade≥2 (evita total-do-lote no campo unitário); descrição normalizada +
    unidade NORMALIZADA na chave (`preco_normalizado`: mesma unidade e apresentação comprovadas —
    galão de 5 L ≠ galão de 20 L; 'Caixa 10 UN' vira preço por unidade); unidade ambígua é
    INDETERMINADO, fica fora da série e é contada em `indeterminados`; razão alta (3×) e tendência
    de alta exigidas juntas — ainda assim a descrição do PNCP é curta e pode misturar especificações
    (por isso mostra a série)."""
    from datetime import date as _date

    def _span(d0: str, d1: str) -> int:
        try:
            return (_date.fromisoformat(d1) - _date.fromisoformat(d0)).days
        except ValueError:
            return 0

    con = _ro(db_path)
    try:
        rows = con.execute(
            "SELECT fornecedor_cnpj, fornecedor_nome, item_descricao d, unidade_medida un, "
            "valor_unitario vu, data_pub, orgao_nome, unidade_nome, certame "
            "FROM pncp_resultado WHERE ordem_classificacao=1 AND valor_unitario>0 AND quantidade>=2 "
            "AND item_descricao IS NOT NULL AND length(item_descricao)>=4 AND data_pub IS NOT NULL "
            "AND length(fornecedor_cnpj)=14").fetchall()
        from collections import defaultdict
        from compliance_agent.collectors.pncp_resultados import certames_da_esfera
        from compliance_agent.preco_normalizado import GAP, normalizar
        certs = certames_da_esfera(con, esfera)
        grupos: dict[tuple, list] = defaultdict(list)
        mercado: dict[tuple, list] = defaultdict(list)   # (item,unid. normalizada) -> preços de TODOS
        indet: list[tuple[dict, str]] = []
        for r in rows:
            base = _norm_item(r["d"])
            if not base:
                continue
            da_esfera = certs is None or r["certame"] in certs   # série = compras DA esfera da aba
            nz = normalizar(r["d"], r["un"])
            if not nz["ok"]:
                if da_esfera:
                    indet.append((dict(r), nz["motivo"]))
                continue                                  # unidade ambígua: fora da série e do mercado
            pn = r["vu"] / nz["fator"]
            if da_esfera:
                grupos[(r["fornecedor_cnpj"], base, nz["chave"])].append((r, pn, nz["rotulo"]))
            mercado[(base, nz["chave"])].append(pn)       # mercado corrobora com TODAS as esferas
        achados = []
        for (cnpj, base, un), itens_pn in grupos.items():
            itens = [r for r, _p, _rot in itens_pn]
            serie = sorted({(r["data_pub"][:10], pn, r["unidade_nome"] or r["orgao_nome"],
                             r["certame"]) for r, pn, _rot in itens_pn})
            if len(serie) < min_compras:
                continue
            datas = [s[0] for s in serie]
            precos = [s[1] for s in serie]
            span = _span(datas[0], datas[-1])   # janela real da 1ª à última compra
            if span < min_span_dias:
                continue
            med_mkt = _mediana(mercado[(base, un)]) if len(mercado[(base, un)]) >= 5 else None
            # a ESCALADA é a tendência (final/inicial), não o spread máx/mín — este é sensível a um
            # único preço-artefato baixo na série (R$0,19 num item de R$100). Guarda anti-artefato:
            # o preço INICIAL precisa ser ≥10% da mediana de mercado (senão é erro de unidade/lote).
            if precos[0] <= 0 or precos[-1] <= precos[0]:
                continue
            if med_mkt and precos[0] < 0.10 * med_mkt:
                continue
            if precos[-1] / precos[0] < fator:
                continue                              # o preço TRIPLICOU (tendência), não só variou
            saltos = [b / a for a, b in zip(precos, precos[1:]) if a > 0 and (b / a >= GAP or a / b >= GAP)]
            if saltos:                                # doutrina do preco_normalizado: salto = outro produto/unidade
                motivo = (f"série com salto ≥{GAP:g}× entre compras consecutivas (maior {max(saltos):.1f}×) — "
                          f"provável unidade, apresentação ou produto diferente, não escalada")
                indet.extend((dict(r), motivo) for r in itens)
                continue
            acima_mkt = round(precos[-1] / med_mkt, 1) if med_mkt and med_mkt > 0 else None
            achados.append({
                "fornecedor": itens[0]["fornecedor_nome"], "fornecedor_cnpj": cnpj,
                "item": itens[0]["d"], "grupo": base, "unidade_medida": itens[0]["un"],
                "unidade_normalizada": itens_pn[0][2],
                "n_compras": len(serie), "span_dias": span,
                "preco_inicial": round(precos[0], 2), "preco_final": round(precos[-1], 2),
                "razao": round(precos[-1] / precos[0], 1),
                "mediana_mercado": round(med_mkt, 2) if med_mkt else None,
                "final_vs_mercado": acima_mkt,
                "serie": [{"data": d, "preco": round(p, 2), "orgao": o} for d, p, o, _ in serie[:8]]})
        # ranking: escalada que também está acima do mercado primeiro, depois pela razão
        achados.sort(key=lambda a: (-(a["final_vs_mercado"] or 0), -a["razao"]))
        from compliance_agent.comparador_precos import resumo_indeterminados
        return {"ok": True, "achados": achados[:limite], "n": len(achados),
                "indeterminados": resumo_indeterminados(indet, None, n_lista=0),
                "explicacao": ("Mesmo fornecedor vendendo o MESMO item por preços unitários cada vez "
                               "maiores ao poder público (≥3 compras, ≥3 meses, alta ≥3×). Indica "
                               "preço dirigido/captura — o fornecedor aprende que o comprador aceita "
                               "aumentos. 'Acima do mercado' cruza com a mediana de outros fornecedores."),
                "ressalva": ("A descrição do PNCP é curta e pode misturar marca/especificação/embalagem "
                             "entre compras — a série é mostrada para conferência. Preço por unidade "
                             "NORMALIZADA (mesma unidade e apresentação); unidade ambígua fica "
                             "INDETERMINADA e fora da série. Reajuste contratual "
                             "legítimo não chega a 3×. Confirmar o termo de referência. Indício ≠ acusação.")}
    finally:
        con.close()


# favorecido que é ENTE PÚBLICO/banco (repasse ou tributo, não fornecedor comercial) —
# fonte ÚNICA. Havia DUAS cópias divergentes disto no arquivo: esta e uma local dentro de
# `fracionamento`, cada uma excluindo o que a outra não excluía (só aqui: ASSEMBLEIA, BANCO,
# CAIXA ECON, EQUALIZ; só lá: C_MARA). O resultado media: 6 dos 63 grupos de "fracionamento"
# eram MINISTÉRIO DA FAZENDA e INSS — recolhimento de tributo e previdência apresentado como
# compra fatiada, num relatório de fiscalização. Uma cópia só, com os dois conjuntos unidos.
#
# Os padrões federais foram conferidos contra o universo de credores antes de entrar, para
# não derrubar fornecedor privado: `%UNIAO%` ficou DE FORA porque pegaria a "União Química
# Farmacêutica"; `%INSTITUTO%` sozinho ficou de fora porque derrubaria OSS reais — por isso
# o INSS é excluído pelo nome inteiro, não pela palavra "Instituto".
# Só OB CONTABILIZADA é pagamento. Anulado/Excluído/Não contabilizado somavam R$ 13.998.871.152,03 no SIAFE em
# 24/09/2026 e entravam em TODOS os detectores deste módulo (fracionamento, dependente, corrida de dezembro,
# pago após a baixa…) — a mesma inflação já corrigida na ficha do Acervo (commit 50a8093b).
_OB_PAGA = "status='Contabilizado'"


def _ob_paga(con, alias: str = "") -> str:
    """OB que é pagamento: Contabilizada e NÃO devolvida pelo banco ('Erro no Pagamento' segue 'Contabilizado' no
    SIAFE). 18/11/2026: 21.044 OB / R$ 5,57 bi; em amostra de 400, 72% tinham reemissão do mesmo credor/UG/valor —
    somar as duas contava o pagamento duas vezes. Base sem a coluna `status_envio` (fixture antiga) → regra antiga.
    `alias`: prefixo da tabela na consulta (ex.: "o" → `o.status`, `o.status_envio`)."""
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(ob_orcamentaria_siafe)")}
    except sqlite3.Error:
        cols = set()
    tem = "status_envio" in cols
    r = (f"{_OB_PAGA} AND COALESCE(status_envio,'')<>'Erro no Pagamento'" if tem else _OB_PAGA)
    r = r.replace("status", f"{alias}.status") if alias else r   # cobre status e status_envio
    # OB SEM NÚMERO não é pagamento: 18/11/2026, 58 linhas (R$ 11,47 mi) de UMA coleta (09/08/2026 08:05–11:36),
    # 57 com a irmã numerada de mesmo PD/valor — a soma contava a mesma OB duas vezes (SEI-080002/019260/2026 virou
    # "2 OB = o dobro da NL" num laudo de execução); a 58ª tem colunas deslocadas e valor 0.
    a = alias + "." if alias else ""
    # PAGAMENTO COMPLEMENTAR não vai ao banco (19/11/2026: 6.905 OB, R$ 294,32 mi, todas 'Enviado Manualmente'): a
    # OB principal paga o código de barras inteiro e lista as complementares no espelho — somá-las conta em dobro
    # (FES × Juturnaíba: 2026OB08840 R$ 218.665,32 = NL líquida 181.489,48 + complementar 37.175,84, lançada 2×).
    if "tipo_regularizacao" in cols:
        r += f" AND COALESCE({a}tipo_regularizacao,'')<>'Pagamento Complementar'"
    # 'Enviado ao Banco' REEMITIDA e paga (mesmo credor/UG/valor/processo, ≤10 dias): a 1ª não é pagamento (19/11/2026:
    # 123 OB, R$ 19,65 mi). A lista vem de `compliance_agent.ob_reemitida` (tabela pequena); sem ela, regra antiga.
    try:
        if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ob_reemitida'").fetchone():
            r += (f" AND NOT EXISTS (SELECT 1 FROM ob_reemitida _re WHERE _re.ob={a}numero_ob"
                  f" AND _re.ug={a}ug_emitente)")
    except sqlite3.Error:
        logging.getLogger(__name__).debug("exceção tolerada em cruzamentos_intel", exc_info=True)
    return r + (f" AND COALESCE({a}numero_ob,'')<>''" if "numero_ob" in cols else "")

# 23/11/2026: o filtro era uma lista de LIKE que divergia da peneira canônica — deixava passar "Funco Municipal De
# Saude De Itaguai" (grafia da fonte), Associação de Apoio à Escola (43 dos 70 da corrida de dezembro), e 222 credores
# de natureza jurídica 1xxx (R$ 1,41 bi: Ipalerj, Defesa Civil, Funasa, UENF, consórcios públicos). Agora é a peneira
# canônica + a natureza da Receita, numa função SQL registrada por `registrar_peneira` (ver `_ro`). Do conjunto
# antigo fica só o que a canônica não cobre e o dado real exige (banco como credor: repasse/consignado; equalização;
# controladoria; instituto de previdência; câmara).
_RX_BANCO_OU_PUBLICO_LEGADO = re.compile(
    r"\bbanco\b|caixa\s+econ|equaliz|controladoria|instituto\s+de\s+prev|\bc[âa]mara\b|assembleia|\btribunal\b", re.I)
_SQL_NAO_PUBLICO = "jfn_eh_publico(nome_credor, credor) = 0"


_NEP_CONECT = {"DA", "DE", "DO", "DAS", "DOS", "E"}
_NEP_SUFIXO = {"NETO", "FILHO", "JUNIOR", "JR", "SOBRINHO", "SEGUNDO", "NETA", "FILHA"}
_NEP_COMUNS = {
    "SILVA", "SANTOS", "OLIVEIRA", "SOUZA", "SOUSA", "LIMA", "PEREIRA", "FERREIRA", "COSTA",
    "RODRIGUES", "ALVES", "GOMES", "RIBEIRO", "MARTINS", "CARVALHO", "ALMEIDA", "LOPES", "SOARES",
    "FERNANDES", "VIEIRA", "BARBOSA", "ROCHA", "DIAS", "MONTEIRO", "CARDOSO", "REIS", "ARAUJO",
    "CASTRO", "ANDRADE", "NASCIMENTO", "MOREIRA", "NUNES", "MARQUES", "MACHADO", "MELO", "FREITAS",
    "CAMPOS", "CUNHA", "PINTO", "MOURA", "DUARTE", "TEIXEIRA", "MENDES", "RAMOS", "GONCALVES",
    "BATISTA", "SANTANA", "SANT ANNA", "CORREA", "CORREIA", "AZEVEDO", "BORGES", "MEDEIROS", "JESUS",
    "ASSIS", "FRANCO", "PINHEIRO", "FONSECA", "GUEDES", "VIDAL", "BRAGA", "ESPIRITO SANTO", "MORAES",
    "CARDOSO", "TAVARES", "MIRANDA", "CAMARGO", "FIGUEIREDO", "SIQUEIRA", "AMARAL"}
_NEP_AUTORIDADE = __import__("re").compile(
    r"DEFENSOR|DESEMBARGADOR|\bJUIZ|SECRETARI[OA]|DIRETOR|PRESIDENTE|PROCURADOR|SUBSECRETARI|"
    r"SUPERINTENDENTE|COORDENADOR GERAL|CHEFE DE GABINETE|VEREADOR")
_NEP_CONF = __import__("re").compile(
    r"COMISS|ESPECIAL|ASSESSOR|GABINETE|\bCHEFE\b|DIRETOR|SUPERINT|COORDENAD|SECRETARI|OFICIAL")


def _nep_tokens(nome: str) -> list:
    import unicodedata
    s = unicodedata.normalize("NFKD", (nome or "").upper())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return [t for t in re.sub(r"[^A-Z ]", " ", s).split() if t not in _NEP_CONECT]


def _nep_familia(toks: list) -> str | None:
    """Sobrenome de família = últimos 2 tokens significativos, ignorando sufixos (Neto/Filho/Jr)."""
    sig = [t for t in toks if len(t) >= 3 and t not in _NEP_SUFIXO]
    return " ".join(sig[-2:]) if len(sig) >= 2 else None


def _corroborar_familia(con, membros: list) -> list[str]:
    """Outro dado (além do sobrenome) que ligue pessoas DISTINTAS da folha: serem sócias da MESMA empresa,
    com a identidade de cada uma conferida pelo CPF na janela da folha (`identidade_pessoa`), nunca pelo nome.
    Eixo 'co-ocorrência societária' (4,76% da base, pode acender — osint/parentesco.EIXOS). `membros`:
    [{nome, cpf, fonte, competencia}]. Devolve frases de prova (sem CPF)."""
    from compliance_agent import identidade_pessoa as _ip
    emp = [(m["nome"], _ip.empresas_da_pessoa_folha(con, m["nome"], m.get("cpf"), m.get("fonte"),
                                                    m.get("competencia"))) for m in membros]
    provas = []
    for i in range(len(emp)):
        for j in range(i + 1, len(emp)):
            comum = sorted(emp[i][1] & emp[j][1])
            if comum:
                provas.append(f"{emp[i][0]} e {emp[j][0]} são sócios da mesma empresa (CNPJ raiz "
                              f"{', '.join(comum[:3])}) — identidade de cada um conferida pelo CPF da folha")
    return provas


def nepotismo(db_path: str | None = None, min_membros: int = 2, max_raridade: int = 20,
              limite: int = 120) -> dict:
    """Nepotismo (Súmula Vinculante 13 STF): ≥2 pessoas de NOMES distintos com o MESMO sobrenome de
    família RARO, ambas em cargo de confiança no MESMO órgão. Sobrenome comum é excluído; sufixos
    (Neto/Filho/Jr) são normalizados; o fragmento de CPF corrobora que são pessoas distintas. Marca
    quando o cluster inclui uma AUTORIDADE nomeante (defensor/diretor/secretário).

    19/11/2026 (dono: "homônimos em tudo têm que ser desmistificados através de outros dados"): sobrenome
    NÃO é parentesco. O grupo só vira ACHADO (selo INDICIO) quando outro dado liga as pessoas — hoje, serem
    sócias da mesma empresa com identidade conferida pelo CPF (`_corroborar_familia`). Sem isso é HIPÓTESE
    (`hipoteses`), com a prevalência do eixo medida na própria folha e a explicação inocente."""
    from compliance_agent import identidade_pessoa as _ip
    con = _ro(db_path)
    try:
        from collections import defaultdict
        total_fam: dict[str, set] = defaultdict(set)
        org_fam: dict = defaultdict(lambda: defaultdict(dict))
        for r in con.execute("SELECT nome, orgao_nome, cargo, cpf, fonte, competencia FROM registros_folha "
                             "WHERE nome IS NOT NULL"):
            toks = _nep_tokens(r["nome"])
            fam = _nep_familia(toks)
            if not fam:
                continue
            nn = " ".join(toks)
            total_fam[fam].add(nn)
            if _NEP_CONF.search((r["cargo"] or "").upper()):
                frag = re.sub(r"\D", "", r["cpf"] or "")
                org_fam[r["orgao_nome"]][fam][nn] = {
                    "nome": r["nome"], "cargo": r["cargo"],
                    "cpf_frag": frag if 5 <= len(frag) <= 9 else "",
                    "cpf": r["cpf"], "fonte": r["fonte"], "competencia": r["competencia"],
                    "autoridade": bool(_NEP_AUTORIDADE.search((r["cargo"] or "").upper()))}
        # prevalência do eixo NA PRÓPRIA FOLHA: das pessoas em cargo de confiança com sobrenome não-comum,
        # quantas dividem o sobrenome com outra pessoa de confiança do mesmo órgão
        n_conf = n_eixo = 0
        for fams in org_fam.values():
            for fam, membros in fams.items():
                if fam in _NEP_COMUNS or any(t in _NEP_COMUNS for t in fam.split()):
                    continue
                n_conf += len(membros)
                if len(membros) >= 2:
                    n_eixo += len(membros)
        _milhar = lambda n: f"{n:,}".replace(",", ".")  # noqa: E731
        prev_txt = (f"na folha, {_milhar(n_eixo)} de {_milhar(n_conf)} pessoas em cargo de confiança com sobrenome "
                    f"não-comum ({f'{100 * n_eixo / max(1, n_conf):.1f}'.replace('.', ',')}%"
                    + ") dividem o sobrenome com outra do mesmo órgão (medido agora); eixo raro, mas sobrenome "
                    "sozinho não prova parentesco")
        achados, hipoteses = [], []
        for org, fams in org_fam.items():
            for fam, membros in fams.items():
                if fam in _NEP_COMUNS or any(t in _NEP_COMUNS for t in fam.split()):
                    continue
                if len(membros) < min_membros:
                    continue
                ntot = len(total_fam[fam])
                if ntot > max_raridade:
                    continue
                # sobrenome menos raro (>4 no total) só passa se o órgão concentra ≥50% deles
                if ntot > 4 and (len(membros) / ntot) < 0.5:
                    continue
                mm = list(membros.values())
                selo = _ip.selo_parentesco(_corroborar_familia(con, mm), prevalencia=prev_txt)
                item = {
                    "sobrenome": fam, "orgao": org, "n_membros": len(membros),
                    "total_folha": ntot, "concentracao": round(len(membros) / ntot, 2) if ntot else 0,
                    "tem_autoridade": any(m["autoridade"] for m in mm),
                    "selo": selo["selo"], "grau": selo["grau"], "motivo": selo["motivo"],
                    "prevalencia": selo["prevalencia"], "falta": selo["falta"],
                    "membros": [{"nome": m["nome"], "cargo": m["cargo"], "cpf_frag": m["cpf_frag"]} for m in mm[:8]]}
                (achados if selo["selo"] == _ip.INDICIO else hipoteses).append(item)
        # autoridade no cluster + mais membros + maior concentração primeiro
        chave = lambda a: (not a["tem_autoridade"], -a["n_membros"], -a["concentracao"])  # noqa: E731
        achados.sort(key=chave)
        hipoteses.sort(key=chave)
        return {"ok": True, "achados": achados[:limite], "n": len(achados),
                "n_com_autoridade": sum(1 for a in achados if a["tem_autoridade"]),
                "hipoteses": hipoteses[:limite], "n_hipoteses": len(hipoteses),
                "n_hipoteses_com_autoridade": sum(1 for a in hipoteses if a["tem_autoridade"]),
                "prevalencia_eixo": prev_txt,
                "folhas": sorted({r[0] for r in con.execute("SELECT DISTINCT fonte FROM registros_folha") if r[0]}),
                "identidade": ("Sobrenome não é parentesco e não há base aberta de parentesco no Brasil. Achado "
                               "(INDÍCIO) só quando outro dado liga as pessoas — sócias da mesma empresa, "
                               "identidade conferida pelo CPF da folha. O resto é HIPÓTESE: não é achado."),
                "explicacao": ("Duas ou mais pessoas de nomes distintos com o mesmo sobrenome de "
                               "família RARO, ambas em cargo de confiança no mesmo órgão — perfil de "
                               "nepotismo (Súmula Vinculante 13 do STF proíbe nomear parente para "
                               "cargo em comissão). Mais forte quando o cluster inclui a autoridade "
                               "nomeante (defensor, diretor, secretário)."),
                "ressalva": ("Sobrenome igual não prova parentesco — pode ser coincidência; confirmar "
                             "o vínculo familiar e a cadeia de nomeação. Cobertura limitada às folhas "
                             "coletadas. Indício ≠ acusação.")}
    finally:
        con.close()


def fornecedor_dependente(db_path: str | None = None, min_total: float = 2_000_000,
                          min_share: float = 0.90, limite: int = 120) -> dict:
    """Fornecedor comercial cuja receita do Estado vem ≥90% de UMA ÚNICA unidade gestora — perfil de
    'empresa do órgão' (criada/mantida para atender um comprador só). Exclui repasses a entes públicos."""
    con = _ro(db_path)
    try:
        rows = con.execute(f"""
        WITH tot AS (SELECT credor, SUM(valor) t FROM ob_orcamentaria_siafe
                     WHERE {_ob_paga(con)} AND length(credor)=14 AND valor>0 AND {_SQL_NAO_PUBLICO}
                     GROUP BY credor HAVING t >= ?),
        porug AS (SELECT credor, ug_emitente, SUM(valor) v, MAX(nome_credor) nome
                  FROM ob_orcamentaria_siafe WHERE {_ob_paga(con)} AND length(credor)=14 AND valor>0
                  GROUP BY credor, ug_emitente),
        -- n_ugs agregado UMA vez: a subconsulta correlacionada varria as 1,2 mi de OBs por linha do
        -- resultado (sem índice em credor) — 166 s a frio em 24/09/2026
        nug AS (SELECT credor, COUNT(*) n_ugs FROM porug GROUP BY credor)
        SELECT p.credor, p.nome, p.ug_emitente, p.v, t.t, n.n_ugs
        FROM porug p JOIN tot t ON t.credor=p.credor JOIN nug n ON n.credor=p.credor
        WHERE p.v >= ? * t.t ORDER BY t.t DESC LIMIT ?""",
                           (min_total, min_share, limite)).fetchall()
        import json as _json
        try:
            ugn = _json.loads((_REPO / "data" / "ug_index_siafe.json").read_text())["ugs"]
        except Exception:
            ugn = {}
        achados = [{
            "cnpj": r["credor"], "nome": r["nome"],
            "cnpj_fmt": (f"{r['credor'][:2]}.{r['credor'][2:5]}.{r['credor'][5:8]}/{r['credor'][8:12]}-{r['credor'][12:]}"),
            "total": r["t"], "valor_ug": r["v"], "share": round(r["v"] / r["t"], 2) if r["t"] else 0,
            "ug": r["ug_emitente"], "ug_nome": ugn.get(r["ug_emitente"], ""), "n_ugs": r["n_ugs"]}
            for r in rows]
        for a in achados:
            a.update(regime_do_credor(con, a["cnpj"]))
        return {"ok": True, "achados": achados, "n": len(achados),
                "explicacao": ("Empresa que recebe quase tudo (≥90%) de uma única unidade gestora do "
                               "Estado. Dependência total de um comprador é o perfil de fornecedor "
                               "cativo/'empresa do órgão' — mercado fechado, risco de direcionamento."),
                "ressalva": ("Monopólio pode ser legítimo (nicho, concessão exclusiva) — cruzar com o "
                             "histórico de licitações do órgão e o QSA. OS e OSC ficam na lista com o REGIME "
                             "marcado (contrato de gestão, Lei 9.637/1998; parceria, Lei 13.019/2014): seguem "
                             "regras próprias, não a licitação da 14.133. Indício ≠ acusação.")}
    finally:
        con.close()


# Decisão do dono (24/11/2026): OS/OSC é fornecedor NORMAL que segue REGRAS DIFERENTES — não sai da lista; o item
# carrega o regime e a régua que vale para ele. Fonte: ~/vault/notas/doutrina/MAPA-DE-REGIMES.md (linhas 2 e 3).
REGIME_OS = ("contrato de gestão com Organização Social — Lei 9.637/1998",
             "A seleção da OS não segue a licitação da Lei 14.133 (dispensa do art. 75, XV/8.666 art. 24, XXIV, após "
             "qualificação e publicidade — Lei 9.637 arts. 5º–7º). Receber quase tudo de uma UG é do DESENHO do contrato "
             "de gestão, não indício de empresa cativa. O que se mede: metas e indicadores pactuados, prestação de "
             "contas e relatório da comissão de avaliação (arts. 8º–9º), subcontratação do objeto e vínculo dirigente × "
             "órgão.")
REGIME_MROSC = ("parceria com OSC (termo de colaboração/fomento) — Lei 13.019/2014",
                "A escolha da OSC é por chamamento público (arts. 24 e 29–31), não por licitação da 14.133 (art. 84 afasta "
                "a lei de licitações). Dependência de uma UG é da parceria. O que se mede: chamamento ou sua dispensa "
                "motivada, plano de trabalho e metas (art. 22), liberação conforme cronograma (art. 48) e prestação de "
                "contas (arts. 63–72).")
REGIME_SFL = ("entidade sem fins lucrativos (natureza jurídica 3xxx) — regime a confirmar no instrumento",
              "Pode ser contrato de gestão (Lei 9.637), parceria MROSC (Lei 13.019) ou contratação comum (Lei 14.133, ex.: "
              "fundação de apoio, art. 75, XV). Ler o instrumento antes de aplicar a régua de fornecedor cativo.")


def regime_do_credor(con, cnpj: str) -> dict:
    """Regime do credor para o leitor do item: {regime, regime_regra} (vazio = fornecedor comercial, régua comum).

    Natureza 3xxx da Receita = entidade sem fins lucrativos. O instrumento sai do ELEMENTO/MODALIDADE dos empenhos dele
    (ne_siafe, 2024+): modalidade 50 (transferência a instituição privada sem fins lucrativos) → parceria MROSC;
    elemento 34 (despesa de pessoal por terceirização — como o RJ empenha o contrato de gestão, LRF art. 18 §1º) →
    contrato de gestão; sem empenho conhecido → 'a confirmar' (INDISPONÍVEL não vira regime)."""
    try:
        r = con.execute("SELECT natureza_cod FROM empresas_cadastro WHERE cnpj_basico=?", ((cnpj or "")[:8],)).fetchone()
    except sqlite3.Error:
        return {}
    if not r or not str(r[0] or "").startswith("3"):
        return {}
    try:
        nats = con.execute("SELECT natureza, SUM(valor) FROM ne_siafe WHERE credor=? GROUP BY natureza "
                           "ORDER BY 2 DESC", (cnpj,)).fetchall()
    except sqlite3.Error:
        nats = []
    regime = REGIME_SFL
    if nats:
        top = str(nats[0][0] or "")
        if top[2:4] == "50":
            regime = REGIME_MROSC
        elif top[4:6] == "34":
            regime = REGIME_OS
    return {"regime": regime[0], "regime_regra": regime[1], "natureza_juridica": str(r[0])}


def capital_incompativel(db_path: str | None = None, min_total: float = 1_000_000,
                         max_capital: float = 50_000.0, fator: float = 100.0,
                         limite: int = 120) -> dict:
    """CAPITAL IRRISÓRIO frente ao volume recebido: empresa com capital social ínfimo (< `max_capital`)
    que recebeu do Estado ≥ `fator`× o próprio capital (e > `min_total`). Subcapitalização crônica é
    sinal de FACHADA/interposição — a empresa não tem lastro econômico-financeiro para o que faturou
    (Lei 14.133 art. 5, art. 62-63: qualificação econômico-financeira; capital de R$10 recebendo
    dezenas de milhões não sustenta a execução). Fonte do capital: dump da Receita (empresas_cadastro).

    Guarda anti-FP: o dump traz o capital de UM mês — pode ter havido aumento de capital depois;
    a razão altíssima (≥100×) e o valor absoluto (>R$1mi) reduzem o ruído, mas confirmar o capital
    ATUAL e a capacidade econômica antes de citar."""
    con = _ro(db_path)
    try:
        cap = {}
        try:
            for r in con.execute("SELECT cnpj_basico, capital_social, razao_social FROM empresas_cadastro "
                                 "WHERE capital_social IS NOT NULL AND capital_social>=0"):
                cap[r["cnpj_basico"]] = (r["capital_social"], r["razao_social"])
        except sqlite3.OperationalError:
            return {"ok": False, "erro": "empresas_cadastro ausente — rodar tools/empresas_dump_sweep"}
        achados = []
        for r in con.execute("SELECT favorecido_cpf c, favorecido_nome nm, total_pago t, n_obs "
                            f"FROM favorecido_resumo WHERE {SQL_FAVORECIDO_PJ} AND total_pago>=?",
                            (min_total,)):
            info = cap.get(r["c"][:8])
            if not info:
                continue
            capital, razao = info
            # capital 0 = 'não declarado' (ambíguo), fora; só capital POSITIVO e ínfimo entra
            if not (0 < capital < max_capital) or r["t"] < fator * capital:
                continue
            achados.append({
                "cnpj": r["c"], "nome": r["nm"] or razao,
                "cnpj_fmt": f"{r['c'][:2]}.{r['c'][2:5]}.{r['c'][5:8]}/{r['c'][8:12]}-{r['c'][12:]}",
                "capital": round(capital, 2), "total_recebido": r["t"], "n_obs": r["n_obs"],
                "razao": round(r["t"] / capital)})
        achados.sort(key=lambda a: -a["razao"])
        return {"ok": True, "achados": achados[:limite], "n": len(achados),
                "explicacao": ("Empresa com capital social irrisório (< R$50 mil) que recebeu do Estado "
                               "≥100× o próprio capital. Subcapitalização frente ao volume faturado é "
                               "indício de fachada/interposição — falta lastro econômico-financeiro para "
                               "executar contratos vultosos (Lei 14.133 art. 5º e 62-63)."),
                "ressalva": ("O capital vem do dump da Receita de UM mês — pode ter havido aumento de "
                             "capital posterior. Serviços intensivos em mão de obra têm capital baixo por "
                             "natureza. Confirmar o capital ATUAL e a capacidade econômica. Indício ≠ acusação.")}
    finally:
        con.close()


def corrida_dezembro(db_path: str | None = None, min_total: float = 2_000_000,
                     min_share: float = 0.75, limite: int = 120) -> dict:
    """Fornecedor comercial com ≥75% do valor recebido no ano concentrado em DEZEMBRO — corrida do
    empenho de fim de ano (planejamento deficiente ou direcionamento na virada do exercício)."""
    con = _ro(db_path)
    try:
        rows = con.execute(f"""
        WITH t AS (SELECT credor, MAX(nome_credor) nome, SUM(valor) tot,
                     SUM(CASE WHEN substr(data_emissao,4,2)='12' THEN valor ELSE 0 END) dez,
                     COUNT(*) n_obs
                   FROM ob_orcamentaria_siafe WHERE {_ob_paga(con)} AND length(credor)=14 AND valor>0 AND {_SQL_NAO_PUBLICO}
                   GROUP BY credor HAVING tot >= ?)
        SELECT credor, nome, tot, dez, n_obs FROM t WHERE dez >= ? * tot
        ORDER BY tot DESC LIMIT ?""", (min_total, min_share, limite)).fetchall()
        achados = [{
            "cnpj": r["credor"], "nome": r["nome"],
            "cnpj_fmt": (f"{r['credor'][:2]}.{r['credor'][2:5]}.{r['credor'][5:8]}/{r['credor'][8:12]}-{r['credor'][12:]}"),
            "total": r["tot"], "dezembro": r["dez"], "share": round(r["dez"] / r["tot"], 2) if r["tot"] else 0,
            "n_obs": r["n_obs"]} for r in rows]
        return {"ok": True, "achados": achados, "n": len(achados),
                "explicacao": ("Fornecedor que recebeu a maior parte do ano em DEZEMBRO. Concentração "
                               "no fim do exercício é red-flag de 'corrida do empenho' — verba usada às "
                               "pressas antes de perder o orçamento, terreno fértil para dispensa e "
                               "direcionamento."),
                "ressalva": ("Alguns objetos são sazonais (fim de ano) legitimamente — confirmar o "
                             "processo. Indício ≠ acusação.")}
    finally:
        con.close()


def socio_oculto(db_path: str | None = None, min_empresas: int = 3, limite: int = 120) -> dict:
    """Pessoa/holding que é sócia de VÁRIAS (≥3) empresas fornecedoras do Estado — empresário oculto
    ou grupo familiar controlando um leque de fornecedores (indício de fracionamento entre 'concorrentes'
    do mesmo dono). Exclui conselheiros de estatal (não são donos).

    Identidade (19/11/2026, régua `identidade_pessoa.chave_qsa`): a PESSOA é (nome, documento da Receita),
    não o nome. A versão anterior agrupava pelo nome do sócio e fundia homônimos de CPF diferente numa
    pessoa só (7 grupos; 5 só passavam do corte de 3 empresas por causa da fusão). Sem documento no QSA = só
    o nome → INDETERMINADO, fora de `achados`."""
    from collections import defaultdict
    from compliance_agent import identidade_pessoa as _ip
    con = _ro(db_path)
    try:
        rows = con.execute("""
        SELECT s.socio_nome, s.socio_doc, s.cnpj, s.cpf_resolvido, f.favorecido_nome, f.total_pago
        FROM socios_fornecedor s JOIN favorecido_resumo f ON f.favorecido_cpf=s.cnpj
        WHERE s.socio_nome<>'' AND f.total_pago>0
          AND (lower(s.qualificacao) LIKE '%administrador%' OR s.qualificacao LIKE '%Sócio%' OR lower(s.qualificacao) LIKE '%titular%')
          AND s.qualificacao NOT LIKE '%Conselh%'""").fetchall()
    finally:
        con.close()
    pessoas: dict = defaultdict(dict)          # (nome_norm, doc) -> {cnpj: (empresa, total)}
    docs_por_nome: dict = defaultdict(set)
    nome_exib, resolvidos = {}, defaultdict(set)
    for r in rows:
        k = _ip.chave_qsa(r["socio_nome"], r["socio_doc"])
        pessoas[k][r["cnpj"]] = (r["favorecido_nome"], r["total_pago"] or 0)
        docs_por_nome[k[0]].add(k[1])
        nome_exib.setdefault(k, r["socio_nome"])
        if len(_ip._dig(r["cpf_resolvido"])) == 11:
            resolvidos[k].add(_ip._dig(r["cpf_resolvido"]))
    achados, indeterminados = [], []
    for k, emps in pessoas.items():
        if len(emps) < min_empresas:
            continue
        tot = sum(v for _, v in emps.values())
        if tot >= 2e9:
            continue
        nn, doc = k
        n_hom = len(docs_por_nome[nn] - {""})
        item = {"socio": nome_exib[k], "n_empresas": len(emps), "total": tot,
                "empresas": [e for e, _ in sorted(emps.values(), key=lambda x: -x[1])][:8],
                "holding": doc.startswith("pj:"),
                "doc": (f"***.{doc[3:6]}.{doc[6:9]}-**" if doc.startswith("pf:")
                        else doc[3:] if doc else "")}
        if not doc:
            item.update(selo=_ip.INDETERMINADO, falta="o QSA não traz o documento deste sócio",
                        motivo="Só o nome coincide entre as empresas; sem documento não há como separar homônimos.")
            indeterminados.append(item)
            continue
        if len(resolvidos[k]) > 1:
            item.update(selo=_ip.PROVAVEL, falta="CPF completo único",
                        motivo="Mesmo nome e mesmos 6 dígitos do CPF na Receita, mas outras fontes resolveram "
                               f"{len(resolvidos[k])} CPFs completos diferentes — pode haver homônimo.")
        else:
            prova = ("mesma raiz de CNPJ do sócio PJ em todas" if item["holding"]
                     else "mesmo nome e mesmos 6 dígitos do CPF (Receita) em todas")
            if n_hom > 1:
                prova += f"; há {n_hom - 1} outro(s) sócio(s) de mesmo nome e CPF diferente, contados à parte"
            item.update(selo=_ip.VERIFICADO, falta="", motivo=f"Mesma pessoa nas {len(emps)} empresas: {prova}.")
        achados.append(item)
    achados.sort(key=lambda a: (-a["n_empresas"], -a["total"]))
    indeterminados.sort(key=lambda a: (-a["n_empresas"], -a["total"]))
    fundidos = sum(1 for nn, ds in docs_por_nome.items() if len(ds - {""}) > 1
                   and any(len(pessoas[(nn, d)]) for d in ds))
    return {"ok": True, "achados": achados[:limite], "n": len(achados),
            "n_verificados": sum(1 for a in achados if a["selo"] == _ip.VERIFICADO),
            "n_indeterminados": len(indeterminados), "indeterminados": indeterminados[:limite],
            "nomes_com_homonimos": fundidos,
            "identidade": ("Pessoa = nome + documento da Receita (CPF mascarado ou CNPJ). Mesmo nome com CPF "
                           "diferente é outra pessoa; sem documento é INDETERMINADO e não entra na lista."),
            "explicacao": ("Mesma pessoa (ou holding) sócia de várias empresas que vendem ao Estado. "
                           "Um dono por trás de vários fornecedores permite simular concorrência "
                           "entre empresas do mesmo grupo (fracionamento, propostas de cobertura) e "
                           "concentrar contratos disfarçadamente."),
            "ressalva": ("Ser sócio de várias empresas é lícito; o indício é a combinação com "
                         "contratos no mesmo órgão/objeto. Cruzar QSA e certames. Indício ≠ acusação.")}


def grafo_familias(db_path: str | None = None, max_raridade: int = 12, so_com_empresa: bool = True) -> dict:
    """Grafo D3 (nodes/links p/ o graph.html) das FAMÍLIAS que tocam o dinheiro público. Uma família =
    sobrenome de família RARO com ≥2 pessoas distintas, ligando as que estão em cargo de confiança
    (folha) E as que são sócias de fornecedores. Conecta pessoa→órgão (lotação) e pessoa→empresa
    (sócio, com o valor recebido). Mostra clãs que ocupam cargos E fornecem ao Estado.
    `so_com_empresa`: só mostra famílias em que ao menos um membro tem empresa fornecedora (o cruzamento).

    19/11/2026 — identidade e parentesco pela régua (`identidade_pessoa`). Antes: o comissionado da folha e
    o sócio do QSA de MESMO NOME viravam um nó só (casamento só pelo nome), sócios homônimos de CPF diferente
    também, e toda família saía com selo 'alta' ("indício alto" no grafo) só pelo sobrenome. Agora:
      · folha × QSA só se fundem com CPF compatível na janela aferida da folha; mesmo nome sem CPF
        comparável fica em nós separados, marcados INDETERMINADO; CPF diferente = homônimo, separados;
      · pessoa do QSA = nome + documento (`chave_qsa`);
      · a aresta família→pessoa é 'mesmo sobrenome (hipótese)'; só vira 'parentesco (indício)' com outro
        dado: comissionado com identidade conferida que é sócio da MESMA empresa que outro membro."""
    from compliance_agent import identidade_pessoa as _ip
    con = _ro(db_path)
    try:
        from collections import defaultdict

        def _fam_ok(fam):
            return fam and fam not in _NEP_COMUNS and not any(t in _NEP_COMUNS for t in fam.split())

        fam_folha: dict = defaultdict(dict)   # fam -> nn -> {nome, orgao, cpf, fonte, competencia}
        for r in con.execute("SELECT nome, orgao_nome, cargo, cpf, fonte, competencia FROM registros_folha "
                             "WHERE nome IS NOT NULL AND (cargo LIKE '%COMISS%' OR cargo LIKE '%ESPECIAL%' "
                             "OR cargo LIKE '%ASSESSOR%' OR cargo LIKE '%GABINETE%' OR cargo LIKE '%DIRETOR%')"):
            toks = _nep_tokens(r["nome"])
            fam = _nep_familia(toks)
            if not _fam_ok(fam):
                continue
            fam_folha[fam][" ".join(toks)] = {"nome": r["nome"], "orgao": r["orgao_nome"], "cpf": r["cpf"],
                                             "fonte": r["fonte"], "competencia": r["competencia"]}
        fam_qsa: dict = defaultdict(dict)     # fam -> (nn, doc) -> {nome, doc, empresas}
        for r in con.execute("SELECT s.socio_nome, s.socio_doc, s.cnpj, f.favorecido_nome, f.total_pago "
                             "FROM socios_fornecedor s JOIN favorecido_resumo f ON f.favorecido_cpf=s.cnpj "
                             "WHERE f.total_pago>0 AND s.socio_nome<>''"):
            toks = _nep_tokens(r["socio_nome"])
            fam = _nep_familia(toks)
            if not _fam_ok(fam):
                continue
            k = (" ".join(toks), _ip.chave_qsa(r["socio_nome"], r["socio_doc"])[1])
            e = fam_qsa[fam].setdefault(k, {"nome": r["socio_nome"], "doc": r["socio_doc"], "empresas": []})
            if len(e["empresas"]) < 5 and all(c != r["cnpj"] for _, _, c in e["empresas"]):
                e["empresas"].append((r["favorecido_nome"], r["total_pago"], r["cnpj"]))
        # raridade global (pessoas distintas com esse sobrenome em TODA a folha)
        tot_fam: dict[str, set] = defaultdict(set)
        for r in con.execute("SELECT nome FROM registros_folha WHERE nome IS NOT NULL"):
            f = _nep_familia(_nep_tokens(r["nome"]))
            if f:
                tot_fam[f].add(" ".join(_nep_tokens(r["nome"])))

        nodes: dict[str, dict] = {}
        links: list[dict] = []
        cont = {"fundidos_por_cpf": 0, "homonimos_separados": 0, "indeterminados": 0}

        def _node(nid, label, tipo, **kw):
            if nid not in nodes:
                nodes[nid] = {"id": nid, "label": (label or "")[:40], "tipo": tipo, **kw}
            return nid

        for fam in set(fam_folha) | set(fam_qsa):
            if len(tot_fam.get(fam, set())) > max_raridade:   # sobrenome pouco raro → fora
                continue
            # pessoas: cada registro da folha casa com o sócio de mesmo nome SÓ pelo CPF
            pessoas, usados, ambiguos = [], set(), 0
            for nn, f in fam_folha.get(fam, {}).items():
                pf = _ip.posicoes_folha(f["cpf"], f["fonte"], f["competencia"])
                p = {"nome": f["nome"], "orgao": f["orgao"], "empresas": [], "identidade": "", "motivo": ""}
                for k, q in fam_qsa.get(fam, {}).items():
                    if k[0] != nn:
                        continue
                    res, npos = _ip.comparar_cpf(_ip.posicoes_qsa(q["doc"]), pf)
                    if res == _ip.COMPATIVEL and not p["empresas"]:
                        p.update(empresas=q["empresas"], identidade=_ip.VERIFICADO,
                                 motivo=f"comissionado e sócio: CPF confere em {npos} posições")
                        usados.add(k)
                        cont["fundidos_por_cpf"] += 1
                    elif res == _ip.INCOMPATIVEL:
                        cont["homonimos_separados"] += 1
                    elif res == _ip.SEM_DADO and not p["identidade"]:
                        p.update(identidade=_ip.INDETERMINADO,
                                 motivo="há sócio de mesmo nome, mas sem CPF comparável — nós separados")
                        cont["indeterminados"] += 1
                        ambiguos += 1
                pessoas.append(p)
            for k, q in fam_qsa.get(fam, {}).items():
                if k not in usados:
                    pessoas.append({"nome": q["nome"], "orgao": None, "empresas": q["empresas"],
                                    "identidade": "", "motivo": "", "_k": k})
            # nós separados por falta de CPF (INDETERMINADO) podem ser UMA pessoa: não contam como 2 para formar família
            if len(pessoas) - ambiguos < 2:
                continue
            tem_emp = any(p["empresas"] for p in pessoas)
            tem_org = any(p["orgao"] for p in pessoas)
            if so_com_empresa and not (tem_emp and tem_org):   # o cruzamento exige os dois lados
                continue
            # outro dado além do sobrenome: comissionado (identidade conferida) sócio da mesma empresa que outro membro
            corr = []
            for a in pessoas:
                if not (a["orgao"] and a["identidade"] == _ip.VERIFICADO):
                    continue
                ca = {c for _, _, c in a["empresas"]}
                for b in pessoas:
                    if b is not a and ca & {c for _, _, c in b["empresas"]}:
                        corr.append(f"{a['nome']} (comissionado, CPF conferido) é sócio da mesma empresa que {b['nome']}")
            selo = _ip.selo_parentesco(corr)
            fid = _node(f"fam:{fam}", fam, "familia", badge="alta" if corr else "hipotese",
                        selo=selo["selo"], motivo=selo["motivo"], prevalencia=selo["prevalencia"])
            for i, p in enumerate(pessoas):
                pid = _node(f"pes:{fam}:{i}", p["nome"], "pessoa", identidade=p["identidade"] or None,
                            motivo=p["motivo"] or None)
                links.append({"source": fid, "target": pid,
                              "tipo": "parentesco (indício)" if corr else "mesmo sobrenome (hipótese)"})
                if p["orgao"]:
                    oid = _node(f"org:{p['orgao']}", p["orgao"], "orgao")
                    links.append({"source": pid, "target": oid, "tipo": "lotacao"})
                for (emp, tot, cnpj) in p["empresas"]:
                    eid = _node(f"emp:{cnpj}", emp, "empresa", valor=float(tot or 0), cnpj=cnpj)
                    links.append({"source": pid, "target": eid, "tipo": "socio", "valor": float(tot or 0)})
        fams = [n for n in nodes.values() if n["tipo"] == "familia"]
        return {"nodes": list(nodes.values()), "links": links,
                "n_familias": len(fams),
                "n_familias_indicio": sum(1 for n in fams if n["selo"] == _ip.INDICIO),
                "n_familias_hipotese": sum(1 for n in fams if n["selo"] == _ip.HIPOTESE),
                "n_pessoas": sum(1 for n in nodes.values() if n["tipo"] == "pessoa"),
                "n_empresas": sum(1 for n in nodes.values() if n["tipo"] == "empresa"),
                "identidade": cont,
                "legenda": ("Família = sobrenome raro com ≥2 pessoas. Azul=pessoa, verde=empresa "
                            "fornecedora, roxo=órgão. Comissionado e sócio só são o mesmo nó quando o CPF "
                            "confere; o sobrenome sozinho é HIPÓTESE ('mesmo sobrenome'), não parentesco — "
                            "vira indício só com outro dado (sociedade comum com CPF conferido). "
                            "Indício ≠ acusação.")}
    finally:
        con.close()


_SITUACOES_SEM_ATIVIDADE = frozenset({"BAIXADA", "INAPTA", "SUSPENSA", "NULA"})
_MOTIVOS_SUCESSAO = frozenset({"02", "03", "04"})   # incorporação, fusão, cisão total (tabela de motivos da Receita)
_NATUREZA_CARTORIO = "3034"                          # Serviço Notarial e Registral (Cartório)
_RX_CARTORIO = re.compile(r"\bCART[OÓ]RIO\b|\bSERVENTIA\b|OF[IÍ]CIO DE (NOTAS|REGISTRO)", re.I)
# Pagamento por decisão judicial / restituição: Encargos Gerais do Estado (UG 370200) com processo da PGE (SEI-1400…).
# Medido em 13/11/2026: Ford, GE Vernova, Brami, Dimpus — OB única pela EGE em processo SEI-140001/140017.
_UG_ENCARGOS_GERAIS = "370200"
_SQL_JUDICIAL = f"(ug_emitente='{_UG_ENCARGOS_GERAIS}' AND processo LIKE 'SEI-1400%')"


def _fora_da_manchete(con, cnpj: str) -> str | None:
    """Credor que não é "empresa morta" ainda que o CNPJ esteja baixado/inapto (verificação de 13/11/2026):
    ente público (natureza 1xxx), cartório (3034 — extinto na reorganização das serventias) e filial baixada de
    matriz ATIVA (a pessoa jurídica segue viva). Sem a tabela/coluna no dump → None (não se presume exclusão)."""
    b = cnpj[:8]
    try:
        nat = con.execute("SELECT natureza_cod, razao_social FROM estab.empresas WHERE cnpj_basico=?", (b,)).fetchone()
    except sqlite3.OperationalError:
        nat = None
    cod = str((nat["natureza_cod"] if nat else "") or "").strip()
    if cod.startswith("1"):
        return "natureza_publica"
    if cod == _NATUREZA_CARTORIO or (nat and _RX_CARTORIO.search(str(nat["razao_social"] or ""))):
        return "cartorio"
    try:
        r = con.execute("SELECT matriz_filial FROM estab.estabelecimentos WHERE cnpj=?", (cnpj,)).fetchone()
        if r and str(r["matriz_filial"] or "").strip() == "2":
            m = con.execute("SELECT situacao_cadastral FROM estab.estabelecimentos WHERE cnpj_basico=? "
                            "AND matriz_filial='1'", (b,)).fetchone()
            if m and str(m["situacao_cadastral"] or "").strip().upper() == "ATIVA":
                return "filial_de_matriz_ativa"
    except sqlite3.OperationalError as exc:      # dump sem matriz_filial: não se presume filial (exclusão não aplicada)
        logger.debug("fenix: matriz/filial de %s indisponível (%s)", cnpj, exc)
    return None


def _pagou_apos_baixa(con, cnpj: str, ultima_ob: str | None, iso: str) -> dict:
    """A baixa é ANTERIOR ao último pagamento? Só então "pago a empresa morta" se sustenta.

    Devolve sempre as três chaves, com `None`/`False` quando não dá para saber — a ausência
    do dado NÃO vira "regular" nem "irregular" (INDISPONÍVEL ≠ 0). O valor pago depois só é
    somado para quem de fato qualifica, para não fazer 373 varreduras à toa.
    Ente público, cartório, filial de matriz ativa e pagamento judicial pago depois da baixa saem da
    soma com o motivo em `fora_da_manchete` e o valor em `valor_fora_da_manchete` — contados à parte.
    """
    vazio = {"data_baixa": None, "motivo_baixa": None, "pagou_apos_baixa": None,
             "valor_apos_baixa": 0.0, "n_ob_apos_baixa": 0,
             "fora_da_manchete": None, "valor_fora_da_manchete": 0.0,
             "n_ob_devolvida_apos_baixa": 0, "valor_devolvido_apos_baixa": 0.0}
    try:
        r = con.execute("SELECT situacao_cadastral, data_situacao, motivo_situacao FROM estab.estabelecimentos "
                        "WHERE cnpj=?", (cnpj,)).fetchone()
    except sqlite3.OperationalError:
        return vazio
    if not r or not str(r["data_situacao"] or "").strip():
        return vazio
    # Revisão de 13/11/2026: em 91 de 146 casos o dump dizia ATIVA e `data_situacao` era a data em que a
    # empresa FICOU ATIVA — e isso virava "pago depois da baixa". Só há "baixa" se a situação do dump for de
    # empresa sem atividade; e sucessão (incorporação 02, fusão 03, cisão total 04) não é empresa morta: a
    # sucessora recebe legitimamente.
    if str(r["situacao_cadastral"] or "").strip().upper() not in _SITUACOES_SEM_ATIVIDADE:
        return vazio
    if str(r["motivo_situacao"] or "").strip() in _MOTIVOS_SUCESSAO:
        return vazio
    d = str(r["data_situacao"])[:10]
    if len(d) == 8 and d.isdigit():                      # AAAAMMDD do dump → ISO
        d = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    out = {**vazio, "data_baixa": d, "motivo_baixa": str(r["motivo_situacao"] or "") or None}
    if not ultima_ob or ultima_ob <= d:
        return {**out, "pagou_apos_baixa": False}        # morreu DEPOIS do último pagamento
    # OB devolvida pelo banco ('Erro no Pagamento': devolução integral, ver `siafe_gd`) segue 'Contabilizado' e
    # não é pagamento — 17/11/2026: R$ 7,60 mi dos R$ 15,59 mi do 1º colocado (IDESI) eram isso. Contada à parte.
    cols_ob = {c[1] for c in con.execute("PRAGMA table_info(ob_orcamentaria_siafe)")}
    tem_envio = "status_envio" in cols_ob
    devolvida = "COALESCE(status_envio,'')='Erro no Pagamento'" if tem_envio else "0"
    # FP medido em 19/11/2026 (~/vault/aprendizados/fp-medida-fenix-radar-ninho-2026-11-19.md): OB de R$ 0,01 sem NL
    # nem processo virava "pago a empresa morta". Pagamento exige número de OB e valor ≥ R$ 1,00. NL/processo NÃO é
    # exigido: as OB de 2021–2023 do espelho vêm sem eles (DOSIMETRIKA e R.R LIMP, verdadeiros, sumiriam).
    lastro = " AND valor >= 1.00"
    lastro += " AND COALESCE(numero_ob,'')<>''" if "numero_ob" in cols_ob else ""
    q = con.execute(f"SELECT COALESCE(SUM(CASE WHEN NOT {devolvida} THEN 1 END),0) n, "
                    f"COALESCE(SUM(CASE WHEN NOT {devolvida} THEN valor END),0) v, "
                    f"COALESCE(SUM(CASE WHEN {_SQL_JUDICIAL} AND NOT {devolvida} THEN 1 END),0) nj, "
                    f"COALESCE(SUM(CASE WHEN {_SQL_JUDICIAL} AND NOT {devolvida} THEN valor END),0) vj, "
                    f"COALESCE(SUM(CASE WHEN {devolvida} THEN 1 END),0) nd, "
                    f"COALESCE(SUM(CASE WHEN {devolvida} THEN valor END),0) vd FROM ob_orcamentaria_siafe "
                    f"WHERE {_OB_PAGA} AND credor=? AND {iso} > ?{lastro}", (cnpj, d)).fetchone()
    n, v, nj, vj = q["n"], q["v"] or 0.0, q["nj"], q["vj"] or 0.0
    out.update(n_ob_devolvida_apos_baixa=q["nd"], valor_devolvido_apos_baixa=round(q["vd"] or 0.0, 2))
    fora = _fora_da_manchete(con, cnpj) if n else None
    if fora:
        return {**out, "pagou_apos_baixa": False, "fora_da_manchete": fora, "valor_fora_da_manchete": round(v, 2)}
    if n and n == nj:
        return {**out, "pagou_apos_baixa": False, "fora_da_manchete": "pagamento_judicial",
                "valor_fora_da_manchete": round(vj, 2)}
    return {**out, "pagou_apos_baixa": bool(n - nj), "valor_apos_baixa": round(v - vj, 2),
            "n_ob_apos_baixa": n - nj, "valor_fora_da_manchete": round(vj, 2)}


def empresa_fenix(db_path: str | None = None, limite: int | None = 120) -> dict:
    """Empresa FÊNIX: (a) BAIXADA/INAPTA na Receita que ainda recebeu do Estado (paga a empresa
    morta); ou (b) aberta ≤12 meses antes do 1º pagamento (nasceu já para faturar). Exclui
    consórcio/SPE (legitimamente criados para um projeto). Cadastro Receita ainda parcial."""
    con = _ro(db_path)
    try:
        # valor recebido = favorecido_resumo.total_pago = OB PAGA do SIAFE (24/11/2026, decisão do dono: OB é o
        # principal, o TFE pode ter erro). Até aqui somava "todas as fontes" — o espelho TFE preenchia quem o SIAFE
        # não tinha. Agora o credor que SÓ o espelho traz, nos exercícios que o SIAFE cobre, sai como DIVERGÊNCIA
        # (`divergencias_tfe`), fora dos totais: ou o SIAFE da casa tem lacuna de coleta, ou o espelho errou.
        pago = {r["favorecido_cpf"]: (r["total_pago"] or 0.0, r["n_obs"] or 0) for r in con.execute(
            "SELECT favorecido_cpf, total_pago, n_obs FROM favorecido_resumo WHERE total_pago>0")}
        cols_res = {r[1] for r in con.execute("PRAGMA table_info(favorecido_resumo)")}
        so_tfe = ({r["favorecido_cpf"]: (r["total_tfe"], r["n_obs_tfe"]) for r in con.execute(
            "SELECT favorecido_cpf, total_tfe, n_obs_tfe FROM favorecido_resumo "
            "WHERE fonte_valor='so_tfe' AND total_tfe>0")} if "fonte_valor" in cols_res else {})
        divergencias = []
        iso = "substr(data_emissao,7,4)||'-'||substr(data_emissao,4,2)||'-'||substr(data_emissao,1,2)"
        janela = {r["credor"]: (r["p"], r["u"]) for r in con.execute(
            f"SELECT credor, MIN({iso}) p, MAX({iso}) u FROM ob_orcamentaria_siafe "
            f"WHERE {_ob_paga(con)} AND length(credor)=14 AND valor>0 GROUP BY credor")}
        prim = {k: v[0] for k, v in janela.items()}
        # ── A DATA DA BAIXA, que faltava ────────────────────────────────────────────────
        # "Pago a empresa MORTA" só é verdade se o pagamento veio DEPOIS da baixa, e este
        # detector nunca perguntou isso: comparava a situação ATUAL da Receita contra o
        # total pago de todos os tempos. O projeto já tem a doutrina em outro lugar — o
        # radar usa "sanção vigente À ÉPOCA" —, ela é que não chegava aqui.
        #
        # Medido em 25/07/2026 sobre as 373 apontadas (R$ 3,99 bi):
        #     54 pagaram DEPOIS da baixa  ->  R$   18.266.205,85   (o indício se sustenta)
        #    319 só pagaram ANTES         ->  R$ 2.558.961.415,54  (não é empresa morta)
        # (Correção de 13/11/2026: a "baixa em 2005" da Cruz Vermelha era a data em que ela ficou
        # ATIVA no dump — o próprio número de julho tinha esse defeito; ver `_pagou_apos_baixa`.)
        #
        # A cura é ACRESCENTAR a prova, não apagar o sinal: quem recebeu muito e hoje está
        # baixada continua valendo conhecimento, só não é "pagamento a empresa morta".
        # `data_situacao` vive no dump da Receita (DB separado), e o lookup é por chave
        # primária — 0 ms por CNPJ (é o que `_pagou_apos_baixa` faz, um CNPJ por vez).
        # NUNCA varrer por situacao_cadastral: sem índice, 25 s.
        try:
            con.execute("ATTACH DATABASE ? AS estab",
                        (f"file:{_REPO / 'data' / 'receita_estab.db'}?mode=ro",))
            _tem_estab = True
        except sqlite3.OperationalError as exc:
            logger.debug("empresa_fenix: receita_estab indisponível (%s) — data da baixa fica INDISPONÍVEL", exc)
            _tem_estab = False
        rx_spe = re.compile(r"CONSORCIO|CONSÓRCIO|\bSPE\b| S/?A\b|SOCIEDADE DE PROPOSITO|CONCESSION", re.I)
        _DEFUNTA = ("BAIXADA", "INAPTA", "SUSPENSA", "NULA", "INAPTA/BAIXADA")
        achados = []
        for e in con.execute("SELECT cnpj, razao_social, data_abertura, situacao FROM empresas "
                             "WHERE situacao IS NOT NULL AND situacao<>''"):
            val = pago.get(e["cnpj"])
            if not val or val[0] <= 0:
                div = so_tfe.get(e["cnpj"])
                if div and any(d in (e["situacao"] or "").upper() for d in _DEFUNTA):
                    divergencias.append({"cnpj": e["cnpj"], "nome": e["razao_social"], "situacao": e["situacao"],
                                         "total_tfe": div[0], "n_obs_tfe": div[1]})
                continue                                # só quem RECEBEU (OB paga do SIAFE) entra
            tot, n_obs = val
            sit = (e["situacao"] or "").upper()         # normaliza caixa: 'Baixada'→'BAIXADA'
            defunta = any(d in sit for d in _DEFUNTA)
            ab = (e["data_abertura"] or "")[:10]
            meses = None
            p = prim.get(e["cnpj"])
            if ab and p:
                try:
                    meses = (int(p[:4]) - int(ab[:4])) * 12 + (int(p[5:7]) - int(ab[5:7]))
                except (ValueError, IndexError):
                    meses = None
            recem = (meses is not None and 0 <= meses <= 12
                     and not rx_spe.search(e["razao_social"] or ""))
            if not (defunta or recem):
                continue
            item = {
                "cnpj": e["cnpj"], "nome": e["razao_social"], "data_abertura": ab, "primeira_ob": p,
                "meses_ate_ob": meses, "situacao": e["situacao"], "total_recebido": tot,
                "n_obs": n_obs, "tipo": "defunta" if defunta else "recem_aberta"}
            if defunta and _tem_estab:
                item.update(_pagou_apos_baixa(con, e["cnpj"], janela.get(e["cnpj"], (None, None))[1], iso))
            achados.append(item)
        achados.sort(key=lambda a: (a["tipo"] != "defunta", -(a["total_recebido"] or 0)))
        fora: dict[str, dict] = {}
        for a in achados:
            if a.get("fora_da_manchete"):
                f = fora.setdefault(a["fora_da_manchete"], {"n": 0, "valor": 0.0})
                f["n"] += 1
                f["valor"] = round(f["valor"] + (a.get("valor_fora_da_manchete") or 0.0), 2)
        return {"ok": True, "achados": achados[:limite], "n": len(achados),
                "n_defunta": sum(1 for a in achados if a["tipo"] == "defunta"),
                "total_defunta": round(sum(a["total_recebido"] for a in achados
                                           if a["tipo"] == "defunta"), 2),
                # ── o número que PODE ser dito em público ────────────────────────────────
                # `n_defunta`/`total_defunta` são o conjunto AMPLO: "hoje está baixada e um
                # dia recebeu". Isso não é "pago a empresa morta". O par CONFIRMADO só
                # conta quem recebeu DEPOIS da baixa, fora de `fora_da_manchete`, e só ele vira manchete.
                "n_defunta_confirmada": sum(1 for a in achados if a.get("pagou_apos_baixa")),
                "total_apos_baixa": round(sum(a.get("valor_apos_baixa") or 0 for a in achados), 2),
                "n_sem_data_baixa": sum(1 for a in achados
                                        if a["tipo"] == "defunta" and a.get("pagou_apos_baixa") is None),
                "n_pagou_so_antes": sum(1 for a in achados if a.get("pagou_apos_baixa") is False
                                        and not a.get("fora_da_manchete")),
                # fora da manchete, contados à parte (verificação de 13/11/2026): ente público, cartório, filial de
                # matriz ativa e pagamento judicial pago depois da baixa não são "empresa morta"
                "fora_da_manchete": fora,
                "n_fora_da_manchete": sum(f["n"] for f in fora.values()),
                "total_fora_da_manchete": round(sum(f["valor"] for f in fora.values()), 2),
                # credor defunto que SÓ o espelho TFE traz nos exercícios que o SIAFE cobre — não somado
                "fonte_valor": "OB paga do SIAFE (favorecido_resumo.total_pago, régua _ob_paga); TFE só confronto",
                "divergencias_tfe": sorted(divergencias, key=lambda d: -(d["total_tfe"] or 0))[:limite],
                "n_divergencias_tfe": len(divergencias),
                "total_divergencias_tfe": round(sum(d["total_tfe"] or 0 for d in divergencias), 2),
                "divergencias_tfe_nota": ("Empresa baixada/inapta que o espelho TFE dá como paga e o SIAFE da casa "
                                          "não tem no mesmo exercício: lacuna de coleta do SIAFE ou erro do "
                                          "espelho. DIVERGÊNCIA a conferir, fora de todo total."),
                "explicacao": ("Empresa BAIXADA/INAPTA/SUSPENSA na Receita que mesmo assim recebeu do "
                               "Estado (OB paga) depois da baixa ou da inaptidão — é o que o número do card soma. "
                               "Empresa aberta ≤12 meses antes do 1º pagamento aparece só na lista, como sinal "
                               "para priorizar leitura: empresa nova não é irregular."),
                "ressalva": ("Indício a conferir no processo de pagamento, não acusação: inapta não é o mesmo que "
                             "extinta, e situação cadastral irregular não prova inexecução. A situação pode ter mudado "
                             "APÓS o pagamento: vale a data do ato (só OB posterior à baixa conta). Fora da conta, ditos à parte: sucessão "
                             "(incorporação, fusão, cisão), ente público, cartório, filial baixada de matriz ativa e "
                             "pagamento judicial (Encargos Gerais com processo da PGE). SPE e consórcio (novos por "
                             "natureza) foram excluídos.")}
    finally:
        con.close()


def porta_giratoria(db_path: str | None = None, limite: int = 120) -> dict:
    """Porta giratória (revolving door): EX-servidor (folha com vínculo inativo/exonerado/encerramento)
    que virou SÓCIO de empresa fornecedora do Estado. Reusa o casamento nome+fragmento de CPF do
    servidor-sócio; exclui entidade de classe. Quebra de quarentena quando o contrato é logo após a saída."""
    con = _ro(db_path)
    try:
        from collections import defaultdict
        from compliance_agent import identidade_pessoa as _ip
        ex = defaultdict(list)  # nome_norm -> [(orgao, cargo, vinculo, cpf_folha, fonte, competencia)]
        vinc_ex = ("INATIVO", "ENCERRAMENTO", "SEM LOTAÇÃO", "Livre Nomeação e Exoneração", "EXONERADO")
        q_ph = ",".join("?" * len(vinc_ex))
        for r in con.execute(f"SELECT nome, orgao_nome, cargo, vinculo, cpf, fonte, competencia FROM registros_folha "
                            f"WHERE vinculo IN ({q_ph})", vinc_ex):
            nn = _norm_nome(r["nome"])
            if nn.count(" ") >= 1:
                ex[nn].append((r["orgao_nome"], r["cargo"], r["vinculo"], r["cpf"], r["fonte"], r["competencia"]))
        # Identidade pela régua única (`identidade_pessoa`): CPF comparado na janela AFERIDA de cada fonte
        # (antes: 3–8 presumido para toda folha). Par só-por-nome NÃO é achado — vai para `indeterminados`.
        achados, conflitos, indeterminados = [], 0, []
        vistos = set()
        for r in con.execute("SELECT s.socio_nome, s.socio_doc, s.cnpj, s.qualificacao, "
                            "f.favorecido_nome, f.total_pago, f.n_obs FROM socios_fornecedor s "
                            "JOIN favorecido_resumo f ON f.favorecido_cpf=s.cnpj "
                            "WHERE f.total_pago>0 AND s.socio_nome<>'' ORDER BY f.total_pago DESC"):
            emp = r["favorecido_nome"] or ""
            if _RX_NAOCOM.search(_norm_nome(emp)):
                continue
            if not _RX_DONO.search(_norm_nome(r["qualificacao"] or "")):
                continue
            nn = _norm_nome(r["socio_nome"])
            cands = ex.get(nn)
            if not cands:
                continue
            q = _ip.posicoes_qsa(r["socio_doc"])
            tier, info, houve = None, None, False
            for (org, cargo, vinc, cpf_f, fonte, comp) in cands:
                res, _n = _ip.comparar_cpf(q, _ip.posicoes_folha(cpf_f, fonte, comp))
                if res == _ip.COMPATIVEL:
                    tier, info = "ALTA", (org, cargo, vinc)
                    break
                if res == _ip.INCOMPATIVEL:
                    houve = True
                elif not tier:
                    tier, info = "MEDIA", (org, cargo, vinc)
            if not tier:
                if houve:
                    conflitos += 1
                continue
            if tier == "MEDIA":
                indeterminados.append({"socio": r["socio_nome"], "empresa": emp, "ex_orgao": info[0],
                                       "motivo": "só o nome coincide — sem CPF comparável na folha"})
                continue
            chave = (nn, r["cnpj"])
            if chave in vistos:
                continue
            vistos.add(chave)
            cnpj = r["cnpj"]
            achados.append({
                "socio": r["socio_nome"], "cnpj": cnpj,
                "cnpj_fmt": (f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}"
                             if len(cnpj or "") == 14 else cnpj),
                "empresa": emp, "qualificacao": r["qualificacao"], "confianca": tier,
                "ex_orgao": info[0], "ex_cargo": info[1], "vinculo": info[2],
                "total_pago": r["total_pago"], "n_obs": r["n_obs"]})
        achados.sort(key=lambda a: (a["confianca"] != "ALTA", -(a["total_pago"] or 0)))
        return {"ok": True, "achados": achados[:limite], "n": len(achados),
                "homonimos_descartados": conflitos, "n_indeterminados": len(indeterminados),
                "indeterminados": indeterminados[:limite],
                "explicacao": ("Ex-servidor público (vínculo inativo/exonerado/sem lotação nas folhas) "
                               "que hoje é sócio de empresa fornecedora do Estado. A 'porta giratória' "
                               "— sair do serviço público e virar fornecedor — pode violar a quarentena "
                               "e indica captura do ex-órgão."),
                "ressalva": ("Casamento por nome + fragmento de CPF; a quarentena depende das datas de "
                             "saída e do contrato (a confirmar). 'Sem lotação' pode não ser saída "
                             "definitiva. Indício ≠ acusação.")}
    finally:
        con.close()


def nepotismo_cruzado(db_path: str | None = None, limite: int = 60) -> dict:
    """Nepotismo CRUZADO: troca de favores entre órgãos — o sobrenome raro X tem AUTORIDADE no órgão A
    e um comissionado no órgão B, enquanto o sobrenome raro Y tem autoridade no órgão B e comissionado
    no A (colocação recíproca de parentes, driblando a SV13 do mesmo órgão). Rigoroso: exige o par
    recíproco A↔B com autoridade dos dois lados.

    19/11/2026 — identidade e parentesco pela régua (`identidade_pessoa`):
      · o "parente colocado" tem de ser OUTRA pessoa que a autoridade. Antes, 6 dos 8 pares eram a própria
        autoridade lotada em duas secretarias (mesmo nome, mesmo CPF) — não há parente nenhum. Mesmo nome
        e CPF compatível = mesma pessoa (descartada); mesmo nome sem CPF comparável = INDETERMINADO;
      · sobrenome não é parentesco: o par só é ACHADO (INDICIO) se outro dado ligar autoridade e colocado
        (sociedade comum com CPF conferido). Sem isso vai para `hipoteses`."""
    from compliance_agent import identidade_pessoa as _ip
    con = _ro(db_path)
    try:
        from collections import defaultdict
        fam_tot: dict[str, set] = defaultdict(set)
        aut: dict = defaultdict(dict)   # fam -> {orgao: registro da autoridade}
        conf: dict = defaultdict(lambda: defaultdict(dict))  # fam -> orgao -> {nome: registro}
        for r in con.execute("SELECT nome, orgao_nome, cargo, cpf, fonte, competencia FROM registros_folha "
                             "WHERE nome IS NOT NULL"):
            toks = _nep_tokens(r["nome"])
            fam = _nep_familia(toks)
            if not fam or fam in _NEP_COMUNS or any(t in _NEP_COMUNS for t in fam.split()):
                continue
            nn = " ".join(toks)
            fam_tot[fam].add(nn)
            cargo = (r["cargo"] or "").upper()
            reg = {"nome": r["nome"], "cpf": r["cpf"], "fonte": r["fonte"], "competencia": r["competencia"]}
            if _NEP_CONF.search(cargo):
                conf[fam][r["orgao_nome"]].setdefault(nn, reg)
            if _NEP_AUTORIDADE.search(cargo):
                aut[fam].setdefault(r["orgao_nome"], reg)

        def _colocados(autoridade: dict, regs: dict) -> tuple[list, list, list]:
            """Separa os 'colocados' em: outra pessoa · a própria autoridade · indeterminado."""
            outros, mesma, indet = [], [], []
            for reg in regs.values():
                v = _ip.mesma_pessoa_folhas(autoridade["nome"], autoridade["cpf"], autoridade["fonte"],
                                            autoridade["competencia"], reg["nome"], reg["cpf"], reg["fonte"],
                                            reg["competencia"])
                (mesma if v["resultado"] == "MESMA" else indet if v["resultado"] == _ip.INDETERMINADO
                 else outros).append((reg, v["motivo"]))
            return outros, mesma, indet

        # só sobrenomes raros
        raros = {f for f, s in fam_tot.items() if len(s) <= 20}
        pares, descartes, vistos_desc = [], {"mesma_pessoa": 0, "indeterminado": 0}, set()
        famX = [f for f in raros if f in aut]
        for X in famX:
            for orgA, autX in aut[X].items():
                for orgB in conf.get(X, {}):
                    if orgB == orgA:
                        continue
                    for Y in raros:
                        if Y == X or Y not in aut:
                            continue
                        if not (orgB in aut[Y] and orgA in conf.get(Y, {})):
                            continue
                        autY = aut[Y][orgB]
                        oX, mX, iX = _colocados(autX, conf[X][orgB])
                        oY, mY, iY = _colocados(autY, conf[Y][orgA])
                        if not oX or not oY:
                            # um dos lados só tem a própria autoridade (ou quem não dá para distinguir dela)
                            kd = tuple(sorted([X, Y]) + sorted([orgA or "", orgB or ""]))
                            if kd not in vistos_desc:
                                vistos_desc.add(kd)
                                descartes["mesma_pessoa" if (mX or mY) and not (iX or iY) else "indeterminado"] += 1
                            continue
                        corr = (_corroborar_familia(con, [autX] + [r for r, _ in oX[:3]])
                                + _corroborar_familia(con, [autY] + [r for r, _ in oY[:3]]))
                        selo = _ip.selo_parentesco(corr)
                        pares.append({
                            "sobrenome_a": X, "orgao_a": orgA, "autoridade_a": autX["nome"],
                            "sobrenome_b": Y, "orgao_b": orgB, "autoridade_b": autY["nome"],
                            "membro_a_em_b": sorted(r["nome"] for r, _ in oX)[:3],
                            "membro_b_em_a": sorted(r["nome"] for r, _ in oY)[:3],
                            "selo": selo["selo"], "grau": selo["grau"], "motivo": selo["motivo"],
                            "prevalencia": selo["prevalencia"], "falta": selo["falta"]})
        # dedup por par de sobrenomes+órgãos
        seen, achados, hipoteses = set(), [], []
        for p in pares:
            k = tuple(sorted([p["sobrenome_a"], p["sobrenome_b"]]) + sorted([p["orgao_a"] or "", p["orgao_b"] or ""]))
            if k in seen:
                continue
            seen.add(k)
            (achados if p["selo"] == _ip.INDICIO else hipoteses).append(p)
        return {"ok": True, "achados": achados[:limite], "n": len(achados),
                "hipoteses": hipoteses[:limite], "n_hipoteses": len(hipoteses),
                "descartados_mesma_pessoa": descartes["mesma_pessoa"],
                "descartados_indeterminados": descartes["indeterminado"],
                "identidade": ("O 'parente colocado' tem de ser outra pessoa que a autoridade (nome diferente, ou "
                               "mesmo nome com CPF diferente). Sobrenome não é parentesco: achado só com outro "
                               "dado que ligue as pessoas; o resto é hipótese."),
                "explicacao": ("Nepotismo cruzado (troca de favores): a família X manda no órgão A e "
                               "coloca um parente no órgão B, enquanto a família Y manda no órgão B e "
                               "coloca um parente no A. A reciprocidade dribla a Súmula Vinculante 13, "
                               "que só proíbe nomear parente no PRÓPRIO órgão."),
                "ressalva": ("Sobrenome igual não prova parentesco nem combinação — é o padrão que "
                             "levanta a suspeita; confirmar vínculos e cadeia de nomeação. Indício ≠ acusação.")}
    finally:
        con.close()


# ── 4. CONLUIO DIRETO vencedor × perdedora × QSA ─────────────────────────────

def _certames_vencedor_perdedora(con) -> dict[str, dict]:
    """Por certame: vencedoras (ordem=1 OU registro só-de-vencedor: ordem NULL com valor>0)
    e perdedoras CONFIRMADAS (ordem>1 em algum item e nenhuma vitória no mesmo certame).
    Exclui ÓRGÃO PÚBLICO que aparece como 'fornecedor' (ruído: Ministério da Fazenda, autarquias
    que recebem repasse) — não é licitante e contaminaria o conluio."""
    try:
        entes = {r[0] for r in con.execute("SELECT cnpj FROM pncp_ente WHERE length(cnpj)=14")}
    except sqlite3.OperationalError:
        entes = set()
    cert: dict[str, dict] = {}
    for r in con.execute(
            "SELECT certame, orgao_nome, objeto, data_pub, fornecedor_cnpj, fornecedor_nome, "
            "valor_homologado, ordem_classificacao FROM pncp_resultado "
            "WHERE length(fornecedor_cnpj)=14"):
        if r["fornecedor_cnpj"] in entes:
            continue                       # órgão público não é licitante
        c = cert.setdefault(r["certame"], {
            "orgao": r["orgao_nome"], "objeto": r["objeto"], "data": (r["data_pub"] or "")[:10],
            "venc": {}, "perd": {}, "nomes": {}})
        c["nomes"][r["fornecedor_cnpj"]] = r["fornecedor_nome"]
        o, v = r["ordem_classificacao"], r["valor_homologado"] or 0.0
        if o == 1 or (o is None and v > 0):
            c["venc"][r["fornecedor_cnpj"]] = c["venc"].get(r["fornecedor_cnpj"], 0.0) + v
        elif o is not None and o > 1:
            c["perd"].setdefault(r["fornecedor_cnpj"], 0)
    for c in cert.values():
        for w in c["venc"]:
            c["perd"].pop(w, None)     # venceu QUALQUER item → não é perdedora do certame
    return cert


def conluio_qsa(db_path: str | None = None, limite: int = 120,
                max_ubiquidade: int = 40, incluir_atas: bool = True,
                limite_atas: int = 8000) -> dict:
    """CONLUIO DIRETO: vencedor e perdedora do MESMO certame com sócio em comum no QSA da
    Receita — a perdedora do mesmo dono existe para dar aparência de disputa (proposta de
    cobertura, OCDE bid rigging; fraude à licitação, Lei 14.133 art. 337-F CP). Tiers:
    MESMA_EMPRESA (matriz×filial concorrendo entre si) > ALTA (nome + fragmento de CPF/CNPJ
    do sócio coincidem) > MEDIA (só o nome). CPF conflitante = homônimo, descarta.
    Sócio-conselheiro e sócio ubíquo (fundo/holding em >max_ubiquidade empresas) não contam.
    Duas fontes de perdedora: PNCP (ordem_classificacao>1, explícita) e ATAS do corpus
    (inabilitada/desclassificada extraída do texto — mesma régua das perdedoras contumazes)."""
    con = _ro(db_path)
    try:
        cert = _certames_vencedor_perdedora(con)
        for m in cert.values():
            m["fonte"] = "pncp"
        if incluir_atas:
            try:
                from compliance_agent.rodizio_grafo import (
                    coletar_atas_do_corpus, extrair_participantes_ata)
                for ata in coletar_atas_do_corpus(db_path or _DB, limite=limite_atas):
                    ext = extrair_participantes_ata(ata["texto"], orgao_cnpj=ata["orgao"])
                    if not ext["avaliavel"]:
                        continue
                    venc = [p["cnpj"] for p in ext["participantes"] if p["venceu"] is True]
                    perd = [p["cnpj"] for p in ext["participantes"] if p["venceu"] is False]
                    if not (venc and perd):
                        continue
                    c = cert.setdefault(ata["certame"], {
                        "orgao": ata["orgao"], "objeto": None, "data": None,
                        "venc": {}, "perd": {}, "nomes": {}, "fonte": "ata"})
                    if c["fonte"] == "pncp":
                        c["fonte"] = "pncp+ata"
                    for v in venc:
                        c["venc"].setdefault(v, 0.0)
                    for p in perd:
                        c["perd"].setdefault(p, 0)
                    for w in c["venc"]:          # venceu (em qualquer fonte) → não é perdedora
                        c["perd"].pop(w, None)
            except Exception as exc:
                logger.warning("conluio_qsa: fonte de atas indisponível: %s", exc)
        alvo = {c for m in cert.values() if m["perd"] and m["venc"]
                for c in list(m["venc"]) + list(m["perd"])}
        # nome p/ CNPJ que só aparece em ata (o PNCP traz nome; a ata só o CNPJ)
        raz_min: dict[str, str] = {}
        alvo_basicos = {c[:8] for c in alvo}
        try:
            for r in con.execute("SELECT cnpj_basico, razao_social FROM empresas_min"):
                if r["cnpj_basico"] in alvo_basicos:
                    raz_min.setdefault(r["cnpj_basico"], r["razao_social"])
        except sqlite3.OperationalError as exc:
            logger.debug("conluio_qsa sem empresas_min (nome fica do PNCP): %s", exc)

        def _nome_emp(cnpj: str, nomes: dict) -> str:
            return nomes.get(cnpj) or raz_min.get(cnpj[:8]) or "—"
        # QSA por cnpj_basico — pessoa = nome_norm, corroborada pelo fragmento do doc
        qsa: dict[str, dict[str, str]] = {}
        basicos = {c[:8] for c in alvo}
        for r in con.execute(
                "SELECT cnpj_basico, nome_socio, nome_norm, doc_socio, qualificacao_txt "
                "FROM socios_receita WHERE nome_norm<>''"):
            if r["cnpj_basico"] not in basicos:
                continue
            if "CONSELH" in _norm_nome(r["qualificacao_txt"] or ""):
                continue                      # conselheiro de S/A não é dono
            qsa.setdefault(r["cnpj_basico"], {})[r["nome_norm"]] = (
                _frag6(r["doc_socio"]) or re.sub(r"\D", "", r["doc_socio"] or ""),
                r["nome_socio"])
        # 2ª fonte de QSA: socios_fornecedor (BrasilAPI por-CNPJ) — cobre firmas que o dump da
        # Receita não trouxe (empresa nova, EIRELI, sócio não migrado). Chaveada por cnpj_basico.
        try:
            for r in con.execute(
                    "SELECT cnpj, socio_nome, socio_nome_norm, socio_doc, qualificacao "
                    "FROM socios_fornecedor WHERE socio_nome_norm<>'' AND socio_nome<>''"):
                b = (r["cnpj"] or "")[:8]
                if b not in basicos or "CONSELH" in _norm_nome(r["qualificacao"] or ""):
                    continue
                qsa.setdefault(b, {}).setdefault(r["socio_nome_norm"], (
                    _frag6(r["socio_doc"]) or re.sub(r"\D", "", r["socio_doc"] or ""),
                    r["socio_nome"]))
        except sqlite3.OperationalError as exc:
            logger.debug("conluio_qsa sem socios_fornecedor (só dump): %s", exc)
        # ubiquidade: fundo/holding presente em dezenas de QSAs geraria FP em série
        ubiq: dict[str, int] = {}
        for socios in qsa.values():
            for nn in socios:
                ubiq[nn] = ubiq.get(nn, 0) + 1

        pares: dict[tuple, dict] = {}
        n_cert_perd = n_pares = n_sem_qsa = 0
        fontes: dict[str, int] = {}
        for cid, m in cert.items():
            if not (m["venc"] and m["perd"]):
                continue
            n_cert_perd += 1
            f = m.get("fonte", "pncp")
            fontes[f] = fontes.get(f, 0) + 1
            for v, val in m["venc"].items():
                for p in m["perd"]:
                    n_pares += 1
                    tier, comuns = None, []
                    if v[:8] == p[:8]:
                        tier = "MESMA_EMPRESA"
                    else:
                        qv, qp = qsa.get(v[:8]), qsa.get(p[:8])
                        if not (qv and qp):
                            n_sem_qsa += 1
                            continue
                        for nn in set(qv) & set(qp):
                            if ubiq.get(nn, 0) > max_ubiquidade:
                                continue
                            (fv, nome), (fp, _) = qv[nn], qp[nn]
                            if fv and fp and fv != fp:
                                continue      # doc conflita → homônimo, descarta
                            forte = bool(fv and fp and fv == fp)
                            comuns.append({"nome": nome, "doc_frag": fv or fp or "",
                                           "match": "ALTA" if forte else "MEDIA"})
                        if comuns:
                            tier = ("ALTA" if any(s["match"] == "ALTA" for s in comuns)
                                    else "MEDIA")
                    if not tier:
                        continue
                    key = (v[:8], p[:8])
                    par = pares.setdefault(key, {
                        "vencedor": {"cnpj": v, "nome": _nome_emp(v, m["nomes"])},
                        "perdedora": {"cnpj": p, "nome": _nome_emp(p, m["nomes"])},
                        "tier": tier, "socios_comuns": comuns,
                        "n_certames": 0, "valor_vencido": 0.0, "certames": []})
                    par["n_certames"] += 1
                    par["valor_vencido"] += val
                    if len(par["certames"]) < 6:
                        par["certames"].append({"certame": cid, "orgao": m["orgao"],
                                                "data": m["data"], "valor": val,
                                                "fonte": m.get("fonte", "pncp")})
                    ordem = {"MESMA_EMPRESA": 0, "ALTA": 1, "MEDIA": 2}
                    if ordem[tier] < ordem[par["tier"]]:
                        par["tier"], par["socios_comuns"] = tier, comuns or par["socios_comuns"]

        rank = {"MESMA_EMPRESA": 0, "ALTA": 1, "MEDIA": 2}
        lista = sorted(pares.values(),
                       key=lambda x: (rank[x["tier"]], -x["n_certames"], -x["valor_vencido"]))
        n_forte = sum(1 for x in lista if x["tier"] in ("MESMA_EMPRESA", "ALTA"))
        return {"ok": True, "pares": lista[:limite], "n": len(lista), "n_forte": n_forte,
                "cobertura": {"certames_com_perdedora": n_cert_perd,
                              "pares_avaliados": n_pares, "pares_sem_qsa": n_sem_qsa,
                              "certames_por_fonte": fontes},
                "explicacao": ("Vencedor e perdedora do MESMO certame com sócio em comum "
                               "(ou matriz×filial 'concorrendo' entre si): a disputa é de "
                               "fachada — o dono ganha dos dois lados. Quanto mais certames "
                               "o par repete, mais forte o padrão."),
                "ressalva": ("Indício ≠ acusação. QSA da Receita com CPF mascarado — ALTA = "
                             "nome + fragmento coincidem; confirmar CPF completo antes de "
                             "citar. Par sem QSA local = INDISPONÍVEL (≠ inocente); a fila "
                             "de enriquecimento resolve.")}
    finally:
        con.close()


# ── HUB COMPARTILHADO (assinatura de "ninho de fantasmas": 1 âncora física, N CNPJs) ──

# chave lógica → coluna física da tabela `estabelecimentos` (dump Receita, Task 1.1;
# vive em DB separado data/receita_estab.db, ATTACHado readonly).
_HUB_COLUNA = {"endereco": "endereco_norm", "telefone": "telefone1",
               "email": "correio_eletronico"}

# Guardas anti-FALSO-POSITIVO: a MESMA âncora física pode ser legítima em massa.
#  - telefone repetido em CENTENAS de CNPJs ≈ contabilidade de massa / call-center /
#    provedor (o contador declara o próprio telefone em todos os clientes) → não é ninho.
#  - e-mail de domínio/prefixo de contabilidade (contabil/assessoria) → idem.
#  - endereço com DEZENAS de CNPJs ≈ galeria comercial / coworking / condomínio de
#    salas — muitos CNPJs reais dividem o mesmo logradouro normalizado.
# Fundamento: um "ninho" fraudulento é COESO (poucas empresas, casca fina); a massa
# legítima é grande e difusa. Por isso 'alto' exige grupo pequeno E materialidade.
_HUB_TELEFONE_MASSA = 200      # telefone1 em >200 CNPJs → risco 'baixo' (contador/provedor)
_HUB_ENDERECO_MASSA = 80       # endereço em >80 CNPJs → risco 'info' (galeria/coworking)
_HUB_TETO_ALTO = 80            # 'alto' só para grupo coeso (min_cnpjs..80), nunca massa
_HUB_TOTAL_ALTO = 1_000_000.0  # materialidade que sozinha sustenta 'alto' (R$ recebido de OB)
_EMAIL_CONTABIL = ("contabil", "contabilidade", "assessoria", "escritorio")


def hub_compartilhado(chave: str = "endereco", min_cnpjs: int = 5,
                      db_path: str | None = None, estab_path: str | None = None,
                      limite: int = 200) -> dict:
    """HUB COMPARTILHADO: uma âncora física (endereço/telefone/e-mail) usada por N CNPJs.

    Empresas de fachada nascem em lote e compartilham o mesmo endereço-ninho, o mesmo
    telefone ou o mesmo e-mail de contato — a assinatura clássica do "ninho de fantasmas"
    (interposição/laranja; Lei 14.133 art. 5º e 62-63, qualificação inexistente). Agrupa
    `estabelecimentos` (dump Receita, DB separado ``data/receita_estab.db``) pela coluna da
    chave, com ``HAVING COUNT(DISTINCT cnpj) >= min_cnpjs``, e cruza com ``favorecido_resumo``
    (OB do Estado) para materialidade.

    Guarda anti-FP (ver ``_HUB_*``): a mesma âncora pode ser massa LEGÍTIMA (contador com
    o próprio telefone em centenas de clientes; galeria/coworking com dezenas de CNPJs
    reais). Por isso ``risco='alto'`` exige grupo COESO (min_cnpjs..``_HUB_TETO_ALTO``) E
    ≥1 CNPJ recebendo OB E (maioria NÃO-ATIVA OU ``total_recebido_ob`` alto); telefone de
    massa (>200) vira 'baixo', e-mail contábil vira 'baixo', endereço de massa (>80) vira
    'info'; grupo com ente PÚBLICO (CNAE 84xx — prédio de governo) vira 'info'; grupo de
    UMA só raiz de CNPJ (matriz+filiais) vira 'info'. INDISPONÍVEL (dump não ingerido)
    ≠ 0: retorna ``ok=False`` com o motivo.

    Retorna ``{ok, grupos:list[dict], n, chave, explicacao, ressalva}`` — cada grupo é
    ``{chave, valor, n_cnpjs, n_ativos, cnpjs (≤20), n_recebem_ob, total_recebido_ob,
    risco, motivo}`` — para casar o padrão dict/ok/ressalva do módulo (o painel e o cache
    esperam ``.get('ok')``).
    """
    col = _HUB_COLUNA.get(chave)
    if not col:
        return {"ok": False, "erro": f"chave inválida: {chave!r} (use endereco|telefone|email)"}
    estab = estab_path or str(_REPO / "data" / "receita_estab.db")
    con = _ro(db_path)
    try:
        try:
            con.execute("ATTACH DATABASE ? AS estab", (f"file:{estab}?mode=ro",))
        except sqlite3.OperationalError as exc:
            return {"ok": False, "erro": f"estabelecimentos indisponível ({estab}): {exc} — "
                                         "rodar ingest_estabelecimentos (Task 1.1)"}
        try:
            rows = con.execute(
                f"SELECT e.{col} AS valor, COUNT(DISTINCT e.cnpj) AS n_cnpjs, "
                f"  COUNT(DISTINCT e.cnpj_basico) AS n_raizes, "
                f"  COUNT(DISTINCT substr(e.cnae_principal,1,2)) AS n_setores, "
                f"  SUM(CASE WHEN e.cnae_principal LIKE '84%' THEN 1 ELSE 0 END) AS n_publicos, "
                f"  SUM(CASE WHEN e.situacao_cadastral='ATIVA' THEN 1 ELSE 0 END) AS n_ativos, "
                f"  COUNT(DISTINCT CASE WHEN f.favorecido_cpf IS NOT NULL THEN e.cnpj END) AS n_recebem_ob, "
                f"  COALESCE(SUM(f.total_pago), 0) AS total_recebido_ob "
                f"FROM estab.estabelecimentos e "
                f"LEFT JOIN favorecido_resumo f ON f.favorecido_cpf = e.cnpj "
                f"WHERE e.{col} IS NOT NULL AND TRIM(e.{col}) != '' "
                f"GROUP BY e.{col} HAVING COUNT(DISTINCT e.cnpj) >= ? "
                f"ORDER BY total_recebido_ob DESC, n_cnpjs DESC LIMIT ?",
                (min_cnpjs, limite)).fetchall()
        except sqlite3.OperationalError as exc:
            return {"ok": False, "erro": f"estabelecimentos ausente no dump: {exc}"}

        grupos = []
        for r in rows:
            valor, n = r["valor"], r["n_cnpjs"]
            n_ativos, n_ob = r["n_ativos"] or 0, r["n_recebem_ob"] or 0
            n_raizes, n_pub = r["n_raizes"] or 0, r["n_publicos"] or 0
            n_setores = r["n_setores"] or 0
            total = float(r["total_recebido_ob"] or 0.0)
            amostra = [x["cnpj"] for x in con.execute(
                f"SELECT cnpj FROM estab.estabelecimentos WHERE {col} = ? LIMIT 20", (valor,))]
            risco, motivo = _hub_risco(chave, valor, n, n_ativos, n_ob, total,
                                       n_raizes, n_pub, n_setores)
            grupos.append({
                "chave": chave, "valor": valor, "n_cnpjs": n, "n_ativos": n_ativos,
                "n_raizes": n_raizes, "n_publicos": n_pub, "n_setores": n_setores,
                "cnpjs": amostra, "n_recebem_ob": n_ob,
                "total_recebido_ob": round(total, 2), "risco": risco, "motivo": motivo})
        # ── UM CNPJ recebendo não é ninho: é um fornecedor com vizinhos ─────────────────
        # A assinatura de interposição é o dinheiro entrando por MAIS DE UMA casca da mesma
        # âncora. Medido em 25/07/2026 sobre os 88 grupos de risco alto (R$ 16,09 bi):
        #     48 grupos (R$ 8,05 bi — 50,0%) tinham `n_recebem_ob <= 1`
        # e os maiores eram endereços de escritório em avenida — Av. Dra. Ruth Cardoso 7221
        # (Pinheiros/SP), Av. Presidente Vargas 2000 (Centro/RJ) —, onde UMA empresa real
        # recebeu centenas de milhões e as outras do prédio nunca receberam nada. Somar o
        # OB dela e chamar de "ninho de fachada" infla o número em 2×.
        # Mesmo padrão do resto: o conjunto amplo continua, e o par COESO é o que vira
        # manchete. `n_cnpjs` alto também não é ninho — 67 CNPJs num endereço é condomínio.
        _altos = [g for g in grupos if g.get("risco") == "alto"]
        _coesos = [g for g in _altos if (g.get("n_recebem_ob") or 0) >= 2]
        return {"ok": True, "grupos": grupos, "n": len(grupos), "chave": chave,
                "n_alto": len(_altos),
                "total_alto": round(sum(g.get("total_recebido_ob") or 0 for g in _altos), 2),
                "n_multi_recebedor": len(_coesos),
                "total_multi_recebedor": round(sum(g.get("total_recebido_ob") or 0
                                                   for g in _coesos), 2),
                "explicacao": ("Uma âncora física (endereço, telefone ou e-mail) usada por vários "
                               "CNPJs é a assinatura de 'ninho de fantasmas' — empresas de fachada "
                               "abertas em lote compartilham o mesmo contato. 'alto' = grupo coeso "
                               "com dinheiro do Estado e maioria não-ativa. Guardas anti-FP rebaixam: "
                               "massa legítima (contador, galeria/coworking), prédio de GOVERNO "
                               "(CNAE 84), matriz+filiais de uma só raiz de CNPJ e prédio comercial "
                               "multi-inquilino (setores econômicos diversos)."),
                "ressalva": ("Indício ≠ acusação. Endereço/telefone/e-mail compartilhado é comum e "
                             "muitas vezes legítimo (contabilidade, condomínio comercial). Confirmar "
                             "o vínculo real (QSA, execução) antes de citar. Dump da Receita = foto de "
                             "um mês; INDISPONÍVEL (não ingerido) ≠ inexistente.")}
    finally:
        con.close()


def _hub_risco(chave: str, valor: str, n_cnpjs: int, n_ativos: int,
               n_recebem_ob: int, total_recebido_ob: float,
               n_raizes: int = 0, n_publicos: int = 0,
               n_setores: int = 0) -> tuple[str, str]:
    """Classifica o risco de um grupo aplicando as guardas anti-FP (ver ``_HUB_*``)."""
    # guarda de ENTE PÚBLICO: prédio institucional (Fazenda, secretarias, autarquias) concentra
    # CNPJs da administração (CNAE 84xx) e recebe OB bilionária — é governo, não ninho de fachada
    if n_publicos >= 1:
        return "info", (f"inclui {n_publicos} CNPJ(s) da administração pública (CNAE 84) — "
                        "endereço institucional de governo, não ninho")
    # guarda de FILIAL: todas as unidades da MESMA raiz de CNPJ = matriz+filiais de um só ente
    # (banco público, estatal, rede corporativa) — coesão societária legítima, não ninho
    if n_raizes == 1 and n_cnpjs > 1:
        return "info", (f"{n_cnpjs} estabelecimentos da MESMA raiz de CNPJ (matriz+filiais) — "
                        "grupo próprio, não ninho")
    if chave == "telefone" and n_cnpjs > _HUB_TELEFONE_MASSA:
        return "baixo", (f"telefone em {n_cnpjs} CNPJs (>{_HUB_TELEFONE_MASSA}) — "
                         "padrão de contabilidade de massa/call-center, não ninho")
    if chave == "email" and any(t in (valor or "").lower() for t in _EMAIL_CONTABIL):
        return "baixo", "e-mail de contabilidade/assessoria — contato terceirizado legítimo"
    if chave == "endereco" and n_cnpjs > _HUB_ENDERECO_MASSA:
        return "info", (f"endereço em {n_cnpjs} CNPJs (>{_HUB_ENDERECO_MASSA}) — "
                        "provável galeria/coworking/condomínio comercial")
    # guarda de TORRE COMERCIAL: ninho nasce em lote com CNAEs coesos; inquilinos de um
    # prédio comercial são de setores econômicos DIVERSOS (banca, obra, lanchonete...)
    if chave == "endereco" and n_setores >= max(4, -(-n_cnpjs * 7 // 10)):  # ceil(0.7n)
        return "medio", (f"{n_setores} setores econômicos distintos em {n_cnpjs} CNPJs — "
                         "perfil de prédio multi-inquilino, não lote de fachadas; "
                         "materialidade merece olhar, sem tratar como ninho")
    if (min_ok := n_recebem_ob >= 1) and n_cnpjs <= _HUB_TETO_ALTO and \
            (n_ativos < n_cnpjs / 2 or total_recebido_ob >= _HUB_TOTAL_ALTO):
        return "alto", (f"grupo coeso ({n_cnpjs} CNPJs), {n_recebem_ob} recebem OB "
                        f"(R${moeda(total_recebido_ob)}), {n_ativos} ativos — ninho com materialidade")
    if min_ok:
        return "medio", f"{n_recebem_ob} de {n_cnpjs} CNPJs recebem OB — verificar vínculo"
    return "baixo", "nenhum CNPJ do grupo recebe OB do Estado — sem materialidade"


def _beneficios_vinculo_resumo() -> dict:
    """Resumo do cruzamento comissionados/servidores PCRJ × benefício social DURANTE o vínculo
    (pericia_beneficios.analisar() — cruza 7,3 mi de registros; NUNCA rodar no request HTTP)."""
    from compliance_agent.pcrj import pericia_beneficios as PB
    r = PB.analisar()
    # ALTA primeiro (os acionáveis — e os que a consulta nominal enriquece com cargo/natureza),
    # depois por duração; ordenar só por meses afogava os 538 ALTA sob 12k casos MÉDIA
    regs = sorted(r.get("registros", []),
                  key=lambda x: (0 if x.get("certeza") == "ALTA" else 1, -x.get("n_meses", 0)))
    # sem cap: os 300 escondiam 12k+ casos do painel (só ~2,4% visível); o cap de DOM
    # fica por conta do client (paginar() incremental) — aqui o cache guarda TUDO.
    casos = [{k: x.get(k) for k in ("nome", "poder", "orgao", "cargo", "vinculo", "partido",
                                    "beneficios_str", "desde", "ate", "n_meses", "ainda_recebe",
                                    "certeza", "situacao", "natureza")} for x in regs]
    return {"ok": True, "n_casos": len(regs), "casos": casos,
            "resumo": {k: r.get(k) for k in ("n_alta", "n_media", "n_nomeados", "n_nao_nomeados",
                                             "n_vinculo_indet", "n_inativos", "n_bpc", "n_bf",
                                             "n_ab", "n_ae", "n_ainda", "ultima",
                                             "cobertura_folha", "cobertura_benef")},
            "explicacao": ("Benefício social recebido NO MESMO MÊS em que a pessoa tinha vínculo "
                           "remunerado com a Prefeitura/Câmara do Rio — incompatibilidade de renda a "
                           "apurar. Meses fora da janela de vínculo NÃO contam (fairness); homônimos "
                           "são eliminados por município+fragmento de CPF."),
            "ressalva": "Indício por competência (mês). Confirmar CPF completo antes de citar. "
                        "Indício ≠ acusação."}


def prioridade_valor(db_path: str | None = None, min_score: int = 10, limite: int = 60) -> dict:
    """FILA DE PRIORIDADE POR VALOR EM RISCO: cruza o RADAR (quão arriscado é o fornecedor) com a
    ECONOMIA POTENCIAL (quanto os cofres recuperariam se ele tivesse pago a mediana). O topo é o
    fornecedor que junta as duas coisas — sinal de risco aceso E muito dinheiro recuperável —, que
    é onde a auditoria rende mais por hora de trabalho. Determinístico; compõe detectores honestos
    já existentes (nenhum dado novo). Responde ao pedido 'cruzar quem paga mais com o radar'.

    Honestidade: economia é TETO teórico (mediana atingível), não valor a ressarcir; score é indício
    interno; a interseção prioriza, não acusa. Só entram fornecedores com score ≥ min_score E economia>0."""
    from compliance_agent.comparador_precos import economia_potencial
    radar = {a["cnpj"]: a for a in radar_risco(db_path, limite=100_000).get("achados", [])}
    eco = economia_potencial(db_path, limite=100_000).get("por_fornecedor", [])
    achados = []
    for f in eco:
        cnpj = (f.get("fornecedor_cnpj") or "").strip()
        r = radar.get(cnpj)
        if not r or r["score"] < min_score or f.get("economia", 0) <= 0:
            continue
        achados.append({
            "cnpj": cnpj, "cnpj_fmt": r["cnpj_fmt"],
            "nome": r.get("nome") or f.get("fornecedor") or "—",
            "score": r["score"], "rating": r["rating"], "n_sinais": r["n_sinais"],
            "sinais": [s["sinal"] for s in r.get("sinais", [])],
            "economia": round(f["economia"], 2), "n_compras": f.get("n", 0)})
    achados.sort(key=lambda a: (-a["economia"], -a["score"]))
    return {"ok": True, "achados": achados[:limite], "n": len(achados),
            "economia_em_risco": round(sum(a["economia"] for a in achados), 2),
            "escala": ("Interseção RADAR × ECONOMIA. Ordenado pelo R$ recuperável (sobrepreço acima "
                       "da mediana) entre fornecedores que o radar já marca (score ≥ "
                       f"{min_score}). Rating honesto do risco: 🔴 ≥50 · 🟡 25-49 · 🟢 <25 "
                       "(sinal fraco, mas há dinheiro em jogo — ainda vale conferir)."),
            "explicacao": ("Risco alto sem dinheiro em jogo pode esperar; dinheiro alto sem sinal de "
                           "risco pode ser variação legítima de mercado. O cruzamento das duas coisas "
                           "no MESMO fornecedor é a fila que rende mais por hora de apuração."),
            "ressalva": ("Economia = teto teórico (mediana atingível), não valor a ressarcir. Score = "
                         "indício interno. Confirmar termo de referência e documentos. Indício ≠ acusação.")}


def gerar_cache_intel(db_path: str | None = None) -> dict:
    """Materializa os cruzamentos pesados em data/cache/*.json (o painel lê em ms)."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out = {}
    def _comunidades():
        from compliance_agent.grafo_comunidades import detectar_comunidades
        return detectar_comunidades(db_path)

    # ordem importa: radar lê os caches de sancionadas/perdedoras/conluio/hub; comunidades lê conluio
    for nome, fn in (("sancionadas_contratadas", lambda: sancionadas_contratadas(db_path)),
                     ("perdedoras_contumazes", lambda: perdedoras_contumazes(db_path)),
                     ("beneficios_vinculo", _beneficios_vinculo_resumo),
                     ("conluio_qsa", lambda: conluio_qsa(db_path)),
                     ("hub_compartilhado", lambda: hub_compartilhado(db_path=db_path)),
                     # ninho por SALA: ~16 s a frio (74 mil lookups por chave primária no dump
                     # da Receita) — perto demais do teto de 30 s do `J()` do painel, e o card
                     # ficava em "aguardando…" para sempre. Materializado aqui como os outros.
                     ("ninho_sala", lambda: __import__(
                         "compliance_agent.ninho_sala", fromlist=["ninhos_por_sala"]
                     ).ninhos_por_sala(db_path=db_path)),
                     ("comunidades", _comunidades),
                     ("radar_risco", lambda: radar_risco(db_path))):
        try:
            d = fn()
            (_CACHE_DIR / f"{nome}.json").write_text(
                json.dumps(d, ensure_ascii=False), encoding="utf-8")
            out[nome] = {"ok": d.get("ok"), "n": d.get("n", d.get("n_casos"))}
        except Exception as exc:
            logger.warning("cache %s falhou: %s", nome, exc)
            out[nome] = {"ok": False, "erro": str(exc)}
    return out


def ler_cache_intel(nome: str) -> dict | None:
    try:
        p = _CACHE_DIR / f"{nome}.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        d["gerado_em"] = __import__("datetime").datetime.fromtimestamp(
            p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        return d
    except (OSError, ValueError):        # cache ausente ou JSON corrompido → sem cache
        return None


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "cache"
    if cmd == "cache":
        print(json.dumps(gerar_cache_intel(), ensure_ascii=False, indent=1))
    elif cmd == "fantasmas":
        print(json.dumps(avaliar_fantasmas(), ensure_ascii=False, indent=1))
    elif cmd == "sancionadas":
        d = sancionadas_contratadas()
        print(f"{d['n']} empresas ({d['n_a_epoca']} com ato À ÉPOCA da sanção)")
        for e in d["empresas"][:10]:
            print(f"  {e['cnpj']} {e['nome'][:40]:40} estado_durante=R${moeda(e['estado']['valor_durante'])} "
                  f"pncp_durante={e['pncp']['vitorias_durante']}")
    elif cmd == "sancionadas_municipio":
        d = sancionadas_municipio()
        print(f"{d['n']} empresas contratadas pela Prefeitura ({d['n_a_epoca']} À ÉPOCA da sanção); "
              f"descartados por esfera: {d['descartados_outra_esfera']}")
        for e in d["empresas"][:10]:
            print(f"  {e['cnpj']} {e['nome'][:38]:38} durante={e['contratos_durante']} "
                  f"R${moeda(e['valor_durante'])}")
    elif cmd == "perdedoras":
        d = perdedoras_contumazes()
        print(f"{d['n']} perdedoras contumazes")
        for p in d["perdedoras"][:10]:
            print(f"  {p['cnpj_fmt']} {p['nome'][:40]:40} participou={p['participou']}")
    elif cmd == "fracionamento":
        d = fracionamento()
        print(f"{d['n']} grupos com possível fracionamento (colado no teto)")
        for g in d["grupos"][:12]:
            print(f"  {(g['nome'] or '')[:26]:26} UG{g['ug_emitente']} {g['mes']} "
                  f"{g['n_colado']}/{g['n']} colados ({int(g['concentracao']*100)}%) soma R${moeda(g['soma'])}")
    elif cmd == "aditivos":
        d = aditivos_estouro()
        print(f"aditivos: {d['n']} (estouram teto={d['n_estoura_teto']}, série={d['n_serie']}) "
              f"de {d['contratos_analisados']} contratos")
        for a in d["achados"][:12]:
            print(f"  [{'TETO' if a['estoura_teto'] else a['tipo']}] +{a['pct']:>7.0f}% "
                  f"({a['num_aditivos']}adt) R${a['valor_inicial']:>12,.0f}->R${a['valor_global']:>13,.0f} "
                  f"{(a['fornecedor'] or '')[:20]:20} @ {(a['orgao'] or '')[:22]}")
    elif cmd == "conluio":
        d = conluio_qsa()
        print(f"conluio direto: {d['n']} pares ({d['n_forte']} fortes) | {d['cobertura']}")
        for p in d["pares"][:15]:
            sc = ", ".join(s["nome"][:22] for s in p["socios_comuns"][:2]) or "matriz×filial"
            print(f"  [{p['tier']:13}] {p['vencedor']['nome'][:26]:26} x "
                  f"{p['perdedora']['nome'][:26]:26} n={p['n_certames']} "
                  f"R${p['valor_vencido']:,.0f} | {sc}")
    elif cmd == "radar":
        d = radar_risco()
        print(f"radar: {d['n']} fornecedores com sinal ({d['n_vermelho']} 🔴)")
        for a in d["achados"][:15]:
            ss = ", ".join(s["sinal"] for s in a["sinais"])
            print(f"  {a['rating']} [{a['score']:3}] {a['nome'][:34]:34} {ss}")
    elif cmd == "socio_servidor":
        d = socio_servidor()
        print(f"sócio-servidor: {d['n']} (ALTA={d['n_alta']}, gerência={d['n_gerencia']}, "
              f"homônimos descartados={d['homonimos_descartados']})")
        for a in d["achados"][:15]:
            print(f"  [{a['confianca']}] {a['socio'][:24]:24} {a['qualificacao'][:16]:16} de "
                  f"{a['empresa'][:26]:26} R${a['total_pago']:>12,.0f} | {a['servidor_cargo'][:16]:16} "
                  f"@ {(a['servidor_orgao'] or '')[:22]}")
    elif cmd == "sobrepreco":
        d = sobrepreco()
        print(f"itens com preço unitário: {d['itens_com_preco']} | grupos comparáveis: "
              f"{d['grupos_comparaveis']} | achados: {d['n']}")
        for a in d["achados"][:12]:
            print(f"  {a['item'][:34]:34} R${a['preco']:>10,.2f} vs med R${a['mediana']:>9,.2f} "
                  f"({a['razao']}x, n={a['amostra']}) — {(a['orgao'] or '')[:26]}")
