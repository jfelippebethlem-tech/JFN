# -*- coding: utf-8 -*-
"""Verificadores puros das regras de qualidade — texto e payload, sem rede, sem banco, sem modelo.

Cada função devolve a LISTA de violações (vazia = conforme). Quem chama decide o que fazer: a catraca barra,
o sensor abre item, o juiz recebe como pré-sinal. Nenhuma função devolve o dado pessoal que encontrou: CPF
sai mascarado na própria mensagem (a mensagem de um verificador vai para log, fila e Telegram).

Todos têm teste de PROVA em `tests/test_regra_verificadores.py` (regra COR-15): o defeito é injetado em
texto sintético e o verificador tem de acusar.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

ESTADOS = ("VERIFICADO", "PENDENTE", "INDISPONIVEL", "REFUTADO")
NATUREZAS = ("pago", "liquidado", "empenhado", "contratado", "teto_de_ata", "estimado", "contagem", "indice")
ESFERAS = ("estadual", "municipal", "federal", "judiciario", "legislativo", "mista_com_quebra")
CAMPOS_PROVENIENCIA = ("fonte", "data_ref", "cobertura", "estado", "natureza", "esfera")

# ───────────────────────────── PAD-03 · moeda ─────────────────────────────
_RE_REAIS = re.compile(r"R\$\s?(?P<num>\d[\d.,]*\d|\d)(?P<abrev>\s?(?:mil|mi|bi|milhões|milhão|bilhões|bilhão)\b)?")
_RE_EXATO = re.compile(r"^\d{1,3}(\.\d{3})*,\d{2}$")
_RE_ABREV = re.compile(r"^\d{1,3}(\.\d{3})*(,\d{1,2})?$")


def moeda_fora_do_padrao(texto: str) -> list[str]:
    """PAD-03: "R$ 1.234.567,89"; abreviado só como "R$ 16,4 mi". Acusa ponto decimal, falta de milhar e de centavos."""
    out = []
    for m in _RE_REAIS.finditer(texto or ""):
        num, abrev = m.group("num"), m.group("abrev")
        if not (_RE_ABREV.match(num) if abrev else _RE_EXATO.match(num)):
            out.append(f"PAD-03 moeda fora do padrão: «{m.group(0).strip()}»")
    return out


# ───────────────────────────── PAD-04 · CPF ─────────────────────────────
_RE_CPF_FMT = re.compile(r"(?<![\d.])(\d{3})\.(\d{3})\.(\d{3})-(\d{2})(?!\d)")
_RE_CPF_CRU = re.compile(r"(?i)\bcpf\b[^\d\n]{0,20}(\d{11})(?!\d)")


def cpf_valido(dig: str) -> bool:
    if len(dig) != 11 or not dig.isdigit() or dig == dig[0] * 11:
        return False
    for n in (9, 10):
        s = sum(int(dig[i]) * (n + 1 - i) for i in range(n))
        if (s * 10 % 11) % 10 != int(dig[n]):
            return False
    return True


def mascarar_cpf(dig: str) -> str:
    return f"***.{dig[3:6]}.{dig[6:9]}-**"


def cpf_exposto(texto: str) -> list[str]:
    """PAD-04/CNF-08: CPF com os 11 dígitos visíveis e dígito verificador válido. A mensagem já sai mascarada."""
    achados = ["".join(m.groups()) for m in _RE_CPF_FMT.finditer(texto or "")]
    achados += [m.group(1) for m in _RE_CPF_CRU.finditer(texto or "")]
    return [f"PAD-04 CPF exposto: {mascarar_cpf(d)}" for d in dict.fromkeys(achados) if cpf_valido(d)]


# ───────────────────────────── PAD-08 · linguagem ─────────────────────────────
TERMOS_ACUSATORIOS = (r"fraudes?", r"fraudulent[oa]s?", r"fantasmas?", r"fachadas?", r"laranjas?", r"desvios?",
                      r"desviad[oa]s?", r"corrup(?:ção|to|ta|tos|tas)", r"crimes?", r"criminos[oa]s?", r"quadrilhas?",
                      r"esquemas?", r"propinas?", r"superfaturad[oa]s?", r"empresas? mortas?")
_RE_ACUSA = re.compile(r"(?i)(?<![\wÀ-ÿ-])(" + "|".join(TERMOS_ACUSATORIOS) + r")(?![\wÀ-ÿ])")
QUALIFICADORES = (r"ind[ií]cios?", r"sina(?:l|is)", r"suspeitas?", r"hip[oó]teses?", r"poss[ií]ve(?:l|is)",
                  r"a verificar", r"a conferir", r"a apurar", r"risco", r"perfil", r"candidat[oa]s?", r"n[aã]o comprovad",
                  r"n[aã]o [eé]", r"sem prova", r"alegad", r"supost", r"potencia(?:l|is)", r"≠", r"nunca", r"score",
                  r"triagem", r"fator(?:es)?", r"apura[cç][aã]o", r"n[aã]o acusa", r"presun")
_RE_QUALIF = re.compile(r"(?i)(" + "|".join(QUALIFICADORES) + r")")
_RE_CORTE = re.compile(r"(?<!\d)[.!?]+(?!\d)|[.!?]+(?=\s|$)|\n|\|")


def frases(texto: str) -> list[str]:
    """Frases de um texto. Ponto entre dígitos ("R$ 10.000,00") não corta; ponto-e-vírgula também não (a ressalva
    costuma vir depois dele, na mesma frase)."""
    return [f for f in _RE_CORTE.split(texto or "") if f and f.strip()]


def linguagem_acusatoria(texto: str) -> list[str]:
    """PAD-08: termo acusatório sem qualificador de indício NA MESMA FRASE. Citação literal de documento
    oficial deve vir marcada entre aspas com a palavra "sic" ou com qualificador — aqui só se mede a frase."""
    out = []
    for fr in frases(texto):
        m = _RE_ACUSA.search(fr)
        if m and not _RE_QUALIF.search(fr):
            out.append(f"PAD-08 linguagem acusatória sem qualificador: «{m.group(1).lower()}» em «{fr.strip()[:70]}»")
    return out


# ───────────────────────────── PAD-01/02/06/07 · proveniência ─────────────────────────────
def estado_invalido(estado: Any) -> list[str]:
    """PAD-02: estado ausente ou fora do vocabulário."""
    if estado is None or str(estado).strip() == "":
        return ["PAD-02 afirmação sem estado (VERIFICADO/PENDENTE/INDISPONIVEL/REFUTADO)"]
    if str(estado).upper().replace("Í", "I") not in ESTADOS:
        return [f"PAD-02 estado fora do vocabulário: «{str(estado)[:30]}»"]
    return []


def proveniencia_incompleta(payload: Any) -> list[str]:
    """PAD-01/02/06/07: o payload de uma manchete traz `proveniencia` com fonte, data_ref, cobertura, estado,
    natureza e esfera — todos preenchidos e dentro do vocabulário."""
    p = payload.get("proveniencia") if isinstance(payload, dict) else None
    if not isinstance(p, dict):
        return ["PAD-01 sem bloco `proveniencia`"]
    out = [f"PAD-01 proveniência sem `{c}`" for c in ("fonte", "data_ref", "cobertura") if not str(p.get(c) or "").strip()]
    out += estado_invalido(p.get("estado"))
    out += natureza_ausente(p.get("natureza"))
    if str(p.get("esfera") or "") not in ESFERAS:
        out.append(f"PAD-06 esfera ausente ou fora do vocabulário: «{str(p.get('esfera') or '')[:30]}»")
    return out


def natureza_ausente(natureza: Any) -> list[str]:
    """PAD-07: o valor diz o que é (pago, liquidado, empenhado, contratado, teto de ata, estimado…)."""
    if str(natureza or "") not in NATUREZAS:
        return [f"PAD-07 natureza do valor ausente ou fora do vocabulário: «{str(natureza or '')[:30]}»"]
    return []


# ───────────────────────────── CNF-01 · estágios da despesa ─────────────────────────────
_RE_PAGO = re.compile(r"(?i)\b(total pago|valor pago|pagos?|pagas?|pagou|pagaram|recebeu|receberam)\b")
_RE_ESTAGIO = re.compile(r"(?i)\b(empenh\w+|liquidad\w+|liquida[cç][aã]o)\b")
_RE_DISTINGUE = re.compile(r"(?i)(≠|n[aã]o [eé]|n[aã]o foi|ainda n[aã]o|diferente|distint|versus|\bx\b|×|sem ob|"
                           r"sem ordem banc|dos quais|, e |; )")


def empenho_como_pago(texto: str) -> list[str]:
    """CNF-01: frase que chama de "pago" o que é empenho ou liquidação (sem distinguir os estágios)."""
    out = []
    for fr in frases(texto):
        if _RE_PAGO.search(fr) and _RE_ESTAGIO.search(fr) and not _RE_DISTINGUE.search(fr):
            out.append(f"CNF-01 estágio da despesa apresentado como pagamento: «{fr.strip()[:80]}»")
    return out


# ───────────────────────────── CNF-09 · culpa ao acesso ─────────────────────────────
_RE_CULPA = re.compile(r"(?i)(acesso negado|sem acesso ao? (sei|siafe)|bloque\w+ (pelo|por|no) (waf|sei|siafe|firewall)|"
                       r"(sei|siafe) (bloqueou|fora do ar|indispon[ií]vel|n[aã]o permite|recusou)|"
                       r"indispon[ií]vel na fonte|barrad[oa] pelo waf)")
_RE_CONTROLE = re.compile(r"(?i)controle positivo")


def culpa_ao_acesso(texto: str) -> list[str]:
    """CNF-09: atribuir a falha ao acesso do SEI/SIAFE sem registrar o controle positivo que prova o bloqueio."""
    if _RE_CONTROLE.search(texto or ""):
        return []
    return [f"CNF-09 falha atribuída ao acesso sem controle positivo: «{m.group(0)[:50]}»"
            for m in _RE_CULPA.finditer(texto or "")][:5]


# ───────────────────────────── COR-08 · ausência como fato ─────────────────────────────
_RE_AUSENCIA = re.compile(r"(?i)\b(n[aã]o h[aá]|n[aã]o existe[m]?|nenhum[a]?|sem|zero|0)\s+"
                          r"(contratos?|ob\b|obs\b|ordens? banc[aá]rias?|pagamentos?|san[cç][aã]o|san[cç][oõ]es|"
                          r"registros?|irregularidades?|v[ií]nculos?)")
_RE_RESSALVA_AUS = re.compile(r"(?i)(controle positivo|indispon[ií]vel|na base|conferid|at[eé] \d|cobertura)")


def ausencia_sem_controle(texto: str) -> list[str]:
    """COR-08: afirmar "não há / sem / zero X" sem dizer o controle ou o limite da base na mesma frase."""
    out = []
    for fr in frases(texto):
        m = _RE_AUSENCIA.search(fr)
        if m and not _RE_RESSALVA_AUS.search(fr):
            out.append(f"COR-08 ausência afirmada sem controle: «{fr.strip()[:80]}»")
    return out


# ───────────────────────────── COR-07 · teto de coleta ─────────────────────────────
TETOS = frozenset({20, 25, 30, 50, 60, 100, 120, 200, 250, 300, 500, 800, 1000, 2000, 2500, 5000, 10000})
_CHAVES_TOTAL = ("n", "total", "n_total", "total_itens", "quantidade", "count", "mostradas", "de")


def contagem_no_teto(n: int, tetos: Iterable[int] = TETOS) -> bool:
    return isinstance(n, int) and n in set(tetos)


def listas_no_teto(payload: Any, caminho: str = "") -> list[str]:
    """COR-07/PAD-05: lista cujo tamanho é um limite conhecido e que não tem, ao lado, o total do universo.
    Com o total ao lado ("N de M") não é violação — é lista cortada e declarada."""
    out = []
    if isinstance(payload, dict):
        tem_total = any(isinstance(payload.get(k), int) and not isinstance(payload.get(k), bool) for k in _CHAVES_TOTAL)
        for k, v in payload.items():
            aqui = f"{caminho}.{k}" if caminho else str(k)
            if isinstance(v, list) and contagem_no_teto(len(v)) and not tem_total:
                out.append(f"COR-07 lista `{aqui}` com {len(v)} itens (tamanho de teto) sem o total ao lado")
            elif isinstance(v, dict):
                out += listas_no_teto(v, aqui)
    return out


# ───────────────────────────── COR-11 · concentração ─────────────────────────────
def concentracao(valores: Iterable[float], k: int = 3) -> float | None:
    """Fração da soma que os `k` maiores respondem. None quando não há o que medir (soma ≤ 0 ou ≤ k itens)."""
    vs = sorted((float(v) for v in valores if isinstance(v, (int, float)) and v > 0), reverse=True)
    total = sum(vs)
    if total <= 0 or len(vs) <= k:
        return None
    return sum(vs[:k]) / total


def concentracao_alta(valores: Iterable[float], k: int = 3, limiar: float = 0.5) -> list[str]:
    c = concentracao(valores, k)
    if c is not None and c >= limiar:
        return [f"COR-11 os {k} maiores registros respondem por {c:.0%} da soma"]
    return []


# ───────────────────────────── CST-02 · variação brusca ─────────────────────────────
def variacao_brusca(anterior: float | None, atual: float | None, limiar: float = 0.25) -> list[str]:
    """CST-02: variou mais que `limiar`, zerou, saiu do zero ou sumiu. None anterior = primeira leitura (sem violação)."""
    if anterior is None:
        return []
    if atual is None:
        return ["CST-02 a manchete deixou de ter valor (era %s)" % _num(anterior)]
    if anterior == atual:
        return []
    if anterior == 0 or atual == 0:
        return [f"CST-02 a manchete foi de {_num(anterior)} para {_num(atual)}"]
    var = (atual - anterior) / abs(anterior)
    if abs(var) > limiar:
        return [f"CST-02 a manchete variou {var:+.0%}: de {_num(anterior)} para {_num(atual)}"]
    return []


def _num(v: float) -> str:
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ───────────────────────────── CST-01 · mesma métrica, mesmo número ─────────────────────────────
def divergencia(a: float | None, b: float | None, tolerancia: float = 0.01) -> list[str]:
    """CST-01: duas superfícies, a mesma métrica. Ausência de um lado NÃO é igualdade — é INDISPONÍVEL."""
    if a is None or b is None:
        return ["CST-01 uma das superfícies não informou o valor (INDISPONÍVEL — não é igualdade)"]
    if abs(float(a) - float(b)) > tolerancia:
        return [f"CST-01 divergência entre superfícies: {_num(float(a))} × {_num(float(b))}"]
    return []


def parte_maior_que_todo(parte: float | None, todo: float | None) -> list[str]:
    """CST-01: uma parcela exibida não pode exceder o total exibido na mesma tela."""
    if parte is None or todo is None:
        return []
    if float(parte) > float(todo) + 0.01:
        return [f"CST-01 a parte ({_num(float(parte))}) é maior que o todo ({_num(float(todo))}) na mesma superfície"]
    return []


# ───────────────────────────── utilitário ─────────────────────────────
def extrair(payload: Any, caminho: str) -> Any:
    """Caminho pontilhado em dict/list ("por_esfera.estado.economia", "achados.0.valor"). None se não existir."""
    cur = payload
    for parte in re.sub(r"\[(-?\d+)\]", r".\1", caminho or "").split("."):
        if parte == "":
            continue
        if isinstance(cur, dict):
            cur = cur.get(parte)
        elif isinstance(cur, list) and parte.lstrip("-").isdigit() and -len(cur) <= int(parte) < len(cur):
            cur = cur[int(parte)]
        else:
            return None
    return cur


def textos(payload: Any, limite: int = 4000) -> list[str]:
    """Todas as strings de um payload (para aplicar verificadores de texto), até `limite` strings."""
    out, pilha = [], [payload]
    while pilha and len(out) < limite:
        v = pilha.pop()
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, dict):
            pilha.extend(v.values())
        elif isinstance(v, list):
            pilha.extend(v)
    return out


def texto_entregue(texto: str) -> list[str]:
    """O pacote aplicado a tudo que é ENTREGUE em texto (resposta, relatório, mensagem)."""
    return (cpf_exposto(texto) + linguagem_acusatoria(texto) + moeda_fora_do_padrao(texto)
            + empenho_como_pago(texto) + culpa_ao_acesso(texto))
