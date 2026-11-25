# -*- coding: utf-8 -*-
"""Lex — parecer de ÓRGÃO (UG): achados de nível órgão + render + gerar_orgao.

Extraído de lex.py (split 2026-07-06); comportamento idêntico (snapshot-tested).
"""
from __future__ import annotations

import logging

from compliance_agent.reporting.inteligencia import _REPORTS, _slug, moeda
from compliance_agent.lex_redflags import _grau
from compliance_agent.lex_render import render_pdf

logger = logging.getLogger(__name__)

# ─────────────────────── PARECER LEX DE ÓRGÃO (UG) ───────────────────────
# O /orgao passa a "pensar" como o /relatorio: além do PDF/XLSX, emite um PARECER LEX próprio. Os indícios
# são de nível ÓRGÃO (concentração/captura, recorrência idêntica, estornos), com os mesmos red flags e
# fundamentos do controle externo, grau 🟢🟡🔴 e encaminhamento. Honesto: indícios a verificar, nunca acusação.

def _ob_zero_da_ug(ug: str) -> int:
    """Quantas OBs de valor <=0 (estornos/regularizações/OB R$ 0,00) a UG tem — insumo do R10.

    Fonte deliberada: espelho TFE (ordens_bancarias), NÃO o SIAFE. A regra "OB = SIAFE" vale para
    VALOR pago; aqui é CONTAGEM de estornos, e o TFE cobre ~1,1M OBs vs ~137k da varredura SIAFE
    (WAF limita a VM) — usar o SIAFE subcontaria. Revisitar se a cobertura SIAFE alcançar o TFE."""
    try:
        import sqlite3

        from compliance_agent.reporting.inteligencia import _DB
        if not ug or not _DB.exists():
            return 0
        con = sqlite3.connect(_DB)
        try:
            n = con.execute("SELECT COUNT(*) FROM ordens_bancarias WHERE ug_codigo=? AND (valor IS NULL OR valor<=0)",
                            (str(ug),)).fetchone()[0]
        finally:
            con.close()
        return int(n or 0)
    except Exception:
        return 0


def _p1(v: float) -> str:
    return f"{v:.1f}".replace(".", ",")


def _achados_orgao(ctx: dict) -> list[dict]:
    """Indícios de NÍVEL ÓRGÃO a partir dos pagamentos (OB) já consolidados pelo /orgao."""
    p = ctx.get("pagamentos") or {}
    if not p.get("tem_dados"):
        return []
    ach: list[dict] = []
    hhi = p.get("hhi") or {}
    nivel = (hhi.get("nivel") or "").lower()
    top_share = float(hhi.get("top_share") or 0)  # percentual (0-100)
    total = float(p.get("total_geral") or 0) or 1.0
    top_nome, top_val = next(iter((p.get("por_favorecido_geral") or {}).items()), ("—", 0))
    if top_share >= 60:
        ach.append({"rf": "R8", "grav": 4, "obs": f"**{top_nome}** concentra **{_p1(top_share)}%** dos pagamentos do órgão "
                    f"(R$ {moeda(top_val)} de R$ {moeda(total)}; HHI {_p1(float(hhi.get('indice') or 0))} — {nivel}). Concentração ≥60% em um "
                    "único fornecedor é *red flag* clássico de captura/cartel (ACFE/OCDE) — exige comprovar a competitividade."})
    elif top_share >= 50:
        ach.append({"rf": "R8", "grav": 3, "obs": f"**{top_nome}** concentra **{_p1(top_share)}%** (R$ {moeda(top_val)}; HHI "
                    f"{_p1(float(hhi.get('indice') or 0))} — {nivel}). Verificar competitividade dos certames ou fracionamento/dispensa reiterada/direcionamento."})
    elif top_share >= 30:
        ach.append({"rf": "R8", "grav": 2, "obs": f"Concentração relevante: **{top_nome}** com **{_p1(top_share)}%** "
                    f"(HHI {_p1(float(hhi.get('indice') or 0))} — {nivel}). Examinar a competitividade dos certames e o parcelamento do objeto."})
    try:
        from compliance_agent.reporting.inteligencia_orgao import _recorrentes_identicos
        grupos = _recorrentes_identicos(p)
    except Exception:
        grupos = []
    if grupos:
        g0 = grupos[0]
        # O4.9: era "R2" (fracionamento) com grav 2 — e o R2 leva à família de improbidade no parecer. Valor idêntico
        # recorrente é a ASSINATURA de contrato contínuo (parcela mensal), não de contratações distintas: sinal.
        ach.append({"rf": "S/VALORES-IDENTICOS", "grav": 1, "obs": f"SINAL, não achado — padrão de **valores "
                    f"idênticos**: **{g0['favorecido']}** recebeu **{g0['n']}×** o valor exato de R$ {moeda(g0['valor'])} "
                    f"(R$ {moeda(g0['total'])} no total). Típico de serviço continuado (parcela mensal de um contrato); "
                    "não é fracionamento (art. 75 §1º soma contratações distintas) — caracterizar objeto/vigência/medição."})
    # contagem de regularizações da MESMA base do pago (SIAFE, lex_fatos) quando o contexto já vem dela; o espelho
    # TFE só como fallback de contexto antigo — e a fonte vai escrita no achado (um fato, uma fonte declarada).
    if "n_regularizacoes" in p:
        n_zero, fonte_zero = int(p["n_regularizacoes"]), "SIAFE · ob_orcamentaria_siafe (OB paga de valor zero)"
    else:
        n_zero, fonte_zero = _ob_zero_da_ug(ctx.get("ug", "")), "espelho TFE · ordens_bancarias (contagem)"
    if n_zero >= 10:
        ach.append({"rf": "R10", "grav": 2, "obs": f"A UG tem **{n_zero}** OBs de valor zero/estorno — verificar regularizações/"
                    "anulações de liquidação (Lei 4.320/64 arts. 62-63; Decreto 93.872/86 art. 38) e seu motivo. "
                    f"Fonte: {fonte_zero}."})
    # Pagamento FORA de contrato regular (TAC/indenização) + emergencial — achado sistêmico de órgão
    # (achado FSERJ codificado). R5 = inexigibilidade/dispensa possivelmente indevida (fuga ao certame).
    tj = ctx.get("tac_orgao") or {}
    if tj.get("ok"):
        ug_m = tj.get("tac_ug") or {}
        emerg = tj.get("emergencial") or {}
        wl = tj.get("worklist") or {}
        pct = float(ug_m.get("pct") or 0)
        tac_val = float(ug_m.get("total_tac") or 0)
        susp = [f for f in (wl.get("fornecedores") or []) if f.get("sede_indicio")]
        if pct >= 25 or tac_val >= 100_000_000:  # sistêmico relevante (faixa FSERJ)
            grav = 4 if (pct >= 25 and tac_val >= 100_000_000) else 3
        elif pct >= 10 and tac_val > 0:
            grav = 2
        else:
            grav = 0
        if grav:
            obs = (f"A UG pagou **{pct:.1f}%** de R$ {moeda(float(ug_m.get('total') or 0))} **FORA de contrato "
                   f"regular** — via TAC/indenização/reconhecimento de dívida (**R$ {moeda(tac_val)}** em "
                   f"{ug_m.get('n_tac', 0)} OBs). Regularização *a posteriori* recorrente e vultosa é indício "
                   "SISTÊMICO de contratação informal/emergencial perpetuada e **fuga ao dever de licitar**.")
            if emerg.get("ok"):
                obs += (f" Soma-se a red flag irmã: **{emerg.get('n_emerg', 0)} OBs** "
                        f"(R$ {moeda(float(emerg.get('total_emerg') or 0))}) por **emergencial/dispensa**.")
            wl_top = (wl.get("fornecedores") or [])[:4]
            if wl_top:
                obs += (" Worklist de co-suspeitos por TAC%: "
                        + "; ".join(f"{(f.get('nome') or '—')[:24]} {f.get('pct', 0):.0f}%"
                                    + (" (sede-fachada)" if f.get("sede_indicio") else "") for f in wl_top) + ".")
            if susp:
                obs += (f" **{len(susp)} desses são fachada-suspeitos** (alto TAC% + sede INDÍCIO/sem-Google) — "
                        "hipótese de interposição/laranja a apurar (indício, não acusação).")
            ach.append({"rf": "R5", "grav": grav, "obs": obs})
    # Cruzamento com o dump da Receita Federal (anomalias nos fornecedores) — alimenta o grau do órgão.
    ar = ctx.get("anomalia_receita") or {}
    if ar.get("ok"):
        sf_flag = [r for r in (ar.get("sem_fins_lucrativos") or []) if not r.get("ressalva")]
        if sf_flag:
            t = sf_flag[0]
            grav = 3 if float(t.get("total") or 0) >= 50_000_000 else 2
            ach.append({"rf": "R5", "grav": grav, "obs":
                        f"**{len(sf_flag)}** entidade(s) **sem fins lucrativos** (associação/fundação/OS, sem "
                        f"perfil de ensino/pesquisa) recebem como fornecedor — maior: **{(t.get('razao_social') or '—')[:40]}** "
                        f"(R$ {moeda(float(t.get('total') or 0))}). Repasse a OS/entidade via contrato de gestão/parceria "
                        "exige confirmar o objeto, o credenciamento e a prestação de contas (Lei 9.637/98; Lei 13.019/2014 — "
                        "MROSC). Indício, não acusação."})
        rede = ar.get("rede_mesmo_orgao") or []
        rede_pf = [r for r in rede if not r.get("eh_pj")]
        if rede_pf:
            t = rede_pf[0]
            ach.append({"rf": "R7", "grav": 3, "obs":
                        f"**{len(rede_pf)}** administrador(es) compartilham **≥2 fornecedores do mesmo órgão** "
                        f"(QSA da Receita) — ex.: **{(t.get('nome_socio') or '—')[:34]}** em **{t.get('n_fornecedores')}** "
                        "fornecedores. Fornecedores aparentemente concorrentes sob a mesma administração indiciam "
                        "**concorrência simulada/concentração oculta** (Art. 90 Lei 8.666; Art. 337-F CP; Art. 36 Lei "
                        "12.529 — CADE) — corroborar os licitantes nos certames (SEI/PNCP)."})
        su = ar.get("socio_unico_alto_valor") or []
        su_priv = [r for r in su if not r.get("sem_fins")]
        if su_priv:
            t = su_priv[0]
            ach.append({"rf": "DD/H-SOCIO-UNICO", "grav": 2, "obs":
                        f"**{len(su_priv)}** fornecedor(es) de alto valor com **administrador único** no QSA — ex.: "
                        f"**{(t.get('razao_social') or '—')[:40]}** (R$ {moeda(float(t.get('total') or 0))}). Gestão "
                        "concentrada num só sócio em contratos vultosos é indício de **interposição (laranja)** ou "
                        "capacidade operacional incompatível — confrontar com a estrutura real. Indício ≠ acusação."})
        cad = ar.get("cadastro") or {}
        if cad.get("ok") and cad.get("achados"):
            ach.append({"rf": "DD/H-SITUACAO", "grav": 4, "obs":
                        f"**{len(cad['achados'])}** fornecedor(es) com **situação cadastral irregular** na Receita "
                        "(INAPTA/baixada/suspensa) — incompatível com o recebimento de pagamento público; conferir a "
                        "vigência contratual (fonte: minhareceita.org)."})
    return ach


def _conluio_pncp_md(ctx: dict) -> str:
    """Conluio a partir dos RESULTADOS estruturados do PNCP (vencedor por item) — cross-certame. '' sem sinal."""
    try:
        from compliance_agent.collectors.pncp_resultados import conluio_do_orgao
        _cj = conluio_do_orgao(ctx.get("nome", "") or "")
    except Exception as exc:  # noqa: BLE001
        logger.warning("conluio PNCP do órgão indisponível (seção some): %s", exc)
        return ""
    _cap, _rod = _cj.get("captura") or [], _cj.get("rodizio_vencedores") or []
    if not (_cj.get("n_certames", 0) >= 3 and (_cap or _rod)):
        return ""
    L = ["### Conluio em licitações — resultados do PNCP (indício OCDE)", "",
         f"*Sobre {_cj['n_certames']} certame(s) com resultado homologado no PNCP para este órgão. Vencedor estruturado "
         "por item — indício a verificar (bid rigging), nunca acusação.*", ""]
    for c in _cap[:5]:
        L.append(f"- **Captura:** {c.get('nome', '—')} venceu **{int(c.get('share', 0) * 100)}%** de {c.get('certames')} "
                 "certames — concentração a examinar (competitividade real).")
    for r in _rod[:5]:
        grp = ", ".join(f"{m}×{n}" for m, n in (r.get("reparticao") or {}).items())
        coesao = r.get("coesao_objeto")
        termos = ", ".join(r.get("termos_comuns") or [])
        sufixo = (f" no MESMO tipo de objeto (coesão {int(coesao * 100)}%" + (f": {termos}" if termos else "") + ")"
                  ) if coesao is not None else ""
        L.append(f"- **Rodízio de vencedores:** {len(r.get('grupo', []))} fornecedores repartem {r.get('certames')} "
                 f"certames{sufixo} (cobertura {int(r.get('cobertura_grupo', 0) * 100)}%): {grp}.")
    return "\n".join(L)


def _parecer_orgao_md(ctx: dict, analise: dict, merito: str = "") -> str:
    """Corpo (markdown) do parecer Lex de órgão — parecer referência por eixos (`lex_parecer.montar_orgao`).
    `merito` é aceito por compatibilidade e NÃO entra: a narrativa antiga repetia, com réguas próprias, o que os
    indícios já dizem (fonte de contradição)."""
    from compliance_agent.lex_parecer import montar_orgao
    from compliance_agent.lex_redflags import jurisdicao as _jurisdicao
    from compliance_agent.pcrj.esfera import classificar_esfera as _classificar_esfera
    _esfera = ctx.get("esfera") or _classificar_esfera(ctx.get("nome", "") or "",
                                                       ctx.get("orgao_cnpj", "") or ctx.get("cnpj", "") or "")
    a = dict(analise)
    a.setdefault("jurisdicao", _jurisdicao(_esfera))
    a.setdefault("conluio_md", _conluio_pncp_md(ctx))
    return montar_orgao(ctx, a)


def analise_orgao(ctx: dict) -> tuple[dict, dict]:
    """(ctx com pagamentos do SIAFE, análise). O contexto do /orgao traz pagamentos do espelho TFE; o parecer
    lê a OB paga do SIAFE da UG (`lex_fatos`) e não altera o contexto do chamador."""
    from compliance_agent import lex_fatos as _lf
    ctx = dict(ctx)
    base = _lf.base_siafe(ug=str(ctx.get("ug") or ""))
    ctx["pagamentos"] = _lf.pagamentos(base)
    achados = _achados_orgao(ctx)
    emoji, rotulo, just = _grau(achados)
    if not achados and not ctx["pagamentos"].get("tem_dados"):
        emoji, rotulo, just = ("⚪", "INDETERMINADO", "nenhuma OB paga do SIAFE para a UG — sem base para graduar")
    return ctx, {"achados": achados, "emoji": emoji, "rotulo": rotulo, "just": just, "base": base}


def gerar_orgao(ctx: dict, salvar: bool = True) -> dict:
    """Parecer LEX de ÓRGÃO (UG). `ctx` é o contexto do relatório de órgão (nome, ug, data). Pagamento = OB paga do
    SIAFE da UG. Retorna {ok, grau, n_indicios, path_lex_pdf, path_lex_md, md}."""
    ctx, analise = analise_orgao(ctx)
    md = _parecer_orgao_md(ctx, analise)
    out = {"ok": True, "grau": analise["rotulo"], "n_indicios": len(analise["achados"]), "path_lex_pdf": "",
           "path_lex_md": "", "md": md}
    if salvar:
        base = f"parecer_lex_orgao_{_slug(ctx.get('nome','')) or ctx.get('ug','')}_{ctx.get('data','')}"
        md_path = _REPORTS / f"{base}.md"
        md_path.write_text(md, encoding="utf-8")
        out["path_lex_md"] = str(md_path)
        try:
            out["path_lex_pdf"] = render_pdf(ctx, str(_REPORTS / f"{base}.pdf"), analise, md=md)
        except Exception as exc:  # noqa: BLE001
            out["_pdf_erro"] = str(exc)[:160]
    return out
