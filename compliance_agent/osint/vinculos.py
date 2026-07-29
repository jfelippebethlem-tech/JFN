# -*- coding: utf-8 -*-
"""Grafo único de vínculos — e o CAMINHO entre duas entidades, aresta a aresta, com fonte.

POR QUE ESTE MÓDULO EXISTE. A casa tem muitas peças de vínculo espalhadas: `rede_societaria`,
`grafo_cartel`, `hub_compartilhado` (endereço/telefone/e-mail), `ninho_sala`, `conluio_qsa`,
`socio_oculto`, `porta_giratoria`, `doacoes_eleitorais`. Cada uma responde a uma pergunta e para
aí. Falta o encadeamento — e é o encadeamento que convence numa representação: não "as duas
empresas têm sócios em comum", mas *"a vencedora e a segunda colocada ligam-se por João da Silva,
sócio de ambas desde 2019, e por um endereço compartilhado na mesma SALA; fontes X e Y"*.

O QUE ESTE MÓDULO NÃO FAZ, e é o que o torna utilizável:

  · **Não trata toda aresta como igual.** Cada tipo carrega uma FORÇA calibrada nas lições que a
    casa já pagou: "mesmo prédio" quase nada (a Rua da Assembleia 10 tem 318 CNPJs), "mesma sala"
    muito; "mesmo contador" isolado vale pouco (mercado regional concentra contabilidade, guard já
    implementado no P2), mesmo IP vale muito. Somar arestas sem peso produz o grafo em que todo
    mundo se liga a todo mundo — que é o mesmo que grafo nenhum.
  · **Não esconde a fonte.** Toda aresta declara de onde veio e em que data. Caminho sem fonte não
    entra em peça.
  · **Não infere identidade.** Duas pessoas com o mesmo NOME não são a mesma pessoa; o grafo liga
    por documento, e nome sem documento entra como aresta FRACA e declarada (a homonímia já custou
    correção na casa — ver `resolucao_cpf`).
  · **Não usa fonte sob sigilo.** RIF/COAF, sigilo bancário e fiscal não entram aqui. Onde a
    conclusão dependeria deles, o produto emite pedido de diligência nominando a fonte necessária.

LGPD: o grafo interno guarda o documento íntegro (é dado público de sócio); a exportação para
entregável mascara CPF por padrão (`mascarar=True`), como o resto da casa.
"""
from __future__ import annotations

import heapq
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

# ── tipos de entidade ─────────────────────────────────────────────────────────────────────────
TIPOS_ENTIDADE = ("pj", "pf", "endereco", "telefone", "email", "dominio", "ip", "orgao",
                  "veiculo", "processo")

# ── tipos de aresta, com FORÇA calibrada ──────────────────────────────────────────────────────
# A força é 0-1 e responde a uma pergunta só: quanto esta aresta, SOZINHA, aproxima duas
# entidades? Os valores vêm das lições medidas da casa, não de intuição:
#
#   · `mesmo_predio` 0.05 — "RUA DA ASSEMBLEIA 10" tem 318 CNPJs (ninho_sala.py:8-17);
#   · `mesma_sala` 0.75 — por sala, o mesmo acervo dá 120 grupos, e aí o sinal é real;
#   · `mesmo_contador` 0.30 — isolado é exculpável por mercado regional (p2_cotacoes:177-179);
#   · `mesmo_ip` 0.90 — assinatura digital compartilhada é crítico no J5 (j5:183-191);
#   · `nome_igual_sem_documento` 0.10 — homonímia; existe para APARECER, não para pesar.
@dataclass(frozen=True)
class TipoAresta:
    id: str
    descricao: str
    forca: float
    exculpatoria: str = ""     # a explicação inocente mais comum — vai junto do achado


TIPOS_ARESTA: dict[str, TipoAresta] = {
    "socio_de": TipoAresta("socio_de", "pessoa é sócia/administradora da empresa", 0.95),
    "mesmo_socio": TipoAresta("mesmo_socio", "empresas com sócio em comum", 0.90),
    "mesma_sala": TipoAresta(
        "mesma_sala", "mesmo endereço COM complemento (sala/andar/conjunto)", 0.75,
        "salas de coworking e escritórios virtuais hospedam empresas sem relação entre si"),
    "mesmo_predio": TipoAresta(
        "mesmo_predio", "mesmo logradouro e número, sem complemento", 0.05,
        "prédio comercial concentra centenas de CNPJs sem qualquer vínculo"),
    "mesmo_ip": TipoAresta("mesmo_ip", "propostas enviadas do mesmo IP", 0.90,
                           "rede compartilhada de associação comercial ou lan house"),
    "mesmo_telefone": TipoAresta("mesmo_telefone", "mesmo telefone cadastrado", 0.70,
                                 "central telefônica de escritório de contabilidade"),
    "mesmo_email": TipoAresta("mesmo_email", "mesmo e-mail cadastrado", 0.80,
                              "e-mail do contador usado por vários clientes"),
    "mesmo_contador": TipoAresta(
        "mesmo_contador", "mesmo contador (CRC) nas peças", 0.30,
        "mercado regional concentra a contabilidade em poucos escritórios"),
    "mesmo_advogado": TipoAresta("mesmo_advogado", "mesmo advogado (OAB) nas peças", 0.35,
                                 "advogado especializado atende o setor inteiro"),
    "mesmo_registrante": TipoAresta("mesmo_registrante", "domínios com o mesmo registrante", 0.75),
    "doou_para": TipoAresta("doou_para", "doação eleitoral declarada", 0.60),
    "nomeado_por": TipoAresta("nomeado_por", "nomeação publicada em diário oficial", 0.60),
    "parente_de": TipoAresta("parente_de", "parentesco declarado ou documentado", 0.85),
    "servidor_de": TipoAresta("servidor_de", "vínculo funcional com o órgão", 0.90),
    "sucessora_de": TipoAresta("sucessora_de", "sucessão/incorporação societária", 0.85),
    "subcontratou": TipoAresta(
        "subcontratou", "subcontratação declarada", 0.70,
        "subcontratação é lícita quando prevista no edital e nos limites do contrato; o sinal "
        "está em subcontratar justamente quem PERDEU o certame"),
    "nome_igual_sem_documento": TipoAresta(
        "nome_igual_sem_documento", "mesmo NOME, sem documento que confirme identidade", 0.10,
        "homonímia — nome comum não identifica pessoa; exige CPF para valer"),
}

# Endereços que NÃO ligam ninguém a ninguém: coworking, caixa postal, sede de junta comercial.
# Lista declarada e versionada — hardcode solto em detector foi o que produziu os falsos
# positivos do "Rua da Assembleia 10" e do "Ministério da Fazenda".
PADROES_ENDERECO_NEUTRO = (
    r"\bcoworking\b", r"\bescrit[óo]rio\s+virtual\b", r"\bcaixa\s+postal\b",
    r"\bsala\s+comercial\s+compartilhada\b", r"\bcondom[íi]nio\s+empresarial\b",
)
_RE_NEUTRO = re.compile("|".join(PADROES_ENDERECO_NEUTRO), re.I)
# Complemento (sala/andar/conjunto) é o que distingue "mesma sala" de "mesmo prédio".
_RE_COMPLEMENTO = re.compile(
    r"\b(sala|sl\.?|conj(?:unto)?\.?|and(?:ar)?\.?|apt?o?\.?|bloco|loja|grupo)\s*\.?\s*\d+", re.I)


@dataclass
class Aresta:
    origem: str
    destino: str
    tipo: str
    fonte: str
    data: str = ""
    detalhe: str = ""
    forca: float = 0.0
    observacoes: list[str] = field(default_factory=list)


def _norm_doc(s: Any) -> str:
    return re.sub(r"\D", "", str(s or ""))


def no_pj(cnpj: Any, nome: str = "") -> str:
    """Chave de nó. Documento manda; sem documento, o nome vira chave e a aresta será fraca."""
    d = _norm_doc(cnpj)
    return f"pj:{d}" if d else f"pj_nome:{re.sub(r'\\s+', ' ', str(nome or '')).strip().lower()}"


def no_pf(cpf: Any, nome: str = "") -> str:
    d = _norm_doc(cpf)
    return f"pf:{d}" if d else f"pf_nome:{re.sub(r'\\s+', ' ', str(nome or '')).strip().lower()}"


def classificar_endereco(logradouro: str, complemento: str = "") -> tuple[str, list[str]]:
    """`(tipo_de_aresta, observações)` para um endereço compartilhado.

    A distinção sala × prédio é o coração da honestidade deste módulo: por prédio, o topo do
    acervo é um endereço com 318 CNPJs; por sala, o mesmo dado dá grupos que significam algo.
    """
    texto = f"{logradouro or ''} {complemento or ''}"
    obs: list[str] = []
    if _RE_NEUTRO.search(texto):
        obs.append("endereço de natureza compartilhada (coworking/escritório virtual) — não liga")
        return "mesmo_predio", obs
    if _RE_COMPLEMENTO.search(complemento or "") or _RE_COMPLEMENTO.search(logradouro or ""):
        return "mesma_sala", obs
    obs.append("sem complemento (sala/andar) — o compartilhamento é do PRÉDIO, não da unidade")
    return "mesmo_predio", obs


class GrafoVinculos:
    """Grafo não-direcionado de entidades. Pequeno de propósito: é montado por caso, não global."""

    def __init__(self) -> None:
        self.arestas: list[Aresta] = []
        self._adj: dict[str, list[int]] = {}
        self.rotulos: dict[str, str] = {}

    # ── construção ────────────────────────────────────────────────────────────────────────────
    def rotular(self, no: str, rotulo: str) -> None:
        if rotulo:
            self.rotulos[no] = rotulo

    def ligar(self, origem: str, destino: str, tipo: str, *, fonte: str, data: str = "",
              detalhe: str = "", observacoes: Iterable[str] = ()) -> Aresta | None:
        """Adiciona uma aresta. Tipo desconhecido é RECUSADO — vocabulário fechado, como a rubrica.

        `fonte` é obrigatória: aresta sem procedência não pode entrar em peça, e uma aresta que
        não pode entrar em peça não deveria existir no grafo.
        """
        t = TIPOS_ARESTA.get(str(tipo))
        if t is None or origem == destino or not origem or not destino or not fonte:
            return None
        a = Aresta(origem=origem, destino=destino, tipo=t.id, fonte=fonte, data=data,
                   detalhe=detalhe, forca=t.forca, observacoes=list(observacoes))
        self.arestas.append(a)
        i = len(self.arestas) - 1
        self._adj.setdefault(origem, []).append(i)
        self._adj.setdefault(destino, []).append(i)
        return a

    def ligar_endereco(self, a_no: str, b_no: str, *, logradouro: str, complemento: str = "",
                       fonte: str, data: str = "") -> Aresta | None:
        tipo, obs = classificar_endereco(logradouro, complemento)
        return self.ligar(a_no, b_no, tipo, fonte=fonte, data=data,
                          detalhe=f"{logradouro} {complemento}".strip(), observacoes=obs)

    # ── consulta ──────────────────────────────────────────────────────────────────────────────
    def vizinhos(self, no: str) -> list[tuple[str, Aresta]]:
        out = []
        for i in self._adj.get(no, []):
            a = self.arestas[i]
            out.append((a.destino if a.origem == no else a.origem, a))
        return out

    def caminho(self, origem: str, destino: str, *, max_saltos: int = 3,
                forca_minima: float = 0.0) -> dict[str, Any]:
        """O caminho MAIS FORTE entre duas entidades, aresta a aresta.

        "Mais forte" e não "mais curto": um caminho de dois saltos por sócio comum vale mais que
        um de um salto por prédio compartilhado. A força do caminho é o PRODUTO das arestas — um
        elo fraco enfraquece a cadeia inteira, que é exatamente o comportamento desejado quando
        se vai afirmar vínculo numa peça.

        `forca_minima` descarta arestas fracas antes de buscar (útil para excluir `mesmo_predio`).
        """
        if origem == destino:
            return {"encontrado": False, "motivo": "origem e destino são a mesma entidade"}
        # Dijkstra sobre -log(forca): maximizar produto = minimizar soma dos custos.
        import math
        melhor: dict[str, float] = {origem: 0.0}
        anterior: dict[str, tuple[str, Aresta]] = {}
        fila: list[tuple[float, int, str]] = [(0.0, 0, origem)]
        contador = 0
        while fila:
            custo, saltos, no = heapq.heappop(fila)
            if no == destino:
                break
            if saltos >= max_saltos:
                continue
            for viz, a in self.vizinhos(no):
                if a.forca <= 0 or a.forca < forca_minima:
                    continue
                novo = custo - math.log(a.forca)
                if novo < melhor.get(viz, float("inf")):
                    melhor[viz] = novo
                    anterior[viz] = (no, a)
                    contador += 1
                    heapq.heappush(fila, (novo, saltos + 1, viz))

        if destino not in anterior:
            return {"encontrado": False,
                    "motivo": f"nenhum caminho de até {max_saltos} salto(s) com força ≥ "
                              f"{forca_minima:.2f} entre as entidades"}
        passos: list[dict] = []
        no = destino
        while no != origem:
            ant, a = anterior[no]
            t = TIPOS_ARESTA[a.tipo]
            passos.append({
                "de": self.rotulos.get(ant, ant), "para": self.rotulos.get(no, no),
                "tipo": a.tipo, "descricao": t.descricao, "forca": a.forca,
                "fonte": a.fonte, "data": a.data, "detalhe": a.detalhe,
                "exculpatoria": t.exculpatoria, "observacoes": a.observacoes,
            })
            no = ant
        passos.reverse()
        forca = 1.0
        for p in passos:
            forca *= p["forca"]
        return {"encontrado": True, "saltos": len(passos), "forca": round(forca, 4),
                "passos": passos,
                "narrativa": narrar(passos),
                "ressalva": ("Vínculo é INDÍCIO. Cada elo traz sua explicação inocente mais "
                             "comum; conferir nos autos antes de afirmar direcionamento.")}

    def grupo(self, origem: str, *, forca_minima: float = 0.5, max_saltos: int = 2) -> list[str]:
        """Entidades alcançáveis por arestas fortes — o "grupo de fato" para fins de checagem."""
        vistos = {origem}
        fronteira = [(origem, 0)]
        while fronteira:
            no, d = fronteira.pop()
            if d >= max_saltos:
                continue
            for viz, a in self.vizinhos(no):
                if a.forca >= forca_minima and viz not in vistos:
                    vistos.add(viz)
                    fronteira.append((viz, d + 1))
        return sorted(vistos - {origem})


def narrar(passos: list[dict]) -> str:
    """A frase que vai para a peça. Sem fonte, a frase não se escreve."""
    if not passos:
        return ""
    partes = []
    for p in passos:
        origem_fonte = f" (fonte: {p['fonte']}{', ' + p['data'] if p['data'] else ''})"
        detalhe = f" — {p['detalhe']}" if p.get("detalhe") else ""
        partes.append(f"{p['de']} → {p['para']}: {p['descricao']}{detalhe}{origem_fonte}")
    return "; ".join(partes)


def mascarar_cpf(texto: str) -> str:
    """CPF mascarado na saída (regra da casa). A base interna segue íntegra."""
    return re.sub(r"\b(\d{3})\.?\d{3}\.?\d{3}-?(\d{2})\b", r"\1.***.***-\2", str(texto or ""))
