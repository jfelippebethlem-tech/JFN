# -*- coding: utf-8 -*-
"""O4.4 — `dominio.regime.regime_contrato`: regime POR CONTRATO, tabela-ouro com a fonte de cada caso.

Fontes conferidas VERBATIM nas cópias com md5 de ~/vault/fontes/juridicas/ (ver docstring de `dominio/regime.py`):
L14133.htm arts. 1º §1º, 190, 191, 193 II (red. LC 198/2023), 194; LCP198.htm art. 3º; L13303.htm arts. 91 §3º e 97;
L14065.htm arts. 1º I e 2º; L13979.htm art. 4º; L10520.htm art. 9º.
"""
from __future__ import annotations

from datetime import date

import pytest

from compliance_agent.dominio.regime import Regime, lei_declarada, regime_contrato

R = Regime
D = date

# (id, kwargs, regime esperado, fonte do caso)
OURO = [
    # ── estatal → 13.303 em qualquer exercício (14.133 art. 1º §1º) ────────────────────────────────────────────
    ("estatal_2025", dict(contratante_estatal=True, data_assinatura=D(2025, 3, 1)), R.L13303,
     "14.133 art. 1º §1º: 'Não são abrangidas por esta Lei as empresas públicas, as sociedades de economia mista'"),
    ("estatal_2022_mesmo_citando_14133", dict(contratante_estatal=True, lei_declarada_texto="Lei 14.133/2021",
                                              data_assinatura=D(2022, 5, 2)), R.L13303,
     "14.133 art. 1º §1º prevalece sobre a citação equivocada"),
    ("estatal_sem_data", dict(contratante_estatal=True), R.L13303, "14.133 art. 1º §1º (ressalva: data ausente)"),
    ("estatal_2015", dict(contratante_estatal=True, data_edital=D(2015, 6, 1)), R.L8666,
     "13.303 art. 97 (vigência na publicação, DOU 1º.7.2016): antes disso a 8.666"),
    ("estatal_adaptacao_sem_lei", dict(contratante_estatal=True, data_edital=D(2017, 8, 1)), R.INDETERMINADO,
     "13.303 art. 91 §3º: 'Permanecem regidos pela legislação anterior [...] até o final do prazo'"),
    ("estatal_adaptacao_declarou_13303", dict(contratante_estatal=True, lei_declarada_texto="Lei 13.303/2016, Art. 29, II",
                                              data_edital=D(2017, 8, 1)), R.L13303, "13.303 declarada no prazo do art. 91"),
    # ── lei declarada ──────────────────────────────────────────────────────────────────────────────────────────
    ("declarou_13303", dict(lei_declarada_texto="Lei 13.303/2016, Art. 29, II"), R.L13303, "13.303 art. 29"),
    ("declarou_14133", dict(lei_declarada_texto="Lei nº 14.133/2021, Art. 75º, II", data_edital=D(2024, 2, 1)),
     R.L14133, "14.133 declarada"),
    ("declarou_14133_antes_da_lei", dict(lei_declarada_texto="Lei 14.133/2021", data_edital=D(2020, 2, 1)),
     R.INDETERMINADO, "14.133 art. 194: vigência em 01/04/2021 — dado contraditório"),
    ("declarou_8666_em_2023", dict(lei_declarada_texto="Pregão Eletrônico - Lei 8.666", data_edital=D(2023, 11, 10)),
     R.L8666, "14.133 art. 191 + par. único: opção pela lei antiga dentro do prazo, regida 'durante toda a sua vigência'"),
    ("declarou_8666_edital_29_12_2023", dict(lei_declarada_texto="Lei 8.666/93", data_edital=D(2023, 12, 29)),
     R.L8666, "MP 1.167 (encerrada) 'até 29 de dezembro de 2023' e LC 198 'em 30 de dezembro' concordam"),
    ("declarou_8666_edital_30_12_2023", dict(lei_declarada_texto="Lei 8.666/93", data_edital=D(2023, 12, 30)),
     R.INDETERMINADO, "marco ambíguo: LC 198 revoga 'em 30 de dezembro'; MP 1.167 dizia 'até 29 de dezembro'"),
    ("declarou_8666_edital_2024", dict(lei_declarada_texto="Lei 8.666/93", data_edital=D(2024, 1, 15)),
     R.INDETERMINADO, "14.133 art. 193, II (red. LC 198): 8.666 revogada em 30/12/2023"),
    ("declarou_8666_assinado_2024_sem_edital", dict(lei_declarada_texto="Lei 8.666/93", data_assinatura=D(2024, 3, 4)),
     R.L8666, "art. 191 par. único: contrato de edital da lei antiga segue nela; ressalva: edital não conferido"),
    ("pregao_10520", dict(lei_declarada_texto="Lei 10.520/2002", data_edital=D(2019, 4, 1)), R.L8666,
     "10.520 art. 9º: 'Aplicam-se subsidiariamente, para a modalidade de pregão, as normas da Lei nº 8.666'"),
    ("covid_13979", dict(lei_declarada_texto="Lei 13.979/2020, art. 4º", data_edital=D(2020, 4, 10)), R.L13979_COVID,
     "13.979 art. 4º: 'É dispensável a licitação [...] enfrentamento da emergência'"),
    ("declarou_14065", dict(lei_declarada_texto="Lei 14.065/2020 c/c Lei 8.666/93"), R.L14065_PANDEMIA,
     "14.065 art. 1º, I"),
    ("dispensa_valor_8666_em_2020", dict(lei_declarada_texto="Inciso II do Artigo 24 da Lei 8.666",
                                         data_edital=D(2020, 8, 3), dispensa_por_valor=True), R.L14065_PANDEMIA,
     "14.065 art. 2º: 'atos realizados durante o estado de calamidade [...] Decreto Legislativo nº 6, de 20 de março'"),
    ("dispensa_valor_8666_antes_da_calamidade", dict(lei_declarada_texto="Lei 8.666 art. 24 II",
                                                     data_edital=D(2020, 3, 19), dispensa_por_valor=True), R.L8666,
     "14.065 art. 2º: o DL 6 é de 20/03/2020"),
    ("rdc", dict(lei_declarada_texto="RDC - Lei 12.462/2011"), R.OUTRO, "12.462 (regime próprio)"),
    ("lei_14217", dict(lei_declarada_texto="Lei 14.217/2021, art. 2º"), R.OUTRO, "14.217 (regime covid próprio)"),
    ("mistura_vedada", dict(lei_declarada_texto="Lei 8.666/93 e Lei 14.133/21"), R.INDETERMINADO,
     "14.133 art. 191: 'vedada a aplicação combinada'"),
    # ── sem lei declarada: só as datas decisivas ─────────────────────────────────────────────────────────────────
    ("assinado_2019", dict(data_assinatura=D(2019, 5, 1)), R.L8666,
     "14.133 art. 190: 'assinado antes da entrada em vigor desta Lei continuará a ser regido [...] legislação revogada'"),
    ("assinado_31_03_2021", dict(data_assinatura=D(2021, 3, 31)), R.L8666, "art. 190 + art. 194 (DOU 1º.4.2021)"),
    ("edital_2020_assinado_2022", dict(data_edital=D(2020, 11, 1), data_assinatura=D(2022, 1, 5)), R.L8666,
     "edital anterior à 14.133 (art. 194) só podia seguir a lei antiga"),
    ("edital_2024", dict(data_edital=D(2024, 6, 1)), R.L14133, "art. 193, II (red. LC 198): leis antigas revogadas"),
    ("edital_2022_sem_lei", dict(data_edital=D(2022, 6, 1)), R.INDETERMINADO, "art. 191: período de opção"),
    ("assinado_2025_sem_edital", dict(data_assinatura=D(2025, 6, 1)), R.INDETERMINADO,
     "art. 191 par. único: contrato de 2025 pode vir de edital 8.666 de 2023"),
    ("sem_nada", dict(), R.INDETERMINADO, "sem dado → INDETERMINADO (plano §4.1)"),
    ("estatal_desconhecida_nao_e_falso", dict(contratante_estatal=None, data_edital=D(2024, 6, 1)), R.L14133,
     "None ≠ False: sem saber se é estatal, só a data decide"),
]


@pytest.mark.parametrize("kw,esperado,fonte", [c[1:] for c in OURO], ids=[c[0] for c in OURO])
def test_tabela_ouro(kw, esperado, fonte):
    d = regime_contrato(**kw)
    assert d.regime is esperado, f"{fonte} → {d}"
    assert d.fonte_da_decisao.strip(), "toda decisão carrega a fonte"


def test_nunca_pelo_ano_corrente():
    """A decisão não depende do relógio: o módulo não consulta a data corrente."""
    import compliance_agent.dominio.regime as m
    fonte = open(m.__file__, encoding="utf-8").read()
    assert "today(" not in fonte and "now(" not in fonte


def test_marco_29_e_30_de_dezembro():
    assert regime_contrato(lei_declarada_texto="8.666", data_edital=D(2023, 12, 29)).regime is R.L8666
    d30 = regime_contrato(lei_declarada_texto="8.666", data_edital=D(2023, 12, 30))
    assert d30.regime is R.INDETERMINADO and "29" in d30.fonte_da_decisao and "30" in d30.fonte_da_decisao


@pytest.mark.parametrize("texto,leis", [
    ("Lei n 14.133/2021, Art. 74, II", ("14133",)),
    ("LEI8666/93ART24II.", ("8666",)),
    ("Inciso XXI do art. 37 da CF/ Art. 2º da Lei 8666/93.", ("8666",)),
    ("Lei 13.303/2016, Art. 30, caput - inexigibilidade", ("13303",)),
    ("Não informado", ()),
    (None, ()),
    ("Processo 330003/008666/2024", ()),   # 8666 no meio de número de processo não é lei
])
def test_lei_declarada(texto, leis):
    assert lei_declarada(texto) == leis
