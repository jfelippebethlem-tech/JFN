# -*- coding: utf-8 -*-
"""Auditoria das CITAÇÕES LEGAIS do catálogo Lex (pedido do dono 2026-07-24: "aplicar juridicamente correto").

Um achado que cita o dispositivo errado é pior que nenhum achado: destrói a credibilidade da peça e pode
imputar crime que não existe. Três erros foram encontrados e travados aqui:

1. **"Art. 90 da Lei 14.133/2021 (frustrar/fraudar licitação)"** — o art. 90 da Lei 14.133 trata da
   CONVOCAÇÃO DO VENCEDOR para assinar o contrato; não tipifica crime algum. O tipo de frustração do
   caráter competitivo é o **art. 337-F do Código Penal**, inserido pelo art. 178 da própria Lei 14.133
   (o antigo art. 90 da Lei 8.666/93 foi revogado).
2. **Sinal isolado de fachada etiquetado com tipo penal** — "sede em endereço residencial" não frustra
   caráter competitivo nem é, por si, ato de improbidade. A tipificação depende de DOLO e de resultado
   (art. 337-L CP exige fraude com prejuízo; a Lei 8.429, após a Lei 14.230/2021, exige dolo específico e
   tem rol taxativo no art. 11). O indício continua; a etiqueta penal automática, não.
3. **Qualificação técnica** — está no art. 67 da Lei 14.133 (técnico-profissional e operacional), não nos
   arts. 62-63 (que definem a fase de habilitação em geral).
"""
from __future__ import annotations

import re

from compliance_agent import lex_redflags as LR

TEXTO = " ".join(f"{k} {v[0]} {v[1]}" for k, v in LR._RF.items())


def test_art_90_da_14133_nunca_e_citado_como_crime():
    # o art. 90 da Lei 14.133 é convocação do vencedor — citá-lo como tipo penal é erro grosseiro
    assert not re.search(r"art\.?\s*90\s+(?:da\s+)?lei\s*14\.?133", TEXTO, re.I)


def test_conluio_cita_o_tipo_penal_correto():
    fundamento = LR._RF["R14"][1]
    assert "337-F" in fundamento                       # frustração do caráter competitivo
    assert "12.529" in fundamento                      # infração à ordem econômica (CADE)
    assert "178" in fundamento or "Código Penal" in fundamento or "CP" in fundamento


def test_sinal_isolado_de_fachada_nao_imputa_crime_automatico():
    for flag in ("DD/H-END-RESID", "DD/H-END-EXISTE", "DD/H-COEND", "DD/H-RECENTE",
                 "DD/H-SOCIO-UNICO", "DD/H-BENEFICIO"):
        fundamento = LR._RF[flag][1]
        # ou não cita tipo penal, ou cita RESSALVANDO que depende de dolo/resultado
        if re.search(r"337-[A-P]", fundamento):
            assert re.search(r"dolo|depende|se comprovad|exige", fundamento, re.I), flag


def test_improbidade_registra_a_exigencia_de_dolo_pos_14230():
    citam_8429 = [k for k, v in LR._RF.items() if "8.429" in v[1]]
    assert citam_8429
    for k in citam_8429:
        assert re.search(r"dolo|14\.230", LR._RF[k][1], re.I), k


def test_qualificacao_tecnica_cita_o_art_67():
    fundamento = LR._RF["R11"][1]
    assert "67" in fundamento


def test_dispositivos_revogados_vem_marcados():
    # a Lei 8.666/93 está revogada (integralmente desde 30/12/2023): se citada, tem de vir com a ressalva
    # de aplicação a FATOS ANTERIORES — senão o parecer sugere norma vigente que não é mais.
    for k, (_titulo, fundamento) in LR._RF.items():
        if "8.666" in fundamento:
            assert re.search(r"revogad|fatos?\s+at[ée]|anterior", fundamento, re.I), k
