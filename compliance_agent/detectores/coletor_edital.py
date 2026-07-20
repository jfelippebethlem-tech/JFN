# -*- coding: utf-8 -*-
"""COLETOR SEI → ctx dos detectores (a ponte do mundo real para o pipeline).

Transforma a íntegra de um processo lido do SEI (``tools.sei_reader.ler`` — o reader autenticado/cracked,
que já lê processo de OUTRA unidade) no ``ctx`` que os detectores de EDITAL/PLANEJAMENTO/JULGAMENTO consomem,
e roda o pipeline em DADO REAL. Esta é a camada 1 (Extração) do spec V2: REGEX/heurística determinística pega
o que dá; o que sobra vai para o LLM-OPCIONAL (extração estruturada, schema JSON fixo, citação obrigatória).

ARQUITETURA (honestidade JFN, cláusula absoluta):
  • Cada campo extraído carrega PROVENIÊNCIA (qual doc/trecho o originou) — nunca um número solto sem fonte.
  • Campo que o regex NÃO pega e o LLM não confirma → fica FORA do ctx. O detector então marca aquele eixo
    como ``nao_avaliavel`` por construção (campo ausente ≠ 0). NUNCA inventamos data/valor/exigência.
  • LLM-opcional via ``direcionamento_cerebro.gerar_sync`` (Gemini→Groq→Cerebras). Sem LLM (ou ``usar_llm=False``),
    o coletor degrada honesto: só o que o regex pegou entra no ctx; o resto fica de fora.

O QUE O REGEX EXTRAI HOJE (determinístico):
  • datas de publicação/abertura/proposta (rótulo + data dd/mm/aaaa ou ISO);
  • modalidade (pregão/concorrência/concurso/leilão/diálogo competitivo/dispensa) + critério de julgamento;
  • exigências de habilitação tipo "atestado de capacidade técnica", "capital social"/"patrimônio líquido X%/R$";
  • lotes/itens (cabeçalho "LOTE N" + linhas de item, CATMAT/CATSER quando citado);
  • valor estimado/de referência (R$).
O QUE FICA P/ LLM-OPCIONAL / COLETOR PNCP FUTURO (não inventado aqui):
  • lista de PROPOSTAS por licitante (J2/J4) — o SEI raramente traz a planilha estruturada; PNCP só dá vencedor;
  • CATMAT por item quando não citado no texto; editais análogos (baseline E1/P1) — vêm do corpus, não de 1 SEI;
  • QSA dos cotantes (P2), metadados de PDF — vêm de enrich/exiftool, não do texto do processo.

Uso:
    from compliance_agent.detectores.coletor_edital import analisar_processo_sei_sync
    out = analisar_processo_sei_sync("SEI-510001/000876/2024")
CLI:
    PYTHONPATH=. .venv/bin/python -m compliance_agent.detectores.coletor_edital "SEI-510001/000876/2024"
"""
from __future__ import annotations

import re
from typing import Any, Callable

from compliance_agent.detectores import (
    rodar_edital,
    rodar_julgamento,
    rodar_planejamento,
)
from compliance_agent.sei.fases import classificar

# ───────────────────────────── normalização de números/datas ─────────────────────────────
_MESES = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4, "maio": 5, "junho": 6,
    "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}
_RE_DATA_BR = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_RE_DATA_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_RE_DATA_EXTENSO = re.compile(
    r"\b(\d{1,2})\s+de\s+([a-zçã]+)\s+de\s+(\d{4})\b", re.IGNORECASE
)
_RE_HORA = re.compile(r"\b(\d{1,2})[:h](\d{2})\b")


def _data_iso(texto: str) -> str | None:
    """Normaliza a 1ª data encontrada em `texto` para ISO ``YYYY-MM-DD`` (ou None). Determinístico."""
    if not texto:
        return None
    m = _RE_DATA_BR.search(texto)
    if m:
        d, mo, a = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{a:04d}-{mo:02d}-{d:02d}"
    m = _RE_DATA_ISO.search(texto)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = _RE_DATA_EXTENSO.search(texto)
    if m:
        mes = _MESES.get(m.group(2).lower())
        if mes:
            return f"{int(m.group(3)):04d}-{mes:02d}-{int(m.group(1)):02d}"
    return None


def _datahora_iso(texto: str) -> str | None:
    """Data + hora (se houver) → ``YYYY-MM-DDTHH:MM:SS`` p/ as regras de data-sombra do E2. Sem hora → só data."""
    d = _data_iso(texto)
    if not d:
        return None
    mh = _RE_HORA.search(texto)
    if mh:
        h, mi = int(mh.group(1)), int(mh.group(2))
        if 0 <= h <= 23 and 0 <= mi <= 59:
            return f"{d}T{h:02d}:{mi:02d}:00"
    return d


def _valor_reais(trecho: str) -> float | None:
    """Extrai um valor monetário em reais de `trecho` (``R$ 1.234.567,89`` → 1234567.89). Determinístico."""
    if not trecho:
        return None
    m = re.search(r"R\$\s*([\d.\s]+,\d{2})", trecho)
    if not m:
        m = re.search(r"R\$\s*([\d.\s]+)", trecho)
        if not m:
            return None
        bruto = m.group(1).replace(".", "").replace(" ", "").strip()
        try:
            return float(bruto)
        except ValueError:
            return None
    bruto = m.group(1).replace(".", "").replace(" ", "").replace(",", ".")
    try:
        return float(bruto)
    except ValueError:
        return None


def _pct(trecho: str) -> float | None:
    """Extrai um percentual (``10%`` → 0.10) de `trecho`."""
    m = re.search(r"(\d{1,3}(?:[.,]\d+)?)\s*%", trecho)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ".")) / 100.0
    except ValueError:
        return None


# ───────────────────────────── proveniência ─────────────────────────────
def _texto_unificado(leitura: dict) -> list[dict]:
    """Lista de FONTES de texto da leitura SEI, cada uma {fonte, texto} p/ proveniência. Ordem: texto da árvore
    primeiro, depois o conteúdo de cada documento (com seu rótulo)."""
    fontes: list[dict] = []
    t = (leitura.get("texto") or "").strip()
    if t:
        fontes.append({"fonte": "texto do processo (árvore SEI)", "texto": t})
    for cd in leitura.get("conteudo_documentos") or []:
        doc = str(cd.get("doc") or "documento").strip()
        conteudo = (cd.get("conteudo") or "").strip()
        if conteudo:
            via = cd.get("via")
            rotulo = f"documento '{doc}'" + (f" (via {via})" if via else "")
            fontes.append({"fonte": rotulo, "texto": conteudo})
    return fontes


def _linhas_com_contexto(fontes: list[dict]) -> list[tuple[str, str]]:
    """Achata as fontes em linhas (linha, fonte) p/ varredura por rótulo, preservando a proveniência."""
    out: list[tuple[str, str]] = []
    for f in fontes:
        for ln in f["texto"].splitlines():
            ln = ln.strip()
            if ln:
                out.append((ln, f["fonte"]))
    return out


# marcadores FORTES de que um CONTEÚDO é edital/TR/ETP (seções e identificadores que NF/OB/empenho não têm).
# Necessário porque no SEI real o título do doc costuma ser o NÚMERO do documento (ex.: "121656966"), não o
# nome — então `classificar(titulo)` cai em 'indefinida' e não basta filtrar por título (perda de sensibilidade).
_RX_EDITAL_CONTEUDO = re.compile(
    r"da\s+habilita[çc][ãa]o|qualifica[çc][ãa]o\s+t[ée]cnic|qualifica[çc][ãa]o\s+econ[ôo]mic"
    r"|termo\s+de\s+refer[êe]ncia|estudo\s+t[ée]cnico\s+preliminar|projeto\s+b[áa]sico"
    r"|edital\s+de\s+(?:preg|concorr|licita|tomada|concurso)"
    r"|(?:preg[ãa]o|concorr[êe]ncia|tomada\s+de\s+pre[çc]os)\s+(?:eletr[ôo]nico\s+)?n[ºo\.]"
    r"|condi[çc][õo]es\s+de\s+(?:habilita|participa[çc])|crit[ée]rio\s+de\s+julgamento",
    re.IGNORECASE)


def _fontes_de_edital(leitura: dict) -> list[dict]:
    """Fontes de texto que são EDITAL ou PLANEJAMENTO (TR/ETP/DFD/pesquisa de preços). Um doc entra se o TÍTULO
    classifica como edital/planejamento (via `sei.fases.classificar`) OU se o CONTEÚDO tem marcador forte de
    edital/TR (`_RX_EDITAL_CONTEUDO`) — no SEI real o título é o NÚMERO do doc, então o conteúdo é o sinal
    confiável. Cláusula de habilitação vive AQUI; extrair de NF/OB/despacho gera falso positivo (a coluna 'MARCA'
    de uma NF, 'patrimônio líquido' de um balanço). Sem doc de edital identificável → vazio (E7 nao_avaliavel)."""
    fontes: list[dict] = []
    for cd in leitura.get("conteudo_documentos") or []:
        doc = str(cd.get("doc") or "").strip()
        conteudo = (cd.get("conteudo") or "").strip()
        if not conteudo:
            continue
        fase, tipo = classificar(doc)
        por_titulo = (fase == "selecao" and tipo in ("edital", "proposta")) or fase == "planejamento"
        if por_titulo or _RX_EDITAL_CONTEUDO.search(conteudo):
            marca = f"{fase}/{tipo}" if por_titulo else "conteúdo=edital/TR"
            fontes.append({"fonte": f"documento '{doc}' ({marca})", "texto": conteudo})
    return fontes


def _prov(fonte: str, trecho: str) -> dict:
    """Item de proveniência {doc, trecho} — qual documento/trecho originou o campo (honestidade JFN)."""
    return {"doc": fonte, "trecho": trecho[:160]}


# ───────────────────────────── extratores determinísticos (regex) ─────────────────────────────
_MODALIDADES = [
    ("pregao", re.compile(r"\bpreg[ãa]o\b", re.IGNORECASE)),
    ("concorrencia", re.compile(r"\bconcorr[êe]ncia\b", re.IGNORECASE)),
    ("concurso", re.compile(r"\bconcurso\b", re.IGNORECASE)),
    ("leilao", re.compile(r"\bleil[ãa]o\b", re.IGNORECASE)),
    ("dialogo_competitivo", re.compile(r"\bdi[áa]logo\s+competitivo\b", re.IGNORECASE)),
]
_CRITERIOS = [
    ("menor_preco", re.compile(r"menor\s+pre[çc]o", re.IGNORECASE)),
    ("maior_desconto", re.compile(r"maior\s+desconto", re.IGNORECASE)),
    ("tecnica_e_preco", re.compile(r"t[ée]cnica\s+e\s+pre[çc]o", re.IGNORECASE)),
    ("melhor_tecnica", re.compile(r"melhor\s+t[ée]cnica", re.IGNORECASE)),
    ("maior_retorno_economico", re.compile(r"maior\s+retorno\s+econ[ôo]mico", re.IGNORECASE)),
]


def _extrair_modalidade(fontes: list[dict]) -> tuple[dict | None, dict | None]:
    """Modalidade + critério de julgamento (cada um com proveniência). None se não achar (não inventa)."""
    modalidade = criterio = None
    for f in fontes:
        txt = f["texto"]
        if modalidade is None:
            for nome, rx in _MODALIDADES:
                m = rx.search(txt)
                if m:
                    ini = max(0, m.start() - 40)
                    modalidade = {"valor": nome, "prov": _prov(f["fonte"], txt[ini:m.end() + 40])}
                    break
        if criterio is None:
            for nome, rx in _CRITERIOS:
                m = rx.search(txt)
                if m:
                    ini = max(0, m.start() - 40)
                    criterio = {"valor": nome, "prov": _prov(f["fonte"], txt[ini:m.end() + 20])}
                    break
        if modalidade and criterio:
            break
    return modalidade, criterio


# rótulos de data (publicação / abertura) — varre a linha (e a seguinte) por uma data
_ROTULOS_PUB = re.compile(
    r"(data\s+de\s+publica[çc][ãa]o|publica[çc][ãa]o\s+do\s+edital|publicado\s+em|divulga[çc][ãa]o)",
    re.IGNORECASE,
)
_ROTULOS_ABE = re.compile(
    r"(data\s+(?:de\s+)?abertura|abertura\s+(?:da\s+)?(?:sess[ãa]o|propostas?|licita[çc][ãa]o)|"
    r"sess[ãa]o\s+p[úu]blica|recebimento\s+das?\s+propostas?|entrega\s+das?\s+propostas?)",
    re.IGNORECASE,
)


def _extrair_data_rotulada(linhas: list[tuple[str, str]], rx_rotulo: re.Pattern, com_hora: bool) -> dict | None:
    """Procura uma data na MESMA linha de um rótulo (ou na linha seguinte). Retorna {valor, prov} ou None."""
    for i, (ln, fonte) in enumerate(linhas):
        if not rx_rotulo.search(ln):
            continue
        val = _datahora_iso(ln) if com_hora else _data_iso(ln)
        trecho = ln
        if not val and i + 1 < len(linhas):  # data pode estar na linha seguinte (label \n valor)
            prox = linhas[i + 1][0]
            val = _datahora_iso(prox) if com_hora else _data_iso(prox)
            trecho = f"{ln} | {prox}"
        if val:
            return {"valor": val, "prov": _prov(fonte, trecho)}
    return None


# exigências de habilitação
_RX_ATESTADO = re.compile(
    r"(atestado[s]?\s+de\s+(?:capacidade\s+t[ée]cnica|aptid[ãa]o)|capacidade\s+t[ée]cnica|qualifica[çc][ãa]o\s+t[ée]cnica)",
    re.IGNORECASE,
)
_RX_CAPITAL = re.compile(
    r"(capital\s+social|patrim[ôo]nio\s+l[íi]quido)",
    re.IGNORECASE,
)


def _extrair_exigencias(linhas: list[tuple[str, str]], valor_estimado: float | None) -> list[dict]:
    """Exigências de habilitação (atestado/capital/PL) com parâmetro numérico quando o texto trouxer. Cada
    exigência carrega proveniência. Determinístico — não infere valor que não está escrito."""
    exigencias: list[dict] = []
    for ln, fonte in linhas:
        ma = _RX_ATESTADO.search(ln)
        if ma:
            # quantitativo exigido: % ou número junto da palavra atestado/capacidade
            qpct = _pct(ln)
            exig: dict[str, Any] = {
                "tipo": "atestado",
                "texto": ln[:200],
                "prov": _prov(fonte, ln),
            }
            if qpct is not None:
                exig["quantitativo_exigido_pct"] = qpct  # informativo; razão objetiva usa valor absoluto
            exigencias.append(exig)
            continue
        mc = _RX_CAPITAL.search(ln)
        if mc:
            tipo = "capital_social" if "capital" in mc.group(0).lower() else "patrimonio_liquido"
            valor = _valor_reais(ln)
            pct = _pct(ln)
            if valor is None and pct is not None and valor_estimado:
                valor = round(pct * valor_estimado, 2)  # "X% do valor estimado" → valor absoluto (com base real)
            exig = {"tipo": tipo, "texto": ln[:200], "prov": _prov(fonte, ln)}
            if valor is not None:
                exig["valor"] = valor
            exigencias.append(exig)
    return exigencias


# ── catálogo de cláusulas restritivas (E7) — chaves canônicas espelham restritividade_licitacoes.md §2 e os
#    TIPO-01…10 da base jurisprudencial. (tipo_canonico, categoria, regex_gatilho). CÓDIGO, não prompt: o regex
#    marca a cláusula; o teste finalístico (E7) decide a gravidade. Ordem: específico antes de genérico.
_CATALOGO_CLAUSULAS: list[tuple[str, str, "re.Pattern[str]"]] = [
    ("atestado_identico", "tecnica",
     re.compile(r"atestad[oa].*(?:id[êe]ntic|exatamente o mesmo|vedad[oa].*somat[óo]rio)", re.IGNORECASE)),
    ("atestado_quantitativo", "tecnica",
     # exige contexto de CAPACIDADE/ACERVO/QUALIFICAÇÃO técnica (não "nota fiscal atestada por 2 fiscais")
     re.compile(r"atestad[oa].{0,60}(?:capacidade\s+t[ée]cnic|acervo\s+t[ée]cnic|qualifica[çc][ãa]o\s+t[ée]cnic|aptid[ãa]o)"
                r".{0,80}(?:quantitativo|no\s+m[íi]nimo|percentual|\d+\s*%|parcela)"
                r"|(?:capacidade\s+t[ée]cnic|acervo\s+t[ée]cnic).{0,60}(?:quantitativo|no\s+m[íi]nimo|\d+\s*%)",
                re.IGNORECASE | re.DOTALL)),
    ("visita_tecnica", "tecnica",
     re.compile(r"(?:visita|vistoria)\s+t[ée]cnica.*(?:obrigat[óo]ri|condi[çc][ãa]o (?:de|para).*habilita)"
                r"|(?:obrigat[óo]ri).*(?:visita|vistoria)\s+t[ée]cnica", re.IGNORECASE)),
    ("vinculo_profissional", "tecnica",
     re.compile(r"(?:v[íi]nculo\s+empregat[íi]cio|carteira\s+de\s+trabalho|ctps|quadro\s+permanente)"
                r".*(?:profissional|respons[áa]vel\s+t[ée]cnico)"
                r"|(?:profissional|respons[áa]vel\s+t[ée]cnico).*(?:v[íi]nculo\s+empregat[íi]cio|ctps)", re.IGNORECASE)),
    ("capital_patrimonio", "economica",
     re.compile(r"(?:capital\s+social|patrim[ôo]nio\s+l[íi]quido)\s+(?:m[íi]nimo|integralizado|de|equivalente)", re.IGNORECASE)),
    ("indices_contabeis", "economica",
     # "índice" SÓ quando seguido de um termo CONTÁBIL (liquidez/solvência/endividamento/imobilização/capital
     # circulante) — senão "Índice Acidez/Iodo/Saponificação" de especificação de produto virava falso positivo.
     re.compile(r"\b(?:[íi]ndice(?:\s+de)?\s+(?:liquidez|solv[êe]ncia|endividamento|imobiliza\w+|"
                r"capital\s+circulante|corrente|geral|seca)"
                r"|liquidez(?:\s+(?:geral|corrente|seca))?|grau\s+de\s+endividamento|"
                r"solv[êe]ncia\s+geral)\b.{0,40}?(?:maior|superior|igual|m[íi]nim|≥|>=|\d[.,]\d)", re.IGNORECASE)),
    ("garantia_proposta", "economica",
     re.compile(r"garantia\s+(?:de\s+)?(?:proposta|participa[çc][ãa]o)", re.IGNORECASE)),
    ("recorte_geografico", "geografico",
     # exige SUJEITO (licitante/empresa) + OBRIGAÇÃO + sede/domicílio + recorte territorial na MESMA cláusula —
     # não casa descrição da localização do próprio órgão ("SAMU ... com sede no Município de X").
     re.compile(r"(?:licitante|empresa|proponente|contratad[ao]|interessad)\w*.{0,60}?"
                r"(?:dever[áa]|obrigat[óo]ri|exig|possuir|manter|comprovar|apresentar|estar\s+sediad|ter\s+sede|dispor).{0,60}?"
                r"(?:sede|filial|domic[íi]lio|escrit[óo]rio|representa[çc][ãa]o|base\s+operacional).{0,60}?"
                r"(?:no\s+munic[íi]pio|neste\s+munic[íi]pio|no\s+estado|na\s+regi[ãa]o|local)", re.IGNORECASE | re.DOTALL)),
    ("recorte_temporal", "temporal",
     # prazo de entrega com deadline EXPLÍCITO e curto (não "entrega imediata", que é lícito e comum)
     re.compile(r"prazo\s+de\s+entrega.{0,40}(?:\b(?:24|48|72)\s*(?:h|horas)\b|\b[1-5]\s*dias\b)"
                r"|entrega.{0,15}(?:24|48|72)\s*horas", re.IGNORECASE)),
    ("marca_dirigida", "marca",
     # SÓ direcionamento REAL: imperativo/exclusividade exigindo uma marca ("deverá ser da marca X", "somente
     # marca Y", "exige-se marca Z"), OU marca com vedação de similar. NÃO casa descrição do objeto ("veículo
     # marca FORD"), coluna de NF ("Marca dos Volumes"), equipamento p/ manutenção ("modelo 504 marca BAUSCH"),
     # nem "modelo <nº>" (medida de pneu/série). Precisão > cobertura (indício ≠ acusação).
     re.compile(r"(?:dever[áa]|dever[ãa]o|exclusivamente|somente|apenas|obrigat[óo]ri\w*|exig\w*|exigid[oa])"
                r"\s+(?:ser\s+)?(?:d[aeo]s?\s+)?\b(?:marca|fabricante|modelo)\b\s*[:\-]?\s*[A-Za-z][\w\-]{2,}"
                r"|\b(?:marca|fabricante)\b\s+[A-Za-z][\w\-]{2,}.{0,40}(?:vedad|proibid|n[ãa]o\s+ser[áa]\s+aceit).{0,25}(?:similar|equivalente)",
                re.IGNORECASE)),
    ("amostra_poc", "amostra",
     re.compile(r"(?:amostra|prova\s+de\s+conceito).*(?:todos\s+os\s+licitantes|antes\s+d[ao]\s+(?:habilita|julgamento))", re.IGNORECASE)),
    ("faturamento_minimo", "economica",
     # exige contexto de HABILITAÇÃO ("comprovar faturamento mínimo") — "faturamento mensal dos serviços"
     # (cobrança/medição do contrato) é rotina lícita e NÃO pode casar (indício ≠ acusação).
     re.compile(r"(?:comprov\w+|demonstr\w+|possuir|apresentar).{0,60}(?:faturamento|receita\s+bruta).{0,30}m[íi]nim"
                r"|(?:faturamento|receita\s+bruta)\s+(?:anual\s+|bruto\s+)?m[íi]nim", re.IGNORECASE | re.DOTALL)),
    ("vigencia_contratual", "vigencia",
     # só o PATOLÓGICO sobe (vigência ≥60 meses / ≥5 anos / indeterminada) — vigência de 12-48 meses é o
     # cotidiano lícito e viraria ruído no peer-diff; o teste finalístico decide (60 = teto legal, > = vício).
     re.compile(r"(?:vig[êe]ncia|dura[çc][ãa]o|prazo\s+de\s+vig[êe]ncia).{0,50}"
                r"(?:indeterminad|(?:6[0-9]|[7-9]\d|1[01]\d|120)\s*(?:\([^)]*\)\s*)?meses"
                r"|(?:[5-9]|10)\s*(?:\([^)]*\)\s*)?anos)", re.IGNORECASE | re.DOTALL)),
    ("pontuacao_dirigida", "pontuacao",
     re.compile(r"pontua[çc][ãa]o.*(?:t[ée]cnica|muito\s+satisfat[óo]ri|crit[ée]rio\s+subjetiv)", re.IGNORECASE)),
]
_RX_OU_EQUIVALENTE = re.compile(r"ou\s+(?:similar|equivalente|de\s+melhor\s+qualidade)", re.IGNORECASE)
_RX_DECLARACAO_SUBST = re.compile(r"declara[çc][ãa]o.*(?:conhecimento|disponibilidade|compromisso|pleno)", re.IGNORECASE)
_RX_JUSTIFICATIVA = re.compile(r"(?:justificativ|motiva[çc][ãa]o|em\s+raz[ãa]o\s+d|devido\s+[àa])", re.IGNORECASE)

# VETOS de contexto (falso positivo): a linha casa o gatilho mas o entorno mostra que não é cláusula restritiva.
_EXCLUDENTES: dict[str, "re.Pattern[str]"] = {
    "marca_dirigida": re.compile(
        r"certid|declara[çc]|modelo\s+especial|modelo\s+[úu]nico|modelo\s+de\b|formul[áa]rio|requerimento|"
        r"marca\s+(?:temporal|d['´]?\s?[áa]gua|registrada)|folha\s+\d|anexo", re.IGNORECASE),
    "indices_contabeis": re.compile(
        r"insolv|certid|nada\s+consta|fal[êe]ncia|recupera[çc][ãa]o\s+judicial|"
        # especificação de produto (químico/físico) que casa "índice" mas não é índice contábil de habilitação:
        r"acidez|iodo|saponifica|refra[çc][ãa]o|viscosidade|granulometr|umidade|teor\s|densidade|pureza|"
        r"per[óo]xido|refrat[óo]metr|ph\b|brix", re.IGNORECASE),
}

# VETO GLOBAL (todo tipo): negação ("NÃO será exigida garantia", "fica dispensada a visita") e mera citação
# de lei ("art. 69 da Lei ... poderá ser exigido") casam o gatilho sem INSTITUIR a exigência — não é cláusula.
_EXCLUDENTE_GLOBAL = re.compile(
    r"n[ãa]o\s+ser[áa]\s+exigid|dispensad|art\.\s*\d+.{0,30}lei", re.IGNORECASE)


def _extrair_clausulas_restritivas(linhas: list[tuple[str, str]], valor_estimado: float | None) -> list[dict]:
    """Lista COMPLETA de cláusulas restritivas do edital (E7), cada uma normalizada em `tipo`+`categoria`, com
    proveniência e flags do teste finalístico (`tem_ou_equivalente`, `tem_declaracao_substitutiva`,
    `justificativa_autos`) e parâmetro numérico (`valor`/`pct`) quando o texto trouxer. Determinístico — o regex
    marca a cláusula; a gravidade é decidida no E7. Uma linha casa no máx. UMA cláusula (a 1ª do catálogo)."""
    clausulas: list[dict] = []
    for ln, fonte in linhas:
        if _EXCLUDENTE_GLOBAL.search(ln):
            continue  # negação/mera citação legal — gatilho sem cláusula instituída (guarda anti-FP)
        for tipo, categoria, rx in _CATALOGO_CLAUSULAS:
            if not rx.search(ln):
                continue
            veto = _EXCLUDENTES.get(tipo)
            if veto is not None and veto.search(ln):
                continue  # gatilho num contexto que não é cláusula restritiva (certidão/formulário/insolvência)
            low = ln.lower()
            c: dict[str, Any] = {
                "tipo": tipo,
                "categoria": categoria,
                "texto": ln[:200],
                "prov": _prov(fonte, ln),
                "tem_ou_equivalente": bool(_RX_OU_EQUIVALENTE.search(low)),
                "tem_declaracao_substitutiva": bool(_RX_DECLARACAO_SUBST.search(low)),
                "justificativa_autos": bool(_RX_JUSTIFICATIVA.search(low)),
            }
            valor = _valor_reais(ln)
            pct = _pct(ln)
            if valor is None and pct is not None and valor_estimado:
                valor = round(pct * valor_estimado, 2)  # "X% do valor estimado" → absoluto (base real)
            if valor is not None:
                c["valor"] = valor
            if pct is not None:
                c["pct"] = pct
            clausulas.append(c)
            break  # 1ª cláusula do catálogo vence nesta linha (evita dupla contagem)
    return clausulas


# lotes / itens
_RX_LOTE = re.compile(r"^\s*(?:lote|grupo)\s*[:nº#]*\s*(\d+)", re.IGNORECASE)
_RX_CATMAT = re.compile(r"\b(?:catmat|catser|classe)\s*[:nº#]*\s*(\d{3,})", re.IGNORECASE)
_RX_ITEM = re.compile(r"^\s*(?:item|it)\s*[:nº#]*\s*(\d+)\b", re.IGNORECASE)


def _extrair_lotes(linhas: list[tuple[str, str]]) -> list[dict]:
    """Estrutura de lotes/itens a partir de cabeçalhos 'LOTE N' e linhas de item/CATMAT. Sem lotes explícitos
    → lista vazia (o E3 então fica nao_avaliavel). Determinístico."""
    lotes: list[dict] = []
    lote_atual: dict | None = None
    for ln, fonte in linhas:
        ml = _RX_LOTE.match(ln)
        if ml:
            lote_atual = {"id": f"lote_{ml.group(1)}", "itens": [], "prov": _prov(fonte, ln)}
            lotes.append(lote_atual)
            continue
        if lote_atual is None:
            continue
        mi = _RX_ITEM.match(ln)
        mcat = _RX_CATMAT.search(ln)
        if mi or mcat:
            item: dict[str, Any] = {"descricao": ln[:160]}
            if mcat:
                item["catmat"] = mcat.group(1)
            lote_atual["itens"].append(item)
    return [lt for lt in lotes if lt["itens"]]


def _extrair_valor_estimado(linhas: list[tuple[str, str]]) -> dict | None:
    """Valor estimado/de referência (R$) junto de um rótulo. Retorna {valor, prov} ou None."""
    rx = re.compile(
        r"(valor\s+(?:estimado|de\s+refer[êe]ncia|global|total\s+estimado)|or[çc]amento\s+estimado)",
        re.IGNORECASE,
    )
    for ln, fonte in linhas:
        if rx.search(ln):
            v = _valor_reais(ln)
            if v is not None:
                return {"valor": v, "prov": _prov(fonte, ln)}
    return None


# ───────────────────────────── LLM-opcional (extração estruturada) ─────────────────────────────
_SYS_EXTRACAO = (
    "Você é EXTRATOR de dados de licitação de controle externo (JFN). Recebe um TRECHO de processo do SEI e uma "
    "lista de CAMPOS a extrair. Para CADA campo, extraia o valor SE — e somente se — ele estiver LITERALMENTE no "
    "texto, e cite o trecho de onde tirou. Se o campo NÃO estiver no texto, retorne null para ele. NUNCA invente, "
    "deduza ou estime. Responda SOMENTE com um objeto JSON no formato: "
    '{"<campo>": {"valor": <valor|null>, "trecho": "<citação literal|null>"}, ...}'
)


def _llm_extrair(faltantes: list[str], fontes: list[dict], gerar: Callable[[str, str], str] | None) -> dict:
    """Extração estruturada LLM-OPCIONAL dos campos `faltantes`. Schema JSON fixo, citação obrigatória; campo sem
    trecho é descartado (honesto). Sem motor LLM → {} (degrada). Retorna {campo: {valor, prov}}."""
    if not faltantes:
        return {}
    if gerar is None:
        try:
            from compliance_agent.direcionamento_cerebro import gerar_sync as gerar  # type: ignore
        except Exception:
            return {}  # sem motor → degrada honesto (campos ficam fora do ctx)

    contexto = "\n\n".join(f"[{f['fonte']}]\n{f['texto'][:1500]}" for f in fontes[:4])[:6000]
    prompt = (
        f"CAMPOS A EXTRAIR: {', '.join(faltantes)}\n\n"
        f"TRECHO DO PROCESSO:\n{contexto}\n\n"
        "Extraia cada campo SOMENTE se estiver literal no texto; senão, null. Responda só com o JSON."
    )
    try:
        raw = gerar(prompt, _SYS_EXTRACAO)
    except Exception:
        return {}  # LLM caiu → honesto, nada entra
    from compliance_agent.detectores.base import _parse_json

    dados = _parse_json(raw)
    if not isinstance(dados, dict):
        return {}
    out: dict = {}
    for campo in faltantes:
        item = dados.get(campo)
        if not isinstance(item, dict):
            continue
        valor = item.get("valor")
        trecho = (item.get("trecho") or "").strip()
        if valor in (None, "", "null") or not trecho:
            continue  # citação obrigatória + sem invenção
        out[campo] = {"valor": valor, "prov": _prov("LLM (extração estruturada)", trecho)}
    return out


# ───────────────────────────── montagem do ctx ─────────────────────────────
def montar_ctx_de_sei(leitura: dict, *, usar_llm: bool = False, gerar: Callable[[str, str], str] | None = None) -> dict:
    """Transforma o dict de ``sei_reader.ler`` no ``ctx`` dos detectores (camada 1 — Extração).

    Extrai por REGEX/heurística determinística (datas, modalidade/critério, exigências de habilitação, lotes/itens,
    valor estimado) a partir de ``texto`` + ``conteudo_documentos``. Cada campo carrega PROVENIÊNCIA (doc/trecho)
    em ``ctx['_proveniencia']``. Para campos que o regex não pega, ``usar_llm=True`` aciona a extração estruturada
    LLM-opcional (schema JSON fixo, citação obrigatória); sem LLM, o campo fica FORA do ctx (detector → nao_avaliavel).

    Retorna o ctx (dict) pronto p/ ``rodar_edital`` / ``rodar_planejamento`` / ``rodar_julgamento``."""
    fontes = _texto_unificado(leitura)
    linhas = _linhas_com_contexto(fontes)
    prov: dict[str, Any] = {}

    ctx: dict[str, Any] = {"processo": str(leitura.get("numero") or "?")}

    # valor estimado (usado também na conversão "X% do valor estimado" das exigências)
    ve = _extrair_valor_estimado(linhas)
    valor_estimado = ve["valor"] if ve else None
    if ve:
        ctx["valor_estimado"] = ve["valor"]
        prov["valor_estimado"] = ve["prov"]

    # modalidade + critério (E2)
    modalidade, criterio = _extrair_modalidade(fontes)
    if modalidade:
        ctx["modalidade"] = modalidade["valor"]
        prov["modalidade"] = modalidade["prov"]
    if criterio:
        ctx["criterio"] = criterio["valor"]
        prov["criterio"] = criterio["prov"]

    # datas de publicação / abertura (E2 / P5)
    pub = _extrair_data_rotulada(linhas, _ROTULOS_PUB, com_hora=True)
    abe = _extrair_data_rotulada(linhas, _ROTULOS_ABE, com_hora=True)
    if pub:
        ctx["data_publicacao"] = pub["valor"]
        prov["data_publicacao"] = pub["prov"]
    if abe:
        ctx["data_abertura"] = abe["valor"]
        ctx["data_abertura_processo"] = abe["valor"]  # P5 usa este rótulo
        prov["data_abertura"] = abe["prov"]

    # exigências de habilitação (E1) — SÓ dos docs de edital/planejamento (mesma guarda das cláusulas:
    # "patrimônio líquido" de um balanço não é exigência de habilitação)
    linhas_edital = _linhas_com_contexto(_fontes_de_edital(leitura))
    exig = _extrair_exigencias(linhas_edital, valor_estimado)
    if exig:
        ctx["exigencias_habilitacao"] = exig
        prov["exigencias_habilitacao"] = [e["prov"] for e in exig]

    # cláusulas restritivas — SÓ dos documentos de edital/planejamento (precisão: não varre NF/OB/despacho)
    clausulas = _extrair_clausulas_restritivas(linhas_edital, valor_estimado)
    if clausulas:
        ctx["clausulas_edital"] = clausulas
        prov["clausulas_edital"] = [c["prov"] for c in clausulas]

    # lotes / itens (E3)
    lotes = _extrair_lotes(linhas)
    if lotes:
        ctx["lotes"] = lotes
        prov["lotes"] = [lt["prov"] for lt in lotes]

    # LLM-OPCIONAL: campos essenciais que o regex não pegou
    if usar_llm:
        faltantes = [c for c in ("modalidade", "data_publicacao", "data_abertura", "valor_estimado") if c not in ctx]
        achados = _llm_extrair(faltantes, fontes, gerar)
        for campo, item in achados.items():
            ctx[campo] = item["valor"]
            if campo == "data_abertura":
                ctx["data_abertura_processo"] = item["valor"]
            prov[campo] = item["prov"]

    ctx["_proveniencia"] = prov
    return ctx


def _resumo_ctx(ctx: dict) -> dict:
    """Resumo legível do que foi extraído (sem despejar o texto inteiro)."""
    return {
        "processo": ctx.get("processo"),
        "modalidade": ctx.get("modalidade"),
        "criterio": ctx.get("criterio"),
        "data_publicacao": ctx.get("data_publicacao"),
        "data_abertura": ctx.get("data_abertura"),
        "valor_estimado": ctx.get("valor_estimado"),
        "n_exigencias": len(ctx.get("exigencias_habilitacao") or []),
        "n_clausulas": len(ctx.get("clausulas_edital") or []),
        "n_lotes": len(ctx.get("lotes") or []),
        "tem_propostas": bool(ctx.get("propostas")),
        "tem_decisoes": bool(ctx.get("decisoes")),
        "campos_extraidos": sorted(k for k in ctx if not k.startswith("_") and k != "processo"),
    }


# ───────────────────────────── pipeline em dado real ─────────────────────────────
async def analisar_processo_sei(numero: str, *, usar_llm: bool = False, ler_fn: Callable | None = None) -> dict:
    """Lê o processo do SEI, monta o ctx e roda o pipeline de detectores em DADO REAL.

    `ler_fn` (opcional) substitui ``tools.sei_reader.ler`` — em teste, injete um mock (sem browser/sessão).
    Honesto: leitura com erro OU 0 documentos → ``{status:'INDISPONIVEL', motivo}`` (INDISPONÍVEL ≠ 0).

    Retorna ``{numero, status, ctx_resumo, proveniencia, resultados:[ResultadoDetector.to_dict()],
    confirmados, nao_avaliaveis}``."""
    if ler_fn is None:
        from tools.sei_reader import ler as ler_fn  # type: ignore  # import LAZY (evita Playwright em teste)

    leitura = await ler_fn(numero)

    if not isinstance(leitura, dict) or leitura.get("erro"):
        motivo = (leitura or {}).get("erro") if isinstance(leitura, dict) else "leitura nula"
        return {"numero": numero, "status": "INDISPONIVEL", "motivo": str(motivo or "leitura indisponível")}
    docs = leitura.get("documentos") or []
    conteudo = leitura.get("conteudo_documentos") or []
    texto = (leitura.get("texto") or "").strip()
    if not docs and not conteudo and not texto:
        return {"numero": numero, "status": "INDISPONIVEL",
                "motivo": "processo sem documentos/texto legíveis (cadeado/restrito ou leitura vazia)"}

    ctx = montar_ctx_de_sei(leitura, usar_llm=usar_llm)

    # ata de julgamento → decisões/propostas/resultado (destrava J4/J7 e o cruzamento cláusula↔resultado do E1/E7)
    from compliance_agent.detectores.coletor_ata import montar_ctx_julgamento  # import LAZY (evita ciclo)
    ctx_julg = montar_ctx_julgamento(leitura, usar_llm=usar_llm)
    for k in ("decisoes", "propostas", "resultado"):
        if ctx_julg.get(k):
            ctx[k] = ctx_julg[k]
            ctx.setdefault("_proveniencia", {})[k] = ctx_julg.get("_proveniencia", {}).get(k)
    # resultado da ata → certame_julgamento (alimenta a família certame_ata do índice); persistência
    # é bônus: falha (db travado, sem nº PNCP nos textos) NUNCA derruba a análise do processo
    if ctx_julg.get("resultado"):
        try:
            from compliance_agent.detectores.coletor_ata import certame_de_leitura, persistir_julgamento
            cert = certame_de_leitura(leitura)
            if cert:
                persistir_julgamento(leitura, cert, processo_sei=numero)
        except Exception:  # noqa: BLE001
            pass

    resultados = []
    resultados.extend(rodar_edital(ctx["processo"], contexto=ctx))
    resultados.extend(rodar_planejamento(ctx["processo"], contexto=ctx))
    # julgamento roda com a lista de propostas OU com as decisões da ata (quando a ata está no SEI, o gap PNCP some)
    if ctx.get("propostas") or ctx.get("decisoes"):
        resultados.extend(rodar_julgamento(ctx["processo"], contexto=ctx))

    dicts = [r.to_dict() for r in resultados]
    confirmados = [d for d in dicts if d["status"] == "confirmado"]
    nao_avaliaveis = [d for d in dicts if d["status"] == "nao_avaliavel"]

    return {
        "numero": numero,
        "status": "OK",
        "ctx_resumo": _resumo_ctx(ctx),
        "proveniencia": ctx.get("_proveniencia", {}),
        "resultados": dicts,
        "confirmados": confirmados,
        "nao_avaliaveis": nao_avaliaveis,
    }


def analisar_processo_sei_sync(numero: str, *, usar_llm: bool = False, ler_fn: Callable | None = None) -> dict:
    """Wrapper SÍNCRONO de :func:`analisar_processo_sei` (asyncio.run) p/ CLI/uso fácil."""
    import asyncio

    return asyncio.run(analisar_processo_sei(numero, usar_llm=usar_llm, ler_fn=ler_fn))


def main() -> None:
    import json
    import sys

    numero = sys.argv[1] if len(sys.argv) > 1 else "SEI-510001/000876/2024"
    usar_llm = "--llm" in sys.argv[2:]
    out = analisar_processo_sei_sync(numero, usar_llm=usar_llm)
    if out.get("status") != "OK":
        print(f"[{out.get('status')}] {numero}: {out.get('motivo')}")
        return
    print(f"=== {numero} ===")
    print("ctx_resumo:", json.dumps(out["ctx_resumo"], ensure_ascii=False, indent=2))
    print(f"\nconfirmados: {len(out['confirmados'])} | nao_avaliaveis: {len(out['nao_avaliaveis'])} "
          f"| total: {len(out['resultados'])}")
    for d in out["resultados"]:
        print(f"  · {d['detector']:>3} [{d['status']:<13}] score={d['score']:.2f}  {d['motivo_refutacao'][:80]}")


if __name__ == "__main__":
    main()
