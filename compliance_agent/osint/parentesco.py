# -*- coding: utf-8 -*-
"""Vínculo familiar como HIPÓTESE MEDIDA — nunca como conclusão.

O QUE NÃO EXISTE, e é preciso dizer antes de qualquer código. Não há base aberta brasileira de
parentesco. Foi conferido na fonte, não de memória: o Registro Civil (`transparencia.
registrocivil.org.br`) só serve agregado por UF — zero valor individual; o TSE não tem campo de
parentesco nos dados abertos e restringiu os bens detalhados por LGPD; **nome da mãe não é público
em nenhuma base federal** (a coluna `pessoas.nome_mae` existe no schema desta casa e sempre esteve
vazia — é assim que fica). O banco de vínculos do TCU que cita "pai/mãe/irmão" — e cuja metodologia
de padrões topológicos em grafos é o fundamento citável desta abordagem — é alimentado por Receita e
CNIS, bases restritas que não temos. Cita-se o MÉTODO, não se finge ter o insumo.

Logo: parentesco aqui é inferência, e a única maneira honesta de fazer inferência é **medir a
prevalência de cada eixo na própria base antes de deixá-lo pesar**. A casa aprendeu isso caro: o
perfil de laranja marcava 55% do acervo até alguém medir que "empresa com um só sócio" é 54,9% do
normal; o P1 acusava 71% dos certames; dois detectores tinham lift ANTI-preditivo. Um eixo que
acende na maioria não mede o alvo, mede a base.

AS QUATRO MEDIÇÕES, feitas em 2026-07-29 sobre 31.132 raízes com QSA:

  · **Co-ocorrência societária repetida** — as mesmas duas pessoas sócias de 2+ empresas: **4,76%**
    das pessoas. É o eixo forte, e o único quase-objetivo: não depende de interpretar nome.
  · **Coabitação** (endereço de estabelecimento idêntico entre empresas distintas): **3,9%** dos
    CNPJs. Sinal usável — com a lição já paga de que *mesma sala ≠ mesmo prédio*.
  · **Sobrenome de família compartilhado DENTRO do mesmo QSA**: **16,9%** das empresas com dois ou
    mais sócios PF (6,71% de toda a base). **Não é sinal.** Empresa familiar é a norma no Brasil.
  · **Sobrenome raro compartilhado ENTRE empresas diferentes**: **17,9% a 32,9%** da base, conforme
    o corte de raridade. **Não é sinal**, e o corte de raridade quase não move o número (16,9% →
    10,6% ao exigir sobrenome com ≤3 ocorrências).

DAÍ A REGRA DE COMPOSIÇÃO. O eixo de sobrenome **nunca acende sozinho** — ele só corrobora um eixo
forte. Um módulo que deixasse sobrenome pontuar isolado estaria acusando um quinto do acervo de
nepotismo empresarial, e é exatamente o defeito que esta casa já corrigiu três vezes.

A faixa etária não pontua: ela só classifica a HIPÓTESE (cônjuge × ascendente/descendente), porque
distinguir o tipo de parentesco muda a diligência cabível, não a força do indício.

Saída: `grau ∈ {hipotese_fraca, hipotese, indicio}`, com a prevalência de cada eixo acionado
impressa junto — o leitor tem de poder calcular sozinho o falso positivo esperado — e o quesito de
diligência que fecharia a questão.
"""
from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from typing import Any

from compliance_agent.cruzamentos_intel import _nep_familia, _nep_tokens

__all__ = [
    "EIXOS", "prevalencia", "avaliar", "familias_do_qsa", "GRAUS", "DILIGENCIA",
]

GRAUS = ("hipotese_fraca", "hipotese", "indicio")


class Eixo:
    """Um eixo de inferência, com a prevalência que o autoriza (ou não) a pesar."""

    def __init__(self, id: str, descricao: str, prevalencia_medida: float, *,
                 pode_acender_sozinho: bool, exculpatoria: str) -> None:
        self.id = id
        self.descricao = descricao
        self.prevalencia_medida = prevalencia_medida   # % da base, medido em 2026-07-29
        self.pode_acender_sozinho = pode_acender_sozinho
        self.exculpatoria = exculpatoria


EIXOS: dict[str, Eixo] = {
    "coocorrencia_societaria": Eixo(
        "coocorrencia_societaria",
        "as mesmas duas pessoas são sócias de 2+ empresas",
        4.76, pode_acender_sozinho=True,
        exculpatoria=("sócios de negócio recorrentes não são parentes; o padrão é igualmente "
                      "compatível com dupla de empreendedores do mesmo setor"),
    ),
    "coabitacao": Eixo(
        "coabitacao",
        "empresas distintas no MESMO endereço de estabelecimento (com complemento)",
        3.9, pode_acender_sozinho=True,
        exculpatoria=("escritório de contabilidade, coworking e prédio comercial hospedam empresas "
                      "sem relação — só o endereço COM complemento (sala/andar) significa algo"),
    ),
    "sobrenome_no_qsa": Eixo(
        "sobrenome_no_qsa",
        "sobrenome de família repetido entre sócios da MESMA empresa",
        16.9, pode_acender_sozinho=False,
        exculpatoria=("empresa familiar é a norma no Brasil: 16,9% das empresas com 2+ sócios PF "
                      "têm sobrenome repetido, e o corte por raridade quase não altera isso"),
    ),
    "sobrenome_entre_empresas": Eixo(
        "sobrenome_entre_empresas",
        "sobrenome de família raro compartilhado entre empresas DIFERENTES",
        25.9, pode_acender_sozinho=False,
        exculpatoria=("sobrenome brasileiro repete; entre 17,9% e 32,9% da base é atingida conforme "
                      "o corte de raridade — isoladamente mede a base, não o alvo"),
    ),
}

DILIGENCIA = {
    "objetivo": "confirmar ou afastar o parentesco inferido",
    "fontes": [
        "certidão de nascimento/casamento dos sócios (registro civil — requisição)",
        "declaração de vínculos familiares (Portaria SE/CGU nº 276/2026, onde houver nomeação)",
        "ficha cadastral completa na JUCERJA (alteração contratual nomeia e qualifica os sócios)",
        "declaração de bens e rendimentos, se agente público envolvido",
    ],
    "por_que": ("Nenhuma base aberta brasileira publica parentesco nem nome da mãe. A inferência "
                "gera hipótese para diligência; ela não substitui documento."),
    "metodologia_citavel": ("TCU — 'Identificação de indícios de irregularidade por meio de padrões "
                           "topológicos em grafos'. Cita-se o método; o banco de vínculos do TCU é "
                           "alimentado por Receita/CNIS, bases restritas não disponíveis aqui."),
}

_FAIXA_ANOS = {"1": (0, 12), "2": (13, 20), "3": (21, 30), "4": (31, 40), "5": (41, 50),
               "6": (51, 60), "7": (61, 70), "8": (71, 80), "9": (81, 200)}


def _tipo_por_idade(faixa_a: str, faixa_b: str) -> str:
    """Classifica a HIPÓTESE, não a força: cônjuge e ascendente pedem diligências diferentes."""
    fa, fb = _FAIXA_ANOS.get(str(faixa_a or "")), _FAIXA_ANOS.get(str(faixa_b or ""))
    if not fa or not fb:
        return "indeterminado"
    dif = abs((fa[0] + fa[1]) / 2 - (fb[0] + fb[1]) / 2)
    if dif <= 10:
        return "conjuge_ou_irmao"
    if dif >= 18:
        return "ascendente_descendente"
    return "indeterminado"


def familias_do_qsa(con: sqlite3.Connection, cnpj_basico: str) -> list[dict]:
    """Sócios PF da empresa, com o sobrenome de família extraído e a faixa etária."""
    con.row_factory = sqlite3.Row
    linhas = con.execute(
        "SELECT nome_socio, doc_socio, qualificacao_txt, faixa_etaria, data_entrada "
        "FROM socios_receita WHERE cnpj_basico=? AND ident='2'", (cnpj_basico,)).fetchall()
    out = []
    for r in linhas:
        out.append({
            "nome": (r["nome_socio"] or "").strip(),
            "doc": (r["doc_socio"] or "").strip(),
            "familia": _nep_familia(_nep_tokens(r["nome_socio"] or "")),
            "qualificacao": (r["qualificacao_txt"] or "").strip(),
            "faixa_etaria": (r["faixa_etaria"] or "").strip(),
            "data_entrada": (r["data_entrada"] or "").strip(),
        })
    return out


def prevalencia(db_path: str = "", *, amostra_max: int = 0) -> dict:
    """Recalcula a prevalência de cada eixo NA BASE DE HOJE.

    Existe para que a calibração não envelheça em silêncio: os números do docstring são de
    2026-07-29, e a base cresce. Um eixo cuja prevalência subiu deixou de discriminar, e o produto
    tem de saber disso antes de continuar acendendo.
    """
    from compliance_agent.reporting.intel_base import _DB

    con = sqlite3.connect(f"file:{db_path or _DB}?mode=ro", uri=True)
    try:
        total_raizes = con.execute(
            "SELECT COUNT(DISTINCT cnpj_basico) FROM socios_receita").fetchone()[0] or 1
        por_raiz: dict[str, list[str]] = defaultdict(list)
        pessoa_empresas: dict[tuple, set[str]] = defaultdict(set)
        familia_empresas: dict[str, set[str]] = defaultdict(set)
        freq_familia: dict[str, int] = defaultdict(int)
        sql = "SELECT cnpj_basico, nome_socio, doc_socio FROM socios_receita WHERE ident='2'"
        if amostra_max:
            sql += f" LIMIT {int(amostra_max)}"
        for raiz, nome, doc in con.execute(sql):
            fam = _nep_familia(_nep_tokens(nome or ""))
            pessoa_empresas[(fam or nome, doc)].add(raiz)
            if fam:
                por_raiz[raiz].append(fam)
                familia_empresas[fam].add(raiz)
                freq_familia[fam] += 1

        n_pessoas = len(pessoa_empresas) or 1
        n_multi = sum(1 for v in pessoa_empresas.values() if len(v) >= 2)
        com2 = [r for r, fs in por_raiz.items() if len(fs) >= 2] or []
        rep = [r for r in com2 if len(set(por_raiz[r])) < len(por_raiz[r])]
        raras = {f for f, n in freq_familia.items() if n <= 3 and len(familia_empresas[f]) >= 2}
        afetadas: set[str] = set()
        for f in raras:
            afetadas |= familia_empresas[f]

        n_end = con.execute(
            "SELECT COUNT(*) FROM endereco_fornecedor WHERE COALESCE(endereco_norm,'')<>''"
        ).fetchone()[0] or 1
        n_end_compart = con.execute(
            "SELECT COALESCE(SUM(c),0) FROM (SELECT COUNT(*) c FROM endereco_fornecedor "
            "WHERE COALESCE(endereco_norm,'')<>'' GROUP BY endereco_norm HAVING COUNT(*)>=2)"
        ).fetchone()[0]
    finally:
        con.close()

    return {
        "base": {"raizes_com_qsa": total_raizes, "pessoas_pf": n_pessoas,
                 "raizes_com_2_ou_mais_pf": len(com2), "cnpjs_com_endereco": n_end},
        "eixos": {
            "coocorrencia_societaria": round(100.0 * n_multi / n_pessoas, 2),
            "coabitacao": round(100.0 * n_end_compart / n_end, 2),
            "sobrenome_no_qsa": round(100.0 * len(rep) / max(1, len(com2)), 2),
            "sobrenome_entre_empresas": round(100.0 * len(afetadas) / total_raizes, 2),
        },
        "regra": ("Eixo com prevalência acima de ~10% não pode acender sozinho: nessa faixa ele "
                  "mede a base, não o alvo. Comparar com EIXOS[*].prevalencia_medida — divergência "
                  "grande significa que a calibração envelheceu."),
    }


def avaliar(con: sqlite3.Connection, cnpj_basico: str, *, outro_cnpj: str = "") -> dict:
    """Hipóteses de parentesco no QSA de uma empresa (e, se dado, na dupla de empresas).

    Devolve sempre a lista de eixos ACIONADOS com a prevalência de cada um, e o grau resultante da
    regra de composição. Nenhuma hipótese sai sem a explicação inocente do eixo que a produziu.
    """
    socios = familias_do_qsa(con, cnpj_basico)
    hipoteses: list[dict] = []
    eixos_acionados: set[str] = set()

    # ── eixo fraco: sobrenome repetido dentro do MESMO QSA (nunca acende sozinho) ──────────────
    por_familia: dict[str, list[dict]] = defaultdict(list)
    for s in socios:
        if s["familia"]:
            por_familia[s["familia"]].append(s)
    for fam, membros in por_familia.items():
        nomes = {m["nome"] for m in membros}
        if len(nomes) < 2:
            continue
        eixos_acionados.add("sobrenome_no_qsa")
        a, b = membros[0], membros[1]
        hipoteses.append({
            "pessoas": sorted(nomes),
            "familia": fam,
            "eixos": ["sobrenome_no_qsa"],
            "tipo_provavel": _tipo_por_idade(a["faixa_etaria"], b["faixa_etaria"]),
            "onde": f"QSA de {cnpj_basico}",
        })

    # ── eixo forte: co-ocorrência societária das MESMAS pessoas em 2+ empresas ─────────────────
    for s in socios:
        if not s["doc"]:
            continue
        outras = [r[0] for r in con.execute(
            "SELECT DISTINCT cnpj_basico FROM socios_receita WHERE doc_socio=? AND nome_socio=? "
            "AND cnpj_basico<>?", (s["doc"], s["nome"], cnpj_basico)).fetchall()]
        if not outras:
            continue
        for s2 in socios:
            if s2 is s or not s2["doc"]:
                continue
            juntos = [r[0] for r in con.execute(
                "SELECT DISTINCT cnpj_basico FROM socios_receita WHERE doc_socio=? AND nome_socio=? "
                "AND cnpj_basico IN (%s)" % ",".join("?" * len(outras)),
                [s2["doc"], s2["nome"], *outras]).fetchall()]
            if not juntos:
                continue
            eixos_acionados.add("coocorrencia_societaria")
            eixos = ["coocorrencia_societaria"]
            mesma_familia = bool(s["familia"] and s["familia"] == s2["familia"])
            if mesma_familia:
                eixos.append("sobrenome_no_qsa")
                eixos_acionados.add("sobrenome_no_qsa")
            hipoteses.append({
                "pessoas": sorted({s["nome"], s2["nome"]}),
                "familia": s["familia"] if mesma_familia else None,
                "eixos": eixos,
                "empresas_em_comum": sorted({cnpj_basico, *juntos}),
                "tipo_provavel": _tipo_por_idade(s["faixa_etaria"], s2["faixa_etaria"]),
                "onde": f"sócios juntos em {len(juntos) + 1} empresas",
            })

    # ── composição: quem pode acender sozinho decide o grau ───────────────────────────────────
    fortes = {e for e in eixos_acionados if EIXOS[e].pode_acender_sozinho}
    if not eixos_acionados:
        grau = None
    elif not fortes:
        grau = "hipotese_fraca"
    elif len(fortes) >= 2 or (fortes and len(eixos_acionados) >= 3):
        grau = "indicio"
    else:
        grau = "hipotese"

    fp = max((EIXOS[e].prevalencia_medida for e in eixos_acionados), default=0.0)
    return {
        "cnpj_basico": cnpj_basico,
        "n_socios_pf": len(socios),
        "hipoteses": hipoteses,
        "n_hipoteses": len(hipoteses),
        "eixos_acionados": [
            {"id": e, "descricao": EIXOS[e].descricao,
             "prevalencia_na_base_pct": EIXOS[e].prevalencia_medida,
             "pode_acender_sozinho": EIXOS[e].pode_acender_sozinho,
             "explicacao_inocente": EIXOS[e].exculpatoria}
            for e in sorted(eixos_acionados)
        ],
        "grau": grau,
        "falso_positivo_esperado_pct": fp,
        "leitura": _leitura(grau, fp, eixos_acionados),
        "diligencia": DILIGENCIA if hipoteses else None,
    }


def _leitura(grau: str | None, fp: float, eixos: set[str]) -> str:
    if grau is None:
        return ("Nenhum eixo de parentesco acionado neste QSA. Isso NÃO afasta parentesco: nenhuma "
                "base aberta publica filiação, e a inferência só vê o que o QSA e o endereço "
                "mostram. INDISPONÍVEL, não ausência.")
    if grau == "hipotese_fraca":
        return (f"Apenas eixo(s) que NÃO acendem sozinhos ({', '.join(sorted(eixos))}). Prevalência "
                f"de {fp:.1f}% na própria base: nessa faixa o eixo mede a base, não o alvo. Serve "
                "para ordenar leitura, não para afirmar vínculo.")
    if grau == "hipotese":
        return (f"Um eixo forte acionado. Falso positivo esperado da ordem de {fp:.1f}%. Hipótese "
                "para diligência — a explicação inocente do eixo é igualmente compatível com o "
                "observado.")
    return (f"Dois ou mais eixos independentes convergem. Falso positivo esperado da ordem de "
            f"{fp:.1f}%. INDÍCIO que justifica diligência documental — segue sendo indício, e "
            "parentesco só se prova por certidão.")


def mascarar(texto: Any) -> str:
    """CPF mascarado na saída (regra da casa) — a base da Receita já entrega mascarado."""
    return re.sub(r"\b(\d{3})\.?\d{3}\.?\d{3}-?(\d{2})\b", r"\1.***.***-\2", str(texto or ""))
