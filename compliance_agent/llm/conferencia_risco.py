# -*- coding: utf-8 -*-
"""conferencia_risco — ENTRADA POR RISCO na fila do Opus (plano mestre v2, E12/O6.5).

Por que existe (24/11/2026): a fila `data/conferencia_opus.db` recebia TUDO o que saía sem o Claude da assinatura —
~750 itens/dia entrando contra ~49/dia conferidos, 6.907 pendentes. A fila nunca esvaziaria. A regra do plano é:
o Opus só relê o que tem RISCO; o resto fica visível como "NÃO JULGADO — fila", nunca como limpo.

ENTRA (fica `pendente`) quem tem pelo menos um motivo, nesta ordem:
  divergencia     — dois motores deram NÍVEIS diferentes para a mesma tarefa × item (já está na própria fila);
  valor           — OB PAGA do processo (SIAFE, `ob_processo.obs_por_processo` → `cruzamentos_intel._ob_paga`, o
                    mesmo predicado de `dominio.pagamento.ob_paga_sql`) ≥ limiar (`JFN_CONFERENCIA_LIMIAR_VALOR`);
  grave           — o motor deu nível 2 (🔴);
  baixa_confianca — sem nível (indeterminado), veredito "indeterminado", metade ou mais dos eixos sem grau, ou a
                    confiança declarada pelo normalizador < 0,5;
  valor_indeterminavel — item de processo cuja OB não pôde ser consultada (INDISPONÍVEL ≠ 0: na dúvida, entra);
  amostra         — 1 a cada 8 do que SOBRAR, estratificada por tarefa × motor × nível (sorteio determinístico pelo
                    hash da chave; estrato sem sorteado leva o de menor hash). É o que mede o falso negativo.
O resto vira `nao_julgado`: `pendente()` continua True (o consumidor nunca dá VERIFICADO), o painel mostra a
contagem com o rótulo "NÃO JULGADO — fila" e uma nova produção da mesma entrada reavalia o item.

LIGAR (quando o dono religar a fila): `JFN_CONFERENCIA_RISCO=1` faz `conferencia_opus.enfileirar` aplicar a regra
na entrada. Sem a variável a entrada é a de sempre — a regra só roda em SOMBRA:

    python -m compliance_agent.llm.conferencia_risco ob --saida ob.json          # OB paga dos itens (rodar na VM-2)
    python -m compliance_agent.llm.conferencia_risco sombra --ob-json ob.json    # relatório + proposta (não altera)
    python -m compliance_agent.llm.conferencia_risco aplicar --proposta P.json   # aplica a proposta à fila real
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

NAO_JULGADO = "nao_julgado"
ROTULO_NAO_JULGADO = "NÃO JULGADO — fila"
AMOSTRA_A_CADA = 8
LIMIAR_VALOR_PADRAO = 1_000_000.00
MOTIVOS = ("divergencia", "valor", "grave", "baixa_confianca", "valor_indeterminavel", "amostra")
_REPO = Path(__file__).resolve().parents[2]


def ativo() -> bool:
    return os.environ.get("JFN_CONFERENCIA_RISCO", "").strip().lower() in ("1", "true", "on", "sim")


def limiar_valor() -> float:
    try:
        return float(os.environ.get("JFN_CONFERENCIA_LIMIAR_VALOR") or LIMIAR_VALOR_PADRAO)
    except ValueError:
        return LIMIAR_VALOR_PADRAO


def sorteado(chave: str) -> bool:
    return _hash(chave) % AMOSTRA_A_CADA == 0


def _hash(chave: str) -> int:
    return int(hashlib.sha1(str(chave).encode("utf-8", "replace")).hexdigest()[:12], 16)


def estrato(tarefa: str, motor: str, nivel) -> str:
    return f"{tarefa}|{(motor or '').split('#', 1)[0]}|{'?' if nivel is None else nivel}"


def baixa_confianca(tarefa: str, resposta: str | None, veredito: str | None, nivel) -> bool:
    if nivel is None or str(veredito or "").strip().lower().startswith(("indeterminado", "?")):
        return True
    v = str(veredito or "")
    if tarefa == "pericia_integral" and v:
        eixos = v.split()
        if eixos and sum(e.endswith("?") for e in eixos) * 2 >= len(eixos):
            return True
    from compliance_agent.llm.normalizadores import NORMALIZADORES
    fn = NORMALIZADORES.get(tarefa)
    if fn is None or not resposta:
        return False
    try:
        conf = fn(resposta)[2]
    except (ValueError, TypeError, KeyError, AttributeError):
        return False
    return conf is not None and conf < 0.5


def motivos_do_item(*, nivel, baixa: bool, valor: float | None, valor_aplica: bool, divergente: bool,
                    limiar: float) -> list[str]:
    """Motivos determinísticos (sem a amostra). `valor=None` com `valor_aplica` ⇒ OB não consultável ⇒ entra."""
    m = []
    if divergente:
        m.append("divergencia")
    if valor is not None and valor >= limiar:
        m.append("valor")
    if nivel == 2:
        m.append("grave")
    if baixa:
        m.append("baixa_confianca")
    if valor is None and valor_aplica:
        m.append("valor_indeterminavel")
    return m


def processo_do_item(item: str | None) -> str | None:
    return item[4:] if str(item or "").startswith("sei:") else None


def divergentes(linhas) -> set[tuple[str, str]]:
    """(tarefa, item) em que ≥ 2 motores distintos deram níveis distintos (linhas de qualquer status)."""
    por: dict[tuple, set] = defaultdict(set)
    for tarefa, item, motor, nivel in linhas:
        if item and nivel is not None:
            por[(tarefa, item)].add(((motor or "").split("#", 1)[0], nivel))
    return {k for k, pares in por.items() if len({m for m, _ in pares}) > 1 and len({n for _, n in pares}) > 1}


def classificar_lote(itens: list[dict], limiar: float | None = None) -> list[dict]:
    """`itens`: dicts com id, chave, tarefa, item, motor, nivel, baixa, valor, valor_aplica, divergente.
    Devolve os mesmos dicts com `motivos` e `decisao` ('fila' | NAO_JULGADO)."""
    limiar = limiar_valor() if limiar is None else limiar
    sobra: dict[str, list[dict]] = defaultdict(list)
    for it in itens:
        it["motivos"] = motivos_do_item(nivel=it.get("nivel"), baixa=bool(it.get("baixa")), valor=it.get("valor"),
                                        valor_aplica=bool(it.get("valor_aplica")),
                                        divergente=bool(it.get("divergente")), limiar=limiar)
        if not it["motivos"]:
            sobra[estrato(it["tarefa"], it.get("motor"), it.get("nivel"))].append(it)
    for grupo in sobra.values():
        sorteio = [it for it in grupo if sorteado(it["chave"])]
        if not sorteio:
            sorteio = [min(grupo, key=lambda x: _hash(x["chave"]))]
        for it in sorteio:
            it["motivos"] = ["amostra"]
    for it in itens:
        it["decisao"] = "fila" if it["motivos"] else NAO_JULGADO
    return itens


# ── leitura da fila e da OB ─────────────────────────────────────────────────────────────────────────
def ler_pendentes(con: sqlite3.Connection) -> list[dict]:
    """Pendentes SEM o blob da entrada (a regra não lê o processo)."""
    div = divergentes(con.execute("SELECT tarefa, item, motor, nivel FROM fila"))
    out = []
    for fid, chave, tarefa, item, motor, resposta, ver, niv in con.execute(
            "SELECT id, chave, tarefa, item, motor, resposta, veredito, nivel FROM fila WHERE status='pendente'"):
        out.append({"id": fid, "chave": chave, "tarefa": tarefa, "item": item, "motor": motor, "veredito": ver,
                    "nivel": niv, "baixa": baixa_confianca(tarefa, resposta, ver, niv),
                    "valor_aplica": processo_do_item(item) is not None, "divergente": (tarefa, item) in div})
    return out


def _grafias(chave: str) -> set[str]:
    """Grafias do nº do processo que o SIAFE grava (com/sem 'SEI-', nº com/sem zeros, ano com 4/2 dígitos)."""
    a, b, ano = chave.split("/")
    return {f"{pre}{a}/{nb}/{y}" for pre in ("SEI-", "", "SEI ") for nb in (f"{int(b):06d}", str(int(b)))
            for y in (ano, ano[2:])}


def ob_paga_por_processo(con: sqlite3.Connection, processos: list[str]) -> dict[str, float | None]:
    """{processo: total pago (OB paga do SIAFE, menos devolução) | 0.0 sem OB | None chave ilegível}.
    Até 50 processos: `ob_processo.obs_por_processo` (sem a camada dos autos). Acima: as mesmas camadas
    `processo_exato`/`processo_normalizado` pelo ÍNDICE de `processo` (as grafias de `_grafias`), com o mesmo
    predicado de OB paga e o mesmo desconto de devolução — a varredura de 1,3 mi de OB por lote não cabe na VM-1.
    As grafias irregulares de `ob_processo._chave_tolerante` ficam de fora no lote: o total é PISO."""
    from compliance_agent import ob_processo
    chaves = {p: ob_processo.chave_processo(p) for p in processos}
    validas = sorted({k for k in chaves.values() if k})
    if len(validas) <= ob_processo._PREFILTRO_MAX:
        obs = ob_processo.obs_por_processo(con, sorted(set(processos)), autos=False)
        return {p: None if k is None else float((obs.get(k) or {}).get("total") or 0.0) for p, k in chaves.items()}
    from compliance_agent.cruzamentos_intel import _ob_paga
    sel, paga = ob_processo._select(con), _ob_paga(con)
    grafias = sorted({g for k in validas for g in _grafias(k)})
    achadas: dict[str, dict] = {k: {} for k in validas}
    for i in range(0, len(grafias), 900):
        lote = grafias[i:i + 900]
        for j, r in enumerate(con.execute(f"SELECT {sel} FROM ob_orcamentaria_siafe WHERE {paga} AND processo IN "
                                          f"({','.join('?' * len(lote))})", lote)):
            o = ob_processo._linha(r)
            k = ob_processo.chave_processo(o["processo"])
            if k in achadas:
                achadas[k][(o["numero_ob"] or f"#{i}-{j}", o["ug_emitente"])] = {**o, "via": "processo_normalizado"}
    gds = ob_processo._gds(con)
    total = {k: ob_processo._consolidar(v, gds, {})["total"] for k, v in achadas.items()}
    return {p: None if k is None else float(total.get(k) or 0.0) for p, k in chaves.items()}


def com_valores(itens: list[dict], valores: dict[str, float | None] | None) -> list[dict]:
    """Preenche `valor`. `valores=None` (base de OB inteira indisponível) ⇒ todo item de processo fica None."""
    for it in itens:
        p = processo_do_item(it["item"])
        it["valor"] = None if (p is None or valores is None) else valores.get(p)
    return itens


# ── sombra e aplicação ──────────────────────────────────────────────────────────────────────────────
def resumo(itens: list[dict], limiar: float) -> dict:
    fica = [i for i in itens if i["decisao"] == "fila"]
    por_motivo = Counter(m for i in fica for m in i["motivos"])
    primeiro = Counter(i["motivos"][0] for i in fica)
    por_tarefa = defaultdict(lambda: {"fila": 0, NAO_JULGADO: 0})
    for i in itens:
        por_tarefa[i["tarefa"]][i["decisao"]] += 1
    return {"em": datetime.now().isoformat(timespec="seconds"), "limiar_valor": limiar, "pendentes": len(itens),
            "ficam_na_fila": len(fica), "viram_nao_julgado": len(itens) - len(fica),
            "por_motivo_qualquer": dict(por_motivo), "por_motivo_principal": dict(primeiro),
            "por_tarefa": dict(por_tarefa),
            "valor_indisponivel": sum(1 for i in itens if i.get("valor_aplica") and i.get("valor") is None)}


def sombra(con: sqlite3.Connection, valores: dict | None, limiar: float | None = None) -> tuple[dict, list[dict]]:
    limiar = limiar_valor() if limiar is None else limiar
    itens = classificar_lote(com_valores(ler_pendentes(con), valores), limiar)
    return resumo(itens, limiar), itens


def gravar_proposta(caminho: Path, rel: dict, itens: list[dict]) -> Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps({"resumo": rel, "itens": [
        {k: i.get(k) for k in ("id", "chave", "tarefa", "item", "motor", "nivel", "valor", "motivos", "decisao")}
        for i in itens]}, ensure_ascii=False), encoding="utf-8")
    os.chmod(caminho, 0o600)
    return caminho


def garantir_coluna(con: sqlite3.Connection) -> None:
    if "risco" not in {r[1] for r in con.execute("PRAGMA table_info(fila)")}:
        con.execute("ALTER TABLE fila ADD COLUMN risco TEXT")
        con.commit()


def aplicar(proposta: Path, con: sqlite3.Connection) -> dict:
    """Aplica a proposta: só mexe em linha AINDA pendente e com a MESMA chave (entrada não mudou desde a sombra)."""
    d = json.loads(Path(proposta).read_text(encoding="utf-8"))
    garantir_coluna(con)
    n = Counter()
    for it in d["itens"]:
        novo = NAO_JULGADO if it["decisao"] == NAO_JULGADO else "pendente"
        cur = con.execute("UPDATE fila SET status=?, risco=? WHERE id=? AND chave=? AND status='pendente'",
                          (novo, ",".join(it["motivos"]) or None, it["id"], it["chave"]))
        n[novo if cur.rowcount else "ignorado"] += 1
    con.commit()
    return dict(n)


def decidir_entrada(con: sqlite3.Connection, *, tarefa: str, item: str | None, chave: str, motor: str, nivel,
                    veredito, resposta: str, valor: float | None, valor_ob=None) -> tuple[str, list[str]]:
    """Regra na ENTRADA (com `JFN_CONFERENCIA_RISCO=1`): (status, motivos). Divergência com outro motor promove as
    linhas irmãs que estavam NÃO JULGADO de volta à fila."""
    div = False
    if item and nivel is not None:
        irmas = con.execute("SELECT id, motor, nivel, status FROM fila WHERE tarefa=? AND item=? AND chave<>?",
                            (tarefa, item, chave)).fetchall()
        base = (motor or "").split("#", 1)[0]
        div = any(n is not None and n != nivel and (m or "").split("#", 1)[0] != base for _, m, n, _ in irmas)
        if div:
            garantir_coluna(con)
            con.executemany("UPDATE fila SET status='pendente', risco='divergencia' WHERE id=? AND status=?",
                            [(i, NAO_JULGADO) for i, _, _, s in irmas if s == NAO_JULGADO])
    proc = processo_do_item(item)
    if valor is None and proc:
        try:
            valor = (valor_ob or _valor_ob_de)(proc)
        except (sqlite3.Error, OSError, ValueError) as e:
            logger.warning("conferência por risco: OB de %s ilegível (%s)", proc, type(e).__name__)
            valor = None
    m = motivos_do_item(nivel=nivel, baixa=baixa_confianca(tarefa, resposta, veredito, nivel), valor=valor,
                        valor_aplica=proc is not None, divergente=div, limiar=limiar_valor())
    if not m and sorteado(chave):
        m = ["amostra"]
    return ("pendente" if m else NAO_JULGADO), m


def _valor_ob_de(processo: str) -> float | None:
    con = sqlite3.connect(f"file:{_REPO / 'data' / 'compliance.db'}?mode=ro", uri=True, timeout=10)
    try:
        return ob_paga_por_processo(con, [processo]).get(processo)
    finally:
        con.close()


def _main(argv=None) -> int:
    from compliance_agent.llm import conferencia_opus
    ap = argparse.ArgumentParser(description="Entrada por risco na fila do Opus (sombra / aplicação)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("ob", help="OB paga dos processos pendentes (rodar onde está a cópia do compliance.db)")
    o.add_argument("--itens", help="JSON com a lista de processos (senão lê a fila)")
    o.add_argument("--compliance-db", default=str(_REPO / "data" / "compliance.db"))
    o.add_argument("--saida", required=True)
    s = sub.add_parser("sombra", help="relatório + proposta; NÃO altera a fila")
    s.add_argument("--ob-json", help="saída do subcomando `ob` (senão consulta o compliance.db local)")
    s.add_argument("--limiar", type=float)
    s.add_argument("--saida", default=str(_REPO / "data" / "conferencia_risco_proposta.json"))
    a_ = sub.add_parser("aplicar", help="aplica a proposta à fila real")
    a_.add_argument("--proposta", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "ob":
        if a.itens:
            procs = json.loads(Path(a.itens).read_text(encoding="utf-8"))
        else:
            con = sqlite3.connect(f"file:{conferencia_opus.caminho()}?mode=ro", uri=True, timeout=30)
            procs = [p for (i,) in con.execute("SELECT DISTINCT item FROM fila WHERE status='pendente'")
                     if (p := processo_do_item(i))]
            con.close()
        cc = sqlite3.connect(f"file:{a.compliance_db}?mode=ro", uri=True, timeout=30)
        try:
            vals = ob_paga_por_processo(cc, procs)
        finally:
            cc.close()
        Path(a.saida).write_text(json.dumps(vals, ensure_ascii=False), encoding="utf-8")
        print(f"{len(vals)} processo(s); {sum(1 for v in vals.values() if v)} com OB paga")
        return 0
    if a.cmd == "sombra":
        con = sqlite3.connect(f"file:{conferencia_opus.caminho()}?mode=ro", uri=True, timeout=30)
        try:
            if a.ob_json:
                valores = json.loads(Path(a.ob_json).read_text(encoding="utf-8"))
            else:
                procs = [p for (i,) in con.execute("SELECT DISTINCT item FROM fila WHERE status='pendente'")
                         if (p := processo_do_item(i))]
                cc = sqlite3.connect(f"file:{_REPO / 'data' / 'compliance.db'}?mode=ro", uri=True, timeout=30)
                try:
                    valores = ob_paga_por_processo(cc, procs)
                finally:
                    cc.close()
            rel, itens = sombra(con, valores, a.limiar)
        finally:
            con.close()
        destino = gravar_proposta(Path(a.saida), rel, itens)
        print(json.dumps(rel, ensure_ascii=False, indent=1))
        print(f"proposta: {destino}\naplicar: python -m compliance_agent.llm.conferencia_risco aplicar --proposta {destino}")
        return 0
    con = conferencia_opus.conectar()
    try:
        print(json.dumps(aplicar(Path(a.proposta), con), ensure_ascii=False))
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
