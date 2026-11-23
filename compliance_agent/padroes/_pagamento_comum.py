# -*- coding: utf-8 -*-
"""Leitura comum da família PAGAMENTO, ATESTO, RETENÇÕES E PARCERIAS (MROSC) — docs/PADROES-DE-IRREGULARIDADE.md.

Uma porta só para: percorrer o acervo SEI pelos MANIFESTOS (só documento declarado conta — pasta pode ter órfão de
outra captura), escolher documentos pelo TÍTULO (barato: não abre o .txt), ler o texto sem a etiqueta da casa
(`sei.acervo_texto.ler`) e somar o pago por OB do SIAFE com o filtro canônico `cruzamentos_intel._ob_paga`.

Processo com árvore > 1.000 documentos: o índice do arquivo estava errado até o commit 80770d09 (1000.pdf virava o
documento 100). Para esses o texto vem de `data/sei_cache/integra_<tag>/<i>.*txt` quando existe; a contagem fica em
`cobertura["arvore_maior_que_1000"]`.

O pago por processo é PISO: a soma por processo está sendo refeita (frente 2bfd — OB por NL dos autos); aqui só a OB
cujo campo `processo` é o próprio SEI entra.
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path

from compliance_agent.padroes._comum import RAIZ, con_ro, credor_publico, mascarar_cpf, ordenar, travar_ocr_ia  # noqa: F401  (C.mascarar_cpf nos detectores)
from compliance_agent.padroes._comum import trecho as _trecho
from compliance_agent.rotina_base import gravar_json

ACERVO = RAIZ / "data" / "sei_arquivo"
CACHE = RAIZ / "data" / "sei_cache"

_RE_TAG = re.compile(r"(\d{6})_(\d{6})_(\d{4})")
MOEDA = r"\d{1,3}(?:\.\d{3})*,\d{2}"


def processo(tag: str) -> str:
    m = _RE_TAG.fullmatch(tag)
    return f"SEI-{m[1]}/{m[2]}/{m[3]}" if m else tag


def tag_de(proc: str) -> str:
    return re.sub(r"^SEI-", "", proc).replace("/", "_")


def norm(s: str) -> str:
    """Minúsculas sem acento e com espaço único — para casar texto e nomes."""
    s = unicodedata.normalize("NFKD", (s or "").casefold())
    return re.sub(r"\s+", " ", "".join(c for c in s if not unicodedata.combining(c))).strip()


def num(s: str) -> float:
    return float(s.replace("R$", "").strip().replace(".", "").replace(",", "."))


def fmt(v: float) -> str:
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def data_br(s: str | None) -> date | None:
    """'DD/MM/AAAA' (o SIAFE guarda TEXTO, não ISO) → date; inválida → None."""
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", s or "")
    if not m:
        return None
    try:
        return date(int(m[3]), int(m[2]), int(m[1]))
    except ValueError:
        return None


MES = r"(janeiro|fevereiro|mar[cç]o|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)"
_MESES = {m: i for i, m in enumerate(
    "janeiro fevereiro marco abril maio junho julho agosto setembro outubro novembro dezembro".split(), 1)}
_RE_DATA_LOCAL = re.compile(r"Rio de Janeiro\s*,\s*(\d{1,2})\s+de\s+" + MES + r"\s+de\s+(\d{4})", re.I)
_RE_ASS = re.compile(r"assinado eletronicamente por .{3,160}?,\s*em\s+(\d{2}/\d{2}/\d{4})", re.I | re.S)


def mes_num(s: str) -> int | None:
    """'março' → 3."""
    return _MESES.get(norm(s).replace("ç", "c"))


def data_ymd(a, m, d) -> date | None:
    try:
        return date(int(a), int(m), int(d))
    except (ValueError, TypeError):
        return None


def data_do_atesto(texto: str) -> date | None:
    """Data de um ato assinado no SEI: a última assinatura eletrônica (a comissão só completa o atesto quando o último
    assina); sem ela, a data do fecho 'Rio de Janeiro, dd de mês de aaaa'."""
    t = re.sub(r"\s+", " ", texto or "")
    ds = [d for d in (data_br(x) for x in _RE_ASS.findall(t)) if d]
    if ds:
        return max(ds)
    ds = [d for d in (data_ymd(m[3], mes_num(m[2]), m[1]) for m in _RE_DATA_LOCAL.finditer(t)) if d]
    return max(ds) if ds else None


def manifesto(pasta: Path) -> dict | None:
    try:
        m = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return m if isinstance(m, dict) else None


def pastas(so: list[str] | None = None) -> list[Path]:
    """Pastas do acervo (todas, ou só as tags pedidas — lista vazia é universo vazio, não o acervo inteiro)."""
    if so is not None:
        return [ACERVO / tag_de(t) for t in so if (ACERVO / tag_de(t)).is_dir()]
    return sorted(p for p in ACERVO.iterdir() if p.is_dir() and _RE_TAG.fullmatch(p.name))


def docs(man: dict) -> list[dict]:
    return [d for d in (man.get("docs") or []) if isinstance(d, dict) and d.get("texto")]


def ler(pasta: Path, man: dict, d: dict, teto: int | None = None) -> str:
    """Texto do documento sem a etiqueta da casa; árvore > 1.000 → íntegra do sei_cache pelo índice."""
    from compliance_agent.sei import acervo_texto as A
    if int(man.get("total_arvore") or 0) > 1000 and d.get("i") is not None:
        integra = CACHE / f"integra_{pasta.name}"
        for nome in (f"{int(d['i']):03d}.ocr.txt", f"{int(d['i']):03d}.txt", f"{int(d['i']):03d}.ocr_gpu.txt"):
            p = integra / nome
            if p.is_file():
                t = p.read_text(encoding="utf-8", errors="ignore")
                return t if teto is None else t[:teto]
    return A.ler(pasta, d, teto)


def numero_doc(d: dict) -> str:
    """'doc N (id SEI)' — como o laudo cita."""
    m = re.search(r"\((\d{6,})\)\s*$", str(d.get("titulo") or ""))
    return f"doc {d.get('i')}" + (f" ({m[1]})" if m else "")


_COLS = ("numero_ob", "ug_emitente", "data_emissao", "nl", "credor", "nome_credor", "valor", "processo")


def obs_pagas(con, processos: list[str]) -> dict[str, list[dict]]:
    """OB pagas (filtro canônico `_ob_paga`) por processo SEI."""
    from compliance_agent.cruzamentos_intel import _ob_paga
    out: dict[str, list[dict]] = {}
    paga = _ob_paga(con)
    processos = sorted(set(processos))
    if len(processos) > 200:   # sem índice em `processo`: uma varredura só, filtrada em Python
        alvo = set(processos)
        for r in con.execute(f"SELECT {', '.join(_COLS)} FROM ob_orcamentaria_siafe WHERE {paga}"):
            if r[-1] in alvo:
                o = dict(zip(_COLS, r))
                out.setdefault(o["processo"], []).append(o)
        return out
    for i in range(0, len(processos), 500):
        lote = processos[i:i + 500]
        q = (f"SELECT {', '.join(_COLS)} FROM ob_orcamentaria_siafe WHERE processo IN ({','.join('?' * len(lote))}) "
             f"AND {paga}")
        for r in con.execute(q, lote):
            o = dict(zip(_COLS, r))
            out.setdefault(o["processo"], []).append(o)
    return out


def pago(obs: list[dict]) -> float | None:
    """Soma das OB pagas (PISO); sem OB → None (INDISPONÍVEL ≠ 0)."""
    return round(sum(float(o["valor"] or 0) for o in obs), 2) if obs else None


def resultado(id_: str, universo: int, cobertura: dict, achados: list[dict], fonte: str) -> dict:
    ordenar(travar_ocr_ia(achados))
    return {"id": id_, "gerado_em": datetime.now().isoformat(timespec="seconds"), "universo": universo,
            "cobertura": cobertura, "fonte": fonte,
            "funil": {g: sum(1 for a in achados if a.get("grau") == g) for g in ("forte", "medio", "fraco")},
            "achados": achados}


def trecho(texto: str, ini: int, fim: int, folga: int = 90) -> str:
    return _trecho(texto, ini, fim, folga)[:400]


def _uma_pasta(args) -> tuple[list[dict], dict]:
    pasta, titulo_re, func = args
    man = manifesto(pasta)
    if not man:
        return [], {"sem_manifesto": 1}
    sel = [d for d in docs(man) if titulo_re is None or titulo_re.search(str(d.get("titulo") or ""))]
    if not sel:
        return [], {}
    cob = {"processos_com_doc_do_tipo": 1}
    if int(man.get("total_arvore") or 0) > 1000:
        cob["arvore_maior_que_1000"] = 1
    achs, c2 = func(pasta, man, sel)
    for k, v in (c2 or {}).items():
        cob[k] = cob.get(k, 0) + v
    return achs, cob


def varrer_acervo(titulo_re, func, so: list[str] | None = None, limite: int | None = None,
                  workers: int = 2) -> tuple[list[dict], dict, int]:
    """Percorre as pastas; `func(pasta, man, docs_do_tipo) -> (achados, cobertura)` só roda onde há documento
    cujo título casa `titulo_re`. Devolve (achados, cobertura somada, nº de pastas)."""
    ps = pastas(so)
    if limite:
        ps = ps[:limite]
    tarefas = [(p, titulo_re, func) for p in ps]
    if workers > 1 and len(tarefas) > 50:
        from multiprocessing import Pool
        with Pool(workers) as pool:
            res = pool.map(_uma_pasta, tarefas, chunksize=64)
    else:
        res = [_uma_pasta(t) for t in tarefas]
    achados, cob = [], {"pastas": len(ps)}
    for a, c in res:
        achados += a
        for k, v in c.items():
            cob[k] = cob.get(k, 0) + v
    return achados, cob, len(ps)


def obs_por_nl(con, nls: set[str], ugs: set[str]) -> list[dict]:
    """OB pagas pelas NL citadas nos autos, restritas às UG que os próprios autos imprimem (NL é numerada por UG:
    sem a UG, a mesma NL de outro órgão entraria). Usado quando o campo `processo` da OB não traz o SEI."""
    from compliance_agent.cruzamentos_intel import _ob_paga
    if not nls or not ugs:
        return []
    q = (f"SELECT {', '.join(_COLS)} FROM ob_orcamentaria_siafe WHERE nl IN ({','.join('?' * len(nls))}) "
         f"AND ug_emitente IN ({','.join('?' * len(ugs))}) AND {_ob_paga(con)}")
    return [dict(zip(_COLS, r)) for r in con.execute(q, [*sorted(nls), *sorted(ugs)])]


def grep_candidatos(padrao: str, so: list[str] | None = None, limite: int | None = None,
                    nomes: list[str] | None = None) -> dict[str, list[str]]:
    """{tag: [nomes de .txt]} cujo texto casa `padrao` (grep -E, sem caixa) — I/O em ionice, sem abrir 10 mil pastas
    em Python. Quem chama confere o documento contra o manifesto (órfão não conta)."""
    import hashlib
    import subprocess
    import time
    # Varredura inteira custa ~45 min de I/O com a VM carregada: o resultado do acervo todo fica em cache por 12 h
    # (recalibrar uma regra não exige reler 14 GB). `so`/`limite` nunca usam nem gravam o cache.
    chave = hashlib.sha1(f"{padrao}|{sorted(nomes or [])}".encode()).hexdigest()[:16]
    cache = RAIZ / "data" / "padroes" / "_grep_cache" / f"{chave}.json"
    if so is None and not limite and cache.is_file() and time.time() - cache.stat().st_mtime < 12 * 3600:
        return json.loads(cache.read_text(encoding="utf-8"))
    alvo = [str(p / "texto") for p in pastas(so)][: limite or None]
    out: dict[str, list[str]] = {}
    for i in range(0, len(alvo), 400):
        # `nomes`: globs do NOME do .txt (derivado do título SEI: "024_nota_fiscal_….txt") — corta o I/O a quem o
        # detector leria de qualquer jeito.
        inc = [f"--include=*{n}*" for n in (nomes or [])]
        r = subprocess.run(["nice", "-n", "19", "ionice", "-c2", "-n7", "grep", "-rliE", *inc, padrao, *alvo[i:i + 400]],
                           capture_output=True, text=True, check=False)
        for linha in r.stdout.splitlines():
            m = re.search(r"sei_arquivo/([^/]+)/texto/(.+)$", linha)
            if m:
                out.setdefault(m[1], []).append(m[2].split("/")[-1])
    if so is None and not limite:
        gravar_json(cache, out)
    return out


def completar_com_ob(achados: list[dict]) -> None:
    """`valor_pago_ob` (PISO) e `credor` de cada achado pelas OB pagas do seu processo."""
    if not achados:
        return
    con = con_ro()
    try:
        obs = obs_pagas(con, [a["processo"] for a in achados])
    finally:
        con.close()
    for a in achados:
        a["valor_pago_ob"] = pago(obs.get(a["processo"], []))
        a["credor"] = credores(obs.get(a["processo"], []))


def docs_por_arquivo(man: dict) -> dict[str, dict]:
    return {str(d["texto"]).split("/")[-1]: d for d in docs(man)}


def credor_nome(obs: list[dict]) -> str | None:
    """Nome do credor das OB (o da primeira com nome); pessoa física sai omitida (`_comum.credor_publico`)."""
    for o in obs:
        if o.get("nome_credor"):
            return credor_publico(o.get("credor"), o["nome_credor"])
    return None


def credores(obs: list[dict]) -> str:
    """Todos os credores das OB, distintos, em ordem alfabética (até 200 caracteres); pessoa física omitida."""
    return "; ".join(sorted({credor_publico(o.get("credor"), o["nome_credor"]) for o in obs
                             if o.get("nome_credor")}))[:200]
