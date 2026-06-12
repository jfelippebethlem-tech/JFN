"""
Lex — passo EXCULPATÓRIO (defesa contra si mesmo) + DESTINATÁRIO recomendado por tipo de achado.

Playbook (manual-deteccao-corrupcao-licitacoes.md): para cada indício, escrever a explicação inocente
mais plausível e ver se os dados a refutam; achado que NÃO sobrevive → monitoramento, não representação.
Enquadramento: conluio → MP+CADE · débito/cautelar → TCE-RJ/TCU · improbidade/penal → MP · PAR → CGU/CGE.

TARGETED + offline: achados STUBADOS direto (sem DuckDB/SEI/browser/rede). Honesto: indício ≠ acusação.
"""
import os

os.environ.setdefault("JFN_LEX_LER_SEI", "0")
os.environ.setdefault("JFN_LEX_DISCURSIVO", "0")

import compliance_agent.lex as lex  # noqa: E402


def _analise_stub(achados):
    """Monta um dossiê de análise mínimo (como _analise devolveria) a partir de achados stubados."""
    emoji, rotulo, just = lex._grau(achados)
    return {
        "cnpj": "11222333000181", "sei": [], "leituras": [], "achados": achados,
        "tem_leitura_doc": False, "tcerj": {}, "cartel": {}, "cruzado": {}, "investigacao": {},
        "exculpatorio": lex._exculpatorio(achados), "destinatarios": lex._destinatarios(achados),
        "emoji": emoji, "rotulo": rotulo, "just": just,
    }


def _ctx():
    return {"cnpj": "11222333000181", "nome": "EMPRESA TESTE LTDA", "data": "2026-06-12",
            "pagamentos": {"tem_dados": False}}


def test_exculpatorio_rebaixa_achado_fraco_a_monitoramento():
    """Achado FRACO (gravidade baixa, sem sócio em comum) → defesa inocente sobrevive → monitoramento."""
    fraco = {"rf": "R8", "grav": 2, "obs": "Concentração relevante em um órgão."}
    exc = lex._exculpatorio([fraco])
    assert len(exc) == 1
    assert exc[0]["sobrevive"] is True, "achado fraco deveria sobreviver à própria defesa"
    assert exc[0]["encaminhamento"] == "monitoramento"
    assert "mercado regional" in exc[0]["defesa"].lower() or "concentrad" in exc[0]["defesa"].lower()


def test_exculpatorio_achado_forte_nao_sobrevive_a_propria_defesa():
    """Achado FORTE (cartel COM sócio em comum) → dados refutam a defesa → representação."""
    forte = {"rf": "R8", "grav": 4,
             "obs": "Fornecedores que co-ocorrem nos mesmos órgãos E compartilham sócio com o favorecido."}
    exc = lex._exculpatorio([forte])
    assert exc[0]["sobrevive"] is False
    assert exc[0]["encaminhamento"] == "representação"


def test_destinatario_por_familia_de_achado():
    """conluio(R8)→MP+CADE · débito(R4)→TCE/TCU · improbidade(R5)→MP · PAR(DD/*)→CGU/CGE."""
    achados = [
        {"rf": "R8", "grav": 4, "obs": "cartel"},
        {"rf": "R4", "grav": 3, "obs": "sobrepreço"},
        {"rf": "R5", "grav": 2, "obs": "dispensa"},
        {"rf": "DD/H-RECENTE", "grav": 3, "obs": "fachada"},
    ]
    dests = {d["destinatario"] for d in lex._destinatarios(achados)}
    assert any("CADE" in d for d in dests), "conluio deveria rotear a MP + CADE"
    assert any("TCE-RJ" in d for d in dests), "débito deveria rotear a TCE-RJ/TCU"
    assert any(d == "MP-RJ" for d in dests), "improbidade deveria rotear a MP-RJ"
    assert any("CGE-RJ" in d for d in dests), "PAR/fachada deveria rotear a CGU/CGE"


def test_destinatario_vazio_sem_achado():
    assert lex._destinatarios([]) == []


def test_parecer_md_surfa_exculpatorio_e_destinatario():
    """O parecer renderizado deve conter a subseção exculpatória, o destinatário e o rebaixamento."""
    achados = [
        {"rf": "R8", "grav": 2, "obs": "Concentração relevante em um órgão."},  # fraco → monitoramento
        {"rf": "R4", "grav": 3, "obs": "Preço acima da referência."},          # forte → TCE/TCU
    ]
    md = lex.parecer_md(_ctx(), _analise_stub(achados))
    assert "PASSO EXCULPATÓRIO" in md, "subseção exculpatória ausente do parecer"
    assert "Destinatário recomendado" in md, "destinatário recomendado ausente do parecer"
    assert "TCE-RJ" in md and "CADE" in md, "destinatários por família ausentes"
    # Achado fraco rebaixado a monitoramento aparece textualmente.
    assert "monitoramento" in md.lower()
    assert "rebaixado" in md.lower()
