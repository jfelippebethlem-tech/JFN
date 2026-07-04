# -*- coding: utf-8 -*-
"""Testes do módulo PCRJ (funções puras; sem rede, sem escrita na compliance.db)."""
from __future__ import annotations

from compliance_agent.pcrj import camara_servidores as cs
from compliance_agent.pcrj import nomes
from compliance_agent.pcrj.cruzamento import _classificar
from compliance_agent.pcrj.pcrj_remuneracao import Sessao
from compliance_agent.pcrj.relatorio import _vinculo_efetivo


class TestNomes:
    def test_normalizar_acentos_e_caixa(self):
        assert nomes.normalizar("José da Silva") == "JOSE DA SILVA"
        assert nomes.normalizar("FÁTIMA  CRISTINA ") == "FATIMA CRISTINA"

    def test_normalizar_pontuacao_e_digitos(self):
        assert nomes.normalizar("Ana-Paula 2º") == "ANA PAULA"

    def test_normalizar_vazio(self):
        assert nomes.normalizar("") == ""
        assert nomes.normalizar(None) == ""

    def test_chave_blocagem_ignora_particulas(self):
        # primeiro + último token significativo (de/da/dos ignorados)
        assert nomes.chave_blocagem("João da Silva Souza") == "JOAO SOUZA"
        assert nomes.chave_blocagem("Maria") == "MARIA"
        assert nomes.chave_blocagem("de da dos") == ""

    def test_tokens_significativos(self):
        assert nomes.tokens_significativos("Luiz de Souza") == ["LUIZ", "SOUZA"]


class TestClassificarLotacao:
    def test_gabinete_parlamentar_extrai_numero(self):
        assert cs._classificar_lotacao("Gabinete Parlamentar Nº 48") == (48, "gabinete_parlamentar")
        assert cs._classificar_lotacao("GABINETE PARLAMENTAR N 3")[0] == 3

    def test_administrativo(self):
        assert cs._classificar_lotacao("Diretoria de Tecnologia")[1] == "administrativo"
        assert cs._classificar_lotacao("Gabinete da 1ª Secretaria")[0] is None  # não é parlamentar

    def test_vazio(self):
        assert cs._classificar_lotacao("")[1] == "indefinido"

    def test_limpar_padding(self):
        assert cs._limpar('"7682                    "') == "7682"


class TestClassificarConfianca:
    def test_nome_unico(self):
        assert _classificar({"matches": {"123": {}}, "erro": False}) == "indicio_nome_unico"

    def test_homonimo_ambiguo(self):
        assert _classificar({"matches": {"1": {}, "2": {}}, "erro": False}) == "homonimo_ambiguo"

    def test_nao_encontrado(self):
        assert _classificar({"matches": {}, "erro": False}) == "nao_encontrado"

    def test_indisponivel(self):
        # sem matches MAS houve erro → INDISPONÍVEL, nunca 'não encontrado' (honestidade)
        assert _classificar({"matches": {}, "erro": True}) == "indisponivel"


class TestVinculoEfetivo:
    def test_guarda_e_professor_sao_efetivos(self):
        assert _vinculo_efetivo("GUARDA MUNICIPAL")
        assert _vinculo_efetivo("PROFESSOR II")

    def test_comissionado_nao_efetivo(self):
        assert not _vinculo_efetivo("ESPECIAL")
        assert not _vinculo_efetivo("")


class TestParsePCRJ:
    def test_parse_extrai_linhas_data_ri(self):
        # fragmento mínimo no formato do partial-response (uma linha data-ri)
        frag = ('<update id="divResultados"><![CDATA['
                '<tr data-ri="0" role="row">'
                '<td>123</td><td>FULANO DE TAL</td><td>PROFESSOR</td><td>SME</td>'
                '<td>5/2025</td><td>F</td><td>1</td><td>0</td><td>1.000,00</td>'
                '</tr>]]></update>')
        linhas = Sessao._parse(frag)
        assert len(linhas) == 1
        assert linhas[0]["nome"] == "FULANO DE TAL"
        assert linhas[0]["cargo"] == "PROFESSOR"
        assert linhas[0]["lotacao"] == "SME"

    def test_parse_sem_resultados(self):
        assert Sessao._parse("<partial-response></partial-response>") == []


class TestRelatorioEleitoral:
    """Integração da seção eleitoral (sem rede): DB tmp semeado → seção renderiza a flag."""

    def _seed(self, tmp_path):
        from compliance_agent.pcrj import db as _db
        p = tmp_path / "pcrj_test.db"
        _db.inicializar(p)
        con = _db.conectar(p)
        con.execute("INSERT INTO pcrj_gabinetes(gabinete_num,vereador,vereador_norm,coletado_em) "
                    "VALUES (12,'Fulano Vereador','FULANO VEREADOR','x')")
        con.execute("INSERT INTO pcrj_camara_servidores(nome,nome_norm,cargo,lotacao,"
                    "gabinete_num,tipo_lotacao,ano_ingresso,doc_num,coletado_em) "
                    "VALUES ('Jose Edmilson','JOSE EDMILSON','OFICIAL','Gab',12,'gabinete_parlamentar',2024,'1','x')")
        con.execute("INSERT INTO tse_candidatura(nome_norm,nome_tse,ano,cargo,municipio,uf,"
                    "partido,situacao,outra_cidade,coletado_em) "
                    "VALUES ('JOSE EDMILSON','Jose Edmilson','2024','VEREADOR','MANGARATIBA','RJ','UNIÃO','APTO',1,'x')")
        con.commit()
        con.close()
        return p

    def test_secao_eleitoral_marca_outra_cidade(self, tmp_path):
        from compliance_agent.pcrj.relatorio import montar_ctx
        p = self._seed(tmp_path)
        ctx = montar_ctx(db_path=p)
        assert ctx["cand"]["pessoas"] == 1
        assert ctx["cand"]["outra_cidade"] == 1
        sec = [s for s in ctx["secoes"] if "candidatos" in s["titulo"].lower()][0]
        assert "MANGARATIBA" in sec["html"]
        assert "OUTRA CIDADE" in sec["html"]
        # a seção de abertura "Principais achados" existe e não quebra com este seed
        assert ctx["secoes"][0]["titulo"] == "Principais achados"


class TestRelatorioGabinete:
    def test_ctx_gabinete_lista_e_vinculo(self, tmp_path):
        from compliance_agent.pcrj import db as _db
        from compliance_agent.pcrj import relatorio_gabinete as rg
        p = tmp_path / "g.db"
        _db.inicializar(p)
        con = _db.conectar(p)
        con.execute("INSERT INTO pcrj_gabinetes(gabinete_num,vereador,vereador_norm,coletado_em) "
                    "VALUES (32,'Pedro Duarte','PEDRO DUARTE','x')")
        con.execute("INSERT INTO pcrj_camara_servidores(nome,nome_norm,cargo,lotacao,gabinete_num,"
                    "tipo_lotacao,ano_ingresso,doc_num,vinculo,coletado_em) VALUES "
                    "('Andreia Domingos','ANDREIA DOMINGOS','AUX','Gab',32,'gabinete_parlamentar',2026,'1','Requisitados sem Cargo','x')")
        con.execute("INSERT INTO pcrj_vinculo_cruzado(nome_norm,nome_camara,gabinetes,cargos_camara,"
                    "cargo_pcrj,orgao_pcrj,confianca,observacao,gerado_em) VALUES "
                    "('ANDREIA DOMINGOS','Andreia Domingos','Gab 32','AUX','PROFESSOR II','E/CRE',"
                    "'indicio_nome_unico','admissao=06/05/2002 exoneracao= matricula=1','x')")
        con.commit(); con.close()
        ctx = rg.montar_ctx(32, db_path=p)
        assert "Pedro Duarte" in ctx["titulo"]
        assert "Andreia Domingos" in ctx["secoes"][0]["html"]      # aparece na seção de vínculos
        assert "cessão/requisição" in ctx["secoes"][0]["html"]     # Requisitado → cessão


class TestPipeline:
    def test_etapas_conhecidas(self):
        from compliance_agent.pcrj import pipeline
        assert pipeline._ETAPAS == ("camara", "cruzamento", "tse", "relatorio")

    def test_tse_escopo_rj_documentado(self):
        # a fronteira RJ-only deve estar explícita no módulo (decisão do dono)
        from compliance_agent.pcrj import tse_candidatos
        assert tse_candidatos._RIO == "RIO DE JANEIRO"
        assert "RJ" in tse_candidatos._URL.format(ano=2024) or "consulta_cand" in tse_candidatos._URL
