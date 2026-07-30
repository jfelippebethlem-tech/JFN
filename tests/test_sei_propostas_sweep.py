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
