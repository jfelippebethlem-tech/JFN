# -*- coding: utf-8 -*-
"""Camada de INTELIGÊNCIA DETERMINÍSTICA de DIRECIONAMENTO — 100% offline (regex/keyword, SEM LLM).

Por quê: o Gemini está DESLIGADO (billing, §4.1). O produto de direcionamento não pode ficar cego quando a
IA cai. Este módulo reaproveita a MESMA doutrina do `direcionamento_cerebro` (exigências restritivas de
habilitação/qualificação técnica + CASCATA de inabilitações pelo mesmo motivo) e a aplica de forma
puramente determinística, para que o sinal apareça mesmo com a LLM offline.

HONESTO (cláusula JFN): indício a verificar, NUNCA acusação (presunção de legitimidade). Cada achado carrega o
TRECHO literal que o sustenta — sem trecho, não afirma. Sem texto de ata/edital → 'dados insuficientes'
(INDISPONÍVEL ≠ 0), nunca inventa cascata nem grau.

Doutrina (espelha `_SYS` do cérebro): atestado idêntico/desproporcional ao objeto; vedação de somatório de
atestados sem justificativa (Súmula TCU 263); marca/modelo; certificação sem essencialidade; visita técnica
obrigatória; prazo/local/quantitativo restritivo; capital/garantia alto. CASCATA = muitas inabilitações/
desclassificações pelo MESMO motivo (a assinatura do direcionamento).
"""
from __future__ import annotations

import re
import unicodedata


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _norm(s: str) -> str:
    """minúsculo + sem acento — para casar regex de forma robusta sobre OCR/acentuação variável."""
    return _sem_acento((s or "").lower())


# ──────────────────────────────────────────────────────────────────────────────
# 1) CLÁUSULAS RESTRITIVAS DE HABILITAÇÃO/QUALIFICAÇÃO
# ──────────────────────────────────────────────────────────────────────────────
# Cada regra: (tipo, regex sobre texto SEM acento e minúsculo, por_que_restringe, base normativa).
# A regex casa o GATILHO; o `trecho` verbatim é recortado do texto ORIGINAL na janela ao redor do match.
# Conservador: só dispara quando o literal sustenta — preferimos não-detecção a falso-positivo.

_FORTE = {"vedacao_somatorio_atestado", "marca_modelo", "atestado_especifico"}

# Regras de cláusula. A ordem importa só para legibilidade; todas são avaliadas.
_REGRAS: list[tuple[str, re.Pattern, str, str]] = [
    # vedação de somatório de atestados — o clássico (Súmula TCU 263 admite o somatório salvo justificativa técnica)
    ("vedacao_somatorio_atestado",
     re.compile(r"(?:vedad|nao sera admitid|nao se admit|nao sera aceit|nao sera permitid|veda-se|e vedad)"
                r"[^.]{0,80}?(?:somatori|soma de atestad|soma dos atestad|atestados? somad)"),
     "Veda o somatório de atestados sem demonstrar justificativa técnica para a exigência de um único atestado, "
     "restringindo a competição.",
     "Súmula TCU 263 (somatório de atestados é admitido salvo justificativa técnica) / art. 37, XXI CF"),
    # também na ordem inversa ("somatório ... não será admitido")
    ("vedacao_somatorio_atestado",
     re.compile(r"(?:somatori|soma de atestad|soma dos atestad)[^.]{0,80}?"
                r"(?:vedad|nao sera admitid|nao se admit|nao sera aceit|nao sera permitid)"),
     "Veda o somatório de atestados sem demonstrar justificativa técnica para a exigência de um único atestado, "
     "restringindo a competição.",
     "Súmula TCU 263 (somatório de atestados é admitido salvo justificativa técnica) / art. 37, XXI CF"),
    # atestado idêntico/similar ao objeto, ou com quantitativo mínimo desproporcional
    ("atestado_especifico",
     re.compile(r"atestad[^.]{0,120}?(?:identic[oa]|igual ao objeto|mesm[oa] objeto|"
                r"caracteristicas? identic|no minimo|quantitativ)"),
     "Atestado de capacidade técnica vinculado a objeto idêntico/quantitativo mínimo pode ser desproporcional "
     "ao objeto e direcionar a fornecedor específico.",
     "Súmula TCU 263 / art. 67 §§ da Lei 14.133/2021 (exigência pertinente e proporcional)"),
    # marca/modelo EXIGIDO/RESTRITIVO (não a mera menção a uma marca em lista de produto). Pede um verbo
    # de exigência/exclusividade perto de "marca/modelo" e SEM "ou equivalente/similar" — evita falso-positivo
    # em "marca COPERTINA" de um item de aquisição.
    ("marca_modelo",
     re.compile(r"(?:exclusivamente|somente|apenas|unica(?:mente)?|obrigatori|exig\w+|devera ser|sera exigid|"
                r"vedad\w*\s+(?:marca|modelo)\s+divers)"
                r"[^.]{0,40}?\b(?:marca|modelo)\b"
                r"(?![^.]{0,40}(?:equivalent|similar|ou superior|de referencia|referencia))"
                r"|\b(?:marca|modelo)\b[^.]{0,40}?(?:exclusiv|sem admitir (?:outr|equivalent|similar)|"
                r"vedad\w*\s+(?:outr|equivalent|similar)|nao sera aceit\w*\s+(?:outr|equivalent|similar))"),
     "Exigência de marca/modelo específico sem admitir equivalente/similar restringe a competição a um produto.",
     "art. 41 da Lei 14.133/2021 (vedação à preferência de marca, salvo justificativa) / art. 37 CF impessoalidade"),
    # certificação/certificado exigido
    ("certificacao",
     re.compile(r"\bcertifica(?:c|ç)(?:ao|oes)\b|\bcertificad[oa]s?\b"),
     "Exigência de certificação específica pode restringir a competição se não comprovada a essencialidade "
     "técnica para a execução do objeto.",
     "art. 37, XXI CF (só exigências indispensáveis) / jurisprudência TCU sobre certificações"),
    # visita técnica / vistoria OBRIGATÓRIA
    ("visita_obrigatoria",
     re.compile(r"(?:visita tecnica|vistoria)[^.]{0,60}?(?:obrigatori|sera obrigatori|"
                r"de carater obrigatori|deverao? realizar)"),
     "Visita técnica/vistoria obrigatória (em vez de facultativa com declaração) tende a restringir a "
     "competição e elevar custo de licitantes não locais.",
     "Súmula TCU 272 (visita deve ser facultativa, substituível por declaração) / art. 37 CF impessoalidade"),
    # prazo/local/quantitativo restritivo — sede/registro local, prazo de N anos
    ("prazo_local_quantitativo",
     re.compile(r"(?:sede|domicili|registr[oa]|inscri(?:c|ç)ao|filial|escritori)[^.]{0,40}?"
                r"(?:no (?:municipio|estado|rio de janeiro)|local|na (?:cidade|regiao))"),
     "Exigência de sede/domicílio/registro local restringe a competição por localização, sem pertinência "
     "técnica com o objeto.",
     "art. 37, XXI CF impessoalidade / jurisprudência TCU (vedação a exigência de sede prévia)"),
    ("prazo_local_quantitativo",
     re.compile(r"prazo de\s+\d+\s+anos|experiencia (?:minima )?de\s+\d+\s+anos"),
     "Exigência de prazo/tempo mínimo de experiência pode ser desproporcional e restringir a competição.",
     "Súmula TCU 263 / art. 67 da Lei 14.133/2021 (proporcionalidade)"),
    # capital social / garantia elevados
    ("capital_garantia_alto",
     re.compile(r"(?:capital social|patrimonio liquido|garantia)[^.]{0,60}?"
                r"(?:no minimo|minim[oa]|igual ou superior|nao inferior)"),
     "Exigência de capital social/patrimônio/garantia mínimos elevados pode restringir a participação de "
     "empresas economicamente capazes mas de menor porte.",
     "art. 69 da Lei 14.133/2021 (até 10% do valor estimado; vedado o excesso) / art. 37 CF"),
    # exclusividade ATADA a fornecedor/marca/produto (restritividade real) — NÃO o advérbio "exclusivamente"
    # solto (que aparece em prosa administrativa: "em relação exclusivamente a", "faltas justificadas
    # exclusivamente"). Calibrado em dado real (falso-positivo em despacho/processo disciplinar do CBMERJ).
    ("marca_modelo",
     re.compile(r"\b(?:exclusivamente|com exclusividade|de forma exclusiva|exclusiv[oa])\b[^.]{0,50}?"
                r"\b(?:marca|modelo|fabricante|fornecedor|distribuidor|representante|revend\w+|"
                r"produto|origem|proced[êe]nc\w+)\b"
                r"|\b(?:fornecimento|distribui\w+|representa\w+|comercializa\w+|venda)\s+exclusiv"),
     "Exigência de fornecimento/marca/fornecedor exclusivo limita a competição a um único agente, sem "
     "previsão de 'ou equivalente/similar'.",
     "Súmula TCU 270 (marca só com 'ou similar') / art. 37, XXI CF impessoalidade"),
]

# Marcadores de que o texto realmente é edital/habilitação (evita disparar em ementa/contrato/menu do SEI).
_MARC_EDITAL = ("atestado", "habilitac", "habilitaç", "qualificac", "qualificaç", "capacidade tecnica",
                "capacidade técnica", "edital", "pregao", "pregão", "licitac", "licitaç", "termo de referencia",
                "termo de referência", "proposta")
_MARC_EDITAL_N = tuple(_sem_acento(k) for k in _MARC_EDITAL)  # versão normalizada (preenchida abaixo)

# Tipos GENÉRICOS (marcadores ambíguos: "Modelo", "certificação de regularidade", "exclusivamente",
# "garantia") que só são CLÁUSULA quando aparecem em CONTEXTO de habilitação/edital — caso contrário
# disparam em prosa de resumo/contrato (falso-positivo). Os FORTES dispensam contexto (são específicos).
_TIPOS_GENERICOS = {"marca_modelo", "certificacao", "prazo_local_quantitativo", "capital_garantia_alto"}
_JANELA_CTX = 400  # chars ao redor do match onde procuramos um marcador de edital


def _tem_contexto_edital(low: str, ini: int, fim: int) -> bool:
    a, b = max(0, ini - _JANELA_CTX), min(len(low), fim + _JANELA_CTX)
    jan = low[a:b]
    return any(k in jan for k in _MARC_EDITAL_N)


def _trecho_em(original: str, low: str, ini: int, fim: int, janela: int = 90, limite: int = 200) -> str:
    """Recorta o trecho VERBATIM do texto ORIGINAL ao redor do match (índices são da string normalizada,
    que tem o MESMO comprimento da original — _norm não muda tamanho). Limita a `limite` chars."""
    a = max(0, ini - janela)
    b = min(len(original), fim + janela)
    seg = original[a:b].strip()
    seg = re.sub(r"\s+", " ", seg)
    return seg[:limite]


def extrair_clausulas_restritivas(texto: str) -> list[dict]:
    """Varre o texto de edital/dossiê e retorna cada cláusula restritiva de habilitação encontrada.

    Retorna lista de dicts: {tipo, trecho (verbatim ≤200 chars), por_que_restringe, base}.
    HONESTO: só inclui uma cláusula quando o literal `trecho` a sustenta; deduplica trechos repetidos.
    """
    if not texto or not texto.strip():
        return []
    low = _norm(texto)
    achados: list[dict] = []
    vistos: set[tuple[str, str]] = set()
    for tipo, rx, porque, base in _REGRAS:
        for m in rx.finditer(low):
            # tipos GENÉRICOS só valem com CONTEXTO de edital/habilitação ao redor (anti-falso-positivo
            # em prosa de resumo/contrato: "Modelo de Recibo", "certificação de regularidade", etc.).
            if tipo in _TIPOS_GENERICOS and not _tem_contexto_edital(low, m.start(), m.end()):
                continue
            trecho = _trecho_em(texto, low, m.start(), m.end())
            if not trecho:
                continue
            chave = (tipo, trecho[:60].lower())
            if chave in vistos:
                continue
            vistos.add(chave)
            achados.append({
                "tipo": tipo,
                "trecho": trecho,
                "por_que_restringe": porque,
                "base": base,
            })
    return achados


# ──────────────────────────────────────────────────────────────────────────────
# 2) INABILITAÇÕES / DESCLASSIFICAÇÕES (a CASCATA)
# ──────────────────────────────────────────────────────────────────────────────
# Janela ao redor de cada inabilitação/desclassificação para capturar o MOTIVO verbatim.
_RX_INAB = re.compile(
    r"(inabilitad|desabilitad|desclassificad|nao habilitad|nao foi habilitad)\w*",
)
# Marcadores de motivo logo após o evento (para isolar o trecho do "porquê").
_RX_MOTIVO = re.compile(
    r"(?:por|por que|porque|em razao de|em virtude de|por nao|deixou de|nao apresentou|"
    r"nao atendeu|nao comprovou|nao cumpriu|ausencia de|falta de|motivo)",
)
_RX_HABIL = re.compile(r"\bhabilitad[oa]\b|declarad[oa] vencedor|empresa vencedora")


def _motivo_apos(low: str, original: str, pos: int, janela: int = 240) -> str:
    """Extrai o motivo verbatim numa janela após a posição da inabilitação."""
    fim = min(len(original), pos + janela)
    seg_low = low[pos:fim]
    mm = _RX_MOTIVO.search(seg_low)
    ini_rel = mm.start() if mm else 0
    seg = original[pos + ini_rel:fim].strip()
    seg = re.sub(r"\s+", " ", seg)
    # corta na primeira sentença (ponto final) para um motivo limpo, mas mantém ≥ trecho mínimo
    corte = seg.find(". ")
    if corte > 30:
        seg = seg[:corte + 1]
    return seg[:200]


def _assinatura_motivo(motivo: str) -> str:
    """Normaliza o motivo para detectar repetição (mesma causa) ignorando nome/numeração/pontuação."""
    s = _norm(motivo)
    s = re.sub(r"\d+", "", s)
    s = re.sub(r"[^a-z ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # palavras-núcleo (remove conectivos curtos) para casar paráfrases leves
    toks = [w for w in s.split() if len(w) > 3]
    return " ".join(toks[:12])


def extrair_inabilitacoes(texto: str) -> dict:
    """Parseia a ata/julgamento e devolve a cascata de inabilitações/desclassificações.

    Retorna: {n_desclassificadas, n_inabilitadas, licitantes:[{situacao, motivo (verbatim)}],
    cascata_mesmo_motivo: {repetido: bool, quais: [...], n: int}, vencedor: {...}|None}.
    HONESTO: motivo só quando o trecho o sustenta; cascata só quando ≥2 motivos com mesma assinatura.
    """
    base = {"n_desclassificadas": 0, "n_inabilitadas": 0, "licitantes": [],
            "cascata_mesmo_motivo": {"repetido": False, "quais": [], "n": 0}, "vencedor": None}
    if not texto or not texto.strip():
        return base
    low = _norm(texto)
    licitantes: list[dict] = []
    for m in _RX_INAB.finditer(low):
        verbo = m.group(1)
        situacao = "desclassificada" if "desclass" in verbo else "inabilitada"
        motivo = _motivo_apos(low, texto, m.start())
        licitantes.append({"situacao": situacao, "motivo": motivo})
        if situacao == "desclassificada":
            base["n_desclassificadas"] += 1
        else:
            base["n_inabilitadas"] += 1
    base["licitantes"] = licitantes

    # cascata: ≥2 motivos com a MESMA assinatura (a assinatura do direcionamento)
    from collections import Counter
    assinaturas = [(_assinatura_motivo(l["motivo"]), l) for l in licitantes if l["motivo"]]
    cont = Counter(a for a, _ in assinaturas if a)
    repetidos = {a: n for a, n in cont.items() if n >= 2}
    if repetidos:
        quais = []
        for a, n in sorted(repetidos.items(), key=lambda kv: -kv[1]):
            # pega um trecho representativo daquele motivo
            ex = next(l["motivo"] for assi, l in assinaturas if assi == a)
            quais.append({"motivo_trecho": ex, "vezes": n})
        base["cascata_mesmo_motivo"] = {"repetido": True, "quais": quais,
                                        "n": sum(repetidos.values())}

    # vencedor (best-effort, sem nome confiável no texto puro): só sinaliza presença
    mv = _RX_HABIL.search(low)
    if mv:
        trecho = _trecho_em(texto, low, mv.start(), mv.end(), janela=80, limite=200)
        base["vencedor"] = {"nome": None, "trecho": trecho, "subiu_apos_quedas": None}
    return base


# ──────────────────────────────────────────────────────────────────────────────
# 3) VEREDITO DETERMINÍSTICO
# ──────────────────────────────────────────────────────────────────────────────
def _parece_ata(low: str) -> bool:
    return bool(_RX_INAB.search(low)) and len(low) > 800 or low.count("inabilitad") + low.count("desclassificad") >= 2


def _parece_edital(low: str) -> bool:
    return len(low) > 1500 and sum(low.count(_norm(k)) for k in _MARC_EDITAL) >= 3


def analisar_direcionamento_det(texto: str) -> dict:
    """Combina (1) cláusulas restritivas + (2) cascata de inabilitações num veredito DETERMINÍSTICO.

    Regra de grau (código, conservador):
      • vermelho = ≥1 restritiva FORTE (vedação de somatório / marca-modelo / atestado idêntico)
                   E cascata mesmo-motivo.
      • amarelo  = restritivas OU cascata isoladas.
      • verde    = é edital/ata, mas sem restritiva forte nem cascata.
      • indeterminado = NÃO há texto de ata nem edital → 'dados insuficientes' (nunca inventa).

    HONESTO: indício a verificar, não acusação. Sem ata → não afirma cascata.
    """
    t = texto or ""
    low = _norm(t)
    clausulas = extrair_clausulas_restritivas(t)
    inab = extrair_inabilitacoes(t)
    tem_ata = _parece_ata(low)
    tem_edital = _parece_edital(low)
    cascata = bool(inab["cascata_mesmo_motivo"]["repetido"])
    n_restr_forte = sum(1 for c in clausulas if c["tipo"] in _FORTE)

    sinais: list[str] = []
    for c in clausulas:
        sinais.append(f"cláusula restritiva ({c['tipo']}): «{c['trecho'][:120]}»")
    if cascata:
        for q in inab["cascata_mesmo_motivo"]["quais"]:
            sinais.append(f"cascata: {q['vezes']}× mesmo motivo — «{q['motivo_trecho'][:120]}»")

    if not tem_ata and not tem_edital:
        return {
            "grau_det": "indeterminado",
            "dados_suficientes": False,
            "n_clausulas_restritivas": len(clausulas),
            "n_inabilitacoes": inab["n_inabilitadas"] + inab["n_desclassificadas"],
            "cascata": cascata,
            "clausulas": clausulas,
            "inabilitacoes": inab,
            "sinais": sinais,
            "resumo": ("Dados insuficientes: o texto não traz edital de licitação nem ata de julgamento com "
                       "cascata de inabilitações — análise determinística não aplicável (necessário coletar "
                       "edital/ata)."),
            "ressalva": "INDISPONÍVEL ≠ 0; coletar edital/ata para análise determinística",
            "fonte": "direcionamento_sinais (determinístico/offline)",
        }

    if n_restr_forte >= 1 and cascata:
        grau = "vermelho"
        resumo = (f"INDÍCIO FORTE a verificar: {n_restr_forte} cláusula(s) restritiva(s) forte(s) de habilitação "
                  f"E cascata de {inab['cascata_mesmo_motivo']['n']} inabilitações/desclassificações pelo MESMO "
                  f"motivo — assinatura clássica de direcionamento.")
    elif clausulas or cascata:
        grau = "amarelo"
        partes = []
        if clausulas:
            partes.append(f"{len(clausulas)} cláusula(s) restritiva(s) de habilitação")
        if cascata:
            partes.append(f"cascata de {inab['cascata_mesmo_motivo']['n']} inabilitações pelo mesmo motivo")
        resumo = "Indício a verificar: " + " e ".join(partes) + " (isoladamente)."
    else:
        grau = "verde"
        resumo = ("Sem cláusula restritiva nem cascata identificadas no texto disponível (não exclui "
                  "direcionamento por outras vias; análise restrita ao que o texto sustenta).")

    return {
        "grau_det": grau,
        "dados_suficientes": True,
        "n_clausulas_restritivas": len(clausulas),
        "n_inabilitacoes": inab["n_inabilitadas"] + inab["n_desclassificadas"],
        "cascata": cascata,
        "clausulas": clausulas,
        "inabilitacoes": inab,
        "sinais": sinais,
        "resumo": resumo,
        "ressalva": "presunção de legitimidade; indício a apurar, não acusação",
        "fonte": "direcionamento_sinais (determinístico/offline)",
    }


# Carona / adesão a Ata de Registro de Preços e referências de certame — vetor SUTIL de restritividade
# (adesão sem vantajosidade comprovada; ARP de outro órgão; item trocado por "mesma marca" pós-registro).
# A maior parte do gasto do FUNESBOM passa por adesão a ARP/PE: o despacho/publicação cita o PE/ARP-lastro,
# não o edital. Mapear o certame permite PRIORIZAR qual edital/ata coletar para a perícia de direcionamento.
_RE_ARP = re.compile(r"Ata de Registro de Pre[çc]os\s*n[°ºo]*\s*([\d./-]+)", re.I)
_RE_PE = re.compile(r"\b(?:PE|Preg[ãa]o Eletr[ôo]nico)\s*n?[°ºo]*\s*([\d./-]+)", re.I)
_RE_ADESAO = re.compile(r"ades[ãa]o", re.I)


def extrair_certames(texto: str) -> dict:
    """Extrai as referências de certame subjacente — Pregão (PE) e Ata de Registro de Preços (ARP) — e sinaliza
    ADESÃO/CARONA no texto (edital/despacho/publicação). Mapeia 'qual certame lastreia este pagamento', para
    priorizar a coleta do edital/ata na perícia de direcionamento. Determinístico, offline.
    Retorna {pregoes:[nº], atas_rp:[nº], adesao:bool, n_refs}. Honesto: lista vazia ≠ ausência de certame."""
    t = texto or ""
    pregoes = sorted({m.strip(" ./-") for m in _RE_PE.findall(t)})
    atas = sorted({m.strip(" ./-") for m in _RE_ARP.findall(t)})
    return {"pregoes": pregoes, "atas_rp": atas, "adesao": bool(_RE_ADESAO.search(t)),
            "n_refs": len(pregoes) + len(atas)}
