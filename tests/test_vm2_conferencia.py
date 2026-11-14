# -*- coding: utf-8 -*-
"""Conferência das entregas da VM-2: só entra no acervo o que passa (md5, documentos × árvore, texto legível,
amostra × leitura da VM-1, juízo do Claude); o resto vai para a quarentena e o log da fila não ganha "ok"."""
from __future__ import annotations

import json

import tools.vm2_conferencia as C
import tools.vm2_lote as L

TEXTO = "Despacho de encaminhamento do processo administrativo para a coordenadoria de contratos. " * 5


def _pasta(base, tag, *, n=3, total=None, texto=TEXTO):
    p = base / tag
    (p / "texto").mkdir(parents=True)
    docs = []
    for i in range(n):
        nome = f"{i:03d}_despacho_{i}.txt"
        (p / "texto" / nome).write_text(texto, encoding="utf-8")
        docs.append({"i": i, "titulo": f"Despacho {i} ({1000 + i})", "texto": f"texto/{nome}", "chars": len(texto)})
    m = {"processo": tag, "docs": docs, "total_arvore": total if total is not None else n, "nao_capturados": 0,
         "captura_vazia": False}
    (p / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    return p


def _isolar(monkeypatch, tmp_path):
    d = tmp_path / "data"
    for nome, val in {"DATA": d, "ENTREGA": d / "vm2_entrega", "QUARENTENA": d / "vm2_quarentena",
                      "SUBST": d / "vm2_entrega" / "_substituidos", "IMPORTADOS": d / "vm2_entrega" / "_importados",
                      "LOG": d / "vm2_conferencia.log", "LOG_FILA": d / "sei_integra_fila.log",
                      "ARQUIVO": d / "sei_arquivo", "CACHE": d / "sei_cache", "AMOSTRA": d / "amostra.json"}.items():
        monkeypatch.setattr(C, nome, val)
    (d / "sei_arquivo").mkdir(parents=True)
    (d / "sei_cache").mkdir(parents=True)
    monkeypatch.setattr(L, "LOTES", d / "vm2_entrega")      # o lote "chega" direto onde a VM-1 o espera
    return d


def test_lote_aprova_o_bom_e_poe_em_quarentena_o_adulterado_e_o_incompleto(monkeypatch, tmp_path):
    d = _isolar(monkeypatch, tmp_path)
    src = tmp_path / "vm2"
    _pasta(src, "100000_000001_2025")
    _pasta(src, "100000_000002_2025")
    _pasta(src, "100000_000003_2025", n=2, total=10)          # árvore com 10, entregou 2
    base = L.montar("integras", {f"arquivo/{t}": src / t for t in
                                 ("100000_000001_2025", "100000_000002_2025", "100000_000003_2025")},
                    {p: {"status": "ok", "juizo": {"legivel": True, "corresponde": True}}
                     for p in ("100000/000001/2025", "100000/000002/2025", "100000/000003/2025")},
                    {"linhas_log": [f"[2026-11-13 17:00:00]   100000/00000{i}/2025: ok" for i in (1, 2, 3)]})
    # adulteração em trânsito
    (base / "arquivo/100000_000002_2025/texto/000_despacho_0.txt").write_text("x", encoding="utf-8")
    r = C.importar(base.name)
    assert r["aprovados"] == ["100000/000001/2025"]
    assert set(r["reprovados"]) == {"100000/000002/2025", "100000/000003/2025"}
    assert (d / "sei_arquivo" / "100000_000001_2025" / "manifest.json").exists()
    assert not (d / "sei_arquivo" / "100000_000002_2025").exists()
    assert (d / "vm2_quarentena" / base.name / "100000_000002_2025.motivo.json").exists()
    log = (d / "sei_integra_fila.log").read_text(encoding="utf-8")
    assert "100000/000001/2025: ok\n" in log
    assert "100000/000002/2025: ok-quarentena" in log and "100000/000003/2025: ok-quarentena" in log
    # sem leitura independente na VM-1 → vai para a fila da amostra independente
    assert json.loads((d / "amostra.json").read_text()) == ["100000/000001/2025"]


def test_juizo_do_claude_reprova_texto_ilegivel(monkeypatch, tmp_path):
    _isolar(monkeypatch, tmp_path)
    p = _pasta(tmp_path / "vm2", "100000_000004_2025")
    ok, motivos, _ = C.conferir_integra(p, "ok", "100000_000004_2025",
                                        {"legivel": False, "corresponde": False, "motivo": "tela de login"})
    assert not ok and any("Claude" in m for m in motivos)


def test_referencia_da_vm1_divergente_reprova(monkeypatch, tmp_path):
    d = _isolar(monkeypatch, tmp_path)
    _pasta(d / "sei_arquivo", "100000_000005_2025", texto="Contrato de locação de veículos blindados " * 10)
    novo = _pasta(tmp_path / "vm2", "100000_000005_2025")
    ok, motivos, met = C.conferir_integra(novo, "ok", "100000_000005_2025", None)
    assert not ok and "diverge" in " ".join(motivos)


def test_legivel():
    assert C.legivel(TEXTO)
    assert not C.legivel("@@@@ #### 1234 5678 9999 %%%% ----" * 3)
    assert not C.legivel("")


def test_lote_sweep_importa_cdp_e_nao_sobrescreve_leitura_boa_com_vazia(monkeypatch, tmp_path):
    d = _isolar(monkeypatch, tmp_path)
    src = tmp_path / "vm2"
    src.mkdir()
    bom = {"numero": "SEI-100000/000007/2025", "documentos": [{"titulo": "Despacho 1"}],
           "conteudo_documentos": [{"doc": "Despacho 1", "conteudo": TEXTO}]}
    vazio = {"numero": "SEI-100000/000008/2025", "documentos": [], "conteudo_documentos": []}
    (src / "cdp_SEI_100000_000007_2025.json").write_text(json.dumps(bom), encoding="utf-8")
    (src / "cdp_SEI_100000_000008_2025.json").write_text(json.dumps(vazio), encoding="utf-8")
    # a VM-1 já tem leitura COM documento do 2º: a vazia da VM-2 não pode apagá-la
    (d / "sei_cache" / "cdp_SEI_100000_000008_2025.json").write_text(json.dumps(
        {"documentos": [{"titulo": "X"}], "conteudo_documentos": []}), encoding="utf-8")
    (d / "sei_cache" / "sei_sweep_progress.json").write_text(json.dumps({"feitos": {}}), encoding="utf-8")
    nomes = ["cdp_SEI_100000_000007_2025.json", "cdp_SEI_100000_000008_2025.json"]
    base = L.montar("sweep", {f"cache/{n}": src / n for n in nomes}, {n: {"juizo": None} for n in nomes},
                    {"progresso": {"SEI-100000/000007/2025": {"n_docs": 1, "em": "2026-11-13T18:00:00"}},
                     "restritos": {}})
    r = C.importar(base.name)
    assert sorted(r["aprovados"]) == nomes
    assert json.loads((d / "sei_cache" / nomes[0]).read_text())["documentos"]
    assert json.loads((d / "sei_cache" / nomes[1]).read_text())["documentos"] == [{"titulo": "X"}]
    prog = json.loads((d / "sei_cache" / "sei_sweep_progress.json").read_text())
    assert prog["feitos"]["SEI-100000/000007/2025"]["n_docs"] == 1


def test_cdp_com_teor_de_40_de_105_nao_e_reprovado(monkeypatch, tmp_path):
    d = _isolar(monkeypatch, tmp_path)
    titulos = [f"Documento {i}" for i in range(105)]
    (d / "sei_cache" / "cdp_SEI_100000_000009_2025.json").write_text(json.dumps(
        {"documentos": [{"titulo": t} for t in titulos],
         "conteudo_documentos": [{"doc": t, "conteudo": TEXTO} for t in titulos]}), encoding="utf-8")
    novo = tmp_path / "cdp_SEI_100000_000009_2025.json"
    novo.write_text(json.dumps({"documentos": [{"titulo": t} for t in titulos],
                                "conteudo_documentos": [{"doc": t, "conteudo": TEXTO} for t in titulos[:40]]}),
                    encoding="utf-8")
    ok, motivos, _ = C.conferir_cdp(novo, None)
    assert ok, motivos


def test_restrito_declarado_pelo_sei_vai_para_o_registro(monkeypatch, tmp_path):
    import tools.vm2_conferencia as C
    import tools.sei_restritos as R
    monkeypatch.setattr(C, "LOG", tmp_path / "conf.log")
    semeados = []
    monkeypatch.setattr(R, "seed", lambda numero, unidade="", motivo="": semeados.append((numero, motivo)))
    linhas = [
        "[2026-11-14 09:17:32]   270032/000052/2023: SEM ÁRVORE (processo não abriu) — RESTRITO: SEI diz "
        "'Unidade atual não possui acesso ao processo restrito SEI-270032/000052/2023' — via='cracked'",
        "[2026-11-14 09:17:32]   270032/000052/2023: sem_arvore",
        "[2026-11-14 09:20:00]   100000/000001/2025: SEM ÁRVORE (processo não abriu) — via='cracked' erro_cracked=None",
    ]
    assert C.registrar_restritos_declarados(linhas, "jorge") == ["270032/000052/2023"]
    assert semeados[0][0] == "270032/000052/2023" and "SEI declarou" in semeados[0][1]
