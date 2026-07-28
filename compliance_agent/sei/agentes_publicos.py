# -*- coding: utf-8 -*-
"""agentes_publicos — QUEM responde por cada processo: ordenador, gestor, fiscal, pregoeiro, parecerista.

O acervo SEI dizia O QUE foi contratado e POR QUANTO; nunca dizia **quem assinou**. Sem isso, todo
achado morre no órgão: representação ao TCE-RJ pede responsável individualizado (Lei Complementar
RJ 63/1990, art. 6º; Lei 8.443/1992, art. 16 §2º no TCU), e o art. 117 da Lei 14.133/2021 exige
fiscal formalmente designado. Este módulo lê o TEXTO já capturado e devolve pares
**(pessoa, papel)** com o trecho de contexto — indício conferível, nunca acusação.

Núcleo PURO (só texto → estruturas). Quem varre o acervo e grava é `tools/sei_agentes_sweep.py`.

**O que foi aprendido lendo o acervo real** (não a doc — 2.055 processos em `data/sei_arquivo/`):

  1. O papel quase nunca vem colado ao nome numa frase. Vem no **bloco de assinatura**:
         EVERTON MEDEIROS
         Subsecretário de Logística
         Ordenador de Despesas
     Nome em caixa alta, cargo, papel — uma linha cada.
  2. Quando vem inline, é rótulo: `Fiscal: André Luiz Gama Filho`, `Fiscal Técnico: ...`,
     `Gestor do Contrato-GEROSMA`.
  3. Designação formal traz **ID funcional** (7 dígitos + dígito): `Designar o servidor Rodolfo da
     Rocha Varize, Chefe de Serviço, ID funcional nº 5143197-1`. É a identificação forte —
     melhor que o nome, que se repete.
  4. **As armadilhas** (todas colhidas do acervo, todas viram falso positivo se ignoradas):
     `Fiscal - NF 313028` e `Nota Fiscal` (documento fiscal, não pessoa) · `Fiscal - IBS/CBS`
     (reforma tributária) · `FISCAL - Relator: Conselheiro ...` (é do TCE, não do órgão) ·
     `Fiscal – Empresa DIAGNÓSTICA...` (o fiscalizado, não o fiscal).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# --------------------------------------------------------------------------- papéis

PAPEIS = {
    "ordenador_despesa": "Ordenador de Despesas",
    "ordenador_substituto": "Ordenador de Despesas Substituto",
    "gestor_contrato": "Gestor do Contrato",
    "fiscal_contrato": "Fiscal do Contrato",
    "fiscal_tecnico": "Fiscal Técnico",
    "fiscal_administrativo": "Fiscal Administrativo",
    "fiscal_substituto": "Fiscal Substituto",
    "pregoeiro": "Pregoeiro",
    "agente_contratacao": "Agente de Contratação",
    "comissao_licitacao": "Membro de Comissão de Licitação",
    "comissao_fiscalizacao": "Membro de Comissão de Fiscalização",
    "autoridade_homologadora": "Autoridade Homologadora",
    "parecerista_juridico": "Parecerista Jurídico",
}

# Papéis com poder de decisão sobre a despesa — os que o TCE-RJ chama a responder primeiro.
PAPEIS_DECISORIOS = {"ordenador_despesa", "ordenador_substituto", "autoridade_homologadora"}
PAPEIS_FISCALIZACAO = {"gestor_contrato", "fiscal_contrato", "fiscal_tecnico",
                       "fiscal_administrativo", "fiscal_substituto", "comissao_fiscalizacao"}

# Rótulo textual -> papel canônico. Ordem importa: o mais específico primeiro.
_ROTULOS: list[tuple[str, str]] = [
    (r"ordenador(?:a)?\s+de\s+despesas?\s+substitut[oa]", "ordenador_substituto"),
    (r"ordenador(?:a)?\s+de\s+despesas?", "ordenador_despesa"),
    (r"fiscal\s+t[ée]cnic[oa]", "fiscal_tecnico"),
    (r"fiscal\s+administrativ[oa]", "fiscal_administrativo"),
    (r"fiscal\s+substitut[oa]", "fiscal_substituto"),
    (r"gestor(?:a)?\s+d[oe]\s+contrato", "gestor_contrato"),
    (r"fiscal\s+d[oe]\s+contrato", "fiscal_contrato"),
    (r"agente\s+de\s+contrata[çc][ãa]o", "agente_contratacao"),
    (r"pregoeir[oa]", "pregoeiro"),
    (r"comiss[ãa]o\s+de\s+licita[çc][ãa]o", "comissao_licitacao"),
    (r"comiss[ãa]o\s+de\s+(?:acompanhamento[^\n]{0,40})?(?:gest[ãa]o\s+e\s+)?fiscaliza[çc][ãa]o",
     "comissao_fiscalizacao"),
    (r"procurador(?:a)?\s+do\s+estado", "parecerista_juridico"),
    (r"\bfiscal\b", "fiscal_contrato"),
]
_ROTULOS_RE = [(re.compile(p, re.IGNORECASE), papel) for p, papel in _ROTULOS]

# --------------------------------------------------------------------------- nomes

# Nome de pessoa: 2 a 6 palavras capitalizadas ou em caixa alta, aceitando conectivos.
# O separador é [ \t]+, NUNCA \s+: com \s+ o nome atravessa a quebra de linha e cola pedaços de
# duas frases ("Aquisição de Motos Aquáticas\nAnexos" virou nome de fiscal na primeira medição).
_PALAVRA = r"[A-ZÀ-Ý][A-Za-zà-ÿ']+"
_CONECT = r"(?:d[aeoi]s?|e|del|van|von)"
_NOME = rf"{_PALAVRA}(?:[ \t]+(?:{_CONECT}|{_PALAVRA})){{1,5}}"
_RE_NOME_LINHA = re.compile(rf"^\s*({_NOME})\s*$")

# GRAFIAS MEDIDAS NO ACERVO (2026-07-28). A régua antiga exigia a palavra "funcional" e falhava
# em 128 dos 317 agentes sem ID — e nesses 128 o ID ESTAVA no contexto capturado. Ou seja, 40%
# das "ausências" eram falha de extração. As formas contadas: "ID:" sozinho (22×), "Id. Funcional:"
# (9×), "ID. Funcional nº" (4×), "– ID:" (6×), além de "IDENTIFICAÇÃO FUNCIONAL Nº".
#
# O ID funcional do Estado tem 6 a 8 dígitos + dígito verificador. Exigir o hífen com o
# verificador é o que separa ID de número de processo, valor e CPF — daí `-\d` obrigatório.
_RE_ID_FUNCIONAL = re.compile(
    r"\b(?:id|identifica[cç][aã]o)\.?\s*(?:[\s\-–]*funcional)?\s*[:\-–]?\s*n?[ºo°.]*\s*"
    r"(\d{6,8}-\d)\b",
    re.IGNORECASE)
# Matrícula aparece com separador de milhar no acervo ("Matrícula 27.646-9"), que o padrão
# anterior não previa — o `\d{4,10}` parava no ponto e devolvia None.
_RE_MATRICULA = re.compile(r"matr[íi]cula\s*n?[ºo°.]*\s*(\d{1,3}(?:\.\d{3})+-?\d?|\d{4,10}-?\d?)",
                           re.IGNORECASE)

# Rótulo seguido de nome na mesma linha: "Fiscal: Fulano", "Gestor do Contrato - Beltrano".
_RE_ROTULO_NOME = re.compile(
    rf"(?P<rotulo>ordenador(?:a)? de despesas?(?: substitut[oa])?|gestor(?:a)? d[oe] contrato|"
    rf"fiscal(?: t[ée]cnic[oa]| administrativ[oa]| substitut[oa]| d[oe] contrato)?|pregoeir[oa]|"
    rf"agente de contrata[çc][ãa]o)\s*[:\-–—]\s*(?P<nome>{_NOME})",
    re.IGNORECASE)

# "Designar o servidor Fulano de Tal, Chefe de Serviço, ID funcional nº 5143197-1"
_RE_DESIGNACAO = re.compile(
    rf"designa(?:r|ndo|o)\s+(?:a\s+|o\s+)?(?:servidor(?:a)?|agente|empregad[oa])?\s*"
    rf"(?P<nome>{_NOME})",
    re.IGNORECASE)

# --------------------------------------------------------------------------- ruído

# Cada padrão foi colhido do acervo real. Um "Fiscal" seguido destes NÃO é pessoa.
_RUIDO_APOS_FISCAL = re.compile(
    r"^\s*[:\-–—]?\s*(?:NFs?\b|nota\s+fiscal|IBS|CBS|eletr[ôo]nic|de\s+servi[çc]o|"
    r"relator|relatora|empresa\b|certid|/\s*NF|n[ºo°]\s*\d)",
    re.IGNORECASE)

# Guarda mais forte que a lista de ruído: se vem "Nota" (ou "danfe"/"cupom") imediatamente ANTES
# de "Fiscal", trata-se de DOCUMENTO fiscal — nunca de pessoa. Foi assim que "NFs Consig" entrou
# como fiscal de contrato em 6 processos: o título do documento era "Nota Fiscal - NFs Consig", e
# a lista de ruído só barrava "NF" com limite de palavra (o "s" de "NFs" furava o \b).
_DOCUMENTO_FISCAL_ANTES = re.compile(r"(?:nota|danfe|cupom|documento)\s*$", re.IGNORECASE)

# Palavras que nunca compõem nome de pessoa (colhidas de falsos positivos reais).
_NAO_NOME = {
    "nota", "fiscal", "empresa", "contrato", "processo", "estado", "governo", "secretaria",
    "servico", "servicos", "diretoria", "gerencia", "subsecretaria", "conselheiro", "conselheira",
    "relator", "relatora", "ltda", "eireli", "sa", "me", "epp", "rio", "janeiro", "lei",
    "decreto", "portaria", "artigo", "art", "anexo", "termo", "referencia", "objeto", "valor",
    "data", "id", "funcional", "matricula", "cpf", "cnpj", "sei", "doc", "documento", "pagina",
    "comissao", "gestao", "fiscalizacao", "despesa", "despesas", "ordenador", "gestor",
    "pregoeiro", "presidente", "diretor", "diretora", "chefe", "coordenador", "coordenadora",
    "subsecretario", "subsecretaria", "secretario", "secretaria", "assessor", "assessora",
    # postos/graduações e siglas que aparecem no lugar do nome ("Maj PM De" foi extraído como
    # gestor na primeira passada pelo acervo)
    "maj", "cel", "ten", "cap", "sgt", "sd", "pm", "bm", "tcel", "major", "coronel", "capitao",
    "tenente", "sargento", "resolucao", "segov", "substituto", "substituta", "aquisicao", "anexos",
}

# Nome exige ao menos DUAS palavras com 3+ letras: mata "Maj PM De" e siglas soltas.
_MIN_PALAVRAS_LONGAS = 2


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s or "")
                   if unicodedata.category(c) != "Mn").lower()


def nome_plausivel(nome: str) -> bool:
    """Filtra o que a regex de nome pega mas não é gente.

    Regra: ao menos duas palavras de conteúdo e nenhuma delas do vocabulário institucional.
    'Nota Fiscal', 'Comissão de Fiscalização' e 'Secretaria de Estado' morrem aqui.
    """
    if "\n" in nome or "\r" in nome:
        return False
    partes = [p for p in _sem_acento(nome).split() if len(p) > 1 and p not in
              {"da", "de", "do", "das", "dos", "e", "del", "van", "von"}]
    if len(partes) < 2:
        return False
    if sum(1 for p in partes if len(p) >= 3) < _MIN_PALAVRAS_LONGAS:
        return False
    return not any(p in _NAO_NOME for p in partes)


# --------------------------------------------------------------------------- extração

@dataclass
class AgenteEncontrado:
    nome: str
    papel: str                      # chave de PAPEIS
    id_funcional: str | None = None
    matricula: str | None = None
    cargo: str | None = None
    contexto: str = ""              # trecho para conferência humana
    origem: str = ""                # como foi identificado: rotulo | assinatura | designacao
    documento: str | None = None    # nº/ nome do doc SEI onde apareceu

    @property
    def papel_legivel(self) -> str:
        return PAPEIS.get(self.papel, self.papel)

    @property
    def decisorio(self) -> bool:
        return self.papel in PAPEIS_DECISORIOS

    def chave(self) -> tuple:
        """Identidade para deduplicar: ID funcional manda; sem ele, nome normalizado."""
        return (self.id_funcional or _sem_acento(self.nome), self.papel)


def _papel_do_rotulo(rotulo: str) -> str | None:
    for rx, papel in _ROTULOS_RE:
        if rx.search(rotulo):
            return papel
    return None


def _identificadores(janela: str) -> tuple[str | None, str | None]:
    idf = _RE_ID_FUNCIONAL.search(janela)
    mat = _RE_MATRICULA.search(janela)
    return (idf.group(1) if idf else None, mat.group(1) if mat else None)


def _por_rotulo(texto: str) -> list[AgenteEncontrado]:
    """`Fiscal: Fulano` / `Ordenador de Despesas - Beltrano`."""
    achados = []
    for m in _RE_ROTULO_NOME.finditer(texto):
        # ruído: "Fiscal - NF 313028", "Fiscal – Empresa X", "FISCAL - Relator"
        resto = texto[m.end("rotulo"):m.end("rotulo") + 40]
        if _RUIDO_APOS_FISCAL.match(resto):
            continue
        # "Nota Fiscal - <qualquer coisa>" é documento, não pessoa
        if _DOCUMENTO_FISCAL_ANTES.search(texto[max(0, m.start() - 12):m.start()]):
            continue
        nome = m.group("nome").strip()
        if not nome_plausivel(nome):
            continue
        papel = _papel_do_rotulo(m.group("rotulo"))
        if not papel:
            continue
        janela = texto[max(0, m.start() - 150):m.end() + 200]
        idf, mat = _identificadores(janela)
        achados.append(AgenteEncontrado(
            nome=nome, papel=papel, id_funcional=idf, matricula=mat,
            contexto=re.sub(r"\s+", " ", texto[max(0, m.start() - 80):m.end() + 80]).strip(),
            origem="rotulo"))
    return achados


def _por_assinatura(texto: str) -> list[AgenteEncontrado]:
    """Bloco de assinatura: NOME / cargo / papel, uma linha cada.

    É o padrão dominante em ato de homologação, despacho e publicação no D.O. Varre-se de baixo
    para cima a partir da linha do papel: as 3 linhas acima carregam cargo e nome.
    """
    achados = []
    linhas = texto.splitlines()
    for i, linha in enumerate(linhas):
        alvo = linha.strip()
        if not alvo or len(alvo) > 70:
            continue
        papel = None
        for rx, p in _ROTULOS_RE:
            if rx.fullmatch(alvo.strip(" .:-–—")):
                papel = p
                break
        if not papel:
            continue
        nome = cargo = None
        for j in range(i - 1, max(-1, i - 4), -1):
            cand = linhas[j].strip()
            if not cand:
                continue
            m = _RE_NOME_LINHA.match(cand)
            if m and nome_plausivel(m.group(1)):
                nome = m.group(1).strip()
                break
            if cargo is None and len(cand) <= 70:
                cargo = cand
        if not nome:
            continue
        janela = "\n".join(linhas[max(0, i - 6):i + 3])
        idf, mat = _identificadores(janela)
        achados.append(AgenteEncontrado(
            nome=nome, papel=papel, id_funcional=idf, matricula=mat, cargo=cargo,
            contexto=re.sub(r"\s+", " ", janela).strip(), origem="assinatura"))
    return achados


def _por_designacao(texto: str) -> list[AgenteEncontrado]:
    """`Designar o servidor Fulano, Chefe de Serviço, ID funcional nº 5143197-1` — designação formal.

    O papel vem do CONTEXTO da frase (o verbo designar não diz para quê), então só se registra
    quando há rótulo de papel na mesma janela. Sem papel identificado, nada é inventado.
    """
    achados = []
    for m in _RE_DESIGNACAO.finditer(texto):
        nome = m.group("nome").strip()
        if not nome_plausivel(nome):
            continue
        janela = texto[max(0, m.start() - 250):m.end() + 250]
        papel = None
        for rx, p in _ROTULOS_RE:
            if rx.search(janela):
                papel = p
                break
        if not papel:
            continue
        idf, mat = _identificadores(texto[m.end():m.end() + 160])
        cargo = None
        cm = re.match(r"\s*,\s*([^,\n]{3,50})\s*,", texto[m.end():m.end() + 60])
        if cm:
            cargo = cm.group(1).strip()
        achados.append(AgenteEncontrado(
            nome=nome, papel=papel, id_funcional=idf, matricula=mat, cargo=cargo,
            contexto=re.sub(r"\s+", " ", texto[max(0, m.start() - 80):m.end() + 120]).strip(),
            origem="designacao"))
    return achados


def extrair_agentes(texto: str, documento: str | None = None) -> list[AgenteEncontrado]:
    """Todos os agentes públicos identificáveis num documento, deduplicados.

    Preferência na deduplicação: quem trouxe ID funcional vence (identificação forte).
    """
    brutos = _por_rotulo(texto) + _por_assinatura(texto) + _por_designacao(texto)
    melhores: dict[tuple, AgenteEncontrado] = {}
    for a in brutos:
        a.documento = documento
        k = a.chave()
        atual = melhores.get(k)
        if atual is None or (a.id_funcional and not atual.id_funcional):
            melhores[k] = a
    return list(melhores.values())


# --------------------------------------------------------------------------- leitura do processo

@dataclass
class FichaResponsabilidade:
    """Quem responde pelo processo, por papel — e o que FALTA."""
    processo: str
    agentes: list[AgenteEncontrado] = field(default_factory=list)
    lacunas: list[str] = field(default_factory=list)
    alertas: list[str] = field(default_factory=list)

    def por_papel(self, papel: str) -> list[AgenteEncontrado]:
        return [a for a in self.agentes if a.papel == papel]

    @property
    def decisores(self) -> list[AgenteEncontrado]:
        return [a for a in self.agentes if a.decisorio]


def montar_ficha(processo: str, documentos: dict[str, str]) -> FichaResponsabilidade:
    """`documentos` = {nome_ou_numero_do_doc: texto}. Devolve quem responde e o que falta.

    Duas verificações nascem daqui, ambas com fundamento legal expresso:

      * **Fiscal não designado** — há execução (medição/liquidação/nota fiscal) mas nenhum fiscal
        ou gestor identificado. Art. 117 da Lei 14.133/2021 exige representante designado; a
        ausência é vício autônomo, não mera formalidade.
      * **Segregação de funções** — a mesma pessoa aparece como ordenador E como fiscal/gestor.
        Quem autoriza a despesa não pode atestar a própria execução (art. 5º da Lei 14.133;
        princípio da segregação de funções).

    Honesto: LACUNA DE CAPTURA ≠ INEXISTÊNCIA. Se nenhum documento de designação foi capturado,
    a ficha diz que não achou — e manda conferir, não acusa.
    """
    # Entidade HTML crua no acervo ("Subsecret&aacute;rio") quebra o casamento de nome e o
    # agente inteiro se perde. Medido em 2026-07-28: 1% dos processos, mas concentrado em
    # despacho e portaria — que é exatamente onde os responsáveis aparecem.
    import html as _html
    documentos = {k: _html.unescape(v or "") for k, v in (documentos or {}).items()}
    ficha = FichaResponsabilidade(processo=processo)
    marcas_execucao = re.compile(
        r"medi[çc][ãa]o|liquida[çc][ãa]o|nota\s+fiscal|aceite\s+definitivo|recebimento\s+definitivo",
        re.IGNORECASE)
    tem_execucao = False

    for doc, texto in (documentos or {}).items():
        ficha.agentes.extend(extrair_agentes(texto or "", documento=doc))
        if marcas_execucao.search(texto or ""):
            tem_execucao = True

    # dedup entre documentos, preservando o primeiro documento em que apareceu
    vistos: dict[tuple, AgenteEncontrado] = {}
    for a in ficha.agentes:
        k = a.chave()
        if k not in vistos or (a.id_funcional and not vistos[k].id_funcional):
            vistos[k] = a
    ficha.agentes = list(vistos.values())

    fiscalizadores = [a for a in ficha.agentes if a.papel in PAPEIS_FISCALIZACAO]
    if tem_execucao and not fiscalizadores:
        ficha.lacunas.append(
            "Há atos de execução contratual (medição/liquidação/nota fiscal) e NENHUM fiscal ou "
            "gestor de contrato identificado nos documentos capturados. Art. 117 da Lei 14.133/2021 "
            "exige representante da Administração formalmente designado. Conferir se o ato de "
            "designação existe e não foi capturado antes de tratar como vício."
        )
    if not ficha.decisores:
        ficha.lacunas.append(
            "Nenhum ordenador de despesas ou autoridade homologadora identificado — sem ele a "
            "representação ao TCE-RJ não individualiza responsável."
        )

    chaves_decisor = {_sem_acento(a.nome) for a in ficha.decisores}
    for a in fiscalizadores:
        if _sem_acento(a.nome) in chaves_decisor:
            ficha.alertas.append(
                f"SEGREGAÇÃO DE FUNÇÕES: '{a.nome}' aparece como ordenador/autoridade E como "
                f"{a.papel_legivel}. Quem autoriza a despesa não deve atestar a própria execução "
                f"(art. 5º da Lei 14.133/2021). Indício — confirmar homonímia pelo ID funcional."
            )
    return ficha


def resumo_texto(ficha: FichaResponsabilidade) -> str:
    """Bloco pronto para o dossiê/parecer."""
    if not ficha.agentes and not ficha.lacunas:
        return ""
    linhas = [f"**Responsáveis identificados — processo {ficha.processo}**", ""]
    if ficha.agentes:
        linhas.append("| Papel | Nome | ID funcional | Cargo | Origem |")
        linhas.append("|---|---|---|---|---|")
        for a in sorted(ficha.agentes, key=lambda x: (not x.decisorio, x.papel, x.nome)):
            linhas.append(f"| {a.papel_legivel} | {a.nome} | {a.id_funcional or '—'} | "
                          f"{a.cargo or '—'} | {a.origem} |")
    for al in ficha.alertas:
        linhas += ["", f"> ⚠️ {al}"]
    for lac in ficha.lacunas:
        linhas += ["", f"> ⓘ {lac}"]
    return "\n".join(linhas)
