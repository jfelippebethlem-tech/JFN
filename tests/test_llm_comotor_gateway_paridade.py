# -*- coding: utf-8 -*-
"""Paridade da migração do co-motor (`llm/comotor.juizo`) e de `rotina_base.pensar` para o gateway LLM
(plano mestre v2 §6; ordem 3 do mapa ~/vault/refatoracao/gateway-llm-pontos-de-chamada.md; risco R3).

Para cada um dos 9 chamadores (#11–19 do mapa), a MESMA entrada roda duas vezes com backends falsos:
  · LEGADO — o co-motor com `pensar` = simulação fiel de `claude_motor.pensar(backend="auto")` (assinatura e, sem
    ela, a API paga com o modelo de `claude_api.modelo_para`) e a cascata de sempre (`contingencia.gerar_cascata`);
  · NOVO — o co-motor sem nada injetado: lado Claude por `gateway.chamar(so_camadas=(2, 3))`, lado cascata por
    `gateway.chamar(so_camadas=(4,))`.
Compara-se o provedor escolhido (assinatura | API, com modelo, espera e prazo), o formato do retorno do chamador e
a proveniência exibida. O que MUDA é testado à parte, com o motivo: a cascata grátis (data_policy desconhecida) não
recebe classe `interno`; o teto mensal barra a API; o CPF sai mascarado. Com a política relaxada para `publico`
(arquivo de política de teste), legado e novo coincidem inteiros — inclusive a cascata.

Nada aqui chama API real nem a assinatura: todo backend é dublê; o default do gateway, sob pytest, nem tenta."""
import importlib
import json
import sqlite3
from datetime import datetime, timezone

import pytest
import yaml

from compliance_agent import rotina_base as RB
from compliance_agent.adaptadores.llm import gateway as G
from compliance_agent.dominio import mascara as M
from compliance_agent.llm import cascata_ajuste, claude_api, claude_motor, contingencia, cruzamento
from compliance_agent.llm import comotor as CM
from compliance_agent.llm.claude_motor import Pensamento

VOL, JUIZO, HAIKU = claude_motor.MODELO_VOLUME, claude_motor.MODELO_JUIZO, claude_api.MODELO_BARATO
TAREFAS = ("triagem_alertas", "camada_subjetiva", "parecer_juridico", "pericia_fornecedor", "investigacao_risco",
           "pericia_execucao")


@pytest.fixture(autouse=True)
def _isolado(tmp_path, monkeypatch):
    for k, v in {"JFN_LLM_TRACE_DB": "trace.db", "JFN_CLAUDE_DADOS": "estado", "JFN_CLAUDE_CWD": "cwd",
                 "JFN_CRUZAMENTO_DB": "cruz.db", "JFN_CONFERENCIA_DB": "conf.db"}.items():
        monkeypatch.setenv(k, str(tmp_path / v))
    monkeypatch.setenv("JFN_CLAUDE_API", "0")                 # a API real nunca
    monkeypatch.delenv("JFN_VEREDITO_LLM_DISABLED", raising=False)
    monkeypatch.delenv("JFN_LLM_POLITICA", raising=False)
    monkeypatch.setattr(G, "_pre_assinatura", lambda t: None)
    monkeypatch.setattr(cruzamento, "preferido", lambda t: None)
    monkeypatch.setattr(cascata_ajuste, "rebaixados", lambda t: set())
    from compliance_agent import direcionamento_cerebro as dc
    monkeypatch.setattr(dc, "ultimo_provedor", "", raising=False)
    monkeypatch.setattr(dc, "ultimo_modelo", "", raising=False)
    return tmp_path


# ── o mundo falso ────────────────────────────────────────────────────────────────────────────────────
class Mundo:
    """Um cenário: o que cada provedor faz. `chamadas` registra quem foi chamado, com modelo/espera/prazo."""

    def __init__(self, resp: str, *, assinatura=True, api=True, cascata: str | None = None):
        self.resp, self.assinatura, self.api = resp, assinatura, api
        self.cascata = resp if cascata is None else cascata
        self.chamadas: list[tuple] = []
        self.prompts: list[str] = []

    def _dados(self, schema):
        return json.loads(self.resp) if schema is not None else None

    # NOVO: backends do gateway
    def b_assinatura(self, *, tarefa, prompt, schema, modelo_pref, timeout, espera=None, **_):
        self.chamadas.append(("assinatura", modelo_pref or VOL, espera, timeout))
        self.prompts.append(prompt)
        if not self.assinatura:
            raise RuntimeError("assinatura caiu (dublê)")
        return G.Retorno(texto=self.resp, modelo=modelo_pref or VOL, dados=self._dados(schema))

    def b_api(self, *, tarefa, prompt, schema, modelo_pref, timeout, **_):
        modelo = claude_api._sem_opus(modelo_pref or claude_api.modelo_para(tarefa))
        self.chamadas.append(("api", modelo, None, timeout))
        if not self.api:
            raise RuntimeError("API caiu (dublê)")
        return G.Retorno(texto=self.resp, modelo=modelo, tokens_in=100, tokens_out=50)

    # LEGADO: claude_motor.pensar(backend="auto"), simulado como o código de antes de 24/11/2026
    def pensar_auto(self, tarefa, prompt, *, schema=None, modelo=VOL, timeout=180.0, sistema="", espera=None, **_):
        self.chamadas.append(("assinatura", modelo, espera, timeout))
        self.prompts.append(prompt)
        if self.assinatura:
            return Pensamento(texto=self.resp, modelo=modelo, segundos=0.0, tarefa=tarefa, dados=self._dados(schema))
        modelo_api = claude_api.modelo_para(tarefa)            # o auto NÃO repassava o modelo à API
        self.chamadas.append(("api", modelo_api, None, timeout))
        if self.api:
            return Pensamento(texto=self.resp, modelo=f"{modelo_api}{claude_api.SUFIXO_API}", segundos=0.0,
                              tarefa=tarefa, dados=self._dados(schema))
        return None

    # a cascata de sempre (DC), nos dois caminhos
    def gerar_cascata(self, prompt, sistema="", timeout=45.0, json_saida=True):
        self.chamadas.append(("cascata",))
        return self.cascata


def rodar(chamar, m: Mundo, monkeypatch, tmp_path, *, legado: bool):
    """Roda o chamador sob o mundo `m`. Devolve (saída do chamador, ultima_chamada(), chamadas)."""
    nome = "legado" if legado else "novo"
    with monkeypatch.context() as mp:
        mp.setenv("JFN_CRUZAMENTO_DB", str(tmp_path / f"cruz_{nome}.db"))
        mp.setenv("JFN_CONFERENCIA_DB", str(tmp_path / f"conf_{nome}.db"))
        mp.setattr(contingencia, "gerar_cascata", m.gerar_cascata)
        if legado:
            orig = CM.juizo
            mp.setattr(CM, "juizo", lambda tarefa, **kw: orig(tarefa, **{"pensar": m.pensar_auto, **kw}))
        else:
            mp.setitem(G.BACKENDS, "assinatura_claude", m.b_assinatura)
            mp.setitem(G.BACKENDS, "api_anthropic", m.b_api)
        CM._ultima.clear()
        from compliance_agent import direcionamento_cerebro as dc
        mp.setattr(dc, "ultimo_provedor", "", raising=False)    # proveniência de uma rodada não vaza para a outra
        mp.setattr(dc, "ultimo_modelo", "", raising=False)
        try:
            saida = chamar()
        except RuntimeError as e:
            saida = ("ERRO", str(e))
        return saida, CM.ultima_chamada(), list(m.chamadas)


# ── os 9 chamadores, cada um pela porta que usa em produção ──────────────────────────────────────────
EXEC = json.dumps({"execucao_comprovada": "parcial", "nota_risco_execucao": 5, "fundamentacao": "f"})
FACH = json.dumps({"veredito": "INDICIOS", "confianca": "MEDIA", "fundamentacao": "f", "base_legal": "b"})
ADV = json.dumps({"refuta": False, "motivo": "sobreviveu", "explicacao_inocente": ""})
RISCO = json.dumps({"risco": "baixo", "citacao": "", "justificativa": "ok"})
TRIA = json.dumps({"prioridade": "provavel_falso_positivo", "nota": 1, "citacao": "trecho citável",
                   "justificativa": "j", "proximo_passo": "p"})
DISC = json.dumps([{"i": 0, "analise": "mecanismo citado no trecho"}])
EVID = [{"fonte": "pncp", "trecho": "t", "hash": "h", "capturado_em": "2026-11-01"}]


def _c11_triagem():
    from compliance_agent import triagem_alertas as T
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE alertas(id INTEGER PRIMARY KEY, tipo TEXT, severidade TEXT, titulo TEXT, descricao TEXT, "
                "evidencias TEXT, status TEXT, detectado_em TEXT, pessoa_id INTEGER)")
    con.execute("INSERT INTO alertas VALUES(1,'fracionamento','ALTA','Dispensa repetida','descrição do alerta um com "
                "trecho citável','{\"valor_total\": 100}','novo','2026-11-01',NULL)")
    T.garantir(con)
    f = T.triar_lote(con, 1)
    return {k: f[0][k] for k in ("prioridade", "nota", "motor", "estado")} if f else None


def _c13_lex():
    from compliance_agent import lex_analise_conteudo as LX
    achados = [{"rf": "R3", "trecho": "trecho do processo lido", "numero_proc": "SEI-1"}]
    return [a.get("analise") for a in LX.analise_discursiva(achados)]


def _c14_fachada():
    from compliance_agent import rede_fachada as RF
    return RF.veredito_llm({"cnpj": "00000000000191", "total_pago": 1000.0})


def _c15_adversarial():
    from compliance_agent.detectores import base
    return base.verificar_adversarial(EVID, "achado preliminar")


def _c16_painel():
    from compliance_agent.detectores import base
    return base.painel_adversarial(EVID, "achado preliminar")      # dict inteiro: votos, refutações, motivo


def _c17_risco():
    from compliance_agent.llm import orquestrador
    return orquestrador._classificar_risco("conclusão do agente sobre o alvo", None)


def _c18_execucao():
    return CM.juizo("pericia_execucao")("PROCESSO SEI-1 ...", "SISTEMA", 60.0, item="sei:SEI-1")


def _c19_bombeiros():
    import tools.lex_bombeiros as LB
    LB = importlib.reload(LB)              # `gerar_sync = juizo(...)` é feito no import do módulo
    return LB.gerar_sync("PROCESSO SEI-2700 ...", "SISTEMA", 60.0)


# (id, tarefa, resposta do Claude, chamador, espera, prazo do Claude, modelo da assinatura)
CHAMADORES = [
    ("#11 triagem_alertas.triar_lote", "triagem_alertas", TRIA, _c11_triagem, None, 180.0, VOL),
    ("#13 lex_analise_conteudo.analise_discursiva", "parecer_juridico", DISC, _c13_lex, 15.0, 150.0, JUIZO),
    ("#14 rede_fachada.veredito_llm", "pericia_fornecedor", FACH, _c14_fachada, 15.0, 120.0, VOL),
    ("#15 detectores.base.verificar_adversarial", "camada_subjetiva", ADV, _c15_adversarial, None, 180.0, VOL),
    ("#16 detectores.base._com_sistema (painel)", "camada_subjetiva", ADV, _c16_painel, None, 180.0, VOL),
    ("#17 orquestrador._classificar_risco", "investigacao_risco", RISCO, _c17_risco, None, 180.0, VOL),
    ("#18 tools.lex_execucao (juizo pericia_execucao)", "pericia_execucao", EXEC, _c18_execucao, None, 180.0, VOL),
    ("#19 tools.lex_bombeiros.gerar_sync", "pericia_execucao", EXEC, _c19_bombeiros, None, 180.0, VOL),
]
IDS = [c[0] for c in CHAMADORES]


def _so_claude(chamadas):
    return [c for c in chamadas if c[0] != "cascata"]


def _sem_proveniencia_da_cascata(saida):
    """O veredito da fachada traz `motor` com o '(+cascata)' do cruzamento: o resto do dict tem de ser igual."""
    if isinstance(saida, dict) and "motor" in saida:
        return {k: v for k, v in saida.items() if k != "motor"}
    return saida


# ── 1. paridade: assinatura responde ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("cid,tarefa,resp,chamar,espera,prazo,modelo", CHAMADORES, ids=IDS)
def test_paridade_assinatura_responde(cid, tarefa, resp, chamar, espera, prazo, modelo, monkeypatch, _isolado):
    s_old, u_old, c_old = rodar(chamar, Mundo(resp), monkeypatch, _isolado, legado=True)
    s_new, u_new, c_new = rodar(chamar, Mundo(resp), monkeypatch, _isolado, legado=False)
    # mesmo provedor (assinatura), mesmo modelo, mesma espera e mesmo prazo
    assert _so_claude(c_new) == _so_claude(c_old) and _so_claude(c_new)
    assert set(_so_claude(c_new)) == {("assinatura", modelo, espera, prazo)}      # o painel (#16) chama 3 lentes
    assert u_new["exibido"] == u_old["exibido"] == f"claude:{modelo}"
    if tarefa != "triagem_alertas":                 # triagem: o ESTADO muda (teste próprio abaixo)
        assert _sem_proveniencia_da_cascata(s_new) == _sem_proveniencia_da_cascata(s_old)
    else:
        assert {k: s_new[k] for k in ("prioridade", "nota", "motor")} == \
            {k: s_old[k] for k in ("prioridade", "nota", "motor")}


# ── 2. paridade: sem assinatura, a API paga (mesmo modelo de antes: o do claude_api, nunca o Opus) ─────
@pytest.mark.parametrize("cid,tarefa,resp,chamar,espera,prazo,modelo", CHAMADORES, ids=IDS)
def test_paridade_sem_assinatura_cai_na_api(cid, tarefa, resp, chamar, espera, prazo, modelo, monkeypatch, _isolado):
    s_old, u_old, c_old = rodar(chamar, Mundo(resp, assinatura=False), monkeypatch, _isolado, legado=True)
    s_new, u_new, c_new = rodar(chamar, Mundo(resp, assinatura=False), monkeypatch, _isolado, legado=False)
    esperado = [("assinatura", modelo, espera, prazo), ("api", HAIKU, None, prazo)]
    assert _so_claude(c_new) == _so_claude(c_old) and _so_claude(c_new)
    assert _so_claude(c_new) == esperado * (len(_so_claude(c_new)) // 2)
    assert u_new["exibido"] == u_old["exibido"] == f"claude:{HAIKU}{claude_api.SUFIXO_API}"
    if tarefa != "triagem_alertas":
        assert _sem_proveniencia_da_cascata(s_new) == _sem_proveniencia_da_cascata(s_old)
    else:
        assert s_new == s_old                      # @api: PENDENTE nos dois (aguarda o Opus)


# ── 3. o que MUDA: a cascata grátis não recebe classe `interno` (recusa explícita, nada sai) ───────────
@pytest.mark.parametrize("cid,tarefa,resp,chamar,espera,prazo,modelo", CHAMADORES, ids=IDS)
def test_muda_cascata_recusada_para_interno(cid, tarefa, resp, chamar, espera, prazo, modelo, monkeypatch, _isolado):
    assert G.classe_da_tarefa(tarefa) == "interno"
    # (a) com o Claude respondendo: o legado rodava a cascata em paralelo (tarefas com normalizador); o novo, nunca
    _, u_old, c_old = rodar(chamar, Mundo(resp), monkeypatch, _isolado, legado=True)
    _, u_new, c_new = rodar(chamar, Mundo(resp), monkeypatch, _isolado, legado=False)
    assert ("cascata",) not in c_new
    if tarefa != "parecer_juridico":               # parecer não tem normalizador: a cascata só entrava sem o Claude
        assert ("cascata",) in c_old and u_old["outro"]
        assert u_new["outro"] is None and "data_policy" in u_new["recusa"]
    # (b) sem Claude nenhum: o legado devolvia a cascata; o novo recusa COM MOTIVO (o chamador degrada honesto)
    s_old, _, c_old = rodar(chamar, Mundo(resp, assinatura=False, api=False), monkeypatch, _isolado, legado=True)
    s_new, u_new, c_new = rodar(chamar, Mundo(resp, assinatura=False, api=False), monkeypatch, _isolado, legado=False)
    assert ("cascata",) in c_old and ("cascata",) not in c_new
    assert "data_policy" in (u_new.get("recusa") or ""), u_new
    assert s_new != s_old


def test_muda_recusa_chega_ao_chamador_com_motivo(monkeypatch, _isolado):
    m = Mundo(EXEC, assinatura=False, api=False)
    s, u, _ = rodar(_c18_execucao, m, monkeypatch, _isolado, legado=False)
    assert s[0] == "ERRO" and "RECUSADA pela política" in s[1] and "data_policy" in s[1]
    s, _, _ = rodar(_c14_fachada, Mundo(FACH, assinatura=False, api=False), monkeypatch, _isolado, legado=False)
    assert s["disponivel"] is False and "LLM indisponível" in s["motivo"]
    s, _, _ = rodar(_c17_risco, Mundo(RISCO, assinatura=False, api=False), monkeypatch, _isolado, legado=False)
    assert s["risco"] == "indeterminado" and "RECUSADA" in s["justificativa"]


def test_muda_triagem_sem_segunda_leitura_fica_pendente(monkeypatch, _isolado):
    """Antes: Claude ⚪ + cascata concordante ⇒ VERIFICADO. Agora a cascata não lê alerta `interno` ⇒ PENDENTE."""
    s_old, _, _ = rodar(_c11_triagem, Mundo(TRIA), monkeypatch, _isolado, legado=True)
    s_new, _, _ = rodar(_c11_triagem, Mundo(TRIA), monkeypatch, _isolado, legado=False)
    assert s_old["estado"] == "VERIFICADO" and s_new["estado"] == "PENDENTE"


# ── 4. com a política relaxada para `publico`: legado e novo coincidem inteiros, cascata inclusive ─────
def _politica_publico(tmp_path, monkeypatch):
    pol = yaml.safe_load(G._caminho_politica().read_text(encoding="utf-8"))
    for t in TAREFAS:
        pol["tarefas"][t]["classe_dado"] = "publico"
    p = tmp_path / "pol_publico.yaml"
    p.write_text(yaml.safe_dump(pol, allow_unicode=True), encoding="utf-8")
    monkeypatch.setenv("JFN_LLM_POLITICA", str(p))


@pytest.mark.parametrize("cenario", ["assinatura", "api", "so_cascata"])
@pytest.mark.parametrize("cid,tarefa,resp,chamar,espera,prazo,modelo", CHAMADORES, ids=IDS)
def test_paridade_total_quando_a_politica_permite(cid, tarefa, resp, chamar, espera, prazo, modelo, cenario,
                                                  monkeypatch, _isolado):
    _politica_publico(_isolado, monkeypatch)
    kw = {"assinatura": {}, "api": {"assinatura": False}, "so_cascata": {"assinatura": False, "api": False}}[cenario]
    s_old, u_old, c_old = rodar(chamar, Mundo(resp, **kw), monkeypatch, _isolado, legado=True)
    s_new, u_new, c_new = rodar(chamar, Mundo(resp, **kw), monkeypatch, _isolado, legado=False)
    assert sorted(c_new) == sorted(c_old)           # mesmos provedores (a cascata roda em paralelo: ordem livre)
    assert s_new == s_old
    for k in ("exibido", "outro", "divergencia", "conferencia_pendente"):
        assert u_new.get(k) == u_old.get(k), k


# ── 5. o que MUDA: teto mensal e máscara ──────────────────────────────────────────────────────────────
def test_muda_teto_mensal_barra_a_api_que_o_auto_chamaria(monkeypatch, _isolado):
    con = sqlite3.connect(_isolado / "trace.db")
    G.migrar(con)
    con.execute("INSERT INTO llm_trace(ts, origem, pago, custo_usd, provedor, ok) VALUES(?, 'gateway', 1, 99.0, "
                "'api_anthropic', 1)", (datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),))
    con.commit()
    con.close()
    _, _, c_old = rodar(_c18_execucao, Mundo(EXEC, assinatura=False), monkeypatch, _isolado, legado=True)
    s_new, u_new, c_new = rodar(_c18_execucao, Mundo(EXEC, assinatura=False), monkeypatch, _isolado, legado=False)
    assert ("api", HAIKU, None, 180.0) in c_old                     # o auto ia à API sem saber do teto mensal
    assert not [c for c in c_new if c[0] == "api"]                  # o gateway nem chama
    assert s_new[0] == "ERRO" and "teto mensal" in s_new[1]


def _cpf_sintetico() -> str:
    base = [5, 2, 9, 9, 8, 2, 2, 4, 7]                              # sintético, montado em tempo de execução
    for _ in range(2):
        s = sum(d * w for d, w in zip(base, range(len(base) + 1, 1, -1)))
        base.append(0 if s % 11 < 2 else 11 - s % 11)
    return "".join(map(str, base))


def test_muda_cpf_sai_mascarado_e_volta_desmascarado(monkeypatch, _isolado):
    cpf = _cpf_sintetico()
    assert M.cpfs_expostos(cpf) == 1
    m = Mundo("eco")

    def ecoa(*, prompt, modelo_pref, **kw):
        m.prompts.append(prompt)
        return G.Retorno(texto="sócio " + prompt.split("sócio ")[1].split()[0], modelo=modelo_pref or VOL)
    with monkeypatch.context() as mp:
        mp.setitem(G.BACKENDS, "assinatura_claude", ecoa)
        out = CM.juizo("parecer_juridico")(f"sócio {cpf} assinou", "S", 45.0, json_saida=False)
    assert M.cpfs_expostos(m.prompts[0]) == 0 and cpf not in m.prompts[0]
    assert out == f"sócio {cpf}"                                    # o chamador recebe o texto original


def test_trace_por_chamada_com_tarefa_classe_e_versao(monkeypatch, _isolado):
    rodar(_c18_execucao, Mundo(EXEC), monkeypatch, _isolado, legado=False)
    con = sqlite3.connect(_isolado / "trace.db")
    linhas = con.execute("SELECT tarefa, classe_dado, prompt_version, provedor, ok, erro FROM llm_trace "
                         "WHERE origem='gateway' ORDER BY rowid").fetchall()
    con.close()
    assert ("pericia_execucao", "interno", CM.PROMPT_VERSION, "assinatura_claude", 1, None) in linhas
    assert any(r[3] is None and "recusado: classe" in (r[5] or "") for r in linhas)   # a recusa da cascata


def test_trava_ocupada_nao_conta_falha_no_circuito(monkeypatch, _isolado):
    """Assinatura que NÃO TENTOU (trava do claude ocupada) pula para a API sem abrir o circuito da assinatura."""
    monkeypatch.setattr(claude_motor, "pensar", lambda *a, **k: None)
    monkeypatch.setattr(claude_motor, "ultimo_motivo", "ocupado: outro claude do JFN rodando há mais de 15 s")
    m = Mundo(FACH)
    with monkeypatch.context() as mp:
        mp.setitem(G.BACKENDS, "api_anthropic", m.b_api)
        for _ in range(6):
            CM.juizo("pericia_fornecedor", espera=15.0, cascata=lambda *a, **k: FACH)("p", "S", 45.0)
    pol = G.politica()
    assert G.circuito_aberto("assinatura_claude", pol) is None
    assert [c[0] for c in m.chamadas] == ["api"] * 6


def test_injetados_seguem_o_caminho_de_antes(monkeypatch, _isolado):
    """`pensar` injetado (juiz de qualidade, perícia integral, testes) não passa pelo gateway: migração própria."""
    monkeypatch.setattr(G, "chamar", lambda *a, **k: pytest.fail("não devia passar pelo gateway"))
    m = Mundo(EXEC)
    with monkeypatch.context() as mp:
        mp.setattr(contingencia, "gerar_cascata", m.gerar_cascata)
        CM.juizo("pericia_execucao", pensar=m.pensar_auto)("p", "S", 60.0)
    assert sorted(m.chamadas) == sorted([("assinatura", VOL, None, 180.0), ("cascata",)])


# ── 6. rotina_base.pensar (#12, governo_couto_regras._rodar) ──────────────────────────────────────────
HIP = json.dumps({"hipoteses": [{"id": "H1", "regra_ou_hipotese": "padrão", "grau": "🟡", "confianca": "média",
                                 "orgao": "X", "regras_base": ["D1"], "explicacao_inocente": "e",
                                 "proximo_passo": "p"}]})


def _c12(monkeypatch, m, **kw):
    from compliance_agent.governo_couto_regras import ESQUEMA_H
    with monkeypatch.context() as mp:
        mp.setitem(G.BACKENDS, "assinatura_claude", m.b_assinatura)
        mp.setitem(G.BACKENDS, "api_anthropic", m.b_api)
        mp.setattr(contingencia, "gerar_cascata", m.gerar_cascata)
        return RB.pensar("camada_subjetiva", "REGRAS: ...", schema=ESQUEMA_H, modelo="claude-opus-5-5",
                         timeout=600.0, **kw)


def test_rotina_assinatura_mesmo_modelo_e_prazo(monkeypatch, _isolado):
    m = Mundo(HIP)
    r, motivo = _c12(monkeypatch, m)
    assert motivo is None and r == json.loads(HIP)                  # dados do schema, como antes
    assert m.chamadas == [("assinatura", "claude-opus-5-5", None, 600.0)]
    assert RB.ULTIMO_MODELO == "claude-opus-5-5" and RB.ULTIMA_EM_CONTINGENCIA is False


def test_rotina_sem_assinatura_api_com_o_modelo_do_claude_api_e_fila_do_opus(monkeypatch, _isolado):
    m = Mundo(HIP, assinatura=False)
    r, motivo = _c12(monkeypatch, m)
    assert motivo is None and r == json.loads(HIP)
    # o auto de antes também mandava o modelo de `claude_api.modelo_para` (Haiku), nunca o Opus pedido
    assert m.chamadas == [("assinatura", "claude-opus-5-5", None, 600.0), ("api", HAIKU, None, 600.0)]
    assert RB.ULTIMO_MODELO == f"{HAIKU}{claude_api.SUFIXO_API}" and RB.ULTIMA_EM_CONTINGENCIA is True


def test_rotina_muda_contingencia_recusada_para_interno(monkeypatch, _isolado):
    chamou = []
    monkeypatch.setattr(contingencia, "cascata", lambda *a, **k: chamou.append(1) or ({"hipoteses": []}, "g:x"))
    r, motivo = _c12(monkeypatch, Mundo(HIP, assinatura=False, api=False))
    assert r is None and "contingência RECUSADA" in motivo and "data_policy" in motivo and not chamou


def test_rotina_contingencia_quando_a_politica_permite(monkeypatch, _isolado):
    _politica_publico(_isolado, monkeypatch)
    vistos = []
    monkeypatch.setattr(contingencia, "cascata",
                        lambda tarefa, prompt, **k: vistos.append(tarefa) or (json.loads(HIP), "gemini:3-flash"))
    r, motivo = _c12(monkeypatch, Mundo(HIP, assinatura=False, api=False))
    assert motivo is None and r == json.loads(HIP) and vistos == ["camada_subjetiva"]
    assert RB.ULTIMO_MODELO == "gemini:3-flash" and RB.ULTIMA_EM_CONTINGENCIA is True


def test_rotina_abstencao_volta_com_motivo(monkeypatch, _isolado):
    r, motivo = _c12(monkeypatch, Mundo(json.dumps({"absteve": True, "motivo": "dados insuficientes"})))
    assert r is None and "absteve-se: dados insuficientes" in motivo
