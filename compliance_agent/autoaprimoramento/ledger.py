# -*- coding: utf-8 -*-
"""ledger — a verdade de chão da perícia de execução, com o PORQUÊ.

Três tabelas em `data/autoaprimoramento/auto.db` (só acréscimo; nada é apagado nem regravado):
  laudo_versao       cada laudo que um motor deu a um processo, com proveniência e NÍVEL DE PROVA
                     (0 modelo de volume · 1 Opus sobre o resumo · 2 conferência na fonte primária: íntegra SEI + OB SIAFE)
  conferencia        o par (laudo de nível menor → laudo de nível maior) do mesmo processo: é o rótulo
  indicio_conferido  cada indício do laudo verificado: confirmado | descartado (com a armadilha e o porquê) | lacuna

Por que existe: `lex_execucao.aplicar_conferencia` e o upsert do sweep REGRAVAM a linha do processo — o laudo anterior
sumia. Medido em 18/11/2026: de 72 laudos escritos por agentes na fonte primária, só 10 estavam na base no fim do dia.
`arquivar_linha` é chamada por `lex_execucao` antes de toda regravação (melhor esforço, nunca levanta).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from pathlib import Path

from . import armadilhas, config

_DDL = """
CREATE TABLE IF NOT EXISTS laudo_versao(
  id INTEGER PRIMARY KEY, numero_sei TEXT NOT NULL, motor TEXT NOT NULL, modelo_bruto TEXT, nivel_prova INTEGER NOT NULL,
  execucao TEXT, coerencia TEXT, nota INTEGER, indicios TEXT, duvidas TEXT, resumo TEXT, em_laudo TEXT,
  origem TEXT NOT NULL, hash TEXT NOT NULL, capturado_em TEXT NOT NULL, UNIQUE(numero_sei, hash));
CREATE INDEX IF NOT EXISTS ix_versao_proc ON laudo_versao(numero_sei, nivel_prova);
CREATE TABLE IF NOT EXISTS conferencia(
  id INTEGER PRIMARY KEY, numero_sei TEXT NOT NULL, antes_id INTEGER NOT NULL, depois_id INTEGER NOT NULL,
  motor_antes TEXT, nivel_antes INTEGER, nivel_depois INTEGER, nota_antes INTEGER, nota_depois INTEGER,
  alto_antes INTEGER, alto_depois INTEGER, conjunto TEXT NOT NULL, amostra TEXT NOT NULL DEFAULT 'dirigida',
  prob_inclusao REAL, valor_pago REAL, tipo_processo TEXT, criado_em TEXT NOT NULL, UNIQUE(antes_id, depois_id));
CREATE INDEX IF NOT EXISTS ix_conf_proc ON conferencia(numero_sei);
CREATE TABLE IF NOT EXISTS indicio_conferido(
  id INTEGER PRIMARY KEY, numero_sei TEXT NOT NULL, depois_id INTEGER NOT NULL, texto TEXT NOT NULL,
  desfecho TEXT NOT NULL, armadilha TEXT, porque TEXT, UNIQUE(depois_id, texto));
CREATE TABLE IF NOT EXISTS consulta_teste(
  id INTEGER PRIMARY KEY, em TEXT NOT NULL, quem TEXT NOT NULL, motivo TEXT NOT NULL);
"""

_RE_ANTECESSOR = re.compile(r"\(conferência; (?:antes|concordou com) (.*)\)\s*$", re.S)
_RE_LEU_FONTE = re.compile(r"\blid[oa]s?\b|autos SEI|SIAFE", re.I)
_RE_DESCARTADO = re.compile(r"^\s*Descartad[oa]s?:\s*(.+?)\s+[—–]\s+(.+)$", re.S)
_RE_LACUNA = re.compile(r"lacuna de leitura|n[aã]o ind[ií]cio material|INDISPON[IÍ]VEL|n[aã]o capturad", re.I)


def _agora() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def conectar(caminho: Path | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(caminho or config.banco(), timeout=20)
    con.executescript(_DDL)
    return con


def motor_e_nivel(modelo: str | None) -> tuple[str, int]:
    """Proveniência gravada em `lex_execucao.modelo` → (motor canônico, nível de prova). -1 = regra (não é juízo).

    Nível 2 só para quem LEU A FONTE: 'agente Claude Code'/'fonte primária', ou 'sessão Claude Code' com a peça lida
    declarada. A 'sessão Claude Code, conferência manual' sem qualificador releu só a entrada do prompt (o script
    daquela conferência diz) — é nível 1, igual à conferência do Opus."""
    m = (modelo or "").strip()
    if not m or m.lower() == "desconhecido":
        return "desconhecido", config.NIVEL_FRACO
    if m.startswith("regra:"):
        return "regra", -1
    cabeca = m.split(" (conferência;")[0]
    if "fonte primária" in cabeca or "agente Claude Code" in cabeca:
        return "claude:fonte-primaria", config.NIVEL_FONTE
    if "sessão Claude Code" in cabeca:
        qualif = cabeca.split("conferência manual", 1)[-1]
        if _RE_LEU_FONTE.search(qualif):
            return "claude:fonte-primaria", config.NIVEL_FONTE
        return "claude-opus:resumo", config.NIVEL_RESUMO
    if "· conferido claude" in m or "opus" in cabeca.lower():
        return "claude-opus:resumo", config.NIVEL_RESUMO
    if cabeca.startswith("claude:"):
        return cabeca.split(" ")[0].replace("claude:claude-", "claude-").replace("-5-5", ""), config.NIVEL_FRACO
    return cabeca.split(" ")[0], config.NIVEL_FRACO


def antecessor(modelo: str | None) -> str | None:
    """'… (conferência; antes X)' → X (a proveniência que a conferência substituiu)."""
    m = _RE_ANTECESSOR.search(modelo or "")
    return m.group(1).strip() if m else None


def conjunto_de(numero_sei: str) -> str:
    """Partição FIXA por processo (hash do número): 50% treino · 25% validação · 25% teste. O teste fica congelado —
    toda leitura dele passa por `consultar_teste` (orçamento por trimestre, Dwork et al. 2015)."""
    h = int(hashlib.sha1(("jfn-auto:" + numero_sei).encode()).hexdigest()[:8], 16) % 100
    return "treino" if h < 50 else "validacao" if h < 75 else "teste"


def _lista(v) -> list:
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            return [v] if v.strip() else []
    return [str(x) for x in v] if isinstance(v, list) else []


def _nota(v) -> int | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return int(round(x)) if 0 <= x <= 10 else None


def registrar_versao(con: sqlite3.Connection, numero_sei: str, laudo: dict, modelo_bruto: str | None, origem: str,
                     em_laudo: str | None = None, motor: str | None = None, nivel: int | None = None) -> int | None:
    """Acrescenta uma versão de laudo (idempotente pelo conteúdo). Devolve o id, ou None para regra/laudo sem nota."""
    m, n = motor_e_nivel(modelo_bruto)
    motor, nivel = motor or m, n if nivel is None else nivel
    nota = _nota(laudo.get("nota_risco_execucao", laudo.get("nota_risco")))
    if nivel < 0 or nota is None:
        return None
    ind = laudo.get("indicios")
    campos = (laudo.get("execucao_comprovada"), laudo.get("coerencia_objeto_evidencia", laudo.get("coerencia")), nota,
              None if ind is None else json.dumps(_lista(ind), ensure_ascii=False),
              None if laudo.get("duvidas") is None else json.dumps(_lista(laudo.get("duvidas")), ensure_ascii=False),
              laudo.get("resumo"))
    h = hashlib.sha1(json.dumps([motor, nivel, *campos], ensure_ascii=False, default=str).encode()).hexdigest()
    con.execute("INSERT OR IGNORE INTO laudo_versao(numero_sei,motor,modelo_bruto,nivel_prova,execucao,coerencia,nota,"
                "indicios,duvidas,resumo,em_laudo,origem,hash,capturado_em) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (numero_sei, motor, (modelo_bruto or "")[:300], nivel, *campos,
                 (em_laudo or "")[:19].replace(" ", "T") or None, origem, h, _agora()))
    return con.execute("SELECT id FROM laudo_versao WHERE numero_sei=? AND hash=?", (numero_sei, h)).fetchone()[0]


def _sem_banco() -> bool:
    """Sob pytest o gancho só grava se o teste apontar um diretório próprio (nunca no ledger de produção)."""
    return bool(os.environ.get("PYTEST_CURRENT_TEST")) and not os.environ.get("JFN_AUTOAPRIMORAMENTO_DIR")


def arquivar_linha(numero_sei: str, linha: dict | None, origem: str = "gancho:lex_execucao",
                   modelo: str | None = None) -> None:
    """Guarda uma versão de laudo no ledger. Melhor esforço — a perícia nunca para por causa do ledger (banco à
    parte, espera curta)."""
    if not linha or _sem_banco():
        return
    try:
        con = sqlite3.connect(config.banco(), timeout=2)
        try:
            con.executescript(_DDL)
            registrar_versao(con, numero_sei, linha, modelo or linha.get("modelo"), origem, linha.get("em"))
            con.commit()
        finally:
            con.close()
    except (sqlite3.Error, OSError, ValueError, TypeError):
        return


def antes_de_regravar(numero_sei: str, vigente: dict, modelo_novo: str | None, laudo_novo: dict | None = None) -> bool:
    """Gancho de `lex_execucao` em toda regravação. Arquiva a linha vigente e responde se ela está PROTEGIDA:
    laudo conferido na fonte primária (nível 2) só é substituído por outro de nível 2. Quando protege, o laudo que
    ia entrar também é arquivado — nada se perde, só não vira o laudo vigente."""
    arquivar_linha(numero_sei, vigente)
    protegido = nivel_gravado(vigente.get("modelo")) == config.NIVEL_FONTE and \
        nivel_gravado(modelo_novo) < config.NIVEL_FONTE
    if protegido and laudo_novo:
        arquivar_linha(numero_sei, laudo_novo, "recusado:prova-primaria-vigente", modelo_novo)
    return protegido


def nivel_gravado(modelo: str | None) -> int:
    return motor_e_nivel(modelo)[1]


def indicios_do_verificado(laudo: dict) -> list[dict]:
    """Laudo conferido na fonte → [{texto, desfecho, armadilha, porque}]. 'Descartado: <indício> — <por quê>' nas
    dúvidas é indício do laudo anterior que caiu; o que ficou em `indicios` é confirmado (ou lacuna de leitura)."""
    out = []
    for d in _lista(laudo.get("duvidas")):
        m = _RE_DESCARTADO.match(d)
        if m:
            texto, porque = m.group(1).strip(" '\"“”‘’"), m.group(2).strip()
            out.append({"texto": texto, "desfecho": "descartado", "porque": porque,
                        "armadilha": armadilhas.classificar(texto, porque)})
    for i in _lista(laudo.get("indicios")):
        out.append({"texto": i, "desfecho": "lacuna" if _RE_LACUNA.search(i) else "confirmado", "porque": None,
                    "armadilha": None})
    return out


def conciliar(con: sqlite3.Connection, valores: dict | None = None, tipos: dict | None = None) -> dict:
    """Monta os pares (nível menor → nível maior) por processo e os indícios conferidos. Idempotente.
    `valores`/`tipos`: {numero_sei: valor pago no SIAFE / tipo de processo}, quando o chamador os tem."""
    valores, tipos = valores or {}, tipos or {}
    novos = 0
    por: dict[str, list] = {}
    for r in con.execute("SELECT id,numero_sei,motor,nivel_prova,nota,indicios,duvidas,em_laudo FROM laudo_versao "
                         "ORDER BY numero_sei, nivel_prova, COALESCE(em_laudo,''), id"):
        por.setdefault(r[1], []).append(r)
    for ns, vs in por.items():
        topo = {}                                   # a versão mais recente de cada nível de conferência
        for v in vs:
            if v[3] >= config.NIVEL_RESUMO:
                topo[v[3]] = v
        for nivel_d, d in topo.items():
            for a in vs:
                if a[3] >= nivel_d or a[0] == d[0]:
                    continue
                if a[7] and d[7] and a[7] > d[7]:
                    continue                        # laudo fraco POSTERIOR à conferência julgou outra captura
                if a[3] == config.NIVEL_RESUMO and a is not topo.get(config.NIVEL_RESUMO):
                    continue                        # Opus-resumo superado por outro Opus-resumo não é par
                cur = con.execute(
                    "INSERT OR IGNORE INTO conferencia(numero_sei,antes_id,depois_id,motor_antes,nivel_antes,nivel_depois,"
                    "nota_antes,nota_depois,alto_antes,alto_depois,conjunto,valor_pago,tipo_processo,criado_em) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (ns, a[0], d[0], a[2], a[3], nivel_d, a[4], d[4], int(a[4] >= config.ALTO), int(d[4] >= config.ALTO),
                     conjunto_de(ns), valores.get(ns), tipos.get(ns), _agora()))
                novos += cur.rowcount
            if nivel_d == config.NIVEL_FONTE:
                for i in indicios_do_verificado({"indicios": d[5], "duvidas": d[6]}):
                    con.execute("INSERT OR IGNORE INTO indicio_conferido(numero_sei,depois_id,texto,desfecho,armadilha,"
                                "porque) VALUES(?,?,?,?,?,?)", (ns, d[0], i["texto"][:1000], i["desfecho"],
                                                               i["armadilha"], (i["porque"] or "")[:1500] or None))
    con.commit()
    return {"pares_novos": novos, "processos": len(por)}


def rotulos(con: sqlite3.Connection, conjuntos: tuple[str, ...] = ("treino",), nivel_min: int = config.NIVEL_RESUMO,
            com_texto: bool = False) -> list[dict]:
    """Um rótulo por laudo de nível 0: o desfecho no MAIOR nível de prova disponível (fonte primária > Opus-resumo).
    Nunca devolve o conjunto de teste por aqui — use `consultar_teste`."""
    if "teste" in conjuntos:
        raise ValueError("o conjunto de teste só é lido por consultar_teste (orçamento de consultas)")
    return _rotulos(con, conjuntos, nivel_min, com_texto)


def _rotulos(con, conjuntos, nivel_min, com_texto) -> list[dict]:
    q = ("SELECT c.numero_sei, c.motor_antes, c.nota_antes, c.nota_depois, c.alto_depois, c.nivel_depois, c.conjunto, "
         "c.valor_pago, c.tipo_processo, a.indicios, a.id FROM conferencia c JOIN laudo_versao a ON a.id=c.antes_id "
         f"WHERE c.nivel_antes=0 AND c.nivel_depois>=? AND c.conjunto IN ({','.join('?' * len(conjuntos))}) "
         "ORDER BY c.antes_id, c.nivel_depois DESC")
    melhor: dict[tuple, tuple] = {}
    for r in con.execute(q, (nivel_min, *conjuntos)):
        if com_texto and r[9] is None:
            continue
        # o mesmo laudo fraco chega por mais de uma fonte (fila com texto, log só com a nota): um rótulo por
        # (processo, nota), preferindo o maior nível de prova, depois quem tem texto e motor conhecido
        chave, ordem = (r[0], r[2]), (r[5], r[9] is not None, r[1] != "desconhecido")
        if chave not in melhor or ordem > melhor[chave][0]:
            melhor[chave] = (ordem, r)
    out = []
    for _, r in sorted(melhor.values(), key=lambda x: (x[1][0], x[1][2])):
        out.append({"numero_sei": r[0], "motor": r[1], "nota": r[2], "nota_verificada": r[3], "alto_verificado": r[4],
                    "nivel_rotulo": r[5], "conjunto": r[6], "valor_pago": r[7], "tipo_processo": r[8],
                    "indicios": _lista(r[9]) if r[9] is not None else None})
    return out


def consultar_teste(con: sqlite3.Connection, quem: str, motivo: str, nivel_min: int = config.NIVEL_RESUMO,
                    com_texto: bool = False) -> list[dict]:
    """Lê o conjunto de teste REGISTRANDO a consulta; recusa acima do teto do trimestre (holdout reutilizado demais
    deixa de medir — Dwork et al. 2015)."""
    desde = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 90 * 86400))
    n = con.execute("SELECT COUNT(*) FROM consulta_teste WHERE em>=?", (desde,)).fetchone()[0]
    teto = config.ORCAMENTO["max_consultas_teste_trimestre"]
    if n >= teto:
        raise PermissionError(f"conjunto de teste já consultado {n}× em 90 dias (teto {teto})")
    con.execute("INSERT INTO consulta_teste(em,quem,motivo) VALUES(?,?,?)", (_agora(), quem, motivo[:300]))
    con.commit()
    return _rotulos(con, ("teste",), nivel_min, com_texto)
