

def test_restrito_confirmado_e_recente_nao_e_semeado(tmp_path):
    """26/11/2026: na religação 14 de ~30 árvores semeadas eram RESTRITAS (navegador gasto em acesso negado). A regra do
    sei_sweep (RESTRITO confirmado e visto há < 90 dias não volta à fila; a marca expira) vale no semeador."""
    import json
    from datetime import datetime, timedelta
    from tools import e2_semear as E
    agora = datetime(2026, 11, 26, 2, 0)
    reg = {"1": {"numero": "070028/000089/2021", "status": "RESTRITO", "ultima": "2026-11-01 10:00"},
           "2": {"numero": "070028/000090/2021", "status": "RESTRITO?", "ultima": "2026-11-01 10:00"},
           "3": {"numero": "070028/000091/2021", "status": "RESTRITO", "ultima": (agora - timedelta(days=91)).isoformat()}}
    (tmp_path / "sei_restritos.json").write_text(json.dumps(reg), encoding="utf-8")
    out = E.restritos_confirmados(tmp_path, agora)
    assert out == {__import__("compliance_agent.dominio.processo_id", fromlist=["x"]).chave_processo("070028/000089/2021")}
    assert E.restritos_confirmados(tmp_path / "nada", agora) == set()
