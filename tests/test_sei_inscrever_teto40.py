# -*- coding: utf-8 -*-
"""Arquivos cortados no teto de 40 do cache voltam à fila de captura, priorizados pelo PAGO no SIAFE (OB paga)."""
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _arq(base: Path, tag: str, n: int, na_arvore: int | None) -> None:
    (base / tag).mkdir(parents=True)
    m = {"processo": tag.replace("_", "/"), "docs": [{"i": str(i), "chars": "100"} for i in range(n)],
         "aviso": "arquivo montado a partir do CACHE do sweep: contém o TEXTO"}
    if na_arvore:
        m["docs_na_arvore"] = na_arvore
    (base / tag / "manifest.json").write_text(json.dumps(m), encoding="utf-8")


def _db():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE sei_fila_captura (numero_sei TEXT PRIMARY KEY, sei_norm TEXT, motivo TEXT, "
                "total_pago REAL, n_docs INTEGER, visto_em TEXT)")
    con.execute("CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, ug_emitente TEXT, data_emissao TEXT, valor REAL, "
                "nl TEXT, nome_credor TEXT, credor TEXT, tipo_ob TEXT, finalidade TEXT, status TEXT, status_envio TEXT, "
                "processo TEXT)")
    obs = [("2024OB1", "1", "01/01/2024", 1000.0, "", "", "", "", "", "Contabilizado", "", "SEI-100000/000001/2024"),
           ("2024OB2", "1", "01/01/2024", 500.0, "", "", "", "", "", "Anulado", "", "SEI-100000/000001/2024"),
           ("2024OB3", "1", "01/01/2024", 70.0, "", "", "", "", "", "Contabilizado", "", "100000/000003/2024")]
    con.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", obs)
    con.execute("INSERT INTO sei_fila_captura VALUES ('SEI-100000/000003/2024','','laudo de execução …',0,0,'x')")
    return con


def test_so_truncado_entra_com_o_pago_do_siafe_e_inscrito_nao_e_tocado(tmp_path):
    from tools import sei_inscrever_teto40 as T
    _arq(tmp_path, "100000_000001_2024", 40, 120)     # truncado (40 de 120)
    _arq(tmp_path, "100000_000002_2024", 40, 40)      # árvore de 40: completo
    _arq(tmp_path, "100000_000003_2024", 40, 90)      # truncado, mas já inscrito por outra fila
    _arq(tmp_path, "100000_000004_2024", 40, None)    # legado: 40 exatos sem o tamanho da árvore
    itens = T.truncados(tmp_path)
    assert sorted(e["processo"] for e in itens) == ["100000/000001/2024", "100000/000003/2024", "100000/000004/2024"]
    con = _db()
    pago = T.pago_siafe(con, [e["processo"] for e in itens])
    assert pago["100000/000001/2024"] == 1000.0, "OB anulada não soma"
    res = T.inscrever(con, itens, pago, aplicar=True)
    assert res["inscritos_agora"] == 2 and res["ja_inscritos"] == 1
    linhas = dict(con.execute("SELECT numero_sei, total_pago FROM sei_fila_captura").fetchall())
    assert linhas["SEI-100000/000001/2024"] == 1000.0
    motivo = con.execute("SELECT motivo FROM sei_fila_captura WHERE numero_sei='SEI-100000/000003/2024'").fetchone()[0]
    assert motivo.startswith("laudo de execução"), "inscrição existente não é sobrescrita"
    from tools.sei_integra_fila import _MOTIVOS_EM_MASSA
    m1 = con.execute("SELECT motivo FROM sei_fila_captura WHERE numero_sei='SEI-100000/000001/2024'").fetchone()[0]
    assert m1.startswith(_MOTIVOS_EM_MASSA)
