# -*- coding: utf-8 -*-
"""Dreno do SIAFE: pares fora do PERFIL da conta saem da fila (com sonda mensal), e o disjuntor de login
só conta falhas realmente SEGUIDAS.

Medido em 28/10/2026: 194 dos 235 pares da fila eram 2019–2020 de UGs que a conta não enxerga no SIAFE 1
(a base tem uma única UG, 010100, de 2016 a 2020) e voltavam "todas as fatias zeradas" a cada passada. E o
disjuntor disparou com falha–sucesso–falha (316100/2022 rendeu 66 OBs entre as duas), tirando o SIAFE 1 da
fila por 24 h.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

SH = Path(__file__).resolve().parent.parent / "tools" / "siafe_drenar_capados.sh"


def _funcoes() -> str:
    """Só as funções do perfil, extraídas do script (rodá-lo inteiro tocaria o SIAFE)."""
    t = SH.read_text(encoding="utf-8")
    ini = t.index("sonda_vencida()")
    fim = t.index("N_FORA=0")
    return t[ini:fim]


def _rodar(restrito: list[str], ug: str, ano: str) -> int:
    script = "RESTRITO=(" + " ".join(restrito) + ")\n" + _funcoes() + f"\nfora_do_perfil {ug} {ano}\n"
    return subprocess.run(["bash", "-c", script]).returncode


def test_par_de_outra_ug_em_exercicio_restrito_fica_fora():
    assert _rodar(["2019:010100", "2020:010100"], "540100", "2020") == 0


def test_a_propria_ug_e_exercicios_livres_seguem():
    assert _rodar(["2020:010100"], "010100", "2020") == 1
    assert _rodar(["2020:010100"], "540100", "2021") == 1


def test_sonda_mensal_reabre_o_caminho():
    t = SH.read_text(encoding="utf-8")
    assert "2592000" in t and 'touch "$SONDA_PERFIL"' in t


def test_ganho_zera_a_sequencia_de_falhas_de_login():
    t = SH.read_text(encoding="utf-8")
    trecho = t[t.index('quar ganho "${UG}_${ANO}"'):t.index('elif grep -q \'"nada_a_fazer": true\'')]
    assert "ULT_LOGIN_FALHO=" in trecho


def test_disjuntor_pausa_curta_e_aviso_separado():
    """Pausa de 90 min (sonda) separada do aviso ao dono (1 por 24 h); login que funciona deixa carimbo."""
    t = SH.read_text(encoding="utf-8")
    assert '_PAUSA=data/.siafe_dreno_pausa_login_$_S' in t and "-lt 5400" in t
    assert 'touch "data/.siafe_dreno_pausa_login_$SIS"' in t
    assert t.count('touch "data/.siafe_dreno_login_ok_$_S"') == 3


def _credencial(tmp_path, carimbo_depois_do_env: bool | None) -> int:
    """30/10/2026: senha recusada parava só 90 min e voltava a tentar — ~20 logins errados no dia."""
    import os
    env = tmp_path / ".env"; env.write_text("x")
    os.utime(env, (1_000, 1_000))
    if carimbo_depois_do_env is not None:
        c = tmp_path / "data" / ".siafe_dreno_credencial_1"; c.parent.mkdir(exist_ok=True); c.write_text("")
        os.utime(c, (2_000, 2_000) if carimbo_depois_do_env else (500, 500))
    script = _funcoes() + "\ncredencial_recusada 1\n"
    return subprocess.run(["bash", "-c", script], cwd=tmp_path).returncode


def test_senha_recusada_trava_o_sistema_ate_o_env_mudar(tmp_path):
    assert _credencial(tmp_path, True) == 0          # carimbo depois do .env: segue travado
    assert _credencial(tmp_path, False) == 1         # o dono trocou a senha no .env: destrava
    assert _credencial(tmp_path, None) == 1          # sem carimbo: livre


def test_dreno_carimba_e_para_com_senha_recusada():
    t = SH.read_text(encoding="utf-8")
    assert "credencial_recusada \"$_S\" && continue" in t
    assert 'grep -qE \'"erro": "senha_(incorreta|expirada)"\' "$SAIDA"' in t
    assert 'touch "data/.siafe_dreno_credencial_$SIS"' in t
