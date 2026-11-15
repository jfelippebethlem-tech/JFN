# -*- coding: utf-8 -*-
"""Navegador VISÍVEL sem travar no PDF (dono, 15/11/2026: "não use headless pra isso nunca").

Com janela, o Chromium abria o anexo escaneado no visualizador de PDF dentro do ifrVisualizacao (450 s/doc medidos em
14/11) — por isso o it-campo tinha ido para headless. O anexo é baixado à parte por `context.request.get` (que não passa
pelo roteamento da página); a carga do PDF DENTRO da página é que se corta."""
from __future__ import annotations

import tools.sei_reader as SR

DOWN = "https://sei.rj.gov.br/sei/controlador.php?acao=documento_download_anexo&id_anexo=1&infra_hash=x"
ANEXO = "https://sei.rj.gov.br/sei/controlador.php?acao=download_anexo&id_anexo=2"
ARVORE = "https://sei.rj.gov.br/sei/controlador.php?acao=procedimento_visualizar&id_procedimento=3"


def test_corta_o_anexo_carregado_como_pagina_ou_quadro():
    assert SR.cortar_no_visualizador("document", DOWN)
    assert SR.cortar_no_visualizador("document", ANEXO)


def test_nao_corta_navegacao_normal_nem_recurso_de_outro_tipo():
    assert not SR.cortar_no_visualizador("document", ARVORE)
    assert not SR.cortar_no_visualizador("script", DOWN)
    assert not SR.cortar_no_visualizador("xhr", DOWN)
