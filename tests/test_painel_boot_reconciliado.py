"""O7.6 — boot check reconciliado com o inventário das abas (plano mestre v2 §8 "Estrutura").

O `painel_boot_check` agora confere o catálogo que a página monta (`TABS`, `TABS_ARQUIVADAS`) contra o inventário do
fonte (`tools/painel_abas`). Aqui, sem navegador: a reconciliação acusa cada divergência, a lista padrão que o check
percorre está no menu, e a marca de arquivamento (`arq:'<motivo>'`) é lida dos dois lados — o filtro no `entrada.js`
e o leitor do `painel_abas`. Auditoria: ~/vault/refatoracao/o76-auditoria-abas.md.
"""
import re
from pathlib import Path

from tools import painel_abas
from tools.painel_boot_check import NOVAS, reconciliar

REPO = Path(__file__).resolve().parents[1]
ENTRADA = (REPO / "static" / "js" / "src" / "entrada.js").read_text(encoding="utf-8")

# Arquivadas por decisão da auditoria O7.6 (25/11/2026): nenhuma — 0 MORTA, e o único POR_ORGAO (e_couto) não tem
# cobertura integral pela lente couto. Arquivar/desarquivar tem de mudar ESTE conjunto de propósito.
ARQUIVADAS = {}


def test_inventario_do_fonte_reconcilia_consigo():
    assert painel_abas.arquivadas() == ARQUIVADAS
    vivo = painel_abas.abas()
    assert reconciliar(vivo, list(ARQUIVADAS), NOVAS) == []


def test_lista_padrao_do_boot_check_esta_no_menu():
    assert set(NOVAS) <= set(painel_abas.abas()), set(NOVAS) - set(painel_abas.abas())


def test_reconciliar_acusa_cada_divergencia():
    esperado = painel_abas.abas()
    assert any("fora do menu montado" in p for p in reconciliar(esperado[1:], [], []))       # bundle defasado
    assert any("fora do inventário" in p for p in reconciliar(esperado + ["x_fantasma"], [], []))
    assert any("repetido" in p for p in reconciliar(esperado + esperado[:1], [], []))
    assert any("arquivadas na página" in p for p in reconciliar(esperado, ["e_couto"], []))
    assert any("percorrer" in p for p in reconciliar(esperado, [], ["x_fantasma"]))
    assert any("não expôs" in p for p in reconciliar(None, None, []))


def test_marca_de_arquivamento_e_lida_pelos_dois_lados():
    # JS: a entrada marcada sai do TABS (menu, boot, hash) e fica em TABS_ARQUIVADAS, exposto ao boot check
    assert "TABS[e]=TABS[e].filter(t=>!t.arq)" in ENTRADA
    assert "window.TABS_ARQUIVADAS=TABS_ARQUIVADAS" in ENTRADA
    # Python: o mesmo formato de linha do registro, com e sem a marca
    linha = "    {id:'g_x',     ic:'🧪',tl:'X',render:renderX, arq:'O7.6: rota morta'},"
    assert painel_abas._ARQ.findall(linha) == [("g_x", "O7.6: rota morta")]
    assert painel_abas._ARQ.findall(linha.replace(", arq:'O7.6: rota morta'", "")) == []


def test_aba_arquivada_nao_tem_atalho_vivo():
    """Antes de esconder, nenhuma outra aba/atalho pode apontar para ela (`ir('<id>')`, `#<id>`, `data-aba`)."""
    src = "\n".join(p.read_text(encoding="utf-8") for p in (REPO / "static" / "js" / "src").rglob("*.js"))
    for aid in ARQUIVADAS:
        assert not re.search(rf"ir\('{aid}'\)|#{aid}\b|ir\(\"{aid}\"\)", src), f"{aid} arquivada ainda tem atalho"
