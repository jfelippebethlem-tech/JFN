# -*- coding: utf-8 -*-
"""Religação O9.0 em sequência verificada — e o desfazer completo (plano mestre v2 §1.1 "Religação", §9 O9.0).

NÃO RELIGA NADA SOZINHO. Dois modos:
  --ensaio    (padrão) imprime, passo a passo, o que faria — comandos, SQL e a checagem de efeito de cada estágio.
              Só lê: o yaml, o crontab, as listas da parada e (somente leitura) o schema do PG.
  --executar  roda a sequência. Exige `--confirmo-dono-avisado` (a religação é numa janela com o dono avisado) e
              recusa se uma pré-condição falhar.

Religação (ordem da §1.1):
  0. pré-condições: grafo válido; schema `fluxo` com todas as migrações (fluxo_002: `liberacao`); crontab ainda
     comentado (`#PARADA-20261124`) — o sistema antigo e o fluxo nunca rodam juntos;
  1. `python -m compliance_agent.fluxo agenda sincronizar` (linha nova entra `ativo=false`);
  2. `jfn-fluxo@<nó>` sobe nas 3 máquinas; efeito = heartbeat de cada nó em `fluxo.nos` há < 5 min;
  3. pausas da parada (`data/.pause_*` criadas no O0.7) removidas — os comandos legados as obedecem;
  4. estágio por estágio — E17/E18 → E1 (desde = parada) → E2…E7 → E8 → E9 → E10 → E11 → E12 → E13 → E14 →
     E15 (sai a faixa de manutenção) → E16. Para cada estágio:
       a. `liberacao` ganha o estágio (o supervisor só reserva job de estágio liberado — fila.reservar);
       b. a agenda do estágio é ativada (`proximo` NULL: calcula o próximo horário, não dispara);
       c. PRIMEIRA VOLTA: um job `…:religar:<parada>` por rotina de agenda ≥ diária do estágio (E1 leva `desde`);
          semanal/mensal/condicional espera o horário (nunca roda fora dele — ex.: zelador `--aplicar`);
       d. efeito conferido: primeira volta + jobs do estágio retidos até a liberação em `feito`, nenhum em quarentena/
          falhou_efeito desde a liberação, dentro de `--espera-max-s`; registrado em `fluxo.metricas`
          (`religacao_estagio`, 1 = conferido, 0 = BLOQUEADO);
       e. falhou ⇒ o estágio fica BLOQUEADO e todo estágio que depende dele (estagios.depende, transitivo) NÃO é
          liberado; o resto segue (ressalva 1 da §1.1).
  5. 48 h de observação (§1.1 item 5) — fora deste script.

Desfazer (volta ao sistema antigo em minutos; §1.1 item 4):
  parar `jfn-fluxo@` nos 3 nós; agenda inteira `ativo=false` e `liberacao` vazia (jobs em fila ficam, parados);
  descomentar `#PARADA-20261124` no crontab; reabilitar os timers listados na parada (VM-1 e VM-2) e os serviços
  parados da VM-1; `schtasks /Change /ENABLE` (+ `/Run`) das 3 tarefas do it-campo; remover as pausas criadas;
  tirar a faixa de manutenção do jfn.service. Restaurar o snapshot é MANUAL (só se houve escrita ruim).

    python -m tools.religar_o90 --ensaio
    python -m tools.religar_o90 --desfazer --ensaio
    python -m tools.religar_o90 --executar --confirmo-dono-avisado          # só na janela, com o dono
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

RAIZ = Path(__file__).resolve().parents[1]
PARADA = "2026-11-24"
MARCA = "#PARADA-20261124 "
BACKUPS = Path.home() / ".config" / "jfn" / "backups" / "refatoracao-20261124"
LISTA_VM2 = "~/timers_parados_20261124.txt"
TAREFAS_ITCAMPO = ("JFN-SEI-Paralelo", "JFN-OCR-GPU", "JFN-Nativo")
SSH = {"vm1": None, "vm2": "vm2-ts", "itcampo": "it-campo"}
# ordem da §1.1; cada sublista é um passo, os estágios dentro dele vão um a um (efeito conferido antes do seguinte)
ORDEM = [["E17", "E18"], ["E1"], ["E2", "E3", "E4", "E5", "E6", "E7"], ["E8"], ["E9"], ["E10"], ["E11"], ["E12"],
         ["E13"], ["E14"], ["E15"], ["E16"]]
ESPERA_MAX_S = 7200
POLL_S = 30
POR = "tools/religar_o90"


@dataclass
class Passo:
    id: str
    titulo: str
    cmds: list[tuple[str, str]] = field(default_factory=list)   # (nó, comando shell)
    sql: list[str] = field(default_factory=list)
    efeito: str = ""
    estagio: str | None = None
    rotinas: list[str] = field(default_factory=list)
    nota: str = ""


def no_cmd(no: str, cmd: str) -> list[str]:
    """argv para rodar `cmd` no nó (VM-1 local; VM-2 por ssh; it-campo por ssh no Windows)."""
    host = SSH[no]
    return ["bash", "-lc", cmd] if host is None else ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", host, cmd]


def ler_lista(caminho: Path) -> list[str]:
    try:
        return [ln.strip() for ln in caminho.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except OSError:
        return []


def ler_lista_vm2(rodar=subprocess.run) -> list[str] | None:
    """Lista dos timers parados na VM-2 (só leitura, por ssh). None = ilegível (o ensaio DIZ que não leu)."""
    try:
        r = rodar(no_cmd("vm2", f"cat {LISTA_VM2}"), capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return [x.strip() for x in r.stdout.splitlines() if x.strip()] if r.returncode == 0 else None


def depende_de(g, estagio: str) -> set[str]:
    """Todos os estágios de que `estagio` depende, transitivamente."""
    out, pilha = set(), list(g.estagios[estagio].depende)
    while pilha:
        e = pilha.pop()
        if e not in out:
            out.add(e)
            pilha += g.estagios[e].depende
    return out


def diaria(r) -> bool:
    """Toda agenda da rotina dispara pelo menos uma vez por dia (e sem `condicao` de dia da semana)."""
    from compliance_agent.fluxo.planejador import Cron
    if r.condicao or not r.agenda:
        return False
    return all((c := Cron(a.cron)).dia_livre and c.dsem_livre and len(c.mes) == 12 for a in r.agenda)


def primeira_volta(g, estagio: str) -> list[str]:
    """Rotinas com agenda ≥ diária do estágio: rodam uma vez na liberação (prova de efeito; E1 recupera a lacuna).
    Semanal/mensal/condicional NÃO roda fora do horário (ex.: zelador `--aplicar` do dia 1–7) — confere no horário,
    dentro das 48 h de observação."""
    return [r for r in rotinas_do_estagio(g, estagio)[0] if diaria(g.rotinas[r])]


def rotinas_do_estagio(g, estagio: str) -> tuple[list[str], list[str]]:
    """(com agenda, só de evento) — só as ativas."""
    ag = sorted(r for r, x in g.rotinas.items() if x.ativa and x.estagio == estagio and x.agenda)
    ev = sorted(r for r, x in g.rotinas.items() if x.ativa and x.estagio == estagio and not x.agenda)
    return ag, ev


# ── plano ────────────────────────────────────────────────────────────────────────────────────────────
def plano_religar(g, pausas: list[str]) -> list[Passo]:
    py = ".venv/bin/python"
    passos = [
        Passo("R0", "pré-condições", cmds=[
            ("vm1", f"{py} -m compliance_agent.fluxo.grafo"),
            ("vm1", f"{py} -m compliance_agent.fluxo.schema aplicar && {py} -m compliance_agent.fluxo.schema verificar"),
            ("vm1", f"crontab -l | grep -c '^{MARCA.strip()}'")],
            efeito="grafo ok; schema `fluxo` com fluxo_001+fluxo_002 (verificar ok=true); crontab com as linhas "
                   "#PARADA ainda comentadas e nenhuma linha de trabalho do JFN ativa",
            nota="o `aplicar` só cria o que falta (idempotente); sem ele o supervisor não sobe (schema incompleto)"),
        Passo("R1", "agenda do yaml no PG (tudo ativo=false)",
              cmds=[("vm1", f"{py} -m compliance_agent.fluxo agenda sincronizar")],
              efeito=f"{len(g.agenda_linhas())} linhas em fluxo.agenda, todas ativo=false",
              sql=["SELECT count(*), count(*) FILTER (WHERE ativo) FROM agenda"]),
        Passo("R2", "jfn-fluxo sobe nas 3 máquinas", cmds=[
            ("vm1", "systemctl --user link ~/JFN/deploy/systemd/jfn-jobs.slice ~/JFN/deploy/systemd/jfn-fluxo@.service"
                    " && systemctl --user daemon-reload && systemctl --user enable --now jfn-fluxo@vm1"),
            ("vm2", "systemctl --user link ~/JFN-worker/deploy/systemd/jfn-jobs.slice "
                    "~/JFN-worker/deploy/systemd/jfn-fluxo@.service && systemctl --user daemon-reload "
                    "&& systemctl --user enable --now jfn-fluxo@vm2"),
            ("itcampo", "wsl -e bash -lc 'systemctl --user enable --now jfn-fluxo@itcampo'")],
            sql=["SELECT no, now() - heartbeat_em, capacidades->>'isolamento' FROM nos ORDER BY no"],
            efeito="vm1, vm2 e itcampo com heartbeat < 5 min e isolamento=systemd; nenhum job reservado ainda "
                   "(nenhum estágio liberado)",
            nota="PRÉ-CONDIÇÕES ABERTAS: unidade aponta WorkingDirectory=%h/JFN — na VM-2 a árvore é ~/JFN-worker "
                 "(O2.4, uma árvore só); no it-campo o jfn-fluxo roda no WSL (O1.10). Sem isso, subir só vm1/vm2 e "
                 "conferir o ensaio sem it-campo (§3.5)."),
        Passo("R3", "pausas da parada removidas (os comandos legados obedecem data/.pause_*)",
              cmds=[("vm1", "cd ~/JFN && rm -f " + " ".join(f"data/{p}" for p in pausas))] if pausas else [],
              efeito="nenhuma das pausas listadas em vm1/pausas_criadas.txt existe"),
    ]
    for grupo in ORDEM:
        for e in grupo:
            ag, ev = rotinas_do_estagio(g, e)
            pv = primeira_volta(g, e)
            no_horario = sorted(set(ag) - set(pv))
            extra = " — com desde=" + PARADA + " (JFN_DESDE no ambiente do comando)" if e == "E1" else ""
            p = Passo(f"R-{e}", f"liberar {e} ({g.estagios[e].nome}){extra}", estagio=e, rotinas=ag + ev,
                      sql=[f"INSERT INTO liberacao(estagio, por) VALUES ('{e}', '{POR}') ON CONFLICT DO NOTHING",
                           f"UPDATE agenda SET ativo = true, proximo = NULL WHERE payload->>'estagio' = '{e}'",
                           f"-- primeira volta: {len(pv)} job(s) legado:<rotina>:religar:{PARADA}"
                           + (f" (desde={PARADA})" if e == "E1" else "") + f": {', '.join(pv) or '—'}"],
                      efeito=f"{len(pv)} job(s) da primeira volta + os jobs do {e} retidos na fila até a liberação, "
                             f"todos em feito, e 0 quarentena/falhou_efeito do {e} desde a liberação (até "
                             f"{ESPERA_MAX_S // 60} min); metricas religacao_estagio=1",
                      nota=(f"no horário (semanal/mensal/condicional, conferir nas 48 h): {', '.join(no_horario)}. "
                            if no_horario else "")
                           + (f"{len(ev)} derivado(s) de evento: {', '.join(ev)}. " if ev else "")
                           + "Falhou ⇒ BLOQUEADO; não libera: "
                           + (", ".join(sorted((x for x in g.estagios if e in depende_de(g, x)),
                                               key=lambda x: int(x[1:]))) or "nenhum"))
            if e == "E15":
                p.cmds.append(("vm1", "sed -i -E 's/^(Environment=\"?JFN_MANUTENCAO)/#O90 \\1/' "
                                      "~/.config/systemd/user/jfn.service && systemctl --user daemon-reload "
                                      "&& systemctl --user restart jfn.service"))
                p.efeito += "; painel sem a faixa (GET / sem 'Em manutenção') e escrita liberada"
            passos.append(p)
    return passos


def plano_desfazer(backups: Path, lista_vm2: list[str] | None) -> list[Passo]:
    vm1_timers = ler_lista(backups / "vm1" / "timers_parados.txt")
    vm1_serv = " ".join(ler_lista(backups / "vm1" / "services_parados.txt")).split()
    pausas = ler_lista(backups / "vm1" / "pausas_criadas.txt")
    t1 = " ".join(f"{t}.timer" for t in vm1_timers)
    t2 = " ".join(f"{t}.timer" for t in (lista_vm2 or []))
    return [
        Passo("D1", "parar o jfn-fluxo nos 3 nós", cmds=[
            ("vm1", "systemctl --user disable --now jfn-fluxo@vm1 2>/dev/null; ! systemctl --user is-active -q jfn-fluxo@vm1"),
            ("vm2", "systemctl --user disable --now jfn-fluxo@vm2 2>/dev/null; ! systemctl --user is-active -q jfn-fluxo@vm2"),
            ("itcampo", "wsl -e bash -lc 'systemctl --user disable --now jfn-fluxo@itcampo 2>/dev/null; "
                        "! systemctl --user is-active -q jfn-fluxo@itcampo'")],
            efeito="nenhum `compliance_agent.fluxo supervisor` no ps das 3 máquinas (SIGTERM devolve os jobs à fila)"),
        Passo("D2", "fluxo inerte no PG (nada apagado)",
              sql=["UPDATE agenda SET ativo = false", "DELETE FROM liberacao"],
              efeito="0 agenda ativa, 0 estágio liberado; jobs em fila ficam (não reservam sem liberação)"),
        Passo("D3", "crontab antigo de volta", cmds=[
            ("vm1", f"crontab -l > ~/.config/jfn/backups/crontab_antes_desfazer_$(date +%s).txt && "
                    f"crontab -l | sed 's/^{MARCA}//' | crontab -")],
            efeito="crontab -l sem nenhuma linha começando por #PARADA-20261124"),
        Passo("D4", "timers e serviços da VM-1", cmds=(
            [("vm1", f"systemctl --user enable --now {t1}")] if t1 else []) + (
            [("vm1", "systemctl --user enable --now " + " ".join(vm1_serv))] if vm1_serv else []),
            efeito=f"{len(vm1_timers)} timer(s) e {len(vm1_serv)} serviço(s) active "
                   f"({', '.join(vm1_timers + vm1_serv)})"),
        Passo("D5", "timers da VM-2", cmds=[("vm2", f"systemctl --user enable --now {t2}")] if t2 else [],
              efeito=(f"{len(lista_vm2)} timer(s) active na VM-2 ({', '.join(lista_vm2)})" if lista_vm2 is not None
                      else "LISTA DA VM-2 ILEGÍVEL neste ensaio — ler vm2:" + LISTA_VM2 + " antes de executar"),
              nota="jfn-amostra-vm2 está na lista mas já estava desligado antes da parada (frente a201: "
                   "data/.vm2_amostra_estratificada) — conferir com o dono antes de religá-lo"),
        Passo("D6", "tarefas do it-campo", cmds=[
            ("itcampo", " & ".join(f'schtasks /Change /TN "\\{t}" /ENABLE' for t in TAREFAS_ITCAMPO)),
            ("itcampo", " & ".join(f'schtasks /Run /TN "\\{t}"' for t in TAREFAS_ITCAMPO))],
            efeito="as 3 tarefas Habilitado e Em execução (schtasks /Query /FO CSV); JFNAcordado nunca foi tocado"),
        Passo("D7", "pausas da parada removidas",
              cmds=[("vm1", "cd ~/JFN && rm -f " + " ".join(f"data/{p}" for p in pausas))] if pausas else [],
              efeito=f"nenhuma de {len(pausas)} pausa(s) existe: {', '.join(pausas)}"),
        Passo("D8", "faixa de manutenção sai do painel", cmds=[
            ("vm1", "sed -i -E 's/^(Environment=\"?JFN_MANUTENCAO)/#DESFAZER \\1/' ~/.config/systemd/user/jfn.service"
                    " && systemctl --user daemon-reload && systemctl --user restart jfn.service")],
            efeito="painel responde sem 'Em manutenção' e aceita escrita"),
        Passo("D9", "snapshot (MANUAL, só se houve escrita ruim)",
              efeito="compliance.db e pg_dump restaurados de D:\\JFN-Frio\\snapshot-20261124\\ com md5 conferido",
              nota="nunca automático: decidir com o dono depois de ver o que foi escrito"),
    ]


# ── execução (só --executar) ─────────────────────────────────────────────────────────────────────────
def liberar_estagio(con, g, estagio: str, desde: str | None = None) -> list[str]:
    """Liberação + agenda ativa + primeira volta. Devolve as chaves a conferir: a primeira volta (idempotente pela
    chave) MAIS os jobs do estágio que esperavam a liberação na fila (eventos de estágios já liberados)."""
    from compliance_agent.fluxo import fila
    from compliance_agent.fluxo import grafo as G
    retidos = [r[0] for r in con.execute("SELECT chave FROM jobs WHERE estado IN ('fila', 'reservado') AND "
                                         "payload->>'estagio' = %s", (estagio,))]
    con.execute("INSERT INTO liberacao(estagio, por) VALUES (%s, %s) ON CONFLICT DO NOTHING", (estagio, POR))
    con.execute("UPDATE agenda SET ativo = true, proximo = NULL WHERE payload->>'estagio' = %s", (estagio,))
    chaves = []
    for rid in primeira_volta(g, estagio):
        tipo, c = G.tipo_da_rotina(rid), g.contrato_da_rotina(rid)
        p = g.payload(rid, g.rotinas[rid].agenda[0].args)
        if desde:
            p["desde"] = desde
        chave = f"{tipo}:religar:{PARADA}"
        fila.enfileirar(con, tipo, chave, p, prioridade=c["prioridade"], recursos=c["recursos"], volta=c["volta"],
                        no_preferido=c["no_preferido"], correlation_id=f"religar:{estagio}")
        chaves.append(chave)
    return chaves + [c for c in retidos if c not in chaves]


def conferir_estagio(con, estagio: str, chaves: list[str]) -> dict:
    """Efeito do estágio: primeira volta inteira em `feito` e nada do estágio em quarentena/falhou_efeito desde a
    liberação. `pendentes` > 0 = ainda não dá para decidir."""
    est = dict(con.execute("SELECT estado, count(*) FROM jobs WHERE chave = ANY(%s) GROUP BY estado",
                           (chaves,)).fetchall()) if chaves else {}
    ruins = con.execute(
        "SELECT count(*) FROM jobs j, liberacao l WHERE l.estagio = %s AND j.payload->>'estagio' = %s "
        "AND j.estado IN ('quarentena', 'falhou_efeito') AND coalesce(j.concluido_em, j.criado_em) >= l.liberado_em",
        (estagio, estagio)).fetchone()[0]
    feitos = est.get("feito", 0)
    pendentes = sum(n for e, n in est.items() if e in ("fila", "reservado"))
    return {"estagio": estagio, "feitos": feitos, "esperados": len(chaves), "pendentes": pendentes, "ruins": ruins,
            "ok": ruins == 0 and pendentes == 0 and feitos == len(chaves)}


def esperar_estagio(con, estagio: str, chaves: list[str], espera_max_s: float = ESPERA_MAX_S,
                    poll_s: float = POLL_S, dormir: Callable[[float], None] = time.sleep,
                    relogio: Callable[[], float] = time.monotonic) -> dict:
    """Espera a decisão (o script é a janela da religação, com o dono olhando — não um laço residente)."""
    fim = relogio() + espera_max_s
    while True:
        r = conferir_estagio(con, estagio, chaves)
        if r["ruins"] or r["pendentes"] == 0 or relogio() >= fim:
            r["esgotou"] = r["pendentes"] > 0          # passou do teto ainda pendente = BLOQUEADO (ok já é False)
            return r
        dormir(poll_s)


def registrar(con, r: dict) -> None:
    con.execute("INSERT INTO metricas(no, nome, valor, rotulos) VALUES (NULL, 'religacao_estagio', %s, %s)",
                (1.0 if r["ok"] else 0.0, json.dumps(r)))


def religar_estagios(con, g, espera_max_s: float = ESPERA_MAX_S, so: list[str] | None = None,
                     dormir: Callable[[float], None] = time.sleep, log=print) -> dict:
    """Passo 4 inteiro: estágio a estágio, com BLOQUEADO propagado só a quem depende."""
    bloqueados: set[str] = set()
    out = {}
    for e in [x for grupo in ORDEM for x in grupo if so is None or x in so]:
        trava = depende_de(g, e) & bloqueados
        if trava:
            out[e] = {"estagio": e, "ok": False, "pulado": f"depende de BLOQUEADO {sorted(trava)}"}
            bloqueados.add(e)
            log(f"[{e}] NÃO liberado: depende de {sorted(trava)}")
            continue
        chaves = liberar_estagio(con, g, e, PARADA if e == "E1" else None)
        log(f"[{e}] liberado; primeira volta: {len(chaves)} job(s)")
        r = esperar_estagio(con, e, chaves, espera_max_s, dormir=dormir)
        registrar(con, r)
        out[e] = r
        if not r["ok"]:
            bloqueados.add(e)
        log(f"[{e}] {'CONFERIDO' if r['ok'] else 'BLOQUEADO'}: {r}")
    return out


def rodar_cmd(no: str, cmd: str, rodar=subprocess.run) -> int:
    r = rodar(no_cmd(no, cmd), timeout=600)
    return r.returncode


# ── saída ────────────────────────────────────────────────────────────────────────────────────────────
def imprimir(passos: list[Passo], titulo: str, pre: list[str], out=None) -> None:
    w = (out or sys.stdout).write
    w(f"=== {titulo} — ENSAIO (nada foi executado) ===\n")
    for ln in pre:
        w(f"  · {ln}\n")
    for p in passos:
        w(f"\n[{p.id}] {p.titulo}\n")
        for no, c in p.cmds:
            w(f"    $ ({no}) {c}\n")
        for s in p.sql:
            w(f"    SQL> {s}\n")
        if p.rotinas:
            w(f"    rotinas ({len(p.rotinas)}): {', '.join(p.rotinas)}\n")
        if p.efeito:
            w(f"    efeito conferido: {p.efeito}\n")
        if p.nota:
            w(f"    nota: {p.nota}\n")


def preliminares(g, rodar=subprocess.run) -> list[str]:
    """Só leitura: o que o ensaio consegue medir agora."""
    out = [f"grafo: {len(g.rotinas)} rotinas ({sum(r.ativa for r in g.rotinas.values())} ativas), "
           f"{len(g.agenda_linhas())} linhas de agenda; transitórios: "
           + (", ".join(f"{k} ({t.slots} {t.recurso} em {t.maquina} até {t.transitorio_ate}, {len(t.rotinas)} rotinas)"
                        for k, t in g.transitorios.items()) or "nenhum")]
    try:
        cr = rodar(["crontab", "-l"], capture_output=True, text=True, timeout=20).stdout.splitlines()
        out.append(f"crontab: {sum(ln.startswith(MARCA) for ln in cr)} linhas {MARCA.strip()} (comentadas)")
    except (OSError, subprocess.TimeoutExpired) as exc:
        out.append(f"crontab: ilegível ({type(exc).__name__})")
    import psycopg

    from compliance_agent.evidencias import dsn_vigente
    from compliance_agent.fluxo import schema
    try:
        dsn = dsn_vigente()
        if dsn:
            con = schema.conectar_leitura(dsn)
            try:
                v = schema.verificar(con)
                out.append(f"schema fluxo (só leitura): ok={v['ok']} versões={v['versoes']} faltando={v['faltando']}")
                for sql, rot in (("SELECT count(*), count(*) FILTER (WHERE ativo) FROM fluxo.agenda", "agenda (total, ativas)"),
                                 ("SELECT estado, count(*) FROM fluxo.jobs GROUP BY estado ORDER BY 1", "jobs por estado")):
                    out.append(f"{rot}: {con.execute(sql).fetchall()}")
            finally:
                con.close()
        else:
            out.append("schema fluxo: sem DSN — não medido")
    except (psycopg.Error, OSError) as exc:            # o ensaio DIZ que não mediu; não derruba o relatório
        out.append(f"schema fluxo: não medido ({type(exc).__name__})")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Religação O9.0 (ou desfazer) em sequência verificada")
    modo = ap.add_mutually_exclusive_group()
    modo.add_argument("--ensaio", action="store_true", help="padrão: só imprime")
    modo.add_argument("--executar", action="store_true")
    ap.add_argument("--desfazer", action="store_true", help="volta ao sistema antigo (crontab, timers, tarefas)")
    ap.add_argument("--confirmo-dono-avisado", action="store_true")
    ap.add_argument("--espera-max-s", type=float, default=ESPERA_MAX_S)
    ap.add_argument("--backups", default=str(BACKUPS))
    a = ap.parse_args(argv)
    from compliance_agent.fluxo import grafo as G
    g = G.carregar()
    backups = Path(a.backups)
    if a.desfazer:
        passos = plano_desfazer(backups, ler_lista_vm2())
        titulo = "DESFAZER da religação O9.0"
    else:
        passos = plano_religar(g, ler_lista(backups / "vm1" / "pausas_criadas.txt"))
        titulo = "RELIGAÇÃO O9.0"
    if not a.executar:
        imprimir(passos, titulo, preliminares(g))
        return 0
    if not a.confirmo_dono_avisado:
        print("recusado: --executar exige --confirmo-dono-avisado (a religação é numa janela com o dono)",
              file=sys.stderr)
        return 2
    return executar(passos, g, a.espera_max_s)


def executar(passos: list[Passo], g, espera_max_s: float, rodar=subprocess.run, con=None, log=print) -> int:
    """Roda os passos em ordem; passo de máquina que falha PARA tudo (rc 1); estágio que falha fica BLOQUEADO."""
    from compliance_agent.fluxo import fila
    con = con or fila.conectar()
    estagios = [p.estagio for p in passos if p.estagio]
    for p in passos:
        if p.estagio:
            continue
        for no, c in p.cmds:
            log(f"[{p.id}] ({no}) {c}")
            rc = rodar_cmd(no, c, rodar)
            if rc != 0:
                log(f"[{p.id}] FALHOU rc={rc} — parado aqui; nada adiante foi feito")
                return 1
        for s in p.sql:
            if not s.startswith(("SELECT", "--")):
                con.execute(s)
    r = religar_estagios(con, g, espera_max_s, so=estagios, log=log) if estagios else {}
    for p in passos:
        if p.estagio == "E15" and r.get("E15", {}).get("ok"):
            for no, c in p.cmds:
                rodar_cmd(no, c, rodar)
    log(json.dumps({"bloqueados": sorted(e for e, x in r.items() if not x.get("ok"))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
