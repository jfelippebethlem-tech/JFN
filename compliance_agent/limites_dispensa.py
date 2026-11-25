# -*- coding: utf-8 -*-
"""limites_dispensa — fonte ÚNICA dos limites de dispensa de licitação (Lei 14.133/2021,
art. 75, I — obras/serviços de engenharia — e II — compras e demais serviços), ano a ano.

Valores verificados VERBATIM no texto dos decretos no Planalto (conferência 2026-07-17;
numérico e por extenso conferem). Atualização anual por IPCA-E (art. 182). Cadeia:
10.922/2021 → 11.317/2022 → 11.871/2023 → 12.343/2024 → 12.807/2025 (cada um revoga o
anterior e vigora a partir de 1º/01 do ano seguinte).

NUNCA duplicar esta tabela em detector — importar daqui (as cópias divergentes em
p4_fracionamento e cruzamentos_intel foram o motivo deste módulo)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

LIMITES: dict[int, dict] = {
    2021: {"obras": 100000.00, "compras": 50000.00,
           "ato": "Lei 14.133/2021, art. 75 (texto original, vigente 01/04-31/12/2021)"},
    2022: {"obras": 108040.82, "compras": 54020.41, "ato": "Decreto 10.922, de 30/12/2021"},
    2023: {"obras": 114416.65, "compras": 57208.33, "ato": "Decreto 11.317, de 29/12/2022"},
    2024: {"obras": 119812.02, "compras": 59906.02, "ato": "Decreto 11.871, de 29/12/2023"},
    2025: {"obras": 125451.15, "compras": 62725.59, "ato": "Decreto 12.343, de 30/12/2024"},
    2026: {"obras": 130984.20, "compras": 65492.11, "ato": "Decreto 12.807, de 29/12/2025"},
}

# ANTES da Lei 14.133 (exercícios < 2021) o teto é o da Lei 8.666/1993, art. 24, I e II (10% do limite do convite
# do art. 23). Sem esta tabela, `limite_dispensa(2019)` devolvia o teto de 2026 (R$ 65.492,11 — 3,7× o legal) e
# contaminava todo detector que roda sobre o SIAFE 1 (2016–2023). Mantida FORA de `LIMITES` de propósito: `LIMITES`
# é a régua da 14.133 (P4 trata exercício anterior a ela como não avaliável) e a catraca de teto copiado lê só ela.
# 2018 é ano partido (Decreto 9.412 vigora 30 dias após 19/06/2018); usa-se o teto MAIOR, que erra para menos achado.
# 2021–2023 a Administração ainda podia optar pela 8.666 (art. 191 da 14.133, até 30/12/2023); a régua devolve o teto
# da 14.133 (maior), sem saber a lei do edital — quem tiver o processo deve ler a lei escolhida.
LIMITES_8666: dict[int, dict] = {
    **{a: {"obras": 15000.00, "compras": 8000.00,
           "ato": "Lei 8.666/1993, art. 24, I e II (redação da Lei 9.648/1998)"} for a in range(1998, 2018)},
    **{a: {"obras": 33000.00, "compras": 17600.00,
           "ato": "Lei 8.666/1993, art. 24, I e II, c/c Decreto 9.412, de 18/06/2018"} for a in range(2018, 2020)},
    # 2020: calamidade da covid — Lei 14.065/2020, art. 1º, I (conversão da MP 961, de 06/05/2020): dispensa dos incisos
    # I e II do art. 24 da 8.666 até R$ 100.000,00 (obras/engenharia) e R$ 50.000,00 (compras/serviços), para os atos
    # praticados na calamidade (até 31/12/2020). Antes de 06/05 valia R$ 33.000/17.600 — usa-se o MAIOR, que erra para
    # menos achado (sem ele, dispensa de R$ 40 mil em 2020 virava "acima do teto").
    2020: {"obras": 100000.00, "compras": 50000.00,
           "ato": "Lei 14.065/2020, art. 1º, I (MP 961/2020 — calamidade covid; antes de 06/05/2020: Decreto 9.412/2018)"},
}


def _info(ano: int) -> dict:
    ano = int(ano)
    if ano < min(LIMITES) and ano in LIMITES_8666:
        return LIMITES_8666[ano]
    return LIMITES.get(ano) or LIMITES[max(LIMITES)]


def limite_dispensa(ano: int, tipo: str = "compras", *, duplicado: bool = False,
                    lei: str | None = None, ente: str | None = None, data_fato: date | None = None) -> float:
    """Limite do exercício (R$). `tipo`: 'compras' (art. 75-II) ou 'obras' (art. 75-I).
    Ano anterior à 14.133 → teto da Lei 8.666 (`LIMITES_8666`); ano posterior à tabela → o mais recente conhecido
    (atualizar a tabela quando sair decreto).

    `duplicado=True` aplica o **art. 75, §2º**: "Os valores referidos nos incisos I e II do caput serão
    DUPLICADOS para compras, obras e serviços contratados por CONSÓRCIO PÚBLICO ou por AUTARQUIA ou
    FUNDAÇÃO qualificadas como AGÊNCIAS EXECUTIVAS." Sem isso, o teto aplicado a esses entes é METADE do
    legal — e o detector acusa fracionamento onde a lei não vê nenhum. (Na 8.666, art. 24 §1º, 20% para
    consórcio público, empresa pública, sociedade de economia mista e agência executiva — o mesmo dobro.)

    O4.5 (SOMBRA ⚖️): com `lei=`, `ente=` ou `data_fato=` a resposta sai de `teto_dispensa` (regime e data do
    fato, nunca o ano corrente) e um teto INDETERMINADO levanta `TetoIndeterminado` em vez de devolver um número.
    SEM esses argumentos o comportamento é exatamente o anterior (teste de paridade sobre todos os chamadores)."""
    if lei is not None or ente is not None or data_fato is not None:
        t = teto_dispensa(lei=lei, tipo=tipo, ano=ano, data_fato=data_fato,
                          ente=ente or ("consorcio_publico" if duplicado else None))
        if t.valor is None:
            raise TetoIndeterminado(t)
        return t.valor
    info = _info(ano)
    return info[tipo] * 2 if duplicado else info[tipo]


def ato_normativo(ano: int) -> str:
    """Decreto/lei que fixa o limite do exercício — para citação em relatório."""
    info = _info(ano)
    return info["ato"]


# ══ O4.5 — teto por LEI, ENTE e DATA DO FATO (⚖️ SOMBRA: nenhum detector chama este caminho ainda) ═══════════════
#
# Cada valor/data abaixo foi conferido VERBATIM nas cópias com md5 de ~/vault/fontes/juridicas/ (INDICE.md), 24/11/2026:
#   D9412.htm (md5 98d2b859033cc6ac943fc661d9f966c8): convite obras "até R$ 330.000,00", compras "até R$ 176.000,00";
#     art. 2º "Este Decreto entra em vigor trinta dias após a data de sua publicação"; "publicado no DOU de 19.6.2018"
#     → vigora em 19/07/2018 (30 dias contados de 19/06; pela contagem da LC 95/1998 art. 8º §1º — não baixada — o
#     último dia é 18/07 e a vigência começa no dia seguinte: as duas contagens dão 19/07/2018).
#   L8666cons.htm (md5 26a008466a58e90b5a2f6cc36e17b050), art. 24 I/II (red. Lei 9.648/1998): "valor até 10% (dez por
#     cento) do limite previsto na alínea 'a'" do art. 23 I/II → R$ 33.000,00 / R$ 17.600,00 (CÁLCULO: 10% do convite,
#     não texto literal do decreto); §1º (red. Lei 11.107/2005, mantida pela 12.715/2012): "serão 20% (vinte por cento)
#     para compras, obras e serviços contratados por consórcios públicos, sociedade de economia mista, empresa pública
#     e por autarquia ou fundação qualificadas [...] como Agências Executivas" (red. 9.648/1998 não tinha consórcio).
#   L14133.htm (md5 5107e213168afb4c15a36665e6695c58), art. 75 I "valores inferiores a R$ 100.000,00 [...] obras e
#     serviços de engenharia ou de serviços de manutenção de veículos automotores"; II "inferiores a R$ 50.000,00";
#     §2º "serão duplicados para [...] consórcio público ou por autarquia ou fundação qualificadas como agências
#     executivas"; §7º "Não se aplica o disposto no § 1º deste artigo às contratações de até R$ 8.000,00 (oito mil reais)
#     de serviços de manutenção de veículos automotores de propriedade do órgão ou entidade contratante, incluído o
#     fornecimento de peças."; art. 1º §1º exclui as estatais (regidas pela 13.303).
#   §7º atualizado (Anexo de cada decreto, "Art. 75, § 7º"): D10922 R$ 8.643,27 · D11317 R$ 9.153,34 · D11871
#     R$ 9.584,97 · D12343 R$ 10.036,10 · D12807 R$ 10.478,74 (vigência 1º/jan do ano seguinte, art. final de cada um).
#   D12807 art. 3º: "Fica delegada à autoridade máxima do Ministério da Gestão e da Inovação em Serviços Públicos a
#     competência para atualizar, nos exercícios subsequentes" → 2027+ por esta via é INDETERMINADO (ato fora da base).
#   L13303.htm (md5 326f5390c34ff235a3aeafa9529d98de), art. 29 I "obras e serviços de engenharia de valor até
#     R$ 100.000,00"; II "outros serviços e compras de valor até R$ 50.000,00"; §3º "Os valores [...] podem ser
#     alterados [...] por deliberação do Conselho de Administração da empresa pública ou sociedade de economia mista,
#     admitindo-se valores diferenciados para cada sociedade." → sem o regulamento da estatal, INDETERMINADO.
#   L14065.htm (md5 e5692eb8a4efa2c2bfae7c5c456632d1), art. 1º I a) "R$ 100.000,00 (cem mil reais), para obras e
#     serviços de engenharia"; b) "R$ 50.000,00 (cinquenta mil reais), para outros serviços e compras"; art. 2º atos
#     "durante o estado de calamidade pública reconhecido pelo Decreto Legislativo nº 6, de 20 de março de 2020".
#   L13979.htm (md5 292ba884095f5df98bd626be465c679b), art. 4º "É dispensável a licitação [...]" sem valor → sem teto.
#
# O4.10 (decisões delegadas D9/D10, 24/11/2026 — ~/vault/refatoracao/RELATORIO-JURIDICO-UNICO-20261124.md §D9/§D10):
#   D9  exercício PARTIDO sem data do fato (2018: D9412 em 19/07; 2020: calamidade do DL 6 em 20/03 e MP 961 publicada
#       em 07/05 — MPV961.htm, art. 3º "Esta Medida Provisória entra em vigor na data de sua publicação"), e ato entre
#       20/03 e 06/05/2020 (a MP manda aplicar-se aos atos da calamidade, mas só existiu a partir de 07/05: retroação
#       sem doutrina nem acórdão que a decida) → teto em FAIXA [menor, maior] dos tetos possíveis. O valor decide: até o
#       menor ("até", inclusivo nas duas leis) está DENTRO sob qualquer data; acima do maior está ACIMA sob qualquer data;
#       entre os dois é INDETERMINADO — nunca o maior por conveniência nem o menor por acusação.
#   D10 a 14.065 (art. 1º I) fixa VALORES absolutos e não repete o "20% (vinte por cento)" do art. 24 §1º da 8.666: para
#       consórcio público e agência executiva na calamidade o teto fica na faixa [valor da 14.065, dobro] — o dobro não
#       é afirmado nem negado.

LIMITES_PAR7: dict[int, dict] = {
    2021: {"valor": 8000.00, "ato": "Lei 14.133/2021, art. 75, §7º (texto original)"},
    2022: {"valor": 8643.27, "ato": "Decreto 10.922, de 30/12/2021 (Anexo, art. 75 §7º)"},
    2023: {"valor": 9153.34, "ato": "Decreto 11.317, de 29/12/2022 (Anexo, art. 75 §7º)"},
    2024: {"valor": 9584.97, "ato": "Decreto 11.871, de 29/12/2023 (Anexo, art. 75 §7º)"},
    2025: {"valor": 10036.10, "ato": "Decreto 12.343, de 30/12/2024 (Anexo, art. 75 §7º)"},
    2026: {"valor": 10478.74, "ato": "Decreto 12.807, de 29/12/2025 (Anexo, art. 75 §7º)"},
}
LIMITES_13303_LEGAL = {"obras": 100000.00, "compras": 50000.00}   # art. 29 I/II — "até" (inclusivo), sem art. 182
LIMITES_14065 = {"obras": 100000.00, "compras": 50000.00}         # art. 1º, I, a/b

VIGENCIA_D9412 = date(2018, 7, 19)
VIGENCIA_14133 = date(2021, 4, 1)
REVOGACAO_8666 = date(2023, 12, 30)
INICIO_CALAMIDADE_2020 = date(2020, 3, 20)
PUBLICACAO_MP961 = date(2020, 5, 7)       # MP 961, de 06/05/2020, DOU de 07/05/2020 (edição extra); art. 3º vigência

_ENTES_DOBRO_14133 = {"consorcio_publico", "agencia_executiva"}                         # art. 75 §2º
_ENTES_20PCT_8666 = {"consorcio_publico", "agencia_executiva", "empresa_publica",
                     "sociedade_economia_mista", "estatal"}                              # art. 24 §1º
_ENTES_ESTATAIS = {"empresa_publica", "sociedade_economia_mista", "estatal"}
ENTES = _ENTES_20PCT_8666 | _ENTES_ESTATAIS | {"administracao_direta", "autarquia", "fundacao"}

_LEI_ALIAS = {"8666": "8666", "L8666": "8666", "10520": "8666", "14133": "14133", "L14133": "14133",
              "13303": "13303", "L13303": "13303", "14065": "14065", "L14065_PANDEMIA": "14065",
              "13979": "13979", "L13979_COVID": "13979"}


class TetoIndeterminado(ValueError):
    """`limite_dispensa(..., lei=/ente=/data_fato=)` sem teto determinável: carrega o `Teto` com o motivo."""

    def __init__(self, teto: "Teto"):
        super().__init__(teto.motivo)
        self.teto = teto


@dataclass(frozen=True)
class Teto:
    """Teto de dispensa por valor. `valor=None` ⇔ `estado` ≠ 'DETERMINADO' (INDETERMINADO ou SEM_TETO).
    `inclusivo`: 8.666/13.303/14.065 dizem "até" (`valor <= teto`); 14.133 diz "inferiores a" (`valor < teto`)."""
    valor: float | None
    estado: str
    lei: str
    tipo: str
    inclusivo: bool | None
    ato: str
    motivo: str = ""
    valor_legal_padrao: float | None = None        # 13.303: o valor do art. 29 quando o conselho não alterou
    ressalvas: tuple[str, ...] = field(default_factory=tuple)
    faixa: tuple[float, float] | None = None       # D9/D10: INDETERMINADO com os tetos possíveis (menor, maior)


def situacao_no_teto(valor: float | None, teto: Teto) -> str:
    """'DENTRO' · 'ACIMA' · 'INDETERMINADO' do valor diante do teto. DETERMINADO compara pela inclusividade da lei;
    FAIXA (D9/D10) só decide quando a resposta é a mesma sob todos os tetos possíveis; o resto é INDETERMINADO."""
    if valor is None:
        return "INDETERMINADO"
    v = round(float(valor), 2)
    if teto.estado == "DETERMINADO" and teto.valor is not None:
        dentro = v <= teto.valor if teto.inclusivo else v < teto.valor
        return "DENTRO" if dentro else "ACIMA"
    if teto.faixa:
        menor, maior = teto.faixa
        if v <= menor:          # D9/D10: todas as leis candidatas dizem "até" (8.666 art. 24, 14.065 art. 1º I)
            return "DENTRO"
        if v > maior:
            return "ACIMA"
    return "INDETERMINADO"


def teto_para_valor(valor: float | None, teto: Teto) -> float | None:
    """O teto que vale PARA ESTE VALOR: o DETERMINADO; na FAIXA, o menor quando o valor está dentro de todos e o
    maior quando está acima de todos (o detector que compara `valor > teto` acerta sob qualquer data); senão None."""
    if teto.estado == "DETERMINADO":
        return teto.valor
    if not teto.faixa:
        return None
    sit = situacao_no_teto(valor, teto)
    return teto.faixa[0] if sit == "DENTRO" else teto.faixa[1] if sit == "ACIMA" else None


def _faixa(lei, tipo, motivo, candidatos, ato, ressalvas=()) -> Teto:
    vs = sorted({round(float(x), 2) for x in candidatos})
    return Teto(None, "INDETERMINADO", lei, tipo, True, ato, motivo, ressalvas=tuple(ressalvas),
                faixa=(vs[0], vs[-1]))


def _indet(lei, tipo, motivo, **kw) -> Teto:
    return Teto(None, "INDETERMINADO", lei, tipo, kw.pop("inclusivo", None), kw.pop("ato", ""), motivo, **kw)


def limite_par7(ano: int) -> float | None:
    """14.133 art. 75 §7º: contratações de manutenção de veículos ATÉ este valor (inclusivo) saem da soma do §1º.
    Exercício fora da tabela → None (2027+ depende de ato do MGI, D12807 art. 3º; antes de 2021 não existia)."""
    info = LIMITES_PAR7.get(int(ano))
    return info["valor"] if info else None


def teto_dispensa(*, lei: str | None, tipo: str = "compras", ano: int | None = None, data_fato: date | None = None,
                  ente: str | None = None) -> Teto:
    """Teto da dispensa POR VALOR para (lei, tipo, ente, data do fato). Função pura; nunca usa o ano corrente.

    lei   '14133' | '8666' (inclui pregão 10.520) | '13303' | '14065' | '13979' — ou o `Regime` de `dominio.regime`.
    tipo  'compras' (14.133 75-II; 8.666 24-II; 13.303 29-II) · 'obras' (inciso I) · 'veiculos' (manutenção de
          veículos automotores: inciso I da 14.133; nas demais leis não há regra própria → 'compras'/'obras' do texto).
    ente  None/'administracao_direta' · 'consorcio_publico' · 'agencia_executiva' · 'empresa_publica' ·
          'sociedade_economia_mista' · 'estatal'.
    data_fato  data do ato da contratação (o que decide 9.412 e 14.065); sem ela vale `ano` (exercício da contratação)."""
    lei_n = _LEI_ALIAS.get(str(lei or "").strip().upper().replace("LEI", "").replace(".", "").strip(),
                           _LEI_ALIAS.get(str(lei or "").strip()))
    if tipo not in ("compras", "obras", "veiculos"):
        raise ValueError(f"tipo desconhecido: {tipo!r}")
    if ente is not None and ente not in ENTES:
        raise ValueError(f"ente desconhecido: {ente!r}")
    if lei_n is None:
        return _indet(str(lei), tipo, "regime da contratação desconhecido — o teto depende da lei (dominio.regime); "
                      "nunca pelo ano corrente")
    a = data_fato.year if data_fato else (int(ano) if ano is not None else None)
    if lei_n == "13979":
        return Teto(None, "SEM_TETO", lei_n, tipo, None, "Lei 13.979/2020, art. 4º",
                    "dispensa covid do art. 4º não tem teto de valor (fora da soma do art. 75 §1º)")
    if ente in _ENTES_ESTATAIS and lei_n != "13303":
        if lei_n == "14133":
            return _indet(lei_n, tipo, "estatal não é regida pela 14.133 (art. 1º §1º): teto da 13.303")
    if lei_n == "13303":
        t = "obras" if tipo in ("obras",) else "compras"
        return _indet(lei_n, tipo, "Lei 13.303 art. 29 §3º: o Conselho de Administração de CADA estatal pode alterar "
                      "os valores; sem o regulamento dela o teto aplicável é INDETERMINADO", inclusivo=True,
                      ato="Lei 13.303/2016, art. 29, " + ("I" if t == "obras" else "II") + " e §3º",
                      valor_legal_padrao=LIMITES_13303_LEGAL[t])
    if a is None:
        return _indet(lei_n, tipo, "sem data do fato nem exercício da contratação")

    if lei_n == "14133":
        if data_fato and data_fato < VIGENCIA_14133 or a < 2021:
            return _indet(lei_n, tipo, "ato anterior à vigência da 14.133 (01/04/2021)")
        if a not in LIMITES:
            return _indet(lei_n, tipo, f"exercício {a} fora da tabela: após 2026 a atualização é ato do MGI "
                          "(D12807 art. 3º), ausente da base", inclusivo=False)
        t = "obras" if tipo in ("obras", "veiculos") else "compras"
        v = LIMITES[a][t] * (2 if ente in _ENTES_DOBRO_14133 else 1)
        ato = LIMITES[a]["ato"] + (" · art. 75 §2º (duplicado)" if ente in _ENTES_DOBRO_14133 else "")
        ress = ()
        if tipo == "veiculos":
            brl = f"{limite_par7(a):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            ress = (f"manutenção de veículos: inciso I; contratações até R$ {brl} saem da soma do §1º "
                    f"(§7º, {LIMITES_PAR7[a]['ato']})",)
        return Teto(round(v, 2), "DETERMINADO", lei_n, tipo, False, ato, "", ressalvas=ress)

    # 8.666 (e 14.065, que é a 8.666 com tetos elevados para atos da calamidade de 2020)
    t = "obras" if tipo == "obras" else "compras"
    if data_fato and data_fato > REVOGACAO_8666:
        return _indet(lei_n, tipo, "contratação direta pela 8.666 depois da revogação (14.133 art. 193, II: "
                      "30/12/2023) — teto da lei antiga não se aplica", inclusivo=True)
    if a < 1999:
        return _indet(lei_n, tipo, "exercício anterior a 1999: redação da Lei 9.648/1998 sem data exata na base",
                      inclusivo=True)
    na_calamidade = bool(data_fato and INICIO_CALAMIDADE_2020 <= data_fato <= date(2020, 12, 31))
    if lei_n == "14065" and not (na_calamidade or (data_fato is None and a == 2020)):
        return _indet(lei_n, tipo, "14.065 declarada para ato fora da calamidade de 2020 (art. 2º)", inclusivo=True)
    dobra_8666 = ente in _ENTES_20PCT_8666 and not (ente == "consorcio_publico" and a < 2005)
    pre_mp = bool(data_fato and data_fato < PUBLICACAO_MP961)
    if (lei_n == "14065" or na_calamidade) and not pre_mp:
        ato14065 = "Lei 14.065/2020, art. 1º, I, " + ("a" if t == "obras" else "b")
        ress = ["fim da calamidade do DL 6/2020 fora da base: aplicado até 31/12/2020"]
        if ente in _ENTES_DOBRO_14133:          # D10: o dobro do art. 24 §1º nem afirmado nem negado
            return _faixa("14065", tipo, "D10: a 14.065 fixa valor absoluto e não repete os 20% do art. 24 §1º da "
                          "8.666 — consórcio/agência executiva na faixa [14.065, dobro]",
                          (LIMITES_14065[t], LIMITES_14065[t] * 2), ato14065 + " × Lei 8.666/1993, art. 24 §1º", ress)
        if ente in _ENTES_20PCT_8666:
            ress.append("a 14.065 não traz o dobro do art. 24 §1º; estatal é regida pela 13.303 desde 01/07/2018")
        return Teto(LIMITES_14065[t], "DETERMINADO", "14065", tipo, True, ato14065, "", ressalvas=tuple(ress))
    base_pre = LIMITES_8666[2019][t] * (2 if dobra_8666 else 1)
    if pre_mp and data_fato >= INICIO_CALAMIDADE_2020:      # D9: calamidade antes da MP 961 existir
        alto = LIMITES_14065[t] * (2 if ente in _ENTES_DOBRO_14133 else 1)
        return _faixa(lei_n, tipo, "D9: ato entre 20/03 e 06/05/2020 — calamidade do DL 6 já reconhecida, MP 961 "
                      "só publicada em 07/05/2020 (art. 3º) e o art. 2º manda aplicá-la aos atos da calamidade: "
                      "retroação sem fonte que a decida → faixa", (base_pre, LIMITES_14065[t], alto),
                      "Lei 8.666/1993, art. 24 × MP 961/2020 (Lei 14.065/2020), art. 1º I e art. 2º")
    if data_fato is None and a == 2018:                      # D9: D9412 em 19/07/2018
        f = 2 if dobra_8666 else 1
        return _faixa(lei_n, tipo, "D9: exercício 2018 partido (Decreto 9.412 em 19/07/2018) sem a data do fato → "
                      "faixa dos dois tetos", (LIMITES_8666[2017][t] * f, LIMITES_8666[2019][t] * f),
                      "Lei 8.666/1993, art. 24 (red. 9.648/1998 × Decreto 9.412/2018)")
    if data_fato is None and a == 2020:                      # D9: calamidade desde 20/03, MP 961 desde 07/05
        alto = LIMITES_14065[t] * (2 if ente in _ENTES_DOBRO_14133 else 1)
        return _faixa(lei_n, tipo, "D9: exercício 2020 partido (calamidade/MP 961 — Lei 14.065) sem a data do fato → "
                      "faixa dos tetos possíveis", (base_pre, LIMITES_14065[t], alto),
                      "Lei 8.666/1993, art. 24 (Decreto 9.412/2018) × Lei 14.065/2020, art. 1º I")
    pos9412 = (data_fato >= VIGENCIA_D9412) if data_fato else (a >= 2019)
    base = LIMITES_8666[2019 if pos9412 else 2017][t]
    ato = ("Lei 8.666/1993, art. 24, " + ("I" if t == "obras" else "II") + " (10% do convite, "
           + ("Decreto 9.412/2018 — cálculo)" if pos9412 else "red. Lei 9.648/1998 — cálculo)"))
    if ente == "consorcio_publico" and a == 2005:
        return _indet(lei_n, tipo, "consórcio público em 2005: o §1º do art. 24 passou a incluí-lo pela Lei 11.107/2005 "
                      "(data exata da vigência não conferida)", inclusivo=True)
    if dobra_8666:
        return Teto(round(base * 2, 2), "DETERMINADO", "8666", tipo, True, ato + " · art. 24 §1º (20%)")
    return Teto(base, "DETERMINADO", "8666", tipo, True, ato)
