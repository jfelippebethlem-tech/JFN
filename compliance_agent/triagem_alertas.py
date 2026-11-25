# -*- coding: utf-8 -*-
"""triagem_alertas — juízo sobre os alertas "novo" que a Ronda acumula sem ninguém olhar.

Medido em 13/11/2026: 62.241 alertas em `alertas` com status `novo` (58.253 de acumulação de cargos),
2 confirmados e 5 descartados. Fila sem triagem é fila invisível. A triagem ORDENA a fila em rubrica fechada

    aprofundar (🔴) · monitorar (🟡) · provavel_falso_positivo (⚪) · nao_avaliavel

com nota 0–10, CITAÇÃO LITERAL do trecho do alerta em que se apoia e o próximo passo. O STATUS do alerta não
muda: confirmar ou descartar é ato humano.

Diretriz do dono: "não pode ter margem pra erro em nada. esse é um projeto de governo." Por isso cada linha
de `alertas_triagem` carrega um ESTADO:
  · VERIFICADO — duas leituras independentes concordaram (e, se 🔴/🟡, o Opus da assinatura confirmou);
  · PENDENTE   — leituras divergiram, citação não conferiu, ou o 🔴/🟡 ainda espera o Opus. Divergência
                 nunca é resolvida por palpite: vai para gente.
A citação é conferida no código (`llm/verificacao`): trecho que não existe no alerta = leitura descartada.

Três caminhos:
  · `triar_lote`        — síncrono, co-motor (Claude da assinatura × cascata), poucos por vez;
  · `enviar_lote_api` / `colher_lotes_api` — VOLUME pela Batch API (Haiku 5.5, 50%), 10 alertas por chamada,
                          parte fixa em cache; a 2ª leitura independente é a cascata gratuita;
  · `verificar_com_opus` — TODO 🔴/🟡 passa pelo Opus da assinatura; a concordância Opus×Haiku é medida no
                          cruzamento e, se cair abaixo do piso, a tarefa é PAUSADA na API e o dono avisado.
CPF vai MASCARADO no prompt (LGPD).

ORIGEM DO CONFERIDO (decisão delegada D5, 24/11/2026 — o E13 só dá Tier 1 com amostra estratificada): cada leitura do
Opus grava `origem_conferencia` — `amostra` (1 vaga a cada `AMOSTRA_A_CADA` do lote, sorteada pelo hash DENTRO de cada
detector entre os triados ainda sem Opus, qualquer prioridade: mede a FP sem o viés da fila), `cota` (alerta da
proposta `calibrar cota` em `JFN_TRIAGEM_COTA`, até `COTA_FRACAO` do lote) ou `risco` (a fila por prioridade 🔴/🟡 de
sempre). Linhas antigas ficam sem origem (o E13 lê como `legado`).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from compliance_agent.cpf_cnpj import mascarar_cpf_no_texto as mascarar_cpf
from compliance_agent.llm.verificacao import PENDENTE, VERIFICADO, citacao_existe

logger = logging.getLogger(__name__)

_REPO = Path(__file__).resolve().parents[1]
DB = _REPO / "data" / "compliance.db"
TAREFA = "triagem_alertas"
PRIORIDADES = ("aprofundar", "monitorar", "provavel_falso_positivo", "nao_avaliavel")
NIVEL = {"aprofundar": 2, "monitorar": 1, "provavel_falso_positivo": 0}
ACHADO = ("aprofundar", "monitorar")          # 🔴/🟡: todo item passa pelo Opus da assinatura
PISO_CONCORDANCIA = 0.80
AMOSTRA_MINIMA = 20
POR_CHAMADA = 10
# chaves de valor por ordem de preferência — cada detector grava o seu (medido nas evidências reais)
CHAVES_VALOR = ("valor", "soma", "total", "total_bruto", "empenhado", "total_autor", "excesso", "remuneracao")

_SYS = (
    "Você é auditor de controle externo (TCE-RJ) fazendo TRIAGEM de alertas automáticos do sistema JFN. "
    "Não é parecer: é decidir para onde o alerta vai na fila. Regras: indício não é acusação; dado ausente é "
    "INDISPONÍVEL, não irregularidade; presunção de legitimidade; nunca invente fato fora da evidência. "
    "Classifique em UMA prioridade: 'aprofundar' (sinal material e verificável que justifica abrir apuração), "
    "'monitorar' (sinal fraco ou dependente de dado que falta), 'provavel_falso_positivo' (a própria evidência "
    "explica o alerta de forma inocente ou o detector disparou por artefato), 'nao_avaliavel' (evidência "
    "insuficiente para qualquer juízo). Em 'citacao', copie LITERALMENTE um trecho (8 a 200 caracteres) do "
    "alerta em que a decisão se apoia — o sistema confere e descarta citação que não existe no alerta."
    # A/B de 14/11/2026 contra o Opus (36 alertas; treino 17, teste 19 não visto no desenho): sem esta regra
    # o Haiku marcava 🔴 pelo VALOR (fracionamento com média por OB 10× o limite de dispensa) — 21/36; com
    # ela 31/36 (teste 17/19), sem perder nenhum 🔴/🟡 do Opus. Effort medium sem a regra: 21/36 (não é o
    # effort). Mudar este texto exige novo A/B (memória prompt-mais-especifico-piorou-recall).
    " Antes de classificar, refaça o raciocínio do detector com os números da própria evidência e diga se a "
    "regra que disparou se sustenta neles — faça a conta quando a evidência permitir. Valor alto mede o "
    "TAMANHO do que está em jogo, não a existência do problema: sozinho, não é sinal. 'aprofundar' exige que "
    "a evidência mostre o padrão irregular, não apenas que o detector disparou."
)
_SCHEMA = ('{"prioridade":"aprofundar|monitorar|provavel_falso_positivo|nao_avaliavel","nota":0-10,'
           '"citacao":"trecho literal do alerta","justificativa":"1-2 frases","proximo_passo":"o que verificar"}')
_ITEM_SCHEMA = {"type": "object", "additionalProperties": False,
                "required": ["id", "prioridade", "nota", "citacao", "justificativa"],
                "properties": {"id": {"type": "integer"}, "prioridade": {"type": "string", "enum": list(PRIORIDADES)},
                               "nota": {"type": "integer"}, "citacao": {"type": "string"},
                               "justificativa": {"type": "string"}}}
FORMATO_LOTE = {"type": "object", "additionalProperties": False, "required": ["itens"],
                "properties": {"itens": {"type": "array", "items": _ITEM_SCHEMA}}}

# Versão do prompt no nome do motor do lote: o vigia de qualidade só soma pares do prompt VIGENTE (os pares do
# prompt antigo, 44% de acordo com o Opus, repausariam a tarefa pelo erro que o A/B de 14/11 já corrigiu).
VERSAO_PROMPT = hashlib.sha256(_SYS.encode()).hexdigest()[:12]


def motor_lote() -> str:
    from compliance_agent.llm import claude_api
    return f"{claude_api.MODELO_API_PADRAO}{claude_api.SUFIXO_API}-lote#{VERSAO_PROMPT}"

_DDL = """CREATE TABLE IF NOT EXISTS alertas_triagem(
  alerta_id INTEGER PRIMARY KEY, prioridade TEXT, nota INTEGER, justificativa TEXT, proximo_passo TEXT,
  valor REAL, motor TEXT, em TEXT)"""
_COLUNAS = {"estado": "TEXT", "citacao": "TEXT", "leitura_b": "TEXT", "motor_b": "TEXT",
            "opus_pendente": "INTEGER DEFAULT 0", "leitura_opus": "TEXT", "verificado_por": "TEXT", "motivo": "TEXT",
            "origem_conferencia": "TEXT"}
AMOSTRA_A_CADA = 8      # 1 vaga do lote do Opus a cada 8 vai à amostra estratificada (D5)
COTA_FRACAO = 0.25      # no máximo 1/4 do lote para a cota dos detectores de manchete (D5)
_DDL_LOTE = "CREATE TABLE IF NOT EXISTS alertas_triagem_lote(lote_id TEXT PRIMARY KEY, grupos TEXT, em TEXT)"


def garantir(con: sqlite3.Connection) -> None:
    con.execute(_DDL)
    con.execute(_DDL_LOTE)
    tem = {r[1] for r in con.execute("PRAGMA table_info(alertas_triagem)")}
    for c, t in _COLUNAS.items():
        if c not in tem:
            con.execute(f"ALTER TABLE alertas_triagem ADD COLUMN {c} {t}")


_COALESCE = "COALESCE(" + ",".join(
    f"CAST(json_extract(a.evidencias,'$.{k}') AS REAL)" for k in CHAVES_VALOR) + ",0)"


def _ids_em_lote(con) -> set[int]:
    ids: set[int] = set()
    for (g,) in con.execute("SELECT grupos FROM alertas_triagem_lote"):
        for lst in json.loads(g or "{}").values():
            ids.update(int(x) for x in lst)
    return ids


# Alerta que o PRÓPRIO detector declara "NÃO é acusação" (ex.: D3 com sanção posterior ou encerrada antes da emenda)
# não vai ao LLM: 346 dos 610 D3 triados voltaram 'provavel_falso_positivo' dizendo exatamente isso (19/11/2026).
_SEM_ACUSACAO = "COALESCE(a.descricao,'') NOT LIKE 'NÃO é acusação%'"

# DETECTOR SUSPENSO DA TRIAGEM (decisão 3 do dono, revisão crítica de 20/11/2026). Detector cujo veredito da própria
# triagem é "provável falso positivo" em metade ou mais dos casos gasta o juiz julgando o erro do detector. Ele sai
# SOZINHO da fila (lote do Haiku, co-motor e fila do Opus); o alerta segue gravado em `alertas`, intacto — só não é
# julgado. A medida é a mesma do sensor `detectores` da automelhoria (vereditos de `alertas_triagem` × `alertas.tipo`
# nos últimos FP_JANELA_DIAS dias). Volta sozinho quando a taxa da janela fica abaixo do corte ou a amostra cai abaixo
# de FP_MIN_N: sem julgamento novo, os vereditos velhos saem da janela em até 30 dias e o detector volta em
# "liberdade vigiada" — se ainda errar, juntam-se FP_MIN_N vereditos e ele sai de novo. Corte num lugar só: aqui.
FP_SUSPENDE, FP_MIN_N, FP_JANELA_DIAS = 0.50, 30, 30


def precisao_por_detector(con: sqlite3.Connection, dias: int = FP_JANELA_DIAS) -> list[tuple[str, int, int]]:
    """[(tipo, vereditos, provável falso positivo)] na janela — a medida única (triagem e automelhoria).

    Mede o que o detector AINDA manda ao juiz: veredito de alerta que hoje se declara "NÃO é acusação" (ramo já
    corrigido) fica fora. Sem isso a taxa de 21/11/2026 do D9 era 37% (158 dos 190 FP eram de ramos que a triagem
    já pula; nos que acusam, 32 de 346 = 9%) e um detector consertado seguia suspenso por até 30 dias."""
    return [(t, n, fp or 0) for t, n, fp in con.execute(
        "SELECT a.tipo, COUNT(*), SUM(t.prioridade='provavel_falso_positivo') FROM alertas_triagem t "
        f"JOIN alertas a ON a.id=t.alerta_id WHERE t.em >= date('now', ?) AND {_SEM_ACUSACAO} GROUP BY 1",
        (f"-{int(dias)} day",))]


def suspenso(n: int, fp: int) -> bool:
    return n >= FP_MIN_N and fp / n >= FP_SUSPENDE


def detectores_suspensos(con: sqlite3.Connection) -> dict[str, tuple[int, int]]:
    """{tipo: (vereditos, falsos positivos)} dos detectores fora da triagem agora. Só leitura (serve à conexão
    `mode=ro` do painel); quem escreve chama `garantir` antes."""
    return {t: (n, fp) for t, n, fp in precisao_por_detector(con) if suspenso(n, fp)}


def fora_dos_suspensos(con: sqlite3.Connection, coluna: str = "a.tipo") -> tuple[str, list[str]]:
    """Fragmento SQL (` AND coluna NOT IN (...)`) + parâmetros; vazio se nenhum detector está suspenso."""
    tipos = sorted(detectores_suspensos(con))
    if not tipos:
        return "", []
    return f" AND COALESCE({coluna},'') NOT IN ({','.join('?' * len(tipos))})", tipos


# Data do FATO no alerta (não a da detecção): as chaves que os detectores gravam nas evidências, da mais à menos
# específica. Prefeitura do Rio (pcrj_*, esfera municipal) nunca é período Couto — Couto é o Governo do Estado.
_CHAVES_DATA_FATO = ("data_ob", "data_pagamento", "data_fim", "data", "data_ini", "mes")


def data_do_alerta(a: dict):
    """Data do fato do alerta (para a cota do período Couto) ou None — sem data, o alerta vai para o resto."""
    if str(a.get("tipo") or "").startswith("pcrj_"):
        return None
    try:
        ev = json.loads(a.get("evidencias") or "{}")
    except (TypeError, ValueError):
        return None
    if not isinstance(ev, dict) or str(ev.get("esfera") or "").startswith("municipal"):
        return None
    return next((ev[k] for k in _CHAVES_DATA_FATO if ev.get(k)), None)


def selecionar(con: sqlite3.Connection, n: int) -> list[dict]:
    """Os `n` alertas `novo` ainda não triados (nem em lote pendente), do MAIOR valor em jogo para o menor.
    Alerta de detector suspenso (FP ≥ FP_SUSPENDE) não entra. FOCO (22/11/2026): metade do lote com fato do
    período Couto (`data_do_alerta`), cada metade por valor (compliance_agent/foco)."""
    from compliance_agent.foco import intercalar
    garantir(con)
    em_lote = _ids_em_lote(con)
    fora, params = fora_dos_suspensos(con)
    sql = (f"SELECT a.id, a.tipo, a.severidade, a.titulo, a.descricao, a.evidencias, "
           f"CASE WHEN json_valid(a.evidencias) THEN {_COALESCE} ELSE 0 END AS v "
           "FROM alertas a LEFT JOIN alertas_triagem t ON t.alerta_id = a.id "
           f"WHERE a.status = 'novo' AND t.alerta_id IS NULL AND {_SEM_ACUSACAO}{fora} ORDER BY v DESC, a.id")
    cols = ("id", "tipo", "severidade", "titulo", "descricao", "evidencias", "valor")
    linhas = (dict(zip(cols, r)) for r in con.execute(sql, params))
    return intercalar((x for x in linhas if x["id"] not in em_lote), data_do_alerta, limite=n)


def texto_do_alerta(a: dict) -> str:
    """O texto do alerta como o modelo o vê (CPF mascarado) — é contra ele que a citação é conferida."""
    evid = a.get("evidencias") or ""
    try:
        evid = json.dumps(json.loads(evid), ensure_ascii=False)
    except (TypeError, ValueError):
        logger.debug("triagem: evidências do alerta %s não são JSON — vão como texto", a.get("id"))
    return mascarar_cpf(
        f"ALERTA #{a['id']} — tipo {a.get('tipo')} · severidade do detector {a.get('severidade')}\n"
        f"TÍTULO: {(a.get('titulo') or '')[:300]}\n"
        f"DESCRIÇÃO: {(a.get('descricao') or '')[:1500]}\n"
        f"EVIDÊNCIAS (JSON do detector): {evid[:2500]}")


def montar_prompt(a: dict) -> str:
    return texto_do_alerta(a) + f"\n\nFaça a triagem. Responda SOMENTE com o JSON: {_SCHEMA}"


def interpretar(txt) -> dict:
    from compliance_agent.llm.json_resposta import parse_json_llm
    d = txt if isinstance(txt, dict) else parse_json_llm(txt or "")
    d = d if isinstance(d, dict) else {}
    p = str(d.get("prioridade") or "").strip().lower()
    try:
        nota = int(round(float(d.get("nota"))))
        nota = nota if 0 <= nota <= 10 else None
    except (TypeError, ValueError):
        nota = None
    if p not in PRIORIDADES:
        return {"prioridade": None, "nota": None, "citacao": "", "justificativa": "resposta fora da rubrica",
                "proximo_passo": ""}
    return {"prioridade": p, "nota": nota, "citacao": str(d.get("citacao") or "")[:400],
            "justificativa": str(d.get("justificativa") or "")[:600],
            "proximo_passo": str(d.get("proximo_passo") or "")[:300]}


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _gravar(con, a: dict, r: dict, *, motor: str, estado: str, leitura_b=None, motor_b=None, motivo: str = "",
            contingencia: bool = False) -> None:
    # 🔴/🟡 sempre ao Opus; leitura descartada (fora da rubrica, citação que não confere) escala para o Opus;
    # `contingencia` = feito sem o Claude da assinatura ⇒ o Opus confere SEMPRE (dono, 14/11/2026)
    opus = int(r.get("prioridade") in ACHADO or r.get("prioridade") is None or motivo.startswith("citação")
               or contingencia)
    con.execute("INSERT OR REPLACE INTO alertas_triagem(alerta_id,prioridade,nota,justificativa,proximo_passo,valor,"
                "motor,em,estado,citacao,leitura_b,motor_b,opus_pendente,motivo) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (a["id"], r.get("prioridade"), r.get("nota"), r.get("justificativa"), r.get("proximo_passo"),
                 a.get("valor"), motor, _agora(), estado, r.get("citacao"), leitura_b, motor_b, opus, motivo or None))
    con.commit()                  # transação curta por alerta: o painel lê o mesmo banco


def _conferir(a: dict, r: dict) -> str:
    """'' se a leitura vale; senão o motivo do descarte (citação ausente ou inexistente no alerta)."""
    if r["prioridade"] is None:
        return "resposta fora da rubrica"
    if r["prioridade"] != "nao_avaliavel" and not citacao_existe(r["citacao"], texto_do_alerta(a)):
        return "citação não confere com o texto do alerta"
    return ""


# ── caminho síncrono (co-motor) ──────────────────────────────────────────────────────────────────────
def triar_lote(con: sqlite3.Connection, n: int = 8, *, gerar=None) -> list[dict]:
    """Tria até `n` alertas pelo co-motor. Duas leituras (Claude × cascata): concordaram ⇒ VERIFICADO (🔴/🟡 ainda
    vão ao Opus); divergiram ou citação falhou ⇒ PENDENTE. Falha do motor num alerta não aborta o lote."""
    if gerar is None:
        from compliance_agent.llm.comotor import juizo
        gerar = juizo(TAREFA, conferencia=False)   # a fila de Opus da triagem é a própria coluna opus_pendente
    from compliance_agent.llm import claude_api
    from compliance_agent.llm.comotor import ultima_chamada
    feitos = []
    for a in selecionar(con, n):
        try:
            bruto = gerar(montar_prompt(a), _SYS, 60.0, True, item=f"alerta:{a['id']}")
        except TypeError:          # gerar dublê/antigo sem `item`
            bruto = gerar(montar_prompt(a), _SYS)
        except (RuntimeError, OSError, ValueError) as e:  # motor fora: o alerta volta no próximo lote
            logger.warning("triagem: alerta %s sem juízo (%s)", a["id"], type(e).__name__)
            continue
        r = interpretar(bruto)
        u = ultima_chamada()
        motivo = _conferir(a, r)
        concordou = u.get("divergencia") is False and bool(u.get("outro"))
        estado = VERIFICADO if (not motivo and concordou and r["prioridade"] not in ACHADO) else PENDENTE
        if not motivo and not concordou:
            motivo = "sem segunda leitura concordante"
        exibido = str(u.get("exibido") or "")
        sem_assinatura = not exibido.startswith("claude:") or claude_api.pela_api(exibido)
        if sem_assinatura:            # contingência: nunca VERIFICADO sem o Opus, mesmo ⚪ com duas leituras
            estado = PENDENTE
            motivo = motivo or "feito sem o Claude da assinatura — aguarda conferência do Opus"
        _gravar(con, a, r, motor=u.get("exibido") or "desconhecido", estado=estado, motor_b=u.get("outro"),
                motivo=motivo, contingencia=sem_assinatura)
        feitos.append({"id": a["id"], **r, "motor": u.get("exibido") or "desconhecido", "estado": estado})
    return feitos


# ── volume: Batch API (Haiku) + 2ª leitura pela cascata ─────────────────────────────────────────────
def _prompt_grupo(alertas: list[dict]) -> str:
    blocos = "\n\n---\n\n".join(texto_do_alerta(a) for a in alertas)
    return (f"Faça a triagem de CADA um dos {len(alertas)} alertas abaixo (um item por alerta, com o id do "
            f"alerta).\n\n{blocos}")


def enviar_lote_api(con: sqlite3.Connection, n: int = 200, *, por_chamada: int = POR_CHAMADA, cliente=None) -> str | None:
    """Piloto/volume: `n` alertas por valor, `por_chamada` por pedido, um lote na Batch API. Devolve o id."""
    from compliance_agent.llm import claude_api
    alertas = selecionar(con, n)
    if not alertas:
        return None
    grupos = [alertas[i:i + por_chamada] for i in range(0, len(alertas), por_chamada)]
    itens = [(f"g{i}", _prompt_grupo(g)) for i, g in enumerate(grupos)]
    lote = claude_api.enviar_lote(TAREFA, itens, sistema=_SYS, max_tokens=400 * por_chamada + 1500, effort="low",
                                  formato=FORMATO_LOTE, n_decisoes=len(alertas), cliente=cliente)
    if lote:
        con.execute("INSERT INTO alertas_triagem_lote VALUES(?,?,?)",
                    (lote, json.dumps({f"g{i}": [a["id"] for a in g] for i, g in enumerate(grupos)}), _agora()))
        con.commit()
    else:
        logger.warning("triagem: lote não enviado — %s", claude_api.ultimo_motivo)
    return lote


def _segunda_leitura(alertas: list[dict], gerar_b) -> dict[int, str | None]:
    """Leitura INDEPENDENTE do mesmo grupo pela cascata gratuita: {alerta_id: prioridade|None}."""
    try:
        bruto = gerar_b(_prompt_grupo(alertas) + '\n\nResponda SOMENTE com o JSON {"itens":[{"id":0,'
                        '"prioridade":"...","nota":0,"citacao":"...","justificativa":"..."}]}', _SYS)
    except (RuntimeError, OSError, ValueError, TypeError) as e:
        logger.warning("triagem: 2ª leitura indisponível (%s)", type(e).__name__)
        return {}
    from compliance_agent.llm.json_resposta import parse_json_llm
    d = parse_json_llm(bruto or "")
    itens = d.get("itens") if isinstance(d, dict) else d if isinstance(d, list) else []
    saida = {}
    for x in itens or []:
        if isinstance(x, dict):
            try:
                saida[int(x.get("id"))] = interpretar(x)["prioridade"]
            except (TypeError, ValueError):
                continue
    return saida


def colher_lotes_api(con: sqlite3.Connection, *, cliente=None, gerar_b=None) -> int:
    """Colhe lotes terminados. Cada item: citação conferida; 2ª leitura (cascata) concordou ⇒ VERIFICADO
    (exceto 🔴/🟡, que esperam o Opus); senão PENDENTE. Devolve quantos alertas foram gravados."""
    from compliance_agent.llm import claude_api
    if gerar_b is None:
        from compliance_agent.direcionamento_cerebro import gerar_sync
        gerar_b = (lambda p, s: gerar_sync(p, s, 90.0))
    garantir(con)
    gravados = 0
    for lote_id, grupos_js in con.execute("SELECT lote_id, grupos FROM alertas_triagem_lote").fetchall():
        res = claude_api.colher_lote(lote_id, cliente=cliente)
        if res is None:
            continue
        grupos = json.loads(grupos_js)
        modelo = motor_lote()
        for gid, ids in grupos.items():
            ja = {r[0] for r in con.execute(f"SELECT alerta_id FROM alertas_triagem WHERE alerta_id IN "
                                            f"({','.join('?' * len(ids))})", ids)}
            alertas = [a for a in _por_ids(con, ids) if a["id"] not in ja]   # colheita retomada: só o que falta
            if not alertas:
                continue
            from compliance_agent.llm.json_resposta import parse_json_llm
            d = parse_json_llm(res.get(gid) or "")
            lidos = {}
            for x in (d.get("itens") if isinstance(d, dict) else []) or []:
                try:
                    lidos[int(x.get("id"))] = interpretar(x)
                except (TypeError, ValueError, AttributeError):
                    continue
            b = _segunda_leitura(alertas, gerar_b) if lidos else {}
            for a in alertas:
                r = lidos.get(a["id"])
                if r is None:
                    continue                       # sem leitura: volta para a fila no próximo lote
                motivo = _conferir(a, r)
                pb = b.get(a["id"])
                concordou = not motivo and pb is not None and pb == r["prioridade"]
                estado = VERIFICADO if concordou and r["prioridade"] not in ACHADO else PENDENTE
                if not motivo and not concordou:
                    motivo = "2ª leitura divergiu ou faltou" if pb != r["prioridade"] else ""
                _gravar(con, a, r, motor=modelo, estado=estado, leitura_b=pb, motor_b="cascata", motivo=motivo)
                gravados += 1
        con.execute("DELETE FROM alertas_triagem_lote WHERE lote_id=?", (lote_id,))
        con.commit()
    fora, params = fora_dos_suspensos(con)
    restantes = con.execute("SELECT COUNT(*) FROM alertas a LEFT JOIN alertas_triagem t ON t.alerta_id=a.id "
                            f"WHERE a.status='novo' AND t.alerta_id IS NULL AND {_SEM_ACUSACAO}{fora}",
                            params).fetchone()[0]
    claude_api.registrar_restantes(TAREFA, restantes)
    return gravados


def _por_ids(con, ids: list[int]) -> list[dict]:
    cols = ("id", "tipo", "severidade", "titulo", "descricao", "evidencias", "valor")
    q = ",".join("?" * len(ids))
    rows = con.execute(f"SELECT a.id, a.tipo, a.severidade, a.titulo, a.descricao, a.evidencias, "
                       f"CASE WHEN json_valid(a.evidencias) THEN {_COALESCE} ELSE 0 END "
                       f"FROM alertas a WHERE a.id IN ({q})", ids).fetchall()
    return [dict(zip(cols, r)) for r in rows]


# ── origem do conferido (D5): amostra estratificada por detector e cota de manchete ──────────────────
def _hash_amostra(aid) -> int:
    return int(hashlib.sha1(f"amostra-triagem\x00{aid}".encode()).hexdigest()[:12], 16)


def amostra_estratificada(con: sqlite3.Connection, k: int, fora: str = "", params: list | None = None) -> list[int]:
    """Até `k` alerta_id triados e ainda sem leitura do Opus, de QUALQUER prioridade, um por detector (`tipo`) por
    vez: dentro de cada detector, a ordem é o hash (sorteio determinístico); os detectores se revezam pela ordem do
    hash do 1º de cada um. Alerta "NÃO é acusação" fica fora (o E13 também o tira)."""
    if k <= 0:
        return []
    por: dict[str, list[int]] = {}
    for aid, tipo in con.execute("SELECT t.alerta_id, a.tipo FROM alertas_triagem t JOIN alertas a ON a.id=t.alerta_id "
                                 f"WHERE t.verificado_por IS NULL AND {_SEM_ACUSACAO}{fora}", params or []):
        por.setdefault(str(tipo or ""), []).append(int(aid))
    filas = sorted((sorted(v, key=_hash_amostra) for v in por.values()), key=lambda v: _hash_amostra(v[0]))
    out: list[int] = []
    while len(out) < k and any(filas):
        for v in filas:
            if v and len(out) < k:
                out.append(v.pop(0))
    return out


def cota_ids(caminho: str | None = None) -> list[int]:
    """alerta_id da proposta `calibrar cota` (`{"candidatos": {detector: ["alerta:<id>", ...]}}`) em `JFN_TRIAGEM_COTA`.
    Sem arquivo ⇒ []. Arquivo ilegível ⇒ [] com aviso (a cota é opcional; nunca derruba a rodada)."""
    import os
    p = caminho or os.environ.get("JFN_TRIAGEM_COTA")
    if not p:
        return []
    try:
        cand = json.loads(Path(p).read_text(encoding="utf-8")).get("candidatos") or {}
        return [int(str(x).split(":", 1)[1]) for v in cand.values() for x in v if str(x).startswith("alerta:")]
    except (OSError, ValueError, AttributeError, IndexError) as e:
        logger.warning("triagem: cota ilegível (%s) — rodada sem cota", type(e).__name__)
        return []


# ── Opus da assinatura: todo 🔴/🟡 e o que ficou pendente por citação ───────────────────────────────
def verificar_com_opus(con: sqlite3.Connection, n: int = 10, *, pensar=None, avisar=None) -> list[dict]:
    """Opus (assinatura) relê os itens com `opus_pendente`. Concordou ⇒ VERIFICADO; divergiu ⇒ PENDENTE (vai
    para gente, nunca auto-resolvido). Cada par Opus×leitura anterior entra no cruzamento; se a concordância
    do Haiku cair abaixo do piso, a tarefa é PAUSADA na API e o dono avisado."""
    from compliance_agent.llm import claude_motor, cruzamento
    pensar = pensar or claude_motor.pensar
    garantir(con)
    fora, params = fora_dos_suspensos(con)      # detector suspenso: o item espera, com opus_pendente=1, a volta dele
    # FOCO (22/11/2026): metade do lote com fato do período Couto; dentro de cada metade, 🔴 primeiro e valor
    from compliance_agent.foco import intercalar
    rows = intercalar(con.execute("SELECT t.alerta_id, t.prioridade, t.motor, a.tipo, a.evidencias "
                                  "FROM alertas_triagem t "
                                  "LEFT JOIN alertas a ON a.id=t.alerta_id WHERE t.opus_pendente=1" + fora +
                                  " ORDER BY CASE t.prioridade WHEN 'aprofundar' THEN 0 WHEN 'monitorar' THEN 1 "
                                  "ELSE 2 END, t.valor DESC", params),   # 🔴 primeiro: 273 de 5.145 na fila (14/11)
                      lambda r: data_do_alerta({"tipo": r[3], "evidencias": r[4]}), limite=n)
    # D5: vagas da amostra estratificada e da cota entram no lugar das últimas da fila por prioridade
    am = amostra_estratificada(con, n // AMOSTRA_A_CADA, fora, params)
    cids = cota_ids()
    pend_cota = {r[0] for r in con.execute("SELECT alerta_id FROM alertas_triagem WHERE opus_pendente=1 AND "
                                           "verificado_por IS NULL")} if cids else set()
    ct = [a for a in cids if a in pend_cota and a not in am][:int(n * COTA_FRACAO)]
    especiais = [(a, "amostra") for a in am] + [(a, "cota") for a in ct]
    base = [r for r in rows if r[0] not in {a for a, _ in especiais}][: max(0, n - len(especiais))]
    meta = {a: con.execute("SELECT prioridade, motor FROM alertas_triagem WHERE alerta_id=?", (a,)).fetchone()
            for a, _ in especiais}
    lote = [(r[0], r[1], r[2], "risco") for r in base] + [(a, *(meta[a] or (None, None)), o) for a, o in especiais]
    feitos = []
    for aid, prio, motor, origem in lote:
        a = (_por_ids(con, [aid]) or [None])[0]
        if a is None:
            continue
        p = pensar("verificacao_opus", montar_prompt(a), modelo=claude_motor.MODELO_JUIZO, sistema=_SYS, backend="cli")
        if p is None:
            break                                   # sem cota da assinatura: para e retoma depois
        r = interpretar(p.texto)
        if _conferir(a, r):
            r["prioridade"] = None                  # citação do Opus também precisa conferir
        cruzamento.cruzar(TAREFA, f"alerta:{aid}",
                          cruzamento.Lado("claude", p.modelo, r["prioridade"], NIVEL.get(r["prioridade"] or "")),
                          cruzamento.Lado("cascata", motor or "?", prio, NIVEL.get(prio or "")),
                          entrada_resumo=texto_do_alerta(a)[:600])
        estado = VERIFICADO if (r["prioridade"] is not None and r["prioridade"] == prio) else PENDENTE
        con.execute("UPDATE alertas_triagem SET opus_pendente=0, leitura_opus=?, verificado_por=?, estado=?, "
                    "motivo=?, origem_conferencia=? WHERE alerta_id=?",
                    (r["prioridade"], p.modelo, estado, None if estado == VERIFICADO else "Opus divergiu — revisão humana",
                     origem, aid))
        if estado == PENDENTE and r["prioridade"] is not None:
            # divergência com leitura válida do Opus: o resultado do Opus PREVALECE (dono, 14/11/2026); o item
            # segue PENDENTE de revisão humana e a leitura anterior fica registrada no motivo e no cruzamento
            con.execute("UPDATE alertas_triagem SET prioridade=?, nota=?, justificativa=?, proximo_passo=?, citacao=?, "
                        "motivo=? WHERE alerta_id=?",
                        (r["prioridade"], r["nota"], r["justificativa"], r["proximo_passo"], r["citacao"],
                         f"Opus divergiu de {motor or '?'} (dizia {prio or 'indeterminado'}) — prevalece o Opus; "
                         "revisão humana", aid))
        con.commit()
        feitos.append({"id": aid, "anterior": prio, "opus": r["prioridade"], "estado": estado, "origem": origem})
    vigiar_qualidade(avisar=avisar)
    return feitos


def vigiar_qualidade(*, avisar=None) -> dict | None:
    """Concordância Opus × Haiku (API) na triagem. Abaixo do piso com amostra mínima ⇒ pausa na API + aviso."""
    from compliance_agent.llm import claude_api, cruzamento
    c = cruzamento.concordancia(dias=30, tarefa=TAREFA)
    linhas = [x for x in c["por_tarefa_modelo"] if (x["modelo"] or "").endswith(f"#{VERSAO_PROMPT}")]
    n = sum(x["n"] for x in linhas)
    if n < AMOSTRA_MINIMA:
        return None
    taxa = sum(x["acordos"] for x in linhas) / n
    if taxa < PISO_CONCORDANCIA and TAREFA not in claude_api.ler_gasto()["pausadas"]:
        motivo = f"concordância Opus×Haiku {taxa:.0%} em {n} itens (< {PISO_CONCORDANCIA:.0%})"
        claude_api.pausar(TAREFA, motivo)
        (avisar or _avisar)(f"🟡 <b>Triagem pela API pausada</b> — {motivo}. Calibrar (Sonnet numa amostra) antes "
                            "de retomar.")
    return {"n": n, "taxa": round(taxa, 3)}


def _avisar(texto: str) -> bool:
    from compliance_agent.llm.claude_motor import avisar_dono
    return avisar_dono(texto)


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Triagem dos alertas 'novo' da Ronda (co-motor, Batch API, Opus)")
    ap.add_argument("--lote", type=int, default=0, help="síncrono pelo co-motor (Claude × cascata)")
    ap.add_argument("--api-enviar", type=int, default=0, help="envia N alertas à Batch API (Haiku); piloto ~200")
    ap.add_argument("--api-colher", action="store_true", help="colhe os lotes terminados")
    ap.add_argument("--opus", type=int, default=0, help="verifica N itens 🔴/🟡/pendentes com o Opus da assinatura")
    ap.add_argument("--db", default=str(DB))
    a = ap.parse_args(argv)
    con = sqlite3.connect(a.db, timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    try:
        if a.lote:
            for f in triar_lote(con, a.lote):
                print(f"  alerta {f['id']}: {f['prioridade']} {f['estado']} motor={f['motor']}")
        if a.api_colher:
            print(f"[triagem] colhidos e gravados: {colher_lotes_api(con)}")
        if a.api_enviar:
            print(f"[triagem] lote enviado: {enviar_lote_api(con, a.api_enviar)}")
        if a.opus:
            for f in verificar_com_opus(con, a.opus):
                print(f"  alerta {f['id']}: {f['anterior']} → opus {f['opus']} = {f['estado']}")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
