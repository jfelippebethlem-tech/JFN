# -*- coding: utf-8 -*-
"""Testes da política de storage SOMADO (R2 primário + B2 transbordo, cada foto em 1 bucket).

Foco: o GUARD do teto de 10GB do R2 (margem 9,5GB) — o sistema NUNCA pode estourar o R2; quando o R2
enche, transborda pro B2; se os dois enchem, degrada honesto (None). Os parses de `visual_img_b2`.

Não toca rede nem DB: o uso de cada bucket é injetado via monkeypatch de `_uso_bytes`.
"""
import compliance_agent.fachada_remotes as fr


def _sel_com_uso(monkeypatch, uso_por_bucket):
    """SelecionadorRemote cujo `rclone size` é mockado: uso_por_bucket = {(remote,bucket): bytes}."""
    def fake_uso(remote, bucket):
        return uso_por_bucket.get((remote, bucket))
    monkeypatch.setattr(fr, "_uso_bytes", fake_uso)
    return fr.SelecionadorRemote()


def test_r2_primario_quando_tem_espaco(monkeypatch):
    """Com R2 quase vazio, a foto vai pro R2 (primário, egress zero)."""
    sel = _sel_com_uso(monkeypatch, {("r2", "jorgefelippe"): 50_000, ("b2", "jfn-backup-jorge"): 0})
    assert sel.escolher(40_000) == "r2:jorgefelippe"


def test_transborda_pro_b2_quando_r2_no_teto(monkeypatch):
    """⚠ GUARD: R2 cheio (acima do teto 9,5GB) → a próxima foto transborda pro B2, NUNCA estoura o R2."""
    cap = fr.REMOTES[0][2]  # teto do R2 em bytes
    sel = _sel_com_uso(monkeypatch, {("r2", "jorgefelippe"): cap, ("b2", "jfn-backup-jorge"): 0})
    assert sel.escolher(40_000) == "b2:jfn-backup-jorge"


def test_r2_no_limiar_exato_nao_estoura(monkeypatch):
    """No limiar: se uso + foto >= teto, NÃO usa o R2 (regra estrita < teto)."""
    cap = fr.REMOTES[0][2]
    sel = _sel_com_uso(monkeypatch, {("r2", "jorgefelippe"): cap - 10_000, ("b2", "jfn-backup-jorge"): 0})
    # foto de 10.000 bytes: cap-10000+10000 == cap → NÃO cabe no R2 → vai pro B2
    assert sel.escolher(10_000) == "b2:jfn-backup-jorge"
    # foto de 9.999 bytes: cabe no R2 (estritamente < teto)
    sel2 = _sel_com_uso(monkeypatch, {("r2", "jorgefelippe"): cap - 10_000, ("b2", "jfn-backup-jorge"): 0})
    assert sel2.escolher(9_999) == "r2:jorgefelippe"


def test_ambos_cheios_degrada_honesto(monkeypatch):
    """Os dois buckets cheios → None (o chamador loga e segue; não derruba, não estoura)."""
    r2cap, b2cap = fr.REMOTES[0][2], fr.REMOTES[1][2]
    sel = _sel_com_uso(monkeypatch, {("r2", "jorgefelippe"): r2cap, ("b2", "jfn-backup-jorge"): b2cap})
    assert sel.escolher(40_000) is None


def test_size_falha_pula_remote_conservador(monkeypatch):
    """Se o `rclone size` do R2 falhar (None), não arrisca estourar — pula pro B2."""
    sel = _sel_com_uso(monkeypatch, {("r2", "jorgefelippe"): None, ("b2", "jfn-backup-jorge"): 0})
    assert sel.escolher(40_000) == "b2:jfn-backup-jorge"


def test_size_falha_em_todos_degrada(monkeypatch):
    """Se o size de TODOS falhar, devolve None (conservador — não estoura nenhum teto)."""
    sel = _sel_com_uso(monkeypatch, {("r2", "jorgefelippe"): None, ("b2", "jfn-backup-jorge"): None})
    assert sel.escolher(40_000) is None


def test_confirmar_acumula_no_run(monkeypatch):
    """`confirmar` contabiliza os bytes subidos no run (sem chamar size de novo): enche o R2 e transborda."""
    cap = fr.REMOTES[0][2]
    sel = _sel_com_uso(monkeypatch, {("r2", "jorgefelippe"): cap - 50_000, ("b2", "jfn-backup-jorge"): 0})
    d1 = sel.escolher(40_000)
    assert d1 == "r2:jorgefelippe"
    sel.confirmar(d1, 40_000)  # agora uso R2 = cap-10000
    # próxima foto de 20.000: cap-10000+20000 > cap → transborda pro B2 (sem nova chamada de size)
    assert sel.escolher(20_000) == "b2:jfn-backup-jorge"


def test_parse_localizacao_completa():
    assert fr.parse_localizacao("r2:jorgefelippe/fachadas/123.jpg") == ("r2", "jorgefelippe", "fachadas/123.jpg")
    assert fr.parse_localizacao("b2:jfn-backup-jorge/fachadas/x.png") == ("b2", "jfn-backup-jorge", "fachadas/x.png")


def test_parse_localizacao_legado_ou_vazio_retorna_none():
    """Legado (só o objeto, sem remote:) e vazios → None (o leitor degrada honesto)."""
    assert fr.parse_localizacao("fachadas/123.jpg") is None
    assert fr.parse_localizacao("") is None
    assert fr.parse_localizacao(None) is None
    assert fr.parse_localizacao("r2:jorgefelippe") is None  # sem objeto


def test_parse_remote_bucket():
    assert fr.parse_remote_bucket("r2:jorgefelippe/fachadas/x.jpg") == ("r2", "jorgefelippe")
    assert fr.parse_remote_bucket("b2:jfn-backup-jorge") == ("b2", "jfn-backup-jorge")


def test_objeto_de():
    assert fr.objeto_de("28470707000180", "jpg") == "fachadas/28470707000180.jpg"
    assert fr.objeto_de("123", "png") == "fachadas/123.png"
