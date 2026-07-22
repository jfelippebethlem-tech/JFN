# -*- coding: utf-8 -*-
"""Análise: cardinalidade, fatores/red flags, parecer raciocinado, anomalias, troca de controle — extraído de inteligencia.py (split 2026-07-06).
Comportamento idêntico; rede de segurança: tools/inteligencia_snapshot_check.py + tests/test_inteligencia_snapshot.py.
"""
from __future__ import annotations

import logging
import re
import sqlite3

from compliance_agent.reporting.intel_base import _DB, moeda, so_digitos
from compliance_agent.reporting.intel_dados import _crescimento
from compliance_agent.reporting.intel_base import _num_brl

logger = logging.getLogger(__name__)

_NOTA_CARDINALIDADE = (
    "**Nota conceitual (cadeia da despesa):** a **OB (Ordem Bancária) é o pagamento** — a verdade financeira, "
    "porém **uma parcela**, não um contrato. Um **contrato** gera **várias OBs** (parcelas/medições/aditivos); "
    "um **processo SEI** (licitação ou **Registro de Preços/SRP**) pode gerar **vários contratos**, **aditivos** "
    "e **muitas OBs**. Portanto **nº de OBs ≠ nº de contratos ≠ nº de processos** — os contadores abaixo são "
    "distintos e honestos quanto à cobertura (a vinculação OB→processo só existe onde o SIAFE/SEI a preencheu)."
)


def cardinalidade_contratual(cnpj: str) -> dict:
    """Relação HONESTA OB × processo SEI × contrato p/ um fornecedor (raiz). NÃO equipara níveis.

    {n_obs, n_obs_com_processo, n_processos, cobertura_processo (0..1), n_contratos, _nota}. OB=pagamento;
    um contrato→várias OBs; um processo/SRP→vários contratos+aditivos. cobertura_processo = fração de OBs com
    processo vinculado (o resto é INDISPONÍVEL, não 'sem processo')."""
    out = {"n_obs": 0, "n_obs_com_processo": 0, "n_processos": 0, "cobertura_processo": 0.0,
           "n_contratos": 0, "_nota": ""}
    if not _DB.exists():
        return out
    raiz = so_digitos(cnpj)[:8]
    con = sqlite3.connect(_DB)
    try:
        row = con.execute(
            "SELECT COUNT(*), "
            "  SUM(CASE WHEN (numero_processo IS NOT NULL AND numero_processo!='') "
            "        OR (numero_sei IS NOT NULL AND numero_sei!='') THEN 1 ELSE 0 END), "
            "  COUNT(DISTINCT CASE WHEN numero_processo!='' THEN numero_processo "
            "                      WHEN numero_sei!='' THEN numero_sei END) "
            "FROM ordens_bancarias WHERE favorecido_cpf LIKE ?", (f"{raiz}%",)).fetchone()
        out["n_obs"] = int(row[0] or 0)
        out["n_obs_com_processo"] = int(row[1] or 0)
        out["n_processos"] = int(row[2] or 0)
        try:
            emps = con.execute("SELECT id FROM empresas WHERE cnpj LIKE ?", (f"{raiz}%",)).fetchall()
            if emps:
                ids = [e[0] for e in emps]
                out["n_contratos"] = int(con.execute(
                    "SELECT COUNT(*) FROM contratos WHERE empresa_id IN (%s)" % ",".join("?" * len(ids)),
                    ids).fetchone()[0] or 0)
        except sqlite3.OperationalError:
            pass
    finally:
        con.close()
    out["cobertura_processo"] = round(out["n_obs_com_processo"] / out["n_obs"], 3) if out["n_obs"] else 0.0
    return out


def _frase_cardinalidade(card: dict) -> str:
    """Uma frase honesta com os 3 contadores distintos (OB/processo/contrato) + cobertura."""
    if not card or not card.get("n_obs"):
        return ""
    n_obs, n_proc, n_contr = card["n_obs"], card["n_processos"], card["n_contratos"]
    cob = card.get("cobertura_processo", 0.0)
    partes = [f"{n_obs} OBs (pagamentos)"]
    if n_proc:
        cob_txt = f", cobertura {cob*100:.0f}%" if cob < 0.99 else ""
        partes.append(f"vinculadas a {n_proc} processo(s) SEI distinto(s){cob_txt}")
    if n_contr:
        partes.append(f"{n_contr} contrato(s) na carteira oficial (SIAFE)")
    return ("**Cardinalidade (OB ≠ contrato):** " + "; ".join(partes) +
            ". Um contrato gera várias OBs; um processo/SRP pode gerar vários contratos e aditivos.")


def _resumo_executivo(ctx: dict) -> str:
    p = ctx["pagamentos"]
    linhas = [f"{ctx['nome']} (CNPJ {ctx['cnpj_fmt']})"]
    if p["tem_dados"]:
        anos_txt = ", ".join(f"{a}: R$ {moeda(p['por_ano'][a]['total'])}" for a in p["anos"])
        linhas.append(f"Pagamentos (OBs) — {anos_txt}.")
        linhas.append(f"Total pago no período: R$ {moeda(p['total_geral'])} em {p['n_geral']} OBs, "
                      f"{len(p['por_orgao_geral'])} órgãos. Concentração (HHI): {p['hhi'].get('indice')} "
                      f"({p['hhi'].get('nivel')}; maior órgão = {p['hhi'].get('top_share')}%).")
    else:
        linhas.append("Sem OBs pagas registradas na base local para este CNPJ.")
    frase_card = _frase_cardinalidade(ctx.get("cardinalidade") or {})
    if frase_card:
        linhas.append(frase_card)
    elif ctx["contratos"]["n"]:
        linhas.append(f"Carteira de contratos (SIAFE): {ctx['contratos']['n']} contratos, "
                      f"R$ {moeda(ctx['contratos']['total'])}.")
    if ctx["risco"] not in ("—", None):
        linhas.append(f"Rating de risco corporativo: {ctx['risco']} (score {ctx['score']}/100).")
    return " ".join(linhas)


_FEAT_ANOM = {"log_valor": "valor atípico", "valor": "valor atípico", "forn_freq": "frequência do fornecedor",
              "forn_tot": "volume do fornecedor", "ug_freq": "frequência na UG", "dow": "dia da semana",
              "mes": "mês", "data": "data", "ano": "ano"}


def _anomalias_fornecedor(cnpj: str, limiar: float = 0.70, limite: int = 10) -> dict:
    """M2 — OBs do fornecedor com score alto no modelo de detecção de anomalias (`ob_anomaly` ⋈ OBs)."""
    cnpj = so_digitos(cnpj)
    out = {"ok": False, "n_obs": 0, "n_anomalas": 0, "itens": [], "modelo": ""}
    if len(cnpj) != 14:
        return out
    try:
        con = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True)
        try:
            tot = con.execute("SELECT COUNT(*) FROM ob_anomaly a JOIN ordens_bancarias o ON o.id=a.ob_id "
                              "WHERE o.favorecido_cpf=?", (cnpj,)).fetchone()[0]
            if not tot:
                return out
            nan = con.execute("SELECT COUNT(*) FROM ob_anomaly a JOIN ordens_bancarias o ON o.id=a.ob_id "
                              "WHERE o.favorecido_cpf=? AND a.score>=?", (cnpj, limiar)).fetchone()[0]
            rows = con.execute(
                "SELECT a.score, a.top_features, o.numero_ob, o.valor, o.data_pagamento, a.modelo_versao "
                "FROM ob_anomaly a JOIN ordens_bancarias o ON o.id=a.ob_id "
                "WHERE o.favorecido_cpf=? AND a.score>=? ORDER BY a.score DESC LIMIT ?",
                (cnpj, limiar, limite)).fetchall()
        finally:
            con.close()
        out.update(ok=True, n_obs=tot, n_anomalas=nan, modelo=(rows[0][5] if rows else ""),
                   itens=[{"score": r[0], "feats": r[1], "ob": r[2], "valor": r[3], "data": r[4]} for r in rows])
        return out
    except Exception as exc:  # noqa: BLE001
        out["_nota"] = str(exc)[:160]
        return out


def _natureza_sem_fins(cnpj: str) -> dict:
    """Natureza jurídica SEM FINS LUCRATIVOS ('3xxx') do fornecedor, ANCORADA NO DUMP LOCAL da Receita
    (`empresas_min`) — funciona mesmo com o enriquecimento RFB INDISPONÍVEL (essa é a vantagem: o dump é
    local). Espelha o modelo de `_anomalias_fornecedor`/`anomalia_receita._sem_fins_lucrativos`, reusando
    `_NATUREZA_3`/`_ressalva_nome`/`_TOKENS_RESSALVA` (não duplica o mapa). Calibração conservadora idêntica
    à do órgão: '3xxx' COM token de ensino/pesquisa/estágio → `ressalva=True` (CIEE/FGV; não é red flag);
    SEM ressalva → indício 🟡 (OS/associação/fundação como fornecedor comum). Read-only; degrada honesto."""
    from compliance_agent.reporting.anomalia_receita import _NATUREZA_3, _ressalva_nome  # noqa: F401
    cnpj = so_digitos(cnpj)
    out = {"ok": False, "sem_fins": False}
    if len(cnpj) != 8 and len(cnpj) != 14:
        return out
    try:
        con = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True)
        try:
            row = con.execute(
                "SELECT razao_social, natureza_cod FROM empresas_min WHERE cnpj_basico = substr(?,1,8)",
                (cnpj,)).fetchone()
        finally:
            con.close()
    except Exception as exc:  # noqa: BLE001
        out["_nota"] = str(exc)[:160]
        return out
    if not row:
        return out
    razao, nat = row[0], (row[1] or "")
    out["ok"] = True
    if not str(nat).startswith("3"):
        return out
    ressalva = _ressalva_nome(razao or "")
    out.update(
        sem_fins=True, natureza_cod=nat, natureza_txt=_NATUREZA_3.get(nat, f"Natureza {nat}"),
        razao=razao, ressalva=ressalva,
    )
    return out


def _fatores_risco(ctx: dict) -> list[tuple]:
    p = ctx["pagamentos"]
    fatores = []
    top = p.get("hhi", {}).get("top_share", 0) if p["tem_dados"] else 0
    if top >= 60:
        fatores.append(("Concentração de pagamentos em órgão único", 6, 7))
    elif top >= 40:
        fatores.append(("Concentração relevante de pagamentos por órgão", 4, 6))
    else:
        fatores.append(("Dispersão de pagamentos entre órgãos", 2, 4))
    if ctx["risco"] == "ALTO":
        fatores.append(("Sinais de risco corporativo (perfil/rede)", 6, 6))
    elif ctx["risco"] == "MÉDIO":
        fatores.append(("Sinais de risco corporativo (perfil/rede)", 4, 5))
    # crescimento abrupto ano a ano
    if p["tem_dados"] and len(p["anos"]) >= 2:
        a0, a1 = p["anos"][0], p["anos"][-1]
        t0 = p["por_ano"][a0]["total"] or 1
        t1 = p["por_ano"][a1]["total"]
        if t1 > t0 * 3:
            fatores.append((f"Crescimento abrupto de pagamentos ({a0}→{a1})", 5, 6))
    # emendas parlamentares: recurso público por indicação concentrado numa OSC = captura política
    em = ctx.get("emendas") or {}
    if em.get("tem_dados"):
        na = em.get("n_autores", 0)
        if na >= 5:
            fatores.append((f"Operador de emendas: {na} padrinhos parlamentares "
                            f"(R$ {moeda(em.get('total', 0))})", 7, 7))
        elif na >= 2:
            fatores.append((f"Recurso público por indicação parlamentar ({na} autores)", 5, 6))
        else:
            fatores.append(("Financiamento por emenda parlamentar", 3, 5))
    return fatores or [("Risco base", 2, 3)]


def _gazetas_lookup(nome: str, cnpj: str) -> dict:
    """Diários oficiais municipais (Querido Diário, keyless). Best-effort; INDISPONÍVEL honesto."""
    try:
        from compliance_agent.providers import lookup
        q = f'"{nome}"' if nome and not nome.replace(".", "").replace("/", "").isdigit() else cnpj
        r = lookup("gazettes", querystring=q, size=8)
        return r.dados if r.ok else {"_indisponivel": r.erro or r.estado}
    except Exception as e:  # noqa: BLE001
        return {"_indisponivel": str(e)[:60]}


def _fatos_para_raciocinio(ctx: dict) -> str:
    """Compila os FATOS já coletados (sem inventar) p/ a análise raciocinada conectar."""
    p = ctx["pagamentos"]
    L: list[str] = [f"Fornecedor: {ctx['nome']} (CNPJ {ctx['cnpj_fmt']}). "
                    f"Rating interno de risco: {ctx.get('risco')} (score {ctx.get('score')}/100)."]
    if p.get("tem_dados"):
        hhi = p["hhi"]
        org = next(iter(p["por_orgao_geral"]), "—")
        L.append(f"Pagamentos (OB): R$ {moeda(p['total_geral'])} em {p['n_geral']} ordens bancárias, "
                 f"{len(p['por_orgao_geral'])} unidades gestoras; maior concentração "
                 f"{hhi.get('top_share', 0):.1f}% em '{org}' (HHI {hhi.get('indice')}, nível {hhi.get('nivel')}).")
        zeros = sum(1 for a in p["anos"] for ln in p["por_ano"][a]["linhas"] if ln["valor"] == 0)
        if zeros:
            L.append(f"{zeros} OB(s) de valor zero (estornos/regularizações).")
    else:
        L.append("Sem Ordens Bancárias na base local para este CNPJ.")
    cz = ctx.get("cruzamento") or {}
    if cz.get("coendereco"):
        L.append(f"Cruzamento: {len(cz['coendereco'])} outro(s) fornecedor(es) do Estado no MESMO endereço do alvo.")
    rel = cz.get("relacionados") or []
    if rel:
        me = sum(1 for r in rel if r.get("mesmo_endereco"))
        L.append(f"Cruzamento: {len(rel)} empresa(s) com SÓCIO em comum com o alvo"
                 + (f" ({me} também no mesmo endereço)" if me else "") + ".")
    if (cz.get("obs_sei") or {}).get("n_sei"):
        L.append(f"Processos SEI vinculados ao alvo: {cz['obs_sei']['n_sei']}.")
    cr = ctx.get("conflito_rede") or {}
    n_conf = (cr.get("n") or len(cr.get("rede") or [])) if isinstance(cr, dict) else 0
    if n_conf:
        L.append(f"Conflito doador↔contrato (TSE): {n_conf} vínculo(s) entre doação eleitoral e o alvo/sócios.")
    sanc = (ctx["enriq"].get("dados") or {}).get("sancoes") if ctx.get("enriq", {}).get("ok") else None
    if isinstance(sanc, dict) and sanc.get("verificado"):
        n = sanc.get("n_sancoes", 0)
        L.append(f"Sanções CEIS/CNEP (consulta verificada): {('SIM — ' + str(n) + ' registro(s)') if n else 'nada localizado'}.")
    gz = ctx.get("gazetas") or {}
    if gz.get("total"):
        muns = ", ".join(dict.fromkeys(f"{i['municipio']}/{i['uf']}" for i in (gz.get("itens") or [])[:5] if i.get("municipio")))
        L.append(f"Diários oficiais (Querido Diário): {gz['total']} menção(ões) ao nome em diários municipais; ex.: {muns}.")
    emp_r = (ctx["enriq"].get("dados") or {}).get("empresa") if ctx.get("enriq", {}).get("ok") else None
    if emp_r and p.get("tem_dados"):
        _cap = _num_brl(emp_r.get("capital_social"))
        if _cap and _cap > 0 and p["total_geral"] >= 50 * _cap and p["total_geral"] > 500_000:
            L.append(f"Capital social ({moeda(_cap)}) é {p['total_geral'] / _cap:,.0f}× menor que o recebido "
                     f"({moeda(p['total_geral'])}) — indício de subcapitalização típica de fachada (H-CAPITAL).")
    rodf = ctx.get("rodizio_forn") or {}
    if rodf.get("aneis"):
        _ugs = ", ".join(str(a["ug"]) for a in rodf["aneis"])
        L.append(f"Rodízio de vencedores (bid rotation/cartel): este fornecedor é campeão de anel em "
                 f"{len(rodf['aneis'])} UG(s) ({_ugs}) — indício de conluio/cartel a corroborar (lista de "
                 "licitantes no SEI/PNCP; sócios em comum entre os campeões).")
    bs = ctx.get("beneficios_socios") or _beneficios_socios(ctx.get("cnpj", ""))
    if bs.get("n_verificados"):
        if bs.get("n_com_beneficio"):
            L.append(f"Benefício social de subsistência (laranja): {bs.get('n_pessoas_beneficio', 0)} sócio(s)/"
                     f"administrador(es) verificado(s) recebe(m) benefício (de {bs['n_verificados']} verificados) — "
                     "indício de interposição de pessoas (testa-de-ferro), a confirmar no contrato social/SEI.")
        else:
            L.append(f"Benefício social dos sócios/administradores: {bs['n_verificados']} verificado(s), nenhum "
                     "recebe benefício de subsistência (indício de laranja afastado para os verificados).")
    if p.get("tem_dados"):
        try:
            from compliance_agent.analysis.benford import benford
            _vals = [ln.get("valor") or 0 for a in p["anos"] for ln in p["por_ano"][a].get("linhas", [])
                     if (ln.get("valor") or 0) > 0]
            _bf = benford(_vals)
            _d1 = _bf.get("primeiro_digito") or {}
            if _bf.get("suficiente") and "NÃO CONFORM" in (_d1.get("faixa_nigrini", "") or "").upper():
                L.append(f"Lei de Benford (1º dígito, n={_d1.get('n')}): NÃO conformidade (MAD {_d1.get('mad')}) — "
                         "indício estatístico de fracionamento/valores fabricados a verificar nos documentos.")
        except Exception as exc:  # noqa: BLE001
            logger.debug("parecer sem Benford: %s", exc)
        _an = ctx.get("anomalias") or _anomalias_fornecedor(ctx.get("cnpj", ""))
        if _an.get("ok") and _an.get("n_anomalas"):
            L.append(f"Modelo de anomalias: {_an['n_anomalas']} de {_an['n_obs']} OBs do fornecedor com score alto "
                     "(≥0,70) — pagamentos atípicos a inspecionar (lastro/contrato/medição).")
    try:
        rf = _red_flags(ctx)
        if rf:
            L.append("Red flags automáticos disparados: " + "; ".join(t for t, _, _ in rf[:6]) + ".")
    except Exception as exc:  # noqa: BLE001
        logger.debug("parecer sem red flags: %s", exc)
    return "\n".join("- " + x for x in L)


def _normaliza_raciocinio(txt: str) -> str:
    """Limpa a saída do LLM: tira cercas de código e converte JSON/dict (mesmo com aspas simples) em bullets."""
    import ast
    import json as _json
    t = (txt or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", t).strip()

    # remove marcador de bullet já presente na string (o LLM às vezes embute "- "/"• "/"* " no próprio
    # item do JSON) p/ não duplicar quando re-prefixamos com "- " → evita o "- -" no MD (§9).
    def _desmarca(s: str) -> str:
        return re.sub(r"^\s*(?:[-*•]\s+)+", "", s).strip()

    def _bullets(obj) -> str:
        frases: list[str] = []

        def _walk(o):
            if isinstance(o, str):
                f = _desmarca(o)
                if f:
                    frases.append(f)
            elif isinstance(o, list):
                for x in o:
                    _walk(x)
            elif isinstance(o, dict):
                for x in o.values():
                    _walk(x)
        _walk(obj)
        return "\n".join(f"- {f}" for f in frases)

    if t[:1] in "[{":  # veio estruturado (array ou objeto) — achatar em bullets
        for parser in (_json.loads, ast.literal_eval):
            try:
                b = _bullets(parser(t))
                if b:
                    return b
            except Exception:  # noqa: BLE001
                continue
    # texto livre (markdown) — colapsa bullets duplicados "- - x" / "- * x" → "- x" linha a linha
    linhas = []
    for ln in t.splitlines():
        linhas.append(re.sub(r"^(\s*)(?:[-*•]\s+){2,}", r"\1- ", ln))
    return "\n".join(linhas)


def parecer_raciocinado(ctx: dict) -> str:
    """Síntese raciocinada (gemini→cerebras, bounded) sobre os FATOS coletados. '' se LLM indisponível.

    Roda no caminho ASSÍNCRONO (via to_thread no montar) — não bloqueia o event loop; degrada honesto
    (sem regressão: o parecer-template segue como base)."""
    try:
        fatos = _fatos_para_raciocinio(ctx)
        if not fatos.strip():
            return ""
        from compliance_agent.direcionamento_cerebro import gerar_sync
        txt = _normaliza_raciocinio(gerar_sync("FATOS:\n" + fatos, _SYS_RACIOCINIO, timeout=45.0))
        return txt if len(txt) > 80 else ""
    except Exception:  # noqa: BLE001
        return ""


def parecer_fornecedor(ctx: dict) -> str:
    """
    PARECER PRELIMINAR do JFN — análise de MÉRITO e JURÍDICA, escrita a partir dos dados reais.
    É interpretativo e honesto: aponta INDÍCIOS a verificar com fundamento legal, sem juízo de
    culpabilidade nem afirmação de irregularidade (princípio da honestidade + presunção de inocência).
    """
    p = ctx["pagamentos"]
    nome = ctx["nome"]
    L: list[str] = []
    add = L.append

    if not p["tem_dados"]:
        return ("Sem Ordens Bancárias na base local para este CNPJ, não é possível emitir parecer de mérito "
                "sobre a execução financeira. Recomenda-se coleta direta no SIAFE/TFE antes de qualquer conclusão.")

    total = p["total_geral"]
    hhi = p["hhi"]
    top_share = hhi.get("top_share", 0)
    org_top = next(iter(p["por_orgao_geral"]), "—")
    # crescimento — HONESTO: usa pico/base entre exercícios (o 1º e o último da série
    # costumam ser parciais; comparar base→último parcial gera manchete distorcida).
    cresc_txt = ""
    anos_pos = [a for a in p["anos"] if (p["por_ano"][a]["total"] or 0) > 0]
    if len(anos_pos) >= 2:
        a_base = anos_pos[0]
        t_base = p["por_ano"][a_base]["total"]
        a_pico = max(anos_pos, key=lambda a: p["por_ano"][a]["total"])
        t_pico = p["por_ano"][a_pico]["total"]
        mult = _crescimento(p)
        cresc_txt = (f"Os pagamentos saltaram de R$ {moeda(t_base)} ({a_base}) ao pico de R$ {moeda(t_pico)} "
                     f"({a_pico}) — fator pico/base de {mult:.1f}× entre exercícios "
                     "(o primeiro e o último ano da série podem ser parciais; usa-se o pico para evitar distorção). ")
    zeros = sum(1 for a in p["anos"] for ln in p["por_ano"][a]["linhas"] if ln["valor"] == 0)

    # 1) Mérito
    add("### Análise de mérito")
    add("")
    add(f"A empresa **{nome}** recebeu **R$ {moeda(total)}** do Estado do Rio de Janeiro no período analisado, "
        f"em **{p['n_geral']} ordens bancárias** distribuídas por **{len(p['por_orgao_geral'])} unidades gestoras**. "
        f"{cresc_txt}"
        f"O valor é **materialmente relevante** e, por si só, recomenda acompanhamento de controle.")
    add("")
    if top_share >= 60:
        add(f"Chama atenção a **concentração de {top_share:.1f}%** dos pagamentos em um único órgão "
            f"(**{org_top}**), com HHI de {hhi.get('indice')} (concentração {hhi.get('nivel').lower()}). "
            "Concentração dessa ordem, para um prestador de serviços, é atípica e merece verificar se decorre "
            "de contratações competitivas e de objeto compatível com a atividade-fim da empresa, ou se há "
            "dependência institucional que favoreça a fornecedora.")
    elif top_share >= 40:
        add(f"Há **concentração relevante** ({top_share:.1f}%) em **{org_top}** (HHI {hhi.get('indice')}), "
            "o que sugere examinar a competitividade dos certames e a pulverização dos contratos.")
    else:
        add(f"Os pagamentos mostram **dispersão razoável** entre órgãos (maior fatia {top_share:.1f}% em {org_top}; "
            f"HHI {hhi.get('indice')}), o que reduz — mas não elimina — o risco de captura institucional.")
    add("")
    if zeros:
        add(f"Registram-se **{zeros} OB(s) de valor zero** (estornos/regularizações). Volume não trivial de "
            "estornos pode indicar retrabalho de liquidação ou ajustes de execução e merece conferência documental.")
        add("")

    # 2) Jurídico
    add("### Avaliação jurídica")
    add("")
    add("Sob o prisma normativo, os pontos acima devem ser cotejados com:")
    add("")
    add("- **CF/88, art. 37, *caput*** — princípios da impessoalidade, moralidade e eficiência na Administração;")
    add("- **Lei 14.133/2021** (nova Lei de Licitações) — dever de **competitividade** e de **publicidade** dos "
        "contratos no PNCP (art. 94); e **Lei 8.666/93** para contratos remanescentes sob sua vigência;")
    add("- **Lei 8.666/93, art. 65, §1º** — limites de aditivos (25%/50%), quando houver contratos aditivados;")
    add("- **Lei 4.320/64 e Decreto 93.872/86** — regularidade do ciclo empenho→liquidação→pagamento "
        "(vedação a pagamento antecipado sem amparo);")
    add("- **ACFE / TCU** — *red flags* de concentração de fornecedor e de pagamentos atípicos.")
    add("")
    if ctx.get("risco") in ("ALTO", "MÉDIO"):
        add(f"O rating de risco corporativo apurado (**{ctx['risco']}**, score {ctx['score']}/100) reforça a "
            "necessidade de diligência sobre quadro societário e eventuais vínculos.")
        add("")

    # 3) Conclusão / grau de atenção
    grau = "ALTO" if top_share >= 60 or ctx.get("risco") == "ALTO" else ("MÉDIO" if top_share >= 40 or zeros else "MODERADO")
    add("### Conclusão e grau de atenção")
    add("")
    add(f"**Grau de atenção recomendado: {grau}.** Os achados configuram **indícios a verificar** — não "
        "conclusão de irregularidade. Recomenda-se: (i) obter a lista oficial de contratos e respectivos "
        "processos SEI dos maiores pagamentos; (ii) confirmar a modalidade licitatória; (iii) checar aderência "
        "entre objeto contratual e atividade-fim; e (iv) cruzar empenho×liquidação×OB para detectar gaps.")
    add("")
    add("> **Ressalva metodológica:** análise baseada em **dados de pagamento (OB)** de fontes públicas; não "
        "examina o mérito documental de cada contrato. Não há, aqui, juízo de culpabilidade — vigora a "
        "presunção de regularidade dos atos administrativos até prova em contrário.")
    return "\n".join(L)


def troca_controle_societaria(emp: dict, pagamentos: dict,
                              min_total: float = 1_000_000.0, min_share: float = 15.0) -> dict | None:
    """Detecta ingresso no QSA POSTERIOR a receita pública relevante (controle trocado depois de a
    empresa já ter recebido vulto do Estado). Helper puro reusado pelo /relatorio (RF-04) e pelo Lex.
    Retorna None se não há sinal; senão {recente, quem, total_antes, n_antes, share}."""
    if not emp or not (pagamentos or {}).get("tem_dados"):
        return None
    entradas = [(s.get("data_entrada") or "") for s in (emp.get("socios") or [])]
    entradas = [d for d in entradas if len(d) == 10 and d.count("-") == 2]
    if not entradas:
        return None
    recente = max(entradas)
    total_antes = n_antes = 0
    for a in pagamentos["anos"]:
        for ln in pagamentos["por_ano"][a]["linhas"]:
            d = ln.get("data") or ""
            if len(d) == 10 and d < recente:
                total_antes += ln.get("valor") or 0
                n_antes += 1
    tg = pagamentos.get("total_geral") or 0
    share = (total_antes / tg * 100) if tg else 0
    if total_antes < min_total or share < min_share:
        return None
    nomes = [s.get("nome", "") for s in (emp.get("socios") or [])
             if (s.get("data_entrada") or "") == recente]
    quem = ", ".join(n for n in nomes if n)[:90] or "sócio(s)"
    return {"recente": recente, "quem": quem, "total_antes": total_antes,
            "n_antes": n_antes, "share": share}


def _red_flags(ctx: dict) -> list[tuple]:
    p = ctx["pagamentos"]
    out = []
    if p["tem_dados"]:
        hhi = p["hhi"]
        if hhi.get("top_share", 0) >= 60:
            org_top = next(iter(p["por_orgao_geral"]))
            out.append((
                "RF-01 — Concentração extrema em um órgão",
                f"{hhi['top_share']}% do valor pago concentrado em **{org_top}**. Para um fornecedor de serviços, "
                "a dispersão esperada seria maior; concentração extrema exige verificação.",
                "Art. 3 Lei 8.666/93 (isonomia); Art. 37 CF/88 (impessoalidade); ACFE — vendor concentration.",
            ))
        # estornos (OBs valor zero)
        zeros = sum(1 for a in p["anos"] for ln in p["por_ano"][a]["linhas"] if ln["valor"] == 0)
        if zeros:
            out.append((
                "RF-02 — Ordens bancárias com valor zero",
                f"{zeros} OB(s) com valor R$ 0,00 (estornos/regularizações). Volume elevado de estornos pode "
                "indicar retrabalho de execução ou ajustes — vale conferir o motivo.",
                "Boa prática de controle interno (CGE-RJ); rastreabilidade da execução (Lei 4.320/64).",
            ))
    # RF-TAC — pagamento FORA de contrato regular (TAC/indenização/reconhecimento de dívida). Detector
    # determinístico (regex em ordens_bancarias.observacao), por CNPJ + contexto sistêmico da UG pagadora.
    cnpj_alvo = so_digitos(ctx.get("cnpj") or "")
    if cnpj_alvo:
        try:
            from compliance_agent.reporting.detector_tac import red_flag_tac
            rf_tac = red_flag_tac(cnpj_alvo)
            if rf_tac:
                out.append((rf_tac["titulo"], rf_tac["descricao"], rf_tac["fundamento"]))
        except Exception:  # noqa: BLE001 — degrada honesto (DB/tabela ausente → sem RF-TAC)
            pass

    # red flag de co-localização (fornecedores na mesma sede) — vindo do cruzamento
    coend = (ctx.get("cruzamento") or {}).get("coendereco") or []
    if coend:
        n_pagos = sum(1 for c in coend if c.get("total_pago", 0) > 0)
        end = (ctx.get("cruzamento") or {}).get("endereco", {}).get("endereco", "")
        out.append((
            "RF-03 — Fornecedores na mesma sede",
            f"{len(coend)} outro(s) fornecedor(es) com sede IDÊNTICA à do alvo ({end}); {n_pagos} também "
            "recebem OBs do Estado. Empresas distintas no mesmo imóvel disputando/recebendo recursos públicos é "
            "indício clássico de fachada/laranja ou direcionamento — verificar QSA, sócios de fato e licitações comuns.",
            "Art. 337-F CP (frustração do caráter competitivo); art. 11 Lei 8.429/92; ACFE — shell company red flags.",
        ))

    # Cadastral (perfil enriquecido) — base das RF-04/05
    emp = (ctx.get("enriq", {}).get("dados") or {}).get("empresa") if ctx.get("enriq", {}).get("ok") else None

    # RF-04 — Alteração de controle societário POSTERIOR a receita pública relevante (helper reusado pelo Lex).
    tc = troca_controle_societaria(emp, p)
    if tc:
        out.append((
            "RF-04 — Controle societário alterado após receita pública relevante",
            f"Ingresso no quadro societário em **{tc['recente']}** ({tc['quem']}), **posterior** a "
            f"R$ {moeda(tc['total_antes'])} já pagos pelo Estado ({tc['n_antes']} OBs, {tc['share']:.0f}% do "
            "total do período). Mudança de controle/administração em fornecedor com receita pública pré-existente "
            "é indício a verificar: histórico de controle, eventual sucessão ou interposição de pessoas, e se a "
            "alteração coincide com escalada de contratos.",
            "Art. 14 Lei 14.133/2021 (idoneidade); art. 11 Lei 8.429/92; ACFE — change-of-control / nominee.",
        ))

    # RF-05 — Possível divergência entre atividade-fim (CNAE) e objeto contratado.
    # Conservador: só dispara quando NÃO há sobreposição de termos significativos (≥4 letras,
    # fora do boilerplate de licitação) entre o CNAE principal e o objeto REAL dos contratos.
    # IMPORTANTE: o campo `contratos.objeto` do SIAFE guarda só "Aditivos: N" (não é o objeto);
    # o objeto verdadeiro vem do TCE-RJ (Dados Abertos) em `tcerj_itens`.
    if emp:
        objs_reais = [(i.get("objeto") or "").strip() for i in (ctx.get("tcerj_itens") or [])]
        objs_reais = [o for o in objs_reais if len(o) >= 12]
        cnae = emp.get("cnae_principal") or ""
        tc = _termos_significativos(cnae)
        to_ = _termos_significativos(" ".join(objs_reais))
        if cnae and objs_reais and tc and to_ and not (tc & to_):
            amostra = objs_reais[0][:70]
            out.append((
                "RF-05 — Atividade-fim (CNAE) sem aderência ao objeto contratado",
                f"O CNAE principal registrado (“{cnae}”) não evidencia aderência ao objeto efetivamente "
                f"contratado (ex.: “{amostra}…”). Atividade econômica de registro incompatível com o objeto "
                "contratado é indício a verificar (adequação do CNAE, pós-fixação de objeto, ou empresa de "
                "prateleira/fachada habilitada para fim diverso).",
                "Art. 37 CF/88 (impessoalidade); Lei 14.133/2021 arts. 62-63 (qualificação técnica); "
                "ACFE — shell company red flags.",
            ))
    return out


def _termos_significativos(texto: str) -> set:
    """Tokens ≥4 letras, fora do boilerplate de licitação — base da aderência CNAE×objeto."""
    return {t for t in re.findall(r"[a-zà-úãõâêôçáéíóú]{4,}", (texto or "").lower())
            if t not in _BOILERPLATE}


_SYS_RACIOCINIO = (
    "Você é auditor sênior de controle externo (padrão TCE-RJ/TCU). A partir EXCLUSIVAMENTE dos fatos "
    "listados (NÃO invente dados, números, nomes ou fontes; não use conhecimento externo), escreva uma "
    "ANÁLISE RACIOCINADA que CONECTE os achados entre si: o que chama atenção, COMO os fatos se "
    "relacionam, quais hipóteses de risco merecem apuração e POR QUÊ, e o que verificar a seguir. Use "
    "linguagem condicional (indício, sugere, merece apuração) — NUNCA afirme fraude/irregularidade nem "
    "culpa; vigora a presunção de regularidade. Responda em MARKDOWN com bullets curtos iniciados por "
    "'- ' (NUNCA JSON, NUNCA cercas de código). Máximo ~320 palavras. Se os fatos forem escassos, diga "
    "objetivamente o que falta apurar."
)


_BOILERPLATE = {
    "contratacao", "contratação", "prestacao", "prestação", "servico", "serviço", "servicos",
    "serviços", "empresa", "pessoa", "juridica", "jurídica", "especializada", "especializado",
    "atividade", "atividades", "outros", "outras", "demais", "fornecimento", "objeto", "trata",
    "presente", "carater", "caráter", "para", "pela", "pelo", "continuado", "continuada",
    "continuos", "contínuos", "diversos", "geral", "comum", "execucao", "execução",
}


def _beneficios_socios(cnpj: str) -> dict:
    """Cruzamento inteligente: benefícios sociais (laranja) dos sócios/admin deste fornecedor (degrada honesto)."""
    try:
        from compliance_agent.reporting import beneficios_view as bv
        return bv.por_fornecedor(so_digitos(cnpj))
    except Exception:  # noqa: BLE001
        return {}
