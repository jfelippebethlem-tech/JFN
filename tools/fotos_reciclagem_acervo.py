"""Foto RECICLADA no acervo inteiro — a mesma fotografia lastreando processos ou MEDIÇÕES diferentes.

`foto_medicao.reciclagem()` existia e era testada, mas só rodava entre os processos de UM dossiê
(`capitulos_dossie`). Em 24/09/2026 o acervo tinha 3.818 processos e 17.492 arquivos em `fotos/` e o
confronto de todos contra todos nunca tinha sido feito — que é justamente onde a reciclagem aparece:
o mesmo registro "comprovando" a execução de dois contratos distintos.

18/11/2026 — a rodada de 27/09 alcançou 123 processos / 5.483 fotos; o acervo tinha 899 pastas com arquivo e 48.646
arquivos (os outros 291.776 foram para o arquivo frio porque `_triar_e_hashear` já os descartava — página de
documento). Esta versão faz os DOIS confrontos numa passada só, sobre um índice por REGIÃO de foto:
  (a) entre processos diferentes;
  (b) entre DOCUMENTOS diferentes do mesmo processo (medição/período diferente), não só nos títulos com
      "fotográfico" — o relatório fotográfico também chega como "Anexo 13ª Medição".
O cálculo pesado (`indexar`, um processo por núcleo) roda onde houver CPU; o agrupamento é leve.

Pares: dHash ≤ LIMIAR (busca exata por gaveta de 2 bytes — duas hashes a ≤ 6 bits de distância têm, pelo princípio
da gaveta, ao menos 2 dos 8 bytes iguais) E 2ª assinatura independente (`foto_medicao._confirma`). Grupo = componente
conexa dos pares confirmados. Indício ≠ acusação: a conferência é humana e cada grupo leva o porquê (`classificar`:
regras R1–R6 medidas no acervo; o resto, veredito a olho em `VEREDITOS`, preso às fotos exatas). 1ª rodada completa
(18/11/2026): 3.506 grupos; 282 contradição, 26 sem explicação; 1.377 PENDENTES (sem céu ou período não identificado).

Uso:
    python -m tools.fotos_reciclagem_acervo indexar --raiz <sei_arquivo> --saida idx.pkl --workers 12
    python -m tools.fotos_reciclagem_acervo agrupar --indice idx.pkl --saida grupos.pkl
    python -m tools.fotos_reciclagem_acervo laudo --grupos grupos.pkl --resumo-indice idx.resumo.json
    nice -n 19 ionice -c3 .venv/bin/python -m tools.fotos_reciclagem_acervo      # tudo, local, 1 núcleo
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pickle
import re
import sqlite3
import sys
import time
from collections import Counter
from datetime import datetime
from itertools import combinations
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from compliance_agent import foto_medicao as FM  # noqa: E402

ARQUIVO = RAIZ / "data" / "sei_arquivo"
SAIDA = RAIZ / "data" / "fotos_reciclagem_acervo.json"
DB = RAIZ / "data" / "compliance.db"


_SLUG = re.compile(r"^\d+_\d+_\d{4}$")
_ARQ = re.compile(r"^(\d+)_p(\d+)", re.I)


def _processos_com_foto() -> list[Path]:
    """Só pastas de PROCESSO (UG_SEQ_ANO). `_substituido/` guarda 3.078 capturas ANTIGAS dos mesmos processos e
    `_orfaos_residuo/` sobras: na 1ª rodada (24/09/2026) a pasta de substituídas entrou como "processo" e 22 fotos
    "recicladas" eram o processo contra a própria captura anterior."""
    return sorted(d for d in ARQUIVO.iterdir() if d.is_dir() and _SLUG.match(d.name) and FM._fotos_do_processo(d))


# ── 1. índice por região de foto (pesado) ───────────────────────────────────────────────────────────────────
def _itens_do_arquivo(f: Path) -> list[dict]:
    """Uma entrada por FOTOGRAFIA do arquivo (região embutida ou a imagem inteira), com dHash, 2ª assinatura e se
    parece mapa. Lista vazia = nada no arquivo serve como registro de execução (mesma triagem do detector)."""
    from PIL import Image
    try:
        with Image.open(f) as im:
            im.load()
            regioes = FM._regioes_foto(im)
            alvos = [im.crop(c) for c in regioes] or [im]
            out = []
            for k, a in enumerate(alvos):
                h = FM._hashear(a)
                if h is None:
                    continue
                out.append({"h": h, "regiao": k + 1 if regioes else 0,
                            "caixa": list(regioes[k]) if regioes else None,
                            "mapa": FM.parece_mapa(a), "s": FM._assinatura_da_imagem(a)})
            return out
    except (OSError, ValueError, Image.DecompressionBombError, SyntaxError):
        return []


def _indexar_processo(pasta: str) -> tuple[str, int, list[dict]]:
    d = Path(pasta)
    arqs = FM._fotos_do_processo(d)
    itens = []
    for f in arqs:
        m = _ARQ.match(f.name)
        for it in _itens_do_arquivo(f):
            it.update({"processo": d.name, "arquivo": f"{d.name}/fotos/{f.name}",
                       "doc": int(m.group(1)) if m else None, "pagina": int(m.group(2)) if m else None})
            itens.append(it)
    return d.name, len(arqs), itens


def indexar(dirs: list[Path], workers: int = 1, log=None) -> dict:
    """{'itens': [...], 'arquivos_por_processo': {slug: n}} — um processo por tarefa."""
    itens: list[dict] = []
    n_arq: dict[str, int] = {}
    alvo = [str(d) for d in dirs]
    if workers <= 1:
        res = map(_indexar_processo, alvo)
    else:
        from multiprocessing import Pool
        pool = Pool(workers, maxtasksperchild=50)
        # os maiores primeiro: a pasta de 4.370 arquivos não pode ficar para o fim sozinha num núcleo
        alvo.sort(key=lambda p: -len(FM._fotos_do_processo(Path(p))))
        res = pool.imap_unordered(_indexar_processo, alvo)
    t0 = time.time()
    for k, (slug, n, its) in enumerate(res, 1):
        n_arq[slug] = n
        itens.extend(its)
        if log and k % 50 == 0:
            log(f"{k}/{len(alvo)} processos · {len(itens)} regiões · {time.time() - t0:.0f} s")
    if workers > 1:
        pool.close()
        pool.join()
    return {"itens": itens, "arquivos_por_processo": n_arq, "gerado_em": datetime.now().isoformat(timespec="seconds")}


# ── 2. pares e grupos (leve) ────────────────────────────────────────────────────────────────────────────────
def _pares_de_hash(hashes: list[int], limiar: int) -> set[tuple[int, int]]:
    """Pares (i<j) de hashes ÚNICAS a distância ≤ limiar. Exato para limiar ≤ 6 (gaveta de 2 bytes)."""
    pares: set[tuple[int, int]] = set()
    byts = [[(h >> (8 * p)) & 0xFF for p in range(8)] for h in hashes]
    for p, q in combinations(range(8), 2):
        baldes: dict[int, list[int]] = {}
        for i, b in enumerate(byts):
            baldes.setdefault((b[p] << 8) | b[q], []).append(i)
        for ids in baldes.values():
            if len(ids) < 2:
                continue
            for a, b in combinations(ids, 2):
                if (a, b) not in pares and bin(hashes[a] ^ hashes[b]).count("1") <= limiar:
                    pares.add((a, b))
    return pares


def _conta_como_par(x: dict, y: dict) -> str | None:
    """'processos' (processos diferentes), 'documentos' (mesmo processo, documentos diferentes) ou None."""
    if x["processo"] != y["processo"]:
        return "processos"
    if x["doc"] is not None and y["doc"] is not None and x["doc"] != y["doc"]:
        return "documentos"
    return None


def agrupar(indice: dict, limiar: int = FM.LIMIAR_IGUAL) -> dict:
    itens = indice["itens"]
    por_hash: dict[int, list[int]] = {}
    for k, it in enumerate(itens):
        por_hash.setdefault(it["h"], []).append(k)
    unicas = list(por_hash)
    pares_h = _pares_de_hash(unicas, limiar)
    blocos = [(por_hash[h], por_hash[h]) for h in unicas if len(por_hash[h]) > 1]
    blocos += [(por_hash[unicas[a]], por_hash[unicas[b]]) for a, b in pares_h]
    pai = list(range(len(itens)))

    def raiz(x):
        while pai[x] != x:
            pai[x] = pai[pai[x]]
            x = pai[x]
        return x

    funil = {"pares_dhash": 0, "pares_dhash_confirmados": 0}
    tipos_par: dict[str, int] = {"processos": 0, "documentos": 0}
    for A, B in blocos:
        mesmo = A is B
        for ia, x in enumerate(A):
            for y in (A[ia + 1:] if mesmo else B):
                tipo = _conta_como_par(itens[x], itens[y])
                if tipo is None:
                    continue
                funil["pares_dhash"] += 1
                if FM._confirma(itens[x]["s"], itens[y]["s"]):
                    funil["pares_dhash_confirmados"] += 1
                    tipos_par[tipo] += 1
                    rx, ry = raiz(x), raiz(y)
                    if rx != ry:
                        pai[rx] = ry
    comp: dict[int, list[int]] = {}
    for k in range(len(itens)):
        comp.setdefault(raiz(k), []).append(k)
    grupos = []
    for membros in comp.values():
        if len(membros) < 2:
            continue
        oc = [{k: v for k, v in itens[m].items() if k != "s"} for m in membros]
        procs = sorted({o["processo"] for o in oc})
        docs = sorted({(o["processo"], o["doc"]) for o in oc})
        if len(procs) < 2 and len(docs) < 2:
            continue                                   # só repetição dentro do mesmo documento
        grupos.append({"processos": procs, "n_processos": len(procs), "n_documentos": len(docs),
                       "todos_mapa": all(o["mapa"] for o in oc), "ocorrencias": oc})
    grupos.sort(key=lambda g: (-g["n_processos"], -g["n_documentos"]))
    funil["pares_por_tipo"] = tipos_par
    funil["grupos"] = len(grupos)
    return {"grupos": grupos, "funil": funil}


# ── 3. contexto de cada processo (VM-1: banco + manifesto) ─────────────────────────────────────────────────
def _contexto(slugs: set[str]) -> dict[str, dict]:
    """Objeto, órgão e risco de cada processo (sei_arvore/sei_ficha), para o laudo dizer O QUE a foto comprova."""
    out: dict[str, dict] = {}
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
    except sqlite3.Error:
        return out
    try:
        for s in slugs:
            ug, seq, ano = (s.split("_") + ["", "", ""])[:3]
            numero = f"SEI-{ug}/{seq}/{ano}"
            r = None
            for tab in ("sei_arvore", "sei_ficha"):
                try:
                    r = con.execute(f"SELECT objeto, nivel_risco FROM {tab} WHERE numero_sei=?", (numero,)).fetchone()
                except sqlite3.Error:
                    r = None
                if r:
                    break
            out[s] = {"numero": numero, "ug": ug, "objeto": (r["objeto"] if r else None), "nivel_risco": (r["nivel_risco"] if r else None)}
    finally:
        con.close()
    return out


# ── 4. o PORQUÊ de cada grupo (pedido do dono, 18/11/2026) ───────────────────────────────────────────────────
# Para TODO grupo — real ou descartado — o motivo, lido no documento que guarda cada cópia, e uma das classes:
CLASSES = ("inocente-comprovada", "inocente-provável", "sem-explicação", "contradição")
VEREDITOS = RAIZ / "data" / "fotos_reciclagem_vereditos.json"   # conferência a olho, caso a caso (ver `_veredito`)

_RX_MED = (re.compile(r"(\d{1,3})\s*[ªa°º]\s*medi", re.I),
           re.compile(r"medi[çc][ãa]o\s*(?:n[º°o]\.?\s*)?(\d{1,3})\b", re.I),
           re.compile(r"\bmed\.?\s*(\d{1,3})\b", re.I),
           re.compile(r"\b(\d{1,3})\s*medi[çc]", re.I),
           re.compile(r"\b(\d{1,3})\s*\(?\s*P0\b", re.I),                          # PSAM: "Cálculo - 23 P0"
           re.compile(r"(?:fotogr[áa]fico|relat[óo]rio)\s*-?\s*(\d{1,3})\s*[°º]", re.I))  # "FOTOGRÁFICO 14°"
_RX_SEI_DOC = re.compile(r"\(?(\d{7,})\)?\s*$")
_MESES = "janeiro|fevereiro|março|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro"
_RX_DATA = re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](20\d{2}|\d{2})\b")
# "N° da medição: 06" no CORPO — o título da SEIOP vem truncado ("Avanço Físico 6ª M (97726179)")
_RX_MED_TEXTO = re.compile(r"(?:n[º°o]\.?\s*da\s*medi[çc][ãa]o|medi[çc][ãa]o\s*n[úu]mero|medi[çc][ãa]o\s*n[º°o]\.?)"
                           r"\s*:?\s*(\d{1,3})\b", re.I)
_RX_MES = re.compile(rf"\b({_MESES})\s*(?:de\s*|/\s*)?(20\d{{2}})\b", re.I)
_RX_ASSINATURA = re.compile(r"assinad|data e hora|autenticidade|c[óo]digo verificador|criado por|hor[áa]rio oficial|"
                            r"emitid[oa] em|gerad[oa] em", re.I)


def numero_medicao(titulo: str) -> int | None:
    """Nº da medição no TÍTULO: "13ª Medição", "Medição 22", "Med05", "Capa 10 medição" (o regex antigo só via o 1º)."""
    t = _RX_SEI_DOC.sub("", titulo or "")
    for rx in _RX_MED:
        m = rx.search(t)
        if m:
            return int(m.group(1))
    return None


def periodos_do_texto(texto: str) -> set[str]:
    """Datas e meses citados no corpo, fora das linhas de assinatura eletrônica (que variam de cópia para cópia)."""
    out: set[str] = set()
    for ln in (texto or "").splitlines():
        if _RX_ASSINATURA.search(ln):
            continue
        for d, m, a in _RX_DATA.findall(ln):
            if 1 <= int(m) <= 12 and 1 <= int(d) <= 31:
                out.add(f"{a if len(a) == 4 else '20' + a}-{int(m):02d}-{int(d):02d}")
        for m, a in _RX_MES.findall(ln):
            out.add(f"{a}-{m.lower()[:3]}")
    return out


_RX_PER_REF = re.compile(r"per[ií]odo[^\n0-9]{0,40}?(?:[^\n]{0,40}?\s)?(\d{1,2}/\d{1,2}/(?:20)?\d{2})(?!\d)", re.I)


def periodo_de_referencia(texto: str) -> str | None:
    """1ª data depois de "Período" no corpo (início do período da medição), normalizada AAAA-MM-DD. É o que o
    cabeçalho do relatório declara; o mesmo início em dois documentos = a mesma medição juntada duas vezes."""
    for m in _RX_PER_REF.finditer(texto or ""):
        d, mes, a = m.group(1).split("/")
        if 1 <= int(mes) <= 12 and 1 <= int(d) <= 31:
            return f"{a if len(a) == 4 else '20' + a}-{int(mes):02d}-{int(d):02d}"
    return None


def _manifesto(slug: str, _cache: dict = {}) -> dict[int, dict]:  # noqa: B006 — cache de propósito
    if slug not in _cache:
        if len(_cache) > 64:
            _cache.clear()
        _cache[slug] = _ler_manifesto(slug)
    return _cache[slug]


def _ler_manifesto(slug: str) -> dict[int, dict]:
    try:
        man = json.loads((ARQUIVO / slug / "manifest.json").read_text(encoding="utf-8", errors="ignore"))
    except (OSError, ValueError):
        return {}
    return {int(x["i"]): x for x in man.get("docs") or [] if isinstance(x, dict) and str(x.get("i", "")).isdigit()}


def _texto_do_doc(slug: str, d: dict) -> str:
    rel = d.get("texto")
    if not rel:
        return ""
    try:
        s = (ARQUIVO / slug / rel).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    return s.split("\n", 1)[1] if s.startswith("[") else s     # 1ª linha = etiqueta do acervo (título)


def info_documento(slug: str, i: int | None, _cache: dict = {}) -> dict:  # noqa: B006 — cache de propósito
    if (slug, i) in _cache:
        return _cache[(slug, i)]
    from compliance_agent.sei import reuso_documento_execucao as R
    d = _manifesto(slug).get(i, {}) if i is not None else {}
    titulo = str(d.get("titulo") or "")
    texto = _texto_do_doc(slug, d) if d else ""
    corpo = re.sub(r"\s+", " ", re.sub(r"\d{6,}", "", texto)).strip().lower()
    m = _RX_SEI_DOC.search(titulo)
    fase, tipo = R.classificar_doc(d) if d else ("", "")
    med = numero_medicao(titulo)
    if med is None and (mt := _RX_MED_TEXTO.search(texto[:3000])):
        med = int(mt.group(1))
    out = {"titulo": titulo, "medicao": med, "sei": m.group(1) if m else None,
           "fase": fase, "tipo": tipo, "texto_md5": hashlib.md5(corpo.encode()).hexdigest() if len(corpo) > 200 else None,
           "periodos": sorted(periodos_do_texto(texto)), "trecho": _trecho_periodo(texto),
           "periodo_ref": periodo_de_referencia(texto)}
    _cache[(slug, i)] = out
    return out


def _trecho_periodo(texto: str) -> str:
    """A linha que declara o período/medição — é ela que o porquê cita."""
    for ln in (texto or "").splitlines():
        if re.search(r"per[ií]odo|medi[çc][ãa]o\s*[-–:]|\d+\s*[ªº°]\s*medi", ln, re.I) and not _RX_ASSINATURA.search(ln):
            return re.sub(r"\s+", " ", ln).strip()[:220]
    return ""


def _contratos(slug: str, _cache: dict = {}) -> set[str]:  # noqa: B006
    if slug not in _cache:
        from compliance_agent.sei import reuso_documento_execucao as R
        _cache[slug] = set(R.contratos_do_processo(ARQUIVO / slug)[:6])
    return _cache[slug]


def classificar(g: dict) -> dict:
    """Regra AUTOMÁTICA (determinística, a partir do manifesto e do texto). Ordem = da explicação mais forte para a
    mais fraca; o que nenhuma explica fica `a_conferir` e vai para a conferência a olho (`VEREDITOS`)."""
    oc = g["ocorrencias"]
    docs = {(o["processo"], o["doc"]): info_documento(o["processo"], o["doc"]) for o in oc}
    tit = "; ".join(sorted({f"{p} doc {i}: “{d['titulo']}”" for (p, i), d in docs.items()})[:4])
    seis = {d["sei"] for d in docs.values()}
    if len(seis) == 1 and None not in seis:
        return {"regra": "R1_mesmo_documento_sei", "classe": "inocente-comprovada", "trecho": tit,
                "porque": f"o MESMO documento SEI nº {next(iter(seis))} juntado em mais de um lugar — cópia, não 2ª prova"}
    md5 = {d["texto_md5"] for d in docs.values()}
    if len(md5) == 1 and None not in md5:
        return {"regra": "R4_texto_identico", "classe": "inocente-provável", "trecho": tit,
                "porque": "o texto inteiro dos documentos é idêntico: é o mesmo relatório reapresentado (a foto não "
                          "prova um 2º período; se o 2º pagamento dependia de relatório próprio, isso é outra apuração)"}
    if all(d["titulo"] for d in docs.values()) and not any(d["fase"] == "execucao" for d in docs.values()):
        tipos = sorted({d["tipo"] or "?" for d in docs.values()})
        return {"regra": "R2_nao_execucao", "classe": "inocente-provável", "trecho": tit,
                "porque": f"nenhuma cópia está em documento de execução/medição (tipos: {', '.join(tipos)}) — "
                          "documento da empresa/órgão (habilitação, programa, certidão) juntado em vários processos"}
    meds = {d["medicao"] for d in docs.values()}
    procs = sorted({p for p, _ in docs})
    cs = [_contratos(p) for p in procs]
    mesmo_ctr = len(procs) == 1 or (all(cs) and bool(set.intersection(*cs)))
    if None not in meds and len(meds) == 1 and mesmo_ctr:
        return {"regra": "R3_mesma_medicao", "classe": "inocente-comprovada", "trecho": tit,
                "porque": f"todas as cópias são da MESMA medição (nº {next(iter(meds))}) do mesmo contrato — o "
                          "relatório anexado ao boletim e repetido no parecer/anexo, não outro período"}
    refs = {d["periodo_ref"] for d in docs.values()}
    if len(refs) == 1 and None not in refs and (len(procs) == 1 or mesmo_ctr):
        return {"regra": "R6_mesmo_periodo_de_referencia", "classe": "inocente-comprovada", "trecho": tit,
                "porque": f"todas as cópias declaram o MESMO período de referência (início {next(iter(refs))}): é a "
                          "mesma medição juntada de novo (prévia, retificação, reenvio), não um 2º período"}
    if g.get("todos_mapa"):
        # NÃO inocenta: em 18/11/2026 um sorteio de 8 destes grupos achou 6 FOTOS DE OBRA (faixas de fotos e fotos
        # sem céu, de chão/interior) e 2 mapas; com ≥ 5 documentos, 4 de 10 não eram mapa nem modelo. Fica PENDENTE.
        return {"regra": "R5_sem_ceu_nao_conferido", "classe": None, "trecho": tit,
                "porque": "nenhuma cópia tem céu (`foto_medicao.parece_mapa`): costuma ser mapa de satélite, capa ou "
                          "cabeçalho repetido por modelo, MAS também foto de obra sem céu (chão, interior, close) — "
                          "PENDENTE de conferência a olho; não é veredito de inocência"}
    pers = {k: d["periodos"] for k, d in docs.items() if d["periodos"]}
    distintos = len({tuple(v) for v in pers.values()}) > 1
    return {"regra": "a_conferir", "classe": None, "trecho": tit,
            "medicoes": sorted(m for m in meds if m is not None), "mesmo_contrato": mesmo_ctr,
            "periodos_de_referencia": sorted(r for r in refs if r),
            "periodos_distintos_no_texto": distintos,
            "trechos_periodo": sorted({d["trecho"] for d in docs.values() if d["trecho"]})[:4],
            "porque": ("cópias em medições/períodos DIFERENTES" if len(meds - {None}) > 1 or distintos
                       else "período de cada cópia não declarado no título — ler a página")}


def _veredito(g: dict, vereditos: list[dict]) -> dict | None:
    """Conferência a olho (arquivo `VEREDITOS`): 1ª regra cujo `processo` e `docs` cobrem TODAS as ocorrências."""
    chaves = {(o["processo"], o["doc"]) for o in g["ocorrencias"]}
    pagina = any(o.get("regiao") == 0 for o in g["ocorrencias"])
    for v in vereditos:
        alvo = v.get("docs")      # {"processo": [i, ...]} — ausente = qualquer documento do(s) processo(s)
        if "pagina_inteira" in v and v["pagina_inteira"] != pagina:   # mapa/capa (página inteira) × foto recortada
            continue
        # `ocorrencias`: as fotos EXATAS ("arquivo#região") que foram olhadas. Grupo novo (outra foto no mesmo documento)
        # não herda veredito de grupo vizinho — volta para "a_conferir". Medido em 18/11/2026: com o veredito só por
        # documento, fotos de obra (quadro elétrico, tubulação) herdavam "objeto estático" do contêiner da mesma página.
        if "ocorrencias" in v and not {f"{o['arquivo']}#{o.get('regiao')}" for o in g["ocorrencias"]} <= set(v["ocorrencias"]):
            continue
        if all(p in v["processos"] and (alvo is None or p not in alvo or i in alvo[p]) for p, i in chaves):
            return v
    return None


def anotar(r: dict) -> dict:
    """Título, nº da medição, período e o PORQUÊ de cada grupo + objeto/órgão de cada processo."""
    slugs = {p for g in r["grupos"] for p in g["processos"]}
    ctx = _contexto(slugs)
    try:
        vereditos = json.loads(VEREDITOS.read_text(encoding="utf-8")).get("vereditos", [])
    except (OSError, ValueError):
        vereditos = []
    for g in r["grupos"]:
        for o in g["ocorrencias"]:
            d = info_documento(o["processo"], o["doc"])
            o["documento"], o["medicao"] = d["titulo"], d["medicao"]
        g["processos_ctx"] = [ctx.get(p, {"numero": p}) for p in g["processos"]]
        g["n_ugs"] = len({ctx.get(p, {}).get("ug") for p in g["processos"]})
        g["medicoes"] = sorted({o["medicao"] for o in g["ocorrencias"] if o["medicao"] is not None})
        g["porque"] = classificar(g)
        if g["porque"]["regra"] == "a_conferir":
            v = _veredito(g, vereditos)
            if v:
                g["porque"].update({"regra": "conferido_a_olho", "classe": v["classe"], "porque": v["porque"],
                                    "trecho": v["trecho"], "caso": v.get("caso"), "gravidade": v.get("gravidade")})
    return r


def rodar(workers: int = 1) -> dict:
    """Tudo, local: índice → grupos → anotação → `SAIDA`. Mantém o formato antigo (grupos entre processos em
    `grupos`, com `processos` = contexto) e acrescenta `grupos_entre_documentos`."""
    t0 = time.time()
    dirs = _processos_com_foto()
    idx = indexar(dirs, workers)
    return laudo(agrupar(idx), idx["arquivos_por_processo"], len({it["processo"] for it in idx["itens"]}),
                 len(idx["itens"]), t0)


def laudo(r: dict, arquivos_por_processo: dict, com_foto: int, n_fotos: int, t0: float | None = None) -> dict:
    """Grupos (de `agrupar`, local ou vindos de outra máquina) → porquê → `SAIDA`."""
    t0 = t0 or time.time()
    r = anotar(r)
    entre_proc = [g for g in r["grupos"] if g["n_processos"] > 1]
    entre_doc = [g for g in r["grupos"] if g["n_processos"] == 1]
    for g in entre_proc:
        g["processos"] = g.pop("processos_ctx")
    entre_proc.sort(key=lambda g: (-g["n_ugs"], -g["n_processos"]))
    todos = entre_proc + entre_doc
    funil = dict(r["funil"])
    funil["por_regra"] = dict(Counter(g["porque"]["regra"] for g in todos))
    funil["por_classe"] = dict(Counter(str(g["porque"]["classe"]) for g in todos))
    reais = [g for g in todos if g["porque"]["classe"] in ("contradição", "sem-explicação")]
    out = {"grau": "vermelho" if reais else ("amarelo" if any(g["porque"]["classe"] is None for g in todos)
                                             else ("verde" if n_fotos else "nao_aplicavel")),
           "n_grupos": len(entre_proc), "grupos": entre_proc, "grupos_entre_documentos": entre_doc,
           "n_fotos": n_fotos, "funil": funil,
           "cobertura": {"processos_com_arquivo": len(arquivos_por_processo), "com_foto_utilizavel": com_foto,
                         "arquivos": sum(arquivos_por_processo.values())},
           "gerado_em": datetime.now().isoformat(timespec="seconds"), "segundos": round(time.time() - t0, 1),
           "processos_examinados": len(arquivos_por_processo), "ressalva": FM._RESSALVA}
    tmp = SAIDA.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(SAIDA)
    return out


def main(argv=None) -> int:
    global ARQUIVO
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    a = sub.add_parser("indexar")
    a.add_argument("--raiz", type=Path, default=ARQUIVO)
    a.add_argument("--saida", type=Path, required=True)
    a.add_argument("--workers", type=int, default=1)
    b = sub.add_parser("agrupar")
    b.add_argument("--indice", type=Path, required=True)
    b.add_argument("--saida", type=Path, required=True)
    c = sub.add_parser("laudo")
    c.add_argument("--grupos", type=Path, required=True)
    c.add_argument("--resumo-indice", type=Path, required=True, help="json: arquivos_por_processo, com_foto, n_fotos")
    args = ap.parse_args(argv)
    if args.cmd == "indexar":
        ARQUIVO = args.raiz
        idx = indexar(_processos_com_foto(), args.workers, log=lambda m: print(m, flush=True))
        args.saida.write_bytes(pickle.dumps(idx))
        args.saida.with_suffix(".resumo.json").write_text(json.dumps({
            "arquivos_por_processo": idx["arquivos_por_processo"], "n_fotos": len(idx["itens"]),
            "com_foto": len({it["processo"] for it in idx["itens"]})}), encoding="utf-8")
        print(f"{len(idx['arquivos_por_processo'])} processos · {sum(idx['arquivos_por_processo'].values())} arquivos "
              f"· {len(idx['itens'])} regiões de foto")
        return 0
    if args.cmd == "agrupar":
        r = agrupar(pickle.loads(args.indice.read_bytes()))
        args.saida.write_bytes(pickle.dumps(r))
        print(json.dumps(r["funil"], ensure_ascii=False))
        return 0
    if args.cmd == "laudo":
        ri = json.loads(args.resumo_indice.read_text(encoding="utf-8"))
        r = laudo(pickle.loads(args.grupos.read_bytes()), ri["arquivos_por_processo"], ri["com_foto"], ri["n_fotos"])
        print(json.dumps(r["funil"], ensure_ascii=False))
        return 0
    r = rodar()
    print(f"{r['processos_examinados']} processos com foto · {r['n_fotos']} fotos · {r['n_grupos']} grupo(s) entre "
          f"processos · {len(r['grupos_entre_documentos'])} entre documentos · {r['segundos']} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
