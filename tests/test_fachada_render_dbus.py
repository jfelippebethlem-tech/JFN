"""O render de fachada Street View precisa do D-Bus do usuário p/ o systemd-run --user.

Bug (25.478 falhas): o sweep roda via cron SEM XDG_RUNTIME_DIR/DBUS_SESSION_BUS_ADDRESS,
então `systemd-run --user` falha com 'Failed to connect to bus: No medium found' e
TODO render falha (0 fotos). Reproduzido: systemd-run --user funciona só com o env.
Fix: prover o env do bus do usuário; se o bus não existir, cair para render SEM
systemd-run (sem cap de cgroup, mas gate+timeout protegem) — nunca falhar por D-Bus.
"""
import tools.fachada_streetview_sweep as SV


def test_com_bus_usa_systemd_run_e_seta_env(monkeypatch, tmp_path):
    bus = tmp_path / "bus"
    bus.write_bytes(b"")
    monkeypatch.setattr(SV, "_dbus_bus", lambda: str(bus))
    cmd, env = SV._cmd_env_render(1.0, 2.0, 90.0, tmp_path / "o.png")
    assert "systemd-run" in cmd, "com bus, usa systemd-run p/ o cap de RAM do cgroup"
    assert env.get("DBUS_SESSION_BUS_ADDRESS", "").endswith("/bus")
    assert env.get("XDG_RUNTIME_DIR")


def test_sem_bus_cai_para_render_direto(monkeypatch, tmp_path):
    monkeypatch.setattr(SV, "_dbus_bus", lambda: None)
    cmd, env = SV._cmd_env_render(1.0, 2.0, 90.0, tmp_path / "o.png")
    assert "systemd-run" not in cmd, "sem bus, NÃO usa systemd-run (senão falha 'No medium')"
    assert "timeout" in cmd and cmd[-1].endswith("o.png"), "ainda renderiza (fallback)"


def test_dbus_bus_detecta_socket_real(monkeypatch, tmp_path):
    monkeypatch.setattr(SV.os, "getuid", lambda: 4242)
    monkeypatch.setattr(SV, "_RUN_USER", str(tmp_path))
    (tmp_path / "4242").mkdir()
    ok = tmp_path / "4242" / "bus"; ok.write_bytes(b"")
    assert SV._dbus_bus() == str(ok)
    ok.unlink()
    assert SV._dbus_bus() is None
