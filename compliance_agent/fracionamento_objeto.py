# -*- coding: utf-8 -*-
"""FRACIONAMENTO DE DESPESA pelo critério da LEI — o mesmo OBJETO picado em várias contratações.

Pedido do dono (19/11/2026): "não se trata da mesma empresa e sim do mesmo objeto ser fracionado".

O CONCEITO (Lei 14.133/2021, art. 75, §1º; Lei 8.666/1993, art. 23, §§2º e 5º, e art. 24, I/II):
para aferir o limite da dispensa por valor soma-se o que a MESMA UNIDADE GESTORA despendeu no EXERCÍCIO
com objetos de MESMA NATUREZA (mesmo ramo de atividade) — seja qual for o fornecedor. Fracionamento é a
mesma necessidade dividida em VÁRIAS CONTRATAÇÕES DISTINTAS (processos/dispensas) que, somadas, passam
do teto que exigiria licitação. Fornecedores podem ser iguais ou diferentes; o fornecedor NÃO entra no
critério — no máximo gradua o indício (TCU: Ac. 3.550/2008-1ª Câm.; 706/2007-1ª Câm.; 2.157/2011-Plen.).

NÃO É fracionamento: PARCELAMENTO em itens/lotes num procedimento da modalidade do todo (Lei 14.133 arts.
40 §§2º-3º e 47; Súmula TCU 247); objetos de naturezas distintas; emergência (art. 75, VIII — régua
própria em `fracionamento_emergencia.py`); credenciamento; inscrição/anuidade.

Fonte desta tela: `output/sweep_fracionamento_tcerj.json`, gerado por `tools/sweep_fracionamento_tcerj.py`
(detector P4 em lote sobre `compras_diretas_tcerj`), recalculado pelo despachante (`config/propagacao.yaml`,
derivado `fracionamento_objeto`). Pagamento = OB do SIAFE ligada pelo nº do processo (`_ob_paga`); sem OB
ligável → INDISPONÍVEL, nunca zero.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

SAIDA = Path(__file__).resolve().parent.parent / "output" / "sweep_fracionamento_tcerj.json"

RAMO_ROTULO = {
    "utilidade_publica": "Utilidade pública (água, energia, telefonia, internet)",
    "combustivel": "Combustíveis e lubrificantes",
    "veiculos": "Veículos — peças, pneus, manutenção, locação",
    "manutencao_equipamentos": "Manutenção e conserto de equipamentos",
    "saude_medicamentos": "Medicamentos e material hospitalar",
    "laboratorio": "Material e equipamento de laboratório",
    "hospedagem": "Hospedagem",
    "alimentacao": "Alimentação (coffee break, refeições, gêneros)",
    "limpeza_higiene": "Limpeza e higiene",
    "informatica": "Informática (equipamentos, licenças, suprimentos)",
    "expediente": "Material de expediente",
    "mobiliario": "Mobiliário",
    "uniforme_epi": "Uniformes e EPI",
    "vigilancia": "Vigilância e segurança patrimonial",
    "manutencao_predial": "Manutenção predial, reformas e obras",
    "grafica": "Serviços gráficos e impressos",
    "eventos": "Eventos (estrutura, som, espaço)",
    "transporte": "Transporte e passagens",
}

CONCEITO = (
    "Fracionamento é a MESMA necessidade — objetos de mesma natureza, do mesmo ramo de atividade — "
    "dividida em várias contratações distintas ao longo do exercício, para que cada parcela caiba na "
    "dispensa por valor. A lei manda somar, por unidade gestora e exercício financeiro, tudo o que foi "
    "contratado com objetos de mesma natureza (Lei 14.133/2021, art. 75, §1º). O fornecedor não entra no "
    "critério: as parcelas podem ir para empresas diferentes — é o caso mais comum.")

RESSALVA = (
    "Indício, não acusação. A soma acima do teto mostra que a despesa daquela natureza precisava de "
    "licitação; os autos dizem se havia necessidade imprevisível e superveniente, ata de registro de preços "
    "ou licitação regular para parte dela. Parcelamento em itens ou lotes dentro de uma licitação da "
    "modalidade do todo é dever (Súmula TCU 247), não fracionamento. Dispensa de emergência, credenciamento, "
    "inscrição e anuidade ficam fora da soma. Pagamento = OB do SIAFE ligada pelo número do processo; "
    "processo sem OB ligável aparece como INDISPONÍVEL, não como zero.")


def _grupo(a: dict) -> dict:
    v = a.get("valores") or {}
    soma = float(v.get("soma_cluster") or 0)
    teto = float(v.get("limite_dispensa_vigente") or 0)
    nat = a.get("natureza")
    por_ramo = a.get("criterio_natureza") == "ramo_de_atividade"
    return {
        "unidade": a.get("unidade"), "exercicio": a.get("exercicio"),
        "natureza": nat, "natureza_rotulo": RAMO_ROTULO.get(nat, nat) if nat else "Objeto de descrição semelhante",
        "criterio_natureza": a.get("criterio_natureza"),
        # ramo de atividade = critério legal; só similaridade de texto = conferir nos autos antes de graduar
        "grau": "indicio" if por_ramo else "a_conferir",
        "inciso": "I (obras e serviços de engenharia)" if v.get("tipo_objeto") == "obras" else "II (compras e demais serviços)",
        "n_contratacoes": int(v.get("n_dispensas_cluster") or 0),
        "n_fornecedores_distintos": a.get("n_fornecedores_distintos"),
        "fornecedores": a.get("fornecedores") or [],
        "soma": round(soma, 2), "teto": round(teto, 2),
        "excesso": round(soma - teto, 2), "vezes_o_teto": round(soma / teto, 2) if teto else None,
        "colados_no_teto": v.get("dispensas_sob_teto_80_100"),
        "max_mesmo_fornecedor": v.get("max_dispensas_mesmo_grupo_economico"),
        "ob_pago_total": a.get("ob_pago_total"),
        "ob_processos_ligados": a.get("ob_processos_ligados", 0),
        "processos_irmaos": a.get("processos_irmaos") or [],
        "contratacoes": a.get("contratacoes") or [],
        "estado": "PENDENTE",
    }


def fracionamento_por_objeto(caminho: Path | str | None = None, limite: int = 120) -> dict:
    """Grupos unidade × exercício × natureza cuja SOMA de dispensas por valor passa do teto do ano."""
    p = Path(caminho) if caminho else SAIDA
    if not p.exists():
        return {"ok": False, "erro": "sweep de fracionamento ainda não gerado (output/sweep_fracionamento_tcerj.json) "
                                     "— INDISPONÍVEL, não zero", "grupos": [], "n": None}
    achados = json.loads(p.read_text(encoding="utf-8"))
    # o núcleo legal é a SOMA acima do teto; os sinais acessórios do P4 (mesmo fornecedor, colado no
    # teto) sozinhos não definem fracionamento e ficam fora da lista
    grupos = [_grupo(a) for a in achados if a.get("soma_acima_do_teto")]
    grupos.sort(key=lambda g: (g["grau"] != "indicio", -g["excesso"]))
    lig = [c for g in grupos for c in g["contratacoes"]]
    return {
        "ok": True, "criterio": "objeto", "conceito": CONCEITO, "ressalva": RESSALVA,
        "explicacao": CONCEITO,
        "fundamento": "Lei 14.133/2021, art. 75, §1º, I e II (e §2º); Lei 8.666/1993, art. 23, §§2º e 5º, e art. 24, I/II; "
                      "Lei 13.303/2016, art. 29, I/II — medido contra o limite da 14.133 (conservador)",
        "fonte": "TCE-RJ — compras diretas (compras_diretas_tcerj) · OB: SIAFE (ob_orcamentaria_siafe, _ob_paga)",
        "gerado_em": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds"),
        "n": len(grupos),
        "n_indicio": sum(1 for g in grupos if g["grau"] == "indicio"),
        "n_a_conferir": sum(1 for g in grupos if g["grau"] == "a_conferir"),
        "n_multi_fornecedor": sum(1 for g in grupos if (g["n_fornecedores_distintos"] or 0) > 1),
        "soma_total": round(sum(g["soma"] for g in grupos), 2),
        "cobertura_ob": {"contratacoes": len(lig), "com_ob": sum(1 for c in lig if c.get("ob_pago") is not None)},
        "lacunas": [
            "Só dispensas registradas no TCE-RJ (2023+); a fuga de MODALIDADE (convites em série, Lei 8.666 art. "
            "23 §5º) não é medida — a base não traz os convites.",
            "Sem data por contratação: proximidade no tempo não entra na graduação.",
            "Natureza de despesa do SIAFE (ne_siafe) só tem o ELEMENTO (6 dígitos, ex.: 339030 material de "
            "consumo) e só 2025: largo demais para dizer 'mesma natureza' e sem modalidade — não serve de 2ª fonte.",
        ],
        "grupos": grupos[:max(1, int(limite))],
        "mostrados": min(len(grupos), max(1, int(limite))),
    }
