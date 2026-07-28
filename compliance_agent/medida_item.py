# -*- coding: utf-8 -*-
"""Assinatura de MEDIDA do item — separa produtos de tamanho/embalagem diferentes.

Motivação (dono, 2026-07-24): a descrição do PNCP mistura tamanhos sob rótulo genérico.
No dado real, 'AGUA MINERAL (CAIXA COM 48 COPOS DE 200ML)' (R$44,94, uma caixa) caía no
mesmo grupo de 'AGUA MINERAL COPO DE 200 ML' (R$0,70, um copo) — 64× de falso sobrepreço.
Comparar preço unitário só faz sentido entre a MESMA embalagem: fardo com fardo, copo com
copo. Esta assinatura vira parte da chave de grupo do comparador.

HONESTIDADE: quando o tamanho NÃO é extraível (`sig == ""`), o agrupamento cai no
comportamento anterior — nunca pior, só mais fino quando há informação. Não inventa
tamanho: número ambíguo (ex.: '20L' vs '20 unidades') só vira volume com unidade explícita.
"""
from __future__ import annotations

import re
import unicodedata

# vocabulário de unidade de medida → forma canônica (agrupa Galao/GL/GAL/GALÃO…)
_UN_CANON = {
    "galao": "galao", "galoes": "galao", "gl": "galao", "gal": "galao",
    "unidade": "unidade", "unidades": "unidade", "un": "unidade", "und": "unidade",
    "unid": "unidade", "uni": "unidade", "pc": "unidade", "pca": "unidade",
    "fardo": "fardo", "fd": "fardo", "frd": "fardo",
    "caixa": "caixa", "cx": "caixa", "cxa": "caixa",
    "garrafa": "garrafa", "grf": "garrafa", "gfa": "garrafa",
    "pacote": "pacote", "pct": "pacote", "pcte": "pacote",
    "litro": "litro", "litros": "litro", "lt": "litro", "l": "litro",
    "frasco": "frasco", "fr": "frasco",
    "ampola": "ampola", "amp": "ampola",
    "embalagem": "embalagem", "emb": "embalagem",
    "rolo": "rolo", "bobina": "rolo",
    "tubo": "tubo", "bisnaga": "bisnaga", "bag": "bag", "balde": "balde",
    "lata": "lata",
    "saco": "saco", "sc": "saco",
    "resma": "resma",
    "par": "par", "pares": "par",
    "metro": "metro", "m": "metro", "mt": "metro",
    "comprimido": "comprimido", "capsula": "capsula", "cap": "capsula",
    "kg": "kg", "quilo": "kg", "quilograma": "kg", "g": "g", "grama": "g",
    "mg": "mg", "mililitro": "mililitro",   # "litro" já está acima, com os aliases
}


def _norm(s: str) -> str:
    t = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


# contagens NOMEADAS → nº de itens por embalagem
_CONTAGEM_NOMEADA = {
    "cento": 100, "centos": 100, "milheiro": 1000, "milheiros": 1000, "milhar": 1000,
    "duzia": 12, "duzias": 12, "resma": 500, "resmas": 500, "grosa": 144, "grosas": 144,
    "par": 2, "pares": 2, "dezena": 10, "dezenas": 10,
}


def un_canon(u: str | None) -> str:
    """Unidade de medida bruta → TIPO de recipiente/unidade canônico.

    Ignora número e medida secundária embutidos ('Frasco 100,00 ML' → 'frasco') e
    distingue metro linear de m²/m³ (que hoje colapsavam e comparavam R$/m² com R$/m).
    Desconhecida preserva o slug alfabético (ex.: 'PESSOAS').
    """
    t = _norm(u)
    if not t.strip():
        return ""
    # área/volume: checar o COMPOSTO antes de 'metro' (senão 'metro quadrado' vira 'metro')
    if re.search(r"\bm2\b|\bm²\b|metros? quadrados?", t):
        return "m2"
    if re.search(r"\bm3\b|\bm³\b|metros? cubicos?", t):
        return "m3"
    if "frasco" in t and "ampola" in t:
        return "frasco_ampola"
    # primeiro token que é uma unidade conhecida (ignora número/medida secundária)
    for tok in re.findall(r"[a-z]+", t):
        if tok in _UN_CANON:
            return _UN_CANON[tok]
        if tok in _CONTAGEM_NOMEADA:
            return tok
    # fallback: só letras (sem números/medidas), como antes
    slug = re.sub(r"[^a-z]", "", t)
    return _UN_CANON.get(slug, slug)


# número pt-BR: permite milhar ('1.500', '1.000.000') e decimal ('1,5', '0,20').
_NUM = r"(\d[\d.]*\d|\d)(?:,\d+)?"
# volume: número seguido de ml | l/lt/lts/litro(s)
_RX_ML = re.compile(rf"({_NUM})\s*ml\b")
_RX_L = re.compile(rf"({_NUM})\s*(?:l|lt|lts|litro|litros)\b")
# peso: kg / mg / g (nessa ordem — kg e mg antes do g solto)
_RX_KG = re.compile(rf"({_NUM})\s*(?:kg|quilo|quilograma)s?\b")
_RX_MG = re.compile(rf"({_NUM})\s*mg\b")
_RX_G = re.compile(rf"({_NUM})\s*(?:g|grama)s?\b")
# contagem de embalagem: 'caixa com 48', 'fardo c/ 12', 'com 6 unidades', 'pacote com 100', 'c/24'
_RX_PACK = re.compile(
    r"(?:caixa|cx|fardo|fd|pacote|pct|c)\s*(?:om|/|\s)?\s*(\d{1,4})\b"
    r"|com\s+(\d{1,4})\s*(?:unidad|copo|garraf|frasco|lata|pote)")
# 'N UN' no campo unidade ('Pacote 100,00 UN', 'Caixa 100,00 UN')
_RX_NUN = re.compile(
    r"(\d{1,5})(?:[.,]\d+)?\s*(?:un|und|unid|unidades?|unidade|copos?|comprimidos?|"
    r"capsulas?|folhas?|ampolas?|frascos?)\b")


def _num(s: str) -> float:
    """Número pt-BR → float. Vírgula = decimal; ponto = MILHAR ('1.500'=1500, '1.000,50'=1000.5).
    Ponto com fração ≠ 3 dígitos é decimal ('1.5'=1.5, '0.20'=0.2)."""
    s = s.strip().strip(".,")
    if "," in s:                       # vírgula decimal → ponto é milhar
        return float(s.replace(".", "").replace(",", "."))
    if "." in s:
        partes = s.split(".")
        if all(len(p) == 3 for p in partes[1:]):   # 1.500 / 1.000.000 = milhar
            return float("".join(partes))
        return float(s)                # 1.5 = decimal
    return float(s)


def _extrai_ml(texto: str) -> float | None:
    """Volume unitário em mL (float — doses <1 mL como 0,2 NÃO podem virar 0)."""
    m = _RX_ML.search(texto)
    if m:
        return _num(m.group(1))
    m = _RX_L.search(texto)
    if m:
        return _num(m.group(1)) * 1000
    return None


# peso que é RATING, não medida do produto: 'CARGA TOTAL: 200 KG', 'suporta 100 kg'
_RATING = ("carga", "suporta", "resistenc", "capacidade de carga", "peso maximo",
           "peso suportado", "tara", "tracao")


def _rating_antes(texto: str, pos: int) -> bool:
    """True se a medida em `pos` é precedida (janela curta) por palavra de rating."""
    janela = texto[max(0, pos - 30):pos]
    return any(w in janela for w in _RATING)


def _extrai_g(texto: str) -> float | None:
    """Peso em GRAMAS (kg→×1000, mg→×0,001). Ignora rating de carga (cadeira 'CARGA 200 KG')."""
    for rx, fator in ((_RX_KG, 1000), (_RX_MG, 0.001), (_RX_G, 1)):
        m = rx.search(texto)
        if m and not _rating_antes(texto, m.start()):
            return _num(m.group(1)) * fator
    return None


def _cento_de_embalagem(texto: str) -> bool:
    """'cento' como unidade (100), NÃO como 'por cento'/'porcento'/'cento e vinte'."""
    if "por cento" in texto or "porcento" in texto or "percent" in texto:
        return False
    for m in re.finditer(r"\bcento\b", texto):
        depois = texto[m.end():m.end() + 3]
        if not depois.lstrip().startswith("e "):   # 'cento e vinte' = número, não 100
            return True
    return False


def _extrai_n(texto: str) -> int:
    # contagem NOMEADA (cento/milheiro/resma/dúzia/grosa/par/dezena)
    if _cento_de_embalagem(texto):
        return 100
    for palavra, val in _CONTAGEM_NOMEADA.items():
        if palavra in ("cento", "centos"):
            continue  # tratado com guarda anti-'por cento' acima
        if re.search(rf"\b{palavra}\b", texto):
            return val
    # 'caixa com N' / 'com N unidades'
    p = _RX_PACK.search(texto)
    if p:
        val = p.group(1) or p.group(2)
        if val and int(val) >= 2:
            return int(val)
    # 'N UN' no campo unidade ('Pacote 100,00 UN')
    m = _RX_NUN.search(texto)
    if m and int(m.group(1)) >= 2:
        return int(m.group(1))
    return 1


def _fmt(x: float) -> str:
    return f"{x:g}"


def assinatura_medida(descricao: str, unidade: str | None = None) -> dict:
    """Descrição (+ unidade_medida) → {ml, g, n, sig}. Volume (ml), peso (g) e itens por
    embalagem (n), extraídos dos DOIS campos (descrição tem prioridade). `sig` = chave
    canônica ('' quando nada extraível) — entra na chave de grupo: mesma sig ⇒ comparáveis.

    Cobre o que quebrava a comparação de preço unitário: fardo≠copo (ml), 1kg≠500g (g),
    pacote-de-100≠unidade-avulsa e cento/milheiro/resma (n). Sem isso, um 'Pacote 100 UN'
    (preço 100× o da unidade) virava falso sobrepreço contra a unidade avulsa.
    """
    d = _norm(descricao)
    u = _norm(unidade)
    ml = _extrai_ml(d)
    if ml is None and u:
        ml = _extrai_ml(u)
    g = _extrai_g(d)
    if g is None and u:
        g = _extrai_g(u)
    n = _extrai_n(d)
    if n == 1 and u:
        n = _extrai_n(u)
    partes = []
    if ml:                       # descarta ml=0 (não é discriminador; junta itens não-relacionados)
        partes.append(f"ml{_fmt(ml)}")
    if g:
        partes.append(f"g{_fmt(g)}")
    if n > 1:
        partes.append(f"n{n}")
    return {"ml": ml, "g": g, "n": n, "sig": "|".join(partes)}
