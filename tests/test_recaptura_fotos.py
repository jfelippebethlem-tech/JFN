"""27/11/2026 — regra única #58: relatório fotográfico só com o texto do cache vira pedido de recaptura."""
from tools import recaptura_fotos as R


def test_so_cache_so_relatorio_fotografico_sem_foto_e_com_numero():
    m = {"origem": "cache CDP (texto)", "processo": "080002/019408/2024", "docs": [
        {"titulo": "Relatório FOTOGRÁFICO (82081372)", "fotos": "[]"},
        {"titulo": "Registro fotográfico (82081373)", "fotos": "['a.jpg']"},      # tem foto
        {"titulo": "Despacho (82081374)", "fotos": "[]"},                         # não é fotográfico
        {"titulo": "Memorial fotográfico sem número", "fotos": "[]"}]}            # sem o número SEI
    assert R.pedidos_do_manifesto(m) == [("080002/019408/2024", "sei:82081372")]
    assert R.pedidos_do_manifesto({**m, "origem": "integra"}) == []              # a íntegra já baixou as fotos
