# -*- coding: utf-8 -*-
"""automelhoria_modelos — a automelhoria sobre os modelos GRÁTIS e os mais fracos que o Opus.

Pedido do dono (22/11/2026, 00h40): "faça a automelhoria atuar também nos modelos grátis e mais fracos que o Opus".
Determinístico, sem LLM. É chamado pelo sensor `modelos` de `tools/automelhoria_geral.py` (fila única
aberto/curado/REINCIDIU) e NÃO manda nada pelo Telegram (dono 22/11: o Yoda só fala quando pedido).

SENTE, por MODELO × TAREFA, com o que a casa já grava:
  a) DIVERGÊNCIA DO OPUS — pares Opus × outro modelo de `data/cruzamento_motores.db` (é lá que a conferência do Opus
     da `data/conferencia_opus.db`, a triagem e a perícia integral gravam os dois lados). Janela de 7 dias contra os 7
     anteriores, GRAVE (um 🔴 contra um ⚪) separado de LEVE (um nível). Também o A/B do few-shot que já roda no
     co-motor (com × sem exemplos): exemplo que PIORA o acordo vira item;
  b) DISPONIBILIDADE — `data/llm_trace.db`: 404 sem resposta depois (o modelo sumiu), cota diária esgotada quase
     todo dia, chamadas acima da janela de 150 s;
  c) CANDIDATOS — modelo grátis COM PROVA no catálogo vivo (`~/.local/state/catalogo-modelos-*.json`) que nunca foi
     medido contra o Opus (nem na bancada, nem em pares de produção).

REMÉDIOS AUTOMÁTICOS — só os seguros e reversíveis, gravados em `llm/cascata_ajuste` com o motivo e o número:
  · REBAIXA na cadeia da tarefa o modelo cuja divergência GRAVE mediu acima da do Sonnet na mesma tarefa (régua em
    `config/modelos_regua.yaml` ou pares Sonnet × Opus no mesmo item) — sem régua medida, não age;
  · TIRA de todas as cadeias o modelo que deu 404 e não respondeu mais.
  Nunca PROMOVE: promoção exige bancada medida e o dono.

APRENDE: cada divergência grave do Opus num modelo fraco vira EXEMPLO NEGATIVO no banco de casos por tarefa, FORA do
repositório (`~/.local/state/jfn-casos-negativos/casos.db` — a resposta do Opus cita trecho do SEI); família de erro
nova vira lição no CATALOGO-DE-FALHAS. O "ensino" (bloco de exemplos negativos) fica só como CANDIDATO: `ensino`
imprime o bloco para a bancada medir COM × SEM; nada é injetado em produção — prompt com lições já derrubou o recall
do gemini lite (100 → 94%, 21/11) e o do `pregao` (3/6 → 0/6).

Uso:
  python -m tools.automelhoria_modelos tabela          # a tabela atual modelo × tarefa (divergência e disponibilidade)
  python -m tools.automelhoria_modelos ensino TAREFA   # bloco candidato para a bancada (com × sem)
"""
from __future__ import annotations

import argparse
import glob
import json
import logging
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
DATA = _REPO / "data"
REGUA = _REPO / "config" / "modelos_regua.yaml"
ESTADO = Path.home() / ".local" / "state"
CATALOGO_FALHAS = Path.home() / "vault" / "aprendizados" / "CATALOGO-DE-FALHAS.md"

JANELA_DIAS = 7
AMOSTRA_MIN = 20          # mesma amostra mínima do placar do cruzamento
SUBIDA_GRAVE = 0.05       # +5 pontos de divergência grave na semana = alerta
SUBIDA_LEVE = 0.10
MIN_GRAVES = 2            # um grave isolado não rebaixa ninguém
JANELA_MS = 150_000       # a janela da leitura dupla (qwen4-max estoura com frequência)
TIMEOUT_MAX = 0.20
DIAS_COTA = 5             # cota diária esgotada em >= 5 dos últimos 7
FEWSHOT_PIORA = 0.10

logger = logging.getLogger(__name__)


def _p(chave: str, titulo: str, detalhe: str = "", acao_humana: str = "") -> dict:
    """Mesmo formato de `automelhoria_geral._p`, área `modelos`. SEM `remediar`: o remédio deste sensor é aplicado
    aqui mesmo (arquivo da cascata), não pelo executor genérico — que escala ao dono pelo Telegram."""
    return {"assinatura": f"modelos:{chave}", "area": "modelos", "titulo": titulo, "detalhe": detalhe[:300],
            "remediar": "", "acao_humana": acao_humana}


def _ro(caminho: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{caminho}?mode=ro", uri=True, timeout=60)


def _modelo(m: str | None) -> str:
    """'claude-haiku-5-5@api-lote#25cdd6329a81' → 'claude-haiku-5-5@api-lote' (o sufixo é o lote, não o modelo)."""
    return (m or "").split("#", 1)[0]


def _iso(d: datetime) -> str:
    return d.isoformat(timespec="seconds")


# ─────────────────────────── a) divergência do Opus ───────────────────────────
# Tarefa com até UM nível (`pericia_integral:juridico` é um juízo por eixo); os pontos (`…:C6`) ficam fora — são
# sub-itens do mesmo juízo e inflariam o n. Modelo 'cascata' (sem proveniência) não se atribui a ninguém.
_SQL_PARES = """
SELECT o.tarefa, o.modelo, o.nivel, c.nivel, o.com_exemplos
FROM veredito c JOIN veredito o ON o.par = c.par AND o.motor = 'cascata'
WHERE c.motor = 'claude' AND c.modelo LIKE 'claude-opus%' AND c.nivel IS NOT NULL AND o.nivel IS NOT NULL
  AND o.tarefa NOT LIKE '%:%:%' AND o.modelo <> 'cascata' AND o.modelo NOT LIKE '%opus%' AND o.em >= ? AND o.em < ?
"""
# Sonnet contra Opus no MESMO item (lados de pares diferentes): é a régua medida em produção, quando houver.
_SQL_SONNET = """
SELECT s.tarefa, s.nivel, o.nivel FROM veredito s JOIN veredito o ON o.tarefa = s.tarefa AND o.item = s.item
WHERE s.modelo LIKE 'claude-sonnet%' AND o.modelo LIKE 'claude-opus%' AND s.nivel IS NOT NULL AND o.nivel IS NOT NULL
  AND s.item IS NOT NULL AND s.em >= ?
"""


def _base(tarefa: str) -> str:
    return tarefa.split(":", 1)[0]


def contar(pares) -> dict:
    """(tarefa, modelo, nivel_outro, nivel_opus[, com_ex]) → {(tarefa_base, modelo): {n, graves, leves}}."""
    out: dict = {}
    for t, m, n_o, n_op, *_ in pares:
        g = out.setdefault((_base(t), _modelo(m)), {"n": 0, "graves": 0, "leves": 0})
        g["n"] += 1
        d = abs(int(n_o) - int(n_op))
        g["graves"] += d >= 2
        g["leves"] += d == 1
    return out


def regua_sonnet(con: sqlite3.Connection | None, regua_yaml: Path = REGUA, desde: str = "") -> dict:
    """{tarefa: {taxa_grave, n, fonte}} — pares Sonnet × Opus no mesmo item (n >= AMOSTRA_MIN) ou o yaml medido."""
    import yaml
    try:
        ref = (yaml.safe_load(regua_yaml.read_text(encoding="utf-8")) or {}).get("referencia_sonnet") or {}
    except OSError:
        ref = {}
    out = {t: dict(v) for t, v in ref.items() if isinstance(v, dict) and (v.get("n") or 0) >= AMOSTRA_MIN
           and v.get("taxa_grave") is not None}
    if con is not None:
        agg: dict = {}
        for t, ns, no in con.execute(_SQL_SONNET, (desde,)):
            a = agg.setdefault(_base(t), [0, 0])
            a[0] += 1
            a[1] += abs(int(ns) - int(no)) >= 2
        for t, (n, g) in agg.items():
            if n >= AMOSTRA_MIN:
                out[t] = {"taxa_grave": g / n, "n": n, "fonte": "pares Sonnet × Opus no mesmo item (cruzamento)"}
    return out


def rebaixavel(modelo: str) -> bool:
    """Só o que a cascata grátis/fraca chama pela ordem do arquivo: Gemini por modelo, OpenRouter por modelo (perícia
    integral) e os provedores da cascata padrão. Claude pela API e lote da triagem têm caminho próprio — item humano."""
    if modelo.startswith(("gemini:", "openrouter:")):
        return True
    return ":" not in modelo and "@" not in modelo and not modelo.startswith("claude")


def avaliar_divergencia(atual: dict, anterior: dict, regua: dict, rebaixados: dict | None = None) -> tuple[list, list]:
    """Itens da fila + rebaixamentos a aplicar [(tarefa, modelo, motivo, numeros)]. Puro (testável)."""
    probs, rebaixar = [], []
    rebaixados = rebaixados or {}
    sem_regua: dict = {}
    for (t, m), g in sorted(atual.items()):
        if g["n"] < AMOSTRA_MIN:
            continue
        tg, tl = g["graves"] / g["n"], g["leves"] / g["n"]
        a = anterior.get((t, m))
        num = f"{g['graves']} grave(s) e {g['leves']} leve(s) em {g['n']} pares com o Opus (7 dias)"
        if a and a["n"] >= AMOSTRA_MIN:
            ag, al = a["graves"] / a["n"], a["leves"] / a["n"]
            if tg > ag + SUBIDA_GRAVE:
                probs.append(_p(f"div_grave:{t}:{m}", f"{m} em {t}: divergência GRAVE do Opus subiu de {ag:.0%} para "
                                f"{tg:.0%}", f"{num}; semana anterior {a['graves']}/{a['n']}",
                                acao_humana="abrir os casos no banco de casos negativos e achar a regra que o modelo "
                                            "erra — conserto por código/régua, não por prompt sem A/B"))
            if tl > al + SUBIDA_LEVE:
                probs.append(_p(f"div_leve:{t}:{m}", f"{m} em {t}: divergência leve do Opus subiu de {al:.0%} para "
                                f"{tl:.0%}", f"{num}; semana anterior {a['leves']}/{a['n']}"))
        if g["graves"] < MIN_GRAVES:
            continue
        ref = regua.get(t)
        if ref is None:
            sem_regua.setdefault(t, []).append(f"{m} {tg:.0%}")
            continue
        if tg <= ref["taxa_grave"]:
            continue
        numeros = {"n": g["n"], "graves": g["graves"], "taxa_grave": round(tg, 4),
                   "sonnet_taxa_grave": round(ref["taxa_grave"], 4), "sonnet_n": ref.get("n"),
                   "sonnet_fonte": ref.get("fonte", "")}
        motivo = (f"divergência grave do Opus {tg:.1%} ({g['graves']}/{g['n']}, 7 dias) acima da do Sonnet "
                  f"{ref['taxa_grave']:.1%} (n={ref.get('n')}) em {t}")
        if rebaixavel(m):
            ja = m in (rebaixados.get(t) or {})
            rebaixar.append((t, m, motivo, numeros))
            probs.append(_p(f"acima_sonnet:{t}:{m}", f"{m} em {t}: grave {tg:.0%} acima do Sonnet "
                            f"{ref['taxa_grave']:.0%} — {'já ' if ja else ''}REBAIXADO na cadeia da tarefa",
                            motivo + "; desfazer: python -m compliance_agent.llm.cascata_ajuste desfazer "
                            f"{t} {m}"))
        else:
            probs.append(_p(f"acima_sonnet:{t}:{m}", f"{m} em {t}: grave {tg:.0%} acima do Sonnet "
                            f"{ref['taxa_grave']:.0%} — fora da cascata que o arquivo ordena", motivo,
                            acao_humana="tirar o modelo da tarefa no código que o chama (não é a cascata grátis)"))
    for t, ms in sorted(sem_regua.items()):
        probs.append(_p(f"sem_regua_sonnet:{t}", f"{t}: modelos fracos com divergência grave do Opus e sem régua do "
                        "Sonnet para comparar", "; ".join(ms[:6]),
                        acao_humana="medir o Sonnet nesta tarefa na bancada (mesma régua: 🔴 × ⚪ contra o Opus) e "
                                    "gravar em config/modelos_regua.yaml — sem isso o rebaixamento não age"))
    return probs, rebaixar


def avaliar_fewshot(pares) -> list[dict]:
    """O A/B que o co-motor já roda (metade com exemplos): exemplo que PIORA o acordo com o Opus vira item."""
    g: dict = {}
    for t, _m, n_o, n_op, com in pares:
        lado = g.setdefault(_base(t), {1: [0, 0], 0: [0, 0]})[1 if com else 0]
        lado[0] += 1
        lado[1] += int(n_o) == int(n_op)
    out = []
    for t, d in sorted(g.items()):
        (nc, ac), (ns, as_) = d[1], d[0]
        if nc >= AMOSTRA_MIN and ns >= AMOSTRA_MIN and ac / nc < as_ / ns - FEWSHOT_PIORA:
            out.append(_p(f"fewshot_piorou:{t}", f"{t}: os exemplos do few-shot PIORARAM o acordo com o Opus "
                          f"({ac / nc:.0%} com × {as_ / ns:.0%} sem)", f"com exemplos {ac}/{nc}; sem {as_}/{ns} (7 dias)",
                          acao_humana="desligar o few-shot desta tarefa (JFN_COMOTOR_FEWSHOT_FRACAO=0) até rever os "
                                      "exemplos — é a régua `prompt-mais-especifico-piorou-recall`"))
    return out


# ─────────────────────────── b) disponibilidade ───────────────────────────
_SQL_DISP = """
SELECT provedor, COALESCE(modelo, ''), COUNT(*), SUM(ok),
       SUM(erro LIKE '404%' OR erro LIKE '%''404 %' OR erro LIKE '%404 Not Found%'),
       MAX(CASE WHEN erro LIKE '404%' OR erro LIKE '%''404 %' OR erro LIKE '%404 Not Found%' THEN ts END),
       MAX(CASE WHEN ok = 1 THEN ts END),
       COUNT(DISTINCT CASE WHEN erro LIKE '%PerDay%' THEN substr(ts, 1, 10) END), COUNT(DISTINCT substr(ts, 1, 10)),
       SUM(ms >= ? OR erro LIKE '%Timeout%'),
       CAST(AVG(CASE WHEN ok = 1 THEN ms END) AS INTEGER)
FROM llm_trace WHERE ts >= ? GROUP BY 1, 2
"""


def disponibilidade(con: sqlite3.Connection, desde: str) -> list[dict]:
    cols = ("provedor", "modelo", "n", "ok", "n404", "ultimo_404", "ultimo_ok", "dias_cota", "dias", "n_timeout", "ms_ok")
    return [dict(zip(cols, r)) for r in con.execute(_SQL_DISP, (JANELA_MS, desde))]


def _rotulo(d: dict) -> str:
    return f"{d['provedor']}:{d['modelo']}" if d["modelo"] else d["provedor"]


def avaliar_disponibilidade(linhas: list[dict]) -> tuple[list, list]:
    """Itens + modelos a tirar [(rotulo, motivo, numeros)]. Puro."""
    probs, tirar = [], []
    for d in linhas:
        rot = _rotulo(d)
        if d["n404"] and (not d["ultimo_ok"] or d["ultimo_ok"] < d["ultimo_404"]):
            motivo = f"404 em {d['n404']} chamada(s), a última {d['ultimo_404']}, nenhuma resposta depois"
            if d["modelo"]:                      # o provedor inteiro não sai por 404 de um modelo
                tirar.append((rot, motivo, {"n404": d["n404"], "ultimo_404": d["ultimo_404"]}))
            probs.append(_p(f"sumiu:{rot}", f"{rot} sumiu (404)" + (" — TIRADO das cadeias" if d["modelo"] else ""),
                            motivo, acao_humana="" if d["modelo"] else "provedor respondeu 404: conferir a URL/catálogo"))
        if d["dias_cota"] >= DIAS_COTA:
            probs.append(_p(f"cota_diaria:{rot}", f"{rot}: cota diária grátis esgota quase todo dia "
                            f"({d['dias_cota']} de {d['dias']} dias com chamada)",
                            f"{d['ok']} respostas em {d['n']} chamadas (7 dias)",
                            acao_humana="espalhar a carga por modelo/projeto ou aceitar o teto — nunca ligar billing "
                                        "(§4.1)"))
        if d["n"] >= AMOSTRA_MIN and (d["n_timeout"] or 0) / d["n"] >= TIMEOUT_MAX:
            probs.append(_p(f"timeout:{rot}", f"{rot}: {d['n_timeout'] / d['n']:.0%} das chamadas passaram da janela "
                            f"de {JANELA_MS // 1000} s", f"{d['n_timeout']}/{d['n']} (7 dias); mediana de quem "
                            f"respondeu ~{(d['ms_ok'] or 0) // 1000} s"))
    return probs, tirar


# ─────────────────────────── c) candidatos do catálogo vivo ───────────────────────────
# Não-texto (voz, imagem, vídeo, música, embedding, moderação) não entra na bancada de texto. OFOX "preço 0" é mídia
# cobrada por unidade (falso grátis, catálogo de 21/11) — fora.
_NAO_TEXTO = re.compile(r"tts|image|imagen|veo|lyria|audio|live|embed|guard|whisper|wan-|seedance|eleven|flux|"
                        r"happyhorse|music|speech|vision-only|ocr|rerank", re.I)
_FALSO_GRATIS = {"ofox"}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_").removesuffix("_free")


def catalogo_atual(padrao: str | None = None) -> dict:
    arqs = sorted(glob.glob(padrao or str(ESTADO / "catalogo-modelos-*.json")))
    if not arqs:
        raise OSError("catálogo vivo ausente (~/.local/state/catalogo-modelos-*.json)")
    return json.loads(Path(arqs[-1]).read_text(encoding="utf-8"))


def medidos(bancadas: str | None = None, modelos_pares: set[str] = frozenset()) -> set[str]:
    """Nomes normalizados já medidos contra o Opus: linhas das bancadas + modelos com pares de produção."""
    out = {_norm(m.split(":", 1)[-1]) for m in modelos_pares}
    for arq in glob.glob(bancadas or str(ESTADO / "jfn-bancada-free-*" / "res" / "tabela.json")):
        try:
            for r in json.loads(Path(arq).read_text(encoding="utf-8")):
                if r.get("processos"):
                    out.add(_norm(r.get("modelo", "")))
        except (OSError, ValueError, AttributeError):
            continue
    return out


def avaliar_candidatos(catalogo: dict, ja: set[str]) -> list[dict]:
    probs = []
    for prov, chaves in sorted((catalogo.get("provedores") or {}).items()):
        if prov in _FALSO_GRATIS:
            continue
        ids: list[str] = []
        for k in chaves or []:
            if k.get("viva") and k.get("prova_gratis"):
                ids += [i for i in (k.get("gratis_ids") or []) if i not in ids]
        novos = [i for i in ids if not _NAO_TEXTO.search(i)
                 and not any(_norm(i) and _norm(i) in m for m in ja)]
        if novos:
            probs.append(_p(f"nao_medido:{prov}", f"{prov}: {len(novos)} modelo(s) grátis com prova ainda não "
                            "medido(s) contra o Opus", ", ".join(novos[:8]),
                            acao_humana="candidatos à bancada do sábado (≥ Sonnet e zero grave, só coleta); "
                                        "nada liga sozinho"))
    return probs


# ─────────────────────────── 3) aprendizado: banco de casos negativos ───────────────────────────
_DDL_CASOS = """
CREATE TABLE IF NOT EXISTS caso(
  chave TEXT PRIMARY KEY, tarefa TEXT NOT NULL, modelo TEXT NOT NULL, item TEXT, familia TEXT NOT NULL,
  nivel INTEGER, nivel_opus INTEGER, veredito TEXT, veredito_opus TEXT, resposta TEXT, resposta_opus TEXT,
  criado_em TEXT, gravado_em TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_caso_tarefa ON caso(tarefa, familia);
CREATE TABLE IF NOT EXISTS familia(
  familia TEXT PRIMARY KEY, tarefa TEXT NOT NULL, descricao TEXT NOT NULL, primeira TEXT NOT NULL,
  no_catalogo INTEGER DEFAULT 0);
"""
_SQL_GRAVES_CONF = """
SELECT chave, tarefa, motor, item, nivel, nivel_opus, veredito, veredito_opus, resposta, resposta_opus, criado_em
FROM fila WHERE status = 'conferido' AND nivel IS NOT NULL AND nivel_opus IS NOT NULL AND ABS(nivel - nivel_opus) >= 2
"""


def banco_casos() -> Path:
    return Path(os.environ.get("JFN_CASOS_NEGATIVOS") or (ESTADO / "jfn-casos-negativos" / "casos.db"))


def familia_de(tarefa: str, nivel: int, nivel_opus: int) -> tuple[str, str]:
    base = _base(tarefa)
    if nivel > nivel_opus:
        return (f"{base}:superestima_risco", f"em {base}, o modelo fraco dá 🔴 onde o Opus, relendo a mesma entrada, "
                "dá ⚪ — acusa o que os autos não sustentam")
    return (f"{base}:subestima_risco", f"em {base}, o modelo fraco dá ⚪ onde o Opus dá 🔴 — deixa passar o que os "
            "autos mostram")


def aprender(con_conf: sqlite3.Connection, banco: Path, catalogo_md: Path | None, agora: datetime | None = None) -> dict:
    """Divergência grave conferida → caso negativo (idempotente pela chave da fila); família nova → lição."""
    from compliance_agent.llm.cruzamento import mascarar
    quando = _iso(agora or datetime.now())
    banco.parent.mkdir(parents=True, exist_ok=True)
    novo = not banco.exists()
    con = sqlite3.connect(banco, timeout=30)
    if novo:
        os.chmod(banco, 0o600)                  # cita trecho do SEI: só o dono da conta lê
    try:
        con.executescript(_DDL_CASOS)
        casos, fams = 0, []
        for (chave, t, motor, item, niv, nop, ver, vop, resp, rop, criado) in con_conf.execute(_SQL_GRAVES_CONF):
            fam, desc = familia_de(t, niv, nop)
            cur = con.execute("INSERT OR IGNORE INTO caso VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                              (chave, _base(t), _modelo(motor), item, fam, niv, nop, ver, vop,
                               mascarar((resp or "")[:1500]), mascarar((rop or "")[:1500]), criado, quando))
            casos += cur.rowcount
            if con.execute("INSERT OR IGNORE INTO familia(familia,tarefa,descricao,primeira) VALUES(?,?,?,?)",
                           (fam, _base(t), desc, quando)).rowcount:
                fams.append(fam)
        con.commit()
        licoes = _licoes_no_catalogo(con, catalogo_md, quando) if catalogo_md else []
        por_tarefa = dict(con.execute("SELECT tarefa, COUNT(*) FROM caso GROUP BY 1").fetchall())
        return {"casos_novos": casos, "familias_novas": fams, "licoes": licoes, "por_tarefa": por_tarefa}
    finally:
        con.close()


_SECAO = ("\n\n## Apêndice — famílias de erro dos modelos fracos medidas pelo Opus (automelhoria, desde 22/11/2026)\n"
          "Gerado por `tools/automelhoria_modelos.py`: cada divergência GRAVE (🔴 × ⚪) de um modelo grátis ou mais fraco "
          "que o Opus, conferida pelo Opus, vira exemplo negativo em `~/.local/state/jfn-casos-negativos/casos.db` "
          "(fora do repositório: cita SEI). Família nova entra aqui UMA vez. **Regra:** resultado de modelo fraco nessas "
          "tarefas nunca é VERIFICADO sem o Opus; o \"ensino\" com estes exemplos é candidato que a bancada mede com × "
          "sem antes de virar padrão (prompt com lições já piorou o recall).\n<!-- familias-modelos -->\n"
          "<!-- /familias-modelos -->\n")


def _licoes_no_catalogo(con: sqlite3.Connection, md: Path, quando: str) -> list[str]:
    pend = con.execute("SELECT familia, descricao FROM familia WHERE no_catalogo = 0 ORDER BY familia").fetchall()
    if not pend:
        return []
    try:
        txt = md.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("catálogo de falhas ilegível (%s): lição fica pendente", e)
        return []
    if "<!-- /familias-modelos -->" not in txt:
        txt = txt.rstrip("\n") + _SECAO
    feitas = []
    for fam, desc in pend:
        marca = f"<!-- fam:{fam} -->"
        if marca not in txt:
            n, modelos = con.execute("SELECT COUNT(*), GROUP_CONCAT(DISTINCT modelo) FROM caso WHERE familia=?",
                                     (fam,)).fetchone()
            linha = (f"- **{fam}** ({quando[:10]}; {n} caso(s); modelos: {modelos}): {desc}. Banco: "
                     f"`casos.db`, `familia='{fam}'`. {marca}\n")
            txt = txt.replace("<!-- /familias-modelos -->", linha + "<!-- /familias-modelos -->", 1)
        feitas.append(fam)
    tmp = md.with_suffix(md.suffix + ".tmp")
    tmp.write_text(txt, encoding="utf-8")
    os.replace(tmp, md)
    con.executemany("UPDATE familia SET no_catalogo = 1 WHERE familia = ?", [(f,) for f in feitas])
    con.commit()
    return feitas


def bloco_ensino(tarefa: str, k: int = 3, banco: Path | None = None) -> str:
    """CANDIDATO de ensino (exemplos negativos com o veredito do Opus) — só para a bancada medir com × sem."""
    con = sqlite3.connect(f"file:{banco or banco_casos()}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT veredito, veredito_opus, resposta_opus FROM caso WHERE tarefa=? "
                           "ORDER BY gravado_em DESC LIMIT ?", (_base(tarefa), k)).fetchall()
    finally:
        con.close()
    return "\n\n".join(f"ERRO REAL {i + 1}: um modelo respondeu «{v}»; o revisor (Opus) releu e concluiu «{vo}».\n"
                       f"Fundamento do revisor: {(ro or '')[:600]}" for i, (v, vo, ro) in enumerate(rows))


# ─────────────────────────── o sensor ───────────────────────────
def medir(cruz: Path | None = None, trace: Path | None = None, agora: datetime | None = None) -> dict:
    agora = agora or datetime.now()
    cruz, trace = cruz or DATA / "cruzamento_motores.db", trace or DATA / "llm_trace.db"
    ini, meio = _iso(agora - timedelta(days=2 * JANELA_DIAS)), _iso(agora - timedelta(days=JANELA_DIAS))
    fim = _iso(agora + timedelta(minutes=1))
    con = _ro(cruz)
    try:
        atual_p = con.execute(_SQL_PARES, (meio, fim)).fetchall()
        ant_p = con.execute(_SQL_PARES, (ini, meio)).fetchall()
        regua = regua_sonnet(con, desde=ini)
        com_pares = {_modelo(m) for (m,) in con.execute(
            "SELECT DISTINCT o.modelo FROM veredito o JOIN veredito c ON c.par=o.par AND c.motor='claude' "
            "AND c.modelo LIKE 'claude-opus%' WHERE o.motor='cascata'")}
    finally:
        con.close()
    con = _ro(trace)
    try:
        disp = disponibilidade(con, meio.replace("T", " "))   # o trace grava 'AAAA-MM-DD HH:MM:SS' (espaço, não T)
    finally:
        con.close()
    return {"atual": contar(atual_p), "anterior": contar(ant_p), "pares_atuais": atual_p, "regua": regua,
            "disp": disp, "modelos_com_pares": com_pares}


RECUSAS_FICHA = DATA / "sei_ficha_gratis_recusas.jsonl"


def avaliar_ficha_gratis(recusas: Path = RECUSAS_FICHA, bancadas: dict | None = None,
                         agora: datetime | None = None) -> list[dict]:
    """Graves da COLETA GRÁTIS da ficha do acervo (22/11/2026) → um item por (modelo, categoria do grave).

    Duas fontes: (1) as recusas de produção dos últimos 7 dias (`tools/sei_ficha_acervo._registrar_recusas` — o
    processo foi ao Haiku porque o grátis inventou número/CNPJ/data/citação); (2) os graves que a BANCADA mediu e
    `config/modelos_regua.yaml` (`bancadas_coleta`) registra — ficam abertos até a bancada seguinte medir zero."""
    agora = agora or datetime.now()
    desde = (agora - timedelta(days=JANELA_DIAS)).isoformat(timespec="seconds")
    cont: dict[tuple[str, str], set] = {}
    try:
        linhas = recusas.read_text(encoding="utf-8").splitlines()
    except OSError:
        linhas = []
    for ln in linhas:
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if str(r.get("em") or "") < desde:
            continue
        for t in r.get("tentativas") or []:
            if t.get("motivo") != "grave":
                continue
            for g in t.get("graves") or []:
                cat = str(g).split(":", 1)[0].split("(", 1)[0].strip() or "?"
                cont.setdefault((str(t.get("modelo")), cat), set()).add(r.get("pasta"))
    probs = [_p(f"ficha_gratis_grave:{mod}:{cat}",
                f"ficha grátis ({mod}): grave de {cat} em {len(ps)} processo(s) em {JANELA_DIAS} dias — foram ao Haiku",
                f"exemplos: {', '.join(sorted(str(p) for p in ps)[:5])} · data/sei_ficha_gratis_recusas.jsonl",
                acao_humana="abrir as recusas, achar a regra que o modelo quebrou e medir o remédio na bancada "
                            "(lição no sistema da ficha grátis só com número COM × SEM)")
             for (mod, cat), ps in sorted(cont.items())]
    for nome, b in (bancadas or {}).items():
        if not isinstance(b, dict):
            continue
        for cat, n in sorted((b.get("graves") or {}).items()):
            if n and (str(b.get("modelo")), cat) not in cont:
                probs.append(_p(f"ficha_gratis_grave:{b.get('modelo')}:{cat}",
                                f"ficha grátis ({b.get('modelo')}): {n} grave(s) de {cat} medido(s) na bancada",
                                f"{nome} · {b.get('fonte', '')}",
                                acao_humana="remédio medido na bancada; a próxima bancada com zero fecha o item"))
    return probs


def _bancadas_coleta(regua_yaml: Path = REGUA) -> dict:
    import yaml
    try:
        return (yaml.safe_load(regua_yaml.read_text(encoding="utf-8")) or {}).get("bancadas_coleta") or {}
    except (OSError, ValueError):
        return {}


def sensor(aplicar: bool = True, agora: datetime | None = None, catalogo_md: Path | None = CATALOGO_FALHAS) -> list[dict]:
    from compliance_agent.llm import cascata_ajuste
    m = medir(agora=agora)
    probs, rebaixar = avaliar_divergencia(m["atual"], m["anterior"], m["regua"],
                                          (cascata_ajuste.ler().get("rebaixados") or {}))
    probs += avaliar_fewshot(m["pares_atuais"])
    p_disp, tirar = avaliar_disponibilidade(m["disp"])
    probs += p_disp
    probs += avaliar_candidatos(catalogo_atual(), medidos(modelos_pares=m["modelos_com_pares"]))
    probs += avaliar_ficha_gratis(RECUSAS_FICHA, _bancadas_coleta(), agora=agora)
    if aplicar:
        for t, mod, motivo, num in rebaixar:
            if cascata_ajuste.rebaixar(t, mod, motivo, num):
                logger.warning("automelhoria: %s REBAIXADO em %s — %s", mod, t, motivo)
        for rot, motivo, num in tirar:
            if cascata_ajuste.tirar(rot, motivo, num):
                logger.warning("automelhoria: %s TIRADO das cadeias — %s", rot, motivo)
        con = _ro(DATA / "conferencia_opus.db")
        try:
            ap = aprender(con, banco_casos(), catalogo_md)
        finally:
            con.close()
        for t, n in sorted(ap["por_tarefa"].items()):
            probs.append(_p(f"ensino_candidato:{t}", f"{t}: {n} erro(s) grave(s) de modelo fraco no banco de casos "
                            "negativos — ensino só como candidato", "bloco: python -m tools.automelhoria_modelos "
                            f"ensino {t}", acao_humana="medir na bancada COM × SEM o bloco antes de qualquer uso em "
                                                       "produção; promoção só com o número e o dono"))
    return probs


# ─────────────────────────── tabela (relatório) ───────────────────────────
def tabela(m: dict) -> str:
    L = ["MODELO × TAREFA — divergência do Opus (7 dias; anterior entre parênteses)",
         f"{'tarefa':<22} {'modelo':<52} {'n':>5} {'grave':>7} {'leve':>7}   (ant n / grave)"]
    for (t, mod), g in sorted(m["atual"].items(), key=lambda x: (x[0][0], -x[1]["n"])):
        a = m["anterior"].get((t, mod)) or {"n": 0, "graves": 0}
        L.append(f"{t:<22} {mod[:52]:<52} {g['n']:>5} {g['graves'] / g['n']:>7.1%} {g['leves'] / g['n']:>7.1%}   "
                 f"({a['n']} / {(a['graves'] / a['n']) if a['n'] else 0:.1%})")
    L.append("régua do Sonnet: " + (json.dumps(m["regua"], ensure_ascii=False) if m["regua"] else "nenhuma medida"))
    L += ["", "DISPONIBILIDADE (llm_trace, 7 dias)",
          f"{'provedor:modelo':<45} {'n':>6} {'ok':>6} {'ok%':>6} {'404':>4} {'dias cota':>9} {'>150s':>6} {'ms ok':>7}"]
    for d in sorted(m["disp"], key=lambda d: -d["n"]):
        L.append(f"{_rotulo(d)[:45]:<45} {d['n']:>6} {d['ok'] or 0:>6} {(d['ok'] or 0) / d['n']:>6.0%} {d['n404'] or 0:>4} "
                 f"{d['dias_cota']:>9} {d['n_timeout'] or 0:>6} {d['ms_ok'] or 0:>7}")
    return "\n".join(L)


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("tabela")
    e = sub.add_parser("ensino")
    e.add_argument("tarefa")
    e.add_argument("-k", type=int, default=3)
    a = ap.parse_args(argv)
    if a.cmd == "ensino":
        print(bloco_ensino(a.tarefa, a.k) or "(sem casos para esta tarefa)")
        return 0
    print(tabela(medir()))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(_REPO))
    sys.exit(_main())
