#!/usr/bin/env python3
"""RELATÓRIO COMPLETO da Perícia do Corpo de Bombeiros (FUNESBOM/CBMERJ) 2024+ — padrão JFN/Lex (Kroll).
Render HTML→PDF da casa (compliance_agent.reporting.render_html). Puxa TODAS as camadas:
execução orçamentária, concentração/redes (dados), perícia documental Lex×Claude (reconciliação +
lex_execucao + leitura própria dos casos prioritários), integridade do ecossistema, matriz de risco P×I,
recomendações, proveniência. Honestidade: indício≠acusação · INDISPONÍVEL≠0 · empenho≠liquidação≠OB.
Uso: .venv/bin/python tools/relatorio_bombeiros.py [--enviar]"""
import sqlite3, json, asyncio, sys, pathlib, datetime
from compliance_agent.reporting.render_html import render_html, html_to_pdf

DB = "/home/ubuntu/JFN/data/compliance.db"
REC = "/home/ubuntu/JFN/reports/_pericia_bombeiros_reconciliacao.json"
FILA = "/home/ubuntu/JFN/data/bombeiros_sei_fila.json"

def con(): return sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=20)
def brl(v): return f"R$ {(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
def tab(head, rows):
    h = "".join(f"<th>{c}</th>" for c in head)
    b = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table>"

def dados():
    c = con().cursor()
    d = {}
    d["exec"] = c.execute("""SELECT exercicio,ug,ROUND(SUM(empenhado),2),ROUND(SUM(liquidado),2),ROUND(SUM(pago),2)
        FROM despesa_execucao WHERE ug IN ('166100','160100') AND exercicio>='2024' GROUP BY exercicio,ug ORDER BY exercicio,ug""").fetchall()
    d["elem"] = c.execute("""SELECT elemento,ROUND(SUM(pago),2) FROM despesa_execucao
        WHERE ug='166100' AND exercicio='2024' GROUP BY elemento ORDER BY 2 DESC LIMIT 8""").fetchall()
    d["ob_ano"] = c.execute("""SELECT exercicio,COUNT(*),ROUND(SUM(valor),2) FROM ordens_bancarias
        WHERE ug_codigo='166100' AND exercicio>=2024 AND valor>0 GROUP BY exercicio ORDER BY exercicio""").fetchall()
    d["top"] = c.execute("""SELECT favorecido_nome,favorecido_cpf,COUNT(*),ROUND(SUM(valor),2) FROM ordens_bancarias
        WHERE ug_codigo='166100' AND exercicio>=2024 AND valor>0 GROUP BY favorecido_cpf ORDER BY 4 DESC LIMIT 15""").fetchall()
    d["tot_ob"] = c.execute("SELECT COUNT(*),ROUND(SUM(valor),2) FROM ordens_bancarias WHERE ug_codigo='166100' AND exercicio>=2024 AND valor>0").fetchone()
    d["contr"] = c.execute("""SELECT COUNT(DISTINCT processo),ROUND(SUM(valor_contrato),2) FROM
        (SELECT DISTINCT processo,valor_contrato FROM contratos_tcerj WHERE unidade LIKE '%BOMBEIR%' AND CAST(ano_processo AS INT)>=2024 AND valor_contrato>0)""").fetchone()
    d["coletados"] = c.execute("SELECT COUNT(*) FROM sei_ficha WHERE numero_sei LIKE 'SEI-2700%' AND n_docs>0").fetchone()[0]
    d["redes"] = c.execute("""SELECT nome_socio,n_fornecedores,ROUND(total_recebido,2) FROM rede_socios_fornecedores
        WHERE cnpjs_basicos LIKE '%33049503%' OR cnpjs_basicos LIKE '%03314057%' ORDER BY total_recebido DESC LIMIT 4""").fetchall()
    # perícia Lex×Claude (reconciliação)
    try: d["rec"] = json.load(open(REC))
    except Exception: d["rec"] = []
    return d

# Casos prioritários — leitura documental própria (Claude), com base legal e evidência verificada nos autos
CASOS = [
 {"sei":"SEI-270006/012128/2024","forn":"ANGLOCO LIMITED (Reino Unido)","valor":77000000,"risco":"ALTO",
  "objeto":"Aquisição de viatura leve de busca e resgate (ABSL), importação direta",
  "lex":"alto (carta de crédito sem processo instrutivo)","claude":"ALTO",
  "evid":"Carta de crédito documentária nº 07141763630 (Banco do Brasil/Barclays), EUR 3.490.124,59, beneficiário ANGLOCO LIMITED; Proforma Invoice PI10001 (31/07/2025). Íntegra: 86 docs / 357 págs enviada.",
  "achado":"Importação direta de fornecedor estrangeiro ÚNICO sem demonstração, no dossiê coletado, de processo licitatório/justificativa de inexigibilidade por exclusividade. Despesa em EUR (risco cambial) com carta de crédito de validade ~2 anos. <b>Descasamento de valor a reconciliar:</b> EUR 3,49 mi (≈R$ 22 mi) nesta carta vs. R$ 77 mi do contrato registrado no TCE-RJ (possível fornecimento múltiplo ou divergência).",
  "base":"Lei 14.133/2021, art. 74 (inexigibilidade exige inviabilidade de competição comprovada por exclusividade); art. 18 (planejamento/ETP); cambial: necessidade de lastro orçamentário.",
  "acao":"Requisitar o processo licitatório/de exclusividade; reconciliar EUR×total; verificar pesquisa de preços internacional e ART/atesto de entrega."},
 {"sei":"SEI-270006/006444/2024","forn":"AstraZeneca / FUNESBOM (Pregão PE-022/24)","valor":3778049,"risco":"MÉDIO-ALTO",
  "objeto":"Registro de preços — medicamentos quimioterápicos (CBMERJ)",
  "lex":"médio","claude":"MÉDIO-ALTO",
  "evid":"Ata 0006/2025/166100 (PE-022/24), vigência 03/04/2025–03/04/2026; Edital PE-022/24; existência simultânea da Ata 0005/2025 mesmo objeto/vigência; gestor da ata com e-mail pessoal (gmail).",
  "achado":"<b>Duas atas (0005 e 0006/2025)</b> para o MESMO objeto, mesma modalidade e MESMA vigência sem justificativa de divisão em lotes — indício de fracionamento/duplicidade de objeto. Designação de gestor de ata com <b>e-mail pessoal</b> em vez de institucional (falha de governança/rastreabilidade).",
  "base":"Lei 14.133/2021, art. 82-86 (SRP — vedação a fracionamento indevido); Decreto de governança de contratos; princípio da segregação de funções.",
  "acao":"Confrontar lotes das Atas 0005 vs 0006; verificar quantitativos e se houve duplicidade de aquisição; regularizar a designação do gestor."},
 {"sei":"SEI-270006/019098/2025","forn":"Fleet Cards Gestão de Frotas Ltda","valor":17865594,"risco":"ALTO",
  "objeto":"Gerenciamento e manutenção de frota do CBMERJ (cartão magnético + peças)",
  "lex":"médio","claude":"ALTO",
  "evid":"Pregão Eletrônico PE-045/25 (Lei 14.133); Contrato 392026/2026 (vig. 04/2026–04/2027), R$ 17.865.594,18; NE 2026NE00818. <b>'Não existem pareceres jurídicos registrados para esta contratação'</b> (doc do próprio processo).",
  "achado":"Contratação de <b>R$ 17,8 mi SEM parecer jurídico</b> registrado — exigência legal para contratos (Lei 14.133/2021, art. 53). Sem pesquisa de preços/planilha de custos no trecho; sem detalhamento do julgamento/habilitação do pregão.",
  "base":"Lei 14.133/2021, art. 53 (parecer jurídico obrigatório), art. 23 (pesquisa de preços), art. 17 (fases da licitação).",
  "acao":"Requisitar o parecer jurídico (ou confirmar sua ausência → vício); a ata de julgamento do PE-045/25 e a planilha de custos."},
 {"sei":"SEI-270005/000778/2025","forn":"Hércules Equip. de Proteção e Borracha Ltda","valor":26053500,"risco":"MÉDIO-ALTO",
  "objeto":"Confecção de 1.937 roupas de proteção (EPI) para o CBMERJ",
  "lex":"médio","claude":"MÉDIO-ALTO",
  "evid":"NE 2025NE03140 (R$ 4,4 mi) + NE de reforço 2025NE03364, mesmo objeto/contratada; comunicação da contratada por e-mail <b>empenhocpeo@gmail.com</b> (não institucional).",
  "achado":"<b>Duas notas de empenho</b> p/ o mesmo objeto/contratada sem justificativa de separação → indício de fracionamento/duplicidade de despesa. <b>E-mail pessoal (gmail)</b> em ato oficial — falha de formalidade (padrão recorrente no FUNESBOM: tb. PE-022 'barbarajustim@gmail.com').",
  "base":"Lei 14.133/2021, art. 75 §1º (vedação a fracionamento), art. 12 (formalismo/instrução do processo).",
  "acao":"Verificar se as 2 NEs são reforço legítimo ou split; exigir e-mail institucional; conferir TR/pesquisa de preços e a relação 1.937 roupas × valor."},
 {"sei":"SEI-270003/002373/2024","forn":"Oncomed Clínica Oncológica Ltda","valor":527947,"risco":"MÉDIO",
  "objeto":"Serviços de quimioterapia (credenciamento, inexigibilidade)",
  "lex":"médio","claude":"MÉDIO",
  "evid":"NE 2026NE00929 (R$ 527.947,47) vinculada ao Contrato 170/2024, CANCELADA por duplicidade com NAD 0011/2026 (mesmo dia); objeto lançado como '1 UN' sem detalhamento de sessões.",
  "achado":"<b>Empenho cancelado por duplicidade</b> com NAD emitida no mesmo dia — verificar se houve dupla contabilização/pagamento. Serviço de quimioterapia registrado como '1 UN' sem memória de volume (sessões/pacientes), impedindo aferição de preço unitário.",
  "base":"Lei 4.320/1964, art. 58-64 (empenho/liquidação); Lei 14.133/2021, art. 74, IV (credenciamento) — exige tabela de preços e detalhamento do objeto.",
  "acao":"Confirmar que o cancelamento evitou duplicidade efetiva de pagamento; exigir detalhamento de sessões e tabela de preços do credenciamento."},
]

CAPTURA_GAP = [
 ("SEI-270006/000660/2024","Link Card Adm. de Benefícios","R$ 19,3 mi","despacho de arquivamento/RH"),
 ("SEI-270042/000828/2022","Enge Prat Engenharia","R$ 15,2 mi","conta de água de R$ 505,46 (Barra do Piraí)"),
 ("SEI-270006/011357/2026","ImagemVida","R$ 6,25 mi","ofício administrativo (Plano de Contingência)"),
]

def secoes(d):
    S = []
    cole, totc = d["coletados"], d["contr"][0]
    # camada FORTE (deepseek-v4-pro) — opiniões dos prioritários, vindas da reconciliação
    ds_by_sei = {x["sei"]: x for x in d.get("rec", []) if x.get("deepseek_risco") is not None}
    S.append({"titulo":"1. Sumário executivo e veredito","html":
      f"<p>Perícia sobre a execução financeira e contratual do <b>Corpo de Bombeiros Militar do RJ</b> "
      f"(SEDEC/CBMERJ — UG 160100; <b>FUNESBOM — UG 166100</b>), exercícios <b>2024 em diante</b>.</p>"
      f"<p><b>Escopo material.</b> A UG 160100 executou R$ 2,46 bi em 2024, dos quais <b>96% é folha militar</b> "
      f"(não transita por Ordem Bancária granular). A perícia de licitação/pagamento concentra-se no "
      f"<b>FUNESBOM (166100)</b>, veículo de contratação: <b>{brl(d['tot_ob'][1])}</b> em {d['tot_ob'][0]:,} OBs (2024–2026) "
      f"e <b>{totc:,} contratos distintos</b> (TCE-RJ, {brl(d['contr'][1])}).</p>"
      f"<p><b>Veredito (preliminar — perícia documental {cole}/{totc} processos coletados).</b> A triagem e a leitura "
      f"documental já firmam: (i) <b>achado crítico de método</b> — a camada de risco automatizada do ecossistema "
      f"(ob_anomaly/redflag) estava <b>órfã</b> (não acoplada à base atual), e parte dos nº SEI do registro resolve "
      f"para processo <b>raso/divergente</b> (pagamento/arquivamento), o que exige re-coleta; (ii) achados substantivos "
      f"a apurar — importação direta de R$ 77 mi (ANGLOCO), possível fracionamento de atas (PE-022/24) e duplicidade "
      f"de empenho (Oncomed). <b>Todo apontamento é indício a apurar, não imputação.</b></p>"
      "<p><b>Regra de ouro:</b> Empenho ≠ Liquidação ≠ Ordem Bancária (pago). INDISPONÍVEL ≠ 0.</p>"})

    S.append({"titulo":"2. Execução orçamentária (fonte: SIAFE — despesa_execucao)","html":
      tab(["Exercício","UG","Empenhado","Liquidado","Pago (OB)"],
          [(e,u,brl(em),brl(li),brl(pg)) for e,u,em,li,pg in d["exec"]])
      + "<p><b>Composição do FUNESBOM (2024, pago) — onde está o risco de contratação:</b></p>"
      + tab(["Elemento de despesa","Pago"], [(el,brl(v)) for el,v in d["elem"]])
      + "<p><i>59% do FUNESBOM é 'Outros Serviços de Terceiros — PJ'; o restante, obras, material e equipamentos.</i></p>"})

    rows_top=[]; T=d["tot_ob"][1]
    for nome,doc,n,v in d["top"]:
        rows_top.append((str(nome)[:38], (str(doc) or "")[:14], f"{n:,}", brl(v), f"{100*v/T:.1f}%"))
    S.append({"titulo":"3. Concentração de fornecedores e redes societárias","html":
      f"<p>Universo FUNESBOM 2024–2026: <b>{brl(T)}</b>. Os 15 maiores favorecidos:</p>"
      + tab(["Favorecido","CNPJ/CPF","OBs","Valor","%"], rows_top)
      + "<p><b>Redes societárias (alcance estadual — não restrito aos bombeiros):</b></p>"
      + tab(["Sócio","Nº de fornecedores","Total recebido (Estado)"], [(n,f"{nf}",brl(t)) for n,nf,t in d["redes"]])
      + "<p><i>No FUNESBOM, da rede de A. C. de Miranda apenas a Construtora Metropolitana recebeu (R$ 20,85 mi); "
      "o demais é Estado afora. Indício de grupo econômico a apurar quanto a concorrência aparente, não imputação.</i></p>"})

    S.append({"titulo":"4. Achados de integridade do ecossistema (controle de qualidade)","html":
      "<p><b>4.1. Camada de risco automatizada órfã.</b> As tabelas <code>ob_anomaly</code> (1,08 mi), "
      "<code>ob_redflag</code> (69 mil) e <code>ob_quarentena</code> (33 mil) usam um <code>ob_id</code> que não "
      "corresponde mais à base atual de OBs (ids resetados em recoletas; modelo <code>onda1-v1.0</code> de 06/06/2026). "
      "Cruzamento casa apenas 50 linhas. <b>'Ausência de flag' não equivale a ausência de risco</b> — exige re-chaveamento e nova execução.</p>"
      "<p><b>4.2. Captura SEI rasa/divergente.</b> Parte dos nº SEI do registro TCE resolve para o processo de "
      "pagamento/arquivamento, não para a licitação. Casos confirmados (perícia indeterminada — re-coletar pelo nº real):</p>"
      + tab(["Contrato (registro)","Fornecedor","Valor registrado","Dossiê coletado (≠ objeto)"],
            [(s,f,v,o) for s,f,v,o in CAPTURA_GAP])
      + "<p>Mitigação implementada: seguimento de árvore mais profundo + extrator que enfileira o processo-licitação "
      "(família 270xxx) para coleta dirigida.</p>"})

    # 5. Perícia por contrato (casos prioritários) — Lex × Claude
    blocos=[]
    for c in CASOS:
        camadas = [("Lex (ecossistema)", c['lex']), ("Claude (independente)", c['claude'])]
        dsc = ds_by_sei.get(c['sei'])
        if dsc:
            lbl = f"{dsc['deepseek_risco']}/10 ({dsc.get('deepseek_exec') or '—'})" + \
                  (" · <b>DIVERGE da Lex/heurística</b>" if dsc.get('deepseek_diverge') else "")
            camadas.append(("deepseek-v4-pro (forte, NVIDIA NIM)", lbl))
        blocos.append(
          f"<h3>{c['sei']} — {c['forn']} · {brl(c['valor'])} · <b>risco {c['risco']}</b></h3>"
          f"<p><b>Objeto:</b> {c['objeto']}</p>"
          f"<p><b>Evidência (autos):</b> {c['evid']}</p>"
          f"<p><b>Achado pericial (Claude):</b> {c['achado']}</p>"
          f"<p><b>Base legal:</b> {c['base']}</p>"
          + tab(["Camada","Veredito"], camadas)
          + f"<p><b>Providência recomendada:</b> {c['acao']}</p><hr>")
    ds_block = ""
    if ds_by_sei:
        ds_rows = []
        for sei, x in sorted(ds_by_sei.items(), key=lambda kv: (0 if kv[1].get("deepseek_diverge") else 1, kv[0])):
            cr = "INDET" if x.get("claude_risco") is None else x.get("claude_risco")
            ds_rows.append((sei, (x.get("fornecedor") or "")[:28], x.get("lex_risco"), cr,
                            x.get("deepseek_risco"), "⚠️ sim" if x.get("deepseek_diverge") else "—"))
        ds_block = ("<p><b>5.1. Camada forte — segunda opinião do deepseek-v4-pro (NVIDIA NIM) nos prioritários.</b> "
            "Modelo de raciocínio reanalisa a execução com a mesma perícia calibrada, em camada SEPARADA que não "
            "sobrescreve as demais. Onde o forte diverge do fraco/heurística, há sinal de revisão prioritária.</p>"
            + tab(["Contrato","Fornecedor","Lex (fraco)","Claude (heur.)","deepseek (forte)","Diverge"], ds_rows))
    S.append({"titulo":"5. Perícia documental por contrato — paralelo Lex × Claude (casos prioritários)","html":
      "<p>Cada caso lê o dossiê SEI na fonte primária; a Lex emite parecer automatizado e o Claude faz leitura "
      "independente. Divergências são explicitadas. A íntegra (PDF) dos casos foi remetida em separado.</p>"
      + ds_block + "".join(blocos)})

    # 6. Credenciamento oncológico (ceticismo nos dois sentidos)
    S.append({"titulo":"6. Credenciamento oncológico — suspeita rebaixada (ceticismo bidirecional)","html":
      "<p>Quatro contratos de <b>R$ 6.250.000,00 idênticos</b> (Exclusive Health, Oncomed, Clínica São Carlos, "
      "ImagemVida) por inexigibilidade (art. 74) chamaram atenção na triagem. <b>Leitura documental afasta a hipótese "
      "de fraude por valor idêntico</b>: trata-se de <b>credenciamento</b>, em que todos os habilitados contratam pelo "
      "mesmo teto — valores iguais são esperados. <b>Exceção que se mantém:</b> 'IMAGEMVIDA CURSO PREPARATÓRIO EM "
      "RADIOLOGIA' credenciada para quimioterapia — objeto social aparentemente incompatível com oncologia: indício a "
      "verificar na habilitação (o processo coletado para esse contrato não correspondia — re-coleta pendente).</p>"})

    # 7. Sobrepreço e direcionamento — status e método
    S.append({"titulo":"7. Sobrepreço e direcionamento — método e limitação atual","html":
      "<p><b>Sobrepreço.</b> Exige preço UNITÁRIO (tabela de itens do edital). Fontes: PNCP (estruturado, porém "
      "<b>cobertura fraca para o RJ/FUNESBOM</b>) e o edital no SEI (fonte fiel). O número do PNCP <b>não coincide</b> "
      "com o número SIGA-RJ do SEI — cruzamento por CNPJ-órgão + objeto/valor. Pipeline arma a extração de itens "
      "assim que os editais forem coletados.</p>"
      "<p><b>Direcionamento (R1–R12).</b> Requer edital + ata de julgamento (exigências restritivas, cascata de "
      "desclassificações). Os processos de pagamento coletados não os contêm; o extrator de licitação foi acoplado "
      "para coletar o processo do pregão e então pontuar direcionamento. <b>Status: em coleta dirigida.</b></p>"})

    # 8. Matriz de risco P×I
    S.append({"titulo":"8. Matriz de risco (probabilidade × impacto)","html":
      tab(["#","Risco","P","I","Score","Nível"],
        [("R1","Importação direta R$ 77 mi sem licitação demonstrada (ANGLOCO)","4","5","20","ALTO"),
         ("R2","Fracionamento/duplicidade de atas (PE-022/24)","3","4","12","MÉDIO-ALTO"),
         ("R3","Duplicidade de empenho (Oncomed)","3","3","9","MÉDIO"),
         ("R4","Camada de risco automatizada órfã (cegueira analítica)","4","4","16","ALTO"),
         ("R5","Captura SEL rasa/divergente (perícia indeterminada)","4","3","12","MÉDIO-ALTO"),
         ("R6","Concentração/rede econômica (concorrência aparente)","2","4","8","MÉDIO")])
      + "<p><i>P/I em escala 1–5; score = P×I. Indícios para apuração; presunção de legitimidade dos atos.</i></p>"})

    # 9. Recomendações
    S.append({"titulo":"9. Recomendações","html":
      "<ol>"
      "<li>Re-chavear e re-executar o pipeline de anomalia/redflag contra a base atual de OBs.</li>"
      "<li>Re-coletar, pelo nº real da licitação, os contratos com captura divergente (Link Card, Enge Prat, ImagemVida).</li>"
      "<li>Requisitar ao FUNESBOM o processo licitatório/exclusividade da importação ANGLOCO e reconciliar EUR×total.</li>"
      "<li>Confrontar as Atas 0005/0006 do PE-022/24 (lotes e quantitativos) e a duplicidade NE×NAD da Oncomed.</li>"
      "<li>Vetar fornecedores (Receita/QSA + CEIS/CNEP + OpenSanctions), a começar pelas construtoras e ANGLOCO.</li>"
      "<li>Concluída a coleta dos 1.638 contratos, emitir o relatório final com sobrepreço (itens) e direcionamento (atas).</li>"
      "</ol>"})
    return S

def build_ctx():
    d = dados()
    return {
      "classificacao":"CONFIDENCIAL — CONTROLE EXTERNO",
      "titulo":"Perícia — Corpo de Bombeiros (FUNESBOM/CBMERJ) · 2024 em diante",
      "subtitulo":f"Execução financeira, concentração e perícia documental paralela Lex × Claude · "
                  f"{d['coletados']} de {d['contr'][0]} contratos lidos (coleta em andamento)",
      "analista":"JFN + Claude (perícia paralela)",
      "metodologia":"OB=pago (SIAFE) · empenho≠liquidação≠OB · perícia documental SEI (fonte primária) · "
                    "4 camadas: Lex (fraco, volume) × heurística determinística × deepseek-v4-pro (forte, prioritários) "
                    "× leitura Claude · matriz P×I (TCU/TCE-RJ) · padrão Kroll/Deloitte",
      "faixa":"ALTO",
      "top_flags":["Importação direta R$ 77 mi sem licitação demonstrada (ANGLOCO)",
                   "Camada de risco automatizada órfã","Fracionamento de atas (PE-022/24)",
                   "Captura SEI rasa/divergente — re-coleta dirigida"],
      "secoes":secoes(d),
      "proveniencia":[
        {"dado":"OBs/execução FUNESBOM 2024+","estado":"REAL","fonte":"SIAFE (ordens_bancarias, despesa_execucao)","data":"26/06/2026"},
        {"dado":"Contratos 2024+","estado":"REAL","fonte":"TCE-RJ (contratos_tcerj, compras_diretas_tcerj)","data":"26/06/2026"},
        {"dado":"Dossiês SEI / íntegras","estado":"PARCIAL (coleta em andamento)","fonte":"SEI-RJ (itkava/CDP)","data":"26/06/2026"},
        {"dado":"Redes societárias","estado":"REAL","fonte":"rede_socios_fornecedores / Receita QSA","data":"26/06/2026"}],
      "ressalva":"Indícios para apuração interna; presunção de legitimidade dos atos administrativos. "
                 "INDISPONÍVEL não equivale a zero. Versão PRELIMINAR: a perícia documental completa-se "
                 "ao final da coleta dos 1.638 contratos, quando se emite o relatório final."}

def main():
    ctx = build_ctx()
    html = render_html(ctx)
    nome = "PERICIA-BOMBEIROS-FUNESBOM-preliminar"
    dest = f"/home/ubuntu/JFN/reports/{nome}.pdf"
    asyncio.run(html_to_pdf(html, dest))
    print("PDF:", dest)
    if "--enviar" in sys.argv:
        import os, httpx
        from compliance_agent.envfile import carregar_env
        carregar_env()
        tok=os.environ["TELEGRAM_BOT_TOKEN"]; chat=os.environ.get("TELEGRAM_CHAT_ID")
        with open(dest,"rb") as f:
            r=httpx.post(f"https://api.telegram.org/bot{tok}/sendDocument",
              data={"chat_id":chat,"caption":"📑 Perícia Bombeiros (FUNESBOM) — relatório PRELIMINAR padrão Kroll (Lex×Claude). Final ao término da coleta."},
              files={"document":(nome+".pdf",f,"application/pdf")},timeout=120).json()
        print("TG:", r.get("ok"), r.get("description"))

if __name__ == "__main__":
    main()
