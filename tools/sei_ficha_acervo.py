# -*- coding: utf-8 -*-
"""sei_ficha_acervo — FICHA SEI a partir do ACERVO (`data/sei_arquivo`), em LOTE pela API (Haiku, Batch, 50%).

POR QUE EXISTE. A ficha (`sei_ficha`) só nascia do cache de varredura do browser (`sei_cache/cdp_SEI_*.json` →
`sei_refichar` → `sei_depurar_db`). Desde que a captura passou a vir das ÍNTEGRAS dos nós (VM-2, it-campo — 14/11/2026),
o processo entra no acervo SEM cache, e ninguém o fichava: medido em 14/11/2026, 3.730 dos 6.418 processos do acervo
sem ficha, e por consequência sem `lex_execucao` (que lê a ficha). O ritmo do caminho antigo era ~60 fichas/dia.

O QUE FAZ, e onde mora cada garantia (diretriz do dono, 13/11/2026: "não pode ter margem pra erro em nada"):
  1. FILA pelo VALOR PAGO (OB `Contabilizado` no SIAFE, `lex_execucao.mapa_obs_siafe`), depois pelo tamanho do texto.
  2. TEXTO por VALOR FISCALIZATÓRIO (`classificador_doc.ordenar_para_leitura`, nunca os N primeiros da árvore), sem a
     etiqueta da casa (`acervo_texto.ler`), cada peça com o cabeçalho `=== DOCUMENTO: <título> ===` que a ficha cita.
     Teto DECLARADO (`TETO_TOTAL`/`TETO_DOC`); o que ficou de fora vai contado em `verificacao`.
  3. EXTRAÇÃO pelo prompt canônico da ficha (`tools/sei_ficha`: mesmo schema, mesmo exemplo) — Haiku 5.5 pela Batch
     API, balde `extracao_sei` do `claude_api` (teto em dólar, reserva antes de enviar). Nunca Opus pela API.
  3b. COLETA GRÁTIS ANTES DO HAIKU (22/11/2026, seção "COLETA GRÁTIS" abaixo): consenso de modelos grátis provados;
     só a coleta, sem juízo; qualquer grave/silêncio → o processo vai ao Haiku. Desliga com JFN_FICHA_GRATIS=0.
  4. CONFERÊNCIA POR CÓDIGO contra o texto (`llm/verificacao`): documento só entra com o trecho LITERAL achado na
     fonte; red flag só com a citação `[Doc: … — "trecho"]` achada; valor/CNPJ/data/parte só se aparecem no texto.
     O resto é DESCARTADO, nunca corrigido — e contado.
     Desde a v2 (20/11/2026) o TEXTO CORRIDO também: a frase de objeto/resumo/análise/perícias, o "ponto" do
     documento, o resto da red flag e a anotação do item que afirmam valor em R$, CNPJ, data ou nº de documento do
     SIAFE ausente do processo são descartados. Conta do modelo (soma/diferença de valores citados) é REFEITA pelo
     código; arredondamento só vale para valor que existe. A fonte da conferência é o processo inteiro no acervo.
  4b. NÍVEL DE RISCO NÃO É GRAVADO: o piloto (14/11/2026) deu 51 "alto" e 54 "médio" em 111 fichas — conta de luz
     da concessionária por inexigibilidade saiu "alto". A citação confere, a INFERÊNCIA não. O palpite do modelo
     fica em `verificacao.nivel_risco_modelo`; a coluna `nivel_risco` fica "" (não avaliado) — quem gradua é a
     camada de juízo (perícia de execução, Processo 360), nunca o modelo barato.
  5. A ficha continua sendo ÍNDICE DE TRIAGEM (ver o cabeçalho de `tools/sei_ficha`): nada daqui vira 🔴/🟡 sem a
     camada de juízo por cima. `fonte_modelo` = `claude-haiku-5-5@api-lote#acervo-v1`.

    PYTHONPATH=. .venv/bin/python -m tools.sei_ficha_acervo --estado
    PYTHONPATH=. .venv/bin/python -m tools.sei_ficha_acervo --ciclo --lote 400     # colhe o que terminou e envia
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from compliance_agent.llm import verificacao as V
from compliance_agent.sei import acervo_texto
from compliance_agent.sei.classificador_doc import ordenar_para_leitura

REPO = Path(__file__).resolve().parents[1]
ACERVO = acervo_texto.RAIZ
DB = REPO / "data" / "compliance.db"
ESTADO = REPO / "data" / "sei_ficha_acervo_estado.json"
TAREFA = "extracao_sei"
VERSAO = "acervo-v2"        # v2 (20/11/2026): o texto corrido também é conferido contra a fonte
TETO_TOTAL = 60_000        # caracteres por processo (~17k tokens): cabe no preço curto do Haiku (≤100k tokens)
TETO_DOC = 8_000           # por peça: uma peça gigante não come a janela das outras
MIN_TEXTO = 400            # abaixo disto não há o que fichar (capa/recibo) — fica fora da fila, contado
MAX_TENTATIVAS = 2         # resposta inválida 2× = sai da fila automática e aparece em --estado
# Piloto de 14/11/2026 (200 processos): com 8.000, 87 respostas cortaram no teto (raciocínio + JSON da ficha passam
# de 6.000 tokens em quase todas) — custo pago e nada aproveitado. 16.000 cabe; o custo é o que a resposta usa.
MAX_TOKENS = 16_000


def _dig(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


numero_da_pasta = acervo_texto.pasta_para_numero


# ── texto ─────────────────────────────────────────────────────────────────────────────────────────────
def _docs(pasta: Path) -> list[dict]:
    try:
        man = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        man = {}
    docs = [d for d in (man.get("docs") or []) if isinstance(d, dict) and d.get("texto")]
    if not docs:   # acervo antigo sem manifesto: os arquivos na ordem do nome, o título é o nome do arquivo
        docs = [{"titulo": f.stem, "texto": f"texto/{f.name}"} for f in sorted((pasta / "texto").glob("*.txt"))]
    return docs


def fonte_de_conferencia(pasta: Path, janela: str) -> str:
    """A fonte contra a qual a ficha é conferida: a janela enviada MAIS o texto inteiro do processo no acervo.

    Medido em 20/11/2026 (12 fatos "ausentes" abertos à mão): 5 estavam no processo, fora da janela de HOJE — o acervo
    muda entre o envio do lote e a conferência (recaptura, OCR restaurado, `--regravar` dias depois) e a ordem por
    valor fiscalizatório muda junto. O fato que está no processo é verdadeiro; ausente é o que não está em peça alguma."""
    return janela + "\n\n" + "\n\n".join(acervo_texto.ler(pasta, d) for d in _docs(pasta))


def texto_para_ficha(pasta: Path) -> tuple[str, dict]:
    """(texto rotulado por documento, cobertura). Ordem = valor fiscalizatório; árvore preservada na faixa."""
    docs = _docs(pasta)
    partes, total, lidos, cortados = [], 0, 0, 0
    for d in ordenar_para_leitura(docs):
        t = acervo_texto.ler(pasta, d).strip()
        if len(t) < 40:
            continue
        if total >= TETO_TOTAL:
            cortados += 1
            continue
        t = t[: min(TETO_DOC, TETO_TOTAL - total)]
        partes.append(f"=== DOCUMENTO: {str(d.get('titulo') or '').strip() or '(sem título)'} ===\n{t}")
        total += len(t)
        lidos += 1
    return "\n\n".join(partes), {"docs_com_texto": len(docs), "docs_lidos": lidos, "docs_fora_do_teto": cortados,
                                 "chars": total}


# ── fila ──────────────────────────────────────────────────────────────────────────────────────────────
def _ler_estado() -> dict:
    try:
        return json.loads(ESTADO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"lotes": {}, "tentativas": {}, "pequenos": []}


def _gravar_estado(e: dict) -> None:
    tmp = ESTADO.with_suffix(".tmp")
    tmp.write_text(json.dumps(e, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(ESTADO)


def _bytes_texto(pasta: Path) -> int:
    t = pasta / "texto"
    return sum(f.stat().st_size for f in t.glob("*.txt")) if t.is_dir() else 0


def fila(con: sqlite3.Connection, estado: dict) -> list[dict]:
    """Pastas do acervo sem ficha, com texto, fora de lote em curso — por valor pago (SIAFE) e depois tamanho."""
    from tools.lex_execucao import _chave_processo, mapa_obs_siafe
    com_ficha = {_dig(r[0]) for r in con.execute("SELECT numero_sei FROM sei_ficha")}
    em_lote = {cid for ids in estado.get("lotes", {}).values() for cid in ids}
    esgotados = {k for k, n in estado.get("tentativas", {}).items() if n >= MAX_TENTATIVAS}
    cands = []
    for p in ACERVO.iterdir() if ACERVO.is_dir() else ():
        if not p.is_dir() or _dig(p.name) in com_ficha or p.name in em_lote or p.name in esgotados:
            continue
        tam = _bytes_texto(p)
        if tam < MIN_TEXTO:
            continue
        cands.append({"pasta": p.name, "numero": numero_da_pasta(p.name), "bytes": tam})
    # só ORDENA a fila: autos=False — ler os espelhos de milhares de pastas custa horas a frio (~7 arquivos/s)
    obs = mapa_obs_siafe(con, [c["numero"] for c in cands], autos=False) if cands else {}
    for c in cands:
        c["pago"] = round((obs.get(_chave_processo(c["numero"])) or {}).get("total", 0.0), 2)
    cands.sort(key=lambda c: (-c["pago"], -c["bytes"]))
    # FOCO (22/11/2026): metade do lote do período Couto, cada metade por valor pago (compliance_agent/foco)
    from compliance_agent.foco import data_processo, intercalar
    return intercalar(cands, lambda c: data_processo(c["numero"]))


# ── prompt (o canônico da ficha, sem o corte de 4.500 caracteres do modelo grátis) ────────────────────────
def sistema_e_prompt(texto: str) -> tuple[str, str]:
    from tools import sei_ficha as F
    sistema = (F._SIST + F._aprendizados_pericia()
               + f"\n\nFormato da FICHA (JSON):\n{F._CAMPOS}\n\n=== EXEMPLO ===\nTEXTO:\n{F._EXEMPLO_TXT}\n"
                 f"FICHA:\n{F._EXEMPLO_FICHA}")
    return sistema, f"=== AGORA (mesmo formato) ===\nTEXTO:\n{texto}\nFICHA:"


# ── conferência por código ────────────────────────────────────────────────────────────────────────────
_FLAG = re.compile(r"^\s*\[\s*Doc:\s*(?P<ref>.*?)\s*[—–-]+\s*[\"“”'](?P<trecho>.+?)[\"“”']\s*\]", re.S)
_RETICENCIAS = re.compile(r"\.\.\.|…|\[\s*\.\.\.\s*\]")
_CNPJ = re.compile(r"\d{2}\.?\d{3}\.?\d{3}\s*/?\s*\d{4}\s*-?\s*\d{2}")
_MOEDA = re.compile(r"(\d{1,3}(?:\.\d{3})+(?:,\d{2})?|\d+,\d{2}|\d+)")
_DATA = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")
_SEM_PARENTESE = re.compile(r"\([^)]*\)")
_PARENTESE = re.compile(r"\(([^)]*)\)")


def _nucleo_data(d) -> str:
    m = _DATA.search(str(d or ""))
    n = V._normal(m.group(0) if m else _SEM_PARENTESE.sub("", str(d or "")))
    return n if len(n) >= 6 else ""


def trecho_confere(trecho: str, fonte_normal: str) -> bool:
    """Toda parte do trecho (separada por reticências) com ≥ 8 caracteres está LITERALMENTE na fonte."""
    pedacos = [V._normal(x) for x in _RETICENCIAS.split(str(trecho or ""))]
    pedacos = [x for x in pedacos if len(x) >= 8]
    return bool(pedacos) and all(x in fonte_normal for x in pedacos)


def _cnpjs_do_texto(texto: str) -> set[str]:
    return {_dig(m) for m in re.findall(r"\d{2}\.?\d{3}\.?\d{3}\s*/?\s*\d{4}\s*-?\s*\d{2}", texto or "")}


# ── texto corrido (20/11/2026) ────────────────────────────────────────────────────────────────────────
# A conferência cobria só as LISTAS. O texto corrido (objeto, resumo, análise, perícias, o "ponto" de cada documento,
# a parte da red flag depois da citação e a ANOTAÇÃO entre parênteses dos itens) era gravado como o modelo escreveu —
# com valor, CNPJ, data e nº de documento do SIAFE que não estão no texto. Regra igual à das listas: a FRASE que traz
# um fato desses sem fonte é descartada (nunca corrigida) e contada em `verificacao.conferido.narrativa`.
_F_CNPJ = re.compile(r"(?<!\d)\d{2}\.?\d{3}\.?\d{3}\s*/\s*\d{4}\s*-?\s*\d{2}(?!\d)")
_F_DATA = re.compile(r"(?<![\d/])\d{1,2}/\d{1,2}/\d{4}(?![\d/])")
_F_SIAFE = re.compile(r"(?<![0-9A-Za-z])\d{4}(?:NE|NL|OB|PD|RE|DL|NC)\d{3,}(?![0-9A-Za-z])")
_F_MOEDA = re.compile(r"R\$\s*(\d[\d.]*(?:,\d{1,2})?)(?:\s*(mil\b|mi\b|milh|bi\b|bilh))?"
                      r"|(?<![\d.,/])(\d{1,3}(?:\.\d{3})+,\d{2}|\d+,\d{2})(?![\d%,.]*\d|\s*%)")
_FRASE = re.compile(r"(?<=[.!?;])\s+(?=[A-ZÀ-Ú\[(\"“])")
_TEXTO_CORRIDO = ("objeto", "modalidade", "fundamento_legal", "resumo", "analise", "situacao")
_PERICIAS = ("pericia_contabil", "pericia_juridica")


_MESES = ("janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
          "novembro", "dezembro")
_VALOR_BR = re.compile(r"(?<![\d.,])(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}(?!\d)")
_VALOR_PONTO = re.compile(r"(?<![\d.,])\d{4,}\.\d+(?![\d.,])")                       # 12369.6 · 1357985.5399999998
_MULT = {"mil": 1e3, "mi": 1e6, "milh": 1e6, "bi": 1e9, "bilh": 1e9}
MAX_PARCELAS = 80          # parcelas = valores que a PRÓPRIA ficha cita e que conferem; acima disto não se tenta


def _float_br(s: str) -> float | None:
    try:
        return float(str(s).replace(".", "").replace(",", "."))
    except ValueError:
        return None


class _Fonte:
    """O texto do processo preparado UMA vez: normalizado, CNPJs, os dígitos de cada número e os valores em R$."""

    def __init__(self, fonte: str, fn: str | None = None, cnpjs: set[str] | None = None):
        self.bruto = fonte or ""
        self.normal = V._normal(self.bruto) if fn is None else fn
        self.cnpjs = _cnpjs_do_texto(self.bruto) if cnpjs is None else cnpjs
        self.numeros = {_dig(m) for m in re.findall(r"\d[\d.,]*", self.bruto)}
        self.compacto = re.sub(r"\s+", "", self.bruto).upper()
        self.valores = sorted({v for m in _VALOR_BR.finditer(self.bruto) if (v := _float_br(m.group(0)))}
                              | {round(float(m.group(0)), 2) for m in _VALOR_PONTO.finditer(self.bruto)})
        self.centavos = {round(v * 100) for v in self.valores}
        self.parcelas: list[int] = []
        self._contas: set[int] | None = None

    def tem_numero(self, valor: str) -> bool:
        """Mesma tolerância de `verificacao.numero_no_trecho` (centavos zerados), em tempo constante."""
        d = _dig(valor)
        if d and (d in self.numeros or d + "00" in self.numeros or (d.endswith("00") and d[:-2] in self.numeros)):
            return True
        v = _float_br(valor)              # outra grafia do MESMO valor: "12369.6", "1357985.5399999998"
        return v is not None and "," in valor and round(v * 100) in self.centavos

    def tem_arredondado(self, valor: str, sufixo: str) -> bool:
        """"R$ 9,05 milhões" vale se ALGUM valor do texto arredonda para ele na casa em que foi escrito."""
        v = _float_br(valor)
        if v is None:
            return False
        mult = _MULT[sufixo.strip().lower()]
        casas = len(valor.split(",")[1]) if "," in valor else 0
        folga = 0.5 * mult / 10 ** casas
        return any(abs(x - v * mult) <= folga for x in self.valores)

    def definir_parcelas(self, ficha: dict) -> None:
        """As parcelas de uma conta do modelo são os valores que a própria ficha cita E que estão no texto."""
        blob = json.dumps(ficha, ensure_ascii=False)
        self.parcelas = sorted({round(v * 100) for m in _VALOR_BR.finditer(blob)
                                if (v := _float_br(m.group(0))) and round(v * 100) in self.centavos})
        self._contas = None

    def tem_derivado(self, valor: str) -> bool:
        """O valor é SOMA de duas ou três parcelas, ou DIFERENÇA de duas (conta que o modelo fez e o código refaz)."""
        v = _float_br(valor) if "," in valor else _float_br(valor + ",00")
        c = self.parcelas
        if v is None or not 2 <= len(c) <= MAX_PARCELAS:
            return False
        if self._contas is None:
            pares = {a + b for i, a in enumerate(c) for b in c[i:]}
            self._contas = (pares | {b - a for i, a in enumerate(c) for b in c[i + 1:]}
                            | {ab + x for ab in pares for x in c})
        return round(v * 100) in self._contas

    def tem_data(self, data: str) -> bool:
        """dd/mm/aaaa em qualquer grafia do texto: 3/2/2025, 03.02.2025, 03-02-25, 2025-02-03, "3 de fevereiro de 2025"."""
        try:
            d, m, a = (int(x) for x in data.split("/"))
        except ValueError:
            return False
        if not (1 <= m <= 12 and 1 <= d <= 31):
            return False
        a4 = a if a > 99 else 2000 + a
        return re.search(rf"(?<!\d)0?{d}\s*[/.\-]\s*0?{m}\s*[/.\-]\s*(?:{a4}|{a4 % 100:02d})(?!\d)"
                         rf"|(?<!\d)0?{d}o?\s+de\s+{_MESES[m - 1]}\s+de\s+{a4}(?!\d)"
                         rf"|(?<!\d){a4}-{m:02d}-{d:02d}(?!\d)", self.normal) is not None


def fatos_sem_fonte(texto: str, fonte: _Fonte, conta: dict | None = None) -> list[str]:
    """Valores em R$, CNPJs, datas completas e nºs de documento do SIAFE escritos em `texto` e AUSENTES da fonte.
    Soma/diferença de dois valores do texto e arredondamento ("R$ 9,05 mi") de valor que existe NÃO são ausência."""
    t = str(texto or "")
    falta = [m.group(0) for m in _F_CNPJ.finditer(t) if _dig(m.group(0)) not in fonte.cnpjs]
    t = _F_CNPJ.sub(" ", t)
    falta += [m.group(0) for m in _F_DATA.finditer(t) if not fonte.tem_data(m.group(0))]
    t = _F_DATA.sub(" ", t)
    falta += [m.group(0) for m in _F_SIAFE.finditer(t) if m.group(0).upper() not in fonte.compacto]
    for m in _F_MOEDA.finditer(t):
        valor = (m.group(1) or m.group(3)).rstrip(".,")
        if m.group(2):
            if not (fonte.tem_arredondado(valor, m.group(2)) or fonte.tem_numero(valor)):
                falta.append(m.group(0).strip())
        elif fonte.tem_numero(valor):
            continue
        elif fonte.tem_derivado(valor):
            if conta is not None:
                conta["derivados_conferidos"] += 1
        else:
            falta.append(m.group(0).strip())
    return falta


def limpar_texto(texto, fonte: _Fonte, conta: dict) -> str:
    """Devolve o texto sem as FRASES que afirmam fato ausente da fonte. Conta frases e guarda exemplos."""
    if not isinstance(texto, str) or not texto.strip():
        return texto if isinstance(texto, str) else ""
    ficam = []
    for frase in _FRASE.split(texto.strip()):
        conta["frases"][1] += 1
        falta = fatos_sem_fonte(frase, fonte, conta)
        if falta:
            conta["fatos_sem_fonte"] += len(falta)
            conta["exemplos"] += [x[:40] for x in falta][: max(0, 6 - len(conta["exemplos"]))]
            continue
        conta["frases"][0] += 1
        ficam.append(frase)
    return " ".join(ficam)


def _conferir_narrativa(out: dict, rel: dict, fonte: _Fonte) -> None:
    conta = {"frases": [0, 0], "fatos_sem_fonte": 0, "derivados_conferidos": 0, "exemplos": [],
             "itens_descartados": 0}
    for k in _TEXTO_CORRIDO:
        if isinstance(out.get(k), str):
            out[k] = limpar_texto(out[k], fonte, conta)
    for k in _PERICIAS:
        if isinstance(out.get(k), dict):
            per = dict(out[k])
            for sub, v in per.items():
                if isinstance(v, list):
                    per[sub] = [x for x in (limpar_texto(i, fonte, conta) for i in v if isinstance(i, str)) if x]
                elif isinstance(v, str):
                    per[sub] = limpar_texto(v, fonte, conta)
            out[k] = per
    out["documentos"] = [dict(d, ponto=limpar_texto(d.get("ponto"), fonte, conta)) for d in out["documentos"]]
    # red flag e item anotado são indivisíveis: fato sem fonte fora da citação/do núcleo derruba o item inteiro
    for k in ("red_flags", "valores", "datas", "cnpjs", "partes"):
        ficam = []
        for item in out.get(k) or []:
            resto = _FLAG.sub(" ", str(item)) if k == "red_flags" else " ".join(_PARENTESE.findall(str(item)))
            falta = fatos_sem_fonte(resto, fonte, conta)
            if falta:
                conta["itens_descartados"] += 1
                conta["fatos_sem_fonte"] += len(falta)
                conta["exemplos"] += [x[:40] for x in falta][: max(0, 6 - len(conta["exemplos"]))]
                continue
            ficam.append(item)
        out[k] = ficam
        rel[k][0] = len(ficam)
    rel["narrativa"] = conta


def conferir(ficha: dict, fonte: str) -> tuple[dict, dict]:
    """(ficha só com o que se confirmou no texto, contagem do que foi descartado). Nunca corrige: descarta."""
    fn = V._normal(fonte)
    rel: dict = {}
    out = dict(ficha)

    docs_ok = [d for d in (ficha.get("documentos") or [])
               if isinstance(d, dict) and trecho_confere(d.get("trecho", ""), fn)]
    rel["documentos"] = [len(docs_ok), len(ficha.get("documentos") or [])]
    out["documentos"] = docs_ok

    flags_ok = []
    for f in ficha.get("red_flags") or []:
        m = _FLAG.match(str(f or ""))
        if m and trecho_confere(m.group("trecho"), fn):
            flags_ok.append(f)
    rel["red_flags"] = [len(flags_ok), len(ficha.get("red_flags") or [])]
    out["red_flags"] = flags_ok

    # O modelo ANOTA os itens ("R$ 988.734,64 (NL 2025NL00384)", "03/06/2025 (NF)", "B&B MED (contratada)") — o
    # piloto perdeu assim 299 de 614 valores verdadeiros. Confere-se o NÚCLEO do item (o valor, a data, o nome sem o
    # parêntese); o item segue gravado como o modelo escreveu, anotação incluída.
    cnpjs_txt = _cnpjs_do_texto(fonte)
    out["cnpjs"] = [c for c in (ficha.get("cnpjs") or []) if (m := _CNPJ.search(str(c)))
                    and _dig(m.group(0)) in cnpjs_txt]
    F = _Fonte(fonte, fn, cnpjs_txt)
    out["valores"] = [v for v in (ficha.get("valores") or []) if (m := _MOEDA.search(str(v))) and F.tem_numero(m.group(1))]
    out["datas"] = [d for d in (ficha.get("datas") or []) if (n := _nucleo_data(d))
                    and (n in fn or (_DATA.fullmatch(n) is not None and F.tem_data(n)))]
    out["partes"] = [p for p in (ficha.get("partes") or []) if len(n := V._normal(_SEM_PARENTESE.sub("", str(p)))) >= 3
                     and n in fn]
    for k in ("cnpjs", "valores", "datas", "partes"):
        rel[k] = [len(out[k]), len(ficha.get(k) or [])]

    F.definir_parcelas(ficha)
    _conferir_narrativa(out, rel, F)

    from tools.sei_depurar_db import nivel_risco_norm
    rel["nivel_risco_modelo"] = nivel_risco_norm(ficha.get("nivel_risco"))   # palpite do modelo: registro, não nota
    out["nivel_risco"] = ""
    return out, rel


# ── COLETA GRÁTIS (22/11/2026) ────────────────────────────────────────────────────────────────────────
# Pedido do dono ("mede e liga o que passar"): o Haiku pago era 80% do gasto da API (US$ 19,94 de 24,94). Bancada de
# 22/11 (~/.local/state/jfn-bancada-ficha-20261122/, 200 processos já fichados pelo Haiku, mesmo prompt/janela, régua
# por código contra o texto): NENHUM grátis sozinho iguala o Haiku por processo (flash-lite 65% × 78%); o CONSENSO
# gemini-3.5-flash-lite + particle-1:free (união, os dois sem grave, senão Haiku) achou mais itens conferidos em 51 × 21
# processos (+7,2 p.p., IC95% +3,8 a +10,7; n=103) e inventou menos (0,24 × 1,07 graves/100 itens) — fez 73% dos
# processos sem o Haiku. Números em config/modelos_regua.yaml (`bancadas_coleta.ficha_gratis`).
# Regras que valem aqui, sem exceção:
#   · grátis só COLETA: o juízo (análise, red flags, perícias, dúvidas, relevante, nível) SAI da ficha grátis — quem
#     gradua é a camada de juízo (perícia de execução, Processo 360);
#   · a ficha grátis só é gravada se NADA do que afirma com número/CNPJ/data/citação/documento for inventado
#     (`graves_coleta` vazio); um grave, JSON inválido ou silêncio → o processo vai ao Haiku, como antes;
#   · e passa pela MESMA conferência literal do Haiku (`conferir`) antes de gravar — nunca vira dado sem conferência;
#   · desliga com JFN_FICHA_GRATIS=0; Gemini só nas chaves com prova FreeTier; OpenRouter só `:free`.
GRATIS_PADRAO = "gem:gemini-3.5-flash-lite,or:particle-ai/particle-1:free"   # consenso (os dois têm de responder)
PROVA_FREE_TIER = REPO / "config" / "gemini_prova_free_tier.json"
GRATIS_TETO_S = 900          # tempo máximo do ciclo gastando com o grátis (o cron mata o ciclo aos 1.500 s)
GRATIS_MAX_TOKENS = 32_000   # o 3.5-flash-lite não raciocina; a ficha cabe com folga
JUIZO = ("analise", "nivel_risco", "red_flags", "pericia_contabil", "pericia_juridica", "duvidas", "relevante")
_SITUACAO_DECLARADA = {"arquivado": ("arquive", "arquivad", "arquivament"),
                       "concluido": ("conclus", "conclui", "concluid", "encerrad", "encerrament"),
                       "em andamento": ("em andamento",)}
_ART = re.compile(r"art(?:igo)?s?\.?\s*(\d{1,3})", re.I)
_LEI = re.compile(r"(?<![\d.])(\d{1,2}\.\d{3})(?:/\d{2,4})?(?!\d)")
_NUMERO = re.compile(r"\d[\d.,]*\d|\d")
_PALAVRA = re.compile(r"[a-z]{4,}")
_TITULO = re.compile(r"^=== DOCUMENTO: (.*?) ===$", re.M)


def cadeia_gratis() -> list[tuple[str, str]]:
    """[(provedor, modelo)] de `JFN_FICHA_GRATIS` ("0"/"off"/"" desliga). Provedores: gem (Gemini, só chave com prova
    FreeTier) e or (OpenRouter, só `:free`). O resto é recusado em silêncio — nunca vira chamada paga."""
    import os
    bruto = os.environ.get("JFN_FICHA_GRATIS", GRATIS_PADRAO).strip()
    if bruto.lower() in ("", "0", "off", "nao", "não", "false"):
        return []
    out = []
    for item in bruto.split(","):
        prov, _, modelo = item.strip().partition(":")
        if prov == "gem" and modelo.startswith("gemini-"):
            out.append((prov, modelo))
        elif prov == "or" and modelo.endswith(":free"):
            out.append((prov, modelo))
    return out


def _chaves_gemini_free() -> list[str]:
    """As chaves do pool da casa (respeita GEMINI_DISABLED) cuja PROVA de free tier está registrada: 429 com a métrica
    `…FreeTier…` (sha1[:6] da chave em `PROVA_FREE_TIER`, nunca a chave). Sem prova lida → nenhuma chave."""
    import hashlib
    from compliance_agent.direcionamento_cerebro import _gemini_keys
    try:
        kids = set(json.loads(PROVA_FREE_TIER.read_text(encoding="utf-8")).get("kids") or [])
    except (OSError, ValueError):
        return []
    return [k for k in _gemini_keys() if hashlib.sha1(k.encode()).hexdigest()[:6] in kids]


_GEMINI_ESGOTADO: dict[tuple[str, str], str] = {}     # (chave, modelo) → dia em que a cota diária acabou


def _gerar_gratis(prov: str, modelo: str):
    """Gerador (sistema, prompt) → texto ("" = não respondeu: o processo vai ao Haiku)."""
    import httpx
    if prov == "or":
        from compliance_agent.llm import free_llm as F
        if not F.openrouter_available():
            return None

        def gerar_or(sistema: str, prompt: str) -> str:
            cab, carga = F._requisicao(F.OPENROUTER_BASE, F._openrouter_key(), modelo,
                                       [{"role": "system", "content": sistema}, {"role": "user", "content": prompt}],
                                       16_000, None)                       # _requisicao força `:free`
            ini, saida, erro = time.monotonic(), "", ""
            try:
                r = httpx.post(f"{F.OPENROUTER_BASE}/chat/completions", headers=cab, json=carga, timeout=180)
                if r.status_code != 200:
                    erro = f"HTTP {r.status_code}"
                else:
                    saida = ((r.json().get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            except (httpx.HTTPError, ValueError) as exc:
                erro = type(exc).__name__
            F._trace("openrouter", bool(saida), int((time.monotonic() - ini) * 1000), erro, modelo=modelo)
            return saida
        return gerar_or

    chaves = _chaves_gemini_free()
    if not chaves:
        return None
    from compliance_agent.direcionamento_cerebro import _quota_429, _trace

    def gerar_gem(sistema: str, prompt: str) -> str:
        hoje = datetime.now().strftime("%F")
        corpo = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                 "systemInstruction": {"parts": [{"text": sistema}]},
                 "generationConfig": {"temperature": 0.1, "maxOutputTokens": GRATIS_MAX_TOKENS,
                                      "responseMimeType": "application/json"}}
        for k in chaves:
            if _GEMINI_ESGOTADO.get((k, modelo)) == hoje:
                continue
            ini = time.monotonic()
            try:
                r = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent",
                               params={"key": k}, json=corpo, timeout=180)
            except httpx.HTTPError as exc:
                _trace("gemini", False, ini, type(exc).__name__, modelo=modelo)
                continue
            _trace("gemini", r.status_code == 200, ini, "" if r.status_code == 200 else
                   f"{r.status_code} {_quota_429(r) if r.status_code == 429 else ''}".strip(), modelo=modelo)
            if r.status_code == 429:
                if "PerDay" in _quota_429(r):
                    _GEMINI_ESGOTADO[(k, modelo)] = hoje       # cota do dia: esta chave não tenta mais hoje
                continue
            if r.status_code in (500, 503, 404):
                return ""                                     # alta demanda do MODELO: as outras chaves dão o mesmo
            if r.status_code != 200:
                continue
            cand = (r.json().get("candidates") or [{}])[0]
            if cand.get("finishReason") == "MAX_TOKENS":
                return ""                                     # resposta cortada não é resposta
            return "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", [])
                           if not p.get("thought"))
        return ""
    return gerar_gem


def _nucleo_inventado(campo: str, item, F: _Fonte) -> bool:
    """O item TEM núcleo conferível (CNPJ, data completa, valor) e ele não está no texto em grafia alguma.
    Item sem núcleo conferível ("Jun/2025", parte parafraseada) é descartado pela conferência, mas não é invenção."""
    s = str(item)
    if campo == "cnpjs":
        m = re.search(r"\d[\d./\s-]{12,22}\d", s)
        return bool(m) and _dig(m.group(0)) not in F.cnpjs
    if campo == "datas":
        m = _F_DATA.search(s)
        return bool(m) and not F.tem_data(m.group(0))
    m = _NUMERO.search(s)                                     # valores
    if not m:
        return False
    tok = m.group(0).rstrip(".,")
    if F.tem_numero(tok):
        return False
    for grafia in (tok.replace(",", ""), tok.replace(".", "").replace(",", ".")):     # 12369.6 · 12.369,60
        if re.fullmatch(r"\d+(?:\.\d+)?", grafia) and round(float(grafia) * 100) in F.centavos:
            return False
    return not F.tem_derivado(tok if "," in tok else tok.replace(".", ","))


def _trecho_inventado(trecho, fn: str, F: _Fonte) -> bool:
    """Citação NÃO literal só é invenção se traz número (≥ 3 dígitos) ausente do texto ou se menos da metade das
    palavras existe nele. OCR corrigido pelo modelo ("qua- tro" → "quatro") é descartado, mas não é invenção."""
    t = str(trecho or "").strip()
    if not t or trecho_confere(t, fn):
        return False
    for n in _NUMERO.findall(t):
        d = _dig(n)
        if len(d) >= 3 and d not in F.numeros and not F.tem_numero(n.rstrip(".,")):
            return True
    pal = _PALAVRA.findall(V._normal(t))
    return bool(pal) and sum(p in fn for p in pal) / len(pal) < 0.5


def graves_coleta(ficha: dict, fonte: str) -> list[str]:
    """O que a ficha AFIRMA com número/CNPJ/data/citação/documento e o texto não tem — a régua da bancada de 22/11.
    Lista vazia = nada inventado (o descarte sem juízo segue para a conferência, como no Haiku)."""
    fn = V._normal(fonte)
    F = _Fonte(fonte, fn)
    F.definir_parcelas({k: v for k, v in ficha.items() if k not in JUIZO})
    graves = [f"{k}: {str(x)[:80]}" for k in ("valores", "cnpjs", "datas") for x in (ficha.get(k) or [])
              if x not in (None, "") and _nucleo_inventado(k, x, F)]
    titulos = [V._normal(t) for t in _TITULO.findall(fonte)]
    for d in ficha.get("documentos") or []:
        if not isinstance(d, dict):
            continue
        if _trecho_inventado(d.get("trecho"), fn, F):
            graves.append(f"documentos(trecho): {str(d.get('trecho'))[:80]}")
        ref = V._normal(str(d.get("doc_ref") or ""))
        if ref and not (len(ref) >= 4 and (ref in fn or any(ref in t or t in ref for t in titulos if len(t) >= 4))):
            graves.append(f"documentos(doc_ref): {str(d.get('doc_ref'))[:80]}")
        graves += [f"ponto: {x}" for x in fatos_sem_fonte(str(d.get("ponto") or ""), F)]
    fund = str(ficha.get("fundamento_legal") or "")
    graves += [f"fundamento_legal: {lei}" for lei in _LEI.findall(fund)
               if lei not in fn and lei.replace(".", "") not in fn]
    graves += [f"fundamento_legal: art. {a}" for a in _ART.findall(fund)
               if not re.search(rf"art(?:igo)?s?\.?\s*{a}(?!\d)", fn)]
    for k in ("objeto", "modalidade", "resumo"):
        graves += [f"{k}: {x}" for x in fatos_sem_fonte(str(ficha.get(k) or ""), F)]
    return graves


def coleta_gratis(ficha: dict, fonte: str) -> dict:
    """A ficha grátis SEM o juízo, e a situação só se o texto a DECLARA (a bancada achou o modelo grátis escrevendo
    "em andamento" em 40 de 55 processos sem nenhuma palavra disso no texto)."""
    out = dict(ficha)
    for k in JUIZO:
        out[k] = [] if k in ("red_flags", "duvidas") else (False if k == "relevante" else "")
    sit = V._normal(str(ficha.get("situacao") or ""))
    fn = V._normal(fonte)
    cat = next((c for c in _SITUACAO_DECLARADA if c in sit), "")
    out["situacao"] = cat if cat and any(p in fn for p in _SITUACAO_DECLARADA[cat]) else ""
    return out


def _chave_item(campo: str, item) -> str:
    """Forma canônica para juntar o MESMO item escrito por modelos diferentes (valor em centavos, CNPJ em dígitos…)."""
    s = str(item)
    if campo == "valores" and (m := _MOEDA.search(s)) and (v := _float_br(m.group(1))) is not None:
        return f"v{round(v * 100)}"
    if campo == "cnpjs" and (m := _CNPJ.search(s)):
        return _dig(m.group(0))
    if campo == "datas" and (m := _DATA.search(s)):
        return _nucleo_data(m.group(0))
    if campo == "documentos" and isinstance(item, dict):
        return V._normal(str(item.get("doc_ref") or ""))[:60] or V._normal(str(item.get("trecho") or ""))[:60]
    return V._normal(_SEM_PARENTESE.sub("", s))[:40]


def unir_fichas(fichas: list[dict]) -> dict:
    """CONSENSO por união: as listas de coleta juntam os itens de todos (sem repetir o mesmo item); o texto corrido é o
    do 1º modelo que o escreveu. Cada item segue passando pela conferência literal depois."""
    out = dict(fichas[0])
    for k in ("valores", "cnpjs", "datas", "partes", "documentos"):
        vistos, lista = set(), []
        for f in fichas:
            for x in f.get(k) or []:
                if x in (None, "") or (c := _chave_item(k, x)) in vistos:
                    continue
                vistos.add(c)
                lista.append(x)
        out[k] = lista
    for k in ("objeto", "modalidade", "fundamento_legal", "resumo", "situacao"):
        out[k] = next((f.get(k) for f in fichas if str(f.get(k) or "").strip()), "")
    return out


def ficha_gratis(pasta: Path, sistema: str, prompt: str, texto: str, geradores: list) -> tuple[dict, dict, str] | None:
    """(ficha conferida, verificação, modelos) do CONSENSO grátis; None → o processo vai ao Haiku.

    TODOS os modelos da cadeia têm de responder com JSON válido e SEM grave (`graves_coleta`); vale a UNIÃO dos itens
    (bancada de 22/11: a união de dois grátis achou mais itens conferidos por processo que o Haiku; um grátis sozinho,
    não). Um que falhe ou invente → o processo inteiro vai ao Haiku."""
    from compliance_agent.llm.json_resposta import parse_json_llm
    fonte = fonte_de_conferencia(pasta, texto)
    tentativas, fichas = [], []
    for modelo, gerar in geradores:
        try:
            bruto = gerar(sistema, prompt)
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:   # o Haiku faz o processo
            tentativas.append({"modelo": modelo, "motivo": f"erro {type(exc).__name__}"})
            break
        ficha = parse_json_llm(bruto) if bruto else None
        if not isinstance(ficha, dict) or ficha.get("_truncado"):
            tentativas.append({"modelo": modelo, "motivo": "sem resposta válida"})
            break
        graves = graves_coleta(ficha, fonte)
        if graves:
            tentativas.append({"modelo": modelo, "motivo": "grave", "graves": graves[:6], "n_graves": len(graves)})
            break
        tentativas.append({"modelo": modelo, "motivo": "ok"})
        fichas.append(ficha)
    if not fichas or len(fichas) < len(geradores):
        _registrar_recusas(pasta.name, tentativas)
        return None
    ok, rel = conferir(coleta_gratis(unir_fichas(fichas), fonte), fonte)
    return ok, {"conferido": rel, "juizo": "fora (coleta grátis: o juízo é da camada de juízo)",
                "consenso": [m for m, _ in geradores]}, "+".join(m for m, _ in geradores)


RECUSAS = REPO / "data" / "sei_ficha_gratis_recusas.jsonl"


def _registrar_recusas(pasta: str, tentativas: list) -> None:
    """Os graves do grátis (o processo foi ao Haiku) ficam registrados para a automelhoria (sensor `modelos`)."""
    if not any(t.get("motivo") == "grave" for t in tentativas):
        return
    linha = json.dumps({"em": datetime.now().isoformat(timespec="seconds"), "pasta": pasta,
                        "tentativas": tentativas}, ensure_ascii=False)
    linha = re.sub(r"(?<!\d)\d{3}\.?\d{3}\.?\d{3}-\d{2}(?!\d)", "CPF#mascarado", linha)    # LGPD: nunca CPF no log
    try:
        with RECUSAS.open("a", encoding="utf-8") as f:
            f.write(linha + "\n")
    except OSError as exc:
        print(f"  ⚠️  recusa do grátis não registrada ({type(exc).__name__}: {exc})", flush=True)


# ── gravação ──────────────────────────────────────────────────────────────────────────────────────────
def _garantir_coluna(con: sqlite3.Connection) -> None:
    cols = {r[1] for r in con.execute("PRAGMA table_info(sei_ficha)")}
    if "verificacao" not in cols:
        con.execute("ALTER TABLE sei_ficha ADD COLUMN verificacao TEXT")


def _escalar(v) -> str:
    if isinstance(v, list):
        return "; ".join(str(x) for x in v if x not in (None, ""))
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False)
    return "" if v is None else str(v)


def gravar(con: sqlite3.Connection, numero: str, ficha: dict, verif: dict, modelo: str) -> None:
    """INSERT só se não existir ficha (a do cache, se chegou antes, não é sobrescrita aqui)."""
    js = lambda k: json.dumps(ficha.get(k) or [], ensure_ascii=False)  # noqa: E731
    per = lambda k: json.dumps(ficha[k], ensure_ascii=False) if isinstance(ficha.get(k), dict) else ""  # noqa: E731
    con.execute(
        """INSERT OR IGNORE INTO sei_ficha
           (numero_sei,objeto,modalidade,fundamento_legal,resumo,analise,nivel_risco,situacao,relevante,
            valores,cnpjs,partes,datas,red_flags,documentos,pericia_contabil,pericia_juridica,
            n_docs,fonte_modelo,cached_at,atualizado_em,verificacao)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),?)""",
        (numero, *(_escalar(ficha.get(c)) for c in ("objeto", "modalidade", "fundamento_legal", "resumo", "analise")),
         ficha.get("nivel_risco") or "", _escalar(ficha.get("situacao")), 1 if ficha.get("relevante") else 0,
         js("valores"), js("cnpjs"), js("partes"), js("datas"), js("red_flags"), js("documentos"),
         per("pericia_contabil"), per("pericia_juridica"), len(ficha.get("documentos") or []), modelo,
         datetime.now().isoformat(timespec="seconds"), json.dumps(verif, ensure_ascii=False)))


# ── ciclo: colher o que terminou, enviar o próximo lote ───────────────────────────────────────────────
def _con() -> sqlite3.Connection:
    con = sqlite3.connect(DB, timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    return con


def regravar_lote(lote_id: str) -> dict:
    """Refaz a CONFERÊNCIA de um lote já colhido (resultado guardado em data/claude_api_lotes/, sem nova chamada nem
    custo) — para quando a régua de conferência muda. Só substitui ficha que É do acervo; a do cache fica."""
    from compliance_agent.llm.json_resposta import parse_json_llm
    saida = json.loads((REPO / "data" / "claude_api_lotes" / f"{lote_id}.json").read_text(encoding="utf-8"))
    from compliance_agent.llm import claude_api as C
    modelo = f"{C.MODELO_BARATO}{C.SUFIXO_API}-lote#{VERSAO}"
    tot = {"regravadas": 0, "invalidas": 0}
    con = _con()
    try:
        _garantir_coluna(con)
        for pasta, bruto in saida.items():
            ficha = parse_json_llm(bruto) if bruto else None
            if not isinstance(ficha, dict) or ficha.get("_truncado"):
                tot["invalidas"] += 1
                continue
            numero = numero_da_pasta(pasta)
            con.execute("DELETE FROM sei_ficha WHERE numero_sei=? AND fonte_modelo LIKE '%#acervo-%'", (numero,))
            texto, cob = texto_para_ficha(ACERVO / pasta)
            ficha_ok, rel = conferir(ficha, fonte_de_conferencia(ACERVO / pasta, texto))
            gravar(con, numero, ficha_ok, {"versao": VERSAO, "cobertura": cob, "conferido": rel, "lote": lote_id},
                   modelo)
            tot["regravadas"] += 1
        con.commit()
    finally:
        con.close()
    return tot


def colher(estado: dict) -> dict:
    from compliance_agent.llm import claude_api as C
    from compliance_agent.llm.json_resposta import parse_json_llm
    modelo = f"{C.MODELO_BARATO}{C.SUFIXO_API}-lote#{VERSAO}"
    tot = {"lotes": 0, "gravadas": 0, "invalidas": 0}
    for lote_id, ids in list(estado.get("lotes", {}).items()):
        res = C.colher_lote(lote_id)
        if res is None:
            continue                                     # em curso
        con = _con()
        try:
            _garantir_coluna(con)
            for pasta in ids:
                bruto = res.get(pasta)
                ficha = parse_json_llm(bruto) if bruto else None
                if not isinstance(ficha, dict) or ficha.get("_truncado"):
                    estado["tentativas"][pasta] = estado.get("tentativas", {}).get(pasta, 0) + 1
                    tot["invalidas"] += 1
                    continue
                texto, cob = texto_para_ficha(ACERVO / pasta)
                ficha_ok, rel = conferir(ficha, fonte_de_conferencia(ACERVO / pasta, texto))
                gravar(con, numero_da_pasta(pasta), ficha_ok, {"versao": VERSAO, "cobertura": cob, "conferido": rel,
                                                               "lote": lote_id}, modelo)
                tot["gravadas"] += 1
                if tot["gravadas"] % 20 == 0:
                    con.commit()      # trava de escrita curta: o lex_execucao espera só 30 s pelo banco
            con.commit()
        finally:
            con.close()
        estado["lotes"].pop(lote_id, None)
        tot["lotes"] += 1
        _gravar_estado(estado)
    return tot


def enviar(estado: dict, n: int) -> dict:
    from compliance_agent.llm import claude_api as C
    con = _con()
    try:
        cands = fila(con, estado)
    finally:
        con.close()
    C.registrar_restantes(TAREFA, len(cands))
    # coleta grátis primeiro (22/11/2026); o que ela não fechar sem grave vai ao Haiku neste mesmo ciclo
    geradores = [(m, g) for prov, m in cadeia_gratis() if (g := _gerar_gratis(prov, m)) is not None]
    gratis = {"gravadas": 0, "ao_haiku": 0, "modelos": [m for m, _ in geradores]}
    t0 = time.monotonic()
    itens, sistema = [], ""
    for c in cands[:n]:
        texto, cob = texto_para_ficha(ACERVO / c["pasta"])
        if len(texto) < MIN_TEXTO:
            continue
        sistema, prompt = sistema_e_prompt(texto)
        if geradores and time.monotonic() - t0 < GRATIS_TETO_S:
            res = ficha_gratis(ACERVO / c["pasta"], sistema, prompt, texto, geradores)
            if res is not None:
                ficha_ok, verif, modelo = res
                con = _con()
                try:
                    _garantir_coluna(con)
                    gravar(con, numero_da_pasta(c["pasta"]), ficha_ok,
                           {"versao": VERSAO, "cobertura": cob, **verif}, f"{modelo}@gratis#{VERSAO}-coleta")
                    con.commit()
                finally:
                    con.close()
                gratis["gravadas"] += 1
                continue
            gratis["ao_haiku"] += 1
        itens.append((c["pasta"], prompt))
    if not itens:
        return {"enviados": 0, "fila": len(cands), "gratis": gratis}
    lote = C.enviar_lote(TAREFA, itens, sistema=sistema, max_tokens=MAX_TOKENS, effort="low")
    if not lote:
        return {"enviados": 0, "fila": len(cands), "motivo": C.ultimo_motivo, "gratis": gratis}
    estado.setdefault("lotes", {})[lote] = [cid for cid, _ in itens]
    _gravar_estado(estado)
    return {"enviados": len(itens), "fila": len(cands), "lote": lote,
            "pago_no_lote": round(sum(c["pago"] for c in cands[:n]), 2), "gratis": gratis}


def main() -> int:
    ap = argparse.ArgumentParser(description="Ficha SEI a partir do acervo, em lote pela API (Haiku)")
    ap.add_argument("--ciclo", action="store_true", help="colhe lotes terminados e envia o próximo")
    ap.add_argument("--lote", type=int, default=400, help="processos por lote")
    ap.add_argument("--max-em-curso", type=int, default=2, help="lotes simultâneos no máximo")
    ap.add_argument("--estado", action="store_true")
    ap.add_argument("--regravar", metavar="LOTE_ID", help="refaz a conferência de um lote já colhido (sem custo)")
    a = ap.parse_args()
    if a.regravar:
        print(json.dumps(regravar_lote(a.regravar), ensure_ascii=False))
        return 0
    estado = _ler_estado()
    estado.setdefault("lotes", {})
    estado.setdefault("tentativas", {})
    if a.estado or not a.ciclo:
        con = _con()
        try:
            n = len(fila(con, estado))
        finally:
            con.close()
        print(json.dumps({"fila": n, "lotes_em_curso": {k: len(v) for k, v in estado["lotes"].items()},
                          "esgotados": sorted(k for k, v in estado["tentativas"].items() if v >= MAX_TENTATIVAS)},
                         ensure_ascii=False))
        return 0
    t0 = time.monotonic()
    r = {"colheita": colher(estado)}
    if len(estado["lotes"]) < a.max_em_curso:
        r["envio"] = enviar(estado, a.lote)
    r["s"] = round(time.monotonic() - t0, 1)
    print(f"[{datetime.now():%F %T}] sei_ficha_acervo {json.dumps(r, ensure_ascii=False)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
