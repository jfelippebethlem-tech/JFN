#!/usr/bin/env python3
"""Página escaneada em `sei_arquivo/<proc>/fotos/` → versão compacta local (.webp cinza) + original no it-campo.

Pedido do dono (20/11/2026): "há processos enormes, cuidado para não estourar storage e memória; queremos um jeito
de ter arquivos menores pra caber tudo". `sei_fotos_frio` tira a página da VM-1 inteira; quando a VM-2 encheu (93%,
20/11) ele parou e o acervo voltou a crescer. Aqui a página FICA legível na VM-1 (cinza, lado maior ≤ 1600 px, WebP
— medição no comentário de `QUALIDADE`) e o JPG original vai para o it-campo
(C:\\JFN-Arquivo\\sei_fotos_orig\\<proc>\\), conferido por sha256 do lado de lá ANTES de sair daqui.

Critério de "página": o MESMO de `foto_medicao.reciclagem` — o que `_triar_e_hashear` descarta. Fotografia de execução
(prova) não é tocada. A versão compacta é retriada: se ela passasse a ser "informativa" (ganhar hash), a reciclagem
mudaria — então ela é descartada e o original fica como está.

Por pasta parada há > 2 h (idade da imagem ORIGINAL mais nova), UMA imagem por vez na memória:
  1. tria (fotografia → anotada e intocada);  2. página → `.<nome>.webp.tmp` + sha256 do original;
  3. rsync dos originais do lote → it-campo;  4. sha256sum lá; só os que BATEM: tmp → `<nome>.webp` e o original sai;
  5. `compactado.json` na pasta (arquivo, webp, bytes antes/depois, sha256, destino) e linha em `sei_arquivo_frio.jsonl`.
Voltar uma pasta: rsync de `it-campo:/mnt/c/JFN-Arquivo/sei_fotos_orig/<proc>/` para `fotos/` e apagar os `.webp`
listados no `compactado.json`.

    nice -n 19 .venv/bin/python -m tools.sei_compactar [--limite N] [--pasta PROC ...] [--ensaio]
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from compliance_agent import foto_medicao as FM  # noqa: E402
from PIL import Image, ImageOps  # noqa: E402

DADOS = Path(os.environ.get("JFN_DADOS") or RAIZ / "data")   # worktree de teste aponta para os dados reais
ARQUIVO = DADOS / "sei_arquivo"
INDICE = DADOS / "sei_arquivo_frio.jsonl"
NO = "it-campo"
RSYNC_PATH = "wsl -d Ubuntu -e rsync"
DEST = "/mnt/c/JFN-Arquivo/sei_fotos_orig"
REGISTRO = "compactado.json"
ORIGINAIS = {".jpg", ".jpeg", ".png"}
LADO = 1600              # as páginas do arquivador já saem com ~1.240 px: o ganho vem do cinza + WebP, não do corte
# MEDIDO 20/11/2026 (300 imagens de 118 pastas, critério da reciclagem): 125 páginas = 16,9 MB → WebP cinza
# q50 8,2 MB (−51,5%) · q55 8,5 MB (−49,5%) · q60 8,9 MB (−47,6%); nenhuma compacta virou "informativa".
# Legibilidade (tesseract por, 15 páginas): o OCR desta resolução nem se repete — reencodar o original em JPEG q95
# já dá similaridade média 0,80 com o OCR do original (só 2/14 ≥ 0,95). Contra o TEXTO JÁ GUARDADO em texto/, q55
# recupera 97,5% das palavras distintas que o original recupera (q75: 98,5%; acerto 0,742 × 0,731 do original).
QUALIDADE = 55
GANHO_MIN = 0.85          # compacta precisa ficar ≤ 85% do original, senão não vale a viagem
LOTE = 200                # originais por rsync/conferência (limita o .tmp em disco)
LIVRE_MIN_GB = 20         # abaixo disso no it-campo, nada sai daqui
_SLUG = re.compile(r"^\d+_\d+_\d{4}$")


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def compactar_bytes(caminho: Path, lado: int = LADO, qualidade: int = QUALIDADE) -> bytes:
    """Cinza + lado maior ≤ `lado` + WebP. `draft` faz o JPEG já decodificar reduzido (memória baixa)."""
    with Image.open(caminho) as im:
        im.draft("L", (lado, lado))
        g = ImageOps.exif_transpose(im).convert("L")
    g.thumbnail((lado, lado), Image.LANCZOS)
    b = io.BytesIO()
    g.save(b, "WEBP", quality=qualidade, method=6)
    return b.getvalue()


def _originais(fotos: Path) -> list[Path]:
    return sorted(p for p in fotos.iterdir()
                  if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in ORIGINAIS)


def _ler_registro(pasta: Path) -> dict:
    reg = pasta / REGISTRO
    try:
        return json.loads(reg.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"itens": [], "fotografias": {}}


def _gravar_registro(pasta: Path, r: dict) -> None:
    r["em"] = time.strftime("%Y-%m-%d %H:%M:%S")
    r["criterio"] = ("página = foto_medicao._triar_e_hashear sem hash (a reciclagem já a descartava); "
                     f"compacta = cinza, lado ≤ {LADO}px, WebP q{QUALIDADE}, retriada sem hash")
    t = pasta / (REGISTRO + ".tmp")
    t.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(t, pasta / REGISTRO)


def pastas(idade_min_h: float) -> list[Path]:
    """Pastas com original novo desde o último registro e cuja imagem original mais nova tem ≥ idade_min_h."""
    agora = time.time()
    res = []
    for d in ARQUIVO.iterdir():
        f = d / "fotos"
        if not (d.is_dir() and _SLUG.match(d.name) and f.is_dir()):
            continue
        mt = [x.stat().st_mtime for x in _originais(f)]
        if not mt or agora - max(mt) < idade_min_h * 3600:
            continue
        reg = d / REGISTRO
        if reg.exists():
            r = _ler_registro(d)
            vistas = r.get("fotografias") or {}
            if all(vistas.get(x.name) == _assin(x) for x in _originais(f)):
                continue   # tudo o que resta é fotografia já triada (ou original que falhou e espera)
        res.append((max(mt), d))
    return [d for _, d in sorted(res)]


def _assin(p: Path) -> str:
    st = p.stat()
    return f"{st.st_size}:{int(st.st_mtime)}"


def _remoto(script: str, timeout: int = 900, tentativas: int = 3) -> subprocess.CompletedProcess:
    """Repete o script (todos os daqui são idempotentes: mkdir -p, df, sha256sum) quando o WSL falha.
    20/11/2026, rodada real: 1 `mkdir -p` saiu rc=1 sem stderr e 1 `sha256sum` voltou vazio com os 26 arquivos íntegros lá."""
    r = _remoto_uma(script, timeout)
    for i in range(1, tentativas):
        if r.returncode == 0:
            break
        time.sleep(5 * i)
        r = _remoto_uma(script, timeout)
    return r


def _remoto_uma(script: str, timeout: int) -> subprocess.CompletedProcess:
    """bash no WSL do it-campo. Falha (ssh caiu, timeout) vira rc≠0 — nunca exceção no meio de um lote.
    20/11/2026: o Windows devolveu mensagem em latin-1 e o decode UTF-8 estrito derrubou a rodada com 61 .tmp órfãos."""
    cmd = ["ssh", "-o", "ConnectTimeout=20", NO, "wsl -d Ubuntu -e bash -s"]
    try:
        return subprocess.run(cmd, input=script, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout)
    except (subprocess.SubprocessError, OSError) as e:
        return subprocess.CompletedProcess(cmd, 255, "", f"{type(e).__name__}: {e}")


def livre_no_gb() -> int | None:
    try:
        r = _remoto("df -BG --output=avail /mnt/c | tail -1", timeout=60)
        return int("".join(c for c in r.stdout if c.isdigit())) if r.returncode == 0 else None
    except (subprocess.SubprocessError, ValueError):
        return None


def enviar(pasta: Path, nomes: list[str]) -> bool:
    """rsync dos originais para it-campo:DEST/<proc>/ (cria a pasta). True se o rsync saiu 0."""
    dest = f"{DEST}/{pasta.name}"
    mk = _remoto(f"mkdir -p {shlex.quote(dest)}", timeout=60)
    if mk.returncode != 0:
        print(f"  {pasta.name}: mkdir remoto rc={mk.returncode} {mk.stderr[-200:]}", flush=True)
        return False
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".lst") as t:
        t.write("".join(n + "\n" for n in nomes))
    try:
        r = subprocess.run(["rsync", "-a", f"--rsync-path={RSYNC_PATH}", f"--files-from={t.name}",
                            str(pasta / "fotos") + "/", f"{NO}:{dest}/"],
                           capture_output=True, text=True, errors="replace", timeout=7200)
    except (subprocess.SubprocessError, OSError) as e:
        print(f"  {pasta.name}: rsync {type(e).__name__}", flush=True)
        return False
    finally:
        Path(t.name).unlink(missing_ok=True)
    if r.returncode != 0:
        print(f"  {pasta.name}: rsync rc={r.returncode} {r.stderr[-200:]}", flush=True)
    return r.returncode == 0


def sha_remoto(pasta: Path, nomes: list[str]) -> dict[str, str]:
    """{nome: sha256} como o it-campo os vê. Ausente/ilegível lá = ausente no dict."""
    dest = f"{DEST}/{pasta.name}"
    out: dict[str, str] = {}
    for tentativa in range(3):                     # saída vazia/parcial do WSL: pergunta de novo só pelo que faltou
        falta = [n for n in nomes if n not in out]
        if not falta:
            break
        if tentativa:
            time.sleep(10 * tentativa)
        script = f"cd {shlex.quote(dest)} || exit 3\n" + "".join(
            f"sha256sum -- {shlex.quote(n)} 2>/dev/null\n" for n in falta) + "exit 0\n"
        r = _remoto(script, timeout=1800)
        for ln in r.stdout.splitlines():
            m = re.match(r"^([0-9a-f]{64})\s+\*?(.+)$", ln.strip())
            if m:
                out[m.group(2)] = m.group(1)
    return out


def _lote(pasta: Path, cands: list[dict], reg: dict) -> int:
    """Envia, confere e só então troca. Devolve bytes liberados. Todo .tmp que não virou .webp é apagado."""
    try:
        return _lote_conferido(pasta, cands, reg)
    finally:
        for c in cands:
            c["tmp"].unlink(missing_ok=True)


def _lote_conferido(pasta: Path, cands: list[dict], reg: dict) -> int:
    nomes = [c["arquivo"] for c in cands]
    if not enviar(pasta, nomes):
        return 0
    lado_de_la = sha_remoto(pasta, nomes)
    livres, ok = 0, []
    fotos = pasta / "fotos"
    for c in cands:
        orig, tmp = fotos / c["arquivo"], c["tmp"]
        if lado_de_la.get(c["arquivo"]) != c["sha256"] or _sha256(orig) != c["sha256"]:
            print(f"  {pasta.name}/{c['arquivo']}: sha256 não confere no {NO} — original fica", flush=True)
            tmp.unlink(missing_ok=True)
            continue
        webp = fotos / (orig.stem + ".webp")
        os.replace(tmp, webp)
        st = orig.stat()
        os.utime(webp, (st.st_atime, st.st_mtime))   # a idade da pasta continua sendo a da captura
        orig.unlink()
        livres += c["bytes_antes"] - c["bytes_depois"]
        ok.append({"arquivo": f"fotos/{c['arquivo']}", "webp": f"fotos/{webp.name}",
                   "bytes_antes": c["bytes_antes"], "bytes_depois": c["bytes_depois"], "sha256": c["sha256"],
                   "destino": f"{NO}:{DEST}/{pasta.name}/{c['arquivo']}"})
    if ok:
        reg.setdefault("itens", []).extend(ok)
        _gravar_registro(pasta, reg)
        with INDICE.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"pasta": f"sei_arquivo/{pasta.name}/fotos", "compactado": len(ok),
                                "bytes_liberados": sum(i["bytes_antes"] - i["bytes_depois"] for i in ok),
                                "destino": f"{NO}:{DEST}/{pasta.name}", "em": reg["em"], "rc": 0},
                               ensure_ascii=False) + "\n")
    return livres


def tratar(pasta: Path, ensaio: bool) -> dict:
    fotos = pasta / "fotos"
    reg = _ler_registro(pasta)
    vistas = reg.setdefault("fotografias", {})
    for orfao in fotos.glob(".*.webp.tmp"):        # rodada anterior interrompida: o original ainda está aqui
        orfao.unlink(missing_ok=True)
    res = {"pasta": pasta.name, "paginas": 0, "fotografias": 0, "mantidas": 0, "antes": 0, "depois": 0, "liberado": 0}
    cands: list[dict] = []
    for orig in _originais(fotos):
        if vistas.get(orig.name) == _assin(orig):
            res["fotografias"] += 1
            continue
        try:
            if FM._triar_e_hashear(orig):
                res["fotografias"] += 1
                vistas[orig.name] = _assin(orig)     # prova de execução: não se toca; não re-hashear à toa
                continue
            b = compactar_bytes(orig)
        except (OSError, ValueError, Image.DecompressionBombError) as e:
            print(f"  {orig}: não li ({type(e).__name__}) — fica", flush=True)
            res["mantidas"] += 1
            continue
        antes = orig.stat().st_size
        if len(b) > GANHO_MIN * antes:
            res["mantidas"] += 1
            continue
        tmp = fotos / f".{orig.stem}.webp.tmp"
        tmp.write_bytes(b)
        if FM._triar_e_hashear(tmp):                 # a compacta mudaria a reciclagem → não troca
            tmp.unlink(missing_ok=True)
            res["mantidas"] += 1
            continue
        res["paginas"] += 1
        res["antes"] += antes
        res["depois"] += len(b)
        if ensaio:
            tmp.unlink(missing_ok=True)
            continue
        cands.append({"arquivo": orig.name, "tmp": tmp, "sha256": _sha256(orig),
                      "bytes_antes": antes, "bytes_depois": len(b)})
        if len(cands) >= LOTE:
            res["liberado"] += _lote(pasta, cands, reg)
            cands = []
    if cands:
        res["liberado"] += _lote(pasta, cands, reg)
    if not ensaio:
        _gravar_registro(pasta, reg)               # anota as fotografias: a próxima rodada não as re-hasheia
    return res


def _baixar_prioridade() -> None:
    try:
        os.nice(19)
        subprocess.run(["ionice", "-c3", "-p", str(os.getpid())], capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--limite", type=int, default=0, help="máximo de pastas nesta rodada")
    ap.add_argument("--pasta", nargs="*", default=[], help="só estas pastas (nome em sei_arquivo/)")
    ap.add_argument("--idade-min-h", type=float, default=2.0)
    ap.add_argument("--ensaio", action="store_true", help="tria e mede, não grava nem envia nada")
    a = ap.parse_args(argv)
    _baixar_prioridade()
    lista = [ARQUIVO / p for p in a.pasta] if a.pasta else pastas(a.idade_min_h)
    if a.limite:
        lista = lista[:a.limite]
    tot = {"pastas": 0, "paginas": 0, "fotografias": 0, "mantidas": 0, "antes": 0, "depois": 0, "liberado": 0}
    for i, p in enumerate(lista, 1):
        if not a.ensaio and i % 20 == 1:
            livre = livre_no_gb()
            if livre is None or livre < LIVRE_MIN_GB:
                print(f"{time.strftime('%F %T')} {NO} {'fora do ar' if livre is None else f'com {livre} GB'} — parei",
                      flush=True)
                break
        r = tratar(p, a.ensaio)
        tot["pastas"] += 1
        for k in ("paginas", "fotografias", "mantidas", "antes", "depois", "liberado"):
            tot[k] += r[k]
        print(json.dumps(r, ensure_ascii=False), flush=True)
    tot["ensaio"] = a.ensaio
    print(json.dumps(tot, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
