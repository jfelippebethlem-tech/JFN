#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Varre o acervo SEI capturado e persiste QUEM responde por cada processo.

Alimenta duas verificações com fundamento expresso (ver `sei/agentes_publicos.montar_ficha`):
  · art. 117 da Lei 14.133/2021 — execução contratual sem fiscal formalmente designado;
  · art. 5º da Lei 14.133/2021 — ordenador de despesas que também atesta a execução
    (quebra de segregação de funções).

Determinístico, sem rede, sem LLM. Escreve em `agente_processo` e `agente_lacuna`.
Educado com a VM (2 vCPU): lê texto já capturado, um processo por vez.

    .venv/bin/python tools/sei_agentes_sweep.py [--limite N] [--so-conta]
"""
from __future__ import annotations

import argparse
import logging
import os
import pathlib
import sqlite3
import sys
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from compliance_agent.sei import acervo_texto, manifesto_norm  # noqa: E402
from compliance_agent.sei.agentes_publicos import (  # noqa: E402
    PAPEIS_DECISORIOS, PAPEIS_FISCALIZACAO, montar_ficha,
)

logger = logging.getLogger(__name__)

ACERVO = acervo_texto.RAIZ          # absoluta; honra JFN_SEI_ARQUIVO
CACHE = pathlib.Path(os.environ.get("JFN_SEI_CACHE", "data/sei_cache"))
DB = os.environ.get("JFN_DB", "data/compliance.db")


def init_schema(con: sqlite3.Connection) -> None:
    con.executescript("""
        CREATE TABLE IF NOT EXISTS agente_processo (
            processo TEXT, nome TEXT, papel TEXT, id_funcional TEXT, matricula TEXT,
            cargo TEXT, origem TEXT, documento TEXT, contexto TEXT, visto_em TEXT,
            PRIMARY KEY (processo, nome, papel)
        );
        CREATE INDEX IF NOT EXISTS ix_agente_nome ON agente_processo(nome);
        CREATE INDEX IF NOT EXISTS ix_agente_papel ON agente_processo(papel);
        CREATE INDEX IF NOT EXISTS ix_agente_id ON agente_processo(id_funcional);
        CREATE TABLE IF NOT EXISTS agente_lacuna (
            processo TEXT, tipo TEXT, descricao TEXT, visto_em TEXT,
            PRIMARY KEY (processo, tipo)
        );
    """)
    con.commit()


def _textos(pasta: pathlib.Path) -> dict[str, str]:
    td = pasta / "texto"
    if not td.is_dir():
        return {}
    docs: dict[str, str] = {}
    # pelo MANIFESTO: sobra de captura anterior não é documento do processo, e daqui saem
    # NOMES de agentes públicos (ver `sei/acervo_texto.arquivos_declarados`).
    # O PROCESSO INTEIRO. Até 20/11/2026 lia `[:60]` na ordem da árvore — e o ato de designação do fiscal costuma vir
    # depois dos despachos de abertura: a "lacuna do art. 117" saía de leitura cortada.
    for f in acervo_texto.arquivos_declarados(pasta):
        try:
            # sem a etiqueta: daqui saem NOMES de agentes públicos, e o título que nós
            # prepomos ao arquivo não pode virar pessoa (ver `sei/acervo_texto`).
            docs[f.name] = acervo_texto.sem_etiqueta(f.read_text(errors="replace"))
        except OSError:
            continue
    return docs


_CACHE_REL: dict[str, dict[str, str]] = {}
_CACHE_REL_MAX = 32


def _textos_rel(rel: str) -> dict[str, str]:
    """O processo relacionado INTEIRO, guardado entre processos: muitos pagamentos citam o mesmo processo de
    contratação, e reler o pai a cada filho multiplicava o tempo da varredura. Guarda os últimos 32 (memória)."""
    from compliance_agent.sei.relacionados import textos_do_relacionado
    if rel not in _CACHE_REL:
        if len(_CACHE_REL) >= _CACHE_REL_MAX:
            _CACHE_REL.pop(next(iter(_CACHE_REL)))
        _CACHE_REL[rel] = textos_do_relacionado(rel, ACERVO, max_docs=1_000_000)
    return _CACHE_REL[rel]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limite", type=int, default=0)
    ap.add_argument("--so-conta", action="store_true",
                    help="mede e imprime, sem gravar no banco")
    args = ap.parse_args()

    if not ACERVO.is_dir():
        print(f"acervo não encontrado: {ACERVO}", file=sys.stderr)
        return 2

    con = None
    if not args.so_conta:
        con = sqlite3.connect(DB, timeout=60)
        init_schema(con)
    agora = __import__("datetime").datetime.now().isoformat(timespec="seconds")

    pastas = sorted(p for p in ACERVO.iterdir() if p.is_dir())
    if args.limite:
        pastas = pastas[:args.limite]

    por_papel: Counter = Counter()
    n_proc = n_com_agente = n_decisor = n_fiscal = 0
    lac_117 = lac_117_parcial = lac_ordenador = alerta_segregacao = 0
    nomes_por_papel: dict[str, Counter] = {}

    for i, pasta in enumerate(pastas, 1):
        docs = _textos(pasta)
        # PROCESSO-PAI. O ato de designação quase nunca está no processo de PAGAMENTO — só 68
        # dos 2.053 processos (3,3%) têm algum. Ele vive no processo de CONTRATAÇÃO, e 18% dos
        # caches citam outro número SEI. O documento vindo de lá entra prefixado com `rel:`
        # para a evidência dizer de onde veio: responsável atribuído ao processo errado é pior
        # que responsável não identificado.
        # TODOS os relacionados, cada um INTEIRO (`max_docs` sem teto): o `[:3]` pegava os três primeiros citados, e o
        # processo de contratação podia ser o quarto. O que não está no acervo vira PARCIAL declarado.
        parcial: list[str] = []
        try:
            from compliance_agent.sei.relacionados import (
                numero_para_pasta, pasta_para_numero, relacionados_de,
            )
            for rel in relacionados_de(pasta_para_numero(pasta.name), CACHE):
                if not (ACERVO / numero_para_pasta(rel) / "texto").is_dir():
                    parcial.append(f"relacionado {rel} fora do acervo")
                    continue
                docs.update(_textos_rel(rel))
        except Exception as e:  # noqa: BLE001 — o pai é bônus; sem ele o sweep segue
            logger.debug("relacionados de %s indisponíveis: %s", pasta.name, e)
            parcial.append("relacionados ilegíveis")
        conf = manifesto_norm.conferir_documentos(pasta)
        if not conf["captura_completa"]:
            parcial.append("captura do processo incompleta" if conf["medido"]
                           else "árvore do processo não medida")
        if not docs:
            continue
        n_proc += 1
        ficha = montar_ficha(pasta.name, docs)
        if ficha.agentes:
            n_com_agente += 1
        if any(a.papel in PAPEIS_DECISORIOS for a in ficha.agentes):
            n_decisor += 1
        if any(a.papel in PAPEIS_FISCALIZACAO for a in ficha.agentes):
            n_fiscal += 1
        for a in ficha.agentes:
            por_papel[a.papel] += 1
            # ranking entre processos normaliza o nome: o mesmo servidor aparece em CAIXA ALTA
            # no bloco de assinatura e capitalizado no rótulo — sem isso ele conta duas vezes.
            nomes_por_papel.setdefault(a.papel, Counter())[a.nome.title()] += 1
        # NUNCA AFIRMAR AUSÊNCIA SOBRE LEITURA PARCIAL: a lacuna sai como `…_leitura_parcial`, com o motivo.
        if parcial:
            ficha.lacunas = [f"LEITURA PARCIAL ({'; '.join(parcial[:3])}) — ausência NÃO afirmada. {lac}"
                             for lac in ficha.lacunas]
        for lac in ficha.lacunas:
            if "117" in lac:
                lac_117 += not parcial
                lac_117_parcial += bool(parcial)
            else:
                lac_ordenador += 1
        alerta_segregacao += len(ficha.alertas)

        if con is not None:
            con.executemany(
                "INSERT OR REPLACE INTO agente_processo VALUES (?,?,?,?,?,?,?,?,?,?)",
                [(ficha.processo, a.nome, a.papel, a.id_funcional, a.matricula, a.cargo,
                  a.origem, a.documento, a.contexto[:600], agora) for a in ficha.agentes])
            # a lacuna é ESTADO do processo, recalculado a cada passada: a de antes (ex.: art. 117 afirmado sobre
            # leitura cortada) não pode sobreviver ao lado da nova.
            con.execute("DELETE FROM agente_lacuna WHERE processo = ?", (ficha.processo,))
            con.executemany(
                "INSERT OR REPLACE INTO agente_lacuna VALUES (?,?,?,?)",
                [(ficha.processo, ("art117_sem_fiscal" if "117" in l else "sem_ordenador")
                  + ("_leitura_parcial" if parcial else ""), l, agora) for l in ficha.lacunas]
                + [(ficha.processo, "segregacao_funcoes", a, agora) for a in ficha.alertas])
            if i % 100 == 0:
                con.commit()
        if i % 200 == 0:
            print(f"  ... {i}/{len(pastas)}", flush=True)

    if con is not None:
        con.commit()
        con.close()

    print(f"\nprocessos com texto : {n_proc}")
    print(f"com algum agente    : {n_com_agente} ({n_com_agente*100//max(1,n_proc)}%)")
    print(f"com decisor (ordenador/homologador): {n_decisor}")
    print(f"com fiscalizador                  : {n_fiscal}")
    print(f"\nagentes por papel: {dict(por_papel.most_common())}")
    print(f"\nLACUNA art. 117 (execução paga sem fiscal designado): {lac_117}")
    print(f"art. 117 sobre LEITURA PARCIAL (ausência não afirmada): {lac_117_parcial}")
    print(f"LACUNA sem ordenador identificado                   : {lac_ordenador}")
    print(f"ALERTA segregação de funções                        : {alerta_segregacao}")
    for papel in ("ordenador_despesa", "fiscal_contrato", "gestor_contrato"):
        top = (nomes_por_papel.get(papel) or Counter()).most_common(5)
        if top:
            print(f"\ntop {papel}: " + " · ".join(f"{n} ({c})" for n, c in top))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
