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
import sqlite3
import zlib
from datetime import datetime
from pathlib import Path

from compliance_agent.llm import arquivo_estado as arq

logger = logging.getLogger(__name__)

_REPO = Path(__file__).resolve().parents[2]
TAREFA = "conferencia_opus"
MAX_TENTATIVAS = 3
# tarefa → "modulo:funcao(item, dados_opus, modelo_opus, concorda) -> bool" que regrava o registro do consumidor
APLICADORES = {"pericia_execucao": "tools.lex_execucao:aplicar_conferencia",
               "pericia_integral": "compliance_agent.pericia_integral:aplicar_conferencia"}

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
            con.execute(
                "INSERT INTO fila(chave,tarefa,item,entrada,sistema,motor,resposta,veredito,nivel,valor,motivo,criado_em) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(chave) DO UPDATE SET item=excluded.item, "
                "entrada=excluded.entrada, motor=excluded.motor, resposta=excluded.resposta, veredito=excluded.veredito, "
                "nivel=excluded.nivel, valor=excluded.valor, motivo=excluded.motivo, criado_em=excluded.criado_em, "
                "status='pendente', tentativas=0 WHERE fila.status IN ('pendente','erro')",
                (ch, tarefa, item, zlib.compress(entrada.encode("utf-8", "replace")), sistema, motor or "desconhecido",
                 (resposta or "")[:60000], (veredito or None) and str(veredito)[:80], nivel, valor,
                 (motivo or "")[:200], _agora()))
            con.commit()
            return True
        finally:
            if proprio:
                con.close()
    except (sqlite3.Error, OSError, ValueError, TypeError) as e:
        logger.warning("conferência Opus: item de %s não entrou na fila (%s)", tarefa, type(e).__name__)
        return False


def pendente(tarefa: str, item: str, con: sqlite3.Connection | None = None) -> bool:
    """O item tem resultado de contingência ainda não conferido? (True ⇒ o consumidor NÃO pode dar VERIFICADO.)"""
    if _sem_banco() and con is None:
        return False
    proprio = con is None
    con = con or conectar()
    try:
        return con.execute("SELECT 1 FROM fila WHERE tarefa=? AND item=? AND status IN ('pendente','erro') LIMIT 1",
                           (tarefa, item)).fetchone() is not None
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
    try:
        mod, fn = alvo.split(":")
        return int(bool(getattr(importlib.import_module(mod), fn)(item, resposta, modelo, concorda)))
    except (ImportError, AttributeError, sqlite3.Error, OSError, ValueError, TypeError, KeyError) as e:
        logger.warning("conferência Opus: aplicador de %s falhou (%s)", tarefa, type(e).__name__)
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


def conferir(n: int = 8, *, pensar=None, con: sqlite3.Connection | None = None) -> list[dict]:
    """O Opus da assinatura confere até `n` itens da fila. Sem cota (ou assinatura ainda em contingência) para e
    retoma na próxima rodada — a fila não se perde e nada é promovido enquanto isso."""
    from compliance_agent.llm import claude_motor, cruzamento
    pensar = pensar or claude_motor.pensar
    proprio = con is None
    con = con or conectar()
    feitos: list[dict] = []
    try:
        rows = con.execute("SELECT id,tarefa,item,entrada,sistema,motor,veredito,nivel FROM fila "
                           f"WHERE status='pendente' {_ORDEM} LIMIT ?", (max(1, n),)).fetchall()
        for fid, tarefa, item, blob, sistema, motor, ver, niv in rows:
            entrada = zlib.decompress(blob).decode("utf-8", "replace") if blob else ""
            p = pensar(TAREFA, entrada, modelo=claude_motor.MODELO_JUIZO, sistema=sistema or "", backend="cli",
                       timeout=300.0)
            if p is None:
                break                                  # sem assinatura agora: para sem gastar tentativa
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
            con.execute("UPDATE fila SET status='conferido', conferido_em=?, modelo_opus=?, veredito_opus=?, "
                        "nivel_opus=?, resposta_opus=?, concorda=?, aplicado=?, entrada=NULL WHERE id=?",
                        (_agora(), p.modelo, (v_op or None) and str(v_op)[:80], n_op, p.texto[:60000], concorda,
                         aplicado, fid))
            con.commit()
            if concorda == 0:                          # prosa sem régua (None) não tem o que comparar
                _registrar_divergencia(tarefa, item, motor, ver, v_op, p.modelo)
            feitos.append({"id": fid, "tarefa": tarefa, "item": item, "motor": motor, "antes": ver, "opus": v_op,
                           "concorda": concorda, "aplicado": aplicado})
        return feitos
    finally:
        if proprio:
            con.close()


def _triagem_pendente() -> int | None:
    """Fila irmã: alertas da triagem aguardando o Opus (`alertas_triagem.opus_pendente`). None = INDISPONÍVEL."""
    try:
        con = sqlite3.connect(f"file:{_REPO / 'data' / 'compliance.db'}?mode=ro", uri=True, timeout=5)
        try:
            return con.execute("SELECT COUNT(*) FROM alertas_triagem WHERE opus_pendente=1").fetchone()[0]
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
                 "erro": er}
                for t, m, p, g, c, a, d, er in con.execute(
                    "SELECT tarefa, motor, SUM(status='pendente'), SUM(status='pendente' AND nivel=2), "
                    "SUM(status='conferido'), SUM(status='conferido' AND concorda=1), "
                    "SUM(status='conferido' AND COALESCE(concorda,0)=0), SUM(status='erro') "
                    "FROM fila GROUP BY tarefa, motor ORDER BY 3 DESC, 1")]
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
                erros=sum(x["erro"] or 0 for x in pt))


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Fila de conferência do Opus (resultados produzidos em contingência)")
    ap.add_argument("--conferir", type=int, metavar="N", help="o Opus da assinatura confere até N itens")
    a = ap.parse_args(argv)
    if a.conferir:
        r = conferir(a.conferir)
        print(f"[{_agora()}] conferência Opus: {len(r)} item(ns) — "
              + json.dumps([{k: x.get(k) for k in ('tarefa', 'item', 'antes', 'opus', 'concorda', 'aplicado', 'estado')
                             if x.get(k) is not None} for x in r], ensure_ascii=False))
        return 0
    print(json.dumps(painel(), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
