# -*- coding: utf-8 -*-
"""Resolver de duplicidade por NOTA FISCAL (NÃO REINVENTAR #4: só a NF fecha a duplicidade de contrato contínuo).

Medido em 11/11/2026: dos 300 pares 🟡 da perícia, 299 tinham T07-DUPLICIDADE-COMP = INDICIO, com 4.865
competências dobradas, 62.151 OBs envolvidas e 26.354 processos SEI distintos — só 696 deles com texto local.
O T07 parava em INDICIO para sempre porque ninguém lia a NF. Aqui: regra determinística primeiro (mesma NF
em 2 processos → CONFIRMADO; NFs e meses distintos → AFASTADO; sem texto → fila de captura), juízo LLM grátis
só onde a regra não decide, e o T07 da perícia LÊ o resultado.
"""
import json
import sqlite3

import pytest

from compliance_agent import auditoria_contrato as ac
from compliance_agent import pericia_sweep as ps
from tools import resolver_duplicidade_nf as R

CNPJ = "13944767000110"
CNPJ_FMT = "13.944.767/0001-10"


def _nf(numero, mes="MARÇO/2026", valor="4.497,00", extra=""):
    return (f"DANFSe v1.0\nDocumento Auxiliar da NFS-e\nNúmero da NFS-e\n{numero}\nCompetência da NFS-e\n01/06/2026\n"
            f"EMITENTE DA NFS-e\nPrestador do Serviço\nCNPJ / CPF / NIF\n{CNPJ_FMT}\n"
            f"Descrição do Serviço\nPrestação de Serviços de Limpeza. Competência {mes} – Posto SEFAZ {extra}\n"
            f"Valor do Serviço\nR$ {valor}\nValor Líquido da NFS-e\nR$ {valor}\n")


def _arquivar(raiz, tag, docs):
    """Monta data/sei_arquivo/<tag>/ no formato do sei_arquivar (manifest + texto/*.txt)."""
    d = raiz / tag
    (d / "texto").mkdir(parents=True)
    man = {"processo": tag.replace("_", "/"), "docs": []}
    for i, (titulo, tipo, texto) in enumerate(docs):
        nome = f"texto/{i:03d}_doc.txt"
        (d / nome).write_text(texto, encoding="utf-8")
        man["docs"].append({"i": str(i), "titulo": titulo, "tipo": tipo, "fase": "", "texto": nome})
    (d / "manifest.json").write_text(json.dumps(man), encoding="utf-8")


def _ob(n, comp, valor, proc, re_=None, status="Contabilizado", data=None):
    mm, aaaa = comp.split("/")
    return {"numero_ob": n, "status": status, "nl": "NL" + n, "re": re_ or ("RE" + n), "pd": "PD" + n,
            "valor": valor, "competencia": comp, "data_emissao": data or f"10/{mm}/{aaaa}", "processo": proc}


# série mensal 01..06/2026 de R$ 30.000,00 com 03/2026 dobrada (2 OBs, REs distintos)
def _serie(proc_a="SEI-040002/001422/2026", proc_b="SEI-040002/001999/2026", valor_b=30000.0):
    obs = [_ob(f"OB{m}", f"{m:02d}/2026", 30000.0, f"SEI-040002/00100{m}/2026") for m in (1, 2, 4, 5, 6)]
    obs.append(_ob("OB3A", "03/2026", 30000.0, proc_a))
    obs.append(_ob("OB3B", "03/2026", valor_b, proc_b))
    # OB excluída sem reemissão (T02 INDICIO): o 🟡 real é T07 + T02 (291 dos 300 em 11/11/2026)
    obs.append(_ob("OBX", "05/2026", 7000.0, "", status="Excluído"))
    return obs


@pytest.fixture
def arq(tmp_path, monkeypatch):
    raiz = tmp_path / "sei_arquivo"
    raiz.mkdir()
    cache = tmp_path / "sei_cache"
    cache.mkdir()
    monkeypatch.setattr(R, "ARQUIVO", raiz)
    monkeypatch.setattr(R, "CACHE", cache)
    return raiz


# ───────────────────────── normalização e extração ─────────────────────────
@pytest.mark.parametrize("bruto,tag", [
    ("SEI-040002/001422/2026", "040002_001422_2026"),
    ("SEI 330020/0878/2025", "330020_000878_2025"),
    ("SEI 330020/000211/21", "330020_000211_2021"),
    ("270006/002251/2024", "270006_002251_2024"),
    ("2026NE08640", None), ("E-20/001.00226/2024", None), ("", None), (None, None),
])
def test_tag_do_processo(bruto, tag):
    assert R.tag_processo(bruto) == tag


def test_extrai_nf_da_danfse():
    nfs = R.extrair_nfs([{"titulo": "Nota Fiscal - NF 93 Três Rios (130930879)", "tipo": "outros",
                          "texto": _nf(93)}])
    assert len(nfs) == 1
    nf = nfs[0]
    assert nf["numero"] == "93" and nf["cnpj"] == CNPJ
    assert nf["competencia"] == "03/2026"          # a do serviço, não "Competência da NFS-e 01/06/2026"
    assert nf["valor"] == pytest.approx(4497.0)


@pytest.mark.parametrize("texto,comp", [
    ("Competência: Março/2026", "03/2026"),
    ("referente ao mês de fevereiro de 2025", "02/2025"),
    ("serviços prestados no período de 01/07/2024 a 31/07/2024", "07/2024"),
    ("Competência 11/2023", "11/2023"),
    ("Competência da NFS-e\n01/06/2026", None),
])
def test_competencia_do_texto(texto, comp):
    assert R.competencia_do_texto(texto) == comp


MERITI = """PREFEITURA DA CIDADE DE SÃO JOÃO DE MERITI
Nota Nº - Série
0000000187 - 1
NOTA FISCAL ELETRÔNICA DE SERVIÇOS
Data da Emissão: 02/02/2024 10:24:05
Competência: 02/2024
PRESTADOR DE SERVIÇOS
Razão Social: CONSORCIO RJ CIDADAO
CNPJ/CPF: 21.602.870/0002-91 IM: 46654
TOMADOR DE SERVIÇOS
CNPJ/CPF: 03.161.283/0001-41 IM:
DISCRIMINAÇÃO DOS SERVIÇOS
MANUTENÇÃO DO PROGRAMA POUPA TEMPO RJ REFERENTE AO MÊS DE JANEIRO,
NO PERÍODO DE 01 A 31 DE JANEIRO DE 2.024.
VALOR TOTAL DA NOTA = R$ 5.082.000,00
"""


def test_nf_municipal_competencia_do_servico_e_filial_do_consorcio():
    """Medido no dry-run de 11/11/2026 (SEI-150001/002101/2024): o campo 'Competência: 02/2024' da NF de Meriti é o
    mês de EMISSÃO; o serviço é janeiro. E o emitente é a filial /0002 do consórcio credor /0001."""
    nfs = R.extrair_nfs([{"titulo": "Nota Fiscal n° 187-1 janeiro 2024 (68310913)", "tipo": "nota_fiscal",
                          "texto": MERITI}])
    assert nfs[0]["numero"] == "187" and nfs[0]["competencia"] == "01/2024" and nfs[0]["comp_desc"]
    assert nfs[0]["valor"] == pytest.approx(5082000.0)
    sem_titulo = R.extrair_nfs([{"titulo": "Nota Fiscal 187", "tipo": "", "texto": MERITI}])
    assert sem_titulo[0]["competencia"] == "01/2024"
    assert R.mesmo_grupo("21602870000291", "21602870000100")


def test_cache_com_corte_fixo_de_400_nao_e_texto(arq, monkeypatch):
    cache = {"conteudo_documentos": [{"doc": str(i), "conteudo": "x" * 400} for i in range(3)]}
    monkeypatch.setattr(R, "_ler_cache", lambda tag: cache)
    assert R.textos_do_processo("080002_017893_2024") == []


def test_processo_de_varios_meses_nao_e_fracionado_pela_soma_de_todas_as_nfs(arq):
    """Processo-continente com NF de jan a mai: a soma das NFs de OUTROS meses não 'cabe' as OBs de um mês."""
    _arquivar(arq, "040002_001422_2026", [
        ("Nota Fiscal - NF 90", "outros", _nf(90, "JANEIRO/2026", "30.000,00")),
        ("Nota Fiscal - NF 91", "outros", _nf(91, "FEVEREIRO/2026", "30.000,00")),
        ("Nota Fiscal - NF 93", "outros", _nf(93, "MARÇO/2026", "30.000,00"))])
    r = R.resolver_par(CNPJ, "200100", _serie(proc_b="SEI-040002/001422/2026"))
    assert r[0]["veredito"] != "AFASTADO", r


def test_mesma_nf_casada_por_valor_em_duas_obs_do_mesmo_processo_e_confirmado(arq):
    _arquivar(arq, "040002_001422_2026", [("Nota Fiscal - NF 93", "outros", _nf(93, valor="30.000,00")),
                                          ("Nota Fiscal - NF 80", "outros", _nf(80, "DEZEMBRO/2025", "12.000,00"))])
    r = R.resolver_par(CNPJ, "200100", _serie(proc_b="SEI-040002/001422/2026"))
    assert r[0]["veredito"] == "CONFIRMADO", r


def test_documento_que_nao_e_nf_nao_vira_nf():
    assert R.extrair_nfs([{"titulo": "Contrato (130930858)", "tipo": "contrato",
                           "texto": "cláusula: a nota fiscal nº 12 deverá ser emitida"}]) == []


# ───────────────────────── camada determinística ─────────────────────────
def test_mesma_nf_em_dois_processos_e_confirmado(arq):
    for tag in ("040002_001422_2026", "040002_001999_2026"):
        _arquivar(arq, tag, [("Nota Fiscal - NF 93 Três Rios", "outros", _nf(93))])
    r = R.resolver_par(CNPJ, "200100", _serie(), favorecido="REDENTOR")
    assert [x["veredito"] for x in r] == ["CONFIRMADO"]
    assert r[0]["competencia"] == "03/2026" and r[0]["camada"] == "deterministica"
    assert "93" in r[0]["motivo"]


def test_nfs_distintas_em_meses_distintos_e_afastado(arq):
    _arquivar(arq, "040002_001422_2026", [("Nota Fiscal - NF 93", "outros", _nf(93, "MARÇO/2026"))])
    _arquivar(arq, "040002_001999_2026", [("Nota Fiscal - NF 88", "outros", _nf(88, "FEVEREIRO/2026"))])
    r = R.resolver_par(CNPJ, "200100", _serie())
    assert r[0]["veredito"] == "AFASTADO", r
    assert "02/2026" in r[0]["motivo"] and "03/2026" in r[0]["motivo"]
    nfs = json.loads(r[0]["nfs_json"])
    assert {n["numero"] for v in nfs.values() for n in v} == {"93", "88"}


def test_nf_distinta_de_retroativo_e_afastado(arq):
    _arquivar(arq, "040002_001422_2026", [("Nota Fiscal - NF 93", "outros", _nf(93))])
    _arquivar(arq, "040002_001999_2026", [("Nota Fiscal - NF 120", "outros",
                                           _nf(120, extra="Referente retroativo da repactuação 2026"))])
    r = R.resolver_par(CNPJ, "200100", _serie())
    assert r[0]["veredito"] == "AFASTADO", r
    assert "retroativ" in r[0]["motivo"].lower()


def test_processo_unico_com_obs_que_cabem_na_nf_e_afastado(arq):
    """Duas OBs no MESMO processo de pagamento somando ≤ o bruto das NFs dele = um pagamento fracionado."""
    _arquivar(arq, "040002_001422_2026", [("Nota Fiscal - NF 93", "outros", _nf(93, valor="40.000,00")),
                                          ("Nota Fiscal - NF 94", "outros", _nf(94, valor="25.000,00"))])
    obs = _serie(proc_b="SEI-040002/001422/2026")
    r = R.resolver_par(CNPJ, "200100", obs)
    assert r[0]["veredito"] == "AFASTADO", r
    assert "fracion" in r[0]["motivo"].lower()


def test_processo_sem_texto_e_pendente_captura_e_vai_para_a_fila(arq):
    _arquivar(arq, "040002_001422_2026", [("Nota Fiscal - NF 93", "outros", _nf(93))])
    r = R.resolver_par(CNPJ, "200100", _serie())            # 040002_001999_2026 não está no arquivo
    assert r[0]["veredito"] == "PENDENTE_CAPTURA"
    assert r[0]["capturar"] == ["SEI-040002/001999/2026"]
    assert "SEI-040002/001999/2026" in r[0]["motivo"]


def test_texto_do_cache_zst_tambem_conta(arq, monkeypatch):
    _arquivar(arq, "040002_001422_2026", [("Nota Fiscal - NF 93", "outros", _nf(93, "MARÇO/2026"))])
    cache = {"conteudo_documentos": [{"doc": "Nota Fiscal - NF 88 (1)", "conteudo": _nf(88, "FEVEREIRO/2026") + "Tributação municipal. " * 20}]}
    monkeypatch.setattr(R, "_ler_cache", lambda tag: cache if tag == "040002_001999_2026" else None)
    r = R.resolver_par(CNPJ, "200100", _serie())
    assert r[0]["veredito"] == "AFASTADO", r


# ───────────────────────── camada de juízo ─────────────────────────
def _ambiguo(arq):
    """NFs distintas, MESMO mês, sem palavra de retroativo/glosa: a regra não decide."""
    _arquivar(arq, "040002_001422_2026", [("Nota Fiscal - NF 93", "outros", _nf(93))])
    _arquivar(arq, "040002_001999_2026", [("Nota Fiscal - NF 101", "outros", _nf(101)),
                                          ("Despacho", "tramitacao", "Pagamento da parcela do posto extra de Três Rios.")])


def test_sem_llm_o_ambiguo_fica_indeterminado(arq):
    _ambiguo(arq)
    r = R.resolver_par(CNPJ, "200100", _serie(), gerar=None)
    assert r[0]["veredito"] == "INDETERMINADO" and r[0]["camada"] == "deterministica"


def test_juizo_com_citacao_literal_conferida_decide(arq):
    _ambiguo(arq)
    resp = json.dumps({"veredito": "afastado", "nf_por_ob": {"OB3A": "93", "OB3B": "101"},
                       "motivo": "a NF 101 paga posto extra, não o mesmo serviço",
                       "citacao_literal": "Pagamento da parcela do posto  extra de Três Rios"})
    chamadas = []
    r = R.resolver_par(CNPJ, "200100", _serie(), gerar=lambda p, s: chamadas.append(p) or resp)
    assert len(chamadas) == 1 and "101" in chamadas[0] and "93" in chamadas[0]
    assert r[0]["veredito"] == "AFASTADO" and r[0]["camada"] == "juizo"
    assert "posto" in r[0]["citacao"]


def test_juizo_com_citacao_inventada_cai_para_indeterminado(arq):
    _ambiguo(arq)
    resp = json.dumps({"veredito": "confirmado", "nf_por_ob": {}, "motivo": "pago em dobro",
                       "citacao_literal": "a NF 93 foi paga duas vezes"})
    r = R.resolver_par(CNPJ, "200100", _serie(), gerar=lambda p, s: resp)
    assert r[0]["veredito"] == "INDETERMINADO"
    assert "citação" in r[0]["motivo"].lower()


def test_juizo_que_quebra_nao_derruba_e_fica_indeterminado(arq):
    _ambiguo(arq)
    def boom(p, s):
        raise RuntimeError("cota")
    r = R.resolver_par(CNPJ, "200100", _serie(), gerar=boom)
    assert r[0]["veredito"] == "INDETERMINADO"


# ───────────────────────── gravação, fila e CLI ─────────────────────────
def _banco(tmp_path, obs):
    db = tmp_path / "c.db"
    c = sqlite3.connect(db)
    c.execute("""CREATE TABLE ob_orcamentaria_siafe(numero_ob TEXT, status TEXT, nl TEXT, re TEXT, pd TEXT,
        valor REAL, competencia TEXT, data_emissao TEXT, processo TEXT, nome_credor TEXT, credor TEXT,
        ug_emitente TEXT)""")
    c.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  [(o["numero_ob"], o["status"], o["nl"], o["re"], o["pd"], o["valor"], o["competencia"],
                    o["data_emissao"], o["processo"], "REDENTOR", CNPJ, "200100") for o in obs])
    c.execute("""CREATE TABLE sei_fila_captura (numero_sei TEXT PRIMARY KEY, sei_norm TEXT, motivo TEXT,
        total_pago REAL, n_docs INTEGER, visto_em TEXT)""")
    c.execute("INSERT INTO sei_fila_captura VALUES ('SEI-040002/001999/2026','x','pedido à mão',1,0,'t')")
    c.execute(ps._DDL)
    c.commit()
    c.row_factory = sqlite3.Row
    ps._gravar(c, ps.periciar(CNPJ, "200100", c))
    c.commit()
    c.close()
    return db


def test_rodar_grava_tabela_enfileira_sem_rebaixar_e_repericia(arq, tmp_path):
    _arquivar(arq, "040002_001422_2026", [("Nota Fiscal - NF 93", "outros", _nf(93))])
    obs = _serie(proc_b="SEI-040002/001888/2026")
    db = _banco(tmp_path, obs)
    c = sqlite3.connect(db)
    assert c.execute("SELECT grau FROM pericia_fornecedor").fetchone()[0] == "🟡"
    c.execute("INSERT INTO sei_fila_captura VALUES ('SEI-040002/001888/2026','x','pedido à mão',1,0,'t')")
    c.commit(); c.close()
    out = R.rodar(db=db, gerar=None)
    assert out["pares"] == 1 and out["vereditos"] == {"PENDENTE_CAPTURA": 1}
    c = sqlite3.connect(db)
    row = c.execute("SELECT cnpj,ug,competencia,veredito,camada FROM resolucao_duplicidade").fetchone()
    assert row == (CNPJ, "200100", "03/2026", "PENDENTE_CAPTURA", "deterministica")
    # INSERT OR IGNORE: o pedido à mão não é rebaixado
    assert c.execute("SELECT motivo FROM sei_fila_captura WHERE numero_sei='SEI-040002/001888/2026'"
                     ).fetchone()[0] == "pedido à mão"
    ach = json.loads(c.execute("SELECT achados_json FROM pericia_fornecedor").fetchone()[0])
    t07 = next(a for a in ach if a["codigo"] == "T07-DUPLICIDADE-COMP")
    assert t07["status"] == "INDICIO" and "SEI-040002/001888/2026" in t07["evidencia"]


def test_rodar_afastado_tira_o_par_do_amarelo_no_banco(arq, tmp_path):
    _arquivar(arq, "040002_001422_2026", [("Nota Fiscal - NF 93", "outros", _nf(93, "MARÇO/2026"))])
    _arquivar(arq, "040002_001999_2026", [("Nota Fiscal - NF 88", "outros", _nf(88, "FEVEREIRO/2026"))])
    db = _banco(tmp_path, _serie())
    out = R.rodar(db=db, gerar=None)
    assert out["vereditos"] == {"AFASTADO": 1}
    c = sqlite3.connect(db)
    grau, aj = c.execute("SELECT grau, achados_json FROM pericia_fornecedor").fetchone()
    t07 = next(a for a in json.loads(aj) if a["codigo"] == "T07-DUPLICIDADE-COMP")
    assert t07["status"] == "AFASTADO" and grau == "🟢"
    assert R.pares_amarelos(c) == []


def test_rodar_enfileira_processo_novo(arq, tmp_path):
    db = _banco(tmp_path, _serie(proc_a="SEI-040002/001777/2026"))
    R.rodar(db=db, gerar=None)
    c = sqlite3.connect(db)
    motivo = c.execute("SELECT motivo FROM sei_fila_captura WHERE numero_sei='SEI-040002/001777/2026'").fetchone()
    assert motivo and motivo[0].startswith("duplicidade_nf")


def test_dry_run_nao_escreve(arq, tmp_path):
    db = _banco(tmp_path, _serie(proc_a="SEI-040002/001777/2026"))
    out = R.rodar(db=db, gerar=None, dry_run=True)
    assert out["vereditos"] == {"PENDENTE_CAPTURA": 1}
    c = sqlite3.connect(db)
    assert not c.execute("SELECT 1 FROM sqlite_master WHERE name='resolucao_duplicidade'").fetchone()
    assert not c.execute("SELECT 1 FROM sei_fila_captura WHERE numero_sei='SEI-040002/001777/2026'").fetchone()


def test_motivo_da_fila_e_inscricao_em_massa():
    """O drenador põe alvo de CASO à frente de inscrição em massa; esta é em massa."""
    from tools import sei_integra_fila as F
    assert any("duplicidade_nf".startswith(p) for p in F._MOTIVOS_EM_MASSA)


# ───────────────────────── T07 lê a resolução ─────────────────────────
def _t07(obs, resol):
    return ac._t07_duplicidade({"obs": obs, "resolucao_duplicidade": resol})


def _res(veredito, obs=("OB3A", "OB3B"), motivo="m"):
    return {"03/2026": {"veredito": veredito, "motivo": motivo, "camada": "deterministica",
                        "obs": list(obs), "citacao": "NF 93"}}


def test_t07_sem_resolucao_continua_indicio():
    assert _t07(_serie(), {})["status"] == "INDICIO"


def test_t07_confirmado():
    h = _t07(_serie(), _res("CONFIRMADO", motivo="NF 93 em 2 processos"))
    assert h["status"] == "CONFIRMADO" and "NF 93 em 2 processos" in h["evidencia"]


def test_t07_afastado_tira_o_par_do_amarelo():
    h = _t07(_serie(), _res("AFASTADO", motivo="NFs de meses distintos"))
    assert h["status"] == "AFASTADO" and "NFs de meses distintos" in h["evidencia"]
    assert ac.auditar_contrato({"obs": _serie()})["grau"] == "🟡"
    res = ac.auditar_contrato({"obs": _serie(), "resolucao_duplicidade": _res("AFASTADO")})
    assert res["grau"] == "🟢", res["resumo"]


def test_t07_pendente_captura_continua_indicio_dizendo_o_que_falta():
    h = _t07(_serie(), _res("PENDENTE_CAPTURA", motivo="capturar SEI-040002/001999/2026"))
    assert h["status"] == "INDICIO" and "SEI-040002/001999/2026" in h["evidencia"]


def test_t07_indeterminado_continua_indicio():
    h = _t07(_serie(), _res("INDETERMINADO", motivo="NFs distintas no mesmo mês"))
    assert h["status"] == "INDICIO" and "NFs distintas no mesmo mês" in h["evidencia"]


def test_t07_resolucao_velha_com_ob_nova_nao_vale():
    """A resolução cobriu OB3A e OB3B; se a competência ganhou OB nova, o veredito não a cobre."""
    obs = _serie() + [_ob("OB3C", "03/2026", 30000.0, "SEI-040002/002000/2026")]
    h = _t07(obs, _res("AFASTADO"))
    assert h["status"] == "INDICIO"


def test_enriquecer_le_a_tabela_e_tolera_ausencia(tmp_path):
    c = sqlite3.connect(tmp_path / "x.db")
    d = ps.enriquecer({"obs": [], "favorecido": "X", "orgao": "200100", "_cnpj": CNPJ}, c)
    assert d.get("resolucao_duplicidade") in (None, {})
    R.garantir_tabela(c)
    R.gravar(c, [{"cnpj": CNPJ, "ug": "200100", "competencia": "03/2026", "veredito": "AFASTADO",
                  "motivo": "m", "nfs_json": "{}", "citacao": "c", "camada": "deterministica",
                  "obs": ["OB3A", "OB3B"]}])
    d = ps.enriquecer({"obs": [], "favorecido": "X", "orgao": "200100", "_cnpj": CNPJ}, c)
    assert d["resolucao_duplicidade"]["03/2026"]["veredito"] == "AFASTADO"
    assert d["resolucao_duplicidade"]["03/2026"]["obs"] == ["OB3A", "OB3B"]
