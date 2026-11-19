# -*- coding: utf-8 -*-
"""Base comum da família ADITIVOS E EXECUÇÃO CONTRATUAL (docs/PADROES-DE-IRREGULARIDADE.md).

Uma porta só para o que os oito detectores da família leem — e para as armadilhas já medidas:

  • UNIVERSO = união de `data/sei_arquivo/<tag>` e `data/sei_cache/integra_<tag>`. Processo com árvore acima de
    1.000 documentos usa o `sei_cache`: até o commit 80770d09 (18/11/2026) o arquivador lia `1000.pdf` como o
    documento 100 e o manifesto do arquivo desses processos tem índice errado.
  • Documento cujo `contexto` (manifesto da íntegra) cita OUTRO processo é ALHEIO e não prova nada sobre este
    (`sei/documentos_alheios`, memória pasta-sei-com-documentos-alheios). Sem número no contexto, o documento fica.
  • Texto sempre SEM a etiqueta do acervo (`sei/acervo_texto`): o rótulo nosso não pode provar a fonte.
  • PAGO = OB do SIAFE com `_ob_paga` (Contabilizada, não devolvida, com número). A soma por processo é PISO:
    o campo `processo` da OB tem grafias variantes (normalizadas aqui: 'SEI-210108/000153/23' = '…/2023') e há
    OB sem processo; a soma canônica por NL está sendo refeita por outra frente (ob_processo.py).
  • Teto do acréscimo: `limites_aditivo` (fonte única). Nenhum percentual legal é escrito aqui.
"""
from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from compliance_agent.sei import acervo_texto
from compliance_agent.sei.documentos_alheios import numero_do_contexto

RAIZ = Path(__file__).resolve().parents[2]
ARQUIVO = RAIZ / "data" / "sei_arquivo"
CACHE = RAIZ / "data" / "sei_cache"
DB = RAIZ / "data" / "compliance.db"
LIMIAR_ARVORE_GRANDE = 1000

_RE_PROC = re.compile(r"(\d{5,6})\s*[/.]\s*(\d{5,6})\s*[/.]\s*(\d{4}|\d{2})\b")


# ── processo ────────────────────────────────────────────────────────────────────────────────────
def chave_processo(s: str | None) -> str | None:
    """'SEI-210108/000153/23' → '210108/000153/2023'. None se não houver número de processo SEI-RJ."""
    m = _RE_PROC.search(str(s or ""))
    if not m:
        return None
    ano = m.group(3)
    if len(ano) == 2:
        ano = "20" + ano
    return f"{int(m.group(1)):06d}/{int(m.group(2)):06d}/{ano}"


def tag_de(chave: str) -> str:
    return chave.replace("/", "_")


def chave_de_tag(tag: str) -> str:
    return tag.replace("_", "/")


def processos() -> list[str]:
    """Tags do universo (arquivo ∪ cache de íntegra)."""
    tags = set()
    if ARQUIVO.is_dir():
        tags |= {p.name for p in ARQUIVO.iterdir() if re.fullmatch(r"\d{6}_\d{6}_\d{4}", p.name)}
    if CACHE.is_dir():
        tags |= {p.name[len("integra_"):] for p in CACHE.glob("integra_*")
                 if re.fullmatch(r"integra_\d{6}_\d{6}_\d{4}", p.name)}
    return sorted(tags)


def _ler_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _texto_cache(pasta: Path, arquivo: str) -> Path | None:
    stem = Path(arquivo or "").stem
    if not stem:
        return None
    for suf, minimo in ((".txt", 200), (".ocr_gpu.txt", 1), (".ocr.txt", 1), (".txt", 1)):
        p = pasta / f"{stem}{suf}"
        try:
            if p.exists() and p.stat().st_size >= minimo:
                return p
        except OSError:
            continue
    return None


def documentos(tag: str) -> tuple[list[dict], str]:
    """(docs, fonte). Cada doc: {i, titulo, tipo, fonte, caminho, alheio}. `caminho` None = sem texto em disco."""
    pa, pc = ARQUIVO / tag, CACHE / f"integra_{tag}"
    ma = _ler_json(pa / "manifest.json") if (pa / "manifest.json").exists() else None
    mc = _ler_json(pc / "manifest.json") if (pc / "manifest.json").exists() else None
    # manifesto antigo do cache é uma LISTA de documentos (sem total_arvore)
    if isinstance(mc, list):
        mc = {"docs": mc, "total_arvore": len(mc)}
    if isinstance(ma, list):
        ma = {"docs": ma, "total_arvore": len(ma)}
    if ma is not None and not isinstance(ma, dict):
        ma = None
    if mc is not None and not isinstance(mc, dict):
        mc = None
    total_a = int((ma or {}).get("total_arvore") or 0)
    total_c = int((mc or {}).get("total_arvore") or 0)
    usar_cache = mc is not None and (ma is None or max(total_a, total_c) > LIMIAR_ARVORE_GRANDE)
    alvo = chave_de_tag(tag)
    out: list[dict] = []
    if usar_cache:
        # O texto do arquivo continua valendo quando o TÍTULO (que traz o nº SEI do documento) é o mesmo — exceto
        # nos índices 100–199, que o bug do arquivador (1000.pdf → 100) pode ter trocado. Medido 18/11/2026: o cache
        # do doc 873 da Seleta é OCR parcial (60 mil caracteres, sem a cláusula de absorção); o arquivo tem o
        # nativo (167 mil). Fica o texto mais longo dos dois.
        do_arquivo = {}
        for d in (ma or {}).get("docs") or []:
            if isinstance(d, dict) and d.get("texto") and not (100 <= int(d.get("i") or 0) < 200):
                do_arquivo.setdefault(str(d.get("titulo") or ""), pa / d["texto"])
        for d in mc.get("docs") or []:
            if not isinstance(d, dict):
                continue
            num = numero_do_contexto(d.get("contexto"))
            tit = str(d.get("titulo") or "")
            caminhos = [c for c in (_texto_cache(pc, str(d.get("arquivo") or "")), do_arquivo.get(tit)) if c]
            out.append({"i": d.get("i"), "titulo": tit, "tipo": "", "fonte": "sei_cache",
                        "caminho": caminhos[0] if caminhos else None, "caminhos": caminhos,
                        "alheio": bool(num and num != alvo)})
        return out, "sei_cache"
    if ma is None:
        return [], "sem_manifesto"
    do_cache = {}
    for d in (mc or {}).get("docs") or []:
        if isinstance(d, dict):
            do_cache.setdefault(str(d.get("titulo") or ""), (d, _texto_cache(pc, str(d.get("arquivo") or ""))))
    for d in ma.get("docs") or []:
        if not isinstance(d, dict):
            continue
        rel = d.get("texto")
        tit = str(d.get("titulo") or "")
        dc, pcache = do_cache.get(tit, (None, None))
        num = numero_do_contexto((dc or {}).get("contexto"))
        caminhos = [c for c in ((pa / rel) if rel else None, pcache) if c]
        out.append({"i": d.get("i"), "titulo": tit, "tipo": str(d.get("tipo") or ""), "fonte": "sei_arquivo",
                    "caminho": caminhos[0] if caminhos else None, "caminhos": caminhos,
                    "alheio": bool(num and num != alvo)})
    return out, "sei_arquivo"


def ler(doc: dict, teto: int | None = None) -> str:
    """Texto do documento sem etiqueta (o mais longo dos caminhos conhecidos). "" = INDISPONÍVEL, nunca 'sem achado'."""
    melhor = ""
    for p in doc.get("caminhos") or ([doc["caminho"]] if doc.get("caminho") else []):
        try:
            t = Path(p).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        t = acervo_texto.sem_etiqueta(t, doc.get("titulo") or "")
        if len(t.strip()) > len(melhor.strip()):
            melhor = t
    return melhor if teto is None else melhor[:teto]


# ── títulos ─────────────────────────────────────────────────────────────────────────────────────
def sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))


_RE_TIT_ADITIVO = re.compile(r"termo\s+(?:de\s+)?aditivo|\baditivo\b|aditamento|rerratifica|re-ratifica|"
                             r"termo\s+de\s+retifica", re.I)
_RE_TIT_NAO_TERMO = re.compile(r"minuta|rascunho|proposta|solicita|parecer|despacho|of[íi]cio|memorando|"
                               r"nota\s+t[ée]cnica|check-?list|lista\s+de\s+verifica|e-?mail|requerimento|"
                               r"justificativa|pesquisa|publica[çc][ãa]o|extrato|an[áa]lise|informa[çc][ãa]o", re.I)


def eh_termo_aditivo(doc: dict) -> bool:
    """O documento É o termo (não minuta, parecer, ofício sobre ele, nem extrato do DOERJ)."""
    t = doc.get("titulo") or ""
    if _RE_TIT_NAO_TERMO.search(t):
        return False
    return bool(_RE_TIT_ADITIVO.search(t)) or doc.get("tipo") == "aditivo"


# ── números ─────────────────────────────────────────────────────────────────────────────────────
_RE_VALOR = re.compile(r"R\$\s*([\d.]{1,15},\d{2})")


def num_br(s: str) -> float | None:
    try:
        return float(str(s).replace(".", "").replace(",", "."))
    except ValueError:
        return None


def pct_br(s: str) -> float | None:
    return num_br(str(s).replace("%", "").strip())


def trecho(texto: str, ini: int, fim: int, folga: int = 120) -> str:
    """Trecho literal (uma linha) em volta de [ini, fim), sem quebra — para a prova."""
    a, b = max(0, ini - folga), min(len(texto), fim + folga)
    return re.sub(r"\s+", " ", texto[a:b]).strip()


# ── SIAFE: OB paga ──────────────────────────────────────────────────────────────────────────────
def _con():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=60)


@lru_cache(maxsize=1)
def ob_por_processo() -> dict[str, dict]:
    """chave → {valor, n, credor, nome_credor, ug}. Valor = PISO (grafias variantes normalizadas; OB sem processo
    fica de fora). Só OB paga (`_ob_paga`)."""
    from compliance_agent.cruzamentos_intel import _ob_paga
    out: dict[str, dict] = {}
    try:
        con = _con()
        try:
            sql = (f"SELECT processo, credor, nome_credor, ug_emitente, SUM(valor), COUNT(*) FROM ob_orcamentaria_siafe "
                   f"WHERE {_ob_paga(con)} AND processo LIKE '%/%/%' GROUP BY 1, 2, 3, 4")
            for proc, cred, nome, ug, v, n in con.execute(sql):
                k = chave_processo(proc)
                if not k:
                    continue
                r = out.setdefault(k, {"valor": 0.0, "n": 0, "por_credor": {}, "ug": ug})
                r["valor"] += float(v or 0)
                r["n"] += int(n or 0)
                pc = r["por_credor"].setdefault(str(cred or ""), [str(nome or ""), 0.0])
                pc[1] += float(v or 0)
        finally:
            con.close()
    except sqlite3.Error:
        return {}
    for r in out.values():
        cred, (nome, _) = max(r["por_credor"].items(), key=lambda kv: kv[1][1])
        r["credor"], r["nome_credor"] = cred, nome
        r["valor"] = round(r["valor"], 2)
        del r["por_credor"]
    return out


def pago(chave: str) -> float | None:
    """Valor pago (OB, piso) ou None = INDISPONÍVEL (nenhuma OB com este processo no SIAFE)."""
    r = ob_por_processo().get(chave)
    return r["valor"] if r else None


def ob_mensal(chave: str) -> dict[str, float]:
    """'AAAA-MM' (data de EMISSÃO da OB) → soma paga. Para comparar faturamento antes × depois de um termo."""
    from compliance_agent.cruzamentos_intel import _ob_paga
    a, b, ano = chave.split("/")
    variantes = [f"%{a}/{b}/{ano}%", f"%{a}/{b}/{ano[2:]}"]
    out: dict[str, float] = {}
    try:
        con = _con()
        try:
            for var in variantes:
                for data, v in con.execute(f"SELECT data_emissao, valor FROM ob_orcamentaria_siafe WHERE "
                                           f"{_ob_paga(con)} AND processo LIKE ?", (var,)):
                    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", str(data or ""))
                    if m:
                        k = f"{m.group(3)}-{m.group(2)}"
                        out[k] = out.get(k, 0.0) + float(v or 0)
        finally:
            con.close()
    except sqlite3.Error:
        return {}
    return out


@lru_cache(maxsize=1)
def _nomes_ug() -> dict[str, str]:
    d = _ler_json(RAIZ / "data" / "ug_index_siafe.json") or {}
    return d.get("ugs") or {}


def info_credor(chave: str) -> dict:
    """Credor (maior soma de OB do processo) e órgão pela UG emitente da OB — INDISPONÍVEL sem OB."""
    r = ob_por_processo().get(chave) or {}
    ug = r.get("ug")
    return {"credor": r.get("nome_credor"), "ug": ug, "orgao": _nomes_ug().get(str(ug or ""), None)}


# ── saída ───────────────────────────────────────────────────────────────────────────────────────
def achado(chave: str, grau: str, prova: str, porque: str, fonte: str, **extra) -> dict:
    a = {"processo": f"SEI-{chave}", "grau": grau, "prova": prova, "valor_pago_ob": pago(chave),
         "valor_pago_ob_estado": "PISO" if pago(chave) is not None else "INDISPONÍVEL",
         "porque": porque, "fonte": fonte, **info_credor(chave)}
    a.update(extra)
    return a


def resultado(id_: str, universo: int, cobertura: dict, achados: list[dict], funil: dict | None = None) -> dict:
    ordem = {"forte": 0, "medio": 1, "fraco": 2}
    achados.sort(key=lambda a: (ordem.get(a.get("grau"), 9), -(a.get("valor_pago_ob") or 0)))
    return {"id": id_, "gerado_em": datetime.now().isoformat(timespec="seconds"), "universo": universo,
            "cobertura": cobertura, "funil": funil or {}, "achados": achados}


def iterar(limite: int | None = None, tags: list[str] | None = None):
    """(tag, docs, fonte) de cada processo do universo — lendo os manifestos (lento: 10 mil arquivos)."""
    lista = tags if tags is not None else processos()
    for n, tag in enumerate(lista):
        if limite and n >= limite:
            break
        docs, fonte = documentos(tag)
        yield tag, docs, fonte


# ── índice da família (um passe nos manifestos serve aos oito detectores) ──────────────────────
INDICE = RAIZ / "data" / "padroes" / "_familia_aditivos_indice.json"
INDICE_VALIDADE_H = 12
# Documentos que algum detector da família lê. O resto do processo (pareceres, ofícios, despachos…) só entra
# pela contagem — exceto no detector de "sem prévio empenho", que procura a frase em qualquer documento.
_RE_TIT_FAMILIA = re.compile(
    r"aditivo|aditamento|apostil|retifica|medi[çc][ãa]o|boletim|planilha|di[áa]rio|nota\s+fiscal|\bNF|"
    r"fatura|empenho|\bNE\b|liquida|\bNL\b|contrato|atestad|atesto|relat[óo]rio|justificativa|"
    r"reconhecimento\s+de\s+d[íi]vida|termo\s+de\s+refer", re.I)


def _doc_leve(d: dict) -> dict:
    return {"i": d.get("i"), "titulo": d.get("titulo"), "tipo": d.get("tipo"), "fonte": d.get("fonte"),
            "caminho": str(d["caminho"]) if d.get("caminho") else None,
            "caminhos": [str(c) for c in d.get("caminhos") or ([d["caminho"]] if d.get("caminho") else [])],
            "alheio": d.get("alheio")}


def indice(reconstruir: bool = False, limite: int | None = None) -> dict:
    """{"gerado_em", "processos": {tag: {"fonte", "n_docs", "n_sem_texto", "docs": [doc leve…]}}}."""
    if not reconstruir and not limite and INDICE.exists():
        idade_h = (datetime.now().timestamp() - INDICE.stat().st_mtime) / 3600
        if idade_h < INDICE_VALIDADE_H:
            dado = _ler_json(INDICE)
            if dado:
                return dado
    procs: dict[str, dict] = {}
    for tag, docs, fonte in iterar(limite):
        procs[tag] = {"fonte": fonte, "n_docs": len(docs),
                      "n_sem_texto": sum(1 for d in docs if not d.get("caminho")),
                      "docs": [_doc_leve(d) for d in docs if _RE_TIT_FAMILIA.search(d.get("titulo") or "")
                               or d.get("tipo") in ("aditivo", "medicao", "nota_fiscal", "empenho", "liquidacao")]}
    dado = {"gerado_em": datetime.now().isoformat(timespec="seconds"), "processos": procs}
    if not limite:
        INDICE.parent.mkdir(parents=True, exist_ok=True)
        tmp = INDICE.with_suffix(".tmp")
        tmp.write_text(json.dumps(dado, ensure_ascii=False), encoding="utf-8")
        tmp.replace(INDICE)
    return dado


def ler_leve(doc: dict, teto: int | None = None) -> str:
    """`ler` para o doc do índice (caminhos em string)."""
    return ler(doc, teto)


# ── leitura do TERMO: percentuais declarados, valor, data, contrato ──────────────────────────────
# Marca de página do Diário Oficial/extrato. Medido 18/11/2026: o termo da Hydra (SEI-070002/026015/2024, doc 264)
# traz a página do DOERJ com o extrato do 1º TA do Contrato 20/2024 do PRODERJ — "PARÁGRAFO PRIMEIRO ... acréscimo
# ... 25%" dentro do extrato. Só CLÁUSULA (não parágrafo) devolve o trecho ao corpo de um termo.
_RE_DOERJ = re.compile(r"DI[ÁA]RIO\s+OFICIAL|D\.?O\.?E\.?R\.?J|IMPRENSA\s+OFICIAL|\bEXTRATO\b|"
                       r"^\s*Id:\s*\d{6,}|INSTRUMENTO\s*:|P\s?A\s?R\s?T\s?E\s?S\s*:|V\s?A\s?L\s?O\s?R\s*:", re.I | re.M)
_RE_CLAUSULA = re.compile(r"CL[ÁA]USULA", re.I)


def no_corpo(texto: str, pos: int) -> bool:
    """O trecho está no corpo de um termo, não num extrato do Diário Oficial colado na mesma peça (ato vizinho):
    entre a última marca de DOERJ/extrato antes dele e ele, há cláusula/parágrafo de termo."""
    antes = texto[max(0, pos - 2500):pos]
    ult = max((m.end() for m in _RE_DOERJ.finditer(antes)), default=-1)
    return ult < 0 or bool(_RE_CLAUSULA.search(antes[ult:]))


_N = r"(\d{1,3}(?:,\d{1,4})?)\s*%"
# entre a palavra e o percentual cabe valor em R$ (ponto de milhar não encerra a frase) — Brasform TA 42/2024:
# "acréscimo do objeto contratual de itens acrescidos no valor de R$ 3.526.040,20 (...) corresponde ao percentual de 19,96%"
def _sem_fim(n: int) -> str:
    return r"(?:[^.;%]|\.(?=\d)){0," + str(n) + "}?"


RE_PCT_ACRESCIMO = re.compile(r"acr[ée]scimo(?!\s+de\s+valor)" + _sem_fim(400) + r"percentual\s+de\s+" + _N, re.I)
RE_PCT_SUPRESSAO = re.compile(r"supress[ãa]o" + _sem_fim(200) + r"percentual\s+de\s+" + _N, re.I)
RE_VALOR_TERMO = re.compile(r"(?:d[áa]-se\s+ao\s+(?:presente\s+)?termo\s+aditivo\s+o\s+valor(?:\s+total)?\s+de|"
                            r"pagar\s+a\s+quantia\s+total\s+de)\s*R\$\s*([\d.]{1,15},\d{2})", re.I)
RE_VALOR_TOTAL = re.compile(r"(?:totalizando\s+o\s+(?:contrato|valor\s+(?:global|total)\s+do\s+contrato)\s+"
                            r"(?:o\s+valor\s+)?(?:de\s+)?|passa(?:ndo)?\s+(?:o\s+contrato\s+)?a\s+(?:ter\s+o\s+valor\s+"
                            r"(?:global|total)\s+de|ser\s+de))\s*R\$\s*([\d.]{1,15},\d{2})", re.I)
RE_CONTRATO_NO = re.compile(r"contrato\s*(?:n[º°o.]*\s*)?(\d{1,4}\s*/\s*\d{2,4})", re.I)
_RE_DATA_ASS = re.compile(r"assinado\s+eletronicamente\s+por[^\n]{0,200}?\bem\s+(\d{2}/\d{2}/\d{4})|"
                          r"DATA\s+D[AE]\s+ASSINATURA\s*:?\s*(" + r"\d{2}/\d{2}/\d{4}|\d{1,2}\s+de\s+[a-zç]+\s+de\s+\d{4}" + r")",
                          re.I)


def norm_contrato(s: str) -> str:
    a, b = re.sub(r"\s", "", s).split("/")
    b = ("20" + b) if len(b) == 2 else b
    return f"{int(a)}/{b}"


_MES_EXT = {"janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
            "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12}
DATA_PADRAO = r"\d{2}/\d{2}/\d{4}|\d{1,2}\s+de\s+[a-zç]+\s+de\s+\d{4}"


def data_br(s: str) -> str | None:
    """'24/01/2024' ou '24 de janeiro de 2024' → '2024-01-24'."""
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", s or "")
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    m = re.match(r"(\d{1,2})\s+de\s+([a-zç]+)\s+de\s+(\d{4})", sem_acento((s or "").lower()))
    if m and m.group(2) in _MES_EXT:
        return f"{m.group(3)}-{_MES_EXT[m.group(2)]:02d}-{int(m.group(1)):02d}"
    return None


def data_assinatura_apos(texto: str, pos: int, alcance: int = 20000) -> str | None:
    m = _RE_DATA_ASS.search(texto, pos, pos + alcance)
    return data_br(m.group(1) or m.group(2)) if m else None


_RE_CONTRATO_ADITADO = re.compile(r"(?:aditivo\s+(?:ao|do)|quantitativa\s+do|altera[çc][ãa]o\s+\w+\s+do|aditado\s*[:,]?\s*)"
                                  r"\s*contrato\s*(?:n[º°o.]*\s*)?(\d{1,4}\s*/\s*\d{2,4})", re.I)


def contrato_antes(texto: str, pos: int, alcance: int = 3000) -> str | None:
    """Contrato ADITADO pelo termo que contém `pos` ("Termo Aditivo ao Contrato nº X"); sem essa redação, o último
    contrato citado antes (pode ser o absorvido — por isso a redação de aditamento tem preferência)."""
    ms = list(_RE_CONTRATO_ADITADO.finditer(texto, max(0, pos - alcance), pos))
    if ms:
        return norm_contrato(ms[-1].group(1))
    ms = list(RE_CONTRATO_NO.finditer(texto, max(0, pos - alcance), pos))
    return norm_contrato(ms[-1].group(1)) if ms else None


_RE_RODAPE = re.compile(r"^[^\n]{0,120}SEI\s+SEI-\d{6}/\d{6}/\d{4}\s*/\s*pg\.\s*\d+[ \t]*$", re.M)


def sem_rodape(texto: str) -> str:
    """Tira o rodapé de página do SEI ("Termo Aditivo 79635048  SEI SEI-070002/008302/2022 / pg. 1"), que cai no meio
    da frase e a corta (o ponto de "pg." encerrava a janela)."""
    return _RE_RODAPE.sub("", texto or "")


def declaracoes_de_acrescimo(texto: str) -> list[dict]:
    """Cada termo do texto que DECLARA acréscimo: {pct, pct_supressao, valor_termo, valor_total, data, contrato, trecho,
    pos}. Só no corpo (não extrato do DOERJ). Termo compilado (1º ao 5º TA numa peça) devolve um item por termo."""
    texto = sem_rodape(texto)
    out = []
    for m in RE_PCT_ACRESCIMO.finditer(texto):
        if not no_corpo(texto, m.start()):
            continue
        pct = pct_br(m.group(1))
        if pct is None or pct <= 0 or pct > 100:
            continue
        depois = texto[m.end(): m.end() + 2500]
        ms = RE_PCT_SUPRESSAO.search(texto, m.start(), m.end() + 300)
        mv = RE_VALOR_TERMO.search(depois)
        mt = RE_VALOR_TOTAL.search(depois)
        out.append({"pct": pct, "pct_supressao": pct_br(ms.group(1)) if ms else None,
                    "valor_termo": num_br(mv.group(1)) if mv else None,
                    "valor_total": num_br(mt.group(1)) if mt else None,
                    "data": data_assinatura_apos(texto, m.end()), "contrato": contrato_antes(texto, m.start()),
                    "trecho": trecho(texto, m.start(), m.end(), 100), "pos": m.start()})
    return out


def termos_do_processo(p: dict) -> tuple[list[tuple[dict, str]], dict]:
    """[(doc, texto)] dos termos aditivos próprios com texto + contagem do que ficou de fora."""
    fora = {"alheios": 0, "sem_texto": 0}
    out = []
    for d in p["docs"]:
        if not eh_termo_aditivo(d):
            continue
        if d.get("alheio"):
            fora["alheios"] += 1
            continue
        t = ler(d)
        if not t.strip():
            fora["sem_texto"] += 1
            continue
        out.append((d, t))
    return out, fora


def declaracoes_do_processo(termos: list[tuple[dict, str]]) -> dict[str, list[dict]]:
    """contrato → declarações de acréscimo DISTINTAS (o mesmo termo aparece em várias peças: compilação, cópia
    juntada no pagamento). Chave de unicidade: (pct, data) — ou (pct, valor_termo) sem data."""
    por: dict[str, dict[tuple, dict]] = {}
    for d, t in termos:
        for x in declaracoes_de_acrescimo(t):
            k = (x["pct"], x["data"] or x["valor_termo"])
            grupo = por.setdefault(x["contrato"] or "?", {})
            if k not in grupo:
                grupo[k] = {**x, "doc": d["i"], "titulo": d["titulo"], "fonte": d["fonte"]}
    return {c: sorted(g.values(), key=lambda x: (x["data"] or "9999", x["doc"])) for c, g in por.items()}


def contrato_principal(decl: dict[str, list[dict]]) -> str | None:
    if not decl:
        return None
    return max(decl, key=lambda c: (c != "?", len(decl[c])))


# ── número por extenso ─────────────────────────────────────────────────────────────────────────
_UNID = {"zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6,
         "sete": 7, "oito": 8, "nove": 9, "dez": 10, "onze": 11, "doze": 12, "treze": 13, "quatorze": 14,
         "catorze": 14, "quinze": 15, "dezesseis": 16, "dezessete": 17, "dezoito": 18, "dezenove": 19,
         "vinte": 20, "trinta": 30, "quarenta": 40, "cinquenta": 50, "sessenta": 60, "setenta": 70,
         "oitenta": 80, "noventa": 90, "cem": 100, "cento": 100, "duzentos": 200, "duzentas": 200,
         "trezentos": 300, "trezentas": 300, "quatrocentos": 400, "quatrocentas": 400, "quinhentos": 500,
         "quinhentas": 500, "seiscentos": 600, "seiscentas": 600, "setecentos": 700, "setecentas": 700,
         "oitocentos": 800, "oitocentas": 800, "novecentos": 900, "novecentas": 900}
_ESCALA = {"mil": 10**3, "milhao": 10**6, "milhoes": 10**6, "bilhao": 10**9, "bilhoes": 10**9}
_NEUTRAS = {"e", "de"}


def _inteiro_extenso(s: str) -> int | None:
    """Inteiro por extenso, só se BEM FORMADO: escalas em ordem decrescente e nenhuma conjunção solta antes de
    escala. Medido 18/11/2026 (Brasform): "vinte e milhões" e "dezesseis mil duzentos e trinta e nove mil reais" são
    erros de redação do extenso, não outro valor — devolver número deles fabricaria divergência."""
    toks = re.findall(r"[a-z]+", sem_acento(s.lower()))
    if not toks:
        return None
    total = grupo = 0
    visto = False
    ultima_escala = None
    anterior = ""
    for t in toks:
        if t in _NEUTRAS:
            anterior = t
            continue
        if t in _UNID:
            grupo += _UNID[t]
            visto = True
        elif t in _ESCALA:
            if anterior == "e" or (ultima_escala is not None and _ESCALA[t] >= ultima_escala):
                return None
            total += (grupo or 1) * _ESCALA[t]
            grupo = 0
            ultima_escala = _ESCALA[t]
            visto = True
        else:
            return None
        anterior = t
    return total + grupo if visto else None


def extenso_para_numero(s: str) -> float | None:
    """'cinco milhões, setecentos e quinze mil, trezentos e setenta e nove reais e trinta e cinco centavos' →
    5715379.35. None se houver palavra que não seja número (o extenso não foi isolado com segurança)."""
    s = re.sub(r"-\s*\n\s*", "", s or "")            # hifenização de quebra de linha ("ses-\nsenta")
    s = sem_acento(s.lower()).replace(",", " ")
    m = re.match(r"\s*(.*?)\s*\breais?\b(?:\s+e\s+(.*?)\s*\bcentavos?\b)?\s*$", s, re.S)
    if m:
        inteiro = _inteiro_extenso(m.group(1)) if m.group(1).strip() else 0
        cent = _inteiro_extenso(m.group(2)) if m.group(2) else 0
    else:
        m = re.match(r"\s*(.*?)\s*\bcentavos?\b\s*$", s, re.S)
        if not m:
            return None
        inteiro, cent = 0, _inteiro_extenso(m.group(1))
    if inteiro is None or cent is None or cent > 99:
        return None
    return round(inteiro + cent / 100, 2)


RE_VALOR_EXTENSO = re.compile(r"R\$\s*([\d.]{1,15},\d{2})\s*\(\s*([^()]{5,400}?)\s*\)", re.S)


def divergencias_extenso(texto: str, minimo: float = 1000.0, minimo_rel: float = 0.01) -> list[dict]:
    """[(valor, extenso, valor_do_extenso, trecho)] onde número e extenso discordam em mais de `minimo` reais E de
    `minimo_rel` do valor (troca de uma palavra em R$ 14.499,00 × 14.449,00 é erro de digitação sem relevância)."""
    out = []
    for m in RE_VALOR_EXTENSO.finditer(texto):
        ext = m.group(2)
        if not re.search(r"\breais?\b|centavos?", ext, re.I):
            continue
        v, ve = num_br(m.group(1)), extenso_para_numero(ext)
        if v is None or ve is None or abs(v - ve) <= minimo or abs(v - ve) <= minimo_rel * max(v, ve):
            continue
        out.append({"valor": v, "valor_extenso": ve, "pos": m.start(), "trecho": trecho(texto, m.start(), m.end(), 80)})
    return out
