# -*- coding: utf-8 -*-
"""Sweep do acervo SEI → `proposta_item`: as travas que impedem número inventado de entrar no banco.

CONTEXTO. `proposta_item` tinha **77 linhas** porque o único alimentador (`coletor_propostas.backfill`)
itera `ata_documento`, que tem 33. O detector J9 estava ligado, testado e sem matéria-prima. O preço
por fornecedor estava no acervo SEI em texto puro — 40.241 documentos que ninguém varrera para isto.

Este sweep usa um LLM livre (`nous stepfun:free`) sobre documento público. Modelo livre em volume
inventa número, e número inventado num indício de conluio é pior que indício nenhum. Daí as travas
que estes testes existem para travar:

  1. **valor tem de aparecer LITERALMENTE no texto de origem**, nas duas grafias brasileiras;
  2. **CNPJ tem de ser um dos que estão no documento** — o modelo não inventa fornecedor;
  3. **descarte é CONTADO**, para o laudo mostrar quanto o modelo estava inventando.

E a seleção do alvo é testada porque ela é o que separa 56 documentos úteis de 615 faturas: filtrar
só por "2+ CNPJs" traria faturas com 154 CNPJs de clientes, que o LLM leria a peso de ouro.
"""
from __future__ import annotations

import sqlite3

import pytest

from tools import sei_propostas_sweep as S


# ── trava 1: o número tem de estar no documento ─────────────────────────────────────────────────
def test_valor_precisa_aparecer_literalmente_no_texto():
    texto = "Item 1 ... VALOR UNITÁRIO R$ 1.234,56 ... TOTAL R$ 12.345,60"
    assert S._valor_literal(1234.56, texto), "grafia com separador de milhar tem de casar"
    assert S._valor_literal(12345.60, texto)
    assert not S._valor_literal(1234.57, texto), "número próximo NÃO é o número"
    assert not S._valor_literal(9999.99, texto), "número ausente do texto não pode entrar"


def test_valor_literal_aceita_a_grafia_sem_milhar():
    """Planilha extraída de PDF às vezes perde o ponto de milhar. As duas grafias valem."""
    assert S._valor_literal(1234.56, "preço 1234,56 por unidade")


def test_valor_nao_numerico_ou_ausente_e_rejeitado():
    for v in (None, "", "abc", [], {}):
        assert not S._valor_literal(v, "qualquer texto R$ 10,00")


# ── trava 2: o fornecedor tem de existir no documento ───────────────────────────────────────────
def test_cnpj_com_digito_repetido_nao_identifica_ninguem():
    """`00.000.000/0000-00` aparece em formulário em branco e casaria a regex."""
    assert S._cnpjs("CNPJ: 00.000.000/0000-00") == []
    assert S._cnpjs("CNPJ: 11.111.111/1111-11") == []
    assert S._cnpjs("CNPJ: 35.824.741/0001-71") == ["35824741000171"]


def test_cnpj_e_lido_em_varias_grafias():
    t = "35.824.741/0001-71 e 02754941000146 e 09 077 954 0001 77"
    assert set(S._cnpjs(t)) >= {"35824741000171", "02754941000146"}


# ── a seleção do alvo ───────────────────────────────────────────────────────────────────────────
def test_certame_derivado_do_processo_sei():
    assert S._certame_do_processo("080002_008019_2026") == "SEI-080002/008019/2026"
    assert S._certame_do_processo("formato_estranho") == "formato_estranho"


def test_faixa_de_fornecedores_exclui_fatura():
    """2 a 8 CNPJs = cotação. Documento com 154 CNPJs é FATURA listando clientes, não concorrentes —
    e era a campeã do filtro ingênuo por '2+ CNPJs'."""
    assert S.MIN_FORNECEDORES == 2
    assert S.MAX_FORNECEDORES == 8


# ── o que o sweep persiste ──────────────────────────────────────────────────────────────────────
class _GerarFalso:
    """Modelo de mentira: devolve o JSON que se mandar, para exercitar as travas sem rede."""

    def __init__(self, resposta):
        self.resposta = resposta
        self.chamadas = 0

    def __call__(self, _prompt):
        self.chamadas += 1
        return self.resposta


@pytest.fixture()
def doc(tmp_path):
    proc = tmp_path / "sei_arquivo" / "080002_008019_2026" / "texto"
    proc.mkdir(parents=True)
    arq = proc / "035_planilha_de_custos_1.txt"
    arq.write_text(
        "PESQUISA DE PREÇOS\n"
        "FJS LTDA - CNPJ: 35.824.741/0001-71\n"
        "NUTRIMED LTDA - CNPJ: 02.754.941/0001-46\n"
        "DESCRIÇÃO UNIDADE QUANTIDADE VALOR UNITÁRIO\n"
        "Almoço ... R$ 13,00 ... R$ 13,20\n", encoding="utf-8")
    return {"arquivo": arq, "processo": "080002_008019_2026",
            "cnpjs": ["02754941000146", "35824741000171"], "valores": 2}


def _db(tmp_path):
    p = tmp_path / "c.db"
    con = sqlite3.connect(p)
    from compliance_agent.editais.coletor_propostas import garantir_tabela
    garantir_tabela(con)
    con.commit()
    con.close()
    return p


def test_valor_que_o_modelo_INVENTOU_nao_entra(doc, tmp_path):
    """O caso que justifica o módulo: o modelo devolve 99,99, que não existe no documento."""
    db = _db(tmp_path)
    g = _GerarFalso('[{"item":1,"descricao":"Almoço","precos":['
                    '{"cnpj":"35824741000171","valor_unitario":99.99}]}]')
    r = S.processar(doc, g, db=db)
    assert r["linhas"] == 0, "valor ausente do texto NÃO pode ser persistido"
    assert r["descartados"] >= 1, "e o descarte tem de ser contado, não engolido"


def test_fornecedor_que_o_modelo_INVENTOU_nao_entra(doc, tmp_path):
    db = _db(tmp_path)
    g = _GerarFalso('[{"item":1,"descricao":"Almoço","precos":['
                    '{"cnpj":"11222333000181","valor_unitario":13.00}]}]')
    r = S.processar(doc, g, db=db)
    assert r["linhas"] == 0, "CNPJ que não está no documento não identifica fornecedor nenhum"
    assert r["descartados"] >= 1


def test_valor_literal_de_fornecedor_do_documento_ENTRA(doc, tmp_path):
    db = _db(tmp_path)
    g = _GerarFalso('[{"item":1,"descricao":"Almoço","precos":['
                    '{"cnpj":"35824741000171","valor_unitario":13.00},'
                    '{"cnpj":"02754941000146","valor_unitario":13.20}]}]')
    r = S.processar(doc, g, db=db)
    assert r["linhas"] == 2 and r["fornecedores"] == 2
    con = sqlite3.connect(db)
    linhas = con.execute("SELECT certame, item, fornecedor_cnpj, valor_unitario, fonte "
                         "FROM proposta_item ORDER BY fornecedor_cnpj").fetchall()
    con.close()
    assert linhas == [("SEI-080002/008019/2026", 1, "02754941000146", 13.2, "sei_precos"),
                      ("SEI-080002/008019/2026", 1, "35824741000171", 13.0, "sei_precos")]


def test_resposta_vazia_do_modelo_e_ZERO_e_nao_erro(doc, tmp_path):
    """`[]` é resposta legítima: o documento não tem tabela. Não é falha, não é achado."""
    r = S.processar(doc, _GerarFalso("[]"), db=_db(tmp_path))
    assert r["linhas"] == 0 and "motivo" in r


def test_resposta_ilegivel_nao_derruba_e_nao_inventa(doc, tmp_path):
    r = S.processar(doc, _GerarFalso("desculpe, não consegui"), db=_db(tmp_path))
    assert r["linhas"] == 0


def test_modelo_de_raciocinio_e_RETENTADO_antes_de_desistir(doc, tmp_path):
    """Medido: a mesma pergunta devolveu 25 itens numa chamada e nada na seguinte. Sem retry, o
    sweep perderia documento bom por sorteio."""
    g = _GerarFalso("pensando em voz alta, sem json")
    S.processar(doc, g, db=_db(tmp_path))
    assert g.chamadas >= 2, "resposta sem JSON tem de ser retentada"


# ── o consumidor: sem ele, tabela cheia continua não virando achado ──────────────────────────────
def test_analisar_ignora_certame_com_um_fornecedor_so(tmp_path):
    """Um fornecedor não é comparação. `sem_par_comparavel` é contado, não silenciado."""
    db = _db(tmp_path)
    con = sqlite3.connect(db)
    con.executemany(
        "INSERT INTO proposta_item (certame,item,fornecedor_cnpj,valor_unitario,fonte) VALUES (?,?,?,?,?)",
        [("SEI-1/1/2026", i, "35824741000171", 10.0 + i, "sei_precos") for i in range(1, 5)])
    con.commit()
    con.close()
    r = S.analisar(db)
    assert r["avaliados"] == 0 and r["sem_par_comparavel"] == 1


def test_analisar_acha_markup_uniforme_entre_cotacoes(tmp_path):
    """O caso do dono: dois 'concorrentes' com a mesma planilha e um percentual fixo."""
    db = _db(tmp_path)
    con = sqlite3.connect(db)
    linhas = []
    for i in range(1, 7):
        base = 100.0 + i * 7
        linhas.append(("SEI-2/2/2026", i, "35824741000171", base, "sei_precos"))
        linhas.append(("SEI-2/2/2026", i, "02754941000146", round(base * 0.95, 2), "sei_precos"))
    con.executemany("INSERT INTO proposta_item (certame,item,fornecedor_cnpj,valor_unitario,fonte) "
                    "VALUES (?,?,?,?,?)", linhas)
    con.commit()
    con.close()
    r = S.analisar(db)
    assert r["avaliados"] == 1
    tipos = {a["tipo"] for a in r["achados"]}
    assert "markup_uniforme" in tipos, f"o caso literal do pedido não acendeu: {r['achados']}"


def test_analisar_diz_que_sao_COTACOES_e_nao_propostas_de_certame(tmp_path):
    """Rótulo errado num laudo de controle externo é defeito, não detalhe."""
    r = S.analisar(_db(tmp_path))
    assert "COTAÇÕES" in r["_nota"] and "Indício ≠ acusação" in r["_nota"]


# ── a trava de ATRIBUIÇÃO: a mais importante, e nasceu de três falsos positivos ──────────────────
def test_documento_com_mais_colunas_que_CNPJs_nao_e_persistido(tmp_path):
    """O caso que quase virou achado de conluio publicado.

    O sweep produziu "markup uniforme de −1% em 6 itens" entre dois concorrentes. Fui à planilha: a
    linha do item tinha QUATRO pares (unitário, total) e o texto só trazia DOIS CNPJs. As colunas
    extras são estimado/média/contratado, e o cabeçalho com os nomes dos fornecedores costuma viver
    numa IMAGEM que a extração não traz. O modelo escolhe duas das quatro colunas e chama de A e B —
    a "diferença percentual constante" é a distância entre duas colunas quaisquer, não entre duas
    propostas. Medido no acervo: **37 de 55 documentos** têm mais colunas de preço do que CNPJs.

    Persistir isso envenenaria todo detector a jusante com atribuição errada.
    """
    proc = tmp_path / "sei_arquivo" / "080002_013339_2024" / "texto"
    proc.mkdir(parents=True)
    arq = proc / "026_planilha_comparativa_de_custos_1.txt"
    # 1 item, QUATRO pares de valores, só DOIS CNPJs — a assinatura do problema
    arq.write_text(
        "PLANILHA COMPARATIVA\n"
        "FORNECEDOR A - CNPJ: 04.075.374/0001-27\n"
        "FORNECEDOR B - CNPJ: 05.197.932/0001-90\n"
        "DESCRIÇÃO UNIDADE QUANTIDADE VALOR UNITÁRIO\n"
        "APOIO ADM  R$ 5.020,76  R$ 40.166,08  R$ 5.203,56  R$ 41.628,48  "
        "R$ 5.179,98  R$ 41.439,84  R$ 5.121,29  R$ 40.970,32\n", encoding="utf-8")
    doc = {"arquivo": arq, "processo": "080002_013339_2024",
           "cnpjs": ["04075374000127", "05197932000190"], "valores": 8}
    g = _GerarFalso('[{"item":1,"descricao":"APOIO ADM","precos":['
                    '{"cnpj":"04075374000127","valor_unitario":5203.56},'
                    '{"cnpj":"05197932000190","valor_unitario":5121.29}]}]')
    r = S.processar(doc, g, db=_db(tmp_path))
    assert r["linhas"] == 0, "atribuição não confiável NÃO pode virar linha no banco"
    assert "NÃO CONFIÁVEL" in r["motivo"]
    assert "colunas de preço por item" in r["motivo"]


def test_documento_com_colunas_batendo_com_CNPJs_PASSA(tmp_path):
    """O contra-exemplo: 2 fornecedores, 2 pares de valores. Aí dá para dizer de quem é o preço."""
    proc = tmp_path / "sei_arquivo" / "080002_007720_2024" / "texto"
    proc.mkdir(parents=True)
    arq = proc / "029_planilha_de_custos_1.txt"
    arq.write_text(
        "PLANILHA DE CUSTOS\n"
        "A - CNPJ: 02.853.169/0001-10\nB - CNPJ: 28.413.325/0001-15\n"
        "DESCRIÇÃO UNIDADE QUANTIDADE VALOR UNITÁRIO\n"
        "Engenheiro  R$ 184,61  R$ 190,53\n", encoding="utf-8")
    doc = {"arquivo": arq, "processo": "080002_007720_2024",
           "cnpjs": ["02853169000110", "28413325000115"], "valores": 2}
    g = _GerarFalso('[{"item":1,"descricao":"Engenheiro","precos":['
                    '{"cnpj":"02853169000110","valor_unitario":184.61},'
                    '{"cnpj":"28413325000115","valor_unitario":190.53}]}]')
    r = S.processar(doc, g, db=_db(tmp_path))
    assert r["linhas"] == 2, f"documento bem-formado tem de passar: {r.get('motivo')}"


def test_vetor_identico_vira_suspeita_de_EXTRACAO_e_nao_achado(tmp_path):
    """Preço byte-a-byte igual em 100% dos itens é coluna duplicada, não conluio.

    Conluio real deixa markup; identidade exata em toda a lista é a assinatura de o modelo ter
    mapeado dois CNPJs para a MESMA coluna.
    """
    db = _db(tmp_path)
    con = sqlite3.connect(db)
    linhas = []
    for i in range(1, 5):
        v = 1000.0 + i
        linhas.append(("SEI-3/3/2026", i, "18993091000179", v, "sei_precos"))
        linhas.append(("SEI-3/3/2026", i, "39185269000125", v, "sei_precos"))
    con.executemany("INSERT INTO proposta_item (certame,item,fornecedor_cnpj,valor_unitario,fonte) "
                    "VALUES (?,?,?,?,?)", linhas)
    con.commit()
    con.close()
    r = S.analisar(db)
    assert r["indicios"] == 0, "não pode sair como achado de conluio"
    assert r["suspeitos_de_extracao"] == 1
    assert "coluna duplicada" in r["suspeitos"][0]["motivo_suspeita"]
