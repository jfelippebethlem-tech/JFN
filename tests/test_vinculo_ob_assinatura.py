"""27/11/2026 — dono: «só autorizo se tiver crédito que venha da assinatura; nada de gasto novo». O modelo do vínculo
OB×contrato lê pela ASSINATURA (camada 2), as mesmas duas leituras do lote; recusa da assinatura para sem gastar."""
from compliance_agent import vinculo_ob_contrato as V
from compliance_agent.adaptadores.llm import gateway as G


class _R:
    def __init__(self, t):
        self.texto = t


def test_le_pela_assinatura_e_para_na_primeira_recusa():
    chamadas = []

    def chamar(tarefa, msgs, **kw):
        chamadas.append(kw)
        if len(chamadas) == 3:
            raise G.SemProvedor("assinatura: teto", [])
        return _R(f"resp{len(chamadas)}")
    saida = V.ler_pela_assinatura([("p1a", "x"), ("p1b", "y"), ("p2a", "z"), ("p2b", "w")], chamar=chamar)
    assert saida == {"p1a": "resp1", "p1b": "resp2"} and len(chamadas) == 3
    assert all(k["so_camadas"] == [2] for k in chamadas)                     # só a assinatura: nenhuma camada paga
