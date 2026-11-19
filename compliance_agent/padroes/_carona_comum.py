"""Base comum da família CARONA EM ATA (adesão) E CONTRATAÇÃO DIRETA (docs/PADROES-DE-IRREGULARIDADE.md).

Leitura do acervo SEI (data/sei_arquivo/<tag> e data/sei_cache/integra_<tag>), trecho literal para a prova e OB paga
do SIAFE (`_ob_paga`). Só leitura. Nada aqui decide achado: só entrega texto e número com proveniência.

Custo medido em 18/11/2026 (VM-1, load 27): o acervo tem ~570 mil textos / 7 GB e a leitura a frio sai a ~7
arquivos/s (IOPS do volume, não CPU) — grep no acervo inteiro levaria horas por detector. Por isso a seleção é pelo
ÍNDICE DE TÍTULOS (manifestos, um arquivo por processo) e só os documentos do tipo que o detector precisa são lidos;
a modalidade pela NE (um documento por processo) fica em cache em disco (`data/padroes/_cache_ne_carona.json`).
"""
from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
ARQUIVO = RAIZ / "data" / "sei_arquivo"
CACHE = RAIZ / "data" / "sei_cache"
DB = RAIZ / "data" / "compliance.db"

_RX_TAG = re.compile(r"(\d{6})_(\d{6})_(\d{4})")


@dataclass
class Doc:
    fonte: str        # "arquivo" | "integra"
    i: str            # índice do documento na árvore daquela fonte
    titulo: str
    texto: str

    @property
    def ref(self) -> str:
        return f"doc {self.i}" if self.fonte == "arquivo" else f"íntegra doc {self.i}"


def agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canon(tag: str) -> str:
    a, b, c = tag.split("_")
    return f"SEI-{a}/{b}/{c}"


def tag_de(caminho: str | Path) -> str | None:
    m = _RX_TAG.search(str(caminho))
    return "_".join(m.groups()) if m else None


def sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn")


def _ler(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _norm_tit(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", sem_acento(t or "").lower())[:60]


@dataclass
class Ref:
    fonte: str
    i: str
    titulo: str
    caminhos: tuple[str, ...]      # arquivo: (texto,); íntegra: (.txt, .ocr.txt) — vale o mais longo


def _docs_do_manifesto(m) -> list[dict]:
    """Manifesto pode ser {"docs": [...]} ou, nos antigos, a lista direta; entrada que não é dict é ignorada."""
    lst = m.get("docs") if isinstance(m, dict) else m
    return [x for x in (lst or []) if isinstance(x, dict)] if isinstance(lst, list) else []


@lru_cache(maxsize=None)
def refs(tag: str) -> tuple[Ref, ...]:
    """Documentos do processo SEM ler o texto: o arquivo (texto já lido, com título) primeiro; da íntegra entram os
    títulos que o arquivo não tem."""
    out: list[Ref] = []
    vistos: set[str] = set()
    d = ARQUIVO / tag
    try:
        m = json.loads(_ler(d / "manifest.json") or "{}")
    except ValueError:
        m = {}
    for x in _docs_do_manifesto(m):
        if x.get("texto"):
            out.append(Ref("arquivo", str(x.get("i")), str(x.get("titulo") or ""), (str(d / str(x["texto"])),)))
            vistos.add(_norm_tit(str(x.get("titulo") or "")))
    di = CACHE / f"integra_{tag}"
    try:
        m = json.loads(_ler(di / "manifest.json") or "{}")
    except ValueError:
        m = {}
    for x in _docs_do_manifesto(m):
        tit = str(x.get("titulo") or "")
        if _norm_tit(tit) in vistos:
            continue
        stem = Path(str(x.get("arquivo") or f"{int(x.get('i') or 0):03d}.pdf")).stem
        out.append(Ref("integra", str(x.get("i")), tit, (str(di / f"{stem}.txt"), str(di / f"{stem}.ocr.txt"))))
    return tuple(out)


def ler(r: Ref) -> Doc | None:
    txt = max((_ler(Path(c)) for c in r.caminhos), key=len)
    return Doc(r.fonte, r.i, r.titulo, txt) if txt.strip() else None


def docs(tag: str, tipos: tuple[str, ...] | None = None) -> list[Doc]:
    """Lê os documentos do processo (só os de `tipos`, por `tipo_doc(titulo)`, quando dado). Texto vazio fica de fora
    (INDISPONÍVEL ≠ texto sem o sinal — quem chama mede a cobertura)."""
    out = []
    for r in refs(tag):
        if tipos is None or tipo_doc(r.titulo) in tipos:
            d = ler(r)
            if d:
                out.append(d)
    return out


def tags() -> list[str]:
    """Todos os processos do acervo (arquivo ∪ íntegra)."""
    a = {p.name for p in ARQUIVO.iterdir() if _RX_TAG.fullmatch(p.name)} if ARQUIVO.exists() else set()
    b = {p.name[8:] for p in CACHE.glob("integra_*") if _RX_TAG.fullmatch(p.name[8:])} if CACHE.exists() else set()
    return sorted(a | b)


# ─────────────── modalidade pela NE (um documento por processo; cache em disco) ───────────────
CACHE_NE = RAIZ / "data" / "padroes" / "_cache_ne_carona.json"
_RX_MOD = re.compile(r"Mod\.?\s*Licita[çc][ãa]o\s*\n?\s*(\d{2})\s*-\s*([^\n]{3,80})", re.I)
_RX_EMB = re.compile(r"Emb\.?\s*Legal\s*\n?\s*([^\n]{3,80})", re.I)


def carregar_cache_ne() -> dict:
    try:
        return json.loads(CACHE_NE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def salvar_cache_ne(c: dict) -> None:
    CACHE_NE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_NE.with_suffix(".tmp")
    tmp.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
    tmp.replace(CACHE_NE)


def modalidade_ne(tag: str, cache: dict) -> dict:
    """{"mod": "12 - Adesão ao Registro de Preços Externo - Pregão" | None, "emb": "...", "prova": "doc i — …",
    "sem_ne": bool}. Lê a NE ORIGINAL (ou a primeira NE) — a modalidade se repete em todas as NE do contrato."""
    if tag in cache:
        return cache[tag]
    rs = [r for r in refs(tag) if re.search(r"empenho", sem_acento(r.titulo), re.I)]
    rs.sort(key=lambda r: (0 if re.search(r"original", r.titulo, re.I) else 1))
    out = {"mod": None, "emb": None, "prova": None, "sem_ne": not rs}
    for r in rs[:2]:
        d = ler(r)
        if not d:
            continue
        m = _RX_MOD.search(d.texto)
        if m:
            e = _RX_EMB.search(d.texto)
            out = {"mod": f"{m.group(1)} - {m.group(2).strip()}", "emb": e.group(1).strip() if e else None,
                   "prova": f'{d.ref} ({d.titulo[:50]}) — "{trecho(d.texto, m.start(), m.end(), 0)[:120]}"',
                   "sem_ne": False}
            break
    cache[tag] = out
    return out


def trecho(texto: str, ini: int, fim: int, raio: int = 140) -> str:
    a, b = max(0, ini - raio), min(len(texto), fim + raio)
    return re.sub(r"\s+", " ", texto[a:b]).strip()


def tipo_doc(titulo: str) -> str:
    t = sem_acento(titulo).lower()
    if re.search(r"estudo\s*t[eé]?cnico|\betp\b|estudos?\s+preliminar", t):
        return "etp"
    if re.search(r"termo\s+de\s+refer|\btr\b|projeto\s+b[aá]sico", t):
        return "tr"
    if re.search(r"edital", t):
        return "edital"
    if re.search(r"\bata\b|\barp\b|registro\s+de\s+pre", t):
        return "ata"
    if re.search(r"extrato.*contrato|^contrato|\bcontrato\s+n|termo\s+de\s+contrato|instrumento\s+contratual", t):
        return "contrato"
    if re.search(r"empenho|\bne\b", t):
        return "empenho"
    if re.search(r"pesquisa\s+de\s+pre|mapa\s+(comparativo|de\s+pre)|cota[cç]", t):
        return "pesquisa"
    return "outro"


def regime(ds: list[Doc]) -> str:
    """'14133' | '8666' | '?' — pelo fundamento declarado na NE/contrato/despacho (o que o próprio processo diz)."""
    n14 = n8 = 0
    for d in ds:
        n14 += len(re.findall(r"14\.?133", d.texto))
        n8 += len(re.findall(r"8\.?666", d.texto))
    if n14 and not n8:
        return "14133"
    if n8 and not n14:
        return "8666"
    if n14 or n8:
        return "14133" if n14 >= 2 * n8 else ("8666" if n8 >= 2 * n14 else "?")
    return "?"


def ob_pagas(processos: set[str]) -> dict[str, dict]:
    """OB PAGA (SIAFE, `_ob_paga`) por processo, pela coluna `processo` — PISO: a ligação por NL/PD dos autos
    (tools/lex_execucao.mapa_obs_siafe, em correção por outra frente) pode achar mais. Uma varredura só."""
    from compliance_agent.cruzamentos_intel import _ob_paga
    if not processos or not DB.exists():
        return {}
    alvo = {re.sub(r"\D", "", p) for p in processos}
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=60)
    try:
        cur = con.execute(f"SELECT processo, numero_ob, valor, data_emissao, nome_credor, credor, ug_emitente "
                          f"FROM ob_orcamentaria_siafe WHERE {_ob_paga(con)} AND processo LIKE '%/%/%'")
        out: dict[str, dict] = {}
        for proc, nob, val, dt, nome, cred, ug in cur:
            m = re.search(r"(\d{6})\D{0,3}(\d{6})\D{0,3}(20\d{2})", proc or "")
            if not m or "".join(m.groups()) not in alvo:
                continue
            k = f"SEI-{m.group(1)}/{m.group(2)}/{m.group(3)}"
            o = out.setdefault(k, {"total": 0.0, "obs": [], "piso": True,
                                   "fonte": "SIAFE ob_orcamentaria_siafe (_ob_paga), ligação pela coluna processo — piso"})
            o["total"] = round(o["total"] + float(val or 0), 2)
            o["obs"].append({"ob": nob, "valor": val, "data": dt, "credor": nome, "cnpj": cred, "ug": ug})
        return out
    finally:
        con.close()


def credor_principal(ob: dict | None) -> str | None:
    if not ob or not ob.get("obs"):
        return None
    soma: dict[str, float] = {}
    for o in ob["obs"]:
        soma[o.get("credor") or "?"] = soma.get(o.get("credor") or "?", 0) + float(o.get("valor") or 0)
    return max(soma, key=soma.get)


def orgao(ds: list[Doc]) -> str | None:
    """UG/órgão pela NE dos autos, quando houver ('180100 - SECRETARIA DE ESTADO DE EDUCACAO')."""
    for d in ds[:120]:
        m = re.search(r"\b(\d{6})\s*-\s*([A-ZÀ-Ú][A-ZÀ-Ú0-9 ,.\-/]{6,90})\(CNPJ", d.texto)
        if m:
            return f"{m.group(1)} - {m.group(2).strip()}"
    return None


def ligar(achados: list[dict], vicio: str, violado=lambda a: False) -> list[dict]:
    """Liga cada achado ao vício do catálogo canônico (`knowledge/catalogo_vicios.py`) e ao gradeador epistemológico
    (`editais/flags.grau_flag`): teto legal excedido em número + fonte → A; indício textual isolado → C."""
    from compliance_agent.editais.flags import grau_flag
    from compliance_agent.knowledge.catalogo_vicios import obter
    v = obter(vicio)
    for a in achados:
        a["vicio_catalogo"] = {"id": vicio, "nome": v.nome if v else None, "escalada": v.escalada if v else None}
        a["flag"] = grau_flag(origem="deterministico", teste_status="violado" if violado(a) else None,
                              score=0.9 if a.get("grau") == "forte" else 0.6)
    return achados


def resultado(id_: str, universo: int, cobertura: dict, achados: list[dict], **extra) -> dict:
    return {"id": id_, "gerado_em": agora(), "universo": universo, "cobertura": cobertura,
            "achados": achados, **extra}


# Leitura a frio é latência de disco, não CPU: 16 leituras em paralelo saem ~6× mais rápidas que em série
# (medido 18/11/2026: 200 manifestos em 4,3 s × 0,8 s). Threads, não processos: o GIL é solto no read().
LEITORES = 12


def prefetch_ne(todos: list[str], cache: dict) -> None:
    """Preenche `cache` com a modalidade da NE de todos os processos, em paralelo, salvando a cada lote."""
    falta = [t for t in todos if t not in cache]
    with ThreadPoolExecutor(LEITORES) as ex:
        for k in range(0, len(falta), 500):
            lote = falta[k:k + 500]
            for t, r in zip(lote, ex.map(lambda x: modalidade_ne(x, {}), lote)):
                cache[t] = r
            salvar_cache_ne(cache)


def em_paralelo(fn, itens: list, lote: int = 200):
    """Gera (item, fn(item)) na ordem, lendo em paralelo por lotes (memória limitada a um lote de textos)."""
    with ThreadPoolExecutor(LEITORES) as ex:
        for k in range(0, len(itens), lote):
            parte = itens[k:k + lote]
            yield from zip(parte, ex.map(fn, parte))


def docs_em_paralelo(pedidos: list[tuple[str, tuple[str, ...] | None]]):
    """[(tag, tipos)] → gera (tag, docs) na mesma ordem, lendo em paralelo."""
    for (t, _), ds in em_paralelo(lambda p: docs(p[0], p[1]), pedidos):
        yield t, ds


def refs_em_paralelo(todos: list[str]) -> None:
    """Aquece o cache de `refs` (manifestos) em paralelo."""
    with ThreadPoolExecutor(LEITORES) as ex:
        list(ex.map(refs, todos))


def codigo_mod(ne: dict) -> str | None:
    """'12' adesão externa · '10' adesão interna · '06' inexigibilidade · … (tabela do SIAFE-RJ na NE)."""
    m = re.match(r"(\d{2})", ne.get("mod") or "")
    return m.group(1) if m else None


def titulos_casam(tag: str, rx: re.Pattern) -> bool:
    return any(rx.search(sem_acento(r.titulo)) for r in refs(tag))
