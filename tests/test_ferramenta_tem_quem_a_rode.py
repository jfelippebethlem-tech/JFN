# -*- coding: utf-8 -*-
"""Ferramenta pronta, testada e SEM NINGUÉM QUE A RODE — a falha que mais se repetiu nesta casa.

Em 2026-08-04, duas mordidas no mesmo dia:

* `tools/sei_reparar_vazios.py`, escrita em 2026-07-24 com a docstring *"por isso esta ferramenta
  roda primeiro"*, tinha **zero callers e zero cron** — e, quando finalmente rodou, recuperou
  documentos que estavam declarados vazios desde julho;
* a fila de recaptura do cap de 20k vinha de uma lista **curada uma vez** e nunca regerada: 103
  processos truncados depois da curadoria jamais voltariam à fila.

O antídoto tem de ser verificável por qualquer um — inclusive por uma IA fraca, ou por ninguém.
Aqui a regra é literal: **toda ferramenta que precisa rodar periodicamente é citada por um script
de sweep do repositório**, e os sweeps é que estão no crontab. Um `grep` decide; não há julgamento.

Quando uma ferramenta nova precisar de rotina, some-a à tabela abaixo com o MOTIVO — a tabela é a
documentação executável de quem roda o quê.
"""
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent

# ferramenta → por que ela PRECISA de rotina (e não pode depender de alguém lembrar)
PRECISAM_DE_ROTINA = {
    "tools.sei_reparar_vazios":
        "recupera texto de documento vazio a partir do PDF já em cache — de graça, sem tocar o "
        "SEI; ficou 11 dias sem caller",
    "tools.sei_reparar_truncados":
        "devolve à fila o que foi cortado no cap de 20k, medindo o alvo a cada rodada",
    "tools.tac_ranking_ugs":
        "recalcula o ranking de pagamento fora de contrato regular; o JSON envelhece a cada "
        "ingestão de OB",
    "tools.sei_cpf_sweep":
        "enriquecimento de CPF a partir dos processos capturados",
}


def _scripts_de_sweep() -> str:
    return "\n".join(p.read_text(encoding="utf-8", errors="ignore")
                     for p in sorted((RAIZ / "tools").glob("*.sh")))


@pytest.mark.parametrize("modulo,motivo", sorted(PRECISAM_DE_ROTINA.items()))
def test_ferramenta_periodica_e_citada_por_um_sweep(modulo, motivo):
    corpo = _scripts_de_sweep()
    alvo = modulo.replace("tools.", "")
    assert (modulo in corpo) or (f"tools/{alvo}.py" in corpo), (
        f"`{modulo}` precisa de rotina ({motivo}) e nenhum script de sweep a chama — "
        "é a família 'construído, testado, nunca rodado'")


def test_o_360_avalia_sem_NENHUMA_ia():
    """O caminho determinístico não pode depender de LLM. `avaliar()` só chama IA com
    `com_llm=True`, e o lote do cron NÃO passa esse sinalizador: com as chaves ausentes, o motor
    continua produzindo faixa, achados e lacunas. É o que garante o sistema rodando com uma IA
    fraca — ou sem nenhuma."""
    import inspect

    from compliance_agent import processo_360

    assinatura = inspect.signature(processo_360.avaliar)
    assert assinatura.parameters["com_llm"].default is False

    fonte = (RAIZ / "tools" / "sweep_360.sh").read_text(encoding="utf-8")
    linha = [ln for ln in fonte.splitlines() if "processo_360.py --lote" in ln]
    assert linha, "o sweep_360 deixou de rodar o lote determinístico"
    assert "--com-llm" not in linha[0], (
        "o lote do cron passou a exigir IA — o caminho determinístico tem de sobreviver sem ela")


def test_a_pipeline_pos_correcao_nao_exige_ia():
    """`tools/pos_correcao` é o comando único depois de mexer num detector; se ele dependesse de
    LLM, a convergência do acervo passaria a depender de cota de API."""
    fonte = (RAIZ / "tools" / "pos_correcao.py").read_text(encoding="utf-8")
    assert "com_llm=True" not in fonte
    assert "avaliar(" in fonte
