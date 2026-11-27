# -*- coding: utf-8 -*-
"""PROPAGAÇÃO AUTOMÁTICA — pedido do dono, 14/11/2026: "uma alteração ou leitura tem que puxar outras para
atualizar tudo automaticamente".

Antes: cada derivado (perícia contábil, vínculo OB↔contrato, mapa por município, CGE × JFN, caches do painel…)
tinha o SEU cron — diário, semanal ou nenhum — e ficava velho entre uma rodada e outra sem ninguém saber. A
correção das Guias de Devolução de 14/11 09:25 só chegaria à perícia contábil publicada na madrugada seguinte.

Agora há UM mecanismo, com três peças, todas declaradas em `config/propagacao.yaml` (o mapa de dependências):

  · FONTES — o que muda no mundo. Os produtores NÃO foram tocados: cada fonte tem uma SONDA barata que percebe a
    mudança de fora (MAX(rowid) de tabela, mtime de arquivo, linha nova de log, commit que toca um caminho, arquivo
    novo numa pasta). Mudou → vira EVENTO. O que não dá para sondar entra por `emitir` (revisão humana, decisão).
  · DERIVADOS — o que fica velho. Cada evento marca como SUJO todo derivado que depende daquela fonte. Um derivado
    recalculado vira, ele mesmo, evento para os que dependem dele (vínculo → perícia → caches do painel).
  · DESPACHANTE — `ciclo`, pelo cron a cada 5 min, FORA do processo do painel. Recalcula só o que está sujo, com:
    trava de arquivo (um ciclo por vez), janela de junção de eventos (debounce, contada do 1º evento — fonte que
    não para não mata o derivado de fome), intervalo mínimo entre execuções, UM pesado por ciclo e só com carga
    abaixo do teto, prioridade, recuo exponencial após falha. Os comandos são as rotinas que já existem, idempotentes.

O que o despachante NÃO faz: não grava no compliance.db, não chama API paga, não gradua nada (🔴/🟡 continuam
saindo só das réguas de cada rotina), e não dá um recálculo por feito sem medir o EFEITO (o arquivo que o painel
lê avançou? a chave do cache foi regravada?). Sonda que falha é erro declarado da fonte — nunca "sem mudança".

Estado em `data/propagacao.db` (base própria, pequena); o painel lê em Sistema › Propagação
(`/api/sistema/propagacao`). Descobertas duráveis seguem para o segundo cérebro (`cerebro_compartilhado`).

⚠ SUBSTITUÍDO PELO MOTOR DE FLUXO (O2.3, 24/11/2026 — plano mestre v2 §3.3): o `ciclo` (cron */5) e o seu
`despachar` são aposentados. Quem recalcula derivado agora é o planejador do `jfn-fluxo`
(compliance_agent/fluxo/planejador.py, grafo em config/fluxo.yaml); o resto do ciclo — sondas, eventos dos produtores,
descobertas → cérebro, poda — segue em `ponte-fluxo` (rotina `propagacao_ponte`, E18), que entrega os eventos ao
`fluxo.eventos`. O `ciclo` fica SÓ como desfazer da religação (crontab `#PARADA-20261124`) e é removido na O9.1,
depois de 14 dias de religação estável. Não chamar `ciclo` e `ponte-fluxo` juntos: dividem a mesma trava.

CLI:
    python -m compliance_agent.propagacao ciclo                 # LEGADO (desfazer da O9.0): sonda + despachante
    python -m compliance_agent.propagacao ponte-fluxo           # o que o fluxo chama: sonda → fluxo.eventos
    python -m compliance_agent.propagacao estado                # JSON do painel
    python -m compliance_agent.propagacao mapa                  # mapa de dependências em Markdown
    python -m compliance_agent.propagacao emitir <fonte> "<detalhe>"
    python -m compliance_agent.propagacao sujar <derivado> "<motivo>"
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import re
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml

from compliance_agent import cerebro_compartilhado as cerebro

RAIZ = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("JFN_DATA_DIR") or RAIZ / "data")
CONFIG = Path(os.environ.get("JFN_PROPAGACAO_YAML") or RAIZ / "config" / "propagacao.yaml")
BASE_PAINEL = os.environ.get("JFN_BASE", "http://127.0.0.1:8000")

ORCAMENTO_CICLO_S = 1200          # um ciclo não começa execução nova depois disto
# leve = segundos de CPU ou um pedido de rota que o pré-aquecimento já faz a cada 30 min sem olhar a carga; com
# teto 10 os leves ficaram dois ciclos parados em 14/11/2026 (carga 11–14 por captura SEI + OCR + análise).
CARGA_MAX = {"leve": 14.0, "pesado": 7.0}
# A VM vive entre carga 5 e 9: sem válvula, um pesado poderia esperar o dia inteiro. Sujo há mais de 2 h, o teto
# sobe (os mesmos comandos já rodam pelo cron, com `nice`, sem olhar a carga).
CARGA_PACIENCIA_S = 7200
# Depois da paciência o teto SOBE, nunca desce (18/11/2026: o 12 único descia o da leve de 14 para 12; com a VM-1
# em carga 14–17 a tarefa leve ficava mais presa quanto mais esperava).
CARGA_TETO_FINAL = {"leve": 18.0, "pesado": 12.0}
# Além do SLO (24/11/2026): a VM-1 vive em carga 14–22 e os pesados ficavam 20–45 h parados enquanto o cron-rede
# rodava o MESMO comando sem olhar carga nenhuma. Passado o SLO o teto vira este (o semáforo único de pesado e o
# `nice 15` continuam) — desde que haja memória: a trava de 23/11 foi swap 100%, não CPU.
CARGA_TETO_ATRASADO = 30.0
MEMORIA_MIN_ATRASADO_MB = 1500
# Pedido de vez no semáforo (24/11/2026): `sei_compactar` (de hora em hora, ~55 min, flock -w 1500) segurava a
# trava 24 h por dia e o despachante, que só tenta sem esperar, nunca a pegava. Pesado atrasado bloqueado SÓ pelo
# semáforo grava este pedido; `tools/pesado.sh` que toma a trava com pedido fresco a devolve e sai (adiado).
PEDIDO_PESADO_VALIDADE_S = 900
RECUO_BASE_S, RECUO_MAX_S = 1800, 6 * 3600
EVENTOS_GUARDADOS = 3000
# SLO do derivado (24/11/2026, Etapa 2): o estado dizia "ok" com 24 de 36 derivados sujos, 17 há mais de 2 h — só o
# ciclo parado contava como defeito. Agora sujo há mais que o SLO = ATRASADO, no estado e no sensor da automelhoria.
SLO_PADRAO_S = 7200

DDL = """
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS sonda(fonte TEXT PRIMARY KEY, assinatura TEXT, visto_em REAL, mudou_em REAL, erro TEXT);
CREATE TABLE IF NOT EXISTS evento(id INTEGER PRIMARY KEY AUTOINCREMENT, fonte TEXT, quando REAL, detalhe TEXT);
CREATE TABLE IF NOT EXISTS pendencia(derivado TEXT, evento_id INTEGER, PRIMARY KEY(derivado, evento_id));
CREATE TABLE IF NOT EXISTS derivado(id TEXT PRIMARY KEY, ultimo_inicio REAL, ultimo_fim REAL, ultimo_estado TEXT,
  ultimo_erro TEXT, falhas INTEGER DEFAULT 0, proxima_tentativa REAL, adiado TEXT, execucoes INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS execucao(id INTEGER PRIMARY KEY AUTOINCREMENT, derivado TEXT, inicio REAL, fim REAL,
  estado TEXT, motivos TEXT, erro TEXT);
"""


# ───────────────────────────── configuração ─────────────────────────────
def carregar(caminho: Path | None = None) -> dict:
    cfg = yaml.safe_load((caminho or CONFIG).read_text(encoding="utf-8")) or {}
    cfg.setdefault("fontes", {})
    cfg.setdefault("derivados", {})
    cfg.setdefault("cerebro", [])
    return cfg


def validar(cfg: dict) -> list[str]:
    """Erros do mapa: dependência inexistente, derivado sem comando, ciclo. Lista vazia = mapa são."""
    erros, fontes, ders = [], cfg["fontes"], cfg["derivados"]
    for i, d in ders.items():
        if d.get("tipo", "comando") == "comando" and not d.get("comando"):
            erros.append(f"{i}: sem comando")
        if d.get("tipo") == "cache" and not (d.get("prefixos") and d.get("urls")):
            erros.append(f"{i}: cache sem prefixos/urls")
        if not d.get("depende"):
            erros.append(f"{i}: não depende de nada (nunca ficaria sujo)")
        if d.get("frescor_max_s") and float(d["frescor_max_s"]) < float(d.get("intervalo_min_s") or 0):
            erros.append(f"{i}: frescor_max_s menor que intervalo_min_s (ficaria ATRASADO por desenho)")
        for dep in d.get("depende", []):
            if dep not in fontes and dep not in ders:
                erros.append(f"{i}: depende de '{dep}', que não existe")
    cor: dict[str, int] = {}

    def visita(n: str, trilha: tuple) -> None:
        if cor.get(n) == 2:
            return
        if cor.get(n) == 1:
            erros.append("ciclo: " + " → ".join(trilha + (n,)))
            return
        cor[n] = 1
        for dep in ders.get(n, {}).get("depende", []):
            if dep in ders:
                visita(dep, trilha + (n,))
        cor[n] = 2

    for i in ders:
        visita(i, ())
    return erros


def slo_s(d: dict, cfg: dict | None = None) -> float:
    """Sujo há mais que isto = ATRASADO. `frescor_max_s` do derivado, se declarado; senão o padrão (`slo_padrao_s`
    do yaml, 2 h) SOMADO ao `intervalo_min_s` — o derivado que por desenho espera N h entre execuções não está
    atrasado por esperar; atrasado é passar 2 h além disso. Fonte única: o grafo da certeza lê daqui."""
    if d.get("frescor_max_s"):
        return float(d["frescor_max_s"])
    return float((cfg or {}).get("slo_padrao_s") or SLO_PADRAO_S) + float(d.get("intervalo_min_s") or 0)


def dependentes(cfg: dict, origem: str) -> list[str]:
    return [i for i, d in cfg["derivados"].items() if origem in d.get("depende", [])]


# ───────────────────────────── base de estado ─────────────────────────────
def conectar(db: Path | None = None) -> sqlite3.Connection:
    alvo = db or DATA / "propagacao.db"
    alvo.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(alvo, timeout=30)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(DDL)
    # 24/11/2026: pesado roda DESTACADO do ciclo — o PID do processo filho fica na linha do derivado
    with contextlib.suppress(sqlite3.OperationalError):
        con.execute("ALTER TABLE derivado ADD COLUMN pid INTEGER")
    cerebro.preparar(con)
    return con


def emitir(con: sqlite3.Connection, cfg: dict, fonte: str, detalhe: str, quando: float | None = None) -> int:
    """Registra o evento e suja todo derivado que depende da fonte. Devolve o id do evento."""
    eid = con.execute("INSERT INTO evento(fonte, quando, detalhe) VALUES (?,?,?)",
                      (fonte, quando or time.time(), (detalhe or "")[:400])).lastrowid
    for d in dependentes(cfg, fonte):
        con.execute("INSERT OR IGNORE INTO pendencia(derivado, evento_id) VALUES (?,?)", (d, eid))
    con.commit()
    return eid


def avisar(fonte: str, detalhe: str) -> int | None:
    """Evento de verdade do PRODUTOR (Etapa 2, 24/11/2026): o coletor que terminou com sucesso avisa na hora, com o
    QUE mudou; a sonda segue como rede de segurança (o evento duplicado cai na mesma janela de junção). Nunca derruba
    o coletor: falha vira aviso no stderr e None. Sob pytest não grava (a base é a de produção), salvo
    JFN_PROPAGACAO_EM_TESTE=1."""
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("JFN_PROPAGACAO_EM_TESTE"):
        return None
    try:
        cfg = carregar()
        if fonte not in cfg["fontes"]:
            raise KeyError(f"fonte '{fonte}' não está em config/propagacao.yaml")
        con = conectar()
        try:
            return emitir(con, cfg, fonte, detalhe)
        finally:
            con.close()
    except (OSError, ValueError, KeyError, sqlite3.Error, yaml.YAMLError) as exc:
        print(f"propagação: evento de {fonte} não emitido ({type(exc).__name__}: {exc})", file=sys.stderr)
        return None


# ───────────────────────────── sondas ─────────────────────────────
class SondaFalhou(RuntimeError):
    """A sonda não conseguiu medir a fonte (isto NÃO é 'sem mudança')."""


def _extrair_siafe_status(linhas: list) -> str | None:
    """Linhas (data_emissao, transicoes 'k=v;k=v') de `ob_status_recoleta` recoletadas desde a última leitura →
    transições somadas. None = nenhum status saiu do estado intermediário (nada a propagar).

    Lê a TABELA e não o log: o `siafe_runner` corta a linha do log em 400 caracteres e o JSON chega pela metade."""
    tot: dict[str, int] = {}
    for _, trans in linhas:
        for par in (trans or "").split(";"):
            k, _, v = par.partition("=")
            if v.strip().isdigit():
                tot[k.strip()] = tot.get(k.strip(), 0) + int(v)
    mudou = {k: v for k, v in tot.items() if k not in ("Enviado ao Banco", "Aguardando Envio", "Aguardando Geração RE")}
    if not mudou:
        return None
    return (f"status de OB recoletado em {len(linhas)} dia(s) de emissão: "
            + ", ".join(f"{v} → {k}" for k, v in sorted(mudou.items(), key=lambda x: -x[1])))


EXTRATORES = {"siafe_status": _extrair_siafe_status}


def _sonda_sql(s: dict, anterior: str | None) -> tuple[str, list[str]]:
    db = RAIZ / s.get("db", "data/compliance.db")
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=20)
        try:
            lin = con.execute(s["sql"]).fetchall()
        finally:
            con.close()
    except sqlite3.Error as exc:
        raise SondaFalhou(f"{type(exc).__name__}: {exc}") from exc
    nova = json.dumps(lin, ensure_ascii=False, default=str)
    if anterior is None or nova == anterior:
        return nova, []
    if s.get("detalhe"):                               # consulta do QUE mudou desde a assinatura anterior
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=20)
            try:
                novas = con.execute(s["detalhe"], (json.loads(anterior)[0][0],)).fetchall()
            finally:
                con.close()
        except (sqlite3.Error, ValueError, IndexError) as exc:
            raise SondaFalhou(f"detalhe: {type(exc).__name__}: {exc}") from exc
        txt = EXTRATORES[s["extrator"]](novas)
        return nova, ([txt] if txt else [])
    try:
        a, b = json.loads(anterior)[0][0], lin[0][0]
        if len(lin) == 1 and len(lin[0]) == 1 and isinstance(a, int) and isinstance(b, int) and b > a:
            return nova, [f"+{b - a:,}".replace(",", ".") + f" {s.get('unidade', 'linha(s)')}"]
    except (ValueError, IndexError, TypeError):
        pass
    return nova, [s.get("mudanca", "conteúdo mudou")]


def _sonda_arquivo(s: dict, anterior: str | None) -> tuple[str, list[str]]:
    try:
        st = (RAIZ / s["arquivo"]).stat()
        nova = f"{st.st_mtime_ns}:{st.st_size}"
    except FileNotFoundError:
        nova = "ausente"
    except OSError as exc:
        raise SondaFalhou(str(exc)) from exc
    return nova, ([] if anterior is None or nova == anterior else [s.get("mudanca", "arquivo regravado")])


def _sonda_pasta(s: dict, anterior: str | None) -> tuple[str, list[str]]:
    pasta = Path(os.path.expanduser(s["pasta"]))
    if not pasta.is_dir():
        raise SondaFalhou(f"pasta ausente: {s['pasta']}")
    arqs = [(f.stat().st_mtime, f.name) for f in pasta.glob(s.get("glob", "*"))
            if f.is_file() and f.name not in s.get("ignorar", ())]
    nova = repr(max((m for m, _ in arqs), default=0.0))
    if anterior is None:
        return nova, []
    corte = float(anterior)
    return nova, [n for m, n in sorted(arqs) if m > corte][-30:]


def _sonda_log(s: dict, anterior: str | None) -> tuple[str, list[str]]:
    arq = RAIZ / s["log"]
    try:
        st = arq.stat()
    except FileNotFoundError:
        return "ausente", []
    if anterior in (None, "ausente"):
        return f"{st.st_ino}:{st.st_size}", []
    ino, pos = (int(x) for x in anterior.split(":"))
    if ino != st.st_ino or st.st_size < pos:          # log rodado/truncado: recomeça do zero
        pos = 0
    rx = re.compile(s["regex"])
    eventos: list[str] = []
    with arq.open("rb") as f:
        f.seek(pos)
        bloco = f.read(8_000_000)
    fim = bloco.rfind(b"\n") + 1                       # só linhas inteiras
    for linha in bloco[:fim].decode("utf-8", "replace").splitlines():
        m = rx.search(linha)
        if not m:
            continue
        mn = s.get("minimo")
        if mn and int(m.group(mn[0])) < mn[1]:
            continue
        txt = s.get("texto", "{0}")
        for i, g in enumerate((m.group(0),) + m.groups()):
            txt = txt.replace("{%d}" % i, str(g))
        eventos.append(txt)
    return f"{st.st_ino}:{pos + fim}", eventos[-40:]


def _git(*args: str) -> str:
    try:
        r = subprocess.run(["git", "-C", str(RAIZ), *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise SondaFalhou(f"git: {exc}") from exc
    if r.returncode != 0:
        raise SondaFalhou(f"git {args[0]}: {r.stderr.strip()[:200]}")
    return r.stdout


def _sonda_git(s: dict, anterior: str | None) -> tuple[str, list[str]]:
    head = _git("rev-parse", "HEAD").strip()
    if anterior is None or anterior == head:
        return head, []
    try:
        _git("merge-base", "--is-ancestor", anterior, head)
    except SondaFalhou:                                # história reescrita/branch trocada: nova linha de base
        return head, []
    saida = _git("log", "--reverse", "--format=%h%x09%s", f"{anterior}..{head}", "--", *s["git"])
    rx = re.compile(s["assunto"]) if s.get("assunto") else None
    return head, [ln.replace("\t", " ", 1) for ln in saida.splitlines()
                  if ln.strip() and (rx is None or rx.search(ln.split("\t", 1)[-1]))][-30:]


_SONDAS = {"sql": _sonda_sql, "arquivo": _sonda_arquivo, "pasta": _sonda_pasta, "log": _sonda_log, "git": _sonda_git}


def sondar(con: sqlite3.Connection, cfg: dict) -> int:
    """Roda todas as sondas; cada mudança vira evento. Devolve quantos eventos nasceram."""
    n = 0
    for fid, f in cfg["fontes"].items():
        s = f.get("sonda") or {}
        tipo = next((t for t in _SONDAS if t in s), None)
        if tipo is None:                               # fonte manual (só `emitir`)
            continue
        ant = con.execute("SELECT assinatura FROM sonda WHERE fonte=?", (fid,)).fetchone()
        agora = time.time()
        try:
            nova, detalhes = _SONDAS[tipo](s, ant[0] if ant else None)
        except (SondaFalhou, OSError, ValueError, KeyError, re.error) as exc:
            con.execute("INSERT INTO sonda(fonte, visto_em, erro) VALUES (?,?,?) "
                        "ON CONFLICT(fonte) DO UPDATE SET visto_em=excluded.visto_em, erro=excluded.erro",
                        (fid, agora, f"{type(exc).__name__}: {exc}"[:300]))
            con.commit()
            continue
        mudou = bool(ant) and nova != ant[0]
        con.execute("INSERT INTO sonda(fonte, assinatura, visto_em, mudou_em, erro) VALUES (?,?,?,NULL,NULL) "
                    "ON CONFLICT(fonte) DO UPDATE SET assinatura=excluded.assinatura, visto_em=excluded.visto_em, "
                    "erro=NULL, mudou_em=CASE WHEN ? THEN excluded.visto_em ELSE mudou_em END",
                    (fid, nova, agora, 1 if (mudou and detalhes) else 0))
        con.commit()
        for det in detalhes:
            emitir(con, cfg, fid, det)
            _descoberta_da_fonte(con, f, fid, det)
            n += 1
    return n


# ───────────────────────────── descobertas → cérebro ─────────────────────────────
def _descoberta_da_fonte(con: sqlite3.Connection, f: dict, fid: str, det: str) -> None:
    """Fonte com bloco `cerebro:` manda cada evento como descoberta (ex.: correção de regra, memória nova)."""
    c = f.get("cerebro")
    if not c:
        return
    if c.get("de") == "memoria":                       # arquivo de memória do Claude: 1 fato = a descrição
        fato = _fato_da_memoria(Path(os.path.expanduser(f["sonda"]["pasta"])) / det)
        if fato:
            cerebro.registrar(f"memoria:{det.removesuffix('.md')}", fato[1], fato[0], det.removesuffix(".md"), con=con)
        return
    if c.get("de") == "commit":
        h, _, assunto = det.partition(" ")
        # lição = correção (`fix`); e o commit que toca dois caminhos entra uma vez só, pela 1ª fonte que o viu
        if not re.match(c.get("so", "fix"), assunto) or con.execute(
                "SELECT 1 FROM cerebro WHERE chave=?", (f"commit:{h}",)).fetchone():
            return
        try:
            corpo = " ".join(_git("show", "-s", "--format=%b", h).split("Co-Authored-By")[0].split())[:900]
            data = _git("show", "-s", "--format=%cd", "--date=format:%d/%m/%Y", h).strip()
        except SondaFalhou:
            corpo, data = "", ""
        cerebro.registrar(f"commit:{h}", f"JFN — {c.get('rotulo', 'correção')} em {data} ({h}): {assunto}. {corpo}".strip(),
                          c.get("kind", "experiencial"), c.get("assunto", fid), con=con)


def _fato_da_memoria(arq: Path) -> tuple[str, str] | None:
    """(kind, fato) de um arquivo de memória: a `description` do cabeçalho, ou o 1º parágrafo."""
    try:
        txt = arq.read_text(encoding="utf-8")
    except OSError:
        return None
    cab, _, corpo = txt.partition("\n---\n") if txt.startswith("---") else ("", "", txt)
    m = re.search(r'^description:\s*"?(.+?)"?\s*$', cab, re.M)
    fato = m.group(1) if m else next((p for p in corpo.split("\n\n") if len(p.strip()) > 40), "")
    fato = " ".join(fato.split())
    if len(fato) < 30:
        return None
    baixo = (cab + corpo[:600]).lower()
    kind = ("decisoria" if re.search(r"palavras do dono|dito pelo dono|decis[ãa]o do dono|o dono (pediu|mandou|decidiu)", baixo)
            else "procedural" if "type: reference" in baixo else "experiencial")
    return kind, f"{arq.stem}: {fato}"


def _valor(obj, caminho: str):
    for p in caminho.split("."):
        obj = obj[p] if isinstance(obj, dict) else obj[int(p)]
    return obj


def _descoberta_do_derivado(con: sqlite3.Connection, did: str, d: dict) -> None:
    """Derivado com `cerebro:` manda o número de manchete; se mudou desde o último envio, vai como correção."""
    c = d.get("cerebro")
    if not c:
        return
    try:
        obj = json.loads((RAIZ / c["arquivo"]).read_text(encoding="utf-8"))
        partes = [f"{rot} = {_valor(obj, cam)}" for rot, cam in c["campos"].items()]
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return                                          # sem leitura do resumo não há o que afirmar
    cerebro.registrar(f"derivado:{did}", f"{d['nome']} (JFN, {c['arquivo']}) — " + "; ".join(partes)
                      + f". {c.get('ressalva', 'Contagem da rotina; indício interno, não acusação.')}",
                      "semantica", c.get("assunto", d["nome"]), con=con)


def descobertas_sql(con: sqlite3.Connection, cfg: dict) -> int:
    """Blocos `cerebro:` do topo do yaml: consultas (só leitura) cujas linhas são descobertas VERIFICADAS.
    `funcao: "modulo:nome"` no lugar de `sql` = a função recebe a conexão só-leitura e devolve (chave, texto, assunto)
    já prontos (texto que não cabe num `format` — ex.: alertas de emendas com o nome do parlamentar)."""
    n = 0
    for b in cfg["cerebro"]:
        try:
            src = sqlite3.connect(f"file:{RAIZ / b.get('db', 'data/compliance.db')}?mode=ro", uri=True, timeout=20)
            src.row_factory = sqlite3.Row
            try:
                if b.get("funcao"):
                    mod, _, nome = b["funcao"].partition(":")
                    prontas = getattr(__import__(mod, fromlist=[nome]), nome)(src)
                else:
                    linhas = [dict(r) for r in src.execute(b["sql"])]
            finally:
                src.close()
        except sqlite3.Error as exc:
            con.execute("INSERT OR REPLACE INTO meta(k, v) VALUES (?,?)", (f"cerebro_erro:{b['id']}", str(exc)[:300]))
            con.commit()
            continue
        if b.get("funcao"):
            for chave, texto, assunto in prontas:
                n += cerebro.registrar(chave, texto, b.get("kind", "semantica"), assunto, con=con) in ("novo", "corrigido")
            continue
        for r in linhas:
            limpo = {k: ("" if v is None else v) for k, v in r.items()}
            st = cerebro.registrar(b["chave"].format(**limpo), b["texto"].format(**limpo), b.get("kind", "semantica"),
                                   b.get("assunto", "").format(**limpo) or None, con=con)
            n += st in ("novo", "corrigido")
    return n


# ───────────────────────────── execução ─────────────────────────────
def _log_do(did: str) -> Path:
    (DATA / "propagacao").mkdir(parents=True, exist_ok=True)
    return DATA / "propagacao" / f"{did}.log"


def trava_da_tarefa(did: str, d: dict) -> Path:
    """Trava (flock) POR TAREFA, a mesma que o cron-rede usa (`flock -n <arquivo> comando`).

    15/11/2026 00:45: o despachante lançou `vinculo_ob_contrato regra --gravar` enquanto a rodada do cron das
    00:30 ainda gravava na mesma tabela — dois gravadores, carga 20. A trava do ciclo (`.propagacao.lock`) só
    serializa ciclos entre si; quem roda fora dele (cron, mão) precisa de uma trava por tarefa."""
    t = d.get("trava")
    if t:
        return Path(t) if os.path.isabs(t) else RAIZ / t
    return DATA / "locks" / f"{did}.lock"


def _trava_ocupada(did: str, d: dict) -> bool:
    """`trava_externa` = trava que a PRÓPRIA tarefa segura por dentro (ex.: território): só consultada, nunca
    segurada pelo despachante — se ele a segurasse, a tarefa veria a trava ocupada e sairia sem rodar."""
    if d.get("tipo") == "cache":
        return False
    caminhos = [trava_da_tarefa(did, d)]
    if d.get("trava_externa"):
        t = d["trava_externa"]
        caminhos.append(Path(t) if os.path.isabs(t) else RAIZ / t)
    for caminho in caminhos:
        if not caminho.exists():
            continue
        with caminho.open("a") as fh:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(fh, fcntl.LOCK_UN)
    return False


def _rodar_comando(did: str, d: dict) -> tuple[bool, str | None]:
    argv = [a.replace("{py}", str(RAIZ / ".venv" / "bin" / "python")) for a in d["comando"]]
    env = dict(os.environ, PYTHONPATH=str(RAIZ), HOME=os.path.expanduser("~"))
    env.update({k: str(v) for k, v in (d.get("env") or {}).items()})
    inicio = time.time()
    caminho = trava_da_tarefa(did, d)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    trava = caminho.open("a")
    try:
        fcntl.flock(trava, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        trava.close()
        return False, f"já rodando fora do despachante (trava {caminho.name} ocupada)"
    try:
        return _rodar_comando_travado(did, d, argv, env, inicio, trava)
    finally:
        trava.close()


def _rodar_comando_travado(did, d, argv, env, inicio, trava, fds_extra=()) -> tuple[bool, str | None]:
    with _log_do(did).open("ab") as log:
        log.write(f"\n== {time.strftime('%F %T')} {' '.join(argv)}\n".encode())
        log.flush()
        # o filho HERDA o descritor da trava (pass_fds): se este ciclo morrer, a trava segue com a tarefa viva
        p = subprocess.Popen(["nice", "-n", "15", *argv], cwd=RAIZ, env=env, stdout=log, stderr=subprocess.STDOUT,
                             start_new_session=True, pass_fds=(trava.fileno(), *fds_extra))
        try:
            rc = p.wait(timeout=int(d.get("timeout_s", 1800)))
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(p.pid, signal.SIGTERM)
            with contextlib.suppress(subprocess.TimeoutExpired):
                p.wait(timeout=20)
            if p.poll() is None:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(p.pid, signal.SIGKILL)
            return False, f"estourou o teto de {d.get('timeout_s', 1800)} s"
    if rc != 0:
        return False, f"saiu com código {rc} (ver data/propagacao/{did}.log)"
    ef = d.get("efeito") or {}
    if ef.get("arquivo"):
        try:
            if (RAIZ / ef["arquivo"]).stat().st_mtime < inicio - 2:
                return False, f"rodou sem efeito: {ef['arquivo']} não foi regravado (outra execução com a trava?)"
        except OSError:
            return False, f"rodou sem efeito: {ef['arquivo']} não existe"
    return True, None


_RX_CACHE = re.compile(rb'^\{"k": "((?:[^"\\]|\\.)*)", "t": ([0-9.]+)')


def _cache_renovado(prefixo: str, desde: float) -> bool:
    for f in (DATA / "cache_painel").glob("*.json"):
        try:
            with f.open("rb") as fh:
                m = _RX_CACHE.match(fh.read(400))
        except OSError:
            continue
        if m and json.loads(b'"' + m.group(1) + b'"').startswith(prefixo) and float(m.group(2)) >= desde:
            return True
    return False


def _rodar_cache(did: str, d: dict) -> tuple[bool, str | None]:
    """Vence as chaves do cache do painel (marca em `_invalidar.json`) e pede as rotas, UMA por vez: o painel
    entrega o valor anterior na hora e recalcula em 2º plano (SWR). Efeito = a chave regravada em disco."""
    pasta = DATA / "cache_painel"
    pasta.mkdir(parents=True, exist_ok=True)
    marca_arq, agora = pasta / "_invalidar.json", time.time()
    try:
        marcas = json.loads(marca_arq.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        marcas = {}
    marcas.update({p: agora for p in d["prefixos"]})
    tmp = marca_arq.with_suffix(".tmp")
    tmp.write_text(json.dumps(marcas), encoding="utf-8")
    tmp.replace(marca_arq)
    falhas, teto = [], int(d.get("espera_s", 240))
    for url, prefixo in d["urls"].items():
        try:
            with urllib.request.urlopen(f"{BASE_PAINEL}/api/{url}", timeout=teto) as r:
                r.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            falhas.append(f"{url}: {type(exc).__name__}")
            continue
        limite = time.time() + teto
        while not _cache_renovado(prefixo, agora) and time.time() < limite:
            time.sleep(3)
        if not _cache_renovado(prefixo, agora):
            falhas.append(f"{url}: chave '{prefixo}' não foi regravada em {teto} s")
    return (not falhas), ("; ".join(falhas)[:380] if falhas else None)


def _sujos(con: sqlite3.Connection, derivados=()) -> dict[str, dict]:
    """Derivados com pendência. `primeiro_fonte` (base da janela de junção) só conta evento de FONTE: o evento
    "derivado X recalculado" não abre janela — sem isso cada elo da cadeia esperaria um ciclo à toa."""
    ids = list(derivados)
    marca = ",".join("?" * len(ids)) or "''"
    return {d: {"primeiro": p, "primeiro_fonte": pf or 0.0, "n": n, "max_id": m} for d, p, pf, n, m in con.execute(
        f"SELECT p.derivado, MIN(e.quando), MIN(CASE WHEN e.fonte IN ({marca}) THEN NULL ELSE e.quando END), "
        "COUNT(*), MAX(e.id) FROM pendencia p JOIN evento e ON e.id=p.evento_id GROUP BY p.derivado", ids)}


def _motivos(con: sqlite3.Connection, did: str, limite: int = 6) -> list[str]:
    return [f"{f}: {t}" for f, t in con.execute(
        "SELECT e.fonte, e.detalhe FROM pendencia p JOIN evento e ON e.id=p.evento_id "
        "WHERE p.derivado=? ORDER BY e.id DESC LIMIT ?", (did, limite))]


def _linha(con: sqlite3.Connection, did: str) -> dict:
    con.execute("INSERT OR IGNORE INTO derivado(id) VALUES (?)", (did,))
    cur = con.execute("SELECT * FROM derivado WHERE id=?", (did,))
    return dict(zip([c[0] for c in cur.description], cur.fetchone()))


def _carga_efetiva(c) -> float:
    """Maior entre a carga de 1 min e a de 5 min (15/11/2026): um mergulho momentâneo da carga de 1 min abaixo do
    teto liberava tarefa pesada com a média em 20."""
    return max(c[0], c[1]) if len(c) > 1 else c[0]


def _memoria_disponivel_mb() -> float:
    with contextlib.suppress(OSError, ValueError):
        for ln in Path("/proc/meminfo").read_text().splitlines():
            if ln.startswith("MemAvailable:"):
                return int(ln.split()[1]) / 1024
    return 0.0


def _pedir_vez_pesado(did: str) -> None:
    (DATA / "locks").mkdir(exist_ok=True)
    tmp = DATA / "locks" / "pesado_vm1.pedido.tmp"
    tmp.write_text(json.dumps({"derivado": did, "quando": time.time()}), encoding="utf-8")
    tmp.replace(DATA / "locks" / "pesado_vm1.pedido")


def _retirar_pedido_pesado() -> None:
    with contextlib.suppress(FileNotFoundError):
        (DATA / "locks" / "pesado_vm1.pedido").unlink()


def _semaforo_pesado():
    """Semáforo ÚNICO de trabalho pesado da VM-1, dividido com os crons pesados (`tools/pesado.sh`) — 23/11/2026:
    5 pesados ao mesmo tempo com swap 100% (o "um pesado por ciclo" não via os crons). Devolve o arquivo com a
    trava tomada (o chamador solta) ou None se outro pesado a segura."""
    (DATA / "locks").mkdir(exist_ok=True)
    fh = open(DATA / "locks" / "pesado_vm1.lock", "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.close()
        return None
    return fh


def _concluir(con: sqlite3.Connection, cfg: dict, did: str, d: dict, max_id: int, inicio: float,
              motivos: list[str], ok: bool, erro: str | None) -> None:
    """Registro do fim de uma execução (no ciclo ou no processo destacado): limpa só as pendências que existiam no
    início, marca o estado, recua em falha e emite o evento para os dependentes."""
    fim = time.time()
    if ok:
        con.execute("DELETE FROM pendencia WHERE derivado=? AND evento_id<=?", (did, max_id))
        con.execute("UPDATE derivado SET ultimo_fim=?, ultimo_estado='ok', ultimo_erro=NULL, falhas=0, pid=NULL, "
                    "proxima_tentativa=NULL, execucoes=execucoes+1 WHERE id=?", (fim, did))
        con.commit()
        emitir(con, cfg, did, f"recalculado em {fim - inicio:.0f} s")
        _descoberta_do_derivado(con, did, d)
    else:
        falhas = _linha(con, did)["falhas"] + 1
        con.execute("UPDATE derivado SET ultimo_fim=?, ultimo_estado='falhou', ultimo_erro=?, falhas=?, pid=NULL, "
                    "proxima_tentativa=?, execucoes=execucoes+1 WHERE id=?",
                    (fim, erro, falhas, fim + min(RECUO_BASE_S * 2 ** (falhas - 1), RECUO_MAX_S), did))
    con.execute("INSERT INTO execucao(derivado, inicio, fim, estado, motivos, erro) VALUES (?,?,?,?,?,?)",
                (did, inicio, fim, "ok" if ok else "falhou", json.dumps(motivos, ensure_ascii=False), erro))
    con.commit()


def _pid_vivo(pid: int | None, did: str) -> bool:
    """O PID ainda é o NOSSO filho (`propagacao executar <did>`)? PID reaproveitado por outro processo = morto."""
    if not pid:
        return False
    try:
        cmd = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except OSError:
        return False
    return b"executar" in cmd and did.encode() in cmd


def _rodando_destacado(con: sqlite3.Connection, cfg: dict) -> set[str]:
    """Derivados com filho destacado VIVO. Filho morto sem registrar o fim = falha registrada (com recuo, sem
    relançar no mesmo ciclo) — 24/11/2026."""
    vivos = set()
    for did, pid, ini in con.execute("SELECT id, pid, ultimo_inicio FROM derivado WHERE ultimo_estado='rodando' "
                                     "AND pid IS NOT NULL").fetchall():
        if _pid_vivo(pid, did):
            vivos.add(did)
        elif did in cfg["derivados"]:
            # relê ANTES de declarar a morte: entre o SELECT e o teste do PID o filho pode ter gravado o próprio fim e
            # saído (26/11/2026: «código 1» virava «morreu sem registrar o fim» — o teste «instável» do portão)
            ainda = con.execute("SELECT 1 FROM derivado WHERE id=? AND ultimo_estado='rodando' AND pid=?",
                                (did, pid)).fetchone()
            if ainda:
                _concluir(con, cfg, did, cfg["derivados"][did], -1, ini or time.time(), [], False,
                          f"processo destacado (pid {pid}) morreu sem registrar o fim")
    return vivos


def _lancar_destacado(con: sqlite3.Connection, did: str, d: dict, max_id: int, inicio: float, semaforo) -> int:
    """Pesado DESTACADO (24/11/2026): um pesado de até 1 h segurava o ciclo inteiro — nenhum leve andava e o estado
    aparecia PARADO. O filho (sessão própria) herda o semáforo de pesado e a trava da tarefa, roda, registra o fim
    e emite o evento; o ciclo segue com os leves. Devolve o PID."""
    trava_arq = trava_da_tarefa(did, d)
    trava_arq.parent.mkdir(parents=True, exist_ok=True)
    trava = trava_arq.open("a")
    try:
        fcntl.flock(trava, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        trava.close()
        raise OSError(f"trava {trava_arq.name} ocupada") from None
    db = con.execute("PRAGMA database_list").fetchone()[2]
    fds = ((semaforo.fileno(),) if semaforo is not None else ()) + (trava.fileno(),)
    env = dict(os.environ, PYTHONPATH=str(RAIZ), JFN_DATA_DIR=str(DATA), JFN_PROPAGACAO_YAML=str(CONFIG))
    try:
        with _log_do(did).open("ab") as log:
            p = subprocess.Popen([sys.executable, "-m", "compliance_agent.propagacao", "executar", did,
                                  "--max-id", str(max_id), "--inicio", repr(inicio), "--db", db,
                                  "--fds", ",".join(map(str, fds))],
                                 cwd=RAIZ, env=env, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                 start_new_session=True, pass_fds=fds)
    finally:
        trava.close()                                    # o filho segura a sua cópia
    return p.pid


def executar_destacado(did: str, max_id: int, inicio: float, db: Path, fds: tuple[int, ...]) -> int:
    """Corpo do processo destacado (`python -m compliance_agent.propagacao executar …`)."""
    cfg = carregar()
    d = cfg["derivados"][did]
    con = conectar(db)
    try:
        motivos = _motivos(con, did)
        try:
            if d.get("tipo") == "cache":
                ok, erro = _rodar_cache(did, d)
            else:
                argv = [a.replace("{py}", str(RAIZ / ".venv" / "bin" / "python")) for a in d["comando"]]
                env = dict(os.environ, PYTHONPATH=str(RAIZ), HOME=os.path.expanduser("~"))
                env.update({k: str(v) for k, v in (d.get("env") or {}).items()})
                ok, erro = _rodar_comando_travado(did, d, argv, env, inicio, type("T", (), {"fileno": lambda _s: fds[-1]})(),
                                                  fds_extra=fds[:-1])
        except (OSError, subprocess.SubprocessError, ValueError, KeyError) as exc:
            ok, erro = False, f"{type(exc).__name__}: {exc}"[:300]
        _concluir(con, cfg, did, d, max_id, inicio, motivos, ok, erro)
        return 0 if ok else 1
    finally:
        con.close()


def _deploy_em_curso() -> bool:
    """`tools/deploy_pos_commit.sh` reiniciando o painel (24/11/2026: painel_sancoes e painel_prefeitura falharam com
    URLError às 09:49, no meio do restart). Marca com mais de 10 min = deploy que morreu; não segura mais nada."""
    try:
        return time.time() - (DATA / ".deploy_em_curso").stat().st_mtime < 600
    except OSError:
        return False


def _motivo_ritmo(tarefa: str) -> str | None:
    """Guarda ÚNICO de LLM do despachante (dono, 24/11/2026: "sim, dentro do ritmo"): derivado com `ritmo: <tarefa>`
    só roda se o governador da assinatura deixar (`llm/contingencia.motivo_bloqueio`, que lê `llm/ritmo_assinatura`
    e o teto diário do motor). Não deixou = espera; leitura que falha = espera (nunca fura o teto)."""
    try:
        from compliance_agent.llm import contingencia
        return contingencia.motivo_bloqueio(tarefa)
    except (ImportError, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:   # falha do guarda fecha a porta
        return f"guarda de ritmo ilegível ({type(exc).__name__})"


def _teto_carga(peso: str, sujo_ha: float, slo: float, memoria) -> float:
    if sujo_ha >= slo and memoria() >= MEMORIA_MIN_ATRASADO_MB:
        return CARGA_TETO_ATRASADO
    return CARGA_MAX[peso] if sujo_ha < CARGA_PACIENCIA_S else CARGA_TETO_FINAL[peso]


def despachar(con: sqlite3.Connection, cfg: dict, carga=os.getloadavg, executar=None,
              memoria=_memoria_disponivel_mb, destacar=None, ritmo=_motivo_ritmo) -> list[dict]:
    """Recalcula o que está sujo e elegível. Devolve o que fez neste ciclo. Pesado sem `executar` injetado roda
    DESTACADO (`destacar`, padrão `_lancar_destacado`): o ciclo segue com os leves."""
    t0, feitos, pesado_feito = time.time(), [], False
    ders = cfg["derivados"]
    destacar = destacar or (None if executar else _lancar_destacado)
    while time.time() - t0 < ORCAMENTO_CICLO_S:
        sujos, agora, escolhido, semaforo = _sujos(con, ders), time.time(), None, None
        rodando = _rodando_destacado(con, cfg)
        # motivo de quem já foi avaliado NESTA passada: o dependente só espera um derivado que pode rodar agora.
        # 24/11/2026: perícia, certeza, juiz e retratos ficavam 10–40 h "aguardando derivado de que depende" atrás
        # de um pesado que o semáforo ou a carga seguravam — o relógio dele estava livre, ele não.
        barrado: dict[str, str] = {}
        ordem = sorted((i for i in sujos if i in ders), key=lambda i: (ders[i].get("prioridade", 5), sujos[i]["primeiro"]))
        def relogio(did: str) -> str | None:
            """Motivo PRÓPRIO do derivado para ainda não rodar (janela de junção, recuo, intervalo) — ou None."""
            d, s, lin = ders[did], sujos[did], _linha(con, did)
            # janela de JUNÇÃO contada do 1º evento de fonte pendente — não "silêncio da fonte": captura SEI, dreno
            # do SIAFE e análise emitem a cada poucos minutos e um silêncio nunca chegaria (medido em 14/11/2026:
            # 3 ciclos seguidos sem recalcular nada). Quem limita a frequência é o `intervalo_min_s`.
            if agora - s["primeiro_fonte"] < d.get("debounce_s", 120):
                return "juntando eventos da fonte"
            if lin["proxima_tentativa"] and agora < lin["proxima_tentativa"]:
                return f"recuo após {lin['falhas']} falha(s)"
            # rodada FORA do despachante (o cron que ficou como rede) também conta: ela regravou o arquivo de efeito
            ultimo = lin["ultimo_fim"] or 0.0
            if (d.get("efeito") or {}).get("arquivo"):
                with contextlib.suppress(OSError):
                    ultimo = max(ultimo, (RAIZ / d["efeito"]["arquivo"]).stat().st_mtime)
            if ultimo and agora - ultimo < d.get("intervalo_min_s", 0):
                return "intervalo mínimo entre execuções"
            return None

        for did in ordem:
            d, s = ders[did], sujos[did]
            peso = d.get("peso", "leve")
            if any(x["id"] == did for x in feitos):
                continue                                # um derivado roda no máximo uma vez por ciclo
            motivo = relogio(did)
            if did in rodando:
                motivo = "rodando destacado (processo próprio)"
            elif motivo:
                pass
            # só espera o derivado de que depende se ESSE está pronto para rodar; se ele ainda junta eventos ou
            # está no intervalo mínimo, este roda já e será sujo de novo quando o outro terminar
            elif any(dep in rodando for dep in d.get("depende", [])) or any(
                    dep in sujos and dep in ders and relogio(dep) is None and dep not in barrado
                    and not any(x["id"] == dep for x in feitos) for dep in d.get("depende", [])):
                motivo = "aguardando derivado de que depende"
            elif _trava_ocupada(did, d):
                motivo = "já rodando fora do despachante (cron ou à mão)"
            elif d.get("tipo") == "cache" and _deploy_em_curso():
                motivo = "painel reiniciando (deploy em curso)"
            elif d.get("ritmo") and (r := ritmo(d["ritmo"])):
                motivo = f"ritmo: {r}"[:300]
            elif peso == "pesado" and pesado_feito:
                motivo = "um pesado por ciclo"
            elif (c := _carga_efetiva(carga())) > (
                    teto := _teto_carga(peso, agora - s["primeiro"], slo_s(d, cfg), memoria)):
                motivo = f"carga {c:.1f} acima do teto {teto:.0f}"
            elif peso == "pesado" and (semaforo := _semaforo_pesado()) is None:
                motivo = "semáforo de pesado da VM-1 ocupado (cron pesado rodando)"
                if agora - s["primeiro"] >= CARGA_PACIENCIA_S and not rodando:   # o próprio filho não pede a vez
                    _pedir_vez_pesado(did)
                    motivo += " — vez pedida ao pesado.sh"
            if motivo and motivo not in ("um pesado por ciclo", "aguardando derivado de que depende",
                                         "rodando destacado (processo próprio)") and relogio(did) is None:
                barrado[did] = motivo               # barrado por fora (carga, semáforo, trava) — não pelo relógio
            con.execute("UPDATE derivado SET adiado=? WHERE id=?", (motivo, did))
            if motivo is None:
                escolhido = did
                break
        con.commit()
        if escolhido is None:
            break
        did, d, s = escolhido, ders[escolhido], sujos[escolhido]
        if semaforo is not None:
            _retirar_pedido_pesado()
        motivos, inicio = _motivos(con, did), time.time()
        con.execute("UPDATE derivado SET ultimo_inicio=?, ultimo_estado='rodando', adiado=NULL WHERE id=?", (inicio, did))
        con.commit()
        if destacar and ((d.get("peso") == "pesado" and semaforo is not None) or d.get("destacado")):
            try:
                pid = destacar(con, did, d, s["max_id"], inicio, semaforo)
            except (OSError, subprocess.SubprocessError) as exc:
                _concluir(con, cfg, did, d, s["max_id"], inicio, motivos, False, f"não lançou: {exc}"[:300])
                feitos.append({"id": did, "ok": False, "erro": str(exc)[:200], "segundos": 0.0})
            else:
                con.execute("UPDATE derivado SET pid=? WHERE id=?", (pid, did))
                con.commit()
                feitos.append({"id": did, "destacado": True, "pid": pid})
            finally:
                if semaforo is not None:
                    semaforo.close()             # SEM unlock: o filho herdou a trava; só esta cópia fecha
            pesado_feito = pesado_feito or d.get("peso") == "pesado"
            continue
        rodar = executar or (_rodar_cache if d.get("tipo") == "cache" else _rodar_comando)
        try:
            ok, erro = rodar(did, d)
        except (OSError, subprocess.SubprocessError, ValueError, KeyError) as exc:
            ok, erro = False, f"{type(exc).__name__}: {exc}"[:300]
        finally:
            if semaforo is not None:
                fcntl.flock(semaforo, fcntl.LOCK_UN)
                semaforo.close()
        pesado_feito = pesado_feito or d.get("peso") == "pesado"
        # só saem as pendências que existiam quando começou: evento que chegou durante o cálculo fica
        _concluir(con, cfg, did, d, s["max_id"], inicio, motivos, ok, erro)
        fim = time.time()
        feitos.append({"id": did, "ok": ok, "erro": erro, "segundos": round(fim - inicio, 1)})
    return feitos


def ciclo(cfg: dict | None = None, db: Path | None = None) -> dict:
    """Um ciclo completo sob trava de arquivo. Trava ocupada = outro ciclo trabalhando; sai sem fazer nada.

    SUBSTITUÍDO (O2.3): o motor de fluxo faz o despacho; este ciclo só existe como desfazer da religação (O9.0) e
    sai na O9.1. Paridade: `ponte_fluxo` (abaixo) faz o resto do que este ciclo fazia."""
    print("propagação: AVISO — `ciclo` foi substituído pelo motor de fluxo (O2.3); rodando como DESFAZER da "
          "religação. O caminho vigente é `ponte-fluxo` + jfn-fluxo.", file=sys.stderr)
    cfg = cfg or carregar()
    erros = validar(cfg)
    if erros:
        raise ValueError("config/propagacao.yaml inválido: " + "; ".join(erros))
    DATA.mkdir(parents=True, exist_ok=True)
    trava = open(DATA / ".propagacao.lock", "w")
    try:
        fcntl.flock(trava, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return {"ocupado": True}
    con = conectar(db)
    try:
        t0 = time.time()
        eventos = sondar(con, cfg)
        feitos = despachar(con, cfg)
        achados = descobertas_sql(con, cfg)
        envio = cerebro.enviar_pendentes(con=con)
        con.execute("DELETE FROM evento WHERE id < (SELECT MAX(id) FROM evento) - ? "
                    "AND id NOT IN (SELECT evento_id FROM pendencia)", (EVENTOS_GUARDADOS,))
        con.execute("DELETE FROM execucao WHERE id < (SELECT MAX(id) FROM execucao) - 2000")
        r = {"quando": time.time(), "segundos": round(time.time() - t0, 1), "eventos": eventos, "feitos": feitos,
             "descobertas": achados, "cerebro": envio, "carga": round(os.getloadavg()[0], 2)}
        con.execute("INSERT OR REPLACE INTO meta(k, v) VALUES ('ultimo_ciclo', ?)", (json.dumps(r, ensure_ascii=False),))
        con.commit()
        return r
    finally:
        con.close()
        trava.close()


CHAVE_PONTE = "fluxo_ultimo_evento"


def ponte_fluxo(cfg: dict | None = None, db: Path | None = None, con_fluxo=None) -> dict:
    """O `ciclo` sem o despachante (O2.3): sondas das fontes, descobertas → cérebro, envio ao cérebro e poda — e
    cada evento novo do `propagacao.db` (sonda OU `avisar` do produtor) é ENTREGUE ao `fluxo.eventos`, de onde o
    planejador suja os derivados (config/fluxo.yaml). Mesma trava do `ciclo`: os dois nunca rodam juntos.

    Entrega pelo marcador `meta.fluxo_ultimo_evento` (id do último evento entregue), gravado DEPOIS do PG: queda no
    meio reentrega — o evento repetido cai no mesmo job (chave do dependente), não duplica trabalho. Primeira rodada
    sem marcador começa do evento mais novo: o histórico antigo não vira rajada (a lacuna da parada é recuperada pela
    religação, E1 com `desde`). As pendências do despachante não são tocadas: no desfazer ele as encontra."""
    cfg = cfg or carregar()
    erros = validar(cfg)
    if erros:
        raise ValueError("config/propagacao.yaml inválido: " + "; ".join(erros))
    DATA.mkdir(parents=True, exist_ok=True)
    trava = open(DATA / ".propagacao.lock", "w")
    try:
        fcntl.flock(trava, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        trava.close()
        return {"ocupado": True}
    con = conectar(db)
    proprio = con_fluxo is None
    try:
        t0 = time.time()
        eventos = sondar(con, cfg)
        achados = descobertas_sql(con, cfg)
        envio = cerebro.enviar_pendentes(con=con)
        marca = con.execute("SELECT v FROM meta WHERE k = ?", (CHAVE_PONTE,)).fetchone()
        maximo = con.execute("SELECT COALESCE(MAX(id), 0) FROM evento").fetchone()[0]
        desde = int(marca[0]) if marca else maximo - eventos      # 1ª rodada: só o que esta sonda acabou de ver
        novos = con.execute("SELECT id, fonte, quando, detalhe FROM evento WHERE id > ? ORDER BY id",
                            (desde,)).fetchall()
        if novos:
            from compliance_agent.fluxo import fila
            if proprio:
                con_fluxo = fila.conectar()
            with con_fluxo.transaction():
                for eid, fonte, quando, det in novos:
                    fila.emitir(con_fluxo, fonte, "mudou", None,
                                {"detalhe": (det or "")[:400], "propagacao_id": eid, "quando": quando})
        ultimo = novos[-1][0] if novos else max(desde, 0)
        con.execute("INSERT OR REPLACE INTO meta(k, v) VALUES (?, ?)", (CHAVE_PONTE, str(ultimo)))
        con.execute("DELETE FROM evento WHERE id < (SELECT MAX(id) FROM evento) - ? "
                    "AND id NOT IN (SELECT evento_id FROM pendencia) AND id <= ?", (EVENTOS_GUARDADOS, ultimo))
        con.commit()
        return {"ponte_fluxo": {"sondados": eventos, "entregues": len(novos), "ultimo": ultimo},
                "descobertas": achados, "cerebro": envio, "segundos": round(time.time() - t0, 1)}
    finally:
        if proprio and con_fluxo is not None:
            con_fluxo.close()
        con.close()
        trava.close()


# ───────────────────────────── leitura (painel) ─────────────────────────────
def estado(cfg: dict | None = None, db: Path | None = None) -> dict:
    """Fotografia para o painel. Só leitura; base ausente = INDISPONÍVEL (o despachante nunca rodou)."""
    cfg = cfg or carregar()
    alvo = db or DATA / "propagacao.db"
    if not alvo.exists():
        return {"ok": False, "estado": "INDISPONIVEL", "motivo": "o despachante de propagação ainda não rodou nesta máquina"}
    con = sqlite3.connect(f"file:{alvo}?mode=ro", uri=True, timeout=10)
    try:
        agora = time.time()
        m = con.execute("SELECT v FROM meta WHERE k='ultimo_ciclo'").fetchone()
        ult = json.loads(m[0]) if m else None
        sujos = _sujos(con)
        sondas = {f: {"visto_em": v, "mudou_em": mu, "erro": e} for f, v, mu, e in
                  con.execute("SELECT fonte, visto_em, mudou_em, erro FROM sonda")}
        linhas = {r[0]: r for r in con.execute(
            "SELECT id, ultimo_inicio, ultimo_fim, ultimo_estado, ultimo_erro, falhas, proxima_tentativa, adiado, execucoes FROM derivado")}
        ders, atrasados = [], []
        for did, d in cfg["derivados"].items():
            ln, s = linhas.get(did), sujos.get(did)
            slo = slo_s(d, cfg)
            sujo_ha = (agora - s["primeiro"]) if s else None
            if sujo_ha is not None and sujo_ha > slo:
                atrasados.append({"id": did, "nome": d["nome"], "sujo_ha_h": round(sujo_ha / 3600, 1),
                                  "slo_h": round(slo / 3600, 1), "peso": d.get("peso", "leve"),
                                  "adiado": ln[7] if ln else None})
            ders.append({
                "id": did, "nome": d["nome"], "onde": d.get("onde"), "peso": d.get("peso", "leve"),
                "tipo": d.get("tipo", "comando"), "depende": d.get("depende", []), "antes": d.get("antes"),
                "sujo": bool(s), "sujo_desde": s["primeiro"] if s else None, "eventos_pendentes": s["n"] if s else 0,
                "motivos": _motivos(con, did, 4) if s else [],
                "ultimo_inicio": ln[1] if ln else None, "ultimo_fim": ln[2] if ln else None,
                "ultimo_estado": ln[3] if ln else None, "ultimo_erro": ln[4] if ln else None,
                "falhas": ln[5] if ln else 0, "proxima_tentativa": ln[6] if ln else None,
                "adiado": ln[7] if ln else None, "execucoes": ln[8] if ln else 0,
                "slo_s": slo, "atrasado": bool(sujo_ha is not None and sujo_ha > slo)})
        atrasados.sort(key=lambda x: -x["sujo_ha_h"])
        fontes = [{"id": fid, "nome": f["nome"], "manual": not any(t in (f.get("sonda") or {}) for t in _SONDAS),
                   "alimenta": dependentes(cfg, fid), **(sondas.get(fid) or {"visto_em": None, "mudou_em": None, "erro": None})}
                  for fid, f in cfg["fontes"].items()]
        eventos = [{"id": i, "fonte": f, "quando": q, "detalhe": t} for i, f, q, t in
                   con.execute("SELECT id, fonte, quando, detalhe FROM evento ORDER BY id DESC LIMIT 40")]
        execs = [{"derivado": d, "inicio": i, "fim": f, "estado": e, "motivos": json.loads(mo or "[]"), "erro": er}
                 for d, i, f, e, mo, er in con.execute(
                     "SELECT derivado, inicio, fim, estado, motivos, erro FROM execucao ORDER BY id DESC LIMIT 30")]
        cer = cerebro.resumo(con)
        parado = ult is None or agora - ult["quando"] > 20 * 60
        # "ok" só com o ciclo vivo E nenhum derivado além do SLO; ATRASADO traz a lista (não basta o despachante girar)
        return {"ok": True, "estado": "PARADO" if parado else "ATRASADO" if atrasados else "ok", "gerado_em": agora,
                "ultimo_ciclo": ult, "derivados": ders, "atrasados": atrasados, "fontes": fontes, "eventos": eventos,
                "execucoes": execs, "cerebro": cer,
                "resumo": {"derivados": len(ders), "sujos": sum(1 for x in ders if x["sujo"]), "atrasados": len(atrasados),
                           "com_falha": sum(1 for x in ders if x["ultimo_estado"] == "falhou"),
                           "fontes": len(fontes), "fontes_com_erro": sum(1 for x in fontes if x["erro"])}}
    finally:
        con.close()


def mapa_md(cfg: dict | None = None) -> str:
    cfg = cfg or carregar()
    nome = lambda x: (cfg["fontes"].get(x) or cfg["derivados"].get(x) or {}).get("nome", x)  # noqa: E731
    out = ["| Fonte / evento | Como é percebida | Derivados que ficam velhos |", "|---|---|---|"]
    for fid, f in cfg["fontes"].items():
        s = f.get("sonda") or {}
        tipo = next((t for t in _SONDAS if t in s), "manual (`emitir`)")
        out.append(f"| {f['nome']} | {tipo} | {', '.join(nome(d) for d in dependentes(cfg, fid)) or '—'} |")
    out += ["", "| Derivado | Onde aparece | Depende de | Antes (agenda própria) | Peso |", "|---|---|---|---|---|"]
    for d in cfg["derivados"].values():
        out.append(f"| {d['nome']} | {d.get('onde', '—')} | {', '.join(nome(x) for x in d.get('depende', []))} | "
                   f"{d.get('antes', '—')} | {d.get('peso', 'leve')} |")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Propagação automática do JFN")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ciclo")
    sub.add_parser("ponte-fluxo")
    sub.add_parser("estado")
    sub.add_parser("mapa")
    ex = sub.add_parser("executar")          # corpo do pesado destacado (lançado pelo despachante, não à mão)
    ex.add_argument("alvo")
    ex.add_argument("--max-id", type=int, required=True)
    ex.add_argument("--inicio", type=float, required=True)
    ex.add_argument("--db", required=True)
    ex.add_argument("--fds", required=True)
    for nome in ("emitir", "sujar"):
        p = sub.add_parser(nome)
        p.add_argument("alvo")
        p.add_argument("detalhe")
    a = ap.parse_args(argv)
    if a.cmd == "executar":
        return executar_destacado(a.alvo, a.max_id, a.inicio, Path(a.db), tuple(int(x) for x in a.fds.split(",")))
    cfg = carregar()
    if a.cmd == "ciclo":
        r = ciclo(cfg)
        print(time.strftime("%F %T"), json.dumps(r, ensure_ascii=False), flush=True)
        return 0
    if a.cmd == "ponte-fluxo":
        r = ponte_fluxo(cfg)
        print(time.strftime("%F %T"), json.dumps(r, ensure_ascii=False, default=str), flush=True)
        return 0
    if a.cmd == "estado":
        print(json.dumps(estado(cfg), ensure_ascii=False, indent=1))
        return 0
    if a.cmd == "mapa":
        print(mapa_md(cfg))
        return 0
    con = conectar()
    try:
        if a.cmd == "emitir":
            if a.alvo not in cfg["fontes"]:
                print(f"fonte desconhecida: {a.alvo} (ver config/propagacao.yaml)", file=sys.stderr)
                return 2
            eid = emitir(con, cfg, a.alvo, a.detalhe)
            print(f"evento {eid}: sujou {dependentes(cfg, a.alvo)}")
        else:
            if a.alvo not in cfg["derivados"]:
                print(f"derivado desconhecido: {a.alvo}", file=sys.stderr)
                return 2
            eid = con.execute("INSERT INTO evento(fonte, quando, detalhe) VALUES ('manual', ?, ?)",
                              (time.time(), a.detalhe[:400])).lastrowid
            con.execute("INSERT OR IGNORE INTO pendencia(derivado, evento_id) VALUES (?,?)", (a.alvo, eid))
            con.commit()
            print(f"evento {eid}: {a.alvo} marcado como sujo")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
