# -*- coding: utf-8 -*-
"""Regime jurídico POR CONTRATO (plano mestre v2, §4.1 — O4.4). ⚖️ SOMBRA: nenhum detector lê isto ainda.

O regime de uma despesa é o da CONTRATAÇÃO que a originou, nunca o ano corrente nem o ano da OB
(doutrina da casa, `~/vault/notas/doutrina/01-transicao-8666-10520-12462.md`, "Regra de ouro").

Saída: `DecisaoRegime(regime, fonte_da_decisao, lei_especifica, ressalvas)`, com `regime` ∈ `Regime`.

FONTES — conferidas VERBATIM nas cópias com md5 de `~/vault/fontes/juridicas/` (INDICE.md), 24/11/2026:

  L14133.htm (md5 5107e213168afb4c15a36665e6695c58)
    art. 1º §1º  "Não são abrangidas por esta Lei as empresas públicas, as sociedades de economia mista e as suas
                 subsidiárias, regidas pela Lei nº 13.303, de 30 de junho de 2016, ressalvado o disposto no art. 178"
    art. 190     "O contrato cujo instrumento tenha sido assinado antes da entrada em vigor desta Lei continuará a ser
                 regido de acordo com as regras previstas na legislação revogada."
    art. 191     (texto vigente — a redação da MP 1.167/2023 está marcada "Vigência encerrada")
                 "Até o decurso do prazo de que trata o inciso II do caput do art. 193, a Administração poderá optar
                 por licitar ou contratar diretamente de acordo com esta Lei ou de acordo com as leis citadas no
                 referido inciso, e a opção escolhida deverá ser indicada expressamente no edital ou no aviso ou
                 instrumento de contratação direta, vedada a aplicação combinada [...]"
                 par. único: "[...] o contrato respectivo será regido pelas regras nelas previstas durante toda a sua
                 vigência."
    art. 191, I  (MP 1.167/2023, "Vigência encerrada"): "a publicação do edital ou do ato autorizativo da contratação
                 direta ocorra até 29 de dezembro de 2023"
    art. 193, II (red. LC 198/2023): "em 30 de dezembro de 2023: a) a Lei nº 8.666 [...]; b) a Lei nº 10.520 [...];
                 c) os arts. 1º a 47-A da Lei nº 12.462"
    art. 194     "Esta Lei entra em vigor na data de sua publicação." — "publicado no DOU de 1º.4.2021"
  LCP198.htm (md5 012075cb69ebd5d2f62f1843eb9aa2c6), art. 3º: dá ao art. 193, II, a redação "em 30 de dezembro de 2023".
  L13303.htm (md5 326f5390c34ff235a3aeafa9529d98de)
    art. 91      "[...] constituídas anteriormente à vigência desta Lei deverão, no prazo de 24 (vinte e quatro) meses,
                 promover as adaptações [...]"; §3º "Permanecem regidos pela legislação anterior procedimentos
                 licitatórios e contratos iniciados ou celebrados até o final do prazo previsto no caput."
    art. 97      "Esta Lei entra em vigor na data de sua publicação." — "publicado no DOU de 1º.7.2016"
  L14065.htm (md5 e5692eb8a4efa2c2bfae7c5c456632d1)
    art. 1º, I   dispensa dos incisos I e II do art. 24 da 8.666 até R$ 100.000,00 / R$ 50.000,00
    art. 2º      "aplica-se aos atos realizados durante o estado de calamidade pública reconhecido pelo Decreto
                 Legislativo nº 6, de 20 de março de 2020." par. único: "aplica-se aos contratos firmados no período
                 [...] independentemente do seu prazo ou do prazo de suas prorrogações."
  L13979.htm (md5 292ba884095f5df98bd626be465c679b), art. 4º "É dispensável a licitação para aquisição ou contratação
                 de bens, serviços, inclusive de engenharia, e insumos destinados ao enfrentamento da emergência [...]"
  L10520.htm, art. 9º "Aplicam-se subsidiariamente, para a modalidade de pregão, as normas da Lei nº 8.666" — por isso
                 o pregão da 10.520 cai na família L8666 (com `lei_especifica='10520'`).

O MARCO 29 × 30/12/2023 (pedido do plano, §4.1): o texto vigente do art. 191 remete ao "decurso do prazo" do art. 193,
II, que revoga as leis antigas "em 30 de dezembro de 2023" (LC 198). A data-limite expressa "até 29 de dezembro de
2023" é da MP 1.167, cuja vigência está ENCERRADA. Logo: edital/ato até 29/12/2023 → opção válida em qualquer leitura;
edital/ato EM 30/12/2023 → as duas leituras divergem → INDETERMINADO (declarado, nunca escolhido em silêncio);
depois de 30/12/2023 → só a 14.133. (`pericia_contabil._FIM_TRANSICAO = 30/12/2023` usa a leitura da LC 198.)

FALTAM NA BASE (→ INDETERMINADO ou ressalva, nunca de memória): texto da MP 1.167/2023 e da MP 961/2020; Decreto
Legislativo 6/2020 (fim da calamidade); tabela CONCLA de natureza jurídica (quem é estatal vem do adaptador).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class Regime(str, Enum):
    L8666 = "L8666"                      # 8.666/1993 (inclui pregão 10.520, art. 9º)
    L14133 = "L14133"
    L13303 = "L13303"                    # estatais
    L14065_PANDEMIA = "L14065_PANDEMIA"  # dispensa por valor da 8.666 com tetos da 14.065 (calamidade 2020)
    L13979_COVID = "L13979_COVID"        # dispensa covid sem teto (art. 4º)
    OUTRO = "OUTRO"                      # RDC (12.462), 14.124, 14.217, leis próprias — ver `lei_especifica`
    INDETERMINADO = "INDETERMINADO"


@dataclass(frozen=True)
class DecisaoRegime:
    regime: Regime
    fonte_da_decisao: str
    lei_especifica: str = ""
    ressalvas: tuple[str, ...] = field(default_factory=tuple)


# ── marcos (cada um com a fonte verbatim no docstring do módulo) ─────────────────────────────────────────────
VIGENCIA_14133 = date(2021, 4, 1)        # art. 194 + "publicado no DOU de 1º.4.2021"
ULTIMO_DIA_OPCAO_SEGURO = date(2023, 12, 29)   # MP 1.167 (encerrada) e LC 198 concordam até aqui
REVOGACAO_8666 = date(2023, 12, 30)      # art. 193, II (red. LC 198/2023): "em 30 de dezembro de 2023"
VIGENCIA_13303 = date(2016, 7, 1)        # art. 97 + "publicado no DOU de 1º.7.2016"
FIM_ADAPTACAO_13303 = date(2018, 7, 1)   # art. 91: 24 meses da vigência; §3º: até o fim do prazo → legislação anterior
INICIO_CALAMIDADE_2020 = date(2020, 3, 20)   # 14.065 art. 2º: "Decreto Legislativo nº 6, de 20 de março de 2020"
FIM_EXERCICIO_2020 = date(2020, 12, 31)      # o fim da calamidade (DL 6) NÃO está na base → ressalva

_RESSALVA_FIM_CALAMIDADE = ("fim da calamidade do DL 6/2020 não conferido na base (texto do DL ausente); "
                            "aplicado só até o fim do exercício de 2020")

# Lei declarada no fundamento/modalidade/enquadramento. Ordem importa: 14.065 antes de 8.666 (cita a 8.666).
_LEIS = (
    ("14065", re.compile(r"14[.\s]?065")),
    ("13979", re.compile(r"13[.\s]?979")),
    ("14124", re.compile(r"14[.\s]?124")),
    ("14217", re.compile(r"14[.\s]?217")),
    ("12462", re.compile(r"12[.\s]?462|\bRDC\b", re.I)),
    ("13303", re.compile(r"13[.\s]?303")),
    ("14133", re.compile(r"14[.\s]?133")),
    ("10520", re.compile(r"10[.\s]?520")),
    ("8666", re.compile(r"(?<![\d.])8[.\s]?666(?![\d])")),
)


def lei_declarada(texto: str | None) -> tuple[str, ...]:
    """Leis citadas num texto de fundamento ('Lei n 14.133/2021, Art. 75, II', 'Pregão Eletrônico - Lei 8.666'…)."""
    t = str(texto or "")
    return tuple(cod for cod, rx in _LEIS if rx.search(t))


def _decide_declarada(leis: tuple[str, ...], d_edital: date | None, d_assin: date | None,
                      dispensa_valor: bool | None) -> DecisaoRegime | None:
    base = [x for x in leis if x != "14065"]   # 14.065 sempre cita a 8.666; trata-se à parte
    if "14065" in leis:
        return DecisaoRegime(Regime.L14065_PANDEMIA, "Lei 14.065/2020 declarada (art. 1º, I; art. 2º)", "14065",
                             (_RESSALVA_FIM_CALAMIDADE,))
    fam = {"8666": "antiga", "10520": "antiga", "14133": "14133", "13303": "13303", "13979": "13979",
           "14124": "14124", "14217": "14217", "12462": "12462"}
    familias = {fam[x] for x in base}
    if len(familias) > 1:
        return DecisaoRegime(Regime.INDETERMINADO, f"fundamento cita leis de regimes distintos ({', '.join(base)}); "
                             "14.133 art. 191 veda a aplicação combinada — ler o instrumento")
    f = familias.pop()
    if f == "13303":
        return DecisaoRegime(Regime.L13303, "Lei 13.303/2016 declarada no fundamento", "13303")
    if f == "13979":
        return DecisaoRegime(Regime.L13979_COVID, "Lei 13.979/2020 declarada (art. 4º: dispensa sem teto)", "13979")
    if f in ("14124", "14217", "12462"):
        return DecisaoRegime(Regime.OUTRO, f"Lei {f} declarada (regime próprio)", f)
    if f == "14133":
        if d_edital and d_edital < VIGENCIA_14133 or (not d_edital and d_assin and d_assin < VIGENCIA_14133):
            return DecisaoRegime(Regime.INDETERMINADO, "14.133 declarada em ato anterior à vigência dela "
                                 "(art. 194: 01/04/2021) — dado contraditório", "14133")
        return DecisaoRegime(Regime.L14133, "Lei 14.133/2021 declarada no fundamento", "14133")
    # família antiga (8.666 / 10.520)
    esp = "10520" if base == ["10520"] else "8666"
    if d_edital and d_edital > REVOGACAO_8666:
        return DecisaoRegime(Regime.INDETERMINADO, "lei antiga declarada com edital/ato posterior à revogação "
                             "(14.133 art. 193, II: 30/12/2023) — dado contraditório", esp)
    if d_edital == REVOGACAO_8666:
        return DecisaoRegime(Regime.INDETERMINADO, "edital/ato em 30/12/2023: o texto vigente do art. 191 remete ao "
                             "art. 193, II ('em 30 de dezembro'), a MP 1.167 (encerrada) dizia 'até 29 de dezembro' — "
                             "marco ambíguo, não decidido em silêncio", esp)
    d_ato = d_edital or d_assin
    if dispensa_valor and d_ato and INICIO_CALAMIDADE_2020 <= d_ato <= FIM_EXERCICIO_2020:
        return DecisaoRegime(Regime.L14065_PANDEMIA, "dispensa por valor da 8.666 em ato de 2020 na calamidade "
                             "(Lei 14.065/2020, arts. 1º, I, e 2º)", "14065", (_RESSALVA_FIM_CALAMIDADE,))
    ress = []
    if not d_edital:
        ress.append("data do edital/ato ausente: a opção do art. 191 (prazo do art. 193, II) não foi conferida")
    fonte = ("lei antiga declarada no instrumento; 14.133 arts. 190/191 par. único (regida pela lei antiga durante "
             "toda a vigência)" + ("; pregão: 10.520 art. 9º (8.666 subsidiária)" if esp == "10520" else ""))
    return DecisaoRegime(Regime.L8666, fonte, esp, tuple(ress))


def regime_contrato(*, contratante_estatal: bool | None = None, lei_declarada_texto: str | None = None,
                    data_edital: date | None = None, data_assinatura: date | None = None,
                    dispensa_por_valor: bool | None = None) -> DecisaoRegime:
    """Regime de UM contrato/contratação. Função pura.

    contratante_estatal  True = empresa pública/SEM/subsidiária (dado do adaptador: natureza jurídica ou declaração
                         13.303 da própria unidade); None = não se sabe (nunca lido como False).
    lei_declarada_texto  fundamento legal / modalidade / enquadramento como veio da fonte.
    data_edital          publicação do edital ou do ato autorizativo da contratação direta (o que o art. 191 mede).
    data_assinatura      assinatura do instrumento (o que o art. 190 mede).
    dispensa_por_valor   True se a contratação é dispensa por valor (8.666 art. 24 I/II) — só muda 2020 (14.065).

    Ordem: (1) estatal; (2) lei declarada; (3) datas; (4) INDETERMINADO. Nunca pelo ano corrente."""
    d_ato = data_edital or data_assinatura
    leis = lei_declarada(lei_declarada_texto)

    # 1. estatal — 14.133 art. 1º §1º; 13.303 arts. 91 §3º e 97
    if contratante_estatal:
        if d_ato and d_ato < VIGENCIA_13303:
            return DecisaoRegime(Regime.L8666, "estatal com ato anterior à vigência da 13.303 (01/07/2016): "
                                 "legislação anterior (8.666, art. 24 §1º para os tetos)", "8666")
        if d_ato and d_ato < FIM_ADAPTACAO_13303 and "13303" not in leis:
            return DecisaoRegime(Regime.INDETERMINADO, "estatal no prazo de adaptação de 24 meses (13.303 art. 91; "
                                 "§3º mantém a legislação anterior até o fim do prazo) sem lei declarada", "13303")
        if not d_ato and "13303" not in leis:
            # D3 (decisão delegada 24/11/2026): sem data não se afirma a 13.303 — o art. 91 §3º mantém na lei
            # anterior o contrato celebrado até 30/06/2018, e contrato contínuo da 8.666 vai até 60 meses + 12.
            # A 14.133 fica fora em qualquer caso (art. 1º §1º); a 13.303 é só a hipótese provável.
            return DecisaoRegime(Regime.INDETERMINADO, "estatal sem data do ato: 13.303 provável, mas o art. 91 §3º "
                                 "mantém na legislação anterior o contrato celebrado até 30/06/2018", "13303",
                                 ("14.133 excluída (art. 1º §1º); 13.303 provável",))
        return DecisaoRegime(Regime.L13303, "contratante estatal: Lei 13.303/2016 (14.133 art. 1º §1º exclui as "
                             "estatais), em qualquer exercício", "13303")

    # 2. lei declarada no instrumento
    if leis:
        dec = _decide_declarada(leis, data_edital, data_assinatura, dispensa_por_valor)
        if dec is not None:
            return dec

    # 3. sem lei declarada: só as datas que a lei torna decisivas
    if data_assinatura and data_assinatura < VIGENCIA_14133:
        if dispensa_por_valor and INICIO_CALAMIDADE_2020 <= data_assinatura <= FIM_EXERCICIO_2020:
            return DecisaoRegime(Regime.L14065_PANDEMIA, "dispensa por valor assinada em 2020 na calamidade "
                                 "(14.065 arts. 1º, I, e 2º)", "14065", (_RESSALVA_FIM_CALAMIDADE,))
        return DecisaoRegime(Regime.L8666, "instrumento assinado antes de 01/04/2021: 14.133 art. 190", "8666")
    if data_edital and data_edital < VIGENCIA_14133:
        return DecisaoRegime(Regime.L8666, "edital/ato anterior à vigência da 14.133 (art. 194, 01/04/2021): só podia "
                             "seguir a lei antiga; contrato regido por ela (art. 191 par. único)", "8666")
    if data_edital and data_edital > REVOGACAO_8666:
        return DecisaoRegime(Regime.L14133, "edital/ato posterior a 30/12/2023: leis antigas revogadas "
                             "(14.133 art. 193, II, red. LC 198/2023)", "14133")
    if data_edital or data_assinatura:
        return DecisaoRegime(Regime.INDETERMINADO, "ato no período de opção (01/04/2021 a 30/12/2023, 14.133 art. 191) "
                             "ou edital desconhecido, sem a lei escolhida declarada")
    return DecisaoRegime(Regime.INDETERMINADO, "sem lei declarada e sem data do edital/assinatura")
