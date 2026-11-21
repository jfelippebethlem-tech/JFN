#!/usr/bin/env python3
"""Zelador semanal de armazenamento — UM roteiro, um PERFIL por máquina (vm1, vm2, itcampo).

Pedido do dono (21/11/2026): "detectores semanais na vm1, vm2, it campo pra liberar storage […] assim não ficamos
sem storage" · "automatize isso sem margem pra erro". Política e camadas: `docs/ARMAZENAMENTO.md`; porta de
nuvem e índice: `compliance_agent/armazenamento.py`.

O ciclo (sempre nesta ordem; QUALQUER falha numa etapa → `abortar`: nada é apagado e o dono é avisado):
  1. PRÉ-VOO     rclone responde em cada destino exigido; montagens do perfil presentes; espaço p/ empacotar.
  2. RECUPERAÇÃO traz de volta uma amostra do que já está na nuvem e confere o hash (a cópia que não volta
                 não é cópia).
  3. CANDIDATOS  só nas RAÍZES do perfil (lista branca), com as travas de `pode_sair()`:
                 exclusão explícita · não-symlink · idade ≥ N dias · ninguém com o arquivo aberto (fuser) ·
                 nada de banco vivo (*.db/-wal/-shm/-journal) · nada de código nem worktree · nada listado
                 numa fila viva (ex.: OCR) · teto de GB e de arquivos por ciclo.
  4. ENVIO       cada unidade (arquivo ou pacote .tar de uma pasta) sobe a TODOS os destinos da política
                 (re-obtível: Drive; insubstituível: Drive + a 2ª que couber no grátis) e cada cópia é conferida.
  5. ÍNDICE      importa manifestos antigos, inventaria as nuvens, marca cópias sumidas/divergentes.
  6. LIBERAR     (só `--aplicar`, só sem abortar, só depois do ensaio limpo): por unidade, a trava
                 `liberado_para_apagar` (cópias exigidas conferidas NESTE ciclo); por arquivo, mesmo tamanho,
                 mesmo mtime e mesmo md5 do que subiu; linha no journal ANTES do unlink.
                 Depois, o regenerável (caches de pip/uv/npm, navegadores sem dono, temporários velhos).
  7. EXPORTAR    o índice sobe às duas nuvens (`indice/<maquina>.db`).
  8. RELATÓRIO   ~/.zelador/relatorio-<ciclo>.json + aviso ao dono SÓ se houve ação, falha ou disco > 85%.

    python tools/zelador/zelador.py --perfil vm1 --ensaio          # obrigatório na 1ª vez de cada máquina
    python tools/zelador/zelador.py --perfil vm1 --aplicar [--teto-gb 40]
"""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

_AQUI = Path(__file__).resolve()
sys.path.insert(0, str(_AQUI.parent.parent.parent))
from compliance_agent import armazenamento as A  # noqa: E402

HOME = Path.home()
ESTADO = HOME / ".zelador"

# ── exclusão explícita (testada em tests/test_zelador.py) ──────────────────────────────────────────────────
NOMES_PROIBIDOS = {"compliance.db", "compliance_analitico.db", "pcrj.db", "pcrj_benef.db", "receita_estab.db",
                   "territorio.db", "achados.db", "armazenamento_indice.db", "rclone.conf", "auth.json",
                   "authorized_keys", "id_rsa", "id_ed25519"}
PADROES_PROIBIDOS = [".env", ".env.*", "*.db", "*.db-wal", "*.db-shm", "*.db-journal", "*.sqlite", "*.sqlite3",
                     "*.sqlite-wal", "*.sqlite-shm", "*.py", "*.sh", "*.js", "*.ts", "*.ps1", "*.lock", "*.pid"]
PARTES_PROIBIDAS = {".git", ".venv", "venv", "node_modules", "site-packages", ".config", ".ssh", ".gnupg",
                    ".zelador", "worktrees", "JFN-test", "v69", ".hermes", "chrome-jfn", "navegador-claude",
                    "siafe_profile", "yt-login", ".pki"}
PREFIXOS_PROIBIDOS = [str(HOME / "JFN-test"), "/mnt/c/up/v69", "/mnt/c/up", str(HOME / ".config"),
                      str(HOME / ".ssh"), str(HOME / "JFN" / ".claude"), str(HOME / "JFN-worker" / ".git")]
# backup comprimido de banco É permitido (é para isso que existe): `*.db.gz`, `*.db.zst` não casam com `*.db`

logger = logging.getLogger("zelador")


@dataclass
class Raiz:
    """Uma raiz da lista branca. `modo`: 'arquivos' (cada arquivo é uma unidade) ou 'pastas' (cada subpasta
    imediata vira um pacote .tar). `original` reescreve o caminho lógico (ex.: cópias no it-campo)."""
    caminho: Path
    classe: str
    modo: str = "pastas"
    idade_dias: float = 7
    padrao: str = "*"
    original: object = None
    fila_viva: list = field(default_factory=list)   # arquivos com listas de relativos que não podem sair
    so_backup: bool = False                         # sobe e indexa, mas não apaga o local


def _itcampo_original(p: Path) -> Path:
    """~/Desktop/it-campo/vm1/<rotulo>/<rel a /home/ubuntu> → /home/ubuntu/<rel> (o que mover-para-itcampo fez)."""
    base = HOME / "Desktop" / "it-campo" / "vm1"
    try:
        rel = p.relative_to(base)
    except ValueError:
        return p
    return HOME.joinpath(*rel.parts[1:]) if len(rel.parts) > 1 else p


@dataclass
class Perfil:
    nome: str
    raizes: list
    montagens: list = field(default_factory=list)
    teto_gb: float = 40.0
    teto_arquivos: int = 200_000
    caches_regeneraveis: list = field(default_factory=list)
    aviso_disco_pct: float = 85.0
    limpar_navegadores: bool = False               # só os perfis reais: nunca num teste (incidente 21/11)
    tmp_globs: list = field(default_factory=list)  # ex.: /tmp/pytest-of-* parado há > 2 dias
    horas_envio: float = 5.0                       # teto de tempo do envio; o que subiu até ali é liberado


def perfis() -> dict[str, Perfil]:
    J = HOME / "JFN"
    return {
        "vm1": Perfil(
            "vm1",
            raizes=[
                Raiz(J / "data" / "vm2_quarentena", "quarentena", idade_dias=2),
                Raiz(J / "data" / "vm2_entrega" / "_substituidos", "substituido", idade_dias=2),
                Raiz(J / "data" / "sei_arquivo" / "_substituido", "substituido", idade_dias=7),
                Raiz(HOME / "Desktop" / "it-campo" / "vm1", "quarentena", idade_dias=0, original=_itcampo_original),
                Raiz(HOME / ".claude" / "projects", "sessao_claude", modo="arquivos", idade_dias=21,
                     padrao="*.jsonl"),
                Raiz(Path("/tmp/claude-1001/-home-ubuntu"), "trabalho", idade_dias=14),
                Raiz(HOME, "backup_db", modo="arquivos", idade_dias=30, padrao="*.db.gz"),
                Raiz(J / "data" / "backups", "backup_db", modo="arquivos", idade_dias=14),
            ],
            montagens=[HOME / "Desktop" / "it-campo"],
            caches_regeneraveis=[".cache/pip", ".cache/uv", ".npm/_cacache", ".cache/go-build", ".cache/node-gyp"],
            limpar_navegadores=True, tmp_globs=["/tmp/pytest-of-*"],
        ),
        "vm2": Perfil(
            "vm2",
            raizes=[
                Raiz(HOME / "arquivo_frio" / "vm2_quarentena", "quarentena", idade_dias=2),
                Raiz(HOME / "arquivo_frio" / "vm2_substituidos", "substituido", idade_dias=2),
                Raiz(HOME / "arquivo_frio" / "sei_arquivo_substituido", "substituido", idade_dias=2),
                Raiz(HOME / "arquivo_frio" / "sei_fotos", "sei_foto", idade_dias=7),
                # PDFs escaneados: insumo do OCR da GPU. A fila (`tools/sei_ocr_gpu_fila.py`) só enxerga o PDF
                # que EXISTE no frio da VM-2 — apagar aqui tiraria o documento do OCR em silêncio. Então: só
                # backup no Drive (indexado, re-obtível) até o OCR aprender a buscar pelo `obter()`.
                Raiz(HOME / "arquivo_frio" / "sei_pdfs", "sei_pdf", idade_dias=1, so_backup=True),
                Raiz(HOME / "arquivo_frio" / "sei_cache", "sei_cache", idade_dias=1, so_backup=True),
            ],
            caches_regeneraveis=[".cache/pip", ".cache/uv", ".npm/_cacache"],
            limpar_navegadores=True, tmp_globs=["/tmp/pytest-of-*"],
        ),
        "itcampo": Perfil(
            "itcampo",
            raizes=[
                Raiz(Path("/mnt/c/JFN-Arquivo/sei_pdfs"), "sei_pdf", idade_dias=1, so_backup=True),  # `--itcampo-local`
                Raiz(Path("/mnt/c/JFN-Arquivo/sei_fotos"), "sei_foto", idade_dias=1),
                Raiz(Path("/mnt/c/JFN-Arquivo/sei_fotos_orig"), "sei_foto", idade_dias=1),
                Raiz(Path("/mnt/c/JFN-Arquivo/vm2_quarentena"), "quarentena", idade_dias=1),
                Raiz(Path("/mnt/c/JFN-Arquivo/vm2_substituidos"), "substituido", idade_dias=1),
                Raiz(Path("/mnt/c/JFN-Arquivo/sei_arquivo_substituido"), "substituido", idade_dias=1),
            ],
            montagens=[Path("/mnt/c")],
            teto_gb=60.0,
            caches_regeneraveis=[".cache/pip", ".cache/uv"],
        ),
    }


# ── travas ────────────────────────────────────────────────────────────────────────────────────────────────
def proibido(p: Path) -> str | None:
    s = str(p)
    if p.name in NOMES_PROIBIDOS:
        return "nome na lista de exclusão"
    if any(fnmatch.fnmatch(p.name, pad) for pad in PADROES_PROIBIDOS):
        return "tipo protegido (banco vivo/código/segredo)"
    if PARTES_PROIBIDAS & set(p.parts):
        return "pasta protegida"
    if any(s == pre or s.startswith(pre.rstrip("/") + "/") for pre in PREFIXOS_PROIBIDOS):
        return "prefixo protegido"
    return None


_ABERTOS: set[str] | None = None


def abertos_agora() -> set[str]:
    """Foto única de todo arquivo aberto (/proc/*/fd) — um `fuser` por arquivo levaria horas em 250 mil fotos."""
    s: set[str] = set()
    for fd in Path("/proc").glob("[0-9]*/fd/*"):
        try:
            s.add(os.readlink(fd))
        except OSError as exc:                    # processo terminou entre o glob e o readlink
            logger.debug("fd sumiu: %s (%s)", fd, exc)
    return s


def aberto(p: Path) -> bool:
    global _ABERTOS
    if _ABERTOS is None:
        _ABERTOS = abertos_agora()
    return str(p) in _ABERTOS or str(p.resolve()) in _ABERTOS


def renovar_abertos() -> None:
    global _ABERTOS
    _ABERTOS = abertos_agora()


def idade_dias(p: Path) -> float:
    st = p.lstat()
    return (time.time() - max(st.st_mtime, st.st_ctime)) / 86400


def pode_sair(p: Path, idade_min: float, fila: set[str] | None = None, rel: str | None = None,
              checar_aberto=aberto) -> str | None:
    """None = pode; senão o motivo. Fechada por padrão: qualquer erro ao medir = não sai."""
    try:
        motivo = proibido(p)
        if motivo:
            return motivo
        if p.is_symlink() or not p.is_file():
            return "não é arquivo regular"
        if idade_dias(p) < idade_min:
            return f"mexido há menos de {idade_min:g} dia(s)"
        if fila and rel and rel in fila:
            return "na fila viva"
        if checar_aberto(p):
            return "aberto por algum processo"
    except OSError as e:
        return f"erro ao medir: {e}"
    return None


# ── ciclo ─────────────────────────────────────────────────────────────────────────────────────────────────
class Abortar(RuntimeError):
    pass


@dataclass
class Ciclo:
    perfil: Perfil
    aplicar: bool
    rc: A.Rclone
    con: object
    teto_gb: float
    id: str = ""
    falhas: list = field(default_factory=list)
    acoes: list = field(default_factory=list)
    enviados: list = field(default_factory=list)      # (Unidade, raiz)
    candidatos: list = field(default_factory=list)
    recusados: dict = field(default_factory=dict)
    liberado_bytes: int = 0
    regenerado_bytes: int = 0
    nuvens_antes: dict = field(default_factory=dict)

    def falhar(self, msg: str) -> None:
        self.falhas.append(msg)
        A.journal(self.con, "falha", self.perfil.nome, msg, self.id)


def vagas_exigidas(perfil: Perfil) -> set[tuple[str, ...]]:
    vagas = {v for r in perfil.raizes for v in A.POLITICA[A.CLASSES[r.classe]]}
    return vagas | set(A.POLITICA["insubstituivel"])            # o índice é exportado sempre


def prevoo(c: Ciclo) -> None:
    """Montagens + binário do rclone + POR NUVEM: acessível, uso real medido no remoto (about/size) e consumo
    do dia/mês contra os limites grátis da config. Vaga sem nenhum remoto utilizável = falha (aborta)."""
    for m in c.perfil.montagens:
        if not os.path.ismount(m):
            c.falhar(f"montagem ausente: {m}")
    ver = c.rc.versao()
    if not ver:
        c.falhar(f"rclone não responde: {c.rc.binario}")
    c.acoes.append(f"rclone {c.rc.binario} · {ver}")
    for vaga in sorted(vagas_exigidas(c.perfil)):
        uteis = []
        for d in vaga:
            if not c.rc.acessivel(A.DESTINOS[d]):
                c.acoes.append(f"pré-voo {d}: inacessível ou recusado")
                continue
            uteis.append(d)
        if not uteis:
            c.falhar(f"destino inacessível: {'|'.join(vaga)}")
    c.nuvens_antes = A.estado_nuvens(c.rc)
    for d, e in c.nuvens_antes.items():
        c.acoes.append(f"pré-voo {d}: usado {e['usado_gb']} GB · alvo {e['alvo_gb']} GB · hoje {e['hoje']}")
    livre = shutil.disk_usage(A._tmp_base()).free / 1e9
    if livre < 5:
        c.falhar(f"só {livre:.1f} GB livres para empacotar")


def recuperacao(c: Ciclo) -> None:
    for r in A.testar_recuperacao(c.con, c.rc, amostra=2):
        if not r["ok"]:
            c.falhar(f"recuperação falhou em {r['destino']}: {r['chave']} — {r['detalhe']}")
        else:
            c.acoes.append(f"recuperação ok {r['destino']}: {r['chave']}")


def _ler_fila(arquivos: list) -> set[str] | None:
    s: set[str] = set()
    for f in arquivos:
        f = Path(f)
        if not f.exists() or (time.time() - f.stat().st_mtime) > 2 * 86400:
            return None                         # fila ausente ou velha (> 2 dias) = não sei o que está em uso
        s |= {ln.strip().lstrip("/") for ln in f.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()}
    return s


def coletar(c: Ciclo) -> None:
    teto = c.teto_gb * 1e9
    total = 0
    narq = 0
    for raiz in c.perfil.raizes:
        if not raiz.caminho.is_dir():
            continue
        fila = _ler_fila(raiz.fila_viva) if raiz.fila_viva else set()
        if fila is None:
            c.falhar(f"fila viva ilegível para {raiz.caminho} — sem ela não sei o que está em uso")
            continue
        grupos: list[tuple[Path, list[Path]]] = []
        if raiz.modo == "arquivos":
            for f in sorted(raiz.caminho.rglob(raiz.padrao)) if raiz.caminho != HOME else sorted(raiz.caminho.glob(raiz.padrao)):
                grupos.append((f, [f]))
        else:
            for sub in sorted(p for p in raiz.caminho.iterdir() if p.is_dir() and not p.is_symlink()):
                grupos.append((sub, [f for f in sub.rglob("*") if f.is_file() or f.is_symlink()]))
        for alvo, arquivos in grupos:
            if not arquivos:
                continue
            bons, motivo_grupo = [], None
            for f in arquivos:
                rel = str(f.relative_to(raiz.caminho))
                m = pode_sair(f, raiz.idade_dias, fila, rel)
                if m:
                    motivo_grupo = m
                    break
                bons.append(f)
            if motivo_grupo:        # pasta é unidade: um arquivo preso segura a pasta inteira neste ciclo
                c.recusados[motivo_grupo] = c.recusados.get(motivo_grupo, 0) + 1
                continue
            base = alvo if raiz.modo != "arquivos" else alvo.parent
            ass = A.assinatura_de(bons, base)
            if raiz.so_backup and A.ja_na_nuvem(c.con, ass):
                c.recusados["já na nuvem (só backup)"] = c.recusados.get("já na nuvem (só backup)", 0) + 1
                continue
            tam = sum(f.stat().st_size for f in bons)
            if raiz.modo != "arquivos" and tam > shutil.disk_usage(A._tmp_base()).free - 5e9:
                c.recusados["maior que o espaço para empacotar"] = c.recusados.get("maior que o espaço para empacotar", 0) + 1
                continue
            if total + tam > teto or narq + len(bons) > c.perfil.teto_arquivos:
                c.recusados["teto do ciclo"] = c.recusados.get("teto do ciclo", 0) + 1
                continue
            total += tam
            narq += len(bons)
            c.candidatos.append((raiz, alvo, bons, tam, ass))


def enviar(c: Ciclo) -> None:
    tmp = Path(A._tmp_base()) / c.id
    t0 = time.time()
    for raiz, alvo, arquivos, tam, ass in c.candidatos:
        if c.falhas:
            return                              # primeira falha encerra o envio; nada será apagado
        if time.time() - t0 > c.perfil.horas_envio * 3600:
            c.acoes.append(f"teto de tempo do envio ({c.perfil.horas_envio:g} h): o resto fica para o próximo ciclo")
            return
        try:
            base = alvo if raiz.modo != "arquivos" else alvo.parent
            ja = A.unidade_do_indice(c.con, ass, arquivos, base, raiz.original)
            if ja is not None:                  # já subiu antes: só reconfere (neste ciclo) — sem reenviar
                res = A.reconferir_unidade(c.con, c.rc, ja, c.id)
                if A.vagas_satisfeitas(ja.natureza, A.copias_ok(res)):
                    c.enviados.append((ja, raiz))
                    c.acoes.append(f"já na nuvem, reconferido {ja.chave} → {sorted(res)}")
                    continue
            if raiz.modo == "arquivos":
                orig = raiz.original(alvo) if raiz.original else alvo
                u = A.unidade_arquivo(alvo, raiz.classe, original=orig)
            else:
                u = A.unidade_pacote(alvo, arquivos, raiz.classe, tmp, c.id, original_de=raiz.original)
            u.assinatura = ass
            res = A.enviar_unidade(c.con, c.rc, u, c.id)
            if not A.vagas_satisfeitas(u.natureza, A.copias_ok(res)):
                c.falhar(f"cópia não conferida {u.chave}: {res}")
            else:
                c.enviados.append((u, raiz))
                c.acoes.append(f"guardado {u.chave} ({tam / 1e6:.1f} MB, {len(arquivos)} arq.) → {sorted(res)}")
        except (OSError, A.ErroArmazenamento) as e:
            c.falhar(f"erro ao enviar {alvo}: {e}")
        finally:
            if raiz.modo != "arquivos":
                shutil.rmtree(tmp, ignore_errors=True)


def liberar(c: Ciclo) -> None:
    for u, raiz in c.enviados:
        if raiz.so_backup:
            continue
        if not A.liberado_para_apagar(c.con, u.chave, c.id):
            c.falhar(f"trava: {u.chave} sem as cópias exigidas conferidas neste ciclo")
            return
        for m in u.membros:
            try:
                st = m.caminho.stat()
                if st.st_size != m.bytes or st.st_mtime != m.mtime or A.hashes(m.caminho)[0] != m.md5:
                    c.acoes.append(f"mudou desde o envio, fica: {m.caminho}")
                    continue
                if aberto(m.caminho):
                    c.acoes.append(f"aberto agora, fica: {m.caminho}")
                    continue
                A.journal(c.con, "apagar_local", str(m.caminho), u.chave, c.id)
                m.caminho.unlink()
                c.con.execute("UPDATE membros SET local_apagado_em=? WHERE chave=? AND caminho=?",
                              (A.agora(), u.chave, str(m.original)))
                c.con.commit()
                c.liberado_bytes += m.bytes
            except OSError as e:
                c.acoes.append(f"não apagado {m.caminho}: {e}")
        if u.tipo == "pacote":                    # pastas que ficaram vazias (só dentro da raiz)
            for d in sorted({p for m in u.membros for p in m.caminho.parents}, key=lambda d: -len(d.parts)):
                if raiz.caminho in d.parents:
                    try:
                        d.rmdir()
                    except OSError as exc:        # diretório não vazio: fica
                        logger.debug("não removi %s: %s", d, exc)


def _du(p: Path) -> int:
    try:
        r = subprocess.run(["du", "-sb", str(p)], capture_output=True, text=True, timeout=600)
        return int(r.stdout.split()[0]) if r.returncode == 0 and r.stdout else 0
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 0


def navegadores_sem_dono() -> list[Path]:
    """Revisões em ~/.cache/ms-playwright que NENHUM playwright instalado (browsers.json) referencia e que não
    estão em execução. Reinstaláveis com `playwright install`."""
    base = HOME / ".cache" / "ms-playwright"
    if not base.is_dir():
        return []
    usadas: set[str] = set()
    sp = "lib/python3*/site-packages/playwright/driver/package/browsers.json"
    achados = [*HOME.glob(f"*/.venv/{sp}"), *HOME.glob(f"*/*/.venv/{sp}"), *HOME.glob(f"*/*-env/{sp}"),
               *HOME.glob(f"*/*venv*/{sp}"), *HOME.glob(f".local/share/*/*/{sp}"), *HOME.glob(f".local/{sp[4:]}")]
    for bj in achados:
        try:
            for b in json.loads(bj.read_text())["browsers"]:
                usadas.add(f"{b['name'].replace('-', '_')}-{b['revision']}")
        except (OSError, ValueError, KeyError):
            return []                          # um browsers.json ilegível = não sei quem usa = não apaga nada
    nm = "node_modules/playwright-core/browsers.json"
    for pj in [*HOME.glob(f"*/{nm}"), *HOME.glob(f"*/*/{nm}"), *HOME.glob(f".npm-global/lib/node_modules/*/{nm}"),
               *HOME.glob(f".npm-global/lib/{nm}"), *HOME.glob(f".npm/_npx/*/{nm}")]:
        try:
            for b in json.loads(pj.read_text())["browsers"]:
                usadas.add(f"{b['name'].replace('-', '_')}-{b['revision']}")
        except (OSError, ValueError, KeyError):
            return []
    try:
        ps = subprocess.run(["/bin/ps", "-eo", "args"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    out = []
    for d in base.iterdir():
        if not d.is_dir() or d.name in (".links", "b") or d.name.startswith("ffmpeg"):
            continue
        if d.name in usadas or str(d) in ps:
            continue
        out.append(d)
    return out


def regeneraveis(c: Ciclo, executar: bool) -> None:
    """Só o que se refaz sozinho: caches de gerenciador de pacote, navegador sem dono, /tmp de sessões velhas."""
    for rel in c.perfil.caches_regeneraveis:
        d = HOME / rel
        if d.is_dir():
            n = _du(d)
            c.acoes.append(f"{'apagado' if executar else 'apagaria'} cache {d} ({n / 1e9:.2f} GB)")
            if executar:
                A.journal(c.con, "apagar_regeneravel", str(d), "", c.id)
                shutil.rmtree(d, ignore_errors=True)
                c.regenerado_bytes += n
    for d in (navegadores_sem_dono() if c.perfil.limpar_navegadores else []):
        n = _du(d)
        c.acoes.append(f"{'apagado' if executar else 'apagaria'} navegador sem dono {d.name} ({n / 1e9:.2f} GB)")
        if executar:
            A.journal(c.con, "apagar_regeneravel", str(d), "playwright install refaz", c.id)
            shutil.rmtree(d, ignore_errors=True)
            c.regenerado_bytes += n
    import glob as _glob
    for d in (Path(x) for g in c.perfil.tmp_globs for x in _glob.glob(g)):
        if d.is_dir() and idade_dias(d) > 2 and not aberto_algo_dentro(d):
            n = _du(d)
            c.acoes.append(f"{'apagado' if executar else 'apagaria'} {d} ({n / 1e9:.2f} GB)")
            if executar:
                shutil.rmtree(d, ignore_errors=True)
                c.regenerado_bytes += n


def aberto_algo_dentro(d: Path) -> bool:
    pre = str(d).rstrip("/") + "/"
    return any(x.startswith(pre) for x in abertos_agora())


def disco_pct() -> float:
    t, u, _ = shutil.disk_usage("/")
    return u * 100 / t


def _enviar_telegram(texto: str) -> dict:
    try:
        from compliance_agent.siafe_coord import enviar_ao_dono
        return enviar_ao_dono(texto)
    except ImportError as exc:
        logger.debug("siafe_coord indisponível (%s) — tentando o envio direto", exc)
    import urllib.parse
    import urllib.request
    from compliance_agent.siafe_coord import CHAT_ID, _token   # cópias antigas do repo (VM-2) não têm enviar_ao_dono
    tok = _token()
    if not tok:
        return {"ok": False}
    data = urllib.parse.urlencode({"chat_id": CHAT_ID, "text": texto}).encode()
    with urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage", data=data),
                                timeout=15) as r:
        return json.loads(r.read().decode("utf-8") or "{}")


def avisar(texto: str) -> bool:
    """Entrega conferida por `message_id` (o "ok" do Telegram já mentiu nesta casa). Sem entrega → fica em
    ~/.zelador/aviso-pendente.txt e o zelador da VM-1 (`--vigiar`) repassa pelo índice exportado."""
    try:
        r = _enviar_telegram(texto[:3900])
        if ((r or {}).get("result") or {}).get("message_id"):
            return True
    except (ImportError, OSError, ValueError) as exc:
        logger.warning("aviso ao dono NÃO entregue: %s", exc)
    ESTADO.mkdir(parents=True, exist_ok=True)
    with open(ESTADO / "aviso-pendente.txt", "a", encoding="utf-8") as f:
        f.write(f"{A.agora()}\n{texto}\n\n")
    return False


def vigiar_outros(avisar_fn=avisar, dias_max: float = 8.5) -> list[str]:
    """VM-1, diário: lê os índices das outras máquinas (sincronizados da nuvem) e avisa ciclo abortado, disco
    acima de 85% ou zelador que parou de rodar — o silêncio de um zelador também é falha."""
    est = ESTADO / "vigiados.json"
    try:
        vistos = set(json.loads(est.read_text()))
    except (OSError, ValueError):
        vistos = set()
    msgs = []
    for db in sorted(A.dir_indices_outros().glob("*.db")):
        con = A.conectar(db)
        r = con.execute("SELECT * FROM ciclos WHERE modo='aplicar' ORDER BY inicio DESC LIMIT 1").fetchone()
        con.close()
        if r is None:
            continue
        idade = (dt.datetime.now() - dt.datetime.fromisoformat(r["inicio"])).total_seconds() / 86400
        res = json.loads(r["resumo"] or "{}")
        if r["id"] not in vistos and (r["status"] != "ok" or res.get("disco_pct_depois", 0) > 85):
            msgs.append(f"🗄️ Zelador {r['perfil']} — {r['status'].upper()} em {r['inicio'][:16]} · disco "
                        f"{res.get('disco_pct_depois', '?')}%" + (f"\n🆘 {'; '.join(res.get('falhas', [])[:3])[:600]}"
                                                                if res.get("falhas") else ""))
            vistos.add(r["id"])
        if idade > dias_max and f"parado:{r['id']}" not in vistos:
            msgs.append(f"🆘 Zelador {r['perfil']} não roda há {idade:.0f} dias (último ciclo {r['inicio'][:16]})")
            vistos.add(f"parado:{r['id']}")
    for m in msgs:
        avisar_fn(m)
    est.write_text(json.dumps(sorted(vistos)))
    return msgs


def rodar(perfil: Perfil, aplicar: bool, teto_gb: float | None = None, rc: A.Rclone | None = None,
          con=None, avisar_fn=avisar, ensaio_flag: Path | None = None) -> dict:
    ESTADO.mkdir(parents=True, exist_ok=True)
    flag = ensaio_flag or ESTADO / f"ensaio_ok-{perfil.nome}.json"
    if aplicar and not flag.exists():
        raise SystemExit(f"recusado: rode antes `--perfil {perfil.nome} --ensaio` (1ª rodada desta máquina)")
    con = con or A.conectar()
    c = Ciclo(perfil, aplicar, rc or A.Rclone(), con, teto_gb or perfil.teto_gb)
    c.id = f"{perfil.nome}-{dt.datetime.now():%Y%m%d-%H%M%S-%f}"
    antes = disco_pct()
    con.execute("INSERT INTO ciclos VALUES(?,?,?,?,?,?,?,?)",
                (c.id, A.maquina(), perfil.nome, "aplicar" if aplicar else "ensaio", A.agora(), None, "rodando", None))
    con.commit()
    prevoo(c)
    if not c.falhas:
        recuperacao(c)
    if not c.falhas:
        coletar(c)
    if aplicar and not c.falhas:
        enviar(c)
    if not c.falhas and perfil.nome == "vm1":
        try:
            A.importar_manifestos(con)
        except OSError as e:
            c.falhar(f"importar manifestos: {e}")
        inv = A.inventariar_nuvens(con, c.rc)          # foto das 3 nuvens; cópia do índice que sumiu = falha
        for nome in A.NUVENS["remotos"]:
            if inv.get(nome) == "erro":
                c.falhar(f"inventário de {nome} falhou")
        for chave, dest in inv.get("copias_sumidas_ou_divergentes", [])[:20]:
            c.falhar(f"cópia sumida/divergente na nuvem: {dest} {chave}")
    if aplicar and not c.falhas and c.enviados:
        exp = A.exportar_indice(con, c.rc)      # o índice (com o que vai sair) em 2 provedores ANTES de apagar
        if not A.indice_exportado(exp):
            c.falhar(f"índice não exportado antes de liberar: {exp}")
    if aplicar and not c.falhas:
        renovar_abertos()                       # a foto de abertos é refeita na hora de apagar
        liberar(c)
    if not c.falhas:
        regeneraveis(c, executar=aplicar)
    if aplicar:
        exp = A.exportar_indice(con, c.rc)
        if not A.indice_exportado(exp):
            c.falhar(f"índice não exportado: {exp}")
    depois = disco_pct()
    status = "abortado" if c.falhas else "ok"
    recusas = list(dict.fromkeys(c.rc.orcamento.recusas)) if c.rc.orcamento else []
    for m in recusas:
        A.journal(con, "recusado_prevoo", perfil.nome, m, c.id)
    rel = {
        "ciclo": c.id, "modo": "aplicar" if aplicar else "ensaio", "status": status,
        "disco_pct_antes": round(antes, 1), "disco_pct_depois": round(depois, 1),
        "candidatos": len(c.candidatos), "candidatos_gb": round(sum(c_[3] for c_ in c.candidatos) / 1e9, 2),
        "enviados": len(c.enviados), "liberado_gb": round(c.liberado_bytes / 1e9, 2),
        "regenerado_gb": round(c.regenerado_bytes / 1e9, 2), "recusados": c.recusados,
        "falhas": c.falhas, "recusas_prevoo": recusas[:200], "nuvens_antes": c.nuvens_antes,
        "nuvens_depois": A.estado_nuvens(c.rc) if c.nuvens_antes else {}, "acoes": c.acoes[:400],
        "lista_candidatos": [f"{r.classe}\t{a}\t{len(fs)}\t{t}" for r, a, fs, t, _ in c.candidatos][:2000],
    }
    con.execute("UPDATE ciclos SET fim=?, status=?, resumo=? WHERE id=?",
                (A.agora(), status, json.dumps({k: v for k, v in rel.items() if k not in ("acoes", "lista_candidatos")},
                                               ensure_ascii=False), c.id))
    con.commit()
    (ESTADO / f"relatorio-{c.id}.json").write_text(json.dumps(rel, ensure_ascii=False, indent=1), encoding="utf-8")
    if not aplicar and not c.falhas:
        flag.write_text(json.dumps({"ciclo": c.id, "em": A.agora(), "candidatos": len(c.candidatos)}), encoding="utf-8")
    houve_acao = c.liberado_bytes or c.regenerado_bytes or c.enviados
    if c.falhas or recusas or depois > perfil.aviso_disco_pct or (aplicar and houve_acao):
        txt = (f"🗄️ Zelador {perfil.nome} — {status.upper()} ({rel['modo']})\n"
               f"Disco {antes:.0f}% → {depois:.0f}% · liberado {rel['liberado_gb']} GB + regenerável "
               f"{rel['regenerado_gb']} GB · {len(c.enviados)} unidade(s) guardada(s) na nuvem\n")
        if c.falhas:
            txt += "🆘 ESCALADO — nada foi apagado neste ciclo:\n" + "\n".join(f"• {f[:300]}" for f in c.falhas[:8])
        if recusas:
            txt += ("\n🆘 ESCALADO — recusado pelo pré-voo (limite GRÁTIS da nuvem; não foi feito):\n" +
                    "\n".join(f"• {m[:300]}" for m in recusas[:8]))
        if depois > perfil.aviso_disco_pct:
            txt += f"\n⚠️ disco acima de {perfil.aviso_disco_pct:.0f}%"
        rel["avisado"] = avisar_fn(txt)
    return rel


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Zelador semanal de armazenamento do JFN")
    ap.add_argument("--perfil", choices=sorted(perfis()))
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--vigiar", action="store_true", help="VM-1: avisa ciclos ruins/parados das outras máquinas")
    g.add_argument("--ensaio", action="store_true", help="mostra o que faria; não sobe nem apaga nada")
    g.add_argument("--aplicar", action="store_true")
    ap.add_argument("--teto-gb", type=float, default=None)
    a = ap.parse_args(argv)
    if a.vigiar:
        A.sincronizar_indices()
        print(json.dumps(vigiar_outros(), ensure_ascii=False))
        return 0
    if not a.perfil:
        ap.error("--perfil é obrigatório")
    rel = rodar(perfis()[a.perfil], aplicar=a.aplicar, teto_gb=a.teto_gb)
    print(json.dumps({k: v for k, v in rel.items() if k not in ("acoes", "lista_candidatos")},
                     ensure_ascii=False, indent=1))
    return 0 if rel["status"] == "ok" else 2


if __name__ == "__main__":
    sys.exit(main())
