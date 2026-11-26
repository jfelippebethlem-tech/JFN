"""26/11/2026 (sensor `motor` da automelhoria): o E3 no it-campo era ADIADO 15× «por carga» — o vm_guard tinha o limite
da VM-1 de 2 vCPU (load 1,7) numa máquina de 24 núcleos; e o `cleanup_orphans` apagava com rm -rf TODO perfil temporário
do Chromium em /tmp, inclusive o de um navegador VIVO de outra captura simultânea."""
import os

from tools import vm_guard as G


def test_limite_de_carga_e_proporcional_aos_nucleos(monkeypatch):
    monkeypatch.delenv("VM_GUARD_MAX_LOAD", raising=False)
    monkeypatch.setattr(G.os, "cpu_count", lambda: 2)
    assert G.limite_carga() == 1.7                          # a VM-1 de sempre
    monkeypatch.setattr(G.os, "cpu_count", lambda: 24)
    assert G.limite_carga() == 20.4                         # o it-campo
    monkeypatch.setenv("VM_GUARD_MAX_LOAD", "3")
    assert G.limite_carga() == 3.0                          # override explícito vale


def test_perfil_em_uso_nao_e_apagado(tmp_path, monkeypatch):
    vivo, morto = tmp_path / "playwright_chromiumdev_profile-AAA", tmp_path / "playwright_chromiumdev_profile-BBB"
    vivo.mkdir(); morto.mkdir()
    monkeypatch.setattr(G, "_cmdlines_vivas", lambda: [f"chrome --user-data-dir={vivo} --headless"])
    apagados = G.limpar_perfis_orfaos(str(tmp_path))
    assert vivo.exists() and not morto.exists() and apagados == 1
