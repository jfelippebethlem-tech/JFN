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

    def test_agregado_por_parlamentar_titular_e_legislatura(self, tmp_path):
        from compliance_agent.pcrj import db as _db
        from compliance_agent.pcrj import relatorio_gabinete as rg
        p = tmp_path / "g2.db"
        _db.inicializar(p)
        con = _db.conectar(p)
        con.execute("INSERT INTO pcrj_gabinetes(gabinete_num,vereador,vereador_norm,titular,"
                    "suplente,coletado_em) VALUES (11,'Jorge Fellipe (suplente)','JORGE FELLIPE',"
                    "'Felipe Michel','Jorge Fellipe','x')")
        # um nomeado da legislatura atual e um de ingresso anterior (atribuição incerta)
        con.execute("INSERT INTO pcrj_camara_servidores(nome,nome_norm,cargo,lotacao,gabinete_num,"
                    "tipo_lotacao,ano_ingresso,doc_num,coletado_em) VALUES "
                    "('Novo Assessor','NOVO ASSESSOR','ASSESSOR','Gab',11,'gabinete_parlamentar',2025,'1','x')")
        con.execute("INSERT INTO pcrj_camara_servidores(nome,nome_norm,cargo,lotacao,gabinete_num,"
                    "tipo_lotacao,ano_ingresso,doc_num,coletado_em) VALUES "
                    "('Antigo Assessor','ANTIGO ASSESSOR','ASSESSOR','Gab',11,'gabinete_parlamentar',2015,'2','x')")
        con.commit(); con.close()
        ctx = rg.montar_ctx_completo(db_path=p)
        sec = [s for s in ctx["secoes"] if s["titulo"].startswith("Felipe Michel")]
        assert sec, "seção deve ser titulada pelo TITULAR (Felipe Michel), não pelo nº"
        html = sec[0]["html"]
        assert "Suplente em exercício" in html and "Jorge Fellipe" in html
        assert "anterior*" in html   # o ingresso 2015 é marcado como atribuição histórica incerta


class TestPericia:
    def _pessoa(self, cam_ato, posts):
        from datetime import date
        def d(s):
            return date(*map(int, s.split("-"))) if s else None
        return {"nome": "X", "cam_ato": d(cam_ato),
                "postos": [{"adm": d(a), "exo": d(e)} for a, e in posts]}

    def test_direcao_prefeitura_antes(self):
        from compliance_agent.pcrj import pericia
        # prefeitura começou 2020, câmara 2025 → estava na prefeitura ANTES
        p = self._pessoa("2025-02-01", [("2020-05-06", "2024-12-31")])
        assert pericia._direcao(p) == "pref_antes"

    def test_direcao_camara_antes(self):
        from compliance_agent.pcrj import pericia
        # câmara 2015, prefeitura 2020 → estava na câmara ANTES
        p = self._pessoa("2015-08-05", [("2020-05-06", None)])
        assert pericia._direcao(p) == "camara_antes"

    def test_concomitante_com_hoje_fixo(self):
        from datetime import date
        from compliance_agent.pcrj import pericia
        pericia._HOJE = date(2026, 7, 1)
        try:
            # prefeitura ativa (sem exoneração) desde 2010, câmara desde 2025 → concomitante
            p = self._pessoa("2025-01-01", [("2010-01-13", None)])
            assert pericia._concomitante(p) is True
            # prefeitura encerrada em 2023, câmara em 2025 → NÃO concomitante
            p2 = self._pessoa("2025-01-01", [("2020-01-01", "2023-01-01")])
            assert pericia._concomitante(p2) is False
        finally:
            pericia._HOJE = None


class TestAlternancia:
    def test_data_parse_e_posse(self):
        from datetime import date
        from compliance_agent.pcrj import alternancia
        assert alternancia._d("02/01/2025") == date(2025, 1, 2)
        assert alternancia._d("") is None
        assert alternancia._POSSE_SUPLENTES == date(2025, 1, 2)
        assert set(alternancia.GABINETES_ALTERNANCIA) == {6, 11, 20, 41, 44}

    def test_split_por_periodo(self, tmp_path):
        from compliance_agent.pcrj import alternancia
        from compliance_agent.pcrj import db as _db
        p = tmp_path / "a.db"
        _db.inicializar(p)
        con = _db.conectar(p)
        con.execute("INSERT INTO pcrj_gabinetes(gabinete_num,titular,suplente,coletado_em) "
                    "VALUES (11,'Felipe Michel','Jorge Fellipe','x')")
        con.execute("INSERT INTO pcrj_camara_servidores(nome,nome_norm,cargo,lotacao,gabinete_num,"
                    "tipo_lotacao,ano_ingresso,data1,doc_num,coletado_em) VALUES "
                    "('Novo','NOVO','ASSESSOR','Gab',11,'gabinete_parlamentar',2025,'01/03/2025','1','x')")
        con.execute("INSERT INTO pcrj_camara_servidores(nome,nome_norm,cargo,lotacao,gabinete_num,"
                    "tipo_lotacao,ano_ingresso,data1,doc_num,coletado_em) VALUES "
                    "('Antigo','ANTIGO','ASSESSOR','Gab',11,'gabinete_parlamentar',2022,'01/06/2022','2','x')")
        con.commit(); con.close()
        sec = alternancia._secao_gabinete(alternancia._db.conectar(p), 11)
        assert "Jorge Fellipe" in sec["titulo"] and "Felipe Michel" in sec["titulo"]
        # 'Novo' (2025) sob suplente; 'Antigo' (2022) período anterior
        assert "sob o suplente Jorge Fellipe</b> (ato ≥ 02/01/2025) — 1" in sec["html"]
        assert "CONTINUIDADE" in sec["html"] and sec["_continuidade"] == 1  # 'Antigo' (2022) manteve-se


class TestMovimentacoes:
    def _pz(self, ato_gab, posts, cands=None, ato_qq=None):
        from datetime import date
        def d(s):
            return date(*map(int, s.split("-"))) if s else None
        return {"nome": "X", "ato_gab": d(ato_gab), "ato_qq": d(ato_qq or ato_gab), "gabs": [11],
                "gab_label": "Gab 11", "nome_norm": "X",
                "postos": [{"cargo": "ESPECIAL", "orgao": "SMS", "adm": d(a), "exo": d(e)}
                           for a, e in posts],
                "cands": cands or []}

    def test_gabinete_para_prefeitura(self):
        from compliance_agent.pcrj import movimentacoes as mv
        # ato no gabinete 2023, admissão PCRJ 2024 → saiu do gabinete p/ Prefeitura
        pz = self._pz("2023-10-01", [("2024-04-08", "2025-01-24")])
        assert mv._gab_para_pref(pz) is not None
        assert mv._pref_para_gab(pz) is None

    def test_prefeitura_para_gabinete(self):
        from compliance_agent.pcrj import movimentacoes as mv
        # admissão PCRJ 2020 anterior ao ato no gabinete 2025 → Prefeitura→gabinete
        pz = self._pz("2025-02-01", [("2020-05-06", None)])
        assert mv._pref_para_gab(pz) is not None
        assert mv._gab_para_pref(pz) is None

    def test_candidato_antes_depois(self):
        from compliance_agent.pcrj import movimentacoes as mv
        pz = self._pz("2024-01-01", [], cands=[
            {"municipio": "NITEROI", "cargo": "VEREADOR", "ano": 2020, "outra_cidade": 1},
            {"municipio": "RIO DE JANEIRO", "cargo": "VEREADOR", "ano": 2024, "outra_cidade": 0}])
        fl = mv._cand_flags(pz)
        assert any("antes da nomeação" in f and "outra cidade" in f for f in fl)  # Niterói 2020
        assert any("no ano da nomeação" in f for f in fl)                          # Rio 2024


class TestCandidatosNominais:
    def test_cand_txt_antes_depois_outra_cidade(self):
        from compliance_agent.pcrj import candidatos_nominais as cn
        antes = cn._cand_txt({"cargo": "VEREADOR", "cidade": "NITEROI", "ano": 2020,
                              "partido": "PT", "outra": 1, "ref": 2024})
        assert "antes da nomeação" in antes and "OUTRA CIDADE" in antes and "Niteroi" in antes
        depois = cn._cand_txt({"cargo": "VEREADOR", "cidade": "RIO DE JANEIRO", "ano": 2024,
                               "partido": "", "outra": 0, "ref": 2022})
        assert "depois da nomeação" in depois


class TestOSPanorama:
    def test_parse_nome_rdp(self):
        from compliance_agent.pcrj import os_panorama as op
        os_, uni, comp, ano, mes = op._parse_nome(
            "https://x/SMS-SPDM-RDP-HOSPITAL-PEDRO-II-Janeiro2026.pdf")
        assert os_ == "SPDM" and ano == 2026 and mes == 1
        assert "HOSPITAL" in uni.upper() and comp == "Janeiro/2026"

    def test_reais(self):
        from compliance_agent.pcrj import os_panorama as op
        assert op._reais(725554.29) == "R$ 725.554,29"


class TestPipeline:
    def test_etapas_conhecidas(self):
        from compliance_agent.pcrj import pipeline
        assert pipeline._ETAPAS == ("camara", "cruzamento", "tse", "relatorio")

    def test_tse_escopo_rj_documentado(self):
        # a fronteira RJ-only deve estar explícita no módulo (decisão do dono)
        from compliance_agent.pcrj import tse_candidatos
        assert tse_candidatos._RIO == "RIO DE JANEIRO"
        assert "RJ" in tse_candidatos._URL.format(ano=2024) or "consulta_cand" in tse_candidatos._URL
