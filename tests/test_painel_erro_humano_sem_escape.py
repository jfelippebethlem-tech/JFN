"""`erroHumano()` devolve HTML já escapado (mensagem + botão "Tentar de novo").

Embrulhá-lo em `esc()` mostrava o markup cru na tela — `<span>a rota … não respondeu</span> <button …>` no
TAC a 390 px (auditoria quadro a quadro, 24/09/2026) — e o botão de tentar de novo sumia. Eram 8 chamadas.
"""
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "static" / "js" / "src"


def test_ninguem_escapa_de_novo_o_erro_humano():
    ofensores = [
        f"{p.relative_to(SRC)}:{i}"
        for p in SRC.rglob("*.js")
        for i, linha in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if "esc(erroHumano(" in linha
    ]
    assert not ofensores, f"erroHumano já devolve HTML seguro; não escapar de novo: {ofensores}"
