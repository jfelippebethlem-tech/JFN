# -*- coding: utf-8 -*-
"""Governador de capacidade (plano mestre v2 §3.4): funções puras sobre o texto do /proc — cada limiar da tabela
com o cenário dos dois lados."""
from compliance_agent.fluxo import governador as G

PSI_CPU = "some avg10=1.68 avg60=2.79 avg300=8.72 total=240958465129\nfull avg10=0.00 avg60=0.00 avg300=0.00 total=0\n"
PSI_MEM = "some avg10=12.50 avg60=0.00 avg300=0.00 total=339080866\nfull avg10=6.20 avg60=0.00 avg300=0.00 total=1\n"
MEMINFO = "MemTotal: 12000000 kB\nSwapTotal:       4194300 kB\nSwapFree:        1048575 kB\n"
BASE = {"cpu_leve": 2, "cpu_pesado": 1, "navegador": 1, "llm": 3, "materializar": 1, "disco": 1}


def test_ler_psi_pega_o_avg10_de_some_e_full():
    assert G.ler_psi(PSI_CPU) == {"some": 1.68, "full": 0.0}
    assert G.ler_psi(PSI_MEM) == {"some": 12.5, "full": 6.2}


def test_psi_ausente_vale_zero():
    assert G.ler_psi("") == {"some": 0.0, "full": 0.0}
    assert G.ler_psi("some avg10=3.00 avg60=0 avg300=0 total=0") == {"some": 3.0, "full": 0.0}   # kernel sem `full`


def test_swap_percentual_e_sem_swap():
    assert G.ler_swap_pct(MEMINFO) == 75.0
    assert G.ler_swap_pct("SwapTotal: 0 kB\nSwapFree: 0 kB\n") == 0.0


def test_montar_medida_junta_as_fontes():
    m = G.montar_medida(PSI_CPU, PSI_MEM, "", MEMINFO, 42.0)
    assert (m.cpu_some, m.mem_some, m.mem_full, m.io_some, m.swap_pct, m.disco_livre_pct) == (
        1.68, 12.5, 6.2, 0.0, 75.0, 42.0)


def test_folga_libera_o_que_sobra_do_slot():
    d = G.decidir(G.Medida(cpu_some=10, mem_full=0.2), BASE, {"cpu_leve": 1})
    assert d.estado == "folga" and d.acao is None
    assert d.livres == {**BASE, "cpu_leve": 1}


def test_limiar_da_folga_e_estrito():
    assert G.classificar(G.Medida(cpu_some=39.9, mem_full=0.9))[0] == "folga"
    assert G.classificar(G.Medida(cpu_some=40.0))[0] == "neutro"
    assert G.classificar(G.Medida(cpu_some=10, mem_full=1.0))[0] == "neutro"


def test_neutro_nao_reserva_pesado_novo():
    d = G.decidir(G.Medida(cpu_some=50), BASE)
    assert d.estado == "neutro"
    assert d.livres["cpu_pesado"] == d.livres["navegador"] == d.livres["disco"] == 0
    assert d.livres["cpu_leve"] == 2 and d.livres["llm"] == 3


def test_contido_por_cpu_ou_mem_so_deixa_o_que_nao_gasta_cpu():
    for m in (G.Medida(cpu_some=60.1), G.Medida(mem_some=10.1)):
        d = G.decidir(m, BASE)
        assert d.estado == "contido", m
        assert {r for r, n in d.livres.items() if n} == {"llm", "materializar"}
    assert G.classificar(G.Medida(cpu_some=60.0, mem_some=10.0))[0] == "neutro"   # o limite é "maior que"


def test_disco_baixo_corta_pesado_mesmo_com_folga():
    d = G.decidir(G.Medida(disco_livre_pct=8), BASE)
    assert d.estado == "folga" and d.livres["disco"] == d.livres["cpu_pesado"] == 0 and d.livres["cpu_leve"] == 2
    assert any("disco" in m for m in d.motivos)


def test_pressao_com_memoria_sobrando_nao_mata_job():
    """26/11/2026: o governador da VM-2 matou 3 jobs do E6 (5× cada, até a quarentena) com 9 GB DISPONÍVEIS: a pressão
    vinha do brain-index (2,5 GB a cada 10 min, fora do motor) — 8 s depois da morte a pressão seguia. Matar job só
    alivia quando a memória está de fato acabando; com folga, só para de reservar pesado."""
    d = G.decidir(G.Medida(mem_full=9.5, mem_disp_pct=78.0), BASE)
    assert d.acao is None and any("disponível" in x for x in d.motivos)
    assert d.livres.get("cpu_pesado", 0) == 0                     # não reserva pesado sob pressão
    assert G.decidir(G.Medida(mem_full=9.5, mem_disp_pct=12.0), BASE).acao == "matar"
    m = G.montar_medida("", "full avg10=6.00 avg60=0 avg300=0 total=0",  "",
                        "MemTotal: 1000 kB\nMemAvailable: 250 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n", 50.0)
    assert m.mem_disp_pct == 25.0


def test_memoria_full_acima_de_5_pede_matar():
    assert G.decidir(G.Medida(mem_full=5.1), BASE).acao == "matar"
    assert G.decidir(G.Medida(mem_full=5.0), BASE).acao is None


def test_pressao_sustentada_pede_suspender_na_terceira_leitura():
    m = G.Medida(cpu_some=80)
    assert G.decidir(m, BASE, contido_seguidas=0).acao is None
    assert G.decidir(m, BASE, contido_seguidas=1).acao is None
    assert G.decidir(m, BASE, contido_seguidas=2).acao == "suspender"


def test_ocupado_acima_do_slot_nao_vira_negativo():
    assert G.decidir(G.Medida(), {"cpu_leve": 1}, {"cpu_leve": 3}).livres == {"cpu_leve": 0}


def test_slots_iniciais_da_secao_3_4():
    """A §3.4 segue dando 0 navegador à VM-1; o único navegador lá é o TRANSITÓRIO declarado no yaml (D1, 24/11),
    restrito às rotinas listadas e com prazo (O3.3)."""
    from compliance_agent.fluxo import grafo
    assert G.SLOTS_INICIAIS["vm1"]["materializar"] == 1 and "navegador" not in G.SLOTS_INICIAIS["vm1"]
    g = grafo.carregar()
    assert g.slots_do_no("vm1")["navegador"] == 1
    assert {k: (t.maquina, t.recurso, t.slots) for k, t in g.transitorios.items()} == {
        "navegador_vm1": ("vm1", "navegador", 1)}
    assert {k: v for k, v in g.slots_do_no("vm1").items() if k != "navegador"} == G.SLOTS_INICIAIS["vm1"]
    assert g.slots_do_no("vm2") == G.SLOTS_INICIAIS["vm2"] and g.slots_do_no("itcampo") == G.SLOTS_INICIAIS["itcampo"]
    assert G.SLOTS_INICIAIS["vm2"]["navegador"] == 1 and "gpu" not in G.SLOTS_INICIAIS["vm2"]
    assert G.SLOTS_INICIAIS["itcampo"]["gpu"] == 1 and G.SLOTS_INICIAIS["itcampo"]["navegador"] == 6


def test_medir_le_a_maquina_sem_quebrar(tmp_path):
    (tmp_path / "pressure").mkdir()
    (tmp_path / "pressure" / "cpu").write_text(PSI_CPU)
    (tmp_path / "meminfo").write_text(MEMINFO)
    m = G.medir(proc=str(tmp_path), disco=str(tmp_path))
    assert m.cpu_some == 1.68 and m.mem_some == 0.0 and m.swap_pct == 75.0 and 0 < m.disco_livre_pct <= 100


def test_swap_ocupado_sem_pressao_nao_contem():
    """Religação O9.0 (25/11/2026): swap 96% de páginas velhas com 8,7 GB de RAM livre e PSI 0 segurou a fila >1 h.
    Swap ocupado não é pressão; a pressão de memória real é o PSI (mem some/full), que já decide."""
    d = G.decidir(G.Medida(swap_pct=96), BASE)
    assert d.estado == "folga" and d.livres["cpu_leve"] == 2
    assert G.decidir(G.Medida(swap_pct=96, mem_some=10.1), BASE).estado == "contido"


def test_so_mata_job_que_pesa():
    """25/11: com a pressão vinda de fora dos jobs, o SIGKILL caía em jobs de 15 MB, um atrás do outro (12 em 3 min),
    sem aliviar nada. Abaixo do piso, matar não alivia: o governador não mata."""
    assert G.vale_matar(G.MATAR_MIN_KB) and not G.vale_matar(G.MATAR_MIN_KB - 1) and not G.vale_matar(0)
