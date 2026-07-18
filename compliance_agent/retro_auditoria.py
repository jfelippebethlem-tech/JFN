# -*- coding: utf-8 -*-
"""retro_auditoria — "hindsight grading" dos detectores (padrão karpathy/hn-time-capsule).

Pergunta que responde: **o que aconteceu DEPOIS que o sistema apontou?** Dois produtos:

  1. CORROBORAÇÃO — empresa sinalizada (fantasma/radar/perdedora/conluio) que DEPOIS entrou em
     sanção federal (CEIS/CNEP, data_inicio > primeira_vez do sinal). O desfecho independente
     corrobora o detector; a taxa por detector calibra em quem confiar (metacognição com dado).
  2. CUSTO DA INAÇÃO — R$ que o Estado CONTINUOU pagando (OB SIAFE) e vitórias PNCP que a
     empresa continuou levando APÓS o primeiro alerta. É o argumento executivo do relatório:
     "depois que o sistema apontou, ainda saíram R$ X".

Peça central: `sinal_ledger` (append-first). Os caches/tabelas de detector são REGRAVADOS a cada
sweep (fantasma_score.avaliado_em é clobrado — todos ficam com a data de hoje), então sem um
ledger a "primeira vez do sinal" não existe. Aqui: INSERT se (cnpj,sinal) inédito — `primeira_vez`
NUNCA muda depois; `ultima_vez`/detalhe atualizam. `registrar_sinais()` roda no timer diário do
intel; a janela retro cresce organicamente (mesmo desenho compostável da coleta de atas).

Determinístico, sem IA. Janela curta nos primeiros dias → o output declara a idade mediana dos
sinais (honestidade: corroboração 0 com ledger de 2 dias não é "detector ruim")."""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_DB = str(_REPO / "data" / "compliance.db")

logger = logging.getLogger(__name__)

_OB_ISO = "substr(data_emissao,7,4)||'-'||substr(data_emissao,4,2)||'-'||substr(data_emissao,1,2)"

_DDL = """
CREATE TABLE IF NOT EXISTS sinal_ledger (
    cnpj         TEXT NOT NULL,
    sinal        TEXT NOT NULL,             -- fantasma_alto | fantasma_medio | radar_50 | ...
    primeira_vez TEXT NOT NULL,             -- data do 1º registro — NUNCA regravada
    ultima_vez   TEXT NOT NULL,
    detalhe      TEXT,
    PRIMARY KEY (cnpj, sinal)
)"""

RESSALVA = ("Corroboração ≠ prova (a sanção posterior pode ter causa alheia ao sinal); ausência de "
            "corroboração ≠ detector errado (janela curta / sanção demora anos). Indício ≠ acusação.")


def _rw(db_path: str | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(db_path or _DB, timeout=60)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=60000")
    return con


def _ro(db_path: str | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{db_path or _DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=30000")
    return con


def _sinais_atuais(con) -> list[tuple[str, str, str]]:
    """(cnpj, sinal, detalhe) de todas as fontes persistidas/cacheadas de HOJE."""
    out: list[tuple[str, str, str]] = []
    try:
        for r in con.execute("SELECT cnpj, classificacao, razao_social FROM fantasma_score "
                             "WHERE classificacao IN ('alto','medio')"):
            out.append((r["cnpj"], f"fantasma_{r['classificacao']}", (r["razao_social"] or "")[:60]))
    except sqlite3.OperationalError as exc:
        logger.debug("ledger sem fantasma_score: %s", exc)
    from compliance_agent.cruzamentos_intel import ler_cache_intel
    radar = (ler_cache_intel("radar_risco") or {}).get("achados") or []
    for a in radar:
        if a.get("score", 0) >= 50:
            out.append((a["cnpj"], "radar_50", f"score {a['score']}"))
        elif a.get("n_sinais", 0) >= 2:
            out.append((a["cnpj"], "radar_multi", f"{a['n_sinais']} sinais"))
    for p in (ler_cache_intel("perdedoras_contumazes") or {}).get("perdedoras") or []:
        out.append((p["cnpj"], "perdedora_contumaz", f"participou {p.get('participou')}x"))
    for par in (ler_cache_intel("conluio_qsa") or {}).get("pares") or []:
        for lado in ("vencedor", "perdedora"):
            out.append((par[lado]["cnpj"], "conluio_par", par["tier"]))
    return [(c, s, d) for c, s, d in out if c and len(c) == 14]


def registrar_sinais(db_path: str | None = None) -> dict:
    """Snapshot diário → ledger. primeira_vez preservada; ultima_vez/detalhe atualizam."""
    con = _rw(db_path)
    try:
        con.execute(_DDL)
        antes = {(r[0], r[1]) for r in con.execute("SELECT cnpj, sinal FROM sinal_ledger")}
        novos = vistos = 0
        for cnpj, sinal, detalhe in _sinais_atuais(con):
            con.execute(
                "INSERT INTO sinal_ledger (cnpj, sinal, primeira_vez, ultima_vez, detalhe) "
                "VALUES (?,?,date('now'),date('now'),?) "
                "ON CONFLICT(cnpj,sinal) DO UPDATE SET ultima_vez=date('now'), "
                "detalhe=excluded.detalhe",
                (cnpj, sinal, detalhe))
            vistos += 1
            if (cnpj, sinal) not in antes:
                novos += 1
        con.commit()
        total = con.execute("SELECT COUNT(*) FROM sinal_ledger").fetchone()[0]
        return {"ok": True, "vistos_hoje": vistos, "novos": novos, "no_ledger": total}
    finally:
        con.close()


def medir(db_path: str | None = None, limite_exemplos: int = 30) -> dict:
    """Hindsight por detector: sanção posterior (corrobora) + R$ pago e vitórias APÓS o 1º sinal."""
    con = _rw(db_path)
    try:
        try:
            ledger = con.execute("SELECT cnpj, sinal, primeira_vez, detalhe "
                                 "FROM sinal_ledger").fetchall()
        except sqlite3.OperationalError:
            return {"ok": False, "erro": "sinal_ledger vazio — rodar registrar_sinais (timer intel)"}
        if not ledger:
            return {"ok": False, "erro": "sinal_ledger vazio — rodar registrar_sinais (timer intel)"}

        idade = con.execute("SELECT CAST(julianday('now')-julianday(MIN(primeira_vez)) AS INT), "
                            "CAST(julianday('now')-julianday(MAX(primeira_vez)) AS INT) "
                            "FROM sinal_ledger").fetchone()
        por_sinal: dict[str, dict] = {}
        exemplos: list[dict] = []
        for r in ledger:
            s = por_sinal.setdefault(r["sinal"], {
                "n_sinais": 0, "n_sancao_depois": 0, "pago_depois": 0.0,
                "n_obs_depois": 0, "vitorias_depois": 0})
            s["n_sinais"] += 1
            sanc = con.execute(
                "SELECT cadastro, categoria, data_inicio FROM sancoes_federais "
                "WHERE cpf_cnpj=? AND data_inicio > ? ORDER BY data_inicio LIMIT 1",
                (r["cnpj"], r["primeira_vez"])).fetchone()
            pago = con.execute(
                f"SELECT COALESCE(SUM(valor),0), COUNT(*) FROM ob_orcamentaria_siafe "
                f"WHERE credor=? AND {_OB_ISO} > ?", (r["cnpj"], r["primeira_vez"])).fetchone()
            vit = con.execute(
                "SELECT COUNT(DISTINCT certame) FROM pncp_resultado WHERE fornecedor_cnpj=? "
                "AND (ordem_classificacao=1 OR (ordem_classificacao IS NULL AND "
                "valor_homologado>0)) AND substr(data_pub,1,10) > ?",
                (r["cnpj"], r["primeira_vez"])).fetchone()[0]
            if sanc:
                s["n_sancao_depois"] += 1
            s["pago_depois"] += pago[0]
            s["n_obs_depois"] += pago[1]
            s["vitorias_depois"] += vit
            if (sanc or pago[0] > 0) and len(exemplos) < limite_exemplos:
                exemplos.append({
                    "cnpj": r["cnpj"], "sinal": r["sinal"], "desde": r["primeira_vez"],
                    "detalhe": r["detalhe"],
                    "sancao_depois": dict(sanc) if sanc else None,
                    "pago_depois": pago[0], "vitorias_depois": vit})
        exemplos.sort(key=lambda e: (-bool(e["sancao_depois"]), -e["pago_depois"]))
        return {"ok": True, "por_sinal": por_sinal, "exemplos": exemplos,
                "janela": {"sinal_mais_antigo_dias": idade[0], "mais_novo_dias": idade[1]},
                "explicacao": ("Hindsight por detector: quantas empresas sinalizadas entraram em "
                               "sanção DEPOIS do 1º alerta (corroboração independente) e quanto o "
                               "Estado ainda pagou/adjudicou após o alerta (custo da inação)."),
                "ressalva": RESSALVA}
    finally:
        con.close()


# ── LIFT DE CORROBORAÇÃO: gabarito OBJETIVO (sanções) valida cada detector ────

# detector → (fonte de CNPJs, usa_sancao_como_input). usa_sancao=True → o lift é CIRCULAR (o
# detector marca em parte PORQUE a empresa é sancionada) e não mede corroboração independente.
def _cnpjs_detector(con, nome: str, db_path: str | None = None) -> set[str]:
    """CNPJs marcados por um detector, das fontes rápidas (cache/tabela/função barata). db_path é
    passado aos detectores para consistência e isolamento de teste (senão rodariam no DB default)."""
    from compliance_agent.cruzamentos_intel import (
        corrida_dezembro, escalada_preco, fornecedor_dependente, ler_cache_intel,
        sobrepreco)
    out: set[str] = set()

    def _add(x):
        if x and len(x) == 14:
            out.add(x)

    if nome == "fantasma_alto":
        for r in con.execute("SELECT cnpj FROM fantasma_score WHERE classificacao='alto'"):
            _add(r["cnpj"])
    elif nome == "fantasma_medio":
        for r in con.execute("SELECT cnpj FROM fantasma_score WHERE classificacao='medio'"):
            _add(r["cnpj"])
    elif nome == "radar_risco":
        for a in (ler_cache_intel("radar_risco") or {}).get("achados") or []:
            _add(a.get("cnpj"))
    elif nome == "escalada_preco":
        for a in escalada_preco(db_path).get("achados", []):
            _add(a.get("fornecedor_cnpj"))
    elif nome == "sobrepreco":
        for a in sobrepreco(db_path).get("achados", []):
            _add(a.get("fornecedor_cnpj"))
    elif nome == "corrida_dezembro":
        for a in corrida_dezembro(db_path).get("achados", []):
            _add(a.get("cnpj"))
    elif nome == "fornecedor_dependente":
        for a in fornecedor_dependente(db_path).get("achados", []):
            _add(a.get("cnpj"))
    elif nome == "conluio_qsa":
        for p in (ler_cache_intel("conluio_qsa") or {}).get("pares") or []:
            _add(p.get("vencedor", {}).get("cnpj"))
            _add(p.get("perdedora", {}).get("cnpj"))
    return out


_LIFT_DETECTORES = [
    ("escalada_preco", False), ("sobrepreco", False), ("corrida_dezembro", False),
    ("fornecedor_dependente", False), ("conluio_qsa", False),
    ("fantasma_medio", True), ("fantasma_alto", True), ("radar_risco", True),
]


def avaliar_lift(db_path: str | None = None) -> dict:
    """Valida cada detector contra o GABARITO OBJETIVO (sanções impeditivas): dos CNPJs que o
    detector marca, que fração está sancionada, e o LIFT vs a taxa-base do universo de fornecedores.
    lift>1 = o detector concentra empresas com problema independente; ~1 = ruído; <1 = anti-sinal.
    Detectores que USAM sanção como input são marcados 'circular' (lift não é independente)."""
    con = _ro(db_path)
    try:
        sanc = {r[0] for r in con.execute(
            "SELECT DISTINCT cpf_cnpj FROM sancoes_federais WHERE length(cpf_cnpj)=14 AND "
            "(lower(categoria) LIKE '%imped%' OR lower(categoria) LIKE '%inid%' OR "
            "lower(categoria) LIKE '%suspens%' OR lower(categoria) LIKE '%declar%')")}
        univ = {r[0] for r in con.execute(
            "SELECT DISTINCT fornecedor_cnpj FROM pncp_resultado WHERE length(fornecedor_cnpj)=14")}
        if not univ:
            return {"ok": False, "erro": "universo de fornecedores vazio (PNCP não coletado)"}
        base = len(univ & sanc) / len(univ)
        linhas = []
        for nome, circular in _LIFT_DETECTORES:
            try:
                cnpjs = _cnpjs_detector(con, nome, db_path)
            except Exception as exc:  # noqa: BLE001
                logger.debug("lift %s: %s", nome, exc)
                continue
            if not cnpjs:
                continue
            marc = len(cnpjs & sanc)
            taxa = marc / len(cnpjs)
            linhas.append({
                "detector": nome, "n": len(cnpjs), "sancionados": marc,
                "taxa": round(taxa, 4), "lift": round(taxa / base, 2) if base else None,
                "circular": circular,
                "n_pequeno": len(cnpjs) < 10})
        # ranking: independentes (não-circular) por lift; circulares ao fim (só sanidade)
        linhas.sort(key=lambda x: (x["circular"], -(x["lift"] or 0)))
        return {"ok": True, "taxa_base": round(base, 4), "universo": len(univ),
                "sancionados_universo": len(univ & sanc), "detectores": linhas,
                "explicacao": ("Gabarito OBJETIVO = sanções impeditivas (CEIS/CNEP). Para cada "
                               "detector, o LIFT é a razão entre a taxa de sancionados no que ele "
                               "marca e a taxa-base do universo. lift>1 = concentra risco real; "
                               "~1 = ruído; <1 = anti-sinal. 'circular' = o detector usa sanção "
                               "como input (lift não é corroboração independente)."),
                "ressalva": ("Sanção é uma prova PARCIAL (nem toda fraude vira sanção; sanção pode "
                             "ter causa alheia ao sinal). n pequeno = lift instável. É calibração "
                             "relativa entre detectores, não veredito sobre empresa. Indício ≠ acusação.")}
    finally:
        con.close()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "lift":
        d = avaliar_lift()
        if not d.get("ok"):
            print(d); sys.exit(1)
        print(f"taxa-base: {d['taxa_base']*100:.2f}% ({d['sancionados_universo']}/{d['universo']})")
        for x in d["detectores"]:
            tag = "🔁circular" if x["circular"] else ("⚠️n<10" if x["n_pequeno"] else "")
            print(f"  {x['detector']:22} n={x['n']:4} lift={x['lift']:5}x taxa={x['taxa']*100:5.1f}% {tag}")
    elif len(sys.argv) > 1 and sys.argv[1] == "registrar":
        print(json.dumps(registrar_sinais(), ensure_ascii=False))
    else:
        d = medir()
        if not d.get("ok"):
            print(d)
            sys.exit(1)
        j = d["janela"]
        print(f"janela: {j['sinal_mais_antigo_dias']}d..{j['mais_novo_dias']}d")
        for s, v in sorted(d["por_sinal"].items()):
            print(f"  {s:20} n={v['n_sinais']:4} sanção_depois={v['n_sancao_depois']:3} "
                  f"pago_depois=R${v['pago_depois']:>14,.2f} vitórias_depois={v['vitorias_depois']}")
        for e in d["exemplos"][:8]:
            tag = "⚖️ SANÇÃO DEPOIS" if e["sancao_depois"] else "💸"
            print(f"  {tag} {e['cnpj']} [{e['sinal']}] desde {e['desde']} "
                  f"pago_depois=R${e['pago_depois']:,.2f}")
