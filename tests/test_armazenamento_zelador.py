"""Travas do armazenamento/zelador — controle POSITIVO e NEGATIVO de cada uma (dono: "sem margem pra erro").

Um rclone falso guarda os "objetos" numa pasta; variantes dele mentem (devolvem ok sem gravar, corrompem,
caem) para provar que nada é apagado sem a cópia exigida conferida por hash NO MESMO ciclo.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from compliance_agent import armazenamento as A
from tools.zelador import zelador as Z


class NuvemFalsa(A.Rclone):
    """`uso_extra`: bytes que cada remoto "já tem" além do que esta nuvem gravou (para encher até o teto)."""
    def __init__(self, base: Path, mentir_envio=(), corromper=(), fora=(), uso_extra=None):
        super().__init__()
        self.base, self.mentir, self.corromper, self.fora = base, set(mentir_envio), set(corromper), set(fora)
        self.uso_extra = dict(uso_extra or {})

    def versao(self):
        return "rclone v-falso"

    def medir_uso(self, nome):
        raiz = self._p(A.NUVENS["remotos"][nome]["raiz"])
        usado = sum(f.stat().st_size for f in raiz.rglob("*") if f.is_file()) if raiz.exists() else 0
        return {"usado": float(usado + self.uso_extra.get(nome, 0)), "total": 20e9, "como": "falso"}

    def _p(self, remoto: str) -> Path:
        return self.base / remoto.replace(":", "/")

    def _dest(self, remoto: str) -> str:
        for d, b in A.DESTINOS.items():
            if remoto.startswith(b):
                return d
        return "indice"

    def enviar(self, local, remoto, substitui=0):
        d = self._dest(remoto)
        if d in self.fora:
            return False, "caiu"
        if d in self.mentir:
            return True, ""                       # rc=0 e nada gravado
        p = self._p(remoto)
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local, p)
        if self.orcamento is not None and A.nome_remoto(remoto):          # como o Rclone real: soma o enviado
            self.orcamento.somar_uso(A.nome_remoto(remoto), p.stat().st_size - substitui)
        if d in self.corromper:
            with open(p, "ab") as f:
                f.write(b"X")
        return True, ""

    def baixar(self, remoto, local, nbytes=0, amostra=False):
        nome, motivo = self._gate("baixar", remoto, nbytes, amostra=amostra)     # o pré-voo de verdade
        if motivo:
            return False, motivo
        p = self._p(remoto)
        if not p.exists():
            return False, "não existe"
        Path(local).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, local)
        self._registrar(nome, "baixar", subprocess.CompletedProcess([], 0, "", ""), p.stat().st_size, amostra=amostra)
        return True, ""

    def stat(self, remoto):
        p = self._p(remoto)
        if not p.exists():
            return None
        h = hashlib.md5(p.read_bytes()).hexdigest()
        return {"Size": p.stat().st_size, "Hashes": {"md5": h}}

    def hash_baixando(self, remoto, tipo="md5", nbytes=0):
        p = self._p(remoto)
        return hashlib.md5(p.read_bytes()).hexdigest() if p.exists() else None

    def acessivel(self, base):
        return self._dest(base) not in self.fora

    def listar(self, base):
        return []


@pytest.fixture()
def amb(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "_tmp_base", lambda: str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()
    monkeypatch.setattr(Z, "ESTADO", tmp_path / "estado")
    monkeypatch.setattr(A, "cache_frio", lambda: tmp_path / "cache")
    monkeypatch.setattr(A, "caminho_indice", lambda: tmp_path / "indice.db")
    monkeypatch.setattr(A, "dir_indices_outros", lambda: tmp_path / "outros")
    monkeypatch.setattr(A, "caminho_consumo", lambda: tmp_path / "consumo.json")
    monkeypatch.setattr(Z, "idade_dias", lambda p: 999.0)
    monkeypatch.setattr(Z, "_ABERTOS", set())
    monkeypatch.setattr(Z, "abertos_agora", lambda: set())
    monkeypatch.setenv("JFN_MAQUINA", "teste")
    raiz = tmp_path / "dados" / "vm2_quarentena"
    for proc in ("integra_070002_021988_2025", "integra_270090_000112_2023"):
        (raiz / proc).mkdir(parents=True)
        for i in range(3):
            (raiz / proc / f"{i:03d}.pdf").write_bytes(os.urandom(2048))
    return tmp_path, raiz


def _perfil(raiz, classe="quarentena"):
    return Z.Perfil("teste", raizes=[Z.Raiz(raiz, classe, idade_dias=1)], aviso_disco_pct=101)


def _arquivos(raiz):
    return sorted(p for p in raiz.rglob("*") if p.is_file())


# ── exclusão explícita ────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("caminho", [
    "/home/ubuntu/JFN/data/compliance.db", "/home/ubuntu/JFN/data/pcrj.db", "/home/ubuntu/JFN/data/receita_estab.db",
    "/home/ubuntu/JFN/data/territorio.db", "/home/ubuntu/JFN/.env", "/home/ubuntu/JFN/data/x.db-wal",
    "/home/ubuntu/JFN/data/x.db-shm", "/home/ubuntu/.config/rclone/rclone.conf", "/home/ubuntu/JFN-test/a.pdf",
    "/mnt/c/up/v69/frame.png", "/home/ubuntu/JFN/.git/objects/ab", "/home/ubuntu/JFN/tools/x.py",
    "/home/ubuntu/JFN/.claude/worktrees/storage/a.pdf", "/home/ubuntu/JFN/data/armazenamento_indice.db",
])
def test_exclusao_explicita_barra(caminho):
    assert Z.proibido(Path(caminho)) is not None


@pytest.mark.parametrize("caminho", [
    "/home/ubuntu/JFN/data/vm2_quarentena/integras-1/integra_1/001.pdf",
    "/home/ubuntu/arquivo_frio/sei_cache/integra_X/002.pdf",
    "/home/ubuntu/backups/compliance-20261116.db.gz",
])
def test_exclusao_nao_barra_o_que_e_frio(caminho):
    assert Z.proibido(Path(caminho)) is None


def test_pode_sair_travas(tmp_path, monkeypatch):
    f = tmp_path / "a.pdf"
    f.write_bytes(b"x")
    monkeypatch.setattr(Z, "idade_dias", lambda p: 10.0)
    assert Z.pode_sair(f, 7, checar_aberto=lambda p: False) is None              # positivo
    assert "menos de" in Z.pode_sair(f, 30, checar_aberto=lambda p: False)       # recente
    assert "aberto" in Z.pode_sair(f, 7, checar_aberto=lambda p: True)           # aberto
    assert "fila" in Z.pode_sair(f, 7, {"a.pdf"}, "a.pdf", checar_aberto=lambda p: False)
    ln = tmp_path / "l.pdf"
    ln.symlink_to(f)
    assert "regular" in Z.pode_sair(ln, 7, checar_aberto=lambda p: False)


def test_fila_velha_ou_ausente_e_falha(tmp_path):
    assert Z._ler_fila([tmp_path / "nao_existe.txt"]) is None
    f = tmp_path / "fila.txt"
    f.write_text("integra_X/001.pdf\n")
    assert Z._ler_fila([f]) == {"integra_X/001.pdf"}
    os.utime(f, (0, 0))
    assert Z._ler_fila([f]) is None


# ── a trava central: cópias conferidas NESTE ciclo ────────────────────────────────────────────────────────
def test_guardar_positivo_apaga_so_com_copia_conferida(amb):
    tmp, raiz = amb
    f = _arquivos(raiz)[0]
    r = A.guardar(f, "quarentena", apagar_local=True, rc=NuvemFalsa(tmp / "nuvem"), con=A.conectar())
    assert r["copias"] == {"gdrive": "ok"} and r["apagado"] and not f.exists()


def test_rclone_diz_ok_mas_nao_gravou_nao_apaga(amb):
    tmp, raiz = amb
    f = _arquivos(raiz)[0]
    r = A.guardar(f, "quarentena", apagar_local=True, rc=NuvemFalsa(tmp / "nuvem", mentir_envio={"gdrive"}),
                  con=A.conectar())
    assert r["copias"]["gdrive"] == "sumida" and not r["apagado"] and f.exists()


def test_copia_corrompida_nao_apaga(amb):
    tmp, raiz = amb
    f = _arquivos(raiz)[0]
    r = A.guardar(f, "quarentena", apagar_local=True, rc=NuvemFalsa(tmp / "nuvem", corromper={"gdrive"}),
                  con=A.conectar())
    assert r["copias"]["gdrive"] == "divergente" and f.exists()


def test_insubstituivel_exige_dois_provedores(amb):
    tmp, raiz = amb
    segunda = A.POLITICA["insubstituivel"][1]
    f = _arquivos(raiz)[0]
    r = A.guardar(f, "backup_db", apagar_local=True, rc=NuvemFalsa(tmp / "nuvem", fora=set(segunda)),
                  con=A.conectar())
    assert r["copias"]["gdrive"] == "ok" and not A.copias_ok(r["copias"]) & set(segunda) and f.exists()
    g = _arquivos(raiz)[1]
    r = A.guardar(g, "backup_db", apagar_local=True, rc=NuvemFalsa(tmp / "nuvem"), con=A.conectar())
    assert r["copias"] == {"gdrive": "ok", segunda[0]: "ok"} and not g.exists()


def test_segunda_copia_vai_para_a_que_couber(amb):
    """Dono 21/11: insubstituível = Drive + B2 OU R2 — a que couber. B2 no teto → R2; B2 caiu → R2."""
    tmp, raiz = amb
    b2 = A.NUVENS["remotos"]["b2"]
    cheio = (b2["armazenamento_gb"] - b2["margem_gb"] - b2.get("reserva_gb", 0)) * 1e9
    f, g = _arquivos(raiz)[:2]
    r = A.guardar(f, "backup_db", apagar_local=True, rc=NuvemFalsa(tmp / "nuvem", uso_extra={"b2": cheio}),
                  con=A.conectar())
    assert r["copias"] == {"gdrive": "ok", "r2": "ok"} and r["apagado"]
    r = A.guardar(g, "backup_db", apagar_local=True, rc=NuvemFalsa(tmp / "nuvem", fora={"b2"}), con=A.conectar())
    assert r["copias"] == {"gdrive": "ok", "b2": "sumida", "r2": "ok"} and r["apagado"]


def test_nenhuma_segunda_copia_cabe_recusa_e_nao_apaga(amb):
    tmp, raiz = amb
    cheios = {n: 25e9 for n in A.POLITICA["insubstituivel"][1]}
    f = _arquivos(raiz)[0]
    nuvem = NuvemFalsa(tmp / "nuvem", uso_extra=cheios)
    r = A.guardar(f, "backup_db", apagar_local=True, rc=nuvem, con=A.conectar())
    assert r["copias"]["|".join(A.POLITICA["insubstituivel"][1])] == "recusado" and f.exists()
    assert nuvem.orcamento.recusas


def test_conferencia_de_ciclo_anterior_nao_vale(amb):
    tmp, raiz = amb
    con = A.conectar()
    u = A.unidade_arquivo(_arquivos(raiz)[0], "quarentena")
    A.enviar_unidade(con, NuvemFalsa(tmp / "nuvem"), u, "ciclo-1")
    assert A.liberado_para_apagar(con, u.chave, "ciclo-1")
    assert not A.liberado_para_apagar(con, u.chave, "ciclo-2")


# ── o ciclo inteiro ───────────────────────────────────────────────────────────────────────────────────────
def test_aplicar_sem_ensaio_e_recusado(amb):
    tmp, raiz = amb
    with pytest.raises(SystemExit):
        Z.rodar(_perfil(raiz), aplicar=True, rc=NuvemFalsa(tmp / "nuvem"), con=A.conectar(), avisar_fn=lambda t: True)


def test_ensaio_nao_sobe_nem_apaga(amb):
    tmp, raiz = amb
    antes = _arquivos(raiz)
    rel = Z.rodar(_perfil(raiz), aplicar=False, rc=NuvemFalsa(tmp / "nuvem"), con=A.conectar(),
                  avisar_fn=lambda t: True)
    assert rel["status"] == "ok" and rel["candidatos"] == 2 and _arquivos(raiz) == antes
    assert not (tmp / "nuvem").exists()


def test_ciclo_completo_libera_journal_antes_e_recupera(amb):
    tmp, raiz = amb
    nuvem = NuvemFalsa(tmp / "nuvem")
    conteudo = {str(p): p.read_bytes() for p in _arquivos(raiz)}
    con = A.conectar()
    Z.rodar(_perfil(raiz), aplicar=False, rc=nuvem, con=con, avisar_fn=lambda t: True)
    rel = Z.rodar(_perfil(raiz), aplicar=True, rc=nuvem, con=con, avisar_fn=lambda t: True)
    assert rel["status"] == "ok" and rel["enviados"] == 2 and _arquivos(raiz) == []
    apagados = [r["alvo"] for r in con.execute("SELECT alvo FROM journal WHERE acao='apagar_local'")]
    assert sorted(apagados) == sorted(conteudo)                       # uma linha por arquivo, gravada antes
    alvo = sorted(conteudo)[0]
    assert A.obter(alvo, rc=nuvem).read_bytes() == conteudo[alvo]     # volta e confere
    assert A.obter(alvo, restaurar=True, rc=nuvem) == Path(alvo) and Path(alvo).read_bytes() == conteudo[alvo]
    assert any(r["chave"].startswith("teste/") for r in A.onde("070002/021988/2025"))


@pytest.mark.parametrize("nuvem_kw", [{"fora": {"gdrive"}}, {"mentir_envio": {"gdrive"}}, {"corromper": {"gdrive"}}])
def test_qualquer_falha_aborta_sem_apagar_e_avisa(amb, nuvem_kw):
    tmp, raiz = amb
    con = A.conectar()
    Z.rodar(_perfil(raiz), aplicar=False, rc=NuvemFalsa(tmp / "nuvem"), con=con, avisar_fn=lambda t: True)
    avisos = []
    antes = _arquivos(raiz)
    rel = Z.rodar(_perfil(raiz), aplicar=True, rc=NuvemFalsa(tmp / "nuvem", **nuvem_kw), con=con,
                  avisar_fn=lambda t: avisos.append(t) or True)
    assert rel["status"] == "abortado" and _arquivos(raiz) == antes and rel["liberado_gb"] == 0
    assert avisos and "ESCALADO" in avisos[0]


def test_recuperacao_que_falha_aborta_o_ciclo(amb):
    tmp, raiz = amb
    nuvem = NuvemFalsa(tmp / "nuvem")
    con = A.conectar()
    A.guardar(_arquivos(raiz)[0], "quarentena", rc=nuvem, con=con)   # uma cópia antiga, sem apagar
    assert Z.rodar(_perfil(raiz), aplicar=False, rc=nuvem, con=con, avisar_fn=lambda t: True)["status"] == "ok"
    for p in (tmp / "nuvem").rglob("*"):                               # depois, a nuvem estraga o objeto
        if p.is_file():
            p.write_bytes(b"estragado")
    ensaio = Z.rodar(_perfil(raiz), aplicar=False, rc=nuvem, con=con, avisar_fn=lambda t: True)
    assert ensaio["status"] == "abortado"                              # o ensaio também enxerga
    antes = _arquivos(raiz)
    rel = Z.rodar(_perfil(raiz), aplicar=True, rc=nuvem, con=con, avisar_fn=lambda t: True)
    assert rel["status"] == "abortado" and any("recuperação" in f for f in rel["falhas"])
    assert _arquivos(raiz) == antes


def test_arquivo_aberto_segura_a_pasta(amb, monkeypatch):
    tmp, raiz = amb
    preso = _arquivos(raiz)[0]
    monkeypatch.setattr(Z, "_ABERTOS", {str(preso)})
    monkeypatch.setattr(Z, "abertos_agora", lambda: {str(preso)})
    con = A.conectar()
    Z.rodar(_perfil(raiz), aplicar=False, rc=NuvemFalsa(tmp / "nuvem"), con=con, avisar_fn=lambda t: True)
    rel = Z.rodar(_perfil(raiz), aplicar=True, rc=NuvemFalsa(tmp / "nuvem"), con=con, avisar_fn=lambda t: True)
    assert preso.exists() and all(p.parent == preso.parent for p in _arquivos(raiz))
    assert rel["recusados"].get("aberto por algum processo") == 1


def test_teto_do_ciclo(amb):
    tmp, raiz = amb
    rel = Z.rodar(Z.Perfil("teste", raizes=[Z.Raiz(raiz, "quarentena", idade_dias=1)], teto_gb=7000 / 1e9,
                           aviso_disco_pct=101), aplicar=False, rc=NuvemFalsa(tmp / "nuvem"), con=A.conectar(),
                  avisar_fn=lambda t: True)
    assert rel["candidatos"] == 1 and rel["recusados"].get("teto do ciclo") == 1


def test_obter_com_nuvem_corrompida_nao_entrega_lixo(amb):
    tmp, raiz = amb
    nuvem = NuvemFalsa(tmp / "nuvem")
    f = _arquivos(raiz)[0]
    alvo = str(f)
    A.guardar(f, "quarentena", apagar_local=True, rc=nuvem, con=A.conectar())
    for p in (tmp / "nuvem").rglob("*"):
        if p.is_file():
            p.write_bytes(b"estragado")
    with pytest.raises(FileNotFoundError):
        A.obter(alvo, rc=nuvem)


def test_processo_e_cnpj_extraidos():
    assert A.processo_de("/x/integra_070002_021988_2025/001.pdf") == "070002/021988/2025"
    assert A.cnpj_de("fornecedor_12345678000199.json") == "12345678000199"
    assert A.processo_de("sem processo") is None


def test_perfil_de_teste_nunca_toca_navegador_real(amb, monkeypatch):
    tmp, raiz = amb
    def explode():
        raise AssertionError("navegadores_sem_dono chamado fora de perfil real")
    monkeypatch.setattr(Z, "navegadores_sem_dono", explode)
    con = A.conectar()
    Z.rodar(_perfil(raiz), aplicar=False, rc=NuvemFalsa(tmp / "nuvem"), con=con, avisar_fn=lambda t: True)
    Z.rodar(_perfil(raiz), aplicar=True, rc=NuvemFalsa(tmp / "nuvem"), con=con, avisar_fn=lambda t: True)
    assert Z.perfis()["vm1"].limpar_navegadores and not _perfil(raiz).limpar_navegadores


def test_so_backup_sobe_nao_apaga_e_nao_resobe(amb):
    tmp, raiz = amb
    perfil = Z.Perfil("teste", raizes=[Z.Raiz(raiz, "sei_pdf", idade_dias=1, so_backup=True)], aviso_disco_pct=101)
    nuvem = NuvemFalsa(tmp / "nuvem")
    con = A.conectar()
    antes = _arquivos(raiz)
    Z.rodar(perfil, aplicar=False, rc=nuvem, con=con, avisar_fn=lambda t: True)
    r1 = Z.rodar(perfil, aplicar=True, rc=nuvem, con=con, avisar_fn=lambda t: True)
    assert r1["enviados"] == 2 and _arquivos(raiz) == antes                 # subiu, nada apagado
    r2 = Z.rodar(perfil, aplicar=True, rc=nuvem, con=con, avisar_fn=lambda t: True)
    assert r2["enviados"] == 0 and r2["recusados"].get("já na nuvem (só backup)") == 2
    (raiz / "integra_070002_021988_2025" / "009.pdf").write_bytes(b"novo")  # pasta mudou → sobe de novo
    r3 = Z.rodar(perfil, aplicar=True, rc=nuvem, con=con, avisar_fn=lambda t: True)
    assert r3["enviados"] == 1


def test_vigiar_avisa_abortado_e_parado_uma_vez(amb, monkeypatch):
    import datetime as dt
    tmp, raiz = amb
    (tmp / "outros").mkdir()
    con = A.conectar(tmp / "outros" / "vm2.db")
    velho = (dt.datetime.now() - dt.timedelta(days=20)).isoformat(timespec="seconds")
    con.execute("INSERT INTO ciclos VALUES('vm2-x','vm2','vm2','aplicar',?,?, 'abortado', ?)",
                (velho, velho, '{"disco_pct_depois": 91, "falhas": ["destino inacessível: gdrive"]}'))
    con.commit()
    ditos = []
    Z.ESTADO.mkdir(parents=True, exist_ok=True)
    Z.vigiar_outros(avisar_fn=ditos.append)
    assert len(ditos) == 2 and "ABORTADO" in ditos[0] and "não roda" in ditos[1]
    Z.vigiar_outros(avisar_fn=ditos.append)
    assert len(ditos) == 2                                    # não repete


def test_reenvio_vira_reconferencia_e_libera(amb):
    tmp, raiz = amb
    nuvem = NuvemFalsa(tmp / "nuvem")
    con = A.conectar()
    perfil = Z.Perfil("teste", raizes=[Z.Raiz(raiz, "quarentena", idade_dias=1)], aviso_disco_pct=101)
    Z.rodar(perfil, aplicar=False, rc=nuvem, con=con, avisar_fn=lambda t: True)
    # ciclo anterior subiu mas morreu antes de apagar: simula com o envio direto
    c = Z.Ciclo(perfil, True, nuvem, con, 40, id="morto")
    Z.coletar(c)
    Z.enviar(c)
    assert len(c.enviados) == 2 and len(_arquivos(raiz)) == 6
    objetos = sorted((tmp / "nuvem").rglob("*.tar"))
    rel = Z.rodar(perfil, aplicar=True, rc=NuvemFalsa(tmp / "nuvem", mentir_envio={"gdrive"}), con=con,
                  avisar_fn=lambda t: True)          # um envio de verdade "mentiria"; reconferir não envia
    assert rel["status"] == "ok" and _arquivos(raiz) == []
    assert sorted((tmp / "nuvem").rglob("*.tar")) == objetos


def test_reconferencia_que_falha_nao_apaga(amb):
    tmp, raiz = amb
    nuvem = NuvemFalsa(tmp / "nuvem")
    con = A.conectar()
    perfil = Z.Perfil("teste", raizes=[Z.Raiz(raiz, "quarentena", idade_dias=1)], aviso_disco_pct=101)
    Z.rodar(perfil, aplicar=False, rc=nuvem, con=con, avisar_fn=lambda t: True)
    c = Z.Ciclo(perfil, True, nuvem, con, 40, id="morto")
    Z.coletar(c)
    Z.enviar(c)
    for p in (tmp / "nuvem").rglob("*.tar"):
        p.unlink()                                   # a nuvem perdeu os pacotes
    rel = Z.rodar(perfil, aplicar=True, rc=NuvemFalsa(tmp / "nuvem", mentir_envio={"gdrive"}), con=con,
                  avisar_fn=lambda t: True)
    assert rel["status"] == "abortado" and len(_arquivos(raiz)) == 6


def test_indice_que_nao_sobe_antes_de_liberar_nao_apaga(amb):
    tmp, raiz = amb
    con = A.conectar()

    class SemIndice(NuvemFalsa):
        def enviar(self, local, remoto):
            if "/indice" in remoto or remoto.startswith("gdrive:indice"):
                return True, ""                     # "ok" sem gravar o índice
            return super().enviar(local, remoto)

    Z.rodar(_perfil(raiz), aplicar=False, rc=NuvemFalsa(tmp / "nuvem"), con=con, avisar_fn=lambda t: True)
    antes = _arquivos(raiz)
    rel = Z.rodar(_perfil(raiz), aplicar=True, rc=SemIndice(tmp / "nuvem"), con=con, avisar_fn=lambda t: True)
    assert rel["status"] == "abortado" and _arquivos(raiz) == antes


# ── pré-voo por nuvem: limites GRÁTIS da config, controle positivo (no limite passa) e negativo (acima recusa) ──
class RcloneDeMentira(A.Rclone):
    """O Rclone de verdade (pré-voo, contador, recusa), só o PROCESSO é falso: `_run` responde como o rclone."""

    def __init__(self, uso=None, stderr_copyto="", rc_copyto=0):
        super().__init__(binario="rclone-de-mentira")
        self.uso_fake = dict(uso or {})
        self.stderr_copyto, self.rc_copyto = stderr_copyto, rc_copyto
        self.chamadas = []

    def _run(self, args, timeout=None):
        self.chamadas.append(args)
        cp = subprocess.CompletedProcess
        nome = str(args[-1]).split(":", 1)[0]
        if args[0] == "size":
            return cp(args, 0, json.dumps({"count": 10, "bytes": self.uso_fake.get(nome, 0)}), "")
        if args[0] == "about":
            return cp(args, 0, json.dumps({"total": 20e9, "free": 20e9 - self.uso_fake.get(nome, 0)}), "")
        if args[0] == "copyto":
            if self.rc_copyto == 0 and ":" not in str(args[2]):
                Path(args[2]).write_bytes(b"x")
            return cp(args, self.rc_copyto, "", self.stderr_copyto)
        if args[0] == "lsjson":
            return cp(args, 0, json.dumps({"Size": 1, "Hashes": {}}), "")
        return cp(args, 0, "", "")


def _partilha(maq="vm1"):
    return A.NUVENS["partilha_por_maquina"][maq]


def _rc(tmp_path, **kw):
    rc = RcloneDeMentira(**kw)
    rc.orcamento = A.Orcamento(caminho=tmp_path / "consumo.json", maq="vm1")
    return rc


def _fazer(rc, nome, op, tmp_path):
    alvo = A.NUVENS["remotos"][nome]["frio"] + "/x"
    if op == "baixar":
        return rc.baixar(alvo, tmp_path / "baixado", nbytes=1000)[0]
    if op == "stat":
        return rc.stat(alvo) is not None
    return rc.acessivel(alvo)


@pytest.mark.parametrize("nome,chave,op", [
    ("b2", "download_bytes_dia", "baixar"), ("b2", "classe_b_dia", "stat"), ("b2", "classe_c_dia", "acessivel"),
    ("r2", "classe_a_mes", "acessivel"), ("r2", "classe_b_mes", "stat"), ("mega", "download_bytes_dia", "baixar"),
])
def test_limite_de_operacao_passa_no_limite_e_recusa_acima(tmp_path, nome, chave, op):
    rc = _rc(tmp_path)
    contador, _ = chave.rsplit("_", 1)
    teto = A.NUVENS["remotos"][nome]["limites"][chave] * _partilha()
    pedido = A.custo_operacao(A.NUVENS["remotos"][nome]["tipo"], op, 1000)[contador]
    rc.orcamento.registrar(nome, {contador: teto - pedido})        # depois desta operação: exatamente no teto
    n0 = len(rc.chamadas)
    assert _fazer(rc, nome, op, tmp_path) and len(rc.chamadas) == n0 + 1          # positivo: chegou ao rclone
    assert not _fazer(rc, nome, op, tmp_path) and len(rc.chamadas) == n0 + 1      # negativo: nem chamou
    assert rc.orcamento.recusas and contador in rc.orcamento.recusas[-1]


@pytest.mark.parametrize("nome", ["b2", "r2", "mega"])
def test_armazenamento_passa_ate_o_alvo_e_recusa_acima(tmp_path, nome):
    cfg = A.NUVENS["remotos"][nome]
    total = (cfg.get("armazenamento_gb") or 20) * 1e9                       # MEGA: o que o `about` mediu
    alvo = total - (cfg.get("margem_gb", 0) + cfg.get("reserva_gb", 0)) * 1e9
    rc = _rc(tmp_path, uso={nome: alvo - 1000})
    f = tmp_path / "f.bin"
    f.write_bytes(b"0" * 1000)
    assert rc.enviar(f, cfg["frio"] + "/f.bin")[0]                          # positivo: fecha no alvo
    ok, err = rc.enviar(f, cfg["frio"] + "/g.bin")                         # negativo: 1000 B acima
    assert not ok and err.startswith("RECUSADO") and "alvo" in err


def test_sem_medida_de_uso_nao_sobe(tmp_path):
    class SemMedida(RcloneDeMentira):
        def _run(self, args, timeout=None):
            if args[0] in ("size", "about"):
                return subprocess.CompletedProcess(args, 1, "", "falhou")
            return super()._run(args, timeout)
    rc = SemMedida()
    rc.orcamento = A.Orcamento(caminho=tmp_path / "c.json", maq="vm1")
    f = tmp_path / "f.bin"
    f.write_bytes(b"0")
    ok, err = rc.enviar(f, A.NUVENS["remotos"]["b2"]["frio"] + "/f.bin")
    assert not ok and "não medido" in err
    assert rc.enviar(f, "gdrive:frio/f.bin")[0] is False                    # o principal também é medido


def test_provedor_diz_cap_exceeded_esgota_ate_00h_utc(tmp_path):
    rc = _rc(tmp_path, rc_copyto=1, stderr_copyto="ERROR : 403 download_cap_exceeded")
    alvo = A.NUVENS["remotos"]["b2"]["frio"] + "/x"
    assert not rc.baixar(alvo, tmp_path / "b", nbytes=10)[0]
    assert rc.stat(alvo) is None and "esgotado" in rc.orcamento.recusas[-1]     # nem chama mais o B2 hoje
    est = json.loads((tmp_path / "consumo.json").read_text())
    est["b2"]["esgotado_ate"] = "2000-01-01T00:00:00+00:00"                     # o dia virou
    (tmp_path / "consumo.json").write_text(json.dumps(est))
    assert rc.stat(alvo) is not None                                           # controle positivo


def test_partilha_entre_maquinas(tmp_path):
    lim = A.NUVENS["remotos"]["b2"]["limites"]["download_bytes_dia"]
    for maq in ("vm1", "vm2"):
        o = A.Orcamento(caminho=tmp_path / f"{maq}.json", maq=maq)
        assert o.recusa("b2", {"download_bytes": lim * _partilha(maq)}) is None
        assert o.recusa("b2", {"download_bytes": lim * _partilha(maq) + 1})
    assert sum(A.NUVENS["partilha_por_maquina"].values()) <= 1.0              # somadas, nunca passam do grátis


def test_recuperacao_confere_pela_listagem_e_amostra_do_b2_tem_teto(amb):
    tmp, raiz = amb
    nuvem = NuvemFalsa(tmp / "nuvem", fora={"r2", "mega"})
    con = A.conectar()
    for f in _arquivos(raiz)[:3]:
        A.guardar(f, "backup_db", rc=nuvem, con=con)                       # gdrive + b2
    res = A.testar_recuperacao(con, nuvem, amostra=3)
    b2 = [r for r in res if r["destino"] == "b2"]
    assert [r["modo"] for r in b2].count("listagem") == 3 and any(r["modo"] == "download" for r in b2)
    assert all(r["ok"] for r in res)
    teto = A.NUVENS["remotos"]["b2"]["amostra_download_mb_dia"] * 1e6 * nuvem.orcamento.partilha()
    nuvem.orcamento.registrar("b2", {"amostra_bytes": teto})                 # a amostra do dia acabou
    res = A.testar_recuperacao(con, nuvem, amostra=3)
    b2 = [r for r in res if r["destino"] == "b2"]
    assert any(r["modo"] == "download recusado" for r in b2) and all(r["ok"] for r in res)
    for p in (tmp / "nuvem" / "b2").rglob("*"):                               # negativo: B2 estragado aparece
        if p.is_file():
            p.write_bytes(b"estragado")
    assert not all(r["ok"] for r in A.testar_recuperacao(con, nuvem, amostra=3) if r["destino"] == "b2")


def test_remoto_novo_entra_so_pela_config(amb, tmp_path_factory):
    tmp, raiz = amb
    cfg = json.loads(A.caminho_config_nuvens().read_text(encoding="utf-8"))
    cfg["remotos"]["koofr"] = {"tipo": "koofr", "raiz": "koofr:JFN", "frio": "koofr:JFN/frio",
                               "indice": "koofr:JFN/indice", "medir": "about", "margem_gb": 0.5,
                               "preferencia_download": 4, "limites": {"download_bytes_dia": 1e9}}
    cfg["segunda_copia"] = ["koofr", *cfg["segunda_copia"]]
    novo = tmp_path_factory.mktemp("cfg") / "nuvens.json"
    novo.write_text(json.dumps(cfg), encoding="utf-8")
    try:
        A.configurar(novo)
        assert "koofr" in A.DESTINOS and A.POLITICA["insubstituivel"][1][0] == "koofr"
        f = _arquivos(raiz)[0]
        conteudo = f.read_bytes()
        r = A.guardar(f, "backup_db", apagar_local=True, rc=NuvemFalsa(tmp / "nuvem"), con=A.conectar())
        assert r["copias"] == {"gdrive": "ok", "koofr": "ok"} and r["apagado"]
        assert A.obter(str(f), rc=NuvemFalsa(tmp / "nuvem")).read_bytes() == conteudo
    finally:
        A.configurar()
    assert "koofr" not in A.DESTINOS                                          # controle: sem a config, não existe


def test_ciclo_com_recusa_do_prevoo_escala_e_nao_apaga(amb):
    tmp, raiz = amb
    con = A.conectar()
    perfil = Z.Perfil("teste", raizes=[Z.Raiz(raiz, "backup_db", idade_dias=1)], aviso_disco_pct=101)
    cheios = {n: 25e9 for n in A.POLITICA["insubstituivel"][1]}
    Z.rodar(perfil, aplicar=False, rc=NuvemFalsa(tmp / "nuvem"), con=con, avisar_fn=lambda t: True)
    avisos, antes = [], _arquivos(raiz)
    rel = Z.rodar(perfil, aplicar=True, rc=NuvemFalsa(tmp / "nuvem", uso_extra=cheios), con=con,
                  avisar_fn=lambda t: avisos.append(t) or True)
    assert rel["status"] == "abortado" and _arquivos(raiz) == antes and rel["recusas_prevoo"]
    assert avisos and "pré-voo" in avisos[0] and "ESCALADO" in avisos[0]
    assert con.execute("SELECT COUNT(*) FROM journal WHERE acao='recusado_prevoo'").fetchone()[0] >= 1


def test_encher_respeita_alvo_e_prioridade(amb, monkeypatch):
    import sqlite3
    tmp, raiz = amb
    monkeypatch.setattr(A, "HOME", tmp)
    for nome, n in (("a.db", 30000), ("b.db", 30000)):
        c = sqlite3.connect(tmp / nome)
        c.execute("CREATE TABLE t(x)")
        c.execute("INSERT INTO t VALUES(?)", (os.urandom(n),))       # incompressível
        c.commit()
        c.close()
    itens = [{"nome": "a.db", "tipo": "sqlite", "caminho": "a.db", "classe": "backup_db"},
             {"nome": "b.db", "tipo": "sqlite", "caminho": "b.db", "classe": "backup_db"},
             {"nome": "ausente.db", "tipo": "sqlite", "caminho": "nao.db", "classe": "backup_db"}]
    b2 = A.NUVENS["remotos"]["b2"]
    alvo_b2 = (b2["armazenamento_gb"] - b2["margem_gb"] - b2.get("reserva_gb", 0)) * 1e9
    tam_a = A.snapshot_sqlite_gz(tmp / "a.db", tmp / "medida" / "a.db.gz").stat().st_size   # o .gz real
    nuvem = NuvemFalsa(tmp / "nuvem", uso_extra={"b2": alvo_b2 - tam_a - 1})   # no B2 só cabe o 1º
    con = A.conectar()
    plano = A.encher(con, nuvem, aplicar=False, itens=itens, remotos=["b2", "r2"])
    assert plano[0]["destinos_plano"] == ["gdrive", "r2"] and plano[0]["talvez_comprimido"] == ["b2"]
    assert plano[2]["status"] == "ausente"
    assert not (tmp / "nuvem").exists()                                      # o plano não sobe nada
    feito = A.encher(con, nuvem, aplicar=True, itens=itens, remotos=["b2", "r2"])
    assert A.copias_ok(feito[0]["copias"]) == {"gdrive", "b2", "r2"}
    assert A.copias_ok(feito[1]["copias"]) == {"gdrive", "r2"}               # o 2º não cabe mais no B2
    assert A.obter(str(tmp / "a.db.gz"), rc=nuvem).exists()
