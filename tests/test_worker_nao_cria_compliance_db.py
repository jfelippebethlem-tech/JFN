"""26/11/2026: na VM-2 nasceu um compliance.db FANTASMA (18 tabelas, 0 linhas) — o get_engine do caminho padrão cria
o arquivo quando falta, e num worker isso vira uma base «existente» e vazia: quem ler recebe zero calado
(INDISPONÍVEL ≠ 0). O compliance.db mora na VM-1; no worker (JFN_NO ≠ vm1) o caminho padrão AUSENTE é erro explícito.
Caminho explícito (ou JFN_DB de teste) segue livre."""
import pytest

from compliance_agent.database import models as M


def test_worker_sem_o_banco_padrao_falha_alto(tmp_path, monkeypatch):
    monkeypatch.delenv("JFN_DB", raising=False)
    monkeypatch.setattr(M, "DB_PATH", tmp_path / "data" / "compliance.db")
    monkeypatch.setenv("JFN_NO", "vm2")
    with pytest.raises(FileNotFoundError, match="só existe na VM-1"):
        M.get_engine()
    assert not (tmp_path / "data" / "compliance.db").exists()


def test_vm1_e_caminho_explicito_seguem_livres(tmp_path, monkeypatch):
    monkeypatch.delenv("JFN_DB", raising=False)
    monkeypatch.setattr(M, "DB_PATH", tmp_path / "data" / "compliance.db")
    monkeypatch.setenv("JFN_NO", "vm1")
    assert M.get_engine() is not None
    monkeypatch.setenv("JFN_NO", "vm2")
    assert M.get_engine(tmp_path / "outro.db") is not None                 # explícito: livre
