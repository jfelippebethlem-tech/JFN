# -*- coding: utf-8 -*-
"""Catraca do filtro de saída dos jobs (deploy/seguranca/nftables-egress.nft) × o que as rotinas ATIVAS da fatia
jfn-coletor.slice precisam alcançar na rede interna (religação O9.0, 26/11/2026).

Medido na VM-1 com sonda TCP dentro × fora da fatia (`systemd-run --user --scope --slice=jfn-coletor.slice`): o
painel :8000, o OpenList :5244, o brain :8443 e o ssh do it-campo passavam fora e eram recusados dentro — e as rotinas
seguiam com rc 0 cegas (ronda «api=FORA» com o painel no ar; propagacao_ponte «Connection refused» no cérebro) ou rc 1
(nuvens_manter_vivas). Cada alvo aqui tem dono declarado; tirar um do filtro sem tirar a rotina quebra este teste.
"""
from __future__ import annotations

import re
from pathlib import Path

NFT = Path(__file__).resolve().parents[1] / "deploy" / "seguranca" / "nftables-egress.nft"

LOOPBACK = {  # porta em 127.0.0.1 → rotinas ativas (config/fluxo.yaml) que a usam de dentro da fatia
    5432: "PG local da VM-2 (jobs do worker)",
    8000: "ronda, keepalive, remediar_painel_shm/travado, prewarm_painel, materializar_painel, vault_retratos",
    5244: "nuvens_manter_vivas (OpenList: terabox/proton/mediafire)",
    9222: "doerj (chrome-jfn CDP)",
    9333: "vm_guard_navegador, verificacao_humana_manter (navegador-cdp)",
}
TAILNET_V4 = {
    ("100.74.228.51", 5432): "PG da VM-2",
    ("100.74.228.51", 2222): "túnel vm1→vm2 (backup_evidencias_pg, automelhoria, graph_report_brain)",
    ("100.123.89.59", 2222): "deploy_vm2 (origin git da VM-1), vm2_amostra (vm1-ts)",
    ("100.74.228.51", 8443): "handoff_watcher, propagacao_ponte, cerebro_*, vault_retratos, conferencia_opus_fila",
    ("100.75.118.110", 22): "indeterminados, padroes, dossie_couto, itcampo_vigia (ssh it-campo)",
}


def _conjunto(nome: str) -> str:
    m = re.search(r"set " + nome + r" \{.*?elements = \{(.*?)\}", NFT.read_text(encoding="utf-8"), re.S)
    assert m, f"conjunto {nome} sumiu do filtro"
    return m.group(1)


def test_loopback_libera_o_que_as_rotinas_da_fatia_usam():
    portas = {int(p) for p in re.findall(r"\d+", _conjunto("loopback_tcp"))}
    faltam = {p: quem for p, quem in LOOPBACK.items() if p not in portas}
    assert not faltam, f"porta de loopback recusada à fatia, mas usada por: {faltam}"


def test_tailnet_libera_o_que_as_rotinas_da_fatia_usam():
    pares = set((ip, int(p)) for ip, p in re.findall(r"(\d+\.\d+\.\d+\.\d+) \. (\d+)", _conjunto("tailnet_v4")))
    faltam = {k: quem for k, quem in TAILNET_V4.items() if k not in pares}
    assert not faltam, f"alvo da Tailnet recusado à fatia, mas usado por: {faltam}"


def test_v6_do_brain_acompanha_o_v4():
    """O nome do brain (MagicDNS) resolve também em fd7a:…; o v6 recusado antes do v4 custa uma volta a cada chamada."""
    assert "fd7a:115c:a1e0::c938:e434 . 8443" in _conjunto("tailnet_v6")


def test_metadata_e_rfc1918_continuam_recusados():
    t = NFT.read_text(encoding="utf-8")
    assert 'ip daddr 169.254.0.0/16 counter reject' in t
    assert re.search(r"ip daddr \{[^}]*10\.0\.0\.0/8[^}]*100\.64\.0\.0/10[^}]*\} counter reject", t)
    assert 'ip daddr 127.0.0.0/8 counter reject' in t
