# -*- coding: utf-8 -*-
"""O vigia do banco era só REATIVO — e por isso não viu a corrupção de 12/08.

`tools/guardiao_db_malformed.sh` roda a cada 5 minutos e checava a integridade do arquivo APENAS
quando uma de três rotas devolvia "database disk image is malformed". Em 11-12/08 o banco corrompeu
de verdade e o vigia não viu nada: a tabela atingida (`ordens_bancarias`) não é tocada por nenhuma
das três sondas.

O preço desse silêncio está medido: a corrupção viveu ~13 horas e, nesse intervalo, **19 processos
foram reavaliados com dado quebrado e perderam achados** — um deles saiu de risco EXTREMO (score
80) para score 0 com zero achados. Detectar uma hora depois teria custado uma reavaliação; detectar
treze horas depois custou uma perícia inteira.

Duas exigências, e as duas são testadas aqui:

1. **Sonda PROATIVA**, com cadência própria: `quick_check(1)` custa 10,6 s numa base de 3,4 GB —
   barato de hora em hora, caro a cada 5 minutos. Sem carimbo de tempo, ou o vigia fica caro ou
   volta a ser cego.
2. **Alerta que CHEGA, e uma vez só.** Escrever num log que ninguém lê é o mesmo que não detectar;
   avisar a cada 5 minutos é trocar o silêncio por um dilúvio — e o dono já pagou o preço do
   dilúvio de e-mail do CI no mesmo dia.
"""
from __future__ import annotations

from pathlib import Path

_G = Path(__file__).resolve().parent.parent / "tools" / "guardiao_db_malformed.sh"


def _texto() -> str:
    return _G.read_text(encoding="utf-8")


def test_a_sonda_proativa_existe_e_tem_cadencia_propria():
    t = _texto()
    assert "quick_check" in t
    assert "SONDA_S" in t and "guardiao_integridade.stamp" in t, (
        "a sonda precisa de carimbo de tempo: sem cadência, ou custa caro ou não roda")


def test_a_sonda_roda_ANTES_de_depender_do_sintoma_nas_rotas():
    """Se a checagem continuar depois do `[ -z "$doente" ] && exit 0`, ela só roda quando uma rota
    adoece — que é exatamente o buraco de 12/08."""
    t = _texto()
    assert t.index("quick_check") < t.index('[ -z "$doente" ]')


def test_a_rota_que_toca_a_tabela_atingida_entrou_nas_sondas():
    """`ordens_bancarias` não era tocada por nenhuma das três rotas originais. `/api/ugs` é a que
    devolveu 500 quando a corrupção apareceu."""
    t = _texto()
    linha = next(ln for ln in t.splitlines() if ln.startswith("ROTAS="))
    assert '"ugs"' in linha, f"faltou a sonda que toca ordens_bancarias: {linha}"


def test_o_alerta_e_DESDUPLICADO_por_incidente():
    t = _texto()
    assert "guardiao_corrompido.alertado" in t
    assert t.count("rm -f data/.guardiao_corrompido.alertado") >= 1, (
        "sem limpar a marca ao normalizar, o PRÓXIMO incidente não avisa")


def test_o_alerta_usa_o_canal_da_casa_e_nao_so_o_log():
    t = _texto()
    assert "from tools.ronda import notificar" in t, (
        "log que ninguém lê não é alerta — o incidente de 12/08 ficou 13 h sem ninguém saber")


def test_corrupcao_real_continua_NAO_reiniciando_o_servico():
    """A salvaguarda antiga não pode ter sido perdida: com corrupção de verdade o vigia grita e
    PARA, porque aí é perícia de dado, não reboot."""
    t = _texto()
    assert "exige perícia humana" in t or "NÃO reinicio" in t
