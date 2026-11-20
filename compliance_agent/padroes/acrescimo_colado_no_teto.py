# -*- coding: utf-8 -*-
"""Acréscimos declarados que SOMAM no teto (24–25%; 49–50% em reforma) ou acima dele — e acréscimo BRUTO acima do
teto disfarçado pelo líquido (acréscimo − supressão).

ORIGEM (perícias integrais 18/11/2026): SEAP × Seleta (SEI-210108/000153/2023) — 1º TA 5,90% + 2º 3,61% + 5º 14,59%
= 24,10%; INEA × Brasform (SEI-070002/006481/2024) — 19,96% + 4,35% = 24,31%; INEA × Hydra (026015/2024) — 24,87%
(com supressão de 2,50%); INEA × Lazarus (012176/2025) — 24,04% bruto.

NORMA: Lei 8.666/93 art. 65 §1º / Lei 14.133/21 art. 125 — teto de `limites_aditivo` (fonte única; inclusivo: 25,00%
exatos é permitido, memória teto-legal-e-limite-inclusivo). Acréscimos e supressões computam-se SEPARADAMENTE (TCU
Acórdão 749/2010-Plenário): compensar acréscimo com supressão para caber no teto é vedado.

SINAL: soma das declarações DISTINTAS de "acréscimo ... percentual de X%" nos termos aditivos do processo, por
contrato aditado. GRAU: forte = soma bruta acima do teto; medio = soma dentro de [teto − 1 p.p., teto] (encostado:
indício de cálculo ajustado ao limite, não prova); fraco = nunca emitido.
EXPLICAÇÕES INOCENTES: percentuais sobre bases diferentes (cada termo mede sobre o valor inicial atualizado da sua
data — a soma é aproximação); termo de reajuste que fala em "acréscimo" (excluído: janela com reajuste/IPCA/INCC/
repactuação); o mesmo termo repetido em várias peças (deduplicado por percentual+data).
"""
from __future__ import annotations

import re

from compliance_agent import limites_aditivo as L
from compliance_agent.padroes import _aditivos_comum as C

ID = "acrescimo_colado_no_teto"
FOLGA_PP = 1.0      # "encostado" = até 1 ponto percentual abaixo do teto
_RE_TALVEZ_REFORMA = re.compile(r"reforma|moderniza|adequa[çc][ãa]o\s+(?:f[íi]sica|predial|d[aoe]s?\s+(?:pr[ée]dio|"
                                r"edif|instala|complexo|unidade))|amplia[çc][ãa]o|requalifica|revitaliza", re.I)


def avaliar(decls: list[dict], objeto: str = "") -> dict | None:
    """Função pura: declarações de UM contrato → veredito ou None."""
    validas = [x for x in decls if not C.RE_REAJUSTE.search(x.get("trecho") or "")]
    if not validas:
        return None
    tipo = L.tipo_objeto(objeto)
    teto = L.teto_acrescimo(tipo) * 100
    soma = round(sum(x["pct"] for x in validas), 2)
    supr = round(sum(x.get("pct_supressao") or 0 for x in validas), 2)
    if soma > teto + 1e-9 and tipo is None and soma <= 50.0 and _RE_TALVEZ_REFORMA.search(objeto or ""):
        # FAETEC × Scalle (260005/*): "adequação e modernização dos complexos esportivos" com 47,18% e 49,62% —
        # se o objeto for REFORMA de edifício, o teto é 50% e o acréscimo está encostado, não estourado. Sem
        # leitura humana do objeto, fica médio com a ressalva.
        g = "medio"
        motivo = (f"acréscimos declarados somam {soma:.2f}% — acima de 25%; objeto pode ser reforma/modernização "
                  f"(teto de 50%), caso em que está encostado no teto")
    elif soma > teto + 1e-9:
        g = "forte"
        motivo = (f"acréscimos declarados somam {soma:.2f}% (bruto) > teto de {teto:.0f}%"
                  + (f"; líquido de supressões {soma - supr:.2f}% — o teto se controla pelo BRUTO" if supr else ""))
    elif soma >= teto - FOLGA_PP:
        g = "medio"
        motivo = f"acréscimos declarados somam {soma:.2f}% — encostados no teto de {teto:.0f}%"
    else:
        return None
    return {"grau": g, "soma_pct": soma, "supressao_pct": supr, "teto_pct": teto, "tipo_objeto": tipo or "padrao",
            "motivo": motivo, "itens": validas}


def varrer(limite: int | None = None) -> dict:
    idx = C.indice(limite=limite)["processos"]
    funil = {"processos": len(idx), "com_termo_aditivo": 0, "com_declaracao_de_acrescimo": 0, "achados": 0}
    cob = {"termos_sem_texto": 0, "termos_alheios": 0}
    achados = []
    for tag, p in idx.items():
        termos, fora = C.termos_do_processo(p)
        cob["termos_sem_texto"] += fora["sem_texto"]
        cob["termos_alheios"] += fora["alheios"]
        if not termos:
            continue
        funil["com_termo_aditivo"] += 1
        decl = C.declaracoes_do_processo(termos)
        c = C.contrato_principal(decl)
        if not c:
            continue
        funil["com_declaracao_de_acrescimo"] += 1
        objeto = C.objeto_dos_termos(termos)
        v = avaliar(decl[c], objeto)
        if not v:
            continue
        funil["achados"] += 1
        prova = "; ".join(f"doc {x['doc']} — \"{x['trecho'][:220]}\"" + (f" (assinado {x['data']})" if x["data"] else "")
                          for x in v["itens"][:6])
        achados.append(C.achado(
            C.chave_de_tag(tag), v["grau"], prova=prova,
            porque=(v["motivo"] + ". Soma de percentuais declarados sobre o valor inicial atualizado de cada data "
                    "(aproximação); termos de reajuste excluídos; mesmo termo em várias peças contado uma vez. "
                    f"Norma: {L.ato_normativo('8666')} / {L.ato_normativo('14133')}."),
            fonte=f"termos aditivos do processo ({termos[0][0]['fonte']})", contrato=c,
            soma_pct=v["soma_pct"], supressao_pct=v["supressao_pct"], teto_pct=v["teto_pct"],
            n_termos=len(v["itens"])))
    return C.resultado(ID, funil["com_termo_aditivo"], cob, achados, funil)
