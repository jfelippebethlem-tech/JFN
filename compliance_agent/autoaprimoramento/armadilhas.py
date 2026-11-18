# -*- coding: utf-8 -*-
"""armadilhas — a taxonomia do que ENGANA a perícia de execução, medida na conferência na fonte primária.

Cada armadilha tem: `porque` (regex sobre o motivo do descarte escrito por quem leu a fonte — classifica o ledger),
`licao` (o texto candidato a entrar no prompt) e, quando existe forma segura, `indicio` (regex sobre o indício do
laudo FRACO — é o que o filtro determinístico usa antes de a fonte ser lida).

As sementes vêm da conferência de 18/11/2026 (regra 9 do prompt, escrita à mão naquele dia). A taxonomia cresce por
`candidatas()`: descartes que nenhuma armadilha explica, agrupados por termos recorrentes em processos distintos — a
proposta vai para candidatos/ e só vira armadilha ativa pelo portão (portao.py). A ORDEM importa: a primeira que casa
classifica (das mais específicas para as mais gerais)."""
from __future__ import annotations

import re
import unicodedata
from collections import Counter

NAO_CLASSIFICADA = "nao_classificada"

# (id, nome, regex do porquê, regex do indício fraco | None, lição)
_SEMENTES = [
    ("ob_devolvida_reemitida", "OB devolvida e reemitida contada em dobro",
     r"devolvid|erro no pagamento|reemi[ts]|em dobro|contada duas", None,
     "OB com status de envio 'Erro no Pagamento' foi devolvida pelo banco e reemitida: não some as duas — só a "
     "reemitida é pagamento."),
    ("ob_existe_no_siafe", "'Ausência de OB' com OB contabilizada no SIAFE",
     r"20\d\dOB\d+|campo processo|filtro por processo|SIAFE: ?(20\d\d)?OB|OB (est[aá]|consta|contabilizad)|pag[oa] no SIAFE|"
     r"contabilizad[ao] no SIAFE",
     r"(aus[eê]ncia|falta|inexist[eê]ncia|sem|n[aã]o (h[aá]|consta|localizad\w+))\b[^.;]{0,60}(ordem(ns)? banc[aá]ri|\bOBs?\b|"
     r"comprovante de pagamento|comprova[çc][aã]o d[eo] pagamento)",
     "A OB vive no SIAFE e o campo 'processo' dela pode estar vazio (2021–2023 quase sempre): 'ausência de OB' só "
     "depois de procurar por NL, PD, credor e valor."),
    ("retencao_tributaria", "Retenção de tributo lida como diferença de valor",
     r"reten[çc]|IRRF|\bIR\b|1,2 ?%|\bISS\b|INSS|l[ií]quido|bruto", None,
     "OB = líquido. Bruto da NF menos retenções (IRRF de 1,2% a 4,8%, ISS, INSS) é pagamento regular: faça a conta "
     "antes de apontar divergência de valor."),
    ("data_futura", "Data de 2025/2026 lida como futura",
     r"futur|n[aã]o [eé] (data )?posterior|data (correta|v[aá]lida)|j[aá] (ocorreu|passou)",
     r"(data|emitid\w+|datad\w+|assinad\w+)[^.;]{0,50}(futur|posterior [aà] data atual|ainda n[aã]o ocorr)|"
     r"futur\w*[^.;]{0,40}(202[56])",
     "Hoje é depois de 2025: data de 2025 ou 2026 não é 'futura'. Compare com a data de captura do processo, não "
     "com a sua data de treino."),
    ("numero_confundido", "Nº SEI, NE ou cadastro lido como nº de NF/contrato",
     r"n[ºo°] ?SEI|n[uú]mero (do )?(processo|SEI|documento|cadastro)|protocolo|n[aã]o [eé] (o )?n[uú]mero d[ae] (NF|nota)|"
     r"[eé] (o )?n[ºo°] d[oe] (documento|cadastro|empenho|processo)", None,
     "Número de 8–9 dígitos junto ao título é o nº do documento SEI; 'AAAANE…' é nota de empenho. Não são número de "
     "NF nem de contrato — não aponte divergência entre eles."),
    ("ocr_digito", "Dígito trocado ou ilegível por OCR",
     r"\bOCR\b|d[ií]gito|ileg[ií]vel|artefato|\?\?\?", None,
     "Dígito trocado, '???' ou valor ilegível em peça escaneada é artefato de OCR: confira contra o quadro de "
     "apuração ou a NL antes de apontar diferença."),
    ("nf_cancelada_substituta", "NF cancelada com substituta regular",
     r"cancelad|substitu", None,
     "Documento 'CANCELADO' com termo de cancelamento e substituto nos autos é substituição regular."),
    ("doerj_ato_vizinho", "Ato vizinho na mesma página do DOERJ",
     r"DOERJ|di[aá]rio oficial|ato vizinho|outro ato|p[aá]gina inteira|publica[çc][aã]o (traz|cont[eé]m)", None,
     "A página do DOERJ juntada traz vários atos: só vale o que cita este processo ou este valor."),
    ("pesquisa_precos_alheia", "Pesquisa de preços citando contratos alheios",
     r"pesquisa de pre[çc]o|pre[çc]os? de refer[eê]ncia|contratos? de outr|outros? [oó]rg[aã]os?", None,
     "A pesquisa de preços cita contratos de outros órgãos e empresas como referência: não são divergência."),
    ("objeto_alucinado", "Objeto da ficha impreciso ou inventado",
     r"objeto[^.;]{0,60}(ficha|resumo|imprecis|errad|inventad|alucin)|(ficha|resumo)[^.;]{0,60}(imprecis|errad|inventad|"
     r"alucin|LLM)|afirmad\w+ sobre (o )?resumo", None,
     "O objeto do resumo pode estar errado: se contradiz a nota de empenho ou a NF, valem a NE e a NF."),
    ("licenca_anual", "Licença ou assinatura anual paga de uma vez",
     r"licen[çc]a|assinatura anual|anuidade|parcela [uú]nica|pag\w+ de uma (s[oó] )?vez", None,
     "Licença, assinatura ou seguro anual é pago de uma vez no início da vigência: não é pagamento antecipado "
     "irregular nem desproporção mensal."),
    ("tipo_processo_sem_execucao", "Cobrar atesto/OB de processo que não é de pagamento",
     r"processo [eé] (s[oó] |apenas )?de |processo pr[oó]prio|corre em (outro )?processo|n[aã]o [eé] processo de|"
     r"aditivo|licita[çc]|fase de contrata[çc]",
     None,
     "Processo de aditivo, licitação, fiscalização ou só de pagamento não tem de trazer contrato, TR, atesto e OB "
     "juntos: a peça que falta corre em processo próprio."),
    ("empenho_estimativo", "Empenho estimativo comparado com a liquidação",
     r"estimativ|empenho [eé] limite|limite de empenho|saldo de empenho", None,
     "Empenho é limite: liquidar menos que o empenhado é normal (o saldo é anulado ou reforçado)."),
    ("documento_existe_nos_autos", "'Ausência' de documento que está nos autos",
     r"os autos t[eê]m|consta\w* (d?os|n?os) autos|est[aá]\w* nos autos|\bdoc\.? ?\d{6,}|juntad\w+|presente\w* nos autos|"
     r"h[aá] (o|a|um|uma) [^.;]{0,40}(nos autos|\(doc)",
     None,
     "Antes de apontar 'ausência' de atesto, NF, medição ou contrato, procure na árvore inteira: a peça costuma "
     "estar sob outro título (ARM, ata de recebimento, anexo)."),
    ("ausencia_no_recorte", "Ausência no recorte capturado tratada como fato",
     r"recorte|n[aã]o capturad|captura|aus[eê]ncia\w*[^.;]{0,40}n[aã]o prova|n[aã]o prova inexist|INDISPON[IÍ]VEL",
     r"^\W*(ind[ií]cio a verificar:?\s*)?(aus[eê]ncia|falta|inexist[eê]ncia|n[aã]o (h[aá]|consta\w*|foi\w* (anexad|"
     r"apresentad|localizad|juntad|identificad)\w*))\b",
     "Documento que não está no recorte capturado é INDISPONÍVEL, não ausente: lacuna de captura não é indício "
     "material e não sustenta nota 7 ou mais."),
]

# ROTEIRO DA CONFERÊNCIA NA FONTE — o que o cruzamento dos casos CONFIRMADOS em 18/11/2026 ensinou a quem confere
# (notas em ~/vault/casos/). Não são armadilhas do modelo de volume: são passos que a conferência tem de cumprir
# antes de graduar um risco. Acompanha cada item da fila da fonte (`selecao.roteiro`).
ROTEIRO_DA_FONTE = [{"id": i, "passo": p} for i, p in (
    ("documento_reaproveitado", "Compare o corpo de diário de obra, atestado e relatório com os de outros processos do "
     "MESMO credor: texto idêntico com cabeçalho de outro contrato só aparece cruzando processos."),
    ("base_e_o_aditivo_vigente", "Desproporção de pagamento mede-se contra a parcela do aditivo vigente, não contra o "
     "valor original do contrato."),
    ("processo_de_continuacao", "Leia o processo de continuação antes de concluir inexecução: a prova da entrega pode "
     "estar nele, e o achado muda de natureza (inexecução × pagamento antecipado)."),
    ("inicio_retroativo", "Termo de início pode fixar início retroativo: compare a data de assinatura com a data de "
     "início que ele fixa."),
    ("cnpj_divergente", "CNPJ divergente entre contratante e contratado costuma ser erro de cópia: confira o cartão "
     "CNPJ e o credor no SIAFE antes de apontar."),
    ("contrato_antigo_na_nf", "Contrato antigo citado em NF: verifique a vigência e se há sucessor de mesmo valor antes "
     "de suspeitar de dupla cobrança."),
    ("controle_negativo_no_processo", "Use o controle negativo de dentro do processo: NF emitida antes e paga depois do "
     "evento delimita onde está a antecipação."),
    ("doerj_inteiro", "Leia o DOERJ por CNPJ e por número SEI antes de graduar: tomada de contas, segundo contrato e "
     "repetição do objeto aparecem ali."),
    ("sancao_vigente", "Sanção vigente não torna o pagamento ilegal por si: veja a data do contrato, a abrangência da "
     "sanção e o acórdão (quem foi punido e por quê)."),
    ("status_da_ob", "Status da OB: 'Enviado ao Banco' não é 'Processado e Pago' — cite o status ao lado do valor."),
    ("razao_liquido_bruto", "Razão líquido/bruto igual entre OBs liga OB sem objeto ao contrato provável: é indício "
     "para procurar, não prova."),
    ("iss_nao_retido", "NF com ISS retido pelo tomador: a OB deve ser bruto − INSS − IRRF − ISS; se sobra exatamente "
     "o ISS, ele não foi retido. Antes de apontar: o regime muda no tempo no mesmo fornecedor, PIS/COFINS/CSLL não se "
     "retêm por tomador estadual, e meça outros fornecedores do mesmo órgão."),
    ("relatorio_modelo_de_fiscalizacao", "Mesmo relatório de fiscalização (amostragem, datas, objeto) em vários "
     "pagamentos do mesmo fornecedor indica fiscalização não feita lote a lote: compare entre pagamentos."),
    ("procurar_na_contratacao", "Ausência no processo não é ausência no caso: o termo que falta no processo de "
     "pagamento pode estar no de contratação — procure nos dois."),
    ("nf_de_outro_municipio", "NF emitida em município diferente do local do serviço com 'tributação fora do "
     "município': verificar o domicílio fiscal do prestador."),
    ("quantidade_copiada", "Horas ou quantidades que não fecham: compare com o implícito nos meses vizinhos (OB ÷ "
     "tarifa) — costuma ser cópia do mês anterior, e o risco real pode estar em outra peça."),
    ("texto_vazio_no_laudo", "Laudo que diz 'texto capturado vazio' tem de ser conferido no arquivo antes de virar "
     "fato: a peça pode estar íntegra."),
    ("percentual_pago_bruto_liquido", "Antes de falar em percentual pago, reconcilie bruto e líquido: '98,8% pago' "
     "pode ser 100% liquidado menos 1,2% de IR."),
)]

SEMENTES = [{"id": i, "nome": n, "porque": re.compile(p, re.I), "indicio": re.compile(f, re.I) if f else None,
             "licao": li} for i, n, p, f, li in _SEMENTES]
POR_ID = {a["id"]: a for a in SEMENTES}


def classificar(texto: str, porque: str | None = None) -> str:
    """Indício descartado + motivo → id da armadilha (ou 'nao_classificada'). O motivo manda; o texto do indício só
    desempata as armadilhas que têm padrão de indício."""
    alvo = porque or ""
    for a in SEMENTES:
        if alvo and a["porque"].search(alvo):
            return a["id"]
    for a in SEMENTES:
        if a["indicio"] is not None and a["indicio"].search(texto or ""):
            return a["id"]
    return NAO_CLASSIFICADA


def do_indicio(texto: str, ativas: tuple[str, ...] | None = None) -> str | None:
    """Indício de laudo FRACO (sem a fonte lida) → armadilha provável, pelas que têm padrão de indício."""
    for a in SEMENTES:
        if a["indicio"] is not None and (ativas is None or a["id"] in ativas) and a["indicio"].search(texto or ""):
            return a["id"]
    return None


_PARADAS = set("a o e de da do das dos em no na nos nas um uma para por com sem que se ao aos as os é foi são não mais "
               "como ou sobre entre pelo pela este esta esse essa isso já há ser tem têm".split())


def _termos(s: str) -> list[str]:
    s = unicodedata.normalize("NFKD", (s or "").lower()).encode("ascii", "ignore").decode()
    return [t for t in re.findall(r"[a-z]{4,}", s) if t not in _PARADAS]


def candidatas(descartes: list[dict], minimo: int = 3) -> list[dict]:
    """Descartes 'nao_classificada' → pares de termos que se repetem em pelo menos `minimo` PROCESSOS distintos.
    É a taxonomia crescendo: cada proposta traz os exemplos; nome, regex e lição são escritos em candidatos/ e
    passam pelo portão como qualquer mudança."""
    onde: dict[tuple[str, str], set] = {}
    exemplos: dict[tuple[str, str], list] = {}
    for d in descartes:
        if d.get("armadilha") != NAO_CLASSIFICADA:
            continue
        ts = sorted(set(_termos(d.get("porque") or "")))
        for i, a in enumerate(ts):
            for b in ts[i + 1:]:
                onde.setdefault((a, b), set()).add(d.get("numero_sei"))
                exemplos.setdefault((a, b), []).append(d)
    cont = Counter({k: len(v) for k, v in onde.items() if len(v) >= minimo})
    out, cobertos = [], set()
    for (a, b), n in cont.most_common():
        procs = onde[(a, b)]
        if procs <= cobertos:                         # mesma massa de processos já proposta por outro par
            continue
        cobertos |= procs
        out.append({"termos": [a, b], "processos": n, "exemplos": [e["porque"][:240] for e in exemplos[(a, b)][:3]]})
    return out
