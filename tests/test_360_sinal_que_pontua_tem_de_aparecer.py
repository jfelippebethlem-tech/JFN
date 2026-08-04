# -*- coding: utf-8 -*-
"""Sinal que PONTUA tem de APARECER — senão a fila mostra processo vazio no topo.

Medido em 2026-08-03, depois de reavaliar o acervo: **14 processos com faixa EXTREMO e ZERO
achados**, um deles com score 93,6. Rastreando um: quem pontuava eram dois detectores de
FORNECEDOR (C9 com score 1,0 e C3/C5 com 0,85), que entram no `score_processo` mas nunca viravam
achado do processo. O fiscal abria o item mais alto da fila e não via nada escrito.

Pior efeito, medido na mesma passada: o processo que eu li à mão e cujos NOVE achados confirmei
um a um ficava em 99,3 — **abaixo** de processos com um único achado, porque o score era dominado
por sinais invisíveis. A fila não ordenava por gravidade.

Regra: todo resultado CONFIRMADO que entra no score entra também na lista de achados, com a
origem declarada. O que não aparece no entregável não existe.
"""
from compliance_agent import processo_360 as P
from compliance_agent.detectores.base import ResultadoDetector


def _rd(det, score, expl=""):
    return ResultadoDetector(detector=det, processo="X", score=score, valores={},
                             evidencia=[], explicacao_inocente=expl, status="confirmado")


def test_detector_de_fornecedor_confirmado_vira_achado():
    achados = P.achados_de_fornecedor([_rd("C9", 1.0, "97% do faturamento vem de TAC")])
    assert len(achados) == 1
    a = achados[0]
    assert a["origem"] == "fornecedor" and a["codigo"] == "C9"
    assert a["gravidade"] in ("media", "alta", "critica")
    assert a["diz"]


def test_detector_nao_confirmado_nao_vira_achado():
    r = _rd("C3", 0.9)
    r.status = "nao_avaliavel"
    assert P.achados_de_fornecedor([r]) == []


def test_detector_refutado_nao_vira_achado():
    r = _rd("C3", 0.9)
    r.refutada = True
    assert P.achados_de_fornecedor([r]) == []


def test_a_gravidade_acompanha_o_score_do_detector():
    fraco = P.achados_de_fornecedor([_rd("C1", 0.3)])[0]["gravidade"]
    forte = P.achados_de_fornecedor([_rd("C1", 1.0)])[0]["gravidade"]
    assert ("media", "critica") == (fraco, forte) or fraco != forte


def test_o_achado_diz_que_e_do_FORNECEDOR_nao_do_processo():
    """Perfil do contratado é indício sobre a EMPRESA; confundir com vício do processo seria
    imputar ao gestor o que é característica de quem ele contratou."""
    a = P.achados_de_fornecedor([_rd("C9", 1.0)])[0]
    assert "fornecedor" in a["diz"].lower() or "contratad" in a["diz"].lower()


def test_achado_de_fornecedor_nao_e_contado_duas_vezes_no_score():
    """O detector já está em `resultados`; virar sinal sintético também inflaria o score."""
    from pathlib import Path as _P
    src = _P(P.__file__).read_text(encoding="utf-8")
    assert 'if origem in ("fornecedor", "execucao", "edital"):\n            continue' in src, (
        "achado de detector voltou a ser convertido em sinal sintético (dupla contagem)")


def test_explicacao_inocente_nao_vira_o_texto_do_achado():
    """Medido: o item saía escrito 'FALSO POSITIVO a descartar' — que é o CONTRA-argumento do
    detector, não a acusação. Ela fica em campo próprio, rotulada."""
    a = P.achados_de_fornecedor([_rd("C3/C5", 0.85, "FALSO POSITIVO a descartar (spread normal)")])[0]
    assert "FALSO POSITIVO" not in a["diz"]
    assert a["explicacao_inocente"] == "FALSO POSITIVO a descartar (spread normal)"


# ───────── a mesma falha, aberta na família de EXECUÇÃO até 2026-08-04 ─────────

def test_detector_de_execucao_confirmado_vira_achado():
    """Medido nos 120 processos de maior risco: X3 confirmado em 29, X7 em 14, X1 em 4 e X9 em 3
    — todos pontuando no score e nenhum aparecendo. Um deles (070002/013553/2024) estava em
    EXTREMO com score 80 e ZERO achados."""
    r = _rd("X3", 0.9)
    r.evidencia = [{"trecho": "pagamento de R$ 1,2 mi sem medição correspondente nos autos"}]
    a = P.achados_de_execucao([r])[0]
    assert a["origem"] == "execucao" and a["codigo"] == "X3"
    assert "medição" in a["diz"], "o TRECHO literal entra no achado — é ele que sustenta a peça"
    assert a["gravidade"] == "critica"


def test_execucao_nao_confirmada_ou_refutada_nao_vira_achado():
    r1 = _rd("X9", 1.0); r1.status = "nao_avaliavel"
    r2 = _rd("X9", 1.0); r2.refutada = True
    assert P.achados_de_execucao([r1]) == [] and P.achados_de_execucao([r2]) == []


def test_achado_de_execucao_fala_do_PROCESSO_e_nao_da_empresa():
    """Execução do contrato é conduta do gestor — ao contrário do perfil do fornecedor, que é
    característica de quem ele contratou."""
    r = _rd("X1", 0.8)
    r.evidencia = [{"trecho": "acréscimos somam 40% do valor inicial"}]
    a = P.achados_de_execucao([r])[0]
    assert "execu" in a["diz"].lower()
    assert "empresa" not in a["ressalva"].lower()


def test_achado_de_execucao_SEM_prova_literal_nao_entra():
    """Ligar a família X me fez quebrar a regra do `instrumento_assinatura`: o X3 confirma com
    `evidencia` VAZIA e o item saía escrito "X3 confirmado (intensidade 0.60)" e mais nada —
    o score sem explicação de novo, de roupa nova."""
    r = _rd("X3", 0.6)
    r.evidencia = []
    r.motivo_refutacao = ""
    assert P.achados_de_execucao([r]) == []


def test_sem_trecho_vale_a_razao_que_o_detector_registrou():
    r = _rd("X3", 0.6)
    r.evidencia = []
    r.motivo_refutacao = "tríade comprimida: ciclo mínimo de 2 dia(s)"
    a = P.achados_de_execucao([r])[0]
    assert "ciclo mínimo de 2" in a["diz"] and a["evidencia"]


def test_detector_de_EDITAL_confirmado_vira_achado():
    """Terceira vez que a mesma falha aparece: depois de C (2026-08-03) e X (2026-08-04), a
    família P/E/J também pontuava invisível — 4 processos ficaram EXTREMO/ALTO com ZERO achados
    por E1 e E7. E a conversão descartava `evidencia` e `explicacao_inocente` no caminho."""
    r = _rd("E7", 0.85)
    r.evidencia = [{"trecho": "exigência de atestado com quantitativo superior ao licitado"}]
    a = P.achados_de_detector([r], origem="edital", rotulo="planejamento/edital/julgamento",
                              ressalva="x")[0]
    assert a["origem"] == "edital" and a["codigo"] == "E7"
    assert "atestado" in a["diz"] and a["gravidade"] == "alta"
