#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CONFERÊNCIA de toda entrega da VM-2 antes de entrar no acervo da VM-1 (pedido do dono, 13/11/2026:
"você precisa checar se o que está vindo da VM-2 está certo").

A VM-2 não escreve mais direto em `data/sei_arquivo/` nem em `data/sei_cache/`: ela deposita um LOTE em
`data/vm2_entrega/<lote>/` com um `MANIFESTO.json` (md5 de cada arquivo, status de cada processo, juízo do
Claude da VM-2 sobre uma amostra). Aqui, para cada processo do lote:

  1. md5 de TODOS os arquivos do processo contra o manifesto (faltou ou divergiu ⇒ reprovado);
  2. documentos do manifesto × árvore do processo (`docs + nao_capturados` tem de cobrir `total_arvore`/
     `docs_na_arvore`; no cache CDP, `conteudo_documentos` × `documentos`);
  3. texto NÃO VAZIO e LEGÍVEL (utf-8, proporção de letras) — a régua de 60% de documentos com teor é a
     mesma do `manifesto_norm.captura_integra`;
  4. AMOSTRA contra uma leitura INDEPENDENTE já existente na VM-1 (arquivo ou cache CDP do mesmo processo):
     títulos em comum e semelhança do texto dos documentos de mesmo título. Sem referência na VM-1, vale o
     juízo do Claude da VM-2 (legível e compatível com o título) — e o relatório diz que foi só isso.

Aprovado ⇒ entra no acervo (o que existia vai para `data/vm2_entrega/_substituidos/`, reversível) e as linhas
"proc: ok" entram no `data/sei_integra_fila.log` (o efeito do motor `sei-integras` do AO VIVO). Reprovado ⇒
`data/vm2_quarentena/<lote>/` com `motivo.json`, e a linha do log vira `-quarentena`. Cada decisão vai para
`data/vm2_conferencia.log` (`CONFERÊNCIA <proc>: APROVADO|QUARENTENA …`).

Uso (VM-1):
    python -m tools.vm2_conferencia importar <lote>        # chamado pela VM-2 depois do rsync
    python -m tools.vm2_conferencia pendentes              # reaplica progresso adiado (sweep da VM-1 rodando)
    python -m tools.vm2_conferencia reconferir <tag> …     # confere pastas já no acervo (entregas antigas)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

DATA = RAIZ / "data"
ENTREGA = DATA / "vm2_entrega"
QUARENTENA = DATA / "vm2_quarentena"
SUBST = ENTREGA / "_substituidos"
IMPORTADOS = ENTREGA / "_importados"
LOG = DATA / "vm2_conferencia.log"
LOG_FILA = DATA / "sei_integra_fila.log"
ARQUIVO = DATA / "sei_arquivo"
CACHE = DATA / "sei_cache"

MIN_TEOR = 0.60          # mesma régua do manifesto_norm.captura_integra
MIN_LETRAS = 0.40        # texto com menos de 40% de letras não é texto legível (lixo de OCR, binário)
MIN_TITULOS = 0.50       # da leitura de referência, ao menos metade dos títulos tem de reaparecer
MIN_SEMELHANCA = 0.50    # semelhança mínima (tokens) do texto de documentos de mesmo título
_RX_STATUS = re.compile(r"^\[[^\]]+\]\s+(\d{6}/\d{6}/\d{4}): (\w+)\s*$")


def _log(msg: str) -> None:
    linha = f"[{time.strftime('%F %T')}] {msg}"
    print(linha, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(linha + "\n")


def _md5(p: Path) -> str:
    h = hashlib.md5()
    with p.open("rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def _ler_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _int(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def legivel(texto: str) -> bool:
    t = (texto or "").strip()
    if len(t) < 40:
        return False
    letras = sum(1 for c in t if c.isalpha())
    return letras / max(1, len(t)) >= MIN_LETRAS


_RX_CABECALHO = re.compile(r"^\s*\[[^\]\n]*\](?:\s*\([^)\n]*\))?\s*$", re.M)


def _sem_cabecalho(texto: str) -> str:
    """Tira as linhas de cabeçalho que o arquivador põe ("[Título] (fase: … · tipo: …)" e "[Título]")."""
    return _RX_CABECALHO.sub("", texto or "")


def _tokens(texto: str) -> set[str]:
    return {w for w in re.findall(r"[a-zà-ú0-9]{3,}", (texto or "").lower()[:4000])}


def semelhanca(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _norm_titulo(t: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9à-ú ]", " ", (t or "").lower())).strip()


# ───────────────────────── referência independente já existente na VM-1 ─────────────────────────

def _arq_txt(d: dict) -> str:
    """Nome do .txt de um documento do manifesto (`texto: "texto/000_x.txt"`)."""
    v = str(d.get("texto") or "")
    return Path(v).name if v.endswith(".txt") else ""


def _referencia(tag: str, incluir_arquivo: bool = True) -> dict[str, str]:
    """{título normalizado: texto} de uma leitura da VM-1 do mesmo processo: o arquivo atual (antes de
    substituir) ou o cache CDP (.json/.json.zst). Vazio = não há referência independente."""
    ref: dict[str, str] = {}
    pasta = ARQUIVO / tag
    man = _ler_json(pasta / "manifest.json") if incluir_arquivo else None
    if isinstance(man, dict) and man.get("docs"):
        for d in man["docs"]:
            if not isinstance(d, dict):
                continue
            txt = ""
            arq = _arq_txt(d)
            if arq and (pasta / "texto" / arq).exists():
                txt = (pasta / "texto" / arq).read_text(encoding="utf-8", errors="replace")
            if txt:
                ref.setdefault(_norm_titulo(d.get("titulo", "")), txt)
        if not ref and incluir_arquivo and (pasta / "texto").is_dir():
            for f in sorted((pasta / "texto").glob("*.txt"))[:200]:
                ref.setdefault(_norm_titulo(f.stem.split("_", 1)[-1].replace("_", " ")),
                               f.read_text(encoding="utf-8", errors="replace"))
    if ref:
        return ref
    try:
        from compliance_agent.sei.cache_arquivo import localizar, ler_json
        cf = localizar(CACHE / f"cdp_SEI_{tag}.json")
        c = ler_json(cf) if cf else None
    except (ImportError, OSError, ValueError):   # referência é opcional: sem ela, a conferência diz que não houve
        c = None
    if isinstance(c, dict):
        for d in c.get("conteudo_documentos") or []:
            if isinstance(d, dict) and d.get("conteudo") and not d.get("_trimado"):
                ref.setdefault(_norm_titulo(d.get("titulo") or d.get("doc") or ""), str(d["conteudo"]))
    return ref


def _titulo_correspondente(t: str, novos: dict[str, str]) -> str | None:
    """O título novo que corresponde ao da referência: igual, ou o antigo é o COMEÇO do novo. 15/11/2026: a leitura de
    julho guardava títulos genéricos ("despacho") e a de hoje os completos ("despacho de encaminhamento de processo 1");
    exigir igualdade mandou à quarentena uma captura 63/63 correta."""
    if t in novos:
        return t
    if re.fullmatch(r"\d{7,}", t):
        # 18/11/2026: leituras antigas guardaram como título só o NÚMERO SEI do documento ("134062161"); a de hoje
        # traz "despacho de formalização de liquidação de despesa 134062161". O número é único no SEI — casa pelo
        # número (o texto ainda é comparado adiante). Sem isto: "só 0/6 títulos reaparecem" e quarentena.
        return next((n for n in sorted(novos) if t in n.split()), None)
    return next((n for n in sorted(novos) if n.startswith(t + " ")), None)


def comparar_com_referencia(novos: dict[str, str], ref: dict[str, str]) -> tuple[bool | None, str]:
    """None = sem referência. Compara títulos e o texto de até 3 documentos de mesmo título."""
    if not ref:
        return None, "sem leitura independente na VM-1"
    titulos_ref = {t for t in ref if t}
    if not titulos_ref:
        # leitura antiga com texto mas SEM título (chave ""): nada a comparar ≠ divergência. 21/11/2026: 11 íntegras
        # completas (291/291 docs) iam à quarentena com "só 0/0 títulos" e voltavam à fila para recaptura igual.
        return None, "leitura da VM-1 sem títulos para comparar"
    par = {t: c for t in titulos_ref if (c := _titulo_correspondente(t, novos))}
    comuns = list(par)
    cobertura = len(comuns) / max(1, len(titulos_ref))
    if cobertura < MIN_TITULOS:
        return False, f"só {len(comuns)}/{len(titulos_ref)} títulos da leitura da VM-1 reaparecem"
    # Só referência com CORPO conta: a leitura antiga às vezes guardou só o cabeçalho "[Título] (fase: … · tipo: …)",
    # que tem letras e passava no `legivel` — 18/11/2026: 44% das íntegras do it-campo iam à quarentena por isso.
    sims = [semelhanca(novos[par[t]], ref[t]) for t in comuns
            if legivel(_sem_cabecalho(ref[t])) and legivel(_sem_cabecalho(novos[par[t]]))][:3]
    if sims and max(sims) < MIN_SEMELHANCA:
        return False, f"texto diverge da leitura da VM-1 (semelhança máx {max(sims):.2f})"
    return True, (f"{len(comuns)}/{len(titulos_ref)} títulos em comum com a VM-1"
                  + (f", semelhança {min(sims):.2f}–{max(sims):.2f}" if sims else ""))


# ───────────────────────── conferência de uma pasta de íntegra ─────────────────────────

def conferir_integra(pasta_arq: Path, status: str, tag: str, juizo: dict | None,
                     ref_do_arquivo: bool = True, com_referencia: bool = True) -> tuple[bool, list[str], dict]:
    """(aprovado, motivos de reprovação, métricas) de um arquivo de íntegra (`arquivo/<tag>/`).
    `com_referencia=False` (23/11/2026): o NÓ pré-confere antes de entregar e não tem leitura independente — a
    comparação com a leitura da VM-1 só pode ser feita na VM-1 (`preconferir`/`conferir_barata`)."""
    motivos: list[str] = []
    m = _ler_json(pasta_arq / "manifest.json")
    if not isinstance(m, dict):
        return False, ["manifesto ilegível ou ausente"], {}
    docs = [d for d in (m.get("docs") or []) if isinstance(d, dict)]
    n = len(docs)
    total = _int(m.get("total_arvore")) or _int(m.get("docs_na_arvore"))
    declarados = _int(m.get("nao_capturados"))
    met = {"docs": n, "arvore": total or None, "nao_capturados": declarados}
    if status != "ok":                      # vazio / sem árvore: o manifesto tem de DIZER isso
        if n and not m.get("captura_vazia"):
            motivos.append(f"status '{status}' mas o manifesto lista {n} documento(s)")
        return not motivos, motivos, met
    if n == 0:
        return False, ["status ok com zero documento"], met
    if total and n + declarados < total:
        motivos.append(f"árvore tem {total} documento(s), manifesto cobre {n}+{declarados} declarados")
    textos: dict[str, str] = {}
    pasta_txt = pasta_arq / "texto"
    arquivos_txt = sorted(pasta_txt.glob("*.txt")) if pasta_txt.is_dir() else []
    for f in arquivos_txt:
        try:
            textos[f.name] = f.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            motivos.append(f"{f.name} não é utf-8")
    com_teor = sum(1 for d in docs if _int(d.get("chars")) >= 40)
    legiveis = sum(1 for t in textos.values() if legivel(t))
    met.update({"com_teor": com_teor, "txt": len(arquivos_txt), "txt_legiveis": legiveis})
    if com_teor / n < MIN_TEOR:
        motivos.append(f"só {com_teor}/{n} documentos com teor (< {MIN_TEOR:.0%})")
    if arquivos_txt and legiveis / len(arquivos_txt) < MIN_TEOR:
        motivos.append(f"só {legiveis}/{len(arquivos_txt)} textos legíveis")
    if not arquivos_txt:
        motivos.append("pasta texto/ vazia")
    # amostra × leitura independente
    novos: dict[str, str] = {}
    for d in docs:
        arq = _arq_txt(d)
        if arq and arq in textos:
            novos.setdefault(_norm_titulo(d.get("titulo", "")), textos[arq])
    if not novos:
        for nome, t in textos.items():
            novos.setdefault(_norm_titulo(nome[:-4].split("_", 1)[-1].replace("_", " ")), t)
    if not com_referencia:
        return not motivos, motivos, met
    ok_ref, nota = comparar_com_referencia(novos, _referencia(tag, incluir_arquivo=ref_do_arquivo))
    met["referencia"] = nota
    if ok_ref is False:
        motivos.append(nota)
    if juizo:
        met["juizo_claude"] = {k: juizo.get(k) for k in ("legivel", "corresponde", "motivo", "modelo")}
        if juizo.get("legivel") is False or juizo.get("corresponde") is False:
            motivos.append(f"juízo do Claude (VM-2): {str(juizo.get('motivo') or 'reprovado')[:120]}")
    return not motivos, motivos, met


# ───────────────────────── conferência BARATA: o nó lê, a VM-1 confere a conta (23/11/2026) ─────────────────────────
#
# Pedido do dono (23/11/2026): "leva a conferência e arquivamento pra VM-2". O ARQUIVAMENTO (PDF → texto + OCR) já
# acontece no nó desde 13/11 (`sei_integra_fila._baixar_e_arquivar` roda `sei_arquivar.py` lá; medido nos lotes de
# 16–23/11: 100% das entregas de íntegra chegam com `arquivo/<tag>/texto/*.txt`, e o `arquivar_integra_lane` da VM-1
# arquivou 0 pendentes em todas as rodadas da semana). O que ainda se repetia aqui era a LEITURA de todo .txt de todo
# processo para medir teor/legibilidade — o nó já tem esses textos na mão. Agora o nó mede (`preconferir`) e manda o
# resultado no MANIFESTO; a VM-1 continua com o que só ela pode fazer: md5 de cada arquivo (o que chegou é o que o nó
# mediu), conta do manifesto, AMOSTRA pequena de textos relida aqui (o nó pode errar) e a leitura independente.
# Desligado por padrão; liga com `touch data/.vm2_conferencia_barata` (ou JFN_VM2_CONFERENCIA=barata|completa, que
# manda sobre o arquivo). Lote sem `preconferencia` (nó com código velho) cai sozinho na conferência completa.

PRE_VERSAO = 1
FLAG_BARATA = DATA / ".vm2_conferencia_barata"
AMOSTRA_TEXTOS = 3            # textos relidos na VM-1 por processo — o bastante para pegar erro SISTEMÁTICO do nó
MAX_ILEGIVEIS_LISTADOS = 500  # acima disso a lista não vai no manifesto e a amostra sorteia entre todos com teor
TEXTOS_REFERENCIA = 6         # textos lidos para a comparação com a leitura da VM-1 (ela usa até 3 semelhanças)


def barata_ligada() -> bool:
    modo = os.environ.get("JFN_VM2_CONFERENCIA", "").strip().lower()
    if modo in ("barata", "completa"):
        return modo == "barata"
    return FLAG_BARATA.exists()


def preconferir(pasta_arq: Path, status: str) -> dict:
    """Lado do NÓ (VM-2/it-campo), antes de montar o lote: as mesmas réguas de `conferir_integra` (teor, árvore,
    legibilidade de TODO .txt), sem a leitura independente — essa só existe na VM-1. Vai no MANIFESTO como
    `processos[proc]["preconferencia"]`; os .txt que o nó julgou ilegíveis vão listados para a VM-1 sortear a
    amostra entre os que ele disse legíveis (um "legível" que não é ⇒ o nó errou ⇒ quarentena)."""
    ok, motivos, met = conferir_integra(pasta_arq, status, pasta_arq.name, None, com_referencia=False)
    ilegiveis: list[str] = []
    pasta_txt = pasta_arq / "texto"
    for f in sorted(pasta_txt.glob("*.txt")) if pasta_txt.is_dir() else []:
        try:
            if not legivel(f.read_bytes().decode("utf-8")):
                ilegiveis.append(f.name)
        except (OSError, UnicodeDecodeError):
            ilegiveis.append(f.name)
    pre = {"versao": PRE_VERSAO, "aprovado": ok, "motivos": motivos, "metricas": met,
           "em": time.strftime("%F %T"), "no": os.uname().nodename}
    if len(ilegiveis) <= MAX_ILEGIVEIS_LISTADOS:
        pre["ilegiveis"] = ilegiveis
    return pre


def conferir_barata(pasta_arq: Path, status: str, tag: str, juizo: dict | None,
                    pre: dict) -> tuple[bool, list[str], dict]:
    """Lado da VM-1 com `preconferencia` do nó. Lê só o `manifest.json`, `AMOSTRA_TEXTOS` textos e, se houver leitura
    independente, os textos de até `TEXTOS_REFERENCIA` documentos de mesmo título. O md5 de TODOS os arquivos contra o
    MANIFESTO do lote continua antes disto (`_importar`) — é ele que garante que a pré-conferência fala destes bytes."""
    m = _ler_json(pasta_arq / "manifest.json")
    if not isinstance(m, dict):
        return False, ["manifesto ilegível ou ausente"], {"conferencia": "barata"}
    docs = [d for d in (m.get("docs") or []) if isinstance(d, dict)]
    n = len(docs)
    total = _int(m.get("total_arvore")) or _int(m.get("docs_na_arvore"))
    declarados = _int(m.get("nao_capturados"))
    met: dict = {"docs": n, "arvore": total or None, "nao_capturados": declarados, "conferencia": "barata"}
    motivos: list[str] = []
    pm = pre.get("metricas") if isinstance(pre.get("metricas"), dict) else {}
    # 1. a pré-conferência tem de falar do MESMO manifesto (nó com bug ou lote remontado à mão não passam)
    for k in ("docs", "arvore", "nao_capturados"):
        if _int(pm.get(k)) != _int(met[k]):
            motivos.append(f"pré-conferência do nó não bate com o manifesto ({k}: {pm.get(k)} × {met[k]})")
    # 2. réguas que o manifesto sozinho responde — recalculadas aqui, não copiadas do nó
    if n == 0:
        return False, motivos + ["status ok com zero documento"], met
    if total and n + declarados < total:
        motivos.append(f"árvore tem {total} documento(s), manifesto cobre {n}+{declarados} declarados")
    com_teor = [d for d in docs if _int(d.get("chars")) >= 40]
    if len(com_teor) / n < MIN_TEOR:
        motivos.append(f"só {len(com_teor)}/{n} documentos com teor (< {MIN_TEOR:.0%})")
    # 3. o que só o nó leu inteiro: contagem de .txt (stat, sem ler) e a régua de legibilidade dele
    pasta_txt = pasta_arq / "texto"
    arquivos_txt = sorted(pasta_txt.glob("*.txt")) if pasta_txt.is_dir() else []
    n_txt, leg_no = _int(pm.get("txt")), _int(pm.get("txt_legiveis"))
    met.update({"com_teor": len(com_teor), "txt": len(arquivos_txt), "txt_legiveis_no": leg_no})
    if not arquivos_txt:
        motivos.append("pasta texto/ vazia")
    elif len(arquivos_txt) != n_txt:
        motivos.append(f"{len(arquivos_txt)} .txt na pasta, a pré-conferência leu {n_txt}")
    elif leg_no / len(arquivos_txt) < MIN_TEOR:
        motivos.append(f"só {leg_no}/{len(arquivos_txt)} textos legíveis (pré-conferência do nó)")
    vazios = [d for d in com_teor if _arq_txt(d) and (pasta_txt / _arq_txt(d)).is_file()
              and (pasta_txt / _arq_txt(d)).stat().st_size < 40]
    if vazios:
        motivos.append(f"{len(vazios)} documento(s) com teor no manifesto e .txt vazio (ex.: {_arq_txt(vazios[0])})")
    if pre.get("aprovado") is False:
        motivos += [f"nó: {x}" for x in (pre.get("motivos") or ["reprovado na pré-conferência"])][:5]
    # 4. amostra relida AQUI, entre os que o nó disse legíveis, espalhada pela árvore (não só os maiores)
    ilegiveis = set(pre.get("ilegiveis") or []) if isinstance(pre.get("ilegiveis"), list) else None
    candidatos = [p for d in com_teor if (a := _arq_txt(d)) and (p := pasta_txt / a).is_file()
                  and (ilegiveis is None or a not in ilegiveis)]
    passo = max(1, len(candidatos) // AMOSTRA_TEXTOS)
    amostra_txt = candidatos[::passo][:AMOSTRA_TEXTOS]
    ruins = []
    for p in amostra_txt:
        try:
            if not legivel(p.read_bytes().decode("utf-8")):
                ruins.append(p.name)
        except (OSError, UnicodeDecodeError):
            ruins.append(p.name)
    met["amostra_vm1"] = f"{len(amostra_txt) - len(ruins)}/{len(amostra_txt)} legíveis"
    # com a lista do nó, um "legível" que não é = o nó errou; sem ela, só a maioria ilegível reprova
    if ruins and (ilegiveis is not None or len(ruins) * 2 > len(amostra_txt)):
        motivos.append(f"amostra relida na VM-1: {', '.join(ruins[:3])} ilegível(is), o nó disse legível")
    # 5. leitura independente da VM-1: títulos do manifesto, texto só dos que casam (preguiçoso)
    ref = _referencia_preguicosa(tag, docs)
    novos: dict[str, str] = {}
    caminhos: dict[str, Path] = {}
    for d in docs:
        t = _norm_titulo(d.get("titulo", ""))
        if t not in novos:
            novos[t] = ""
            if _arq_txt(d):
                caminhos[t] = pasta_txt / _arq_txt(d)
    lidos = 0
    for t in ref:
        c = _titulo_correspondente(t, novos) if t else None
        if c and lidos < TEXTOS_REFERENCIA and c in caminhos and caminhos[c].is_file() \
                and legivel(_sem_cabecalho(ref[t])):
            novos[c] = caminhos[c].read_text(encoding="utf-8", errors="replace")
            lidos += 1
    ok_ref, nota = comparar_com_referencia(novos, ref)
    met["referencia"] = nota
    if ok_ref is False:
        motivos.append(nota)
    if juizo:
        met["juizo_claude"] = {k: juizo.get(k) for k in ("legivel", "corresponde", "motivo", "modelo")}
        if juizo.get("legivel") is False or juizo.get("corresponde") is False:
            motivos.append(f"juízo do Claude (VM-2): {str(juizo.get('motivo') or 'reprovado')[:120]}")
    return not motivos, motivos, met


def _referencia_preguicosa(tag: str, docs_novos: list[dict]) -> dict[str, str]:
    """Como `_referencia`, mas do arquivo atual da VM-1 só lê o TEXTO dos documentos cujo título casa com a entrega
    (até `TEXTOS_REFERENCIA` com corpo); os demais entram só pelo título (texto "" — `comparar_com_referencia` mede a
    cobertura por título e a semelhança só de quem tem corpo legível). Medido em 23/11/2026 em 60 entregas reais: ler
    TODA a referência custava ~0,22 s por processo, 4× o resto da conferência. Sem `docs` no manifesto antigo (ou sem
    arquivo), vale o `_referencia` de sempre (pasta solta ou cache CDP)."""
    pasta = ARQUIVO / tag
    man = _ler_json(pasta / "manifest.json")
    if not (isinstance(man, dict) and man.get("docs")):
        return _referencia(tag)
    novos = dict.fromkeys((_norm_titulo(d.get("titulo", "")) for d in docs_novos), "")
    ref: dict[str, str] = {}
    lidos = 0
    for d in man["docs"]:
        if not isinstance(d, dict) or not (arq := _arq_txt(d)):
            continue
        p = pasta / "texto" / arq
        try:
            if p.stat().st_size == 0:      # `_referencia` só conta título COM texto: o denominador tem de ser o mesmo
                continue
        except OSError:
            continue
        t = _norm_titulo(d.get("titulo", ""))
        if ref.get(t):
            continue
        txt = ""
        if lidos < TEXTOS_REFERENCIA and _titulo_correspondente(t, novos):
            txt = p.read_text(encoding="utf-8", errors="replace")
            lidos += legivel(_sem_cabecalho(txt))
        ref[t] = txt
    if not ref:
        # nenhum texto no arquivo antigo: `_referencia` também não o usaria (só conta quem tem texto) — cai no cache CDP
        return _referencia(tag)
    return ref


def _conferir_entrega_integra(pasta: Path, status: str, tag: str, info: dict) -> tuple[bool, list[str], dict]:
    """Escolhe a conferência: barata quando ligada E o nó mandou pré-conferência desta versão; senão a completa."""
    pre = info.get("preconferencia")
    if barata_ligada() and status == "ok" and isinstance(pre, dict) and pre.get("versao") == PRE_VERSAO:
        return conferir_barata(pasta, status, tag, info.get("juizo"), pre)
    return conferir_integra(pasta, status, tag, info.get("juizo"))


# ───────────────────────── conferência de um cache CDP (sweep geral) ─────────────────────────

def conferir_cdp(caminho: Path, juizo: dict | None) -> tuple[bool, list[str], dict]:
    c = _ler_json(caminho)
    if not isinstance(c, dict):
        return False, ["cache ilegível"], {}
    arvore = [d for d in (c.get("documentos") or []) if d]
    conteudos = [d for d in (c.get("conteudo_documentos") or []) if isinstance(d, dict)]
    leg = sum(1 for d in conteudos if legivel(str(d.get("conteudo") or "")))
    met = {"arvore": len(arvore), "conteudos": len(conteudos), "legiveis": leg}
    motivos: list[str] = []
    if arvore and conteudos and leg == 0:
        motivos.append(f"{len(conteudos)} conteúdo(s) e nenhum legível")
    if len(conteudos) > len(arvore) + 5 and arvore:
        motivos.append(f"{len(conteudos)} conteúdos para {len(arvore)} documentos na árvore")
    tag = re.sub(r"^cdp_SEI_|\.json$", "", caminho.name)
    # títulos da ÁRVORE inteira, texto só dos que têm conteúdo: o sweep lê o teor de no máximo
    # SEI_MAX_DOCS (40) documentos — comparar só esses 40 com a árvore de 105 da VM-1 reprovou duas
    # entregas boas em 13/11 ("só 40/105 títulos reaparecem").
    novos = {_norm_titulo(d.get("titulo") or d.get("texto") or ""): "" for d in arvore if isinstance(d, dict)}
    novos.update({_norm_titulo(d.get("titulo") or d.get("doc") or ""): str(d.get("conteudo") or "")
                  for d in conteudos})
    ref = _referencia(tag)
    ok_ref, nota = comparar_com_referencia(novos, ref) if arvore else (None, "sem documentos")
    # o sweep TRIMA o conteúdo depois da ficha (400 chars): comparar títulos vale, o texto não
    met["referencia"] = nota
    if ok_ref is False and "títulos" in nota:
        motivos.append(nota)
    if juizo:
        met["juizo_claude"] = {k: juizo.get(k) for k in ("legivel", "corresponde", "motivo", "modelo")}
        if juizo.get("legivel") is False:
            motivos.append(f"juízo do Claude (VM-2): {str(juizo.get('motivo') or 'ilegível')[:120]}")
    return not motivos, motivos, met


# ───────────────────────── importação ─────────────────────────

def _substituir(origem: Path, destino: Path, lote: str) -> None:
    if destino.exists():
        SUBST.mkdir(parents=True, exist_ok=True)
        shutil.move(str(destino), str(SUBST / f"{destino.name}__{lote}"))
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(origem), str(destino))


def _quarentena(lote: str, origem: Path, motivos: list[str], met: dict) -> None:
    dst = QUARENTENA / lote / origem.name
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        shutil.rmtree(dst, ignore_errors=True)
    shutil.move(str(origem), str(dst))
    (QUARENTENA / lote / f"{origem.name}.motivo.json").write_text(
        json.dumps({"motivos": motivos, "metricas": met}, ensure_ascii=False, indent=1), encoding="utf-8")


def _md5_confere(base: Path, arquivos: dict[str, str], prefixos: tuple[str, ...]) -> list[str]:
    erros = []
    for rel, md5 in arquivos.items():
        if not rel.startswith(prefixos):
            continue
        p = base / rel
        if not p.exists():
            erros.append(f"faltou {rel}")
        elif _md5(p) != md5:
            erros.append(f"md5 divergente em {rel}")
    return erros


def _mesclar_progresso(delta: dict) -> None:
    """Mesma trava curta e mesma regra do `sei_sweep._salvar_prog` (mais novo vence por processo): um sweep
    vivo na VM-1 não apaga mais o que entra aqui, então a incorporação não espera a ausência de sweep."""
    import fcntl
    prog_arq = CACHE / "sei_sweep_progress.json"
    with prog_arq.with_name(prog_arq.name + ".lock").open("w") as trava:
        fcntl.flock(trava, fcntl.LOCK_EX)
        prog = _ler_json(prog_arq) or {"feitos": {}}
        fe = prog.setdefault("feitos", {})
        for k, v in delta.items():
            atual = fe.get(k) or {}
            if str(v.get("em") or "") >= str(atual.get("em") or ""):
                fe[k] = v
        tmp = prog_arq.with_name(f"{prog_arq.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(prog, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(prog_arq)


def _mesclar_restritos(delta: dict) -> None:
    arq = DATA / "sei_restritos.json"
    reg = _ler_json(arq) or {}
    for k, v in delta.items():
        if str((v or {}).get("ultima") or "") >= str((reg.get(k) or {}).get("ultima") or ""):
            reg[k] = v
    tmp = arq.with_name(f"{arq.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(arq)


_RX_RESTRITO_DECLARADO = re.compile(r"^\[[^\]]+\]\s+(\d{6}/\d{6}/\d{4}): SEM ÁRVORE .*RESTRITO: SEI diz '([^']*)'")


def registrar_restritos_declarados(linhas: list[str], origem: str = "") -> list[str]:
    """Processo que o PRÓPRIO SEI declarou restrito ("Unidade atual não possui acesso ao processo restrito …",
    registrado pela captura desde 13/11/2026) entra no registro da casa como RESTRITO confirmado
    (`tools/sei_restritos.seed`): sai das filas de captura (a conta tem UMA unidade — reabrir não traz documento) e
    entra na requisição formal (`tools/gerar_requisicoes.py`). Medido em 14/11/2026 no it-campo: os 15 primeiros
    processos da fila exportada eram todos assim, ~3 min de sessão cada, e voltavam a cada exportação."""
    procs = list(dict.fromkeys(m.group(1) for m in map(_RX_RESTRITO_DECLARADO.match, linhas) if m))
    if not procs:
        return []
    from tools import sei_restritos as R
    for proc in procs:
        R.seed(proc, motivo=f"SEI declarou: Unidade atual não possui acesso (captura de íntegra{', ' + origem if origem else ''})")
    _log(f"RESTRITOS declarados pelo SEI registrados: {len(procs)} ({', '.join(procs[:6])}{'…' if len(procs) > 6 else ''})")
    return procs


def importar(lote: str) -> dict:
    """Confere e importa um lote. Segura `data/.vm2_conferencia.lock` (flock) enquanto roda: é a `trava` do
    motor `vm2-conferencia` no AO VIVO, e impede duas importações ao mesmo tempo."""
    import fcntl
    with (DATA / ".vm2_conferencia.lock").open("w") as trava:
        fcntl.flock(trava, fcntl.LOCK_EX)
        return _importar(lote)


def _importar(lote: str) -> dict:
    base = ENTREGA / lote
    man = _ler_json(base / "MANIFESTO.json")
    if not isinstance(man, dict):
        _log(f"LOTE {lote}: MANIFESTO ausente/ilegível — nada importado")
        return {"lote": lote, "erro": "manifesto"}
    arquivos: dict = man.get("arquivos") or {}
    procs: dict = man.get("processos") or {}
    aprovados, reprovados = {}, {}
    if man.get("tipo") == "integras":
        for proc, info in procs.items():
            tag = proc.replace("/", "_")
            status = info.get("status", "")
            pref = (f"arquivo/{tag}/", f"cache/integra_{tag}/")
            erros = _md5_confere(base, arquivos, pref)
            pasta = base / "arquivo" / tag
            ok, motivos, met = (False, erros, {}) if erros else _conferir_entrega_integra(pasta, status, tag, info)
            if ok:
                _substituir(pasta, ARQUIVO / tag, lote)
                if (base / "cache" / f"integra_{tag}").is_dir():
                    _substituir(base / "cache" / f"integra_{tag}", CACHE / f"integra_{tag}", lote)
                aprovados[proc] = met
            else:
                if pasta.exists():
                    _quarentena(lote, pasta, motivos, met)
                if (base / "cache" / f"integra_{tag}").is_dir():
                    _quarentena(lote, base / "cache" / f"integra_{tag}", motivos, met)
                reprovados[proc] = motivos
            if ok and status == "ok" and str(met.get("referencia", "")).startswith("sem leitura"):
                enfileirar_amostra([proc], str(man.get("origem") or "?"))
            _log(f"CONFERÊNCIA {proc}: {'APROVADO' if ok else 'QUARENTENA'} [{status}] "
                 + json.dumps(met, ensure_ascii=False) + ("" if ok else f" motivos={motivos}"))
        # linhas do log da fila: só "ok" de quem foi APROVADO
        saida = [f"[{time.strftime('%F %T')}] {man.get('origem') or 'VM-2'}: lote {lote} conferido — {len(aprovados)} aprovado(s), "
                 f"{len(reprovados)} em quarentena (data/vm2_conferencia.log)"]
        for ln in man.get("linhas_log") or []:
            mm = _RX_STATUS.match(ln)
            if mm and mm.group(1) in reprovados:
                ln = ln.rstrip() + "-quarentena"
            elif mm and mm.group(1) in (man.get("nao_entregues") or {}):
                ln = ln.rstrip() + "-vm2-nao-entregue"
            saida.append(ln)
        with LOG_FILA.open("a", encoding="utf-8") as f:
            f.write("\n".join(saida) + "\n")
        registrar_restritos_declarados(man.get("linhas_log") or [], str(man.get("origem") or ""))
    elif man.get("tipo") == "sweep":
        for nome, info in procs.items():                  # nome = arquivo cdp_*.json
            erros = _md5_confere(base, arquivos, (f"cache/{nome}",))
            p = base / "cache" / nome
            ok, motivos, met = (False, erros, {}) if erros else conferir_cdp(p, info.get("juizo"))
            if not ok:
                _quarentena(lote, p, motivos, met)
                reprovados[nome] = motivos
            else:
                from compliance_agent.sei.cache_arquivo import localizar, ler_json
                atual = localizar(CACHE / nome)
                c_atual = ler_json(atual) if atual else None
                if met.get("arvore", 0) == 0 and isinstance(c_atual, dict) and c_atual.get("documentos"):
                    met["mantido"] = "VM-1 já tem leitura com documentos; leitura vazia não sobrescreve"
                    p.unlink(missing_ok=True)
                else:
                    if atual and atual.suffix == ".zst":
                        SUBST.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(atual), str(SUBST / f"{atual.name}__{lote}"))
                    _substituir(p, CACHE / nome, lote)
                aprovados[nome] = met
            _log(f"CONFERÊNCIA {nome}: {'APROVADO' if ok else 'QUARENTENA'} "
                 + json.dumps(met, ensure_ascii=False) + ("" if ok else f" motivos={motivos}"))
        # progresso/restritos: tudo, menos o de processo cuja leitura foi para a quarentena
        def _cdp(k: str) -> str:
            return "cdp_" + re.sub(r"[^0-9A-Za-z]", "_", k) + ".json"
        man["progresso_pendente"] = {k: v for k, v in (man.get("progresso") or {}).items()
                                     if _cdp(k) not in reprovados}
        man["restritos_pendente"] = man.get("restritos") or {}
    elif man.get("tipo") == "amostra":                  # leituras independentes feitas noutra máquina (23/11/2026)
        aprovados, reprovados = _importar_amostra(man)
    man["conferencia"] = {"em": time.strftime("%F %T"), "aprovados": aprovados, "reprovados": reprovados}
    IMPORTADOS.mkdir(parents=True, exist_ok=True)
    (IMPORTADOS / f"{lote}.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    shutil.rmtree(base, ignore_errors=True)
    aplicar_pendentes()
    _log(f"LOTE {lote} ({man.get('tipo')}): {len(aprovados)} aprovado(s), {len(reprovados)} em quarentena")
    return {"lote": lote, "aprovados": list(aprovados), "reprovados": reprovados}


def aplicar_pendentes() -> int:
    """Progresso e restritos dos lotes de sweep. Até 13/11 isto esperava NÃO haver sweep vivo na VM-1 (o
    merge-on-save dele apagava o importado) — e sempre havia. Com o "mais novo vence" + trava curta no
    `_salvar_prog`, incorpora na hora; a fila só segura o que falhar (erro de disco, JSON ilegível)."""
    n = 0
    for arq in sorted(IMPORTADOS.glob("*.json")) if IMPORTADOS.is_dir() else []:
        man = _ler_json(arq)
        if not isinstance(man, dict) or not (man.get("progresso_pendente") or man.get("restritos_pendente")):
            continue
        if man.get("progresso_pendente"):
            _mesclar_progresso(man["progresso_pendente"])
        if man.get("restritos_pendente"):
            _mesclar_restritos(man["restritos_pendente"])
        _log(f"progresso aplicado: {len(man.get('progresso_pendente') or {})} processo(s), "
             f"{len(man.get('restritos_pendente') or {})} restrito(s) — lote {arq.stem}")
        man["progresso_pendente"], man["restritos_pendente"] = {}, {}
        arq.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
        n += 1
    return n


AMOSTRA = DATA / "vm2_amostra_pendente.json"

# ───────────────────────── AMOSTRA independente: sorteada e lida fora do produtor (23/11/2026) ─────────────────────────
#
# Medido em 16–23/11/2026 (log desta conferência): a leitura independente pelo navegador da VM-1 custava 1,5–2,8 h/dia de
# Chromium (cada processo ~5–6 min com a VM-1 em load 5–10), lia 10–20 processos/dia, ADIAVA outros 1–9, e a fila — que
# recebia TODO aprovado sem referência (150–1.700/dia) — chegou a 2.321 (2.011 do it-campo, 310 da VM-2). Em toda a
# história, 2 divergências. Uma fila FIFO de tudo nunca alcança a cabeça: não é amostra, é atraso.
#
# Agora (com a chave ligada): (1) SORTEIO estratificado por nó produtor na entrada — taxa fixa (JFN_AMOSTRA_TAXA, 3%),
# no mínimo 1 por nó por dia, teto JFN_AMOSTRA_MAX_DIA por nó; (2) a leitura é feita por uma máquina que NÃO produziu a
# entrega: o que o it-campo entregou é lido na VM-2 (`amostra-exportar` → `amostra-ler` lá → lote `amostra` →
# `importar` aqui, que só roda `comparar_leitura` contra o acervo); o que a VM-2 entregou (ou de origem desconhecida)
# continua lido aqui. A VM-1 nunca é produtora de lote, então ler aqui é sempre independente.
# Liga: `touch data/.vm2_amostra_estratificada` (ou JFN_VM2_AMOSTRA=estratificada|fifo, que manda sobre o arquivo).
# Desligada, a entrada na fila é a de sempre (tudo, FIFO) — mas a fila aceita os dois formatos (texto ou dict).

FLAG_ESTRATIFICADA = DATA / ".vm2_amostra_estratificada"
SORTEIO = DATA / "vm2_amostra_sorteio.json"
AMOSTRA_TAXA = float(os.environ.get("JFN_AMOSTRA_TAXA") or 0.03)
AMOSTRA_MAX_DIA = int(os.environ.get("JFN_AMOSTRA_MAX_DIA") or 30)
DESPACHO_H = 24                     # despachada à VM-2 e sem resposta nesse prazo ⇒ volta a ser despachável
LE_NA_VM1 = ("JFN-Agent-2", "VM-2", "?")   # produtores cuja entrega a VM-1 lê (VM-2 e origem desconhecida)
LIDA_MAX_CHARS = 8000               # `semelhanca` usa os 4.000 primeiros; `legivel` não precisa de mais


def estratificada_ligada() -> bool:
    modo = os.environ.get("JFN_VM2_AMOSTRA", "").strip().lower()
    if modo in ("estratificada", "fifo"):
        return modo == "estratificada"
    return FLAG_ESTRATIFICADA.exists()


def _item(e) -> dict:
    """Entrada da fila nos dois formatos: texto (até 23/11/2026, origem desconhecida) ou dict."""
    return dict(e) if isinstance(e, dict) else {"proc": str(e), "origem": "?"}


def _mexer_fila(fn):
    """Ler-mudar-gravar da fila sob trava curta. Antes de 23/11/2026 o `amostra` lia a fila, passava ~10 min no navegador e
    regravava a lista que tinha lido — o que o `importar` enfileirou nesse meio tempo se perdia."""
    import fcntl
    with AMOSTRA.with_name(AMOSTRA.name + ".lock").open("w") as trava:
        fcntl.flock(trava, fcntl.LOCK_EX)
        fila = [_item(e) for e in (_ler_json(AMOSTRA) or [])]
        res = fn(fila)
        # chave desligada ⇒ grava no formato de sempre (lista de números): voltar o código atrás não quebra a fila. A
        # origem perdida aqui é recuperada pelo `reduzir_fila_amostra` (manifestos de `_importados`).
        saida = fila if estratificada_ligada() else [e["proc"] for e in fila]
        tmp = AMOSTRA.with_name(f"{AMOSTRA.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(saida, ensure_ascii=False), encoding="utf-8")
        tmp.replace(AMOSTRA)
        return res


def _sorteado(proc: str) -> bool:
    """Sorteio REPRODUTÍVEL pelo número do processo (md5 → [0,1)): a mesma entrada dá o mesmo resultado em qualquer
    máquina e no teste — e não há como o nó "escolher" o que será lido (ele não sabe a taxa nem o dia de corte)."""
    return int(hashlib.md5(proc.encode()).hexdigest()[:8], 16) / 0x100000000 < AMOSTRA_TAXA


def _sortear(procs: list[str], origem: str) -> list[str]:
    """Quais de `procs` (aprovados sem referência, do nó `origem`) entram na amostra hoje."""
    hoje = time.strftime("%F")
    est = _ler_json(SORTEIO) or {}
    if est.get("dia") != hoje:
        est = {"dia": hoje, "sorteados": {}, "vistos": {}}
    out = []
    for p in procs:
        n = _int(est["sorteados"].get(origem))
        est["vistos"][origem] = _int(est["vistos"].get(origem)) + 1
        if n < AMOSTRA_MAX_DIA and (n == 0 or _sorteado(p)):
            out.append(p)
            est["sorteados"][origem] = n + 1
    SORTEIO.write_text(json.dumps(est, ensure_ascii=False), encoding="utf-8")
    return out


def enfileirar_amostra(procs: list[str], origem: str = "?") -> None:
    """Processos aprovados SEM leitura independente na VM-1: entram na fila da leitura independente (todos, com a chave
    desligada; só os sorteados, com ela ligada)."""
    if estratificada_ligada():
        procs = _sortear(procs, origem)
    if not procs:
        return

    def _add(fila):
        ja = {e["proc"] for e in fila}
        fila.extend({"proc": p, "origem": origem, "em": time.strftime("%F %T")} for p in procs if p not in ja)
    _mexer_fila(_add)


def _le_na_vm1(e: dict) -> bool:
    return str(e.get("origem") or "?") in LE_NA_VM1


def comparar_leitura(lida: dict, pasta: Path) -> tuple[bool | None, str]:
    """Leitura INDEPENDENTE da VM-1 (`sei_reader.ler`) × o que a VM-2 entregou no arquivo."""
    if lida.get("erro") or not lida.get("documentos"):
        return None, f"leitura da VM-1 indisponível: {str(lida.get('erro') or 'sem árvore')[:100]}"
    man = _ler_json(pasta / "manifest.json") or {}
    entregues = {_norm_titulo(d.get("titulo", "")): d for d in man.get("docs") or [] if isinstance(d, dict)}
    arvore = {_norm_titulo(d.get("titulo") or d.get("texto") or "") for d in lida["documentos"] if isinstance(d, dict)}
    arvore.discard("")
    comuns = arvore & set(entregues)
    cob = len(comuns) / max(1, len(arvore))
    sims = []
    for c in lida.get("conteudo_documentos") or []:
        t = _norm_titulo(c.get("doc") or c.get("titulo") or "")
        d = entregues.get(t)
        if d and _arq_txt(d) and (pasta / "texto" / _arq_txt(d)).exists() and legivel(str(c.get("conteudo") or "")):
            sims.append(semelhanca(str(c["conteudo"]),
                                   (pasta / "texto" / _arq_txt(d)).read_text(encoding="utf-8", errors="replace")))
    nota = (f"árvore da VM-1 {len(arvore)} doc(s), {len(comuns)} na entrega ({cob:.0%})"
            + (f"; texto de {len(sims)} doc(s): semelhança {min(sims):.2f}–{max(sims):.2f}" if sims else ""))
    if cob < 0.80 or (sims and max(sims) < MIN_SEMELHANCA):
        return False, nota
    return True, nota


def _desfecho_amostra(proc: str, lida: dict, leitor: str) -> bool | None:
    """Compara uma leitura independente com o acervo e aplica: confere ⇒ sai da fila; diverge ⇒ quarentena e sai;
    indisponível ⇒ fica (e perde o despacho, para voltar a ser despachável)."""
    pasta = ARQUIVO / proc.replace("/", "_")
    if not (pasta / "manifest.json").exists():
        _mexer_fila(lambda f: f.__setitem__(slice(None), [e for e in f if e["proc"] != proc]))
        return None
    ok, nota = comparar_leitura(lida, pasta)
    if ok is None:
        def _solta(f):
            for e in f:
                if e["proc"] == proc:
                    e.pop("despachado", None)
        _mexer_fila(_solta)
        _log(f"AMOSTRA INDEPENDENTE {proc}: ADIADA ({nota}) [leitura: {leitor}]")
        return None
    _mexer_fila(lambda f: f.__setitem__(slice(None), [e for e in f if e["proc"] != proc]))
    if ok is False:
        _quarentena("amostra-" + time.strftime("%Y%m%d"), pasta, [nota], {"leitor": leitor})
    _log(f"AMOSTRA INDEPENDENTE {proc}: {'CONFERE' if ok else 'DIVERGE → QUARENTENA'} ({nota}) [leitura: {leitor}]")
    return ok


def amostra(n: int = 2) -> dict:
    """Leitura independente pela VM-1 de até `n` processos da fila que cabem a ela (produzidos pela VM-2 ou de origem
    desconhecida; os do it-campo vão à VM-2 por `amostra-exportar`). O `sei_reader.ler` cede sozinho com a VM-1
    carregada (devolve INDISPONÍVEL) — aí fica para a próxima."""
    import asyncio
    os.environ.setdefault("SEI_MAX_DOCS", "6")
    from tools import sei_reader as SR
    # chave desligada = comportamento de sempre: a VM-1 lê a cabeça da fila, de qualquer produtor
    meus = _mexer_fila(lambda f: [e["proc"] for e in f if _le_na_vm1(e) or not estratificada_ligada()])
    res = {}
    for proc in meus[:n]:
        lida = asyncio.run(SR.ler(f"SEI-{proc}", usar_cache=False))
        res[proc] = _desfecho_amostra(proc, lida, "VM-1")
        if res[proc] is None and (ARQUIVO / proc.replace("/", "_") / "manifest.json").exists():
            break                                   # VM-1 sem folga: não insistir nos próximos agora
    return res


def amostra_exportar(no: str, max_n: int = 4) -> list[dict]:
    """(VM-1) Até `max_n` processos para o nó `no` (hostname) LER — nunca os que ele mesmo produziu, nem os que cabem à
    VM-1. Marca o despacho (vale `DESPACHO_H`): dois disparos seguidos não leem o mesmo processo."""
    corte = time.time() - DESPACHO_H * 3600

    def _escolhe(fila):
        out = []
        for e in fila:
            if len(out) >= max_n:
                break
            if _le_na_vm1(e) or e.get("origem") == no or float(e.get("despachado") or 0) > corte:
                continue
            e["despachado"] = time.time()
            out.append({"proc": e["proc"], "origem": e.get("origem")})
        return out
    return _mexer_fila(_escolhe)


def _reduzir_lida(lida: dict) -> dict:
    """Só o que `comparar_leitura` usa: títulos da árvore e o teor (cortado) dos poucos documentos lidos."""
    if lida.get("erro"):
        return {"erro": str(lida["erro"])[:300]}
    return {"documentos": [{"titulo": str(d.get("titulo") or "")[:300], "texto": str(d.get("texto") or "")[:300]}
                           for d in lida.get("documentos") or [] if isinstance(d, dict)],
            "conteudo_documentos": [{"doc": str(c.get("doc") or "")[:300], "titulo": str(c.get("titulo") or "")[:300],
                                     "conteudo": str(c.get("conteudo") or "")[:LIDA_MAX_CHARS]}
                                    for c in (lida.get("conteudo_documentos") or [])[:6] if isinstance(c, dict)]}


def amostra_ler(itens: list[dict]) -> dict | None:
    """(VM-2) Lê com o navegador DESTA máquina os processos exportados pela VM-1 e devolve as leituras num lote
    `amostra` (o `importar` de lá compara com o acervo). A trava do navegador do worker (`data/.vm2_sei.lock`) é do
    script `tools/vm2_amostra.sh`. Primeiro INDISPONÍVEL encerra (sessão/carga): o resto volta a ser despachável."""
    import asyncio
    os.environ.setdefault("SEI_MAX_DOCS", "6")
    from tools import sei_reader as SR
    from tools import vm2_lote as L
    L.reenviar_pendentes()
    host = os.uname().nodename
    processos: dict[str, dict] = {}
    for it in itens:
        proc = str(it.get("proc") or "")
        if not re.fullmatch(r"\d{6}/\d{6}/\d{4}", proc) or it.get("origem") == host:
            continue                                     # nunca ler a própria entrega (a exportação já filtra)
        t0 = time.time()
        lida = _reduzir_lida(asyncio.run(SR.ler(f"SEI-{proc}", usar_cache=False)))
        processos[proc] = {"origem_entrega": it.get("origem"), "lida": lida, "segundos": round(time.time() - t0, 1)}
        if lida.get("erro"):
            break
    if not processos:
        return None
    return L.enviar(L.montar("amostra", {}, processos))


def _importar_amostra(man: dict) -> tuple[dict, dict]:
    """(VM-1) Lote `amostra`: leituras independentes feitas noutra máquina. Só `comparar_leitura` roda aqui."""
    leitor = str(man.get("origem") or "?")
    aprovados, reprovados = {}, {}
    for proc, info in (man.get("processos") or {}).items():
        if not isinstance(info, dict) or str(info.get("origem_entrega") or "") == leitor:
            _log(f"AMOSTRA INDEPENDENTE {proc}: leitura RECUSADA — leitor {leitor} é o produtor da entrega")
            reprovados[proc] = ["leitor = produtor"]
            continue
        ok = _desfecho_amostra(proc, info.get("lida") or {}, leitor)
        (aprovados if ok is not False else reprovados)[proc] = {"confere": ok, "segundos": info.get("segundos")}
    return aprovados, reprovados


def reduzir_fila_amostra(taxa: float = AMOSTRA_TAXA, semente: int = 20261123, aplicar: bool = False) -> dict:
    """Uma vez (23/11/2026): a fila FIFO acumulada vira AMOSTRA aleatória estratificada por produtor (≥1 por nó). A lista
    original fica em `data/vm2_amostra_pendente.json.bak-20261123` (não sobrescreve um .bak que já exista). O produtor
    de cada processo vem do manifesto do lote que o aprovou (`data/vm2_entrega/_importados/integras-*.json`)."""
    import random
    origem: dict[str, str] = {}
    for f in sorted(IMPORTADOS.glob("integras-*.json")) if IMPORTADOS.is_dir() else []:
        m = _ler_json(f)
        if isinstance(m, dict):
            for p in ((m.get("conferencia") or {}).get("aprovados") or {}):
                origem[p] = str(m.get("origem") or "?")
    def _reduz(fila: list[dict]) -> dict:
        por_no: dict[str, list[dict]] = {}
        for e in fila:
            if e.get("origem") in (None, "", "?"):
                e["origem"] = origem.get(e["proc"], "?")
            por_no.setdefault(e["origem"], []).append(e)
        rnd = random.Random(semente)
        nova = []
        for _no, itens in sorted(por_no.items()):
            nova += rnd.sample(itens, min(len(itens), max(1, round(taxa * len(itens)))))
        res = {"antes": len(fila), "depois": len(nova),
               "por_no": {no: [len(v), sum(1 for e in nova if e["origem"] == no)] for no, v in sorted(por_no.items())}}
        if aplicar:
            fila[:] = nova
        return res
    if not aplicar:
        return _reduz([_item(e) for e in (_ler_json(AMOSTRA) or [])])
    if not estratificada_ligada():
        # desligada, a fila é gravada só com números: a origem achada aqui se perderia e tudo voltaria a ser lido na VM-1
        raise SystemExit("ligue a amostra estratificada antes (touch data/.vm2_amostra_estratificada)")
    bak = AMOSTRA.with_name(AMOSTRA.name + ".bak-20261123")
    if not bak.exists():
        shutil.copy2(AMOSTRA, bak)
    res = _mexer_fila(_reduz)
    _log(f"AMOSTRA: fila FIFO reduzida a amostra estratificada {json.dumps(res, ensure_ascii=False)} (original em {bak.name})")
    return res


def rever_quarentena(lote: str) -> dict:
    """Reconfere os caches CDP de um lote em quarentena (depois de corrigir a régua) e importa o que passar."""
    pasta = QUARENTENA / lote
    man = _ler_json(IMPORTADOS / f"{lote}.json") or {}
    res = {}
    for p in sorted(x for x in pasta.glob("cdp_*.json") if not x.name.endswith(".motivo.json")) if pasta.is_dir() else []:
        ok, motivos, met = conferir_cdp(p, ((man.get("processos") or {}).get(p.name) or {}).get("juizo"))
        if ok:
            _substituir(p, CACHE / p.name, lote)
            (pasta / f"{p.name}.motivo.json").unlink(missing_ok=True)
            num = ((man.get("processos") or {}).get(p.name) or {}).get("numero")
            if num and num in (man.get("progresso") or {}):
                man.setdefault("progresso_pendente", {})[num] = man["progresso"][num]
        _log(f"REVISÃO DA QUARENTENA {p.name}: {'APROVADO' if ok else 'segue em quarentena'} "
             + json.dumps(met, ensure_ascii=False) + ("" if ok else f" motivos={motivos}"))
        res[p.name] = ok
    # ÍNTEGRAS (15/11/2026): a revisão só cobria caches CDP da varredura — as íntegras barradas por uma régua que depois
    # foi corrigida (títulos antigos genéricos × completos) ficavam presas para sempre. Mesmo caminho da importação.
    for pi in sorted(x for x in pasta.iterdir() if x.is_dir() and not x.name.startswith("integra_")) \
            if pasta.is_dir() else []:
        tag = pi.name
        info = (man.get("processos") or {}).get(tag.replace("_", "/")) or {}
        ok, motivos, met = conferir_integra(pi, info.get("status") or "ok", tag, info.get("juizo"))
        if ok:
            _substituir(pi, ARQUIVO / tag, lote)
            cache = QUARENTENA / lote / f"integra_{tag}"
            if cache.is_dir():
                _substituir(cache, CACHE / f"integra_{tag}", lote)
                (QUARENTENA / lote / f"integra_{tag}.motivo.json").unlink(missing_ok=True)
            (QUARENTENA / lote / f"{tag}.motivo.json").unlink(missing_ok=True)
        _log(f"REVISÃO DA QUARENTENA {tag}: {'APROVADO' if ok else 'segue em quarentena'} "
             + json.dumps(met, ensure_ascii=False) + ("" if ok else f" motivos={motivos}"))
        res[tag] = ok
    if man:
        (IMPORTADOS / f"{lote}.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    aplicar_pendentes()
    return res


def reconferir(tags: list[str]) -> dict:
    """Confere pastas que já entraram no acervo (entregas anteriores à conferência). Sem md5 de origem —
    o md5 do manifesto foi conferido na entrega. Reprovada ⇒ quarentena (o acervo não fica com o defeito)."""
    res = {}
    for tag in tags:
        pasta = ARQUIVO / tag
        m = _ler_json(pasta / "manifest.json") or {}
        status = "ok" if (m.get("docs") and not m.get("captura_vazia")) else "vazio"
        # o arquivo É a entrega: a referência independente só pode vir do cache CDP da VM-1
        ok, motivos, met = conferir_integra(pasta, status, tag, None, ref_do_arquivo=False)
        if not ok:
            _quarentena("reconferencia-" + time.strftime("%Y%m%d"), pasta, motivos, met)
        elif status == "ok" and str(met.get("referencia", "")).startswith("sem leitura"):
            enfileirar_amostra([tag.replace("_", "/")])
        _log(f"RECONFERÊNCIA {tag}: {'APROVADO' if ok else 'QUARENTENA'} [{status}] "
             + json.dumps(met, ensure_ascii=False) + ("" if ok else f" motivos={motivos}"))
        res[tag] = {"ok": ok, "motivos": motivos, "metricas": met}
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("importar"); i.add_argument("lote")
    sub.add_parser("pendentes")
    r = sub.add_parser("reconferir"); r.add_argument("tags", nargs="+")
    am = sub.add_parser("amostra"); am.add_argument("--n", type=int, default=2)
    rq = sub.add_parser("rever-quarentena"); rq.add_argument("lote")
    ae = sub.add_parser("amostra-exportar"); ae.add_argument("--no", required=True); ae.add_argument("--max", type=int, default=4)
    al = sub.add_parser("amostra-ler"); al.add_argument("--fila", required=True)
    ar = sub.add_parser("amostra-reduzir"); ar.add_argument("--taxa", type=float, default=AMOSTRA_TAXA)
    ar.add_argument("--aplicar", action="store_true")
    a = ap.parse_args()
    if a.cmd == "importar":
        print(json.dumps(importar(a.lote), ensure_ascii=False))
    elif a.cmd == "pendentes":
        print(aplicar_pendentes())
    elif a.cmd == "rever-quarentena":
        print(json.dumps(rever_quarentena(a.lote), ensure_ascii=False))
    elif a.cmd == "amostra":
        print(json.dumps(amostra(a.n), ensure_ascii=False))
    elif a.cmd == "amostra-exportar":
        print(json.dumps(amostra_exportar(a.no, a.max), ensure_ascii=False))
    elif a.cmd == "amostra-ler":
        print(json.dumps(amostra_ler(_ler_json(Path(a.fila)) or []), ensure_ascii=False))
    elif a.cmd == "amostra-reduzir":
        print(json.dumps(reduzir_fila_amostra(a.taxa, aplicar=a.aplicar), ensure_ascii=False))
    else:
        print(json.dumps(reconferir(a.tags), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
