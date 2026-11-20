# -*- coding: utf-8 -*-
"""Fontes do juiz subjetivo que estavam CEGAS (medido em 20/11/2026: 160 candidatas, Yoda 0, nenhum produto).

1. Yoda no modo /cc (desde 15/11): o plugin `jfn-claude` manda a resposta do Claude Code direto pelo Bot API — ela
   não entra no `state.db` do Hermes. O juiz lê o transcript da sessão /cc e só aceita o texto cujo sha256 bate com
   o `sha_enviado`/`sha_resultado` do log do plugin (prova de que FOI entregue ao dono).
2. Produtos da casa (`reports/inteligencia_*`, `parecer_lex_*`, `dossie_*`): os entregáveis não eram julgados.

Nenhum teste chama o Claude de verdade; tudo em pasta temporária.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta

from compliance_agent.qualidade import juiz, sensores

AGORA = datetime(2026, 11, 20, 10, 0)
SID = "afca3691-83f3-45b9-8204-24c7949f9021"


def _sha(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def _ctx(tmp_path, monkeypatch):
    monkeypatch.setattr(juiz, "PASTA_CC", tmp_path / "projetos" / "-home-ubuntu-JFN")
    return sensores.Ctx(dados=tmp_path / "dados", vault=tmp_path / "vault", hermes=tmp_path / "h", repo=tmp_path / "repo",
                        api=lambda r: {}, agora=AGORA)


def _transcript(tmp_path, sid: str, textos: list[str]) -> None:
    pasta = tmp_path / "projetos" / "-home-ubuntu-JFN"
    pasta.mkdir(parents=True, exist_ok=True)
    linhas = [{"type": "user", "message": {"role": "user", "content": "pedido do dono"}}]
    for t in textos:
        linhas.append({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}, {"type": "text", "text": t}]}})
    (pasta / f"{sid}.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in linhas), encoding="utf-8")


def _log(tmp_path, itens: list[dict]) -> None:
    arq = tmp_path / "h" / "logs" / "jfn-claude.jsonl"
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text("\n".join(json.dumps(x) for x in itens), encoding="utf-8")


ENTREGUE = "A MGS Clean recebeu R$ 164.932.532,33 em OBs de 2021 a 2026; 🟡 indício de concentração a verificar."
SEM_NUMERO = "Achei a causa do defeito da foto: a ponte só copia o texto. Corrijo assim que você der o ok."
NAO_ENTREGUE = "Rascunho intermediário com R$ 9.999.999,99 que o dono nunca recebeu."


def test_yoda_le_a_resposta_entregue_pelo_cc(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    _transcript(tmp_path, SID, [NAO_ENTREGUE, ENTREGUE + "\n[[PRECISA_OK]]", SEM_NUMERO])
    _log(tmp_path, [
        {"origem": "modo_direto", "ok": True, "sessao_id": SID, "sha_resultado": _sha(ENTREGUE), "sha_enviado": _sha(ENTREGUE)},
        {"origem": "modo_direto", "ok": True, "sessao_id": SID, "sha_resultado": _sha(SEM_NUMERO)},
    ])
    ys = [a for a in juiz.candidatas(ctx) if a.sistema == "yoda"]
    assert len(ys) == 1, [a.texto[:80] for a in ys]                    # sem R$ nem grau não entra; não entregue não entra
    a = ys[0]
    assert "164.932.532,33" in a.texto and "PRECISA_OK" not in a.texto and "9.999.999,99" not in a.texto
    assert a.valor == 164_932_532.33 and a.publica is False and a.grupo == "yoda"
    assert a.id == f"yoda:{a.impressao}"                                 # id estável por impressão
    assert [x.id for x in juiz.candidatas(ctx) if x.sistema == "yoda"] == [a.id]


def test_yoda_cc_mascara_cpf_e_ignora_sessao_fora_do_modo_direto(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    com_cpf = "Sócio de CPF 111.444.777-35 recebeu R$ 1.000,00 da fornecedora."
    outra = "bbbbbbbb-83f3-45b9-8204-24c7949f9021"
    whats = "Secretário: a conta de R$ 2.000,00 vence amanhã 🔴."
    _transcript(tmp_path, SID, [com_cpf])
    _transcript(tmp_path, outra, [whats])
    _log(tmp_path, [
        {"origem": "modo_direto", "ok": True, "sessao_id": SID, "sha_resultado": _sha(com_cpf)},
        {"origem": "whatsapp", "ok": True, "sessao_id": outra, "sha_resultado": _sha(whats)},     # nada de WhatsApp
        {"origem": "modo_direto", "ok": True, "sessao_id": "../../etc/passwd", "sha_resultado": _sha(whats)},
    ])
    ys = [a for a in juiz.candidatas(ctx) if a.sistema == "yoda"]
    assert len(ys) == 1 and "111.444.777-35" not in ys[0].texto and "***.444.777-**" in ys[0].texto


def test_yoda_cc_sem_log_ou_sem_transcript_nao_quebra(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    assert juiz._respostas_cc(ctx) == []
    _log(tmp_path, [{"origem": "modo_direto", "ok": True, "sessao_id": SID, "sha_resultado": _sha(ENTREGUE)}, "lixo"])
    assert juiz._respostas_cc(ctx) == []


def _produto(pasta, nome: str, texto: str, idade_dias: float = 1.0) -> None:
    pasta.mkdir(parents=True, exist_ok=True)
    arq = pasta / nome
    arq.write_text(texto, encoding="utf-8")
    t = (AGORA - timedelta(days=idade_dias)).timestamp()
    os.utime(arq, (t, t))


RELATORIO = ("# RELATÓRIO DE INTELIGÊNCIA DE FORNECEDOR\n### ALFA LTDA (fictícia)\n\n## SUMÁRIO EXECUTIVO\n"
             "Total pago no período: R$ 2.500.000,00 em 40 OBs. Rating: 🟡 MÉDIO.\n" + "x" * 9000 + "\nFIM-DO-ARQUIVO")
PARECER = ("# PARECER JURÍDICO PRELIMINAR — ALFA LTDA\n**Grau de atenção:** 🔴 VERMELHO\n"
           "- Exposição: R$ 12.000.000,00\n- Sócio-administrador: CPF ***.444.777-**\n")


def test_produtos_entram_com_grupo_proprio_e_sem_o_que_nao_e_produto(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    rep = tmp_path / "repo" / "reports"
    _produto(rep, "inteligencia_alfa_ltda_2026-11-19.md", RELATORIO, 1)
    _produto(rep, "inteligencia_alfa_ltda_2026-11-10.md", RELATORIO.replace("2.500.000", "1.000.000"), 10)  # versão velha
    _produto(rep, "parecer_lex_alfa_ltda_2026-11-19.md", PARECER, 1)
    _produto(rep, "inteligencia_beta_ltda_2026-07-01.md", RELATORIO, 140)           # velho demais
    _produto(rep, "comissao_P12_rreo_2026_4B.html", "<p>R$ 1,00</p>", 1)             # fora do padrão
    _produto(rep, "notas_soltas_2026-11-19.md", "R$ 5,00", 1)                       # fora do padrão
    _produto(rep / "arquivo" / "2026-11", "inteligencia_gama_ltda_2026-11-19.md", RELATORIO, 1)  # subpasta não
    ps = {a.id: a for a in juiz.candidatas(ctx) if a.grupo == "produto"}
    assert set(ps) == {"produto:inteligencia_alfa_ltda", "produto:parecer_lex_alfa_ltda"}
    rel, lex = ps["produto:inteligencia_alfa_ltda"], ps["produto:parecer_lex_alfa_ltda"]
    assert rel.sistema == "relatorios" and lex.sistema == "lex"                    # sistemas que a rubrica conhece
    assert juiz.criterios_de(rel.sistema) and juiz.criterios_de(lex.sistema)
    assert "2.500.000,00" in rel.texto and "FIM-DO-ARQUIVO" not in rel.texto         # o mais novo; só o começo
    assert rel.valor == 2_500_000.0 and rel.grau == "🟡" and rel.publica is True and not rel.pessoa_fisica
    assert lex.grau == "🔴" and lex.valor == 12_000_000.0
    assert lex.publica is False and lex.pessoa_fisica is True                        # dado pessoal: só a assinatura


def test_produtos_respeitam_o_teto_de_n(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    rep = tmp_path / "repo" / "reports"
    for i in range(juiz.PRODUTO_N + 3):
        _produto(rep, f"inteligencia_emp{i}_ltda_2026-11-1{i % 10}.md", RELATORIO, 1 + i / 10)
    ps = juiz._de_produtos(ctx)
    assert len(ps) == juiz.PRODUTO_N
    assert "produto:inteligencia_emp0_ltda" in {a.id for a in ps}                     # os mais recentes por mtime


def test_amostra_da_vaga_ao_grupo_de_menor_risco():
    """Com 5 grupos e n=6 o teto por grupo (2) deixava o último grupo sem vaga: 2+2+2 enchia a amostra."""
    def af(i, grupo_id, sistema, valor):
        return juiz.Afirmacao(id=f"{grupo_id}{i}", sistema=sistema, rotulo="r", texto=f"{grupo_id}{i}", grau="🔴", valor=valor)
    cands = [af(i, "painel:m", "painel", 1e9) for i in range(3)] + [af(i, "painel:gestao:g", "painel", 1e8) for i in range(3)]
    cands += [af(i, "vault:c", "vault", 1e7) for i in range(3)] + [af(i, "yoda:y", "yoda", 1e3) for i in range(3)]
    cands += [af(i, "produto:p", "relatorios", 1e2) for i in range(3)]
    esc = juiz.amostrar(cands, {}, 6, AGORA)
    assert {a.grupo for a in esc} == {"painel", "painel:gestao", "vault", "yoda", "produto"}
    assert esc[0].id == "painel:m0"                                                   # risco continua mandando na ordem
