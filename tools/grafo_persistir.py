# -*- coding: utf-8 -*-
"""Persiste o grafo de vínculos dos credores que o Estado PAGOU — as tabelas estavam a zero.

`pessoas` e `relacionamentos` existem no schema desde sempre, `osint/persistencia.salvar_grafo` foi
escrito e testado, e **nenhum caller** os alimentava: 0 e 0 linhas. Sem isso, cada consulta remonta
o grafo do zero, nada sobrevive à execução e a pergunta mais útil — *o que mudou desde a última
vez?* — não tem onde ser feita.

O UNIVERSO É O DE QUEM RECEBEU DINHEIRO, e vem do **SIAFE** (`ob_orcamentaria_siafe`), nunca do
espelho TFE, com `status='Contabilizado'` — OB anulada ou excluída não é pagamento e já inflou
número nesta casa. São 5.615 credores PJ distintos, ordenados pelo valor pago: quem mais recebeu é
quem primeiro merece grafo.

MEDIDO ANTES DE LIGAR (família 18), nos 100 maiores credores, 189 s: 215 arestas societárias (24
credores sem nenhuma), 62 `mesmo_telefone`, 69 `mesmo_email` e 140 `mesmo_contador` — mais 33
telefones e 22 e-mails descartados por fan-out. E a cobertura desmente o susto dos 5 primeiros
(todos sem QSA): nos 500 maiores, 399 das 493 raízes têm QSA (81%), 499 têm registro de
estabelecimento e 474 têm telefone. Os do topo são banco e ente público, não lacuna.

RETOMADA POR FATO, NÃO POR CONTAGEM. `grafo_persistido` grava o CNPJ processado **mesmo com zero
arestas** — porque "olhei e não achei vínculo" e "nunca olhei" são coisas diferentes, e ler uma
como a outra é a família 22 do catálogo. A ~1,9 s por credor, o universo inteiro leva ~3 h; por
isso `--limite` existe e o sweep chama em fatias.

    python -m tools.grafo_persistir --limite 200        # grava
    python -m tools.grafo_persistir --limite 20 --seco  # mede sem escrever
"""
from __future__ import annotations

import argparse
import collections
import sqlite3
import time
from pathlib import Path

from compliance_agent.osint.contato_compartilhado import (
    explicacao_estrutural,
    vinculos_por_contato,
)
from compliance_agent.osint.fonte_grafo import _razao_social, montar_grafo_societario
from compliance_agent.osint.persistencia import salvar_grafo
from compliance_agent.osint.vinculos import no_pj

_CRIA_MARCA = """
CREATE TABLE IF NOT EXISTS grafo_persistido (
    cnpj TEXT PRIMARY KEY,
    arestas INTEGER NOT NULL,
    valor_pago REAL,
    processado_em TEXT NOT NULL
)"""


def _fatia() -> tuple[int, int]:
    """`JFN_SWEEP_FATIA=1/2` → `(1, 2)`. Sem a variável, máquina única `(0, 1)`.

    DUAS MÁQUINAS NA MESMA FILA DUPLICAM, NÃO SOMAM. Medido em 2026-08-07: a VM-2 rodou o grafo e
    percorreu **os mesmos 400 credores** que a VM-1 já tinha feito — as duas atacam o topo da mesma
    ordem por valor, e `grafo_persistido` é local a cada máquina. Sem fatia, a segunda gasta CPU
    para refazer o que existe. É a mesma divisão que o sweep SEI já usava, aplicada onde faltava.
    """
    import os

    bruto = (os.environ.get("JFN_SWEEP_FATIA") or "").strip()
    if not bruto:
        return 0, 1
    try:
        i, n = (int(x) for x in bruto.split("/", 1))
    except ValueError:
        return 0, 1
    return (i, n) if 0 <= i < n else (0, 1)


def universo(con: sqlite3.Connection, limite: int) -> list[tuple[str, float]]:
    """Credores PJ ainda não processados, do maior valor pago para o menor (SIAFE, contabilizado).

    A fatia da máquina é aplicada por RESTO DO CNPJ, não por posição na lista: assim as duas
    metades são estáveis entre rodadas e não dependem de quem chegou primeiro.
    """
    con.execute(_CRIA_MARCA)
    indice, total = _fatia()
    linhas = [(r[0], float(r[1] or 0.0)) for r in con.execute(
        "SELECT credor, SUM(valor) v FROM ob_orcamentaria_siafe "
        "WHERE status='Contabilizado' AND length(credor)=14 "
        "  AND credor NOT IN (SELECT cnpj FROM grafo_persistido) "
        "GROUP BY 1 ORDER BY v DESC LIMIT ?", (limite * max(total, 1),)).fetchall()]
    if total > 1:
        linhas = [x for x in linhas if int(x[0]) % total == indice]
    return linhas[:limite]


def _naturezas(raizes: set[str]) -> dict[str, str]:
    """Natureza jurídica das raízes, da base de estabelecimentos. Ausente devolve vazio."""
    caminho = Path(__file__).resolve().parent.parent / "data" / "receita_estab.db"
    if not caminho.exists() or not raizes:
        return {}
    con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    try:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='empresas'"
                           ).fetchone():
            return {}
        ph = ",".join("?" * len(raizes))
        return {r[0]: str(r[1] or "") for r in con.execute(
            f"SELECT cnpj_basico, natureza_cod FROM empresas WHERE cnpj_basico IN ({ph})",
            tuple(raizes))}
    finally:
        con.close()


def grafo_do_credor(con_ro: sqlite3.Connection, cnpj: str):
    """Grafo societário do credor mais as arestas de contato compartilhado.

    As duas fontes entram no MESMO grafo de propósito: telefone e e-mail ligam empresas que a
    cadeia societária não liga, e é justamente aí que o vínculo interessa.
    """
    grafo, diag = montar_grafo_societario(con_ro, cnpj, profundidade=4)
    contato = vinculos_por_contato([cnpj])
    # A EXPLICAÇÃO ESTRUTURAL VIAJA COM A ARESTA. Percorrendo 850 credores, as empresas mais
    # ligadas por contato eram CONSÓRCIOS — que dividem telefone e e-mail com as consorciadas por
    # desenho da lei. Sem isto, a lista de "elos ocultos" é encabeçada por forma jurídica.
    _nat = _naturezas({a["de"][:8] for a in contato["arestas"]}
                      | {a["para"][:8] for a in contato["arestas"]} | {cnpj[:8]})
    for a in contato["arestas"]:
        # OS DOIS SUBGRAFOS PRECISAM SE TOCAR. O societário chaveia por RAIZ (8 dígitos) e o
        # contato devolve o CNPJ inteiro: ligados como vinham, a MESMA empresa virava dois nós —
        # medido na primeira passada, 40 nós de 8 dígitos e 186 de 14 — e a aresta de telefone
        # jamais alcançava a cadeia de sócios do próprio credor. Raiz é a identidade certa: é a
        # mesma regra que já governa o fan-out, porque filial não é outra empresa.
        de, para = no_pj(a["de"][:8]), no_pj(a["para"][:8])
        grafo.rotular(de, _razao_social(con_ro, a["de"][:8]))
        grafo.rotular(para, _razao_social(con_ro, a["para"][:8]))
        _estrutural = explicacao_estrutural(_nat.get(a["de"][:8], ""),
                                            _nat.get(a["para"][:8], ""))
        grafo.ligar(de, para, a["tipo"], fonte=a["fonte"],
                    detalhe=f"{a['detalhe']} · {a['de']} × {a['para']}"
                            + (f" · ESTRUTURAL: {_estrutural}" if _estrutural else ""),
                    observacoes=[x for x in (a["explicacao_inocente"], _estrutural) if x])
    return grafo, diag, contato


def persistir(limite: int = 200, *, db: str = "", seco: bool = False) -> dict:
    from compliance_agent.reporting.intel_base import _DB

    caminho = db or _DB
    con = sqlite3.connect(caminho, timeout=60)
    con.row_factory = sqlite3.Row
    ro = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    ro.row_factory = sqlite3.Row
    inicio = time.time()
    tot = collections.Counter()
    por_tipo: collections.Counter = collections.Counter()
    try:
        alvos = universo(con, limite)
        for cnpj, valor in alvos:
            grafo, _diag, contato = grafo_do_credor(ro, cnpj)
            for a in grafo.arestas:
                por_tipo[a.tipo] += 1
            for k, n in contato["descartados"].items():
                tot["descarte_" + k] += n
            if seco:
                tot["arestas_vistas"] += len(grafo.arestas)
                continue
            r = salvar_grafo(con, grafo)
            for k in ("pessoas_novas", "arestas_novas", "arestas_repetidas", "recusadas"):
                tot[k] += int(r[k])
            con.execute(
                "INSERT OR REPLACE INTO grafo_persistido (cnpj, arestas, valor_pago, "
                "processado_em) VALUES (?,?,?,datetime('now'))",
                (cnpj, len(grafo.arestas), valor))
            con.commit()
    finally:
        ro.close()
        con.close()
    return {"credores": len(alvos), "segundos": round(time.time() - inicio, 1),
            "por_tipo": dict(por_tipo), **dict(tot)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limite", type=int, default=200, help="credores por passada (~1,9 s cada)")
    ap.add_argument("--seco", action="store_true", help="mede sem escrever nada")
    a = ap.parse_args()
    for k, v in persistir(a.limite, seco=a.seco).items():
        print(f"{k:24s} {v}")


if __name__ == "__main__":
    main()
