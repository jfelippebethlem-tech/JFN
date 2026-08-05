# -*- coding: utf-8 -*-
"""Triagem DETERMINÍSTICA da perícia sobre o acervo SEI já capturado.

É o estágio 2 do pipeline pedido pelo dono (arquivo compacto → triagem
determinística → LLM só no que sobra). Não chama IA nenhuma: lê o manifesto de
cada processo em ``data/sei_arquivo/`` e aplica regras que ou batem ou não batem.

**A separação que decide tudo — e ela tem TRÊS baldes, não dois.**

A lição de que "59% das red flags eram queixa de CAPTURA" continua valendo, mas ela
foi mal aplicada na 1ª versão deste arquivo: eu joguei toda lacuna num balde só e a
tratei como ruído. **Está errado.** Em controle externo, peça que deveria estar no
processo e não está é falha de controle tão grave quanto contradição — processo que
paga R$ 11,4 mi sem uma única evidência de execução é achado, não silêncio.

O que não pode é confundir a falta DELE com a falha NOSSA:

* ``achados``          — contradição no que EXISTE (contrato antes do parecer);
* ``lacunas_processo`` — peça que deveria estar no processo e não está. **Pesa como
  achado.** Só vale quando a captura está íntegra: sem isso não dá para saber de
  quem é a falta;
* ``lacunas_captura``  — nós não lemos. É trabalho nosso, nunca vício dele.

Foi a confusão entre o 2º e o 3º que pôs 874 processos na fila do fiscal à toa.

**Honestidade das regras.** Cada achado diz em que documento se apoia. Nenhuma
regra conclui por ausência: "não achei o parecer" é lacuna, não irregularidade.
E indício ≠ acusação — o campo ``grau`` é fila de apuração, não veredito.

Uso:
    .venv/bin/python -m tools.sei_triagem_pericia            # acervo inteiro
    .venv/bin/python -m tools.sei_triagem_pericia --limite 50
    .venv/bin/python -m tools.sei_triagem_pericia --json /tmp/triagem.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
ARQUIVO = RAIZ / "data" / "sei_arquivo"

from compliance_agent.sei import acervo_texto  # noqa: E402

# Tipos que o arquivador já classifica. Fonte: contagem no acervo em 2026-07-25.
_PARECER = {"parecer_juridico", "parecer", "nota_juridica"}
# o TÍTULO desmente o tipo: "CERTIDÃO/Certidões ... PGE" e "Parecer Técnico - Medição" viram
# parecer_juridico no classificador e fabricam A1; "Nota Fiscal" e "Minuta de Termo Aditivo"
# viram contrato (o classificador por CONTEÚDO mente em doc escaneado) — e minuta ANTES do
# parecer é o fluxo CORRETO do art. 53. (FPs reais 030001/087722, 080002/020278, 270131/000548.)
_RE_ID_DOC = re.compile(r"(\d{6,})")
"""Identificador SEI da peça — o último grupo de 6+ dígitos do título."""

_RX_NOTA_TECNICA = re.compile(r"(?i)\bnota\s+t[ée]cnica\b(?!\s+jur)")
"""Nota técnica PURA (a jurídica segue valendo) — peça de fiscalização, não análise prévia."""

# `minuta` entra no veto: minuta revisada pela assessoria é o INSUMO do controle, não a
# manifestação dele — e suas cláusulas condicionais ("desde que devidamente justificado", "caso os
# recursos não sejam totalmente executados") casam com o padrão de ressalva. Medido em 2026-08-04
# no SEI-080001/037511/2024: o A3 se ancorava no "Anexo Minuta Revisada Assjur" e cobrava
# acatamento de uma cláusula de minuta, quando a sequência posterior (nova minuta → Resolução →
# publicação) é o controle FUNCIONANDO. Mesma doutrina que o I1/I2 já aplica desde 2026-08-03:
# correção antes da assinatura não é vício.
_RX_NAO_PARECER = re.compile(
    r"certid|parecer\s+t[ée]cnic|parecer\s+de\s+medi|laudo|minuta", re.I)
# O que NÃO é o instrumento, mesmo tipado `contrato`. "Registro siafe encerramento contrato" é o
# REGISTRO do encerramento; "Publicação/Extrato" é o extrato no D.O.; "Termo de apostilamento" é
# registro unilateral. Medido em 2026-08-04: o A1 do 070026/000410/2021 dizia "contrato antes do
# parecer" tendo como "contrato" um registro de ENCERRAMENTO na posição 5. Mesma doutrina do
# `sei/instrumento_assinatura._RE_NAO_E_INSTRUMENTO`, que já derrubou 4 falsos do I1.
_RX_NAO_CONTRATO = re.compile(
    r"minuta|nota\s+fiscal|\bnfs?-?e?\b|e-?mail|gmail|pesquisa"
    r"|registro\s+siafe|encerramento|publica[çc][ãa]o|extrato|apostilamento"
    r"|consulta\s+ao|termo\s+de\s+cancelamento", re.I)
_CONTRATO = {"contrato", "termo_contrato", "ata_registro_precos"}
_RESPOSTA = {"despacho", "oficio", "nota_tecnica", "informacao", "manifestacao"}
# O ATO QUE DECIDE não é do tipo "resposta" — e é ele que responde ao parecer. Medido em
# 2026-08-05 nos 11 disparos "nenhum registra acatamento": o SEI-070002/013107/2024 tem o
# "Ato de Reconhecimento de Dívida 86639308" enumerando ponto a ponto os procedimentos e
# citando o parecer pelo identificador ("(I) Parecer jurídico exarado pela Procuradoria do
# INEA (85972668) com a conclusão de não ocorrência de prescrição"). O classificador o tipa
# `parecer`, então ele ficava fora de `_RESPOSTA` e o achado afirmava uma ausência que os
# autos desmentem. Casar por TÍTULO, e só valer quando o ato CITA o parecer — a conjunção é o
# que segura: alargar `_RESPOSTA` por tipo importaria ruído puro (anexo de planilha, recibo
# SIGFIS, "impugnação não acatada" em edital). Controle negativo: o SEI-080001/036964/2025
# também tem ato decisório posterior, não cita o parecer, e segue `medio` — que é o caso
# verdadeiro (a Deliberação CIB 1.237/2025 nunca foi referendada).
_RX_ATO_DECISORIO = re.compile(
    r"^\s*(?:ato\s+de\s+reconhecimento\s+de\s+d[ií]vida|termo\s+de\s+ratifica"
    r"|ratifica[çc][ãa]o|homologa[çc][ãa]o|autoriza[çc][ãa]o\b|decis[ãa]o\b)", re.I)
_EXECUCAO = {"medicao", "relatorio_fotografico", "atesto", "recebimento"}
_PESQUISA = {"pesquisa_preco", "mapa_precos", "cotacao", "orcamento"}

# CALIBRAGEM 2026-07-25 — o `tipo` do arquivador nao basta. Medido em 300
# processos: a regra A5 acusava 222 e em 89 deles (40%) o TITULO trazia
# "Atestado"/"Medicao"/"Recebimento" — o documento existia e o tipo nao o
# reconhecia. Auditor que exagera e ignorado; e a licao que o auditar_layout.py
# ja pagou na primeira geracao. Por isso as regras olham TIPO **ou** TITULO.
_RX_EXEC_TIT = re.compile(
    r"medi[çc][ãa]o|atesto|atestad|recebimento (provis|defin)|termo de recebimento"
    r"|relat[óo]rio fotogr", re.I)
_RX_PESQ_TIT = re.compile(
    r"pesquisa de pre[çc]|mapa de pre[çc]|cota[çc][ãa]o|or[çc]amento"
    r"|proposta comercial|painel de pre|tabela sinapi", re.I)

# NATUREZA DO PROCESSO — repasse nao e contratacao (2026-07-25).
# Medido: os SEIS maiores da fila (R$ 168 mi) eram Fundos Municipais de Saude, e o
# Gemini leu neles "Informacao de conta bancaria para repasse financeiro" e "Repasse
# da Resolucao SES 3618". Nao ha contrato, nao ha licitacao, nao ha entrega a medir:
# e transferencia fundo a fundo. Um "parecer com ressalva sem acatamento expresso"
# ali nao tem o peso que tem num contrato de obra — tratar os dois igual poe R$ 168
# mi de repasse na fila com peso de vicio contratual, e o fiscal perde a viagem.
# CALIBRAGEM 2026-07-25, 2a volta. A 1a versao punha "empenho" na lista de
# contratacao — e TODO processo de pagamento tem Nota de Empenho, entao tudo virava
# contratacao e os seis Fundos Municipais de Saude (R$ 168 mi) continuaram na fila
# com peso de vicio contratual. O sinal certo estava nos titulos o tempo todo:
# "Relacao de Ordens Bancarias EXTERNAS" — OB externa e pagamento a OUTRO ente, que
# e a assinatura de transferencia fundo a fundo. Contratacao exige prova de
# contrato/licitacao, nao de despesa: despesa toda execucao tem.
_RX_REPASSE = re.compile(
    r"repasse|cofinanciamento|fundo a fundo|transfer[êe]ncia volunt[áa]ria"
    r"|resolu[çc][ãa]o SES|conv[êe]nio|termo de fomento|termo de colabora[çc][ãa]o"
    r"|emenda parlamentar|subven[çc][ãa]o|ordens? banc[áa]ri[ao]s? externa", re.I)
_RX_CONTRATACAO = re.compile(
    r"contrato|licita[çc][ãa]o|preg[ãa]o|dispensa de licita|inexigibilidade"
    r"|ata de registro|termo aditivo|ordem de in[íi]cio|medi[çc][ãa]o"
    r"|termo de refer[êe]ncia|projeto b[áa]sico", re.I)


# OVERRIDE FORTE, no mesmo idioma que `pcrj/esfera.py` usa para a raiz de CNPJ:
# ha sinal que nao se decide por contagem. "Ordens Bancarias EXTERNAS" e pagamento a
# OUTRO ente — so aparece em transferencia. Um processo de repasse cita "contrato" em
# documento acessorio (minuta, anexo), entao contar palavra fazia contratacao vencer
# 14 a 1 e os seis Fundos Municipais de Saude (R$ 168 mi) seguiam na fila com peso de
# vicio contratual. Sinal inequivoco decide sozinho; o resto vai por contagem.
_RX_OB_EXTERNA = re.compile(r"ordens? banc[áa]ri[ao]s? externa|OB externa", re.I)
_RX_CONTRATO_FORTE = re.compile(
    r"\bcontrato n[ºo°]|termo de contrato|termo aditivo|ordem de in[íi]cio"
    r"|ata de registro de pre[çc]o", re.I)


# Processo cujo OBJETO é aditar/prorrogar um contrato existente. Precisa vir antes do teste de
# contratação: "termo aditivo" também casa `_RX_CONTRATO_FORTE`, e aí o processo era lido como
# contratação nova e cobrado pela fase de seleção que ele nunca teria.
_RX_ADITIVO = re.compile(
    r"termo aditivo|1[ºo°]\s*termo aditivo|prorroga[çc][ãa]o|aditamento|repactua[çc][ãa]o", re.I)
# Cadeia da despesa: os três marcos que definem um processo financeiro. Empenho ≠ liquidação ≠ OB
# (regra da casa) — aqui basta a PRESENÇA da cadeia para saber que o processo é de pagamento.
# CANCELAMENTO expresso da compra. Medido em 2026-08-03 (SEI-080007/001365/2024): os autos trazem
# "Processo Cancelado com Sucesso" do SIGA e o sistema seguiu cobrando seleção e contrato de uma
# contratação que nunca se consumou. Encerramento SOZINHO não basta — todo processo termina com um.
_RX_CANCELAMENTO = re.compile(
    r"cancelamento\s+siga|processo\s+cancelado|cancelamento\s+d[ao]\s+(?:processo|compra|"
    r"licita[çc][ãa]o)|desist[êe]ncia\s+d[ao]\s+processo|revoga[çc][ãa]o\s+d[ao]\s+licita", re.I)
_RX_PAGAMENTO = re.compile(
    r"ordem\s+banc[áa]ria|\b20\d{2}OB\d|nota\s+de\s+liquida|\b20\d{2}NL\d|"
    r"programa[çc][ãa]o\s+de\s+desembolso|\b20\d{2}PD\d", re.I)
_RX_SELECAO_PROPRIA = re.compile(
    r"\bedital\b|ata da sess[ãa]o|mapa de lances|termo de julgamento|homologa[çc][ãa]o|"
    r"ato de dispensa|ratifica[çc][ãa]o", re.I)


_TIPOS_DE_DESPESA = frozenset({
    "nota_empenho", "nota_liquidacao", "ordem_bancaria", "programacao_desembolso",
    "autorizacao_despesa"})
_TIPOS_DE_CONTRATACAO = frozenset({
    "contrato", "ata_rp", "edital", "proposta", "homologacao", "termo_referencia", "etp",
    "ordem_inicio"})


def natureza(man: dict, docs: list[dict]) -> str:
    """contratacao | aditivo | pagamento | repasse | indefinido. Sem sinal, fica indefinido."""
    txt = " | ".join(str(d.get("titulo") or "") for d in docs)
    # aditivo/prorrogação SEM peça de seleção própria: a seleção está no processo de origem
    if _RX_ADITIVO.search(txt) and not _RX_SELECAO_PROPRIA.search(txt):
        return "aditivo"
    # PROCESSO FINANCEIRO: empenho→liquidação→OB, sem peça de contratação própria. Medido em
    # 2026-08-03 no SEI-080001/018592/2026, que diz nos próprios autos onde a contratação mora
    # ("o presente processo financeiro encontra respaldo no processo administrativo
    # SEI-080001/004018/2023, vinculado ao Contrato n.º 051/2023") e ainda assim recebeu cobrança
    # de planejamento, seleção e contrato — porque UMA menção isolada a "licitação" num título
    # vencia a contagem e o classificava como contratação.
    if _RX_PAGAMENTO.search(txt) and not _RX_SELECAO_PROPRIA.search(txt) \
            and not _RX_CONTRATO_FORTE.search(txt):
        return "pagamento"
    # compra CANCELADA sem instrumento assinado: as fases seguintes não existem porque a
    # contratação não se consumou — cobrá-las é imputar vício ao que não aconteceu.
    if _RX_CANCELAMENTO.search(txt) and not _RX_CONTRATO_FORTE.search(txt):
        return "cancelado"
    # 1) sinais inequivocos decidem sozinhos, na ordem: contrato forte vence OB externa
    #    (obra paga por OB externa continua sendo contratacao).
    if _RX_CONTRATO_FORTE.search(txt):
        return "contratacao"
    if _RX_OB_EXTERNA.search(txt):
        return "repasse"

    # QUANDO O TÍTULO NÃO DIZ NADA, O TIPO DIZ. Medido em 2026-08-04: **1.129 dos 2.174 processos
    # (52%) ficavam `indefinido`**, e o `fases.lacunas` dá ao indefinido o checklist COMPLETO de
    # contratação — é o caso menos conhecido recebendo o tratamento mais severo. Numa amostra, 65
    # de 67 indefinidos eram acusados de "Planejamento ausente"; abrindo-os, são processos de
    # empenho→liquidação. A causa: parte dos manifestos perdeu os TÍTULOS e guarda só o
    # identificador ("86655470 | 84392504 | …"), então as regras acima não têm o que ler — mas o
    # `tipo` canônico está lá, preenchido pelo `manifesto_norm`.
    #
    # A regra é conservadora e a isenção é estreita: só vale sem NENHUMA peça de contratação nos
    # autos e com metade dos documentos sendo despesa; e o que ela dispensa é planejamento,
    # seleção e formalização — a cobrança de **evidência de execução continua**, que é o achado
    # que mais importa (pagar sem prova de entrega).
    tipos = [str(d.get("tipo") or "") for d in docs]
    if tipos and not any(x in _TIPOS_DE_CONTRATACAO for x in tipos):
        if sum(1 for x in tipos if x in _TIPOS_DE_DESPESA) / len(tipos) >= 0.5:
            return "pagamento"
    # 2) sem sinal forte, decide a contagem
    r = len(_RX_REPASSE.findall(txt))
    c = len(_RX_CONTRATACAO.findall(txt))
    if r and r >= c * 2:
        return "repasse"
    if c and c > r:
        return "contratacao"
    return "indefinido"


# ATENDER a ressalva é acatá-la — e o OBJETO é que decide. Medido em 2026-08-04 nos 90 processos
# de maior risco: **6 de 65** respondiam o parecer ponto a ponto e eram acusados de "nenhum
# documento registra acatamento":
#     "em atendimento ao Parecer Nº 130/2022/INEA/GERCON (32744974), que condicionou…"
#     "Recomendação atendida através do documento de Oficialização de Demanda…"
#     "Em atendimento ao parecer jurídico 82243420, aduz-se: Quanto ao item 1, informa-se que…"
# O padrão é ESTREITO de propósito: "em atendimento ao DESPACHO" é encaminhamento de rotina e
# NÃO entra — foi por isso que "atendida" solto ficou de fora. Acusar de silêncio quem respondeu
# é acusação sobre servidor nomeado.
_RX_ACATA = re.compile(
    r"\bacat(a|o|ando|ada)\b|\bem aten[çc][ãa]o ao parecer\b|\bcumprida[s]? as\b"
    r"|\bsanad[ao]s?\b|\bretific(a|ado|ação)\b"
    r"|em\s+atendimento\s+(?:ao|à|aos|às)\s+"
    r"(?:parecer|cota|manifesta[çc][ãa]o|recomenda|ressalva|condicionante|exig[êe]ncia)"
    r"|atendid[ao]s?\s+(?:a|as|o|os)?\s*"
    r"(?:recomenda|ressalva|condicionante|exig[êe]ncia|parecer)"
    r"|(?:recomenda[çc][ãa]o|ressalva|condicionante|exig[êe]ncia)[^.]{0,60}\batendid", re.I)
_RX_RESSALVA = re.compile(
    r"\bcom ressalva|\bcondicionad[oa]\b|\bdesde que\b|\brecomend(a|o|ando)\b"
    r"|\bnecess[áa]rio (que|se)\b|\bdeve[rm]? ser (sanad|corrigid|providenci)", re.I)


_JANELA_FORMA = 160


def _e_forma(texto: str, m) -> bool:
    """O que acendeu a ressalva é TEXTO DE FÔRMA (checklist, citação literal, doutrina, certidão)?

    Medido em 2026-08-04: das 31 passagens distintas que acendiam "parecer com ressalva" nos 150
    processos de maior risco, 7 se repetiam IGUAIS e cobriam 39 processos — item de checklist da
    PGE, citação literal do art. 149, doutrina e rodapé de certidão. Repetição idêntica entre
    processos diferentes é a prova objetiva de que aquilo não é opinião sobre ESTE processo.
    O catálogo mora em `sei_recomendacoes._RE_BOILERPLATE`, para não haver duas cópias.
    """
    from compliance_agent.sei_recomendacoes import _RE_BOILERPLATE
    janela = texto[max(0, m.start() - _JANELA_FORMA):m.end() + _JANELA_FORMA]
    return bool(_RE_BOILERPLATE.search(janela))


def _docs(man: dict) -> list[dict]:
    return [d for d in (man.get("docs") or []) if isinstance(d, dict)]


def _ordem(d: dict) -> int:
    """Ordem do documento na árvore. É o único eixo temporal confiável aqui:
    o manifesto nem sempre traz data, mas a árvore do SEI é cronológica."""
    try:
        return int(str(d.get("i") or 0))
    except (TypeError, ValueError):
        return 0


def _texto_do_doc(pasta: Path, doc: dict) -> str:
    """Texto capturado do documento, se houver. Vazio nunca vira conclusão.

    O CAMINHO VEM DO MANIFESTO, não de um glob pelo identificador no nome do arquivo. A versão
    anterior procurava `texto/*<id>*` — e o nome do arquivo é o título SANITIZADO e CORTADO, de
    modo que em título longo o identificador simplesmente não está no nome. Medido em 2026-08-04
    sobre o acervo: **5.722 dos 33.584 documentos com teor (17%) eram lidos como VAZIOS**, e com
    eles **56,5 milhões de caracteres** ficavam invisíveis para o A1, o A2 e a auditoria de
    acatamento — os três detectores que decidem sobre o art. 53. Um deles era o
    "Despacho de Encaminhamento de Processo PARECER DE FAVORABILIDADE (121198855)", 3.144
    caracteres que o glob não achava porque o nome do arquivo termina antes do número.

    `acervo_texto.ler` é a porta única da casa: usa o `texto` declarado no manifesto, devolve sem
    a etiqueta e com o teto por documento. O fallback pelo glob fica para o manifesto sem o campo.
    """
    alvo = str(doc.get("titulo") or "")
    if doc.get("texto"):
        lido = acervo_texto.ler(pasta, doc, teto=20000)
        if (lido or "").strip():
            return lido
    m = re.search(r"\((\d{6,})\)|\b(\d{8,})\b", alvo)
    if not m:
        return ""
    ident = m.group(1) or m.group(2)
    for p in (pasta / "texto").glob(f"*{ident}*"):
        try:
            # sem a etiqueta, e o teto conta o DOCUMENTO (ver `sei/acervo_texto`)
            return acervo_texto.sem_etiqueta(
                p.read_text(encoding="utf-8", errors="ignore"), alvo)[:20000]
        except OSError:
            return ""
    return ""


def periciar(pasta: Path) -> dict | None:
    """Triagem de UM processo. Devolve achados e lacunas SEPARADOS."""
    mf = pasta / "manifest.json"
    if not mf.exists():
        return None
    try:
        man = json.loads(mf.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    # VOCABULÁRIO. O manifesto CRU traz o tipo GROSSO do arquivador (`tramitacao`, `outros`) e as
    # regras daqui falam o vocabulário FINO/canônico (`despacho`, `oficio`, `nota_tecnica`…). Sem
    # normalizar, `_RESPOSTA` não encontrava NENHUM despacho — e o A2 anunciava "não há documento
    # posterior que responda" num processo com **174 despachos** (070002/012954/2022, medido em
    # 2026-08-04). Era o achado mais frequente da faixa EXTREMO: 80 dos 150 processos de maior
    # risco. `manifesto_norm.normalizar` existe exatamente para isto — dois formatos, um shape.
    try:
        from compliance_agent.sei import manifesto_norm as _mn
        man = _mn.normalizar({**man, "_pasta": str(pasta)})
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError):
        pass                     # sem normalização, segue com o cru: pior, não quebrado

    docs = _docs(man)
    tipos = Counter(str(d.get("tipo") or "").lower() for d in docs)
    nat = natureza(man, docs)
    achados: list[dict] = []
    observacoes: list[dict] = []   # estrutural, NAO e contradicao — ver nota abaixo

    # MARCO exige DUPLA concordância: o tipo do arquivador E o classificador por TÍTULO
    # (sei/fases). O tipo por CONTEÚDO mente em doc escaneado — tipou "Declaração",
    # "Justificativa", "minnuta" (typo real!) como contrato e "Checklist" como parecer
    # (FP A1 no 270131/000548/2023). Para o achado mais forte, precisão > recall.
    from compliance_agent.sei.fases import classificar as _cls_titulo
    pareceres = [d for d in docs if str(d.get("tipo") or "").lower() in _PARECER
                 and not _RX_NAO_PARECER.search(str(d.get("titulo") or ""))
                 and _cls_titulo(str(d.get("titulo") or ""))[1] == "parecer"]
    contratos = [d for d in docs if str(d.get("tipo") or "").lower() in _CONTRATO
                 and not _RX_NAO_CONTRATO.search(str(d.get("titulo") or ""))
                 and _cls_titulo(str(d.get("titulo") or ""))[1] in ("contrato", "ata_rp")]
    respostas = [d for d in docs if str(d.get("tipo") or "").lower() in _RESPOSTA]

    # ── A1 · CONTRATO ASSINADO ANTES DO PARECER ────────────────────────────────
    # O jurídico opinou depois de o contrato já existir. É o achado mais forte que
    # a árvore sozinha sustenta: não depende de ler o texto, só da ORDEM.
    # DUAS GUARDAS, medidas em 2026-08-04 sobre os 10 disparos do acervo (10 → 4):
    #
    # (1) NOTA TÉCNICA não é o parecer do art. 53. Cinco disparos se ancoravam numa — e a de
    #     SEI-510001/001309/2025 é da "Subsecretaria de Gestão e Fiscalização de Obras", assinada
    #     "na qualidade de Fiscais do Contrato": é nota de FISCALIZAÇÃO, posterior por natureza ao
    #     contrato que fiscaliza. Acusar art. 53 com ela é acusar o normal. "Nota técnica
    #     JURÍDICA" continua valendo — a exclusão é só da técnica pura.
    # (2) Parecer SEM TEXTO não ancora nada. Um disparo saía de um documento com ZERO caractere,
    #     tipado parecer só pelo título. É a doutrina que o A2 logo abaixo já aplica ("sem texto do
    #     parecer não há achado: vira lacuna, nunca conclusão por ausência") e que faltava aqui.
    #
    # O que os 10 tinham em comum e o refinamento remove: contrato PRÉ-EXISTENTE juntado como
    # anexo a processo posterior ("Anexo 16 - CONTRATO 020.2025", "Anexo Contrato nº 004/2020"),
    # com uma peça técnica depois. Ordem na árvore não é ordem de formalização quando a peça
    # anterior nem é do processo.
    # `d["texto"]` no manifesto é o CAMINHO do arquivo, não o teor — testá-lo seria um no-op
    # (foi o que eu escrevi primeiro). O teor se lê com `_texto_do_doc`, que já é a porta daqui.
    pareceres = [d for d in pareceres
                 if not _RX_NOTA_TECNICA.search(str(d.get("titulo") or ""))
                 and (_texto_do_doc(pasta, d) or "").strip()]
    if pareceres and contratos:
        p0, c0 = min(map(_ordem, pareceres)), min(map(_ordem, contratos))
        if c0 < p0:
            achados.append({
                "codigo": "A1_CONTRATO_ANTES_DO_PARECER",
                "grau": "alto",
                "diz": "contrato formalizado ANTES do parecer jurídico",
                "apoio": f"contrato na posição {c0} · parecer na posição {p0}",
            })

    # ── A2 · PARECER COM RESSALVA E SEM RESPOSTA ───────────────────────────────
    # Parecer que condiciona ou recomenda, e nenhum documento POSTERIOR que responda.
    # Sem texto do parecer não há achado: vira lacuna, nunca conclusão por ausência.
    for pa in pareceres:
        txt = _texto_do_doc(pasta, pa)
        if not txt:
            continue
        m_res = _RX_RESSALVA.search(txt)
        if not m_res or _e_forma(txt, m_res):
            continue
        pos = _ordem(pa)
        posteriores = [d for d in respostas if _ordem(d) > pos]
        acatou = any(_RX_ACATA.search(_texto_do_doc(pasta, d) or "") for d in posteriores)
        if not posteriores:
            achados.append({
                "codigo": "A2_PARECER_COM_RESSALVA_SEM_RESPOSTA",
                "grau": "alto",
                "diz": "parecer jurídico condiciona/recomenda e não há documento posterior que responda",
                "apoio": f"parecer na posição {pos}, {len(docs)} documentos no total",
            })
        elif not acatou:
            # AUSÊNCIA DE FÓRMULA NÃO É AUSÊNCIA DE RESPOSTA. `_RX_ACATA` procura o modo expresso
            # de acolher; quando ele não aparece, dizer "nenhum documento registra acatamento" é
            # afirmar uma ausência que muitas vezes não existe. Medido em 2026-08-04 nos 27
            # disparos: **18 tinham documento posterior citando o IDENTIFICADOR do parecer**, e o
            # que está escrito ali é resposta de verdade — "Em atendimento ao disposto no Despacho
            # PROMOÇÃO Nº 05/2024 (77129895), emitimos a Declaração, ratificando o interesse desta
            # Pasta"; "quanto ao apontamento contido no parágrafo 31 do Parecer nº 625/2024
            # (81625942), cumpre esclarecer que a competente sindicância foi instaurada".
            #
            # Citar o parecer não é o mesmo que ACATÁ-LO (há despacho que só encaminha os autos
            # depois dele), então o achado não some: ele passa a dizer o que se sabe — há resposta
            # que se reporta ao parecer, o acolhimento não está em fórmula expressa — e cai de
            # grau, porque a peça que decide já está nos autos para o fiscal ler.
            ids_par = _RE_ID_DOC.findall(str(pa.get("titulo") or ""))
            decisorios = [d for d in docs if _ordem(d) > pos
                          and _RX_ATO_DECISORIO.search(str(d.get("titulo") or ""))]
            responde = bool(ids_par) and any(
                ids_par[-1] in (_texto_do_doc(pasta, d) or "")
                for d in (posteriores + decisorios))
            (observacoes if nat == "repasse" else achados).append({
                "codigo": ("A3_REPASSE_PARECER_SEM_ACATAMENTO" if nat == "repasse"
                           else "A3_PARECER_COM_RESSALVA_SEM_ACATAMENTO_EXPRESSO"),
                "grau": "baixo" if (nat == "repasse" or responde) else "medio",
                "diz": ("há documento posterior que se REPORTA ao parecer, mas o acolhimento não "
                        "está em fórmula expressa — conferir o teor da resposta"
                        if responde else
                        "há documentos posteriores, mas nenhum registra acatamento do parecer"),
                "apoio": (f"parecer na posição {pos} · {len(posteriores)} documento(s) posterior(es)"
                          + (f" · um deles cita o identificador {ids_par[-1]}" if responde else "")),
            })
        break  # um achado por processo basta para a fila; o resto é da perícia

    # ── A4 · DESPESA SEM PESQUISA DE PREÇO NO PROCESSO ─────────────────────────
    # Só vale quando HÁ autorização de despesa ou empenho: aí a pesquisa deveria
    # estar. Sem nenhum dos dois, é lacuna de captura e não entra como achado.
    titulos = " | ".join(str(d.get("titulo") or "") for d in docs)
    tem_despesa = tipos.get("autorizacao_despesa", 0) or tipos.get("empenho", 0)
    tem_pesquisa = any(t in _PESQUISA for t in tipos) or bool(_RX_PESQ_TIT.search(titulos))
    if tem_despesa and not tem_pesquisa and len(docs) >= 8:
        observacoes.append({
            "codigo": "A4_DESPESA_SEM_PESQUISA_DE_PRECO",
            "grau": "medio",
            "diz": "processo autoriza despesa e não traz pesquisa de preços",
            "apoio": f"{tem_despesa} doc(s) de despesa, nenhum de pesquisa, {len(docs)} no total",
        })

    # ── A5 · EXECUÇÃO SEM EVIDÊNCIA ────────────────────────────────────────────
    tem_liq = tipos.get("liquidacao", 0) + tipos.get("nota_liquidacao", 0)
    tem_exec = any(t in _EXECUCAO for t in tipos) or bool(_RX_EXEC_TIT.search(titulos))
    fotos = int(man.get("fotos_total") or 0)
    if tem_liq and not tem_exec and not fotos:
        observacoes.append({
            "codigo": "A5_LIQUIDACAO_SEM_EVIDENCIA_DE_ENTREGA",
            "grau": "medio",
            "diz": "há liquidação e nenhuma evidência de execução (medição, atesto ou foto)",
            "apoio": f"{tem_liq} doc(s) de liquidação, 0 de execução, 0 fotos",
        })

    # A captura íntegra é o que permite atribuir a falta ao PROCESSO. Sem ela, a
    # mesma ausência pode ser nossa — e vender falha nossa como vício dele foi o
    # erro que pôs 874 processos na fila à toa.
    #
    # MEDIR PELO TEXTO, NÃO PELA ETIQUETA. A 1ª versão exigia
    # `qualidade_cache == "completo"` e zerou as lacunas de processo — mas só 791 de
    # 2.050 têm essa marca, e medido: os 1.259 "sem-marca" têm arquivo de texto em
    # **96%** dos casos. "Sem-marca" é arquivador antigo que não preenchia o campo,
    # não captura ruim. Pior: os **214 processos com lacuna declarada são TODOS
    # "sem-marca"** — o gate pela etiqueta jogava fora exatamente o que interessa.
    _txt = pasta / "texto"
    _n_txt = len(list(_txt.glob("*"))) if _txt.exists() else 0
    captura_integra = bool(docs) and _n_txt >= max(1, int(len(docs) * 0.6))
    lac = man.get("lacunas") or []
    return {
        "processo": man.get("processo") or pasta.name,
        "pasta": pasta.name,
        "n_docs": len(docs),
        "fotos": fotos,
        "qualidade": man.get("qualidade_cache") or "sem-marca",
        "natureza": nat,
        # TRÊS baldes. A lacuna do PROCESSO pesa como achado; a de CAPTURA é nossa.
        "lacunas_processo": lac if captura_integra else [],
        "lacunas_captura": [] if captura_integra else lac,
        "lacunas": lac,                       # compatibilidade com quem já lia isto
        "captura_integra": captura_integra,
        "achados": achados,
        # OBSERVAÇÃO ≠ ACHADO. A4 e A5 batiam em mais da METADE do acervo (149 e 132
        # de 299) mesmo depois de calibradas — e regra que acusa metade do universo
        # nao e fila, e ruido. A causa e estrutural e conhecida: a pesquisa de preco
        # costuma viver no processo de PLANEJAMENTO, nao no de pagamento, e a
        # evidencia de entrega as vezes fica fora do SEI. Ficam registradas, porque
        # somadas a um achado forte elas agravam — mas nao entram na fila sozinhas.
        # Auditor que exagera e ignorado: e a licao que o auditar_layout.py ja pagou.
        "observacoes": observacoes,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limite", type=int, default=0)
    ap.add_argument("--json", dest="saida", default="")
    a = ap.parse_args(argv)

    pastas = sorted(p for p in ARQUIVO.iterdir() if p.is_dir())
    if a.limite:
        pastas = pastas[: a.limite]

    linhas, cod, grau = [], Counter(), Counter()
    so_lacuna = com_achado = limpo = 0
    for pasta in pastas:
        r = periciar(pasta)
        if r is None:
            continue
        linhas.append(r)
        for x in r.get("observacoes", []):
            cod["(obs) " + x["codigo"]] += 1
        if r.get("lacunas_processo"):
            for _l in r["lacunas_processo"]:
                cod["LP_" + str(_l.get("falta", "?"))[:34].upper().replace(" ", "_")] += 1
            grau["lacuna_processo"] += len(r["lacunas_processo"])
        if r["achados"] or r.get("lacunas_processo"):
            com_achado += 1
            for x in r["achados"]:
                cod[x["codigo"]] += 1
                grau[x["grau"]] += 1
        elif r.get("lacunas_captura"):
            so_lacuna += 1
        else:
            limpo += 1

    print(f"\n=== TRIAGEM DETERMINÍSTICA · {len(linhas)} processos do acervo ===\n")
    print(f"  na FILA (achado ou lacuna do processo) .. {com_achado}")
    print(f"  só lacuna de CAPTURA (falha nossa) ...... {so_lacuna}")
    print(f"  sem achado e sem lacuna ................. {limpo}")
    print("\n  achados por código:")
    for k, v in cod.most_common():
        print(f"    {v:>5}  {k}")
    print("\n  por grau:", dict(grau))
    print("\n  LACUNA NÃO É ACHADO: os dois saem em campos separados e o fiscal")
    print("  vê a diferença antes de abrir o processo.")

    if a.saida:
        Path(a.saida).write_text(
            json.dumps(linhas, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n  laudo completo → {a.saida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
