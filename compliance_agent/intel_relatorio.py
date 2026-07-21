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
    for e in d.get("empresas", [])[:1000]:
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
          for g in d.get("grupos", [])[:1000]]
    return ("Fracionamento de despesa — fatiar para não licitar",
            f"{d.get('n',0)} grupos favorecido+UG+mês com OBs coladas no teto de dispensa",
            [{"titulo": "1. Grupos com concentração colada no teto",
              "html": _tabela(["Conc.", "Favorecido / UG / mês", "OBs coladas", "Soma"], ls)}], d)


def _b_sobrepreco(d):
    ls = [f"<tr><td>{a['razao']}×</td><td>{_esc(a['item'])}{(' / '+_esc(a['unidade_medida'])) if a.get('unidade_medida') else ''}</td>"
          f"<td>{_esc((a.get('orgao') or '')[:40])}<br><small>venc.: {_esc(a.get('fornecedor'))}</small></td>"
          f"<td style='text-align:right'>{_rs(a['preco'])}<br><small>mediana {_rs(a['mediana'])} (n={a['amostra']})</small></td></tr>"
          for a in d.get("achados", [])[:1000]]
    return ("Sobrepreço por mediana de item (PNCP)",
            f"{d.get('n',0)} itens com preço unitário ≥2× a mediana do grupo · {d.get('grupos_comparaveis',0)} grupos",
            [{"titulo": "1. Itens pagos muito acima da mediana",
              "html": _tabela(["× med", "Item", "Órgão / vencedor", "Preço unit."], ls)}], d)


def _b_escalada(d):
    ls = [f"<tr><td>{a['razao']}×</td><td>{_esc(a['item'])}{(' / '+_esc(a['unidade_medida'])) if a.get('unidade_medida') else ''}"
          f"<br><small>{_esc(a.get('fornecedor'))}</small></td>"
          f"<td>{a['n_compras']} compras / {a['span_dias']}d"
          f"{('<br><small>'+str(a['final_vs_mercado'])+'× o mercado</small>') if a.get('final_vs_mercado') else ''}</td>"
          f"<td style='text-align:right'>{_rs(a['preco_inicial'])} → {_rs(a['preco_final'])}</td></tr>"
          for a in d.get("achados", [])[:1000]]
    return ("Escalada de preço unitário (mesmo fornecedor, mesmo item)",
            f"{d.get('n',0)} escaladas: o mesmo fornecedor subiu o preço do mesmo item ≥3× no tempo",
            [{"titulo": "1. Fornecedores que escalaram o preço do próprio item",
              "html": _tabela(["× alta", "Item / fornecedor", "Compras / janela", "Inicial → final"], ls)}], d)


def _b_aditivos(d):
    ls = [f"<tr><td>{'🔴' if a['estoura_teto'] else '🟡'}</td><td>{_esc(a.get('fornecedor'))}<br><small>{_esc((a.get('orgao') or '')[:40])}</small></td>"
          f"<td>{('+'+str(a['pct'])+'%') if a['estoura_teto'] else str(a['num_aditivos'])+' aditivos'} (teto {a['teto_pct']}%)</td>"
          f"<td style='text-align:right'>{_rs(a['valor_inicial'])} → {_rs(a['valor_global'])}</td></tr>"
          for a in d.get("achados", [])[:1000]]
    return ("Aditivos que estouram o limite legal",
            f"{d.get('n_estoura_teto',0)} estouram o teto (25%/50%) · {d.get('n_serie',0)} com ≥3 aditivos",
            [{"titulo": "1. Contratos com acréscimo acima do limite / aditivos em série",
              "html": _tabela(["", "Fornecedor / órgão", "Acréscimo", "Inicial → global"], ls)}], d)


def _b_socio_servidor(d):
    ls = [f"<tr><td>{'🔴' if a.get('mesmo_orgao') else ('⚖️' if a['gerencia'] else '🟡')}</td>"
          f"<td>{_esc(a['socio'])}<br><small>{_esc(a['qualificacao'])} de {_esc(a['empresa'])}</small></td>"
          f"<td>{_esc(a['servidor_cargo'])} · {_esc((a['servidor_orgao'] or '')[:34])}</td>"
          f"<td style='text-align:right'>{_rs(a['total_pago'])}<br><small>{a['confianca']}</small></td></tr>"
          for a in d.get("achados", [])[:1000]]
    return ("Servidor público sócio de fornecedor do Estado",
            f"{d.get('n',0)} servidores · {d.get('n_gerencia',0)} com gerência (vedada) · {d.get('n_art9',0)} art. 9",
            [{"titulo": "1. Servidores sócios de fornecedores",
              "html": _tabela(["", "Servidor / empresa", "Cargo / órgão", "Recebido"], ls)}], d)


def _b_fornecedor_dependente(d):
    ls = [f"<tr><td>{int(a['share']*100)}%</td><td>{_esc(a['nome'])}<br><small>{_esc(a['cnpj_fmt'])}</small></td>"
          f"<td>UG {a['ug']} {_esc(a.get('ug_nome',''))}</td><td style='text-align:right'>{_rs(a['total'])}</td></tr>"
          for a in d.get("achados", [])[:1000]]
    return ("Fornecedor dependente — 'empresa do órgão'",
            f"{d.get('n',0)} fornecedores comerciais com ≥90% da receita em UMA unidade gestora",
            [{"titulo": "1. Empresas cativas de um único comprador",
              "html": _tabela(["Depend.", "Empresa", "Unidade gestora", "Total recebido"], ls)}], d)


def _b_corrida_dezembro(d):
    ls = [f"<tr><td>{int(a['share']*100)}%</td><td>{_esc(a['nome'])}<br><small>{_esc(a['cnpj_fmt'])}</small></td>"
          f"<td style='text-align:right'>{_rs(a['dezembro'])} em dez.</td><td style='text-align:right'>{_rs(a['total'])}</td></tr>"
          for a in d.get("achados", [])[:1000]]
    return ("Corrida do empenho de dezembro",
            f"{d.get('n',0)} fornecedores comerciais com ≥75% do valor concentrado em dezembro",
            [{"titulo": "1. Concentração de pagamentos no fim do exercício",
              "html": _tabela(["% dez.", "Empresa", "Em dezembro", "Total ano"], ls)}], d)


def _b_socio_oculto(d):
    ls = [f"<tr><td>{a['n_empresas']}</td><td>{_esc(a['socio'])}</td>"
          f"<td><small>{_esc(', '.join(a['empresas'][:4]))}</small></td>"
          f"<td style='text-align:right'>{_rs(a['total'])}</td></tr>"
          for a in d.get("achados", [])[:1000]]
    return ("Sócio oculto — um dono, vários fornecedores",
            f"{d.get('n',0)} pessoas/holdings sócias de ≥3 empresas fornecedoras do Estado",
            [{"titulo": "1. Concentração societária entre fornecedores",
              "html": _tabela(["Empresas", "Sócio / holding", "Fornecedoras (amostra)", "Total recebido"], ls)}], d)


def _b_fantasmas(d):
    ls = [f"<tr><td>{a.get('score','—')}</td><td>{_esc(a.get('razao_social') or a['cnpj'])}<br><small>{_esc(a['cnpj'])} · {_esc(a.get('origem'))}</small></td>"
          f"<td>{_esc(', '.join(s.get('id','') for s in a.get('sinais',[])[:4]))}</td><td>{_esc(a.get('classificacao'))}</td></tr>"
          for a in d.get("empresas", [])[:1000] if a.get("classificacao") != "sem_cadastro"]
    return ("Radar de empresas-fantasma",
            f"{d.get('total_alvo',0)} no alvo · {d.get('sem_cadastro',0)} sem cadastro",
            [{"titulo": "1. Empresas com sinais de fachada", "html": _tabela(["Score", "Empresa", "Sinais", "Risco"], ls)}], d)


def _b_fenix(d):
    ls = [f"<tr><td>{'🔴' if a['tipo']=='defunta' else '🟡'}</td><td>{_esc(a['nome'])}<br><small>{_esc(a['cnpj'])}</small></td>"
          f"<td>{_esc(a['situacao'] or '')} · aberta {_esc(a['data_abertura'])} · 1ª OB {_esc(a['primeira_ob'])}</td>"
          f"<td style='text-align:right'>{_rs(a['total_recebido'])}</td></tr>" for a in d.get("achados", [])[:1000]]
    return ("Empresas fênix — defunta ou aberta às vésperas",
            f"{d.get('n',0)} empresas · {d.get('n_defunta',0)} baixadas/inaptas que receberam",
            [{"titulo": "1. Empresas de risco (situação × pagamento)", "html": _tabela(["", "Empresa", "Situação / datas", "Recebido"], ls)}], d)


def _b_porta(d):
    ls = [f"<tr><td>{_esc(a['socio'])}<br><small>{_esc(a['qualificacao'])} de {_esc(a['empresa'])}</small></td>"
          f"<td>ex: {_esc(a['ex_cargo'])} · {_esc((a['ex_orgao'] or '')[:30])} ({_esc(a['vinculo'])})</td>"
          f"<td style='text-align:right'>{_rs(a['total_pago'])}<br><small>{a['confianca']}</small></td></tr>"
          for a in d.get("achados", [])[:1000]]
    return ("Porta giratória — ex-servidor virou fornecedor",
            f"{d.get('n',0)} ex-servidores sócios de fornecedores do Estado",
            [{"titulo": "1. Ex-servidores sócios de fornecedores", "html": _tabela(["Sócio / empresa", "Ex-cargo / órgão", "Recebido"], ls)}], d)


def _b_nepcruz(d):
    ls = [f"<tr><td>{_esc(a['sobrenome_a'])} ⇄ {_esc(a['sobrenome_b'])}</td>"
          f"<td>{_esc((a['orgao_a'] or '')[:26])}<br><small>autoridade: {_esc(a['autoridade_a'])}</small></td>"
          f"<td>{_esc((a['orgao_b'] or '')[:26])}<br><small>autoridade: {_esc(a['autoridade_b'])}</small></td></tr>"
          for a in d.get("achados", [])[:1000]]
    return ("Nepotismo cruzado — colocação recíproca entre órgãos",
            f"{d.get('n',0)} pares recíprocos (dribla a SV13 do mesmo órgão)",
            [{"titulo": "1. Pares recíprocos A⇄B", "html": _tabela(["Sobrenomes", "Órgão A", "Órgão B"], ls)}], d)


def _b_nepotismo(d):
    ls = []
    for a in d.get("achados", [])[:1000]:
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
          for p in d.get("perdedoras", [])[:1000]]
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
            "JOIN _cand c ON UPPER(TRIM(f.nome))=c.nc ORDER BY f.nome LIMIT 2000").fetchall()
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
          for x in d.get("itens", [])[:1000]]
    return ("Servidores × candidatos (folha × TSE)",
            f"{d.get('n',0)} servidores que também foram candidatos",
            [{"titulo": "1. Cruzamento nome a nome", "html": _tabela(["", "Servidor", "Órgão / cargo", "Disputou"], ls)}], d)


def _d_comissionados(p):
    import sqlite3

    from compliance_agent.pcrj.comissionados_candidatos import agrupar_por_pessoa
    con = sqlite3.connect(f"file:{p.replace('compliance.db','pcrj.db')}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in con.execute(
            "SELECT nome_norm, nome_pcrj, cargo_pcrj, orgao_pcrj, admissao, exoneracao, "
            "matricula, cand_ano, cand_cargo, cand_cidade FROM pcrj_comissionado_candidato")]
    finally:
        con.close()
    pessoas = agrupar_por_pessoa(rows)
    return {"ok": True, "itens": pessoas, "n": len(pessoas),
            "ressalva": "1 linha por PESSOA (histórico de nomeações agregado); match por NOME — "
                        "confirmar por CPF antes de citar."}


def _b_comissionados(d):
    ls = []
    for x in d.get("itens", [])[:1000]:
        postos = "<br>".join(
            f"<small>{_esc(p['cargo'] or '—')} · {_esc((p['orgao'] or '—')[:40])} · "
            f"{_esc(p['admissao'] or '?')}{' → ' + _esc(p['exoneracao']) if p['exoneracao'] else ' (ativo)'}</small>"
            for p in x.get("postos", []))
        cands = " · ".join(f"{_esc(c['cargo'] or '?')} {_esc(str(c['ano'] or ''))} ({_esc(c['cidade'] or '?')})"
                           for c in x.get("candidaturas", []))
        ls.append(f"<tr><td>{_esc(x['nome_pcrj'])}{' ⚠ homônimo?' if x.get('homonimo_provavel') else ''}</td>"
                  f"<td>{postos}</td><td><small>{cands}</small></td></tr>")
    return ("Comissionados da Prefeitura do Rio × candidaturas (TSE)",
            f"{d.get('n',0)} pessoas (histórico completo de nomeações por pessoa)",
            [{"titulo": "1. Cargo de confiança × disputa eleitoral — por pessoa",
              "html": _tabela(["Pessoa", "Histórico de nomeações", "Candidaturas"], ls)}], d)


def _d_certames(p):
    from compliance_agent.editais.avaliacao_conjunto import avaliar_portfolio, avaliar_unidades
    pf = avaliar_portfolio(db_path=p)
    un = avaliar_unidades(db_path=p)
    return {"ok": True, "orgaos": pf.get("orgaos", []), "unidades": un.get("unidades", []),
            "mediana_pares": pf.get("mediana_pares"), "n": pf.get("n_orgaos", 0),
            "ressalva": "Mediana só sobre certames com confiança>0 (≥1 família analisável); "
                        "indexado sem análise = INDISPONÍVEL (≠ 0). Indício ≠ acusação."}


def _b_certames(d):
    def _linha(nome, x):
        med = f"{x['score_mediana']:.0f}" if x.get("score_mediana") is not None else "—"
        p90 = f"{x['score_p90']:.0f}" if x.get("score_p90") is not None else "—"
        dv = x.get("desvio_vs_pares")
        return (f"<tr><td>{_esc(nome)}</td>"
                f"<td style='text-align:right'>{x.get('n_avaliados', 0)}/{x.get('n_certames_indexados', x.get('n_certames', 0))}</td>"
                f"<td style='text-align:right'>{med}</td><td style='text-align:right'>{p90}</td>"
                f"<td style='text-align:right'>{('%+.0f' % dv) if dv is not None else '—'}</td>"
                f"<td style='text-align:right'>{x.get('n_alto_extremo', 0)}</td></tr>")
    cab = ["Órgão / unidade", "Avaliados/indexados", "Mediana", "p90", "vs pares", "ALTO/EXTREMO"]
    lo = [_linha(x.get("orgao_nome") or x.get("orgao_cnpj"), x) for x in d.get("orgaos", [])]
    lu = [_linha(x["unidade"], x) for x in d.get("unidades", [])]
    secoes = [{"titulo": "1. Índice de Direcionamento por órgão (conjunto)", "html": _tabela(cab, lo)}]
    if lu:
        secoes.append({"titulo": "2. Por unidade / secretaria", "html": _tabela(cab, lu)})
    return ("Certames — o padrão de cada órgão licitante",
            f"{d.get('n',0)} órgão(s) avaliados como conjunto (mediana dos pares "
            f"{d.get('mediana_pares') if d.get('mediana_pares') is not None else '—'})", secoes, d)


def _d_beneficios(p):
    from compliance_agent.cruzamentos_intel import ler_cache_intel
    d = ler_cache_intel("beneficios_vinculo") or {}
    if not d.get("ok"):
        return {"ok": False, "erro": "cache beneficios_vinculo ainda não gerado"}
    d.setdefault("n", len(d.get("casos", [])))
    return d


def _b_beneficios(d):
    r = d.get("resumo", {})
    ls = [f"<tr><td>{'✓' if x.get('certeza') == 'ALTA' else '?'} {_esc(x['nome'])}</td>"
          f"<td><small>{_esc((x.get('orgao') or '—')[:38])} · {_esc((x.get('cargo') or '—')[:30])}</small></td>"
          f"<td><small>{_esc(x.get('beneficios_str') or '—')}</small></td>"
          f"<td>{_esc(x.get('desde') or '?')}→{_esc(x.get('ate') or '?')} ({x.get('n_meses') or '?'}m)"
          f"{' · <b>ainda recebe</b>' if x.get('ainda_recebe') else ''}</td></tr>"
          for x in d.get("casos", [])]
    return ("Servidores × benefício social — DURANTE o vínculo (Prefeitura/Câmara)",
            f"{len(d.get('casos', []))} casos no período ({r.get('n_alta', 0)} com identidade confirmada; "
            f"{r.get('n_ainda', 0)} ainda recebendo)",
            [{"titulo": "1. Benefício recebido dentro da janela do vínculo (nível de mês)",
              "html": _tabela(["Servidor (✓=identidade)", "Órgão · cargo", "Benefícios", "Janela"], ls)}], d)


def _d_fantasmas_pcrj(p):
    import sqlite3
    con = sqlite3.connect(f"file:{p.replace('compliance.db','pcrj.db')}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        it = [dict(r) for r in con.execute(
            "SELECT nome, gabinetes, cargos_camara, sinais, score, faixa, homonimo "
            "FROM pcrj_fantasma_servidor ORDER BY score DESC")]
    finally:
        con.close()
    return {"ok": True, "itens": it, "n": len(it),
            "ressalva": "Funil de priorização OSINT (8 sinais determinísticos) — a prova definitiva "
                        "é o ponto/frequência interno, que só a apuração formal alcança."}


def _b_fantasmas_pcrj(d):
    ls = [f"<tr><td>{'🔴' if x['faixa'] == 'forte' else '🟡' if x['faixa'] == 'verificar' else '⚪'} "
          f"{x['score']}</td><td>{_esc(x['nome'])}{' ⚠ homônimo?' if x.get('homonimo') else ''}</td>"
          f"<td><small>{_esc((x.get('gabinetes') or '—')[:44])}</small></td>"
          f"<td><small>{_esc((x.get('sinais') or '')[:120])}</small></td></tr>"
          for x in d.get("itens", [])[:1500]]
    return ("Sinais de servidor-fantasma — Câmara/Prefeitura do Rio",
            f"{d.get('n', 0)} servidores com sinal, ordenados por score",
            [{"titulo": "1. Escore composto (8 sinais determinísticos)",
              "html": _tabela(["Faixa/score", "Servidor", "Gabinetes", "Sinais"], ls)}], d)


def _d_gastos_pcrj(p):
    import sqlite3
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            """SELECT tipo, severidade, titulo, descricao, MAX(id) id FROM alertas
               WHERE tipo LIKE 'pcrj_d%' GROUP BY titulo
               ORDER BY CASE severidade WHEN 'alta' THEN 0 WHEN 'media' THEN 1 ELSE 2 END, id DESC
            """).fetchall()
    finally:
        con.close()
    it = [dict(r) for r in rows]
    return {"ok": True, "itens": it, "n": len(it),
            "ressalva": "Perícia determinística D7-D12 sobre despesa por credor (CGM) + PNCP "
                        "municipal. Indício ≠ acusação; match por NOME vem sinalizado."}


def _b_gastos_pcrj(d):
    ls = [f"<tr><td>{'🔴' if x['severidade'] == 'alta' else '🟡' if x['severidade'] == 'media' else '⚪'}</td>"
          f"<td>{_esc(x['tipo'].replace('pcrj_', ''))}</td><td>{_esc(x['titulo'])}"
          f"<br><small>{_esc((x.get('descricao') or '')[:220])}</small></td></tr>"
          for x in d.get("itens", [])[:1500]]
    return ("Perícia de gastos da Prefeitura — achados D7-D12",
            f"{d.get('n', 0)} achados (fracionamento, credor recém-aberto, sócio na folha, "
            "rede entre concorrentes, aditivo estourado, coendereço)",
            [{"titulo": "1. Achados por severidade", "html": _tabela(["Sev.", "Detector", "Achado"], ls)}], d)


def _d_contratos_analise(p):
    import json as _json
    import sqlite3
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            """SELECT ed.numero_controle_pncp nc, ed.ano, ed.objeto, ed.valor_estimado,
                      ci.score, ci.faixa, ci.confianca, ci.drivers_json
               FROM edital_documento ed JOIN certame_indice ci
               ON ci.certame = ed.numero_controle_pncp
               WHERE substr(ed.orgao_cnpj,1,8) IN ('42498733','42498600') AND ci.confianca > 0
               ORDER BY ci.prioridade DESC""").fetchall()
    finally:
        con.close()
    it = []
    for r in rows:
        drivers = []
        try:
            drivers = [f"{x['familia']}: {x['flag']}" for x in _json.loads(r["drivers_json"] or "[]")]
        except (ValueError, TypeError, KeyError):
            pass
        it.append({**{k: r[k] for k in ("nc", "ano", "objeto", "valor_estimado", "score", "faixa",
                                        "confianca")}, "drivers": drivers})
    return {"ok": True, "itens": it, "n": len(it),
            "ressalva": "Só certames com confiança>0 (≥1 família analisável) — indexado sem análise "
                        "= INDISPONÍVEL (≠ 0). Índice determinístico e auditável; indício ≠ acusação."}


def _b_contratos_analise(d):
    ls = [f"<tr><td>{'🔴' if x['faixa'] in ('ALTO', 'EXTREMO') else '🟡' if x['faixa'] == 'MEDIO' else '⚪'} "
          f"{x['score']:.0f}</td><td><small>{_esc(x['nc'])}</small><br>{_esc((x['objeto'] or '—')[:110])}</td>"
          f"<td style='text-align:right'>{_rs(x['valor_estimado']) if x['valor_estimado'] else '—'}</td>"
          f"<td><small>{_esc('; '.join(x['drivers'][:4]) or '—')}</small></td></tr>"
          for x in d.get("itens", [])[:1500]]
    return ("Contratações Estado + Município — cada certame com a sua análise",
            f"{d.get('n', 0)} certames com Índice de Direcionamento calculado (temas nas 7 famílias)",
            [{"titulo": "1. Certames analisados, por prioridade",
              "html": _tabela(["Índice", "Certame / objeto", "Valor estimado", "O que disparou"], ls)}], d)


def _b_capital(d):
    ls = [f"<tr><td>{_esc(a['nome'])}<br><small>{_esc(a['cnpj_fmt'])}</small></td>"
          f"<td style='text-align:right'>{_rs(a['capital'])}</td>"
          f"<td style='text-align:right'>{_rs(a['total_recebido'])}</td>"
          f"<td style='text-align:right'>{a['razao']:,}×</td>"
          f"<td style='text-align:right'>{a['n_obs']}</td></tr>".replace(",", ".")
          for a in d.get("achados", [])[:1000]]
    return ("Capital irrisório — sem lastro para o que faturou",
            f"{d.get('n',0)} empresas com capital <R$50 mil recebendo ≥100× o próprio capital",
            [{"titulo": "1. Subcapitalização frente ao volume recebido (Lei 14.133 art. 62-63)",
              "html": _tabela(["Empresa", "Capital social", "Recebido (OB)", "Razão", "OBs"], ls)}], d)


def _b_prioridade(d):
    ls = [f"<tr><td>{a['rating']} {a['score']}</td><td>{_esc(a['nome'])}<br><small>{_esc(a['cnpj_fmt'])}</small></td>"
          f"<td style='text-align:right'>{_rs(a['economia'])}</td>"
          f"<td style='text-align:right'>{a['n_compras']}</td>"
          f"<td><small>{_esc(', '.join(a.get('sinais', [])[:6]))}</small></td></tr>"
          for a in d.get("achados", [])[:1000]]
    return ("Prioridade — onde a auditoria rende mais (risco × dinheiro)",
            f"{d.get('n',0)} fornecedores no radar com economia recuperável "
            f"(total em risco {_rs(d.get('economia_em_risco') or 0)})",
            [{"titulo": "1. Fila risco × economia potencial",
              "html": _tabela(["Score", "Empresa / CNPJ", "Economia potencial", "Compras", "Sinais"], ls)}], d)


def _b_radar(d):
    ls = [f"<tr><td>{a['rating']} {a['score']}</td><td>{_esc(a['nome'])}<br><small>{_esc(a['cnpj_fmt'])}</small></td>"
          f"<td>{a['n_sinais']}</td><td><small>{_esc(', '.join(s['sinal'] for s in a.get('sinais', [])[:6]))}</small></td></tr>"
          for a in d.get("achados", [])[:1000]]
    return ("Radar de risco — todos os detectores somados",
            f"{d.get('n',0)} fornecedores com sinal · {d.get('n_vermelho',0)} com score ≥50 (🔴)",
            [{"titulo": "1. Fila de apuração priorizada (score composto 0-100)",
              "html": _tabela(["Score", "Empresa / CNPJ", "Nº", "Sinais"], ls)}], d)


def _b_conluio_qsa(d):
    ls = []
    for p in d.get("pares", [])[:1000]:
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
    for c in d.get("comunidades", [])[:1000]:
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
          for e in d.get("exemplos", [])[:1000]]
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
    # limite=1000 aqui: o PDF é "baixar TUDO" — bem acima do cap de 120-150 usado na TELA
    # (esse cap de tela continua existindo, é sobre performance de DOM, não sobre o dado).
    L = 1000
    return {
        "conluio": (_d_conluio, _b_conluio, "ALTO"),
        "nomeados": (_d_nomeados, _b_nomeados, "MÉDIO"),
        "comissionados": (_d_comissionados, _b_comissionados, "MÉDIO"),
        "sancionadas": (lambda p: C.sancionadas_contratadas(p), _b_sancionadas, "ALTO"),
        "fracionamento": (lambda p: C.fracionamento(db_path=p, limite=L), _b_fracionamento, "ALTO"),
        "sobrepreco": (lambda p: C.sobrepreco(db_path=p, limite=L), _b_sobrepreco, "ALTO"),
        "escalada": (lambda p: C.escalada_preco(db_path=p, limite=L), _b_escalada, "ALTO"),
        "aditivos": (lambda p: C.aditivos_estouro(db_path=p, limite=L), _b_aditivos, "ALTO"),
        "socio_servidor": (lambda p: C.socio_servidor(db_path=p, limite=L), _b_socio_servidor, "EXTREMO"),
        "fornecedor_dependente": (lambda p: C.fornecedor_dependente(db_path=p, limite=L), _b_fornecedor_dependente, "MÉDIO"),
        "corrida_dezembro": (lambda p: C.corrida_dezembro(db_path=p, limite=L), _b_corrida_dezembro, "MÉDIO"),
        "socio_oculto": (lambda p: C.socio_oculto(db_path=p, limite=L), _b_socio_oculto, "ALTO"),
        "nepotismo": (lambda p: C.nepotismo(db_path=p, limite=L), _b_nepotismo, "ALTO"),
        "fenix": (lambda p: C.empresa_fenix(db_path=p, limite=L), _b_fenix, "ALTO"),
        "porta_giratoria": (lambda p: C.porta_giratoria(db_path=p, limite=L), _b_porta, "ALTO"),
        "nepotismo_cruzado": (lambda p: C.nepotismo_cruzado(db_path=p, limite=L), _b_nepcruz, "ALTO"),
        "fantasmas": (lambda p: C.ranking_fantasmas(db_path=p, limite=L), _b_fantasmas, "ALTO"),
        "perdedoras": (lambda p: C.perdedoras_contumazes(db_path=p), _b_perdedoras, "MÉDIO"),
        "radar_risco": (lambda p: C.radar_risco(db_path=p, limite=L), _b_radar, "ALTO"),
        "conluio_qsa": (lambda p: C.conluio_qsa(db_path=p, limite=L, incluir_atas=False), _b_conluio_qsa, "ALTO"),
        "comunidades": (_d_comunidades, _b_comunidades, "ALTO"),
        "retro": (_d_retro, _b_retro, "MÉDIO"),
        "certames": (_d_certames, _b_certames, "ALTO"),
        "beneficios": (_d_beneficios, _b_beneficios, "MÉDIO"),
        "fantasmas_pcrj": (_d_fantasmas_pcrj, _b_fantasmas_pcrj, "ALTO"),
        "gastos_pcrj": (_d_gastos_pcrj, _b_gastos_pcrj, "ALTO"),
        "contratos_analise": (_d_contratos_analise, _b_contratos_analise, "ALTO"),
        "capital_incompativel": (lambda p: C.capital_incompativel(db_path=p, limite=L), _b_capital, "ALTO"),
        "prioridade_valor": (lambda p: C.prioridade_valor(db_path=p, limite=L), _b_prioridade, "ALTO"),
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
