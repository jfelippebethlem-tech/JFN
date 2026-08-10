#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Processo lido pelo sweep que voltou com ZERO documento — quantos, e POR QUÊ.

POR QUE EXISTE. O sweep dizia, ciclo após ciclo, `N sem (fora de escopo/vazio)`. Isso afirma uma
CAUSA — o processo não tinha o que ler — e ninguém a mediu. Medido em 2026-08-10: dos **3.775**
processos zerados no progresso, apenas **930** têm motivo registrado no `sei_restritos.json`
(378 RESTRITO · 352 NAO_LOCALIZADO · 200 RESTRITO?). Os outros **2.794 não têm motivo nenhum** — e
**4 estão marcados OK** no registro, sem arquivo e ainda assim vazios — contradição direta: se o
cadastro diz que dá para ler, um zero ali é falha NOSSA. (Eram 51 antes de descontar os que já
tinham arquivo por outro caminho; a contradição real é a que sobra depois desse desconto.)

A distinção não é acadêmica. "Não há documento" fecha o processo para a análise; "não consegui ler"
o mantém aberto e vira fila de trabalho. Tratar os dois igual é a mesma família de erro que fez a
casa publicar ausência de prova que era ausência de CAPTURA.

O QUE ESTE SCRIPT NÃO FAZ. Não abre o SEI. Ele cruza o que já está no disco — o progresso do sweep
e o registro de restritos — e devolve a fila dos zeros SEM causa, ordenada por exposição (valor de
OB do processo, quando conhecido). Quem resolve a causa é a leitura dirigida, com browser.

    python -m tools.sei_zeros_por_causa
    python -m tools.sei_zeros_por_causa --fila 40      # os 40 primeiros a diligenciar
    python -m tools.sei_zeros_por_causa --so-contradicao   # os marcados OK que vieram vazios
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent
_PROG = _REPO / "data" / "sei_cache" / "sei_sweep_progress.json"
_REG = _REPO / "data" / "sei_restritos.json"
_DB = _REPO / "data" / "compliance.db"
_ARQ = _REPO / "data" / "sei_arquivo"

# Estados que EXPLICAM o zero. Qualquer outra coisa (inclusive ausência de registro) é causa
# desconhecida — e é isso que a fila persegue.
EXPLICAM = {"RESTRITO", "NAO_LOCALIZADO"}
# "RESTRITO?" é hipótese da casa, não confirmação: conta à parte para não virar explicação por
# osmose. A mesma disciplina do `indício ≠ acusação`, aplicada à nossa própria coleta.
SUSPEITA = {"RESTRITO?"}


def _norm(proc: str) -> str:
    return re.sub(r"\D", "", proc or "")


def medir(prog: Path | None = None, reg: Path | None = None,
          db: Path | None = None) -> dict[str, Any]:
    try:
        feitos = json.loads((prog or _PROG).read_text(encoding="utf-8")).get("feitos", {})
    except (OSError, ValueError):
        return {"ok": False, "erro": "progresso do sweep ilegível", "estado": "indisponivel"}
    try:
        registro = json.loads((reg or _REG).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        registro = {}

    zeros = [p for p, v in feitos.items()
             if not (v or {}).get("n_docs") and not (v or {}).get("arvore_docs")]
    por_causa: collections.Counter = collections.Counter()
    sem_causa: list[str] = []
    contradicao: list[str] = []
    for p in zeros:
        e = registro.get(_norm(p)) or {}
        st = str(e.get("status") or "")
        if st in EXPLICAM:
            por_causa[st] += 1
        elif st in SUSPEITA:
            por_causa[st] += 1
        elif st == "OK":
            por_causa["OK (contradição)"] += 1
            contradicao.append(p)
        else:
            por_causa["sem causa registrada"] += 1
            sem_causa.append(p)

    # EXPOSIÇÃO: o zero de um processo com R$ 80 mi pago pesa diferente do zero de um com R$ 4 mil.
    valor: dict[str, float] = {}
    try:
        con = sqlite3.connect(f"file:{db or _DB}?mode=ro", uri=True, timeout=60)
        try:
            alvo = set(sem_causa) | set(contradicao)
            # A ponte processo→OB é `ob_orcamentaria_siafe.processo`, que é a MESMA que o sweep usa
            # para montar a fila. Minha primeira versão usou `ordens_bancarias.numero_sei`: o campo
            # está preenchido em **10** processos no acervo inteiro, então a ordenação por exposição
            # saía toda zerada — publicar essa fila seria oferecer uma prioridade que não prioriza.
            for num, v in con.execute(
                    "SELECT processo, COALESCE(SUM(valor),0) FROM ob_orcamentaria_siafe "
                    "WHERE COALESCE(processo,'') <> '' AND status='Contabilizado' GROUP BY 1"):
                if num in alvo:
                    valor[num] = float(v or 0)
        finally:
            con.close()
    except sqlite3.Error:
        valor = {}

    # O PROGRESSO NÃO É A ÚLTIMA PALAVRA. Um processo pode constar "0 docs" no progresso do sweep e
    # ainda assim ter pasta no arquivo — chegou por outro caminho (colheita da VM-2, recaptura
    # integral). Medido em 2026-08-10: 6 dos 20 zeros de maior exposição já tinham arquivo, entre
    # eles o maior de todos. Sem esta conferência a fila mandaria rebuscar o que já está em casa.
    # (E a conferência só vale com CONTROLE POSITIVO: a primeira versão usava o nome com prefixo
    # `SEI-`, que as pastas não têm, e dizia "nenhum tem arquivo" — inclusive para processos com
    # 375 documentos lidos.)
    def _tem_arquivo(proc: str) -> bool:
        return (_ARQ / proc.replace("SEI-", "").replace("/", "_")).exists()

    ja_no_arquivo = [p for p in sem_causa if _tem_arquivo(p)]
    sem_causa = [p for p in sem_causa if p not in set(ja_no_arquivo)]
    contradicao = [p for p in contradicao if not _tem_arquivo(p)]
    # Os contadores TÊM de refletir o mundo DEPOIS do filtro de arquivo, senão a tabela do painel
    # mostra 51 contradições ao lado de uma lista com 4 — foi o que a rota exibiu na estreia.
    # Quem tem arquivo sai da sua categoria de origem e entra na de "já capturado por outro caminho",
    # venha ele de "sem causa" ou de "OK (contradição)".
    contradicao_com_arquivo = por_causa.get("OK (contradição)", 0) - len(contradicao)
    por_causa["sem causa registrada"] = len(sem_causa)
    por_causa["OK (contradição)"] = len(contradicao)
    por_causa["zero no progresso, mas COM arquivo (outro caminho)"] = (
        len(ja_no_arquivo) + contradicao_com_arquivo)
    ordenar = sorted(sem_causa, key=lambda p: -valor.get(p, 0.0))
    return {
        "ok": True, "estado": "medido",
        "processos_com_registro": len(feitos), "zeros": len(zeros),
        "pct_zeros": round(100.0 * len(zeros) / len(feitos), 1) if feitos else 0.0,
        "por_causa": dict(por_causa.most_common()),
        "sem_causa": len(sem_causa),
        "ja_no_arquivo_por_outro_caminho": len(ja_no_arquivo),
        "contradicao_ok_mas_vazio": contradicao,
        "fila": [{"processo": p, "valor_ob": round(valor.get(p, 0.0), 2)} for p in ordenar],
        "valor_ob_sem_causa": round(sum(valor.get(p, 0.0) for p in sem_causa), 2),
        "ressalva": (
            "Zero documento NÃO é 'processo vazio': é 'não trouxe nada', e a causa só está medida "
            "para uma fração. Enquanto a causa não é conhecida, o processo segue ABERTO para a "
            "análise — nenhuma conclusão de ausência pode se apoiar nele."),
    }


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    ap = argparse.ArgumentParser()
    ap.add_argument("--fila", type=int, default=0, help="imprime os N primeiros a diligenciar")
    ap.add_argument("--so-contradicao", action="store_true",
                    help="só os marcados OK no registro que ainda assim vieram vazios")
    a = ap.parse_args(argv)
    r = medir()
    if not r.get("ok"):
        print(f"INDISPONÍVEL: {r.get('erro')}")
        return 1
    if a.so_contradicao:
        print(f"{len(r['contradicao_ok_mas_vazio'])} processo(s) marcados OK que vieram VAZIOS "
              "— se o cadastro diz que dá para ler, o zero é falha nossa:")
        for p in r["contradicao_ok_mas_vazio"]:
            print(f"   {p}")
        return 0
    print(f"processos com registro de leitura: {r['processos_com_registro']:,}".replace(",", "."))
    print(f"  voltaram com ZERO documento: {r['zeros']:,} ({r['pct_zeros']}%)".replace(",", "."))
    for k, v in r["por_causa"].items():
        print(f"     {v:6}  {k}")
    from compliance_agent.reporting.intel_base import moeda
    print(f"  soma de OB dos zeros SEM causa: R$ {moeda(r['valor_ob_sem_causa'])}")
    if a.fila:
        print(f"\nfila a diligenciar (maior exposição primeiro), {a.fila} de {r['sem_causa']}:")
        for x in r["fila"][: a.fila]:
            print(f"   {x['processo']:28} R$ {moeda(x['valor_ob']):>18}")
    print(f"\n{r['ressalva']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
