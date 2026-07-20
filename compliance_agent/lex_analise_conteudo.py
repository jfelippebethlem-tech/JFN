# -*- coding: utf-8 -*-
"""Lex — análise de CONTEÚDO: texto do SEI, contratos TCE-RJ, dados de OB e LLM discursivo.

Extraído de lex.py (split 2026-07-06); comportamento idêntico (snapshot-tested).
"""
from __future__ import annotations

import os
import re

from compliance_agent.reporting.inteligencia import moeda
from compliance_agent.lex_redflags import (
    _RF, _eh_servico_continuo, _ramo_objeto,
)
from compliance_agent.lex_sei_leitura import (
    _bloqueio_rede, _eh_interface_sei, _texto_integra,
)

def _modalidade(low: str) -> str:
    for chave, rotulo in [
        ("pregão eletrônico", "Pregão eletrônico"), ("pregão", "Pregão"),
        ("concorrência", "Concorrência"), ("inexigibilidade", "Inexigibilidade"),
        ("dispensa de licitação", "Dispensa de licitação"), ("dispensa", "Dispensa"),
        ("credenciamento", "Credenciamento"), ("adesão", "Adesão a ata (carona)"),
        ("registro de preços", "Registro de preços"),
    ]:
        if chave in low:
            return rotulo
    return "—"


def _trecho(txt: str, gatilhos, janela: int = 340) -> str:
    """Excerpt em torno do 1º gatilho encontrado no texto real — para o parecer CITAR 'onde' (o trecho do
    documento que disparou o indício). Limpo p/ markdown. Vazio se nenhum gatilho aparece."""
    low = (txt or "").lower()
    pos = -1
    for g in gatilhos:
        p = low.find(g)
        if p >= 0:
            pos = p
            break
    if pos < 0:
        return ""
    ini = max(0, pos - janela // 4)
    fim = min(len(txt), pos + janela)
    ex = re.sub(r"\s+", " ", txt[ini:fim].replace("|", "/")).strip()
    return ("…" if ini > 0 else "") + ex + ("…" if fim < len(txt) else "")


# Termos que evidenciam OBJETO de bem/serviço (vs. um trecho monetário de despacho de execução).
_OBJ_BEM_SERVICO_KW = (
    "serviço", "servico", "serviços", "servicos", "fornecimento", "aquisição", "aquisicao", "contratação",
    "contratacao", "prestação", "prestacao", "locação", "locacao", "manutenção", "manutencao", "obra", "execução",
    "execucao", "material", "equipamento", "consultoria", "limpeza", "vigilância", "vigilancia", "transporte",
    "construção", "construcao", "reforma", "elaboração", "elaboracao", "implantação", "implantacao", "suporte",
    "licença", "licenca", "software", "mão de obra", "mao de obra",
)
# Trecho que é só VALOR/quantia (ex.: "no valor de R$68.000,00") — não é objeto contratual.
_OBJ_VALOR_RE = re.compile(r"^\s*(no\s+valor\s+de\s+)?r?\$?\s*[\d.,]+\s*$", re.I)


def _objeto_valido(cand: str) -> bool:
    """True se `cand` parece um OBJETO de bem/serviço (não um valor monetário/trecho de despacho de execução)."""
    c = (cand or "").strip()
    if len(c) < 12:
        return False
    low = c.lower()
    if _OBJ_VALOR_RE.match(low) or low.startswith("no valor de") or "valor de r$" in low[:18]:
        return False
    return any(k in low for k in _OBJ_BEM_SERVICO_KW)


def _analisar_conteudo_sei(integra: dict) -> tuple[list, dict]:
    """Red flags a partir do TEXTO REAL do processo. Retorna (achados, resumo)."""
    txt = _texto_integra(integra)
    low = txt.lower()
    achados: list[dict] = []
    modal = _modalidade(low)

    # Objeto contratual. Preferir o objeto ESTRUTURADO (dossiê/TCE-RJ) quando o leitor já o trouxe — é o objeto
    # do contrato, não um trecho de despacho. Só cair na heurística de regex se não houver estruturado.
    objeto = ""
    obj_estrut = (integra.get("objeto") or "").strip()
    if _objeto_valido(obj_estrut):
        objeto = obj_estrut[:180]
    else:
        # Documentos de execução (liquidação/empenho) trazem "Objeto: <valor R$…>" no corpo do despacho — NÃO é o
        # objeto contratual. Quando o texto é de liquidação/empenho, só aceitar a captura se contiver termo de
        # bem/serviço (não um valor monetário). Caso geral: 1ª ocorrência de 'objeto:' já basta.
        _exec = any(g in low for g in ("liquidação de despesa", "liquidacao de despesa", "nota de empenho",
                                       "nota de liquidação", "nota de liquidacao"))
        for m in re.finditer(r"objeto[:\s]+([A-Z0-9À-Ú][^\n.;]{15,180})", txt, re.I):
            cand = m.group(1).strip()
            if not _exec or _objeto_valido(cand):
                objeto = cand
                break

    if txt.strip():
        # R5 — contratação direta sem prova robusta de exclusividade/singularidade
        if "dispensa" in low or "inexigibil" in low:
            tem_just = any(k in low for k in [
                "exclusividade", "singular", "notória especialização", "notoria especializacao",
                "inviabilidade de competição", "inviabilidade de competicao", "art. 74", "artigo 74",
            ])
            achados.append({"rf": "R5", "grav": 2 if tem_just else 3,
                            "obs": f"O processo registra **{modal if modal != '—' else 'contratação direta'}**" +
                                   ("." if tem_just else
                                    " — no texto lido **não localizei** prova robusta de exclusividade/singularidade "
                                    "(art. 74 Lei 14.133/Art. 25 Lei 8.666).")})
        # R3 — sem pesquisa/cesta de preços visível
        if any(k in low for k in ["edital", "contrato", "termo de referência", "termo de referencia"]) and \
           not any(k in low for k in ["pesquisa de preç", "cesta de preç", "mapa de preç", "cotaç", "orçament"]):
            achados.append({"rf": "R3", "grav": 2,
                            "obs": "No texto lido **não localizei** pesquisa/cesta de preços (Acórdão 1875/2021-TCU) — "
                                   "verificar a instrução do ETP/valor estimado."})
        # R9 — aditivos
        n_adit = low.count("termo aditivo") + low.count("aditamento")
        if n_adit >= 2:
            achados.append({"rf": "R9", "grav": 2,
                            "obs": f"{n_adit} menções a termo aditivo/aditamento no processo — verificar se a soma "
                                   "respeita os limites de 25%/50% (arts. 125-126 Lei 14.133)."})
        # R7 — restrição/direcionamento por especificação
        if any(k in low for k in ["atestado de capacidade", "marca", "modelo "]) and "ou equivalente" not in low:
            achados.append({"rf": "R7", "grav": 2,
                            "obs": "Há exigências de habilitação/especificação (atestado/marca) sem a cláusula "
                                   "'ou equivalente' visível — verificar restrição à competitividade (art. 9º Lei 14.133)."})

    # B (qualidade): anexa o TRECHO real do documento + o nº do processo a cada achado, para o parecer
    # citar ONDE (o trecho que disparou o indício). Sem trecho → fica vazio (não inventa).
    _gat = {"R5": ["dispensa", "inexigibil"],
            "R3": ["edital", "termo de referência", "termo de referencia", "contrato"],
            "R9": ["termo aditivo", "aditamento"],
            "R7": ["atestado de capacidade", "marca", "modelo "]}
    for a in achados:
        a["numero_proc"] = integra.get("numero", "")
        a["trecho"] = _trecho(txt, _gat.get(a["rf"], []))

    # R15 — acatamento de pareceres (art. 53, dossiê mestre §4): auditoria determinística sobre os
    # docs da íntegra. IGNORADO = ressalva sem resposta + decisão tomada → grav 4; SILENTE/CONTRARIADO
    # motivado → grav 2 (registrar). Falha aqui nunca derruba a análise (achado é bônus).
    docs_aud = [{"ref": d.get("doc"), "tipo": d.get("doc"), "texto": d.get("conteudo")}
                for d in integra.get("conteudo_documentos") or []]
    if docs_aud:
        try:
            from compliance_agent.sei_recomendacoes import auditar_acatamento
            aud = auditar_acatamento(docs_aud)
            if aud["veredito"] == "IGNORADO_INDICIO":
                achados.append({"rf": "R15", "grav": 4,
                                "obs": f"**Acatamento de pareceres:** {aud['leitura']}"})
            elif aud["veredito"] in ("SILENTE", "CONTRARIADO_COM_MOTIVACAO"):
                achados.append({"rf": "R15", "grav": 2,
                                "obs": f"**Acatamento de pareceres ({aud['veredito']}):** {aud['leitura']}"})
        except Exception as exc:  # noqa: BLE001 — achado R15 é bônus, mas NUNCA mudo (catraca)
            import logging
            logging.getLogger(__name__).debug("auditar_acatamento falhou: %s", exc)

    resumo = {
        "numero": integra.get("numero", ""),
        "objeto": objeto,
        "modalidade": modal,
        "tipo": integra.get("tipo", "") or integra.get("title", ""),
        "n_docs": len(integra.get("documentos", []) or []),
        "n_docs_lidos": len(integra.get("conteudo_documentos", []) or []),
        "cnpjs": (integra.get("cnpjs", []) or [])[:8],
        "valores": (integra.get("valores", []) or [])[:8],
        "url": integra.get("url", ""),
        "lido": bool(txt.strip()),
        "de_cache": bool(integra.get("_de_cache") or integra.get("_cached_at")),
        "erro": integra.get("erro", "") or _bloqueio_rede(integra) or _eh_interface_sei(integra),
    }
    return achados, resumo


_SYS_DISCURSIVO = (
    "Voce e auditor de controle externo (TCU/TCE-RJ) redigindo um parecer. Para cada indicio, com base "
    "ESTRITAMENTE no TRECHO real do documento, escreva 2 a 4 frases de analise: (a) ONDE no documento o "
    "problema aparece (parafraseie/cite o trecho) e (b) POR QUE e um indicio — o MECANISMO concreto (ex.: "
    "'a exigencia de atestado X restringe porque elimina concorrentes que nao tem Y'). NAO invente fato "
    "fora do trecho; se o trecho nao bastar, diga objetivamente o que precisaria conferir. Indicio, nunca "
    "acusacao. Responda SOMENTE JSON."
)


def _json_lex(texto: str):
    """Extrai JSON (lista/obj) de uma resposta de LLM, tolerante a cercas ```json e texto ao redor."""
    import json
    t = (texto or "").strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(t)
    except Exception:
        m = re.search(r"(\[.*\]|\{.*\})", t, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                return None
        return None


def analise_discursiva(achados: list[dict], gerar=None) -> list[dict]:
    """Para cada achado COM trecho (= SEI lido), gera uma 'analise' DISCURSIVA (onde + por que, mecanismo)
    ancorada no texto real, numa UNICA chamada LLM (lote). Robusto: LLM caido/sem trecho → achado segue
    com a obs deterministica (degrada honesto, nao inventa). `gerar` injetavel p/ teste."""
    com = [(i, a) for i, a in enumerate(achados) if (a.get("trecho") or "").strip()]
    if not com:
        return achados
    if gerar is None:
        try:
            from compliance_agent.direcionamento_cerebro import gerar_sync
            gerar = lambda p, s="": gerar_sync(p, s, timeout=45.0)  # noqa: E731
        except Exception:
            return achados
    itens = "\n\n".join(
        f'{j}. INDICIO {a["rf"]} ({_RF.get(a["rf"], (a["rf"], ""))[0]}); processo {a.get("numero_proc", "")}\n'
        f'   TRECHO: "{(a.get("trecho") or "")[:600]}"'
        for j, (_i, a) in enumerate(com)
    )
    # MÉTODO PERICIAL COMPARTILHADO — Lex aprende as mesmas lições do Hermes (memória `metodo`).
    metodo = ""
    try:
        from compliance_agent.llm.memoria import lembrar
        regras = lembrar("metodo")[:8]
        if regras:
            metodo = ("MÉTODO PERICIAL (aplique):\n"
                      + "\n".join(f"- {r['valor'][:180]}" for r in regras) + "\n\n")
    except Exception:
        metodo = ""
    prompt = (metodo + 'Analise cada indicio abaixo. Responda SOMENTE JSON: lista de '
              '{"i":<indice>,"analise":"2 a 4 frases citando o trecho e explicando o mecanismo"}.\n\n' + itens)
    try:
        d = _json_lex(gerar(prompt, _SYS_DISCURSIVO))
    except Exception:
        d = None
    por: dict = {}
    if isinstance(d, list):
        for x in d:
            try:
                por[int(x["i"])] = str(x.get("analise", "")).strip()
            except Exception:
                pass
    for j, (_i, a) in enumerate(com):
        if por.get(j):
            a["analise"] = por[j]
    return achados


def analisar_texto_edital(texto: str, numero: str = "", url: str = "") -> dict:
    """API pública (Onda 2c): roda os red flags R3/R5/R7/R9/R12 sobre o texto de um
    edital/TR (ex.: baixado do PNCP) reusando o mesmo motor do SEI (`_analisar_conteudo_sei`).

    Retorna {achados:[{rf,grav,obs}], resumo:{...}, lido:bool}. Honesto: indício, nunca
    acusação; se o texto vier vazio (download/extração falhou), `lido=False` e achados=[]."""
    integra = {"texto": texto or "", "numero": numero, "url": url,
               "conteudo_documentos": [], "documentos": []}
    achados, resumo = _analisar_conteudo_sei(integra)
    return {"achados": _merge_achados(achados), "resumo": resumo, "lido": bool((texto or "").strip())}


def _merge_achados(lst: list[dict]) -> list[dict]:
    """Funde achados por red flag (mantém maior gravidade, concatena observações)."""
    por: dict = {}
    for a in lst:
        k = a["rf"]
        if k not in por:
            por[k] = dict(a)
        else:
            if a["grav"] > por[k]["grav"]:
                por[k]["grav"] = a["grav"]
            if a["obs"] not in por[k]["obs"]:
                por[k]["obs"] += " " + a["obs"]
    return sorted(por.values(), key=lambda x: -x["grav"])


# ── Análise dos contratos/compras do TCE-RJ (Dados Abertos — não depende do SEI) ──

def _analisar_contratos_tcerj(itens: list[dict]) -> tuple[list, dict]:
    """Red flags a partir dos contratos/compras diretas oficiais do TCE-RJ. Retorna (achados, resumo).

    Esta é a fonte que CONTORNA o bloqueio de WAF do SEI: traz objeto, critério de julgamento, valores e —
    sobretudo — o **EnquadramentoLegal** das compras diretas (dispensa/inexigibilidade) direto da API pública."""
    achados: list[dict] = []
    contratos = [i for i in itens if i.get("_tipo") == "contrato"]
    compras = [i for i in itens if i.get("_tipo") == "compra_direta"]

    soma_contr = sum(c.get("valor_contrato") or 0 for c in contratos)
    soma_compras = sum(c.get("valor") or 0 for c in compras)

    # R5 — contratações diretas (dispensa/inexigibilidade) registradas no TCE-RJ
    diretas = [c for c in compras if any(
        k in ((c.get("afastamento") or "") + " " + (c.get("enquadramento_legal") or "")).lower()
        for k in ["dispensa", "inexigibil"])]
    if diretas:
        total_d = sum(c.get("valor") or 0 for c in diretas)
        grav = 3 if len(diretas) >= 5 else 2
        achados.append({"rf": "R5", "grav": grav,
                        "obs": f"O TCE-RJ registra **{len(diretas)} contratação(ões) direta(s)** (dispensa/"
                               f"inexigibilidade) deste fornecedor, somando R$ {moeda(total_d)} — verificar o "
                               "enquadramento legal e a regularidade da fundamentação (art. 74/75 Lei 14.133/Art. 24-25 Lei 8.666)."})

    # R2 — FRACIONAMENTO (teste TCU, Ac. 1.620/2010-Pleno): múltiplas DISPENSAS de objeto de MESMA NATUREZA, na
    # MESMA unidade gestora, no MESMO exercício, cada uma sob o teto de dispensa, somando ACIMA dele (art. 75 §1º
    # Lei 14.133). NÃO é fracionamento: várias OBs de um mesmo contrato (parcelas mensais/medição/pagamento parcial),
    # nem atuar em vários órgãos, nem a pluralidade de contratos de serviço contínuo. Agrupa por (ano, UG, ramo).
    from collections import defaultdict
    # dispensa por valor — art. 75, II, Lei 14.133 (serviços/compras). Reajustado por decreto anual:
    # override sem tocar código via LEX_TETO_DISPENSA no .env (valor de referência 2024/2025 = 59.906,02).
    _TETO_DISP = float(os.environ.get("LEX_TETO_DISPENSA", "") or 59906.02)
    grupos = defaultdict(list)
    for c in diretas:
        grupos[(c.get("ano_processo"), (c.get("unidade") or "")[:40], _ramo_objeto(c.get("objeto")))].append(c)
    candidatos = []
    for (ano, unid, ramo), itens in grupos.items():
        sob_teto = [i for i in itens if 0 < (i.get("valor") or 0) <= _TETO_DISP]
        soma = sum(i.get("valor") or 0 for i in itens)
        if len(sob_teto) >= 2 and soma > _TETO_DISP:   # ≥2 dispensas da mesma natureza que, somadas, furam o teto
            candidatos.append((ano, unid, ramo, len(sob_teto), soma))
    if candidatos:
        ano, unid, ramo, n, soma = max(candidatos, key=lambda x: x[4])
        achados.append({"rf": "R2", "grav": 3,
                        "obs": f"**{n} dispensas** de objeto de mesma natureza (**{ramo}**) na unidade **{unid}** no "
                               f"exercício {ano}, cada uma sob o teto de dispensa (≈R$ {moeda(_TETO_DISP)}) mas somando "
                               f"R$ {moeda(soma)} — indício de **FRACIONAMENTO** (substituição da licitação obrigatória "
                               "por múltiplas dispensas do mesmo objeto; art. 75 §1º Lei 14.133; Ac. 1.620/2010-TCU-"
                               "Pleno). Diligência: confirmar identidade de objeto/natureza e somatório no exercício."})
    elif diretas:
        # há dispensas, mas SEM o padrão de fracionamento — registrar a leitura correta (evita falso achado)
        achados.append({"rf": "R2", "grav": 1,
                        "obs": "As contratações diretas registradas **não** apresentam o padrão de fracionamento "
                               "(múltiplas dispensas do MESMO objeto/natureza, na mesma unidade e exercício, somando "
                               "acima do teto). Pluralidade de OBs (parcelas mensais/medição de um contrato) e atuação "
                               "em vários órgãos **não** caracterizam fracionamento — verificar apenas o enquadramento "
                               "de cada dispensa (art. 75 Lei 14.133)."})

    # R9 — execução acima do contratado (valor pago > contrato + 25%, limite de aditivo)
    for c in contratos:
        vc, vp = c.get("valor_contrato") or 0, c.get("valor_pago") or 0
        if vc > 0 and vp > vc * 1.25:
            achados.append({"rf": "R9", "grav": 2,
                            "obs": f"Contrato {c.get('processo')}: pago R$ {moeda(vp)} sobre valor contratado "
                                   f"R$ {moeda(vc)} (+{((vp-vc)/vc*100):.0f}%) — verificar aditivos e o limite de "
                                   "25%/50% (arts. 125-126 Lei 14.133)."})
            break  # um exemplo basta para o indício

    resumo = {
        "n_contratos": len(contratos), "soma_contratos": soma_contr,
        "n_compras_diretas": len(compras), "soma_compras": soma_compras,
        "n_diretas_dispensa": len(diretas),
        "contratos": contratos[:15], "compras": compras[:15],
    }
    return achados, resumo


# ── Detecção data-driven (carteira de pagamentos) ─────────────────────────────

def _detectar(ctx: dict) -> list[dict]:
    """Indícios a partir dos dados financeiros (OBs). Cada item: {rf, obs, grav(1-5)}."""
    p = ctx.get("pagamentos") or {}
    achados = []
    if not p.get("tem_dados"):
        return achados
    # Serviço CONTÍNUO (limpeza/vigilância/mão de obra): a escalada de faturamento é, em regra, legítima
    # (renovações/aditivos de contrato plurianual). Calibra o R12 (crescimento) como o R2 já trata o fracionamento.
    emp = (ctx.get("enriq", {}).get("dados") or {}).get("empresa") or {}
    continuo = _eh_servico_continuo([emp.get("cnae_principal"), emp.get("atividade"), ctx.get("nome")])
    hhi = p.get("hhi", {})
    top = hhi.get("top_share", 0) or 0
    org_top = next(iter(p.get("por_orgao_geral", {})), "—")
    if top >= 60:
        achados.append({"rf": "R8", "grav": 4,
                        "obs": f"{top:.1f}% do valor pago concentrado em um único órgão (**{org_top}**) — "
                               "concentração extrema para um prestador de serviços."})
    elif top >= 40:
        achados.append({"rf": "R8", "grav": 3, "obs": f"Concentração relevante ({top:.1f}%) em **{org_top}**."})
    anos = p.get("anos", [])
    if len(anos) >= 2:
        t0 = p["por_ano"][anos[0]]["total"] or 0
        t1 = p["por_ano"][anos[-1]]["total"] or 0
        if t0 > 0 and t1 > t0 * 3:
            pct = (t1 - t0) / t0 * 100
            if continuo:  # serviço contínuo: escalada legítima a justificar — sem rotular 'fachada' nem grav alto
                achados.append({"rf": "R12", "grav": 2,
                                "obs": f"**Escalada de faturamento a justificar:** pagamentos de R$ {moeda(t0)} "
                                       f"({anos[0]}) para R$ {moeda(t1)} ({anos[-1]}) — {pct:+.0f}%. Em serviço contínuo, "
                                       "crescimento por renovação/aditivo de contrato plurianual é comum — verificar o "
                                       "lastro contratual (aditivos/postos de trabalho), sem presumir planejamento de fachada."})
            else:
                achados.append({"rf": "R12", "grav": 3,
                                "obs": f"Crescimento abrupto dos pagamentos de R$ {moeda(t0)} ({anos[0]}) para "
                                       f"R$ {moeda(t1)} ({anos[-1]}) — {pct:+.0f}%."})
    zeros = sum(1 for a in anos for ln in p["por_ano"][a]["linhas"] if ln.get("valor") == 0)
    if zeros >= 3:
        achados.append({"rf": "R10", "grav": 2,
                        "obs": f"{zeros} ordens bancárias de valor R$ 0,00 (estornos/regularizações) — verificar a regularidade da liquidação."})
    # (Removido o antigo R2 baseado em nº de OBs/órgãos: pluralidade de OBs = parcelas de um contrato (mensal/
    #  medição/parcial) e atuação em vários órgãos NÃO são fracionamento. O fracionamento real é testado sobre as
    #  DISPENSAS do TCE-RJ por (ano, UG, mesma natureza) em _analisar_contratos_tcerj.)
    if ctx.get("risco") == "ALTO":
        achados.append({"rf": "R8", "grav": 2, "obs": f"Rating de risco corporativo ALTO (score {ctx.get('score')}/100) — diligência sobre quadro societário/vínculos."})
    return achados


