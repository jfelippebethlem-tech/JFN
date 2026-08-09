#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mantém (e RETIRA) o aviso de "valor é piso" nas notas de caso do vault.

POR QUE EXISTE. Em 2026-08-09 descobriu-se que a coleta do SIAFE tinha 23 pares (UG, ano) parados
em contagem redonda — e que todo valor citado nas notas era **piso**, não total. O tamanho do erro
é grande: a PHOTONLUX saiu de R$ 4,3 mi para R$ 385,8 mi ao recoletar UM ano. As notas afetadas
ganharam um aviso dizendo quais UG/anos faltavam.

Só que **o aviso envelhece**: a drenagem roda a cada 2 h e vai destravando os pares. Um aviso que
lista "UG 294200: 2022" depois de 2022 estar drenado é ruído — e ruído ensina o leitor a pular o
bloco de alerta, que é o pior resultado possível. Aqui o aviso é REESCRITO a cada passada, com a
lista de agora, e **some sozinho** quando nenhuma UG citada na nota tem mais ano travado.

Regra de honestidade: o aviso só cita UG que a nota REALMENTE menciona. Marcar nota que não fala
daquela unidade seria alarme genérico — e alarme genérico ninguém lê.

    python -m tools.vault_aviso_piso_siafe            # relatório (não escreve)
    python -m tools.vault_aviso_piso_siafe --aplicar  # atualiza/retira os avisos
"""
from __future__ import annotations

import argparse
import re
import sqlite3
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
CASOS = Path.home() / "vault" / "casos"
MARCA = "<!-- piso-siafe -->"
_FIM = re.compile(rf"{re.escape(MARCA)}\n(?:>.*\n)+\n?", re.M)
CONTAGENS_DE_TETO = (1000, 2000, 3000, 5000)


def travados(db: str = "") -> dict[str, list[int]]:
    """{UG: [anos]} cujas contagens ainda são redondas — o sintoma do teto de coleta."""
    from compliance_agent.reporting.intel_base import _DB

    con = sqlite3.connect(f"file:{db or _DB}?mode=ro", uri=True, timeout=30)
    try:
        fora: dict[str, list[int]] = {}
        marcas = ",".join(str(n) for n in CONTAGENS_DE_TETO)
        for ug, ano in con.execute(
                "SELECT ug_emitente, exercicio FROM ob_orcamentaria_siafe "
                f"GROUP BY 1,2 HAVING COUNT(*) IN ({marcas}) ORDER BY 1,2"):
            fora.setdefault(str(ug), []).append(int(ano))
        return fora
    except sqlite3.Error:
        return {}
    finally:
        con.close()


def _aviso(cita: dict[str, list[int]]) -> str:
    detalhe = " · ".join(f"UG {u}: {', '.join(map(str, sorted(a)))}" for u, a in sorted(cita.items()))
    return (f"{MARCA}\n"
            f"> ⚠️ **Os valores de SIAFE nesta nota são PISO.** A coleta do SIAFE ficou anos parada em\n"
            f"> contagem redonda por defeitos de chave, limiar e ingestão — já corrigidos. Ainda faltam\n"
            f"> drenar: **{detalhe}**. A drenagem roda a cada 2 h (`tools/siafe_drenar_capados.sh`);\n"
            f"> **refaça a soma antes de qualquer peça**. Tamanho real do erro: a PHOTONLUX saiu de\n"
            f"> R$ 4,3 mi para R$ 385,8 mi ao recoletar UM ano.\n\n")


def aplicar(escrever: bool = False, db: str = "") -> dict:
    tv = travados(db)
    posto = retirado = intacto = 0
    detalhes: list[str] = []
    for f in sorted(CASOS.glob("*.md")) if CASOS.exists() else []:
        try:
            t = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "R$" not in t:
            continue
        cita = {u: a for u, a in tv.items() if u in t}
        tinha = MARCA in t
        limpo = _FIM.sub("", t)
        if cita:
            partes = limpo.split("---\n", 2)          # aviso entra depois do frontmatter
            novo = (partes[0] + "---\n" + partes[1] + "---\n\n" + _aviso(cita) + partes[2]
                    if len(partes) >= 3 else _aviso(cita) + limpo)
            acao = "atualizado" if tinha else "posto"
        else:
            novo, acao = limpo, ("retirado" if tinha else None)
        if acao is None or novo == t:
            intacto += 1
            continue
        if escrever:
            f.write_text(novo, encoding="utf-8")
        detalhes.append(f"{acao}: {f.name}")
        if acao == "retirado":
            retirado += 1
        else:
            posto += 1
    return {"ug_ano_travados": sum(len(v) for v in tv.values()), "postos_ou_atualizados": posto,
            "retirados": retirado, "sem_mudanca": intacto, "detalhes": detalhes}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aplicar", action="store_true", help="escreve nas notas (sem isto, só relata)")
    a = ap.parse_args(argv)
    r = aplicar(a.aplicar)
    print(f"pares (UG, ano) ainda travados: {r['ug_ano_travados']}")
    print(f"avisos postos/atualizados: {r['postos_ou_atualizados']} · retirados: {r['retirados']} "
          f"· sem mudança: {r['sem_mudanca']}")
    for d in r["detalhes"]:
        print("   ", d)
    if not a.aplicar and r["detalhes"]:
        print("\n(nada foi escrito — rode com --aplicar)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
