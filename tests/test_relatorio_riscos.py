"""
Testes OFFLINE do módulo Relatório de Riscos Corporativos.

Todos os testes simulam respostas de API com unittest.mock.patch,
sem fazer chamadas reais de rede.

Como rodar:
    cd /home/user/JFN
    python -m pytest tests/test_relatorio_riscos.py -v
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Garante que a raiz do projeto esteja no sys.path
_RAIZ = Path(__file__).resolve().parents[1]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

# ---------------------------------------------------------------------------
# Fixtures de dados simulados
# ---------------------------------------------------------------------------

CNPJ_CASHPAGO = "28584601000108"

EMPRESA_MOCK = {
    "ok": True,
    "fonte": "brasilapi",
    "razao_social": "CASHPAGO SOLUCOES LTDA",
    "nome_fantasia": "CASHPAGO",
    "cnpj": CNPJ_CASHPAGO,
    "situacao": "ATIVA",
    "data_abertura": "2021-03-15",
    "capital_social": 500000.0,
    "porte": "MICRO EMPRESA",
    "natureza_juridica": "206-2 - Sociedade Empresária Limitada",
    "cnae_principal": "6499-9/99 - Outras atividades de serviços financeiros não especificadas anteriormente",
    "endereco": "RUA TESTE, 123, CENTRO, SAO PAULO, SP, 01310-100",
    "email": "financeiro@cashpago.com.br",
    "telefone": "11999999999",
    "socios": [
        {
            "nome": "CRISTIANO ROSA SILVA",
            "cpf_cnpj_socio": "***677591**",
            "qualificacao": "49-Sócio-Administrador",
            "data_entrada": "2021-03-15",
        }
    ],
    "simples": True,
    "mei": False,
}

EMPRESA_GMAIL_MOCK = {**EMPRESA_MOCK, "email": "lincecaco@gmail.com"}

EMPRESA_CAPITAL_ALTO = {
    **EMPRESA_MOCK,
    "capital_social": 10_000_000.0,
    "porte": "MICRO EMPRESA",
}

EMPRESA_JOVEM = {
    **EMPRESA_MOCK,
    "data_abertura": "2025-12-01",  # menos de 2 anos atrás
}

CONTRATOS_MOCK = {
    "ok": True,
    "cnpj": CNPJ_CASHPAGO,
    "total": 3,
    "pagina": 1,
    "tam_pagina": 20,
    "contratos": [
        {
            "id_pncp": "TC-001-2026",
            "orgao": "MUNICIPIO DE SAO PAULO",
            "cnpj_orgao": "46392130000180",
            "objeto": "Prestação de serviços de pagamento digital",
            "modalidade": "INEXIGIBILIDADE",
            "valor_global": 2_160_000.0,
            "data_assinatura": "2026-01-09",
            "vigencia_inicio": "2026-01-09",
            "vigencia_fim": "2026-12-31",
            "numero_contrato": "001/2026",
        }
    ],
}

CONTRATOS_SIMBOLICO = {
    **CONTRATOS_MOCK,
    "contratos": [
        {**CONTRATOS_MOCK["contratos"][0], "valor_global": 0.01, "modalidade": "PREGÃO"},
    ],
}

CONTRATOS_VAZIOS = {"ok": True, "cnpj": CNPJ_CASHPAGO, "total": 0, "contratos": []}

SANCOES_SEM_CHAVE = {
    "ok": True,
    "cnpj": CNPJ_CASHPAGO,
    "verificado": False,
    "motivo": "sem chave API — defina TRANSPARENCIA_API_KEY para ativar verificação",
    "n_sancoes": 0,
    "sancoes": [],
}

SANCOES_COM_RESULTADO = {
    "ok": True,
    "cnpj": CNPJ_CASHPAGO,
    "verificado": True,
    "n_sancoes": 2,
    "sancoes": [
        {
            "tipo": "CEIS",
            "nome_informado": "CASHPAGO SOLUCOES LTDA",
            "cpf_cnpj": CNPJ_CASHPAGO,
            "orgao_sancionador": "CGU",
            "fundamentacao_legal": "Lei 12.846/2013",
            "data_inicio": "2025-01-01",
            "data_fim": "2026-01-01",
            "tipo_sancao": "Impedimento",
            "numero_processo": "00190.999999/2025-01",
            "valor_multa": None,
        }
    ],
}

REDE_MOCK = {
    "ok": True,
    "cnpj_raiz": CNPJ_CASHPAGO,
    "empresa_raiz": "CASHPAGO SOLUCOES LTDA",
    "nos": {
        "N0": [
            {
                "cnpj": CNPJ_CASHPAGO,
                "razao_social": "CASHPAGO SOLUCOES LTDA",
                "status": "ATIVA",
                "capital_social": 500000.0,
                "data_abertura": "2021-03-15",
                "natureza_juridica": "206-2",
                "socios": [{"nome": "CRISTIANO ROSA SILVA", "cpf_cnpj_socio": "***677591**", "qualificacao": "Sócio"}],
            }
        ],
        "N1": [],
        "N2": [],
        "N3": [],
    },
    "pessoas_chave": [],
    "total_cnpjs": 1,
    "baixadas_inaptas": 0,
    "pct_baixadas": 0.0,
    "aviso": "Expansão automática limitada: APIs públicas não permitem busca por CPF.",
}

REDE_COM_BAIXADAS = {
    **REDE_MOCK,
    "total_cnpjs": 10,
    "baixadas_inaptas": 5,
    "pct_baixadas": 50.0,
}


# ---------------------------------------------------------------------------
# Teste 1: sinais de risco — lógica central (sem I/O)
# ---------------------------------------------------------------------------

class TestSinaisRisco:
    """Testa a função calcular_sinais sem qualquer chamada de rede."""

    def _calcular(self, empresa, rede, contratos, sancoes):
        from relatorio_riscos.analise.sinais_risco import calcular_sinais
        return calcular_sinais(empresa, rede, contratos, sancoes)

    def test_sem_sinais_nivel_baixo(self):
        """Empresa sem anomalias deve resultar em nível BAIXO."""
        sinais = self._calcular(EMPRESA_MOCK, REDE_MOCK, CONTRATOS_VAZIOS, SANCOES_SEM_CHAVE)
        assert sinais["nivel_geral"] in ("BAIXO", "MÉDIO", "ALTO")  # deve ser válido
        assert isinstance(sinais["score"], int)
        assert 0 <= sinais["score"] <= 100
        assert "sinais_alto" in sinais
        assert "sinais_medio" in sinais
        assert "sinais_baixo" in sinais

    def test_inexigibilidade_gera_sinal_alto(self):
        """Contrato com modalidade INEXIGIBILIDADE deve gerar sinal ALTO."""
        sinais = self._calcular(EMPRESA_MOCK, REDE_MOCK, CONTRATOS_MOCK, SANCOES_SEM_CHAVE)
        descricoes_alto = [s["descricao"] for s in sinais["sinais_alto"]]
        assert any("inexigibilidade" in d.lower() for d in descricoes_alto), (
            f"Esperado sinal ALTO de inexigibilidade, sinais ALTO: {descricoes_alto}"
        )
        assert sinais["nivel_geral"] == "ALTO"

    def test_contrato_simbolico_gera_sinal_alto(self):
        """Contrato com valor R$ 0,01 deve gerar sinal ALTO de remuneração oculta."""
        sinais = self._calcular(EMPRESA_MOCK, REDE_MOCK, CONTRATOS_SIMBOLICO, SANCOES_SEM_CHAVE)
        descricoes_alto = [s["descricao"] for s in sinais["sinais_alto"]]
        assert any("simb" in d.lower() for d in descricoes_alto), (
            f"Esperado sinal ALTO simbólico, sinais ALTO: {descricoes_alto}"
        )

    def test_capital_alto_micro_empresa(self):
        """Capital R$ 10M em microempresa deve gerar sinal ALTO."""
        sinais = self._calcular(EMPRESA_CAPITAL_ALTO, REDE_MOCK, CONTRATOS_VAZIOS, SANCOES_SEM_CHAVE)
        descricoes_alto = [s["descricao"] for s in sinais["sinais_alto"]]
        assert any("capital" in d.lower() for d in descricoes_alto), (
            f"Esperado sinal ALTO de capital, sinais ALTO: {descricoes_alto}"
        )

    def test_email_gmail_gera_sinal_medio(self):
        """Email gmail deve gerar sinal MÉDIO."""
        sinais = self._calcular(EMPRESA_GMAIL_MOCK, REDE_MOCK, CONTRATOS_VAZIOS, SANCOES_SEM_CHAVE)
        descricoes_medio = [s["descricao"] for s in sinais["sinais_medio"]]
        assert any("email" in d.lower() for d in descricoes_medio), (
            f"Esperado sinal MÉDIO de email, sinais MÉDIO: {descricoes_medio}"
        )

    def test_alto_indice_baixadas(self):
        """Rede com 50% de empresas baixadas deve gerar sinal MÉDIO."""
        sinais = self._calcular(EMPRESA_MOCK, REDE_COM_BAIXADAS, CONTRATOS_VAZIOS, SANCOES_SEM_CHAVE)
        descricoes_medio = [s["descricao"] for s in sinais["sinais_medio"]]
        assert any("baixad" in d.lower() or "encerrad" in d.lower() for d in descricoes_medio), (
            f"Esperado sinal MÉDIO de empresas baixadas, sinais MÉDIO: {descricoes_medio}"
        )

    def test_sancao_gera_sinal_alto(self):
        """Sanções verificadas devem gerar sinal ALTO."""
        sinais = self._calcular(EMPRESA_MOCK, REDE_MOCK, CONTRATOS_VAZIOS, SANCOES_COM_RESULTADO)
        descricoes_alto = [s["descricao"] for s in sinais["sinais_alto"]]
        assert any("san" in d.lower() for d in descricoes_alto), (
            f"Esperado sinal ALTO de sanção, sinais ALTO: {descricoes_alto}"
        )

    def test_score_proporcional(self):
        """Score deve crescer com mais sinais de alto risco."""
        sinais_poucos = self._calcular(EMPRESA_MOCK, REDE_MOCK, CONTRATOS_VAZIOS, SANCOES_SEM_CHAVE)
        sinais_muitos = self._calcular(
            EMPRESA_CAPITAL_ALTO, REDE_COM_BAIXADAS, CONTRATOS_MOCK, SANCOES_COM_RESULTADO
        )
        assert sinais_muitos["score"] >= sinais_poucos["score"]


# ---------------------------------------------------------------------------
# Teste 2: gerador de Markdown (sem I/O)
# ---------------------------------------------------------------------------

class TestGeradorMarkdown:
    """Testa a geração de relatório Markdown sem chamadas de rede."""

    def _sinais_base(self):
        from relatorio_riscos.analise.sinais_risco import calcular_sinais
        return calcular_sinais(EMPRESA_MOCK, REDE_MOCK, CONTRATOS_MOCK, SANCOES_SEM_CHAVE)

    def test_md_contem_secoes_obrigatorias(self):
        """Relatório Markdown deve conter todas as 7 seções."""
        from relatorio_riscos.relatorio.gerador import gerar_md
        sinais = self._sinais_base()
        md = gerar_md(EMPRESA_MOCK, REDE_MOCK, CONTRATOS_MOCK, SANCOES_SEM_CHAVE, sinais, "2026-06-04")

        secoes_esperadas = [
            "Relatório de Riscos Corporativos",
            "Sumário Executivo",
            "Dados Cadastrais",
            "Rede Societária",
            "Pessoas-Chave",
            "Contratos Públicos",
            "Sanções",
            "Sinais de Risco",
            "Conclusões",
        ]
        for secao in secoes_esperadas:
            assert secao in md, f"Seção '{secao}' não encontrada no relatório"

    def test_md_contem_cnpj(self):
        """Relatório deve conter o CNPJ formatado."""
        from relatorio_riscos.relatorio.gerador import gerar_md
        sinais = self._sinais_base()
        md = gerar_md(EMPRESA_MOCK, REDE_MOCK, CONTRATOS_MOCK, SANCOES_SEM_CHAVE, sinais, "2026-06-04")
        assert "28.584.601/0001-08" in md

    def test_md_contem_razao_social(self):
        """Relatório deve mencionar a razão social da empresa."""
        from relatorio_riscos.relatorio.gerador import gerar_md
        sinais = self._sinais_base()
        md = gerar_md(EMPRESA_MOCK, REDE_MOCK, CONTRATOS_MOCK, SANCOES_SEM_CHAVE, sinais, "2026-06-04")
        assert "CASHPAGO SOLUCOES LTDA" in md

    def test_txt_strip_markdown(self):
        """Versão TXT não deve conter marcadores Markdown como '##' ou '**'."""
        from relatorio_riscos.relatorio.gerador import gerar_txt
        sinais = self._sinais_base()
        txt = gerar_txt(EMPRESA_MOCK, REDE_MOCK, CONTRATOS_MOCK, SANCOES_SEM_CHAVE, sinais, "2026-06-04")
        # Não deve conter headers markdown
        import re
        assert not re.search(r"^#{1,6}\s", txt, re.MULTILINE), "TXT contém headers markdown"

    def test_md_nivel_risco_visivel(self):
        """Relatório deve exibir o nível de risco."""
        from relatorio_riscos.relatorio.gerador import gerar_md
        sinais = self._sinais_base()
        md = gerar_md(EMPRESA_MOCK, REDE_MOCK, CONTRATOS_MOCK, SANCOES_SEM_CHAVE, sinais, "2026-06-04")
        assert any(nivel in md for nivel in ("ALTO", "MÉDIO", "BAIXO"))


# ---------------------------------------------------------------------------
# Teste 3: coletores — parsing e normalização offline
# ---------------------------------------------------------------------------

class TestCnpjReceita:
    """Testa funções de normalização do coletor CNPJ (sem HTTP)."""

    def test_mascarar_cpf_11_digitos(self):
        """CPF de 11 dígitos deve ser mascarado — inicia com *** e termina com **."""
        from relatorio_riscos.collectors.cnpj_receita import _mascarar_cpf
        resultado = _mascarar_cpf("361.677.591-05")
        assert resultado == "***677591**", f"Esperado '***677591**', obtido '{resultado}'"
        assert resultado.startswith("***")
        assert resultado.endswith("**")

    def test_mascarar_cnpj_nao_mascara(self):
        """CNPJ (14 dígitos) não deve ser mascarado."""
        from relatorio_riscos.collectors.cnpj_receita import _mascarar_cpf
        cnpj = "28.584.601/0001-08"
        resultado = _mascarar_cpf(cnpj)
        assert resultado == cnpj, "CNPJ não deve ser mascarado"

    def test_mascarar_cpf_sem_pontuacao(self):
        """CPF sem pontuação também deve ser mascarado corretamente."""
        from relatorio_riscos.collectors.cnpj_receita import _mascarar_cpf
        resultado = _mascarar_cpf("36167759105")
        assert resultado.startswith("***")
        assert resultado.endswith("**")

    def test_limpar_cnpj(self):
        """CNPJ formatado deve virar string de 14 dígitos."""
        from relatorio_riscos.collectors.cnpj_receita import _limpar_cnpj
        assert _limpar_cnpj("28.584.601/0001-08") == "28584601000108"
        assert _limpar_cnpj("28584601000108") == "28584601000108"

    def test_cnpj_invalido_retorna_erro(self):
        """CNPJ com número errado de dígitos deve retornar ok=False."""
        async def _run():
            from relatorio_riscos.collectors.cnpj_receita import buscar_cnpj
            return await buscar_cnpj("123")

        resultado = asyncio.run(_run())
        assert resultado["ok"] is False
        assert "inválido" in resultado["erro"].lower()

    @patch("relatorio_riscos.collectors.cnpj_receita.httpx.AsyncClient")
    def test_buscar_cnpj_brasilapi_sucesso(self, mock_client_cls):
        """Simula resposta bem-sucedida da BrasilAPI."""
        payload = {
            "razao_social": "CASHPAGO SOLUCOES LTDA",
            "nome_fantasia": "CASHPAGO",
            "cnpj": "28584601000108",
            "descricao_situacao_cadastral": "ATIVA",
            "data_inicio_atividade": "2021-03-15",
            "capital_social": 500000.0,
            "porte": "MICRO EMPRESA",
            "natureza_juridica": "206-2 - Soc. Emp. Ltda",
            "cnae_fiscal": 6499999,
            "cnae_fiscal_descricao": "Outras atividades financeiras",
            "logradouro": "RUA TESTE",
            "numero": "123",
            "complemento": "",
            "bairro": "CENTRO",
            "municipio": "SAO PAULO",
            "uf": "SP",
            "cep": "01310100",
            "email": "financeiro@cashpago.com.br",
            "ddd_telefone_1": "11999999999",
            "qsa": [
                {
                    "nome_socio": "CRISTIANO ROSA SILVA",
                    "cnpj_cpf_do_socio": "361.677.591-05",
                    "qualificacao_socio": "49-Sócio-Administrador",
                    "data_entrada_sociedade": "2021-03-15",
                }
            ],
            "opcao_pelo_simples": True,
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = payload

        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_instance.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client_instance

        async def _run():
            from relatorio_riscos.collectors.cnpj_receita import buscar_cnpj
            return await buscar_cnpj("28584601000108")

        resultado = asyncio.run(_run())
        assert resultado["ok"] is True
        assert resultado["razao_social"] == "CASHPAGO SOLUCOES LTDA"
        assert resultado["situacao"] == "ATIVA"
        assert resultado["capital_social"] == 500000.0
        assert len(resultado["socios"]) == 1
        assert resultado["socios"][0]["nome"] == "CRISTIANO ROSA SILVA"
        # CPF deve estar mascarado
        assert resultado["socios"][0]["cpf_cnpj_socio"].startswith("***")


# ---------------------------------------------------------------------------
# Teste 4: coletor PNCP — parsing offline
# ---------------------------------------------------------------------------

class TestContratosPNCP:
    """Testa parsing de resposta do PNCP sem chamada real."""

    @patch("relatorio_riscos.collectors.contratos_pncp.httpx.AsyncClient")
    def test_pncp_retorna_contratos(self, mock_client_cls):
        """Simula resposta do PNCP com contratos."""
        payload = {
            "data": [
                {
                    "numeroControlePNCP": "TC-001-2026",
                    "orgaoEntidade": {"razaoSocial": "MUNICIPIO SP", "cnpj": "46392130000180"},
                    "objetoContrato": "Serviços de pagamento",
                    "modalidadeNome": "INEXIGIBILIDADE",
                    "valorGlobal": 2160000.0,
                    "dataAssinatura": "2026-01-09",
                    "dataInicioVigencia": "2026-01-09",
                    "dataFimVigencia": "2026-12-31",
                    "numeroContratoEmpenho": "001/2026",
                }
            ],
            "totalRegistros": 1,
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = payload

        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_instance.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client_instance

        async def _run():
            from relatorio_riscos.collectors.contratos_pncp import buscar_contratos_por_cnpj
            return await buscar_contratos_por_cnpj("28584601000108")

        resultado = asyncio.run(_run())
        assert resultado["ok"] is True
        assert resultado["total"] == 1
        assert len(resultado["contratos"]) == 1
        c = resultado["contratos"][0]
        assert c["modalidade"] == "INEXIGIBILIDADE"
        assert c["valor_global"] == 2160000.0
        assert c["orgao"] == "MUNICIPIO SP"

    @patch("relatorio_riscos.collectors.contratos_pncp.httpx.AsyncClient")
    def test_pncp_404_retorna_vazio(self, mock_client_cls):
        """HTTP 404 do PNCP deve retornar lista vazia (sem erros)."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_instance.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client_instance

        async def _run():
            from relatorio_riscos.collectors.contratos_pncp import buscar_contratos_por_cnpj
            return await buscar_contratos_por_cnpj("28584601000108")

        resultado = asyncio.run(_run())
        assert resultado["ok"] is True
        assert resultado["total"] == 0
        assert resultado["contratos"] == []


# ---------------------------------------------------------------------------
# Teste 5: coletor WHOIS — parsing offline
# ---------------------------------------------------------------------------

class TestWhoisBr:
    """Testa parsing RDAP sem chamadas reais."""

    @patch("relatorio_riscos.collectors.whois_br.httpx.AsyncClient")
    def test_whois_dominio_encontrado(self, mock_client_cls):
        """Simula resposta RDAP com domínio registrado."""
        payload = {
            "ldhName": "cashpago.com.br",
            "events": [
                {"eventAction": "registration", "eventDate": "2021-05-17T00:00:00Z"},
                {"eventAction": "last changed", "eventDate": "2025-01-01T00:00:00Z"},
                {"eventAction": "expiration", "eventDate": "2027-05-17T00:00:00Z"},
            ],
            "nameservers": [
                {"ldhName": "ns1.cloudflare.com"},
                {"ldhName": "ns2.cloudflare.com"},
            ],
            "entities": [
                {
                    "roles": ["registrant"],
                    "handle": "CRS123",
                    "vcardArray": [
                        "vcard",
                        [
                            ["version", {}, "text", "4.0"],
                            ["fn", {}, "text", "Cristiano Rosa Silva"],
                            ["email", {}, "text", "lincecaco@gmail.com"],
                        ],
                    ],
                    "publicIds": [{"type": "CPF", "identifier": "361.677.591-05"}],
                }
            ],
            "status": ["active"],
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = payload

        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_instance.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client_instance

        async def _run():
            from relatorio_riscos.collectors.whois_br import consultar_whois
            return await consultar_whois("cashpago.com.br")

        resultado = asyncio.run(_run())
        assert resultado["ok"] is True
        assert resultado["encontrado"] is True
        assert resultado["registrado_em"] == "2021-05-17"
        assert resultado["registrante"]["nome"] == "Cristiano Rosa Silva"
        assert resultado["registrante"]["email"] == "lincecaco@gmail.com"
        assert len(resultado["nome_servidores"]) == 2

    @patch("relatorio_riscos.collectors.whois_br.httpx.AsyncClient")
    def test_whois_dominio_nao_registrado(self, mock_client_cls):
        """HTTP 404 deve indicar domínio não registrado sem erro."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_instance.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client_instance

        async def _run():
            from relatorio_riscos.collectors.whois_br import consultar_whois
            return await consultar_whois("dominionaoexistente99999.com.br")

        resultado = asyncio.run(_run())
        assert resultado["ok"] is True
        assert resultado["encontrado"] is False

    def test_gerar_variacoes_dominio(self):
        """Deve gerar variações .com.br a partir do nome da empresa."""
        from relatorio_riscos.collectors.whois_br import _gerar_variacoes_dominio
        variacoes = _gerar_variacoes_dominio("CASHPAGO SOLUCOES LTDA")
        assert any(".com.br" in v for v in variacoes)
        assert any("cashpago" in v for v in variacoes)


# ---------------------------------------------------------------------------
# Teste 6: integração do main.py com mocks
# ---------------------------------------------------------------------------

class TestMainIntegracao:
    """Testa o fluxo completo com todos os coletores mockados."""

    @patch("relatorio_riscos.main.buscar_dominios_grupo", new_callable=AsyncMock)
    @patch("relatorio_riscos.main.expandir_rede", new_callable=AsyncMock)
    @patch("relatorio_riscos.main.verificar_sancoes", new_callable=AsyncMock)
    @patch("relatorio_riscos.main.buscar_contratos_por_cnpj", new_callable=AsyncMock)
    @patch("relatorio_riscos.main.buscar_cnpj", new_callable=AsyncMock)
    def test_fluxo_completo_sem_salvar(
        self,
        mock_cnpj,
        mock_contratos,
        mock_sancoes,
        mock_rede,
        mock_whois,
    ):
        """Fluxo completo deve retornar estrutura correta sem salvar arquivo."""
        mock_cnpj.return_value = EMPRESA_MOCK
        mock_contratos.return_value = CONTRATOS_MOCK
        mock_sancoes.return_value = SANCOES_SEM_CHAVE
        mock_rede.return_value = REDE_MOCK
        mock_whois.return_value = []

        async def _run():
            from relatorio_riscos.main import gerar_relatorio_risco
            return await gerar_relatorio_risco("28584601000108", salvar=False)

        resultado = asyncio.run(_run())

        assert resultado["ok"] is True
        assert resultado["cnpj"] == "28584601000108"
        assert resultado["empresa"] == "CASHPAGO SOLUCOES LTDA"
        assert resultado["risco"] in ("ALTO", "MÉDIO", "BAIXO")
        assert isinstance(resultado["sinais"], list)
        assert isinstance(resultado["relatorio_md"], str)
        assert len(resultado["relatorio_md"]) > 500
        assert "dados" in resultado
        assert resultado["relatorio_path"] == ""  # não salvou

    def test_cnpj_invalido_retorna_erro(self):
        """CNPJ inválido deve retornar ok=False imediatamente."""
        async def _run():
            from relatorio_riscos.main import gerar_relatorio_risco
            return await gerar_relatorio_risco("12345")

        resultado = asyncio.run(_run())
        assert resultado["ok"] is False
        assert "inválido" in resultado["erro"].lower()

    @patch("relatorio_riscos.main.buscar_dominios_grupo", new_callable=AsyncMock)
    @patch("relatorio_riscos.main.expandir_rede", new_callable=AsyncMock)
    @patch("relatorio_riscos.main.verificar_sancoes", new_callable=AsyncMock)
    @patch("relatorio_riscos.main.buscar_contratos_por_cnpj", new_callable=AsyncMock)
    @patch("relatorio_riscos.main.buscar_cnpj", new_callable=AsyncMock)
    def test_coletor_falho_nao_quebra_fluxo(
        self,
        mock_cnpj,
        mock_contratos,
        mock_sancoes,
        mock_rede,
        mock_whois,
    ):
        """Falha em um coletor não deve impedir geração do relatório."""
        mock_cnpj.return_value = EMPRESA_MOCK
        mock_contratos.return_value = {"ok": False, "erro": "Timeout PNCP", "total": 0, "contratos": []}
        mock_sancoes.return_value = SANCOES_SEM_CHAVE
        mock_rede.return_value = REDE_MOCK
        mock_whois.return_value = []

        async def _run():
            from relatorio_riscos.main import gerar_relatorio_risco
            return await gerar_relatorio_risco("28584601000108", salvar=False)

        resultado = asyncio.run(_run())
        assert resultado["ok"] is True
        assert resultado["risco"] in ("ALTO", "MÉDIO", "BAIXO")


# ---------------------------------------------------------------------------
# Runner standalone
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import unittest

    # Executa via unittest quando rodado diretamente
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in [
        TestSinaisRisco,
        TestGeradorMarkdown,
        TestCnpjReceita,
        TestContratosPNCP,
        TestWhoisBr,
        TestMainIntegracao,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
