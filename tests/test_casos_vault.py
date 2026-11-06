"""Aba Casos: leitura dos dossiês do vault (frontmatter heterogêneo, gravidade, cruzamento com o 360)."""
from compliance_agent import casos_vault as cv


def _nota(d, nome, txt):
    (d / f"{nome}.md").write_text(txt, encoding="utf-8")


def test_gravidade_de_qualquer_campo_e_sem_grau_nao_vira_verde(tmp_path, monkeypatch):
    monkeypatch.setattr(cv, "VAULT_CASOS", tmp_path)
    monkeypatch.setattr(cv, "_DB", tmp_path / "nao-existe.db")
    _nota(tmp_path, "a", "---\nstatus: aberto\ngrau: 🔴 alto\n---\n# Caso A\n\nTexto do caso A. SEI-070002/015404/2022\n")
    _nota(tmp_path, "b", "---\nstatus: concluído\nseveridade: 🟡 médio\nresumo: curto\n---\n# Caso B\n")
    _nota(tmp_path, "c", "---\nstatus: aberto\n---\n# Caso C\n\n**Relacionados:** [[x]]\n\nO que importa.\n")
    r = cv.listar()
    assert r["ok"] and r["total"] == 3
    por = {c["slug"]: c for c in r["casos"]}
    assert por["a"]["nivel_rotulo"] == "alto" and por["a"]["sei"] == ["SEI-070002/015404/2022"]
    assert por["b"]["nivel_rotulo"] == "médio" and por["b"]["situacao"] == "concluído" and por["b"]["resumo"] == "curto"
    assert por["c"]["nivel_rotulo"] == "sem grau"             # sem semáforo: nunca "baixo"
    assert por["c"]["resumo"] == "O que importa."             # pula a linha de links
    assert [c["slug"] for c in r["casos"]][0] == "a"          # gravidade alta primeiro


def test_nota_recusa_caminho_fora_da_pasta(tmp_path, monkeypatch):
    monkeypatch.setattr(cv, "VAULT_CASOS", tmp_path)
    assert cv.nota("../../etc/passwd")["ok"] is False
    assert cv.nota("nao-existe")["ok"] is False
    _nota(tmp_path, "ok", "---\nstatus: aberto\n---\n# Título\n\ncorpo")
    r = cv.nota("ok")
    assert r["ok"] and r["markdown"].startswith("# Título") and r["meta"]["status"] == "aberto"
