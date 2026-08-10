# -*- coding: utf-8 -*-
"""Perícia determinística de emendas — detectores D1–D6 (código, não prompt).

Todo achado carrega: escala de risco 0–10 explícita, fonte citada e texto
"indício de" (indício ≠ acusação — regra-mãe). Valores nas 3 fases sempre
separados (empenhado ≠ liquidado ≠ pago). Match por NOME = indício fraco
(homônimo possível); match por CPF/CNPJ = forte.
"""
from __future__ import annotations

import logging
import re

from .camara import norm_nome

logger = logging.getLogger(__name__)

# limiares (o porquê de cada um no detector que o usa)
D2_SHARE_MINIMO = 0.5        # metade da carteira num único destino = curral em tese
D2_PISO_TOTAL = 1_000_000.0  # abaixo disso concentração não é informativa
D4_VALOR_MINIMO = 100_000.0  # fantasma só interessa com dinheiro relevante
D4_SCORE_MINIMO = 50         # score do empresa_fantasma (0-100) p/ virar achado
D6_FRACAO_CANCELADA = 0.5    # >50% do empenho cancelado = anúncio sem execução

# entes públicos recebem emenda por desenho legal (fundo a fundo) — não são "fantasma"
_ENTE_PUBLICO = re.compile(
    r"\b(FUNDO|MUNICIPIO|MUNICÍPIO|PREFEITURA|ESTADO D[EO]|SECRETARIA|UNIVERSIDADE"
    r"|INSTITUTO FEDERAL|CAMARA|CÂMARA|TRIBUNAL|COMANDO|MINISTERIO|MINISTÉRIO)\b", re.I)


def _brl(v: float | None) -> str:
    v = v or 0.0
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _sev(risco: int) -> str:
    return "alta" if risco >= 8 else ("media" if risco >= 5 else "baixa")


def _achado(detector: str, risco: int, titulo: str, descricao: str,
            evidencias: dict, codigo_emenda: str | None = None) -> dict:
    return {"detector": detector, "risco": max(0, min(10, risco)), "titulo": titulo,
            "descricao": descricao, "evidencias": evidencias, "codigo_emenda": codigo_emenda}


# ── D1 — emenda PIX com plano impedido/rejeitado ────────────────────────────
def d1_pix_impedida(con) -> list[dict]:
    achados = []
    for r in con.execute("""select id_plano, ano, cnpj_beneficiario, nome_beneficiario,
                                   municipio, situacao
                            from emendas_pix_planos
                            where upper(situacao) like 'IMPEDIDO%'"""):
        rejeitado = "REJEICAO" in (r["situacao"] or "").upper()
        risco = 7 if rejeitado else 6
        achados.append(_achado(
            "d1_pix_impedida", risco,
            # o PLANO no título: um beneficiário com 36 planos impedidos são 36 achados, e sem
            # o id eles colapsavam num só (a dedup do gravador e a poda decidem por título)
            f"Emenda PIX impedida — {r['nome_beneficiario']} (plano {r['id_plano']}/{r['ano']})",
            f"Indício de transferência especial (art. 166-A CF) sem execução regular: "
            f"plano de ação {r['id_plano']} ({r['ano']}) do beneficiário "
            f"{r['nome_beneficiario']} (CNPJ {r['cnpj_beneficiario']}) está na situação "
            f"\"{r['situacao']}\" no Transferegov"
            + (" — plano de trabalho rejeitado" if rejeitado else "")
            + ". (fonte: API Transferegov, transferenciasespeciais)",
            {"id_plano": r["id_plano"], "situacao": r["situacao"],
             "cnpj": r["cnpj_beneficiario"]}))
    return achados


# ── D2 — concentração autor→destino (curral eleitoral em tese) ──────────────
def d2_concentracao_autor(con, share_minimo: float = D2_SHARE_MINIMO,
                          piso_total: float = D2_PISO_TOTAL) -> list[dict]:
    """Só destinos municipais contam (UF inteira/NACIONAL/MÚLTIPLO não é curral)."""
    achados = []
    rows = con.execute("""
        select autor_norm, localidade_gasto, sum(empenhado) as v,
               sum(sum(empenhado)) over (partition by autor_norm) as total
        from emendas
        where autor_norm != '' and localidade_gasto like '% - %'
        group by 1, 2""").fetchall()
    for r in rows:
        if not r["total"] or r["total"] < piso_total:
            continue
        share = r["v"] / r["total"]
        if share < share_minimo:
            continue
        risco = min(8, 4 + round(share * 4))
        achados.append(_achado(
            "d2_concentracao_autor", risco,
            f"Concentração de emendas — {r['autor_norm']} → {r['localidade_gasto']}",
            f"Indício de concentração territorial: {share:.0%} da carteira de emendas de "
            f"{r['autor_norm']} (R$ {_brl(r['total'])} empenhados no recorte coletado) "
            f"destina-se a {r['localidade_gasto']} (R$ {_brl(r['v'])}). Concentração "
            f"não é ilícito por si; vira alvo quando combinada com favorecido frágil ou "
            f"retroalimentação (D4/D5). (fonte: API Portal da Transparência, /emendas)",
            {"autor": r["autor_norm"], "destino": r["localidade_gasto"],
             "share": round(share, 3), "total_autor": r["total"]}))
    return achados


# ── D3 — favorecido sancionado (CEIS/CNEP/…) ────────────────────────────────
def d3_favorecido_sancionado(con) -> list[dict]:
    """Favorecido de emenda que consta em cadastro de sanção — com a VIGÊNCIA conferida.

    A versão anterior cruzava favorecido × sanção sem olhar data nenhuma, e acusava com risco 9.
    Medido em 2026-08-10 sobre os 746 pares (emenda, favorecido) que casam: **656 (87,9%) têm
    sanção que só COMEÇOU depois do ano da emenda** — e o vão não é de meses: 529 têm 2 anos ou
    mais, 278 têm 4 ou mais. É a mesma lição de `situacao-cadastral-vigencia-na-data`, onde 78,7%
    das acusações de "empresa não-ativa" eram anacrônicas.

    Contratar quem JÁ ESTAVA sancionado é o achado. Contratar quem viria a ser sancionado anos
    depois é informação de contexto — pode até indicar que o problema já existia e só foi apurado
    tarde, mas não sustenta acusação, e chamar as duas coisas de "favorecido sancionado" com risco
    9 é fabricar gravidade.

    RESSALVA DE MÉTODO: a régua aqui é o ANO DA EMENDA, não a data do pagamento — o
    `emenda_favorecidos` não guarda data de pagamento (só `coletado_em`, que é nossa). Um pagamento
    pode ocorrer anos depois da emenda, então o corte de 1 ano de vão é conservador de propósito: o
    achado posterior não some, muda de natureza e de risco.
    """
    # O CASAMENTO É EM MEMÓRIA, não em SQL. O join anterior tinha um `OR` com `substr()`, o que
    # impede o uso dos índices: o plano virava SCAN × SCAN — 24.220 favorecidos × 25.218 sanções =
    # ~600 milhões de comparações por corrida, numa máquina de 2 vCPU. Dois dicionários (por
    # documento e por raiz de CNPJ) fazem o mesmo em segundos, e o resultado é idêntico porque a
    # regra de casamento é exatamente essa: documento igual, ou raiz igual quando os dois são CNPJ.
    achados = []
    por_doc: dict[str, list] = {}
    por_raiz: dict[str, list] = {}
    for s_ in con.execute("select cadastro, cpf_cnpj, categoria, orgao, data_inicio, data_fim "
                          "from sancoes_federais"):
        d = (s_["cpf_cnpj"] or "").strip()
        por_doc.setdefault(d, []).append(s_)
        if len(d) == 14:
            por_raiz.setdefault(d[:8], []).append(s_)

    rows, visto = [], set()
    for f_ in con.execute(
            "select f.codigo_emenda, f.documento_favorecido, f.nome_favorecido, f.valor, "
            "e.ano as ano_emenda from emenda_favorecidos f "
            "left join emendas e on e.codigo = f.codigo_emenda"):
        doc = (f_["documento_favorecido"] or "").strip()
        candidatas = por_doc.get(doc) or (por_raiz.get(doc[:8], []) if len(doc) == 14 else [])
        for s_ in candidatas:
            # mesma chave de dedup do `group by` anterior
            chave = (f_["codigo_emenda"], doc, s_["cadastro"], s_["cpf_cnpj"])
            if chave in visto:
                continue
            visto.add(chave)
            rows.append({**dict(f_), "cadastro": s_["cadastro"], "categoria": s_["categoria"],
                         "orgao": s_["orgao"], "doc_sancao": s_["cpf_cnpj"],
                         "data_inicio": s_["data_inicio"], "data_fim": s_["data_fim"]})

    def _ano(v) -> int | None:
        t = str(v or "")[:4]
        return int(t) if t.isdigit() else None

    for r in rows:
        exato = r["doc_sancao"] == r["documento_favorecido"]
        ano_e, ini, fim = _ano(r["ano_emenda"]), _ano(r["data_inicio"]), _ano(r["data_fim"])
        if ano_e is None or ini is None:
            vigencia, risco = "indeterminada", (7 if exato else 5)
        elif ini > ano_e:
            vigencia, risco = "posterior", 3
        elif fim is not None and fim < ano_e:
            vigencia, risco = "encerrada", 3
        else:
            vigencia, risco = "vigente", (9 if exato else 7)

        rotulo = {"vigente": "Favorecido sancionado",
                  "posterior": "Favorecido sancionado APÓS a emenda",
                  "encerrada": "Favorecido com sanção encerrada antes da emenda",
                  "indeterminada": "Favorecido sancionado (vigência não apurada)"}[vigencia]
        explica = {
            "vigente": ("Indício grave: a sanção já estava VIGENTE no ano da emenda"),
            "posterior": (f"NÃO é acusação: a sanção só começou em {ini}, "
                          f"{ini - (ano_e or ini)} ano(s) DEPOIS da emenda de {ano_e}. Serve de "
                          "contexto sobre o favorecido, não de irregularidade na emenda"),
            "encerrada": (f"NÃO é acusação: a sanção terminou em {fim}, antes da emenda de {ano_e}"),
            "indeterminada": ("Vigência não apurada — falta o ano da emenda ou a data da sanção; "
                              "INDISPONÍVEL, não confirmação"),
        }[vigencia]
        achados.append(_achado(
            "d3_favorecido_sancionado", risco,
            # a EMENDA no título: o mesmo favorecido sancionado em 60 emendas são 60 achados
            f"{rotulo} — {r['nome_favorecido']} (emenda {r['codigo_emenda']})",
            f"{explica}. Favorecido {r['nome_favorecido']} "
            f"(doc. {r['documento_favorecido']}) da emenda {r['codigo_emenda']} consta no "
            f"{r['cadastro']} ({r['categoria'] or 'sanção'}, órgão {r['orgao'] or 'n/d'}), "
            f"sanção de {r['data_inicio'] or 'data n/d'} a {r['data_fim'] or 'sem fim declarado'}"
            + ("" if exato else " — match pela RAIZ do CNPJ (filial/matriz), conferir")
            + f". Valor no documento: R$ {_brl(r['valor'])}. A régua é o ANO DA EMENDA: o "
            "`emenda_favorecidos` não guarda data de pagamento. "
            f"(fontes: API Portal da Transparência /emendas/documentos + sancoes_federais/CEIS)",
            {"cadastro": r["cadastro"], "doc": r["documento_favorecido"],
             "match_exato": exato, "vigencia_na_emenda": vigencia,
             "ano_emenda": ano_e, "sancao_inicio": r["data_inicio"], "sancao_fim": r["data_fim"]},
            r["codigo_emenda"]))
    return achados


# ── D4 — favorecido com sinais de fachada/fantasma ──────────────────────────
def _avaliar_cnpj_padrao(cnpj: str) -> dict | None:
    """Liga no motor da casa (empresa_fantasma, 8 sinais) via sessão SQLAlchemy."""
    try:
        from compliance_agent.database.models import get_session
        from compliance_agent.empresa_fantasma import avaliar_perfil, perfil_do_cnpj
        session = get_session()
        try:
            perfil = perfil_do_cnpj(session, cnpj)
            return avaliar_perfil(perfil) if perfil else None
        finally:
            session.close()
    except Exception as e:
        logger.warning("d4: motor empresa_fantasma INDISPONÍVEL p/ %s: %s", cnpj, e)
        return None


def d4_favorecido_fantasma(con, avaliar_cnpj=None, valor_minimo: float = D4_VALOR_MINIMO,
                           score_minimo: int = D4_SCORE_MINIMO, top: int = 200) -> list[dict]:
    avaliar_cnpj = avaliar_cnpj or _avaliar_cnpj_padrao
    achados = []
    rows = con.execute("""
        select documento_favorecido, nome_favorecido,
               sum(valor) as total, count(distinct codigo_emenda) as n_emendas,
               min(codigo_emenda) as uma_emenda
        from emenda_favorecidos
        where length(documento_favorecido) = 14
        group by 1, 2 having total >= ? order by total desc limit ?""",
        (valor_minimo, top)).fetchall()
    for r in rows:
        if _ENTE_PUBLICO.search(r["nome_favorecido"] or ""):
            continue        # fundo/prefeitura recebe por desenho legal — não é fachada
        res = avaliar_cnpj(r["documento_favorecido"])
        if not res or (res.get("score") or 0) < score_minimo:
            continue
        sinais = ", ".join(s.get("id", "?") for s in res.get("sinais", [])) or "n/d"
        risco = min(10, 4 + round((res["score"] / 100) * 5))
        achados.append(_achado(
            "d4_favorecido_fantasma", risco,
            f"Sinais de fachada — {r['nome_favorecido']}",
            f"Indício de favorecido sem substância: {r['nome_favorecido']} "
            f"(CNPJ {r['documento_favorecido']}) recebeu R$ {_brl(r['total'])} por "
            f"{r['n_emendas']} emenda(s) e soma score {res['score']}/100 no detector "
            f"determinístico de fachada (sinais: {sinais}). Triagem: manda verificar "
            f"in loco, não acusa. (fontes: Portal da Transparência + Receita/QSA local)",
            {"cnpj": r["documento_favorecido"], "score": res["score"],
             "sinais": res.get("sinais", []), "total": r["total"]}, r["uma_emenda"]))
    return achados


# ── D5 — retroalimentação eleitoral (doador ∈ QSA do favorecido) ────────────
def d5_retroalimentacao_eleitoral(con) -> list[dict]:
    con.create_function("jfn_norm", 1, norm_nome)
    achados = []
    rows = con.execute("""
        select e.codigo, e.autor_raw, e.autor_norm,
               f.documento_favorecido, f.nome_favorecido,
               s.nome_socio, s.doc_socio,
               d.nome_doador, d.cpf_cnpj_doador, d.valor as doacao, d.ano_eleicao,
               case when d.cpf_cnpj_doador != '' and d.cpf_cnpj_doador = s.doc_socio
                    then 'CPF' else 'NOME' end as match_tipo,
               sum(f.valor) as valor_emenda
        from emendas e
        join emenda_favorecidos f on f.codigo_emenda = e.codigo
        join socios_receita s
          on length(f.documento_favorecido) = 14
         and s.cnpj_basico = substr(f.documento_favorecido, 1, 8)
        join doacoes_eleitorais d
          on jfn_norm(d.nome_candidato) = e.autor_norm
         and ((d.cpf_cnpj_doador != '' and d.cpf_cnpj_doador = s.doc_socio)
              or jfn_norm(d.nome_doador) = s.nome_norm)
        group by e.codigo, f.documento_favorecido, s.nome_socio, d.cpf_cnpj_doador,
                 d.ano_eleicao, match_tipo""").fetchall()
    for r in rows:
        forte = r["match_tipo"] == "CPF"
        risco = 8 if forte else 4
        aviso = ("" if forte else
                 " Match apenas por NOME normalizado — homônimo é possível; "
                 "confirmar CPF antes de qualquer uso.")
        achados.append(_achado(
            "d5_retroalimentacao_eleitoral", risco,
            f"Retroalimentação — sócio de {r['nome_favorecido']} doou para {r['autor_raw']}",
            f"Indício de retroalimentação eleitoral: {r['nome_socio']}, sócio do favorecido "
            f"{r['nome_favorecido']} (CNPJ {r['documento_favorecido']}, R$ "
            f"{_brl(r['valor_emenda'])} recebidos da emenda {r['codigo']}), doou R$ "
            f"{_brl(r['doacao'])} à campanha de {r['autor_raw']} em {r['ano_eleicao']} "
            f"(match por {r['match_tipo']}).{aviso} "
            f"(fontes: QSA Receita local + doações TSE local + Portal da Transparência)",
            {"match_tipo": r["match_tipo"], "socio": r["nome_socio"],
             "doacao": r["doacao"], "ano_eleicao": r["ano_eleicao"],
             "cnpj": r["documento_favorecido"]}, r["codigo"]))
    return achados


# ── D6 — empenho sem pagamento / restos cancelados ──────────────────────────
def d6_empenho_sem_pagamento(con, fracao: float = D6_FRACAO_CANCELADA) -> list[dict]:
    achados = []
    rows = con.execute("""
        select codigo, ano, autor_norm, localidade_gasto,
               empenhado, liquidado, pago, resto_cancelado
        from emendas
        where empenhado > 0 and pago = 0
          and resto_cancelado / empenhado > ?""", (fracao,)).fetchall()
    for r in rows:
        pct = r["resto_cancelado"] / r["empenhado"]
        risco = min(7, 3 + round(pct * 4))
        achados.append(_achado(
            "d6_empenho_sem_pagamento", risco,
            f"Empenho sem execução — emenda {r['codigo']}",
            f"Indício de anúncio sem execução: emenda {r['codigo']} ({r['ano']}, autor "
            f"{r['autor_norm']}, destino {r['localidade_gasto'] or 'n/d'}) teve R$ "
            f"{_brl(r['empenhado'])} empenhados, R$ {_brl(r['liquidado'])} liquidados e "
            f"R$ {_brl(r['pago'])} pagos, com R$ {_brl(r['resto_cancelado'])} "
            f"({pct:.0%}) de restos cancelados. Empenho não é pagamento. "
            f"(fonte: API Portal da Transparência, /emendas)",
            {"empenhado": r["empenhado"], "pago": r["pago"],
             "resto_cancelado": r["resto_cancelado"]}, r["codigo"]))
    return achados


# ── orquestração ─────────────────────────────────────────────────────────────
_DETECTORES = {
    "d1": d1_pix_impedida,
    "d2": d2_concentracao_autor,
    "d3": d3_favorecido_sancionado,
    "d4": d4_favorecido_fantasma,
    "d5": d5_retroalimentacao_eleitoral,
    "d6": d6_empenho_sem_pagamento,
}


def rodar_todas(con, gravar_alertas: bool = False) -> dict:
    """{"achados": [...] ordenados por risco, "cobertura": {dN: "ok: N achados"|"ERRO: ..."}}.
    Cobertura declarada sempre — detector que falhou é INDISPONÍVEL, não zero."""
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
        # Antes: INSERT cru a cada corrida, sem dedup e sem poda — 81,3% das 2.322 linhas de
        # alerta de emendas eram cópias de reexecução (a mesma ONG sancionada 60 vezes). A
        # persistência agora é a mesma dos dois lados, com as três regras num lugar só.
        from compliance_agent.alertas_persistencia import gravar as _gravar
        poda = _gravar(con, achados, cobertura, prefixo="emendas",
                       detectores=_DETECTORES, severidade=_sev)
        return {"achados": achados, "cobertura": cobertura, "poda": poda}
    return {"achados": achados, "cobertura": cobertura}
