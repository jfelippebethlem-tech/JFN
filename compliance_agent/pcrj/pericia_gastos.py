# -*- coding: utf-8 -*-
"""Perícia determinística de gastos PCRJ — detectores D7–D10.

Mesmo contrato dos detectores de emendas: risco 0–10 explícito, fonte citada,
"indício de" sempre (indício ≠ acusação), match por NOME = fraco (homônimo).
"""
from __future__ import annotations

import json
import logging
import re as _re_reforma
from datetime import date, datetime

logger = logging.getLogger(__name__)

# Lei 14.133/2021, art. 75, II (compras/serviços) — teto ATUALIZADO ANUALMENTE por decreto.
#
# Esta era a TERCEIRA cópia divergente do teto no projeto, e `limites_dispensa.py` avisa no
# topo: "NUNCA duplicar esta tabela em detector — importar daqui (as cópias divergentes em
# p4_fracionamento e cruzamentos_intel foram o motivo deste módulo)". A cópia tinha um único
# ano — `{2026: 62_725.68}`, comentado como "valor vigente conferido (2026)" — e estava
# errada nos dois sentidos, porque o fallback puxava esse mesmo número para TODO ano:
#
#   ano   teto usado    teto legal    efeito                      medido no acervo PCRJ
#   2024  62.725,68     59.906,02     teto ALTO  -> falso POSITIVO   46 contratos
#   2025  62.725,68     62.725,59     9 centavos a mais                0
#   2026  62.725,68     65.492,11     teto BAIXO -> falso NEGATIVO   35 contratos + 52 licitações
#
# Os alertas de fracionamento saem com severidade ALTA no painel; teto errado nos dois
# sentidos é acusar quem não devia e perder quem devia. Agora vem da fonte única, por ANO.
from compliance_agent.limites_aditivo import teto_acrescimo as _teto_acrescimo
from compliance_agent.limites_dispensa import LIMITES, limite_dispensa as _limite_dispensa


def teto_dispensa(ano: int | None = None) -> float:
    """Teto de dispensa de COMPRAS do exercício, da fonte única `limites_dispensa`."""
    return _limite_dispensa(ano or date.today().year, "compras")


TETO_DISPENSA_COMPRAS = teto_dispensa(2026)  # compat: consumidores antigos importam a constante
_RE_REFORMA_OBJ = _re_reforma.compile(r"reforma\s+(?:de\s+)?(?:edif[íi]cio|pr[ée]dio|im[óo]vel|equipamento|cobertura)|reforma\s+d[ao]\s", _re_reforma.I)
D7_JANELA_DIAS = 90
D7_MINIMO_REGISTROS = 3
D8_DIAS_RECEM_ABERTA = 180
D8_VALOR_MINIMO = 100_000.0
# art. 125: acréscimo até 25% (50% só reforma de edifício/equip.). O número vem da fonte única
# `limites_aditivo`; aqui fica como MULTIPLICADOR (1 + teto) porque a consulta compara global×inicial.
D10_LIMITE_ADITIVO = 1.0 + _teto_acrescimo(None)


def _brl(v: float | None) -> str:
    v = v or 0.0
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _sev(risco: int) -> str:
    return "alta" if risco >= 8 else ("media" if risco >= 5 else "baixa")


def _achado(detector: str, risco: int, titulo: str, descricao: str, evidencias: dict) -> dict:
    return {"detector": detector, "risco": max(0, min(10, risco)), "titulo": titulo,
            "descricao": descricao, "evidencias": evidencias}


def _data(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


# ── D7 — fracionamento de despesa ────────────────────────────────────────────
def d7_fracionamento(con, teto: float | None = None,
                     janela_dias: int = D7_JANELA_DIAS,
                     minimo: int = D7_MINIMO_REGISTROS) -> list[dict]:
    """≥3 empenhos/contratos ABAIXO do teto de dispensa, mesmo credor+órgão,
    em janela de 90 dias, cuja SOMA ultrapassa o teto — o padrão clássico de
    fatiar para fugir de licitação (Lei 14.133, art. 75 §1º).

    O teto é o **do ano da contratação**, não um valor único. Antes um número só era
    aplicado a todos os exercícios, e ele era o de 2025 rotulado como 2026 — resultado
    medido: **46 contratos de 2024 entravam indevidamente** (teto alto demais) e **35
    contratos + 52 licitações de 2026 sumiam** (teto baixo demais). Trocar só a constante
    para a de 2026 teria PIORADO 2024, porque o teto sobe a cada ano — por isso a
    comparação virou por exercício, no próprio SQL.

    `teto` explícito continua aceito e passa a valer para todos os anos (compatibilidade e
    cenário de teste); `None` = por ano, que é o correto em produção.
    """
    if teto is None:
        casos = " ".join(f"WHEN {a} THEN {v['compras']}" for a, v in sorted(LIMITES.items()))
        padrao = LIMITES[max(LIMITES)]["compras"]
        teto_sql = f"(CASE CAST(substr(data_assinatura,1,4) AS INT) {casos} ELSE {padrao} END)"
        params: tuple = ()
    else:
        teto_sql, params = "?", (teto,)
    rows = con.execute(f"""
        select orgao_cnpj, coalesce(orgao_nome,'') as orgao_nome,
               fornecedor_documento, coalesce(fornecedor_nome,'') as fornecedor_nome,
               data_assinatura, valor_global, numero_controle_pncp,
               {teto_sql} as teto_ano
        from pcrj_contratos
        where valor_global > 0 and valor_global < {teto_sql} and data_assinatura is not null
        order by orgao_cnpj, fornecedor_documento, data_assinatura""",
        params * 2).fetchall()
    grupos: dict[tuple, list] = {}
    for r in rows:
        d = _data(r["data_assinatura"])
        if d:
            grupos.setdefault((r["orgao_cnpj"], r["fornecedor_documento"]), []).append((d, r))
    achados = []
    for (orgao, forn), itens in grupos.items():
        itens.sort(key=lambda x: x[0])
        ini = 0
        melhor: list | None = None
        for fim in range(len(itens)):
            while (itens[fim][0] - itens[ini][0]).days > janela_dias:
                ini += 1
            janela = itens[ini:fim + 1]
            if len(janela) >= minimo and (melhor is None or len(janela) > len(melhor)):
                melhor = janela
        if not melhor:
            continue
        soma = sum(r["valor_global"] for _, r in melhor)
        # o teto da JANELA é o do exercício em que ela começa (o `teto_ano` já vem do SQL,
        # por linha) — comparar a soma contra um teto de outro ano era parte do mesmo erro.
        teto_janela = melhor[0][1]["teto_ano"]
        if soma <= teto_janela:
            continue        # fatias que nem somadas passam do teto não indicam fuga
        r0 = melhor[0][1]
        risco = min(9, 5 + min(4, len(melhor) - minimo + 1))
        achados.append(_achado(
            "d7_fracionamento", risco,
            f"Fracionamento — {r0['fornecedor_nome'] or forn} × {r0['orgao_nome'] or orgao}",
            f"Indício de fracionamento de despesa: {len(melhor)} contratações do credor "
            f"{r0['fornecedor_nome'] or forn} (doc. {forn}) pelo órgão "
            f"{r0['orgao_nome'] or orgao} em ≤{janela_dias} dias, todas abaixo do teto de "
            f"dispensa de {r0['data_assinatura'][:4]} (R$ {_brl(teto_janela)}), somando R$ {_brl(soma)} — soma acima do teto "
            f"sugere fuga de licitação (Lei 14.133/2021, art. 75 §1º). "
            f"(fonte: PNCP, contratos/empenhos publicados)",
            {"subtipo": "fracionamento", "orgao": orgao, "fornecedor": forn,
             "n_contratos": len(melhor), "soma": soma,
             "controles_pncp": [r["numero_controle_pncp"] for _, r in melhor]}))
    return achados


# ── D8 — credor recém-aberto ganhando valor relevante ───────────────────────
def _consulta_minhareceita(cnpj: str) -> dict | None:
    import httpx
    try:
        r = httpx.get(f"https://minhareceita.org/{cnpj}", timeout=30)
        if r.status_code == 200:
            return r.json()
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("d8: minhareceita INDISPONÍVEL p/ %s: %s", cnpj, e)
    return None


def d8_credor_recem_aberto(con, consulta_cnpj=None, dias: int = D8_DIAS_RECEM_ABERTA,
                           valor_minimo: float = D8_VALOR_MINIMO, top: int = 60) -> list[dict]:
    consulta_cnpj = consulta_cnpj or _consulta_minhareceita
    rows = con.execute("""
        select fornecedor_documento, coalesce(fornecedor_nome,'') as fornecedor_nome,
               min(data_assinatura) as primeiro, sum(valor_global) as total, count(*) as n
        from pcrj_contratos
        where length(fornecedor_documento) = 14 and data_assinatura is not null
        group by 1 having total >= ? order by total desc limit ?""",
        (valor_minimo, top)).fetchall()
    # cadastro LOCAL primeiro (tabela empresas, backfill diário): quando a minhareceita cai,
    # o D8 inteiro zerava silenciosamente — 1.820 fornecedores têm data_abertura local
    def _abertura_local(doc: str) -> str | None:
        try:
            r = con.execute("SELECT data_abertura FROM empresas WHERE cnpj=? "
                            "AND data_abertura IS NOT NULL", (doc,)).fetchone()
            return r[0] if r else None
        except Exception:  # noqa: BLE001 — tabela pode não existir num banco parcial
            return None

    achados = []
    for r in rows:
        local = _abertura_local(r["fornecedor_documento"])
        info = {"data_inicio_atividade": local} if local else consulta_cnpj(r["fornecedor_documento"])
        if not info:
            continue        # INDISPONÍVEL — logado na consulta; não vira "limpo"
        abertura = _data(str(info.get("data_inicio_atividade") or ""))
        primeiro = _data(r["primeiro"])
        if not abertura or not primeiro:
            continue
        idade = (primeiro - abertura).days
        if idade < 0 or idade > dias:
            continue
        risco = 8 if idade <= 90 else 7
        achados.append(_achado(
            "d8_credor_recem_aberto", risco,
            f"Credor recém-aberto — {r['fornecedor_nome'] or r['fornecedor_documento']}",
            f"Indício de credor sem histórico: {r['fornecedor_nome']} "
            f"(CNPJ {r['fornecedor_documento']}) foi aberto em {abertura:%d/%m/%Y} e "
            f"{idade} dias depois já firmava contratação com a PCRJ "
            f"({primeiro:%d/%m/%Y}); soma R$ {_brl(r['total'])} em {r['n']} registro(s). "
            f"(fontes: PNCP + Receita Federal via minhareceita.org)",
            {"subtipo": "recem_aberta", "cnpj": r["fornecedor_documento"],
             "idade_dias": idade, "total": r["total"]}))
    return achados


# ── D9 — sócio de credor ∈ folha municipal ──────────────────────────────────
def _folha_padrao() -> dict[str, dict]:
    """nome_norm → {orgao, cargo} da competência mais recente da folha PCRJ."""
    from compliance_agent.pcrj.db import conectar as conectar_folha
    fol = conectar_folha()
    comp = fol.execute("select max(competencia) from pcrj_folha_pref").fetchone()[0]
    out = {}
    for r in fol.execute("""select nome_norm, orgao from pcrj_folha_pref
                            where competencia = ?""", (comp,)):
        out[r[0]] = {"orgao": r[1], "cargo": ""}
    return out


def d9_socio_na_folha(con, folha_norm: dict[str, dict] | None = None) -> list[dict]:
    """QSA dos credores PCRJ × folha municipal por nome normalizado.
    Sem CPF em nenhuma das pontas → SEMPRE indício (homônimo possível)."""
    rows = con.execute("""
        select distinct s.nome_norm, s.nome_socio, s.cnpj_basico,
               d.credor_nome, d.credor_documento, sum(d.pago) as pago
        from pcrj_despesa d
        join socios_receita s
          on length(d.credor_documento) = 14
         and s.cnpj_basico = substr(d.credor_documento, 1, 8)
        group by s.nome_norm, s.cnpj_basico, d.credor_documento""").fetchall()
    if not rows:
        return []                       # sem QSA×credor não há o que cruzar
    if folha_norm is None:
        folha_norm = _folha_padrao()    # 12M linhas → só carrega se precisar
    achados = []
    for r in rows:
        # guard anti-homônimo: nome com <3 tokens (JOAO SILVA) gera ruído em massa
        # na folha de ~200k servidores — só nome completo entra no match
        if len((r["nome_norm"] or "").split()) < 3:
            continue
        hit = folha_norm.get(r["nome_norm"])
        if not hit:
            continue
        achados.append(_achado(
            "d9_socio_na_folha", 5,
            f"Sócio de credor na folha — {r['nome_socio']}",
            f"Indício de conflito: {r['nome_socio']}, sócio do credor {r['credor_nome']} "
            f"(CNPJ {r['credor_documento']}, R$ {_brl(r['pago'])} pagos pela PCRJ), tem "
            f"HOMÔNIMO na folha municipal (lotação {hit.get('orgao') or 'n/d'}). Match "
            f"somente por nome normalizado — homônimo é possível; confirmar CPF/matrícula "
            f"antes de qualquer uso. (fontes: Open_Data_Empenhos CGM + QSA Receita + "
            f"folha PCRJ via contracheque)",
            {"subtipo": "socio_folha", "socio": r["nome_socio"],
             "credor": r["credor_documento"], "lotacao": hit.get("orgao"),
             "match_tipo": "NOME"}))
    return achados


# ── D10 — rede societária entre fornecedores do mesmo órgão ─────────────────
def d10_rede_concorrentes(con) -> list[dict]:
    achados = []
    # mesmo sócio (nome_norm ou CPF) em ≥2 fornecedores do MESMO órgão no ano
    rows = con.execute("""
        select c.orgao_cnpj, coalesce(c.orgao_nome,'') as orgao_nome, c.ano,
               s.nome_norm, s.nome_socio, s.doc_socio,
               group_concat(distinct c.fornecedor_documento) as fornecedores,
               group_concat(distinct c.fornecedor_nome) as nomes
        from pcrj_contratos c
        join socios_receita s
          on length(c.fornecedor_documento) = 14
         and s.cnpj_basico = substr(c.fornecedor_documento, 1, 8)
        -- O vínculo tem de existir NA ÉPOCA do contrato. O QSA é um retrato de hoje, e sem este
        -- corte o detector acusava rede societária que ainda não existia: medido em 2026-08-09,
        -- 54 dos 649 alertas (8,3%) apoiavam-se em sócio que entrou na empresa DEPOIS do ano do
        -- contrato — inclusive o par ROMA×MEDKA em 2024, cujo administrador comum só chegou em
        -- março de 2026. Mesma lição de `situacao-cadastral-vigencia-na-data`. O teto é o fim do
        -- ano (a tabela só tem o ano), o que é generoso de propósito: na dúvida, mantém o alerta.
         and (length(coalesce(s.data_entrada,'')) <> 8
              or s.data_entrada <= cast(c.ano as text) || '1231')
        group by c.orgao_cnpj, c.ano, s.nome_norm,
                 case when s.doc_socio != '' then s.doc_socio else s.nome_norm end
        having count(distinct substr(c.fornecedor_documento, 1, 8)) >= 2""").fetchall()
    for r in rows:
        forte = bool(r["doc_socio"])
        achados.append(_achado(
            "d10_rede_concorrentes", 7 if forte else 5,
            # O título é a IDENTIDADE do achado: é por ele que o gravador dedupa e a poda decide o
            # que morreu. Sem órgão e ano, catorze achados distintos do mesmo sócio colapsavam num
            # título só — a dedup nunca os separou e a poda não conseguia retirar o anacrônico de
            # 2024 sem levar junto o legítimo de 2026.
            f"Rede societária — {r['nome_socio']} em ≥2 fornecedores de "
            f"{(r['orgao_nome'] or r['orgao_cnpj'])[:40]} ({r['ano']})",
            f"Indício de rede entre fornecedores: {r['nome_socio']} figura no QSA de "
            f"fornecedores distintos ({r['nomes']}) contratados pelo mesmo órgão "
            f"({r['orgao_nome'] or r['orgao_cnpj']}) em {r['ano']} — padrão compatível com "
            f"concorrência fictícia (checar se disputaram os mesmos certames)."
            + ("" if forte else " Match por NOME normalizado — homônimo possível.")
            + " (fontes: PNCP + QSA Receita local)",
            {"subtipo": "rede_socios", "socio": r["nome_socio"], "ano": r["ano"],
             "fornecedores": (r["fornecedores"] or "").split(","),
             "match_tipo": "CPF" if forte else "NOME"}))
    return achados


# ── D11 — aditivo acima do limite do art. 125 ────────────────────────────────
# (vivia DENTRO do d10 sob o MESMO código de detector — duas análises num rótulo só
# confundiam contagem, KPI e ficha; split 2026-07-18, subtipo preservado p/ compat)
def d11_aditivo_estourado(con, limite_aditivo: float = D10_LIMITE_ADITIVO) -> list[dict]:
    """Acréscimo por aditivo acima do teto do art. 125.

    A versão anterior comparava apenas `valor_global > valor_inicial * 1.25`, sem olhar os termos:
    reajuste, reequilíbrio e prorrogação entravam no teto como se fossem acréscimo de escopo, e o
    tipo do objeto era ignorado (reforma tem teto de 50%). Agora a natureza de cada termo vem da
    régua única (`limites_aditivo`), a mesma do X1 e do intel; quando os termos existem em
    `contrato_aditivo`, o percentual é o do ACRÉSCIMO REAL. Sem eles, o achado ainda sai — mas
    declarado como `nao_confirmado`, porque global−inicial não é acréscimo do art. 125.
    """
    from compliance_agent.limites_aditivo import acrescimo_computavel, ato_normativo

    # pré-filtro largo pelo MENOR teto possível: nada que possa estourar é descartado no SQL.
    rows = con.execute("""
        select numero_controle_pncp, ano, orgao_cnpj, coalesce(orgao_nome,'') as orgao_nome,
               fornecedor_documento, coalesce(fornecedor_nome,'') as fornecedor_nome,
               coalesce(objeto,'') as objeto, valor_inicial, valor_global
        from pcrj_contratos
        where valor_inicial > 0 and valor_global > valor_inicial * ?""",
        (limite_aditivo,)).fetchall()

    por_contrato: dict[str, list[dict]] = {}
    try:
        for a in con.execute(
                "select numero_controle_pncp, objeto, valor_acrescido, prazo_aditado_dias, "
                "qualif_acrescimo, qualif_vigencia, qualif_reajuste, fundamento_legal "
                "from contrato_aditivo"):
            por_contrato.setdefault(a["numero_controle_pncp"], []).append(dict(a))
    except Exception as exc:  # noqa: BLE001 — sem a tabela, degrada p/ nao_confirmado (não cala)
        logger.debug("contrato_aditivo indisponível no d11: %s", exc)

    achados = []
    for r in rows:
        e_reforma = bool(_RE_REFORMA_OBJ.search(r["objeto"]))
        teto = _teto_acrescimo("reforma" if e_reforma else None)
        ads = por_contrato.get(r["numero_controle_pncp"])
        if ads:
            comp = acrescimo_computavel(ads)
            pct_frac, confirmado = comp["acrescimo"] / r["valor_inicial"], True
            lacunas = comp["lacunas"]
        else:
            pct_frac, confirmado, lacunas = (r["valor_global"] / r["valor_inicial"] - 1), False, []
        if pct_frac <= teto:
            continue
        pct = pct_frac * 100
        origem = ("acréscimo apurado nos termos aditivos" if confirmado
                  else "global−inicial (NÃO confirmado: pode incluir reajuste ou prorrogação)")
        achados.append(_achado(
            "d11_aditivo_estourado", min(9, 6 + int(pct // 50)) - (0 if confirmado else 2),
            f"Aditivos acima do limite — {r['fornecedor_nome'] or r['fornecedor_documento']}",
            f"Indício de acréscimo contratual acima do limite: contrato "
            f"{r['numero_controle_pncp']} ({r['orgao_nome'] or r['orgao_cnpj']}, {r['ano']}) "
            f"saiu de R$ {_brl(r['valor_inicial'])} para R$ {_brl(r['valor_global'])} "
            f"(+{pct:.0f}%), acima dos {teto:.0%} do {ato_normativo()} "
            f"{'(reforma de edifício/equipamento)' if e_reforma else ''}. "
            f"Base do percentual: {origem}. (fonte: PNCP)",
            {"subtipo": "aditivo_estourado", "controle": r["numero_controle_pncp"],
             "pct_acrescimo": round(pct, 1), "teto_pct": round(teto * 100),
             "acrescimo_confirmado": confirmado, "lacunas_aditivo": lacunas}))
    return achados


# ── D12 — co-endereço entre fornecedores do mesmo órgão (OCDE 2025) ──────────
D12_CEP_POPULAR = 5   # CEP em mais empresas que isto na base = edifício/galeria comercial → guard


def d12_coendereco_concorrentes(con, cep_popular: int = D12_CEP_POPULAR) -> list[dict]:
    """Fornecedores CONTRATADOS pelo mesmo órgão/ano compartilhando o MESMO CEP — red flag
    clássica da lista OCDE 2025 de bid rigging ("bidders sharing the same address").
    Guards de honestidade: (a) CEP no Rio cobre um trecho de logradouro, não um imóvel —
    risco médio, nunca alto sozinho; (b) CEP presente em > cep_popular empresas da base é
    endereço comercial popular (coworking/galeria) e sai do detector."""
    try:
        rows = con.execute("""
            select c.orgao_cnpj, coalesce(c.orgao_nome,'') as orgao_nome, c.ano, e.cep,
                   group_concat(distinct c.fornecedor_documento) as docs,
                   group_concat(distinct coalesce(c.fornecedor_nome, c.fornecedor_documento)) as nomes
            from pcrj_contratos c
            join empresas e on e.cnpj = c.fornecedor_documento
            where length(c.fornecedor_documento) = 14
              and e.cep is not null and trim(e.cep) != ''
            group by c.orgao_cnpj, c.ano, e.cep
            having count(distinct c.fornecedor_documento) >= 2""").fetchall()
    except Exception as e:  # noqa: BLE001 — tabela empresas ausente = INDISPONÍVEL, não zero
        logger.warning("d12: cadastro local indisponível (%s) — detector não avaliável", e)
        return []
    # dedup por (cep, conjunto de fornecedores): o MESMO par em anos distintos é UM indício
    # (recorrente até fortalece) — sem isso o leitor via o par repetido por ano
    grupos: dict[tuple, dict] = {}
    for r in rows:
        docs = tuple(sorted((r["docs"] or "").split(",")))
        g = grupos.setdefault((r["cep"], docs), {"anos": set(), "r": r})
        g["anos"].add(r["ano"])
    achados = []
    for (cep, docs), g in grupos.items():
        n_no_cep = con.execute("SELECT COUNT(*) FROM empresas WHERE cep=?", (cep,)).fetchone()[0]
        if n_no_cep > cep_popular:
            continue  # endereço comercial popular — co-localização não indicia nada
        r = g["r"]
        anos = ", ".join(str(a) for a in sorted(g["anos"]))
        recorrente = len(g["anos"]) > 1
        achados.append(_achado(
            "d12_coendereco_concorrentes", 7 if recorrente else 6,
            f"Co-endereço — {len(docs)} fornecedores do mesmo órgão no CEP {cep}",
            f"Indício de vínculo entre fornecedores: {r['nomes']} compartilham o CEP "
            f"{cep} e foram contratados pelo mesmo órgão "
            f"({r['orgao_nome'] or r['orgao_cnpj']}) em {anos}"
            + (" — padrão RECORRENTE em múltiplos exercícios" if recorrente else "")
            + ". Empresas concorrentes no mesmo endereço é red flag da lista OCDE 2025 de "
            "combinação de propostas (bid rigging). CEP cobre trecho de logradouro (não um "
            "imóvel) — corroborar com QSA, telefone/e-mail de cadastro e participação nos "
            "mesmos certames. (fontes: PNCP + cadastro local RFB)",
            {"subtipo": "coendereco", "cep": cep, "fornecedores": list(docs), "anos": sorted(g["anos"]),
             "n_empresas_no_cep_base": n_no_cep}))
    return achados


# ── orquestração ─────────────────────────────────────────────────────────────
_DETECTORES = {
    "d7": d7_fracionamento,
    "d8": d8_credor_recem_aberto,
    "d9": d9_socio_na_folha,
    "d10": d10_rede_concorrentes,
    "d11": d11_aditivo_estourado,
    "d12": d12_coendereco_concorrentes,
}


def rodar_todas(con, gravar_alertas: bool = False) -> dict:
    achados: list[dict] = []
    cobertura: dict[str, str] = {}
    for nome, fn in _DETECTORES.items():
        try:
            res = fn(con)
            cobertura[nome] = f"ok: {len(res)} achado(s)"
            achados.extend(res)
        except Exception as e:
            logger.exception("detector %s falhou", nome)
            cobertura[nome] = f"ERRO (INDISPONÍVEL ≠ 0): {e}"
    achados.sort(key=lambda a: -a["risco"])
    if gravar_alertas:
        for a in achados:
            # dedup por (tipo, titulo): re-rodar a perícia ATUALIZA o alerta em vez de duplicar
            # (antes cada corrida empilhava cópias; o painel dedupava na leitura, o DB inchava)
            ex = con.execute("select id from alertas where tipo=? and titulo=?",
                             (f"pcrj_{a['detector']}", a["titulo"])).fetchone()
            if ex:
                con.execute("update alertas set severidade=?, descricao=?, evidencias=? where id=?",
                            (_sev(a["risco"]), a["descricao"],
                             json.dumps(a["evidencias"], ensure_ascii=False, default=str), ex[0]))
            else:
                con.execute(
                    """insert into alertas (tipo, severidade, titulo, descricao, evidencias, status)
                       values (?,?,?,?,?, 'novo')""",
                    (f"pcrj_{a['detector']}", _sev(a["risco"]), a["titulo"], a["descricao"],
                     json.dumps(a["evidencias"], ensure_ascii=False, default=str)))
        cobertura["poda"] = _podar_superados(con, achados, cobertura)
        con.commit()
    return {"achados": achados, "cobertura": cobertura}


def _tipos_gravados(con) -> list[str]:
    """Tipos `pcrj_*` já presentes na tabela — inclui os que o detector deixou de produzir."""
    try:
        return [r[0] for r in con.execute(
            "select distinct tipo from alertas where tipo like 'pcrj_%'")]
    except Exception:                      # noqa: BLE001 — tabela ausente não é erro de perícia
        logger.warning("tabela de alertas indisponível — poda não roda nesta corrida")
        return []


def _podar_superados(con, achados: list[dict], cobertura: dict[str, str]) -> str:
    """Retira alertas que o detector NÃO produz mais — consertar o detector não limpa o painel.

    O gravador só inseria e atualizava. Quando o `d10` ganhou o corte de vigência (2026-08-09), os
    **54 alertas anacrônicos já gravados continuaram no painel**, afirmando rede societária que o
    próprio detector deixara de afirmar. É a lição de `reparar-e-verificar-o-efeito-nao-a-acao`:
    a correção do produtor não alcança o que já foi publicado.

    Poda CONSERVADORA, por causa de `INDISPONÍVEL ≠ 0`: só mexe em detector que rodou sem erro **e
    devolveu pelo menos um achado**. Detector que zerou pode ter zerado porque a fonte sumiu, e
    apagar tudo nesse caso transformaria uma falha de coleta em "nada a apurar" — o pior estrago
    possível num painel de fiscalização. Quando isso acontece, fica registrado na cobertura.
    """
    # A chave de `_DETECTORES` é curta ("d10"); o `tipo` gravado usa o nome longo do achado
    # ("pcrj_d10_rede_concorrentes"). Montar o tipo a partir da chave não casa com nada e a poda
    # vira silenciosa — o `tipo` tem de vir do próprio achado, e o prefixo da chave é a ponte.
    vivos: dict[str, set[str]] = {}
    for a in achados:
        vivos.setdefault(f"pcrj_{a['detector']}", set()).add(a["titulo"])
    tipos_do_detector = {
        nome: {t for t in list(vivos) + _tipos_gravados(con) if t.startswith(f"pcrj_{nome}_")}
        for nome in _DETECTORES}
    apagados, poupados = 0, []
    for nome in _DETECTORES:
        if not str(cobertura.get(nome, "")).startswith("ok"):
            continue                       # erro no detector: não julga o que não mediu
        for tipo in sorted(tipos_do_detector[nome]):
            titulos = vivos.get(tipo)
            if not titulos:
                n = con.execute("select count(*) from alertas where tipo=?", (tipo,)).fetchone()
                if n and n[0]:
                    poupados.append(f"{tipo}({n[0]})")
                continue                   # zerou: pode ser fonte ausente — poupa e declara
            marcas = ",".join("?" * len(titulos))
            cur = con.execute(f"delete from alertas where tipo=? and titulo not in ({marcas})",
                              (tipo, *sorted(titulos)))
            apagados += cur.rowcount or 0
    aviso = f"{apagados} alerta(s) superado(s) retirado(s)"
    if poupados:
        aviso += (f"; POUPADOS por zerarem nesta corrida (INDISPONÍVEL ≠ 0): {', '.join(poupados)}")
    logger.info("poda de alertas: %s", aviso)
    return aviso
