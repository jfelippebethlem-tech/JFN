"""Contrato de DADO entre rota e tela em três abas que mostravam zero/repetição (14/11/2026).

- Hub físico: a rota devolve `grupos`; a tela lia `achados`/`hubs` e mostrava zero com 200 na resposta.
- Escalada: zero detectado com séries INDETERMINADAS não é "sem escalada".
- Perícias: matriz e filiais (mesmo nome, CNPJs distintos) pareciam linha repetida sem o CNPJ.
"""
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
JS = (RAIZ / "static/js/src/abas/index.js").read_text(encoding="utf-8")
ROTA = (RAIZ / "rotas/investigacao.py").read_text(encoding="utf-8")


def _fn(nome: str) -> str:
    i = JS.index(f"export async function {nome}(")
    j = JS.index("\nexport ", i + 10)
    return JS[i:j]


def test_hub_le_a_chave_que_a_rota_envia():
    # positivo: a rota envia `grupos` e a tela lê `grupos`
    rota = ROTA[ROTA.index('@router.get("/api/intel/hub_compartilhado")'):][:3000]
    assert '"grupos": d.get("grupos"' in rota
    assert "d.grupos" in _fn("renderHubFisico")


def test_hub_nao_le_so_chaves_que_a_rota_nunca_envia():
    # negativo: a leitura antiga (só achados/hubs) não pode voltar
    assert not re.search(r"const a=d\.achados\|\|d\.hubs\|\|\[\]", _fn("renderHubFisico"))
    rota = ROTA[ROTA.index('@router.get("/api/intel/hub_compartilhado")'):][:3000]
    assert '"achados"' not in rota and '"hubs"' not in rota


def test_hub_vazio_diz_indisponivel_e_nao_zero():
    assert "INDISPONÍVEL" in _fn("renderHubFisico")


def test_escalada_vazia_mostra_indeterminados():
    f = _fn("renderEscalada")
    assert "d.indeterminados" in f and "INDETERMINADAS" in f
    # negativo: a frase que afirmava ausência sem citar o que não foi comparado
    assert "Sem escalada detectada na janela atual" not in f


def test_pericias_mostra_cnpj_do_estabelecimento():
    assert "_cnpjEstab(x.cnpj)" in _fn("renderPericias")
    # a rota agrupa por CNPJ (estabelecimento): nome igual com CNPJ distinto é legítimo
    rota = ROTA[ROTA.index('@router.get("/api/pericias")'):][:2500]
    assert "GROUP BY cnpj" in rota
