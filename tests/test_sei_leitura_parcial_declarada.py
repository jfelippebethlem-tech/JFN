# -*- coding: utf-8 -*-
"""Corte "os N primeiros" não sustenta ausência (20/11/2026).

`sei_agentes_sweep` lia só 60 documentos e os 3 primeiros relacionados — a lacuna do art. 117 saía de leitura cortada.
A busca de credor gravava a lista colhida até o teto de páginas como resultado final, e o resolvedor aceitava
"candidato único" dela. Agora: lê-se o processo inteiro, e o que for parcial é DECLARADO.
"""
from __future__ import annotations

import json
import sqlite3
import sys

from tools import resolver_duplicidade_nf as R


def test_candidato_unico_de_busca_parcial_nao_vira_processo():
    m = {("35208086000127", "133100", 2022): {"parcial": True, "candidatos": ["SEI-330020/000100/2022"]}}
    obs = [{"numero_ob": "a", "competencia": "01/07/2022", "processo": None, "valor": 100.0}]
    R.completar_pela_busca(obs, "35208086000127", "133100", m)
    assert not obs[0]["processo"], "único de lista cortada não é único"
    assert "parcial" in obs[0]["processo_fonte_nota"]


def test_mapa_busca_marca_o_estado_parcial():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE sei_busca_credor (cnpj TEXT, ug TEXT, ano INTEGER, estado TEXT, n_total INTEGER, "
              "candidatos_json TEXT, buscado_em TEXT)")
    c.execute("INSERT INTO sei_busca_credor VALUES ('1','2',2022,'com_resultado_parcial',140,'[\"SEI-1\"]','x')")
    c.execute("INSERT INTO sei_busca_credor VALUES ('1','2',2023,'com_resultado',3,'[\"SEI-2\"]','2026-11-21T00:00:00')")
    c.execute("INSERT INTO sei_busca_credor VALUES ('1','2',2021,'com_resultado',3,'[\"SEI-3\"]','2026-11-13T06:11:26')")
    m = R.mapa_busca(c)
    assert m[("1", "2", 2022)] == {"parcial": True, "candidatos": ["SEI-1"]}
    assert m[("1", "2", 2023)] == ["SEI-2"]
    assert m[("1", "2", 2021)]["parcial"], "busca de antes do fim_paginacao não sabe se a lista era inteira"


def _acervo(tmp_path, n_docs, designacao_em):
    pasta = tmp_path / "arq" / "080001_000001_2024"
    (pasta / "texto").mkdir(parents=True)
    docs = []
    for i in range(n_docs):
        corpo = "Despacho de encaminhamento. Liquidação da nota fiscal."
        if i == designacao_em:
            corpo = ("PORTARIA Nº 12. Designar o servidor JOAO DA SILVA TESTE, ID Funcional nº 1234567-8, "
                     "como Fiscal do Contrato.")
        rel = f"texto/{i:03d}_d.txt"
        (pasta / rel).write_text(f"[Doc {i}] (fase: x · tipo: y)\n\n{corpo}", encoding="utf-8")
        docs.append({"i": i, "titulo": f"Doc {i}", "texto": rel})
    (pasta / "manifest.json").write_text(json.dumps({"docs": docs, "total_arvore": n_docs}))
    return pasta


def test_agentes_le_o_processo_inteiro_e_nao_afirma_lacuna_cortada(tmp_path, monkeypatch, capsys):
    import tools.sei_agentes_sweep as S
    pasta = _acervo(tmp_path, 80, designacao_em=70)       # o ato de designação depois do 60º documento
    assert any("PORTARIA" in t for t in S._textos(pasta).values()), "o documento 70 ficou de fora da leitura"
    monkeypatch.setattr(S, "ACERVO", pasta.parent)
    monkeypatch.setattr(S, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(sys, "argv", ["x", "--so-conta"])
    assert S.main() == 0
    assert "LACUNA art. 117 (execução paga sem fiscal designado): 0" in capsys.readouterr().out


def test_lacuna_sobre_captura_incompleta_sai_declarada_parcial(tmp_path, monkeypatch):
    import tools.sei_agentes_sweep as S
    pasta = _acervo(tmp_path, 3, designacao_em=-1)
    m = json.loads((pasta / "manifest.json").read_text())
    m["total_arvore"] = 10                                  # 7 documentos da árvore não vieram
    (pasta / "manifest.json").write_text(json.dumps(m))
    db = tmp_path / "c.db"
    monkeypatch.setattr(S, "ACERVO", pasta.parent)
    monkeypatch.setattr(S, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(S, "DB", str(db))
    monkeypatch.setattr(sys, "argv", ["x"])
    assert S.main() == 0
    tipos = {r[0] for r in sqlite3.connect(db).execute("SELECT tipo FROM agente_lacuna")}
    assert "art117_sem_fiscal_leitura_parcial" in tipos and "art117_sem_fiscal" not in tipos
