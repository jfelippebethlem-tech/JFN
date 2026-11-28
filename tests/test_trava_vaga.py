"""27/11/2026 — N vagas do `claude` por nó (o it-campo, 24 fios, ficava preso a 1 leitura)."""
from compliance_agent.llm import arquivo_estado as A


def test_n_vagas_pega_ate_n_e_a_seguinte_espera(tmp_path):
    base = tmp_path / "claude_motor.lock"
    with A.trava_vaga(base, 2, 0) as a, A.trava_vaga(base, 2, 0) as b, A.trava_vaga(base, 2, 0) as c:
        assert a and b and not c                      # 2 vagas: a 3ª não pega
    with A.trava_vaga(base, 1, 0) as d:
        assert d                                      # soltaram


def test_uma_vaga_e_a_trava_de_sempre(tmp_path):
    base = tmp_path / "claude_motor.lock"
    with A.trava(base, 0) as a, A.trava_vaga(base, 1, 0) as b:
        assert a and not b                            # o mesmo arquivo: quem usa a trava antiga também segura
