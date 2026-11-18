#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Preços das PROPOSTAS dos autos SEI → `proposta_item` (fonte='sei_proposta'), SEM LLM — matéria-prima do J9.

POR QUE EXISTE. O J9 (`detectores/j9_propostas_gemeas` → `sei/conluio_propostas`) compara planilhas de
concorrentes item a item, e `proposta_item` tinha 192 linhas: o coletor de atas lê 48 atas, o
`sei_propostas_sweep` usa LLM livre e só aceita matriz comparativa, e o `extrator_precos` exige PDF ou LLM.
O arquivo canônico (`data/sei_arquivo/<tag>/manifest.json`) tem ~2.270 documentos tipo `proposta` /
`planilha_preco` com o texto já extraído. Este extrator lê esse texto de forma DETERMINÍSTICA.

A TRAVA QUE TORNA ISSO CONFIÁVEL SEM MODELO — a conta tem de fechar:
    só entra a linha de item em que  quantidade × valor unitário = valor total
    (tolerância de arredondamento: o maior entre R$ 0,02 e meio centavo por unidade, nunca acima de 0,1% do total).
O Tesseract erra ~22% dos valores em R$; um dígito trocado não fecha a conta e a linha CAI FORA (é contada).
Coincidência aritmética entre três números quaisquer de uma linha é rara; entre três números de uma linha de
planilha é o próprio item. Valores zero/negativos não entram.

FORNECEDOR. CNPJ com DV conferido no CABEÇALHO do próprio documento (primeiros `_CABECALHO_CHARS`
caracteres do corpo). Regra herdada de `sei/cotacoes_acervo` (medida no acervo): pessoa jurídica de direito
público (natureza 1xxx na Receita local) fica fora; filiais do mesmo CNPJ básico contam uma vez; se sobrar
MAIS DE UM CNPJ básico privado no cabeçalho, o documento é ambíguo (mapa comparativo, carta com
destinatário privado) e NÃO entra — atribuir preço ao fornecedor errado é pior que não atribuir.
Sem CNPJ válido → não entra.

CERTAME = o PROCESSO SEI, na chave normalizada `tools.lex_execucao._chave_processo` ('080002/8019/2026').
⚠️ O que há nos autos de execução são, na maior parte, COTAÇÕES de pesquisa de preço / dispensa, não lances
de licitantes num certame (ver docstring de `tools/sei_propostas_sweep`). O J9 serve igual — orçamento de
fachada tem a mesma assinatura —, mas o rótulo tem de ser honesto: "cotações/propostas nos autos".

FORMATOS DE TEXTO (medidos em amostras reais antes do parser):
  · tabela com " | " — planilha convertida (office) e OCR da GPU (Surya, `tools/sei_ocr_gpu_integrar`):
        '4 | Andador Pediátrico e Adulto | 278 | 0 | 30 | 8340'
  · texto nativo do PDF — as colunas viram tokens na mesma linha OU um por linha:
        '02' / 'Gigante' / … / 'R$ 14.900,00' / '(Quatorze' … / 'R$ 29.800,00'
O parser trata os dois como um FLUXO DE TOKENS (palavras e números, linha a linha); a linha de item é o trio
(q, u, t) que fecha a conta dentro de uma janela curta. Em tabela com pipes, o trio tem de estar na MESMA linha.

Uso:
    nice -n 15 .venv/bin/python -m tools.propostas_sei_extrair --medir          # só mede, não escreve
    nice -n 15 .venv/bin/python -m tools.propostas_sei_extrair --rodar          # persiste em proposta_item
    nice -n 15 .venv/bin/python -m tools.propostas_sei_extrair --analisar       # roda o J9 no que persistiu
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
DATA = _REPO / "data"
ARQUIVO = DATA / "sei_arquivo"
DB = DATA / "compliance.db"
RESUMO = DATA / "propostas_sei_extrair.json"

FONTE = "sei_proposta"
TIPOS = ("proposta", "planilha_preco")
_CABECALHO_CHARS = 3000
_JANELA_NUM = 8          # trio procurado entre os 8 números anteriores ao total
_JANELA_LINHAS = 16      # e dentro de 16 linhas (texto nativo, uma coluna por linha)
_DESC_MAX = 160
_DESC_LINHAS = 6        # descrição: até 6 linhas acima do 1º número do item
_TRECHO_MAX = 400

# ───────────────────────────── números ─────────────────────────────
_RE_BR = re.compile(r"\d{1,3}(?:\.\d{3})+,\d+|\d+,\d+")       # 1.234,56 · 12,30
_RE_MILHAR = re.compile(r"\d{1,3}(?:\.\d{3})+")                 # 22.627.200 · 1.234 (ambíguo)
_RE_PONTO = re.compile(r"\d+\.\d+")                             # 0.0792 · 3959.1 (planilha exportada)
_RE_INT = re.compile(r"\d+")
_PREFIXO_MOEDA = re.compile(r"^(?:R\s?\$|RS\$?)\s*", re.I)


def valores(tok: str) -> tuple[list[float], bool]:
    """Candidatos numéricos de um token que É um número (inteiro do token) e se ele tem cara de dinheiro.

    '1.234' é ambíguo (mil duzentos e trinta e quatro OU um vírgula dois três quatro em planilha exportada):
    devolve as duas leituras — a conta q × u = t é que decide. Token que não é número inteiro → ([], False)."""
    s = tok.strip()
    moeda = bool(_PREFIXO_MOEDA.match(s))
    s = _PREFIXO_MOEDA.sub("", s).strip()
    if not s:
        return [], False
    if _RE_BR.fullmatch(s):
        return [float(s.replace(".", "").replace(",", "."))], moeda
    if _RE_MILHAR.fullmatch(s):
        inteiro = float(s.replace(".", ""))
        return ([inteiro, float(s)] if s.count(".") == 1 else [inteiro]), moeda
    if _RE_PONTO.fullmatch(s):
        return [float(s)], moeda
    if _RE_INT.fullmatch(s) and len(s) <= 12:
        return [float(s)], moeda
    return [], False


def fecha_conta(q: float, u: float, t: float) -> bool:
    """q × u = t com tolerância de ARREDONDAMENTO (não de erro de leitura): ≥ R$ 0,02; até meio centavo por
    unidade (unitário publicado com 2 casas); nunca mais que 0,1% do total."""
    if q <= 0 or u <= 0 or t < 1.0:
        return False
    if q == 1 and u == t == 1:                 # '1,00 = 1,00' (coordenada, índice) não é item
        return False
    tol = max(0.02, min(0.005 * q + 0.01, 0.001 * t))
    return abs(q * u - t) <= tol + 1e-9


# ───────────────────────────── CNPJ / fornecedor ─────────────────────────────
_CNPJ = re.compile(r"(?<![\d/])(\d{2})\s?\.?\s?(\d{3})\s?\.?\s?(\d{3})\s?/\s?(\d{4})\s?-?\s?(\d{2})(?!\d)")
_CNPJ_NU = re.compile(r"CNPJ\W{0,12}(\d{14})(?!\d)", re.I)
_PUBLICO_TXT = re.compile(r"secretaria|governo|estado do|prefeitura|munic[ií]pio|fundo (?:estadual|municipal)|"
                          r"tribunal|minist[eé]rio|assembleia|c[aâ]mara municipal|corpo de bombeiros|pol[ií]cia|"
                          r"universidade (?:estadual|federal)|funda[cç][aã]o estadual|defensoria|procuradoria", re.I)


def cnpj_valido(c: str) -> bool:
    from compliance_agent.sei.cotacoes_acervo import cnpj_valido as _v
    return _v(c)


def cnpjs_cabecalho(corpo: str) -> list[tuple[str, str]]:
    """[(cnpj, linha)] dos CNPJs com DV válido no cabeçalho, na ordem em que aparecem (sem repetir)."""
    cab = corpo[:_CABECALHO_CHARS]
    vistos, out = set(), []
    achados = [(m.start(), "".join(m.groups())) for m in _CNPJ.finditer(cab)]
    achados += [(m.start(1), m.group(1)) for m in _CNPJ_NU.finditer(cab)]
    for pos, c in sorted(achados):
        if c in vistos or not cnpj_valido(c):
            continue
        vistos.add(c)
        ini = cab.rfind("\n", 0, pos) + 1
        fim = cab.find("\n", pos)
        out.append((c, cab[ini:fim if fim >= 0 else len(cab)].strip()))
    return out


def fornecedor_do_documento(corpo: str, cadastro=None) -> tuple[str | None, str]:
    """(cnpj, motivo). `cadastro(cnpj)` → {'publico': bool, 'razao': str} | None (Receita local).

    Público fora (natureza 1xxx; sem cadastro, a linha do CNPJ citando órgão também tira). Um só CNPJ básico
    privado → é o fornecedor. Nenhum → 'sem_cnpj'. Mais de um → 'ambiguo' (não se adivinha)."""
    privados: dict[str, str] = {}
    achados = cnpjs_cabecalho(corpo)
    if not achados:
        return None, "sem_cnpj"
    for c, linha in achados:
        cad = cadastro(c) if cadastro else None
        if cad is not None:
            if cad.get("publico"):
                continue
        elif _PUBLICO_TXT.search(linha):
            continue
        privados.setdefault(c[:8], c)
    if not privados:
        return None, "so_cnpj_publico"
    if len(privados) > 1:
        return None, "ambiguo"
    return next(iter(privados.values())), "ok"


# ───────────────────────────── fluxo de tokens ─────────────────────────────
_SEP_COL = re.compile(r"\s{2,}|\t")
_CAB_TABELA = re.compile(r"^(?:valor(?:es)?|unit[aá]ri[oa]s?|total|quantidade|quant\.?|qtde?\.?|qtd\.?|unid\.?|"
                         r"unidade|descri[cç][aã]o|item|marca|modelo|pre[cç]o|r\$|lote|subtotal|und\.?|un\.?)$", re.I)
_ITEM_ROTULO = re.compile(r"\bitem\s*(?:n[º°o.]*\s*)?(\d{1,4})\b", re.I)
_TEM_LETRA = re.compile(r"[A-Za-zÀ-ÿ]{2,}")
_MOEDA_ESTRANGEIRA = ("US$", "USD", "U$", "U$S", "€", "EUR", "EUR$")


def _tokens(texto: str) -> list[dict]:
    """Fluxo de tokens {lin, txt, vals, moeda, pipe}. Numérico = token que É número (com 'R$' grudado ou
    no token anterior). Tabela com pipes: células; texto nativo: colunas por 2+ espaços, depois palavras."""
    out: list[dict] = []
    for lin, linha in enumerate(texto.splitlines()):
        pipe = linha.count("|") >= 2
        celulas = linha.split("|") if pipe else _SEP_COL.split(linha)
        for cel in celulas:
            cel = cel.strip()
            if not cel:
                continue
            vals, moeda = valores(cel)
            if vals:
                out.append({"lin": lin, "txt": cel, "vals": vals, "moeda": moeda, "pipe": pipe})
                continue
            # célula com texto e números ('VALOR TOTAL PARA 40 UNIDADES: R$ 22.627.200,00'): palavra a palavra
            palavras = cel.split()
            moeda_prox = False
            for w in palavras:
                w2 = w.strip(":;()[]")
                if _PREFIXO_MOEDA.fullmatch(w2 + " ") or w2.upper() in ("R$", "RS", "R$:"):
                    moeda_prox = True
                    out.append({"lin": lin, "txt": w, "vals": [], "moeda": False, "pipe": pipe})
                    continue
                v, m = valores(w2) if not w2.endswith("%") else ([], False)
                out.append({"lin": lin, "txt": w, "vals": v, "moeda": m or (moeda_prox and bool(v)),
                            "pipe": pipe})
                moeda_prox = False
    # 'R$' sozinho num token/linha → o número seguinte é dinheiro
    for k in range(1, len(out)):
        ant = out[k - 1]["txt"].strip().upper()
        if out[k]["vals"] and ant in ("R$", "RS", "R$:"):
            out[k]["moeda"] = True
        if out[k]["vals"] and ant in _MOEDA_ESTRANGEIRA:
            out[k]["estrangeira"] = True          # US$/€: preço em outra moeda não se compara com real
    return out


def _texto_descritivo(toks: list[dict]) -> list[str]:
    """Palavras não numéricas, sem rótulo de coluna nem 'R$', aparadas nas pontas até a 1ª/última com letra."""
    ws = [tk["txt"] for tk in toks if not tk["vals"] and not _CAB_TABELA.match(tk["txt"].strip(" :."))
          and tk["txt"].strip().upper() not in _MOEDA_ESTRANGEIRA + ("R$", "RS", "R$:")]
    com = [n for n, w in enumerate(ws) if _TEM_LETRA.search(w)]
    return ws[com[0]:com[-1] + 1] if com else []


def _cara_de_dinheiro(tok: dict) -> bool:
    return tok["moeda"] or bool(re.search(r",\d{2}$", tok["txt"]))


def _papeis(a: dict, va: float, b: dict, vb: float, quant_antes: bool | None) -> tuple[float, float, dict, dict]:
    """Quem é quantidade e quem é unitário no par (a antes de b). Devolve (q, u, tok_q, tok_u)."""
    da, db = _cara_de_dinheiro(a), _cara_de_dinheiro(b)
    if da != db:
        return (vb, va, b, a) if da else (va, vb, a, b)
    # os dois com cara de dinheiro ('63.764,20' kg × '42,44'): a ordem do cabeçalho decide antes do "é inteiro"
    # (medido: Milano '150.027,60 / 42,00' virava 42 unidades a R$ 150.027,60)
    if da and quant_antes is not None:
        return (va, vb, a, b) if quant_antes else (vb, va, b, a)
    ia, ib = float(va).is_integer(), float(vb).is_integer()
    if ia != ib:
        return (va, vb, a, b) if ia else (vb, va, b, a)
    if quant_antes is False:
        return vb, va, b, a
    return va, vb, a, b


def _ordem_cabecalho(texto: str) -> bool | None:
    """True se o cabeçalho da tabela traz QUANTIDADE antes de UNITÁRIO; False se o contrário; None sem pista."""
    m_q = re.search(r"\b(?:quantidade|quant\.?|qtde?\.?|qtd\.?)", texto, re.I)
    m_u = re.search(r"\bunit[aá]ri", texto, re.I)
    if not m_q or not m_u:
        return None
    return m_q.start() < m_u.start()


def _achar_trio(toks: list[dict], janela: list[int], t: dict, quant_antes: bool | None):
    """O par (q, u) da janela cujo produto fecha com o total `t` — o par mais perto do total primeiro.
    Devolve (i, j, q, u, total, tok_q, tok_u) ou None."""
    for j in reversed(janela):
        for i in reversed([x for x in janela if x < j]):
            for vt in t["vals"]:
                for vi in toks[i]["vals"]:
                    for vj in toks[j]["vals"]:
                        q, u, tq, tu = _papeis(toks[i], vi, toks[j], vj, quant_antes)
                        # texto nativo: o unitário ou o total tem de ter cara de dinheiro ('1 2 1 2' de
                        # paginação fecha a conta por acaso); na tabela com pipes a coluna já delimita
                        if not t["pipe"] and not (_cara_de_dinheiro(tu) or _cara_de_dinheiro(t)):
                            continue
                        if fecha_conta(q, u, vt):
                            return i, j, q, u, vt, tq, tu
    return None


def extrair_linhas(texto: str) -> dict:
    """Linhas de item cuja conta fecha. Devolve {linhas:[...], candidatos_total:int, sem_descricao:int}.

    `candidatos_total` = números com cara de total e 2+ números antes na janela — TETO (inclui unitários e
    subtotais), não contagem de itens; a medida delimitada é `tabela_linhas`/`tabela_fecharam`.
    Cada linha: {item, descricao, quantidade, valor_unitario, valor_total,
    trecho, item_literal}."""
    toks = _tokens(texto)
    linhas_txt = texto.splitlines()
    quant_antes = _ordem_cabecalho(texto)
    out, consumido, candidatos, sem_desc, estrangeira = [], -1, 0, 0, 0
    seq = 0
    for k, t in enumerate(toks):
        if not t["vals"] or k <= consumido:
            continue
        janela: list[int] = []                    # os últimos _JANELA_NUM NÚMEROS antes do total (texto não conta)
        for x in range(k - 1, consumido, -1):
            if t["lin"] - toks[x]["lin"] > _JANELA_LINHAS or (t["pipe"] and toks[x]["lin"] != t["lin"]):
                break
            if toks[x]["vals"]:
                janela.insert(0, x)
                if len(janela) >= _JANELA_NUM:
                    break
        if len(janela) < 2:
            continue
        if _cara_de_dinheiro(t):
            candidatos += 1
        achado = _achar_trio(toks, janela, t, quant_antes)
        if not achado:
            continue
        i, j, q, u, vt, tq, tu = achado
        if any(x.get("estrangeira") for x in (t, tq, tu)):
            estrangeira += 1                         # US$/€ fecha a conta mas não se compara com real: fora,
            consumido = k                            # e o registro termina aqui (o texto não vaza p/ o próximo)
            continue
        # registro = tokens desde o fim do item anterior (cortando o cabeçalho de tabela, se houver)
        ini = consumido + 1
        if t["pipe"]:
            ini = max(ini, next(x for x in range(ini, k + 1) if toks[x]["lin"] == t["lin"]))
        else:
            ini = max(ini, next((x for x in range(ini, k + 1) if toks[i]["lin"] - toks[x]["lin"] <= 40), i))
        for x in range(ini, i):                      # cabeçalho = rótulos ANTES do 1º número do registro
            if toks[x]["vals"]:
                break
            if _CAB_TABELA.match(toks[x]["txt"].strip(" :.")):
                ini = x + 1
        registro = toks[ini:k + 1]
        # nº do item: o ÚLTIMO inteiro curto do registro que abre a linha e é seguido de texto (a descrição). O
        # último, não o primeiro: quando o item anterior não fechou a conta, o registro começa no nº DELE
        # (medido: 'Graná 298' item 02 CHARQUE não fecha → o LAGARTO herdava o nº 02 em vez do 03).
        item, literal, desc_ini = None, False, ini
        for x in range(ini, i):
            tk = toks[x]
            if (tk["vals"] and tk is not tq and tk is not tu and re.fullmatch(r"0*\d{1,4}", tk["txt"])
                    and (x == 0 or toks[x - 1]["lin"] != tk["lin"])
                    and x + 1 < len(toks) and not toks[x + 1]["vals"] and _TEM_LETRA.search(toks[x + 1]["txt"])):
                item, literal, desc_ini = int(tk["txt"]), True, x + 1
        if item is None:
            ms = _ITEM_ROTULO.findall(" ".join(tk["txt"] for tk in registro))
            if ms:
                item, literal = int(ms[-1]), True
        # descrição = só as linhas PRÓXIMAS do 1º número do item: o 1º registro de um documento começa no topo e
        # puxaria endereço, saudação e cabeçalho do órgão para a descrição
        desc_toks = _texto_descritivo([tk for tk in toks[desc_ini:i] if toks[i]["lin"] - tk["lin"] <= _DESC_LINHAS])
        if not desc_toks:   # texto entre o par e o total (marca/modelo no nativo) só se não houve descrição antes
            desc_toks = _texto_descritivo(toks[i:k])
        descricao = re.sub(r"\s+", " ", " ".join(desc_toks)).strip()[:_DESC_MAX]
        if not descricao:                          # sem o que é o item não há o que conferir nem casar
            sem_desc += 1
            consumido = k
            continue
        seq += 1
        l0 = min(toks[ini]["lin"], toks[i]["lin"])
        trecho = " / ".join(s.strip() for s in linhas_txt[l0:t["lin"] + 1] if s.strip())
        if len(trecho) > _TRECHO_MAX:
            trecho = "… " + trecho[-(_TRECHO_MAX - 2):]
        out.append({"item": item if item is not None else seq, "item_literal": literal,
                    "descricao": descricao, "quantidade": q, "valor_unitario": u, "valor_total": vt,
                    "trecho": trecho, "_lin": t["lin"]})
        consumido = k
    # medida honesta do que NÃO fechou, onde a linha é delimitada: linha de tabela com pipes que tem texto e 3+
    # células numéricas (cara de item) — quantas viraram linha válida e quantas não fecharam a conta
    por_lin: dict[int, list[dict]] = {}
    for tk in toks:
        if tk["pipe"]:
            por_lin.setdefault(tk["lin"], []).append(tk)
    usadas = {ln["_lin"] for ln in out}
    tab = [li for li, ts in por_lin.items()
           if sum(1 for x in ts if x["vals"]) >= 3 and any(_TEM_LETRA.search(x["txt"]) for x in ts)]
    for ln in out:
        ln.pop("_lin", None)
    return {"linhas": out, "candidatos_total": candidatos, "sem_descricao": sem_desc,
            "moeda_estrangeira": estrangeira, "tabela_linhas": len(tab),
            "tabela_fecharam": sum(1 for li in tab if li in usadas)}


# ───────────────────────────── acervo ─────────────────────────────
def _corpo(texto: str) -> str:
    """Tira o cabeçalho da casa ('[título] (fase: … · tipo: …)') — o título do SEI não é do fornecedor."""
    if texto.startswith("["):
        fim = texto.find("\n")
        if fim > 0:
            return texto[fim + 1:]
    return texto


def documentos(raiz: Path = ARQUIVO):
    """Gera {tag, processo, i, titulo, tipo, caminho, ocr, motor} dos docs proposta/planilha_preco."""
    for mpath in sorted(raiz.glob("*/manifest.json")):
        try:
            man = json.loads(mpath.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        tag = mpath.parent.name
        for d in man.get("docs") or []:
            if d.get("tipo") not in TIPOS or not d.get("texto"):
                continue
            yield {"tag": tag, "processo": man.get("processo") or tag, "i": d.get("i"),
                   "titulo": d.get("titulo") or "", "tipo": d["tipo"], "caminho": mpath.parent / d["texto"],
                   "ocr": str(d.get("ocr")) == "True", "motor": str(d.get("ocr_motor") or "")}


def certame_de(doc: dict) -> str | None:
    from tools.lex_execucao import _chave_processo
    return _chave_processo(doc["processo"]) or _chave_processo(doc["tag"].replace("_", "/"))


def _cadastro_receita():
    """cnpj → {'publico','razao'} pela Receita local (READONLY); sem a base → None (a regra textual assume)."""
    from compliance_agent.sei import cotacoes_acervo as CA
    if not CA._RECEITA.exists():
        return None
    con = sqlite3.connect(f"file:{CA._RECEITA}?mode=ro", uri=True)
    cache: dict[str, dict | None] = {}

    def cad(c: str):
        if c not in cache:
            try:
                cache[c] = CA._cadastro(con, c)
            except sqlite3.Error:
                cache[c] = None
        return cache[c]
    return cad


def processar(raiz: Path = ARQUIVO, *, cadastro=None, limite: int | None = None) -> dict:
    """Varre o acervo e devolve {medidas, por_certame: {certame: [linha canônica p/ persistir_propostas]}}."""
    med = {"docs": 0, "docs_ocr": 0, "docs_gpu": 0, "sem_texto": 0, "sem_certame": 0,
           "sem_cnpj": 0, "so_cnpj_publico": 0, "ambiguo": 0, "com_fornecedor": 0,
           "docs_com_linha": 0, "linhas_validas": 0, "linhas_validas_ocr": 0,
           "candidatos_total": 0, "nao_fecharam_conta": 0, "sem_descricao": 0, "item_sem_numero": 0,
           "moeda_estrangeira": 0, "tabela_linhas": 0, "tabela_fecharam": 0}
    # sem a Receita local o filtro de órgão público é só textual (mais fraco) — o laudo tem de dizer
    med["receita_local"] = cadastro is not None
    por_certame: dict[str, list[dict]] = {}
    nomes: dict[str, str] = {}
    for n, doc in enumerate(documentos(raiz)):
        if limite and n >= limite:
            break
        med["docs"] += 1
        med["docs_ocr"] += doc["ocr"]
        med["docs_gpu"] += doc["motor"].startswith("surya")
        try:
            texto = doc["caminho"].read_text(encoding="utf-8", errors="replace")
        except OSError:
            med["sem_texto"] += 1
            continue
        corpo = _corpo(texto)
        certame = certame_de(doc)
        if not certame:
            med["sem_certame"] += 1
            continue
        cnpj, motivo = fornecedor_do_documento(corpo, cadastro)
        if not cnpj:
            med[motivo] += 1
            continue
        med["com_fornecedor"] += 1
        r = extrair_linhas(corpo)
        med["candidatos_total"] += r["candidatos_total"]
        for k_ in ("sem_descricao", "moeda_estrangeira", "tabela_linhas", "tabela_fecharam"):
            med[k_] += r[k_]
        if not r["linhas"]:
            continue
        med["docs_com_linha"] += 1
        if cadastro and cnpj not in nomes:
            nomes[cnpj] = (cadastro(cnpj) or {}).get("razao") or ""
        for ln in r["linhas"]:
            med["linhas_validas"] += 1
            med["linhas_validas_ocr"] += doc["ocr"]
            med["item_sem_numero"] += not ln["item_literal"]
            por_certame.setdefault(certame, []).append({
                "item": ln["item"], "fornecedor_cnpj": cnpj, "fornecedor_nome": nomes.get(cnpj) or None,
                "valor_unitario": ln["valor_unitario"], "valor_total": ln["valor_total"],
                "quantidade": ln["quantidade"], "descricao": ln["descricao"], "fonte": FONTE,
                "item_literal": ln["item_literal"],
                "trecho": ln["trecho"], "documento": f"{doc['tag']}#{doc['i']} {doc['titulo']}"[:200]})
    por_certame = _numerar(por_certame, med)
    # teto, não contagem: todo número com cara de dinheiro e 2+ números antes (inclui unitários e subtotais)
    med["nao_fecharam_conta"] = max(0, med["candidatos_total"] - med["linhas_validas"])
    med["tabela_nao_fecharam"] = med["tabela_linhas"] - med["tabela_fecharam"]
    # fornecedor = CNPJ BÁSICO: matriz e filial da mesma empresa não são dois concorrentes
    forn = {c: {p["fornecedor_cnpj"][:8] for p in ps} for c, ps in por_certame.items()}
    med["certames_com_linha"] = len(por_certame)
    med["certames_2mais_fornecedores"] = sum(1 for s in forn.values() if len(s) >= 2)
    med["fornecedores_distintos"] = len({c for s in forn.values() for c in s})
    return {"medidas": med, "por_certame": por_certame}


# `proposta_item` guarda só o hash do trecho e não tem descrição/quantidade (o schema é contrato de outros
# leitores e de teste). A EVIDÊNCIA literal fica ao lado, na mesma chave — é o que se abre para conferir.
DDL_EVIDENCIA = """CREATE TABLE IF NOT EXISTS proposta_item_evidencia (
    certame TEXT NOT NULL, item INTEGER NOT NULL, fornecedor_cnpj TEXT NOT NULL, fonte TEXT NOT NULL,
    descricao TEXT, quantidade REAL, item_literal INTEGER, documento TEXT, trecho TEXT,
    PRIMARY KEY (certame, item, fornecedor_cnpj, fonte))"""


ITEM_ATRIBUIDO = 100001     # nº ≥ este = atribuído pelo extrator (o texto não numerava o item); < este = literal


def _numerar(por_certame: dict[str, list[dict]], med: dict) -> dict[str, list[dict]]:
    """Por certame e fornecedor: tira a MESMA linha repetida (proposta juntada duas vezes, cópia em outro
    anexo) e dá ao item sem número literal um nº próprio ≥ ITEM_ATRIBUIDO — senão o sequencial do extrator
    colide na PK (certame, item, cnpj) com o item literal ou com o de outro documento e uma linha apaga a outra.
    Mesmo nº literal com preço diferente (lotes que recomeçam em 1, proposta revista, quantidade lida como nº):
    a 1ª fica literal; as outras viram nº atribuído (a linha fica, o nº deixa de casar entre propostas) e conta-se."""
    med.setdefault("linhas_repetidas", 0)
    med.setdefault("item_literal_colidiu", 0)
    out: dict[str, list[dict]] = {}
    for certame, linhas in por_certame.items():
        vistos, literais, prox, fica = set(), set(), {}, []
        for ln in linhas:
            assin = (ln["fornecedor_cnpj"], ln["descricao"], ln["quantidade"], ln["valor_unitario"],
                     ln["valor_total"])
            if assin in vistos:
                med["linhas_repetidas"] += 1
                continue
            vistos.add(assin)
            chave = (ln["fornecedor_cnpj"], ln["item"])
            if ln["item_literal"] and chave in literais:
                med["item_literal_colidiu"] += 1             # o nº não identifica o item: deixa de ser literal
                ln = {**ln, "item_literal": False}
            if ln["item_literal"]:
                literais.add(chave)
            else:
                n = prox.get(ln["fornecedor_cnpj"], ITEM_ATRIBUIDO)
                prox[ln["fornecedor_cnpj"]] = n + 1
                ln = {**ln, "item": n}
            fica.append(ln)
        out[certame] = fica
    med["linhas_persistiveis"] = sum(len(v) for v in out.values())
    return out


def persistir(por_certame: dict[str, list[dict]], db: Path = DB) -> int:
    """Grava em `proposta_item` (só fonte='sei_proposta') + a evidência literal em `proposta_item_evidencia`.
    Apaga o que ESTA fonte tinha e regrava (as outras fontes ficam intocadas): a extração é determinística, e
    linha que deixou de fechar a conta (texto relido pela GPU) não pode ficar viva."""
    from compliance_agent.editais.coletor_propostas import garantir_tabela, persistir_propostas
    con = sqlite3.connect(str(db), timeout=120)
    try:
        garantir_tabela(con)
        con.execute(DDL_EVIDENCIA)
        con.execute("DELETE FROM proposta_item WHERE fonte=?", (FONTE,))
        con.execute("DELETE FROM proposta_item_evidencia WHERE fonte=?", (FONTE,))
        n = 0
        for certame, linhas in sorted(por_certame.items()):
            n += persistir_propostas(con, certame, linhas)
            for ln in linhas:
                con.execute("INSERT OR REPLACE INTO proposta_item_evidencia VALUES (?,?,?,?,?,?,?,?,?)",
                            (certame, int(ln["item"]), ln["fornecedor_cnpj"], FONTE, ln.get("descricao"),
                             ln.get("quantidade"), int(bool(ln.get("item_literal"))), ln.get("documento"),
                             ln.get("trecho")))
        con.commit()
    finally:
        con.close()
    return n


# ───────────────────────────── J9 sobre o resultado ─────────────────────────────
def analisar(db: Path = DB, *, minimo_itens: int = 3) -> dict:
    """Roda o J9 (`detectores.J9PropostasGemeas`) por certame sobre as linhas desta fonte.

    Casamento de item: pelo NÚMERO quando os dois lados o têm literal; descrição como fallback (a chave do motor
    já inclui a medida). Vetor 100% idêntico entre dois CNPJs vai para `suspeitos` (provável mesmo documento /
    coluna duplicada — lição do `sei_propostas_sweep`), não para achados."""
    from compliance_agent.detectores.j9_propostas_gemeas import J9PropostasGemeas
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT p.certame, p.fornecedor_cnpj, p.item, e.descricao, p.valor_unitario, e.item_literal "
            "FROM proposta_item p "
            "LEFT JOIN proposta_item_evidencia e ON e.certame=p.certame AND e.item=p.item "
            "AND e.fornecedor_cnpj=p.fornecedor_cnpj AND e.fonte=p.fonte "
            "WHERE p.fonte=? AND p.valor_unitario > 0 ORDER BY p.certame, p.fornecedor_cnpj, p.item",
            (FONTE,)).fetchall()
    finally:
        con.close()
    por: dict[str, dict[str, list[dict]]] = {}
    for certame, cnpj, item, desc, vu, literal in rows:
        # nº LITERAL do item casa entre propostas (o edital/termo numera); nº sequencial (o extrator contou) não
        # casa — uma linha que não fechou a conta desalinharia a lista inteira. Aí casa pela descrição.
        chave = f"item {item}" if literal else (desc or "")
        if not chave:
            continue
        por.setdefault(certame, {}).setdefault(cnpj, []).append({"descricao": chave, "valor_unitario": float(vu)})
    det = J9PropostasGemeas()
    achados, suspeitos, avaliados = [], [], 0
    for certame, forn in sorted(por.items()):
        uteis = {c: it for c, it in forn.items() if len(it) >= minimo_itens}
        if len({c[:8] for c in uteis}) < 2:
            continue
        avaliados += 1
        res = det.avaliar({"processo": certame,
                           "propostas": [{"fornecedor": c, "cnpj": c, "itens": it} for c, it in uteis.items()]})
        for ind in (res.valores or {}).get("indicios") or []:
            va = {i["descricao"]: i["valor_unitario"] for i in uteis.get(ind["a"], [])}
            vb = {i["descricao"]: i["valor_unitario"] for i in uteis.get(ind["b"], [])}
            comuns = set(va) & set(vb)
            reg = {"certame": certame, "fornecedores": len(uteis), **ind}
            if ind["a"][:8] == ind["b"][:8]:
                continue                                 # matriz × filial: a mesma empresa não conluia consigo
            if comuns and all(va[k] == vb[k] for k in comuns):
                reg["motivo_suspeita"] = ("vetor IDÊNTICO em 100% dos itens comuns — provável mesmo documento "
                                          "juntado sob dois CNPJs ou coluna duplicada; conferir antes de tratar "
                                          "como indício.")
                suspeitos.append(reg)
            else:
                achados.append(reg)
    return {"certames_com_dado": len(por), "avaliados": avaliados, "indicios": len(achados),
            "achados": achados, "suspeitos_de_extracao": len(suspeitos), "suspeitos": suspeitos,
            "_nota": "Cotações/propostas nos autos SEI (fonte sei_proposta). Indício a verificar, nunca acusação."}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--medir", action="store_true", help="só mede (não escreve)")
    ap.add_argument("--rodar", action="store_true", help="extrai e persiste em proposta_item")
    ap.add_argument("--analisar", action="store_true", help="roda o J9 sobre o que esta fonte persistiu")
    ap.add_argument("--limite", type=int, default=None)
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--arquivo", default=str(ARQUIVO), help="raiz do arquivo canônico SEI (só leitura)")
    a = ap.parse_args()
    if not (a.medir or a.rodar or a.analisar):
        a.rodar = a.analisar = True                      # padrão da propagação: extrai, grava, analisa
    out: dict = {"em": time.strftime("%F %T")}
    if a.medir or a.rodar:
        r = processar(Path(a.arquivo), cadastro=_cadastro_receita(), limite=a.limite)
        out["medidas"] = r["medidas"]
        if a.rodar:
            out["persistidas"] = persistir(r["por_certame"], Path(a.db))
    if a.analisar:
        j9 = analisar(Path(a.db))
        out["j9"] = {k: v for k, v in j9.items() if k not in ("achados", "suspeitos")}
        out["j9"]["achados"] = j9["achados"][:50]
        out["j9"]["suspeitos"] = j9["suspeitos"][:20]
    if a.rodar:
        RESUMO.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "j9"} | {"j9": {k: v for k, v in out.get("j9", {}).items()
                                                                          if k not in ("achados", "suspeitos")}},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
