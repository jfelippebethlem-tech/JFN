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


def _b_fenix(d):
    ls = [f"<tr><td>{'🔴' if a['tipo']=='defunta' else '🟡'}</td><td>{_esc(a['nome'])}<br><small>{_esc(a['cnpj'])}</small></td>"
          f"<td>{_esc(a['situacao'] or '')} · aberta {_esc(a['data_abertura'])} · 1ª OB {_esc(a['primeira_ob'])}</td>"
          f"<td style='text-align:right'>{_rs(a['total_recebido'])}</td></tr>" for a in d.get("achados", [])[:120]]
    return ("Empresas fênix — defunta ou aberta às vésperas",
            f"{d.get('n',0)} empresas · {d.get('n_defunta',0)} baixadas/inaptas que receberam",
            [{"titulo": "1. Empresas de risco (situação × pagamento)", "html": _tabela(["", "Empresa", "Situação / datas", "Recebido"], ls)}], d)


def _b_porta(d):
    ls = [f"<tr><td>{_esc(a['socio'])}<br><small>{_esc(a['qualificacao'])} de {_esc(a['empresa'])}</small></td>"
          f"<td>ex: {_esc(a['ex_cargo'])} · {_esc((a['ex_orgao'] or '')[:30])} ({_esc(a['vinculo'])})</td>"
          f"<td style='text-align:right'>{_rs(a['total_pago'])}<br><small>{a['confianca']}</small></td></tr>"
          for a in d.get("achados", [])[:120]]
    return ("Porta giratória — ex-servidor virou fornecedor",
            f"{d.get('n',0)} ex-servidores sócios de fornecedores do Estado",
            [{"titulo": "1. Ex-servidores sócios de fornecedores", "html": _tabela(["Sócio / empresa", "Ex-cargo / órgão", "Recebido"], ls)}], d)


def _b_nepcruz(d):
    ls = [f"<tr><td>{_esc(a['sobrenome_a'])} ⇄ {_esc(a['sobrenome_b'])}</td>"
          f"<td>{_esc((a['orgao_a'] or '')[:26])}<br><small>autoridade: {_esc(a['autoridade_a'])}</small></td>"
          f"<td>{_esc((a['orgao_b'] or '')[:26])}<br><small>autoridade: {_esc(a['autoridade_b'])}</small></td></tr>"
          for a in d.get("achados", [])[:80]]
    return ("Nepotismo cruzado — colocação recíproca entre órgãos",
            f"{d.get('n',0)} pares recíprocos (dribla a SV13 do mesmo órgão)",
            [{"titulo": "1. Pares recíprocos A⇄B", "html": _tabela(["Sobrenomes", "Órgão A", "Órgão B"], ls)}], d)


def _b_nepotismo(d):
    ls = []
    for a in d.get("achados", [])[:120]:
        membros = "<br>".join(f"{_esc(m['nome'])} <small>({_esc(m['cargo'])}{' · CPF …'+_esc(m['cpf_frag']) if m.get('cpf_frag') else ''})</small>"
                              for m in a.get("membros", [])[:6])
        ls.append(f"<tr><td>{'⚖️' if a['tem_autoridade'] else ''} {a['n_membros']}</td>"
                  f"<td>{_esc(a['sobrenome'])}<br><small>{int(a['concentracao']*100)}% de {a['total_folha']} na folha</small></td>"
                  f"<td>{_esc((a['orgao'] or '')[:34])}</td><td>{membros}</td></tr>")
    return ("Nepotismo — parentes em cargo de confiança (SV13)",
            f"{d.get('n',0)} clusters de sobrenome raro · {d.get('n_com_autoridade',0)} com autoridade nomeante",
            [{"titulo": "1. Famílias em cargos de confiança no mesmo órgão",
              "html": _tabela(["Nº", "Sobrenome (raridade)", "Órgão", "Membros"], ls)}], d)


def _b_perdedoras(d):
    ls = [f"<tr><td>{p['participou']}×</td><td>{_esc(p['nome'])}<br><small>{_esc(p['cnpj_fmt'])}</small></td>"
          f"<td><small>{_esc(', '.join(x['nome'] for x in p.get('perde_junto_com',[])[:3]))}</small></td></tr>"
          for p in d.get("perdedoras", [])[:150]]
    return ("Perdedoras contumazes — proposta de cobertura",
            f"{d.get('n',0)} empresas que participam e nunca vencem",
            [{"titulo": "1. Licitantes que só perdem", "html": _tabela(["Particip.", "Empresa", "Perde junto com"], ls)}], d)


def _d_conluio(p):
    import sqlite3
    from compliance_agent.collectors.pncp_resultados import conluio_enriquecido
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    try:
        dd = conluio_enriquecido(con, min_certames=4)
        dd["n"] = len(dd.get("captura", [])) + len(dd.get("rodizio_vencedores", []))
        return {"ok": True, **dd}
    finally:
        con.close()


def _b_conluio(d):
    cap = d.get("captura", [])
    rod = d.get("rodizio_vencedores", [])
    lc = [f"<tr><td>{int(c['share']*100)}%</td><td>{_esc(c['orgao_nome'])}</td><td>{_esc(c['nome'])}</td>"
          f"<td>{c['certames']} certames</td></tr>" for c in cap[:100]]
    lr = [f"<tr><td>{len(r.get('membros_nome',[]))}</td><td>{_esc(r['orgao_nome'])}</td>"
          f"<td><small>{_esc(' · '.join(m['nome'] for m in r.get('membros_nome',[])[:3]))}</small></td>"
          f"<td>{r['certames']} certames</td></tr>" for r in rod[:100]]
    secoes = [{"titulo": "1. Captura de órgão (1 empresa vence ≥80%)",
               "html": _tabela(["Share", "Órgão", "Vencedor", "Volume"], lc) if lc else "<p>Nenhuma.</p>"},
              {"titulo": "2. Rodízio de vencedores (revezamento)", "page_break": True,
               "html": _tabela(["Empresas", "Órgão", "Grupo", "Volume"], lr) if lr else "<p>Nenhum.</p>"}]
    return ("Conluio em licitações — captura e rodízio (PNCP)",
            f"{len(cap)} capturas · {len(rod)} rodízios · indício OCDE de bid rigging",
            secoes, d)


def _d_nomeados(p):
    import sqlite3
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        # mesma otimização do endpoint: TEMP TABLE indexada de candidatos, evita o cross-join lento
        con.execute("CREATE TEMP TABLE _cand AS SELECT DISTINCT UPPER(TRIM(nome_candidato)) nc, "
                    "cargo_candidato, partido, ano_eleicao FROM doacoes_eleitorais")
        con.execute("CREATE INDEX _tc ON _cand(nc)")
        rows = con.execute(
            "SELECT f.nome, f.cargo, f.orgao_nome, c.cargo_candidato, c.partido, c.ano_eleicao "
            "FROM (SELECT DISTINCT nome, cargo, orgao_nome FROM registros_folha) f "
            "JOIN _cand c ON UPPER(TRIM(f.nome))=c.nc ORDER BY f.nome LIMIT 300").fetchall()
        it = [{"nome": r["nome"], "cargo": r["cargo"], "orgao": r["orgao_nome"],
               "disputou": r["cargo_candidato"], "partido": r["partido"], "ano": r["ano_eleicao"],
               "comiss": "comiss" in (r["cargo"] or "").lower()} for r in rows]
        return {"ok": True, "itens": it, "n": len(it)}
    finally:
        con.close()


def _b_nomeados(d):
    ls = [f"<tr><td>{'🎖️' if x['comiss'] else ''}</td><td>{_esc(x['nome'])}</td>"
          f"<td>{_esc((x['orgao'] or '')[:34])} · {_esc(x['cargo'])}</td>"
          f"<td>{_esc(x['disputou'])} / {_esc(x['partido'])} / {_esc(str(x['ano']))}</td></tr>"
          for x in d.get("itens", [])[:200]]
    return ("Servidores × candidatos (folha × TSE)",
            f"{d.get('n',0)} servidores que também foram candidatos",
            [{"titulo": "1. Cruzamento nome a nome", "html": _tabela(["", "Servidor", "Órgão / cargo", "Disputou"], ls)}], d)


def _d_comissionados(p):
    import sqlite3
    con = sqlite3.connect(f"file:{p.replace('compliance.db','pcrj.db')}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        it = [dict(r) for r in con.execute(
            "SELECT nome_pcrj, cargo_pcrj, orgao_pcrj, admissao, exoneracao, cand_ano, cand_cargo, cand_cidade "
            "FROM pcrj_comissionado_candidato ORDER BY cand_ano DESC LIMIT 400")]
        return {"ok": True, "itens": it, "n": len(it)}
    finally:
        con.close()


def _b_comissionados(d):
    ls = [f"<tr><td>{_esc(x['nome_pcrj'])}</td><td>{_esc((x['orgao_pcrj'] or '')[:34])} · {_esc(x['cargo_pcrj'])}</td>"
          f"<td>{_esc(x['cand_cargo'])} {_esc(str(x['cand_ano']))} · {_esc(x['cand_cidade'])}</td></tr>"
          for x in d.get("itens", [])[:250]]
    return ("Comissionados da Prefeitura do Rio × candidaturas (TSE)",
            f"{d.get('n',0)} comissionados que foram candidatos",
            [{"titulo": "1. Cargo de confiança × disputa eleitoral", "html": _tabela(["Nome", "Órgão / cargo", "Disputou"], ls)}], d)


def _b_radar(d):
    ls = [f"<tr><td>{a['rating']} {a['score']}</td><td>{_esc(a['nome'])}<br><small>{_esc(a['cnpj_fmt'])}</small></td>"
          f"<td>{a['n_sinais']}</td><td><small>{_esc(', '.join(s['sinal'] for s in a.get('sinais', [])[:6]))}</small></td></tr>"
          for a in d.get("achados", [])[:150]]
    return ("Radar de risco — todos os detectores somados",
            f"{d.get('n',0)} fornecedores com sinal · {d.get('n_vermelho',0)} com score ≥50 (🔴)",
            [{"titulo": "1. Fila de apuração priorizada (score composto 0-100)",
              "html": _tabela(["Score", "Empresa / CNPJ", "Nº", "Sinais"], ls)}], d)


def _b_conluio_qsa(d):
    ls = []
    for p in d.get("pares", [])[:150]:
        socios = ", ".join(s["nome"] for s in p.get("socios_comuns", [])[:3]) or "matriz × filial (mesmo CNPJ-raiz)"
        ls.append(f"<tr><td>{'🔴' if p['tier'] != 'MEDIA' else '🟡'} {_esc(p['tier'])}</td>"
                  f"<td>{_esc(p['vencedor']['nome'])}<br><small>{_esc(p['vencedor']['cnpj'])}</small></td>"
                  f"<td>{_esc(p['perdedora']['nome'])}<br><small>{_esc(p['perdedora']['cnpj'])}</small></td>"
                  f"<td><small>{_esc(socios)}</small></td>"
                  f"<td style='text-align:right'>{p['n_certames']}×<br><small>{_rs(p['valor_vencido'])}</small></td></tr>")
    return ("Conluio direto — vencedor × perdedora do mesmo dono",
            f"{d.get('n',0)} pares · {d.get('n_forte',0)} fortes (QSA/matriz-filial) · proposta de cobertura (OCDE)",
            [{"titulo": "1. Pares vencedor × perdedora com sócio em comum",
              "html": _tabela(["Tier", "Vencedor", "Perdedora", "Sócios comuns", "Certames"], ls)
              if ls else "<p>Nenhum par identificado na base atual.</p>"}], d)


def _b_comunidades(d):
    ls = []
    for c in d.get("comunidades", [])[:100]:
        emps = " · ".join(m["label"] for m in c.get("membros", []) if m["tipo"] == "empresa")
        sinais = ", ".join(s["sinal"] for s in c.get("sinais", [])) or "—"
        ls.append(f"<tr><td>{c['rating']} {c['score']}</td>"
                  f"<td>#{c['id']} · {c['n_empresas']} emp / {c['n_pessoas']} pes / {c['n_orgaos']} órg"
                  f"<br><small>{_esc(emps[:120])}</small></td>"
                  f"<td><small>{_esc(sinais)}</small></td>"
                  f"<td style='text-align:right'>{_rs(c['valor_total'])}</td></tr>")
    g = d.get("grafo", {})
    return ("Comunidades — clusters família-empresa-órgão (Louvain)",
            f"{d.get('n',0)} comunidades relevantes · grafo com {g.get('nos',0)} nós e {g.get('arestas',0)} arestas",
            [{"titulo": "1. Comunidades ranqueadas por risco (score 0-100)",
              "html": _tabela(["Score", "Comunidade", "Sinais", "Valor movimentado"], ls)}], d)


def _b_retro(d):
    lp = [f"<tr><td>{_esc(s)}</td><td style='text-align:right'>{v['n_sinais']}</td>"
          f"<td style='text-align:right'>{v['n_sancao_depois']}</td>"
          f"<td style='text-align:right'>{_rs(v['pago_depois'])}<br><small>{v['vitorias_depois']} vitória(s) PNCP depois</small></td></tr>"
          for s, v in sorted(d.get("por_sinal", {}).items())]
    lx = [f"<tr><td>{'⚖️' if e.get('sancao_depois') else '💸'}</td>"
          f"<td>{_esc(e['cnpj'])}<br><small>{_esc(e['sinal'])} · desde {_esc(e['desde'])}</small></td>"
          f"<td><small>{_esc((e.get('detalhe') or '')[:40])}"
          f"{(' · sanção em ' + _esc(e['sancao_depois'].get('data_inicio'))) if e.get('sancao_depois') else ''}</small></td>"
          f"<td style='text-align:right'>{_rs(e['pago_depois'])}</td></tr>"
          for e in d.get("exemplos", [])[:60]]
    j = d.get("janela", {})
    return ("Retro-auditoria — o que aconteceu DEPOIS do alerta",
            f"janela de {j.get('sinal_mais_antigo_dias', '—')} dia(s) de ledger · sanção posterior corrobora · pago após = custo da inação",
            [{"titulo": "1. Hindsight por detector",
              "html": _tabela(["Detector", "Sinais", "Sanção depois", "Pago depois"], lp)},
             {"titulo": "2. Casos (sanção posterior ou pagamento pós-alerta)", "page_break": True,
              "html": _tabela(["", "Empresa / sinal", "Detalhe", "Pago após"], lx) if lx else "<p>Nenhum.</p>"}], d)


def _d_comunidades(p):
    # cache do intel primeiro (construir o grafo completo é pesado p/ o request); fallback = computa sem d3
    from compliance_agent.cruzamentos_intel import ler_cache_intel
    d = ler_cache_intel("comunidades")
    if not (d and d.get("ok")):
        from compliance_agent.grafo_comunidades import detectar_comunidades
        d = detectar_comunidades(db_path=p, incluir_grafo_d3=False)
    return d


def _d_retro(p):
    from compliance_agent.retro_auditoria import medir
    d = medir(db_path=p)
    if d.get("ok"):
        d["n"] = sum(v["n_sinais"] for v in d.get("por_sinal", {}).values())
    return d


# tipo → (função-detector com db_path opcional, builder, faixa)
def _detectores():
    from compliance_agent import cruzamentos_intel as C
    return {
        "conluio": (_d_conluio, _b_conluio, "ALTO"),
        "nomeados": (_d_nomeados, _b_nomeados, "MÉDIO"),
        "comissionados": (_d_comissionados, _b_comissionados, "MÉDIO"),
        "sancionadas": (lambda p: C.sancionadas_contratadas(p), _b_sancionadas, "ALTO"),
        "fracionamento": (lambda p: C.fracionamento(db_path=p), _b_fracionamento, "ALTO"),
        "sobrepreco": (lambda p: C.sobrepreco(db_path=p), _b_sobrepreco, "ALTO"),
        "aditivos": (lambda p: C.aditivos_estouro(db_path=p), _b_aditivos, "ALTO"),
        "socio_servidor": (lambda p: C.socio_servidor(db_path=p), _b_socio_servidor, "EXTREMO"),
        "fornecedor_dependente": (lambda p: C.fornecedor_dependente(db_path=p), _b_fornecedor_dependente, "MÉDIO"),
        "corrida_dezembro": (lambda p: C.corrida_dezembro(db_path=p), _b_corrida_dezembro, "MÉDIO"),
        "socio_oculto": (lambda p: C.socio_oculto(db_path=p), _b_socio_oculto, "ALTO"),
        "nepotismo": (lambda p: C.nepotismo(db_path=p), _b_nepotismo, "ALTO"),
        "fenix": (lambda p: C.empresa_fenix(db_path=p), _b_fenix, "ALTO"),
        "porta_giratoria": (lambda p: C.porta_giratoria(db_path=p), _b_porta, "ALTO"),
        "nepotismo_cruzado": (lambda p: C.nepotismo_cruzado(db_path=p), _b_nepcruz, "ALTO"),
        "fantasmas": (lambda p: C.ranking_fantasmas(db_path=p, limite=150), _b_fantasmas, "ALTO"),
        "perdedoras": (lambda p: C.perdedoras_contumazes(db_path=p), _b_perdedoras, "MÉDIO"),
        "radar_risco": (lambda p: C.radar_risco(db_path=p), _b_radar, "ALTO"),
        "conluio_qsa": (lambda p: C.conluio_qsa(db_path=p, incluir_atas=False), _b_conluio_qsa, "ALTO"),
        "comunidades": (_d_comunidades, _b_comunidades, "ALTO"),
        "retro": (_d_retro, _b_retro, "MÉDIO"),
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
