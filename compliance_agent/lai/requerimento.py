# -*- coding: utf-8 -*-
"""Texto do requerimento LAI — fundamentado, nominal, neutro (diligência, nunca acusação)."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[2]
_REQUERENTE_JSON = _RAIZ / "data" / "lai_requerente.json"

DESTINATARIOS = {
    "prefeitura": {
        "nome": "Controladoria Geral do Município do Rio de Janeiro — Serviço de Informação ao Cidadão (e-SIC PCRJ)",
        "canal": "https://carioca.rio/servicos/acesso-a-informacao/ (Carioca Digital → Acesso à Informação → Novo pedido)",
        "base": ("art. 5º, XXXIII, e art. 37, caput, da Constituição Federal; arts. 7º, 8º, 10 e 11 da Lei Federal "
                 "12.527/2011 (LAI); Lei Municipal 5.394/2012 e Decreto Rio 35.606/2012"),
        "prazo_dias": 20,
    },
    "estado": {
        "nome": "Serviço de Informação ao Cidadão do Estado do Rio de Janeiro (e-SIC RJ)",
        "canal": "https://www.rj.gov.br/transparencia (Acesso à Informação → e-SIC) ou o SIC do órgão detentor",
        "base": ("art. 5º, XXXIII, e art. 37, caput, da Constituição Federal; arts. 7º, 8º, 10 e 11 da Lei Federal "
                 "12.527/2011 (LAI); Decreto Estadual 46.475/2018"),
        "prazo_dias": 20,
    },
}

_PEDIDO_PADRAO = [
    "íntegra do processo administrativo, em formato digital pesquisável (PDF/A ou nativo do SEI), com todos os documentos, "
    "despachos, pareceres, notas técnicas, e-mails juntados, anexos e o histórico de andamentos e assinaturas",
    "Estudo Técnico Preliminar, Termo de Referência/Projeto Básico e pesquisa/planilha de preços que embasaram a contratação",
    "justificativa da escolha do fornecedor e do preço, ato de ratificação/homologação e o parecer jurídico correspondente",
    "contrato e todos os termos aditivos, apostilamentos e a planilha de custos vigente",
    "atos de designação dos gestores e fiscais e os relatórios de fiscalização/medição que amparam as liquidações e pagamentos",
]


def requerente() -> dict:
    """Dados do requerente: data/lai_requerente.json (gitignored) com fallback em variáveis LAI_*."""
    base = {"nome": "", "cargo": "", "cpf": "", "email": "", "telefone": "", "endereco": ""}
    if _REQUERENTE_JSON.exists():
        try:
            base.update({k: str(v or "") for k, v in json.loads(_REQUERENTE_JSON.read_text(encoding="utf-8")).items()})
        except (OSError, ValueError):
            pass
    for k in list(base):
        base[k] = base[k] or os.environ.get(f"LAI_{k.upper()}", "")
    base["completo"] = bool(base["nome"] and base["cpf"] and base["email"])
    return base


def _moeda(v) -> str:
    try:
        return "R$ " + f"{float(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "R$ —"


def _bloco_contratos(contratos: list[dict]) -> list[str]:
    linhas = []
    for c in contratos[:15]:
        linhas.append(
            f"- Instrumento nº {c.get('numero_instrumento') or c.get('contrato')} ({c.get('ano')}), {c.get('orgao') or 'órgão n/d'}; "
            f"processo {c.get('processo') or 'n/d'}; {c.get('forma_contratacao') or 'forma n/d'}; objeto: "
            f"{(c.get('objeto') or '')[:160]}; valor atualizado {_moeda(c.get('valor_atualizado'))}; "
            f"pago {_moeda(c.get('total_pago'))}; vigência {c.get('vigencia_ini') or '?'} a {c.get('vigencia_fim') or '?'}"
            + (f"; anexos publicados em {c['url_ccon']}" if c.get("url_ccon") else ""))
    return linhas


def _bloco_documentos(proc: dict) -> list[str]:
    """Nomeia os documentos que o SEI mostra mas não abre — o pedido vira específico, não genérico."""
    linhas = []
    vistos = proc.get("documentos_vistos") or []
    if vistos:
        linhas.append(f"  Documentos identificados na pesquisa pública do SEI (processo {proc['numero']}), cuja íntegra se requer:")
        for d in vistos[:60]:
            linhas.append(f"    · documento SEI nº {d['prot']} — {(d.get('titulo') or '').split(' nº')[0][:90]} "
                          f"({d.get('unidade') or 'unidade n/d'}, {d.get('data') or 'data n/d'})")
        if len(vistos) > 60:
            linhas.append(f"    · … e mais {len(vistos) - 60} documentos listados na pesquisa pública")
    cp = proc.get("campos") or {}
    if cp:
        partes = []
        if cp.get("contrato_numero"):
            partes.append("contrato(s) nº " + ", ".join(cp["contrato_numero"][:4]))
        if cp.get("termo_aditivo"):
            partes.append("aditivo(s) " + ", ".join(cp["termo_aditivo"][:4]))
        if cp.get("fundamento"):
            partes.append("fundamento declarado: " + "; ".join(cp["fundamento"][:3]))
        if cp.get("prazo_vigencia"):
            partes.append("vigência: " + "; ".join(cp["prazo_vigencia"][:3]))
        if cp.get("pregao"):
            partes.append("certame de origem: pregão " + ", ".join(cp["pregao"][:2]))
        if cp.get("base_preco"):
            partes.append("base de preço declarada: " + ", ".join(cp["base_preco"][:4]))
        if partes:
            linhas.append("  O que os documentos já obtidos declaram (leitura estruturada): " + " · ".join(partes) + ".")
    ass = [a for a in (proc.get("assinantes") or []) if a.get("nome")]
    if ass:
        linhas.append("  Servidores que assinaram documentos no processo (matrícula → folha municipal): "
                      + "; ".join(f"{a['nome']} (mat. {a['matricula']}, {a.get('sigla_ua') or a.get('orgao') or ''}, {a['n']} assinatura(s))"
                                  for a in ass[:10]) + (" …" if len(ass) > 10 else ""))
    obtidos = proc.get("documentos_obtidos") or []
    if obtidos:
        linhas.append(f"  Já obtidos por fonte pública (não precisam ser reenviados): {len(obtidos)} documento(s) — "
                      + ", ".join(str(o.get('seq')) for o in obtidos[:12]) + (" …" if len(obtidos) > 12 else ""))
    return linhas


def montar(fatos: dict, esfera: str | None = None, motivo: str | None = None) -> dict:
    """→ {titulo, destinatario, texto, itens_pedido, base_legal, prazo_dias, avisos[]}."""
    esfera = esfera or fatos.get("esfera_sugerida") or "prefeitura"
    dest = DESTINATARIOS.get(esfera, DESTINATARIOS["prefeitura"])
    req = requerente()
    avisos = []
    if not req["completo"]:
        avisos.append("requerente incompleto: preencha data/lai_requerente.json (nome, cpf, email) antes de protocolar")
    hoje = datetime.now().strftime("%d/%m/%Y")
    procs = fatos.get("processos") or []
    contratos = fatos.get("contratos") or []
    forn = "; ".join(f"{n} (CNPJ {d})" if d else n for d, n in (fatos.get("fornecedores") or [])[:6]) or "não identificado na base"
    alvo_txt = fatos.get("alvo")

    L = []
    L.append("REQUERIMENTO DE ACESSO À INFORMAÇÃO (Lei 12.527/2011)")
    L.append("")
    L.append(f"AO: {dest['nome']}")
    L.append(f"Canal de protocolo: {dest['canal']}")
    L.append("")
    L.append("REQUERENTE:")
    L.append(f"{req['nome'] or '«nome»'}, {req['cargo'] or '«cargo/mandato»'}, CPF {req['cpf'] or '«cpf»'}, "
             f"e-mail {req['email'] or '«email»'}{', tel. ' + req['telefone'] if req['telefone'] else ''}"
             f"{', ' + req['endereco'] if req['endereco'] else ''}.")
    L.append("")
    L.append("OBJETO:")
    L.append(f"Acesso a informações e documentos referentes a: {alvo_txt}. Fornecedor(es) envolvido(s): {forn}.")
    if procs:
        L.append("Processos administrativos: " + "; ".join(p["numero"] for p in procs) + ".")
    if contratos:
        L.append("Instrumentos contratuais identificados no ContasRio (CGM):")
        L.extend(_bloco_contratos(contratos))
    L.append("")
    L.append("FUNDAMENTO:")
    L.append(f"Com fundamento no {dest['base']}, e no dever de fiscalização inerente ao mandato parlamentar "
             "(CF, arts. 70 e 71; Constituição do Estado do Rio de Janeiro, art. 99), requer-se o acesso abaixo. "
             "A informação pedida é de interesse público e não se enquadra nas hipóteses de sigilo dos arts. 23 e 31 da LAI; "
             "havendo trecho sigiloso, requer-se a entrega da parte não sigilosa (art. 7º, §2º) com a indicação do fundamento "
             "legal da restrição (art. 14).")
    if motivo:
        L.append(f"Contexto do pedido: {motivo}")
    L.append("")
    L.append("PEDIDO:")
    itens = []
    for p in procs:
        itens.append(f"Processo {p['numero']}: " + _PEDIDO_PADRAO[0] + ".")
        itens.extend(_bloco_documentos(p))
    if not procs:
        itens.append(_PEDIDO_PADRAO[0].capitalize() + f" relativo a: {alvo_txt}.")
    for txt in _PEDIDO_PADRAO[1:]:
        itens.append(txt[0].upper() + txt[1:] + ".")
    if fatos.get("fiscais"):
        itens.append("Atos de designação e relatórios dos fiscais nomeados: " +
                     "; ".join(sorted({f['fiscal_nome'] for f in fatos['fiscais']})[:12]) + ".")
    n = 0
    for it in itens:
        if it.startswith("  "):
            L.append(it)
        else:
            n += 1
            L.append(f"{n}. {it}")
    L.append("")
    L.append("FORMA E PRAZO:")
    L.append(f"Requer-se a entrega em meio digital (e-mail do requerente ou link no e-SIC), em formato pesquisável, no prazo "
             f"de {dest['prazo_dias']} dias (art. 11, §1º, LAI), prorrogável por 10 dias mediante justificativa (art. 11, §2º). "
             "Caso a informação já esteja disponível em portal público, requer-se a indicação precisa do endereço eletrônico "
             "(art. 11, §6º).")
    L.append("")
    L.append("Ressalva: este pedido tem natureza de diligência e fiscalização; não se afirma irregularidade — vigora a presunção "
             "de legitimidade dos atos administrativos, e a caracterização de qualquer ilícito compete aos órgãos de controle "
             "após o contraditório.")
    L.append("")
    L.append(f"Rio de Janeiro, {hoje}.")
    L.append("")
    L.append(f"{req['nome'] or '«nome»'}")
    L.append(f"{req['cargo'] or '«cargo/mandato»'}")
    texto = "\n".join(L)
    return {"titulo": L[0], "esfera": esfera, "destinatario": dest["nome"], "canal": dest["canal"],
            "base_legal": dest["base"], "prazo_dias": dest["prazo_dias"], "texto": texto,
            "itens_pedido": n, "avisos": avisos}
