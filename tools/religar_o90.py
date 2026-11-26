# -*- coding: utf-8 -*-
"""Religação O9.0 em sequência verificada — e o desfazer completo (plano mestre v2 §1.1 "Religação", §9 O9.0).

NÃO RELIGA NADA SOZINHO. Modos:
  --ensaio    (padrão) imprime, passo a passo, o que faria — comandos, SQL e a checagem de efeito de cada estágio —,
              o mapa rotina legada → estágio nativo e as PRÉ-CONDIÇÕES ABERTAS (as do dono marcadas). Só lê: o yaml,
              o crontab, as listas da parada, o schema do PG (sessão READ ONLY) e o estado dos nós (ssh, só leitura).
  --executar  roda a sequência. Exige `--confirmo-dono-avisado` (a religação é numa janela com o dono avisado) e
              recusa se uma pré-condição falhar.
  --mapa      o mapa rotina legada → destino em Markdown (vai para o vault, ~/vault/refatoracao/o90-janela.md).
  --provar-schema ESQUEMA   prova num esquema de ENSAIO (`ensaio_o90…`, nunca o `fluxo`) que `schema aplicar` leva de
              fluxo_001 a ok=true e é idempotente (2× = mesmo resultado); apaga o esquema no fim.

Uma porta por trabalho (§3.2 "1 porta de captura em vez de 15"): onde o estágio tem NATIVO, a religação libera o
nativo e a rotina legada equivalente está DESLIGADA no próprio grafo (`ativa: false` + `substituida_por: Ek` em
config/fluxo.yaml — o planejador não a agenda nem a deriva de evento). Legado só onde não há nativo (E1 inteiro) ou
onde o nativo ainda está em SOMBRA (E9/E10/E11/E12/E13/E14/E16: escreve no esquema `sombra`), com motivo por rotina
(MOTIVO_ESTAGIO/MOTIVO_ROTINA abaixo; a catraca tests/test_religar_o90.py exige destino para TODA rotina).

Religação (ordem da §1.1):
  R0 pré-condições: grafo válido; schema `fluxo` com fluxo_002 (`aplicar`, idempotente — provado por --provar-schema);
     schemas dos estágios nativos (`<estágio> schema aplicar`); crontab ainda comentado (`#PARADA-20261124`);
     `JFN_ASSINATURA_ESCOPO` fora do ambiente do systemd de usuário (VM-1 e VM-2);
  R1 árvores: VM-2 e it-campo (WSL) `~/JFN-worker` andam até o SHA EXATO do main da VM-1, fixado no começo
     (ff-only; `tools.deploy_worker --sha` confere HEAD = SHA e md5 da árvore = md5 do HEAD) e o grafo valida lá;
  R2 DSN do PG nos 2 workers (`~/.config/jfn/pg_evidencias.env`, 600, nunca impresso) e conexão conferida;
  R3 `cron_para_fluxo --aplicar` (VM-1) e `--timers --aplicar` (VM-2) ANTES das agendas (O8.1: sem isso backup,
     WAL, zelador… rodariam 2×) + `agenda sincronizar` (linha nova entra `ativo=false`);
  R4 `jfn-fluxo` sobe nos 3 nós, cada um na SUA árvore (drop-in `arvore.conf` por nó; it-campo = tarefa
     JFN-Fluxo-Boot no WSL, O1.10) e com o ambiente de deploy/fluxo/producao.env (JFN_E3_DELTA=1,
     JFN_LEITURAS_REGISTRAR=1; sem JFN_ASSINATURA_ESCOPO); efeito = cwd e ambiente do processo + heartbeat;
  R5 pausas da parada (`data/.pause_*` do O0.7) removidas;
  R-Ek estágio por estágio — E17/E18 → E1 (desde = parada) → E2…E7 → E8 → … → E15 (sai a faixa de manutenção, LOGO
     depois do E15 conferido) → E16. Em cada um: liberação, agenda do estágio ativa (nativa + legado mantido),
     primeira volta (rotina ≥ diária), efeito conferido em `fluxo.metricas` (`religacao_estagio`); falhou ⇒ BLOQUEADO
     e quem depende dele não é liberado (ressalva 1 da §1.1).
  48 h de observação (§1.1 item 5) — fora deste script (checklist ~/vault/refatoracao/o90-janela.md).

Desfazer (volta ao sistema antigo em minutos; §1.1 item 4): parar `jfn-fluxo` nos 3 nós; agenda inteira `ativo=false`
e `liberacao` vazia; `cron_para_fluxo --desfazer` + descomentar `#PARADA-20261124`; timers/serviços da VM-1 e VM-2;
as 3 tarefas do it-campo; pausas fora; faixa de manutenção fora. Restaurar o snapshot é MANUAL.

    python -m tools.religar_o90 --ensaio
    python -m tools.religar_o90 --desfazer --ensaio
    python -m tools.religar_o90 --provar-schema ensaio_o90_schema
    python -m tools.religar_o90 --executar --confirmo-dono-avisado          # só na janela, com o dono
"""
from __future__ import annotations

import argparse
import base64
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
TAREFA_FLUXO_ITCAMPO = "JFN-Fluxo-Boot"
SSH = {"vm1": None, "vm2": "vm2-ts", "itcampo": "it-campo"}
# árvore do código por nó (AMBIENTE.md §1a; O2.4): VM-1 é o canônico; VM-2 e it-campo (WSL Ubuntu) puxam dela
ARVORE = {"vm1": "~/JFN", "vm2": "~/JFN-worker", "itcampo": "~/JFN-worker"}
DROPIN = {"vm1": "deploy/systemd/drop-ins/jfn-fluxo@vm1.service.d/arvore.conf",
          "vm2": "deploy/vm2/jfn-fluxo@vm2.service.d/arvore.conf"}
AMBIENTE = "deploy/fluxo/producao.env"
PS1_ITCAMPO = "deploy/itcampo/fluxo/jfn_fluxo_boot.ps1"
ENV_PRODUCAO = {"JFN_E3_DELTA": "1", "JFN_LEITURAS_REGISTRAR": "1", "JFN_NAVEGADOR_VAGAS": "6",
                "JFN_E3_ESPELHO": "vm2-ts:JFN-worker/data/sei_cache"}
ENV_PROIBIDA = "JFN_ASSINATURA_ESCOPO"           # autorização do dono para a assinatura: só no ensaio O8.5
DSN_ARQ = "~/.config/jfn/pg_evidencias.env"
# schemas dos estágios nativos (cada um idempotente) e a tabela que prova que o schema está lá (to_regclass)
SCHEMAS_NATIVOS = (("arvore", "public.arvore_leitura"), ("texto", "public.ocr_numero"), ("fatos", "public.fatos"),
                   ("elegibilidade", "dominio.elegibilidade"), ("detectar", "sombra.execucao_regra"),
                   ("periciar", "sombra.laudos_v2"), ("caso", "sombra.caso"))
# ordem da §1.1; cada sublista é um passo, os estágios dentro dele vão um a um (efeito conferido antes do seguinte)
ORDEM = [["E17", "E18"], ["E1"], ["E2", "E3", "E4", "E5", "E6", "E7"], ["E8"], ["E9"], ["E10"], ["E11"], ["E12"],
         ["E13"], ["E14"], ["E15"], ["E16"]]
# duas janelas (decisão do coordenador, delegada pelo dono, 25/11): a 1ª religa o que não depende de LLM e vem antes
# do E8 na sequência; a 2ª, do E8 em diante, só depois da virada da assinatura. O E8 NÃO é liberado na 1ª etapa (o
# ritmo fechado não vira BLOQUEADO: ele simplesmente fica de fora).
ETAPAS = {1: ["E17", "E18", "E1", "E2", "E3", "E4", "E5", "E6", "E7"],
          2: ["E8", "E9", "E10", "E11", "E12", "E13", "E14", "E15", "E16"]}
VIRADA_ASSINATURA = "2026-11-28T19:00:00-03:00"
MISTOS_PARAR = "bash ~/o36/sombra_parar.sh"          # OCR dos mistos (frente O3.6) — para antes do wsl --shutdown
MISTOS_TAREFA = "JFN-O36-Mistos"
ESPERA_MAX_S = 7200
# 26/11/2026 (pré-mortem da etapa 2): estágio de LLM não cabe INTEIRO no prazo — o E8 recebe os fatos retidos da
# janela 1 (mediana de 58 fatias por processo, 1 job da assinatura por nó) e o E10 tem ~20.000 s de cpu_pesado num
# slot só da VM-1. Neles a 1ª volta é conferida PARCIAL: depois desta espera mínima, ≥ 1 job feito, 0 quarentena/
# falhou_efeito e o resto só esperando (fila/reservado sem erro, ou `adiado` pelo ritmo). Os pendentes vão no rótulo
# da métrica para as 48 h de observação. Estágio sem LLM continua exigindo a volta inteira.
ESPERA_PARCIAL_S = 1800
POLL_S = 30
POR = "tools/religar_o90"
PAINEL = "http://127.0.0.1:8000/"
JFN_SERVICE = "~/.config/systemd/user/jfn.service"
# aviso Telegram ao começar e ao terminar (pedido do coordenador, 25/11): credencial achada pelo resolvedor (nunca
# impressa), JFN_TELEGRAM_PEDIDO=1 (não cai no silêncio) e SUCESSO SÓ COM message_id (memória telegram-silencio-
# devolve-ok: envio calado devolvia ok=True). Desligado no --ensaio (só imprime o comando).
AVISO_CMD = ("cd ~/JFN && PYTHONPATH=. .venv/bin/python -m compliance_agent.credenciais com "
             "TELEGRAM_BOT_TOKEN,TELEGRAM_CHAT_ID -- env JFN_TELEGRAM_PEDIDO=1 PYTHONPATH=. .venv/bin/python -m "
             "tools.religar_o90 --avisar {texto}")

# ── legado mantido: motivo (o padrão do estágio; a rotina pode ter o seu) ─────────────────────────────────────────
MOTIVO_ESTAGIO = {
    "E1": "E1 não tem estágio nativo (o coletor é legado); roda com desde=parada na primeira volta e o e1_eventos "
          "leva a novidade aos nativos (coleta/*)",
    "E9": "nativo E9 elegibilidade em sombra ⚖️ até o ✅ do dono no lote jurídico (O4.10): o legado é a produção",
    "E10": "nativo E10 detectar grava no esquema `sombra` (O5.3, Tier 3) até o ✅ do lote jurídico (O4.10): estes "
           "detectores são a produção",
    "E11": "nativo E11 periciar grava laudo v2 no esquema `sombra` (O6.4: falta a paridade de juízo e o ✅ do dono na "
           "estimativa o64-pericia-unica): a perícia legada é a produção; depois do ✅, pericia_integral e "
           "lex_execucao_fila passam a `substituida_por: E11`",
    "E12": "nativo E12 conferir em sombra (O6.5/O6.6: regra de risco, 2º executor); a triagem/Opus legada é a "
           "produção e é ela que gera os conferidos que o E13 lê (coleta/conferidos)",
    "E13": "nativo E13 calibrar em sombra (O5.4): só grava o JSON; o --gravar do registro de tiers é com o ✅ do dono",
    "E14": "nativo E14 caso só monta os casos citados pelos achados do E10 nativo (esquema `sombra`); 360/vault são "
           "outros produtos",
    "E15": "nativo E15 materializar cobre siafe_stats (rota coleta/fonte_mudou) e as 18 visões do materializar_painel "
           "(religado); o resto das visões e caches do painel ainda é do materializador legado",
    "E16": "nativo E16 entregar faz o dossiê por órgão/lente em sombra (O7.5); digest/triagem/pulos são outros "
           "produtos",
    "E17": "nativo E17 manter roda em --simular (só confere pré-condições, sombra); quem executa é o legado",
    "E18": "sensores nativos E18 observar por nó (no lugar das observar_<nó>); estes são vigias/remédios com motivo "
           "na O2.3 (tests/test_fluxo_o23.py::test_os_14_vigias_viram_sensores_e18_ou_tem_motivo)",
}
MOTIVO_ROTINA = {
    "pcrj_sei_busca_termos": "SEI.RIO (Prefeitura): o E2 nativo só lê SEI-RJ (processo_do recusa outro formato)",
    "sei_busca_credor": "descoberta de nº de processo por CNPJ na PESQUISA do SEI (não captura); ATENÇÃO: a fila que "
                        "ela alimenta (sei_fila_captura) era lida pelo sweep_sei, que saiu — ver ressalva do backlog",
    "sweep_integra_contratos_pcrj": "PNCP → PDF do contrato da Prefeitura (nº SEI.RIO): é coleta E1 de outra fonte "
                                    "(mapa O1.2), não captura SEI-RJ",
    "obra_fase_sei": "fase da obra lida do acervo (produto próprio); o E8 nativo grava fatos, não fase de obra",
    "pcrj_leitura_campos": "leitura de campos da Prefeitura (SEI.RIO): fora do E8 nativo (SEI-RJ)",
    "fila_analise_sigilo": "fila de sigilo (ficha de processo restrito): produto que o E8 nativo não gera",
    "propostas_sei": "preço por fornecedor das cotações (insumo do J9): o E8 nativo não extrai proposta",
    "sei_fichas_fila": "ficha de processo SEI (painel/Lex): o E8 nativo grava fatos com citação, não a ficha",
    "materializar_painel": "é o próprio estágio nativo E15 pela CLI (18 visões); religado na O9.0",
    "e1_eventos": "ponte E1 → nativos (O9.0): emite coleta/ob_nova, coleta/fonte_mudou e coleta/conferidos",
    "deploy_vm2": "deploy por evento do worker da VM-2 (O2.4); religado na O9.0",
    "e2_semear": "semeador do backlog do E2 (O9.0): enfileira jobs NATIVOS arvore:<processo> na prioridade única; não "
                 "abre navegador (a porta continua sendo o E2 nativo)",
}


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
    """argv para rodar `cmd` no nó (VM-1 local; VM-2 por ssh; it-campo por ssh no Windows = PowerShell)."""
    host = SSH[no]
    return ["bash", "-lc", cmd] if host is None else ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", host, cmd]


def wsl(script: str) -> str:
    """Comando PowerShell que roda `script` (bash) no WSL do it-campo. O script vai em base64: o PowerShell 5.1 do
    it-campo estraga aspas e `$( )` passadas a programa nativo, e `&` nem é aceito (medido 25/11)."""
    b = base64.b64encode(script.encode("utf-8")).decode("ascii")
    return f"wsl -d Ubuntu -e bash -lc 'echo {b} | base64 -d | bash'"


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


def sha_main(rodar=subprocess.run) -> str:
    """SHA do main da VM-1 fixado para a janela inteira (as 3 máquinas rodam ESTE commit)."""
    r = rodar(["git", "-C", str(RAIZ), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=30)
    return r.stdout.strip() if r.returncode == 0 else "<SHA-DO-MAIN>"


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


# ── uma porta por trabalho: mapa legado → nativo, entradas dos nativos, órfãs ───────────────────────────────────
def estagios_nativos(g) -> dict[str, dict]:
    """Ek → {tipo, entradas (eventos das rotas que chegam nele), agenda (linhas da agenda nativa)}."""
    out: dict[str, dict] = {}
    for r in g.nativos.rotas:
        out.setdefault(r.estagio, {"entradas": set(), "agenda": []})["entradas"].add(r.evento)
    for a in g.nativos.agenda:
        out.setdefault(a.estagio, {"entradas": set(), "agenda": []})["agenda"].append(a.id)
    for e, d in out.items():
        d["tipo"] = g.estagios[e].tipo
    return out


def _involucro(r) -> str | None:
    """A rotina é só a CLI de um estágio nativo (`compliance_agent.aplicacao.estagios.<x>`)? Devolve o módulo."""
    for argv in r.argvs():
        for a in argv:
            if a.startswith("compliance_agent.aplicacao.estagios."):
                return a.rsplit(".", 1)[1]
    return None


def mapa_legado(g) -> list[dict]:
    """TODA rotina do grafo com o seu destino na religação (nenhuma some sem destino declarado):
    `nativo` (desligada, o estágio nativo faz o trabalho) · `legado` (fica ligada, com motivo) · `desligada` (com o
    bloqueio do yaml). Ordem: estágio, rotina."""
    nat = estagios_nativos(g)
    out = []
    for rid, r in sorted(g.rotinas.items(), key=lambda kv: (int(kv[1].estagio[1:]), kv[0])):
        if r.substituida_por:
            d = {"destino": "nativo", "para": r.substituida_por, "motivo": r.bloqueio}
        elif r.ativa:
            d = {"destino": "legado", "para": None,
                 "motivo": MOTIVO_ROTINA.get(rid) or MOTIVO_ESTAGIO.get(r.estagio)}
        elif _involucro(r) and r.estagio in nat:
            d = {"destino": "nativo", "para": r.estagio,
                 "motivo": f"invólucro de CLI do estágio nativo {r.estagio} ({_involucro(r)}): o motor agenda o job "
                           f"nativo `{nat[r.estagio]['tipo']}`; esta linha fica desligada"}
        else:
            d = {"destino": "desligada", "para": None, "motivo": r.bloqueio}
        out.append({"rotina": rid, "estagio": r.estagio, "ativa": r.ativa, **d})
    return out


def entradas_sem_produtor(g) -> dict[str, list[str]]:
    """Estágio nativo → eventos de entrada sem PRODUTOR em produção (nenhum nativo os emite, o e1_eventos não está
    ativo para os `coleta/*`). Estágio com agenda nativa tem entrada própria. Vazio = todo nativo tem porta."""
    from tools import e1_eventos
    produz = {ev for evs in g.nativos.emite.values() for ev in evs}
    if g.rotinas.get("e1_eventos") and g.rotinas["e1_eventos"].ativa:
        produz |= set(e1_eventos.EMITE)
    out = {}
    for e, d in estagios_nativos(g).items():
        if d["agenda"] or (d["entradas"] & produz):
            continue
        out[e] = sorted(d["entradas"])
    return out


def orfas(g) -> list[str]:
    """Rotinas ATIVAS sem agenda cujo único gatilho é uma rotina desligada: nunca mais disparariam (calado)."""
    out = []
    for rid, r in g.rotinas.items():
        if not r.ativa or r.agenda or not r.evento:
            continue
        vivos = [d for d in r.evento.depende if d not in g.rotinas or g.rotinas[d].ativa]
        if not vivos:
            out.append(rid)
    return sorted(out)


def ressalvas(g) -> list[str]:
    """O que a religação NÃO resolve e fica observado nas 48 h (não é pré-condição: nada se perde, mede-se)."""
    capt = {"sei_arquivado", "sei_lote", "ocr_gpu", "ocr_reserva"}
    quietas = sorted(rid for rid, r in g.rotinas.items()
                     if r.ativa and r.evento and set(r.evento.depende) & capt)
    return [
        "backlog do E2: o semeador (e2_semear, 40 por ciclo de 2 h na prioridade única) substitui a varredura do "
        "sweep_sei; medir nas 48 h: processos com OB paga sem árvore (deve cair, não subir) e a vazão do E2 nativo "
        "(1 navegador na VM-2 sem o it-campo)",
        "fontes legadas de captura/OCR (sei_arquivado, sei_lote, ocr_gpu, ocr_reserva) eram emitidas pelas portas que "
        f"saíram; derivados legados que as escutam podem silenciar (têm agenda de rede, conferir): {', '.join(quietas)}",
        "E6: ocr_ia_prova.vale_como_prova ainda lê data/sei_ocr_ia_conferencia.jsonl — número novo do E5 nativo fica "
        "a_conferir para os leitores legados (falha FECHADA: nunca vira prova sem confirmação)",
    ]


# ── plano ────────────────────────────────────────────────────────────────────────────────────────────
def _script_arvore(sha: str, unit: str) -> str:
    """bash: a árvore do worker anda até o SHA exato e confere (ff-only; recusa código local mexido)."""
    return (f"set -e; cd ~/JFN-worker; test -z \"$(git status --porcelain --untracked-files=no -- . ':(exclude)data')\"; "
            f"git fetch -q origin; git merge --ff-only -q {sha}; test \"$(git rev-parse HEAD)\" = {sha}; "
            # 25/11/2026: a 1ª execução parou no R2 — o venv dos workers não tinha psycopg (nunca seguira o lock).
            # O venv anda junto com a árvore: o lock de produção com hashes (O9.3), por uv quando houver (venv sem pip).
            f"if [ -x ~/.local/bin/uv ]; then ~/.local/bin/uv pip install -q --require-hashes -r requirements.lock "
            f"--python .venv/bin/python; else .venv/bin/python -m pip install -q --require-hashes -r requirements.lock; fi; "
            f".venv/bin/python -c 'import psycopg, yaml, pydantic'; "
            f"PYTHONPATH=. .venv/bin/python -m tools.deploy_worker --sha {sha} --sem-recarga; "
            f"PYTHONPATH=. .venv/bin/python -m compliance_agent.fluxo.grafo > /dev/null; echo arvore-ok {unit}")


def _script_env(unit: str, arvore: str) -> str:
    """bash: o processo do supervisor roda na árvore do nó e com o ambiente da produção (e SEM o escopo do ensaio)."""
    exige = " && ".join(f"echo \"$E\" | grep -qx {k}={v}" for k, v in ENV_PRODUCAO.items())
    return (f"sleep 5; P=$(systemctl --user show -p MainPID --value {unit}); test \"$P\" -gt 0; "
            f"E=$(tr '\\0' '\\n' < /proc/$P/environ); {exige} && ! echo \"$E\" | grep -q '^{ENV_PROIBIDA}=' "
            f"&& test \"$(readlink /proc/$P/cwd)\" = \"$HOME/{arvore[2:]}\"")


def resolver_dsn_cmd() -> str:
    """bash no worker: o DSN é ACHADO (resolvedor; nunca copiado), conecta, e nenhum arquivo do worker o guarda."""
    md = "PYTHONPATH=. .venv/bin/python"
    return (f"cd ~/JFN-worker && {md} -m compliance_agent.credenciais onde JFN_EVIDENCIAS_DSN | grep -v NAO && "
            f"{md} -m compliance_agent.credenciais com JFN_EVIDENCIAS_DSN -- .venv/bin/python -c 'from "
            "compliance_agent.fluxo import fila; fila.conectar().close(); print(\"pg-ok\")' && test \"$(grep -rls "
            "'^JFN_EVIDENCIAS_DSN=' ~/.config/jfn ~/JFN-worker/.env 2>/dev/null | wc -l)\" = 0")


# it-campo (O1.10): o .wslconfig proposto entra na 1ª janela, com cópia do atual; conferência = o que o WSL vê
WSLCONFIG_APLICAR = ("set -e; W=/mnt/c/Users/iterj; cp -n $W/.wslconfig $W/.wslconfig.antes-o90; "
                     "cp ~/JFN-worker/deploy/itcampo/fluxo/wslconfig.proposto $W/.wslconfig; "
                     "cmp ~/JFN-worker/deploy/itcampo/fluxo/wslconfig.proposto $W/.wslconfig")
WSLCONFIG_CONFERIR = ("test \"$(nproc)\" -ge 24 && test \"$(awk '/MemTotal/{print int($2/1048576)}' /proc/meminfo)\" "
                      "-ge 23")


def ordem_da_etapa(etapa: int | None) -> list[str]:
    todos = [x for grupo in ORDEM for x in grupo]
    return todos if etapa is None else [x for x in todos if x in ETAPAS[etapa]]


def _script_env_itcampo() -> str:
    exige = " && ".join(f"echo \"$E\" | grep -qx {k}={v}" for k, v in ENV_PRODUCAO.items())
    return ("sleep 20; P=$(pgrep -f '[c]ompliance_agent.fluxo supervisor --no itcampo' | head -1); test -n \"$P\"; "
            f"E=$(tr '\\0' '\\n' < /proc/$P/environ); {exige} && ! echo \"$E\" | grep -q '^{ENV_PROIBIDA}=' "
            "&& test \"$(readlink /proc/$P/cwd)\" = \"$HOME/JFN-worker\"")


def plano_religar(g, pausas: list[str], sha: str | None = None, etapa: int | None = None) -> list[Passo]:
    """etapa None = a sequência inteira; 1 = R0–R5 + E17, E18, E1–E7; 2 = conferência da etapa 1 + E8–E16."""
    py = ".venv/bin/python"
    sha = sha or "<SHA-DO-MAIN>"
    md = "PYTHONPATH=. " + py
    n_agenda = len(g.agenda_linhas()) + len(g.agenda_nativa())
    ps1 = ("set -e; install -m 644 ~/JFN-worker/" + PS1_ITCAMPO + " /mnt/c/JFN-Fluxo/jfn_fluxo_boot.ps1; "
           "test \"$(md5sum < ~/JFN-worker/" + PS1_ITCAMPO + ")\" = \"$(md5sum < /mnt/c/JFN-Fluxo/jfn_fluxo_boot.ps1)\"")
    passos = [
        Passo("R0", "pré-condições (VM-1)", cmds=[
            ("vm1", f"cd ~/JFN && {md} -m compliance_agent.fluxo.grafo"),
            ("vm1", f"cd ~/JFN && {md} -m compliance_agent.fluxo.schema aplicar && {md} -m compliance_agent.fluxo.schema verificar"),
            *[("vm1", f"cd ~/JFN && {md} -m compliance_agent.aplicacao.estagios.{m} schema aplicar")
              for m, _t in SCHEMAS_NATIVOS],
            ("vm1", f"test \"$(crontab -l | grep -c '^{MARCA.strip()}')\" -gt 0"),
            ("vm1", f"! systemctl --user show-environment | grep -q '^{ENV_PROIBIDA}='"),
            ("vm2", f"! systemctl --user show-environment | grep -q '^{ENV_PROIBIDA}='")],
            efeito="grafo ok; schema `fluxo` com fluxo_001+fluxo_002 (verificar ok=true — o `aplicar` é idempotente, "
                   "provado em esquema de ensaio: --provar-schema); tabelas dos 7 estágios nativos presentes "
                   f"({', '.join(t for _m, t in SCHEMAS_NATIVOS)}); crontab com as linhas #PARADA ainda comentadas; "
                   f"{ENV_PROIBIDA} fora do ambiente do systemd de usuário nas VMs",
            nota="sem o fluxo_002 o supervisor não sobe (schema incompleto); prova do `aplicar` em "
                 "~/vault/refatoracao/o90-janela.md"),
        Passo("R1", f"árvores dos workers no SHA do main ({sha[:12]})", cmds=[
            ("vm2", _script_arvore(sha, "vm2")),
            ("itcampo", wsl(_script_arvore(sha, "itcampo"))),
            ("itcampo", wsl(ps1))],
            efeito=f"VM-2 e it-campo (WSL) com ~/JFN-worker em HEAD = {sha[:12]}, md5 da árvore = md5 do HEAD "
                   "(deploy_worker --sha), grafo válido lá; C:\\JFN-Fluxo\\jfn_fluxo_boot.ps1 = o da árvore (md5)",
            nota="o SHA é fixado no começo da janela (commit novo na VM-1 durante a janela NÃO entra); depois da "
                 "religação o deploy_vm2 (E17, evento codigo_commit) segue o main. it-campo: script em base64 "
                 "(PowerShell 5.1)"),
        Passo("R2", "DSN do PG nos workers pelo resolvedor de credenciais (nada copiado, nada gravado)", cmds=[
            ("vm2", resolver_dsn_cmd()),
            ("itcampo", wsl(resolver_dsn_cmd()))],
            efeito="`pg-ok` nos 2 workers com o DSN ACHADO pelo resolvedor (compliance_agent.credenciais: VM-1 por "
                   "ssh) e 0 arquivo com JFN_EVIDENCIAS_DSN em ~/.config/jfn e ~/JFN-worker/.env",
            nota="regra do dono: credencial é achada, nunca copiada. O supervisor faz o mesmo no boot "
                 "(compliance_agent.fluxo.__main__.resolver_dsn): o valor fica só na memória do processo e dos "
                 "filhos. Medido 25/11: resolve nos 2 workers (vm1(vm1)/vm1(vm1-ts):pg_evidencias.env), 0 arquivo"),
        Passo("R3", "cron → fluxo e agenda do yaml no PG (tudo ativo=false)", cmds=[
            ("vm1", f"cd ~/JFN && {md} -m tools.cron_para_fluxo --aplicar"),
            ("vm2", f"cd ~/JFN-worker && {md} -m tools.cron_para_fluxo --timers --aplicar"),
            ("vm1", f"cd ~/JFN && {md} -m compliance_agent.fluxo agenda sincronizar")],
            efeito=f"crontab sem linha viva que o fluxo assumiu (marca #FLUXO-AAAAMMDD; recontagem do próprio "
                   f"cron_para_fluxo); {n_agenda} linhas em fluxo.agenda ({len(g.agenda_linhas())} legado + "
                   f"{len(g.agenda_nativa())} nativas), todas ativo=false",
            sql=["SELECT count(*), count(*) FILTER (WHERE ativo) FROM agenda"],
            nota="O8.1: o cron_para_fluxo vem ANTES das agendas — senão backup/WAL/zelador rodariam no cron E no fluxo"),
        Passo("R4", "jfn-fluxo sobe nos 3 nós, cada um na sua árvore e com o ambiente da produção", cmds=[
            ("vm1", "mkdir -p ~/.config/systemd/user/jfn-fluxo@vm1.service.d && ln -sf ~/JFN/deploy/systemd/"
                    "jfn-fluxo@.service ~/.config/systemd/user/jfn-fluxo@.service && ln -sf ~/JFN/" + DROPIN["vm1"]
                    + " ~/.config/systemd/user/jfn-fluxo@vm1.service.d/arvore.conf && test -e ~/.config/systemd/user/"
                    "jfn-coletor.slice && test -e ~/.config/systemd/user/jfn-egress.service && systemctl --user "
                    "daemon-reload && systemctl --user enable --now jfn-fluxo@vm1"),
            ("vm1", _script_env("jfn-fluxo@vm1", ARVORE["vm1"])),
            ("vm2", "cp -n ~/.config/systemd/user/jfn-fluxo@.service ~/.config/jfn/jfn-fluxo@.service.antes-o90 "
                    "2>/dev/null; mkdir -p ~/.config/systemd/user/jfn-fluxo@vm2.service.d && ln -sf ~/JFN-worker/"
                    "deploy/systemd/jfn-fluxo@.service ~/.config/systemd/user/jfn-fluxo@.service && ln -sf "
                    "~/JFN-worker/" + DROPIN["vm2"] + " ~/.config/systemd/user/jfn-fluxo@vm2.service.d/arvore.conf "
                    "&& test -e ~/.config/systemd/user/jfn-coletor.slice && test -e ~/.config/systemd/user/"
                    "jfn-egress.service && systemctl --user daemon-reload && systemctl --user enable --now "
                    "jfn-fluxo@vm2"),
            ("vm2", _script_env("jfn-fluxo@vm2", ARVORE["vm2"])),
            ("itcampo", wsl(MISTOS_PARAR)),
            ("itcampo", wsl(WSLCONFIG_APLICAR)),
            ("itcampo", "wsl --shutdown; Start-Sleep -Seconds 10"),
            ("itcampo", f"schtasks /Change /TN \\{TAREFA_FLUXO_ITCAMPO} /ENABLE; schtasks /Run /TN "
                        f"\\{TAREFA_FLUXO_ITCAMPO}"),
            ("itcampo", wsl(_script_env_itcampo())),
            ("itcampo", wsl(WSLCONFIG_CONFERIR)),
            ("itcampo", f"Start-ScheduledTask -TaskName {MISTOS_TAREFA}")],
            sql=["SELECT no, now() - heartbeat_em, capacidades->>'isolamento' FROM nos ORDER BY no"],
            efeito="cada supervisor com cwd = a árvore do nó (vm1 ~/JFN, vm2 e it-campo ~/JFN-worker) e ambiente "
                   f"{', '.join(f'{k}={v}' for k, v in ENV_PRODUCAO.items())} sem {ENV_PROIBIDA} (lido de "
                   "/proc/<pid>/environ); vm1, vm2 e itcampo com heartbeat < 5 min; isolamento=systemd na vm1/vm2 "
                   "(it-campo: o que o WSL der — systemd ou subprocesso com RLIMIT_DATA); nenhum job reservado ainda",
            nota="árvore por nó declarada: drop-in arvore.conf da VM-1 e da VM-2 (WorkingDirectory/PYTHONPATH/"
                 f"ExecStart + EnvironmentFile={AMBIENTE} + UnsetEnvironment={ENV_PROIBIDA}); it-campo = tarefa "
                 f"{TAREFA_FLUXO_ITCAMPO} (boot sem logon, O1.10) que lê o mesmo {AMBIENTE}. Sem o it-campo: seguir "
                 "com vm1/vm2 (§3.5, volta declarada por estágio). it-campo: o OCR dos mistos (O3.6) PARA antes, o "
                 ".wslconfig proposto (25 GB / 24 CPU / swap 12 GB) entra com `wsl --shutdown` (cópia do antigo em "
                 "%USERPROFILE%\\.wslconfig.antes-o90; volta = copiar de volta + wsl --shutdown) e o "
                 f"{MISTOS_TAREFA} é retomado depois"),
        Passo("R5", "pausas da parada removidas (os comandos legados obedecem data/.pause_*)",
              cmds=[("vm1", "cd ~/JFN && rm -f " + " ".join(f"data/{p}" for p in pausas))] if pausas else [],
              efeito="nenhuma das pausas listadas em vm1/pausas_criadas.txt existe"),
    ]
    if etapa == 2:
        passos = [Passo("R6", "conferir a etapa 1 antes de seguir (2ª janela, depois da virada da assinatura)", cmds=[
            ("vm1", f"cd ~/JFN && {md} -m compliance_agent.fluxo saude")],
            sql=["SELECT estagio FROM liberacao ORDER BY 1",
                 "SELECT DISTINCT ON (rotulos->>'estagio') rotulos->>'estagio', valor FROM metricas "
                 "WHERE nome = 'religacao_estagio' ORDER BY rotulos->>'estagio', quando DESC"],
            efeito=f"{', '.join(ETAPAS[1])} liberados e com religacao_estagio=1 (o que não estiver vira BLOQUEADO "
                   "aqui e quem depende dele não sobe); os 3 nós com heartbeat; agora ≥ " + VIRADA_ASSINATURA,
            nota="o script recusa a etapa 2 antes da virada da assinatura")]
    mapa = {m["rotina"]: m for m in mapa_legado(g)}
    for grupo in [ordem_da_etapa(etapa)]:
        for e in grupo:
            ag, ev = rotinas_do_estagio(g, e)
            pv = primeira_volta(g, e)
            no_horario = sorted(set(ag) - set(pv))
            subst = sorted(r for r, m in mapa.items() if m["destino"] == "nativo" and m["para"] == e
                           and g.rotinas[r].substituida_por)
            nat = estagios_nativos(g).get(e)
            extra = " — com desde=" + PARADA + " (JFN_DESDE no ambiente do comando)" if e == "E1" else ""
            p = Passo(f"R-{e}", f"liberar {e} ({g.estagios[e].nome}){extra}", estagio=e, rotinas=ag + ev,
                      sql=[f"INSERT INTO liberacao(estagio, por) VALUES ('{e}', '{POR}') ON CONFLICT DO NOTHING",
                           f"UPDATE agenda SET ativo = true, proximo = NULL WHERE payload->>'estagio' = '{e}'",
                           f"-- primeira volta: {len(pv)} job(s) legado:<rotina>:religar:{PARADA}"
                           + (f" (desde={PARADA})" if e == "E1" else "") + f": {', '.join(pv) or '—'}"],
                      efeito=f"{len(pv)} job(s) da primeira volta + os jobs do {e} retidos na fila até a liberação, "
                             + (f"≥ 1 em feito e o resto só esperando (sem erro) depois de {ESPERA_PARCIAL_S // 60} "
                                "min — estágio de LLM: volta PARCIAL, pendentes no rótulo da métrica para as 48 h —"
                                if estagio_parcial(g, e) else "todos em feito,")
                             + f" e 0 quarentena/falhou_efeito do {e} desde a liberação (até "
                             f"{ESPERA_MAX_S // 60} min); metricas religacao_estagio=1",
                      nota=(f"NATIVO `{nat['tipo']}` liberado (entrada: "
                            + (", ".join(sorted(nat["entradas"])) or "—")
                            + (f"; agenda nativa: {', '.join(nat['agenda'])}" if nat["agenda"] else "") + "). "
                            if nat else "sem estágio nativo. ")
                           + (f"Legado DESLIGADO (substituida_por {e}): {', '.join(subst)}. " if subst else "")
                           + (f"no horário (semanal/mensal/condicional, conferir nas 48 h): {', '.join(no_horario)}. "
                              if no_horario else "")
                           + (f"{len(ev)} derivado(s) de evento: {', '.join(ev)}. " if ev else "")
                           + "Falhou ⇒ BLOQUEADO; não libera: "
                           + (", ".join(sorted((x for x in g.estagios if e in depende_de(g, x)),
                                               key=lambda x: int(x[1:]))) or "nenhum"))
            if e == "E15":
                p.cmds += manutencao_sai()
                p.efeito += "; LOGO depois do E15 conferido (antes do E16): painel sem a faixa (GET / sem " \
                            "id=\"jfn-manutencao\") e escrita liberada"
                p.nota += (". Volta da faixa (se for preciso congelar de novo sem desfazer tudo): "
                           + manutencao_volta())
            passos.append(p)
    return passos


def manutencao_sai() -> list[tuple[str, str]]:
    """Fim da faixa de manutenção (E15): backup da unit instalada, comenta JFN_MANUTENCAO*, reinicia e CONFERE."""
    return [("vm1", f"cp {JFN_SERVICE} ~/.config/jfn/jfn.service.antes-o90-$(date +%s) && "
                    f"sed -i -E 's/^(Environment=\"?JFN_MANUTENCAO)/#O90 \\1/' {JFN_SERVICE} && systemctl --user "
                    "daemon-reload && systemctl --user restart jfn.service"),
            ("vm1", f"for i in $(seq 60); do curl -sf -o /tmp/o90_painel.html {PAINEL} && break; sleep 2; done; "
                    "test -s /tmp/o90_painel.html && ! grep -q 'id=\"jfn-manutencao\"' /tmp/o90_painel.html && "
                    "! systemctl --user show jfn.service -p Environment | grep -q 'JFN_MANUTENCAO=1'")]


def manutencao_volta() -> str:
    return (f"sed -i -E 's/^#O90 (Environment=\"?JFN_MANUTENCAO)/\\1/' {JFN_SERVICE} && systemctl --user "
            "daemon-reload && systemctl --user restart jfn.service")


def plano_desfazer(backups: Path, lista_vm2: list[str] | None) -> list[Passo]:
    vm1_timers = ler_lista(backups / "vm1" / "timers_parados.txt")
    vm1_serv = " ".join(ler_lista(backups / "vm1" / "services_parados.txt")).split()
    pausas = ler_lista(backups / "vm1" / "pausas_criadas.txt")
    t1 = " ".join(f"{t}.timer" for t in vm1_timers)
    t2 = " ".join(f"{t}.timer" for t in (lista_vm2 or []))
    md = "PYTHONPATH=. .venv/bin/python"
    para_itc = ("pgrep -f '[c]ompliance_agent.fluxo supervisor --no itcampo' | xargs -r kill -TERM; sleep 10; "
                "! pgrep -f '[c]ompliance_agent.fluxo supervisor --no itcampo'")
    return [
        Passo("D1", "parar o jfn-fluxo nos 3 nós", cmds=[
            ("vm1", "systemctl --user disable --now jfn-fluxo@vm1 2>/dev/null; ! systemctl --user is-active -q jfn-fluxo@vm1"),
            ("vm2", "systemctl --user disable --now jfn-fluxo@vm2 2>/dev/null; ! systemctl --user is-active -q jfn-fluxo@vm2"),
            ("itcampo", f"schtasks /End /TN \\{TAREFA_FLUXO_ITCAMPO}; schtasks /Change /TN \\{TAREFA_FLUXO_ITCAMPO} "
                        "/DISABLE"),
            ("itcampo", wsl(para_itc))],
            efeito="nenhum `compliance_agent.fluxo supervisor` no ps das 3 máquinas (SIGTERM devolve os jobs à fila); "
                   f"{TAREFA_FLUXO_ITCAMPO} Desabilitado"),
        Passo("D2", "fluxo inerte no PG (nada apagado)",
              sql=["UPDATE agenda SET ativo = false", "DELETE FROM liberacao"],
              efeito="0 agenda ativa, 0 estágio liberado; jobs em fila ficam (não reservam sem liberação)"),
        Passo("D3", "crontab antigo de volta (as linhas que o fluxo assumiu e as da parada)", cmds=[
            ("vm1", f"cd ~/JFN && {md} -m tools.cron_para_fluxo --desfazer"),
            ("vm1", f"crontab -l > ~/.config/jfn/backups/crontab_antes_desfazer_$(date +%s).txt && "
                    f"crontab -l | sed 's/^{MARCA}//' | crontab -")],
            efeito="crontab -l sem nenhuma linha começando por #PARADA-20261124 ou #FLUXO-"),
        Passo("D4", "timers e serviços da VM-1", cmds=(
            [("vm1", f"systemctl --user enable --now {t1}")] if t1 else []) + (
            [("vm1", "systemctl --user enable --now " + " ".join(vm1_serv))] if vm1_serv else []),
            efeito=f"{len(vm1_timers)} timer(s) e {len(vm1_serv)} serviço(s) active "
                   f"({', '.join(vm1_timers + vm1_serv)})"),
        Passo("D5", "timers da VM-2", cmds=[("vm2", "cd ~/JFN-worker && if [ -f tools/cron_para_fluxo.py ]; then "
                                                    f"{md} -m tools.cron_para_fluxo --timers --desfazer; fi")]
              + ([("vm2", f"systemctl --user enable --now {t2}")] if t2 else []),
              efeito=(f"{len(lista_vm2)} timer(s) active na VM-2 ({', '.join(lista_vm2)})" if lista_vm2 is not None
                      else "LISTA DA VM-2 ILEGÍVEL neste ensaio — ler vm2:" + LISTA_VM2 + " antes de executar"),
              nota="jfn-amostra-vm2 está na lista mas já estava desligado antes da parada (frente a201: "
                   "data/.vm2_amostra_estratificada) — conferir com o dono antes de religá-lo. As units da VM-2 "
                   "apontam para ~/JFN-worker (O2.4): o código que volta é o do SHA da janela"),
        Passo("D6", "tarefas do it-campo", cmds=[
            ("itcampo", "; ".join(f'schtasks /Change /TN "\\{t}" /ENABLE' for t in TAREFAS_ITCAMPO)),
            ("itcampo", "; ".join(f'schtasks /Run /TN "\\{t}"' for t in TAREFAS_ITCAMPO))],
            efeito="as 3 tarefas Habilitado e Em execução (schtasks /Query /FO CSV); JFNAcordado nunca foi tocado",
            nota="o shell do it-campo é PowerShell: comandos separados por `;` (`&` é recusado — medido 25/11)"),
        Passo("D7", "pausas da parada removidas",
              cmds=[("vm1", "cd ~/JFN && rm -f " + " ".join(f"data/{p}" for p in pausas))] if pausas else [],
              efeito=f"nenhuma de {len(pausas)} pausa(s) existe: {', '.join(pausas)}"),
        Passo("D8", "faixa de manutenção sai do painel (o sistema antigo escreve)", cmds=[
            ("vm1", f"sed -i -E 's/^(Environment=\"?JFN_MANUTENCAO)/#DESFAZER \\1/' {JFN_SERVICE}"
                    " && systemctl --user daemon-reload && systemctl --user restart jfn.service")],
            efeito="painel responde sem 'Em manutenção' e aceita escrita (se o E15 já a tirou, a linha não casa e "
                   "nada muda)"),
        Passo("D9", "snapshot (MANUAL, só se houve escrita ruim)",
              efeito="compliance.db e pg_dump restaurados de D:\\JFN-Frio\\snapshot-20261124\\ com md5 conferido",
              nota="nunca automático: decidir com o dono depois de ver o que foi escrito"),
    ]


# ── prova do schema num esquema de ENSAIO (problema 3 da preparação) ─────────────────────────────────────────
def provar_schema(con, esquema: str, manter: bool = False) -> dict:
    """fluxo_001 SÓ (o estado do `fluxo` de produção em 25/11) → verificar (falta) → aplicar → verificar → aplicar →
    verificar. ok = a 1ª verificação acusa o fluxo_002, as outras duas dão ok=true e são iguais, e o 2º `aplicar`
    não aplica nada. Recusa qualquer esquema fora de `ensaio_o90…` (o `fluxo` real nunca é tocado)."""
    from compliance_agent.fluxo import schema as S
    S.validar_esquema(esquema)
    if not esquema.startswith("ensaio_o90"):
        raise ValueError(f"só esquema de ensaio `ensaio_o90…` (nunca o `fluxo` real): {esquema!r}")
    con.execute(f'DROP SCHEMA IF EXISTS "{esquema}" CASCADE')
    try:
        con.execute(S.renderizar((S.PASTA_SQL / "fluxo_001.sql").read_text(encoding="utf-8"), esquema))
        v0 = S.verificar(con, esquema)
        a1 = S.aplicar(con, esquema)
        v1 = S.verificar(con, esquema)
        a2 = S.aplicar(con, esquema)
        v2 = S.verificar(con, esquema)
    finally:
        if not manter:
            con.execute(f'DROP SCHEMA IF EXISTS "{esquema}" CASCADE')
    ok = (not v0["ok"] and "migração fluxo_002" in v0["faltando"] and v1["ok"] and v2 == v1 and a2 == []
          and "fluxo_002" in a1)
    return {"esquema": esquema, "ok": ok, "antes": {"ok": v0["ok"], "versoes": v0["versoes"],
                                                    "faltando": v0["faltando"]},
            "aplicar_1": a1, "depois_1": v1, "aplicar_2": a2, "depois_2": v2, "apagado": not manter}


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


def estagio_de_llm(g, estagio: str) -> bool:
    """O estágio pede `llm` ou alguma rotina da primeira volta pede (o ritmo da assinatura segura o passo)."""
    return "llm" in g.estagios[estagio].recursos or any("llm" in g.contrato_da_rotina(r)["recursos"]
                                                        for r in primeira_volta(g, estagio))


# estágios que DRENAM fila alimentada por eventos (26/11/2026: o E2 da janela 1 tinha 2.239 árvores na 1ª volta)
ESTAGIOS_DE_FILA = frozenset({"E2", "E3", "E4", "E5", "E6", "E7"})


def estagio_parcial(g, estagio: str) -> bool:
    """Confere pela volta parcial (≥ 1 feito, 0 erro, o resto esperando): estágio de LLM ou estágio de fila."""
    return estagio in ESTAGIOS_DE_FILA or estagio_de_llm(g, estagio)


def conferir_estagio(con, estagio: str, chaves: list[str], parcial: bool = False, decorrido_s: float = 0.0,
                     espera_parcial_s: float = ESPERA_PARCIAL_S, fila: bool = False) -> dict:
    """Efeito do estágio: primeira volta inteira em `feito` e nada do estágio em quarentena/falhou_efeito desde a
    liberação. `pendentes` > 0 = ainda não dá para decidir. `parcial` (estágio de LLM): passada a espera mínima,
    vale ≥ 1 feito com o resto só esperando, sem erro (ESPERA_PARCIAL_S)."""
    est = dict(con.execute("SELECT estado, count(*) FROM jobs WHERE chave = ANY(%s) GROUP BY estado",
                           (chaves,)).fetchall()) if chaves else {}
    esperando = [(c, e) for c, e in con.execute(
        "SELECT chave, erro_tipo FROM jobs WHERE chave = ANY(%s) AND estado IN ('fila', 'reservado') ORDER BY chave",
        (chaves,)).fetchall()] if chaves else []
    # resultado declarado do domínio (processo restrito/sigilo, ForaDeAlcance) não é erro do estágio (26/11/2026)
    ruins, fora = con.execute(
        "SELECT count(*) FILTER (WHERE coalesce(j.erro_resumo, '') NOT LIKE '[fora\\_de\\_alcance]%%'), "
        "count(*) FILTER (WHERE coalesce(j.erro_resumo, '') LIKE '[fora\\_de\\_alcance]%%') "
        "FROM jobs j, liberacao l WHERE l.estagio = %s AND j.payload->>'estagio' = %s "
        "AND j.estado IN ('quarentena', 'falhou_efeito') AND coalesce(j.concluido_em, j.criado_em) >= l.liberado_em",
        (estagio, estagio)).fetchone()
    feitos = est.get("feito", 0)
    pendentes = sum(n for e, n in est.items() if e in ("fila", "reservado"))
    # chave da 1ª volta que é ForaDeAlcance (quarentena declarada) está DECIDIDA — sem isto a soma nunca fechava e o
    # E2 (com processos restritos na própria volta) não passava em caso nenhum (26/11/2026 12h25)
    fora_da_volta = con.execute(
        "SELECT count(*) FROM jobs WHERE chave = ANY(%s) AND estado IN ('quarentena', 'falhou_efeito') "
        "AND coalesce(erro_resumo, '') LIKE '[fora\\_de\\_alcance]%%'", (chaves,)).fetchone()[0] if chaves else 0
    inteira = ruins == 0 and pendentes == 0 and feitos + fora_da_volta == len(chaves)
    # interrupção da INFRAESTRUTURA não é falha do job (26/11/2026: reinícios do supervisor e do PG deixaram 15 jobs
    # com `parada`/`lease_vencido` e o E2 não fechava): espera (adiado), supervisor parado, posse vencida, governador
    com_erro = sum(1 for _c, e in esperando if e not in (None, "adiado", "parada", "lease_vencido", "pressao"))
    # estágio de FILA (26/11/2026): nova tentativa isolada é normal numa fila de milhares (a falha real é a quarentena,
    # já em `ruins`); tolera até 10% dos feitos (mínimo 3). Erro sistemático passa disso e barra. LLM: zero.
    tolerancia = max(3, feitos // 10) if fila else 0
    so_esperando = feitos + pendentes + fora_da_volta == len(chaves) and com_erro <= tolerancia
    meia = (parcial and not inteira and ruins == 0 and feitos >= 1 and so_esperando
            and decorrido_s >= espera_parcial_s)
    r = {"estagio": estagio, "feitos": feitos, "esperados": len(chaves), "pendentes": pendentes, "ruins": ruins,
         "fora_de_alcance": fora, "ok": inteira or meia}
    if parcial:
        r.update(parcial=meia, com_erro=com_erro, pendentes_chaves=[c for c, _e in esperando][:50])
    return r


def esperar_estagio(con, estagio: str, chaves: list[str], espera_max_s: float = ESPERA_MAX_S,
                    poll_s: float = POLL_S, dormir: Callable[[float], None] = time.sleep,
                    relogio: Callable[[], float] = time.monotonic, parcial: bool = False,
                    espera_parcial_s: float = ESPERA_PARCIAL_S, fila: bool = False) -> dict:
    """Espera a decisão (o script é a janela da religação, com o dono olhando — não um laço residente)."""
    ini = relogio()
    fim = ini + espera_max_s
    while True:
        r = conferir_estagio(con, estagio, chaves, parcial, relogio() - ini, espera_parcial_s, fila)
        if r["ok"] or r["ruins"] or r["pendentes"] == 0 or relogio() >= fim:
            r["esgotou"] = r["pendentes"] > 0 and not r["ok"]   # passou do teto ainda pendente = BLOQUEADO
            return r
        dormir(poll_s)


def registrar(con, r: dict) -> None:
    con.execute("INSERT INTO metricas(no, nome, valor, rotulos) VALUES (NULL, 'religacao_estagio', %s, %s)",
                (1.0 if r["ok"] else 0.0, json.dumps(r)))


def religar_estagios(con, g, espera_max_s: float = ESPERA_MAX_S, so: list[str] | None = None,
                     dormir: Callable[[float], None] = time.sleep, log=print,
                     apos: Callable[[str, dict], dict | None] | None = None,
                     bloqueados_iniciais: set[str] | None = None) -> dict:
    """Passo 4 inteiro: estágio a estágio, com BLOQUEADO propagado só a quem depende. `apos(e, r)` roda logo
    depois do estágio conferido e ANTES do seguinte (E15: a faixa de manutenção sai aqui, não no fim); se devolver
    {"ok": False, …} o estágio vira BLOQUEADO (a faixa não saiu = o efeito do E15 não está completo)."""
    bloqueados: set[str] = set(bloqueados_iniciais or ())
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
        r = esperar_estagio(con, e, chaves, espera_max_s, dormir=dormir, parcial=estagio_parcial(g, e),
                            fila=e in ESTAGIOS_DE_FILA)
        if r["ok"] and apos is not None:
            extra = apos(e, r)
            if extra:
                r.update(extra)
        registrar(con, r)
        out[e] = r
        if not r["ok"]:
            bloqueados.add(e)
        log(f"[{e}] {'CONFERIDO' if r['ok'] else 'BLOQUEADO'}: {r}")
    return out


def rodar_cmd(no: str, cmd: str, rodar=subprocess.run) -> int:
    r = rodar(no_cmd(no, cmd), timeout=600)
    return r.returncode


# ── ensaio: o que se consegue medir agora (só leitura) ───────────────────────────────────────────────────────
def _ler(rodar, argv: list[str], timeout: int = 40) -> tuple[int, str]:
    try:
        r = rodar(argv, capture_output=True, text=True, errors="replace", timeout=timeout)  # schtasks pt-BR = CP-850 (Em execução)
        return r.returncode, (r.stdout or "").strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return -1, type(exc).__name__


def estado_nos(sha: str, rodar=subprocess.run) -> dict:
    """Só leitura, por ssh: HEAD da árvore do worker, código mexido, DSN presente (nunca o conteúdo), tarefa do
    it-campo. Chaves ausentes = não medido (o ensaio DIZ)."""
    mod = base64.b64encode((RAIZ / "compliance_agent" / "credenciais.py").read_bytes()).decode("ascii")
    sonda = ("cd ~/JFN-worker 2>/dev/null && echo head=$(git rev-parse HEAD) && echo sujo=$(git status --porcelain "
             "--untracked-files=no -- . ':(exclude)data' | wc -l); "
             f"python3 -c 'import base64;exec(base64.b64decode(\"{mod}\"))' onde JFN_EVIDENCIAS_DSN "
             "| sed 's/^JFN_EVIDENCIAS_DSN: /dsn=/'; "
             "echo disco=$(grep -rls '^JFN_EVIDENCIAS_DSN=' ~/.config/jfn ~/JFN-worker/.env 2>/dev/null | wc -l)")
    out = {}
    for no, cmd in (("vm2", sonda), ("itcampo", wsl(sonda))):
        rc, txt = _ler(rodar, no_cmd(no, cmd))
        d = dict(ln.split("=", 1) for ln in txt.splitlines() if "=" in ln)
        head = d.get("head", "")
        # ff conferido AQUI (o worker ainda não buscou o SHA novo): o HEAD dele é ancestral do SHA no canônico?
        ff = bool(head) and _ler(rodar, ["git", "-C", str(RAIZ), "merge-base", "--is-ancestor", head, sha])[0] == 0
        out[no] = {"medido": bool(head), "head": head, "sujo": int(d.get("sujo") or 0), "ff": ff,
                   "dsn": d.get("dsn", "NAO") if not d.get("dsn", "NAO").startswith("NAO") else None,
                   "disco": int(d.get("disco") or 0)}
    rc, txt = _ler(rodar, no_cmd("itcampo", f"schtasks /Query /TN \\{TAREFA_FLUXO_ITCAMPO} /FO CSV /NH"))
    out["itcampo"]["tarefa"] = txt.split(",")[-1].strip('" ') if rc == 0 and txt else None
    return out


def catraca_ambiente(raiz: Path = RAIZ) -> list[str]:
    """Os arquivos que montam o ambiente da produção dizem o que a O9.0 pede? Devolve os defeitos (vazio = ok)."""
    erros = []
    env = (raiz / AMBIENTE).read_text(encoding="utf-8")
    linhas = {ln.split("=", 1)[0]: ln.split("=", 1)[1] for ln in env.splitlines()
              if ln.strip() and not ln.lstrip().startswith("#") and "=" in ln}
    for k, v in ENV_PRODUCAO.items():
        if linhas.get(k) != v:
            erros.append(f"{AMBIENTE}: {k}={v} ausente")
    if ENV_PROIBIDA in linhas:
        erros.append(f"{AMBIENTE}: {ENV_PROIBIDA} no ambiente da produção")
    for no, d in DROPIN.items():
        t = (raiz / d).read_text(encoding="utf-8")
        arv = ARVORE[no].replace("~", "%h")
        for exigido in (f"WorkingDirectory={arv}", f"EnvironmentFile={arv}/{AMBIENTE}",
                        f"UnsetEnvironment={ENV_PROIBIDA}"):
            if exigido not in t:
                erros.append(f"{d}: falta `{exigido}`")
    ps = (raiz / PS1_ITCAMPO).read_text(encoding="utf-8")
    for exigido in (f". {AMBIENTE}", f"unset {ENV_PROIBIDA}", "/home/iterj/JFN-worker"):
        if exigido not in ps:
            erros.append(f"{PS1_ITCAMPO}: falta `{exigido}`")
    return erros


def pendencias(g, nos: dict | None, sha: str, schema_ok: bool | None) -> list[tuple[str, bool]]:
    """(texto, depende_do_dono). O que um passo do roteiro resolve NÃO é pendência (vai como nota medida)."""
    out: list[tuple[str, bool]] = []
    for e, evs in entradas_sem_produtor(g).items():
        out.append((f"estágio nativo {e} sem produtor de entrada em produção ({', '.join(evs)})", False))
    for r in orfas(g):
        out.append((f"rotina {r} ficaria sem gatilho (só escuta rotina desligada)", False))
    sem = [m["rotina"] for m in mapa_legado(g) if not m["motivo"]]
    if sem:
        out.append((f"rotina(s) sem destino/motivo declarado: {', '.join(sem)}", False))
    out += [(f"ambiente da produção: {x}", False) for x in catraca_ambiente()]
    for no, d in (nos or {}).items():
        if not d.get("medido"):
            out.append((f"{no}: estado da árvore não medido (ssh) — repetir o ensaio", False))
        elif d["sujo"]:
            out.append((f"{no}: ~/JFN-worker com {d['sujo']} arquivo(s) de código mexido(s) — o ff-only recusa", False))
        elif not d.get("dsn"):
            out.append((f"{no}: DSN do PG não resolvível pelo resolvedor de credenciais", False))
        elif d.get("disco"):
            out.append((f"{no}: {d['disco']} arquivo(s) do worker guardam JFN_EVIDENCIAS_DSN (credencial só se acha)",
                        False))
        elif not d["ff"] and d["head"] != sha:
            out.append((f"{no}: ~/JFN-worker em {d['head'][:10]} não é ancestral de {sha[:10]} (ff impossível)", False))
    if nos and nos.get("itcampo", {}).get("tarefa") is None:
        out.append((f"it-campo: tarefa {TAREFA_FLUXO_ITCAMPO} não encontrada (registrar o XML de deploy/itcampo/fluxo)",
                    False))
    out += [
        ("O8.5 verde (ensaio ponta a ponta + leitura única) — critério da §1.1 para abrir a janela", True),
        ("janela marcada com o dono avisado (--confirmo-dono-avisado)", True),
        ("§3.5 ensaio de 24 h sem it-campo (O8.3, dono em casa) — critério da §1.1; sem ele, religar sabendo que a "
         "volta sem it-campo não foi ensaiada", True),
        ("duas janelas: etapa 1 (E17, E18, E1–E7) agora; etapa 2 (E8–E16) só depois da virada da assinatura "
         f"({VIRADA_ASSINATURA}) — o script recusa a etapa 2 antes", True),
        ("✅ do lote jurídico (O4.10) e da paridade de juízo (O6.4): enquanto não vier, E9/E10/E11 nativos ficam em "
         "sombra e o legado é a produção", True),
        ("jfn-amostra-vm2: religar ou não no desfazer (estava desligado antes da parada)", True),
    ]
    return out


def preliminares(g, rodar=subprocess.run) -> list[str]:
    """Só leitura: o que o ensaio consegue medir agora."""
    sha = sha_main(rodar)
    ativas = sum(r.ativa for r in g.rotinas.values())
    mapa = mapa_legado(g)
    cont = {k: sum(m["destino"] == k for m in mapa) for k in ("nativo", "legado", "desligada")}
    out = [f"SHA do main (fixado para a janela): {sha}",
           f"grafo: {len(g.rotinas)} rotinas ({ativas} ativas), {len(g.agenda_linhas())} linhas de agenda legado + "
           f"{len(g.agenda_nativa())} nativas; transitórios: "
           + (", ".join(f"{k} ({t.slots} {t.recurso} em {t.maquina} até {t.transitorio_ate}, {len(t.rotinas)} rotinas)"
                        for k, t in g.transitorios.items()) or "nenhum"),
           f"uma porta por trabalho: {cont['nativo']} rotina(s) → nativo (desligadas), {cont['legado']} legado ligado "
           f"com motivo, {cont['desligada']} desligada(s) com bloqueio (mapa: --mapa)"]
    rc, txt = _ler(rodar, ["crontab", "-l"], 20)
    out.append(f"crontab: {sum(ln.startswith(MARCA) for ln in txt.splitlines())} linhas {MARCA.strip()} (comentadas)"
               if rc == 0 else f"crontab: ilegível ({txt})")
    schema_ok = None
    import psycopg

    from compliance_agent.evidencias import dsn_vigente
    from compliance_agent.fluxo import schema
    try:
        dsn = dsn_vigente()
        if dsn:
            con = schema.conectar_leitura(dsn)
            try:
                v = schema.verificar(con)
                schema_ok = v["ok"]
                out.append(f"schema fluxo (só leitura): ok={v['ok']} versões={v['versoes']} faltando={v['faltando']}"
                           + ("" if v["ok"] else " → resolvido no R0 (`aplicar`, idempotente; prova: --provar-schema)"))
                for sql, rot in (("SELECT count(*), count(*) FILTER (WHERE ativo) FROM fluxo.agenda", "agenda (total, ativas)"),
                                 ("SELECT estado, count(*) FROM fluxo.jobs GROUP BY estado ORDER BY 1", "jobs por estado")):
                    out.append(f"{rot}: {con.execute(sql).fetchall()}")
                falta = [t for _m, t in SCHEMAS_NATIVOS if con.execute("SELECT to_regclass(%s)", (t,)).fetchone()[0]
                         is None]
                out.append("schemas dos estágios nativos: " + (f"faltam {', '.join(falta)} → resolvido no R0 "
                                                               "(`<estágio> schema aplicar`)" if falta else "todos presentes"))
            finally:
                con.close()
        else:
            out.append("schema fluxo: sem DSN — não medido")
    except (psycopg.Error, OSError) as exc:            # o ensaio DIZ que não mediu; não derruba o relatório
        out.append(f"schema fluxo: não medido ({type(exc).__name__})")
    nos = estado_nos(sha, rodar)
    for no, d in nos.items():
        if d["medido"]:
            out.append(f"{no}: ~/JFN-worker em {d['head'][:10]} ({'= SHA' if d['head'] == sha else 'ff até o SHA ok' if d['ff'] else 'SEM ff'}; "
                       f"{d['sujo']} código mexido{'; R1 atualiza' if d['head'] != sha else ''}); "
                       f"DSN pelo resolvedor: {d['dsn'] or 'NÃO ENCONTRADO'}; {d.get('disco', 0)} arquivo(s) com o "
                       "DSN no worker"
                       + (f"; tarefa {TAREFA_FLUXO_ITCAMPO}: {d.get('tarefa')} → R4 habilita" if no == "itcampo" else ""))
        else:
            out.append(f"{no}: não medido (ssh)")
    for r in ressalvas(g):
        out.append(f"RESSALVA (observar nas 48 h): {r}")
    pend = pendencias(g, nos, sha, schema_ok)
    abertas = [t for t, dono in pend if not dono]
    out.append(f"PRÉ-CONDIÇÕES ABERTAS sem depender do dono: {len(abertas)}" + "".join(f"\n      ✗ {t}" for t in abertas))
    out.append("CRITÉRIOS DA JANELA (decisão delegada ao coordenador — conferir antes do --executar; não são "
               "passos do roteiro): " + "".join(f"\n      ◻ {t}" for t, dono in pend if dono))
    return out


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


def mapa_markdown(g) -> str:
    linhas = ["| Estágio | Rotina | Destino na religação | Motivo |", "|---|---|---|---|"]
    rot = {"nativo": "**nativo {p}** (desligada)", "legado": "legado (ligada)", "desligada": "desligada"}
    for m in mapa_legado(g):
        motivo = (m["motivo"] or "").replace("|", "/").replace("\n", " ")
        linhas.append(f"| {m['estagio']} | `{m['rotina']}` | {rot[m['destino']].format(p=m['para'])} | {motivo} |")
    return "\n".join(linhas) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Religação O9.0 (ou desfazer) em sequência verificada")
    modo = ap.add_mutually_exclusive_group()
    modo.add_argument("--ensaio", action="store_true", help="padrão: só imprime")
    modo.add_argument("--executar", action="store_true")
    modo.add_argument("--mapa", action="store_true", help="mapa rotina legada → destino (Markdown)")
    modo.add_argument("--provar-schema", metavar="ESQUEMA", help="prova do `schema aplicar` num esquema ensaio_o90…")
    ap.add_argument("--desfazer", action="store_true", help="volta ao sistema antigo (crontab, timers, tarefas)")
    ap.add_argument("--confirmo-dono-avisado", action="store_true")
    ap.add_argument("--espera-max-s", type=float, default=ESPERA_MAX_S)
    # 25/11/2026: a 1ª janela teve estágios BLOQUEADOS por defeitos já corrigidos (filtro de saída, governador, teto
    # de 900 s); repetir só a liberação + conferência, sem refazer R0–R5 (wsl --shutdown, deploy, cron → fluxo).
    ap.add_argument("--so-estagios", action="store_true",
                    help="só os passos de estágio (liberar + conferir); pula os de máquina (R0–R5)")
    ap.add_argument("--backups", default=str(BACKUPS))
    ap.add_argument("--sha", help="SHA do main para a janela (padrão: HEAD da VM-1 agora)")
    ap.add_argument("--etapa", type=int, choices=(1, 2), help="1 = E17, E18, E1–E7 (1ª janela); 2 = E8–E16 (depois "
                                                              "da virada da assinatura). Obrigatória no --executar")
    ap.add_argument("--avisar", metavar="TEXTO", help="manda TEXTO ao Telegram (env TELEGRAM_BOT_TOKEN/CHAT_ID); "
                                                     "rc 0 só com message_id")
    a = ap.parse_args(argv)
    for f in (sys.stdout, sys.stderr):                 # janela 1: `> arquivo` só mostrava os [E…] no fim
        if hasattr(f, "reconfigure"):
            f.reconfigure(line_buffering=True)
    if a.avisar:
        mid = avisar_telegram(a.avisar)
        print(f"aviso: message_id={mid}" if mid else "aviso: NÃO entregue (sem message_id)")
        return 0 if mid else 1
    from compliance_agent.fluxo import grafo as G
    g = G.carregar()
    if a.mapa:
        sys.stdout.write(mapa_markdown(g))
        return 0
    if a.provar_schema:
        import psycopg

        from compliance_agent.evidencias import dsn_vigente
        con = psycopg.connect(dsn_vigente(), autocommit=True)
        try:
            r = provar_schema(con, a.provar_schema)
        finally:
            con.close()
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0 if r["ok"] else 1
    backups = Path(a.backups)
    if a.desfazer:
        passos = plano_desfazer(backups, ler_lista_vm2())
        titulo = "DESFAZER da religação O9.0"
    else:
        pausas = ler_lista(backups / "vm1" / "pausas_criadas.txt")
        passos = plano_religar(g, pausas, a.sha or sha_main(), a.etapa)
        titulo = "RELIGAÇÃO O9.0" + (f" — ETAPA {a.etapa}" if a.etapa else "")
        if a.so_estagios:
            passos = so_estagios(passos)
            titulo += " (só estágios)"
    if not a.executar:
        aviso = [f"aviso Telegram (DESLIGADO no ensaio; no --executar, ao começar e ao terminar): "
                 f"{AVISO_CMD.format(texto=chr(39) + '<texto>' + chr(39))}"]
        if a.desfazer or a.etapa:
            imprimir(passos, titulo, (preliminares(g) if not a.desfazer else []) + aviso)
        else:                                          # sem --etapa: as duas janelas, uma depois da outra
            imprimir(plano_religar(g, pausas, a.sha or sha_main(), 1), "RELIGAÇÃO O9.0 — ETAPA 1 (1ª janela)",
                     preliminares(g) + aviso)
            imprimir(plano_religar(g, pausas, a.sha or sha_main(), 2),
                     f"RELIGAÇÃO O9.0 — ETAPA 2 (2ª janela, depois de {VIRADA_ASSINATURA})", [])
        return 0
    if not a.confirmo_dono_avisado:
        print("recusado: --executar exige --confirmo-dono-avisado (a religação é numa janela com o dono)",
              file=sys.stderr)
        return 2
    if not a.desfazer and a.etapa is None:
        print("recusado: --executar exige --etapa 1 ou 2 (religação em duas janelas)", file=sys.stderr)
        return 2
    if a.etapa == 2 and not virou_assinatura():
        print(f"recusado: etapa 2 só depois da virada da assinatura ({VIRADA_ASSINATURA})", file=sys.stderr)
        return 2
    if not a.desfazer:
        abertas = [t for t, dono in pendencias(g, estado_nos(a.sha or sha_main()), a.sha or sha_main(), None)
                   if not dono]
        if abertas:
            print("recusado: pré-condição aberta — " + "; ".join(abertas), file=sys.stderr)
            return 2
    return executar(passos, g, a.espera_max_s, titulo=titulo, etapa=a.etapa)


def porta_llm(con, g) -> str | None:
    """O que o supervisor leria agora para o E8 (fluxo/ritmo.py: medição no PG, ausente/velha = fechada)."""
    from compliance_agent.fluxo import ritmo
    return ritmo.motivo(con, g.estagios["E8"].ritmo)


def virou_assinatura(agora=None) -> bool:
    from datetime import datetime, timezone
    agora = agora or datetime.now(timezone.utc)
    return agora >= datetime.fromisoformat(VIRADA_ASSINATURA)


def bloqueados_da_etapa1(con) -> set[str]:
    """Estágio da etapa 1 sem liberação ou cuja última `religacao_estagio` não é 1: BLOQUEADO para a etapa 2."""
    lib = {r[0] for r in con.execute("SELECT estagio FROM liberacao")}
    ult = dict(con.execute("SELECT DISTINCT ON (rotulos->>'estagio') rotulos->>'estagio', valor FROM metricas "
                           "WHERE nome = 'religacao_estagio' ORDER BY rotulos->>'estagio', quando DESC").fetchall())
    return {e for e in ETAPAS[1] if e not in lib or ult.get(e) != 1.0}


def avisar_telegram(texto: str, enviar=None) -> int | None:
    """sendMessage com o chat EXPLÍCITO do ambiente; devolve o message_id ou None (sem credencial, HTTP ≠ 200,
    ok=False ou sem message_id). Nunca imprime o token."""
    import os
    import urllib.parse
    import urllib.request
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_CHAT_ID", "")
    if not tok or not chat:
        return None
    dados = urllib.parse.urlencode({"chat_id": chat, "text": texto[:3500]}).encode()
    if enviar is None:
        def enviar(url, corpo):
            with urllib.request.urlopen(urllib.request.Request(url, data=corpo), timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
    try:
        r = enviar(f"https://api.telegram.org/bot{tok}/sendMessage", dados)
    except (OSError, ValueError):
        return None
    mid = (r or {}).get("result", {}).get("message_id") if (r or {}).get("ok") else None
    return int(mid) if mid else None


def avisar(texto: str, rodar=subprocess.run, log=print) -> bool:
    import shlex
    rc = rodar_cmd("vm1", AVISO_CMD.format(texto=shlex.quote(texto)), rodar)
    log(f"[aviso] {'entregue' if rc == 0 else 'NÃO entregue'}: {texto}")
    return rc == 0


class ConexaoResiliente:
    """Conexão do religar que sobrevive a reinício do PG (26/11/2026 03:04: o unattended-upgrades da VM-2 reiniciou o
    PG e a janela morreu com AdminShutdown no meio do E1). Tudo que o religar executa é idempotente (SELECT, INSERT …
    ON CONFLICT, enfileirar pela chave): na OperationalError reconecta e repete, até `tentativas` vezes."""

    def __init__(self, abrir: Callable, primeira=None, tentativas: int = 12, pausa_s: float = 10.0,
                 dormir: Callable[[float], None] = time.sleep):
        self._abrir, self._con = abrir, primeira if primeira is not None else abrir()
        self._tentativas, self._pausa_s, self._dormir = tentativas, pausa_s, dormir

    def execute(self, *a, **k):
        import psycopg
        for n in range(self._tentativas):
            try:
                return self._con.execute(*a, **k)
            except psycopg.OperationalError as exc:
                if n == self._tentativas - 1:
                    raise
                print(f"[pg] conexão caiu ({type(exc).__name__}); reconectando ({n + 1}/{self._tentativas})",
                      flush=True)
                try:
                    self._con.close()
                except Exception as fechar:                        # noqa: BLE001 — conexão já morta
                    print(f"[pg] fechar a conexão morta falhou ({type(fechar).__name__})", flush=True)
                self._dormir(self._pausa_s)
                try:
                    self._con = self._abrir()
                except psycopg.OperationalError as abrir_exc:      # PG ainda subindo: a volta seguinte tenta de novo
                    print(f"[pg] reconexão falhou ({type(abrir_exc).__name__})", flush=True)

    def close(self):
        self._con.close()

    def __getattr__(self, nome):
        return getattr(self._con, nome)


def so_estagios(passos: list[Passo]) -> list[Passo]:
    """Repetição de uma janela: só os passos de estágio (liberar + conferir, idempotentes pela chave)."""
    return [p for p in passos if p.estagio]


def executar(passos: list[Passo], g, espera_max_s: float, rodar=subprocess.run, con=None, log=print,
             titulo: str = "RELIGAÇÃO O9.0", etapa: int | None = None) -> int:
    """Roda os passos em ordem; passo de máquina que falha PARA tudo (rc 1); estágio que falha fica BLOQUEADO.
    Os comandos de um estágio (E15: a faixa de manutenção) rodam LOGO depois de ele conferir, antes do seguinte."""
    from compliance_agent.fluxo import fila
    if not avisar(f"JFN {titulo}: começando ({len(passos)} passos). Volta: tools/religar_o90.py --desfazer", rodar, log):
        log("aviso de início NÃO entregue (sem message_id) — nada foi feito")
        return 1
    con = con or ConexaoResiliente(fila.conectar)
    estagios = [p.estagio for p in passos if p.estagio]
    cmds_do = {p.estagio: p.cmds for p in passos if p.estagio and p.cmds}
    for p in passos:
        if p.estagio:
            continue
        for no, c in p.cmds:
            log(f"[{p.id}] ({no}) {c}")
            rc = rodar_cmd(no, c, rodar)
            if rc != 0:
                log(f"[{p.id}] FALHOU rc={rc} — parado aqui; nada adiante foi feito")
                avisar(f"JFN {titulo}: PAROU no {p.id} (rc={rc}). Decidir: corrigir e repetir, ou --desfazer",
                       rodar, log)
                return 1
        for s in p.sql:
            if not s.startswith(("SELECT", "--")):
                con.execute(s)

    def apos(e: str, _r: dict) -> dict | None:
        for no, c in cmds_do.get(e, []):
            log(f"[R-{e}] ({no}) {c}")
            rc = rodar_cmd(no, c, rodar)
            if rc != 0:
                log(f"[R-{e}] FALHOU rc={rc} — estágio BLOQUEADO (o que depende dele não é liberado)")
                volta = None
                if e == "E15":                         # sem meio-estado: a faixa VOLTA (unit editada ou painel fora)
                    volta = rodar_cmd("vm1", manutencao_volta(), rodar)
                    log(f"[R-{e}] faixa de manutenção recolocada: rc={volta}")
                return {"ok": False, "falhou_cmd": c[:200], "rc": rc, "faixa_voltou_rc": volta}
        return None

    if etapa == 2 and (porta := porta_llm(con, g)):
        log(f"[etapa 2] porta da assinatura FECHADA — nada liberado: {porta}")
        avisar(f"JFN {titulo}: PAROU antes do E8 — {porta[:200]}. Repetir com --so-estagios quando abrir", rodar, log)
        return 1
    ini = bloqueados_da_etapa1(con) if etapa == 2 else set()
    if ini:
        log(f"[etapa 2] da etapa 1 sem efeito conferido (BLOQUEADOS): {sorted(ini)}")
    r = religar_estagios(con, g, espera_max_s, so=estagios, log=log, apos=apos,
                         bloqueados_iniciais=ini) if estagios else {}
    bloq = sorted((e for e, x in r.items() if not x.get("ok")), key=lambda x: int(x[1:]))
    log(json.dumps({"bloqueados": bloq}, ensure_ascii=False))
    fim = avisar(f"JFN {titulo}: terminou. " + (f"BLOQUEADOS: {', '.join(bloq)}" if bloq else
                                               "todos os estágios conferidos") + ". Começam as 48 h de observação.",
                 rodar, log)
    return 0 if fim else 4


if __name__ == "__main__":
    sys.exit(main())
