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
