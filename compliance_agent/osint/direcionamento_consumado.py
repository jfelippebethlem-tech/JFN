# -*- coding: utf-8 -*-
"""A virada de natureza: de "cláusula restritiva" para "direcionamento CONSUMADO".

A régua da casa (skill `analise-clausulas-br`, §5) já dizia em prosa: *vencedor identificado +
sinal societário ⇒ o achado deixa de ser "cláusula restritiva" e vira "direcionamento consumado";
a peça muda de natureza*. E `editais/escalada.recomendar()` já aceita o gatilho
`vinculo_societario_vencedor`. Faltava quem PRODUZISSE o gatilho — alguém tinha de olhar o
vencedor, olhar as perdedoras, e dizer se há caminho entre eles.

É o que este módulo faz, e a pergunta que ele responde é a que decide o caso:

    "existe caminho de comprimento ≤ N entre o vencedor e a perdedora X?"
    → e a resposta vem com o caminho explicitado, aresta a aresta, cada uma com fonte.

POR QUE A PERDEDORA IMPORTA MAIS QUE O VENCEDOR SOZINHO. Empresa vencedora com sócio conhecido é
fato comum. Empresa vencedora ligada a quem "concorreu" contra ela é outra coisa: a competição
era aparente. Esse cruzamento é uma tarefa aberta do próprio acervo do controle externo — "cruzar
QSA das concorrentes perdedoras com o grupo; se perdedora ∈ grupo, corrobora forte".

HONESTIDADE, e ela define o resultado:
  · caminho por PRÉDIO compartilhado não conta (a Rua da Assembleia 10 tem 318 CNPJs);
  · caminho por NOME sem documento não conta (homonímia);
  · **ausência de caminho não é prova de lisura** — pode ser ausência de dado. O resultado
    declara a cobertura (quantas perdedoras tinham QSA conhecido) junto do veredito;
  · nada aqui afirma direcionamento: afirma que o vínculo, se confirmado nos autos, MUDA a
    natureza do achado — e diz qual peça isso passa a sustentar.
"""
from __future__ import annotations

from typing import Any

from compliance_agent.osint.vinculos import GrafoVinculos, no_pf, no_pj

# Um caminho só "corrobora forte" se for por elo que signifique alguma coisa. O piso exclui
# prédio (0.05) e nome sem documento (0.10) e deixa passar contador/advogado (0.30/0.35) apenas
# quando o chamador afrouxa explicitamente.
FORCA_MINIMA_PADRAO = 0.5
MAX_SALTOS_PADRAO = 3


def montar_grafo(vencedor: dict, perdedores: list[dict], *,
                 fonte_qsa: str = "Receita Federal/QSA",
                 fonte_endereco: str = "Receita Federal/cadastro") -> GrafoVinculos:
    """Monta o grafo do certame a partir de dicionários simples.

    Cada participante: `{cnpj, nome, socios: [{cpf?, nome}], endereco?: {logradouro, complemento},
    telefone?, email?, ip?, contador_crc?}`. Campos ausentes viram cobertura menor, nunca aresta
    inventada.
    """
    g = GrafoVinculos()
    por_endereco: dict[tuple[str, str], list[str]] = {}
    por_chave: dict[tuple[str, str], list[str]] = {}

    for p in [vencedor, *perdedores]:
        if not isinstance(p, dict):
            continue
        no = no_pj(p.get("cnpj"), p.get("nome", ""))
        g.rotular(no, str(p.get("nome") or p.get("cnpj") or no))

        for s in p.get("socios") or []:
            if not isinstance(s, dict):
                continue
            doc = s.get("cpf") or s.get("documento")
            ns = no_pf(doc, s.get("nome", ""))
            g.rotular(ns, str(s.get("nome") or ns))
            # Sócio sem CPF liga por NOME — e o tipo de aresta declara isso, com força 0,10.
            g.ligar(ns, no, "socio_de" if doc else "nome_igual_sem_documento",
                    fonte=fonte_qsa, data=str(s.get("desde") or ""),
                    detalhe=str(s.get("nome") or ""))

        end = p.get("endereco") or {}
        if end.get("logradouro"):
            chave = (str(end["logradouro"]).strip().lower(),
                     str(end.get("complemento") or "").strip().lower())
            por_endereco.setdefault(chave, []).append(no)

        for campo, tipo in (("telefone", "mesmo_telefone"), ("email", "mesmo_email"),
                            ("ip", "mesmo_ip"), ("contador_crc", "mesmo_contador")):
            valor = str(p.get(campo) or "").strip().lower()
            if valor:
                por_chave.setdefault((tipo, valor), []).append(no)

    for (logradouro, complemento), nos in por_endereco.items():
        for i, a in enumerate(nos):
            for b in nos[i + 1:]:
                g.ligar_endereco(a, b, logradouro=logradouro, complemento=complemento,
                                 fonte=fonte_endereco)
    for (tipo, valor), nos in por_chave.items():
        for i, a in enumerate(nos):
            for b in nos[i + 1:]:
                g.ligar(a, b, tipo, fonte="cadastro/peças do certame", detalhe=valor)
    return g


def avaliar(vencedor: dict, perdedores: list[dict], *,
            clausula_restritiva: bool = False,
            forca_minima: float = FORCA_MINIMA_PADRAO,
            max_saltos: int = MAX_SALTOS_PADRAO) -> dict[str, Any]:
    """Há caminho entre o vencedor e alguma perdedora? E o que isso muda na peça?

    `clausula_restritiva` diz se o certame já tinha achado de restritividade — é a combinação
    (restrição + vínculo) que caracteriza o direcionamento consumado. Vínculo sozinho é
    concentração de mercado, que é outro problema.
    """
    g = montar_grafo(vencedor, perdedores)
    no_venc = no_pj(vencedor.get("cnpj"), vencedor.get("nome", ""))

    ligadas, sem_dado = [], 0
    for p in perdedores or []:
        if not isinstance(p, dict):
            continue
        if not (p.get("socios") or p.get("endereco") or p.get("telefone") or p.get("email")
                or p.get("ip") or p.get("contador_crc")):
            sem_dado += 1
            continue
        alvo = no_pj(p.get("cnpj"), p.get("nome", ""))
        r = g.caminho(no_venc, alvo, max_saltos=max_saltos, forca_minima=forca_minima)
        if r.get("encontrado"):
            ligadas.append({"perdedora": p.get("nome") or p.get("cnpj"),
                            "cnpj": p.get("cnpj"), **r})

    n_perdedoras = len([p for p in (perdedores or []) if isinstance(p, dict)])
    cobertura = {
        "perdedoras": n_perdedoras,
        "com_dado": n_perdedoras - sem_dado,
        "sem_dado": sem_dado,
        "frac_coberta": round((n_perdedoras - sem_dado) / n_perdedoras, 3) if n_perdedoras else 0.0,
    }

    if ligadas:
        veredito = "direcionamento_consumado" if clausula_restritiva else "competicao_aparente"
        peca = "representacao" if clausula_restritiva else "diligencia"
        resumo = (
            f"{len(ligadas)} de {cobertura['com_dado']} perdedora(s) com dado disponível têm "
            f"caminho até o vencedor. "
            + ("Combinado ao achado de cláusula restritiva, o caso deixa de ser 'exigência "
               "restritiva' e passa a 'direcionamento consumado': a competição era aparente."
               if clausula_restritiva else
               "Não há achado de restritividade neste certame — o vínculo isolado indica "
               "competição aparente, a apurar, e não direcionamento por cláusula."))
    else:
        veredito = "sem_vinculo_apurado"
        peca = None
        resumo = (
            f"Nenhum caminho apurado entre o vencedor e as {cobertura['com_dado']} perdedora(s) "
            f"com dado disponível"
            + (f"; {sem_dado} perdedora(s) SEM dado societário/cadastral — a ausência de vínculo "
               f"aqui é lacuna de captura, não atestado de lisura." if sem_dado else
               ". A ausência de vínculo nos dados consultados não prova lisura: outras fontes "
               "(juntas comerciais, atos societários) não foram consultadas."))

    return {
        "veredito": veredito,
        "peca_sugerida": peca,
        "ligadas": ligadas,
        "cobertura": cobertura,
        "resumo": resumo,
        "gatilho_escalada": {"vinculo_societario_vencedor": bool(ligadas and clausula_restritiva)},
        "ressalva": ("Vínculo apurado em fonte aberta é INDÍCIO. Confirmar nos autos (atas, "
                     "propostas, QSA na data do certame) antes de afirmar direcionamento; a "
                     "sociedade pode ser posterior ao certame."),
    }
