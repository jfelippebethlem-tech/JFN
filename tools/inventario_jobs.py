#!/usr/bin/env python3
"""Inventário de TUDO o que rodava antes da parada de obras (O1.1 do plano mestre v2 — "Esteira Única").

Só leitura. Lê as fotografias de 24/11/2026 (~/.config/jfn/backups/refatoracao-20261124/{vm1,vm2,itcampo}/),
o crontab da VM-1 (linhas ativas, as comentadas pela parada com `#PARADA-20261124 ` e as comentadas antes),
os timers/serviços systemd da VM-1 e da VM-2, as tarefas JFN do Windows do it-campo (schtasks.csv) e os
derivados de config/propagacao.yaml. Gera config/jobs.yaml (um registro por job) e, com --md, a nota legível
do vault. Com --capacidade, mede duração p50 por job (propagacao.db, journal do systemd, tools/pesado.sh e logs
em data/) e escreve a nota de capacidade (O1.6).

Rede: nenhuma, exceto `--ssh` (opcional): `ssh vm2-ts` com timeout para ler `systemctl --user cat` e o journal
da VM-2 (sem isso, as definições da VM-2 vêm de deploy/vm2/ e a duração dos timers dela fica estimada).

Campos de cada job: id (slug estável), dono (vm1|vm2|itcampo), executa_em (quando o gatilho mora num nó e o
trabalho em outro), gatilho {tipo: cron|timer|servico|logon|evento|filho|boot, expr}, comando, recursos
(leve|pesado|navegador|gpu|llm, inferidos do comando e do script chamado), timeout_s, orcamento_s (teto que o
próprio job declara: --segundos, --max-min, SWEEP_MAX_SECONDS…), estado_pre_parada
(ativo|rede|comentado|parado), estagio_destino (E1..E18, combinação "E2+E3", "aposentar", ou as duas extensões
declaradas aqui: "infra" = serviço residente que não é estágio, "fora_do_jfn" = outro sistema que divide a
máquina), lente, duplicado_de (id do 1º job com o mesmo ponto de entrada) + duplicacao (exato|mesmo_script).

Uso:
  python tools/inventario_jobs.py                 # gera config/jobs.yaml
  python tools/inventario_jobs.py --md            # + vault/refatoracao/inventario-jobs-20261124.md
  python tools/inventario_jobs.py --capacidade    # + duracao_p50 nos jobs e vault/.../capacidade-20261124.md
  python tools/inventario_jobs.py --ssh           # complementa a VM-2 pela rede (timeout 40 s)
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import re
import sqlite3
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent
BACKUP = Path.home() / ".config/jfn/backups/refatoracao-20261124"
VAULT = Path.home() / "vault/refatoracao"
MARCA_PARADA = "#PARADA-20261124 "

# ----------------------------------------------------------------------------------------------- higiene
_RX_CPF = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b|\b\d{11}\b")
_RX_SEGREDO = re.compile(r"(?i)\b([A-Z0-9_]*(?:TOKEN|KEY|SENHA|PASSWORD|SECRET|PASS)[A-Z0-9_]*)=(\S+)")


def higienizar(texto: str) -> str:
    """Nada de CPF nem segredo no inventário: CPF/11 dígitos viram ***, VAR_TOKEN=valor vira VAR_TOKEN=***."""
    texto = _RX_CPF.sub("***", texto or "")
    return _RX_SEGREDO.sub(lambda m: f"{m.group(1)}=***", texto)


def slug(texto: str, maximo: int = 60) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", texto.lower()).strip("-")
    return s[:maximo].strip("-") or "job"


# ----------------------------------------------------------------------------------------------- cron
_CAMPO = r"[\d*][\d*/,\-]*|[A-Za-z]{3}(?:[,-][A-Za-z]{3})*"
_RX_CRON = re.compile(rf"^(@reboot|@hourly|@daily|@weekly|@monthly|(?:(?:{_CAMPO})\s+){{4}}(?:{_CAMPO}))\s+(\S.*)$")
_RX_ENV = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def parse_linha_cron(linha: str) -> dict | None:
    """Uma linha de crontab → {agenda, comando, marca} ou None (comentário de texto, env, vazia).

    marca: "ativo" (linha viva), "parada" (comentada pela parada com MARCA_PARADA — estava ativa antes),
    "comentado" (já comentada antes da parada: `# 25 6 * * * cmd`, `#*/5 * * * * cmd`, `# DESLIGADO …: 17 * * * * cmd`).
    """
    s = linha.rstrip("\n")
    if not s.strip():
        return None
    marca = "ativo"
    if s.startswith(MARCA_PARADA):
        s, marca = s[len(MARCA_PARADA):], "parada"
    st = s.strip()
    if st.startswith("#"):
        if marca == "parada":
            return None
        corpo = st.lstrip("#").strip()
        m = _RX_CRON.match(corpo)
        if not m:  # "# DESLIGADO 2026-06-25 (motivo): 17 * * * * cmd" → procura a agenda depois de ': '
            for parte in re.split(r":\s+", corpo)[1:]:
                m = _RX_CRON.match(parte.strip())
                if m:
                    break
        if not m:
            return None
        return {"agenda": m.group(1), "comando": m.group(2).strip(), "marca": "comentado"}
    if _RX_ENV.match(st) and not _RX_CRON.match(st):
        return None
    m = _RX_CRON.match(st)
    if not m:
        return None
    return {"agenda": m.group(1), "comando": m.group(2).strip(), "marca": marca}


def parse_crontab(texto: str) -> list[dict]:
    """Crontab inteiro → linhas de job, com `nota` = último comentário de texto logo acima (contexto do dono)."""
    out, nota = [], ""
    for n, linha in enumerate(texto.splitlines(), 1):
        j = parse_linha_cron(linha)
        if j is None:
            st = linha.strip()
            if st.startswith(MARCA_PARADA):
                st = st[len(MARCA_PARADA):]
            if st.startswith("#") and len(st) > 3:
                nota = st.lstrip("#").strip()
            elif not st:
                nota = ""
            continue
        j["linha"], j["nota"] = n, higienizar(nota)[:220]
        out.append(j)
    return out


_DOW = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}


def _valores(campo: str, lo: int, hi: int) -> set[int]:
    vals: set[int] = set()
    for parte in campo.lower().split(","):
        passo = 1
        if "/" in parte:
            parte, p = parte.split("/")
            passo = int(p)
        if parte in ("*", ""):
            a, b = lo, hi
        elif "-" in parte:
            a, b = (int(_DOW.get(x, x)) for x in parte.split("-"))
        else:
            a = int(_DOW.get(parte, parte))
            b = hi if passo > 1 else a
        vals.update(range(a, b + 1, passo))
    return vals


def execucoes_por_dia(agenda: str, mes: tuple[int, int] = (2026, 11)) -> float:
    """Média de disparos por dia da agenda cron num mês inteiro (cobre semanal e mensal). @reboot = 0."""
    especiais = {"@hourly": "0 * * * *", "@daily": "0 0 * * *", "@weekly": "0 0 * * 0", "@monthly": "0 0 1 * *"}
    if agenda == "@reboot":
        return 0.0
    agenda = especiais.get(agenda, agenda)
    mi, ho, dm, me, ds = agenda.split()
    mins, horas = _valores(mi, 0, 59), _valores(ho, 0, 23)
    dias_m, meses = _valores(dm, 1, 31), _valores(me, 1, 12)
    dias_s = {d % 7 for d in _valores(ds, 0, 7)}
    ano, m = mes
    d0 = dt.date(ano, m, 1)
    dias = [(d0 + dt.timedelta(days=i)) for i in range(40) if (d0 + dt.timedelta(days=i)).month == m]
    total = 0
    for d in dias:
        if d.month not in meses:
            continue
        cron_dow = (d.weekday() + 1) % 7
        ok_m, ok_s = d.day in dias_m, cron_dow in dias_s
        if dm != "*" and ds != "*":
            ok = ok_m or ok_s
        else:
            ok = ok_m and ok_s
        if ok:
            total += len(mins) * len(horas)
    return round(total / len(dias), 3)


# ----------------------------------------------------------------------------------------------- systemd
def parse_units(texto: str, nome_padrao: str | None = None) -> dict[str, dict]:
    """Saída de `systemctl --user cat` (blocos '# /caminho/unit') ou um arquivo .service/.timer → {unit: chaves}.

    Drop-ins ('unit.d/x.conf') somam ao unit principal. Chaves repetidas (ExecStart, OnCalendar…) viram lista.
    """
    units: dict[str, dict] = {}
    atual = nome_padrao
    for linha in texto.splitlines():
        m = re.match(r"^# (/\S+)$", linha.strip())
        if m:
            caminho = m.group(1)
            dropin = re.search(r"/([^/]+)\.d/[^/]+\.conf$", caminho)
            atual = dropin.group(1) if dropin else Path(caminho).name
            units.setdefault(atual, {})
            continue
        if atual is None or not linha.strip() or linha.lstrip().startswith(("#", ";", "[")):
            continue
        if "=" in linha:
            k, v = linha.split("=", 1)
            units.setdefault(atual, {}).setdefault(k.strip(), []).append(v.strip())
    return units


def parse_lista_timers(texto: str) -> list[str]:
    return re.findall(r"(\S+\.timer)\s+\S+\.service", texto)


def parse_lista_servicos(texto: str) -> dict[str, str]:
    """`systemctl --user list-units --type=service` → {unit: 'active running'|'inactive dead'|'failed failed'…}."""
    out = {}
    for linha in texto.splitlines():
        m = re.match(r"^[\s●]*(\S+\.service)\s+(loaded|not-found)\s+(\S+)\s+(\S+)", linha)
        if m:
            out[m.group(1)] = f"{m.group(3)} {m.group(4)}"
    return out


def execucoes_timer(chaves: dict) -> float:
    """Disparos/dia de um .timer (OnCalendar simples, OnUnitActiveSec). 0 = só boot/sob demanda."""
    total = 0.0
    for expr in chaves.get("OnCalendar", []):
        e = expr.replace(" UTC", "").strip()
        if e in ("hourly",):
            total += 24
            continue
        if e == "daily":
            total += 1
            continue
        partes = e.split()
        dias = 7
        if partes and re.match(r"^[A-Za-z]", partes[0]):
            dias = len(_valores(partes[0].replace("..", "-"), 0, 6))
            partes = partes[1:]
        hora = partes[-1] if partes else "00:00"
        hm = hora.split(":")
        h = hm[0]
        mi = hm[1] if len(hm) > 1 else "0"
        nh = len(_valores(h.replace("*", "0-23") if h == "*" else h, 0, 23)) if "/" not in h else len(range(int(h.split("/")[0]), 24, int(h.split("/")[1])))
        nm = len(_valores(mi, 0, 59)) if "/" not in mi else len(range(int(mi.split("/")[0] or 0), 60, int(mi.split("/")[1])))
        total += dias / 7 * nh * nm
    for expr in chaves.get("OnUnitActiveSec", []) + chaves.get("OnUnitInactiveSec", []):
        s = _segundos(expr)
        if s:
            total += 86400 / s
    return round(total, 3)


def _segundos(expr: str) -> float | None:
    m = re.findall(r"(\d+(?:\.\d+)?)\s*(h|min|m|s|ms)?", expr.strip())
    if not m:
        return None
    mult = {"h": 3600, "min": 60, "m": 60, "s": 1, "": 1, "ms": 0.001}
    return sum(float(n) * mult[u or ""] for n, u in m)


# ----------------------------------------------------------------------------------------------- Windows
def parse_schtasks(caminho: Path) -> list[dict]:
    """schtasks /query /fo csv /v (cp850). Só tarefas JFN: JFN-*, JFNAcordado, missao-jfn-*."""
    bruto = caminho.read_bytes()
    texto = bruto.decode("cp850", errors="replace")
    linhas = list(csv.reader(io.StringIO(texto)))
    if not linhas:
        return []
    cab = linhas[0]
    vistos: dict[str, dict] = {}
    for r in linhas[1:]:
        if not r or r[0] == cab[0] or len(r) < 20:
            continue
        nome = r[1].lstrip("\\")
        if not re.match(r"(?i)^(jfn|missao-jfn)", nome):
            continue
        t = vistos.setdefault(nome, {"nome": nome, "status": r[3], "habilitada": r[11], "comando": r[8],
                                    "ultima": r[5], "resultado": r[6], "agendas": []})
        ag = " ".join(x for x in (r[18].strip(), r[19].strip()) if x and x != "N/A")
        if ag and ag not in t["agendas"]:
            t["agendas"].append(ag)
    return list(vistos.values())


# ----------------------------------------------------------------------------------------------- comando
_WRAPPERS = re.compile(r"^(nice|ionice|timeout|flock|env|xvfb-run|exec|sh|bash|/bin/bash|/usr/bin/bash|cd)$")


def ponto_de_entrada(comando: str) -> str:
    """O que o comando realmente roda (módulo python ou script), sem cd/env/nice/timeout/flock/pesado.sh/redireção.

    'cd X && PYTHONPATH=. timeout 600 nice -n 10 .venv/bin/python -m tools.x --a 1 >> log' → 'py:tools.x'.
    """
    c = re.sub(r"\s(?:\d?>>?|2>&1|>)\s*\S+", " ", comando)
    m = re.search(r"python[\d.]*\s+(?:-u\s+|-I\s+)*-m\s+([\w.]+)(?:\s+([a-z][\w-]*)\b)?", c)
    if m:  # subcomando posicional (ex.: `-m tools.vm2_conferencia amostra`) distingue jobs do mesmo módulo
        return "py:" + m.group(1) + (f" {m.group(2)}" if m.group(2) else "")
    m = re.search(r"python[\d.]*\s+(?:-u\s+)*(\S+\.py)(?:\s+([a-z][\w-]*)\b)?", c)
    if m:
        return "py:" + _norm_caminho(m.group(1)) + (f" {m.group(2)}" if m.group(2) else "")
    m = re.search(r"python[\d.]*\s+-c\s", c)
    if m:
        alvo = re.search(r"from\s+([\w.]+)\s+import|import\s+([\w.]+)", c)
        return "py-c:" + ((alvo.group(1) or alvo.group(2)) if alvo else "inline")
    m = re.search(r"(\S+\.(?:sh|ps1|cmd))\b(?:\s+([a-z][\w-]*)\b)?", c)
    if m:
        sub = f" {m.group(2)}" if m.group(2) else ""
        return "sh:" + _norm_caminho(m.group(1)) + sub
    toks = [t for t in re.split(r"\s+|&&|;", c) if t and not _RX_ENV.match(t)]
    for t in toks:
        if not _WRAPPERS.match(t) and not t.startswith("-") and not t.isdigit():
            return "bin:" + Path(t).name
    return "bin:?"


def _norm_caminho(p: str) -> str:
    p = p.replace("%h/", "").replace("%USERPROFILE%\\", "").replace("\\", "/")
    p = re.sub(r"^.*?/JFN(?:-worker)?/", "", p)
    p = re.sub(r"^\./", "", p)
    return p


def chave_exata(comando: str) -> str:
    """Comando normalizado com argumentos (para duplicação EXATA): sem wrappers, logs, caminhos absolutos."""
    c = re.sub(r"\s(?:\d?>>?|2>&1|>)\s*\S+", " ", comando)
    c = re.sub(r"(?:/home/ubuntu|%h)/JFN/", "", c)
    c = re.sub(r"\.venv/bin/python\S*|\{py\}|python3?", "python", c)
    c = re.sub(r"\b(nice|ionice)\s+(-n\s*\d+|-c\s*\d+|-n\d+|-c\d)\s*", "", c)
    c = re.sub(r"\btimeout\s+\d+\s*", "", c)
    c = re.sub(r"\bflock\s+(-[nw]\s*\d*\s*)?\S+\s*", "", c)
    c = re.sub(r"\b[A-Z_]+=\S+\s*", "", c)
    c = re.sub(r"^.*?&&\s*", "", c)
    c = re.sub(r"tools/pesado\.sh\s+\S+\s+\d+\s*", "", c)
    c = re.sub(r"^(env|/bin/bash|bash)\s+", "", c.strip())
    return re.sub(r"\s+", " ", c).strip()


def _arquivo_do_ponto(ponto: str) -> Path | None:
    tipo, _, alvo = ponto.partition(":")
    alvo = alvo.split(" ")[0]
    if tipo == "py":
        if alvo.endswith(".py"):
            p = RAIZ / alvo
        else:
            p = RAIZ / (alvo.replace(".", "/") + ".py")
            if not p.exists():
                p = RAIZ / alvo.replace(".", "/") / "__main__.py"
        return p if p.exists() else None
    if tipo == "sh":
        for cand in (RAIZ / alvo, RAIZ / "deploy/itcampo" / Path(alvo).name, *(RAIZ / "deploy").rglob(Path(alvo).name)):
            if cand.exists():
                return cand
    return None


def _texto_script(ponto: str, profundidade: int = 1) -> str:
    """Texto do script chamado (+ os scripts que ele chama, 1 nível) — matéria-prima da inferência de recursos."""
    p = _arquivo_do_ponto(ponto)
    if not p:
        return ""
    try:
        txt = p.read_text(errors="replace")[:200_000]
    except OSError:
        return ""
    if profundidade and p.suffix in (".sh", ".ps1"):
        for sub in set(re.findall(r"(?:-m\s+)([\w.]+)|(tools/[\w/]+\.py)", txt)):
            alvo = sub[0] or sub[1]
            txt += "\n" + _texto_script("py:" + alvo, 0)[:60_000]
    return txt


_RECURSOS = [
    ("gpu", r"vllm|surya|JFN-OCR-GPU|jfn_ocr_gpu|ocr_gpu\.sh"),
    ("navegador", r"playwright|nodriver|selenium|camoufox|xvfb-run|chromium|browser\.lock|browser_lock|cdp_url|"
                  r"sei_sweep|sweep_sei|sei_integra|itcampo_sei_paralelo|sei_arquivar|vm2_integras|vm2_sweep_geral|sei_busca|varredura_sei|sei_bombeiros|siafe_runner|"
                  r"siafe_documento|siafe_drenar|itkava|sei-pcrj|sei_pcrj|verificacao_humana|mediafire_sessao"),
    ("llm", r"anthropic|claude_motor|claude -p|JFN_CLAUDE|gemini|openrouter|groq|cerebras|compliance_agent\.llm|"
            r"from compliance_agent\.llm|cascata|haiku|conferencia_opus|--opus"),
    ("pesado", r"tools/pesado\.sh|duckdb|tesseract|rapidocr|VACUUM|\bpeso:\s*pesado|ocr_contratos|sei_compactar|"
               r"gitnexus analyze|pandas"),
]


_RECURSOS_SCRIPT = [  # no TEXTO do script só sinal forte (import/uso), não menção em comentário
    ("gpu", r"vllm serve|^\s*import torch|torch\.cuda"),
    ("navegador", r"^\s*(?:from|import)\s+(?:playwright|nodriver|selenium|camoufox)|browser_lock\(|xvfb-run|"
                  r"^\s*from compliance_agent\.sei(?:\.\w+)* import .*(?:sessao|Sessao|navegador|browser)"),
    ("llm", r"^\s*(?:from|import)\s+(?:anthropic|compliance_agent\.llm)|claude -p|\$JFN_CLAUDE_BIN|"
            r"^\s*from compliance_agent(?:\.\w+)* import .*(?:free_llm|cascata|claude_motor)"),
    ("pesado", r"^\s*import duckdb|tesseract|rapidocr|tools/pesado\.sh"),
]


def inferir_recursos(comando: str, texto_script: str = "", timeout_s: int | None = None,
                     peso: str | None = None) -> list[str]:
    rec = [nome for nome, rx in _RECURSOS if re.search(rx, comando, re.I)]
    for nome, rx in _RECURSOS_SCRIPT:
        if nome not in rec and re.search(rx, texto_script, re.M):
            rec.append(nome)
    rec.sort(key=[n for n, _ in _RECURSOS].index)
    if peso == "pesado" or (timeout_s and timeout_s >= 3600):
        if "pesado" not in rec:
            rec.append("pesado")
    return rec or ["leve"]


def extrair_timeout(comando: str) -> int | None:
    vals = [int(x) for x in re.findall(r"\btimeout\s+(\d+)", comando)]
    m = re.search(r"pesado\.sh\s+\S+\s+(\d+)", comando)
    return max(vals) if vals else None if not m else None


def extrair_orcamento(comando: str) -> int | None:
    for rx, mult in ((r"--segundos\s+(\d+)", 1), (r"--orcamento(?:-s)?\s+(\d+)", 1), (r"--max-min\s+(\d+)", 60),
                     (r"SWEEP_MAX_SECONDS=(\d+)", 1)):
        m = re.search(rx, comando)
        if m:
            return int(m.group(1)) * mult
    return None


# ----------------------------------------------------------------------------------------------- estágio/lente
# (regex sobre comando+nome, destino). A 1ª que casa vence — ordem importa (específico antes do genérico).
REGRAS_ESTAGIO: list[tuple[str, str]] = [
    (r"polimonitor|whatsapp|hermes[-_]update|hermes_metacognicao|jfn-metacognicao|hermes_rag|atena|khoj|massare|"
     r"brain-index|brain-api|hermes-gateway|launchpadlib|openlist|syncthing", "fora_do_jfn"),
    (r"missao-jfn|chrome-2j|chrome-debug-it", "aposentar"),
    (r"jfn-intel-cache", "E1+E10+E15"),
    (r"coletar_siconfi_rj", "E1+E16"),
    (r"compliance_agent\.propagacao\b|sweeps_serial|tools\.itcampo_vigia\b|claude_no_itcampo", "aposentar"),
    (r"server\.py|wal_keeper|chrome-jfn|painel-tunnel|JFNAcordado|jfn_acordado|cua-driver", "infra"),
    (r"browser\.lock", "aposentar"),
    (r"guardiao|painel_vigia|vm_guard|jfn-ronda|ronda\.py|keepalive|handoff-watcher|pipelines_slo|sentinela|"
     r"automelhoria_geral|ritmo_assinatura|claude_motor --canario|yoda_autoauditoria|siafe_ingest_cobertura|"
     r"qualidade', 'sensores|qualidade sensores|cerebro_bateria|compliance_agent\.certeza|certeza', 'ciclo|"
     r"automelhoria_executor|jfn-suite|run_suite|autoauditoria", "E18"),
    (r"manutencao|backup_|logrotate|checkpoint_wal|zelador|graphify-out|git push -q origin|nuvens-manter|"
     r"gitnexus|GRAPH_REPORT|verificacao_humana --manter|mediafire_sessao|jfn-logrotate", "E17"),
    (r"sei_arquivo_frio|sei_compactar|arquivar_cache_lane|arquivar_integra_lane|hd_migracao", "E7"),
    (r"sei_ocr_ia_conferir|ocr_confirmacao", "E6"),
    (r"ocr_gpu|ocr_contratos_imagem|itcampo_ocr_cpu|ocr[-_]reserva|pool_nativo|JFN-Nativo|vllm|tesseract", "E5"),
    (r"sei_arquivar\.py", "E4"),
    (r"sei_integra|integra-fila|integras-vm2|run_integras|bombeiros_integra|sweep_integra_contratos", "E3"),
    (r"itcampo_sei_paralelo|JFN-SEI-Paralelo", "E2+E3"),
    (r"sei-pcrj\.service|sei-pcrj\.timer|sei_pcrj_busca|run_sweep\.sh", "E2+E3"),
    (r"sweep_sei|sei_sweep|varredura_sei|sei_busca|sei-noturno|sweep-geral-vm2|vm2_sweep_geral|sei-pcrj-consulta|"
     r"pcrj_sei_busca_termos|sei_bombeiros_sweep|jfn-sei-sweep", "E2"),
    (r"conferencia_opus|vm2_conferencia|triagem_alertas|amostra-vm2|qualidade', 'cobertura|juiz", "E12"),
    (r"autoaprimoramento|cerebro_consolidacao|bancada", "E13"),
    (r"digest_diario|relatorio_|montar_|dossie_couto|triagem_amarelos|gerar_pecas_comissao|pulos_do_gato|"
     r"bombeiros_alerta", "E16"),
    (r"sweep_360|processo_360|dossie_mestre|cerebro_sync|vault_retratos|cerebro_ponte", "E14"),
    (r"prewarm_painel|cruzamentos_intel cache|lentes_materializar|refresh_favorecido_resumo|territorio|"
     r"tipo: cache|cache-painel|sei_integra_vm2 precalcular", "E15"),
    (r"fila_analise_sei\.sh ficha|leitura_integral|propostas_sei|obra_fase_sei|leitura_campos|"
     r"fila_analise_sei\.sh sigilo", "E8"),
    (r"pericia_contabil|vinculo_ob|ob_reemitida", "E9"),
    (r"fila_analise_sei\.sh lex|pericia|lex_|nucleo\.ciclo|indeterminados|bombeiros_supervisor", "E11"),
    (r"sweep_beneficios|beneficios_sweep", "E1+E10"),
    (r"detectores\.|governo_couto_regras|sweep_fiscalizacao_247|sweep_avaliacao_total|cruzador|sweep_dados|"
     r"sweep_sede|fachada|resolver_duplicidade|verificar_precos|fracionamento|padroes|iss_retido|cge_confronto|"
     r"conluio|cruzamentos_intel|emergencia_incumbente|ocp_redflags|pcrj_saude|acervo_regras|fantasma_servidor|"
     r"jfn-analise|jfn-sweeps|sweeps\.service|sei_fila_por_dinheiro", "E10"),
    (r"siafe|folha_orquestrador|socios_dump|tcerj|doerj|lista_suja|siga_|fserj_site_docs|noticias_orgaos|"
     r"pcrj_sei_crc|contasrio|doweb|pcrj_sei_ingest|sei_rj_catalogo|dadosabertos|cge_paineis|siconfi|"
     r"garantir_obs|sweep_atas|pncp|ceis|sancoes|fisc_coletar|descobre-doe|descobre_doe", "E1"),
]

REGRAS_LENTE: list[tuple[str, str]] = [
    (r"bombeir|funesbom|cbmerj", "bombeiros"), (r"mgs|iterj", "mgs_iterj"), (r"beneficio", "beneficios"),
    (r"fserj", "fserj"), (r"couto", "couto"), (r"pcrj_saude", "pcrj_saude"), (r"ajovem", "ajovem"),
    (r"emenda|fisc_coletar|fiscalizacao_247", "emendas"), (r"obra", "obras"),
    (r"pcrj|contasrio|doweb|prefeitura|sei-pcrj|descobre-doe|leitura_campos", "pcrj"),
]


def classificar(texto: str, texto_lente: str | None = None) -> tuple[str, str | None]:
    estagio = next((dest for rx, dest in REGRAS_ESTAGIO if re.search(rx, texto, re.I)), "SEM_DESTINO")
    tl = re.sub(r"(?i)(/home/|users[\\/])iterj\b", r"\1<usuario>", texto if texto_lente is None else texto_lente)
    tl = re.sub(r"--k-bombeiros\s+\d+", "", tl)  # cota de bombeiros dentro da fila geral não faz o job ser da lente
    lente = next((nome for rx, nome in REGRAS_LENTE if re.search(rx, tl, re.I)), None)
    return estagio, lente


def executa_em(comando: str, texto_script: str) -> str | None:
    alvo = comando + "\n" + texto_script[:30_000]
    if re.search(r"claude_no_itcampo|_no_itcampo\.sh|itcampo_ocr_cpu|ssh\s+(?:-\S+\s+)*(?:\S+@)?it-?campo", alvo):
        return "itcampo"
    if re.search(r"ssh\s+(?:-\S+\s+\S*\s+)*vm2(?:-ts)?\b|--ler-em', 'vm2|--ler-em vm2", alvo):
        return "vm2"
    return None


# ----------------------------------------------------------------------------------------------- montagem
def _job(**kw) -> dict:
    kw["comando"] = higienizar(kw.get("comando") or "")
    texto = kw.pop("_texto", "")
    ponto = ponto_de_entrada(kw["comando"]) if kw["comando"] else "bin:?"
    tscript = _texto_script(ponto)
    base_cls = " ".join(filter(None, [kw.get("_nome_cls", ""), kw["comando"], texto]))
    kw.pop("_nome_cls", None)
    est, lente = classificar(base_cls, kw.pop("_texto_lente", None))
    kw.setdefault("estagio_destino", est)
    kw.setdefault("lente", lente)
    kw.setdefault("timeout_s", extrair_timeout(kw["comando"]))
    kw.setdefault("orcamento_s", extrair_orcamento(kw["comando"]))
    kw["recursos"] = kw.get("recursos") or inferir_recursos(kw["comando"], tscript, kw.get("timeout_s"), kw.pop("_peso", None))
    kw.setdefault("executa_em", executa_em(kw["comando"], tscript))
    kw["ponto_entrada"] = ponto
    kw["_pontos"] = sorted({ponto_de_entrada(p) for p in kw["comando"].split(" ; ") if p.strip()} | {ponto})
    kw["_chave"] = chave_exata(kw["comando"])
    return kw


def jobs_crontab(texto: str, dono: str = "vm1") -> list[dict]:
    out = []
    for j in parse_crontab(texto):
        ponto = ponto_de_entrada(j["comando"])
        estado = {"ativo": "ativo", "parada": "ativo", "comentado": "comentado"}[j["marca"]]
        out.append(_job(id=f"{dono}-cron-{slug(ponto.split(':', 1)[-1].split('/')[-1])}",
                        dono=dono, gatilho={"tipo": "boot" if j["agenda"] == "@reboot" else "cron", "expr": j["agenda"]},
                        comando=j["comando"], estado_pre_parada=estado,
                        execucoes_dia=execucoes_por_dia(j["agenda"]) if estado != "comentado" else 0.0,
                        origem=f"crontab:{j['linha']}", nota=j["nota"] or None,
                        comentada_pela_parada=j["marca"] == "parada"))
    return out


def jobs_systemd(dono: str, defs: dict[str, dict], timers_ativos: list[str], servicos: dict[str, str],
                 parados_pela_parada: set[str]) -> list[dict]:
    out = []
    timers = {u for u in defs if u.endswith(".timer")} | set(timers_ativos)
    cobertos = set()
    for t in sorted(timers):
        svc = t[:-6] + ".service"
        cobertos.add(svc)
        td, sd = defs.get(t, {}), defs.get(svc, {})
        cmds = sd.get("ExecStartPre", []) + sd.get("ExecStart", []) + sd.get("ExecStartPost", [])
        comando = " ; ".join(cmds) or f"(sem definição na fotografia de {svc})"
        nome = t[:-6]
        ativo = t in timers_ativos or nome in parados_pela_parada
        to = sd.get("TimeoutStartSec") or sd.get("RuntimeMaxSec")
        expr = "; ".join(td.get("OnCalendar", []) + [f"OnUnitActiveSec={x}" for x in td.get("OnUnitActiveSec", [])]
                         + [f"OnBootSec={x}" for x in td.get("OnBootSec", [])]) or "(timer sem definição na fotografia)"
        desc = (sd.get("Description") or [""])[0]
        out.append(_job(id=f"{dono}-timer-{slug(nome)}", dono=dono, gatilho={"tipo": "timer", "expr": expr},
                        comando=comando, estado_pre_parada="ativo" if ativo else "parado",
                        execucoes_dia=execucoes_timer(td) if ativo else 0.0,
                        timeout_s=int(_segundos(to[0])) if to and _segundos(to[0]) else None,
                        origem=f"systemd:{t}", nota=desc or None, _nome_cls=f"{nome} {svc} {desc}",
                        comentada_pela_parada=nome in parados_pela_parada))
    for svc, estado in sorted(servicos.items()):
        if svc in cobertos or svc.startswith(("notificar-falha@", "dbus", "dirmngr", "gpg", "gcr", "gnome-keyring",
                                              "gvfs", "keyboxd", "pk-debconf", "pulseaudio", "snapd", "xdg-",
                                              "systemd-", "launchpadlib")):
            continue
        sd = defs.get(svc, {})
        residente = "running" in estado or "Restart" in sd or svc[:-8] in parados_pela_parada
        if not residente and "failed" not in estado:
            continue
        cmds = sd.get("ExecStart", [])
        desc = (sd.get("Description") or [""])[0]
        out.append(_job(id=f"{dono}-svc-{slug(svc[:-8])}", dono=dono, gatilho={"tipo": "servico", "expr": "residente"},
                        comando=" ; ".join(cmds) or f"(serviço {svc}; sem definição na fotografia)",
                        estado_pre_parada="ativo" if ("running" in estado or svc[:-8] in parados_pela_parada) else "parado",
                        execucoes_dia=None, origem=f"systemd:{svc} ({estado})", nota=desc or None,
                        _nome_cls=f"{svc} {desc}", comentada_pela_parada=svc[:-8] in parados_pela_parada))
    return out


_PS1_FILHOS = {  # o que cada laço do it-campo realmente roda (deploy/itcampo/*.ps1 e a foto do WSL)
    "JFN-SEI-Paralelo": "wsl -- python -m tools.itcampo_sei_paralelo rodar",
    "JFN-OCR-GPU": "wsl -- bash ocr_gpu.sh (vllm serve surya-ocr + ocr_gpu_worker.py)",
    "JFN-Nativo": "C:/JFN-Nativo/venv python pool_nativo.py (sei_ocr_reserva rodar --paralelo, nó itcampo-win-K)",
    "JFNAcordado": "powershell jfn_acordado.ps1 (anti-suspensão)",
}


def jobs_windows(tarefas: list[dict]) -> list[dict]:
    out = []
    for t in tarefas:
        laco = "-NoExit" in t["comando"]
        estado = "ativo" if (t["habilitada"].startswith("Habilitado") and not t["nome"].startswith("missao")) else "parado"
        cmd = t["comando"] + (f"  ⇒ {_PS1_FILHOS[t['nome']]}" if t["nome"] in _PS1_FILHOS else "")
        nota = f"última execução {t['ultima']} → resultado {t['resultado']}"
        if t["resultado"] == "-2147023829":
            nota += " (0x8007042B: o processo saiu — laço caído ou sessão encerrada)"
        out.append(_job(id=f"itcampo-task-{slug(t['nome'])}", dono="itcampo",
                        gatilho={"tipo": "logon" if any("logon" in a.lower() for a in t["agendas"]) else "agenda",
                                 "expr": "; ".join(t["agendas"]) + (" (laço contínuo -NoExit)" if laco else "")},
                        comando=cmd, estado_pre_parada=estado, execucoes_dia=None if laco else 0.0,
                        origem=f"schtasks:{t['nome']}", nota=nota, _nome_cls=t["nome"]))
    return out


def jobs_wsl(texto_ps: str) -> list[dict]:
    """Filhos vivos dos laços do it-campo na foto do WSL (o trabalho que os laços faziam), um por script."""
    vistos: dict[str, dict] = {}
    for linha in texto_ps.splitlines()[1:]:
        cmd = linha.split(None, 10)[-1] if len(linha.split(None, 10)) == 11 else ""
        m = re.search(r"(tools/[\w/]+\.py|-m\s+tools\.[\w.]+|vllm serve \S+|\btesseract\b)", cmd)
        if not m:
            continue
        chave = m.group(1).replace("-m ", "")
        if chave in vistos:
            vistos[chave]["instancias"] += 1
            continue
        pai = "JFN-OCR-GPU" if re.search(r"vllm|surya|gpu", cmd) else "JFN-SEI-Paralelo"
        vistos[chave] = {"cmd": re.sub(r"\b\d{6}/\d{6}/\d{4}\b", "<processo>", cmd)[:240], "pai": pai, "instancias": 1}
    out = []
    for chave, v in vistos.items():
        out.append(_job(id=f"itcampo-filho-{slug(Path(chave).stem if '/' in chave else chave)}", dono="itcampo",
                        gatilho={"tipo": "filho", "expr": f"laço {v['pai']}"}, comando=v["cmd"],
                        estado_pre_parada="ativo", execucoes_dia=None,
                        origem=f"wsl.txt ({v['instancias']} instância(s) na foto)", nota=None))
    return out


def jobs_derivados(cfg: dict) -> list[dict]:
    out = []
    for did, d in (cfg.get("derivados") or {}).items():
        argv = d.get("comando")
        cache = d.get("tipo") == "cache"
        comando = " ".join("python" if str(a) == "{py}" else str(a) for a in argv) if argv else f"(cache do painel no jfn.service: {', '.join(d.get('prefixos') or [])})"
        expr = (f"depende={','.join(d.get('depende') or [])}; debounce={d.get('debounce_s', 120)}s; "
                f"intervalo_min={d.get('intervalo_min_s', 0)}s")
        out.append(_job(id=f"vm1-deriv-{slug(did)}", dono="vm1", gatilho={"tipo": "evento", "expr": expr},
                        comando=comando, estado_pre_parada="ativo", execucoes_dia=None,
                        timeout_s=d.get("timeout_s"), origem=f"propagacao.yaml:derivados.{did}",
                        nota=higienizar(str(d.get("antes") or ""))[:220] or None,
                        _nome_cls=f"{did} {'tipo: cache' if cache else ''}", _peso=d.get("peso"),
                        _texto_lente=f"{did} {comando if not cache else ''}"))
        out[-1]["derivado"] = did
    return out


def marcar_duplicados(jobs: list[dict]) -> None:
    """Mesmo ponto de entrada em mais de um gatilho → duplicado_de = id do 1º (derivado e timer antes do cron).

    duplicacao: exato (mesmo comando normalizado, com argumentos) | mesmo_script (mesmo script, argumentos outros).
    Cron ativo cujo comando é o de um derivado da propagação = "rede" (a rede de segurança que a propagação manteve).
    """
    ordem = {"evento": 0, "timer": 1, "servico": 2, "logon": 3, "filho": 4, "cron": 5, "boot": 6, "agenda": 7}
    por_ponto: dict[str, list[dict]] = defaultdict(list)
    for j in jobs:
        if j["comando"].startswith("("):
            continue
        for p in j.get("_pontos") or [j["ponto_entrada"]]:
            if p in ("bin:?", "py-c:inline") or p.startswith("bin:("):
                continue
            # binário de sistema (logrotate, rsync…) em máquinas diferentes não é duplicação
            por_ponto[f"{j['dono']}|{p}" if p.startswith("bin:") else p].append(j)
    for grupo in por_ponto.values():
        if len(grupo) < 2:
            continue
        grupo.sort(key=lambda j: (j["estado_pre_parada"] not in ("ativo", "rede"), ordem.get(j["gatilho"]["tipo"], 9), j["id"]))
        primeiro = grupo[0]
        for j in grupo[1:]:
            if j.get("duplicado_de") or j is primeiro:
                continue
            if j["ponto_entrada"].startswith("bin:") and j["_chave"] != primeiro["_chave"]:
                continue  # mesmo binário (uvicorn, logrotate) com alvo outro não é o mesmo job
            j["duplicado_de"] = primeiro["id"]
            j["duplicacao"] = "exato" if j["_chave"] == primeiro["_chave"] else "mesmo_script"
            if (primeiro["gatilho"]["tipo"] == "evento" and j["gatilho"]["tipo"] == "cron"
                    and j["estado_pre_parada"] == "ativo" and j["duplicacao"] == "exato"):
                j["estado_pre_parada"] = "rede"


def ids_unicos(jobs: list[dict]) -> None:
    vistos: Counter = Counter()
    for j in jobs:
        vistos[j["id"]] += 1
        if vistos[j["id"]] > 1:
            j["id"] = f"{j['id']}-{vistos[j['id']]}"


def ler(caminho: Path) -> str:
    try:
        return caminho.read_text(errors="replace")
    except OSError:
        return ""


def defs_systemd_vm1() -> dict[str, dict]:
    defs: dict[str, dict] = {}
    for f in sorted((RAIZ / "deploy/systemd").glob("*.[st][ei]*")):
        if f.suffix in (".service", ".timer"):
            defs[f.name] = parse_units(ler(f), f.name)[f.name] if parse_units(ler(f), f.name) else {}
    defs.update(parse_units(ler(BACKUP / "vm1/units.txt")))
    return defs


def defs_systemd_vm1_local(units: list[str]) -> dict[str, dict]:
    """`systemctl --user cat` LOCAL (só leitura) para o que a fotografia não trouxe."""
    if not units:
        return {}
    try:
        r = subprocess.run(["systemctl", "--user", "cat", *units], capture_output=True, text=True, timeout=20)
        return parse_units(r.stdout)
    except (OSError, subprocess.SubprocessError):
        return {}


def ssh_vm2(cmd: str, timeout: int = 40) -> str:
    try:
        r = subprocess.run(["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes", "vm2-ts", cmd],
                           capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def defs_systemd_vm2(usar_ssh: bool) -> tuple[dict[str, dict], str]:
    defs: dict[str, dict] = {}
    for f in sorted((RAIZ / "deploy/vm2").glob("*")):
        if f.suffix in (".service", ".timer"):
            defs[f.name] = parse_units(ler(f), f.name).get(f.name, {})
    fonte = "deploy/vm2"
    if usar_ssh:
        out = ssh_vm2("cd ~/.config/systemd/user && ls | grep -E '\\.(service|timer)$' | grep -v '^massare' | "
                      "xargs systemctl --user cat 2>/dev/null")
        if out.strip():
            defs.update(parse_units(out))
            fonte = "ssh vm2-ts systemctl --user cat (24/11) + deploy/vm2"
    return defs, fonte


def montar(usar_ssh: bool = False) -> tuple[list[dict], dict]:
    meta: dict = {"fontes": []}
    jobs: list[dict] = []
    # VM-1 crontab: a fotografia pré-parada é a verdade do "o que rodava"; o crontab vivo confere a marca.
    cron_pre = ler(BACKUP / "vm1/crontab_pre_parada.txt")
    jobs += jobs_crontab(cron_pre, "vm1")
    meta["fontes"].append("vm1/crontab_pre_parada.txt")
    try:
        vivo = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        vivo = ""
    marcadas = {(j["agenda"], j["comando"]) for j in parse_crontab(vivo) if j["marca"] == "parada"}
    for j in jobs:
        if j["gatilho"]["tipo"] in ("cron", "boot"):
            j["comentada_pela_parada"] = (j["gatilho"]["expr"], j.pop("_cmd_bruto", j["comando"])) in marcadas \
                or any(c == j["comando"] for _, c in marcadas)
    meta["crontab_vivo_marcadas"] = len(marcadas)
    # VM-1 systemd
    defs1 = defs_systemd_vm1()
    timers1 = parse_lista_timers(ler(BACKUP / "vm1/timers.txt"))
    serv1 = parse_lista_servicos(ler(BACKUP / "vm1/services.txt"))
    faltam = [u for u in set(timers1) | {t[:-6] + ".service" for t in timers1} | set(serv1) if u not in defs1]
    defs1.update(defs_systemd_vm1_local(sorted(faltam)))
    parados1 = set(ler(BACKUP / "vm1/timers_parados.txt").split()) | set(ler(BACKUP / "vm1/services_parados.txt").split())
    # deploy/systemd traz units antigos que não existem mais na VM-1: só entram se a fotografia/local os tem.
    vivos1 = set(timers1) | set(serv1) | {u for u in parse_units(ler(BACKUP / "vm1/units.txt"))}
    defs1_f = {u: v for u, v in defs1.items() if u in vivos1 or u[:-6] + ".timer" in vivos1
               or (u.endswith(".service") and u[:-8] + ".timer" in vivos1)}
    jobs += jobs_systemd("vm1", defs1_f, timers1, serv1, parados1)
    meta["fontes"] += ["vm1/units.txt", "vm1/timers.txt", "vm1/services.txt", "vm1/timers_parados.txt",
                       "systemctl --user cat (local, só leitura) p/ units fora da foto"]
    # VM-2 systemd
    est2 = ler(BACKUP / "vm2/estado.txt")
    secs = dict(re.findall(r"===(\w+)\n(.*?)(?=\n===|\Z)", est2, re.S))
    timers2 = parse_lista_timers(secs.get("TIMERS", ""))
    serv2 = parse_lista_servicos(secs.get("SERV", ""))
    defs2, fonte2 = defs_systemd_vm2(usar_ssh)
    vivos2 = set(timers2) | set(serv2)
    defs2_f = {u: v for u, v in defs2.items() if u in vivos2 or (u.endswith(".service") and u[:-8] + ".timer" in vivos2)
               or u.startswith(("jfn-", "sei-", "descobre-", "zelador-"))}
    jobs += jobs_systemd("vm2", defs2_f, timers2, serv2, set())
    meta["fontes"] += ["vm2/estado.txt", fonte2]
    meta["vm2_sem_crontab"] = True
    # it-campo
    jobs += jobs_windows(parse_schtasks(BACKUP / "itcampo/schtasks.csv"))
    jobs += jobs_wsl(ler(BACKUP / "itcampo/wsl.txt"))
    meta["fontes"] += ["itcampo/schtasks.csv", "itcampo/wsl.txt", "deploy/itcampo/*.ps1"]
    # derivados
    cfg = yaml.safe_load(ler(RAIZ / "config/propagacao.yaml")) or {}
    jobs += jobs_derivados(cfg)
    meta["fontes"].append("config/propagacao.yaml")
    ids_unicos(jobs)
    marcar_duplicados(jobs)
    return jobs, meta


# ----------------------------------------------------------------------------------------------- duração (O1.6)
def _p50(xs: list[float]) -> float | None:
    xs = [x for x in xs if x is not None and x >= 0]
    return round(statistics.median(xs), 1) if xs else None


def duracoes_derivados(db: Path) -> dict[str, tuple[float, int, float]]:
    """{derivado: (p50_s, n, execucoes_por_dia)} da tabela execucao do propagacao.db (só leitura)."""
    out = {}
    try:
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
        rows = c.execute("SELECT derivado, inicio, fim FROM execucao WHERE fim IS NOT NULL AND inicio IS NOT NULL").fetchall()
    except sqlite3.Error:
        return out
    por: dict[str, list] = defaultdict(list)
    for d, i, f in rows:
        por[d].append((i, f))
    for d, xs in por.items():
        xs.sort()
        dias = max((xs[-1][0] - xs[0][0]) / 86400, 1.0)
        out[d] = (_p50([f - i for i, f in xs[-200:]]), len(xs), round(len(xs) / dias, 2))
    return out


def duracoes_journal(texto: str) -> dict[str, tuple[float, int]]:
    """journalctl -o short-unix: pares 'Starting X.service' → 'Finished|Failed|Deactivated X' → {unit: (p50, n)}."""
    abertos: dict[str, float] = {}
    por: dict[str, list[float]] = defaultdict(list)
    for linha in texto.splitlines():
        m = re.match(r"^(\d+\.\d+)\s+\S+\s+systemd\[\d+\]:\s+(Starting|Finished|Failed to start)\s+(\S+\.service)", linha)
        m2 = re.match(r"^(\d+\.\d+)\s+\S+\s+systemd\[\d+\]:\s+(\S+\.service): (Failed with result|Deactivated successfully)", linha)
        if m:
            ts, ev, u = float(m.group(1)), m.group(2), m.group(3)
            if ev == "Starting":
                abertos[u] = ts
            elif u in abertos:
                por[u].append(ts - abertos.pop(u))
        elif m2:
            ts, u = float(m2.group(1)), m2.group(2)
            if u in abertos:
                por[u].append(ts - abertos.pop(u))
    return {u: (_p50(v), len(v)) for u, v in por.items()}


def duracoes_pesado(texto: str) -> dict[str, tuple[float, int]]:
    """data/pesado_vm1.log: 'início (esperou Es)' … 'fim rc=R (Ts)' → duração = T − E (sem a espera)."""
    espera: dict[str, float] = {}
    por: dict[str, list[float]] = defaultdict(list)
    for linha in texto.splitlines():
        m = re.search(r"\[pesado:(\S+)\] início \(esperou (\d+)s\)", linha)
        if m:
            espera[m.group(1)] = float(m.group(2))
            continue
        m = re.search(r"\[pesado:(\S+)\] fim rc=\S+ \((\d+)s\)", linha)
        if m:
            por[m.group(1)].append(float(m.group(2)) - espera.pop(m.group(1), 0.0))
    return {k: (_p50(v), len(v)) for k, v in por.items()}


_RX_TS = re.compile(r"(20\d\d-\d\d-\d\d)[ T](\d\d:\d\d:\d\d)")


def duracao_por_log(texto: str, periodo_s: float) -> tuple[float | None, int]:
    """Heurística: linhas com data/hora agrupadas em rodadas (intervalo > min(periodo/2, 1 h) separa rodadas);
    duração da rodada = última − primeira linha. Só vale com ≥ 3 rodadas de ≥ 2 linhas (MEDIDO-LOG, ±)."""
    ts = []
    for m in _RX_TS.finditer(texto):
        try:
            ts.append(dt.datetime.fromisoformat(f"{m.group(1)} {m.group(2)}").timestamp())
        except ValueError:
            pass
    if len(ts) < 6:
        return None, 0
    ts.sort()
    corte = max(90.0, min(periodo_s / 2, 3600.0))
    rodadas, ini, ult, n = [], ts[0], ts[0], 1
    for t in ts[1:]:
        if t - ult > corte:
            if n >= 2:
                rodadas.append(ult - ini)
            ini, n = t, 0
        ult, n = t, n + 1
    if n >= 2:
        rodadas.append(ult - ini)
    rodadas = rodadas[-60:]
    return (_p50(rodadas), len(rodadas)) if len(rodadas) >= 3 else (None, len(rodadas))


def _log_do_comando(comando: str) -> Path | None:
    m = re.search(r">>\s*(\S+\.log)", comando)
    if not m:
        return None
    p = m.group(1)
    p = p if p.startswith("/") else str(RAIZ / p)
    return Path(p) if Path(p).exists() else None


def _tail(p: Path, n_bytes: int = 400_000) -> str:
    with open(p, "rb") as f:
        f.seek(0, 2)
        tam = f.tell()
        f.seek(max(0, tam - n_bytes))
        return f.read().decode("utf-8", errors="replace")


def medir(jobs: list[dict], usar_ssh: bool) -> dict:
    info = {"journal_vm1": 0, "journal_vm2": 0}
    der = duracoes_derivados(RAIZ / "data/propagacao.db")
    try:
        j1 = subprocess.run(["journalctl", "--user", "-o", "short-unix", "--since", "-14days", "--no-pager"],
                            capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        j1 = ""
    jr1 = duracoes_journal(j1)
    info["journal_vm1"] = len(jr1)
    jr2 = {}
    if usar_ssh:
        j2 = ssh_vm2("journalctl --user -o short-unix --since -14days --no-pager | grep -E "
                     "'systemd\\[[0-9]+\\]: (Starting|Finished|Failed to start) |\\.service: (Failed with result|Deactivated successfully)'",
                     timeout=60)
        jr2 = duracoes_journal(j2)
        info["journal_vm2"] = len(jr2)
    pes = duracoes_pesado(ler(RAIZ / "data/pesado_vm1.log"))
    for j in jobs:
        p50, fonte, n = None, None, 0
        if j.get("derivado") and j["derivado"] in der:
            p50, n, por_dia = der[j["derivado"]]
            fonte = "medido:propagacao.db"
            j["execucoes_dia"] = por_dia
        elif j["gatilho"]["tipo"] in ("timer", "servico") and j["origem"].startswith("systemd:"):
            unit = j["origem"].split(":", 1)[1].split()[0].replace(".timer", ".service")
            fonte_j = jr1 if j["dono"] == "vm1" else jr2
            if unit in fonte_j and fonte_j[unit][0] is not None and j["gatilho"]["tipo"] == "timer":
                p50, n = fonte_j[unit]
                fonte = f"medido:journal-{j['dono']}"
        if p50 is None and "pesado.sh" in j["comando"]:
            nome = re.search(r"pesado\.sh\s+(\S+)", j["comando"]).group(1)
            if nome in pes and pes[nome][0] is not None:
                p50, n = pes[nome]
                fonte = "medido:pesado_vm1.log"
        if p50 is None and j["gatilho"]["tipo"] == "cron" and j["estado_pre_parada"] != "comentado":
            log = _log_do_comando(j["comando"])
            if log:
                periodo = 86400 / j["execucoes_dia"] if j.get("execucoes_dia") else 86400
                p50, n = duracao_por_log(_tail(log), periodo)
                fonte = f"medido:log({log.name})" if p50 is not None else None
        if p50 is None:
            teto = min(x for x in (j.get("timeout_s"), j.get("orcamento_s"), 86400) if x)
            periodo = 86400 / j["execucoes_dia"] if j.get("execucoes_dia") else 86400
            if j["gatilho"]["tipo"] in ("servico", "filho", "logon") and j["execucoes_dia"] is None:
                p50, fonte = 86400.0, "residente (24 h/dia de ocupação, não de CPU)"
            elif teto < 86400:
                p50 = round(min(teto * 0.5, periodo * 0.5), 1)
                fonte = "estimado: 50% do teto declarado (timeout/orçamento), ≤ 50% do intervalo"
            else:
                p50 = round(min(60.0, periodo * 0.1), 1)
                fonte = "estimado: 60 s ou 10% do intervalo (sem teto, sem log de rodada)"
        j["duracao_p50_s"] = p50
        j["duracao_fonte"] = fonte
        j["duracao_n"] = n or None
        if j.get("execucoes_dia") is not None and j["estado_pre_parada"] in ("ativo", "rede"):
            j["horas_dia"] = round(min(p50 * j["execucoes_dia"], 86400) / 3600, 2)
        elif j["gatilho"]["tipo"] in ("servico", "filho", "logon") and j["estado_pre_parada"] == "ativo":
            j["horas_dia"] = 24.0
        else:
            j["horas_dia"] = 0.0
    return info


# ----------------------------------------------------------------------------------------------- saída
CAMPOS = ["id", "dono", "executa_em", "gatilho", "comando", "ponto_entrada", "recursos", "timeout_s", "orcamento_s",
          "estado_pre_parada", "comentada_pela_parada", "estagio_destino", "lente", "duplicado_de", "duplicacao",
          "execucoes_dia", "duracao_p50_s", "duracao_fonte", "duracao_n", "horas_dia", "origem", "nota"]


def limpar(jobs: list[dict]) -> list[dict]:
    out = []
    for j in jobs:
        out.append({k: j[k] for k in CAMPOS if j.get(k) not in (None, "", False)})
    return out


def escrever_yaml(jobs: list[dict], meta: dict, destino: Path) -> None:
    conta = Counter(j["dono"] for j in jobs)
    doc = {"gerado_por": "tools/inventario_jobs.py (O1.1, plano mestre v2)",
           "gerado_em": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
           "fontes": meta["fontes"], "total": len(jobs), "por_dono": dict(conta),
           "legenda": {"estado_pre_parada": "ativo | rede (cron que era rede de segurança de um derivado) | "
                                            "comentado (já desligado antes) | parado (unit/tarefa instalada, não rodava)",
                       "estagio_destino": "E1..E18 | combinação | aposentar | infra (serviço residente) | "
                                          "fora_do_jfn (outro sistema na máquina)"},
           "jobs": limpar(jobs)}
    destino.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=140))


def _fmt_h(x: float | None) -> str:
    return "—" if x is None else f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _cel(s: str | None, n: int = 70) -> str:
    s = (s or "—").replace("|", "\\|").replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def escrever_md_inventario(jobs: list[dict], destino: Path) -> None:
    conta = Counter(j["dono"] for j in jobs)
    est = Counter(j["estado_pre_parada"] for j in jobs)
    dups = [j for j in jobs if j.get("duplicado_de")]
    linhas = [
        "---", "tipo: inventario", "plano: PLANO-MESTRE-v2-esteira-unica (O1.1)", f"data: {dt.date.today()}",
        "gerado_por: tools/inventario_jobs.py --md", "---", "",
        "# Inventário de jobs pré-parada — 24/11/2026", "",
        "> **Escopo.** Tudo o que rodava (ou estava instalado) antes da parada de obras de 24/11/2026, nas três "
        "máquinas, mais os derivados da propagação. Fonte de máquina: `config/jobs.yaml` (este arquivo é a visão "
        "legível; regenerar com `python tools/inventario_jobs.py --md --capacidade --ssh`).", "",
        "## 1. Números", "",
        "| Máquina | Jobs | | Estado | Jobs |", "|---|---:|---|---|---:|",
    ]
    estados = list(est.items())
    for i, (dono, n) in enumerate(sorted(conta.items())):
        e = estados[i] if i < len(estados) else ("", "")
        linhas.append(f"| {dono} | {n} | | {e[0]} | {e[1]} |")
    for e in estados[len(conta):]:
        linhas.append(f"| | | | {e[0]} | {e[1]} |")
    linhas += [f"| **total** | **{len(jobs)}** | | | |", "",
               f"- Duplicações (mesmo ponto de entrada em mais de um gatilho): **{len(dups)}** "
               f"({sum(1 for j in dups if j['duplicacao'] == 'exato')} exatas, "
               f"{sum(1 for j in dups if j['duplicacao'] == 'mesmo_script')} mesmo script com argumentos outros).",
               f"- Sem destino: **{sum(1 for j in jobs if j['estagio_destino'] == 'SEM_DESTINO')}**.", ""]
    por_est = Counter(j["estagio_destino"] for j in jobs if j["estado_pre_parada"] in ("ativo", "rede"))
    linhas += ["### Jobs ativos por estágio de destino", "", "| Estágio | Jobs ativos/rede |", "|---|---:|"]
    for e, n in sorted(por_est.items(), key=lambda x: (not x[0].startswith("E"), int(re.sub(r"\D.*", "", x[0][1:]) or 99) if x[0].startswith("E") else 0, x[0])):
        linhas.append(f"| {e} | {n} |")
    linhas.append("")
    sec = 2
    for dono in ("vm1", "vm2", "itcampo"):
        js = [j for j in jobs if j["dono"] == dono]
        linhas += [f"## {sec}. {dono.upper() if dono != 'itcampo' else 'it-campo'} — {len(js)} jobs", "",
                   "| id | gatilho | estado | estágio | lente | recursos | p50 | h/dia | dup. de |",
                   "|---|---|---|---|---|---|---:|---:|---|"]
        for j in sorted(js, key=lambda j: (j["gatilho"]["tipo"], j["id"])):
            g = f"{j['gatilho']['tipo']}: {j['gatilho']['expr']}"
            p50 = j.get("duracao_p50_s")
            p50s = "—" if p50 is None else (f"{p50/60:,.1f} min".replace(".", ",") if p50 < 86400 else "contínuo")
            if j.get("duracao_fonte", "").startswith("estimado") and p50 is not None and p50 < 86400:
                p50s += "*"
            linhas.append(f"| `{j['id']}` | {_cel(g, 48)} | {j['estado_pre_parada']} | {j['estagio_destino']} | "
                          f"{j.get('lente') or '—'} | {', '.join(j['recursos'])} | {p50s} | {_fmt_h(j.get('horas_dia'))} | "
                          f"{('`' + j['duplicado_de'] + '`') if j.get('duplicado_de') else '—'} |")
        linhas += ["", "`*` = duração estimada (sem medição); ver `capacidade-20261124.md`.", ""]
        sec += 1
    linhas += [f"## {sec}. Duplicações", "",
               "| job | duplica | tipo | ponto de entrada | gatilhos |", "|---|---|---|---|---|"]
    by_id = {j["id"]: j for j in jobs}
    for j in sorted(dups, key=lambda j: (j["ponto_entrada"], j["id"])):
        p = by_id[j["duplicado_de"]]
        linhas.append(f"| `{j['id']}` ({j['estado_pre_parada']}) | `{p['id']}` | {j['duplicacao']} | `{j['ponto_entrada']}` | "
                      f"{_cel(j['gatilho']['expr'], 30)} × {_cel(p['gatilho']['expr'], 30)} |")
    linhas += ["", f"## {sec + 1}. Convenções", "",
               "- `id` estável: `<dono>-<cron|timer|svc|task|filho|deriv>-<slug do ponto de entrada>`; sufixo `-N` "
               "quando o mesmo script tem mais de um gatilho no mesmo dono.",
               "- `rede` = cron que a propagação manteve como rede de segurança de um derivado (mesmo comando).",
               "- `infra` e `fora_do_jfn` são destinos fora dos 18 estágios: serviço residente (painel, wal-keeper, "
               "ponte CDP) e sistemas vizinhos (Hermes/Yoda, WhatsApp, Polimonitor, brain, Atena).",
               "- Recursos inferidos do comando e do texto do script chamado (1 nível): heurística, conferir antes "
               "de usar como slot.", ""]
    destino.write_text("\n".join(linhas))


def escrever_md_capacidade(jobs: list[dict], info: dict, destino: Path, ocr: dict) -> None:
    ativos = [j for j in jobs if j["estado_pre_parada"] in ("ativo", "rede")]
    PRIO = ["gpu", "navegador", "llm", "pesado", "leve"]

    def principal(j):
        return next(r for r in PRIO if r in j["recursos"])

    def onde(j):
        return j.get("executa_em") or j["dono"]

    tab: dict = defaultdict(lambda: defaultdict(float))
    resid: dict = defaultdict(list)
    medido_h = defaultdict(float)
    for j in ativos:
        if j["estagio_destino"] in ("fora_do_jfn",):
            continue
        h = j.get("horas_dia") or 0.0
        if (j.get("duracao_fonte") or "").startswith("residente"):
            resid[onde(j)].append(j)
            continue
        tab[onde(j)][principal(j)] += h
        if (j.get("duracao_fonte") or "").startswith("medido"):
            medido_h[onde(j)] += h
    por_est: dict = defaultdict(lambda: defaultdict(float))
    for j in ativos:
        if j["estagio_destino"] == "fora_do_jfn" or (j.get("duracao_fonte") or "").startswith("residente"):
            continue
        por_est[j["estagio_destino"]][onde(j)] += j.get("horas_dia") or 0.0
    n_med = sum(1 for j in ativos if (j.get("duracao_fonte") or "").startswith("medido"))
    n_est = sum(1 for j in ativos if (j.get("duracao_fonte") or "").startswith("estimado"))
    L = ["---", "tipo: capacidade", "plano: PLANO-MESTRE-v2-esteira-unica (O1.6)", f"data: {dt.date.today()}",
         "gerado_por: tools/inventario_jobs.py --capacidade", "---", "",
         "# Capacidade das máquinas — horas/dia de trabalho pré-parada", "",
         "> **Leitura.** *Medido* = duração p50 de rodadas reais (propagacao.db, journal do systemd, "
         "`data/pesado_vm1.log`, ou rodadas reconstruídas pelo carimbo de hora do log do próprio job — esta última é "
         "aproximação ±). *Estimado* = 50% do teto declarado (`timeout`/`--segundos`) ou 60 s quando não há teto. "
         "*Residente* = laço ou serviço que ocupa um slot 24 h (não é CPU contínua).", "",
         f"- Jobs ativos considerados: **{len(ativos)}** · com duração medida: **{n_med}** · estimada: **{n_est}** · "
         f"residentes: **{sum(len(v) for v in resid.values())}**.",
         f"- Journal: VM-1 {info.get('journal_vm1', 0)} units com rodadas; VM-2 {info.get('journal_vm2', 0)} "
         f"({'via ssh' if info.get('journal_vm2') else 'sem ssh — timers da VM-2 estimados'}).", "",
         "## 1. Horas/dia por máquina e recurso principal (a) com as 3 máquinas", "",
         "| Máquina | gpu | navegador | llm | pesado | leve | **total** | dos quais medido | residentes (slots 24 h) |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    for m in ("vm1", "vm2", "itcampo"):
        t = tab[m]
        tot = sum(t.values())
        rs = ", ".join(sorted({j['id'].split('-', 2)[-1] for j in resid[m]}))
        L.append(f"| {m} | " + " | ".join(_fmt_h(t[r]) for r in PRIO) + f" | **{_fmt_h(tot)}** | {_fmt_h(medido_h[m])} | "
                 f"{len(resid[m])}: {_cel(rs, 90)} |")
    L += ["", "Horas/dia de um recurso > 24 significa mais de um slot ocupado em média (ex.: 30 h de navegador = 1,25 "
          "sessão sempre aberta).", "",
          "## 2. Horas/dia por estágio de destino", "", "| Estágio | VM-1 | VM-2 | it-campo | total |", "|---|---:|---:|---:|---:|"]
    for e in sorted(por_est, key=lambda x: (not x.startswith("E"), int(re.sub(r"\D.*", "", x[1:]) or 99) if x.startswith("E") else 0, x)):
        v = por_est[e]
        L.append(f"| {e} | {_fmt_h(v['vm1'])} | {_fmt_h(v['vm2'])} | {_fmt_h(v['itcampo'])} | {_fmt_h(sum(v.values()))} |")
    # (b) sem it-campo
    it = tab["itcampo"]
    L += ["", "## 3. (b) Só VM-1 + VM-2 (it-campo fora)", "",
          "O que o it-campo fazia em laços residentes (SEI paralelo, OCR GPU, pool nativo) não aparece em h/dia de "
          "job — aparece como **vazão**. A conta abaixo traduz a vazão do it-campo para a VM-2 (§3.5 do plano):", ""]
    L += ocr.get("linhas", [])
    L += ["", "| Máquina | total (a) | carga que migra do it-campo | total (b) | teto prático/dia |", "|---|---:|---:|---:|---:|"]
    mig = sum(it.values())
    for m, extra in (("vm1", 0.0), ("vm2", mig)):
        tot = sum(tab[m].values())
        L.append(f"| {m} | {_fmt_h(tot)} | {_fmt_h(extra)} | {_fmt_h(tot + extra)} | 2 vCPU × 24 h = 48 h-CPU |")
    L += ["", "## 4. Jobs que mais pesam (top 25 em h/dia, sem residentes)", "",
          "| job | onde | estágio | recurso | p50 | ×/dia | h/dia | fonte |", "|---|---|---|---|---:|---:|---:|---|"]
    top = sorted((j for j in ativos if not (j.get("duracao_fonte") or "").startswith("residente")
                  and j["estagio_destino"] != "fora_do_jfn"), key=lambda j: -(j.get("horas_dia") or 0))[:25]
    for j in top:
        L.append(f"| `{j['id']}` | {onde(j)} | {j['estagio_destino']} | {principal(j)} | "
                 f"{_fmt_h(j['duracao_p50_s']/60)} min | {_fmt_h(j.get('execucoes_dia'))} | {_fmt_h(j.get('horas_dia'))} | "
                 f"{_cel(j.get('duracao_fonte'), 40)} |")
    L += [""]
    manual = ""  # o que vem depois do marcador é texto do analista: regenerar não apaga
    if destino.exists() and MARCADOR_MANUAL in ler(destino):
        manual = ler(destino)[ler(destino).index(MARCADOR_MANUAL):]
    destino.write_text("\n".join(L) + "\n" + (manual or MARCADOR_MANUAL + "\n"))


MARCADOR_MANUAL = "<!-- MANUAL: daqui para baixo é análise escrita à mão; o gerador preserva -->"


def vazao_ocr() -> dict:
    """Vazão medida do OCR por nó (data/sei_ocr_reserva_estado.json: PDFs entregues por nó e dia) + bancada GPU."""
    linhas, d = [], {}
    try:
        est = json.loads(ler(RAIZ / "data/sei_ocr_reserva_estado.json") or "{}")
    except json.JSONDecodeError:
        est = {}
    por_no: dict = defaultdict(list)
    for v in est.values():
        if isinstance(v, dict) and v.get("estado") == "entregue" and v.get("ts"):
            por_no[v.get("no", "?")].append(float(v["ts"]))
    linhas += ["| Nó (OCR de reserva, CPU) | PDFs entregues | janela (dias) | PDFs/dia (medido) |", "|---|---:|---:|---:|"]
    for no, ts in sorted(por_no.items()):
        dias = max((max(ts) - min(ts)) / 86400, 1.0)
        d[no] = len(ts) / dias
        linhas.append(f"| {no} | {len(ts):,} | {_fmt_h(dias)} | {_fmt_h(len(ts) / dias)} |".replace(f"{len(ts):,}", f"{len(ts):,}".replace(",", ".")))
    # captura SEI por nó: data/itcampo_rodadas.jsonl (uma linha por rodada de sessão; últimos 7 dias)
    cap: dict = defaultdict(lambda: {"ok": 0, "docs": 0, "slot_s": 0.0, "dias": set()})
    limite = (dt.datetime.now() - dt.timedelta(days=7)).strftime("%Y-%m-%d")
    for linha in ler(RAIZ / "data/itcampo_rodadas.jsonl").splitlines():
        try:
            r = json.loads(linha)
        except json.JSONDecodeError:
            continue
        if str(r.get("ts", "")) < limite:
            continue
        c = cap[r.get("no", "?")]
        c["ok"] += int(r.get("ok") or 0)
        c["docs"] += int(r.get("docs_com_teor") or 0)
        c["slot_s"] += float(r.get("duracao_s") or 0)
        c["dias"].add(str(r["ts"])[:10])
    if cap:
        linhas += ["", "| Nó (captura SEI, `itcampo_rodadas.jsonl`, 7 dias) | processos ok/dia | documentos/dia | "
                   "slots médios ocupados | documentos por slot-hora |", "|---|---:|---:|---:|---:|"]
        for no, c in sorted(cap.items()):
            nd = max(len(c["dias"]), 1)
            sh = c["slot_s"] / 3600
            d[f"captura:{no}"] = {"docs_dia": c["docs"] / nd, "docs_slot_h": c["docs"] / sh if sh else 0,
                                  "slots": sh / 24 / nd, "ok_dia": c["ok"] / nd}
            linhas.append(f"| {no} | {_fmt_h(c['ok'] / nd)} | {_fmt_h(c['docs'] / nd)} | {_fmt_h(sh / 24 / nd)} | "
                          f"{_fmt_h(c['docs'] / sh if sh else 0)} |")
    banc = RAIZ / "deploy/itcampo/ocr_gpu/bench_vazao_resultado_20261118.jsonl"
    pags = []
    for linha in ler(banc).splitlines():
        try:
            pags.append(json.loads(linha)["pags_por_h"])
        except (json.JSONDecodeError, KeyError):
            pass
    if pags:
        linhas += ["", f"- GPU do it-campo (Surya/vLLM, bancada de 18/11, **medido**): p50 "
                   f"**{_fmt_h(statistics.median(pags))} páginas/h** ≈ {_fmt_h(statistics.median(pags) * 24)} páginas/dia."]
    return {"linhas": linhas, "por_no": d}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--saida", default=str(RAIZ / "config/jobs.yaml"))
    ap.add_argument("--md", action="store_true", help="escreve a nota do inventário no vault")
    ap.add_argument("--capacidade", action="store_true", help="mede p50 e escreve a nota de capacidade (O1.6)")
    ap.add_argument("--ssh", action="store_true", help="lê units e journal da VM-2 por ssh (timeout)")
    a = ap.parse_args(argv)
    jobs, meta = montar(a.ssh)
    info = medir(jobs, a.ssh) if a.capacidade else {}
    escrever_yaml(jobs, meta, Path(a.saida))
    if a.md:
        escrever_md_inventario(jobs, VAULT / "inventario-jobs-20261124.md")
    if a.capacidade:
        escrever_md_capacidade(jobs, info, VAULT / "capacidade-20261124.md", vazao_ocr())
    conta = Counter(j["dono"] for j in jobs)
    print(f"{len(jobs)} jobs {dict(conta)}; duplicados {sum(1 for j in jobs if j.get('duplicado_de'))}; "
          f"sem destino {sum(1 for j in jobs if j['estagio_destino'] == 'SEM_DESTINO')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
