# -*- coding: utf-8 -*-
"""Leitura estruturada dos documentos municipais (15/09/2026): trechos reais dos autos SME × AGILE."""
from __future__ import annotations

import sqlite3

from compliance_agent.pcrj.leitura_campos import campos_do_processo, extrair, ler_pendentes

_TA = ("1º TERMO ADITIVO Nº 119/2025 AO CONTRATO Nº 167/2025 … a empresa AGILE CORP SERVIÇOS ESPECIALIZADOS LTDA, "
       "inscrita no CNPJ sob o nº 00.801.512/0001-57 … Constitui objeto do presente termo aditivo ao Contrato n.º 167/2025 "
       "a prorrogação do prazo contratual por mais 06 (seis) meses, a contar de 01/01/2026 até 30/06/2026, com fundamento "
       "no art. 107 c/c art. 75, VIII, da Lei Federal nº 14.133/2021 e suas alterações. CLÁUSULA SEGUNDA - DO VALOR O valor "
       "do presente termo aditivo é de R$ 11.815.380,00 (onze milhões…). Aos dias 13 (treze) do mês de janeiro do ano de 2026, "
       "… Assinado com senha por LUCAS GERMANO FORTUNATO - GERENTE II / 52102 - 01/07/2025 às 18:23:39. "
       "Processo SME-PRO-2025/38233. código verificador 5192267 e o código CRC 1A2B3C4D. "
       "Pregão Eletrônico nº 90209/2025. acréscimo de 10 (dez) postos, no valor de R$ 832.755,00")


def test_extrai_os_campos_dos_autos_reais():
    c = {(x["campo"], x["valor"]) for x in extrair(_TA)}
    assert ("contrato_numero", "167/2025") in c and ("termo_aditivo", "1º TA 119/2025") in c
    assert ("cnpj", "00801512000157") in c and ("valor_total", "11815380.00") in c
    assert ("prazo_vigencia", "01/01/2026 a 30/06/2026") in c
    assert any(k == "fundamento" and "75, VIII" in v and "14.133/2021" in v for k, v in c)
    assert ("postos", "10") in c and ("processo", "SME-PRO-2025/38233") in c
    assert ("verificador_crc", "5192267/1A2B3C4D") in c and ("pregao", "90209/2025") in c
    assert ("data_assinatura", "2026-01-13") in c
    assert any(k == "assinado_por" and v.startswith("LUCAS GERMANO FORTUNATO") for k, v in c)
    # todo campo carrega o trecho de origem
    assert all(x["trecho"] for x in extrair(_TA))


def test_texto_sem_nada_nao_fabrica():
    assert extrair("relatório de vistoria sem números") == []
    assert extrair("") == []
    # casos reais que a 1ª versão fabricava (15/09): endereço, nº de processo e ano NÃO são postos
    ruido = "Rua Vinte e Quatro de Maio, 421 ( comercial composto de loja com postos de trabalho ) Processo EIS-PRO-2022/12888 Na forma; evento em 15 de agosto de 2026 na cidade. cota no valor de R$50.000,00"
    c = {(x["campo"], x["valor"]) for x in extrair(ruido)}
    assert not any(k == "postos" for k, _ in c)
    assert ("valor_mencionado", "50000.00") in c and not any(k == "valor_total" for k, _ in c)


def test_ler_pendentes_e_idempotente(tmp_path):
    db = tmp_path / "pcrj.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE pcrj_processo_doc (numero_processo, seq, tipo, titulo, texto, url, coletado_em, PRIMARY KEY (numero_processo, seq))")
    c.execute("INSERT INTO pcrj_processo_doc VALUES ('SME-PRO-2025/38233', 3618, 'ccon_integra', 'TA', ?, 'u', 'x')", (_TA,))
    c.commit(); c.close()
    r1 = ler_pendentes(db)
    r2 = ler_pendentes(db)
    assert r1["documentos_lidos"] == 1 and r1["campos"] >= 10 and r2["documentos_lidos"] == 0
    cp = campos_do_processo("SME-PRO-2025/38233", db)
    assert cp["contrato_numero"][0]["valor"] == "167/2025" and "valor_total" in cp


def test_pagina_coletiva_do_diario_so_atribui_o_que_esta_perto_do_proprio_processo():
    pagina = ("EXTRATO Processo 005600.000386/2026-51 Partes: GEO-RIO e R T C ENGENHARIA. Fundamento: art. 74, I da Lei 14.133/2021. "
              "Valor total de R$ 1.000,00. " + "x" * 300 +
              " EXTRATO Processo 005600.000111/2026-11 Partes: A LTDA. " + "y" * 300 +
              " EXTRATO Processo 005600.000222/2026-22 Partes: B LTDA. " + "z" * 300 +
              " EXTRATO Processo 005600.000999/2026-00 Partes: OUTRA LTDA, conforme o Art. 75, Inciso VIII da Lei 14.133/2021. "
              "Valor total de R$ 9.999,00.")
    c = {(x["campo"], x["valor"]) for x in extrair(pagina, "005600.000386/2026-51")}
    assert ("valor_total", "1000.00") in c and ("valor_total", "9999.00") not in c
    assert any(k == "fundamento" and "74" in v for k, v in c) and not any(k == "fundamento" and "75" in v for k, v in c)
    assert ("processo", "005600.000999/2026-00") in c            # âncoras continuam registradas
    # sem processo informado, ou documento próprio (não coletivo): comportamento antigo
    assert ("valor_total", "9999.00") in {(x["campo"], x["valor"]) for x in extrair(pagina)}


def test_base_de_preco_declarada():
    c = {(x["campo"], x["valor"]) for x in extrair("Dentre as 3 propostas apresentadas … mantidos os mesmos preços praticados no contrato anterior … referência SINAPI")}
    assert ("base_preco", "orcamentos") in c and ("base_preco", "contrato_anterior") in c and ("base_preco", "sinapi_emop") in c
    assert not any(k == "base_preco" for k, _ in extrair("sem menção a preço"))
