#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RELATÓRIO CORRIGIDO — Contrato 005/2021 ITERJ × MGS. SUPERA a ASSCONT e meus relatórios
anteriores. Baseado SÓ em documentos primários (Termos Aditivos, planilha, pesquisa de preços/Cotações,
Parecer 64, atestados/NFs, ledger). Render Kroll → PDF → Yoda."""
import asyncio
import re
import sys
from datetime import datetime
from pathlib import Path
REPO = Path("/home/ubuntu/JFN"); sys.path.insert(0, str(REPO))
from compliance_agent.reporting.render_html import render_html, html_to_pdf
import httpx

S = []
S.append({"titulo": "0. Correção de rumo (este relatório SUPERA os anteriores e a peça da ASSCONT)", "html": """
<blockquote>Relatórios anteriores (inclusive a apuração da <b>ASSCONT</b>, doc SEI 130344941) concluíram que <b>"o
Estado deve à MGS R$ 56.044,28"</b>. A leitura dos <b>documentos primários</b> (4º Termo Aditivo, planilha de custos,
pesquisa de preços/Cotações, Parecer 64, atestados e NFs) <b>derruba essa conclusão</b>. A diferença não é dívida
líquida e certa do Estado — é uma <b>disputa de repactuação</b>, na qual o Estado <b>glosa</b> (paga menos do que a
empresa fatura) por entender, com base em <b>pesquisa de preços</b>, que a planilha da contratada está acima do mercado.</blockquote>
"""})

S.append({"titulo": "1. O fato central — dois valores em disputa", "html": """
<table>
<tr><th>Valor</th><th>Origem (primária)</th><th>Mensal</th><th>Anual</th></tr>
<tr><td><b>NF de face / planilha da empresa</b></td><td>Planilha de Custos e Formação de Preços (Anexo II, Repactuação 2025), assinada pelo sócio-diretor</td><td>R$ 118.441,47</td><td>R$ 1.421.297,64</td></tr>
<tr><td><b>Valor CONTRATADO (4º Termo Aditivo)</b></td><td>4º Termo Aditivo (prorrogação 20/11/2025–19/11/2026), instrumento assinado</td><td>R$ 111.435,94</td><td>R$ 1.337.231,26</td></tr>
<tr><td><b>Diferença glosada</b></td><td>= 118.441,47 − 111.435,94</td><td><b>R$ 7.005,53</b></td><td>R$ 84.066,38</td></tr>
</table>
<p>A glosa real é de <b>R$ 7.005,53/mês</b> (a partir de 2026), e não os R$ 5.257,33 que a ASSCONT usou. O 4º Termo
foi assinado <b>no valor reduzido</b> (R$ 111.435,94), confirmando que a Administração não reconheceu integralmente a
repactuação pleiteada pela empresa (R$ 118.441,47).</p>
"""})

S.append({"titulo": "2. Por que o valor foi reduzido — pesquisa de preços e vantajosidade (Parecer 64)", "html": """
<p>O <b>Parecer 64</b> (jurídico) condicionou a prorrogação à comprovação de <b>vantajosidade</b>: <i>"NÃO foram
carreados aos autos documentação que comprovam a pesquisa de preços mediante fontes de pesquisas variadas, a demonstrar
a vantajosidade em prorrogar o contrato"</i>, e que a prorrogação só se admite <i>"com vistas à obtenção de preços e
condições mais vantajosas para a administração"</i> (art. 57, Lei 8.666/93). Em resposta, foram juntadas as
<b>Cotações 02 e 03</b> (pesquisa de mercado por lote/posto). O valor contratado no 4º Termo (R$ 111.435,94) é,
portanto, fruto desse processo de <b>economicidade</b> — não um simples "esquecimento" de repassar o reajuste.</p>
<p><b>Consequência:</b> a glosa de R$ 7.005,53/mês é, em princípio, <b>medida de economicidade legítima</b> (a empresa
fatura acima do valor de mercado pesquisado), e <b>não</b> um crédito da empresa. A direção da diferença é
oposta à apontada pela ASSCONT.</p>
"""})

S.append({"titulo": "3. Evolução mensal efetiva (primário: NF de face × valor pago)", "html": """
<table>
<tr><th>Competência (serviço)</th><th>NF face</th><th>Pago (bruto implícito)</th><th>Situação</th></tr>
<tr><td>Jan–Jun/2025</td><td>118.441,47 (pleiteado)</td><td>≈ 109.800 (valor CCT2024)</td><td>pago no valor ANTIGO — retroativo do dissídio em aberto</td></tr>
<tr><td>Jul–Out/2025</td><td>118.441,47</td><td>≈ 118.442 (cheio)</td><td>✅ repactuação aplicada integralmente (sem glosa)</td></tr>
<tr><td>Nov–Dez/2025</td><td>118.441,47</td><td>≈ 113.252</td><td>glosa ≈ R$ 5.190/mês (início da redução)</td></tr>
<tr><td>Fev/2026</td><td>118.441,47</td><td>≈ 111.526</td><td>glosa ≈ R$ 6.915/mês (→ valor do 4º Termo)</td></tr>
<tr><td>Mar/2026</td><td>118.441,47</td><td>≈ 110.732</td><td>glosa ≈ R$ 7.710/mês</td></tr>
</table>
<p>Padrão claro: o Estado <b>pagou o valor cheio Jul–Out/2025</b> e depois, com o 4º Termo e a pesquisa de preços,
<b>passou a reduzir/glosar</b>, convergindo ao valor contratado de R$ 111.435,94. Os valores são extraídos do
<i>ledger</i> de OBs (líquido ÷ fator de retenção ≈ 0,9086) e batem com os atestados/NFs.</p>
"""})

S.append({"titulo": "4. O único crédito plausível da empresa — retroativo do dissídio (Mar–Jun/2025)", "html": """
<p>Jan–Jun/2025 foram pagos no valor da CCT2024 (≈ R$ 109,8 mil bruto). Como a <b>data-base é março</b>, o reajuste
da CCT2025 é devido a partir de Mar/2025. O retroativo (Mar–Jun/2025) é o <b>único</b> valor que, em princípio, a
empresa tem a receber — mas o <b>quantum depende da disputa</b>:</p>
<table>
<tr><th>Hipótese de valor da repactuação</th><th>Δ mensal</th><th>Retroativo Mar–Jun (×4)</th></tr>
<tr><td>Pela planilha da empresa (118.441,47)</td><td>8.753,74</td><td>R$ 35.014,96</td></tr>
<tr><td>Pelo valor contratado no 4º Termo (111.435,94)</td><td>1.748,21</td><td>R$ 6.992,84</td></tr>
</table>
<p>Ou seja: o crédito real da empresa pelo retroativo está entre <b>R$ 6.992,84 e R$ 35.014,96</b>, conforme se
reconheça o valor de mercado (4º Termo) ou o valor pleiteado (planilha). <b>A glosa de Nov/2025 em diante NÃO é
crédito da empresa</b> — é o Estado pagando o valor que entende correto.</p>
"""})

S.append({"titulo": "5. Veredito corrigido", "html": """
<table>
<tr><th>Quesito</th><th>Conclusão (primária, não-ASSCONT)</th></tr>
<tr><td>Há crédito de R$ 56.044,28 da empresa?</td><td><b>NÃO.</b> Esse número (ASSCONT) está <b>errado</b>: usou glosa de R$ 5.257,33 e tratou a glosa como crédito. A glosa real (R$ 7.005,53/mês) é <b>redução de preço por economicidade</b>, não dívida.</td></tr>
<tr><td>O Estado deve à empresa?</td><td>No máximo o <b>retroativo do dissídio Mar–Jun/2025</b>, entre R$ 6.992,84 e R$ 35.014,96 — a depender do valor reconhecido na repactuação.</td></tr>
<tr><td>Houve pagamento a maior ao erário?</td><td><b>Não há indício de dano:</b> ao contrário, o Estado vem <b>glosando</b> (pagando menos que o faturado).</td></tr>
<tr><td>Reajustes/dissídios corretos?</td><td>Os <b>percentuais</b> das CCTs (9,91/6,01/6,20/7,50%) são corretos; a <b>controvérsia</b> é o valor de mercado da repactuação de 2025 (planilha da empresa × pesquisa de preços do Estado).</td></tr>
</table>
<blockquote><b>Síntese:</b> o caso NÃO é "o Estado deve R$ 56 mil à empresa". É uma <b>disputa de repactuação</b>: a empresa
pleiteia R$ 118.441,47/mês (sua planilha); o Estado contratou R$ 111.435,94/mês (pesquisa de preços/vantajosidade) e
glosa a diferença. O único crédito provável da empresa é o <b>retroativo do dissídio de Mar–Jun/2025</b> (R$ 6,99 mil a
R$ 35,01 mil). <b>Pendente de confirmação: a decisão final da repactuação/vantajosidade</b> (despacho GERAF da glosa +
manifestação final), que fixará o valor reconhecido.</blockquote>
"""})

ctx = {
    "classificacao": "CONFIDENCIAL — USO INTERNO (controle externo)",
    "titulo": "Auditoria CORRIGIDA — Contrato 005/2021 ITERJ × MGS Clean",
    "subtitulo": "Revisão sobre documentos primários · SUPERA a peça da ASSCONT e os relatórios anteriores · disputa de repactuação, não dívida líquida",
    "data": datetime.now().strftime("%d/%m/%Y"),
    "analista": "JFN — Núcleo de Fiscalização (revisão documental primária)",
    "metodologia": "4º/3º/2º Termos Aditivos + Planilha de Custos + Cotações 02/03 (pesquisa de preços) + Parecer 64 + Atestados/NFs (007/2024, 018/2025, 030/2026) + ledger SIAFE · SEM apoio na ASSCONT",
    "score": 45, "faixa": "MÉDIO",
    "top_flags": [
        "SUPERA a ASSCONT: NÃO há dívida líquida de R$ 56.044,28 da empresa",
        "Glosa real = R$ 7.005,53/mês (NF 118.441,47 − 4º Termo 111.435,94), não 5.257,33",
        "4º Termo foi assinado no valor REDUZIDO (111.435,94) — repactuação não reconhecida na íntegra",
        "Glosa baseada em pesquisa de preços/vantajosidade (Parecer 64 + Cotações) = economicidade, não crédito",
        "Único crédito plausível: retroativo dissídio Mar-Jun/25 (R$ 6.992,84 a R$ 35.014,96)",
    ],
    "secoes": S,
    "proveniencia": [
        {"dado": "Valor contratado R$ 111.435,94/mês (1.337.231,26/ano)", "estado": "REAL", "fonte": "4º Termo Aditivo (instrumento + anexo), SEI-330020/000762/2021", "data": "20/06/2026"},
        {"dado": "NF de face R$ 118.441,47 (planilha da empresa)", "estado": "REAL", "fonte": "Planilha de Custos + NFs 1125/12415/1506 (007/2024,018/2025,030/2026)", "data": "20/06/2026"},
        {"dado": "Exigência de vantajosidade / pesquisa de preços", "estado": "REAL", "fonte": "Parecer 64 + Cotações 02/03 (762/2021)", "data": "20/06/2026"},
        {"dado": "Série mensal de pagamento (glosa progressiva)", "estado": "REAL", "fonte": "ob_orcamentaria_siafe (55 OBs)", "data": "20/06/2026"},
    ],
    "ressalva": ("Revisão baseada EXCLUSIVAMENTE em documentos primários; SUPERA a apuração da ASSCONT. O quantum final do "
                 "retroativo e a legitimidade definitiva da glosa dependem da decisão final da repactuação/vantajosidade "
                 "(despacho GERAF da glosa, doc 128839240, e manifestação final), ainda a confirmar. Indício ≠ acusação."),
}
nome = f"auditoria_corrigida_iterj_mgs_005_2021_{datetime.now().date()}"
destino = str(REPO/"reports"/f"{nome}.pdf")
asyncio.run(html_to_pdf(render_html(ctx), destino))
print(f"PDF: {destino} {Path(destino).stat().st_size} bytes | {len(S)} seções")
ENV = Path("/home/ubuntu/.hermes/.env")
def key(n):
    m = re.search(rf"^{n}=(.+)$", ENV.read_text(), re.M); return m.group(1).strip().strip('"').strip("'") if m else ""
tok, chat = key("TELEGRAM_BOT_TOKEN"), key("TELEGRAM_CHAT_ID"); base = f"https://api.telegram.org/bot{tok}"
msg = ("📕 *AUDITORIA CORRIGIDA — ITERJ × MGS (005/2021)* — SUPERA a ASSCONT e meus relatórios anteriores.\n\n"
       "*Correção (de fonte primária):*\n"
       "• O número da ASSCONT (Estado deve R$ 56.044,28) está *ERRADO* — usou glosa de R$ 5.257,33 e tratou glosa como crédito.\n"
       "• A glosa real é *R$ 7.005,53/mês* (NF 118.441,47 − 4º Termo 111.435,94).\n"
       "• O *4º Termo foi assinado no valor REDUZIDO* (111.435,94), com base em *pesquisa de preços/vantajosidade* (Parecer 64 + Cotações) → glosa = economicidade, *não* dívida.\n"
       "• Não é 'Estado deve R$56k'. É *disputa de repactuação*: empresa pede 118.441,47 (planilha); Estado paga 111.435,94 (mercado).\n"
       "• Único crédito provável da empresa: *retroativo dissídio Mar-Jun/2025* (R$ 6.992,84 a R$ 35.014,96).\n\n"
       "📎 PDF com a moldura corrigida. Pendente: decisão final da repactuação (despacho GERAF da glosa).")
print("msg:", httpx.post(f"{base}/sendMessage", data={"chat_id": chat, "text": msg, "parse_mode": "Markdown"}, timeout=30).json().get("ok"))
with open(destino, "rb") as f:
    print("pdf:", httpx.post(f"{base}/sendDocument", data={"chat_id": chat, "caption": "Auditoria CORRIGIDA ITERJ×MGS (supera ASSCONT)"},
          files={"document": (f"{nome}.pdf", f, "application/pdf")}, timeout=90).json().get("ok"))
