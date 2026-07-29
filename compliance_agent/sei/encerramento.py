# -*- coding: utf-8 -*-
"""Processo encerrado e já lido não se relê — mas encerrado nunca quer dizer inauditável.

POR QUE ISTO EXISTE. O sweep de CAPTURA já pula árvore encerrada (`sei_arvore.encerrado`, 686
dos 3.919 processos). A ANÁLISE EM SÉRIE, que é a parte que gasta cota de modelo, nunca
consultou esse sinal: relia processo encerrado, sem fato novo, pelo mesmo preço de um processo
vivo. Com 45.939 processos no universo e cota `:free`, cada releitura inútil é uma leitura nova
que deixou de acontecer.

AS TRÊS CONDIÇÕES, e por que nenhuma sobra:

    já foi lido por inteiro  — nunca pular o que nunca se leu. Processo encerrado e não lido é
                               dinheiro pago sobre o qual não se leu uma linha; é o PIOR caso,
                               não o melhor.
    está encerrado           — termo de encerramento no arquivo local OU a árvore autoritativa.
    sem pagamento novo       — OB posterior à leitura reabre o interesse mesmo em processo
                               encerrado: pagar depois do encerramento é, por si, algo a olhar.

O veredito sai SEMPRE com o motivo. Fila sem motivo vira caixa-preta, e quem a lê precisa saber
se o processo saiu por estar em dia ou por estar cego.
"""
from __future__ import annotations

import json
import os
import pathlib
import re

# "Termo de Encerramento de Processo" encerra o PROCESSO. "Termo de encerramento do contrato"
# é peça de execução — o processo segue tramitando (pagamento, prestação de contas). Casar os
# dois marcaria como encerrado processo vivo, e ele sairia da fila de análise em silêncio.
_RE_ENCERRA_PROCESSO = re.compile(
    r"termo\s+de\s+encerramento\s+(?:de\s+)?(?:processo|autos)"
    r"|encerramento\s+(?:de\s+)?processo"
    r"|termo\s+de\s+arquivamento",
    re.IGNORECASE)
_RE_ENCERRA_CONTRATO = re.compile(r"encerramento\s+d[eo]s?\s+contrato|encerramento\s+contratual",
                                  re.IGNORECASE)


def encerrado_no_arquivo(documentos) -> bool:
    """Há Termo de Encerramento DO PROCESSO entre os documentos capturados?

    Fonte local (o manifest do acervo), sem depender do banco — a análise roda sobre o arquivo
    e precisa do sinal ali mesmo.
    """
    for doc in documentos or []:
        titulo = str((doc or {}).get("titulo") or "")
        if _RE_ENCERRA_CONTRATO.search(titulo):
            continue
        if _RE_ENCERRA_PROCESSO.search(titulo):
            return True
    return False


def deve_reanalisar(*, ja_lido: bool, encerrado: bool, ob_apos_leitura: bool,
                    leitura_incompleta: bool = False) -> dict:
    """`{"reanalisar": bool, "motivo": str}` — a decisão de gastar cota, com a razão junto."""
    if not ja_lido:
        return {"reanalisar": True,
                "motivo": "nunca foi lido — encerrado ou não, é pagamento sem uma linha lida"}
    if leitura_incompleta:
        return {"reanalisar": True,
                "motivo": "leitura INCOMPLETA (lote não lido): pular por 'já lido' cristalizaria "
                          "um dossiê que não cobriu o processo"}
    if ob_apos_leitura:
        return {"reanalisar": True,
                "motivo": "há pagamento (OB) POSTERIOR à leitura — fato novo reabre o processo, "
                          "e pagar depois do encerramento é por si algo a olhar"}
    if encerrado:
        return {"reanalisar": False,
                "motivo": "processo ENCERRADO, já lido por inteiro e sem pagamento novo — releitura "
                          "não traria fato; encerrado segue auditável, o que cai é a prioridade"}
    return {"reanalisar": True, "motivo": "processo vivo: pode ter documento novo desde a leitura"}


ACERVO = pathlib.Path(os.environ.get("JFN_SEI_ARQUIVO", "data/sei_arquivo"))


def situacao_do_processo(pasta: str, *, arvore_encerradas: set[str] | None = None) -> dict:
    """Funde os sinais de encerramento e DECLARA a fonte de cada um.

    Duas fontes independentes, e a divergência entre elas é informação: o arquivo local (Termo
    de Encerramento entre os documentos capturados) e a árvore autoritativa
    (`sei_arvore.encerrado`, que já embute as salvaguardas de OB recente, aditivo e filho
    vigente). Sem manifest não se afirma nada — ausência de dado não é ausência de
    encerramento, e o campo `fonte` diz isso em vez de calar.
    """
    numero = "SEI-" + str(pasta).replace("_", "/")
    manifesto = ACERVO / str(pasta) / "manifest.json"
    docs, tem_manifest = [], manifesto.is_file()
    if tem_manifest:
        try:
            docs = json.loads(manifesto.read_text(encoding="utf-8")).get("docs") or []
        except (OSError, json.JSONDecodeError, AttributeError):
            docs, tem_manifest = [], False

    por_arquivo = encerrado_no_arquivo(docs)
    por_arvore = numero in (arvore_encerradas or set())
    fontes = []
    if por_arquivo:
        fontes.append("arquivo (Termo de Encerramento entre os documentos)")
    if por_arvore:
        fontes.append("árvore autoritativa (sei_arvore.encerrado)")
    if not fontes:
        fontes.append("sem sinal de encerramento" if tem_manifest
                      else "INDISPONÍVEL: sem manifest no acervo")
    return {"processo": numero, "encerrado": bool(por_arquivo or por_arvore),
            "por_arquivo": por_arquivo, "por_arvore": por_arvore,
            "n_docs": len(docs), "fonte": " + ".join(fontes)}
