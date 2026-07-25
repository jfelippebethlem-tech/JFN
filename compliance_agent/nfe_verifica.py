# -*- coding: utf-8 -*-
"""NF-e — a nota que lastreia o pagamento foi CANCELADA? foi emitida em CONTINGÊNCIA? (plano #4, item 1.3)

Pergunta do dono (2026-07-24): "dá pra saber?" — **dá**. A CHAVE DE ACESSO (44 dígitos) impressa no DANFE e
citada no processo é auto-descritiva; dela saem, SEM REDE:

    cUF(2) AAMM(4) CNPJ(14) mod(2) série(3) nNF(9) tpEmis(1) cNF(8) cDV(1)

  • **tpEmis** (posição 35) revela CONTINGÊNCIA na hora — emitir em contingência é lícito, mas exige
    autorização posterior; NF em contingência lastreando pagamento é ponto de verificação clássico.
  • **cDV** (mod 11) valida a chave — é o que separa uma chave real de um número de 44 dígitos qualquer
    (protocolo, código de barras) e evita falso positivo na varredura de texto.

CANCELAMENTO/DENEGAÇÃO **não** está na chave: exige consulta à SEFAZ. **Nada pago entra aqui** (decisão do
dono 2026-07-24): certificado digital A1 e agregadores por consulta estão FORA. Por isso `situacao()`
recebe a consulta INJETADA (`consultar`): o módulo não amarra fornecedor nenhum. Sem consulta disponível o
veredito é **`nao_verificada` / `a_verificar`** — NUNCA "autorizada" por omissão: ausência de verificação
≠ regularidade.

⚠️ **O caminho gratuito descrito aqui até 25/07/2026 NÃO EXISTE MAIS — medido, não suposto.** A versão
anterior deste texto dizia que bastava o "portal público, que consulta pela chave sem credencial, com o
captcha resolvido pelo **ddddocr** local". Testado nesta data, por **duas** razões independentes:

  · **`www.nfe.fazenda.gov.br` não conecta** — cadeia TLS quebrada do lado deles (certificado Let's Encrypt
    `CN=YR2` sem emissor local). Não é bundle velho aqui: PNCP, minhareceita, opencnpj, brasil.io e o
    próprio `dfe-portal.svrs.rs.gov.br` respondem normalmente com o mesmo `certifi`;
  · **o portal estadual (SVRS) passou a exigir login gov.br** — `GET /NFE/Consulta` redireciona para
    `sso.acesso.gov.br/login`. Não é mais consulta anônima.

E mesmo que conectasse: a página se chama `consultaRecaptcha.aspx` — é **reCAPTCHA do Google**, que o
**ddddocr NÃO resolve** (ele faz OCR de captcha de imagem simples). A premissa estava errada em dois
níveis. Enquanto não houver caminho gratuito e sem credencial, a situação na SEFAZ fica **INDISPONÍVEL**,
que é o comportamento-padrão desta função — e isso não é o mesmo que "nota regular".

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
# ── MODELO do documento (posições 20-22) ──────────────────────────────────────────────
# A "chave de acesso" de 44 dígitos NÃO é exclusiva da NF-e: é o formato de TODO documento
# fiscal eletrônico (DF-e). Medido no acervo em 25/07/2026: das 845 chaves que passavam no
# DV, **640 eram modelo 66** — e não era lixo, era NF3e, a nota de ENERGIA ELÉTRICA, de dois
# emitentes só (Ampla, 393; Light, 247), ambos fornecedores reais das OB. Chamar tudo de
# "NF-e" num dossiê é erro de rótulo, e o endereço de consulta na SEFAZ é outro.
_MODELO_DFE = {
    "55": "NF-e (nota fiscal eletrônica)",
    "65": "NFC-e (nota fiscal de consumidor)",
    "66": "NF3e (nota fiscal de energia elétrica)",
    "57": "CT-e (conhecimento de transporte)",
    "67": "CT-e OS (transporte — outros serviços)",
    "58": "MDF-e (manifesto de documentos fiscais)",
    "59": "CF-e/SAT (cupom fiscal eletrônico)",
    "63": "BP-e (bilhete de passagem)",
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
    """44 dígitos, DV fechando **e estrutura plausível**.

    O DV sozinho NÃO basta, ao contrário do que este módulo afirmava: o módulo 11 aceita
    ~1 em 11 sequências por acaso, e o texto de um processo é cheio de números longos.
    Medido no acervo em 25/07/2026: das **845** chaves aceitas só pelo DV, **49 eram lixo** —
    UF inexistente (20, 85, 30), modelo inexistente (00, 24, 43, 10) e emitentes que não
    aparecem em nenhuma OB. Elas produziram um alarme falso de "20 notas em contingência",
    das quais **1** era real; 11 diziam SCAN, desativada desde 2014, numa nota de 2026.

    Três checagens estruturais, todas de graça: UF na tabela oficial, modelo de DF-e
    conhecido, e AAMM plausível. Não valida CNPJ do emitente de propósito — emitente de
    fora do acervo é legítimo.
    """
    c = re.sub(r"\D", "", chave or "")
    if len(c) != 44 or digito_verificador(c[:43]) != int(c[43]):
        return False
    if c[0:2] not in _UF or c[20:22] not in _MODELO_DFE:
        return False
    aa, mm = c[2:4], c[4:6]
    return "06" <= aa <= "40" and "01" <= mm <= "12"


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
    # o documento pode NÃO ser NF-e (640 das 845 chaves do acervo são NF3e de energia):
    # quem monta texto para o dossiê precisa do rótulo certo, não de "NF-e" genérico.
    d["modelo_nome"] = _MODELO_DFE.get(d["modelo"], "documento fiscal eletrônico")
    d["eh_nfe"] = d["modelo"] in ("55", "65")
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
    — INJETADO. Caminho admitido: portal público + ddddocr local (grátis). Nada pago.

    Sem consulta, ou se ela falhar: `verificado=False`, `situacao='nao_verificada'`, grau `a_verificar`.
    Nunca se afirma que a nota está regular só porque não se conseguiu perguntar."""
    pend = {"chave": re.sub(r"\D", "", chave or ""), "verificado": False, "situacao": "nao_verificada",
            "grau": "a_verificar",
            "acao": ("consultar a situação da NF-e no portal público da SEFAZ pela chave de acesso "
                     "(captcha resolvido localmente por ddddocr — sem custo e sem credencial)"),
            "ressalva": "ausência de verificação ≠ nota regular"}
    if consultar is None:
        return pend
    try:
        r = await consultar(chave)
    except Exception as e:  # noqa: BLE001 — rede/captcha/portal fora do ar: degrada honesto, não inventa
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
            "acao": "" if consultar else ("ligar a consulta ao portal público da SEFAZ por chave "
                                          "(ddddocr local resolve o captcha; sem custo)"),
            "estagio_despesa": est["estagio"], "pagamento_efetivo": est["tem_ob"],
            "ressalva": "indício a apurar, não acusação; contingência é lícita; presunção de legitimidade",
            "fonte": "nfe_verifica"}
