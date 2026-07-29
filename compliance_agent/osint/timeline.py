# -*- coding: utf-8 -*-
"""Linha do tempo do caso — a anomalia que só aparece na SEQUÊNCIA dos fatos.

POR QUE A ORDEM IMPORTA MAIS QUE OS FATOS ISOLADOS. Cada peça já é detectada em separado: empresa
recém-aberta (C1), sócio que também é servidor (`socio_servidor`), pagamento a empresa baixada
(`empresa_fenix`), sanção vigente à data (C7). Sozinho, cada um é fraco e explicável. Juntos e em
ORDEM, contam outra história:

    empresa aberta 40 dias antes do edital → vence → sócio trocado 15 dias após a homologação
    → Ordem Bancária 8 meses depois da baixa da empresa

Nenhum desses fatos, isolado, sustenta peça. A sequência sustenta diligência com objeto certo.

O QUE ESTE MÓDULO FAZ E NÃO FAZ. Ele ORDENA e mede distâncias entre marcos, aplicando regras
temporais objetivas — nada de LLM, nada de score contínuo. Ele NÃO conclui: a proximidade entre
abertura e edital é indício, e a explicação inocente (empresa criada para atender um mercado que
o edital anunciou publicamente) vai junto de cada achado.

DUAS HONESTIDADES QUE MUDAM O RESULTADO:

  · **Evento sem data não vira evento sem posição.** Ele fica FORA da linha e aparece na lista de
    lacunas. A casa já pagou por isso: `cadeia_processo` usa o ID sequencial do SEI como proxy de
    ordem e DECLARA que é proxy. Inventar posição é pior que admitir que não se sabe.
  · **Data igual não é sequência.** Dois fatos no mesmo dia não provam qual veio antes; regras que
    dependem de "A antes de B" exigem diferença estrita, e o empate vira lacuna declarada.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterable

# ── marcos reconhecidos ───────────────────────────────────────────────────────────────────────
# Vocabulário fechado: evento de tipo desconhecido entra na linha mas não dispara regra, e isso
# fica declarado. Regra que dispara sobre tipo não previsto é regra que ninguém revisou.
TIPOS = {
    "empresa_aberta": "abertura do CNPJ do fornecedor",
    "empresa_baixada": "baixa do CNPJ do fornecedor",
    "alteracao_qsa": "alteração do quadro societário",
    "sancao_inicio": "início de vigência de sanção impeditiva",
    "sancao_fim": "fim de vigência de sanção impeditiva",
    "edital_publicado": "publicação do edital",
    "sessao": "sessão de abertura/julgamento",
    "homologacao": "homologação do certame",
    "contrato_assinado": "assinatura do contrato",
    "aditivo": "termo aditivo",
    "vigencia_fim": "fim da vigência contratual",
    "empenho": "empenho (NÃO é pagamento)",
    "liquidacao": "liquidação",
    "ordem_bancaria": "pagamento (Ordem Bancária)",
    "atesto": "atesto de recebimento",
    "nomeacao": "nomeação publicada no diário oficial",
    "doacao_eleitoral": "doação eleitoral declarada",
}

# Janelas objetivas, no CÓDIGO. Cada uma existe porque a proximidade é o que informa.
DIAS_EMPRESA_NOVA = 180        # aberta a menos disto do edital: entrou no mercado para o certame
DIAS_QSA_POS_HOMOLOGACAO = 90  # troca de sócio logo após vencer: quem ganhou não é quem executa
DIAS_ADITIVO_PRECOCE = 90      # aditivo logo após assinar: projeto incompleto por desenho


@dataclass
class Evento:
    tipo: str
    data: date
    descricao: str = ""
    fonte: str = ""
    valor: float | None = None
    detalhe: dict = field(default_factory=dict)


def _data(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v or "")[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def montar(eventos: Iterable[dict]) -> dict[str, Any]:
    """Ordena os eventos datados e separa o que não pôde entrar na linha.

    Evento sem data NÃO recebe posição inventada: sai em `lacunas`, com o tipo, para que quem
    fiscaliza saiba o que buscar.
    """
    linha: list[Evento] = []
    lacunas: list[dict] = []
    desconhecidos: set[str] = set()
    for e in eventos or []:
        if not isinstance(e, dict):
            continue
        d = _data(e.get("data"))
        tipo = str(e.get("tipo") or "").strip()
        if d is None:
            lacunas.append({"tipo": tipo or "?", "motivo": "evento sem data — fora da linha",
                            "descricao": str(e.get("descricao") or "")[:160]})
            continue
        if tipo not in TIPOS:
            desconhecidos.add(tipo)
        linha.append(Evento(tipo=tipo, data=d, descricao=str(e.get("descricao") or ""),
                            fonte=str(e.get("fonte") or ""),
                            valor=e.get("valor"), detalhe=e.get("detalhe") or {}))
    linha.sort(key=lambda x: (x.data, x.tipo))
    return {"linha": linha, "lacunas": lacunas, "tipos_desconhecidos": sorted(desconhecidos)}


def _primeiro(linha: list[Evento], tipo: str) -> Evento | None:
    return next((e for e in linha if e.tipo == tipo), None)


def _todos(linha: list[Evento], tipo: str) -> list[Evento]:
    return [e for e in linha if e.tipo == tipo]


def analisar(eventos: Iterable[dict]) -> dict[str, Any]:
    """Achados de SEQUÊNCIA. Cada um traz a distância medida e a explicação inocente."""
    m = montar(eventos)
    linha, achados = m["linha"], []

    abertura = _primeiro(linha, "empresa_aberta")
    edital = _primeiro(linha, "edital_publicado")
    homologacao = _primeiro(linha, "homologacao")
    contrato = _primeiro(linha, "contrato_assinado")
    baixa = _primeiro(linha, "empresa_baixada")

    # 1 · empresa criada às vésperas do certame
    if abertura and edital:
        dias = (edital.data - abertura.data).days
        if 0 <= dias <= DIAS_EMPRESA_NOVA:
            achados.append({
                "regra": "empresa_criada_as_vesperas",
                "nivel": "forte" if dias <= 90 else "medio",
                "dias": dias,
                "texto": (f"CNPJ aberto {dias} dia(s) antes da publicação do edital "
                          f"({abertura.data} → {edital.data})"),
                "explicacao_inocente": ("mercado pode ter sido anunciado publicamente antes do "
                                        "edital, e abrir empresa para atendê-lo é lícito; o que "
                                        "informa é a coincidência com ESTE certame"),
                "fontes": [abertura.fonte, edital.fonte],
            })
        elif dias < 0:
            achados.append({
                "regra": "empresa_aberta_apos_o_edital", "nivel": "forte", "dias": -dias,
                "texto": (f"CNPJ aberto {-dias} dia(s) DEPOIS da publicação do edital — a "
                          f"empresa não existia quando o certame foi lançado"),
                "explicacao_inocente": "constituição de SPE para o objeto, prática lícita e comum",
                "fontes": [abertura.fonte, edital.fonte],
            })

    # 2 · troca de sócio logo após vencer
    if homologacao:
        for alt in _todos(linha, "alteracao_qsa"):
            dias = (alt.data - homologacao.data).days
            if 0 <= dias <= DIAS_QSA_POS_HOMOLOGACAO:
                achados.append({
                    "regra": "qsa_alterado_apos_homologacao",
                    "nivel": "forte", "dias": dias,
                    "texto": (f"quadro societário alterado {dias} dia(s) após a homologação — "
                              f"quem venceu o certame pode não ser quem executa o contrato"),
                    "explicacao_inocente": ("reorganização societária ordinária; a habilitação foi "
                                            "aferida na data do certame, e a lei não congela o QSA"),
                    "fontes": [alt.fonte, homologacao.fonte],
                })

    # 3 · pagamento após a baixa do CNPJ
    if baixa:
        posteriores = [e for e in _todos(linha, "ordem_bancaria") if e.data > baixa.data]
        if posteriores:
            total = sum(float(e.valor or 0) for e in posteriores)
            achados.append({
                "regra": "pagamento_apos_baixa", "nivel": "critico",
                "dias": (posteriores[-1].data - baixa.data).days,
                "valor": total,
                "texto": (f"{len(posteriores)} Ordem(ns) Bancária(s) emitida(s) APÓS a baixa do "
                          f"CNPJ ({baixa.data}); a última {(posteriores[-1].data - baixa.data).days} "
                          f"dia(s) depois"),
                "explicacao_inocente": ("pagamento de obrigação anterior à baixa é lícito; o que "
                                        "importa é se houve EXECUÇÃO após a extinção da empresa"),
                "fontes": [baixa.fonte] + [e.fonte for e in posteriores[:3]],
            })

    # 4 · sanção vigente na data da homologação
    ini, fim = _primeiro(linha, "sancao_inicio"), _primeiro(linha, "sancao_fim")
    if ini and homologacao and ini.data <= homologacao.data and (
            fim is None or fim.data >= homologacao.data):
        achados.append({
            "regra": "sancao_vigente_na_homologacao", "nivel": "critico",
            "texto": (f"sanção impeditiva vigente em {homologacao.data} "
                      f"(início {ini.data}{', fim ' + str(fim.data) if fim else ', sem termo final'})"),
            "explicacao_inocente": ("a sanção pode ter abrangência restrita ao ente que a aplicou; "
                                    "conferir o alcance antes de afirmar impedimento"),
            "fontes": [ini.fonte, homologacao.fonte],
        })

    # 5 · aditivo precoce
    if contrato:
        for ad in _todos(linha, "aditivo"):
            dias = (ad.data - contrato.data).days
            if 0 <= dias <= DIAS_ADITIVO_PRECOCE:
                achados.append({
                    "regra": "aditivo_precoce", "nivel": "medio", "dias": dias,
                    "texto": (f"termo aditivo {dias} dia(s) após a assinatura do contrato — "
                              f"projeto incompleto no momento da contratação"),
                    "explicacao_inocente": ("superveniente real pode ocorrer logo no início; a "
                                            "apuração pede o fato datado que motivou o termo"),
                    "fontes": [ad.fonte, contrato.fonte],
                })

    # 6 · pagamento antes do atesto
    atesto = _primeiro(linha, "atesto")
    if atesto:
        antes = [e for e in _todos(linha, "ordem_bancaria") if e.data < atesto.data]
        if antes:
            achados.append({
                "regra": "pagamento_antes_do_atesto", "nivel": "forte",
                "texto": (f"{len(antes)} pagamento(s) com data anterior ao atesto de recebimento "
                          f"({atesto.data})"),
                "explicacao_inocente": ("atesto pode ter sido registrado no sistema depois de "
                                        "ocorrido; conferir a data do recebimento, não a do lançamento"),
                "fontes": [atesto.fonte] + [e.fonte for e in antes[:3]],
            })

    ordem = {"critico": 4, "forte": 3, "medio": 2, "fraco": 1}
    achados.sort(key=lambda a: -ordem.get(a["nivel"], 0))
    return {
        "linha": [{"data": e.data.isoformat(), "tipo": e.tipo,
                   "descricao": e.descricao or TIPOS.get(e.tipo, e.tipo),
                   "fonte": e.fonte, "valor": e.valor} for e in linha],
        "achados": achados,
        "lacunas": m["lacunas"],
        "tipos_desconhecidos": m["tipos_desconhecidos"],
        "n_eventos": len(linha),
        "periodo": ({"de": linha[0].data.isoformat(), "ate": linha[-1].data.isoformat()}
                    if linha else None),
        "ressalva": ("A sequência é INDÍCIO: cada achado traz a explicação inocente mais comum ao "
                     "lado. Eventos sem data ficam fora da linha e aparecem em `lacunas` — "
                     "ausência de evento não é ausência de fato."),
    }
