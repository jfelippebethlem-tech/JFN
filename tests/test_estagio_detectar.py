# -*- coding: utf-8 -*-
"""E10 `detectar` (O5.3 fatias 1–2, SOMBRA ⚖️): registro e contrato do estágio, catracas (Tier ≠ 1 nunca manchete; teto de
dispensa só em limites_dispensa; todo detector tem exigência na E9), rotina inativa do config/fluxo.yaml e — com PG
(VM-2) — handler idempotente pela chave (detector, escopo), leitura da E9 e efeito conferido, SEMPRE em esquemas
temporários (nunca `dominio` nem `sombra` reais)."""
import re
import sqlite3
import uuid
from pathlib import Path

import pytest

from compliance_agent.aplicacao import detectores as DET
from compliance_agent.aplicacao.estagios import Contexto, ErroPermanente, estagio_de
from compliance_agent.aplicacao.estagios import detectar as D
from compliance_agent.aplicacao.estagios import elegibilidade as E9
from compliance_agent.fluxo import grafo as G
from tests.fluxo_pg import DSN, precisa_pg

REPO = Path(__file__).resolve().parents[1]


def test_estagio_registrado():
    assert estagio_de("detectar") is D.ESTAGIO
    assert estagio_de("detectar:e10.ob_antes_da_liquidacao") is D.ESTAGIO
    assert "cpu_pesado" in D.ESTAGIO.recursos


@pytest.mark.parametrize("did", sorted(DET.MODULOS))
def test_todo_detector_tem_registro_tier3_e_exigencia_na_e9(did):
    reg = E9.carregar_registro()[did]
    det = DET.carregar_detector(did)
    assert det.ID == did and reg["tier"] == 3 and reg["manchete"] is False and reg["manchete_efetiva"] is False
    assert reg["controle_positivo"] and reg["controle_negativo"] and reg["dominio"]
    unidade, exige = D.exigencia(did)
    assert unidade == det.UNIDADE and unidade in E9.UNIDADES
    assert D.versao_execucao(did).startswith(det.VERSAO + "@")


def test_regras_a_portar_apontam_para_o_detector_portado():
    reg = E9.carregar_registro()
    for antigo, novo in (("a_portar.p4_obra_e_lei_8666_tcerj", "e10.p4_fracionamento_objeto"),
                         ("a_portar.p5_dedup_por_processo", "e10.p5_emergencia_recorrente"),
                         ("a_portar.lex_fatos.c_pago_maior_que_nl", "e10.ob_paga_acima_liquidado"),
                         ("a_portar.lex_fatos.c_ob_antes_da_nl", "e10.ob_antes_da_liquidacao")):
        assert reg[antigo]["portar_para"] == novo
        assert E9.exiges_do_detector(antigo) == E9.exiges_do_detector(novo)


# fatia 2: regras do governo_couto_regras portadas com data de corte (portar_para + a mesma exigência, sem a janela)
PORTADOS_COUTO = {"couto.D01": "e10.tg_direta_salto", "couto.D02": "e10.tg_emergencial_incumbente",
                  "couto.D05": "e10.tg_concentracao", "couto.D09": "e10.tg_pico_vespera",
                  "couto.D10": "e10.tg_credor_estreante", "couto.D16": "e10.tg_tac_aceleracao",
                  "couto.D20": "e10.tg_ob_anulada"}
FATIA2 = sorted(set(PORTADOS_COUTO.values()) | {"e10.candidato_p4_siafe", "e10.c_sede_fachada"})


def test_couto_portados_apontam_para_o_detector_generico():
    reg = E9.carregar_registro()
    for antigo, novo in PORTADOS_COUTO.items():
        assert reg[antigo]["portar_para"] == novo and novo in DET.MODULOS
        if antigo in E9.DETECTORES:                                  # couto.D16 nunca teve exigência na E9
            assert E9.exiges_do_detector(antigo) == E9.exiges_do_detector(novo)
    assert E9.exiges_do_detector("e10.candidato_p4_siafe") == {"ob_siafe": "soma_art75"}


def test_fundir_em_aponta_para_detector_registrado():
    reg = E9.carregar_registro()
    for k, e in reg.items():
        for alvo in e.get("fundir_em") or []:
            assert alvo in reg, (k, alvo)


@pytest.mark.parametrize("did", FATIA2)
def test_fatia2_resumo_declara_cobertura(did):
    """A regra única das varreduras por certame/órgão (aposentadas): zero achado só se lê com o denominador — todo
    detector novo declara a cobertura da E9 no resumo, mesmo com universo vazio."""
    r = DET.carregar_detector(did).resumo([], [])
    assert "cobertura" in r and r["disparos"] == 0


def test_catraca_candidato_p4_nunca_afirma_fracionamento():
    """Plano §4 item 5: agregação por credor × teto fora do P4 não emite fracionamento — só candidato_p4, INCERTO."""
    txt = (REPO / "compliance_agent" / "aplicacao" / "detectores" / "candidato_p4_siafe.py").read_text("utf-8")
    corpo = txt.split('"""', 2)[-1]
    assert 'estado="INCERTO"' in corpo and 'estado="INDICIO"' not in corpo
    assert not re.search(r"observacao=.*fracionamento", corpo, re.I)


def test_catraca_teto_literal_fora_de_limites_dispensa():
    """Nenhum teto de dispensa escrito à mão nos detectores do E10 (fonte única: limites_dispensa.py)."""
    for p in (REPO / "compliance_agent" / "aplicacao" / "detectores").glob("*.py"):
        txt = p.read_text(encoding="utf-8")
        assert not re.search(r"\b\d{2,3}[_.]?\d{3}(?:\.\d{2})?\b", txt.split('"""', 2)[-1]), p.name


def test_escopo_invalido_e_permanente():
    with pytest.raises(ErroPermanente):
        D._escopo({"detector": "inventado"})
    assert D._escopo({}, Contexto(no="t", tipo="detectar:e10.ob_antes_da_liquidacao", chave="k", ficha=1,
                                  tentativa=1)) == ("e10.ob_antes_da_liquidacao", None, "todos")
    assert D._escopo({"detector": "e10.p5_emergencia_recorrente", "exercicio": "2025"})[2] == "2025"


def test_rotina_e10_inativa_com_efeito_verificavel():
    r = G.carregar().rotinas["detectar_sombra"]
    assert r.estagio == "E10" and r.ativa is False and "O4.10" in (r.bloqueio or "")
    dets = {a[a.index("--detector") + 1] for a in r.argvs()}
    assert dets == set(DET.MODULOS)
    assert re.search(r.efeito.log_contem, "detectar: 3 achado(s) conferido(s) em sombra.achado (x, escopo todos)")
    assert re.search(r.efeito.log_contem, "detectar: 0 achado(s) conferido(s) em sombra.achado (x, escopo todos)")
    assert not re.search(r.efeito.log_contem, "detectar: EFEITO NÃO CONFERIDO")


# ── PostgreSQL: esquemas temporários (E9 e E10) ─────────────────────────────────────────────────────────────────
_DDL = """
CREATE TABLE ob_orcamentaria_siafe(numero_ob, ug_emitente, exercicio INTEGER, data_emissao, nl, credor, valor, status,
  status_envio, tipo_regularizacao);
CREATE TABLE nl_siafe(numero, ug_emitente, exercicio INTEGER, status, valor, data_emissao, credor);
INSERT INTO nl_siafe VALUES ('2025NL1','010100',2025,'Contabilizado',1000,'05/03/2025','22222222000100'),
  ('2025NL2','010100',2025,'Contabilizado',1000,'05/03/2025','22222222000100');
INSERT INTO ob_orcamentaria_siafe VALUES
  ('2025OB1','010100',2025,'01/03/2025','2025NL1','22222222000100',600,'Contabilizado','',''),
  ('2025OB2','010100',2025,'02/03/2025','2025NL2','22222222000100',600,'Contabilizado','','');
"""


@pytest.fixture()
def fonte(tmp_path):
    p = tmp_path / "compliance.db"
    c = sqlite3.connect(p)
    c.executescript(_DDL)
    c.commit()
    c.close()
    return p


@pytest.fixture()
def pg():
    e9, e10 = f"tmp_e9_{uuid.uuid4().hex[:10]}", f"tmp_e10_{uuid.uuid4().hex[:10]}"
    con = E9.conectar(DSN, "public")
    try:
        E9.aplicar_schema(con, e9)

        def veredito(chave, v):
            con.execute(f'INSERT INTO "{e9}".elegibilidade (unidade, chave, exiges, versao, entrada_hash) '
                        "VALUES ('ob_siafe', %s, %s::jsonb, %s, 'h') ON CONFLICT (unidade, chave) DO UPDATE "
                        "SET exiges = EXCLUDED.exiges", (chave, '{"execucao": "%s", "universo": "%s"}' % (v, v), E9.VERSAO))
        # (E9-9, 24/11: o C-OB<NL lê `universo`; o veredito sintético vai nas duas para o teste de mecânica)
        veredito("010100|2025OB1|2025", "E")
        veredito("010100|2025OB2|2025", "?:SEM_NE")      # anterior à NL também, mas indeterminada na E9
        yield con, e9, e10, veredito
    finally:
        for s in (e9, e10):
            con.execute(f'DROP SCHEMA IF EXISTS "{s}" CASCADE')
        con.close()


def _ctx(did):
    return Contexto(no="teste", tipo=f"detectar:{did}", chave=f"detectar:{did}:todos", ficha=1, tentativa=1)


@precisa_pg
def test_handler_idempotente_le_a_e9_e_efeito_conferido(pg, fonte):
    con, e9, e10, veredito = pg
    did = "e10.ob_antes_da_liquidacao"
    payload = {"detector": did, "fonte": str(fonte), "dsn": DSN, "esquema": e10, "esquema_e9": e9}
    res = D.ESTAGIO.handler(payload, _ctx(did))
    assert res.efeito["achados"] == 1 and res.efeito["achados_novos"] == 1 and res.eventos   # só a OB1 ('E')
    assert res.efeito["resumo"]["por_veredito"] == {"?:SEM_NE": 1, "E": 1}
    assert D.ESTAGIO.efeito(payload, _ctx(did), res) is True
    again = D.ESTAGIO.handler(payload, _ctx(did))                        # mesma entrada: 0 linha, mesma rodada
    assert again.efeito["achados_novos"] == 0 and not again.eventos and again.efeito["rodada"] == res.efeito["rodada"]
    assert con.execute(f'SELECT count(*) FROM "{e10}".achado').fetchone()[0] == 1
    estado, status = con.execute(f'SELECT estado, status FROM "{e10}".achado').fetchone()
    assert (estado, status) == ("INDICIO", "triagem")
    # efeito INDEPENDENTE: declarar mais do que há, ou adulterar o hash gravado, é recusado
    falso = D.Resultado(efeito={**again.efeito, "achados": 2})
    assert D.ESTAGIO.efeito(payload, _ctx(did), falso) is False
    con.execute(f"UPDATE \"{e10}\".execucao_regra SET entradas_hash = repeat('0', 64) WHERE origem LIKE 'e10:%:010100%'")
    assert D.ESTAGIO.efeito(payload, _ctx(did), again) is False


@precisa_pg
def test_sem_elegivel_zero_achado_declarado_e_conferido(pg, fonte):
    con, e9, e10, veredito = pg
    veredito("010100|2025OB1|2025", "I:TRANSFERENCIA")
    did = "e10.ob_antes_da_liquidacao"
    payload = {"detector": did, "fonte": str(fonte), "dsn": DSN, "esquema": e10, "esquema_e9": e9}
    res = D.ESTAGIO.handler(payload, _ctx(did))
    assert res.efeito["achados"] == 0 and res.efeito["resumo_novo"] is True
    assert D.ESTAGIO.efeito(payload, _ctx(did), res) is True             # 0 achado DECLARADO, com o resumo
    n = con.execute(f"SELECT (resultado->>'ob_com_nl_na_base')::int FROM \"{e10}\".execucao_regra "
                    "WHERE origem LIKE '%:resumo'").fetchone()[0]
    assert n == 2                                                        # o denominador fica gravado


# ── O8.5: vínculo achado → processo SEI (os 58 achados do ensaio r2 saíam com processo NULL e o E11 ficava sem nada) ─
from decimal import Decimal  # noqa: E402

from compliance_agent.aplicacao.detectores import Disparo  # noqa: E402
from compliance_agent.dominio.achado import Fato, Papel  # noqa: E402


def _ob(num, ug="010100", ex=2025, papel=Papel.SUPORTE, tipo="ob"):
    return Fato(papel=papel, tipo=tipo, fonte="ob_orcamentaria_siafe", referencia=num, valor=Decimal("10"),
                dados={"ug": ug, "exercicio": ex})


def _disp(*fatos, processo=None, identidade=None):
    return Disparo(chave="k", grupo="g", estado="INDICIO", observacao="o", entradas={}, processo=processo,
                   evidencias=list(fatos), identidade=identidade)


def test_vinculo_ob_pelo_campo_processo_do_siafe_na_chave_canonica():
    v = D.vinculo_processo(_disp(_ob("2025OB1"), _ob("2025OB2")),
                           {("010100", "2025OB1", "2025"): "SEI-010100/123/2025",
                            ("010100", "2025OB2", "2025"): "SEI 010100/000123/25"})
    assert v["estado"] == "VINCULADO" and v["processos"] == [{"processo": "010100/000123/2025", "via": ["ob_siafe"]}]


def test_contabil_antes_do_conserto_nao_tinha_processo():
    """Reproduz o defeito: o detector C-PAGO>NL declara processo=None; sem o vínculo, o achado ia sem processo."""
    d = _disp(Fato(papel=Papel.SUPORTE, tipo="nl", fonte="nl_siafe", referencia="2025NL1"), _ob("2025OB1"))
    assert d.processo is None and D._processo_unico(d, None) is None
    v = D.vinculo_processo(d, {("010100", "2025OB1", "2025"): "SEI-010100/000007/2025"})
    assert D._processo_unico(d, v) == "010100/000007/2025"


@pytest.mark.parametrize("ob_proc, causa", [
    (None, "ob_siafe: a fonte não tem o campo processo"),
    ({}, "ob_siafe: OB não encontrada na fonte"),
    ({("010100", "2025OB1", "2025"): "E-12/001/123/2020"}, "ob_siafe: grafia sem processo SEI canônico"),
    ({("010100", "2025OB1", "2025"): ""}, "ob_siafe: sem processo na fonte"),
])
def test_sem_processo_provavel_indisponivel_com_motivo(ob_proc, causa):
    v = D.vinculo_processo(_disp(_ob("2025OB1")), ob_proc)
    assert v["estado"] == "INDISPONIVEL" and v["processos"] == [] and v["causas"] == [causa] and v["motivo"]


def test_fato_de_contexto_nao_liga_processo():
    v = D.vinculo_processo(_disp(_ob("2025OB1", papel=Papel.CONTEXTO, tipo="ob_anulada")),
                           {("010100", "2025OB1", "2025"): "SEI-010100/000007/2025"})
    assert v["estado"] == "INDISPONIVEL" and "nenhum fato de suporte" in v["motivo"]


def test_identidade_parcial_nao_sustenta_vinculo_e_nao_vaza_chave_processo():
    import json
    v = D.vinculo_processo(_disp(_ob("2025OB1"), identidade="indeterminado"),
                           {("010100", "2025OB1", "2025"): "SEI-010100/000007/2025"})
    assert v["estado"] == "INDISPONIVEL" and v["candidatos"][0]["candidato"] == "010100/000007/2025"
    assert '"processo"' not in json.dumps(v)        # E11/E14 casam pela chave `processo`: candidato não liga
    assert D.vinculo_processo(_disp(_ob("2025OB1"), identidade="forte"),
                              {("010100", "2025OB1", "2025"): "SEI-010100/000007/2025"})["estado"] == "VINCULADO"


def test_contrato_liga_ao_processo_mae_e_varios_processos_nao_escolhe_um():
    ct = Fato(papel=Papel.SUPORTE, tipo="contrato", fonte="contratos_tcerj", referencia="SEI-330002/000010/2024")
    d = _disp(ct, _ob("2025OB1"), processo="SEI-330002/10/2024")
    v = D.vinculo_processo(d, {("010100", "2025OB1", "2025"): "SEI-010100/000007/2025"})
    assert [p["processo"] for p in v["processos"]] == ["010100/000007/2025", "330002/000010/2024"]
    assert v["processos"][1]["via"] == ["contratos_tcerj", "detector"]
    assert D._processo_unico(d, v) is None          # vários: todos no resultado, nenhum escolhido


def test_processos_das_obs_casa_ug_numero_e_exercicio():
    c = sqlite3.connect(":memory:")
    c.executescript("CREATE TABLE ob_orcamentaria_siafe(numero_ob, ug_emitente, exercicio INTEGER, processo);"
                    "INSERT INTO ob_orcamentaria_siafe VALUES ('2025OB1','010100',2025,'SEI-010100/000007/2025'),"
                    "('2025OB1','020200',2025,'SEI-020200/000009/2025');")
    assert D.processos_das_obs(c, {("010100", "2025OB1", "2025")}) == {
        ("010100", "2025OB1", "2025"): "SEI-010100/000007/2025"}
    c2 = sqlite3.connect(":memory:")
    c2.execute("CREATE TABLE ob_orcamentaria_siafe(numero_ob, ug_emitente, exercicio)")
    assert D.processos_das_obs(c2, {("010100", "2025OB1", "2025")}) is None


def _cnpj_valido(raiz12: str) -> str:
    """CNPJ com DV calculado (credor sintético com identidade `forte`, sem literal no código)."""
    d = [int(x) for x in raiz12]
    for pesos in ([5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]):
        r = sum(a * b for a, b in zip(d, pesos)) % 11
        d.append(0 if r < 2 else 11 - r)
    return "".join(map(str, d))


@pytest.fixture()
def fonte_com_processo(tmp_path):
    p = tmp_path / "compliance.db"
    c = sqlite3.connect(p)
    c.executescript(_DDL.replace("tipo_regularizacao);", "tipo_regularizacao, processo);")
                    .replace("'Contabilizado','','')", "'Contabilizado','','','SEI-010100/000007/2025')")
                    .replace("22222222000100", _cnpj_valido("222222220001")))
    c.commit()
    c.close()
    return p


@precisa_pg
def test_handler_liga_achado_ao_processo_e_suja_o_e11(pg, fonte_com_processo):
    con, e9, e10, veredito = pg
    did = "e10.ob_antes_da_liquidacao"
    payload = {"detector": did, "fonte": str(fonte_com_processo), "dsn": DSN, "esquema": e10, "esquema_e9": e9}
    res = D.ESTAGIO.handler(payload, _ctx(did))
    assert res.efeito["achados"] == 1 and res.efeito["com_processo"] == 1 and res.efeito["processo_indisponivel"] == 0
    assert {"fonte": "detectar", "tipo": "achado_processo", "chave": "010100/000007/2025",
            "detalhe": {"detector": did, "escopo": "todos", "rodada": res.efeito["rodada"]}} in res.eventos
    assert con.execute(f'SELECT processo FROM "{e10}".execucao_regra WHERE origem NOT LIKE %s',
                       ("%:resumo",)).fetchone()[0] == "010100/000007/2025"
    assert D.ESTAGIO.efeito(payload, _ctx(did), res) is True
    # o vínculo gravado é conferido de novo da fonte: adulterado, o efeito recusa
    con.execute(f"UPDATE \"{e10}\".execucao_regra SET resultado = jsonb_set(resultado, '{{vinculo_processo,estado}}',"
                " '\"INDISPONIVEL\"') WHERE origem NOT LIKE '%:resumo'")
    assert D.ESTAGIO.efeito(payload, _ctx(did), res) is False


@precisa_pg
def test_fonte_sem_campo_processo_declara_indisponivel(pg, fonte):
    con, e9, e10, veredito = pg
    did = "e10.ob_antes_da_liquidacao"
    payload = {"detector": did, "fonte": str(fonte), "dsn": DSN, "esquema": e10, "esquema_e9": e9}
    res = D.ESTAGIO.handler(payload, _ctx(did))
    assert res.efeito["com_processo"] == 0 and res.efeito["processo_indisponivel"] == 1
    assert res.efeito["resumo"]["vinculo_processo"]["causas_indisponivel"] == {
        "ob_siafe: a fonte não tem o campo processo": 1}
    assert not [e for e in res.eventos if e["tipo"] == "achado_processo"]
    assert D.ESTAGIO.efeito(payload, _ctx(did), res) is True
