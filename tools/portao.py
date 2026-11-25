# -*- coding: utf-8 -*-
"""Portão de pre-push v2 (O2.5 da Esteira Única): testes pelo grafo de import, rodados FORA da VM-1.

POR QUE EXISTE. O portão v1 (tools/pre_push_gate.sh) tinha três buracos medidos em 24/11:
  1. escolhia testes por NOME e deixou passar falhas que só a suíte completa pegou — a seleção agora é a de
     tools/portao_grafo.py (import transitivo + catracas + transversais);
  2. empacotava a ÁRVORE DE TRABALHO (com o WIP das outras frentes) e não o commit que sobe — agora o nó busca o
     próprio commit num espelho git (tools/portao_no.sh), então as catracas de `git ls-files` também rodam lá;
  3. com a VM-2 fora ele dizia "dívida, não aprovação" e DEIXAVA PASSAR (exit 0). Agora: nenhum nó respondeu → o push
     NÃO passa, e fica registrado em data/push_divida.json; `python -m tools.push_divida drenar` testa e empurra
     quando um nó voltar. Nunca há --no-verify implícito.

NÓS. VM-2 primeiro (2 vCPU, 1 lote); it-campo (WSL, 24 fios) é o segundo e, com seleção grande, divide o lote com a
VM-2 em paralelo (6 pytest no it-campo, cada um no seu worktree). Nó que cai no meio → a parte dele vai para o outro.

COMO LIGAR (desligado por padrão; o v1 segue para quem não ligar):
    git config jfn.portaov2 1        # repo inteiro: todo push/commit de toda sessão passa pelo v2
    export JFN_PORTAO_V2=1           # só a sessão/shell atual
    git config --unset jfn.portaov2  # desligar (a variável, se exportada, vence o git config)
  Liga junto: .git/hooks/pre-commit → tools/pre_commit_v2.sh (só checagens) e .git/hooks/post-commit →
  tools/grafo_pos_commit.sh (graphify/codegraph/compressão em 2º plano, no it-campo quando ele responde).

    python -m tools.portao pre-push <remoto> <url>   < linhas do git    # o hook (via tools/pre_push_gate.sh)
    python -m tools.portao testar <base> <sha>                          # mede um intervalo sem empurrar
    python -m tools.portao nos                                          # quem está respondendo
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from tools import portao_grafo

RAIZ = Path(__file__).resolve().parent.parent
CORPO_NO = RAIZ / "tools" / "portao_no.sh"
ORIGEM = os.environ.get("JFN_PORTAO_ORIGEM", "ssh://vm1-ts/home/ubuntu/JFN")
ZERO = "0" * 40
LIMIAR_PARALELO = int(os.environ.get("JFN_PORTAO_LIMIAR_PARALELO", "40"))   # arquivos; abaixo disso, um nó só
TETO_NO = int(os.environ.get("JFN_PORTAO_TETO", "2400"))                    # s: TETO máximo de um lote
# 25/11: o teto fixo de 2.400 s fez o portão esperar 40 min, duas rodadas seguidas, pelo it-campo saturado de OCR
# antes de refazer na VM-2. Agora o teto do lote é proporcional ao tamanho dele (base + s por arquivo, limitado ao
# TETO_NO) e o nó aborta sozinho o lote cujo log do pytest parou de crescer por PARADO s (tools/portao_no.sh).
TETO_BASE = int(os.environ.get("JFN_PORTAO_TETO_BASE", "300"))
TETO_POR_ARQ = float(os.environ.get("JFN_PORTAO_TETO_POR_ARQ", "4"))      # medido: VM-2 0,57 s/arquivo (1040 em 590 s)
PARADO = int(os.environ.get("JFN_PORTAO_PARADO", "600"))                  # s sem crescer o log do lote → aborta
MARGEM_SSH = int(os.environ.get("JFN_PORTAO_MARGEM_SSH", "600"))          # fetch + worktrees + venv antes dos lotes
# nó ACELERADOR acima disto não recebe lote (a referência nunca é pulada por carga: ela é lenta, mas termina)
LIMIAR_PSI = float(os.environ.get("JFN_PORTAO_LIMIAR_PSI", "60"))         # % de /proc/pressure/cpu "some avg10"
LIMIAR_LOAD = float(os.environ.get("JFN_PORTAO_LIMIAR_LOAD", "1.0"))      # load1 / nproc
LOG = Path(os.environ.get("JFN_PORTAO_LOG", "/tmp/pre_push_v2.log"))

_SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=4"]


@dataclass(frozen=True)
class No:
    nome: str
    argv: tuple[str, ...]      # comando que recebe o script pelo stdin
    paralelo: int              # pytest simultâneos no nó
    peso: float                # fatia relativa quando a seleção é dividida
    referencia: bool = False   # ambiente de referência (o do CI): confirma falha vista em nó acelerador


NOS: tuple[No, ...] = (
    # pesos medidos em 24/11 (9d40ae78, 293 arquivos): VM-2 60 arquivos em 233 s (1 pytest, load 8 dos outros
    # trabalhos dela); it-campo 233 arquivos em 46 s (6 pytest) — ~18× a vazão. Peso 1 × 15.
    No("vm2", (*_SSH, "vm2-ts", "bash -s"), paralelo=1, peso=1.0, referencia=True),
    No("itcampo", (*_SSH, "it-campo", "wsl -d Ubuntu bash -s"), paralelo=6, peso=15.0),
)


def _rodar(argv: tuple[str, ...], script: str, timeout: int) -> tuple[int, str]:
    """ÚNICA porta para o ssh (os testes trocam esta função por um fake)."""
    try:
        r = subprocess.run(list(argv), input=script, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        saida = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        return 124, saida + f"\nPORTAO_INFRA ssh sem resposta em {timeout} s"
    except OSError as e:
        return 127, f"PORTAO_INFRA ssh não executou: {e}"
    return r.returncode, (r.stdout or "") + (r.stderr or "")


SONDA = ("echo PORTAO_VIVO $(nproc) $(cut -d' ' -f1 /proc/loadavg)"
         " $(sed -n 's/^some avg10=\\([0-9.]*\\).*/\\1/p' /proc/pressure/cpu 2>/dev/null)\n")


@dataclass(frozen=True)
class Sonda:
    vivo: bool
    nproc: int | None = None
    load: float | None = None
    psi: float | None = None       # /proc/pressure/cpu some avg10 (%); None = o kernel não expõe (ex.: WSL antigo)

    def sobrecarga(self) -> str:
        """'' se cabe lote; senão a medida que passou do limiar. Carga não medida não é carga zero: é dita."""
        if self.psi is not None and self.psi > LIMIAR_PSI:
            return f"PSI cpu some avg10 {self.psi:.0f}% > {LIMIAR_PSI:.0f}%"
        if self.load is not None and self.nproc and self.load / self.nproc > LIMIAR_LOAD:
            return f"load {self.load:.1f}/{self.nproc} = {self.load / self.nproc:.2f} > {LIMIAR_LOAD:.2f}"
        return ""

    def carga(self) -> str:
        if self.load is None or not self.nproc:
            return "carga não medida"
        return f"load {self.load:.1f}/{self.nproc}" + (f", PSI {self.psi:.0f}%" if self.psi is not None else "")


def _num(x: str, tipo):
    return tipo(x) if re.fullmatch(r"\d+(?:\.\d+)?", x) else None


def sondar(no: No, timeout: int = 40) -> Sonda:
    rc, out = _rodar(no.argv, SONDA, timeout)
    ln = next((x for x in out.splitlines() if x.startswith("PORTAO_VIVO")), None)
    if ln is None:
        return Sonda(False)
    p = ln.split()[1:] + ["", "", ""]
    return Sonda(True, _num(p[0], int), _num(p[1], float), _num(p[2], float))


def nos_vivos(nos: tuple[No, ...] | None = None, pulados: list[str] | None = None) -> list[No]:
    """Os nós que respondem e cabem lote. Nó acelerador sobrecarregado é PULADO (dito em `pulados` e no stderr) —
    a não ser que seja o único vivo: aí vai assim mesmo (o teto proporcional e o PARADO o abortam cedo)."""
    nos = nos or NOS
    with ThreadPoolExecutor(len(nos)) as ex:
        sondas = list(ex.map(sondar, nos))
    vivos = [(n, sd) for n, sd in zip(nos, sondas) if sd.vivo]
    leves = [(n, sd) for n, sd in vivos if n.referencia or not sd.sobrecarga()]
    if not leves:
        return [n for n, _ in vivos]
    for n, sd in vivos:
        if (n, sd) not in leves:
            msg = f"{n.nome} pulado: carga {sd.sobrecarga()}"
            print(f"[portão] {msg}", file=sys.stderr)
            if pulados is not None:
                pulados.append(msg)
    return [n for n, _ in leves]


@dataclass
class Resultado:
    estado: str                       # "ok" | "falhou" | "infra"
    no: str
    testes: list[str]
    falhas: list[str] = field(default_factory=list)
    resumo: list[str] = field(default_factory=list)
    motivo: str = ""
    saida: str = ""
    segundos: float = 0.0
    nao_medidos: list[str] = field(default_factory=list)   # enviados que nenhum lote terminado executou
    vazios: list[str] = field(default_factory=list)        # de lote limpo, sem caso no junit (1ª rodada "sem casos")
    sem_casos: list[str] = field(default_factory=list)     # sem caso em 2 rodadas limpas: aceito, mas sempre listado


# resumo final do pytest ("3 passed, 1 failed in 2.0s"); "no tests ran" NÃO é resumo de lote medido
_RESUMO_PYTEST = re.compile(r"\b\d+ (?:passed|failed|errors?|skipped|xfailed|xpassed)\b")
_LOTE = re.compile(r"^PORTAO_LOTE (\d+) rc=(\S*)\s*(.*)$")


def _norm(caminho: str) -> str:
    """`./tests/x.py`, `tests//x.py` e `/…/w1/tests/x.py` casam com `tests/x.py` (o absoluto, por sufixo em _casa)."""
    c = os.path.normpath(caminho)
    return c[2:] if c.startswith("./") else c


def _casa(arq: str, vistos: set[str]) -> bool:
    a = _norm(arq)
    return a in vistos or any(v.startswith("/") and v.endswith("/" + a) for v in vistos)


@dataclass
class _Medicao:
    nao_medidos: list[str]
    rc_ruim: bool          # algum lote medido saiu com rc de erro
    vazios: list[str]      # de lote limpo (rc 0/5, resumo, dentro do TETO) e sem caso no junit
    zero: set[str]         # destes, os que o `pytest --co` do nó também achou com 0 itens (PORTAO_ZERO)


def _lotes_medidos(testes: list[str], linhas: list[str]) -> _Medicao:
    """0 execuções não é 0 erros (25/11/2026: o lote 5 do it-campo estourou o TETO com 173 arquivos, a falha dele não
    tinha nodeid, a confirmação na VM-2 trocou as falhas pelas dela e o portão APROVOU sem rodar os 173). Um lote só
    MEDE algo com rc ≠ 124 (TETO) e linha de resumo do pytest; aí conta POR ARQUIVO: medido é o enviado que aparece em
    PORTAO_VISTOS (tem caso no junit). Era tudo-ou-nada por lote (coletados == enviados) até 25/11, quando UM arquivo
    sem caso nenhum (tests/test_goal_modes_smoke.py, script sem test_*) derrubou os 71 do lote da VM-2 que rodou
    683 testes. Nó sem PORTAO_VISTOS (versão antiga do portao_no.sh) cai na regra tudo-ou-nada do PORTAO_COLETA."""
    lotes = {m.group(1): (m.group(2), m.group(3)) for ln in linhas if (m := _LOTE.match(ln))}
    vistos_por_lote: dict[str, set[str]] = {}
    zero: set[str] = set()
    for ln in linhas:
        partes = ln.split()
        if ln.startswith("PORTAO_VISTOS ") and len(partes) >= 2:
            vistos_por_lote[partes[1]] = {_norm(v) for v in partes[2:]}
        elif ln.startswith("PORTAO_ZERO ") and len(partes) == 3:
            zero.add(_norm(partes[2]))
    medidos: set[str] = set()
    vazios: list[str] = []
    rc_ruim = False
    for ln in linhas:
        if not ln.startswith("PORTAO_COLETA "):
            continue
        partes = ln.split()
        if len(partes) < 4:
            continue
        k, n, arqs = partes[1], partes[2], partes[3:]
        rc, resumo = lotes.get(k, ("", ""))
        if rc == "124" or not _RESUMO_PYTEST.search(resumo):
            continue
        if k in vistos_por_lote:
            vistos = vistos_por_lote[k]
            achados = [a for a in arqs if _casa(a, vistos)]
            if rc in ("0", "5"):
                vazios += [a for a in arqs if a not in achados]
        elif n.isdigit() and int(n) == len(set(arqs)):
            achados = arqs
        else:
            continue
        if achados:
            medidos.update(achados)
            rc_ruim = rc_ruim or rc not in ("0", "5")
    return _Medicao([t for t in testes if t not in medidos], rc_ruim, [t for t in testes if t in set(vazios)],
                    {t for t in testes if _norm(t) in zero})


def interpretar(no: str, testes: list[str], rc: int, saida: str) -> Resultado:
    """Só o contrato de linhas de tools/portao_no.sh conta. Sem PORTAO_FIM a rodada não aconteceu (infra) — nunca
    "passou"."""
    linhas = saida.splitlines()
    infra = [ln[len("PORTAO_INFRA "):] for ln in linhas if ln.startswith("PORTAO_INFRA ")]
    fim = [ln for ln in linhas if ln.startswith("PORTAO_FIM rc=")]
    falhas = [ln[len("PORTAO_FALHA "):] for ln in linhas if ln.startswith("PORTAO_FALHA ")]
    resumo = [ln[len("PORTAO_LOTE "):] for ln in linhas if ln.startswith("PORTAO_LOTE ")]
    if infra or not fim:
        motivo = infra[-1] if infra else f"saída sem PORTAO_FIM (rc do ssh {rc})"
        return Resultado("infra", no, testes, falhas, resumo, motivo, saida)
    med = _lotes_medidos(testes, linhas)
    # vazio de lote limpo cujo `--co` também deu 0 itens: duas rodadas limpas sem caso → "sem casos" (listado)
    sem_casos = [t for t in med.vazios if t in med.zero]
    nao_medidos, rc_ruim = [t for t in med.nao_medidos if t not in sem_casos], med.rc_ruim
    com_nodeid = [f for f in falhas if _NODEID.match(f)]
    estado = "ok"
    if com_nodeid:
        estado = "falhou"
    elif fim[-1].strip() != "PORTAO_FIM rc=0" and (rc_ruim or not nao_medidos):
        # rc de erro que nenhum arquivo não medido explica: falha sem nodeid, nunca some
        estado = "falhou"
        falhas = falhas or ["(lote falhou sem linha FAILED — ver o log)"]
    motivo = f"{len(nao_medidos)} arquivo(s) não medido(s) neste nó" if nao_medidos else ""
    return Resultado(estado, no, testes, falhas, resumo, motivo, saida, nao_medidos=nao_medidos,
                     vazios=[t for t in med.vazios if t not in sem_casos], sem_casos=sem_casos)


def teto_lote(n_testes: int, paralelo: int) -> int:
    """s que o MAIOR lote do nó pode levar: base + TETO_POR_ARQ × arquivos dele, nunca acima do TETO_NO."""
    por_lote = -(-n_testes // max(1, min(paralelo, n_testes or 1)))
    return int(min(TETO_NO, TETO_BASE + TETO_POR_ARQ * por_lote))


def montar_script(sha: str, testes: list[str], paralelo: int, run: str, teto: int, ref: str) -> str:
    cab = {"SHA": sha, "REF": ref, "ORIGEM": ORIGEM, "RUN": run, "PAR": str(max(1, min(paralelo, len(testes)))),
           "TESTES": " ".join(testes), "TETO": str(teto), "PARADO": str(PARADO)}
    return "".join(f"{k}={shlex.quote(v)}\n" for k, v in cab.items()) + CORPO_NO.read_text(encoding="utf-8")


def rodar_no(no: No, sha: str, testes: list[str], run: str, ref: str) -> Resultado:
    teto = teto_lote(len(testes), no.paralelo)
    script = montar_script(sha, testes, no.paralelo, f"{run}-{no.nome}", teto, ref)
    t0 = time.time()
    rc, out = _rodar(no.argv, script, teto + MARGEM_SSH)
    r = interpretar(no.nome, testes, rc, out)
    r.segundos = time.time() - t0
    return r


def dividir(testes: list[str], nos: list[No], custo: dict[str, int]) -> dict[str, list[str]]:
    """Guloso por custo (tamanho do arquivo): o mais caro vai para o nó com menos carga relativa ao peso."""
    carga = {n.nome: 0.0 for n in nos}
    partes: dict[str, list[str]] = {n.nome: [] for n in nos}
    peso = {n.nome: n.peso for n in nos}
    for t in sorted(testes, key=lambda x: (-custo.get(x, 1), x)):
        alvo = min(carga, key=lambda k: ((carga[k] + custo.get(t, 1)) / peso[k], k))
        partes[alvo].append(t)
        carga[alvo] += custo.get(t, 1)
    return {k: sorted(v) for k, v in partes.items() if v}


@dataclass
class Veredito:
    estado: str                       # "aprovado" | "reprovado" | "nao_medido"
    resultados: list[Resultado]
    motivo: str = ""
    sem_casos: list[str] = field(default_factory=list)
    pulados: list[str] = field(default_factory=list)      # "itcampo pulado: carga …" (vai para o log)


def executar(sha: str, testes: list[str], custo: dict[str, int] | None = None,
             nos: tuple[No, ...] | None = None, ref: str = "") -> Veredito:
    run = f"{time.strftime('%Y%m%d%H%M%S')}-{os.getpid()}"
    ref = ref or sha
    nos = nos or NOS
    pulados: list[str] = []
    vivos = nos_vivos(nos, pulados)
    if not vivos:
        return Veredito("nao_medido", [], "nenhum nó de teste respondeu (" + ", ".join(n.nome for n in nos) + ")")
    v = _executar_nos(sha, testes, custo, vivos, run, ref)
    v.pulados = pulados
    return v


def _executar_nos(sha: str, testes: list[str], custo: dict[str, int] | None, vivos: list[No], run: str,
                  ref: str) -> Veredito:
    if len(testes) >= LIMIAR_PARALELO and len(vivos) > 1:
        partes = dividir(testes, vivos, custo or {})
    else:
        partes = {vivos[0].nome: list(testes)}     # VM-2 primeiro (ordem de NOS); fora, o it-campo
    por_nome = {n.nome: n for n in vivos}
    with ThreadPoolExecutor(len(partes)) as ex:
        res = list(ex.map(lambda kv: rodar_no(por_nome[kv[0]], sha, kv[1], run, ref), partes.items()))
    finais: list[Resultado] = []
    caidos = {r.no for r in res if r.estado == "infra"}
    for r in res:
        if r.estado != "infra":
            finais.append(r)
            continue
        outro = next((n for n in vivos if n.nome not in caidos), None)
        if outro is None:
            return Veredito("nao_medido", [*finais, r], f"{r.no}: {r.motivo}; nenhum outro nó para refazer a parte dele")
        print(f"[portão] {r.no} não mediu ({r.motivo}) — refazendo os {len(r.testes)} arquivos no {outro.nome}",
              file=sys.stderr)
        r2 = rodar_no(outro, sha, r.testes, run + "-refeito", ref)
        if r2.estado == "infra":
            return Veredito("nao_medido", [*finais, r, r2], f"{r.no}: {r.motivo}; {outro.nome}: {r2.motivo}")
        finais.append(r2)
    finais = _confirmar_na_referencia(finais, vivos, sha, run, ref)
    finais = _refazer_nao_medidos(finais, [n for n in vivos if n.nome not in caidos], sha, run, ref)
    sem_casos = sorted({t for r in finais for t in r.sem_casos})
    pendentes = sorted({t for r in finais for t in r.nao_medidos} - set(sem_casos))
    if pendentes:
        return Veredito("reprovado", finais, f"não medido: {len(pendentes)} arquivo(s) — nenhum nó terminou "
                                             + ", ".join(pendentes[:10]) + (" …" if len(pendentes) > 10 else ""),
                        sem_casos=sem_casos)
    estado = "aprovado" if all(r.estado == "ok" for r in finais) else "reprovado"
    return Veredito(estado, finais, sem_casos=sem_casos)


def _refazer_nao_medidos(finais: list[Resultado], vivos: list[No], sha: str, run: str, ref: str) -> list[Resultado]:
    """A parte que um nó não mediu (TETO, lote sem resumo, coleta parcial) é refeita nos OUTROS nós vivos, em ordem
    (a referência primeiro). O que sobra fica em `nao_medidos` e o `executar` reprova — nunca vira aprovação."""
    saida: list[Resultado] = []
    for r in finais:
        saida.append(r)
        pend, tentados = list(r.nao_medidos), {r.no}
        while pend:
            outro = next((n for n in sorted(vivos, key=lambda n: not n.referencia) if n.nome not in tentados), None)
            if outro is None:
                break
            tentados.add(outro.nome)
            print(f"[portão] {r.no} não mediu {len(pend)} arquivo(s) — refazendo no {outro.nome}", file=sys.stderr)
            r2 = rodar_no(outro, sha, pend, f"{run}-refaz{len(tentados)}", ref)
            if r2.estado == "infra":
                continue
            r2 = _confirmar_na_referencia([r2], vivos, sha, run, ref)[0]
            # vazio em lote limpo aqui E no nó anterior: duas rodadas limpas, nós diferentes → "sem casos"
            dois = [t for t in r2.vazios if t in r.vazios]
            r2.sem_casos += dois
            r2.nao_medidos = [t for t in r2.nao_medidos if t not in dois]
            r.nao_medidos, pend = [], r2.nao_medidos
            r.motivo = (r.motivo + " · " if r.motivo else "") + f"refeitos no {outro.nome}"
            saida.append(r2)
            r = r2
    return saida


_NODEID = re.compile(r"^(?:FAILED|ERROR) (\S+?\.py)\b")


def _confirmar_na_referencia(finais: list[Resultado], vivos: list[No], sha: str, run: str, ref: str) -> list[Resultado]:
    """Falha vista num nó ACELERADOR (it-campo) é refeita no nó de REFERÊNCIA (VM-2, o ambiente do CI) antes de
    reprovar. Medido em 24/11: o WSL do it-campo não tinha `unzip` (nem zstd, node, ffmpeg, xvfb-run), e
    tests/test_socio_pj_raiz.py falhava lá com FileNotFoundError e passava na VM-2. Instalados no mesmo dia por apt
    (root do WSL pelo lado Windows; /usr/bin, já no PATH do `bash -s`): os 7 arquivos que só falhavam lá passam
    (51 testes). A confirmação fica para a próxima diferença de ambiente. Vale o veredito da referência —
    se ela também falha, reprova; se ela está fora, a falha fica (bloquear é o lado seguro) e o motivo é dito."""
    ref_no = next((n for n in vivos if n.referencia), None)
    saida: list[Resultado] = []
    for r in finais:
        no = next((n for n in vivos if n.nome == r.no), None)
        if r.estado != "falhou" or no is None or no.referencia:
            saida.append(r)
            continue
        arquivos = sorted({m.group(1) for f in r.falhas if (m := _NODEID.match(f))})
        if ref_no is None or not arquivos:
            r.motivo = (r.motivo + " · " if r.motivo else "") + (
                "sem nó de referência vivo para confirmar" if ref_no is None else "falha sem nodeid para refazer")
            saida.append(r)
            continue
        print(f"[portão] {r.no} acusou {len(arquivos)} arquivo(s) — confirmando na {ref_no.nome} (referência)",
              file=sys.stderr)
        conf = rodar_no(ref_no, sha, arquivos, run + "-confirma", ref)
        if conf.estado == "infra":
            r.motivo = f"confirmação na {ref_no.nome} não mediu ({conf.motivo})"
            saida.append(r)
            continue
        if conf.estado == "ok" and conf.nao_medidos:
            r.motivo = f"confirmação na {ref_no.nome} não mediu {len(conf.nao_medidos)} arquivo(s)"
            saida.append(r)
            continue
        if conf.estado == "ok":
            print(f"[portão]   {', '.join(arquivos)}: falha só no {r.no} (ambiente) — a {ref_no.nome} passa",
                  file=sys.stderr)
        r.estado = "ok" if conf.estado == "ok" else "falhou"
        r.motivo = f"falha do {r.no} refeita na {ref_no.nome}: {conf.estado}"
        r.falhas = conf.falhas
        r.resumo = [*r.resumo, *(f"{ref_no.nome}: {x}" for x in conf.resumo)]
        saida.append(r)
    return saida


def _git(*args: str, repo: Path | None = None) -> str:
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:3])}: {r.stderr.strip()[:200]}")
    return r.stdout.strip()


def base_do_push(sha_local: str, sha_remoto: str, repo: Path) -> str:
    """Contra o que o remoto já tem; ref nova → merge-base com o upstream/origin/HEAD; sem nada → o pai."""
    if sha_remoto != ZERO:
        try:
            _git("cat-file", "-e", f"{sha_remoto}^{{commit}}", repo=repo)
            return sha_remoto
        except RuntimeError:
            print(f"[portão] o remoto está em {sha_remoto[:10]}, que não existe aqui — medindo contra o pai",
                  file=sys.stderr)
    for ref in ("@{u}", "origin/HEAD", "origin/main"):
        try:
            return _git("merge-base", sha_local, ref, repo=repo)
        except RuntimeError:
            continue
    return f"{sha_local}~1"


def _custo(repo: Path, sha: str, testes: list[str]) -> dict[str, int]:
    arv = portao_grafo.arvore(repo, sha)
    return {t: arv[t][1] for t in testes if t in arv}


def _imprimir(v: Veredito) -> None:
    for r in v.resultados:
        print(f"[portão]   {r.no}: {r.estado} · {len(r.testes)} arquivo(s) em {r.segundos:.0f} s · "
              + " | ".join(r.resumo or [r.motivo]))
        for f in r.falhas[:15]:
            print(f"[portão]     {f}")
        if r.nao_medidos:
            print(f"[portão]     NÃO MEDIDOS ({len(r.nao_medidos)}): " + ", ".join(r.nao_medidos[:10]))
    if v.sem_casos:
        print(f"[portão] sem casos: {len(v.sem_casos)} arquivo(s): " + ", ".join(v.sem_casos)
              + " (0 casos no junit em 2 rodadas limpas — aceito, não é teste)")


def medir(repo: Path, base: str, sha: str) -> Veredito:
    sel = portao_grafo.selecionar(repo, base, sha)
    print(f"[portão] {sha[:10]} contra {base[:10]}: {len(sel.mudados)} arquivo(s) mudados → {len(sel.testes)} arquivo(s)"
          f" de teste {json.dumps(sel.motivos, ensure_ascii=False)}")
    t0 = time.time()
    # ref temporária: o nó busca por ela (o upload-pack não serve commit que não seja ponta de ref anunciada)
    ref = f"refs/portao/{time.strftime('%Y%m%d%H%M%S')}-{os.getpid()}"
    _git("update-ref", ref, sha, repo=repo)
    try:
        v = executar(sha, sel.testes, _custo(repo, sha, sel.testes), ref=ref)
    finally:
        _git("update-ref", "-d", ref, repo=repo)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(f"\n=== {time.strftime('%F %T')} {sha} base {base} → {v.estado} em {time.time() - t0:.0f} s\n")
        for msg in v.pulados:
            fh.write(f"{msg}\n")
        if v.sem_casos:
            fh.write(f"sem casos: {len(v.sem_casos)} arquivo(s): {' '.join(v.sem_casos)}\n")
        for r in v.resultados:
            fh.write(f"--- {r.no} ({r.estado}, {r.segundos:.0f} s) {r.motivo}\n{r.saida}\n")
    _imprimir(v)
    print(f"[portão] {v.estado} em {time.time() - t0:.0f} s (log: {LOG})" + (f" — {v.motivo}" if v.motivo else ""))
    return v


def _scan_pii(repo: Path, base: str, sha: str) -> bool:
    """O0.5: o repo é público — CPF com DV válido no diff do push bloqueia. Barato e local (só o diff)."""
    py = Path(_git("rev-parse", "--git-common-dir", repo=repo)).resolve()
    py = (py if py.name != ".git" else py.parent) / ".venv" / "bin" / "python"
    r = subprocess.run([str(py if py.exists() else sys.executable), "-m", "tools.scan_pii", "--faixa", f"{base}..{sha}"],
                       cwd=repo, timeout=300)
    return r.returncode == 0


def pre_push(remoto: str, url: str, linhas: list[str], repo: Path) -> int:
    from tools import push_divida

    pedidos = []
    for ln in linhas:
        partes = ln.split()
        if len(partes) != 4:
            continue
        ref_local, sha_local, ref_remota, sha_remoto = partes
        if sha_local == ZERO:          # apagar ref remota: não há código a testar
            continue
        pedidos.append((ref_local, sha_local, ref_remota, base_do_push(sha_local, sha_remoto, repo)))
    if not pedidos:
        print("[portão] nada a testar neste push (só remoção de ref)")
        return 0
    for ref_local, sha, ref_remota, base in pedidos:
        if not _scan_pii(repo, base, sha):
            print(f"[portão] ⛔ CPF com DV válido no que este push leva ({base[:10]}..{sha[:10]}) — mascare antes de subir")
            return 1
        v = medir(repo, base, sha)
        if v.estado == "reprovado":
            print(f"[portão] ❌ BLOQUEADO — {v.motivo or 'teste falhando'} em {sha[:10]} (o CI mandaria e-mail de falha)")
            return 1
        if v.estado == "nao_medido":
            push_divida.registrar(sha=sha, ref_local=ref_local, ref_remota=ref_remota, remoto=remoto, url=url,
                                  repo=str(repo), motivo=v.motivo)
            print(f"[portão] ❌ BLOQUEADO — NÃO MEDIDO: {v.motivo}.\n"
                  f"[portão]    Registrado em data/push_divida.json. Quando um nó voltar:"
                  f" .venv/bin/python -m tools.push_divida drenar")
            return 1
        push_divida.quitar(sha, ref_remota, "aprovado no portão")
    print("[portão] ✅ aprovado")
    return 0


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(line_buffering=True)      # o hook mistura stdout e stderr: na ordem em que acontecem
    repo = Path(_git("rev-parse", "--show-toplevel"))
    if argv[:1] == ["pre-push"] and len(argv) >= 2:
        return pre_push(argv[1], argv[2] if len(argv) > 2 else "", sys.stdin.read().splitlines(), repo)
    if argv[:1] == ["testar"] and len(argv) == 3:
        v = medir(repo, _git("rev-parse", argv[1], repo=repo), _git("rev-parse", argv[2], repo=repo))
        return {"aprovado": 0, "reprovado": 1}.get(v.estado, 3)
    if argv[:1] == ["nos"]:
        with ThreadPoolExecutor(len(NOS)) as ex:
            sondas = list(ex.map(sondar, NOS))
        for n, sd in zip(NOS, sondas):
            alem = sd.sobrecarga()
            estado = "NÃO responde" if not sd.vivo else (
                f"responde · {sd.carga()}" + (f" · SOBRECARGA ({alem})" + ("" if n.referencia else " — pulado")
                                              if alem else ""))
            print(f"{n.nome}: {estado}")
        return 0 if any(sd.vivo for sd in sondas) else 3
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
