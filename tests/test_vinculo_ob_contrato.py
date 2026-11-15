# -*- coding: utf-8 -*-
"""Vínculo OB ↔ contrato pelos AUTOS do processo de pagamento. Dados 100% sintéticos (repositório público)."""
import json
import sqlite3
from datetime import date

import pytest

from compliance_agent import pericia_contabil as pc
from compliance_agent import vinculo_ob_contrato as vo
from compliance_agent.llm import verificacao as V
from tests.test_pericia_contabil import _base_estado

PAG = "9999990000012024"           # processo de pagamento da OB do credor D na base sintética
CNPJ_D = "44444444000144"


def _autos(raiz, chave, docs: dict[str, str], orfaos: dict[str, str] | None = None):
    p = raiz / f"{chave[:6]}_{chave[6:12]}_{chave[12:]}"
    (p / "texto").mkdir(parents=True)
    man = {"processo": vo.formatar(chave), "docs": []}
    for i, (nome, txt) in enumerate(docs.items()):
        (p / "texto" / nome).write_text(txt, encoding="utf-8")
        man["docs"].append({"i": str(i), "titulo": nome, "texto": f"texto/{nome}"})
    for nome, txt in (orfaos or {}).items():
        (p / "texto" / nome).write_text(txt, encoding="utf-8")
    (p / "manifest.json").write_text(json.dumps(man), encoding="utf-8")


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(vo, "ARQUIVO", tmp_path / "arq")
    return _base_estado(tmp_path)


def _regra(db):
    con = pc._con_ro(db)
    try:
        return vo.rodar_regra(con)
    finally:
        con.close()


DESPACHO = ("Encaminho para pagamento a nota fiscal 101, competência 03/2024, referente ao contrato "
            "celebrado no processo SEI-100001/000004/2024, objeto aquisição de mesas.")


def test_controle_positivo_autos_citam_o_processo_do_contrato(base, tmp_path):
    _autos(tmp_path / "arq", PAG, {"000_despacho.txt": DESPACHO})
    linhas, ao_modelo, est = _regra(base)
    assert est["resolvido"][0] == 1 and not ao_modelo
    (ln,) = linhas
    assert ln[:3] == ("2024OB00011", "300300", 2024)
    assert ln[3] == "D" and ln[9] == vo.REGRA and ln[10] == V.VERIFICADO
    assert V.citacao_existe(ln[8], DESPACHO) and "100001/000004/2024" in ln[8]
    antes = {r["id"]: r for r in pc.avaliar_estado(base, corte=date(2026, 7, 1))}["D"]
    assert antes["motivo"] == "ob_do_credor_fora_do_processo"
    assert vo.gravar(base, linhas) == 1
    d = {r["id"]: r for r in pc.avaliar_estado(base, corte=date(2026, 7, 1))}["D"]
    assert d["categoria"] != "INDETERMINADO", d
    assert d["pago"] == pytest.approx(60_000.0) and d["vinculo"] == "autos_do_pagamento"
    assert "pelos autos" in d["ressalvas"]


def test_controle_negativo_pendente_nao_muda_classe(base, tmp_path):
    # Termo de Ajuste de Contas: indenização, não pagamento do contrato — PENDENTE
    _autos(tmp_path / "arq", PAG, {"000_tac.txt": DESPACHO + " TERMO DE AJUSTE DE CONTAS nº 3/2024."})
    linhas, _, est = _regra(base)
    assert est["tac"][0] == 1 and all(x[10] == V.PENDENTE for x in linhas)
    vo.gravar(base, linhas)
    d = {r["id"]: r for r in pc.avaliar_estado(base, corte=date(2026, 7, 1))}["D"]
    assert d["categoria"] == "INDETERMINADO" and d["motivo"] == "ob_do_credor_fora_do_processo"


def test_dois_contratos_citados_nao_se_escolhe_por_regra(base, tmp_path):
    con = sqlite3.connect(base)
    con.execute("INSERT INTO contratos_tcerj (id,processo,sei_norm,data_contratacao,valor_contrato,status,cnpj,"
                "vig_inicio,vig_fim,objeto) VALUES ('D2','SEI-100001/000044/2024','1000010000442024',"
                "'2024-02-01',10.0,'Ativo',?,'01/02/2024','31/01/2025','AQUISIÇÃO')", (CNPJ_D,))
    con.commit()
    con.close()
    _autos(tmp_path / "arq", PAG, {"000_d.txt": DESPACHO + " Ver também SEI-100001/000044/2024."})
    linhas, ao_modelo, _ = _regra(base)
    assert linhas == [] and ao_modelo == {(PAG, CNPJ_D): ["1000010000042024", "1000010000442024"]}


def test_ob_anterior_ao_contrato_deixa_o_par_pendente(base, tmp_path):
    con = sqlite3.connect(base)
    con.execute("INSERT INTO ob_orcamentaria_siafe (numero_ob,ug_emitente,ug_pagadora,data_emissao,status,credor,"
                "processo,valor,exercicio) VALUES ('2023OB00077','300300','300300','10/03/2023','Contabilizado',?,"
                "'SEI-999999/000001/2024',1.0,2023)", (CNPJ_D,))
    con.commit()
    con.close()
    _autos(tmp_path / "arq", PAG, {"000_despacho.txt": DESPACHO})
    linhas, _, _ = _regra(base)
    assert len(linhas) == 2 and all(x[10] == V.PENDENTE for x in linhas)


def test_documento_orfao_fora_do_manifesto_nao_e_lido(base, tmp_path):
    _autos(tmp_path / "arq", PAG, {"000_nf.txt": "Nota fiscal 101 sem menção a contrato."},
           orfaos={"zz_alheio.txt": DESPACHO})
    linhas, ao_modelo, est = _regra(base)
    assert linhas == [] and not ao_modelo and est["sem_citacao"][0] == 1


def test_cnpj_nao_vira_numero_de_processo():
    assert vo.chaves_citadas("Credor 11430698000100 - EMPRESA") == set()
    assert vo.chaves_citadas("SEI-080007/003095/23 e SEI 260007 / 010076 / 2025") == {
        "0800070030952023", "2600070100762025"}


# ───────────── leitura do modelo: citação conferida e dupla leitura ─────────────

CAND = ["1000010000042024", "1000010000442024"]


def _resp(proc, cit, mais=False):
    return json.dumps({"processo_contrato": proc, "mais_de_um": mais, "citacao": cit})


def test_leitura_com_citacao_literal_e_numero_no_trecho_passa():
    k, _, motivo = vo.conferir_leitura(_resp("100001/000004/2024", "referente ao contrato celebrado no processo "
                                                                    "SEI-100001/000004/2024"), CAND, DESPACHO)
    assert k == "1000010000042024" and motivo == ""


@pytest.mark.parametrize("resp,motivo", [
    (_resp("100001/000004/2024", "pagamento do contrato SEI-100001/000004/2024"), "literalmente"),   # parafraseou
    (_resp("100001/000004/2024", "Encaminho para pagamento a nota fiscal 101"), "não está no trecho"),
    (_resp("100001/000099/2024", "processo SEI-100001/000004/2024"), "candidato"),                  # inventou
    (_resp("", "", mais=True), "mais de um"),
    ("isto não é json", "JSON"),
    (None, "vazia"),
])
def test_leitura_que_nao_confere_e_descartada(resp, motivo):
    k, _, m = vo.conferir_leitura(resp, CAND, DESPACHO)
    assert k is None and motivo in m


def test_dupla_leitura_so_verifica_quando_as_duas_concordam():
    boa = _resp("100001/000004/2024", "contrato celebrado no processo SEI-100001/000004/2024")
    outra = _resp("100001/000044/2024", "Pagamento referente ao SEI-100001/000044/2024")
    texto = DESPACHO + " Pagamento referente ao SEI-100001/000044/2024."
    ctx = {"p0": ((PAG, CNPJ_D), CAND, texto)}
    assert vo.decidir_modelo({"p0a": boa, "p0b": boa}, ctx)[(PAG, CNPJ_D)][2] == V.VERIFICADO
    d = vo.decidir_modelo({"p0a": boa, "p0b": outra}, ctx)[(PAG, CNPJ_D)]
    assert d[2] == V.PENDENTE and "divergem" in d[3]
    assert vo.decidir_modelo({"p0a": boa, "p0b": None}, ctx)[(PAG, CNPJ_D)][2] == V.PENDENTE


def test_excerto_e_recorte_literal_do_texto():
    docs = [("d1", "linha sem nada\nReferente ao contrato\nprocesso SEI-100001/000004/2024\nfim")]
    exc = vo.excerto(docs)
    for ln in exc.splitlines()[1:]:
        assert ln in docs[0][1]


def test_fila_de_captura_pula_o_arquivado_e_ordena_por_valor(tmp_path, monkeypatch):
    monkeypatch.setattr(vo, "ARQUIVO", tmp_path / "arq")
    _autos(tmp_path / "arq", "1000010000992024", {"000.txt": "x" * 400})
    d = date(2024, 5, 1)
    jan = {"1": [(date(2024, 1, 1), date(2024, 12, 31), 1_000.0)], "00394460000141": [(date(2024, 1, 1), None, 9e9)]}
    pares = {("1000010000992024", "1"): [("o1", "u", 2024, d, 500.0)],          # já arquivado: fora
             ("1000010000982024", "1"): [("o2", "u", 2024, d, 10.0)],
             ("1000010000972024", "1"): [("o3", "u", 2024, d, 20.0)],
             ("1000010000952024", "1"): [("o5", "u", 2024, date(2026, 1, 1), 999.0)],   # fora da vigência
             ("1000010000962024", "2"): [("o4", "u", 2024, d, 99.0)],        # credor sem indeterminado: fora
             ("1000010000942024", "00394460000141"): [("o6", "u", 2024, d, 9e8)]}  # União: nunca é o contratado
    fila = vo.fila_captura(pares, jan)
    assert [e["sei"] for e in fila] == ["SEI-100001/000097/2024", "SEI-100001/000098/2024"]


def test_fila_escore_limitado_ao_valor_dos_contratos():
    d = date(2024, 5, 1)
    jan = {"1": [(date(2024, 1, 1), None, 100.0)], "2": [(date(2024, 1, 1), None, 5_000.0)]}
    pares = {("1000010000932024", "1"): [("o1", "u", 2024, d, 1e9)],      # banco da folha: R$ 1 bi, contrato de 100
             ("1000010000922024", "2"): [("o2", "u", 2024, d, 3_000.0)]}
    fila = vo.fila_captura(pares, jan)
    assert fila[0]["sei"] == "SEI-100001/000092/2024" and fila[1]["score"] == 100.0


def test_excerto_traz_a_citacao_do_candidato_mesmo_longe_do_inicio():
    enchimento = "\n".join(f"processo de pagamento linha {i} referente ao objeto" for i in range(2000))
    docs = [("d1", enchimento), ("d2", "Despacho final\nconforme contrato SEI-100001/000004/2024\nok")]
    exc = vo.excerto(docs, teto=3000, candidatos=["1000010000042024"])
    assert "SEI-100001/000004/2024" in exc and len(exc) <= 3000


def test_citacao_so_com_o_numero_nao_liga_o_pagamento():
    texto = "Capa. PROCESSO Nº SEI-100001/000004/2024. Ver também SEI-100001/000044/2024."
    k, _, m = vo.conferir_leitura(_resp("100001/000004/2024", "PROCESSO Nº SEI-100001/000004/2024."), CAND, texto)
    assert k is None and "não liga o pagamento" in m


def test_custom_id_do_lote_identifica_o_par_e_nao_a_posicao(tmp_path, monkeypatch):
    monkeypatch.setattr(vo, "ARQUIVO", tmp_path / "arq")
    _autos(tmp_path / "arq", PAG, {"000.txt": DESPACHO})
    a, ca = vo.montar_itens({(PAG, CNPJ_D): CAND, ("1000010000012024", "1"): CAND})
    b, cb = vo.montar_itens({("1000010000012024", "1"): CAND, (PAG, CNPJ_D): CAND})
    assert dict(a) == dict(b) and ca.keys() == cb.keys()
    assert all(len(cid) <= 64 and cid.replace("_", "").isalnum() for cid, _ in a)


@pytest.mark.parametrize("bruto,trecho,rebaixa", [
    ("SEI-080007/011667-D/2023", "Processo SEI-080007/011667/2023", True),     # desdobramento de ata
    ("SEI-360343/000277D/2022", "Processo SEI-360343/000277/2022", True),
    ("SEI-100001/000004/2024", "ATA DE REGISTRO DE PREÇOS Nº 1/2024 - SEI-100001/000004/2024", True),
    ("SEI-100001/000004/2024", "referente ao contrato celebrado no processo SEI-100001/000004/2024", False),
])
def test_desdobramento_de_ata_e_citacao_em_ata_nao_verificam(bruto, trecho, rebaixa):
    assert bool(vo.motivo_rebaixa(bruto, trecho)) is rebaixa


# 14/11/2026: a OB de R$ 8,85 mi de uma parceria NOVA (UG 170100, Lei 13.019) foi ligada ao contrato de R$ 1 mi da SETUR
# porque o processo do contrato aparece num "Comprovante de Capacidade Técnica" — a entidade cita a parceria ANTERIOR como
# experiência. Citação em prova de experiência não diz o que a OB paga.
@pytest.mark.parametrize("fonte,trecho,rebaixa", [
    ("texto/030_comprovante_de_capacidade_tecnica_lei_13_019_2014_122750279.txt — Comprovante de Capacidade Técnica "
     "Lei 13.019/2014 (122750279)", "corrobora o processo SEI-050001/000746/2025", True),
    ("texto/012_atestado_de_capacidade_tecnica_1.txt — Atestado de Capacidade Técnica (1)",
     "prestou serviços no processo SEI-050001/000746/2025", True),
    ("texto/040_relatorio.txt — Relatório", "experiência anterior comprovada no processo SEI-050001/000746/2025", True),
    ("texto/005_nota_fiscal.txt — Nota Fiscal (99)", "referente ao contrato do processo SEI-050001/000746/2025", False),
])
def test_citacao_em_prova_de_experiencia_nao_verifica(fonte, trecho, rebaixa):
    assert bool(vo.motivo_rebaixa("SEI-050001/000746/2025", trecho, fonte)) is rebaixa


def test_reconferir_rebaixa_o_ja_gravado(base, tmp_path):
    con = sqlite3.connect(base)
    con.execute("UPDATE contratos_tcerj SET processo='SEI-100001/000004-B/2024' WHERE id='D'")
    con.commit()
    con.close()
    _autos(tmp_path / "arq", PAG, {"000_despacho.txt": DESPACHO})
    con = pc._con_ro(base)
    por_cred, info = vo.indice_contratos(con)
    con.close()
    linhas = vo.linhas_do_par(PAG, CNPJ_D, [("2024OB00011", "300300", 2024, date(2024, 4, 10), 60_000.0)], "D",
                              "1000010000042024", {**info, "D": (info["D"][0], info["D"][1], "SEI-100001/000004/2024")},
                              "f", DESPACHO, vo.REGRA, V.VERIFICADO)
    assert linhas[0][10] == V.VERIFICADO
    vo.gravar(base, linhas)
    assert vo.reconferir(base) == {"rebaixadas": 1}
    d = {r["id"]: r for r in pc.avaliar_estado(base, corte=date(2026, 7, 1))}["D"]
    assert d["categoria"] == "INDETERMINADO"


# ── modelo diário: não reler o par já lido (14/11/2026) ────────────────────────────────────────────────
def test_modelo_diario_nao_rele_o_par_ja_decidido():
    """O `modelo` agendado depois da `regra` noturna só manda ao lote o que NUNCA foi lido; INDISPONÍVEL volta
    depois de `DIAS_RELER_INDISPONIVEL` (o acervo cresce com a captura da VM-2)."""
    ao = {("1", "C1"): ["a", "b"], ("2", "C1"): ["a", "b"], ("3", "C2"): ["x", "y"], ("4", "C2"): ["x", "y"]}
    lidos = {vo.id_par("1", "C1"): {"em": "2026-11-13", "estado": V.VERIFICADO},
             vo.id_par("2", "C1"): {"em": "2026-11-13", "estado": V.PENDENTE},
             vo.id_par("3", "C2"): {"em": "2026-11-13", "estado": V.INDISPONIVEL},
             vo.id_par("4", "C2"): {"em": "2026-10-01", "estado": V.INDISPONIVEL}}
    assert set(vo.pares_nao_lidos(ao, lidos, date(2026, 11, 14))) == {("4", "C2")}
    assert set(vo.pares_nao_lidos(ao, {}, date(2026, 11, 14))) == set(ao)


def test_registro_de_lidos_ilegivel_nao_quebra(tmp_path):
    arq = tmp_path / "lidos.json"
    arq.write_text("{quebrado", encoding="utf-8")
    assert vo.ler_lidos(arq) == {}
    vo.registrar_lidos(arq, {("9", "C9"): (None, "", V.INDISPONIVEL, "x")}, date(2026, 11, 14))
    assert vo.ler_lidos(arq)[vo.id_par("9", "C9")] == {"em": "2026-11-14", "estado": V.INDISPONIVEL}


# ── estrato "fecha contrato" da fila de captura (14/11/2026) ─────────────────────────────────────────
def test_perícia_declara_o_processo_que_falta_ao_contrato_indeterminado(base):
    d = {r["id"]: r for r in pc.avaliar_estado(base, corte=date(2026, 7, 1))}["D"]
    assert d["motivo"] == "ob_do_credor_fora_do_processo"
    assert d["processos_fora"] == {"processos": [PAG], "obs_sem_processo": 0}


def _r(motivo, valor, procs, sem=0):
    return {"motivo": motivo, "valor_atualizado": valor,
            "processos_fora": {"processos": procs, "obs_sem_processo": sem}}


def test_fila_fecha_contrato_so_o_que_a_captura_pode_fechar():
    res = [
        _r("ob_do_credor_fora_do_processo", 900.0, ["1111110000012024", "1111110000022024"]),   # fecha: 450 cada
        _r("a_menor_com_ob_fora_do_processo", 300.0, ["1111110000012024"]),                      # fecha: +300
        _r("ob_do_credor_fora_do_processo", 10_000.0, ["2222220000012024"], sem=1),              # OB sem processo
        _r("ob_do_credor_fora_do_processo", 10_000.0, [f"33333300000{i}2024" for i in range(1, 5)]),  # faltam 4
        _r("ob_do_credor_fora_do_processo", 10_000.0, ["4444440000012024", "5555550000012024"]),  # um já lido
        _r("vinculo_ambiguo", 10_000.0, ["6666660000012024"]),                                    # outro motivo
        _r("ob_do_credor_fora_do_processo", 10_000.0, []),                                        # nada a capturar
    ]
    fila = vo.fila_fecha_contrato(res, capturado=lambda k: k == "4444440000012024")
    assert [(e["sei"], e["score"], e["n_contratos"]) for e in fila] == [
        ("SEI-111111/000001/2024", 750.0, 2), ("SEI-111111/000002/2024", 450.0, 1)]
    assert all("FECHA_CONTRATO" in e["flags"] for e in fila)


def test_ob_sem_processo_na_base_tem_motivo_proprio_e_nao_vai_a_fila(base):
    # controle: com a OB do credor D num processo de pagamento, o motivo é "fora do processo";
    # tirado o processo da OB (como no SIAFE 1, 2021–2023), nenhuma captura resolve — motivo próprio
    con = sqlite3.connect(base)
    con.execute("UPDATE ob_orcamentaria_siafe SET processo='' WHERE credor=?", (CNPJ_D,))
    con.commit()
    con.close()
    d = {r["id"]: r for r in pc.avaliar_estado(base, corte=date(2026, 7, 1))}["D"]
    assert d["categoria"] == "INDETERMINADO" and d["motivo"] == "ob_do_credor_sem_processo_na_base"
    assert d["processos_fora"] == {"processos": [], "obs_sem_processo": 1}
    assert "ob_do_credor_sem_processo_na_base" in pc.MOTIVOS
    assert vo.fila_fecha_contrato([d], capturado=lambda k: False) == []


# ── processo dominante (14/11/2026: pagamento que cita 47× o contrato não registrado e 2× o registrado) ─────
OUTRO_PROC = "SEI-100001/000777/2021"


def test_autos_que_falam_sobretudo_de_outro_processo_nao_verificam(base, tmp_path):
    docs = {"000_despacho.txt": DESPACHO}
    docs.update({f"{i:03d}_nl.txt": f"Nota de liquidação referente ao contrato do processo {OUTRO_PROC}."
                 for i in range(1, 7)})
    _autos(tmp_path / "arq", PAG, docs)
    linhas, _, est = _regra(base)
    assert est["resolvido"][0] == 1
    assert all(x[10] == V.PENDENTE and "sobretudo outro processo" in x[11] for x in linhas)


def test_codigo_de_barras_nao_vira_processo_dominante():
    docs = [("d", "linha digitável 012505/086918/7189 " * 9 + " processo SEI-100001/000004/2024")]
    c = vo.contagem_processos(docs, PAG)
    assert "0125050869187189" not in c and vo.motivo_dominante(c, "1000010000042024") == ""


def test_reconferir_rebaixa_vinculo_de_processo_dominado(base, tmp_path):
    _autos(tmp_path / "arq", PAG, {"000_despacho.txt": DESPACHO})
    vo.gravar(base, _regra(base)[0])
    p = tmp_path / "arq" / f"{PAG[:6]}_{PAG[6:12]}_{PAG[12:]}"
    man = json.loads((p / "manifest.json").read_text())
    for i in range(1, 7):
        (p / "texto" / f"x{i}.txt").write_text(f"pagamento do contrato {OUTRO_PROC}", encoding="utf-8")
        man["docs"].append({"i": str(i), "titulo": "NL", "texto": f"texto/x{i}.txt"})
    (p / "manifest.json").write_text(json.dumps(man))
    assert vo.reconferir(base)["rebaixadas"] == 1


def test_ug_repetida_do_siafe_nao_vira_processo_dominante():
    c = vo.contagem_processos([("d", "UG 166100/166100/2023 " * 9)], PAG)
    assert not c
