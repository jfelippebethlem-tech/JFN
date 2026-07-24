# -*- coding: utf-8 -*-
"""NF-e — a nota que lastreia o pagamento foi CANCELADA? foi emitida em CONTINGÊNCIA? (plano #4, item 1.3)

Pergunta do dono (2026-07-24): "dá pra saber?" — **dá**. A CHAVE DE ACESSO (44 dígitos) impressa no DANFE e
citada no processo é auto-descritiva; dela saem, SEM REDE:

    cUF(2) AAMM(4) CNPJ(14) mod(2) série(3) nNF(9) tpEmis(1) cNF(8) cDV(1)

  • **tpEmis** (posição 35) revela CONTINGÊNCIA na hora — emitir em contingência é lícito, mas exige
    autorização posterior; NF em contingência lastreando pagamento é ponto de verificação clássico.
  • **cDV** (mod 11) valida a chave — é o que separa uma chave real de um número de 44 dígitos qualquer
    (protocolo, código de barras) e evita falso positivo na varredura de texto.

CANCELAMENTO/DENEGAÇÃO **não** está na chave: exige consulta à SEFAZ. Três caminhos, todos com custo ou
credencial — **decisão pendente do dono** (§4.1 "nunca assumir free tier"):
    (a) webservice `NfeConsultaProtocolo` — exige certificado digital A1 (custo + guarda da chave privada);
    (b) portal público nfe.fazenda.gov.br / portal estadual — sem certificado, mas com captcha;
    (c) agregador pago por consulta.
Por isso `situacao()` recebe a consulta INJETADA (`consultar`). Sem ela o veredito é **`nao_verificada` /
`a_verificar`** — NUNCA "autorizada" por omissão: ausência de verificação ≠ regularidade.

HONESTIDADE: indício ≠ acusação; contingência é lícita (é sinal a verificar, não vício); só a NF cancelada
ou denegada lastreando **OB paga** (§2: só a Ordem Bancária é "pago") é vermelho forte.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# ───────────────────────────── estrutura da chave ─────────────────────────────
_POS = {"uf": (0, 2), "aamm": (2, 6), "cnpj_emitente": (6, 20), "modelo": (20, 22), "serie": (22, 25),
        "numero": (25, 34), "tp_emissao": (34, 35), "codigo": (35, 43), "dv": (43, 44)}
_UF = {"11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO", "21": "MA",
       "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL", "28": "SE", "29": "BA",
       "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR", "42": "SC", "43": "RS", "50": "MS",
       "51": "MT", "52": "GO", "53": "DF"}
# tpEmis — tabela oficial (Manual de Orientação do Contribuinte / NT). 1 = normal; o resto é contingência.
_TP_EMISSAO = {
    "1": ("Emissão normal", False),
    "2": ("Contingência FS-IA (formulário de segurança)", True),
    "3": ("Contingência SCAN (desativada desde 2014)", True),
    "4": ("Contingência EPEC (Evento Prévio de Emissão em Contingência)", True),
    "5": ("Contingência FS-DA (formulário de segurança p/ DANFE)", True),
    "6": ("Contingência SVC-AN (SEFAZ Virtual de Contingência — Ambiente Nacional)", True),
    "7": ("Contingência SVC-RS (SEFAZ Virtual de Contingência — Rio Grande do Sul)", True),
    "9": ("Contingência off-line da NFC-e", True),
}
# situações da consulta à SEFAZ → grau. 'autorizada' é a única que tranquiliza.
_SITUACAO_GRAU = {"autorizada": "verde", "cancelada": "vermelho", "denegada": "vermelho",
                  "inutilizada": "vermelho", "nao_encontrada": "amarelo"}
# candidata a chave: 44 dígitos, tolerando separadores (o DANFE imprime em grupos de 4)
_RE_CANDIDATA = re.compile(r"(?<!\d)(\d[\s.\-]?){43}\d(?!\d)")


def digito_verificador(base43: str) -> int:
    """DV da chave (módulo 11, pesos 2..9 cíclicos da direita para a esquerda). Resto 0 ou 1 ⇒ DV 0."""
    pesos = (2, 3, 4, 5, 6, 7, 8, 9)
    soma = sum(int(c) * pesos[i % 8] for i, c in enumerate(reversed(base43)))
    dv = 11 - (soma % 11)
    return 0 if dv >= 10 else dv


def chave_valida(chave: str) -> bool:
    """A chave tem 44 dígitos e o DV fecha? É o filtro que separa chave real de número qualquer."""
    c = re.sub(r"\D", "", chave or "")
    return len(c) == 44 and digito_verificador(c[:43]) == int(c[43])


def extrair_chaves(texto: str) -> list[str]:
    """Todas as chaves de acesso VÁLIDAS no texto (ordem de aparição, sem repetir). Só entra o que passa
    no DV — anti-falso-positivo contra protocolos/códigos de barras de 44 dígitos."""
    achadas: list[str] = []
    for m in _RE_CANDIDATA.finditer(texto or ""):
        c = re.sub(r"\D", "", m.group(0))
        if len(c) == 44 and chave_valida(c) and c not in achadas:
            achadas.append(c)
    return achadas


def decompor(chave: str) -> dict:
    """Quebra a chave nos seus campos (offline). Retorna {} se a chave não for válida."""
    c = re.sub(r"\D", "", chave or "")
    if not chave_valida(c):
        return {}
    d = {k: c[a:b] for k, (a, b) in _POS.items()}
    d["uf_nome"] = _UF.get(d["uf"], "?")
    d["chave"] = c
    return d


def tp_emissao(chave: str) -> dict:
    """CONTINGÊNCIA direto da chave — sem rede, sem custo, sem credencial (posição 35 = tpEmis)."""
    d = decompor(chave)
    if not d:
        return {"contingencia": False, "codigo": "", "descricao": "chave inválida",
                "fonte": "chave de acesso (offline)", "valida": False}
    desc, cont = _TP_EMISSAO.get(d["tp_emissao"], ("tipo de emissão desconhecido", False))
    return {"contingencia": cont, "codigo": d["tp_emissao"], "descricao": desc,
            "fonte": "chave de acesso (offline)", "valida": True}


async def situacao(chave: str, *, consultar=None) -> dict:
    """Situação da NF na SEFAZ (autorizada/cancelada/denegada/inutilizada). `consultar`: async(chave)->dict
    — INJETADO (webservice com certificado A1, portal com captcha ou agregador; decisão do dono).

    Sem consulta, ou se ela falhar: `verificado=False`, `situacao='nao_verificada'`, grau `a_verificar`.
    Nunca se afirma que a nota está regular só porque não se conseguiu perguntar."""
    pend = {"chave": re.sub(r"\D", "", chave or ""), "verificado": False, "situacao": "nao_verificada",
            "grau": "a_verificar",
            "acao": ("consultar a situação da NF-e na SEFAZ pela chave de acesso (webservice "
                     "NfeConsultaProtocolo com certificado A1, portal público ou agregador) — decisão de "
                     "custo/credencial pendente"),
            "ressalva": "ausência de verificação ≠ nota regular"}
    if consultar is None:
        return pend
    try:
        r = await consultar(chave)
    except Exception as e:  # noqa: BLE001 — rede/certificado/captcha: degrada honesto, não inventa
        logger.debug("situacao NF-e: consulta falhou (%s): %s", chave, e)
        return {**pend, "erro": str(e)[:120]}
    if not isinstance(r, dict) or not r.get("situacao"):
        return {**pend, "erro": "consulta sem resposta utilizável"}
    sit = str(r["situacao"]).strip().lower()
    return {**r, "chave": pend["chave"], "situacao": sit, "verificado": True,
            "grau": _SITUACAO_GRAU.get(sit, "amarelo"), "fonte": "SEFAZ (consulta por chave de acesso)"}


_ORDEM = {"verde": 0, "a_verificar": 1, "amarelo": 2, "vermelho": 3}


async def analisar_nfe(texto: str = "", *, consultar=None) -> dict:
    """Veredito RESOLVIDO sobre as NF-e que lastreiam o processo: acha as chaves, lê a contingência offline
    e (se houver consulta injetada) confere a situação na SEFAZ. Cruza com o §2: NF cancelada lastreando
    **Ordem Bancária** (dinheiro que SAIU) é vermelho forte; sem OB, o mesmo vício pesa menos."""
    from compliance_agent.execucao_sinais import estagio_despesa
    est = estagio_despesa(texto)
    chaves = extrair_chaves(texto)
    if not chaves:
        return {"grau": "a_verificar", "chaves": [], "notas": [], "sinais": [],
                "resumo": ("Não há chave de acesso de NF-e (44 dígitos) no texto lido — a situação da nota "
                           "na SEFAZ não pode ser verificada sobre esta peça."),
                "acao": ("localizar a chave de acesso no DANFE/nota anexada ao processo (ou capturar o "
                         "documento) e reavaliar"),
                "ressalva": "INDISPONÍVEL ≠ irregular; ausência de chave ≠ ausência de nota",
                "estagio_despesa": est["estagio"], "fonte": "nfe_verifica"}
    notas, sinais, grau = [], [], "verde"
    for c in chaves:
        d = decompor(c)
        tp = tp_emissao(c)
        st = await situacao(c, consultar=consultar)
        nota = {**d, "contingencia": tp["contingencia"], "tp_emissao_descricao": tp["descricao"],
                "situacao": st["situacao"], "verificado": st["verificado"], "grau_situacao": st["grau"]}
        if not st["verificado"]:
            nota["acao"] = st["acao"]
        notas.append(nota)
        if tp["contingencia"]:
            sinais.append(f"NF-e {d['numero']} (série {d['serie']}) emitida em CONTINGÊNCIA — "
                          f"{tp['descricao']}: verificar a autorização definitiva na SEFAZ. Lícito em "
                          "abstrato; é ponto de verificação, não vício.")
        if st["situacao"] in ("cancelada", "denegada", "inutilizada"):
            msg = (f"NF-e {d['numero']} consta {st['situacao'].upper()} na SEFAZ e lastreia despesa neste "
                   "processo.")
            if est["tem_ob"]:
                msg += (" Há ORDEM BANCÁRIA no processo — pagamento EFETIVO (§2: só a OB é 'pago') contra "
                        "nota sem validade: indício GRAVE, a confirmar.")
            else:
                msg += (" Não há Ordem Bancária no texto: a despesa aparenta não ter sido paga ainda "
                        "(empenho/liquidação ≠ pagamento) — corrigir antes do pagamento.")
            sinais.append(msg)
        for g in (st["grau"], "amarelo" if tp["contingencia"] else "verde"):
            if _ORDEM.get(g, 0) > _ORDEM.get(grau, 0):
                grau = g
    resumo = ("; ".join(sinais) if sinais else
              f"{len(chaves)} chave(s) de NF-e localizada(s), sem contingência e sem vício detectado "
              "no que foi possível verificar.")
    if any(not n["verificado"] for n in notas):
        resumo += (" Situação na SEFAZ NÃO verificada para ao menos uma nota (sem consulta disponível) — "
                   "não se afirma que estão autorizadas.")
    return {"grau": grau, "chaves": chaves, "notas": notas, "sinais": sinais, "resumo": resumo,
            "acao": "" if consultar else "habilitar a consulta à SEFAZ por chave (decisão de custo/credencial)",
            "estagio_despesa": est["estagio"], "pagamento_efetivo": est["tem_ob"],
            "ressalva": "indício a apurar, não acusação; contingência é lícita; presunção de legitimidade",
            "fonte": "nfe_verifica"}
