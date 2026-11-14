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


def comparar_com_referencia(novos: dict[str, str], ref: dict[str, str]) -> tuple[bool | None, str]:
    """None = sem referência. Compara títulos e o texto de até 3 documentos de mesmo título."""
    if not ref:
        return None, "sem leitura independente na VM-1"
    titulos_ref = {t for t in ref if t}
    comuns = [t for t in titulos_ref if t in novos]
    cobertura = len(comuns) / max(1, len(titulos_ref))
    if cobertura < MIN_TITULOS:
        return False, f"só {len(comuns)}/{len(titulos_ref)} títulos da leitura da VM-1 reaparecem"
    sims = [semelhanca(novos[t], ref[t]) for t in comuns
            if legivel(ref[t]) and legivel(novos[t])][:3]
    if sims and max(sims) < MIN_SEMELHANCA:
        return False, f"texto diverge da leitura da VM-1 (semelhança máx {max(sims):.2f})"
    return True, (f"{len(comuns)}/{len(titulos_ref)} títulos em comum com a VM-1"
                  + (f", semelhança {min(sims):.2f}–{max(sims):.2f}" if sims else ""))


# ───────────────────────── conferência de uma pasta de íntegra ─────────────────────────

def conferir_integra(pasta_arq: Path, status: str, tag: str, juizo: dict | None,
                     ref_do_arquivo: bool = True) -> tuple[bool, list[str], dict]:
    """(aprovado, motivos de reprovação, métricas) de um arquivo de íntegra (`arquivo/<tag>/`)."""
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
    ok_ref, nota = comparar_com_referencia(novos, _referencia(tag, incluir_arquivo=ref_do_arquivo))
    met["referencia"] = nota
    if ok_ref is False:
        motivos.append(nota)
    if juizo:
        met["juizo_claude"] = {k: juizo.get(k) for k in ("legivel", "corresponde", "motivo", "modelo")}
        if juizo.get("legivel") is False or juizo.get("corresponde") is False:
            motivos.append(f"juízo do Claude (VM-2): {str(juizo.get('motivo') or 'reprovado')[:120]}")
    return not motivos, motivos, met


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
            ok, motivos, met = (False, erros, {}) if erros else conferir_integra(pasta, status, tag, info.get("juizo"))
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
                enfileirar_amostra([proc])
            _log(f"CONFERÊNCIA {proc}: {'APROVADO' if ok else 'QUARENTENA'} [{status}] "
                 + json.dumps(met, ensure_ascii=False) + ("" if ok else f" motivos={motivos}"))
        # linhas do log da fila: só "ok" de quem foi APROVADO
        saida = [f"[{time.strftime('%F %T')}] VM-2: lote {lote} conferido — {len(aprovados)} aprovado(s), "
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


def enfileirar_amostra(procs: list[str]) -> None:
    """Processos aprovados SEM leitura independente na VM-1: entram na fila da leitura independente."""
    fila = _ler_json(AMOSTRA) or []
    for p in procs:
        if p not in fila:
            fila.append(p)
    AMOSTRA.write_text(json.dumps(fila), encoding="utf-8")


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


def amostra(n: int = 2) -> dict:
    """Leitura independente pela VM-1 de até `n` processos entregues pela VM-2 sem referência local.
    O `sei_reader.ler` cede sozinho com a VM-1 carregada (devolve INDISPONÍVEL) — aí fica para a próxima."""
    import asyncio
    os.environ.setdefault("SEI_MAX_DOCS", "6")
    from tools import sei_reader as SR
    fila = _ler_json(AMOSTRA) or []
    res = {}
    for proc in list(fila)[:n]:
        tag = proc.replace("/", "_")
        pasta = ARQUIVO / tag
        if not (pasta / "manifest.json").exists():
            fila.remove(proc)
            continue
        lida = asyncio.run(SR.ler(f"SEI-{proc}", usar_cache=False))
        ok, nota = comparar_leitura(lida, pasta)
        if ok is None:
            _log(f"AMOSTRA INDEPENDENTE {proc}: ADIADA ({nota})")
            res[proc] = None
            break                                   # VM-1 sem folga: não insistir nos próximos agora
        fila.remove(proc)
        if ok is False:
            _quarentena("amostra-" + time.strftime("%Y%m%d"), pasta, [nota], {})
        _log(f"AMOSTRA INDEPENDENTE {proc}: {'CONFERE' if ok else 'DIVERGE → QUARENTENA'} ({nota})")
        res[proc] = ok
    AMOSTRA.write_text(json.dumps(fila), encoding="utf-8")
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
    a = ap.parse_args()
    if a.cmd == "importar":
        print(json.dumps(importar(a.lote), ensure_ascii=False))
    elif a.cmd == "pendentes":
        print(aplicar_pendentes())
    elif a.cmd == "rever-quarentena":
        print(json.dumps(rever_quarentena(a.lote), ensure_ascii=False))
    elif a.cmd == "amostra":
        print(json.dumps(amostra(a.n), ensure_ascii=False))
    else:
        print(json.dumps(reconferir(a.tags), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
