# -*- coding: utf-8 -*-
"""E11 `periciar` (O6.4): grau fora de {0,1,2} rejeitado (não clampado), eixo INCERTO não puxa o global, citação
inexistente invalida o achado, cérebro FORA dos marcadores de documento (e não citável), sem teto de 240k por processo,
versionamento (mesma chave = nada; chave nova = n+1 com supersedes), retomada sem pagar de novo, gates genéricos
(nega OB, ausência), registro do estágio, rotina inativa, Lex sem o limite de 3 processos e os bugs do lex_execucao
(`_chave_processo` pelo dominio/processo_id; radical "medi"). LLM sempre FALSO. Partes de PG só com JFN_EVIDENCIAS_DSN
(VM-2) — sempre num esquema temporário."""
import json
import sqlite3
import uuid
from pathlib import Path

import pytest
import yaml

from compliance_agent import evidencias as EV
from compliance_agent import leitura_integral as LI
from compliance_agent.adaptadores.llm import prompt_seguro as PS
from compliance_agent.aplicacao.estagios import estagio_de
from compliance_agent.aplicacao.estagios import periciar as P
from tests.fluxo_pg import DSN, precisa_pg

PROC = "999001/000001/2026"
DESPACHO = ("Autorizo o pagamento de R$ 10.000,00 à empresa ACME LTDA, CNPJ 11.222.333/0001-81, referente à "
            "nota fiscal 3890, emitida em 10/04/2026, conforme o atesto do fiscal do contrato.")
ATESTO = "Atesto que os serviços foram prestados integralmente no período de março de 2026, conforme medição nº 3."
CEREBRO = {"estado": "OK", "motivo": "1 item",
           "texto": "CONTEXTO DO SEGUNDO CÉREBRO (jfn-brain) sobre X — REFERÊNCIA\n- [fonte: nota casos/acme.md] "
                    "A ACME LTDA foi citada em representação do TCE-RJ por sobrepreço em 2025.",
           "itens": [{"fonte": "nota casos/acme.md"}]}


def _acervo(tmp_path: Path, monkeypatch, docs: list[tuple[str, str]], proc: str = PROC) -> Path:
    monkeypatch.setattr(EV, "ARQUIVO", tmp_path)
    monkeypatch.setattr(LI, "_CONF", set())
    pasta = tmp_path / proc.replace("/", "_")
    (pasta / "texto").mkdir(parents=True)
    man = {"captura_completa": True, "docs_faltantes": [], "docs": []}
    for i, (titulo, texto) in enumerate(docs):
        rel = f"texto/{i:03d}.txt"
        (pasta / rel).write_text(texto, encoding="utf-8")
        man["docs"].append({"i": i, "titulo": titulo, "texto": rel, "ocr": False})
    (pasta / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    return pasta


def _prep(tmp_path, monkeypatch, docs=None, **kw):
    _acervo(tmp_path, monkeypatch, docs or [("Despacho (1000001)", DESPACHO), ("Atesto (1000002)", ATESTO)])
    return P.preparar(PROC, kw.pop("fatos", []), **kw)


def _eixo(grau=0, achados=(), **extra):
    return {"grau": grau, "pontos": {}, "achados": list(achados), "lacunas": [], **extra}


def _resposta(eixos: dict) -> str:
    return json.dumps({"eixos": eixos}, ensure_ascii=False)


# ── grau validado {0,1,2} ───────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("v", [3, -1, 1.5, "2", True, "alto", 10])
def test_grau_fora_da_escala_e_rejeitado_nao_clampado(v):
    assert P.grau_valido(v) == (False, None)
    r = P.validar_eixo("contratacao", _eixo(grau=v), {}, {}, ob_paga=None)
    assert r["rejeitado"] and "fora de {0,1,2}" in r["rejeitado"] and r["grau"] is None


def test_graus_validos():
    assert [P.grau_valido(v) for v in (0, 1, 2, None)] == [(True, 0), (True, 1), (True, 2), (True, None)]


def test_eixo_so_com_grau_rejeitado_vira_indisponivel_e_nao_conta(tmp_path, monkeypatch):
    p = _prep(tmp_path, monkeypatch)
    c = P.interpretar(_resposta({n: _eixo(grau=7) for n in p.eixos}), p, p.fatias[0], ob_paga=None)
    eix = P.agregar(p, [c], cnpj_resolvido=True)
    assert all(e["estado"] == P.INDISPONIVEL and e["grau"] is None for e in eix.values())
    assert P.grau_global(eix) is None


# ── citação ancorada ──────────────────────────────────────────────────────────────────────────────────────
def test_citacao_inexistente_invalida_o_achado_e_derruba_o_grau(tmp_path, monkeypatch):
    p = _prep(tmp_path, monkeypatch)
    f = p.fatias[0]
    inventado = {"doc_id": "sei:1000001", "citacao": "Autorizo o pagamento de R$ 99.999,00 à empresa ACME LTDA",
                 "descricao": "valor pago acima do contratado", "grau": 2, "fundamento": "L14 art. 124"}
    r = P.validar_eixo("preco", _eixo(grau=2, achados=[inventado]), p.originais, f.mapa, ob_paga=None)
    assert r["achados"] == [] and r["descartados"][0]["estado"] == P.FALHA_CITACAO
    assert r["descartados"][0]["motivo"] == "citação não existe no documento"
    assert r["grau"] is None and "INCERTO" in r["nota"]
    outro = {**inventado, "doc_id": "sei:9", "citacao": "Autorizo o pagamento de R$ 10.000,00 à empresa ACME LTDA"}
    assert "não existe no processo" in P.ancorar_achado(outro, p.originais, f.mapa)["motivo"]


def test_citacao_real_e_ancorada_com_offset_e_sha(tmp_path, monkeypatch):
    p = _prep(tmp_path, monkeypatch)
    a = P.ancorar_achado({"doc_id": "sei:1000001", "citacao": "Autorizo   o pagamento de R$ 10.000,00 à empresa",
                          "descricao": "x", "grau": 1, "fundamento": "L4320 art. 63"}, p.originais, p.fatias[0].mapa)
    d = p.originais["sei:1000001"]
    assert a["estado"] == "VERIFICADO" and d["texto"][a["inicio"]:a["fim"]] == a["citacao"]
    assert a["doc_sha"] == d["sha"] and a["pagina"] == 1


def test_gates_genericos_nega_ob_ausencia_e_r4(tmp_path, monkeypatch):
    p = _prep(tmp_path, monkeypatch)
    cit = "Autorizo o pagamento de R$ 10.000,00 à empresa ACME LTDA"
    nega = {"doc_id": "sei:1000001", "citacao": cit, "descricao": "ausência de ordem bancária do pagamento", "grau": 2,
            "fundamento": "L4320 art. 64"}
    r = P.validar_eixo("execucao", _eixo(grau=2, achados=[nega]), p.originais, p.fatias[0].mapa, ob_paga=10000.0)
    assert not r["achados"] and "SIAFE" in r["descartados"][0]["motivo"]
    aus = {**nega, "descricao": "Não consta relatório fotográfico nos autos"}
    r = P.validar_eixo("execucao", _eixo(grau=1, achados=[aus]), p.originais, p.fatias[0].mapa, ob_paga=None)
    assert not r["achados"] and "lacuna" in r["descartados"][0]["motivo"] and r["lacunas"]
    sem_norma = {**nega, "descricao": "pagamento integral com atesto genérico", "fundamento": ""}
    r = P.validar_eixo("execucao", _eixo(grau=2, achados=[sem_norma]), p.originais, p.fatias[0].mapa, ob_paga=None)
    assert r["grau"] == 1 and r["achados"][0]["grau"] == 1


# ── agregação: eixo INCERTO não puxa o global ─────────────────────────────────────────────────────────────
def test_eixo_incerto_nao_puxa_o_global(tmp_path, monkeypatch):
    p = _prep(tmp_path, monkeypatch)
    cit = {"doc_id": "sei:1000001", "citacao": "Autorizo o pagamento de R$ 10.000,00 à empresa ACME LTDA",
           "descricao": "pagamento sem cobertura contratual", "grau": 2, "fundamento": "L4320 art. 60"}
    resp = {n: _eixo(grau=0) for n in p.eixos}
    resp["contabil"] = _eixo(grau=2, achados=[cit], incerto=True)          # o modelo disse: incerto
    resp["preco"] = _eixo(grau=1, achados=[{**cit, "grau": 1}])
    c = P.interpretar(_resposta(resp), p, p.fatias[0], ob_paga=None)
    eix = P.agregar(p, [c], cnpj_resolvido=True)
    assert eix["contabil"]["grau"] == 2 and eix["contabil"]["estado"] == P.INCERTO
    assert eix["preco"]["estado"] == P.PROPOSTA and P.grau_global(eix) == 1
    # sem CNPJ resolvido, o societário é INCERTO mesmo com grau 2 — e também não puxa
    resp["societario"] = _eixo(grau=2, achados=[cit])
    c = P.interpretar(_resposta(resp), p, p.fatias[0], ob_paga=None)
    eix = P.agregar(p, [c], cnpj_resolvido=False)
    assert eix["societario"]["estado"] == P.INCERTO and P.grau_global(eix) == 1


def test_agregacao_entre_fatias_maximo_e_precedencia_dos_pontos(tmp_path, monkeypatch):
    p = _prep(tmp_path, monkeypatch)
    cit = {"doc_id": "sei:1000002", "citacao": ATESTO[:60], "descricao": "atesto genérico", "grau": 1,
           "fundamento": "L14 art. 140"}
    a = P.interpretar(_resposta({n: _eixo(grau=0, pontos={"X2": "conforme"}) for n in p.eixos}), p, p.fatias[0],
                      ob_paga=None)
    b = P.interpretar(_resposta({n: _eixo(grau=1, achados=[cit], pontos={"X2": "desconforme"}) for n in p.eixos}),
                      p, p.fatias[0], ob_paga=None)
    eix = P.agregar(p, [a, b], cnpj_resolvido=True)
    assert eix["execucao"]["grau"] == 1 and eix["execucao"]["pontos"]["X2"] == "desconforme"
    assert eix["execucao"]["fatias_validas"] == 2


def test_abstencao_e_estado_com_motivo(tmp_path, monkeypatch):
    p = _prep(tmp_path, monkeypatch)
    c = P.interpretar('{"absteve": true, "motivo": "texto ilegível"}', p, p.fatias[0], ob_paga=None)
    eix = P.agregar(p, [c], cnpj_resolvido=True)
    assert all(e["estado"] == P.ABSTEVE and e["motivo"] == "texto ilegível" for e in eix.values())
    assert P.interpretar("não é json", p, p.fatias[0], ob_paga=None) is None


# ── cérebro fora dos marcadores (spotlighting) e não citável ──────────────────────────────────────────────
def test_cerebro_entra_fora_dos_marcadores_e_documento_dentro(tmp_path, monkeypatch):
    p = _prep(tmp_path, monkeypatch)
    f = p.fatias[0]
    sis, instr = P.montar_prompt(p, f, ob_paga=10000.0, cerebro=CEREBRO)
    sis_f, prompt = P.prompt_final(sis, instr, f.documentos, "QWERTYUIOP")
    ini, fim = prompt.index("<<<DADOS marcador=QWERTYUIOP>>>"), prompt.index("<<<FIM DOS DADOS marcador=QWERTYUIOP>>>")
    frase = "foi citada em representação do TCE-RJ"
    assert prompt.index(frase) < ini                                           # cérebro ANTES do bloco de dados
    assert frase not in prompt[ini:fim]
    dados = prompt[ini:fim].splitlines()[1:]
    assert dados and all(ln.startswith("QWERTYUIOP| ") for ln in dados)       # todo documento marcado
    assert any("Autorizo o pagamento" in ln for ln in dados)
    assert PS.REGRA_DADOS in sis_f and "não pode ser citado" in instr.lower()
    # citar o cérebro não ancora em documento nenhum
    a = P.ancorar_achado({"doc_id": "sei:1000001", "citacao": "A ACME LTDA foi citada em representação do TCE-RJ",
                          "descricao": "x", "grau": 2, "fundamento": "L14"}, p.originais, f.mapa)
    assert a["estado"] == P.FALHA_CITACAO
    b = P.ancorar_achado({"doc_id": "cerebro", "citacao": "A ACME LTDA foi citada em representação do TCE-RJ",
                          "descricao": "x", "grau": 2, "fundamento": "L14"}, p.originais, f.mapa)
    assert b["estado"] == P.FALHA_CITACAO and "não existe no processo" in b["motivo"]
    assert P.DOC_FATOS not in p.originais                                     # o bloco de fatos também não é citável


def test_cerebro_indisponivel_e_declarado_nao_vira_nada_consta(tmp_path, monkeypatch):
    p = _prep(tmp_path, monkeypatch)
    _, instr = P.montar_prompt(p, p.fatias[0], ob_paga=None,
                               cerebro={"estado": "INDISPONIVEL", "motivo": "cérebro fora do ar"})
    assert "INDISPONIVEL — cérebro fora do ar" in instr and "INDISPONÍVEL (SIAFE não consultado)" in instr


# ── sem teto de 240k, máscara, fatos ──────────────────────────────────────────────────────────────────────
def test_sem_teto_de_240k_todo_o_texto_entra_em_fatias(tmp_path, monkeypatch):
    par = "Cláusula de execução do contrato com medição mensal e atesto do fiscal designado. " * 6
    grande = "\n\n".join(f"Parágrafo {i}: {par}" for i in range(1400))          # ~700 mil caracteres
    assert len(grande) > 600_000
    p = _prep(tmp_path, monkeypatch, docs=[("Contrato (1000003)", grande), ("Despacho (1000001)", DESPACHO)])
    assert p.cobertura["fracao"] == 1.0 and p.cobertura["chars_enviados"] == len(grande.strip()) + len(DESPACHO)
    assert len(p.fatias) >= 600_000 // P.ALVO_CHARS
    for f in p.fatias:
        assert sum(len(d.texto) for d in f.documentos if d.documento_id != P.DOC_FATOS) <= P.ALVO_CHARS + LI.SOBREPOSICAO
    assert not hasattr(P, "TETO_TEXTO")


def test_cpf_mascarado_e_fatos_do_e8_na_fatia(tmp_path, monkeypatch):
    cpf = "123.456.789-00"
    fatos = [{"doc_id": "sei:1000001", "tipo": "data", "valor": "10/04/2026", "descricao": "emissão da NF",
              "citacao": "emitida em 10/04/2026"},
             {"doc_id": "sei:1000001", "tipo": "valor", "valor": "10.000,00", "descricao": "pago",
              "citacao": "R$ 10.000,00"}]
    p = _prep(tmp_path, monkeypatch, docs=[("Despacho (1000001)", DESPACHO + f" Fiscal CPF {cpf}.")], fatos=fatos)
    docs = p.fatias[0].documentos
    assert all(cpf not in d.texto for d in docs)
    bloco = next(d for d in docs if d.documento_id == P.DOC_FATOS).texto
    assert "2026-04-10 [sei:1000001]" in bloco and "R$ 10.000,00" in bloco
    a = P.ancorar_achado({"doc_id": "sei:1000001", "citacao": "Fiscal CPF [CPF_1]", "descricao": "x", "grau": 1,
                          "fundamento": "L14"}, p.originais, p.fatias[0].mapa)
    assert a["estado"] == "VERIFICADO" and cpf in a["citacao"]                 # volta ao original para ancorar


def test_beneficios_so_quando_a_lente_pede():
    assert "beneficios" not in P.eixos_pedidos() and "beneficios" in P.eixos_pedidos(["beneficios"])
    assert set(P.eixos_pedidos()) == {"contratacao", "preco", "execucao", "juridico", "contabil", "societario"}
    with pytest.raises(P.ErroPermanente):
        P.eixos_pedidos(["bombeiros"])


def test_release_ia_e_rotulo_nao_julgado():
    r = P.release_ia(P.MODELO, P.eixos_pedidos())
    assert r["regua"] == "nao_cumprida" and r["rotulo"] == f"NÃO JULGADO — proposta de {P.MODELO}"
    assert r["id"] == P.release_ia(P.MODELO, P.eixos_pedidos())["id"] != P.release_ia("outro", P.eixos_pedidos())["id"]


def test_modelo_e_o_juiz_da_casa():
    from compliance_agent.llm import claude_api
    assert P.MODELO == claude_api.MODELO_JUIZO
    assert all(set(e) >= {"nome", "dominio", "pergunta", "base", "pontos", "absorve"} for e in P.EIXOS)
    assert not any("orgao" in str(e).lower() and "ug" in e for e in P.EIXOS)


# ── Lex sem o limite de 3 processos ────────────────────────────────────────────────────────────────────────
def test_processos_do_fornecedor_sem_limite_de_3():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE ob_orcamentaria_siafe(processo TEXT, credor TEXT, valor REAL, status TEXT, "
                "data_emissao TEXT, tipo_ob TEXT, gd TEXT, numero_ob TEXT, ug_emitente TEXT, exercicio INT)")
    for i in range(7):
        con.execute("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (f"SEI-120001/{i + 1:06d}/2025", "11.222.333/0001-81", 1000.0 * (i + 1), "Contabilizado",
                     "01/02/2025", "OB", None, f"2025OB{i:05d}", "120100", 2025))
    lista = P.processos_do_fornecedor(con, "11222333000181")
    assert len(lista) == 7 and lista[0] == ("120001/000007/2025", 7000.0)
    with pytest.raises(P.ErroPermanente):
        P.processos_do_fornecedor(con, "123")


# ── bugs do lex_execucao ───────────────────────────────────────────────────────────────────────────────────
def test_lex_execucao_chave_processo_pelo_dominio():
    from tools.lex_execucao import _chave_processo
    assert _chave_processo("SEI-330002/031566/24") == _chave_processo("330002/31566/2024") == "330002/31566/2024"
    assert _chave_processo("SEI-080007/010100/1/2023") == "080007/10100/2023"     # antes: '010100/1/2023'
    assert _chave_processo("texto sem número") is None


def test_lex_execucao_radical_medi_nao_casa_medicamento():
    from tools.lex_execucao import _flags
    assert _flags([{"tipo": "Nota de empenho", "ponto": "aquisição de medicamentos para uso imediato"}])["medicao"] == 0
    assert _flags([{"tipo": "Boletim de Medição", "ponto": "medição nº 3"}])["medicao"] == 1
    assert _flags([{"tipo": "Planilha", "ponto": "medicoes mensais"}])["medicao"] == 1


# ── mapa das variantes ────────────────────────────────────────────────────────────────────────────────────
def test_estagio_registrado_e_rotina_inativa():
    assert estagio_de("periciar") is P.ESTAGIO and estagio_de(f"periciar:{PROC}") is P.ESTAGIO
    cfg = yaml.safe_load((P.RAIZ / "config" / "fluxo.yaml").read_text(encoding="utf-8"))
    r = cfg["rotinas"]["periciar_e11"]
    assert r["estagio"] == "E11" and r["ativa"] is False and r.get("bloqueio")
    assert "compliance_agent.aplicacao.estagios.periciar" in " ".join(map(str, r["comando"]))
    import re
    assert re.search(r["efeito"]["log_contem"], "periciar: 3 laudo(s) conferido(s) em sombra.laudos_v2")


# ── PostgreSQL (esquema temporário): versionamento, efeito, retomada ──────────────────────────────────────
@pytest.fixture()
def pg():
    import psycopg
    nome = f"tmp_e11_{uuid.uuid4().hex[:10]}"
    con = psycopg.connect(DSN, autocommit=True)
    try:
        P.aplicar_schema(con, nome)
        yield con
    finally:
        con.execute(f'DROP SCHEMA IF EXISTS "{nome}" CASCADE')
        con.close()


class _Juiz:
    """LLM falso: um achado real (copiado do documento da fatia) no eixo execução e um inventado no preço."""

    def __init__(self, sem_cota_depois: int | None = None):
        self.chamadas: list[tuple[str, str, list]] = []
        self.sem_cota_depois = sem_cota_depois

    def __call__(self, sis, instr, documentos):
        if self.sem_cota_depois is not None and len(self.chamadas) >= self.sem_cota_depois:
            return None
        self.chamadas.append((sis, instr, documentos))
        doc = next(d for d in documentos if d.documento_id != P.DOC_FATOS)
        real = {"doc_id": doc.documento_id, "citacao": doc.texto[:80], "descricao": "atesto genérico", "grau": 1,
                "fundamento": "L14 art. 140"}
        falso = {**real, "citacao": "trecho que não existe em documento nenhum do processo", "grau": 2}
        eixos = {n: _eixo(grau=0) for n in ("contratacao", "juridico", "contabil", "societario")}
        eixos["execucao"] = _eixo(grau=1, achados=[real])
        eixos["preco"] = _eixo(grau=2, achados=[falso])
        return P.Julgamento(texto=_resposta(eixos), motor="claude-opus-5-5@falso")


@precisa_pg
def test_versionamento_idempotencia_e_efeito_no_pg(pg, tmp_path, monkeypatch):
    _acervo(tmp_path, monkeypatch, [("Despacho (1000001)", DESPACHO), ("Atesto (1000002)", ATESTO)])
    j = _Juiz()
    r1 = P.periciar(pg, PROC, j, fatos=[], ob_paga=10000.0, cnpj="11222333000181", cerebro=CEREBRO)
    assert r1["versao"] == 1 and r1["nova_versao"] and len(j.chamadas) == 1
    c = P.conferir(pg, r1)
    assert P.efeito_ok(c) and c["amostra"] == 1
    v = P.laudo_vigente(pg, PROC)["laudo"]
    assert v["eixos"]["preco"]["estado"] == P.INCERTO and v["eixos"]["preco"]["descartados"]
    assert v["grau_global"] == 1 and v["release_ia"]["rotulo"].startswith("NÃO JULGADO")
    assert v["cerebro"]["fontes"] == ["nota casos/acme.md"] and "e12" in v
    # mesma entrada ⇒ nada refeito
    r2 = P.periciar(pg, PROC, j, fatos=[], ob_paga=10000.0, cnpj="11222333000181", cerebro=CEREBRO)
    assert r2["ja_periciado"] and len(j.chamadas) == 1
    assert pg.execute("SELECT count(*) FROM laudos_v2").fetchone()[0] == 1
    # fatos novos do E8 ⇒ chave nova ⇒ versão 2 com supersedes = 1 (a 1 fica, não vigente)
    fatos = [{"doc_id": "sei:1000001", "tipo": "data", "valor": "10/04/2026", "descricao": "NF",
              "citacao": "emitida em 10/04/2026"}]
    r3 = P.periciar(pg, PROC, j, fatos=fatos, ob_paga=10000.0, cnpj="11222333000181", cerebro=CEREBRO)
    assert r3["versao"] == 2 and r3["chave"] != r1["chave"]
    linhas = pg.execute("SELECT versao, vigente, supersedes, id FROM laudos_v2 ORDER BY versao").fetchall()
    assert [(x[0], x[1]) for x in linhas] == [(1, False), (2, True)] and linhas[1][2] == linhas[0][3]
    assert P.efeito_ok(P.conferir(pg, r3)) and not P.conferir(pg, r1)["vigente"]
    # efeito independente: adulterar a citação gravada derruba a conferência
    pg.execute("UPDATE laudos_v2 SET laudo = jsonb_set(laudo, '{eixos,execucao,achados,0,citacao}', '\"X\"') "
               "WHERE vigente")
    assert P.conferir(pg, r3)["divergentes"]


@precisa_pg
def test_sem_cota_no_meio_nao_grava_laudo_e_retoma_sem_pagar_de_novo(pg, tmp_path, monkeypatch):
    par = "Atesto que os serviços foram prestados no mês, conforme a medição e o relatório do fiscal. " * 5
    grande = "\n\n".join(f"Parágrafo {i}: {par}" for i in range(300))
    _acervo(tmp_path, monkeypatch, [("Atesto (1000002)", grande)])
    n = len(P.preparar(PROC, []).fatias)
    assert n >= 2
    with pytest.raises(P.SemCota):
        P.periciar(pg, PROC, _Juiz(sem_cota_depois=1), fatos=[], ob_paga=None, cnpj="11222333000181")
    assert pg.execute("SELECT count(*) FROM laudos_v2").fetchone()[0] == 0
    assert pg.execute("SELECT count(*) FROM laudo_fatias").fetchone()[0] == 1
    j = _Juiz()
    r = P.periciar(pg, PROC, j, fatos=[], ob_paga=None, cnpj="11222333000181")
    assert len(j.chamadas) == n - 1 and r["versao"] == 1 and P.efeito_ok(P.conferir(pg, r))
    assert P.laudo_vigente(pg, PROC)["laudo"]["cobertura"]["fatias_validas"] == n


def test_sinais_do_e10_entram_como_contexto_nao_citavel(tmp_path, monkeypatch):
    p = _prep(tmp_path, monkeypatch)
    sinais = [{"detector": "e10.ob_paga_acima_liquidado", "resumo": "Achados a destacar: T07-DUPLICIDADE-COMP"}]
    _, instr = P.montar_prompt(p, p.fatias[0], ob_paga=None, cerebro={}, sinais=sinais)
    assert "T07-DUPLICIDADE-COMP" in instr and "NÃO podem ser citados" in instr
    a = P.ancorar_achado({"doc_id": "sei:1000001", "citacao": "Achados a destacar: T07-DUPLICIDADE-COMP",
                          "descricao": "x", "grau": 1, "fundamento": "L14"}, p.originais, p.fatias[0].mapa)
    assert a["estado"] == P.FALHA_CITACAO
