# -*- coding: utf-8 -*-
"""Retratos do JFN no vault (compliance_agent/vault_retratos.py): INDISPONÍVEL nunca vira zero, CPF nunca sai inteiro,
todo retrato declara fonte e estado, fonte fora do ar não apaga a nota boa, e nada é regravado sem mudança.
Tudo em `tmp_path`, sem rede (as rotas do painel são simuladas)."""
from __future__ import annotations

import json
import re

import pytest

from compliance_agent import cerebro_compartilhado as C
from compliance_agent import propagacao as P
from compliance_agent import vault_retratos as V

CPF = "52998224725"                      # CPF de teste com dígito verificador válido
CPF_FMT = "529.982.247-25"
CNPJ = "60853934000106"


def _pericia(placar_estado="VERIFICADO — régua determinística"):
    linha = {"orgao": "SEHIS - SECRETARIA", "fornecedor": "CONSTRUTORA X S.A.", "fornecedor_doc": "60.853.934/0001-06",
             "processo": "SEI-490001/001323/2024", "contrato": "2025007357", "valor_atualizado": 1000000.0, "fonte_valor": "",
             "pago": 1902706.43, "diferenca": 902706.43, "n_obs": 1, "vig_inicio": "2025-09-26", "vig_fim": "2026-09-26",
             "ressalvas": f"a fonte não publica termos aditivos; sócio {CPF_FMT}", "verificacao": "PENDENTE",
             "prova_primaria": "1 OB Contabilizada do SIAFE no processo"}
    pf = dict(linha, fornecedor="PESSOA FISICA", fornecedor_doc=CPF, processo="SEI-000001/000001/2025", diferenca=10.0)
    esf = {"n": 40411, "placar": {"A_MAIOR": 62, "CONFORME": 4569, "INDETERMINADO": 34941},
           "rotulos": {"A_MAIOR": "Pago acima do valor contratado"}, "pago_determinado": 1297655242.92,
           "devido_determinado": 1378336270.91, "excesso_a_maior": 3580594.29, "adiantado": None, "deficit_encerrado": 0.0,
           "corte": "2026-11-13", "fonte_pago": "SIAFE-Rio — OB Orçamentária, status Contabilizado",
           "proveniencia": {"fonte_contratos": "contratos_tcerj", "cobertura": "OB a partir de 2021"},
           "verificacao": {"placar": placar_estado, "listas": "PENDENTE — cada linha é indício a conferir"},
           "motivos_indeterminado": [{"motivo": "vinculo_ambiguo", "texto": "par aponta para mais de um contrato", "n": 7446}],
           "a_maior": [linha, pf], "duplicidades": {"aferivel": False}}
    return {"ok": True, "gerado_em": "2026-11-14T18:11:28", "regua": "pericia", "tolerancia": "1%",
            "definicoes": {"indeterminado": "sem base"}, "esferas": {"Estado do RJ": esf}}


def _couto():
    itens = [{"id": "D14-x", "regra_ou_hipotese": "D14 · Empresa Y paga na vigência de sanção", "grau": "🔴",
              "orgao": "FUNDACAO (324200)", "valor_ob": 235487.1, "fonte": "SIAFE-Rio; CEIS", "cnpj": "00700484000181",
              "explicacao_inocente": "sanção de outro ente", "proximo_passo": "conferir NL",
              "prova_primaria": ["OB 2026OB00332 · UG 324200 · R$ 47.097,42 (SIAFE, Contabilizado)"], "verificacao": "VERIFICADO"},
             {"id": "H3-z", "regra_ou_hipotese": "H3 · hipótese do modelo SEGREDO-PENDENTE", "grau": "🟡", "verificacao": "PENDENTE"}]
    return {"ok": True, "gestao": {"inicio": "2026-03-23", "ate": "2026-11-13", "fonte": "DOERJ"},
            "placar": {"pago": 60851365642.08, "n_obs": 173756, "pago_anterior": None, "contratacoes": 6956,
                       "valor_contratado": 4602719356.54},
            "atos": {"fonte": "DOERJ", "pessoal": [{"ato": "EXONERAR", "nome": "FULANO DE TAL NOMEADO"}]},
            "contratacoes": {"fonte": "TCE-RJ", "cobertura": "valor CONTRATADO", "n": 6956, "por_orgao": [],
                             "lista": [{"processo": "SEI-030001/047295/2026", "data": "2026-10-08", "valor": 97736000.0,
                                        "orgao": "SEEDUC - X", "fornecedor": "FUNDAÇÃO Z", "doc": CPF, "modalidade": "Licitação"}]},
            "execucao": {"fonte": "SIAFE-Rio 2 — OB Contabilizado", "cobertura": "OB emitidas", "fim": "2026-11-13"},
            "pontos_atencao": {"gerado_em": "2026-11-14T15:08:24", "verificacao_definicao": "VERIFICADO = conferível", "itens": itens},
            "ressalva": "Indício não é acusação."}


def _orcamento(ano=2026, mes=None):
    tot = {"dotacao_inicial": 100.0, "dotacao_atualizada": None, "empenhado": 0.0, "liquidado": 40.0, "pago_siafe": 30.0,
           "pago_balancete": 35.0, "faltam": {"pago_siafe": 7}, "taxa_empenho": None, "taxa_pago": None,
           "estados": {"dotacao_inicial": "VERIFICADO", "dotacao_atualizada": "INDISPONIVEL", "empenhado": "PENDENTE",
                       "liquidado": "PENDENTE", "pago_siafe": "INDISPONIVEL", "pago_balancete": "PENDENTE"}}
    return {"ok": True, "exercicio": ano, "periodo": f"exercício de {ano}", "visao_descricao": "por órgão",
            "exercicios": [{"ano": 2026}], "meses_com_execucao": [1, 2], "proveniencia": {"fonte": "TFE; SIAFE", "cobertura": "44 órgãos"},
            "colunas": {"pago_siafe": "soma das OB Contabilizadas"}, "total": tot, "ressalva": "taxa baixa não é irregularidade",
            "orgaos": [dict(tot, orgao="20", nome="Fazenda")], "mes": mes}


def _periodo(fid, medida, anos):
    return {"ok": True, "fonte": {"id": fid, "rotulo": f"Série {fid}", "medidas": [medida], "rotulos_medidas": {medida: "Valor"},
                                  "campo_data": "data", "origem": "origem"},
            "cobertura": {"inicio": "2026-01", "fim": "2026-11", "nota": "valor é piso"},
            "quebra": {"anos": [{"ano": a, "n": 3, "v": {medida: 30.0}, "status": "parcial", "sem_mes": {"n": 0},
                                 "meses": [{"mes": 1, "n": 3, "v": {medida: 30.0}, "status": "ok"},
                                           {"mes": 2, "n": None, "v": {medida: None}, "status": "indisponivel"}]} for a in anos]}}


def _rotas():
    sob = {"ok": True, "n": 1, "n_verificados": 1, "n_divergentes": 0, "itens_com_preco": 10, "grupos_comparaveis": 2, "sem_par": 3,
           "achados": [{"item": "Espéculo", "unidade_normalizada": "unidade", "orgao": "PREFEITURA", "fornecedor": "F LTDA",
                        "fornecedor_cnpj": "44982273000154", "preco_normalizado": 7.99, "mediana": 1.84, "razao": 4.3,
                        "excesso_total_est": 922.5, "ata_registro_precos": False, "verificacao": "VERIFICADO",
                        "verificado_em": "2026-11-13T17:04:28", "data": "2024-06-05", "certame": "44982273000154-1-000301/2024", "item_n": 3, "link_pncp": "https://pncp.gov.br/app/editais/1/2024/301"}],
           "indeterminados": {"n": 5, "por_motivo": [{"motivo": "grupo heterogêneo", "n": 5}]}}
    return {
        "pericia_contabil": _pericia(), "governo_couto": _couto(),
        "cge_confronto": {"estado": "ok", "gerado_em": "2026-11-14T16:50:18", "curado_em": "2026-11-13", "fonte": "CGE", "cobertura": "64",
                          "rotulo_grau": {"G1": "indício de dano"}, "metricas": {"G1": {"n": 2, "valor_contratado": 10.0, "com_ob": 1}},
                          "linhas": [{"orgao": "ISP", "processo": "090002/000036/2025", "fornecedor": "W S/A", "valor_contratado": 10.0,
                                      "grau": "G1", "irregularidade": "direcionamento", "ob_n": 0, "ob_pago": 0.0, "casos": []}],
                          "historico": [], "ressalva": "avaliação interna"},
        "territorio/estado": {"fonte": "PNCP", "atualizado_em": "2026-11-14T15:01:40-03:00", "periodo": "vigentes",
                              "baldes": {"atribuido": {"n": 2456, "valor": 1.0}, "sem_municipio": {"n": 2754, "valor": 2.0},
                                         "total": {"n": 7080, "valor": 3.0}, "com_pago": {"n": 1, "valor": 1.0, "pago": 0.5}},
                              "municipios": [{"nome": "Angra dos Reis", "n_contratos": 2, "n_em_execucao": 2, "valor_contratado": 1320849.82,
                                              "pago": None, "n_com_pago": 0, "n_alertas": 0}]},
        "territorio/pcrj": {"fonte": "Contas Rio", "aps": [{"nome": "AP 1", "ras": ["Centro"], "n_contratos": 72,
                                                            "valor_contratado": 10.0, "pago": 2.0, "pct_executado": None}]},
        "territorio/baldes": {"periodo": "tudo", "estado": {"total": {"n": 39302, "valor": 4.0}}},
        "comparador/economia": {"ok": True, "economia_total": 13045.5, "n_compras_acima_mediana": 5, "economia_ata_teto": None,
                                "n_compras_ata": None, "explicacao": "só conferidas", "ressalva": "não é OB"},
        "intel/sobrepreco?limite=120&esfera=estado": sob, "intel/sobrepreco?limite=120&esfera=prefeitura": sob,
        "orcamento_orgao": _orcamento(), "orcamento_orgao?ano=2026": _orcamento(),
        "orcamento_orgao?ano=2026&mes=1": _orcamento(mes=1), "orcamento_orgao?ano=2026&mes=2": _orcamento(mes=2),
        "periodo/ob_siafe": _periodo("ob_siafe", "pago", [2025, 2026]),
        "periodo/contratos_estado": _periodo("contratos_estado", "valor_inicial", [2026]),
        "periodo/aditivos_estado": _periodo("aditivos_estado", "valor_acrescido", [2026]),
        "periodo/tac_estado": _periodo("tac_estado", "valor_publicado", [2026]),
    }


@pytest.fixture()
def amb(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    (vault / "casos").mkdir(parents=True)
    (vault / "casos" / "caso-construtora.md").write_text("---\ntipo: caso\n---\nCNPJ 60.853.934/0001-06 no SEI-490001/001323/2024\n",
                                                         encoding="utf-8")
    (vault / "00-INDEX.md").write_text("# hub\n\n<!-- cerebro:hub:inicio -->\nx\n<!-- cerebro:hub:fim -->\n", encoding="utf-8")
    monkeypatch.setattr(V, "VAULT", vault)
    monkeypatch.setattr(V, "DATA", tmp_path / "data")
    monkeypatch.setattr(C, "DATA", tmp_path / "data")                 # fila do cérebro também isolada
    rotas = _rotas()

    def obter(cam):
        if cam not in rotas or rotas[cam] is None:
            raise V.FonteIndisponivel(f"/api/{cam}: fora do ar")
        return rotas[cam]
    return vault, rotas, obter


def _ler(vault, rel):
    return (vault / "jfn" / f"{rel}.md").read_text(encoding="utf-8")


# ───────────── INDISPONÍVEL nunca vira zero (controle positivo e negativo) ─────────────
def test_ausente_e_indisponivel_e_zero_de_verdade_continua_zero():
    assert V.brl(None) == V.IND and V.num(None) == V.IND and V.pct(None) == V.IND
    assert V.brl(0) == "R$ 0,00" and V.num(0) == "0"                    # zero que a fonte afirma não é escondido
    assert V.brl(1297655242.92) == "R$ 1.297.655.242,92" and V.num(40411) == "40.411"
    assert V.brl("lixo") == V.IND and V.brl(True) == V.IND


def test_orcamento_sem_dado_sai_indisponivel_e_soma_parcial_sai_rotulada(amb):
    vault, _, obter = amb
    V.gerar(obter)
    nota = _ler(vault, "anos/2026")
    linha = lambda rot: next(ln for ln in nota.splitlines() if ln.startswith(f"| {rot}"))  # noqa: E731
    assert "| INDISPONÍVEL | INDISPONÍVEL |" in linha("Dotação atualizada") and "R$" not in linha("Dotação atualizada").split("|")[2]
    assert "R$ 30,00 (parcial) | INDISPONÍVEL | 7 |" in linha("Pago — OB Contabilizada do SIAFE")
    assert "| R$ 0,00 | PENDENTE |" in linha("Empenhado")              # zero declarado pela fonte: fica zero
    assert "| R$ 100,00 | VERIFICADO |" in linha("Dotação inicial")
    assert "Taxa de empenho INDISPONÍVEL" in nota
    fev = next(ln for ln in nota.split("## 2.")[1].splitlines() if ln.startswith("| fev"))
    assert fev.count("INDISPONÍVEL") == 3 and "R$" not in fev and "| 0 |" not in fev   # mês sem coleta: nem contagem zero


def test_exercicio_fora_da_fonte_e_indisponivel_nao_tabela_vazia(amb):
    vault, _, obter = amb
    V.gerar(obter)
    nota = _ler(vault, "anos/2025")                                    # só a série de OB tem 2025
    assert "o exercício 2025 não está na base de orçamento (não é zero)" in nota
    assert nota.count("a fonte não tem o exercício 2025 (não é zero)") == 3
    assert "| jan | 3 | R$ 30,00 | PENDENTE |" in nota


def test_municipio_sem_pago_e_pericia_sem_valor_ficam_indisponiveis(amb):
    vault, _, obter = amb
    V.gerar(obter)
    assert "| 1 | Angra dos Reis | 2 | 2 | R$ 1.320.849,82 | INDISPONÍVEL | 0 | 0 |" in _ler(vault, "contratos-por-municipio")
    per = _ler(vault, "pericia-contabil")
    assert "| Pago à frente do pró-rata, dentro do contrato | INDISPONÍVEL | VERIFICADO |" in per
    assert "**Estado do RJ:** INDISPONÍVEL — a fonte não permite aferir (não é zero)." in per
    assert "nenhuma OB localizada (não prova ausência de pagamento)" in _ler(vault, "cge-x-jfn")
    assert "INDISPONÍVEL em INDISPONÍVEL compra(s)" in _ler(vault, "sobrepreco-conferido")


# ───────────── CPF mascarado ─────────────
def test_cpf_nunca_sai_inteiro_e_cnpj_continua_legivel(amb):
    vault, _, obter = amb
    V.gerar(obter)
    tudo = "\n".join(p.read_text(encoding="utf-8") for p in (vault / "jfn").rglob("*.md"))
    assert CPF not in tudo and CPF_FMT not in tudo
    assert "***.982.247-**" in tudo                                    # o dado existe, mascarado
    assert "60.853.934/0001-06" in tudo                                # CNPJ é público: controle negativo da máscara
    assert "FULANO DE TAL NOMEADO" not in tudo                         # nome de ato de pessoal não é copiado


def test_mascarar_nao_estraga_cnpj_processo_nem_numero_comum():
    assert V.mascarar(f"cpf {CPF} e {CPF_FMT}") == "cpf ***.982.247-** e ***.982.247-**"
    for intacto in ("60.853.934/0001-06", CNPJ, "SEI-490001/001323/2024", "12345678901", "OB 2026OB00332 · R$ 47.097,42"):
        assert V.mascarar(intacto) == intacto                          # 12345678901 não tem dígito verificador válido
    assert V.doc(CPF) == "***.982.247-**" and V.doc(CNPJ) == "60.853.934/0001-06"


# ───────────── número com fonte e estado ─────────────
def test_toda_nota_declara_fonte_posicao_e_estado(amb):
    vault, _, obter = amb
    V.gerar(obter)
    notas = sorted(p for p in (vault / "jfn").rglob("*.md") if "itens" not in p.parts)
    assert len(notas) == 9                                             # 6 retratos + 2 exercícios + índice
    for p in notas:
        t = p.read_text(encoding="utf-8")
        assert re.search(r'^fonte: ".+"$', t, re.M) and re.search(r'^fonte_de: ".+"$', t, re.M), p.name
        assert "> **Fonte:** " in t and "Indício não é acusação" in t and "[[jfn/00-retratos]]" in t, p.name
        assert re.search(r"VERIFICADO|PENDENTE|INDISPONÍVEL", t), p.name
    per = _ler(vault, "pericia-contabil")
    cab = [ln for ln in per.splitlines() if ln.startswith("| ") and "Valor" in ln and "---" not in ln and "R$" not in ln]
    assert cab and all("Estado" in ln for ln in cab)


def test_estado_nunca_promove_a_verificado():
    assert V.estado("VERIFICADO — régua determinística") == "VERIFICADO" and V.estado("INDISPONIVEL") == V.IND
    for nao in ("ok", "", None, "conferido", "verificado_parcial", "parcial"):
        assert V.estado(nao) == "PENDENTE"
    assert V._estado_periodo("ok") == "PENDENTE" and V._estado_periodo("indisponivel") == V.IND


def test_sinais_so_com_prova_conferida(amb):
    _, rotas, _ = amb
    ss = V.sinais(rotas["governo_couto"], rotas["pericia_contabil"])
    assert [s["grau"] for s in ss] == ["🔴", "🟡"] and ss[0]["n_graves"] == 1 and ss[0]["n_atencao"] == 0
    assert "SEGREDO-PENDENTE" not in json.dumps(ss, ensure_ascii=False)          # ponto PENDENTE não vira sinal
    assert len(V.sinais(rotas["governo_couto"], _pericia("PENDENTE — em conferência"))) == 1   # placar não verificado: fora
    assert V.sinais({"pontos_atencao": {"itens": []}}, {"esferas": {}}) == []
    vazio, _ = V.nota_sinais({"pontos_atencao": {"itens": []}}, {"esferas": {}})
    assert "Nenhum sinal verificado" in vazio and "não é atestado de regularidade" in vazio


def test_gestao_couto_lista_so_verificados_e_liga_ao_caso(amb):
    vault, _, obter = amb
    V.gerar(obter)
    couto = _ler(vault, "gestao-couto")
    assert "1 de 2 pontos têm prova primária" in couto and "SEGREDO-PENDENTE" not in couto
    assert "OB 2026OB00332" in couto and "sanção de outro ente" in couto
    assert "| Pago na mesma janela do ano anterior | INDISPONÍVEL |" in couto
    assert "[[casos/caso-construtora]]" in _ler(vault, "pericia-contabil")       # por CNPJ/processo citado no caso


# ───────────── fonte fora do ar, idempotência e escrita ─────────────
def test_fonte_fora_do_ar_nao_apaga_a_nota_boa_e_a_rodada_falha(amb, monkeypatch):
    vault, rotas, obter = amb
    V.gerar(obter)
    antes = _ler(vault, "gestao-couto")
    rotas["governo_couto"] = None
    est = V.gerar(obter)
    assert _ler(vault, "gestao-couto") == antes                        # mantida na última posição boa
    assert {i["nota"] for i in est["indisponiveis"]} == {"jfn/gestao-couto", "jfn/sinais-criticos"}
    assert est["manchetes"]["couto_graves"] == 1                       # manchete anterior mantida, não zerada
    assert "INDISPONÍVEL nesta rodada — nota mantida" in _ler(vault, "00-retratos")
    monkeypatch.setattr(V, "gerar", lambda seco=False: est)
    assert V.main([]) == 1                                             # o despachante vê a falha e tenta de novo


def test_tudo_fora_do_ar_nao_escreve_nada(amb):
    vault, rotas, obter = amb
    rotas.clear()
    est = V.gerar(obter)
    assert est["em_dia"] == 0 and not (vault / "jfn").exists()
    assert "retratos" not in (vault / "00-INDEX.md").read_text(encoding="utf-8")


def test_segunda_rodada_sem_mudanca_nao_regrava_nenhum_byte(amb, tmp_path):
    vault, rotas, obter = amb
    um = V.gerar(obter)
    assert um["regravadas"] == um["notas"] == 8 and um["indice_regravado"] and um["hub_regravado"]
    marcas = {p: p.stat().st_mtime_ns for p in vault.rglob("*.md")}
    dois = V.gerar(obter)
    assert dois["regravadas"] == 0 and not dois["indice_regravado"] and not dois["hub_regravado"]
    assert marcas == {p: p.stat().st_mtime_ns for p in vault.rglob("*.md")}
    rotas["pericia_contabil"]["esferas"]["Estado do RJ"]["placar"]["A_MAIOR"] = 63
    tres = V.gerar(obter)
    assert sorted(r["nota"] for r in tres["registro"] if r["mudou"]) == ["jfn/pericia-contabil", "jfn/sinais-criticos"]
    assert not [p for p in vault.rglob("*") if p.is_file() and p.suffix not in (".md", ".base")]   # nenhum temporário no vault
    assert not list((tmp_path / ".jfn_vault_tmp").iterdir())
    hub = (vault / "00-INDEX.md").read_text(encoding="utf-8")
    assert hub.count("[[jfn/00-retratos]]") == 1 and "<!-- cerebro:hub:inicio -->\nx\n" in hub   # bloco alheio intacto


def test_modo_seco_nao_grava(amb, tmp_path):
    vault, _, obter = amb
    est = V.gerar(obter, seco=True)
    assert est["regravadas"] == 8 and not (vault / "jfn").exists() and not (tmp_path / "data").exists()


# ───────────── propagação e segundo cérebro ─────────────
def test_derivado_esta_no_mapa_e_as_manchetes_existem_e_passam_no_filtro_do_cerebro(amb, tmp_path):
    _, _, obter = amb
    cfg = P.carregar()
    assert P.validar(cfg) == []
    d = cfg["derivados"]["vault_retratos"]
    assert d["efeito"]["arquivo"] == "data/vault_retratos_estado.json" and d["peso"] == "leve"
    V.gerar(obter)
    est = json.loads((tmp_path / "data" / V.ESTADO).read_text(encoding="utf-8"))
    texto = "; ".join(f"{rot} = {P._valor(est, cam)}" for rot, cam in d["cerebro"]["campos"].items())   # KeyError = campo órfão
    assert C.recusar(texto + " " + d["cerebro"]["ressalva"]) is None
    assert "13.045,50" in texto and "= 2456" in texto
    ja = {c for o in ("pericia_contabil", "cge_confronto") for c in cfg["derivados"][o]["cerebro"]["campos"]}
    assert not ja & set(d["cerebro"]["campos"])                        # não duplica memória de outro derivado
    assert not re.search(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}|CONSTRUTORA|Empresa Y", json.dumps(est, ensure_ascii=False))


def test_descobertas_verificadas_vao_ao_cerebro_uma_vez_e_corrigem_quando_o_fato_muda(amb, tmp_path):
    _, rotas, obter = amb
    um = V.gerar(obter)
    assert um["cerebro"] == {"novo": 2}                                # a mesma compra nas 2 esferas da simulação: 1 memória só
    con = C._con(tmp_path / "data" / "propagacao.db")
    linhas = dict(con.execute("SELECT chave, conteudo FROM cerebro").fetchall())
    assert set(linhas) == {"couto:D14-x", "sobrepreco:44982273000154-1-000301/2024:3"}
    assert all(C.recusar(t) is None for t in linhas.values())
    assert "SEGREDO-PENDENTE" not in " ".join(linhas.values())           # PENDENTE não vira memória
    assert "não é pagamento" in linhas["sobrepreco:44982273000154-1-000301/2024:3"]
    assert V.gerar(obter)["cerebro"] == {"igual": 2}                   # mesma rodada: nenhuma memória duplicada
    rotas["governo_couto"]["pontos_atencao"]["itens"][0]["valor_ob"] = 300000.0
    assert V.gerar(obter)["cerebro"] == {"corrigido": 1, "igual": 1}   # fato mudou: vai como correção (supersedes)
    assert V.gerar(obter, seco=True)["cerebro"] == {}


def test_descobertas_mascaram_cpf_e_ignoram_grau_sem_cor():
    couto = {"pontos_atencao": {"itens": [
        {"id": "a", "grau": "🟡", "verificacao": "VERIFICADO", "regra_ou_hipotese": f"sócio {CPF_FMT}", "valor_ob": None},
        {"id": "b", "grau": "⚪", "verificacao": "VERIFICADO", "regra_ou_hipotese": "x"}]}}
    ds = V.descobertas(couto, {})
    assert [d[0] for d in ds] == ["couto:a"] and CPF_FMT not in ds[0][1]
    assert "OB contabilizada (SIAFE): INDISPONÍVEL" in ds[0][1]


def test_soma_da_diferenca_sem_valor_nao_vira_zero():
    assert V._soma_dif([{"diferenca": 10.0}, {"diferenca": None}]) == "R$ 10,00 (parcial: 1 sem valor)"
    assert V._soma_dif([{"diferenca": None}]) == V.IND and V._soma_dif([{"diferenca": 0.0}]) == "R$ 0,00"


# ───────────── propriedades padronizadas e notas-item para o Bases ─────────────
def _props(texto):
    import yaml
    return yaml.safe_load(texto.split("---\n")[1])


def test_frontmatter_padronizado_em_retratos_e_itens(amb):
    vault, _, obter = amb
    est = V.gerar(obter)
    for p in (vault / "jfn").rglob("*.md"):
        pr = _props(p.read_text(encoding="utf-8"))                  # YAML válido
        assert "[[Retratos JFN]]" in pr["categories"] and pr["fonte"] and pr["gerado_por"] == V.GERADO_POR, p
        assert set(pr["estado"] if isinstance(pr["estado"], list) else [pr["estado"]]) <= {"VERIFICADO", "PENDENTE", V.IND, "DIVERGENTE", "REFUTADO"}
    per = _props(_ler(vault, "pericia-contabil"))
    assert per["gerado"] == "2026-11-14" and per["categories"] == ["[[Retratos JFN]]", "[[Contratos]]"]
    assert est["itens"]["a-maior"] == {"ok": True, "n": 2, "regravadas": 2, "removidas": 0}
    am = _props(_ler(vault, "itens/a-maior/estado-do-rj-2025007357"))
    assert am["valor_pago"] == 1902706.43 and am["diferenca"] == 902706.43 and am["estado"] == "PENDENTE"
    assert am["ug"] is None and am["cnpj"] == "60.853.934/0001-06" and am["casos"] == ["[[casos/caso-construtora]]"]
    pf = next(_props(p.read_text(encoding="utf-8")) for p in (vault / "jfn/itens/a-maior").glob("*.md") if "PESSOA" in p.read_text(encoding="utf-8"))
    assert pf["cnpj"] == "***.982.247-**"                              # CPF mascarado também na propriedade
    co = _props(_ler(vault, "itens/couto/d14-x"))
    assert co["grau"] == "🔴" and co["ug"] == "324200" and co["regra"] == "D14" and co["estado"] == "VERIFICADO"
    assert not (vault / "jfn/itens/couto/h3-z.md").exists()           # PENDENTE não vira item
    base = (vault / "jfn" / "retratos-jfn.base").read_text(encoding="utf-8")
    import yaml
    b = yaml.safe_load(base)
    assert [v["name"] for v in b["views"]] == ["A_MAIOR por órgão", "Pontos Couto por grau", "Retratos"]


def test_valor_ausente_no_item_fica_vazio_nunca_zero(amb):
    vault, rotas, obter = amb
    rotas["pericia_contabil"]["esferas"]["Estado do RJ"]["a_maior"][0]["pago"] = None
    V.gerar(obter)
    am = _props(_ler(vault, "itens/a-maior/estado-do-rj-2025007357"))
    assert am["valor_pago"] is None
    assert "| Pago | INDISPONÍVEL |" in _ler(vault, "itens/a-maior/estado-do-rj-2025007357")


def test_item_que_sai_da_lista_e_removido_so_se_for_nosso(amb):
    vault, rotas, obter = amb
    V.gerar(obter)
    alheia = vault / "jfn/itens/couto/nota-do-dono.md"
    alheia.write_text("minha nota\n", encoding="utf-8")
    rotas["governo_couto"]["pontos_atencao"]["itens"][0]["verificacao"] = "PENDENTE"
    est = V.gerar(obter)
    assert est["itens"]["couto"]["removidas"] == 1 and not (vault / "jfn/itens/couto/d14-x.md").exists()
    assert alheia.exists()
    rotas["governo_couto"] = None
    assert V.gerar(obter)["itens"]["couto"] == {"ok": False} and alheia.exists()
