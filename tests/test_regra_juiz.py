# -*- coding: utf-8 -*-
"""Juiz subjetivo das regras de qualidade — nenhum teste chama o Claude de verdade (executor dublê).

Trava principal (CNF-10, ordem do dono de 13/11/2026: "fable tem que usar assinatura só"): o juiz chama o motor
SEMPRE com `backend="cli"` — o padrão `auto` do motor cai na API paga quando a assinatura falha.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from compliance_agent.llm import claude_motor
from compliance_agent.qualidade import juiz, regras, sensores

FONTE = Path(juiz.__file__).read_text(encoding="utf-8")
AGORA = datetime(2026, 11, 13, 22, 0)


def _resposta(notas: dict, **extra) -> str:
    return json.dumps({"notas": notas, "motivos": {c: f"motivo de {c}" for c in notas}, "veredito": "aprovada",
                       "o_que_falta": "extrato da conta", "escalar": False} | extra, ensure_ascii=False)


def _pensar_duble(texto: str, chamadas: list):
    def pensar(tarefa, prompt, **kw):
        chamadas.append({"tarefa": tarefa, "prompt": prompt, **kw})
        return claude_motor.Pensamento(texto=texto, modelo="claude-duble", segundos=0.1, tarefa=tarefa)
    return pensar


def _afirmacao(**kw) -> juiz.Afirmacao:
    base = dict(id="vault:caso-sintetico", sistema="vault", rotulo="caso sintético", grau="alto", valor=2_000_000.0,
                texto="Empresa Alfa Ltda (fictícia) recebeu R$ 2.000.000,00; indício de duplicidade a verificar.")
    return juiz.Afirmacao(**(base | kw))


def test_juiz_so_chama_o_claude_pela_assinatura():
    """Estático E dinâmico: o código fixa backend cli, não lê chave, e a chamada real ao motor leva backend='cli'."""
    assert juiz.BACKEND == "cli"
    assert not re.search(r"backend\s*=\s*[\"'](auto|api)[\"']", FONTE), "o juiz não pode usar backend auto/api"
    assert not re.search(r"ANTHROPIC|anthropic\.env|claude_api", FONTE), "o juiz não toca em chave nem no módulo da API paga"
    chamadas: list = []
    todas = {c: 3 for c in regras.rubricas()}
    juiz.julgar(_afirmacao(), pensar=_pensar_duble(_resposta(todas), chamadas), agora=AGORA)
    assert chamadas and all(c["backend"] == "cli" for c in chamadas)
    assert chamadas[0]["tarefa"] == "juiz_qualidade" and chamadas[0]["modelo"] == claude_motor.MODELO_JUIZO


def test_prova_backend_errado_seria_acusado():
    """A catraca acima fica vermelha com o defeito: uma linha com backend auto casa a regex."""
    assert re.search(r"backend\s*=\s*[\"'](auto|api)[\"']", 'r = pensar(t, p, backend="auto")')


def test_juiz_tem_teto_proprio_no_motor():
    assert 0 < claude_motor.TETOS_TAREFA.get("juiz_qualidade", 0) <= 20      # amostra pequena: cota é compartilhada


def test_veredito_sai_das_notas_e_nao_da_palavra_do_modelo():
    notas = {c: 4 for c in regras.rubricas()} | {"moldura": 1}
    av = juiz.julgar(_afirmacao(), pensar=_pensar_duble(_resposta(notas, veredito="aprovada"), []), agora=AGORA)
    assert av.estado == "JULGADA" and av.veredito == "reprovada"            # o modelo disse "aprovada"; a nota 1 manda
    assert juiz.veredito_de({"a": 2, "b": 4}) == "ressalva" and juiz.veredito_de({"a": 3}) == "aprovada"


def test_sem_claude_fica_pendente_e_nao_inventa_nota():
    def sem_cota(tarefa, prompt, **kw):
        claude_motor.ultimo_motivo = "teto diário da tarefa"
        return None
    av = juiz.julgar(_afirmacao(), pensar=sem_cota, agora=AGORA)
    assert av.estado == "PENDENTE" and not av.notas and "sem Claude" in av.juiz


def test_resposta_sem_json_ou_nota_fora_da_escala_nao_vira_veredito():
    av = juiz.julgar(_afirmacao(), pensar=_pensar_duble("não consigo avaliar", []), agora=AGORA)
    assert av.estado == "PENDENTE"
    av = juiz.julgar(_afirmacao(), pensar=_pensar_duble(_resposta({"moldura": 9, "auditor": "alta"}), []), agora=AGORA)
    assert av.estado == "PENDENTE" and not av.notas


def test_cpf_e_mascarado_antes_de_ir_ao_modelo(tmp_path):
    chamadas: list = []
    ctx = sensores.Ctx(dados=tmp_path, vault=tmp_path / "vault", hermes=tmp_path / "h", api=lambda r: {}, agora=AGORA)
    casos = tmp_path / "vault" / "casos"
    casos.mkdir(parents=True)
    (casos / "caso-x.md").write_text("---\ntipo: caso\ngrau: alto\nstatus: aberto\n---\nSócio de CPF 111.444.777-35.\n", encoding="utf-8")
    (ctx.repo / "config").exists()
    cands = [c for c in juiz.candidatas(ctx) if c.sistema == "vault"]
    assert cands and "111.444.777-35" not in cands[0].texto and "***.444.777-**" in cands[0].texto
    juiz.julgar(cands[0], pensar=_pensar_duble(_resposta({"moldura": 3}), chamadas), agora=AGORA)
    assert "111.444.777-35" not in chamadas[0]["prompt"]


def test_vault_nao_vai_para_a_cascata():
    """Material interno só ao Claude da assinatura: com `publica=False` a cascata nem é consultada."""
    usou = []
    juiz.julgar(_afirmacao(publica=False), pensar=_pensar_duble(_resposta({"moldura": 3}), []),
                cascata=lambda *a, **k: usou.append(1) or "{}", agora=AGORA)
    assert not usou


def test_escala_ao_dono_por_codigo():
    a = _afirmacao(valor=50_000_000.0, grau="🔴")
    assert juiz.deve_escalar(a, {"moldura": 2, "auditor": 4}, False)[0]       # R$ 10 mi+ com ressalva de moldura
    assert juiz.deve_escalar(_afirmacao(), {"moldura": 0}, False)[0]          # nota 0
    assert juiz.deve_escalar(_afirmacao(pessoa_fisica=True), {"moldura": 4}, False)[0]
    assert not juiz.deve_escalar(_afirmacao(valor=1000.0), {"moldura": 3}, False)[0]


def test_amostra_e_por_risco_nao_rejulga_e_nao_deixa_um_sistema_comer_tudo():
    cands = [_afirmacao(id=f"painel:m{i}", sistema="painel", valor=10.0 ** (9 - i), grau="manchete", texto=f"m{i}") for i in range(6)]
    cands += [_afirmacao(id="vault:c1", valor=1e5, texto="c1"), _afirmacao(id="yoda:y1", sistema="yoda", valor=1e3, grau="", texto="y1")]
    esc = juiz.amostrar(cands, {}, 4, AGORA)
    assert [a.id for a in esc[:2]] == ["painel:m0", "painel:m1"]             # maior risco primeiro
    assert {a.sistema for a in esc} == {"painel", "vault", "yoda"}           # repartida entre os grupos presentes
    hist = {"painel:m0": {"impressao": cands[0].impressao, "em": AGORA.isoformat(), "estado": "JULGADA"}}
    assert "painel:m0" not in [a.id for a in juiz.amostrar(cands, hist, 4, AGORA)]
    hist["painel:m0"]["impressao"] = "outro-texto"                           # o texto mudou: volta a ser julgada
    assert "painel:m0" in [a.id for a in juiz.amostrar(cands, hist, 4, AGORA)]


def test_rodada_grava_fotografia_e_o_sensor_abre_a_violacao(tmp_path):
    ctx = sensores.Ctx(dados=tmp_path, vault=tmp_path / "vault", hermes=tmp_path / "h", api=lambda r: {}, agora=AGORA)
    casos = tmp_path / "vault" / "casos"
    casos.mkdir(parents=True)
    (casos / "caso-y.md").write_text("---\ntipo: caso\ngrau: alto\nstatus: aberto\n---\nAchado sintético.\n", encoding="utf-8")
    notas = {c: 4 for c in regras.rubricas()} | {"inocente": 1}
    r = juiz.rodar(ctx, 3, pensar=_pensar_duble(_resposta(notas), []))
    assert r["julgadas_nesta_rodada"] == 1 and r["reprovadas"] == ["vault:caso-y"]
    vio = sensores.sensor_juiz_qualidade(ctx)
    assert [x["regra"] for x in vio] == ["SUB-03"] and vio[0]["sistema"] == "vault"
    r2 = juiz.rodar(ctx, 3, pensar=_pensar_duble(_resposta(notas), []))      # idempotente: nada novo a julgar
    assert r2["julgadas_nesta_rodada"] == 0 and r2["vigentes"] == 1


def test_prompt_traz_rubrica_ancoras_e_formato():
    p = juiz.montar_prompt(_afirmacao(), ["PAD-08 exemplo"])
    for c in juiz.criterios_de("vault"):
        assert f"[{c}]" in p and regras.rubricas()[c]["pergunta"] in p
    assert "clareza" not in juiz.criterios_de("vault") and "acabamento" not in juiz.criterios_de("painel")   # só onde a regra vale
    assert "[acabamento]" not in juiz.montar_prompt(_afirmacao(sistema="painel"), [])
    assert "exemplo RUIM" in p and "ESCALAR AO DONO" in p and '"notas"' in p and "PAD-08 exemplo" in p
