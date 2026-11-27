# -*- coding: utf-8 -*-
"""Supervisor do motor de fluxo — um por máquina (`jfn-fluxo@<no>.service`; plano mestre v2 §3.3).

O laço SÓ ESCOLHE. Cada volta:
  1. mede a pressão (governador) e grava o heartbeat do nó em `nos`;
  2. se tiver a liderança (advisory lock 42), roda o planejador;
  3. colhe os filhos que terminaram: handler ok → filho de CONFERÊNCIA do efeito → concluir (feito/falhou_efeito,
     eventos na mesma transação) · erro → falhar (backoff/quarentena) · tempo estourado → mata e falha;
  4. renova o lease dos filhos vivos — lease perdido (outro nó assumiu) ⇒ mata o filho, o trabalho dele não vale;
  5. reserva jobs enquanto houver slot livre e lança cada um em SUBPROCESSO ISOLADO:
     `systemd-run --user --scope --slice=jfn-coletor.slice -p MemoryMax=… -p CPUWeight=…` + `timeout` (a fatia do
     egress da O0.4: deploy/seguranca/nftables-egress.nft casa por cgroup v2 — job sem rede interna), quando o
     systemd do usuário responde; senão subprocess com `prlimit` (RLIMIT_DATA), nice e `timeout`. Na reserva: só
     estágio LIBERADO (O9.0), slot transitório do yaml só para as rotinas dele (D1) e o ritmo da assinatura lido
     do PG (fluxo/ritmo.py; sem medição = porta fechada) somado ao guarda local.
Entre voltas espera `LISTEN jfn_jobs` (job novo acorda na hora), no máximo 60 s — 2 s com filho rodando.

Catraca (tests/test_fluxo_supervisor.py): este módulo não importa `compliance_agent.aplicacao` e o handler roda
num PID diferente do supervisor. Matar o supervisor no meio não perde o job: o lease vence e o planejador o
devolve à fila (o estágio é idempotente pela chave).
"""
from __future__ import annotations

import json
import logging
import os
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping

from compliance_agent.evidencias import ENV_DSN, dsn_vigente
from compliance_agent.fluxo import fila, fonte_coleta, governador, planejador, schema
from compliance_agent.fluxo import grafo as grafo_mod
from compliance_agent.fluxo.fila import Job, Resultado

log = logging.getLogger("jfn.fluxo.supervisor")
RAIZ = Path(__file__).resolve().parents[2]
MODULO_FILHO = "compliance_agent.fluxo.executar"

# teto por recurso: (MemoryMax, CPUWeight, tempo máximo em s). Job com vários recursos pega o mais folgado.
LIMITES: dict[str, tuple[str, int, int]] = {
    "cpu_leve": ("1G", 50, 900), "cpu_pesado": ("3G", 30, 3600), "navegador": ("3G", 50, 3600),
    "gpu": ("6G", 50, 7200), "llm": ("1G", 20, 1800), "materializar": ("1G", 200, 600), "disco": ("1G", 20, 3600),
}
LIMITE_CONFERIR = ("512M", 50, 120)
# teto de memória do filho SEM systemd: RLIMIT_DATA (heap + mmap anônimo ≈ memória de fato). NÃO RLIMIT_AS: o Chromium
# reserva dezenas de GB de espaço de endereço e morre ao abrir sob qualquer RLIMIT_AS (medido na VM-2 em 25/11 com 2 e
# 8 GB; com RLIMIT_DATA de 2 GB gera o PDF) — o E16 (PDF) e o navegador real do E2/E3 caíam em quarentena.
RLIMIT_FILHO = resource.RLIMIT_DATA
PLANEJAR_A_CADA_S = 10.0
ESPERA_OCIOSA_S = 60.0
ESPERA_COM_FILHO_S = 2.0
SAIDA_PERMANENTE = 3                  # = executar.SAIDA_PERMANENTE (sem importar o filho: catraca)
SAIDA_ADIADO = 4                      # = executar.SAIDA_ADIADO: espera conhecida, sem gastar tentativa


def _bytes(txt: str) -> int:
    mult = {"K": 1 << 10, "M": 1 << 20, "G": 1 << 30}
    return int(float(txt[:-1]) * mult[txt[-1]]) if txt[-1] in mult else int(txt)


def limites_do_job(recursos: list[str], payload: Mapping | None = None) -> tuple[str, int, int]:
    escolhidos = [LIMITES.get(r, LIMITES["cpu_leve"]) for r in (recursos or ["cpu_leve"])]
    mem = max((m for m, _, _ in escolhidos), key=_bytes)
    peso = min(p for _, p, _ in escolhidos)
    tempo = int((payload or {}).get("timeout_s") or max(t for _, _, t in escolhidos))
    return mem, peso, tempo


def montar_comando(fase: str, entrada: Path, saida: Path, limites: tuple[str, int, int], isolamento: str,
                   python: str = sys.executable, unidade: str | None = None) -> list[str]:
    """Função pura: o argv exato do filho. `isolamento` = 'systemd' ou 'subprocesso'."""
    mem, peso, tempo = limites
    base = [python, "-m", MODULO_FILHO, fase, str(entrada), str(saida)]
    if shutil.which("timeout"):
        base = ["timeout", "-k", "10", str(tempo)] + base
    if isolamento == "systemd":
        # Wants+After do jfn-egress: fatia que (re)nasce com este escopo só o executa depois de a regra nftables ser
        # recarregada para o ID novo do cgroup (medido 24/11: sem isso, ms de janela com egress aberto). Onde a unit
        # não existe (it-campo), Wants/After de unit ausente não bloqueiam.
        return ["systemd-run", "--user", "--scope", "--quiet", "--slice=jfn-coletor.slice",
                "-p", "Wants=jfn-egress.service", "-p", "After=jfn-egress.service",
                "-p", f"MemoryMax={mem}", "-p", f"CPUWeight={peso}"] + ([f"--unit={unidade}"] if unidade else []) \
            + ["--"] + base
    return base


def _hash_yaml() -> str:
    import hashlib
    return hashlib.sha256(Path(grafo_mod.CAMINHO).read_bytes()).hexdigest()


def matar_escopo(unidade: str | None) -> None:
    """Mata o escopo INTEIRO do job (25/11/2026: neto destacado sobrevivia ao `timeout`/killpg — o despachante antigo
    ficou órfão horas com 1 GB). Escopo já vazio/inexistente: nada a fazer."""
    if unidade:
        subprocess.run(["systemctl", "--user", "kill", "--signal=SIGKILL", f"{unidade}.scope"],
                       capture_output=True, timeout=15)


def systemd_disponivel() -> bool:
    """O systemd do usuário aceita escopo transitório? (cron sem barramento e contêiner não aceitam)."""
    if not shutil.which("systemd-run"):
        return False
    try:
        r = subprocess.run(["systemd-run", "--user", "--scope", "--quiet", "true"], capture_output=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0


def motivo_ritmo(tarefa: str) -> str | None:
    """O MESMO guarda de LLM do despachante antigo (`propagacao._motivo_ritmo`): `llm/contingencia.motivo_bloqueio`,
    que lê `llm/ritmo_assinatura` e o teto diário do motor. None = pode; leitura que falha = espera (nunca fura o
    teto). Atenção: o arquivo de medição mora na máquina que roda `ritmo_assinatura --medir` (VM-1)."""
    try:
        from compliance_agent.fluxo import ritmo as ritmo_pg
        return ritmo_pg.motivo_local(tarefa)         # contingência + a exceção do dono (só no escopo do ensaio)
    except (ImportError, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        return f"guarda de ritmo ilegível ({type(exc).__name__}: {exc})"[:300]


def _rss_kb(pid: int) -> int:
    try:
        for ln in Path(f"/proc/{pid}/status").read_text().splitlines():
            if ln.startswith("VmRSS:"):
                return int(ln.split()[1])
    except (OSError, ValueError):
        pass
    return 0


def _rss_grupo_kb(pgid: int) -> int:
    """RSS somada do grupo de processos do job (o filho direto é só o invólucro `timeout`; o trabalho está nos netos)."""
    total = 0
    for d in Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        try:
            if os.getpgid(int(d.name)) == pgid:
                total += _rss_kb(int(d.name))
        except (OSError, ValueError):
            continue
    return total


@dataclass
class Filho:
    job: Job
    fase: str                                   # 'rodar' | 'conferir'
    proc: subprocess.Popen
    pasta: Path
    inicio: float
    tempo_max: float
    resultado: dict | None = None
    parado: bool = False                        # SIGSTOP do governador
    unidade: str | None = None                  # escopo systemd nomeado (morto inteiro ao encerrar)


@dataclass
class Supervisor:
    no: str
    dsn: str | None = None
    esquema: str | None = None
    slots: dict[str, int] | None = None
    grafo: Mapping[str, list] | None = None        # None = config/fluxo.yaml (grafo.carregar)
    contrato: Mapping[str, Mapping] | None = None
    tetos: Mapping[str, int] | None = None
    ritmos: set[str] | None = None
    ritmo: Callable[[str], str | None] | None = None   # None = PG (fluxo/ritmo.py) + guarda local (motivo_ritmo)
    restritos: Mapping[str, list[str]] | None = None   # slot transitório do nó → tipos que podem usá-lo (D1)
    terminais: Mapping[str, str] | None = None         # 'fonte/tipo' sem consumidor DECLARADO (grafo.terminais)
    dividas: Mapping[str, str] | None = None           # evento sem consumidor com motivo declarado (saúde)
    nos_esperados: tuple[str, ...] | None = None       # nós do yaml: fora = DEGRADADO na saúde do ciclo (1.15)
    prazo_s: float = 120.0
    isolamento: str = "auto"                    # auto | systemd | subprocesso
    chave_lideranca: int = planejador.CHAVE_LIDERANCA
    medir: Callable[[], governador.Medida] = governador.medir
    filhos: list[Filho] = field(default_factory=list)

    def __post_init__(self):
        self.dsn = self.dsn or dsn_vigente()
        self.esquema = schema.validar_esquema(self.esquema or fila.esquema_vigente())
        slots_dados = self.slots is not None
        self.slots = dict(self.slots if slots_dados else governador.SLOTS_INICIAIS.get(self.no, {}))
        self._hash_grafo = None                      # só o grafo REAL (lido do yaml) se recarrega a quente
        self._teto_vivo: dict[str, int] = {}         # teto adaptativo vigente (fluxo.teto_adaptativo), relido a cada 60 s
        self._teto_lido_em = 0.0
        if self.grafo is None:                       # o grafo real: inválido ⇒ o supervisor não sobe (portão)
            self._hash_grafo = _hash_yaml()
            g = grafo_mod.carregar()
            if not slots_dados:                      # §3.4 + o transitório declarado no yaml (D1), nada além
                self.slots = g.slots_do_no(self.no)
            self.restritos = g.restritos_do_no(self.no) if self.restritos is None else self.restritos
            self.grafo = g.grafo_planejador()
            self.contrato = g.contrato() if self.contrato is None else self.contrato
            self.tetos = g.tetos() if self.tetos is None else self.tetos
            self.ritmos = g.ritmos() if self.ritmos is None else self.ritmos
            self.terminais = g.terminais() if self.terminais is None else self.terminais
            self.dividas = g.dividas() if self.dividas is None else self.dividas
            self.nos_esperados = tuple(g.nos) if self.nos_esperados is None else self.nos_esperados
        self.tetos = dict(self.tetos or {})
        self.terminais = dict(self.terminais or {})
        self.dividas = dict(self.dividas or {})
        self.nos_esperados = tuple(self.nos_esperados or ())
        self.ritmos = set(self.ritmos or ())
        if self.isolamento == "auto":
            self.isolamento = "systemd" if systemd_disponivel() else "subprocesso"
        self.restritos = dict(self.restritos or {})
        self.con = fila.conectar(self.dsn, self.esquema)
        if self.ritmo is None:
            self.ritmo = self._motivo_ritmo
        v = schema.verificar(self.con, self.esquema)
        if not v["ok"]:
            raise RuntimeError(f"schema {self.esquema} incompleto: {v['faltando']}")
        self._con_lider = None
        self._lider = False
        self._ultimo_plano = 0.0
        self._contido_seguidas = 0
        self._parar = False
        self.versao = self._versao()

    # ── utilidades ──
    @staticmethod
    def _versao() -> str | None:
        try:
            r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=RAIZ, capture_output=True, text=True,
                               timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return r.stdout.strip() or None

    def _ocupados(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for f in self.filhos:
            for r in f.job.recursos:
                out[r] = out.get(r, 0) + 1
        return out

    def _env_filho(self) -> dict:
        env = dict(os.environ)
        env[ENV_DSN] = self.dsn
        env[fila.ENV_ESQUEMA] = self.esquema
        env["JFN_NO"] = self.no                  # o filho sabe em que nó roda (lateral/captura fora da VM-2, 26/11/2026)
        env["PYTHONPATH"] = os.pathsep.join(p for p in (str(RAIZ), env.get("PYTHONPATH", "")) if p)
        return env

    # ── liderança ──
    def _liderar(self) -> bool:
        if self._con_lider is None or self._con_lider.closed:
            self._con_lider = fila.conectar(self.dsn, self.esquema)
        self._lider = planejador.tentar_lideranca(self._con_lider, self.chave_lideranca)
        return self._lider

    # ── filhos ──
    def _lancar(self, job: Job, fase: str, pasta: Path | None = None, resultado: dict | None = None) -> None:
        pasta = pasta or Path(tempfile.mkdtemp(prefix=f"jfn-fluxo-{job.id}-"))
        entrada, saida = pasta / f"{fase}.entrada.json", pasta / f"{fase}.saida.json"
        entrada.write_text(json.dumps({"tipo": job.tipo, "chave": job.chave, "ficha": job.ficha, "no": self.no,
                                       "tentativa": job.tentativas, "correlation_id": job.correlation_id,
                                       "payload": job.payload, "resultado": resultado}, default=str),
                           encoding="utf-8")
        lim = LIMITE_CONFERIR if fase == "conferir" else limites_do_job(job.recursos, job.payload)
        unidade = f"jfn-job-{job.id}-{job.ficha}-{fase}" if self.isolamento == "systemd" else None
        cmd = montar_comando(fase, entrada, saida, lim, self.isolamento, unidade=unidade)
        mem = _bytes(lim[0])

        def _teto():                                     # só no ramo sem systemd: prlimit + nice
            resource.setrlimit(RLIMIT_FILHO, (mem * 2, mem * 2))         # folga para o mapa do Python
            os.nice(10)
        with open(pasta / f"{fase}.stderr", "wb") as err:
            proc = subprocess.Popen(cmd, cwd=RAIZ, env=self._env_filho(), stdout=subprocess.DEVNULL, stderr=err,
                                    start_new_session=True,
                                    preexec_fn=_teto if self.isolamento != "systemd" else None)
        self.filhos.append(Filho(job=job, fase=fase, proc=proc, pasta=pasta, inicio=time.monotonic(),
                                 tempo_max=lim[2] + 15, resultado=resultado, unidade=unidade))
        log.info("lançou %s %s (ficha %s, pid %s)", fase, job.chave, job.ficha, proc.pid)

    @staticmethod
    def _matar(f: Filho) -> None:
        try:
            os.killpg(f.proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        matar_escopo(f.unidade)
        f.proc.wait(timeout=30)

    def _encerrar(self, f: Filho) -> None:
        matar_escopo(f.unidade)                          # o que sobrou no escopo depois do job é órfão
        self.filhos.remove(f)
        shutil.rmtree(f.pasta, ignore_errors=True)

    def _stderr(self, f: Filho) -> str:
        try:
            return (f.pasta / f"{f.fase}.stderr").read_text(encoding="utf-8", errors="replace")[-1500:]
        except OSError:
            return ""

    def _colher(self) -> dict:
        r = {"feito": 0, "falhou_efeito": 0, "volta_efeito": 0, "falhou": 0, "adiado": 0, "recusado": 0}
        for f in list(self.filhos):
            rc = f.proc.poll()
            if rc is None:
                if time.monotonic() - f.inicio > f.tempo_max:
                    self._matar(f)
                    self._contar(r, fila.falhar(self.con, f.job.ficha, f"tempo estourado na fase {f.fase}",
                                                True, "timeout"), "falhou")
                    self._encerrar(f)
                continue
            dados = self._saida(f)
            if rc == 0 and dados is None:
                # S4: saída 0 sem o JSON (ou corrompido) não é "efeito vazio" — é falha do filho, transitória
                self._contar(r, fila.falhar(self.con, f.job.ficha, f"fase {f.fase} saiu 0 sem {f.fase}.saida.json "
                                            f"legível {self._stderr(f)}", True, "saida"), "falhou")
            elif rc == 0 and f.fase == "rodar":
                matar_escopo(f.unidade)                  # o rodar acabou: neto que ficou no escopo é órfão
                self.filhos.remove(f)                    # a mesma pasta segue para a conferência
                self._lancar(f.job, "conferir", f.pasta, dados)
                continue
            elif rc == 0:
                conf = dados.get("conferencia")
                ok = bool(dados.get("conferido"))
                efeito = dict((f.resultado or {}).get("efeito") or {})
                if conf is not None:
                    efeito["conferencia"] = conf
                res = Resultado(efeito=efeito, efeito_conferido=ok, eventos=(f.resultado or {}).get("eventos") or [])
                motivo = None if ok else ("efeito não conferido: " + json.dumps(conf, ensure_ascii=False, default=str)
                                          if conf is not None else "efeito não conferido (a conferência não disse por quê)")
                if not ok and isinstance(conf, dict) and conf.get("continua"):
                    # parcial COM progresso nesta posse (estágio por janela, ex. E3 em lotes de 40): continua já,
                    # sem gastar tentativa — 26/11/2026: processo grande ia à quarentena avançando a cada volta
                    from datetime import datetime, timedelta, timezone
                    self._contar(r, fila.adiar(self.con, f.job.ficha, "parcial com progresso: " + motivo,
                                               datetime.now(timezone.utc) + timedelta(seconds=fila.ADIADO_MIN_S)),
                                 "adiado")
                else:
                    estado = fila.concluir(self.con, f.job.ficha, res, motivo)
                    self._contar(r, estado, {"fila": "volta_efeito"}.get(estado or "", estado or "recusado"))
            elif rc == SAIDA_ADIADO:
                d = dados or {}
                self._contar(r, fila.adiar(self.con, f.job.ficha, d.get("adiado") or self._stderr(f),
                                           d.get("reabre_em")), "adiado")
            elif rc == SAIDA_PERMANENTE:
                self._contar(r, fila.falhar(self.con, f.job.ficha, (dados or {}).get("erro") or self._stderr(f),
                                            False, "permanente"), "falhou")
            else:
                self._contar(r, fila.falhar(self.con, f.job.ficha, f"rc={rc} {self._stderr(f)}", True,
                                            "conferencia" if f.fase == "conferir" else "erro"), "falhou")
            self._encerrar(f)
        return r

    @staticmethod
    def _saida(f: Filho) -> dict | None:
        """O JSON de saída do filho; None = ausente, ilegível ou não é objeto."""
        try:
            d = json.loads((f.pasta / f"{f.fase}.saida.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return d if isinstance(d, dict) else None

    @staticmethod
    def _contar(r: dict, estado: str | None, chave: str) -> None:
        r["recusado" if estado is None else chave] += 1

    def _renovar(self) -> int:
        perdidos = 0
        for f in list(self.filhos):
            if not fila.heartbeat(self.con, f.job.ficha, self.prazo_s):
                log.warning("lease perdido: %s (ficha %s) — filho morto", f.job.chave, f.job.ficha)
                self._matar(f)
                self._encerrar(f)
                perdidos += 1
        return perdidos

    def _aplicar_acao(self, d: governador.Decisao) -> None:
        if d.acao in ("matar", "suspender") and self.filhos:
            rss = {id(f): _rss_grupo_kb(f.proc.pid) for f in self.filhos if not f.parado}
            alvo = max((f for f in self.filhos if not f.parado), key=lambda f: rss[id(f)], default=None)
            if alvo and d.acao == "matar" and not governador.vale_matar(rss[id(alvo)]):
                log.warning("governador: pressão de memória (%s) sem job que pese ≥ %d MB aqui — nada a matar "
                            "(maior: %s, %d MB)", d.motivos, governador.MATAR_MIN_KB // 1024, alvo.job.chave,
                            rss[id(alvo)] // 1024)
            elif alvo and d.acao == "matar":
                log.warning("governador: SIGKILL em %s (%s)", alvo.job.chave, d.motivos)
                self._matar(alvo)
                fila.falhar(self.con, alvo.job.ficha, f"morto pelo governador: {d.motivos}", True, "pressao")
                self._encerrar(alvo)
            elif alvo and not any(f.parado for f in self.filhos):     # um suspenso por vez
                log.warning("governador: SIGSTOP em %s (%s)", alvo.job.chave, d.motivos)
                os.killpg(alvo.proc.pid, signal.SIGSTOP)
                alvo.parado = True
        elif d.estado == "folga":
            for f in self.filhos:
                if f.parado:
                    os.killpg(f.proc.pid, signal.SIGCONT)
                    f.parado = False

    # ── a volta ──
    def _registrar_no(self, m: governador.Medida, d: governador.Decisao) -> None:
        self.con.execute(
            "INSERT INTO nos(no, capacidades, slots, psi, versao_codigo, heartbeat_em) VALUES (%s, %s, %s, %s, %s, "
            "now()) ON CONFLICT (no) DO UPDATE SET capacidades = EXCLUDED.capacidades, slots = EXCLUDED.slots, "
            "psi = EXCLUDED.psi, versao_codigo = EXCLUDED.versao_codigo, heartbeat_em = now()",
            (self.no, json.dumps({"isolamento": self.isolamento, "lider": self._lider}),
             json.dumps({**self.slots, **fonte_coleta.capacidades()}),        # vagas + presença (o planejador lê)
             json.dumps({**m.como_dict(), "estado": d.estado, "motivos": d.motivos, "livres": d.livres}),
             self.versao))

    def _motivo_ritmo(self, tarefa: str) -> str | None:
        """O ritmo publicado no PG (vale em qualquer nó; ausente/velho = porta fechada) E o guarda local da
        contingência (limite da conta, teto diário do motor — arquivos da VM-1). Qualquer um fechando, fecha."""
        from compliance_agent.fluxo import ritmo as ritmo_pg
        return ritmo_pg.motivo(self.con, tarefa) or motivo_ritmo(tarefa)

    def _bloqueio_da_reserva(self, bloqueados: list[str]) -> list[str]:
        """UM job da assinatura (payload com `ritmo`) por nó: o `claude_motor` roda um `claude` por vez na máquina
        (flock em data/claude_motor.lock, espera 90 s). Um 2º job de LLM no mesmo nó esperava a trava, desistia
        ("ocupado"), adiava e RELIA o texto ao voltar — passada r3 de 25/11: 36% de leitura repetida no E8/E11.
        Com um rodando aqui, todas as tarefas de ritmo ficam fora desta reserva (outro nó pode pegá-las)."""
        if any((f.job.payload or {}).get("ritmo") for f in self.filhos):
            return sorted(set(bloqueados) | set(self.ritmos))
        return bloqueados

    def recarregar_grafo_se_mudou(self, sincronizar: bool | None = None) -> dict | None:
        """Yaml mudado ⇒ relê grafo, contrato, tetos, ritmos, terminais, dívidas, slots e restritos SEM reiniciar (job
        longo segue vivo) e, no líder, ressincroniza `fluxo.agenda` (o payload leva `timeout_s`). Religação O9.0,
        26/11/2026: o yaml só era lido no boot e 8 tetos corrigidos nunca chegaram às rodadas agendadas. Yaml inválido
        ⇒ mantém o grafo anterior e devolve o erro (o portão do deploy já o recusa; aqui é defesa)."""
        if self._hash_grafo is None:
            return None
        h = _hash_yaml()
        if h == self._hash_grafo:
            return None
        try:
            g = grafo_mod.carregar()
        except Exception as exc:                     # noqa: BLE001 — qualquer yaml ruim: segue com o anterior
            log.error("yaml do fluxo mudou e é INVÁLIDO — sigo com o grafo anterior: %s", exc)
            self._hash_grafo = h
            return {"erro": f"{type(exc).__name__}: {str(exc)[:300]}"}
        self.slots, self.restritos = g.slots_do_no(self.no), dict(g.restritos_do_no(self.no) or {})
        self.grafo, self.contrato, self.tetos = g.grafo_planejador(), g.contrato(), dict(g.tetos() or {})
        self.ritmos, self.terminais = set(g.ritmos() or ()), dict(g.terminais() or {})
        self.dividas, self.nos_esperados = dict(g.dividas() or {}), tuple(g.nos or ())
        self._hash_grafo = h
        r: dict = {"recarregado": True}
        if self._lider if sincronizar is None else sincronizar:
            r["agenda"] = planejador.sincronizar_agenda(self.con, g.agenda_linhas() + g.agenda_nativa())
            r["fila_recontratada"] = planejador.reaplicar_contrato(self.con, g)   # contrato novo vale para quem espera
        log.info("yaml do fluxo recarregado a quente: %s", r)
        return r

    def tetos_efetivos(self) -> dict[str, int]:
        """Tetos de concorrência da reserva: o do yaml, limitado pelo ADAPTATIVO vigente onde houver (26/11/2026: os
        logins simultâneos no SEI são decididos pela medida — fluxo/teto_adaptativo.py). Relido a cada 60 s."""
        from compliance_agent.fluxo import teto_adaptativo as TA
        if time.monotonic() - self._teto_lido_em >= 60.0:
            self._teto_lido_em = time.monotonic()
            maximo = int(self.tetos.get(TA.ETIQUETA) or 0)
            if maximo:
                v = TA.vigente(self.con, maximo=maximo)
                self._teto_vivo = {TA.ETIQUETA: v} if v else {}
            else:
                self._teto_vivo = {}
        return {**self.tetos, **{k: min(v, self.tetos.get(k, v)) for k, v in self._teto_vivo.items()}}

    def uma_volta(self) -> dict:
        r: dict = {"no": self.no}
        if time.monotonic() - self._ultimo_plano >= PLANEJAR_A_CADA_S:
            rec = self.recarregar_grafo_se_mudou()
            if rec:
                r["grafo"] = rec
        bloqueados = sorted(t for t in self.ritmos if self.ritmo(t))
        if time.monotonic() - self._ultimo_plano >= PLANEJAR_A_CADA_S and self._liderar():
            self._ultimo_plano = time.monotonic()
            r["planejador"] = planejador.ciclo(self.con, self.grafo, self.contrato, self.terminais,
                                               self.nos_esperados, self.dividas, bloqueados)
        r["colhidos"] = self._colher()
        r["leases_perdidos"] = self._renovar()
        m = self.medir()
        d = governador.decidir(m, self.slots, self._ocupados(), self._contido_seguidas)
        self._contido_seguidas = self._contido_seguidas + 1 if d.estado == "contido" else 0
        self._aplicar_acao(d)
        self._registrar_no(m, d)
        livres, lancados = dict(d.livres), 0
        livres.update(fonte_coleta.capacidades())   # presença da fonte da coleta neste nó (26/11/2026)
        if bloqueados:
            r["ritmo_bloqueado"] = bloqueados
        while not self._parar:
            job = fila.reservar(self.con, self.no, livres, self.prazo_s, tetos=self.tetos_efetivos(),
                                ritmo_bloqueado=self._bloqueio_da_reserva(bloqueados), liberacao=True,
                                restritos=self.restritos)
            if job is None:
                break
            for rec in job.recursos:
                livres[rec] = livres.get(rec, 0) - 1
            self._lancar(job, "rodar")
            lancados += 1
        r.update(estado=d.estado, lancados=lancados, rodando=len(self.filhos))
        return r

    def drenar(self, limite_s: float = 300.0) -> dict:
        """Espera os filhos desta volta terminarem e serem concluídos (modo --uma-volta e testes)."""
        tot: dict[str, int] = {}
        fim = time.monotonic() + limite_s
        while self.filhos and time.monotonic() < fim:
            time.sleep(0.2)
            for k, v in self._colher().items():
                tot[k] = tot.get(k, 0) + v
            self._renovar()
        return tot

    def parar(self, *_):
        """SIGTERM: SÓ levanta a bandeira. O handler de sinal roda no meio do laço — talvez dentro de uma consulta na
        MESMA conexão (psycopg não é reentrante: o lock da conexão travaria o processo). Quem mata os filhos e
        devolve os jobs à fila é `encerrar_filhos`, chamado pelo laço ao sair (`rodar`)."""
        self._parar = True

    def encerrar_filhos(self, motivo: str = "supervisor parado (SIGTERM)") -> int:
        """Mata os filhos vivos e devolve os jobs à fila já (sem esperar o lease vencer). Fora do handler de sinal."""
        n = 0
        for f in list(self.filhos):
            self._matar(f)
            fila.devolver_parada(self.con, f.job.ficha, motivo)
            self._encerrar(f)
            n += 1
        return n

    def rodar(self) -> None:
        import psycopg
        signal.signal(signal.SIGTERM, self.parar)
        escuta = psycopg.connect(self.dsn, autocommit=True)
        escuta.execute("LISTEN jfn_jobs")
        try:
            while not self._parar:
                log.info("%s", self.uma_volta())
                espera = ESPERA_COM_FILHO_S if self.filhos else ESPERA_OCIOSA_S
                for _ in escuta.notifies(timeout=espera, stop_after=1):
                    pass
        finally:
            escuta.close()
            self.encerrar_filhos()
            self.fechar()

    def fechar(self) -> None:
        for c in (self._con_lider, self.con):
            if c is not None and not c.closed:
                c.close()
