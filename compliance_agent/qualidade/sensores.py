# -*- coding: utf-8 -*-
"""Sensores das regras de qualidade — rodam em PRODUÇÃO, sobre o que o dono de fato vê.

A catraca olha o código; o sensor olha o DADO servido: payload das rotas das manchetes, arquivos que alimentam
o painel, casos do vault, respostas do Yoda, estado dos motores, banco de cruzamento dos modelos.

Contrato (o mesmo do laço de automelhoria):
  · cada sensor recebe um `Ctx` e devolve a lista de violações AGORA (`violacao(...)`);
  · sensor que não consegue medir LEVANTA — `rodar()` registra `sensor:<nome>` como problema (CST-10:
    INDISPONÍVEL ≠ 0; sensor cego nunca vira "ok");
  · nenhum sensor escreve em banco de produção, chama modelo ou abre navegador; leitura de SQLite é só-leitura;
  · nenhuma violação carrega dado pessoal: trecho citado é curto e CPF sai mascarado pelo verificador.

`rodar()` grava `data/qualidade_estado.json` (a fotografia) e uma linha por HORA em
`data/qualidade_historico.jsonl` (a tendência) — rodar duas vezes na mesma hora não duplica (CST-06).
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import sqlite3
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

import yaml

from compliance_agent.qualidade import regras, verificadores as v

REPO = Path(__file__).resolve().parents[2]
_FALHAS = (OSError, ValueError, KeyError, TypeError, RuntimeError, sqlite3.Error, urllib.error.URLError)
API = os.environ.get("JFN_API", "http://127.0.0.1:8000")


def _dados() -> Path:
    return Path(os.environ.get("JFN_DADOS") or REPO / "data")


def _api(caminho: str, timeout: float = 25.0):
    """GET na API local do painel. Falha de rede/HTTP LEVANTA: quem chama decide se é cegueira ou violação."""
    with urllib.request.urlopen(API + caminho, timeout=timeout) as r:  # noqa: S310 — só 127.0.0.1
        return json.loads(r.read().decode("utf-8"))


@dataclass
class Ctx:
    dados: Path = field(default_factory=_dados)
    vault: Path = field(default_factory=lambda: Path(os.environ.get("JFN_VAULT") or Path.home() / "vault"))
    hermes: Path = field(default_factory=lambda: Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes"))
    hermes_agent: Path = field(default_factory=lambda: Path.home() / "hermes-agent")
    repo: Path = REPO
    api: Callable = _api
    agora: datetime = field(default_factory=datetime.now)
    _cache: dict = field(default_factory=dict)

    def inventario(self) -> dict:
        arq = self.repo / "config" / "qualidade_inventario.yaml"
        if "inv" not in self._cache:
            self._cache["inv"] = yaml.safe_load(arq.read_text(encoding="utf-8"))
        return self._cache["inv"]

    def manchetes(self) -> list[dict]:
        return [m for m in self.inventario().get("manchetes", []) if m.get("rota")]

    def payload(self, rota: str):
        """Payload de uma rota, uma vez por rodada. Guarda a exceção: 3 cards da mesma rota não a chamam 3 vezes."""
        if rota not in self._cache:
            try:
                self._cache[rota] = self.api(rota)
            except _FALHAS as e:
                self._cache[rota] = e
        if isinstance(self._cache[rota], Exception):
            raise RuntimeError(f"rota {rota} não respondeu ({type(self._cache[rota]).__name__})")
        return self._cache[rota]


@contextmanager
def trava(dados: Path, nome: str):
    """Trava de arquivo da rodada (`data/qualidade_<nome>.lock`): aparece em /proc/locks — é por ela que o AO VIVO
    mostra "rodando" — e impede duas rodadas simultâneas de regravarem a mesma fotografia."""
    dados.mkdir(parents=True, exist_ok=True)
    with open(dados / f"qualidade_{nome}.lock", "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def violacao(regra: str, sistema: str, chave: str, titulo: str, detalhe: str = "", acao_humana: str = "") -> dict:
    return {"regra": regra, "sistema": sistema, "chave": str(chave)[:120], "titulo": titulo[:200],
            "detalhe": detalhe[:400], "acao_humana": acao_humana[:300]}


def _regra_de(msg: str, padrao: str) -> str:
    m = re.match(r"([A-Z]{3}-\d{2})\b", msg)
    return m.group(1) if m else padrao


# ───────────────────────── PAD-01/02/06/07 · proveniência das manchetes ─────────────────────────
def sensor_proveniencia(ctx: Ctx) -> list[dict]:
    """Cada manchete do inventário: a rota serve o bloco `proveniencia` completo?"""
    out, mediu = [], 0
    for m in ctx.manchetes():
        try:
            p = ctx.payload(m["rota"])
        except RuntimeError:
            continue                                    # rota fora do ar é do sensor payloads_painel
        mediu += 1
        faltas = v.proveniencia_incompleta(p)
        if faltas:
            regras_faltando = sorted({_regra_de(f, "PAD-01") for f in faltas})
            for r in regras_faltando:
                out.append(violacao(r, "painel", m["id"], f"manchete {m['id']} sem proveniência completa",
                                    "; ".join(f for f in faltas if f.startswith(r))[:300],
                                    "a rota deve devolver `proveniencia` {fonte, data_ref, cobertura, estado, natureza, esfera}"))
    if ctx.manchetes() and not mediu:
        raise RuntimeError("nenhuma rota de manchete respondeu")
    return out


# ───────────────────────── PAD-04/05 · COR-07/11 · payloads do painel ─────────────────────────
def sensor_payloads_painel(ctx: Ctx) -> list[dict]:
    """O que as rotas das manchetes entregam: CPF exposto, lista no teto sem total, concentração, rota muda."""
    out, mediu = [], 0
    for rota in dict.fromkeys(m["rota"] for m in ctx.manchetes()):
        ids = ",".join(m["id"] for m in ctx.manchetes() if m["rota"] == rota)
        try:
            p = ctx.payload(rota)
        except RuntimeError as e:
            out.append(violacao("CST-10", "painel", rota, f"rota de manchete não respondeu: {rota}", str(e),
                                f"os cards {ids} ficam vazios sem dizer por quê"))
            continue
        mediu += 1
        cpfs = [c for t in v.textos(p) for c in v.cpf_exposto(t)]
        if cpfs:
            out.append(violacao("PAD-04", "painel", rota, f"CPF exposto no payload de {rota}",
                                f"{len(cpfs)} ocorrência(s), ex.: {cpfs[0]}", "mascarar na origem; a rota fica EM REVISÃO"))
        for msg in v.listas_no_teto(p)[:3]:
            out.append(violacao("COR-07", "painel", f"{rota}:{msg.split('`')[1]}", f"lista no teto sem total em {rota}", msg))
    for m in ctx.manchetes():
        conc = m.get("concentracao") or {}
        if not conc:
            continue
        try:
            itens = v.extrair(ctx.payload(m["rota"]), conc["lista"]) or []
        except RuntimeError:
            continue
        filtro = conc.get("filtro") or {}
        valores = [i.get(conc["item"]) for i in itens
                   if isinstance(i, dict) and all(i.get(k) == val for k, val in filtro.items())]
        msgs = v.concentracao_alta(valores)
        if msgs and not _diz_concentracao(ctx.payload(m["rota"])):
            out.append(violacao("COR-11", "painel", m["id"], f"manchete {m['id']} refém de poucos registros", msgs[0],
                                "a manchete deve informar a concentração e os registros devem ser conferidos na fonte primária"))
    if ctx.manchetes() and not mediu:
        raise RuntimeError("nenhuma rota de manchete respondeu")
    return out


def _diz_concentracao(p) -> bool:
    return isinstance(p, dict) and any("concentra" in str(k).lower() for k in p)


# ───────────────────────── PAD-03/04/08 · CNF-01/09 · texto entregue ─────────────────────────
def _textos_yoda(ctx: Ctx, limite: int = 60) -> list[str]:
    db = ctx.hermes / "state.db"
    if not db.exists():
        raise RuntimeError("state.db do Hermes não encontrado")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
    try:
        linhas = con.execute(
            "SELECT m.content FROM messages m JOIN sessions s ON s.id = m.session_id "
            "WHERE s.source = 'telegram' AND m.role = 'assistant' AND m.content IS NOT NULL AND length(m.content) > 40 "
            "ORDER BY m.timestamp DESC LIMIT ?", (limite,)).fetchall()
    finally:
        con.close()
    return [str(r[0]) for r in linhas]


def _textos_arquivos(ctx: Ctx) -> dict[str, list[str]]:
    """Arquivos de dados que o painel serve como texto pronto (JSON de análise) e os últimos relatórios."""
    out = {}
    for nome in ("governo_couto_suspeitas.json", "pericia_contabil_resumo.json"):
        arq = ctx.dados / nome
        if arq.exists():
            out[f"painel:{nome}"] = v.textos(json.loads(arq.read_text(encoding="utf-8")))
    rel = ctx.dados / "reports"
    if rel.is_dir():
        for arq in sorted(rel.glob("*.md"), key=lambda a: a.stat().st_mtime, reverse=True)[:5]:
            out[f"relatorios:{arq.name}"] = [arq.read_text(encoding="utf-8", errors="replace")]
    return out


def sensor_texto_entregue(ctx: Ctx) -> list[dict]:
    """Verificadores de texto sobre o que foi ENTREGUE: últimas respostas do Yoda, JSON de análise, relatórios."""
    fontes = {"yoda:respostas": _textos_yoda(ctx)}
    fontes.update(_textos_arquivos(ctx))
    out = []
    for origem, textos in fontes.items():
        sistema = origem.split(":")[0]
        por_regra: dict[str, list[str]] = {}
        for t in textos:
            for msg in v.texto_entregue(t):
                por_regra.setdefault(_regra_de(msg, "PAD-08"), []).append(msg)
        for regra, msgs in sorted(por_regra.items()):
            out.append(violacao(regra, sistema, origem, f"{len(msgs)} ocorrência(s) de {regra} em {origem}",
                                " | ".join(dict.fromkeys(msgs))[:380]))
    return out


# ───────────────────────── CST-02 · variação brusca de manchete ─────────────────────────
def _numeros(m: dict, p) -> dict[str, float]:
    out = {}
    for nome, caminho in (m.get("campos") or {}).items():
        val = v.extrair(p, caminho)
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            out[nome] = float(val)
    return out


def sensor_manchetes_variacao(ctx: Ctx) -> list[dict]:
    """Guarda o histórico de cada manchete e acusa variação > 25%, zeragem ou sumiço sem mudança registrada."""
    arq = ctx.dados / "qualidade_manchetes.json"
    hist = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {}
    out, mediu = [], 0
    carimbo = ctx.agora.strftime("%Y-%m-%dT%H:%M")
    for m in ctx.manchetes():
        try:
            atual = _numeros(m, ctx.payload(m["rota"]))
        except RuntimeError:
            continue
        mediu += 1
        serie = hist.setdefault(m["id"], [])
        anterior = serie[-1]["valores"] if serie else {}
        for nome in sorted(set(anterior) | set(atual)):
            for msg in v.variacao_brusca(anterior.get(nome), atual.get(nome)):
                out.append(violacao("CST-02", "painel", f"{m['id']}:{nome}", f"manchete {m['id']} ({nome}) variou sem explicação",
                                    f"{msg} — leitura anterior em {serie[-1]['em']}",
                                    "explicar a causa (mudança de lógica, de base ou defeito) antes de usar o número"))
        if not serie or serie[-1]["valores"] != atual:
            serie.append({"em": carimbo, "valores": atual})
            del serie[:-90]
    if ctx.manchetes() and not mediu:
        raise RuntimeError("nenhuma rota de manchete respondeu")
    arq.parent.mkdir(parents=True, exist_ok=True)
    tmp = arq.with_suffix(".tmp")
    tmp.write_text(json.dumps(hist, ensure_ascii=False), encoding="utf-8")
    tmp.replace(arq)
    return out


# ───────────────────────── CST-01/07/13 · constância entre superfícies ─────────────────────────
def _valor_fonte(ctx: Ctx, f: dict):
    if "rota" in f:
        return v.extrair(ctx.payload(f["rota"]), f.get("campo", ""))
    if "arquivo" in f:
        arq = ctx.dados / f["arquivo"]
        if not arq.exists():
            return None
        return v.extrair(json.loads(arq.read_text(encoding="utf-8")), f.get("campo", ""))
    raise ValueError(f"fonte de métrica sem `rota` nem `arquivo`: {f}")


def _soma_lista(ctx: Ctx, f: dict):
    itens = _valor_fonte(ctx, {k: f[k] for k in ("rota", "arquivo") if k in f} | {"campo": f["lista"]})
    if not isinstance(itens, list):
        return None
    filtro = f.get("filtro") or {}
    return sum(float(i.get(f["item"]) or 0) for i in itens if isinstance(i, dict)
               and all(i.get(k) == val for k, val in filtro.items()))


def sensor_constancia_superficies(ctx: Ctx) -> list[dict]:
    """Mapa `config/qualidade_metricas.yaml`: a mesma métrica em duas superfícies (igual), parte × todo, e
    total × soma da lista. Diferença = CST-01 (ou CST-07 quando um lado é o cache servido e o outro o arquivo)."""
    mapa = yaml.safe_load((ctx.repo / "config" / "qualidade_metricas.yaml").read_text(encoding="utf-8"))
    out, mediu = [], 0
    for met in mapa.get("metricas", []):
        try:
            if met["tipo"] == "igual":
                a, b = _valor_fonte(ctx, met["a"]), _valor_fonte(ctx, met["b"])
                msgs = v.divergencia(a, b, float(met.get("tolerancia", 0.01)))
            elif met["tipo"] == "parte_todo":
                msgs = v.parte_maior_que_todo(_valor_fonte(ctx, met["parte"]), _valor_fonte(ctx, met["todo"]))
            elif met["tipo"] == "total_lista":
                total, soma = _valor_fonte(ctx, met["total"]), _soma_lista(ctx, met["lista"])
                msgs = [] if soma is None or total is None else v.divergencia(total, soma, float(met.get("tolerancia", 0.01)))
                msgs = [m.replace("entre superfícies", "entre o total exibido e a soma da lista") for m in msgs]
            else:
                raise ValueError(f"tipo de métrica desconhecido: {met['tipo']}")
        except RuntimeError:
            continue
        mediu += 1
        for msg in msgs:
            out.append(violacao(met.get("regra", "CST-01"), met.get("sistema", "painel"), met["id"],
                                f"{met['titulo']}", msg, met.get("acao", "")))
    if mapa.get("metricas") and not mediu:
        raise RuntimeError("nenhuma métrica pôde ser medida")
    return out


# ───────────────────────── CST-03 · motores sem efeito ─────────────────────────
def sensor_motores_sem_efeito(ctx: Ctx) -> list[dict]:
    """AO VIVO: motor cujo efeito está parado além da janela ("rodando sem efeito")."""
    est = ctx.payload("/api/ao-vivo/estado")
    out = []
    for m in est.get("motores", []):
        ef = m.get("efeito")
        if isinstance(ef, dict) and ef.get("parado"):
            out.append(violacao("CST-03", "aovivo", m["id"], f"motor {m.get('nome', m['id'])} rodando sem efeito",
                                f"último efeito: {ef.get('ultimo') or ef.get('ultimo_iso') or 'sem registro'}; "
                                f"janela de {ef.get('horas', '?')} h"))
    return out


# ───────────────────────── COR-01 · CST-08/14 · CNF-12 · PAD-12 · casos do vault ─────────────────────────
_RE_FM = re.compile(r"\A---\n(.*?)\n---\n", re.S)
_RE_GRAU_ALTO = re.compile(r"(?i)^(alto|alta|critico|crítico|vermelho|🔴.*)$")
_RE_ABERTO = re.compile(r"(?i)^(|aberto.*|ativo|em andamento.*|andamento)$")


def grau_do_caso(fm: dict) -> str:
    """O grau de um caso mora em `grau`, `severidade` ou `gravidade` (os três existem no acervo)."""
    return str(fm.get("grau") or fm.get("severidade") or fm.get("gravidade") or fm.get("risco") or "").strip()


def caso_aberto(fm: dict) -> bool:
    return bool(_RE_ABERTO.match(str(fm.get("status") or "").strip()))
_RE_DESFECHO = re.compile(r"(?im)^\s*(?:[#>*\-| ]*)\**\s*(?:desfecho|veredito|conclus[aã]o|status)\**\s*[:—-]\s*\**\s*"
                          r"(🟢|refutad|sem irregularidade|arquivad|n[aã]o confirmad|regular\b)")
_RE_PROVA = re.compile(r"(?i)(doerj|d\.o\.|di[aá]rio oficial|sei-?\d|processo n|ac[oó]rd[aã]o|\bob\b|nota de empenho|"
                       r"\bfls?\.|p[aá]g(ina)?\.? ?\d|https?://)")
_RE_TRECHO = re.compile(r"[«\"“][^«»\"“”\n]{25,}[»\"”]|^>\s?.{25,}", re.M)
_RE_REFUTADA = re.compile(r"\*\*(REFUTADA|PARCIAL)\*\*")


def _frontmatter(texto: str) -> dict:
    m = _RE_FM.match(texto)
    if not m:
        return {}
    try:
        d = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return {}
    return d if isinstance(d, dict) else {}


def sensor_vault_casos(ctx: Ctx) -> list[dict]:
    """Casos do vault: grau alto com desfecho inocente no corpo (CST-08); 🔴 aberto sem prova primária citada
    (COR-01); caso aberto sem esfera (CNF-12); revisão com REFUTADA/PARCIAL sem errata registrada (CST-14)."""
    pasta = ctx.vault / "casos"
    if not pasta.is_dir():
        raise RuntimeError(f"pasta de casos não encontrada: {pasta}")
    out, n = [], 0
    for arq in sorted(pasta.glob("*.md")):
        texto = arq.read_text(encoding="utf-8", errors="replace")
        fm = _frontmatter(texto)
        if not fm or str(fm.get("tipo") or "caso").lower() not in ("caso", "investigacao", "investigação"):
            continue
        n += 1
        corpo = texto[_RE_FM.match(texto).end():]
        grau = grau_do_caso(fm)
        status = str(fm.get("status") or "").strip().lower()
        aberto = caso_aberto(fm)
        alto = bool(_RE_GRAU_ALTO.match(grau))
        revisado = str(fm.get("grau_revisado") or "").strip()
        if alto and aberto and revisado and not revisado.startswith("🔴"):
            out.append(violacao("CST-08", "vault", arq.name, f"caso com grau alto no frontmatter e grau revisado menor: {arq.stem}",
                                f"grau={grau[:30]!r} × grau_revisado={revisado[:60]!r} — as superfícies que leem `grau` ainda mostram 🔴",
                                "gravar o grau revisado em `grau`/`severidade` e guardar o anterior na errata"))
        elif alto and aberto and _RE_DESFECHO.search(corpo):
            out.append(violacao("CST-08", "vault", arq.name, f"caso com grau alto e desfecho inocente no corpo: {arq.stem}",
                                f"frontmatter grau={grau[:30]!r} status={status or 'vazio'!r}; o corpo registra desfecho que afasta o achado",
                                "regenerar grau/status/resumo a partir do corpo"))
        if alto and aberto and not (_RE_PROVA.search(corpo) and _RE_TRECHO.search(corpo)):
            out.append(violacao("COR-01", "vault", arq.name, f"caso 🔴 aberto sem prova primária citada: {arq.stem}",
                                "não há documento identificado + trecho literal no corpo",
                                "citar documento, trecho e data — ou rebaixar a PENDENTE"))
        if aberto and not str(fm.get("esfera") or fm.get("ente") or "").strip():
            out.append(violacao("CNF-12", "vault", arq.name, f"caso aberto sem esfera/Poder no frontmatter: {arq.stem}"))
    if not n:
        raise RuntimeError("nenhum caso com frontmatter legível — o sensor não mediu")
    notas = ctx.vault / "notas"
    erratas = {a.name for a in notas.glob("errata-*.md")} if notas.is_dir() else set()
    for arq in sorted(notas.glob("revisao-cetica-*.md")) if notas.is_dir() else []:
        n_ref = len(_RE_REFUTADA.findall(arq.read_text(encoding="utf-8", errors="replace")))
        esperado = arq.name.replace("revisao-cetica-", "errata-")
        if n_ref and esperado not in erratas:
            out.append(violacao("CST-14", "vault", arq.name, f"revisão com vereditos REFUTADA/PARCIAL sem errata: {arq.stem}",
                                f"{n_ref} marcações REFUTADA/PARCIAL; não existe notas/{esperado}",
                                "registrar a errata (o que foi dito, onde, o que a fonte mostra) e avisar o dono"))
    return out


# ───────────────────────── PAD-10 · COR-12/16 · base de alertas e de OB ─────────────────────────
def _ro(caminho: Path) -> sqlite3.Connection:
    if not caminho.exists():
        raise RuntimeError(f"banco não encontrado: {caminho.name}")
    con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True, timeout=10)
    limite = time.monotonic() + 40
    con.set_progress_handler(lambda: 1 if time.monotonic() > limite else 0, 20000)   # nunca segura o banco do painel
    return con


def sensor_alertas_base(ctx: Ctx) -> list[dict]:
    """Alertas por tipo: sem código (PAD-10), salto de volume ×3 entre leituras e tipo que domina a fila (COR-16).
    OB: linhas com chave vazia (COR-12)."""
    con = _ro(ctx.dados / "compliance.db")
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(alertas)")}
        if not cols:
            raise RuntimeError("tabela alertas não encontrada")
        campo = "tipo" if "tipo" in cols else ("regra" if "regra" in cols else None)
        if campo is None:
            raise RuntimeError("tabela alertas sem coluna de tipo/regra")
        # só o que está ABERTO: alerta descartado já foi julgado e não pode contar como volume do detector
        abertos = " WHERE status IN ('novo', 'confirmado')" if "status" in cols else ""
        por_tipo = {str(t or ""): n for t, n in con.execute(f"SELECT {campo}, COUNT(*) FROM alertas{abertos} GROUP BY {campo}")}  # noqa: S608
        try:
            sem_chave = con.execute("SELECT COUNT(*) FROM ob_orcamentaria_siafe WHERE numero_ob IS NULL OR numero_ob = ''").fetchone()[0]
        except sqlite3.OperationalError:
            sem_chave = None
    finally:
        con.close()
    out = []
    total = sum(por_tipo.values())
    if por_tipo.get("", 0):
        out.append(violacao("PAD-10", "detectores", "alertas:sem_tipo", f"{por_tipo['']} alerta(s) sem código de regra"))
    arq = ctx.dados / "qualidade_alertas.json"
    ant = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {}
    for tipo, n in sorted(por_tipo.items()):
        a = ant.get(tipo)
        if a and n >= 3 * a and n - a >= 200:
            out.append(violacao("COR-16", "detectores", f"alertas:{tipo}", f"alertas do tipo {tipo} multiplicaram por {n / a:.1f}",
                                f"de {a} para {n} entre leituras", "conferir amostra na fonte primária antes de exibir"))
        if total >= 1000 and n / total >= 0.8:
            out.append(violacao("COR-16", "detectores", f"alertas:{tipo}:dominante", f"um tipo responde por {n / total:.0%} dos alertas ({tipo})",
                                f"{n} de {total}", "taxa alta de um detector é defeito de leitura até prova em contrário"))
    if sem_chave:
        out.append(violacao("COR-12", "coletores", "ob:sem_numero", f"{sem_chave} linha(s) de OB do SIAFE sem número de OB",
                            "linha sem chave entra em dobro nas somas", "descartar/reconciliar na coleta"))
    tmp = arq.with_suffix(".tmp")
    tmp.write_text(json.dumps(por_tipo, ensure_ascii=False), encoding="utf-8")
    tmp.replace(arq)
    return out


# ───────────────────────── COR-02/14 · cruzamento dos motores ─────────────────────────
def sensor_cruzamento_motores(ctx: Ctx) -> list[dict]:
    """Banco de cruzamento Claude × cascata: revisões de divergência grave paradas e tarefas com concordância baixa."""
    db = ctx.dados / "cruzamento_motores.db"
    if not db.exists():
        return [violacao("COR-02", "llm", "cruzamento:ausente", "o banco de cruzamento dos motores ainda não existe",
                         "nenhum veredito foi cruzado: a dupla leitura não está medida")]
    from compliance_agent.llm import cruzamento
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
    try:
        pend = cruzamento.revisoes_pendentes(limite=200, con=con)
        conc = cruzamento.concordancia(dias=30, con=con)
    finally:
        con.close()
    out = []
    limite = (ctx.agora - timedelta(days=7)).isoformat()
    velhas = [p for p in pend if str(p.get("criado_em") or p.get("em") or "") < limite]
    if velhas:
        out.append(violacao("COR-02", "llm", "cruzamento:revisoes", f"{len(velhas)} divergência(s) grave(s) sem revisão há mais de 7 dias",
                            "Claude e cascata discordaram em dois níveis e ninguém decidiu", "revisar em /api/ao-vivo/cruzamento"))
    for tarefa, d in (conc.get("por_tarefa") or {}).items():
        n, taxa = d.get("pares") or d.get("n") or 0, d.get("concordancia")
        if n >= 20 and isinstance(taxa, (int, float)) and taxa < 0.6:
            out.append(violacao("COR-14", "llm", f"cruzamento:{tarefa}", f"concordância de {taxa:.0%} na tarefa {tarefa} (n={n})",
                                "abaixo de 60%: a cascata não pode exibir veredito sozinha nessa tarefa"))
    return out


# ───────────────────────── CNF-10 · gasto de API ─────────────────────────
def sensor_gasto_api(ctx: Ctx) -> list[dict]:
    """API paga: gasto acumulado contra o teto (US$ 100). Só LÊ o registro — este sensor não chama API nenhuma."""
    arq = ctx.dados / "claude_api_gasto.json"
    if not arq.exists():
        return []
    d = json.loads(arq.read_text(encoding="utf-8"))
    gasto = float(d.get("total_usd") or 0)
    teto = float(os.environ.get("JFN_CLAUDE_API_TETO_USD") or d.get("teto_usd") or 100)
    if gasto >= 0.8 * teto:
        return [violacao("CNF-10", "llm", "api:teto", f"gasto de API em {gasto / teto:.0%} do teto",
                         f"US$ {gasto:.2f} de US$ {teto:.2f}", "decidir: pausar a API (kill-switch) ou rever o teto")]
    return []


# ───────────────────────── COR-04 · manchete de detector não calibrado ─────────────────────────
def sensor_calibragem_manchetes(ctx: Ctx) -> list[dict]:
    """Manchetes servidas por detector sem taxa de falso positivo medida em fonte primária (≤ 180 dias)."""
    from compliance_agent.qualidade import detectores
    nao = set(detectores.nao_calibrados_em_manchete())
    out = []
    for m in ctx.manchetes():
        det = m.get("detector")
        if det and det in nao:
            out.append(violacao("COR-04", "painel", m["id"], f"manchete {m['id']} vem de detector não calibrado ({det})",
                                "sem taxa de falso positivo medida em amostra contra fonte primária",
                                "medir em amostra e registrar em config/qualidade_detectores.yaml — até lá, selo 'não calibrado'"))
    return out


# ───────────────────────── CNF-17 · personalizações do Hermes ─────────────────────────
MARCADORES_HERMES = ("_JFN_MENU_TEXT", "_JFN_MENU_HINTS", "_aplicar_orcamento_de_imagem", "_ORCAMENTO_IMAGEM_TURNO")


def sensor_hermes_personalizacoes(ctx: Ctx) -> list[dict]:
    """As personalizações do JFN no adapter do Telegram sobreviveram à última atualização? E o script seguro existe?"""
    adapter = ctx.hermes_agent / "plugins" / "platforms" / "telegram" / "adapter.py"
    if not adapter.exists():
        raise RuntimeError("adapter do Telegram do Hermes não encontrado")
    texto = adapter.read_text(encoding="utf-8", errors="replace")
    out = [violacao("CNF-17", "yoda", f"hermes:{m}", f"personalização do JFN sumiu do Hermes: {m}",
                    "a atualização descartou o patch local", "reaplicar o diff salvo (git apply --3way) e reiniciar o gateway")
           for m in MARCADORES_HERMES if m not in texto]
    if not (ctx.hermes_agent / "update-hermes-safe.sh").exists():
        out.append(violacao("CNF-17", "yoda", "hermes:script_seguro", "script de atualização segura do Hermes não encontrado"))
    return out


# ───────────────────────── CST-15 · SUB-* · o juiz ─────────────────────────
def sensor_juiz_qualidade(ctx: Ctx) -> list[dict]:
    """Última rodada do juiz: silêncio > 48 h é falha; nota ≤ 1 em qualquer critério é violação da regra SUB."""
    arq = ctx.dados / "qualidade_juiz.json"
    if not arq.exists():
        return [violacao("CST-15", "llm", "juiz:nunca", "o juiz de qualidade ainda não rodou",
                         acao_humana="python -m compliance_agent.qualidade juiz")]
    d = json.loads(arq.read_text(encoding="utf-8"))
    out = []
    em = datetime.fromisoformat(d["em"])
    if ctx.agora - em > timedelta(hours=48):
        out.append(violacao("CST-15", "llm", "juiz:silencio", f"o juiz de qualidade não conclui rodada desde {em:%d/%m %H:%M}",
                            d.get("motivo") or "", "ver data/qualidade_juiz.log e o orçamento do motor Claude"))
    rub = regras.rubricas()
    for av in d.get("avaliacoes", []):
        for criterio, nota in (av.get("notas") or {}).items():
            if isinstance(nota, (int, float)) and nota <= 1 and criterio in rub:
                out.append(violacao(rub[criterio]["regra"], av.get("sistema", "painel"), f"juiz:{av['id']}:{criterio}",
                                    f"juiz: nota {nota:g} em {criterio} — {av.get('rotulo', av['id'])[:80]}",
                                    (av.get("motivos") or {}).get(criterio, "")[:300],
                                    "escalar ao dono" if av.get("escalar") else "ajustar a afirmação"))
    return out


SENSORES: dict[str, Callable[[Ctx], list[dict]]] = {
    "proveniencia": sensor_proveniencia,
    "payloads_painel": sensor_payloads_painel,
    "texto_entregue": sensor_texto_entregue,
    "manchetes_variacao": sensor_manchetes_variacao,
    "constancia_superficies": sensor_constancia_superficies,
    "motores_sem_efeito": sensor_motores_sem_efeito,
    "vault_casos": sensor_vault_casos,
    "alertas_base": sensor_alertas_base,
    "cruzamento_motores": sensor_cruzamento_motores,
    "gasto_api": sensor_gasto_api,
    "calibragem_manchetes": sensor_calibragem_manchetes,
    "hermes_personalizacoes": sensor_hermes_personalizacoes,
    "juiz_qualidade": sensor_juiz_qualidade,
}


def sentir(ctx: Ctx | None = None, sensores: dict | None = None) -> tuple[list[dict], dict[str, str]]:
    """Roda os sensores. Devolve (violações, cegos): sensor que levantou vira `cegos[nome] = motivo`."""
    ctx = ctx or Ctx()
    violacoes, cegos = [], {}
    por_id = regras.por_id()
    for nome, fn in (sensores or SENSORES).items():
        try:
            achados = fn(ctx)
        except _FALHAS as e:
            cegos[nome] = f"{type(e).__name__}: {str(e)[:200]}"
            continue
        for a in achados:
            r = por_id.get(a["regra"])
            a["sensor"] = nome
            a["severidade"] = r.severidade if r else "media"
            a["titulo_regra"] = r.titulo if r else ""
            violacoes.append(a)
    return violacoes, cegos


def rodar(ctx: Ctx | None = None, sensores: dict | None = None, gravar: bool = True) -> dict:
    """Uma rodada completa: sente, grava a fotografia e a linha da hora no histórico. Idempotente por hora."""
    ctx = ctx or Ctx()
    with trava(ctx.dados, "sensores"):
        return _rodar(ctx, sensores, gravar)


def _rodar(ctx: Ctx, sensores: dict | None, gravar: bool) -> dict:
    violacoes, cegos = sentir(ctx, sensores)
    por_sistema: dict[str, int] = {}
    por_regra: dict[str, int] = {}
    for a in violacoes:
        por_sistema[a["sistema"]] = por_sistema.get(a["sistema"], 0) + 1
        por_regra[a["regra"]] = por_regra.get(a["regra"], 0) + 1
    estado = {"em": ctx.agora.isoformat(timespec="seconds"), "violacoes": violacoes, "cegos": cegos,
              "por_sistema": por_sistema, "por_regra": por_regra, "total": len(violacoes),
              "bloqueantes": sum(a["severidade"] == "bloqueante" for a in violacoes)}
    if gravar:
        ctx.dados.mkdir(parents=True, exist_ok=True)
        tmp = ctx.dados / "qualidade_estado.tmp"
        tmp.write_text(json.dumps(estado, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(ctx.dados / "qualidade_estado.json")
        _historico(ctx, estado)
    return estado


def _historico(ctx: Ctx, estado: dict) -> None:
    arq = ctx.dados / "qualidade_historico.jsonl"
    hora = ctx.agora.strftime("%Y-%m-%dT%H")
    linhas = [ln for ln in (arq.read_text(encoding="utf-8").splitlines() if arq.exists() else [])
              if ln.strip() and json.loads(ln).get("hora") != hora]
    linhas.append(json.dumps({"hora": hora, "total": estado["total"], "bloqueantes": estado["bloqueantes"],
                              "por_sistema": estado["por_sistema"], "por_regra": estado["por_regra"],
                              "cegos": sorted(estado["cegos"])}, ensure_ascii=False))
    tmp = arq.with_suffix(".tmp")
    tmp.write_text("\n".join(linhas[-24 * 120:]) + "\n", encoding="utf-8")
    tmp.replace(arq)


def para_automelhoria(estado: dict) -> list[dict]:
    """Agrega para a fila única: UM item por (regra, sistema) — o dono não recebe 60 mensagens, recebe a regra
    violada, quantas vezes e os três primeiros exemplos. O detalhe completo fica no painel de conformidade."""
    grupos: dict[tuple, list[dict]] = {}
    juiz: dict[str, list[dict]] = {}
    for a in estado["violacoes"]:
        if a["regra"].startswith("SUB-"):                       # as notas do juiz: um item por sistema, não por critério
            juiz.setdefault(a["sistema"], []).append(a)
        else:
            grupos.setdefault((a["regra"], a["sistema"]), []).append(a)
    out = []
    for sistema, itens in sorted(juiz.items()):
        afirm = sorted({i["chave"].split(":", 1)[1].rsplit(":", 1)[0] for i in itens})
        bloq = any(i["severidade"] == "bloqueante" for i in itens)
        out.append({"area": "qualidade", "chave": f"SUB:{sistema}",
                    "titulo": f"juiz de qualidade reprovou {len(afirm)} afirmação(ões) em {sistema} "
                              f"({', '.join(sorted({i['regra'] for i in itens}))})",
                    "detalhe": "; ".join(afirm[:4]), "acao_humana": "ver as notas e o que falta em /api/qualidade/conformidade",
                    "severidade": "bloqueante" if bloq else "alta"})
    for (regra, sistema), itens in sorted(grupos.items()):
        ex = "; ".join(i["titulo"] for i in itens[:3])
        out.append({"area": "qualidade", "chave": f"{regra}:{sistema}",
                    "titulo": f"{regra} ({itens[0]['titulo_regra']}) — {len(itens)} violação(ões) em {sistema}",
                    "detalhe": ex, "acao_humana": itens[0].get("acao_humana") or "ver /api/qualidade/conformidade",
                    "severidade": itens[0]["severidade"]})
    for nome, motivo in sorted(estado["cegos"].items()):
        out.append({"area": "sensor", "chave": f"qualidade.{nome}", "titulo": f"sensor de qualidade {nome} não conseguiu medir",
                    "detalhe": motivo, "acao_humana": "o sensor está cego: ver data/qualidade_estado.json", "severidade": "alta"})
    return out
