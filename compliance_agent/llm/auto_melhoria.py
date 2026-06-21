#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Loop de AUTO-MELHORIA do Hermes (meta-cognição).

Diferente de `refletir_com_hermes` (que aprende sobre os DADOS), aqui o Hermes critica os
PRÓPRIOS outputs e MÉTODO contra a verdade (veredito dos casos) e gera **auto-correções**
acionáveis — categoria de memória `metodo` — que são reinjetadas no prompt (`contexto_para_prompt`
inclui `metodo`), fechando o loop: erro pego → regra que o previne → aplicada nas próximas análises.

Rodar: python tools/hermes_auto_melhoria.py {seed|run}
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path

REPO = Path("/home/ubuntu/JFN"); sys.path.insert(0, str(REPO))

# Auto-correções FUNDACIONAIS — lições de método já pagas com erro real (semeadas idempotentemente).
METODOS_FUNDACIONAIS = [
    ("primario-sobre-derivado",
     "Documento de parte interessada (ex.: relatório contábil do próprio órgão / ASSCONT) é ALEGAÇÃO a testar, "
     "nunca prova final. Refutar/confirmar com fonte primária (SIAFE, registro de reajustes, NF). "
     "Por quê: a ASSCONT superdimensionou um saldo de R$ 56k com erro aritmético + crédito-fantasma."),
    ("bruto-vs-liquido",
     "Pagamento líquido (OB) ≠ valor bruto da NF. Retenção (~9% INSS+IRRF) NÃO é glosa. Nunca tratar a "
     "diferença bruto×líquido como crédito/débito. Por quê: gerou crédito-fantasma de ~R$ 21k."),
    ("reajuste-componente-nao-flat",
     "Reajuste de contrato de mão-de-obra é repactuação COMPONENTE-A-COMPONENTE (IN 05/2017: CCT na "
     "mão-de-obra + IPCA nos insumos), não % flat sobre o total. O índice CCT (ex.: 9,91%) incide só na "
     "mão-de-obra → efetivo na tarifa cheia é menor (≈8,7%). Validar por % flat dá falso desvio."),
    ("empenho-liquidacao-ob",
     "Empenho ≠ Liquidação ≠ OB. Só a Ordem Bancária é pagamento. Nunca citar empenho como total pago."),
    ("duplicidade-por-competencia",
     "Duplicidade de contrato contínuo checa-se por COMPETÊNCIA, não por valor; split = mesmo RE; valores "
     "iguais NÃO provam duplicidade (tarifa flat); só a NF fecha. Contar meses do contrato vs nº de OBs."),
    ("sei-busca-por-interessado",
     "Para enumerar processos de um fornecedor no SEI, buscar por INTERESSADO; CNPJ+full-text é largo demais "
     "(pega quem só MENCIONA o CNPJ). Por quê: uma busca por CNPJ trouxe a Mobiliza como se fosse a MGS."),
    ("verificar-contagem-antes-de-relatar",
     "Antes de relatar totais do SIAFE, conferir a CONTAGEM esperada (ex.: 55 OBs ITERJ×MGS); a base perde "
     "linhas — reingerir do cache se vier abaixo do esperado. Por quê: um laudo quase saiu com 35 OBs."),
]


def _parse_auto_correcoes(raw: str) -> list[dict]:
    """Extrai as auto-correções do output do LLM, tolerante a JSON malformado (LLM erra vírgula/aspas).
    1) tenta json.loads do bloco; 2) fallback: regex campo-a-campo por objeto."""
    raw = re.sub(r"^```(?:json)?|```$", "", (raw or "").strip(), flags=re.M).strip()
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group()).get("auto_correcoes", [])
        except Exception:
            pass
    # fallback robusto: cada objeto {chave..regra..porque}
    out = []
    for obj in re.findall(r"\{[^{}]*\}", raw, re.DOTALL):
        g = lambda f: (re.search(rf'"{f}"\s*:\s*"((?:[^"\\]|\\.)*)"', obj, re.DOTALL) or [None, ""])[1]
        chave, regra = g("chave"), g("regra")
        if chave and regra:
            out.append({"chave": chave, "regra": regra.replace('\\"', '"'), "porque": g("porque")})
    return out


def seed_metodos(session=None) -> int:
    from compliance_agent.llm.memoria import aprender
    n = 0
    for chave, regra in METODOS_FUNDACIONAIS:
        aprender("metodo", chave, regra, fonte="auto_melhoria_seed", delta_confianca=0.2, session=session)
        n += 1
    return n


def _verdicts_dos_casos(max_casos: int = 12) -> str:
    """Verdade de campo: status/veredito das notas de caso do vault (ground truth p/ a crítica)."""
    base = Path("/home/ubuntu/vault/casos")
    if not base.exists():
        return ""
    linhas = []
    for md in sorted(base.glob("*.md"))[:max_casos]:
        t = md.read_text(encoding="utf-8", errors="ignore")
        rating = next((l.strip() for l in t.splitlines() if re.search(r"rating:|status:|VEREDITO", l, re.I)), "")
        linhas.append(f"- {md.stem}: {rating[:160]}")
    return "VEREDITOS DE CASOS (verdade de campo):\n" + "\n".join(linhas)


async def auto_melhorar(session=None) -> dict:
    """Passe de meta-cognição: confronta hipóteses/recomendações do Hermes com os veredittos reais,
    extrai erros de MÉTODO recorrentes e grava auto-correções (categoria `metodo`)."""
    from compliance_agent.llm.memoria import lembrar, aprender, _session
    from compliance_agent.llm.hermes_agent import _hermes

    own = session is None
    s = _session(session)
    try:
        hipoteses = lembrar("hipotese", session=s)[:10]
        esquemas = lembrar("esquema", session=s)[:6]
        metodos_atuais = lembrar("metodo", session=s)[:20]
        verdicts = _verdicts_dos_casos()

        track = "\n".join(f"- HIPÓTESE: {h['valor'][:200]}" for h in hipoteses) or "(sem hipóteses registradas)"
        esq = "\n".join(f"- ESQUEMA: {e['valor'][:200]}" for e in esquemas)
        regras = "\n".join(f"- [{m['chave']}] {m['valor'][:160]}" for m in metodos_atuais) or "(nenhuma ainda)"

        system = (
            "Você é o supervisor metacognitivo do Hermes (agente auditor do Estado do RJ). NÃO analise os "
            "casos em si — analise o MÉTODO do Hermes: onde ele errou, superestimou, confiou em fonte "
            "derivada, ou repetiu vícios. Compare as hipóteses/esquemas que ELE produziu com os VEREDITOS "
            "reais. Produza AUTO-CORREÇÕES de método: regras curtas, imperativas, com o porquê. NÃO repita "
            "regras que já existem. Responda SÓ JSON: "
            '{"auto_correcoes":[{"chave":"id-curto","regra":"texto imperativo","porque":"erro que previne"}]}'
        )
        prompt = (
            f"REGRAS DE MÉTODO JÁ VIGENTES (não repetir):\n{regras}\n\n"
            f"OUTPUTS DO PRÓPRIO HERMES:\n{track}\n{esq}\n\n"
            f"{verdicts}\n\n"
            "Quais erros de MÉTODO o Hermes deve corrigir para a próxima auditoria? Máximo 5. "
            "Se o método está sólido e não há correção nova honesta, retorne lista vazia."
        )
        novas = []
        try:
            raw = await _hermes(system, prompt, max_tokens=1500)
            itens = _parse_auto_correcoes(raw)
            for ac in itens[:5]:
                chave = (ac.get("chave") or "").strip()[:120]
                regra = (ac.get("regra") or "").strip()
                porque = (ac.get("porque") or "").strip()
                if chave and regra:
                    aprender("metodo", chave, f"{regra} (Por quê: {porque})" if porque else regra,
                             fonte="auto_melhoria", delta_confianca=0.15, session=s)
                    novas.append(chave)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "erro": str(e)[:150], "novas": novas}
        return {"ok": True, "novas_auto_correcoes": novas, "total_metodos": len(lembrar("metodo", session=s))}
    finally:
        if own:
            s.close()


if __name__ == "__main__":
    import asyncio
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "seed":
        print(f"{seed_metodos()} métodos fundacionais semeados.")
    else:
        seed_metodos()  # garante a base
        print(json.dumps(asyncio.run(auto_melhorar()), ensure_ascii=False, indent=1))
