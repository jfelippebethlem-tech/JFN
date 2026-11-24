# -*- coding: utf-8 -*-
"""conferencia_opus — a fila ÚNICA do que foi produzido SEM o Claude da assinatura e espera o Opus conferir.

Pedido do dono (14/11/2026): "o que for feito por eles depois tem conferência sempre pelo claude opus".

ENTRA NA FILA (`data/conferencia_opus.db`, tabela `fila`): todo resultado que um consumidor entregou vindo da
cascata (Claude ausente: limite da conta, teto do motor, trava ocupada, erro) ou do Claude barato pela API
(`<modelo>@api`). Guarda a ENTRADA (comprimida — é o que o Opus vai reler), o `motor` REAL, o veredito
normalizado e o porquê de o Claude não estar. Item da fila nunca é VERIFICADO: `pendente(tarefa, item)` responde
aos consumidores, e o painel mostra a fila em Sistema.

SAI DA FILA (`conferir`): quando a assinatura volta, o Opus (`claude_motor.pensar(..., backend="cli")` — NUNCA a
API paga) relê a mesma entrada, por gravidade (🔴 → 🟡 → indeterminado → ⚪), valor e idade, dentro dos tetos.
  · o par Opus × modelo de contingência vai para o cruzamento (`cruzamento_motores.db`): concordância, exemplo
    de few-shot e, se for 🔴×⚪, revisão humana;
  · divergiu (ou a tarefa é prosa, sem régua) ⇒ o resultado do Opus PREVALECE: o aplicador da tarefa regrava o
    registro do consumidor (`APLICADORES`), e o co-motor passa a devolver a resposta do Opus para a mesma
    entrada (`resposta_conferida`) — produto regenerado sai com o Opus, sem nova chamada;
  · a divergência é registrada na propagação (fonte `conferencia_opus`) e no segundo cérebro.

ENTRADA POR RISCO (E12/O6.5, 24/11/2026): com `JFN_CONFERENCIA_RISCO=1` só fica `pendente` o que tem risco
(`llm/conferencia_risco`: divergência, valor, grave, baixa confiança, amostra 1/8); o resto entra como `nao_julgado`
— "NÃO JULGADO — fila", visível no painel e NUNCA limpo (`pendente()` continua True). Sem a variável, a de sempre.
DOIS EXECUTORES (O1.9): a rodada escolhe it-campo ou VM-2 (`llm/conferencia_executor`) com a mesma trava de ritmo.
PISO DE CONCORDÂNCIA: motor da cascata que concorda < 60% com o Opus numa tarefa de juízo (n ≥ 20) é rebaixado
naquela tarefa (`llm/cascata_ajuste`), ao fim de cada rodada.

A triagem de alertas tem fila própria e mais antiga (`alertas_triagem.opus_pendente`, consumida por
`triagem_alertas --opus`); `painel()` soma as duas para o dono ver uma fila só.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import logging
import os
import re
import sqlite3
import time
import zlib
from datetime import datetime
from pathlib import Path

from compliance_agent.llm import arquivo_estado as arq
from compliance_agent.llm import conferencia_risco as risco

logger = logging.getLogger(__name__)

_REPO = Path(__file__).resolve().parents[2]
TAREFA = "conferencia_opus"
MAX_TENTATIVAS = 3
# falha do ITEM, não falta de cota: recusa por conteúdo; prazo estourado (a mesma entrada estoura de novo — 21/11/2026)
_RE_RECUSA_ITEM = re.compile(r"safeguards flagged|passou do prazo", re.I)
# a trava do motor é uma só e a perícia integral a segura ~200 s por processo: com a espera padrão (90 s) a rodada
# desistia no 3º item (medido 21/11 20:30); o cron é horário com teto de 1.500 s, esperar a vez não custa cota
ESPERA_TRAVA_S = 420.0
TIMEOUT_S = 600.0       # a perícia integral (até 240 mil caracteres) leva 200–220 s no Opus e tem 600 s; aqui eram 300
# tarefa → "modulo:funcao(item, dados_opus, modelo_opus, concorda) -> bool" que regrava o registro do consumidor
APLICADORES = {"pericia_execucao": "tools.lex_execucao:aplicar_conferencia",
               "pericia_integral": "compliance_agent.pericia_integral:aplicar_conferencia",
               # número divergente do OCR por IA: só decisão com base objetiva no texto vira registro (23/11/2026)
               "ocr_ia_numero": "tools.sei_ocr_ia_conferir:aplicar_conferencia"}
# aplicador que bate em "database is locked" (compliance.db com outro escritor além do busy_timeout de 120 s —
# 22/11/2026 18:35, 2 vereditos do Opus da perícia integral perdidos) tenta de novo depois destas esperas
RETENTAR_S = (10.0, 30.0)
_RE_TRANSITORIO = re.compile(r"locked|busy", re.I)
# piso de concordância da cascata com o Opus (plano mestre v2, E12): abaixo dele, com amostra mínima, rebaixa
PISO_CONCORDANCIA = 0.60
PISO_AMOSTRA_MIN = 20
_STATUS_ABERTOS = ("pendente", "erro", risco.NAO_JULGADO)

_DDL = """
CREATE TABLE IF NOT EXISTS fila(
  id INTEGER PRIMARY KEY, chave TEXT NOT NULL UNIQUE, tarefa TEXT NOT NULL, item TEXT,
  entrada BLOB, sistema TEXT, motor TEXT NOT NULL, resposta TEXT, veredito TEXT, nivel INTEGER, valor REAL,
  motivo TEXT, status TEXT NOT NULL DEFAULT 'pendente', criado_em TEXT NOT NULL, tentativas INTEGER DEFAULT 0,
  conferido_em TEXT, modelo_opus TEXT, veredito_opus TEXT, nivel_opus INTEGER, resposta_opus TEXT,
  concorda INTEGER, aplicado INTEGER);
CREATE INDEX IF NOT EXISTS ix_fila_status ON fila(status, nivel, valor);
CREATE INDEX IF NOT EXISTS ix_fila_item ON fila(tarefa, item);
"""
# AMOSTRA DE CONTROLE (plano de reescrita, Fase 2 — 23/11/2026): o ⚪ (nível 0 ou sem nível) fica sempre no fim da
# `_ORDEM` e nunca era conferido — o falso negativo do motor barato nunca foi medido (e o Opus concordou só em 28%
# dos conferidos). 1 vaga a cada `AMOSTRA_A_CADA` do lote vai a um ⚪ SORTEADO; cada sorteio fica em
# `conferencia_opus_amostra.jsonl` para medir o recall ("quantos ⚪ o Opus pôs em 🟡/🔴").
AMOSTRA_A_CADA = 8


def AMOSTRA_ARQ() -> Path:
    return arq.dados() / "conferencia_opus_amostra.jsonl"


def _com_amostra(con: sqlite3.Connection, ids: list, n: int) -> list:
    k = n // AMOSTRA_A_CADA
    if k <= 0:
        return ids
    escolhidos = {fid for fid, _ in ids}
    limpos = [r for r in con.execute("SELECT id, item FROM fila WHERE status='pendente' AND COALESCE(nivel,0)=0 "
                                     "ORDER BY RANDOM() LIMIT ?", (k + len(ids),)) if r[0] not in escolhidos][:k]
    if not limpos:
        return ids
    base = [r for r in ids if r[0] not in {fid for fid, _ in limpos}][: max(0, n - len(limpos))]
    AMOSTRA_ARQ().parent.mkdir(parents=True, exist_ok=True)
    with AMOSTRA_ARQ().open("a", encoding="utf-8") as f:
        for fid, item in limpos:
            f.write(json.dumps({"id": fid, "item": item, "em": _agora()}, ensure_ascii=False) + "\n")
    return base + list(limpos)


_ORDEM = ("ORDER BY CASE WHEN nivel=2 THEN 0 WHEN nivel=1 THEN 1 WHEN nivel IS NULL THEN 2 ELSE 3 END, "
          "COALESCE(valor,0) DESC, id")


def _sem_banco() -> bool:
    """Sob pytest sem `JFN_CONFERENCIA_DB`: não toca o banco real (teste de outro módulo passando pelo co-motor)."""
    return arq.sob_pytest() and not os.environ.get("JFN_CONFERENCIA_DB")


def caminho() -> Path:
    return Path(os.environ.get("JFN_CONFERENCIA_DB") or (_REPO / "data" / "conferencia_opus.db"))


def conectar() -> sqlite3.Connection:
    p = caminho()
    novo = not p.exists()
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p, timeout=30)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(_DDL)
    if novo:
        os.chmod(p, 0o600)            # guarda entradas de perícia: só o dono do processo lê
    return con


def chave_de(tarefa: str, entrada: str, sistema: str = "") -> str:
    return hashlib.sha1(f"{tarefa}\x00{sistema}\x00{entrada}".encode("utf-8", "replace")).hexdigest()


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _normalizar(tarefa: str, texto: str):
    from compliance_agent.llm.normalizadores import NORMALIZADORES
    fn = NORMALIZADORES.get(tarefa)
    if fn is None:
        return None, None
    v, n, _ = fn(texto or "")
    return v, n


def enfileirar(tarefa: str, item: str | None, entrada: str, *, sistema: str = "", motor: str, resposta: str,
               motivo: str = "", valor: float | None = None, veredito: str | None = None, nivel: int | None = None,
               con: sqlite3.Connection | None = None) -> bool:
    """Marca o resultado como PENDENTE de conferência do Opus. Nunca levanta (a produção não para por causa da
    fila); devolve False se não gravou. Mesma entrada produzida de novo substitui a pendência anterior."""
    if _sem_banco() and con is None:
        return False
    try:
        if veredito is None and nivel is None:
            veredito, nivel = _normalizar(tarefa, resposta)
        proprio = con is None
        con = con or conectar()
        try:
            ch = chave_de(tarefa, entrada, sistema)
            status, motivos = "pendente", None
            if risco.ativo():                    # entrada por risco (E12): o sem-risco entra NÃO JULGADO, visível
                risco.garantir_coluna(con)
                status, ms = risco.decidir_entrada(con, tarefa=tarefa, item=item, chave=ch, motor=motor, nivel=nivel,
                                                   veredito=veredito, resposta=resposta or "", valor=valor)
                motivos = ",".join(ms) or None
            con.execute(
                "INSERT INTO fila(chave,tarefa,item,entrada,sistema,motor,resposta,veredito,nivel,valor,motivo,criado_em,"
                "status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(chave) DO UPDATE SET item=excluded.item, "
                "entrada=excluded.entrada, motor=excluded.motor, resposta=excluded.resposta, veredito=excluded.veredito, "
                "nivel=excluded.nivel, valor=excluded.valor, motivo=excluded.motivo, criado_em=excluded.criado_em, "
                "status=excluded.status, tentativas=0 WHERE fila.status IN ('pendente','erro','nao_julgado')",
                (ch, tarefa, item, zlib.compress(entrada.encode("utf-8", "replace")), sistema, motor or "desconhecido",
                 (resposta or "")[:60000], (veredito or None) and str(veredito)[:80], nivel, valor,
                 (motivo or "")[:200], _agora(), status))
            if motivos is not None or status != "pendente":
                con.execute("UPDATE fila SET risco=? WHERE chave=? AND status=?", (motivos, ch, status))
            con.commit()
            return True
        finally:
            if proprio:
                con.close()
    except (sqlite3.Error, OSError, ValueError, TypeError) as e:
        logger.warning("conferência Opus: item de %s não entrou na fila (%s)", tarefa, type(e).__name__)
        return False


def pendente(tarefa: str, item: str, con: sqlite3.Connection | None = None) -> bool:
    """O item tem resultado de contingência ainda não conferido? (True ⇒ o consumidor NÃO pode dar VERIFICADO.)
    NÃO JULGADO conta como pendente: fora da fila do Opus não é o mesmo que limpo."""
    if _sem_banco() and con is None:
        return False
    proprio = con is None
    con = con or conectar()
    try:
        return con.execute("SELECT 1 FROM fila WHERE tarefa=? AND item=? AND status IN (?,?,?) LIMIT 1",
                           (tarefa, item, *_STATUS_ABERTOS)).fetchone() is not None
    finally:
        if proprio:
            con.close()


def resposta_conferida(tarefa: str, entrada: str, sistema: str = "") -> tuple[str, str] | None:
    """(resposta do Opus, modelo) se ESTA MESMA entrada já foi conferida — o Opus prevalece em toda regeneração."""
    if _sem_banco() or not caminho().exists():
        return None
    try:
        con = sqlite3.connect(f"file:{caminho()}?mode=ro", uri=True, timeout=5)
        try:
            r = con.execute("SELECT resposta_opus, modelo_opus FROM fila WHERE chave=? AND status='conferido' "
                            "AND resposta_opus IS NOT NULL", (chave_de(tarefa, entrada, sistema),)).fetchone()
        finally:
            con.close()
        return (r[0], r[1]) if r else None
    except sqlite3.Error:
        return None


def _aplicar(tarefa: str, item: str | None, resposta: str, modelo: str, concorda) -> int | None:
    """1 aplicou · 0 o aplicador não achou/recusou · None a tarefa não tem registro próprio a regravar."""
    alvo = APLICADORES.get(tarefa)
    if not alvo or not item:
        return None
    for espera in (*RETENTAR_S, None):
        try:
            mod, fn = alvo.split(":")
            return int(bool(getattr(importlib.import_module(mod), fn)(item, resposta, modelo, concorda)))
        except sqlite3.OperationalError as e:
            if espera is None or not _RE_TRANSITORIO.search(str(e)):
                logger.warning("conferência Opus: aplicador de %s falhou (OperationalError: %s)", tarefa, str(e)[:160])
                return 0
            logger.info("conferência Opus: aplicador de %s esbarrou em %s — nova tentativa em %.0f s", tarefa,
                        str(e)[:80], espera)
            time.sleep(espera)
        except (ImportError, AttributeError, sqlite3.Error, OSError, ValueError, TypeError, KeyError) as e:
            logger.warning("conferência Opus: aplicador de %s falhou (%s: %s)", tarefa, type(e).__name__, str(e)[:160])
            return 0
    return 0


def _registrar_divergencia(tarefa: str, item: str | None, motor: str, antes, depois, modelo_opus: str) -> None:
    """Divergência vai à propagação (derivados que dependem do juízo recalculam) e ao segundo cérebro (correção)."""
    if arq.sob_pytest() and not os.environ.get("JFN_CONFERENCIA_PROPAGAR"):
        return
    det = (f"conferência Opus corrigiu {tarefa} {item or '(sem item)'}: {motor} disse {antes or 'indeterminado'}; "
           f"{modelo_opus} disse {depois or 'indeterminado'} — prevalece o Opus")
    try:
        from compliance_agent import propagacao
        pc = propagacao.conectar()
        try:
            propagacao.emitir(pc, propagacao.carregar(), "conferencia_opus", det)
        finally:
            pc.close()
    except (ImportError, sqlite3.Error, OSError, ValueError, KeyError) as e:
        logger.warning("conferência Opus: evento de propagação não emitido (%s)", type(e).__name__)
    try:
        from compliance_agent import cerebro_compartilhado
        cerebro_compartilhado.registrar(f"conferencia-opus:{tarefa}:{item}", "JFN — " + det + ". Indício interno; a "
                                        "confirmação é ato humano.", kind="experiencial",
                                        assunto=f"conferência Opus de {tarefa}")
    except (ImportError, sqlite3.Error, OSError, ValueError) as e:
        logger.warning("conferência Opus: correção não registrada no cérebro (%s)", type(e).__name__)


def _data_do_item(item: str | None) -> str | None:
    """Item `sei:<processo>` (perícia integral, perícia de execução) → data do período Couto; outro item → None."""
    from compliance_agent.foco import data_processo
    return data_processo(item[4:]) if (item or "").startswith("sei:") else None


def conferir(n: int = 8, *, pensar=None, con: sqlite3.Connection | None = None, escolher=None, ritmo=None,
             executar_em=None, piso: bool = True) -> list[dict]:
    """O Opus da assinatura confere até `n` itens da fila. Sem cota (ou assinatura ainda em contingência) para e
    retoma na próxima rodada — a fila não se perde e nada é promovido enquanto isso.
    Em produção (sem `pensar` injetado) a rodada passa pela trava de ritmo e escolhe o executor (it-campo | VM-2,
    `llm/conferencia_executor`); teste injeta `escolher`/`ritmo`/`executar_em`."""
    from compliance_agent.foco import intercalar
    from compliance_agent.llm import claude_motor, cruzamento
    from compliance_agent.llm import conferencia_executor as exe
    producao = pensar is None
    pensar = pensar or claude_motor.pensar
    executar, executor = None, None
    if producao or escolher is not None or ritmo is not None:
        barrado = (ritmo or exe.motivo_ritmo)(TAREFA)
        if barrado:
            logger.info("conferência Opus: rodada não confere — %s", barrado)
            return []
        executor, porque = (escolher or exe.escolher)()
        if executor is None:
            logger.warning("conferência Opus: nenhum executor da assinatura disponível — %s", porque)
            return []
        logger.info("conferência Opus: executor %s", porque)
        executar = (executar_em or exe.executar_em)(executor)
    extra = {"executar": executar} if executar is not None else {}
    proprio = con is None
    con = con or conectar()
    feitos: list[dict] = []
    try:
        # FOCO (22/11/2026): metade do lote do período Couto; dentro de cada metade, `_ORDEM` (compliance_agent/foco).
        # A entrada (blob) só é lida para os escolhidos.
        ids = intercalar(con.execute(f"SELECT id, item FROM fila WHERE status='pendente' {_ORDEM}"),
                         lambda r: _data_do_item(r[1]), limite=max(1, n))
        ids = _com_amostra(con, list(ids), max(1, n))
        rows = [con.execute("SELECT id,tarefa,item,entrada,sistema,motor,veredito,nivel FROM fila WHERE id=?",
                            (fid,)).fetchone() for fid, _ in ids]
        for fid, tarefa, item, blob, sistema, motor, ver, niv in rows:
            entrada = zlib.decompress(blob).decode("utf-8", "replace") if blob else ""
            p = pensar(TAREFA, entrada, modelo=claude_motor.MODELO_JUIZO, sistema=sistema or "", backend="cli",
                       timeout=TIMEOUT_S, espera=ESPERA_TRAVA_S, **extra)
            if p is None:
                if not _RE_RECUSA_ITEM.search(claude_motor.ultimo_motivo or ""):
                    break                              # sem assinatura agora: para sem gastar tentativa
                # falha DESTE item (21/11/2026: o topo travou a fila 2,5 dias) — gasta tentativa e segue
                con.execute("UPDATE fila SET tentativas=tentativas+1, status=CASE WHEN tentativas+1>=? THEN 'erro' "
                            "ELSE 'pendente' END WHERE id=?", (MAX_TENTATIVAS, fid))
                con.commit()
                feitos.append({"id": fid, "tarefa": tarefa, "item": item, "estado": "Opus recusou ou estourou o prazo"})
                continue
            v_op, n_op = _normalizar(tarefa, p.texto)
            tinha_regua = ver is not None or niv is not None
            if tinha_regua and v_op is None and n_op is None:        # Opus fora do formato: não vale como conferência
                con.execute("UPDATE fila SET tentativas=tentativas+1, status=CASE WHEN tentativas+1>=? THEN 'erro' "
                            "ELSE 'pendente' END WHERE id=?", (MAX_TENTATIVAS, fid))
                con.commit()
                feitos.append({"id": fid, "tarefa": tarefa, "item": item, "estado": "resposta do Opus fora do formato"})
                continue
            concorda = (int(n_op == niv) if (n_op is not None and niv is not None) else None) if tinha_regua else None
            try:
                cruzamento.cruzar(tarefa, item, cruzamento.Lado("claude", p.modelo, v_op, n_op),
                                  cruzamento.Lado("cascata", motor, ver, niv), entrada_resumo=entrada[:600])
            except (sqlite3.Error, OSError, ValueError) as e:
                logger.warning("conferência Opus: cruzamento não gravado (%s)", type(e).__name__)
            aplicado = _aplicar(tarefa, item, p.texto, p.modelo, concorda)
            # aplicador que falhou: a ENTRADA fica (o aplicador da perícia integral relê dela) para `reaplicar`;
            # antes ela era apagada e o veredito do Opus nunca chegava ao registro (22/11/2026)
            con.execute("UPDATE fila SET status='conferido', conferido_em=?, modelo_opus=?, veredito_opus=?, "
                        "nivel_opus=?, resposta_opus=?, concorda=?, aplicado=?, "
                        "entrada=CASE WHEN ? THEN entrada ELSE NULL END WHERE id=?",
                        (_agora(), p.modelo, (v_op or None) and str(v_op)[:80], n_op, p.texto[:60000], concorda,
                         aplicado, int(aplicado == 0), fid))
            con.commit()
            if concorda == 0:                          # prosa sem régua (None) não tem o que comparar
                _registrar_divergencia(tarefa, item, motor, ver, v_op, p.modelo)
            feitos.append({"id": fid, "tarefa": tarefa, "item": item, "motor": motor, "antes": ver, "opus": v_op,
                           "concorda": concorda, "aplicado": aplicado, "executor": executor})
        if piso and feitos:
            aplicar_piso(con)
        return feitos
    finally:
        if proprio:
            con.close()


def reaplicar(n: int = 50, con: sqlite3.Connection | None = None) -> list[dict]:
    """Conferido cujo aplicador falhou (aplicado=0), com aplicador e com a ENTRADA guardada: roda o aplicador de novo
    com a resposta do Opus já gravada — sem nova chamada. Aplicou ⇒ aplicado=1 e a entrada é apagada. Sem a entrada
    (os 4 de antes de 24/11) não reaplica: o aplicador da perícia integral leria a entrada de OUTRA linha do item."""
    proprio = con is None
    con = con or conectar()
    out = []
    try:
        marcas = ",".join("?" * len(APLICADORES))
        rows = con.execute(f"SELECT id, tarefa, item, resposta_opus, modelo_opus, concorda, entrada IS NOT NULL FROM fila "
                           f"WHERE status='conferido' AND aplicado=0 AND resposta_opus IS NOT NULL AND entrada IS NOT NULL "
                           f"AND tarefa IN ({marcas}) ORDER BY id LIMIT ?", (*APLICADORES, n)).fetchall()
        for fid, tarefa, item, resp, modelo, concorda, tem_entrada in rows:
            ap = _aplicar(tarefa, item, resp, modelo or "", concorda)
            if ap == 1:
                con.execute("UPDATE fila SET aplicado=1, entrada=NULL WHERE id=?", (fid,))
                con.commit()
            out.append({"id": fid, "tarefa": tarefa, "item": item, "aplicado": ap, "tinha_entrada": bool(tem_entrada)})
        return out
    finally:
        if proprio:
            con.close()


def _motor_da_cascata(motor: str | None) -> str | None:
    """Rótulo do `cascata_ajuste` para o motor gravado na fila; None = não é um modelo da cascata (Claude pela API,
    'cascata' agregada, desconhecido) — não há o que rebaixar."""
    m = (motor or "").split("#", 1)[0].strip()
    if not m or m in ("cascata", "desconhecido") or m.startswith("claude"):
        return None
    return m


def concordancia_por_motor(con: sqlite3.Connection) -> list[dict]:
    """Concordância Opus × motor por tarefa de JUÍZO (as que têm normalizador), só conferidos com régua."""
    from compliance_agent.llm.normalizadores import NORMALIZADORES
    out = []
    for tarefa, motor, n, a in con.execute("SELECT tarefa, motor, COUNT(*), SUM(concorda=1) FROM fila WHERE "
                                           "status='conferido' AND concorda IS NOT NULL GROUP BY 1, 2"):
        if tarefa in NORMALIZADORES:
            out.append({"tarefa": tarefa, "motor": motor, "n": n, "concordou": a or 0,
                        "taxa": round((a or 0) / n, 3) if n else None, "modelo": _motor_da_cascata(motor)})
    return out


def aplicar_piso(con: sqlite3.Connection, *, rebaixar=None, aplicar: bool = True) -> list[dict]:
    """Rebaixa (por tarefa) o motor da cascata que concorda < `PISO_CONCORDANCIA` com o Opus em n ≥
    `PISO_AMOSTRA_MIN`. `aplicar=False` só lista (sombra). Idempotente (o `cascata_ajuste` ignora o repetido)."""
    from compliance_agent.llm import cascata_ajuste
    rebaixar = rebaixar or cascata_ajuste.rebaixar
    abaixo = []
    for c in concordancia_por_motor(con):
        if c["modelo"] is None or c["n"] < PISO_AMOSTRA_MIN or c["taxa"] >= PISO_CONCORDANCIA:
            continue
        c["novo"] = bool(rebaixar(c["tarefa"], c["modelo"], f"concordância com o Opus {c['taxa']:.0%} < piso "
                                  f"{PISO_CONCORDANCIA:.0%} (conferência Opus)",
                                  {"n": c["n"], "concordou": c["concordou"], "taxa": c["taxa"]})) if aplicar else None
        abaixo.append(c)
    return abaixo


def _triagem_pendente() -> int | None:
    """Fila irmã: alertas da triagem aguardando o Opus (`alertas_triagem.opus_pendente`). None = INDISPONÍVEL."""
    try:
        con = sqlite3.connect(f"file:{_REPO / 'data' / 'compliance.db'}?mode=ro", uri=True, timeout=5)
        try:
            from compliance_agent.triagem_alertas import fora_dos_suspensos
            fora, params = fora_dos_suspensos(con)   # detector suspenso da triagem não está na fila do Opus
            return con.execute("SELECT COUNT(*) FROM alertas_triagem t LEFT JOIN alertas a ON a.id=t.alerta_id "
                               "WHERE t.opus_pendente=1" + fora, params).fetchone()[0]
        finally:
            con.close()
    except sqlite3.Error:
        return None


def painel() -> dict:
    """Bloco "Conferência Opus" da esfera Sistema: estado da contingência + fila. Sem custo, sem conteúdo."""
    from compliance_agent.llm import contingencia
    e = contingencia.estado()
    out = {"contingencia": {k: e.get(k) for k in ("ativa", "origem", "ate_iso", "motivo", "tarefas_perto_do_teto")},
           "ultima_contingencia": e.get("ultima"), "triagem_pendente": _triagem_pendente(),
           "disponivel": False, "pendentes": None, "por_tarefa": [], "conferidos": None, "divergencias": None,
           "itens": [], "legenda": "Resultado produzido por outro modelo enquanto o Claude da assinatura não podia "
                                   "responder. Fica PENDENTE até o Opus reler a mesma entrada; se divergir, vale o Opus."}
    if not caminho().exists():
        return dict(out, disponivel=True, pendentes=0, conferidos=0, divergencias=0)   # fila ainda não criada = vazia
    try:
        con = sqlite3.connect(f"file:{caminho()}?mode=ro", uri=True, timeout=5)
        try:
            out["por_tarefa"] = [
                {"tarefa": t, "motor": m, "pendentes": p, "graves": g, "conferidos": c, "concordou": a, "divergiu": d,
                 "erro": er, "nao_julgados": nj}
                for t, m, p, g, c, a, d, er, nj in con.execute(
                    "SELECT tarefa, motor, SUM(status='pendente'), SUM(status='pendente' AND nivel=2), "
                    "SUM(status='conferido'), SUM(status='conferido' AND concorda=1), "
                    "SUM(status='conferido' AND COALESCE(concorda,0)=0), SUM(status='erro'), "
                    "SUM(status='nao_julgado') FROM fila GROUP BY tarefa, motor ORDER BY 3 DESC, 1")]
            out["itens"] = [
                {"tarefa": t, "item": i, "motor": m, "veredito": v, "nivel": n, "desde": em, "motivo": mo}
                for t, i, m, v, n, em, mo in con.execute(
                    f"SELECT tarefa,item,motor,veredito,nivel,criado_em,motivo FROM fila WHERE status='pendente' {_ORDEM} LIMIT 15")]
        finally:
            con.close()
    except sqlite3.Error as e:
        logger.debug("conferência Opus: fila ilegível (%s)", e)
        return out
    pt = out["por_tarefa"]
    return dict(out, disponivel=True, pendentes=sum(x["pendentes"] or 0 for x in pt),
                conferidos=sum(x["conferidos"] or 0 for x in pt), divergencias=sum(x["divergiu"] or 0 for x in pt),
                erros=sum(x["erro"] or 0 for x in pt), nao_julgados=sum(x["nao_julgados"] or 0 for x in pt),
                rotulo_nao_julgado=risco.ROTULO_NAO_JULGADO)


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Fila de conferência do Opus (resultados produzidos em contingência)")
    ap.add_argument("--conferir", type=int, metavar="N", help="o Opus da assinatura confere até N itens")
    ap.add_argument("--reaplicar", type=int, metavar="N", help="reaplica até N conferidos cujo aplicador falhou")
    ap.add_argument("--piso", action="store_true", help="concordância por motor × tarefa e quem cairia no piso")
    ap.add_argument("--aplicar-piso", action="store_true", help="com --piso: grava o rebaixamento (cascata_ajuste)")
    a = ap.parse_args(argv)
    if a.reaplicar:
        print(json.dumps(reaplicar(a.reaplicar), ensure_ascii=False))
        return 0
    if a.piso:
        con = conectar()
        try:
            print(json.dumps({"todos": concordancia_por_motor(con),
                              "abaixo_do_piso": aplicar_piso(con, aplicar=a.aplicar_piso)}, ensure_ascii=False, indent=1))
        finally:
            con.close()
        return 0
    if a.conferir:
        r = conferir(a.conferir)
        print(f"[{_agora()}] conferência Opus: {len(r)} item(ns) — "
              + json.dumps([{k: x.get(k) for k in ('tarefa', 'item', 'antes', 'opus', 'concorda', 'aplicado', 'estado', 'executor')
                             if x.get(k) is not None} for x in r], ensure_ascii=False))
        return 0
    print(json.dumps(painel(), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
