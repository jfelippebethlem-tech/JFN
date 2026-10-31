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

A EVIDÊNCIA JÁ ESTAVA NO ARQUIVO (2026-08-11). "Sem causa registrada" era grande demais porque só
o `sei_restritos.json` era consultado. O PRÓPRIO progresso do sweep guarda `rel` — e `rel > 15` com
zero documento é, pela regra do `sei_sweep`, a CAIXA de entrada do SEI, isto é, a LEITURA FALHOU.
São **1.050** processos: um terço do balde de ignorância tinha a causa gravada em casa. Também
guarda `tentativas`: 3+ significa que o sweep DESISTIU — atributo do item (precisa de outro
caminho, não de uma 4ª tentativa igual), nunca uma causa a mais na tabela.

O QUE ESTE SCRIPT NÃO FAZ. Não abre o SEI. Ele cruza o que já está no disco — o progresso do sweep
e o registro de restritos — e devolve a fila de diligência (sem causa + CAIXA), ordenada por
exposição (valor de OB do processo, quando conhecido). Quem resolve a causa é a leitura dirigida.

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

# A CAIXA. O `sei_sweep` decide pelo mesmo limiar: `len(relacionados) > 15` com 0 documento é a
# caixa de entrada/desktop do SEI (~40 itens), não o processo — e é por isso que ele retenta e
# depois cai no método CRACKED. Ou seja: no instante em que a entrada foi gravada, a casa JÁ sabia
# que a LEITURA falhou. Mesmo assim o zero saía como "sem causa registrada" (1.057 dos 3.206 no
# acervo de 2026-08-11). Evidência que está no próprio arquivo não pode ser contada como ignorância.
_REL_CAIXA = 15
CAIXA = "CAIXA (leitura falhou)"

# Régua única da casa para "isto é pagamento a fornecedor?" — a MESMA que a fila do `sei_sweep`
# usa para rebaixar folha. Duas cópias do mesmo critério divergem: o teto do art. 125 chegou a
# cinco, com valores diferentes, dentro de detectores de risco alto.
from compliance_agent.credor_generico import (  # noqa: E402
    LIMIAR_FORNECEDOR as _LIMIAR_FORNECEDOR,
    classificar_por_processo as _classificar,
)


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
    caixa: list[str] = []
    contradicao: list[str] = []
    for p in zeros:
        e = registro.get(_norm(p)) or {}
        st = str(e.get("status") or "")
        # O REGISTRO MANDA MAIS QUE O PROGRESSO: `RESTRITO` é apuração; `rel` é sintoma. Invertida,
        # a ordem faria a CAIXA roubar os restritos já confirmados e inflar a fila de diligência com
        # o que já está fechado por falta de ACESSO.
        if st in EXPLICAM:
            por_causa[st] += 1
        elif st in SUSPEITA:
            por_causa[st] += 1
        elif st == "OK":
            por_causa["OK (contradição)"] += 1
            contradicao.append(p)
        elif ((feitos.get(p) or {}).get("rel") or 0) > _REL_CAIXA:
            por_causa[CAIXA] += 1
            caixa.append(p)
        else:
            por_causa["sem causa registrada"] += 1
            sem_causa.append(p)

    # EXPOSIÇÃO: o zero de um processo com R$ 80 mi pago pesa diferente do zero de um com R$ 4 mil.
    valor: dict[str, float] = {}
    forn: dict[str, float] = {}
    publico: dict[str, float] = {}
    try:
        con = sqlite3.connect(f"file:{db or _DB}?mode=ro", uri=True, timeout=60)
        try:
            alvo = set(sem_causa) | set(contradicao) | set(caixa)
            # A ponte processo→OB é `ob_orcamentaria_siafe.processo`, que é a MESMA que o sweep usa
            # para montar a fila. Minha primeira versão usou `ordens_bancarias.numero_sei`: o campo
            # está preenchido em **10** processos no acervo inteiro, então a ordenação por exposição
            # saía toda zerada — publicar essa fila seria oferecer uma prioridade que não prioriza.
            # E A EXPOSIÇÃO TAMBÉM PRECISA DIZER DE QUE ELA É FEITA. Medido em 2026-08-11: dos
            # R$ 9,90 bi desta fila, R$ 6,17 bi (62%) são FOLHA e previdência (`CG0004700`,
            # `123400`, `CG0006026`) e só R$ 3,73 bi é pagamento a CNPJ/CPF. Publicar o total como
            # exposição fiscalizável superestima — é a família dos quatro números de manchete já
            # corrigidos. A régua é a da casa (`credor_generico`), a mesma que a fila do sweep usa.
            # `Contabilizado` é obrigatório aqui porque este número vai para o PAINEL: a casa já
            # somou OB cancelada numa fila do fiscal.
            for num, c in _classificar(con, status="Contabilizado").items():
                if num in alvo:
                    valor[num] = c["total"]
                    forn[num] = c["fornecedor"]
                    publico[num] = c["publico"]
        finally:
            con.close()
    except sqlite3.Error:
        valor, forn, publico = {}, {}, {}

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
    caixa_com_arquivo = [p for p in caixa if _tem_arquivo(p)]
    sem_causa = [p for p in sem_causa if p not in set(ja_no_arquivo)]
    caixa = [p for p in caixa if p not in set(caixa_com_arquivo)]
    contradicao = [p for p in contradicao if not _tem_arquivo(p)]
    # Os contadores TÊM de refletir o mundo DEPOIS do filtro de arquivo, senão a tabela do painel
    # mostra 51 contradições ao lado de uma lista com 4 — foi o que a rota exibiu na estreia.
    # Quem tem arquivo sai da sua categoria de origem e entra na de "já capturado por outro caminho",
    # venha ele de "sem causa", da CAIXA ou de "OK (contradição)".
    contradicao_com_arquivo = por_causa.get("OK (contradição)", 0) - len(contradicao)
    por_causa["sem causa registrada"] = len(sem_causa)
    por_causa[CAIXA] = len(caixa)
    por_causa["OK (contradição)"] = len(contradicao)
    por_causa["zero no progresso, mas COM arquivo (outro caminho)"] = (
        len(ja_no_arquivo) + len(caixa_com_arquivo) + contradicao_com_arquivo)
    por_causa = collections.Counter({k: v for k, v in por_causa.items() if v})

    # A FILA É O TRABALHO ABERTO, não a cesta "sem causa". A CAIXA tem causa conhecida e mesmo assim
    # exige diligência — o processo continua ILEGÍVEL. Cada item declara a sua causa para que a
    # priorização não confunda "não sei por quê" com "sei, e falhamos".
    def _item(p: str, causa: str) -> dict[str, Any]:
        f = feitos.get(p) or {}
        tot, fo = valor.get(p, 0.0), forn.get(p, 0.0)
        return {"processo": p, "valor_ob": round(tot, 2), "causa": causa,
                "valor_ob_fornecedor": round(fo, 2),
                # Repasse a ente público (fundo municipal de saúde, Ministério da Fazenda) tem
                # CNPJ e passava como fornecedor: R$ 601 mi da fila. Não é contratação.
                "valor_ob_publico": round(publico.get(p, 0.0), 2),
                # Sem OB conhecida NÃO é folha: na dúvida o processo segue como trabalho de
                # fornecedor, porque rebaixar por ausência de dado esconderia trabalho.
                "eh_folha": bool(tot > 0 and fo / tot < _LIMIAR_FORNECEDOR),
                # 3+ tentativas com 0 documento não diz vazio nem falha — diz que o sweep DESISTIU.
                # Repetir a mesma leitura é gastar browser; esses precisam de outro caminho
                # (CRACKED, VM-2, pedido formal). É atributo do item, nunca uma causa a mais.
                "esgotou_tentativas": bool((f.get("tentativas") or 0) >= 3),
                "tentativas": int(f.get("tentativas") or 0),
                "lido_em": f.get("em") or ""}

    itens = ([_item(p, "sem causa registrada") for p in sem_causa]
             + [_item(p, CAIXA) for p in caixa])
    # ORDENA PELO QUE A FISCALIZAÇÃO PERSEGUE. Por valor bruto, o topo da fila era folha e
    # previdência — pagamento grande, legítimo, e que nenhum detector de licitação examina.
    itens.sort(key=lambda x: (-x["valor_ob_fornecedor"], -x["valor_ob"]))
    return {
        "ok": True, "estado": "medido",
        "processos_com_registro": len(feitos), "zeros": len(zeros),
        "pct_zeros": round(100.0 * len(zeros) / len(feitos), 1) if feitos else 0.0,
        "por_causa": dict(por_causa.most_common()),
        "sem_causa": len(sem_causa),
        "caixa_leitura_falhou": len(caixa),
        "ja_no_arquivo_por_outro_caminho": len(ja_no_arquivo),
        "contradicao_ok_mas_vazio": contradicao,
        "fila": itens,
        "valor_ob_sem_causa": round(sum(valor.get(p, 0.0) for p in sem_causa), 2),
        "valor_ob_fila": round(sum(x["valor_ob"] for x in itens), 2),
        "valor_ob_fornecedor": round(sum(x["valor_ob_fornecedor"] for x in itens), 2),
        "valor_ob_publico": round(sum(x["valor_ob_publico"] for x in itens), 2),
        "valor_ob_folha": round(sum(x["valor_ob"] - x["valor_ob_fornecedor"]
                                    - x["valor_ob_publico"] for x in itens), 2),
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
    pct = (100.0 * r["valor_ob_fornecedor"] / r["valor_ob_fila"]) if r["valor_ob_fila"] else 0.0
    print(f"  da fila inteira (R$ {moeda(r['valor_ob_fila'])}): "
          f"R$ {moeda(r['valor_ob_fornecedor'])} é pagamento a FORNECEDOR ({pct:.1f}%), "
          f"R$ {moeda(r['valor_ob_publico'])} é repasse a ente público e "
          f"R$ {moeda(r['valor_ob_folha'])} é folha/previdência")
    if a.fila:
        print(f"\nfila a diligenciar (maior exposição a FORNECEDOR primeiro), {a.fila} de "
              f"{len(r['fila'])} ({r['sem_causa']} sem causa + {r['caixa_leitura_falhou']} CAIXA):")
        for x in r["fila"][: a.fila]:
            marca = " ⛔3+" if x["esgotou_tentativas"] else "    "
            folha = " [folha]" if x["eh_folha"] else ""
            print(f"   {x['processo']:28} R$ {moeda(x['valor_ob_fornecedor']):>18}{marca}  "
                  f"{x['causa']}{folha}")
    print(f"\n{r['ressalva']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
