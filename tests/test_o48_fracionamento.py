# -*- coding: utf-8 -*-
"""O4.8 (plano mestre v2 §4.5) — fracionamento: só o P4, por objeto, emite.

  · motor antigo (`rules/engine.py` regras 4 e OB, `rules/generate_alerts.py` bloco 4) deprecated e SEM emissão;
  · `fracionamento_siafe` deixa de dizer "fracionamento" (é `candidato_p4`) e `siafe_fracionamento` fica congelada;
  · seed da memória reescrito (o antigo vai ao histórico ao reaplicar);
  · frota do §7º fora da soma do ramo no P4;
  · CATRACA: módulo que emite código de "fracionamento" e mede contra o teto de dispensa fora do P4 → falha.
Fixtures sintéticas (sem banco real)."""
from __future__ import annotations

import ast
import io
import re
import sqlite3
import subprocess
import tokenize
from datetime import date, timedelta
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
PRIVADO = "11222333000181"


# ── 1. motor antigo: zero emissão ────────────────────────────────────────────────────────────────────────────────
def _sessao_que_acenderia():
    """Dados que a régua antiga transformava em alerta: 3 OB de 40 mil em processos distintos ao mesmo credor/UG/mês
    e 2 contratos por dispensa do mesmo par órgão × empresa somando acima do teto."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from compliance_agent.database.models import Base, Contrato, Empresa, OrdemBancaria
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    dia = date.today() - timedelta(days=3)
    s.add_all([OrdemBancaria(numero_ob=f"OB{i}", data_emissao=dia, ug_codigo="294200", favorecido_cpf=PRIVADO,
                             favorecido_nome="GESPED GESTAO LTDA", valor=40_000.0, numero_processo=f"SEI-{i}",
                             status="paga") for i in range(3)])
    emp = Empresa(cnpj=PRIVADO, razao_social="GESPED GESTAO LTDA")
    s.add(emp)
    s.flush()
    s.add_all([Contrato(orgao_contrat="SEC X", empresa_id=emp.id, modalidade="dispensa", valor_total=90_000.0)
               for _ in range(2)])
    s.commit()
    return s


def test_motor_antigo_nao_emite_fracionamento():
    from compliance_agent.rules.engine import MotorCompliance
    m = MotorCompliance(_sessao_que_acenderia())
    m._alertas_novos = []
    m._regra_ob_fracionamento()
    m._regra_fracionamento_contrato()
    assert m._alertas_novos == []


def test_engine_e_generate_alerts_nao_tem_codigo_de_fracionamento():
    """Controle estático do mesmo fato: nenhum literal de tipo 'fracionamento…' nos dois motores antigos."""
    for rel in ("compliance_agent/rules/engine.py", "compliance_agent/rules/generate_alerts.py"):
        assert not _codigos(rel), rel


# ── 2. catraca: agregação credor × teto fora do P4 ───────────────────────────────────────────────────────────────
_COD = re.compile(r"^[A-Za-z0-9_]*fracionamento[A-Za-z0-9_]*$", re.I)
_TETO = re.compile(r"\b(limite_dispensa|teto_dispensa|_teto|LIMITE_DISPENSA|LIMITES)\b")
# Só estes emitem sobre o teto por OBJETO (o P4) ou dizem `candidato_p4` (série de pagamento).
P4 = {
    "compliance_agent/aplicacao/detectores/fracionamento_objeto.py": "E10 P4 por objeto (o único que emite)",
    "compliance_agent/detectores/p4_fracionamento.py": "card P4 (objeto/ramo, UG, exercício)",
    "compliance_agent/aplicacao/detectores/candidato_p4_siafe.py": "emite só candidato_p4 (INCERTO)",
    "compliance_agent/fracionamento_siafe.py": "triagem candidato_p4 (régua do E10)",
    "compliance_agent/limites_dispensa.py": "fonte única do teto",
}
# Dívida conhecida (só encolhe): módulos que ainda carregam código de fracionamento ao lado do teto. Pela §17.2 do
# plano, fracionamento por OB fica INDETERMINADO até a coleta de NE/NL; nenhum deles é achado do produto novo.
EXCECOES = {
    "compliance_agent/anomalias.py": "R_FRACIONAMENTO_MES/SAMEDAY: sinal 0,3 em ob_redflag_siafe, não achado; sai na O5",
    "compliance_agent/analysis/anomaly_detector.py": "threshold_fracionamento: OB individual rente ao teto, sem soma",
    "compliance_agent/aplicacao/estagios/elegibilidade.py": "nomes de módulo/tabela lidos pela E9 (não emite)",
    "compliance_agent/cruzamentos_intel.py": "subcomando 'fracionamento' do cruzador (sinal de triagem); sai na O5",
    "compliance_agent/hermes_goal.py": "lê o tipo de alerta para o resumo do Hermes (não emite)",
    "compliance_agent/nucleo/indicadores.py": "IND-FRAC-01 (indicador por objeto do núcleo); conferir na O5",
    "compliance_agent/nucleo/parametros.py": "nomes de parâmetro (janela, mínimo de contratos)",
    "compliance_agent/pcrj/pericia_gastos.py": "d7 da Prefeitura (esfera municipal, perícia); sai na O5",
    "compliance_agent/reporting/dossie_couto.py": "rótulo da seção D07 no dossiê (já ⚪, decisão do dono 24/11)",
}


def _codigos(rel: str, src: str | None = None) -> list[str]:
    src = (RAIZ / rel).read_text(encoding="utf-8") if src is None else src
    out = []
    try:
        for t in tokenize.generate_tokens(io.StringIO(src).readline):
            if t.type != tokenize.STRING:
                continue
            try:
                v = ast.literal_eval(t.string)
            except (ValueError, SyntaxError):
                continue
            if isinstance(v, str) and _COD.match(v):
                out.append(v)
    except tokenize.TokenError:
        return out
    return out


def _agregadores(src_por_arquivo: dict[str, str]) -> set[str]:
    return {rel for rel, src in src_por_arquivo.items() if _TETO.search(src) and _codigos(rel, src)}


def _versionados() -> dict[str, str]:
    try:
        arqs = subprocess.run(["git", "ls-files", "*.py"], cwd=RAIZ, capture_output=True, text=True,
                              check=True).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        arqs = [str(p.relative_to(RAIZ)) for p in RAIZ.rglob("*.py")]
    return {a: (RAIZ / a).read_text(encoding="utf-8", errors="replace") for a in arqs
            if not a.startswith(("tests/", "docs/", "_SANDBOX/", "_PROTEGIDO/", "graphify-out/")) and (RAIZ / a).exists()}


def test_catraca_agregacao_credor_x_teto_fora_do_p4():
    fora = sorted(_agregadores(_versionados()) - set(P4) - set(EXCECOES))
    assert not fora, ("código de 'fracionamento' medido contra o teto de dispensa fora do P4 (O4.8: só o P4, por "
                      f"objeto, emite; a série por credor é `candidato_p4`): {fora}")


def test_catraca_excecoes_so_encolhem():
    vivos = _agregadores(_versionados())
    mortas = sorted(set(EXCECOES) - vivos)
    assert not mortas, f"exceção curada — remova da lista: {mortas}"


def test_catraca_enxerga_agregador_novo():
    """Controle positivo: um agregador credor × teto sintético é pego; o mesmo sem código de fracionamento, não."""
    novo = ('from compliance_agent.limites_dispensa import limite_dispensa\n'
            'def r(obs):\n    if sum(obs) > limite_dispensa(2025):\n        return {"tipo": "fracionamento"}\n')
    assert _agregadores({"x/novo.py": novo}) == {"x/novo.py"}
    assert _agregadores({"x/novo.py": novo.replace('"fracionamento"', '"candidato_p4"')}) == set()


# ── 3. fracionamento_siafe: candidato_p4, sem a palavra ──────────────────────────────────────────────────────────
def _siafe(tmp_path, n=3, mesmo_processo=False):
    db = tmp_path / "s.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE ob_orcamentaria_siafe (exercicio INT, ug_emitente TEXT, credor TEXT, nome_credor TEXT, "
                "data_emissao TEXT, valor REAL, processo TEXT, numero_ob TEXT, status TEXT)")
    con.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (2025,'294200',?,?,?,?,?,?,'Pago')",
                    [(PRIVADO, "ACME SERVICOS LTDA", f"2025-03-{i + 1:02d}", 40_000.0,
                      "P1" if mesmo_processo else f"P{i}", f"2025OB{i}") for i in range(n)])
    con.commit()
    return con


def test_triagem_siafe_diz_candidato_p4_e_nunca_fracionamento(tmp_path):
    from compliance_agent import fracionamento_siafe as FS
    r = FS.triagem(_siafe(tmp_path), exercicio=2025)
    assert len(r["candidatos"]) == 1 and r["natureza"] == "candidato_p4"
    c = r["candidatos"][0]
    assert c["natureza"] == "candidato_p4" and c["grau"] == "a_verificar"
    for campo in ("resumo", "acao", "ressalva", "fundamento", "fonte"):
        assert "fracionamento" not in c[campo].lower(), campo


def test_triagem_siafe_negativo_parcelas_do_mesmo_processo(tmp_path):
    from compliance_agent import fracionamento_siafe as FS
    assert FS.triagem(_siafe(tmp_path, mesmo_processo=True), exercicio=2025)["candidatos"] == []


def test_siafe_fracionamento_congelada(tmp_path, monkeypatch):
    import sys

    sys.path.insert(0, str(RAIZ / "tools"))
    import fracionamento_siafe_sweep as SW
    con = _siafe(tmp_path)
    with pytest.raises(SW.TabelaCongelada):
        SW.persistir(con, [{"exercicio": 2025}], exercicio=2025)
    assert not con.execute("SELECT 1 FROM sqlite_master WHERE name='siafe_fracionamento'").fetchone()
    monkeypatch.setattr(sys, "argv", ["x", "--exercicio", "2025", "--gravar"])
    assert SW.main() == 2
    assert "fracionamento_siafe_sweep.py" not in (RAIZ / "tools/sweep_fiscalizacao_247.sh").read_text()


# ── 4. seed da memória reescrito e reaplicado com histórico ──────────────────────────────────────────────────────
def test_seed_da_memoria_sem_agregacao_por_fornecedor():
    from compliance_agent.llm.memoria import CONTEXTO_INICIAL
    txt = dict(CONTEXTO_INICIAL)
    assert "ao mesmo fornecedor somando" not in txt["limite_dispensa_compras"]
    assert "mesmo ramo" in txt["limite_dispensa_compras"] and "unidade gestora" in txt["limite_dispensa_obras"]


def test_seed_reaplicado_versiona_o_antigo():
    import json

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from compliance_agent.database.models import Base, MemoriaAprendizado
    from compliance_agent.llm import memoria as M
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    antigo = ("Lei 14.133/21 art. 75 II: ... Múltiplas compras ao mesmo fornecedor somando acima disso = "
              "fracionamento.")
    s.add(MemoriaAprendizado(categoria="contexto_admin", chave="limite_dispensa_compras", valor=antigo,
                             confianca=0.9, fonte="humano", origem="humano", estado="nao_confirmado"))
    s.commit()
    M.garantir_contexto_inicial(session=s)
    it = s.query(MemoriaAprendizado).filter_by(categoria="contexto_admin", chave="limite_dispensa_compras").one()
    assert it.valor == dict(M.CONTEXTO_INICIAL)["limite_dispensa_compras"]
    assert json.loads(it.historico)[-1]["valor"] == antigo
    assert M.confianca_efetiva(it) <= M.CONF_MAX_NAO_CONFIRMADO      # sem auto-reforço (O6.7)
    M.garantir_contexto_inicial(session=s)                            # idempotente: não cresce o histórico
    assert len(json.loads(it.historico)) == 1


# ── 5. P4: frota do §7º fora da soma do ramo ─────────────────────────────────────────────────────────────────────
def _linha(proc, valor, objeto, ano=2025):
    return dict(processo=proc, unidade="SEC X - SECRETARIA", ano_processo=ano, valor=valor, objeto=objeto,
                afastamento="Dispensa", enquadramento="Lei 14.133/2021, Art. 75, I", fornecedor=f"OFICINA {proc} LTDA")


def _p4(linhas):
    from compliance_agent.aplicacao.detectores import fracionamento_objeto as F
    it = F._itens(linhas)
    for c in it:
        c["e9"] = "E"
    return F, it


def test_frota_ate_o_par7_fica_fora_da_soma():
    from compliance_agent.limites_dispensa import limite_par7
    v = limite_par7(2025)
    F, it = _p4([_linha(f"SEI-{i}", v, "MANUTENÇÃO PREVENTIVA E CORRETIVA DE VEÍCULOS DA FROTA") for i in range(14)])
    assert all(c["frota_par7"] and not c["dispensa"] for c in it)
    assert F.detectar(it) == []
    r = F.resumo(it, [])
    assert r["frota_par7_fora_da_soma"] == 14 and r["frota_par7_fora_da_soma_valor"] == round(14 * v, 2)


def test_frota_acima_do_par7_continua_na_soma():
    from compliance_agent.limites_dispensa import limite_dispensa, limite_par7
    v = limite_par7(2025) + 1000
    n = int(limite_dispensa(2025, "obras") // v) + 2
    F, it = _p4([_linha(f"SEI-{i}", v, "MANUTENÇÃO PREVENTIVA E CORRETIVA DE VEÍCULOS DA FROTA") for i in range(n)])
    assert not any(c["frota_par7"] for c in it) and all(c["dispensa"] for c in it)
    assert F.detectar(it)


def test_frota_regex_nao_pega_objeto_alheio():
    from compliance_agent.aplicacao.detectores import fracionamento_objeto as F
    assert not F.frota_par7("AQUISIÇÃO DE MATERIAL DE LIMPEZA", 1000.0, 2025)
    assert not F.frota_par7("MANUTENÇÃO DE VEÍCULOS", 1000.0, 2019)     # sem §7º antes da 14.133
