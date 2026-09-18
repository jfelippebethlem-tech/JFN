# -*- coding: utf-8 -*-
"""O lane da varredura: continuar sem depender de sessão aberta, e sem quebrar as regras da casa.

A leitura custa ~70 s por processo e o acervo tem 2.354. Enquanto dependia de eu relançar lote a
lote entre supervisões, o gargalo deixava de ser a máquina e passava a ser a minha cadência — a VM
ficava ociosa no intervalo. O lane resolve isso na forma que a casa admite:

  · cron SINGLE-PASS com `timeout`, nunca `while true`;
  · um só de cada vez (2 vCPU é o gargalo);
  · teto de carga: acima dele o disparo desiste em silêncio;
  · kill-switch de arquivo, para o dono parar sem mexer no cron.

**O `flock` sozinho não bastava, e isso foi MEDIDO no primeiro teste:** ele serializa os disparos do
lane, mas havia uma varredura lançada à mão fora dele — dois leitores concorrendo, exatamente o que
a regra proíbe. O guard passou a enxergar qualquer leitura viva.
"""
from __future__ import annotations

from pathlib import Path

_LANE = Path(__file__).resolve().parent.parent / "tools" / "varredura_sei_lane.sh"


def _texto() -> str:
    return _LANE.read_text(encoding="utf-8")


def _codigo() -> str:
    """Só as linhas de CÓDIGO — a regra proíbe o construto, não a palavra.

    Pela terceira vez nesta sessão um teste que procura literal proibido falhou por causa do
    COMENTÁRIO que avisa contra o literal. A catraca da casa tem o mesmo defeito e já me pegou duas
    vezes. Quem verifica código tem de olhar código.
    """
    return "\n".join(ln for ln in _texto().splitlines()
                      if not ln.lstrip().startswith("#"))


def test_e_single_pass_com_timeout_e_nunca_while_true():
    c = _codigo()
    assert "timeout " in c, "disparo sem timeout vira processo eterno — proibido pela casa"
    assert "while true" not in c and "while :" not in c


def test_enxerga_leitura_viva_lancada_FORA_do_lane():
    """O defeito que o primeiro teste real expôs: `flock` não vê processo lançado à mão."""
    t = _texto()
    assert "ps -C python" in t and "sei_leitura_dupla" in t


def test_nao_usa_pgrep_f_que_casa_o_proprio_script():
    """`pgrep -f sei_leitura_dupla` casaria com o PRÓPRIO lane (o nome do módulo está na linha de
    comando) — a armadilha que já mordeu esta casa antes."""
    assert "pgrep -f" not in _codigo()


def test_respeita_o_teto_de_carga():
    t = _texto()
    assert "/proc/loadavg" in t and "-ge 4" in t


def test_tem_kill_switch_de_arquivo():
    """Parar tem de ser imediato e sem editar cron."""
    t = _texto()
    assert ".varredura_sei.off" in t
    # antes de QUALQUER trabalho: o desligamento não pode depender de o lock ser obtido
    assert t.index("[ -f data/.varredura_sei.off ]") < t.index("exec 9>")
