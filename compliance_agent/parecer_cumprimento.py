# -*- coding: utf-8 -*-
"""PARECER DA PGE — as CONDICIONANTES foram CUMPRIDAS no processo? (pedido do dono 2026-07-24)

Por quê (o buraco que este módulo fecha): `sei_recomendacoes.auditar_acatamento` responde se a autoridade
ACOLHEU o parecer — eixo FORMAL. Mas o parecer jurídico quase nunca é um "sim/não": ele aprova **SOB
CONDIÇÃO** ("opino favoravelmente DESDE QUE: (i) seja juntada a pesquisa de preços; (ii) conste a dotação;
(iii) corrija-se a cláusula X"). Um despacho dizendo "acolho o parecer" NÃO prova que (i), (ii) e (iii)
foram efetivamente atendidos nos autos. O cumprimento é MATERIAL e se verifica item a item, nos documentos
**POSTERIORES** ao parecer.

Doutrina jurídica: art. 53 da Lei 14.133/2021 (análise jurídica prévia obrigatória) — a manifestação
vincula a instrução; a autoridade só diverge MOTIVADAMENTE (LINDB art. 22). Homologar/contratar com
condicionante pendente é instrução viciada (indício; Lei 8.429 art. 11 exige dolo, que NÃO se presume).

Camadas (mesma receita das outras famílias):
  1. DETERMINÍSTICA (offline): `extrair_condicionantes` → `verificar_cumprimento` → `auditar_parecer_pge`.
  2. SUBJETIVA (LLM, injetável): julga cumprimento MATERIAL (o determinístico vê a palavra; o LLM vê se a
     palavra tem lastro — "a pesquisa será providenciada oportunamente" não é cumprimento).
  3. FUSÃO `fundir_graus` (nenhum alarme silenciado) + `_versao_hash` p/ o snapshot versionado.

HONESTIDADE (cláusula JFN): documento POSTERIOR ausente ⇒ `NAO_VERIFICAVEL` (cobertura de leitura), NUNCA
"descumprida" — INDISPONÍVEL ≠ irregular. Cada status cita o TRECHO literal e o doc que o sustenta. Veredito
sempre RESOLVIDO (nunca 'indeterminado'/'indisponível').
"""
from __future__ import annotations

import json
import logging
import re

from compliance_agent.direcionamento_cerebro import _com_fusao, _parse_json
from compliance_agent.sei_recomendacoes import _RE_BOILERPLATE, classificar_emissor

logger = logging.getLogger(__name__)

# ───────────────────────────── 1. extração das condicionantes ─────────────────────────────
# Gatilho de CONDICIONALIDADE: onde o parecer deixa de ser opinião e vira condição de prosseguimento.
_RE_GATILHO = re.compile(
    r"(desde\s+que|condicionad[oa]s?\s+a|condiciona-?se|sob\s+(?:a\s+)?condi[çc][ãa]o\s+de|"
    r"observad[ao]s?\s+as\s+seguintes|com\s+as\s+seguintes\s+(?:ressalvas|recomenda[çc][õo]es|condicionantes)|"
    r"as\s+seguintes\s+(?:ressalvas|recomenda[çc][õo]es|condicionantes)|ressalvas?:|recomenda[çc][õo]es:|"
    r"sane-?se|providencie-?se|corrija-?se|"
    # 2026-08-02 — formas COLHIDAS no acervo (103 pareceres com fecho e zero condicionante). Cada
    # uma continua submetida às três proteções que já existiam: escopo no fecho, verbo opinativo a
    # até _JANELA_OPINATIVO e veto de transcrição de norma. Ficaram DE FORA de propósito "deverá
    # ser" e "necessário que" soltos: genéricos demais (4 e 1 ocorrência) e frequentes dentro de
    # citação legal — o ganho não paga o risco de falso positivo.
    r"sugere-?se\s+(?:a|o|que)|sugiro\s+que|"
    r"mediante\s+o?\s*atendimento\s+d|atendidas?\s+as\s+(?:recomenda|ressalv|condi)|"
    r"observadas?\s+as\s+(?:recomenda|ressalv|cautel)|"
    r"faz-?se\s+necess[áa]ri[ao]|"
    r"recomend(?:o|a-?se|amos)\s+(?:que|a\s|o\s|à\s))", re.I)

# Linguagem de EXIGÊNCIA em geral — não serve para extrair (não diz onde a exigência começa nem
# onde termina), serve para saber se o parecer cobra algo. É o que separa "não havia exigência"
# de "não consegui ler a exigência": sem essa distinção, 378 processos saíam com grau VERDE por
# falha de leitura da casa, e 160 deles tinham cobrança no texto.
_RE_EXIGENCIA = re.compile(
    r"\b(recomend\w+|imprescind\w+|indispens[áa]v\w+|necess[áa]ri[ao]s?|ressalv\w+|condicion\w+|"
    r"san(?:e|ar|ado|amento)\w*|providenci\w+|corrij\w+|suprir|dever[áa]\s+ser|dever[ãa]o\s+ser|"
    r"exig[eê]\w*|juntad[ao]s?)\b", re.I)
# Enumeração dos itens: (i)/(ii)/(iii)… · a)/b) · 1./2.
# aceita "(i)" e também "i." / "a." — formato real do acervo ("notadamente: i. … ii. … iii. …").
# O ponto sem parênteses só entra precedido de espaço/início e seguido de espaço, e a sequência ordinal
# (`_sequencia_valida`) descarta o que não formar lista — é o que impede "art." e "n." de virarem itens.
_RE_ITEM = re.compile(
    r"[\(\[]\s*(x{0,3}i{1,3}|iv|vi{0,3}|ix|x|[a-h])\s*[\)\]]"
    r"|(?:^|\s)(\d{1,2})\s*[\)\.]\s+"
    # 2026-08-02: aceita também "i)" / "a)" SEM parêntese de abertura — forma comuníssima no acervo
    # ("a saber: i) juntada da pesquisa de preços; ii) comprovação da dotação"). Sem ela, a lista
    # inteira virava UMA condicionante em bloco e a verificação item a item se perdia. A guarda é a
    # mesma da variante com ponto: precedido de espaço/dois-pontos e validado por `_sequencia_valida`.
    r"|(?:^|[\s:;])(i{1,3}|iv|vi{0,3}|ix|[a-h])[\).]\s+", re.I)
_MAX_COND = 400   # corte do texto de uma condicionante (o trecho é literal, mas não despeja o parecer inteiro)
_CABECALHO = 1200  # janela do topo onde um parecer se identifica (o resto do texto é fundamentação)
_MIN_COND = 25    # anti-FP (arquivo SEI real): "(a) Engenheiro" não é condicionante, é rótulo solto

# FECHO do parecer — onde mora o que ELE exige. Medido no acervo (parecer de 101 mil caracteres): o
# primeiro gatilho de condicionalidade aparecia lá atrás, na FUNDAMENTAÇÃO, dentro de uma citação a outro
# parecer ("celebrado desde que seguidas as condições … do Parecer nº 02/2017") — e essa citação virava
# "a condicionante". Havendo fecho, a leitura começa nele; sem fecho, o parecer inteiro vale (curtos).
_RE_CONCLUSAO = re.compile(
    r"(isto\s+posto|ante\s+o\s+exposto|diante\s+d[oe]\s+exposto|pelo\s+exposto|face\s+ao\s+exposto|"
    r"em\s+face\s+do\s+exposto|conclus[ãa]o\s*[:.\-]|concluo|posto\s+isso|do\s+exposto|ex\s+positis|"
    r"[ée]\s+o\s+parecer|sub\s+censura|salvo\s+melhor\s+ju[íi]zo)", re.I)

# VERBO OPINATIVO — o que separa a exigência DESTE parecer de tudo o mais que ele contém. Dois falsos
# positivos reais mostraram que o gatilho sozinho não basta:
#   • aula de doutrina: "Resoluções são atos administrativos … DESDE QUE complementar à lei" (Parecer 126,
#     96 mil caracteres);
#   • transcrição de norma: "nos termos do Decreto nº …, o expediente deverá ser instruído com: (i) … (ii) …"
#     — repetida IDÊNTICA em vários processos, porque é a norma, não o caso.
# Condicionante é o que o parecerista IMPÕE; ela anda colada a "opino/recomendo/condiciono/determino".
_RE_OPINATIVO = re.compile(
    r"\b(opino|opina-?se|opinamos|recomendo|recomenda-?se|recomendamos|condiciono|condiciona-?se|"
    r"determino|determina-?se|manifesto-?me|sugiro|sugere-?se|concluo|conclui-?se|entendo\s+que|"
    r"aprovo|aprova-?se|autorizo|ressalvo|ressalva-?se)\b", re.I)
_JANELA_OPINATIVO = 400   # distância máxima entre o verbo opinativo e o gatilho (mesmo período/parágrafo)

# TRANSCRIÇÃO DE NORMA logo antes do gatilho: o que vem é o texto legal, não a exigência do parecerista.
_RE_TRANSCRICAO = re.compile(
    r"(nos\s+termos\s+d[oae]s?|na\s+forma\s+d[oae]s?|conforme\s+(?:disp[õo]e|prev[êe]|estabelece)|"
    r"disp[õo]e\s+o\s+art|prev[êe]\s+o\s+art|estabelece\s+o\s+art|segundo\s+o\s+art|"
    # O ponto que separa períodos encerra a janela — mas o ponto de "art. 92" e de "14.133" não é
    # fim de período. Sem esta exceção o veto não alcançava a forma mais comum de citação legal
    # ("nos termos do art. 92 da Lei 14.133/2021, faz-se necessária…") e a norma virava exigência.
    r"reza\s+o\s+art|de\s+acordo\s+com\s+o\s+art)(?:[^.]|\.(?=\s*\d)){0,80}$", re.I)

# O documento É um parecer? (anti-FP medido no arquivo SEI real 2026-07-24: minutas e contratos CITAM a
# Procuradoria — "previamente examinado pela PGE" — e viravam falsos pareceres, com cláusulas contratuais
# extraídas como se fossem condicionantes.) Exige a MARCA da peça opinativa, não a mera citação do órgão.
_RE_PECA_PARECER = re.compile(
    r"\b(parecer\s*(?:n?[ºo°.]|\s+n[ºo°]|\s+jur[ií]dic|\s+PGE|\s+normativ)|opino|opina-?se|"
    r"manifesta[çc][ãa]o\s+jur[ií]dica|nota\s+t[ée]cnica\s+jur[ií]dica|promo[çc][ãa]o\s+de\s+arquivamento|"
    r"cota\s+jur[ií]dica|encaminhe-?se\s+.{0,40}\bap[óo]s\s+o\s+parecer)\b", re.I)
# ... e o que o documento NÃO pode ser (peças que citam a PGE mas são outra coisa)
# Tipos que o classificador canônico de documentos do SEI já resolve como peça opinativa jurídica.
# `parecer_tecnico` NÃO entra: parecer técnico não é análise jurídica do art. 53.
_TIPOS_CANONICOS_PARECER = {"parecer", "parecer_juridico", "manifestacao_juridica", "cota_juridica"}
_RE_NAO_PARECER = re.compile(
    r"\b(contrato\s+n[ºo°.]|termo\s+de\s+contrato|termo\s+aditivo|ata\s+de\s+registro\s+de\s+pre[çc]os|"
    r"minuta\s+de\s+contrato|edital\s+de|nota\s+de\s+empenho|ordem\s+banc[áa]ria)\b", re.I)


def e_parecer(tipo: str, texto: str) -> bool:
    """O documento é uma PEÇA OPINATIVA (parecer/manifestação jurídica)? Citar a Procuradoria não basta —
    contrato, ata e edital costumam citá-la. O TÍTULO manda: 'Parecer …' no tipo decide; no corpo, exige
    marca de opinião ('opino', 'parecer nº') e ausência de marca de contrato/ata/edital."""
    rot = (tipo or "")
    # O classificador de documentos da casa já responde isto: se ele disse `parecer`, é parecer.
    # Ignorá-lo custava caro — medido em 2026-08-02, dos 506 processos com documento de tipo
    # canônico `parecer` só 157 passavam aqui, e o entregável afirmava "nenhum parecer entre os
    # documentos lidos" em 349 processos que tinham um.
    if rot.strip().lower() in _TIPOS_CANONICOS_PARECER:
        return True
    if _RE_PECA_PARECER.search(rot):
        return True
    if _RE_NAO_PARECER.search(rot):
        return False
    # No CORPO, a marca vale só no CABEÇALHO: um parecer se anuncia no topo ("PARECER Nº …/… ", "opino").
    # Citação a outro parecer aparece no meio do texto — e foi assim que um anexo de 38 mil caracteres
    # ("Anexo 2024PD26194", programação de desembolso) passou por peça opinativa no acervo real.
    corpo = (texto or "")[:_CABECALHO]
    peca = _RE_PECA_PARECER.search(corpo)
    if not peca:
        return False
    # O veto é POSICIONAL: identidade é o que o documento anuncia PRIMEIRO. Varrer 3.000 caracteres
    # atrás de "TERMO ADITIVO"/"EDITAL DE" barrava justamente o parecer que OPINA sobre o aditivo —
    # citar a peça analisada é o que todo parecer faz. Quem se anuncia contrato antes segue fora.
    nao = _RE_NAO_PARECER.search(corpo)
    return not (nao and nao.start() < peca.start())


def _sequencia_valida(marcas: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Mantém só a enumeração REAL: os rótulos que seguem, em ordem, a sequência iniciada pelo primeiro
    item (i,ii,iii… · a,b,c… · 1,2,3…). Anti-FP: '(x) do anexo' e '(b) do contrato' soltos no meio do
    texto não formam lista e são descartados."""
    if not marcas:
        return []
    romanos = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"]
    letras = [chr(c) for c in range(ord("a"), ord("i"))]
    primeiro = marcas[0][1]
    if primeiro in ("i", "ii", "iii", "iv", "v"):        # trata 'i' como romano (mais comum em parecer)
        serie = romanos
    elif primeiro.isdigit():
        serie = [str(n) for n in range(1, 21)]
    else:
        serie = letras
    if primeiro not in serie:
        return []
    esperado = serie.index(primeiro)
    out = []
    for pos, rot in marcas:
        if esperado < len(serie) and rot == serie[esperado]:
            out.append((pos, rot))
            esperado += 1
    return out

# TIPO da condicionante — ordem IMPORTA (a 1ª que casar vence: da mais específica para a mais genérica).
_TIPOS: tuple[tuple[str, str], ...] = (
    ("pesquisa_precos", r"pesquisa\s+de\s+pre[çc]os|mapa\s+de\s+pre[çc]os|cota[çc][õo]es|or[çc]amento\s+estimado|"
                        r"pesquisa\s+mercadol[óo]gica"),
    ("dotacao_orcamentaria", r"dota[çc][ãa]o|adequa[çc][ãa]o\s+or[çc]ament|disponibilidade\s+or[çc]ament|"
                             r"reserva\s+or[çc]ament|programa\s+de\s+trabalho|LDO|LOA"),
    ("regularidade_fiscal", r"certid[ãa]o|regularidade\s+(?:fiscal|trabalhista)|CND\b|SICAF|FGTS|INSS"),
    ("garantia_contratual", r"garantia\s+(?:contratual|de\s+execu[çc][ãa]o)|seguro-?garantia|cau[çc][ãa]o"),
    ("designacao_fiscal", r"fiscal\s+do\s+contrato|gestor\s+do\s+contrato|designa[çc][ãa]o\s+de\s+fiscal"),
    ("publicidade", r"publica[çc][ãa]o|di[áa]rio\s+oficial|divulga[çc][ãa]o\s+no\s+PNCP|extrato"),
    ("minuta_clausula", r"cl[áa]usula|minuta"),
    ("estudo_justificativa", r"justificativa|motiva[çc][ãa]o|estudo\s+t[ée]cnico|ETP\b|termo\s+de\s+refer[êe]ncia|"
                             r"projeto\s+b[áa]sico"),
    ("prazo_vigencia", r"vig[êe]ncia|prazo\s+contratual|cronograma"),
)


_NUCLEO = 160   # a exigência mora no COMEÇO do item; o resto costuma ser fundamentação/remissão legal


def classificar_condicionante(texto: str) -> str:
    """Tipo da condicionante pelo NÚCLEO da exigência (primeiras ~160 chars). Anti-FP real: um item que
    pede pesquisa de preços e ao fim remete às regras de publicação no DO era classificado 'publicidade'
    — e passava a ser 'cumprido' por qualquer publicação nos autos.

    Sem tipo no núcleo, o retorno é 'outra' — e NÃO se procura a palavra-chave no resto do item: foi
    exatamente assim que "parecer conclusivo do órgão de assessoramento jurídico … sobre a forma de
    publicação" virou 'publicidade' e passou a ser "cumprido" por qualquer publicação nos autos. 'outra'
    é honesto: sem verificador determinístico, quem julga é a camada subjetiva.
    """
    nucleo = (texto or "")[:_NUCLEO]
    for nome, pat in _TIPOS:
        if re.search(pat, nucleo, re.I):
            return nome
    return "outra"


def _limpa(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())[:_MAX_COND]


def extrair_condicionantes(texto_parecer: str) -> list[dict]:
    """Condicionantes (o que o parecer EXIGE para o feito prosseguir), item a item.

    Retorna [{id, texto, tipo, trecho}] — `id` é o rótulo do item no parecer ('i','ii','a','1') ou 'unica'.
    HONESTO: nada de inventar — parecer sem gatilho de condicionalidade devolve []; boilerplate de
    checklist/certidão (que casa 'recomenda-se' mas não é ressalva substantiva) é descartado."""
    txt = texto_parecer or ""
    # a exigência deste parecer está no FECHO; o que vem antes é relatório e fundamentação (onde moram as
    # citações a outros pareceres). Só se recua para o texto inteiro quando não há fecho identificável.
    mc = None
    for mc in _RE_CONCLUSAO.finditer(txt):
        pass                       # a ÚLTIMA ocorrência é o fecho de verdade (as outras são anúncios)
    escopo = txt[mc.start():] if mc else txt
    # entre todos os gatilhos do escopo, vale o que o PARECERISTA impõe: precedido de verbo opinativo por
    # perto e NÃO precedido de marca de transcrição de norma.
    m = None
    for cand in _RE_GATILHO.finditer(escopo):
        antes = escopo[max(0, cand.start() - _JANELA_OPINATIVO):cand.start()]
        if _RE_TRANSCRICAO.search(antes.rstrip()):
            continue                      # o que vem a seguir é a norma citada, não a exigência
        if _RE_OPINATIVO.search(antes) or (mc and cand.start() < 200):
            m = cand
            break
    if not m:
        return []
    corpo = escopo[m.end():]
    marcas = _sequencia_valida(
        [(mm.start(), (mm.group(1) or mm.group(2) or mm.group(3) or "").lower())
         for mm in _RE_ITEM.finditer(corpo)])
    conds: list[dict] = []
    if len(marcas) >= 2:
        for j, (pos, rot) in enumerate(marcas):
            fim = marcas[j + 1][0] if j + 1 < len(marcas) else len(corpo)
            item = _limpa(corpo[pos:fim])
            item_sem_rotulo = _limpa(re.sub(r"^[\(\[]?\s*[a-z0-9ivx]{1,3}\s*[\)\].]\s*", "", item, flags=re.I))
            if item_sem_rotulo:
                conds.append({"id": rot, "texto": item_sem_rotulo, "trecho": item})
    else:
        # condicionante ÚNICA em prosa: da condição até o fim do período
        frase = re.split(r"(?<=[.;])\s+(?=[A-ZÀ-Ú])", corpo.strip())[0] if corpo.strip() else ""
        frase = _limpa(frase)
        if frase:
            conds.append({"id": "unica", "texto": frase, "trecho": _limpa(m.group(0) + " " + frase)})
    # descarta boilerplate (checklist/autenticidade) e fragmentos curtos demais para serem exigência
    conds = [c for c in conds
             if not _RE_BOILERPLATE.search(c["texto"]) and len(c["texto"]) >= _MIN_COND]
    for c in conds:
        c["tipo"] = classificar_condicionante(c["texto"])
    return conds


# ───────────────────────────── 2. verificação do cumprimento ─────────────────────────────
# Marcadores de CUMPRIMENTO por tipo, procurados nos documentos POSTERIORES ao parecer. São a PROVA
# documental de que a exigência entrou nos autos (não a mera promessa de fazê-lo).
_CUMPRE: dict[str, str] = {
    "pesquisa_precos": r"pesquisa\s+de\s+pre[çc]os|mapa\s+de\s+pre[çc]os|(?:tr[êe]s|3)\s+cota[çc][õo]es|"
                       r"cota[çc][õo]es\s+(?:anexad|juntad)|pesquisa\s+mercadol[óo]gica",
    "dotacao_orcamentaria": r"dota[çc][ãa]o|adequa[çc][ãa]o\s+or[çc]ament|programa\s+de\s+trabalho|"
                            r"nota\s+de\s+empenho|reserva\s+or[çc]ament",
    "regularidade_fiscal": r"certid[ãa]o\s+negativa|certid[õo]es\s+(?:negativas|juntad)|regularidade\s+fiscal|"
                           r"CND\b|consulta\s+ao\s+SICAF",
    "garantia_contratual": r"garantia\s+(?:contratual|prestada|de\s+execu[çc][ãa]o)|seguro-?garantia|"
                           r"comprovante\s+de\s+cau[çc][ãa]o",
    "designacao_fiscal": r"designo|designa[çc][ãa]o\s+d[eo]|portaria\s+de\s+designa[çc][ãa]o|fiscal\s+designad",
    "publicidade": r"publicad[oa]|extrato\s+publicado|di[áa]rio\s+oficial|divulgad[oa]\s+no\s+PNCP",
    "minuta_clausula": r"retificad|suprimid|corrigid|nova\s+minuta|minuta\s+(?:revisada|ajustada|alterada)|"
                       r"altera[çc][ãa]o\s+da\s+cl[áa]usula",
    "estudo_justificativa": r"justificativa\s+(?:apresentada|juntada|acostada)|estudo\s+t[ée]cnico\s+preliminar|"
                            r"ETP\s+(?:juntad|anexad)|termo\s+de\s+refer[êe]ncia\s+(?:retificad|revisad)",
    "prazo_vigencia": r"vig[êe]ncia\s+(?:ajustada|retificada|corrigida)|cronograma\s+(?:juntado|anexado)",
}
# menção genérica de atendimento (vale como evidência SÓ com o marcador específico do tipo, para não
# transformar "em atendimento ao parecer, informo que providenciarei" em cumprimento)
_RE_ATENDIMENTO = re.compile(
    r"em\s+(?:atendimento|cumprimento)\s+(?:ao|[àa]|aos|[àa]s)\s+(?:parecer|recomenda|ressalva|condicionante|"
    r"determina)|conforme\s+(?:solicitado|determinado|recomendado)\s+(?:pela|pelo)\s+(?:PGE|PGM|CGE|CGM|"
    r"procuradoria|controladoria)", re.I)
# PROMESSA ≠ cumprimento (anti-FP): "será providenciada", "oportunamente", "em momento oportuno"
_RE_PROMESSA = re.compile(
    r"ser[áã]o?\s+(?:providenciad|juntad|apresentad|anexad)|oportunamente|em\s+momento\s+oportuno|"
    r"posteriormente\s+ser[áã]", re.I)
# ato DECISÓRIO forte posterior: o processo AVANÇOU (homologou/adjudicou/contratou/autorizou) — é o que
# transforma "não achei a prova" em "seguiu sem cumprir" (indício). Sem ele, fica NAO_VERIFICAVEL.
_RE_DECISORIO = re.compile(
    r"\b(homolog|adjudic|autorizo|ratifico|contrato\s+n|termo\s+de\s+contrato|assinatura\s+do\s+contrato|"
    r"ordem\s+de\s+in[íi]cio)", re.I)


def _evidencia(texto: str, pat: str, janela: int = 110) -> str:
    m = re.search(pat, texto or "", re.I)
    if not m:
        return ""
    a, b = max(0, m.start() - janela), min(len(texto), m.end() + janela)
    return _limpa(texto[a:b])


def verificar_cumprimento(condicionantes: list[dict], docs_posteriores: list[dict]) -> list[dict]:
    """Para CADA condicionante, procura a prova documental nos documentos POSTERIORES ao parecer.

    status: CUMPRIDA (marcador específico do tipo num doc posterior) · NAO_CUMPRIDA (nenhuma prova E o
    processo AVANÇOU com ato decisório — homologação/contrato) · NAO_VERIFICAVEL (nenhuma prova e nenhum
    ato decisório posterior lido — pode ser cobertura de leitura; INDISPONÍVEL ≠ descumprido).
    """
    avancou = any(_RE_DECISORIO.search(f"{d.get('tipo') or ''} {d.get('texto') or ''}")
                  for d in docs_posteriores or [])
    out = []
    for c in condicionantes:
        pat = _CUMPRE.get(c["tipo"])
        achado = None
        for d in docs_posteriores or []:
            txt = d.get("texto") or ""
            if pat and re.search(pat, txt, re.I) and not _RE_PROMESSA.search(txt):
                achado = {"doc_ref": d.get("ref"), "doc_tipo": d.get("tipo"),
                          "evidencia": _evidencia(txt, pat),
                          "mencao_expressa": bool(_RE_ATENDIMENTO.search(txt))}
                break
        if achado:
            item = {**c, "status": "CUMPRIDA", **achado,
                    "observacao": "Prova documental do atendimento localizada em documento posterior ao parecer."}
        elif not pat:
            # HONESTIDADE: não existe marcador determinístico para este tipo de exigência. "Não sei
            # verificar" ≠ "não foi cumprida" — o julgamento fica para a camada subjetiva (LLM/auditor).
            item = {**c, "status": "NAO_VERIFICAVEL", "doc_ref": None, "evidencia": "",
                    "observacao": ("Exigência genérica, sem verificador determinístico: exige LEITURA dos "
                                   "documentos posteriores (camada LLM/auditor) — não se presume descumprida.")}
        elif avancou:
            item = {**c, "status": "NAO_CUMPRIDA", "doc_ref": None, "evidencia": "",
                    "observacao": ("O processo AVANÇOU (homologação/adjudicação/contrato) e não há, nos "
                                   "documentos posteriores lidos, prova do atendimento desta condicionante — "
                                   "indício de instrução viciada (art. 53 Lei 14.133), a confirmar.")}
        else:
            item = {**c, "status": "NAO_VERIFICAVEL", "doc_ref": None, "evidencia": "",
                    "observacao": ("Não há documento posterior ao parecer entre os LIDOS que comprove (ou "
                                   "negue) o atendimento — cobertura de captura, NÃO descumprimento.")}
        out.append(item)
    return out


# ───────────────────────────── 3. veredito determinístico ─────────────────────────────
_RESSALVA = ("INDISPONÍVEL ≠ irregular: documento posterior não lido não é condicionante descumprida; "
             "indício a apurar, não acusação; presunção de legitimidade dos atos administrativos")


def _pareceres_com_condicionantes(docs: list[dict]) -> list[dict]:
    """Localiza, na ORDEM do processo, os pareceres de PGE/PGM/CGE/CGM/jurídico e extrai as condicionantes
    de cada um (guardando o índice, que define o que é documento POSTERIOR)."""
    achados = []
    for i, d in enumerate(docs or []):
        texto = d.get("texto") or ""
        tipo = d.get("tipo") or ""
        emissor = classificar_emissor(texto) or classificar_emissor(tipo)
        # DOIS gates: (1) órgão de controle/jurídico E (2) o doc É peça opinativa — citar a PGE num
        # contrato não faz dele parecer (falso positivo medido no arquivo SEI real).
        if not emissor or not e_parecer(tipo, texto):
            continue
        achados.append({"i": i, "ref": d.get("ref"), "tipo": tipo, "emissor": emissor,
                        "condicionantes": extrair_condicionantes(texto)})
    return achados


def auditar_parecer_pge(docs: list[dict]) -> dict:
    """Veredito DETERMINÍSTICO e RESOLVIDO do CUMPRIMENTO das condicionantes do parecer jurídico.

    `docs`: documentos NA ORDEM do processo [{ref, tipo, texto}] (a ordem é o que separa "antes" de
    "depois" do parecer — prova anterior não cumpre exigência posterior).

    Vereditos: SEM_PARECER_LOCALIZADO · SEM_CONDICIONANTES · CUMPRIDO_INTEGRAL · CUMPRIDO_PARCIAL ·
    DESCUMPRIDO_INDICIO · COBERTURA_INSUFICIENTE. Grau: verde/amarelo/vermelho/nao_aplicavel.
    """
    pareceres = _pareceres_com_condicionantes(docs)
    if not pareceres:
        return {"veredito": "SEM_PARECER_LOCALIZADO", "grau": "nao_aplicavel", "condicionantes": [],
                "n_cumpridas": 0, "n_nao_cumpridas": 0, "n_nao_verificaveis": 0, "pareceres": [],
                "leitura": ("Nenhum parecer de PGE/PGM/CGE/CGM/jurídico entre os documentos LIDOS. O art. 53 "
                            "da Lei 14.133/2021 exige análise jurídica prévia — mas leitura parcial ≠ "
                            "inexistência: conferir a íntegra do processo antes de apontar."),
                "acao": "capturar o processo completo (árvore SEI) e reavaliar",
                "ressalva": _RESSALVA, "fonte": "parecer_cumprimento (determinístico/offline)"}
    todas: list[dict] = []
    for p in pareceres:
        posteriores = [d for j, d in enumerate(docs or []) if j > p["i"]]
        for item in verificar_cumprimento(p["condicionantes"], posteriores):
            todas.append({**item, "parecer_ref": p["ref"], "emissor": p["emissor"]})
    if not todas:
        base = {"condicionantes": [], "n_cumpridas": 0, "n_nao_cumpridas": 0, "n_nao_verificaveis": 0,
                "pareceres": [{k: p[k] for k in ("ref", "emissor")} for p in pareceres],
                "ressalva": _RESSALVA, "fonte": "parecer_cumprimento (determinístico/offline)"}
        # Verde só quando o parecer de fato não cobra nada. Se ele cobra e a extração não alcançou,
        # o honesto é dizer que o limite é da LEITURA da casa — INDISPONÍVEL ≠ regularidade.
        cobra = any(_RE_EXIGENCIA.search(d.get("texto") or "") for d in docs or []
                    if e_parecer(d.get("tipo") or "", d.get("texto") or ""))
        if cobra:
            return {**base, "veredito": "CONDICIONANTES_NAO_EXTRAIDAS", "grau": "amarelo",
                    "leitura": ("Há parecer jurídico/de controle nos autos e ele usa linguagem de "
                                "EXIGÊNCIA (recomendação/ressalva/saneamento), mas a leitura automática "
                                "não conseguiu isolar as condicionantes item a item. Isto é limite de "
                                "LEITURA desta casa, não atestado de regularidade: INDISPONÍVEL ≠ "
                                "cumprido e ≠ inexistente."),
                    "acao": "ler o parecer na íntegra e listar as condicionantes à mão antes de "
                            "concluir qualquer coisa sobre o cumprimento"}
        return {**base, "veredito": "SEM_CONDICIONANTES", "grau": "verde",
                "leitura": ("Há parecer jurídico/de controle nos autos e nenhuma CONDICIONANTE substantiva "
                            "(aprovação sem ressalva de cumprimento) — nada a cobrar quanto a condicionantes."),
                "acao": ""}
    n_ok = sum(1 for c in todas if c["status"] == "CUMPRIDA")
    n_nao = sum(1 for c in todas if c["status"] == "NAO_CUMPRIDA")
    n_nv = sum(1 for c in todas if c["status"] == "NAO_VERIFICAVEL")
    pend = "; ".join(f"({c['id']}) {c['tipo']}" for c in todas if c["status"] == "NAO_CUMPRIDA")
    if n_nao and n_ok:
        veredito, grau = "CUMPRIDO_PARCIAL", "vermelho"
        leitura = (f"Das {len(todas)} condicionantes do parecer, {n_ok} têm prova nos autos e {n_nao} NÃO — e "
                   f"ainda assim o processo avançou (homologação/contrato). Pendentes: {pend}. Indício de "
                   "instrução viciada (art. 53 Lei 14.133; LINDB art. 22), a confirmar em documento não lido.")
        acao = "cobrar a comprovação das condicionantes pendentes (diligência) antes de qualquer peça"
    elif n_nao:
        veredito, grau = "DESCUMPRIDO_INDICIO", "vermelho"
        leitura = (f"NENHUMA das {len(todas)} condicionantes do parecer tem prova de atendimento nos documentos "
                   f"posteriores, e o processo avançou (homologação/adjudicação/contrato). Pendentes: {pend}. "
                   "Indício FORTE de que o controle prévio foi contornado (art. 53 Lei 14.133) — indício, "
                   "não acusação: confirmar se há documento posterior não capturado.")
        acao = "diligência: exigir a comprovação do atendimento das condicionantes e o despacho de acolhimento"
    elif n_nv:
        veredito, grau = "COBERTURA_INSUFICIENTE", "amarelo"
        leitura = (f"O parecer impôs {len(todas)} condicionante(s) e NÃO há documento posterior lido que "
                   f"comprove ou negue o atendimento ({n_nv} não verificável(is), {n_ok} com prova). "
                   "Fragilidade de CAPTURA, não de mérito — INDISPONÍVEL ≠ descumprido.")
        acao = "capturar os documentos posteriores ao parecer (árvore SEI completa) e reavaliar"
    else:
        veredito, grau = "CUMPRIDO_INTEGRAL", "verde"
        leitura = (f"Todas as {len(todas)} condicionantes do parecer têm prova documental de atendimento em "
                   "documento posterior — cadeia de controle prévio regular quanto ao cumprimento.")
        acao = ""
    return {"veredito": veredito, "grau": grau, "condicionantes": todas, "n_cumpridas": n_ok,
            "n_nao_cumpridas": n_nao, "n_nao_verificaveis": n_nv,
            "pareceres": [{k: p[k] for k in ("ref", "emissor")} for p in pareceres],
            "leitura": leitura, "acao": acao, "ressalva": _RESSALVA,
            "fonte": "parecer_cumprimento (determinístico/offline)"}


# ───────────────────────────── 4. camada subjetiva (LLM) + fusão ─────────────────────────────
_SYS = (
    "Você é AUDITOR DE CONTROLE EXTERNO (TCE-RJ) verificando se as CONDICIONANTES de um parecer jurídico "
    "(PGE/PGM/CGE/jurídico) foram MATERIALMENTE cumpridas nos documentos POSTERIORES do processo. "
    "Regras ABSOLUTAS: (1) indício ≠ acusação (presunção de legitimidade). (2) PROMESSA NÃO É CUMPRIMENTO: "
    "'será providenciado', 'oportunamente', 'informo que serão juntados' = NÃO cumprida. (3) Menção formal "
    "('em atendimento ao parecer') sem o documento correspondente = NÃO cumprida. (4) Se os documentos "
    "posteriores não permitem concluir, diga 'nao_verificavel' — NUNCA invente cumprimento nem "
    "descumprimento. (5) Ausência de documento pode ser captura incompleta: INDISPONÍVEL ≠ descumprido. "
    "Responda SOMENTE um objeto JSON no schema pedido, sem texto fora do JSON."
)
_SCHEMA = (
    '{"grau":"verde|amarelo|vermelho","cumpridas":["id"],"nao_cumpridas":["id"],'
    '"nao_verificaveis":["id"],"resumo":"1-2 frases (indício, não acusação)",'
    '"analise_por_item":[{"id":"","veredito":"cumprida|nao_cumprida|nao_verificavel","por_que":"",'
    '"trecho":"literal do documento posterior"}],"dados_suficientes":true}'
)
_MAX_DOC = 1200


def _montar_user(det: dict, docs_posteriores: list[dict]) -> str:
    linhas = ["CONDICIONANTES DO PARECER (verificar UMA A UMA):"]
    for c in det.get("condicionantes", []):
        linhas.append(f"  ({c['id']}) [{c['tipo']}] {c['texto']}")
        linhas.append(f"       leitura determinística: {c['status']}"
                      + (f" — evidência: \"{c['evidencia']}\"" if c.get("evidencia") else ""))
    linhas.append("\nDOCUMENTOS POSTERIORES AO PARECER (a prova, se houver, está aqui):")
    for d in docs_posteriores[:12]:
        linhas.append(f"  [{d.get('ref')}] {d.get('tipo') or ''}: {_limpa((d.get('texto') or ''))[:_MAX_DOC]}")
    linhas.append("\nResponda no schema: " + _SCHEMA)
    return "\n".join(linhas)


async def avaliar_parecer_cumprimento(docs: list[dict], *, gerar=None, contexto: dict | None = None) -> dict:
    """Veredito FUNDIDO (determinístico × LLM) do cumprimento das condicionantes do parecer.

    `gerar`: callable async(messages)->str. **None ⇒ só a camada determinística** (offline, honesto — não
    chama rede). Em produção, injete `direcionamento_cerebro._gerar_default` (Gemini rotacionado).
    Acrescenta `_versao_hash` (assinatura da captura) para o snapshot versionado em `analise_remotes`.
    """
    det = auditar_parecer_pge(docs)
    from compliance_agent import analise_remotes
    texto_todo = "\n\n".join((d.get("texto") or "") for d in docs or [])
    det["_versao_hash"] = analise_remotes.hash_versao(texto_todo)
    grau_det = det.get("grau")
    # LLM não roda quando não há o que julgar (sem parecer/sem condicionante) nem quando não foi injetado
    if gerar is None or not det.get("condicionantes"):
        return _com_fusao({**det, "contexto": contexto or {}}, None, grau_det)
    pareceres = _pareceres_com_condicionantes(docs)
    corte = min((p["i"] for p in pareceres), default=-1)
    posteriores = [d for j, d in enumerate(docs or []) if j > corte]
    messages = [{"role": "system", "content": _SYS},
                {"role": "user", "content": _montar_user(det, posteriores)}]
    try:
        raw = await gerar(messages)
    except Exception as e:  # noqa: BLE001 — LLM indisponível: o veredito objetivo SUSTENTA (não fica cego)
        logger.debug("avaliar_parecer_cumprimento: LLM indisponível: %s", e)
        return _com_fusao({**det, "_llm_erro": str(e)[:80],
                           "leitura": det["leitura"] + f" (parecer interpretativo não gerado: {str(e)[:40]})"},
                          None, grau_det)
    dados = _parse_json(raw)
    if not isinstance(dados, dict):
        return _com_fusao({**det, "_llm_erro": "resposta não-parseável"}, None, grau_det)
    llm = {k: dados.get(k) for k in ("cumpridas", "nao_cumpridas", "nao_verificaveis", "resumo",
                                     "analise_por_item", "dados_suficientes")}
    return _com_fusao({**det, "llm": llm}, dados.get("grau"), grau_det)


def para_json(veredito: dict) -> str:
    """Serializa o veredito (para persistência/snapshot). Mantém acentuação."""
    return json.dumps(veredito, ensure_ascii=False)
