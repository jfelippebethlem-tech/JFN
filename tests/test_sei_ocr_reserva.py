"""OCR de reserva nas VMs (18/11/2026): precedência no integrador, gatilho da GPU parada, coordenação com a fila da
GPU (sem duplicar), correção decimal e trava de carga. Cada regra com controle positivo E negativo."""
from __future__ import annotations

import json
import time

import pytest

import tools.sei_ocr_gpu_integrar as G
import tools.sei_ocr_reserva as R

TAG = "111_222_2024"


@pytest.fixture
def casa(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "ARQUIVO", tmp_path / "sei_arquivo")
    monkeypatch.setattr(G, "CACHE", tmp_path / "sei_cache")
    monkeypatch.setattr(G, "LEDGER", tmp_path / "ledger.jsonl")
    monkeypatch.setattr(R, "LEDGER", tmp_path / "ledger.jsonl")
    monkeypatch.setattr(R, "CACHE", tmp_path / "sei_cache")
    monkeypatch.setattr(R, "DATA", tmp_path)
    monkeypatch.setattr(R, "ESTADO", tmp_path / "estado.json")
    monkeypatch.setattr(R, "LOG", tmp_path / "reserva.log")
    monkeypatch.setattr(R, "PAUSA", tmp_path / ".pause_ocr_reserva")
    monkeypatch.setattr(R, "FILA_VM1", tmp_path / "fila_vm1.txt")
    (tmp_path / "sei_arquivo" / TAG / "texto").mkdir(parents=True)
    (tmp_path / "sei_cache" / f"integra_{TAG}").mkdir(parents=True)
    return tmp_path


def _manifesto(casa, docs, textos=None):
    arq = casa / "sei_arquivo" / TAG
    for nome, t in (textos or {}).items():
        (arq / "texto" / nome).write_text(t, encoding="utf-8")
    (arq / "manifest.json").write_text(json.dumps({"docs": docs}), encoding="utf-8")
    return arq


def _entrega(casa, i, texto, motor):
    suf = ".ocr_gpu" if motor == "surya" else ".ocr_reserva"
    d = casa / "sei_cache" / f"integra_{TAG}"
    (d / f"{i:03d}{suf}.txt").write_text(texto, encoding="utf-8")
    (d / f"{i:03d}{suf}.json").write_text(json.dumps(
        {"motor": "surya-ocr-2.5 (vLLM)" if motor == "surya" else R.MOTOR, "paginas": 1}))


def _docs(arq):
    return {d["i"]: d for d in json.loads((arq / "manifest.json").read_text())["docs"]}


# ───────────────────────────── precedência no integrador ─────────────────────────────

def test_reserva_preenche_substitui_tesseract_e_nunca_toca_nativo(casa):
    arq = _manifesto(casa, [
        {"i": 0, "titulo": "NF", "fase": "despesa", "tipo": "nota_fiscal", "texto": "", "chars": 0},
        {"i": 1, "titulo": "Pub", "fase": "x", "tipo": "outro", "texto": "texto/001_pub.txt", "chars": 60, "ocr": True},
        {"i": 2, "titulo": "Desp", "fase": "x", "tipo": "despacho", "texto": "texto/002_desp.txt", "chars": 70,
         "ocr": False}],
        {"001_pub.txt": "[Pub]\n\nDIÁRIO E) OFICIAL DO RFO DE JANEIRO tesseract",
         "002_desp.txt": "[Desp]\n\nEncaminho o processo à DIRAF, texto nativo do PDF."})
    _entrega(casa, 0, "NOTA FISCAL DE SERVIÇO Nº 53 Valor R$ 94.999,98 prestado em março", "reserva")
    _entrega(casa, 1, "DIÁRIO OFICIAL DO ESTADO DO RIO DE JANEIRO — publicação do extrato", "reserva")
    _entrega(casa, 2, "lixo da reserva que não pode substituir o texto nativo do PDF", "reserva")
    res = G.integrar()
    d = _docs(arq)
    assert res["preenchidos"] == 1 and res["substituidos"] == 1 and res["nativos_mantidos"] == 1
    assert d[0]["ocr_motor"].startswith("reserva:") and d[0]["texto_recuperado_ocr_reserva"] is True
    assert "94.999,98" in (arq / d[0]["texto"]).read_text()
    assert d[1]["ocr_motor"].startswith("reserva:") and "RFO" in (arq / d[1]["ocr_anterior"]).read_text()
    assert d[1]["ocr_anterior"].endswith(".tesseract.txt")
    assert "lixo" not in (arq / "texto" / "002_desp.txt").read_text() and "ocr_motor" not in d[2]   # negativo
    motores = {json.loads(ln)["motor"] for ln in (casa / "ledger.jsonl").read_text().splitlines()}
    assert motores == {"reserva"}


def test_surya_substitui_reserva_quando_chega_e_guarda_os_dois_anteriores(casa):
    arq = _manifesto(casa, [{"i": 1, "titulo": "Pub", "fase": "x", "tipo": "outro", "texto": "texto/001_pub.txt",
                             "chars": 60, "ocr": True}],
                     {"001_pub.txt": "[Pub]\n\nDIÁRIO E) OFICIAL DO RFO tesseract original"})
    _entrega(casa, 1, "DIARIO OFICIAL DO ESTADO DO RIO DE JANEIRO pela reserva da VM-2", "reserva")
    G.integrar()
    _entrega(casa, 1, "DIÁRIO OFICIAL DO ESTADO DO RIO DE JANEIRO lido pelo Surya na GPU", "surya")
    res = G.integrar()
    d = _docs(arq)[1]
    assert res["substituidos"] == 1 and d["ocr_motor"].startswith("surya")
    assert "Surya" in (arq / d["texto"]).read_text()
    assert d["ocr_anterior"].endswith(".reserva.txt") and "reserva da VM-2" in (arq / d["ocr_anterior"]).read_text()
    assert "tesseract original" in (arq / "texto" / "001_pub.tesseract.txt").read_text()   # o do Tesseract segue lá


def test_reserva_que_chega_depois_do_surya_nao_entra(casa):
    arq = _manifesto(casa, [{"i": 0, "titulo": "NF", "fase": "d", "tipo": "nota_fiscal", "texto": "", "chars": 0}])
    _entrega(casa, 0, "NOTA FISCAL lida pelo Surya na GPU, valor R$ 1.234,56 em março", "surya")
    G.integrar()
    _entrega(casa, 0, "NOTA FISCAL lida pela reserva, valor R$ 1.234.56 em marco", "reserva")
    res = G.integrar()
    d = _docs(arq)[0]
    assert res["preenchidos"] == 0 and res["substituidos"] == 0 and res["mantido_superior"] == 1
    assert d["ocr_motor"].startswith("surya") and "Surya" in (arq / d["texto"]).read_text()
    assert G.integrar().get("mantido_superior") is None          # registrada: não reprocessa


def test_surya_e_reserva_na_mesma_rodada_vence_o_surya(casa):
    arq = _manifesto(casa, [{"i": 0, "titulo": "NF", "fase": "d", "tipo": "nota_fiscal", "texto": "", "chars": 0}])
    _entrega(casa, 0, "NOTA FISCAL lida pela reserva, valor R$ 1.234,56 em março de 2025", "reserva")
    _entrega(casa, 0, "NOTA FISCAL lida pelo Surya na GPU, valor R$ 1.234,56 em março de 2025", "surya")
    res = G.integrar()
    assert res["preenchidos"] == 1 and res["mantido_superior"] == 1
    assert _docs(arq)[0]["ocr_motor"].startswith("surya")


def test_reserva_vazia_ou_com_acento_quebrado_nao_entra(casa):
    arq = _manifesto(casa, [{"i": 0, "titulo": "NF", "fase": "d", "tipo": "nota_fiscal", "texto": "", "chars": 0}])
    _entrega(casa, 0, "[página 1]\n  ", "reserva")
    assert G.integrar()["preenchidos"] == 0
    assert not (casa / "sei_cache" / f"integra_{TAG}" / "000.ocr_reserva.txt").exists()   # volta na releitura
    assert _docs(arq)[0]["chars"] == 0


# ───────────────────────────── correção decimal ─────────────────────────────

@pytest.mark.parametrize("cru,certo", [("Valor R$ 94.999.98", "Valor R$ 94.999,98"), ("1.234.56 | 2.000.00", "1.234,56 | 2.000,00"),
                                       ("total 1.234.567.89", "total 1.234.567,89")])
def test_correcao_decimal_positivo(cru, certo):
    assert R.corrigir(cru) == certo


@pytest.mark.parametrize("t", ["CNPJ 12.345.678/0001-90", "CPF 123.456.789-01", "pi 3.14", "data 18.11.2026",
                               "R$ 94.999,98", "versão 1.2.3.45", "processo 150016/008912/2025"])
def test_correcao_decimal_negativo_nao_mexe(t):
    assert R.corrigir(t) == t


# ───────────────────────────── gatilho: pulso real da GPU ─────────────────────────────

def _saida(agora, vivo=True, pausa=False, lote_ha_min=10, pend=("integra_a/001.pdf",)):
    linhas = [f"agora={agora}", f"vivo={'4242' if vivo else ''}", f"pausa={1 if pausa else 0}"]
    if lote_ha_min is not None:
        linhas.append(f"lote_epoch={agora - lote_ha_min * 60}")
    return "\n".join(linhas + ["fila_md5=abc", "---pendentes---", *pend]) + "\n"


def test_pulso_gpu_ativa_nao_dispara():
    p = R.interpretar_pulso(_saida(10_000_000), None)
    assert p["parada"] is False and p["ssh"] is True and p["pendentes"] == ["integra_a/001.pdf"]


@pytest.mark.parametrize("kw,trecho", [({"vivo": False}, "morto"), ({"pausa": True}, "PAUSA"),
                                       ({"lote_ha_min": 200}, "último lote"), ({"lote_ha_min": None}, "nenhum lote")])
def test_pulso_gpu_parada_dispara(kw, trecho):
    p = R.interpretar_pulso(_saida(10_000_000, **kw), None)
    assert p["parada"] is True and trecho in p["motivo"]


def test_pulso_sem_ssh_so_dispara_com_entrega_velha_na_vm1():
    agora = 10_000_000
    assert R.interpretar_pulso(None, agora - 20 * 60, agora)["parada"] is False          # entrega recente: indeterminado
    assert R.interpretar_pulso(None, None, agora)["parada"] is False                     # nada medido: não roda
    assert R.interpretar_pulso(None, agora - 200 * 60, agora)["parada"] is True


# ───────────────────────────── coordenação com a fila da GPU ─────────────────────────────

def test_escolher_pega_do_fim_respeita_margem_e_exclusao():
    fila = [f"integra_t/{i:03d}.pdf" for i in range(10)]
    assert R.escolher(fila, set(), 3, margem=4) == ["integra_t/009.pdf", "integra_t/008.pdf", "integra_t/007.pdf"]
    assert R.escolher(fila, {"integra_t/009.pdf"}, 2, margem=4) == ["integra_t/008.pdf", "integra_t/007.pdf"]
    assert R.escolher(fila, set(), 50, margem=4) == fila[4:][::-1]          # nunca a cabeça (margem)
    assert R.escolher(fila, set(), 3, margem=10) == []                     # fila curta: a GPU chega lá — não toca


def test_prova_disjuncao_com_o_lote_da_gpu():
    """O lote em curso da GPU são os 40 primeiros pendentes; a reserva só pega de MARGEM em diante."""
    fila = [f"integra_t/{i:04d}.pdf" for i in range(R.MARGEM + 100)]
    lote_gpu = set(fila[:40])
    assert not lote_gpu & set(R.escolher(fila, set(), 100))
    assert R.MARGEM >= 40 * 5


def _pulso(parada, pend, ssh=True):
    return {"ssh": ssh, "parada": parada, "pendentes": pend if ssh else None, "fila_md5": "m5", "motivo": "teste"}


def test_reservar_gpu_ativa_nao_reserva_nada(casa, monkeypatch):
    fila = [f"integra_t/{i:04d}.pdf" for i in range(R.MARGEM + 50)]
    monkeypatch.setattr(R, "pulso_gpu", lambda: _pulso(False, fila))
    chamadas = []
    monkeypatch.setattr(R, "_tirar_da_fila_gpu", lambda rels, md5: chamadas.append(rels) or "OK")
    assert R.reservar(5, "vm2")["itens"] == [] and chamadas == []


def test_reservar_gpu_parada_tira_da_fila_do_itcampo_e_exclui_da_fila_da_vm1(casa, monkeypatch):
    fila = [f"integra_t/{i:04d}.pdf" for i in range(R.MARGEM + 50)]
    monkeypatch.setattr(R, "pulso_gpu", lambda: _pulso(True, fila))
    chamadas = []
    monkeypatch.setattr(R, "_tirar_da_fila_gpu", lambda rels, md5: chamadas.append((rels, md5)) or "OK 7000")
    itens = R.reservar(5, "vm2")["itens"]
    assert itens == fila[-5:][::-1] and chamadas == [(itens, "m5")]
    assert R.reservados_pela_reserva() == set(itens)
    # 2ª rodada: o que já está reservado volta primeiro e nada é pego duas vezes
    itens2 = R.reservar(8, "vm2")["itens"]
    assert itens2[:5] == sorted(itens) and not set(itens2[5:]) & set(itens)


def test_reservar_troca_da_fila_recusada_nao_reserva(casa, monkeypatch):
    fila = [f"integra_t/{i:04d}.pdf" for i in range(R.MARGEM + 50)]
    monkeypatch.setattr(R, "pulso_gpu", lambda: _pulso(True, fila))
    monkeypatch.setattr(R, "_tirar_da_fila_gpu", lambda rels, md5: "CAS_MUDOU")
    assert R.reservar(5, "vm2")["itens"] == [] and R.reservados_pela_reserva() == set()


def test_reservar_sem_ssh_marca_retirada_pendente_e_faz_no_primeiro_contato(casa, monkeypatch):
    fila = [f"integra_t/{i:04d}.pdf" for i in range(R.MARGEM + 50)]
    R.FILA_VM1.write_text("\n".join(fila))
    monkeypatch.setattr(R, "pulso_gpu", lambda: _pulso(True, None, ssh=False))
    chamadas = []
    monkeypatch.setattr(R, "_tirar_da_fila_gpu", lambda rels, md5: chamadas.append(rels) or "OK")
    itens = R.reservar(3, "vm2")["itens"]
    assert len(itens) == 3 and chamadas == []
    assert all(e.get("tirar_pendente") for e in json.loads(R.ESTADO.read_text()).values())
    monkeypatch.setattr(R, "pulso_gpu", lambda: _pulso(False, fila))
    R.reservar(3, "vm2")
    assert chamadas[0] == sorted(itens)
    assert not any(e.get("tirar_pendente") for e in json.loads(R.ESTADO.read_text()).values())


def test_reservados_vencidos_e_aplicados_voltam_para_a_fila(casa):
    agora = time.time()
    estado = {"integra_t/001.pdf": {"estado": "reservado", "ts": agora},
              "integra_t/002.pdf": {"estado": "reservado", "ts": agora - 30 * 3600},       # reserva morta
              "integra_t/003.pdf": {"estado": "entregue", "ts": agora},                    # ainda não aplicado
              "integra_t/004.pdf": {"estado": "entregue", "ts": agora}}                    # aplicado
    (casa / "ledger.jsonl").write_text(json.dumps({"arq": str(R._arq_reserva("integra_t/004.pdf")), "tag": "t", "i": 4,
                                                   "motor": "reserva"}) + "\n")
    assert R.reservados_pela_reserva(estado, agora) == {"integra_t/001.pdf", "integra_t/003.pdf"}


def test_fila_da_gpu_exclui_reservado_e_poe_reserva_aplicada_no_fim(tmp_path, monkeypatch):
    import tools.sei_ocr_gpu_fila as F
    arq = tmp_path / "sei_arquivo" / TAG
    arq.mkdir(parents=True)
    docs = [{"i": 0, "tipo": "nota_fiscal", "chars": 0},
            {"i": 1, "tipo": "edital", "chars": 500, "ocr": True},                        # Tesseract
            {"i": 2, "tipo": "nota_fiscal", "chars": 500, "ocr": True, "ocr_motor": R.MOTOR},  # reserva aplicada
            {"i": 3, "tipo": "nota_fiscal", "chars": 0},                                   # reservado pela reserva
            {"i": 4, "tipo": "nota_fiscal", "chars": 500, "ocr": True, "ocr_motor": "surya-ocr-2.5"}]
    (arq / "manifest.json").write_text(json.dumps({"docs": docs}))
    monkeypatch.setattr(F, "ARQUIVO", tmp_path / "sei_arquivo")
    frio = {f"integra_{TAG}/{i:03d}.pdf" for i in range(5)}
    fila = F.montar(frio, set(), set(), {f"integra_{TAG}/003.pdf"})
    assert fila == [f"integra_{TAG}/000.pdf", f"integra_{TAG}/001.pdf", f"integra_{TAG}/002.pdf"]


# ───────────────────────────── trava de carga ─────────────────────────────

def test_carga_cede_com_load_ou_memoria_altos_e_desconta_a_propria_reserva():
    assert R.pode_rodar(1.0, 6.0, 2)[0] is True
    assert R.pode_rodar(3.5, 6.0, 2)[0] is False                    # captura SEI + outros: cede
    assert R.pode_rodar(1.0, 1.5, 2)[0] is False                    # memória: cede
    assert R.pode_rodar(4.5, 6.0, 2, proprio=2)[0] is True          # 2 da própria reserva não contam
    assert R.pode_rodar(5.5, 6.0, 2, proprio=2)[0] is False


def test_pausa_na_vm1_para_a_reserva(casa, monkeypatch):
    R.PAUSA.write_text("dono")
    monkeypatch.setattr(R, "pulso_gpu", lambda: pytest.fail("não deve nem medir"))
    assert R.reservar(5, "vm2") == {"itens": [], "motivo": "pausado"}


def test_paralelo_do_itcampo_reserva_com_gpu_ativa_so_com_retirada_imediata(casa, monkeypatch):
    """Nó de CPU do it-campo ao lado do Surya: com a GPU ATIVA reserva do fim (e tira da fila); sem ssh, nada."""
    fila = [f"integra_t/{i:04d}.pdf" for i in range(R.MARGEM + 50)]
    chamadas = []
    monkeypatch.setattr(R, "_tirar_da_fila_gpu", lambda rels, md5: chamadas.append(rels) or "OK")
    monkeypatch.setattr(R, "pulso_gpu", lambda: _pulso(False, fila))
    itens = R.reservar(4, "itcampo-1", paralelo=True)["itens"]
    assert itens == fila[-4:][::-1] and chamadas == [itens]
    # outro processo do mesmo nó físico (outro nome): nunca recebe os mesmos itens
    itens2 = R.reservar(4, "itcampo-2", paralelo=True)["itens"]
    assert len(itens2) == 4 and not set(itens2) & set(itens)
    monkeypatch.setattr(R, "pulso_gpu", lambda: _pulso(False, None, ssh=False))
    assert R.reservar(4, "itcampo-3", paralelo=True)["itens"] == []
