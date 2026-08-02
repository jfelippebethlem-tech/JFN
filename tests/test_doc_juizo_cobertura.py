# -*- coding: utf-8 -*-
"""O juízo por documento tem de alcançar o ato que DECIDE o gasto.

Medido em 2026-08-02 sobre 2.175 processos do arquivo SEI: 29.945 documentos ficavam fora de
qualquer rubrica — entre eles 998 autorizações de despesa, 207 termos de referência e 193
pesquisas de preços. O juízo subjetivo via só despacho e parecer; o ato do ordenador que
autoriza o gasto, a peça que define o objeto e a que fundamenta o preço passavam em branco.

Dois riscos que estes testes travam: (1) a rubrica existir mas o tipo ficar fora do
`_PRIORIDADE` — aí o teto de 25 documentos corta justamente o ato decisório; (2) a fila do
sweep pular um processo inteiro só porque ELE já tem algum veredito, deixando os documentos
recém-elegíveis nunca julgados.
"""
from compliance_agent.sei import doc_juizo as J

NOVOS = ("autorizacao_despesa", "termo_referencia", "pesquisa_precos")


def test_atos_decisorios_tem_rubrica():
    for t in NOVOS:
        assert t in J.RUBRICAS, f"{t} continua sem rubrica — 0 análise subjetiva"
    assert J.RUBRICAS["projeto_basico"] == J.RUBRICAS["termo_referencia"]


def test_rubricas_novas_declaram_as_tres_escalas_e_a_saida_null():
    """Rubrica sem os três níveis vira classificador binário e infla 'problemático'."""
    for t in NOVOS:
        txt = J.RUBRICAS[t]
        for nivel in ("1 =", "2 =", "3 ="):
            assert nivel in txt, f"{t} não descreve o nível {nivel}"
        assert "14.133" in txt or "9.784" in txt or "LINDB" in txt, f"{t} sem base legal citada"


def test_ato_que_autoriza_o_gasto_nao_e_cortado_pelo_teto():
    """Com 30 despachos na frente, a autorização de despesa tem de sobreviver ao teto de 25."""
    docs = [{"i": i, "tipo": "despacho", "titulo": f"Despacho {i}"} for i in range(30)]
    docs.append({"i": 99, "tipo": "autorizacao_despesa", "titulo": "Autorização de Despesa 123"})
    sel = J.selecionar(docs)
    assert len(sel) == J.TETO_DEFAULT
    assert any(d["tipo"] == "autorizacao_despesa" for d in sel), (
        "a autorização caiu fora do teto — está ausente do _PRIORIDADE")


def test_prioridade_poe_quem_decide_antes_de_quem_executa():
    ordem = list(J._PRIORIDADE)
    assert ordem.index("autorizacao_despesa") < ordem.index("aceite")
    assert ordem.index("parecer") < ordem.index("pesquisa_precos")


def test_sweep_360_enfileira_por_documento_pendente_nao_por_processo():
    """A fila do sweep não pode usar `distinct numero_sei`: um processo com 1 despacho julgado
    ficaria 'pronto' para sempre e suas peças novas nunca seriam avaliadas."""
    from pathlib import Path
    txt = Path(__file__).resolve().parents[1].joinpath("tools", "sweep_360.sh").read_text(
        encoding="utf-8")
    assert "distinct numero_sei from doc_veredito" not in txt, (
        "a fila ainda pula o processo inteiro; tem de considerar documento pendente")
    assert "doc_i" in txt, "a fila precisa raciocinar em nível de documento"
