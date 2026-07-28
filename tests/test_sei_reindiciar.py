# -*- coding: utf-8 -*-
"""Melhorar a régua não conserta o que ela já escreveu no vault.

Em 2026-07-28, às 14:34, o indício DV deixou de contar o rótulo do roteiro como achado. Às
13:50 daquele mesmo dia, a nota de SEI-420001/004984/2025 tinha sido gravada dizendo
"4 divergência(s)" — três delas eram: duas inconsistências que o próprio texto declara
**corrigidas por Termo de Rerratificação**, e uma "cláusula de contraditório e defesa
prévia", que casou por a palavra *contraditório* conter `contradi`.

Medido: **81 das 145 notas** do vault nasceram antes do conserto. O vault é a memória
permanente do órgão — um fiscal que abrir aquela nota vê 4 divergências onde há 1.

O reprocessamento é barato porque o dossiê extraído está em disco (`output/dossies/`): as
réguas são regex sobre o texto já citado. Zero cota de modelo, zero browser. É a divisão da
casa: a IA leu, o CÓDIGO reavalia.
"""
from tools.sei_reindiciar import indicios_declarados_na_nota, precisa_regravar

NOTA = """---
processo: 420001/004984/2025
pago_ob_siafe: 7910916.00
indicios: 4
analisado_em: 2026-07-28
---

# 🟡 Processo 420001/004984/2025
"""


def test_le_quantos_indicios_a_nota_declarou():
    assert indicios_declarados_na_nota(NOTA) == 4


def test_nota_sem_frontmatter_nao_quebra():
    assert indicios_declarados_na_nota("# nota solta sem cabeçalho") is None


def test_regrava_quando_a_regua_nova_acha_numero_diferente():
    assert precisa_regravar(NOTA, 1) is True


def test_nao_regrava_quando_nada_muda():
    """Reescrever 145 notas idênticas suja o histórico do vault sem informar nada."""
    assert precisa_regravar(NOTA, 4) is False


def test_regrava_quando_muda_o_CONTEUDO_com_o_mesmo_numero_de_indicios():
    """O caso que escapou na primeira passada, e só apareceu ao conferir o produto.

    SEI-420001/004984/2025 tinha 3 indícios antes e 3 depois — total igual, então a nota foi
    dada como inalterada. Mas o DV dentro dela caiu de 4 divergências para 1: as outras três
    eram duas correções por Termo de Rerratificação e uma "cláusula de contraditório". A nota
    seguiu no vault afirmando "4 divergência(s)". Contar indícios não basta; compara-se o
    texto.
    """
    antiga = NOTA.replace("indicios: 4", "indicios: 3") + "\nA leitura apontou 4 divergência(s)"
    nova = NOTA.replace("indicios: 4", "indicios: 3") + "\nA leitura apontou 1 divergência(s)"
    assert precisa_regravar(antiga, 3, texto_novo=nova) is True


def test_texto_identico_nao_regrava_mesmo_passando_o_novo():
    igual = NOTA + "\ncorpo igual"
    assert precisa_regravar(igual, 4, texto_novo=igual) is False


def test_diferenca_apenas_na_data_de_analise_nao_conta_como_mudanca():
    """`analisado_em` é carimbado pelo gerador; sozinho, não é motivo para reescrever."""
    antiga = NOTA + "\ncorpo"
    nova = NOTA.replace("2026-07-28", "2026-08-01") + "\ncorpo"
    assert precisa_regravar(antiga, 4, texto_novo=nova) is False


def test_nota_sem_contagem_conhecida_e_regravada_por_precaucao():
    """Não saber quantos eram é razão para reavaliar, não para pular."""
    assert precisa_regravar("# nota antiga sem frontmatter", 0) is True


def test_reindiciar_preserva_a_data_em_que_o_processo_FOI_LIDO():
    """Reavaliar o que se leu não é ler de novo — carimbar hoje seria mentir sobre a leitura."""
    from tools.sei_reindiciar import preservar_data_de_analise

    nova = "---\nprocesso: x\nindicios: 1\nanalisado_em: 2026-07-28\n---\n# corpo"
    saida = preservar_data_de_analise(nova, NOTA.replace("2026-07-28", "2026-07-11"))
    assert "analisado_em: 2026-07-11" in saida
    assert "indicios: 1" in saida, "só a data volta; o resto é o conteúdo recalculado"


def test_sem_data_antiga_mantem_a_nova():
    from tools.sei_reindiciar import preservar_data_de_analise

    nova = "---\nanalisado_em: 2026-07-28\n---\n# corpo"
    assert preservar_data_de_analise(nova, "# nota sem frontmatter") == nova


def test_a_escrita_no_vault_grava_o_recalculado_com_a_data_antiga(tmp_path, monkeypatch):
    """O único passo que toca o vault — testado sem o pipeline e sem o vault de verdade."""
    import tools.sei_reindiciar as R

    monkeypatch.setattr(R, "NOTAS", tmp_path)
    antiga = NOTA.replace("2026-07-28", "2026-07-11")

    def monta_nota(pasta, pago, dossie, indicios, conf):
        assert pago == 7910916.00, "o valor pago vem da nota antiga, não é recalculado"
        return f"---\nprocesso: {pasta}\nindicios: {len(indicios)}\nanalisado_em: 2026-07-28\n---\n# ok"

    escritas = R.regravar_nota("420001_004984_2025", "dossiê", antiga,
                               monta_nota, lambda d: ["um"], lambda p, d: {})

    gravada = (tmp_path / "420001_004984_2025.md").read_text()
    assert escritas == 1
    assert "indicios: 1" in gravada          # o recálculo entrou
    assert "analisado_em: 2026-07-11" in gravada  # a data de leitura ficou
