from compliance_agent.pericia_sweep import _fora_da_bateria, eh_ente_publico


def test_ente_publico_pelo_nome_abreviado_do_siafe():
    for nome in ("Inst.de Prev.serv.mun.de Nova Iguacu-previni", "NITEROI PREV", "Pref Munic De Campos De Goytacazes",
                 "Fundo Munic.de Saude De Niteroi/cgr Metro.ii", "Conselho Nacional De Justic - Cnj",
                 "Sup.regional Do D.p.f. No Rj.", "Universidade Federal Do Rio Grande Do Norte",
                 "Instituto Nacional De Seguro Social.", "PLANO DE BENEFICIOS RJPREV CD", "Fundacao Amazonprev"):
        assert eh_ente_publico(nome), nome


def test_empresa_e_entidade_privada_nunca_sao_ente():
    for nome in ("Mobiliza For Rent Ltda", "PREVENT SENIOR PRIVATE OPERADORA DE SAUDE LTDA", "ALGAR TELECOM S/A",
                 "Empr.proc.de Dados Prev.social Dataprev", "Fund.p/o Vest.da Unesp Julio De M.f.-vunesp",
                 "INSTITUIÇÃO ADVENTISTA ESTE BRAS. DE PREV. E ASSIST", "PREVINE SAUDE OCUPACIONAL"):
        assert not eh_ente_publico(nome), nome


def test_receita_decide_quando_tem_natureza():
    assert eh_ente_publico("FMS DE SAO FRANCISCO", "", "Fundo Público da Administração Direta Municipal")
    # razão com "DO ESTADO DO RIO DE JANEIRO" e natureza privada: Fetranspor continua fornecedor
    assert not eh_ente_publico("Fed. Emp.de Transp.de Pas.do E.rj-fetranspor",
                               "FEDERACAO DAS EMPRESAS DE MOBILIDADE DO ESTADO DO RIO DE JANEIRO", "Entidade Sindical")
    assert _fora_da_bateria("29138278000101", "Pref Munic De Nova Iguacu")
    assert not _fora_da_bateria("35208086000127", "Mobiliza For Rent Ltda")
