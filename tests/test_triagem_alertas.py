# -*- coding: utf-8 -*-
"""Triagem dos alertas da Ronda — banco sintético em tmp; Claude, cascata, API e Opus são dublês."""
import json
import sqlite3
from types import SimpleNamespace as NS

import pytest

from compliance_agent import triagem_alertas as T
from compliance_agent.llm import comotor as CM
from compliance_agent.llm.claude_motor import Pensamento


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setenv("JFN_CRUZAMENTO_DB", str(tmp_path / "cruz.db"))
    monkeypatch.setenv("JFN_CLAUDE_DADOS", str(tmp_path / "dados"))
    c = sqlite3.connect(tmp_path / "c.db")
    c.execute("CREATE TABLE alertas(id INTEGER PRIMARY KEY, tipo TEXT, severidade TEXT, titulo TEXT, "
              "descricao TEXT, evidencias TEXT, status TEXT)")
    linhas = [
        (1, "acumulacao", "alta", "Emprego múltiplo", "d", json.dumps({"cpf": "12345678901", "total_bruto": 30000.0}), "novo"),
        (2, "direcionamento", "baixa", "OB empresa nova", "empresa aberta 106 dias antes", json.dumps({"valor": 5_000_000.0}), "novo"),
        (3, "pcrj_d7_fracionamento", "media", "Fracionamento", "d", json.dumps({"soma": 200_000.0}), "novo"),
        (4, "x", "baixa", "json torto", "d", "{nao é json", "novo"),
        (5, "direcionamento", "alta", "já confirmado", "d", json.dumps({"valor": 9e9}), "confirmado"),
    ]
    c.executemany("INSERT INTO alertas VALUES(?,?,?,?,?,?,?)", linhas)
    c.commit()
    yield c
    c.close()


def _gerar(resp_claude, resp_casc):
    prompts = []

    def pensar(t, p, **kw):
        prompts.append(p)
        return Pensamento(texto=resp_claude, modelo="claude-sonnet-5-5", segundos=1, tarefa=t) if resp_claude else None
    g = CM.juizo("triagem_alertas", pensar=pensar, cascata=lambda *a, **k: resp_casc, sorteio=lambda: 1.0)
    g.prompts = prompts
    return g


def _r(prio, cit="empresa aberta 106 dias antes", nota=5):
    return json.dumps({"prioridade": prio, "nota": nota, "citacao": cit, "justificativa": "j"})


def _estado(con, aid):
    return con.execute("SELECT prioridade, estado, opus_pendente FROM alertas_triagem WHERE alerta_id=?", (aid,)).fetchone()


def test_prioriza_por_valor_ignora_nao_novos_e_json_torto(con):
    assert [a["id"] for a in T.selecionar(con, 10)] == [2, 3, 1, 4]


def test_sincrono_concordante_sem_achado_fica_verificado(con):
    T.triar_lote(con, 1, gerar=_gerar(_r("provavel_falso_positivo"), _r("provavel_falso_positivo")))
    assert _estado(con, 2) == ("provavel_falso_positivo", "VERIFICADO", 0)
    assert con.execute("SELECT COUNT(*) FROM alertas WHERE status='novo'").fetchone()[0] == 4


def test_achado_concordante_ainda_espera_o_opus(con):
    T.triar_lote(con, 1, gerar=_gerar(_r("aprofundar"), _r("aprofundar")))
    assert _estado(con, 2) == ("aprofundar", "PENDENTE", 1)


def test_divergencia_fica_pendente_nunca_resolvida(con):
    T.triar_lote(con, 1, gerar=_gerar(_r("provavel_falso_positivo"), _r("aprofundar")))
    assert _estado(con, 2)[1] == "PENDENTE"


def test_citacao_inventada_descarta_e_escala(con):
    T.triar_lote(con, 1, gerar=_gerar(_r("provavel_falso_positivo", cit="trecho que não existe no alerta"),
                                       _r("provavel_falso_positivo", cit="trecho que não existe no alerta")))
    assert _estado(con, 2) == ("provavel_falso_positivo", "PENDENTE", 1)


def test_cpf_vai_mascarado_no_prompt(con):
    g = _gerar(_r("monitorar"), "{}")
    T.triar_lote(con, 3, gerar=g)
    assert not any("12345678901" in p for p in g.prompts)


def test_resposta_fora_da_rubrica_nao_vira_prioridade():
    assert T.interpretar('{"prioridade":"culpado","nota":10}')["prioridade"] is None
    assert T.interpretar('{"prioridade":"monitorar","nota":42}')["nota"] is None


def test_motor_fora_nao_aborta_o_lote(con):
    def explode(*a, **k):
        raise RuntimeError("tudo fora")
    assert T.triar_lote(con, 3, gerar=explode) == []


# ── Batch API (Haiku) + 2ª leitura ──────────────────────────────────────────────────────────────────
class LoteDuble:
    def __init__(self, respostas):
        self.respostas, self.enviados = respostas, []
        lote = self

        class Batches:
            def create(self, requests):
                lote.enviados = requests
                return NS(id="msgbatch_x")

            def retrieve(self, i):
                return NS(processing_status="ended")

            def results(self, i):
                for cid, txt in lote.respostas.items():
                    msg = NS(content=[NS(type="text", text=txt)], stop_reason="end_turn",
                             usage={"input_tokens": 1000, "output_tokens": 300, "cache_read_input_tokens": 400})
                    yield NS(custom_id=cid, result=NS(type="succeeded", message=msg))
        self.messages = NS(batches=Batches())


def test_lote_api_grava_com_dupla_leitura_e_contabiliza(con):
    itens = {"itens": [{"id": 2, "prioridade": "provavel_falso_positivo", "nota": 2,
                        "citacao": "empresa aberta 106 dias antes", "justificativa": "j"},
                       {"id": 3, "prioridade": "monitorar", "nota": 5, "citacao": "Fracionamento", "justificativa": "j"}]}
    cli = LoteDuble({"g0": json.dumps(itens)})
    assert T.enviar_lote_api(con, 2, cliente=cli) == "msgbatch_x"
    req = cli.enviados[0]["params"]
    assert req["model"] == "claude-haiku-5-5" and req["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert req["output_config"]["format"]["type"] == "json_schema" and req["output_config"]["effort"] == "low"
    assert T.selecionar(con, 10)[0]["id"] == 1          # os do lote pendente não são reenviados
    segunda = lambda p, s: json.dumps({"itens": [{"id": 2, "prioridade": "provavel_falso_positivo"},
                                                 {"id": 3, "prioridade": "aprofundar"}]})
    assert T.colher_lotes_api(con, cliente=cli, gerar_b=segunda) == 2
    assert _estado(con, 2) == ("provavel_falso_positivo", "VERIFICADO", 0)
    assert _estado(con, 3) == ("monitorar", "PENDENTE", 1)
    from compliance_agent.llm import claude_api
    p = claude_api.painel()
    assert p["baldes"]["triagem_alertas"]["itens"] == 2 and p["baldes"]["triagem_alertas"]["restantes"] == 2
    assert p["gasto_usd"] > 0 and p["cache"]["claude-haiku-5-5"]["cache_lido"] == 400


def test_colheita_interrompida_retoma_sem_perder_grupo_nem_pagar_duas_vezes(con):
    # 14/11/2026: lote de 607 grupos; a colheita (2ª leitura pela cascata em cada grupo) leva horas e o cron
    # a mata em 900 s. O custo era liquidado e o lote apagado do registro ANTES dos grupos: a 2ª rodada não
    # achava mais o lote e os grupos restantes ficavam órfãos para sempre.
    r2 = {"itens": [{"id": 2, "prioridade": "provavel_falso_positivo", "nota": 2,
                     "citacao": "empresa aberta 106 dias antes", "justificativa": "j"}]}
    r3 = {"itens": [{"id": 3, "prioridade": "monitorar", "nota": 5, "citacao": "Fracionamento", "justificativa": "j"}]}
    cli = LoteDuble({"g0": json.dumps(r2), "g1": json.dumps(r3)})
    assert T.enviar_lote_api(con, 2, por_chamada=1, cliente=cli) == "msgbatch_x"
    ids_g = json.loads(con.execute("SELECT grupos FROM alertas_triagem_lote").fetchone()[0])
    vistos = []

    def morre_no_segundo(p, s):
        vistos.append(p)
        if len(vistos) == 2:
            raise SystemExit("timeout do cron")
        return json.dumps({"itens": []})
    with pytest.raises(SystemExit):
        T.colher_lotes_api(con, cliente=cli, gerar_b=morre_no_segundo)
    from compliance_agent.llm import claude_api
    gasto = claude_api.ler_gasto()["total_usd"]
    assert con.execute("SELECT COUNT(*) FROM alertas_triagem").fetchone()[0] == 1
    assert T.colher_lotes_api(con, cliente=cli, gerar_b=lambda p, s: json.dumps({"itens": []})) == 1
    assert con.execute("SELECT COUNT(*) FROM alertas_triagem").fetchone()[0] == 2
    assert con.execute("SELECT COUNT(*) FROM alertas_triagem_lote").fetchone()[0] == 0
    assert claude_api.ler_gasto()["total_usd"] == gasto                  # não paga duas vezes
    assert set(ids_g) == {"g0", "g1"}


def test_opus_verifica_achado_e_pausa_api_se_haiku_discorda(con, monkeypatch):
    monkeypatch.setattr(T, "AMOSTRA_MINIMA", 1)
    T.triar_lote(con, 2, gerar=_gerar(_r("aprofundar"), _r("aprofundar")))
    con.execute("UPDATE alertas_triagem SET motor=?", (T.motor_lote(),))
    con.commit()
    opus = lambda t, p, **k: Pensamento(texto=_r("provavel_falso_positivo"), modelo="claude-opus-5-5", segundos=1, tarefa=t)
    avisos = []
    feitos = T.verificar_com_opus(con, 5, pensar=opus, avisar=avisos.append)
    assert {f["estado"] for f in feitos} == {"PENDENTE"}          # Opus divergiu: vai para gente
    from compliance_agent.llm import claude_api
    assert "triagem_alertas" in claude_api.ler_gasto()["pausadas"] and avisos


def test_vigia_so_conta_pares_do_prompt_vigente(con, monkeypatch):
    # 14/11/2026: o vigia somava os 36 pares do prompt ANTIGO (44%) aos do prompt medido no A/B — a tarefa
    # seria repausada pelo erro que o A/B já corrigiu. O motor do lote leva a versão do prompt.
    monkeypatch.setattr(T, "AMOSTRA_MINIMA", 1)
    T.triar_lote(con, 2, gerar=_gerar(_r("aprofundar"), _r("aprofundar")))
    con.execute("UPDATE alertas_triagem SET motor='claude-haiku-5-5@api-lote'")    # prompt antigo, sem versão
    con.commit()
    opus = lambda t, p, **k: Pensamento(texto=_r("provavel_falso_positivo"), modelo="claude-opus-5-5", segundos=1, tarefa=t)
    T.verificar_com_opus(con, 5, pensar=opus, avisar=lambda *_: None)
    from compliance_agent.llm import claude_api
    assert "triagem_alertas" not in claude_api.ler_gasto()["pausadas"]
    assert T.motor_lote().endswith("#" + T.VERSAO_PROMPT) and T.VERSAO_PROMPT == _HASH_SYS_MEDIDO


def test_prompt_medido_no_ab_nao_muda_sem_novo_ab():
    # A/B de 14/11/2026 (Opus como referência, 36 alertas): a regra de MECANISMO levou o Haiku de 21/36 a
    # 31/36 sem perder 🔴/🟡. Trocar o texto sem medir de novo já derrubou recall em outra tarefa (3/6 → 0/6).
    import hashlib
    assert "refaça o raciocínio do detector" in T._SYS and "Valor alto mede o TAMANHO" in T._SYS
    assert hashlib.sha256(T._SYS.encode()).hexdigest()[:12] == _HASH_SYS_MEDIDO, (
        "o prompt da triagem mudou: rode o A/B contra o Opus (scratch ab_triagem) antes de atualizar o hash")


_HASH_SYS_MEDIDO = "25cdd6329a81"


def test_alerta_que_o_detector_declara_nao_acusacao_nao_vai_ao_llm(con):
    con.execute("INSERT INTO alertas VALUES(6,'emendas_d3_favorecido_sancionado','baixa','D3 posterior',"
                "'NÃO é acusação: a sanção só começou em 2026, 3 ano(s) DEPOIS da emenda de 2023',?, 'novo')",
                (json.dumps({"valor": 9e9}),))
    assert 6 not in [a["id"] for a in T.selecionar(con, 10)]


# ── decisão 3 (20/11/2026): detector com FP ≥ 50% sai sozinho da triagem e volta sozinho ─────────────────
def _vereditos(con, tipo, n, fp, em="now"):
    """`n` alertas de `tipo` já julgados (`fp` como provável falso positivo), com a data do veredito `em`."""
    T.garantir(con)
    base = con.execute("SELECT COALESCE(MAX(id),0) FROM alertas").fetchone()[0] + 1
    for i in range(n):
        con.execute("INSERT INTO alertas VALUES(?,?,?,?,?,?,?)", (base + i, tipo, "baixa", "t", "d", "{}", "novo"))
        con.execute("INSERT INTO alertas_triagem(alerta_id,prioridade,em,opus_pendente) VALUES(?,?,datetime(?),0)",
                    (base + i, "provavel_falso_positivo" if i < fp else "monitorar", em))
    con.commit()


def test_detector_com_metade_de_falso_positivo_sai_da_triagem_e_o_alerta_fica(con):
    _vereditos(con, "direcionamento", 30, 15)                      # 50% em 30: exatamente no corte → sai
    assert T.detectores_suspensos(con) == {"direcionamento": (30, 15)}
    ids = [a["id"] for a in T.selecionar(con, 10)]
    assert 2 not in ids and ids == [3, 1, 4]                       # o alerta 2 (direcionamento) não vai ao juiz
    assert con.execute("SELECT status FROM alertas WHERE id=2").fetchone()[0] == "novo"   # e segue gravado


def test_abaixo_do_corte_ou_amostra_pequena_nao_suspende(con):
    _vereditos(con, "direcionamento", 30, 14)                      # 46,7%: fica
    _vereditos(con, "pcrj_d7_fracionamento", 29, 29)               # 100% mas n=29 < 30: não mede, fica
    assert T.detectores_suspensos(con) == {}
    assert [a["id"] for a in T.selecionar(con, 10)] == [2, 3, 1, 4]


def test_veredito_de_ramo_que_hoje_nao_acusa_fica_fora_da_medida(con):
    """Catraca da classe "medida conta o ramo já corrigido" (21/11/2026): D9 tinha 37% de FP na janela, mas 158 dos
    190 eram de alertas que hoje se declaram "NÃO é acusação" (a triagem já os pula). A taxa mede o que o detector
    ainda manda ao juiz — senão o detector consertado segue suspenso por 30 dias."""
    _vereditos(con, "pcrj_d9_socio_na_folha", 30, 30)              # 30 FP antigos…
    con.execute("UPDATE alertas SET descricao='NÃO é acusação — sócio entrou depois do último pagamento' "
                "WHERE tipo='pcrj_d9_socio_na_folha'")              # …de um ramo que hoje não acusa
    _vereditos(con, "pcrj_d9_socio_na_folha", 30, 3)               # controle: os que acusam, 10%
    assert dict((t, (n, fp)) for t, n, fp in T.precisao_por_detector(con))["pcrj_d9_socio_na_folha"] == (30, 3)
    assert T.detectores_suspensos(con) == {}


def test_detector_volta_sozinho_quando_os_vereditos_saem_da_janela(con):
    _vereditos(con, "direcionamento", 40, 40, em="-31 days")       # todo o histórico ruim, fora da janela
    assert T.detectores_suspensos(con) == {}
    assert 2 in [a["id"] for a in T.selecionar(con, 10)]


def test_fila_do_opus_pula_detector_suspenso_sem_perder_o_item(con):
    T.triar_lote(con, 2, gerar=_gerar(_r("aprofundar"), _r("aprofundar")))   # alertas 2 e 3 esperam o Opus
    _vereditos(con, "direcionamento", 30, 30)
    vistos = []

    def opus(t, p, **k):
        vistos.append(p)
        return Pensamento(texto=_r("aprofundar"), modelo="claude-opus-5-5", segundos=1, tarefa=t)
    T.verificar_com_opus(con, 10, pensar=opus, avisar=lambda *_: None)
    assert len(vistos) == 1 and "ALERTA #3" in vistos[0]          # só o pcrj_d7 foi julgado
    assert _estado(con, 2)[2] == 1                                 # o 2 espera a volta do detector


def test_o_corte_mora_num_lugar_so():
    import inspect

    from tools import automelhoria_geral as A
    assert (T.FP_SUSPENDE, T.FP_MIN_N, T.FP_JANELA_DIAS) == (0.50, 30, 30)
    assert "0.50" not in inspect.getsource(A) and not hasattr(A, "FP_MIN_N")
    t = A.avaliar_precisao([("d3", 610, 346), ("d6", 228, 80)])
    assert "SUSPENSO" in t[0]["titulo"] and "SUSPENSO" not in t[1]["titulo"]   # 57% sai; 35% só avisa
