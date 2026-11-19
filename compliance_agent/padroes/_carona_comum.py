"""Base comum da família CARONA EM ATA (adesão) E CONTRATAÇÃO DIRETA (docs/PADROES-DE-IRREGULARIDADE.md).

Leitura do acervo SEI (data/sei_arquivo/<tag> e data/sei_cache/integra_<tag>), pré-filtro por `grep` (o acervo tem
~570 mil textos / 7 GB; ler tudo em Python a cada detector custaria horas na VM-1), trecho literal para a prova e
OB paga do SIAFE (`_ob_paga`). Só leitura. Nada aqui decide achado: só entrega texto e número com proveniência.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import unicodedata
from dataclasses import dataclass
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


_ACENTOS = "áàâãéêíóôõúüç"


def _regex_c(regex_ere: str) -> str:
    """grep -i em locale UTF-8 é ~20× mais lento; em LC_ALL=C o -i só dobra ASCII — então cada letra acentuada
    vira (minúscula|MAIÚSCULA) explicitamente. Não usar letra acentuada dentro de [colchetes] no prefiltro."""
    return "".join(f"({c}|{c.upper()})" if c in _ACENTOS else c for c in regex_ere)


def candidatos(regex_ere: str) -> dict[str, set[str]]:
    """Processos (tag) cujo texto casa `regex_ere` (grep -E, sem distinção de caixa) → nomes dos arquivos que casaram.
    Roda com prioridade mínima de CPU e de disco (VM-1 compartilhada)."""
    env = dict(os.environ, LC_ALL="C")
    base = ["nice", "-n", "19", "ionice", "-c3", "grep", "-rliE", "--include=*.txt", _regex_c(regex_ere)]
    alvos = [str(ARQUIVO)] + sorted(str(p) for p in CACHE.glob("integra_*") if p.is_dir())
    out: dict[str, set[str]] = {}
    for k in range(0, len(alvos), 400):        # lotes: a linha de comando tem limite
        r = subprocess.run(base + alvos[k:k + 400], capture_output=True, text=True, env=env, check=False)
        if r.returncode not in (0, 1):
            raise RuntimeError(f"grep falhou ({r.returncode}): {r.stderr[:300]}")
        for linha in r.stdout.splitlines():
            t = tag_de(linha)
            if t:
                out.setdefault(t, set()).add(Path(linha).name)
    return out


def _ler(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _norm_tit(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", sem_acento(t or "").lower())[:60]


def docs(tag: str) -> list[Doc]:
    """Documentos do processo: o arquivo (texto já lido, com título) primeiro; da íntegra entram os títulos que o
    arquivo não tem. Texto vazio fica de fora (INDISPONÍVEL ≠ texto sem o sinal — quem chama mede a cobertura)."""
    saida: list[Doc] = []
    vistos: set[str] = set()
    d = ARQUIVO / tag
    man = d / "manifest.json"
    if man.exists():
        try:
            m = json.loads(_ler(man) or "{}")
        except ValueError:
            m = {}
        for x in m.get("docs") or []:
            p = d / str(x.get("texto") or "")
            if not x.get("texto") or not p.is_file():
                continue
            txt = _ler(p)
            if txt.strip():
                saida.append(Doc("arquivo", str(x.get("i")), str(x.get("titulo") or ""), txt))
                vistos.add(_norm_tit(str(x.get("titulo") or "")))
    di = CACHE / f"integra_{tag}"
    mi = di / "manifest.json"
    if mi.exists():
        try:
            m = json.loads(_ler(mi) or "{}")
        except ValueError:
            m = {}
        for x in m.get("docs") or []:
            tit = str(x.get("titulo") or "")
            if _norm_tit(tit) in vistos:
                continue
            stem = Path(str(x.get("arquivo") or f"{int(x.get('i') or 0):03d}.pdf")).stem
            txts = [_ler(di / f"{stem}.txt"), _ler(di / f"{stem}.ocr.txt")]
            txt = max(txts, key=len)
            if txt.strip():
                saida.append(Doc("integra", str(x.get("i")), tit, txt))
    return saida


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


def resultado(id_: str, universo: int, cobertura: dict, achados: list[dict], **extra) -> dict:
    return {"id": id_, "gerado_em": agora(), "universo": universo, "cobertura": cobertura,
            "achados": achados, **extra}
