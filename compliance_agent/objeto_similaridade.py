# -*- coding: utf-8 -*-
"""MESMO OBJETO? — agrupamento de contratações para o fracionamento de despesa (art. 75 §1º, Lei 14.133).

Refino pedido pelo dono (2026-07-24). O agrupamento é o coração do P4: somar o que NÃO é o mesmo objeto
inventa fracionamento; deixar de somar o que É o mesmo objeto deixa o fracionamento passar. O critério
anterior (similaridade de SEQUÊNCIA, difflib) errava dos dois lados:

  • falso NEGATIVO — "aquisição de material de limpeza" × "compra de produtos de limpeza": mesmo objeto,
    palavras diferentes, sequências distintas → não agrupava;
  • falso POSITIVO — "material de limpeza" × "material de escritório": sequências quase idênticas,
    objetos distintos → quase agrupava.

A causa é a mesma nos dois casos: difflib pesa TODAS as palavras igual. Num lote de compras públicas,
"aquisição", "material" e "contratação" aparecem em quase tudo e não discriminam nada — enquanto
"limpeza", "pneu", "merenda" discriminam. Este módulo pesa cada termo pelo que ele DISCRIMINA no lote
(TF-IDF + cosseno), com stemming leve para plural/flexão ("copos descartáveis" = "copo descartável").

Hierarquia de decisão (a mais confiável primeiro):
  1. **CHAVE DURA** — CATMAT/CATSER ou NATUREZA DE DESPESA do SIAFE (33903007 = gêneros de alimentação):
     classificação OFICIAL do objeto. Igualdade agrupa, divergência SEPARA (não cai para o texto).
  2. **TF-IDF/cosseno ≥ LIMIAR** sobre os termos discriminantes, quando não há chave dura.
  3. **GENÉRICO** ("material diverso", "serviços gerais") — não descreve objeto: fica isolado. Não se
     soma o que não se sabe o que é (INDISPONÍVEL ≠ mesmo objeto).

Cada agrupamento é EXPLICÁVEL (`explicar`): critério, score e termos em comum — o auditor vê por que
somou. Determinístico, sem dependência pesada (a VM tem 2 vCPU).
"""
from __future__ import annotations

import math
import re
import unicodedata

LIMIAR = 0.35      # cosseno TF-IDF a partir do qual dois objetos são "o mesmo" (calibrado
                   # em dado real: mesmo objeto fica bem acima; objeto distinto cai para ~0)
_MIN_TOKEN = 3

# Ruído do vocabulário licitatório: aparece em quase toda contratação e não discrimina objeto.
_STOP = {
    "de", "da", "do", "das", "dos", "e", "para", "com", "em", "a", "o", "as", "os", "no", "na", "ao",
    "aos", "por", "ou", "um", "uma", "pelo", "pela", "sob", "sobre", "entre", "ate", "the",
    "aquisicao", "compra", "contratacao", "prestacao", "fornecimento", "servico", "servicos",
    "material", "materiais", "produto", "produtos", "item", "itens", "objeto", "empresa", "pessoa",
    "juridica", "eventual", "futura", "destinado", "destinada", "atender", "atendimento", "demanda",
    "necessidade", "necessidades", "uso", "utilizacao", "diversos", "diversas", "geral", "gerais",
    "referente", "conforme", "termo", "referencia", "processo", "unidade", "secretaria", "orgao",
    # LOCAL DE DESTINO ≠ objeto: entram na descrição e roubavam peso do termo que identifica
    "almoxarifado", "estoque", "deposito", "sede", "setor", "gerencia", "diretoria",
    # FÓRMULA do termo de referência: "estabelecer as condições para contratação de empresa
    # especializada em X" — tudo isso é moldura; só o X identifica o objeto. Medido no dado real: sem
    # remover, duas contratações de ramos distintos agrupavam pela moldura que compartilham.
    "estabelecer", "condicao", "condicoes", "especializada", "especializado", "especializadas",
    "especializados", "presente", "visa", "visando", "objetivo", "finalidade", "vista", "forma",
    # VOCABULÁRIO ADMINISTRATIVO-FINANCEIRO: descreve o TRÂMITE, não o que foi comprado. Sem isto,
    # "geramos o processo administrativo para o empenho e pagamento das despesas relativas ao exercício"
    # (fórmula real, repetida em dezenas de registros do TCE-RJ) agrupava consigo mesma como se fosse um
    # objeto — e o somatório do art. 75 §1º passava a incidir sobre despesas sem nenhuma natureza comum.
    "geramos", "gerado", "abertura", "empenho", "empenhos", "pagamento", "pagamentos", "despesa",
    "despesas", "exercicio", "administrativo", "administrativa", "relativa", "relativas", "relativo",
    "relativos", "referentes", "autorizacao", "solicitacao", "solicito", "informamos", "encaminhamos",
    "trata", "tratam", "fins", "reais", "valor", "valores", "total",
}
# Descrições que NÃO descrevem objeto — não podem formar cluster (só ruído restaria após as stopwords).
_RE_GENERICO = re.compile(
    r"^\s*(materia(?:l|is)\s+(?:divers[oa]s?|de\s+consumo|em\s+geral)|servi[çc]os?\s+(?:gerais|divers[oa]s)|"
    r"despesas?\s+(?:divers[oa]s|mi[úu]das)|outros?\s+servi[çc]os|itens?\s+divers[oa]s)\s*\.?\s*$", re.I)
# chaves OFICIAIS de classificação do objeto (a ordem define a precedência)
_CHAVES_DURAS = ("catmat", "catser", "natureza_despesa", "elemento_despesa", "subelemento",
                 "grupo_objeto", "grupo")

# PREÂMBULO burocrático: abre a descrição sem dizer NADA sobre o objeto. Medido no dado real do TCE-RJ —
# dezenas de contratações começam com a mesma fórmula e agrupavam por ela, não pelo que foi comprado.
_RE_PREAMBULO = re.compile(
    r"^.{0,200}?(?:tem\s+por\s+(?:objeto|objetivo|finalidade)|o\s+objetivo\s+deste\s+termo[^.]{0,80}?[ée]|"
    r"constitui\s+objeto\s+(?:deste|desta)[^,]{0,60},?|geramos\s+o\s+processo\s+administrativo[^.]{0,80}?|"
    r"abertura\s+de\s+processo\s+administrativo[^.]{0,80}?|trata-?se\s+(?:de|do|da))\s*", re.I)

# ───────────────────────────── RAMO DE ATIVIDADE (art. 75, §1º, II) ─────────────────────────────
# A lei NÃO manda somar "objeto idêntico": manda somar "objetos de MESMA NATUREZA, entendidos como tais
# aqueles relativos a contratações no MESMO RAMO DE ATIVIDADE". Somar só o idêntico SUBESTIMA o
# fracionamento — que é justamente a manobra de picar a mesma necessidade em descrições diferentes.
# Cada ramo é um conjunto de termos-âncora; a classificação é conservadora (sem âncora → None → cai para
# a similaridade de objeto, e o achado nasce mais fraco).
RAMOS: tuple[tuple[str, str], ...] = (
    # utilidade pública prestada por CONCESSIONÁRIA (água/energia/telefonia). Aferido no dado real do
    # TCE-RJ: a descrição costuma vir como "fornecimento de água por intermédio da concessionária X" —
    # sem estes termos o ramo saía None e contratos idênticos ficavam sem natureza comum.
    ("utilidade_publica", r"energia\s+el[ée]trica|[áa]gua\s+e\s+esgoto|abastecimento\s+de\s+[áa]gua|"
                          r"fornecimento\s+de\s+[áa]gua|[áa]gua\s+pot[áa]vel|concession[áa]ria|"
                          r"telefonia|internet|saneamento|tratamento\s+de\s+esgoto"),
    ("combustivel", r"combust[íi]vel|gasolina|diesel|etanol|arla|[óo]leo\s+lubrificante"),
    ("veiculos", r"pneu|ve[íi]culo|autom[óo]vel|frota|manuten[çc][ãa]o\s+veicular|revis[ãa]o\s+de\s+ve[íi]culo|"
                 r"loca[çc][ãa]o\s+de\s+ve[íi]culo"),
    ("saude_medicamentos", r"medicamento|f[áa]rmaco|hospitalar|seringa|luva\s+de\s+procedimento|"
                           r"insumo\s+m[ée]dico|material\s+m[ée]dico|odontol[óo]gic|laborat[óo]ri"),
    ("alimentacao", r"aliment[íi]cio|alimento|merenda|refei[çc][ãa]o|g[êe]nero\s+aliment|cesta\s+b[áa]sica|"
                    r"[áa]gua\s+mineral|caf[ée]|marmita|coffee\s*break"),
    ("limpeza_higiene", r"limpeza|higiene|higieniza|desinfetante|[áa]gua\s+sanit[áa]ria|saneante|sab[ãa]o|"
                        r"sabonete|papel\s+higi[êe]nico|detergente|copa\s+e\s+cozinha|descart[áa]vel"),
    ("informatica", r"inform[áa]tica|computador|notebook|impressora|software|licen[çc]a\s+de\s+uso|"
                    r"servidor\s+de\s+rede|toner|cartucho|no-?break|switch|link\s+de\s+dados"),
    ("expediente", r"expediente|escrit[óo]rio|papel\s+a4|caneta|grampeador|pasta\s+suspensa|"
                   r"material\s+de\s+consumo\s+administrativo"),
    ("mobiliario", r"mobili[áa]rio|cadeira|mesa\s+de\s+escrit|arm[áa]rio|estante|long[ao]rina"),
    ("uniforme_epi", r"uniforme|EPI\b|equipamento\s+de\s+prote[çc][ãa]o|bota\s+de\s+seguran|capacete|"
                     r"fardamento"),
    ("vigilancia", r"vigil[âa]ncia|seguran[çc]a\s+patrimonial|monitoramento\s+eletr[ôo]nico|"
                   r"portaria\s+e\s+vigil"),
    ("manutencao_predial", r"manuten[çc][ãa]o\s+predial|reforma|obra|hidr[áa]ulic|instala[çc][ãa]o\s+el[ée]tric|"
                           r"rede\s+el[ée]tric|servi[çc]os?\s+el[ée]tric|pintura|"
                           r"alvenaria|ar[- ]condicionado|climatiza[çc][ãa]o|telhado|impermeabiliza"),
    ("grafica", r"gr[áa]fic|impress[ãa]o\s+de|encaderna[çc][ãa]o|banner|crach[áa]|panfleto|folder"),
    ("eventos", r"evento|loca[çc][ãa]o\s+de\s+espa[çc]o|som\s+e\s+ilumina|palco|buffet"),
    ("transporte", r"passagem\s+a[ée]rea|frete|mudan[çc]a|transporte\s+de\s+(?:carga|passageiro)"),
)


def ramo_atividade(objeto: str) -> str | None:
    """RAMO DE ATIVIDADE do objeto (art. 75, §1º, II — "objetos de mesma natureza"). None quando o texto
    não permite classificar: aí não se soma por natureza (conservador — INDISPONÍVEL ≠ mesmo ramo)."""
    t = _sem_acento((objeto or "").lower())
    alvo = _RE_PREAMBULO.sub("", t, count=1) or t
    for nome, pat in RAMOS:
        if re.search(_sem_acento(pat), alvo, re.I):
            return nome
    return None


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _stem(t: str) -> str:
    """Stemming leve para português: reduz plural e flexões comuns. Barato e suficiente para casar
    'copos descartaveis' com 'copo descartavel' sem trazer dependência de NLP para a VM."""
    for suf in ("coes", "aveis", "iveis", "oes", "aes", "eis"):
        if t.endswith(suf) and len(t) > len(suf) + 2:
            return t[: -len(suf)] + {"coes": "cao", "aveis": "avel", "iveis": "ivel",
                                     "oes": "ao", "aes": "ao", "eis": "el"}[suf]
    for suf in ("es", "s"):
        if t.endswith(suf) and len(t) > len(suf) + 2:
            return t[: -len(suf)]
    return t


def tokens(objeto: str) -> list[str]:
    """Termos DISCRIMINANTES do objeto: sem acento, sem pontuação, sem preâmbulo burocrático, sem
    vocabulário licitatório, stemizados."""
    t = _sem_acento((objeto or "").lower())
    t = _RE_PREAMBULO.sub("", t, count=1) or t
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    out = []
    for w in t.split():
        if len(w) < _MIN_TOKEN or w in _STOP or w.isdigit():
            continue          # token só-dígitos (ano, nº de processo) não identifica objeto
        # sujeira REAL do dado: artigo/conjunção colada na palavra seguinte ("para OEMPENHO", "água
        # EENERGIA"). Só se descarta quando o resto é EXATAMENTE uma palavra neutra — nunca se corta a
        # primeira letra por conta própria ("elevador" não pode virar "levador").
        if len(w) > 3 and w[0] in "oae" and w[1:] in _STOP:
            continue
        s = _stem(w)
        if len(s) >= _MIN_TOKEN and s not in _STOP:
            out.append(s)
    return out


def generico(objeto: str) -> bool:
    """A descrição não identifica o objeto? ('material diverso', 'serviços gerais', ou só ruído)."""
    if _RE_GENERICO.match((objeto or "").strip()):
        return True
    return not tokens(objeto)


def chave_dura(c: dict) -> str | None:
    """Classificação OFICIAL do objeto (CATMAT/CATSER/natureza de despesa do SIAFE), se houver."""
    for k in _CHAVES_DURAS:
        v = c.get(k)
        if v not in (None, "", 0):
            return f"{k}:{str(v).strip().lower()}"
    return None


def _idf(docs: list[list[str]]) -> dict[str, float]:
    """IDF suavizado: quanto mais raro o termo NO LOTE, mais ele discrimina. É o que faz 'material'
    (presente em quase tudo) valer quase nada e 'limpeza' (presente em poucos) valer muito."""
    n = len(docs) or 1
    df: dict[str, int] = {}
    for d in docs:
        for t in set(d):
            df[t] = df.get(t, 0) + 1
    return {t: math.log((n + 1) / (v + 1)) + 1.0 for t, v in df.items()}


def _vetor(doc: list[str], idf: dict[str, float]) -> dict[str, float]:
    tf: dict[str, float] = {}
    for t in doc:
        tf[t] = tf.get(t, 0.0) + 1.0
    vec = {t: (1.0 + math.log(f)) * idf.get(t, 1.0) for t, f in tf.items()}
    norma = math.sqrt(sum(v * v for v in vec.values())) or 1.0
    return {t: v / norma for t, v in vec.items()}


def _cos(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(t, 0.0) for t, v in a.items())


def _vetores(contratacoes: list[dict]) -> tuple[list[dict], list[list[str]]]:
    docs = [tokens(c.get("objeto", "")) for c in contratacoes]
    idf = _idf([d for d in docs if d])
    return [_vetor(d, idf) for d in docs], docs


def agrupar(contratacoes: list[dict], limiar: float = LIMIAR, *, por_ramo: bool = False) -> list[list[int]]:
    """Agrupa contratações. Retorna clusters de índices, ordenados (determinístico).

    `por_ramo=True` aplica o critério LEGAL do art. 75, §1º, II — "objetos de MESMA NATUREZA, entendidos
    como tais aqueles relativos a contratações no MESMO RAMO DE ATIVIDADE". É o que o detector de
    fracionamento deve usar: sabão em pó e desinfetante não são o mesmo objeto, mas são o mesmo ramo e
    SOMAM para o limite de dispensa. `por_ramo=False` (default) agrupa por objeto ~idêntico — o
    detalhamento que o auditor lê no dossiê.

    Chave dura (CATMAT/natureza) manda: igual agrupa, diferente SEPARA — não cai para o texto, porque a
    classificação oficial é mais confiável que a descrição livre. Sem chave dura, ramo (se pedido) e
    depois TF-IDF/cosseno ≥ limiar. Objeto genérico nunca agrupa (não se soma o que não se sabe o que é).
    """
    n = len(contratacoes)
    if n == 0:
        return []
    pai = list(range(n))

    def find(x: int) -> int:
        while pai[x] != x:
            pai[x] = pai[pai[x]]
            x = pai[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            pai[max(ra, rb)] = min(ra, rb)

    duras = [chave_dura(c) for c in contratacoes]
    genericos = [generico(c.get("objeto", "")) for c in contratacoes]
    ramos = [ramo_atividade(c.get("objeto", "")) if por_ramo else None for c in contratacoes]
    vecs, _docs = _vetores(contratacoes)
    for i in range(n):
        for j in range(i + 1, n):
            if duras[i] and duras[j]:
                if duras[i] == duras[j]:
                    union(i, j)
                continue                      # classificação oficial divergente: NÃO cai para o texto
            if genericos[i] or genericos[j]:
                continue                      # descrição que não identifica objeto fica isolada
            if por_ramo and ramos[i] and ramos[j]:
                if ramos[i] == ramos[j]:      # art. 75, §1º, II — mesma natureza = mesmo ramo
                    union(i, j)
                continue                      # ramos distintos NÃO somam, ainda que o texto se pareça
            if _cos(vecs[i], vecs[j]) >= limiar:
                union(i, j)
    grupos: dict[int, list[int]] = {}
    for i in range(n):
        grupos.setdefault(find(i), []).append(i)
    return [sorted(g) for g in sorted(grupos.values(), key=lambda g: min(g))]


def explicar(contratacoes: list[dict], i: int, j: int) -> dict:
    """POR QUE estes dois foram (ou não) agrupados — para o dossiê: critério, score e termos em comum.
    Um achado de fracionamento sem isto é inauditável."""
    di, dj = chave_dura(contratacoes[i]), chave_dura(contratacoes[j])
    if di and dj:
        return {"criterio": "chave_dura", "score": 1.0 if di == dj else 0.0,
                "agrupa": di == dj, "chave_i": di, "chave_j": dj, "termos_em_comum": []}
    oi, oj = contratacoes[i].get("objeto", ""), contratacoes[j].get("objeto", "")
    if generico(oi) or generico(oj):
        return {"criterio": "objeto_generico", "score": 0.0, "agrupa": False, "termos_em_comum": [],
                "nota": "descrição não identifica o objeto — não se soma o que não se sabe o que é"}
    vecs, docs = _vetores(contratacoes)
    score = _cos(vecs[i], vecs[j])
    comuns = sorted(set(docs[i]) & set(docs[j]), key=lambda t: -vecs[i].get(t, 0.0))
    return {"criterio": "similaridade_tfidf", "score": round(score, 4), "agrupa": score >= LIMIAR,
            "termos_em_comum": comuns,
            "nota": "peso de cada termo = quanto ele DISCRIMINA no lote (TF-IDF); termos comuns a "
                    "quase toda contratação não sustentam agrupamento"}
