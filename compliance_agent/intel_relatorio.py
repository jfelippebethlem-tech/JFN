# -*- coding: utf-8 -*-
"""intel_relatorio — gera PDF padrão Kroll de QUALQUER detector de inteligência do painel.

Um registry mapeia `tipo` → (função detectora, título, colunas). O builder genérico monta a tabela
HTML, formata R$ no padrão BR e chama render_html.gerar_pdf (mesmo pipeline dos relatórios da casa).
Cada aba do painel ganha um botão "Gerar PDF" que aciona /api/intel/pdf?tipo=...
"""
from __future__ import annotations

from compliance_agent.reporting.intel_base import moeda
from compliance_agent.reporting.render_html import gerar_pdf


def _rs(v) -> str:
    return f"R$ {moeda(v or 0)}"


def _tabela(headers: list[str], linhas: list[str]) -> str:
    th = "".join(f"<th>{h}</th>" for h in headers)
    return f"<table><tr>{th}</tr>{''.join(linhas)}</table>"


def _esc(s) -> str:
    s = "" if s is None else str(s)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ── builders por tipo: recebem o dict do detector, devolvem (titulo, subtitulo, secoes, prov) ──

def _b_sancionadas(d):
    ls = []
    for e in d.get("empresas", [])[:150]:
        est, pncp = e.get("estado", {}), e.get("pncp", {})
        grave = est.get("obs_durante") or pncp.get("vitorias_durante")
        s0 = (e.get("sancoes") or [{}])[0]
        ls.append(f"<tr><td>{'🔴' if grave else '🟡'}</td><td>{_esc(e['nome'])}<br><small>{_esc(e['cnpj'])}</small></td>"
                  f"<td>{_esc(s0.get('cadastro'))} · {_esc((s0.get('categoria') or '')[:40])}<br><small>{_esc(s0.get('data_inicio'))}→{_esc(s0.get('data_fim'))}</small></td>"
                  f"<td style='text-align:right'>{_rs(est.get('valor_durante',0)+pncp.get('valor_durante',0) or est.get('valor',0)+pncp.get('valor',0))}</td></tr>")
    return ("Empresas sancionadas contratadas pelo poder público",
            f"CEIS/CNEP × pagamentos e licitações · {d.get('n_a_epoca',0)} com ato À ÉPOCA da sanção",
            [{"titulo": "1. Empresas com sanção que contrataram",
              "html": _tabela(["", "Empresa / CNPJ", "Sanção (vigência)", "Recebido"], ls)}], d)


def _b_fracionamento(d):
    ls = [f"<tr><td>{int(g['concentracao']*100)}%</td><td>{_esc(g['nome'])}<br><small>{_esc(g['cnpj_fmt'])} · UG {g['ug_emitente']} · {g['mes']}</small></td>"
          f"<td>{g['n_colado']}/{g['n']} coladas no teto</td><td style='text-align:right'>{_rs(g['soma'])}</td></tr>"
          for g in d.get("grupos", [])[:150]]
    return ("Fracionamento de despesa — fatiar para não licitar",
            f"{d.get('n',0)} grupos favorecido+UG+mês com OBs coladas no teto de dispensa",
            [{"titulo": "1. Grupos com concentração colada no teto",
              "html": _tabela(["Conc.", "Favorecido / UG / mês", "OBs coladas", "Soma"], ls)}], d)


def _b_sobrepreco(d):
    ls = [f"<tr><td>{a['razao']}×</td><td>{_esc(a['item'])}{(' / '+_esc(a['unidade_medida'])) if a.get('unidade_medida') else ''}</td>"
          f"<td>{_esc((a.get('orgao') or '')[:40])}<br><small>venc.: {_esc(a.get('fornecedor'))}</small></td>"
          f"<td style='text-align:right'>{_rs(a['preco'])}<br><small>mediana {_rs(a['mediana'])} (n={a['amostra']})</small></td></tr>"
          for a in d.get("achados", [])[:150]]
    return ("Sobrepreço por mediana de item (PNCP)",
            f"{d.get('n',0)} itens com preço unitário ≥2× a mediana do grupo · {d.get('grupos_comparaveis',0)} grupos",
            [{"titulo": "1. Itens pagos muito acima da mediana",
              "html": _tabela(["× med", "Item", "Órgão / vencedor", "Preço unit."], ls)}], d)


def _b_aditivos(d):
    ls = [f"<tr><td>{'🔴' if a['estoura_teto'] else '🟡'}</td><td>{_esc(a.get('fornecedor'))}<br><small>{_esc((a.get('orgao') or '')[:40])}</small></td>"
          f"<td>{('+'+str(a['pct'])+'%') if a['estoura_teto'] else str(a['num_aditivos'])+' aditivos'} (teto {a['teto_pct']}%)</td>"
          f"<td style='text-align:right'>{_rs(a['valor_inicial'])} → {_rs(a['valor_global'])}</td></tr>"
          for a in d.get("achados", [])[:150]]
    return ("Aditivos que estouram o limite legal",
            f"{d.get('n_estoura_teto',0)} estouram o teto (25%/50%) · {d.get('n_serie',0)} com ≥3 aditivos",
            [{"titulo": "1. Contratos com acréscimo acima do limite / aditivos em série",
              "html": _tabela(["", "Fornecedor / órgão", "Acréscimo", "Inicial → global"], ls)}], d)


def _b_socio_servidor(d):
    ls = [f"<tr><td>{'🔴' if a.get('mesmo_orgao') else ('⚖️' if a['gerencia'] else '🟡')}</td>"
          f"<td>{_esc(a['socio'])}<br><small>{_esc(a['qualificacao'])} de {_esc(a['empresa'])}</small></td>"
          f"<td>{_esc(a['servidor_cargo'])} · {_esc((a['servidor_orgao'] or '')[:34])}</td>"
          f"<td style='text-align:right'>{_rs(a['total_pago'])}<br><small>{a['confianca']}</small></td></tr>"
          for a in d.get("achados", [])[:150]]
    return ("Servidor público sócio de fornecedor do Estado",
            f"{d.get('n',0)} servidores · {d.get('n_gerencia',0)} com gerência (vedada) · {d.get('n_art9',0)} art. 9",
            [{"titulo": "1. Servidores sócios de fornecedores",
              "html": _tabela(["", "Servidor / empresa", "Cargo / órgão", "Recebido"], ls)}], d)


def _b_fornecedor_dependente(d):
    ls = [f"<tr><td>{int(a['share']*100)}%</td><td>{_esc(a['nome'])}<br><small>{_esc(a['cnpj_fmt'])}</small></td>"
          f"<td>UG {a['ug']} {_esc(a.get('ug_nome',''))}</td><td style='text-align:right'>{_rs(a['total'])}</td></tr>"
          for a in d.get("achados", [])[:150]]
    return ("Fornecedor dependente — 'empresa do órgão'",
            f"{d.get('n',0)} fornecedores comerciais com ≥90% da receita em UMA unidade gestora",
            [{"titulo": "1. Empresas cativas de um único comprador",
              "html": _tabela(["Depend.", "Empresa", "Unidade gestora", "Total recebido"], ls)}], d)


def _b_corrida_dezembro(d):
    ls = [f"<tr><td>{int(a['share']*100)}%</td><td>{_esc(a['nome'])}<br><small>{_esc(a['cnpj_fmt'])}</small></td>"
          f"<td style='text-align:right'>{_rs(a['dezembro'])} em dez.</td><td style='text-align:right'>{_rs(a['total'])}</td></tr>"
          for a in d.get("achados", [])[:150]]
    return ("Corrida do empenho de dezembro",
            f"{d.get('n',0)} fornecedores comerciais com ≥75% do valor concentrado em dezembro",
            [{"titulo": "1. Concentração de pagamentos no fim do exercício",
              "html": _tabela(["% dez.", "Empresa", "Em dezembro", "Total ano"], ls)}], d)


def _b_socio_oculto(d):
    ls = [f"<tr><td>{a['n_empresas']}</td><td>{_esc(a['socio'])}</td>"
          f"<td><small>{_esc(', '.join(a['empresas'][:4]))}</small></td>"
          f"<td style='text-align:right'>{_rs(a['total'])}</td></tr>"
          for a in d.get("achados", [])[:150]]
    return ("Sócio oculto — um dono, vários fornecedores",
            f"{d.get('n',0)} pessoas/holdings sócias de ≥3 empresas fornecedoras do Estado",
            [{"titulo": "1. Concentração societária entre fornecedores",
              "html": _tabela(["Empresas", "Sócio / holding", "Fornecedoras (amostra)", "Total recebido"], ls)}], d)


def _b_fantasmas(d):
    ls = [f"<tr><td>{a.get('score','—')}</td><td>{_esc(a.get('razao_social') or a['cnpj'])}<br><small>{_esc(a['cnpj'])} · {_esc(a.get('origem'))}</small></td>"
          f"<td>{_esc(', '.join(s.get('id','') for s in a.get('sinais',[])[:4]))}</td><td>{_esc(a.get('classificacao'))}</td></tr>"
          for a in d.get("empresas", [])[:150] if a.get("classificacao") != "sem_cadastro"]
    return ("Radar de empresas-fantasma",
            f"{d.get('total_alvo',0)} no alvo · {d.get('sem_cadastro',0)} sem cadastro",
            [{"titulo": "1. Empresas com sinais de fachada", "html": _tabela(["Score", "Empresa", "Sinais", "Risco"], ls)}], d)


def _b_perdedoras(d):
    ls = [f"<tr><td>{p['participou']}×</td><td>{_esc(p['nome'])}<br><small>{_esc(p['cnpj_fmt'])}</small></td>"
          f"<td><small>{_esc(', '.join(x['nome'] for x in p.get('perde_junto_com',[])[:3]))}</small></td></tr>"
          for p in d.get("perdedoras", [])[:150]]
    return ("Perdedoras contumazes — proposta de cobertura",
            f"{d.get('n',0)} empresas que participam e nunca vencem",
            [{"titulo": "1. Licitantes que só perdem", "html": _tabela(["Particip.", "Empresa", "Perde junto com"], ls)}], d)


# tipo → (função-detector com db_path opcional, builder, faixa)
def _detectores():
    from compliance_agent import cruzamentos_intel as C
    return {
        "sancionadas": (lambda p: C.sancionadas_contratadas(p), _b_sancionadas, "ALTO"),
        "fracionamento": (lambda p: C.fracionamento(db_path=p), _b_fracionamento, "ALTO"),
        "sobrepreco": (lambda p: C.sobrepreco(db_path=p), _b_sobrepreco, "ALTO"),
        "aditivos": (lambda p: C.aditivos_estouro(db_path=p), _b_aditivos, "ALTO"),
        "socio_servidor": (lambda p: C.socio_servidor(db_path=p), _b_socio_servidor, "EXTREMO"),
        "fornecedor_dependente": (lambda p: C.fornecedor_dependente(db_path=p), _b_fornecedor_dependente, "MÉDIO"),
        "corrida_dezembro": (lambda p: C.corrida_dezembro(db_path=p), _b_corrida_dezembro, "MÉDIO"),
        "socio_oculto": (lambda p: C.socio_oculto(db_path=p), _b_socio_oculto, "ALTO"),
        "fantasmas": (lambda p: C.ranking_fantasmas(db_path=p, limite=150), _b_fantasmas, "ALTO"),
        "perdedoras": (lambda p: C.perdedoras_contumazes(db_path=p), _b_perdedoras, "MÉDIO"),
    }


async def gerar_pdf_intel(tipo: str, db_path: str | None = None) -> dict:
    """Gera o PDF Kroll do detector `tipo` e devolve {ok, path_pdf, url, n}."""
    reg = _detectores()
    if tipo not in reg:
        return {"ok": False, "erro": f"tipo desconhecido: {tipo}"}
    detector, builder, faixa = reg[tipo]
    d = detector(db_path)
    if not d.get("ok"):
        return {"ok": False, "erro": d.get("erro", "detector falhou")}
    titulo, subtitulo, secoes, dd = builder(d)
    n = d.get("n") or d.get("n_a_epoca") or len(d.get("empresas", []) or d.get("achados", []))
    # ressalva do detector vira seção final + nota
    if d.get("explicacao") or d.get("ressalva"):
        secoes = secoes + [{"titulo": "Método e ressalvas",
                            "html": f"<p>{_esc(d.get('explicacao',''))}</p><p><b>Ressalva.</b> {_esc(d.get('ressalva',''))}</p>"}]
    ctx = {
        "titulo": titulo, "subtitulo": subtitulo,
        "classificacao": "CONFIDENCIAL — USO INTERNO (controle externo · RJ)",
        "faixa": faixa, "score": min(95, 40 + n) if n else 30,
        "rotulo_score": "Volume de indícios",
        "top_flags": [f"{n} indícios"] + ([d.get("ressalva", "")[:1]] if False else []),
        "metodologia": "Cruzamento determinístico de bases públicas (SIAFE, PNCP, CEIS/CNEP, folhas).",
        "secoes": secoes,
        "proveniencia": [
            {"dado": "Pagamentos (OB)", "estado": "REAL", "fonte": "SIAFE-Rio", "data": ""},
            {"dado": "Licitações/contratos", "estado": "REAL", "fonte": "PNCP", "data": ""},
            {"dado": "Sanções", "estado": "REAL", "fonte": "CEIS/CNEP", "data": ""},
        ],
        "ressalva": d.get("ressalva", "Indício para apuração interna — não é acusação."),
        "_dados": {"tipo": tipo, "n": n},
    }
    path = await gerar_pdf(ctx, f"intel_{tipo}")
    import os
    return {"ok": True, "path_pdf": path, "url": f"/reports/{os.path.basename(path)}", "n": n}
