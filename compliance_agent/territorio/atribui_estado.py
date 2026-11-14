# -*- coding: utf-8 -*-
"""(A) Contratos do ESTADO do RJ → município de EXECUÇÃO.

BASE: `compliance.db.pcrj_contratos` com `orgao_cnpj` = CNPJ do Estado (42.498.600/0001-71), das DUAS
coletas do PNCP (`fonte` 'pncp_estado' e 'pncp' — até 14/11/2026 só a primeira entrava: 4.910 contratos,
R$ 6,12 bi, ficavam fora), somada ao SIGA/TCE-RJ (`contratos_tcerj`). Ficam FORA, por decisão do brief:
  · unidades MUNICIPAIS que o PNCP pendura no CNPJ do Estado (prefeituras, fundos, autarquias e
    institutos de previdência municipais) — é exatamente o "contrato de prefeitura" que o dono não quer;
  · órgãos que não são do Poder Executivo (TJRJ, MPRJ, TCE-RJ, DPE, ALERJ) e entes de outra esfera;
  · do SIGA: registro Cancelado e registro ainda em elaboração (`_SIGA_RASCUNHO`) — contados em `territorio_meta`.
JUNÇÃO PNCP × SIGA (`_integrar_tcerj`): um para um, por CNPJ + valor ±1% + data coincidente (≤ 7 dias). A regra
anterior (valor ±10%, primeiro candidato, sem limite) fazia 3.021 contratos do PNCP engolirem 6.895 registros
do SIGA (R$ 3,43 bi sumiam). O que parece o mesmo contrato e não fecha a chave fica contado nas duas fontes e
é DECLARADO (`estado_possivel_duplicidade`).

GRAU DE CERTEZA (coluna `grau`): `explicito` (município, distrito, bairro ou CEP escrito no texto) ·
`unidade` (inferido de unidade de endereço conhecido: compradora de sítio único ou citada no objeto) ·
`sede` (objeto da própria organização — atribuído ao município da sede do órgão, o grau mais fraco).

ATRIBUIÇÃO, por ordem de força (guarda TODOS os métodos que acertaram; decide pelo mais forte):
  1. campo     unidade compradora de SÍTIO ÚNICO (`dados/unidades_regionais.csv`). Sede de órgão NÃO
               é local de execução: quase toda secretaria tem sede na capital.
  2. orçamento regionalização do empenho no SIAFE — SEM DADO LOCAL (as tabelas SIAFE coletadas não
               trazem localizador/subtítulo). O método existe no desenho e devolve nada: INDISPONÍVEL.
  3. unidade   o objeto cita unidade estadual de endereço conhecido (`data/territorio_unidades.csv`,
               montado dos locais de votação do TSE: colégios estaduais, CIEPs, escolas técnicas).
  4. endereço  CEP no objeto — só a faixa da capital (20000-000 a 23799-999) é resolvida aqui.
  5. texto     dicionário dos 92 municípios (`dicionario.py`), com as armadilhas tratadas.

  6. sede      só quando nada acima casou E o objeto é da organização (serviço "na sede", tecnologia
               corporativa, despesa administrativa, órgão-meio): município da sede em `dados/sedes_orgaos.csv`
               (cadastro de unidades do PNCP). Órgão de sede divergente/não conferida fica SEM município.

Vários municípios → `multi=1`, lista guardada, VALOR NÃO DIVIDIDO. Sem município → fica sem.
STATUS: `rescindido` (termo de rescisão) · `em_execucao` (vigência final, com aditivos de prazo,
≥ hoje) · `executado` · `sem_vigencia` (a fonte não registra fim de vigência: não entra em "vigentes").
PAGO = o da perícia contábil (`pericia_contabil.avaliar_estado`, fonte única da casa): OB do SIAFE
Contabilizada do MESMO processo SEI ao MESMO CNPJ (ou vinculada pelos autos, VERIFICADO), sem a OB devolvida
pelo banco e sem a anterior ao contrato. Sem vínculo → NULL com o motivo (a tela diz INDISPONÍVEL, nunca 0).
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
from datetime import date
from pathlib import Path

from compliance_agent.territorio import base
from compliance_agent.territorio.dicionario import ler_municipios
from compliance_agent.territorio.geo import RIO, nome_municipio, norm

CNPJ_ESTADO = "42498600000171"
FONTE = "PNCP + TCE-RJ/SIGA + DOERJ — contratos do Estado do RJ (Poder Executivo)"
_DADOS = Path(__file__).resolve().parent / "dados"
FORCA = {"campo": 5, "orcamento": 4, "unidade": 3, "endereco": 2, "texto": 1, "sede": 0}
GRAU = {"campo": "unidade", "orcamento": "unidade", "unidade": "unidade", "endereco": "explicito", "texto": "explicito",
        "sede": "sede"}
GRAUS = ("explicito", "unidade", "sede")
# SIGA/TCE-RJ: registro que ainda não é contrato (em elaboração) e registro cancelado ficam fora, CONTADOS
_SIGA_RASCUNHO = ("Em Edição", "Em Aprovação", "Aguard. Liberação")
_SIGA_FORA = ("Cancelado",) + _SIGA_RASCUNHO


def reparar_texto(s: str | None) -> str:
    """O SIGA/TCE-RJ entrega 1.756 objetos com 'ã'/'õ' trocados por '?' ("EXECUC?O", "S?O GONCALO", "AC?ES"):
    sem o reparo, "S?O GONCALO" normaliza para "S O GONCALO" e o município some. Só mexe em '?' entre letras."""
    if not s or "?" not in s:
        return s or ""
    s = re.sub(r"(?<=[A-Za-z])\?(?=[Oo][Ss]?(?![A-Za-z]))", "A", s)        # ?O / ?OS → ÃO / ÃOS
    s = re.sub(r"(?<=[A-Za-z])\?(?=[Ee][Ss](?![A-Za-z]))", "O", s)         # ?ES → ÕES
    return re.sub(r"(?<=[Mm])\?(?=[Ee](?![A-Za-z]))", "A", s)              # M?E → MÃE

_RE_MUNICIPAL = re.compile(r"\bPREF\b|PREFEITURA|MUNICIP|\bMUN\b|\bCAMARA\b|\bSAAE\b|SERV(?:ICO)? AUT|OSTRASPREV")
# não são do Executivo estadual (ou são de outra esfera) e não trazem "municipal" no nome
_FORA = [r"CONSORCIO INT", r"CONSELHO DE ARQUITETURA", r"DEFENSORIA PUBLICA", r"TRIBUNAL", r"MINISTERIO PUBLICO",
         r"ASSEMBLEIA LEGISLATIVA"]
_RE_FORA = re.compile("|".join(_FORA))


def esfera_unidade(unidade: str | None) -> str:
    """'estadual' | 'municipal' | 'outro' para a unidade compradora do PNCP."""
    u = norm(unidade)
    if not u:
        return "estadual"
    if _RE_MUNICIPAL.search(u):
        return "municipal"
    if _RE_FORA.search(u):
        return "outro"
    # autarquia/fundação/instituto com nome de município (≠ capital) e sem marca de "estado" → municipal
    if not re.search(r"\bEST\b|ESTADO|ESTADUAL|\bERJ\b|NORTE FLUMINENSE", u):
        achou = [a for a in ler_municipios(unidade).municipios if a.cod_ibge != RIO]
        if achou or u == "PORTO REAL":
            return "municipal"
    return "estadual"


def _unidades_regionais() -> list[tuple[str, str, str, str]]:
    with open(_DADOS / "unidades_regionais.csv", encoding="utf-8") as f:
        return [(r["padrao"], r["cod_ibge"], r["confianca"], r["fonte"]) for r in csv.DictReader(f)]


# ── método `unidade`: cadastro de unidades estaduais com município conhecido ─────────────────────
_RE_ESCOLA = re.compile(r"^(COLEGIO ESTADUAL|ESCOLA ESTADUAL|ESCOLA TECNICA ESTADUAL|INSTITUTO DE EDUCACAO|C E|E E|CE|EE|CIEP|"
                        r"ETE|FAETEC|CEJA|CENTRO DE EDUCACAO DE JOVENS E ADULTOS)\b ?(.*)$")
_GATILHO = re.compile(r"\b(COLEGIO ESTADUAL|ESCOLA ESTADUAL|ESCOLA TECNICA ESTADUAL|INSTITUTO DE EDUCACAO|CIEP|C E|E E|ETE|FAETEC|CEJA)\b")


def montar_unidades(log=print) -> Path | None:
    """`data/territorio_unidades.csv`: nome normalizado → cod_ibge, a partir dos locais de votação do
    TSE (são prédios públicos com município). Só entra nome que existe em UM município só."""
    origem = base.DATA / "tse_cache" / "eleitorado_local_votacao_2026_RJ.csv"
    destino = base.DATA / "territorio_unidades.csv"
    if not origem.exists():
        log(f"[unidades] {origem.name} ausente — método `unidade` fica sem cadastro (INDISPONÍVEL)")
        return destino if destino.exists() else None
    por_nome = {norm(n): c for c, n in nome_municipio().items()}
    por_nome.update({"PARATI": "3303807", "TRAJANO DE MORAIS": "3305901"})
    achados: dict[str, set] = {}
    with open(origem, encoding="latin-1", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            cod = por_nome.get(norm(r.get("NM_MUNICIPIO")))
            n = norm(r.get("NM_LOCAL_VOTACAO"))
            m = _RE_ESCOLA.match(n)
            if not cod or not m:
                continue
            tipo, resto = m.group(1), m.group(2).strip()
            chaves = set()
            if tipo == "CIEP":
                num = re.match(r"(?:BRIZOLAO )?(\d{2,3})\b", resto)
                if num:
                    chaves.add(f"CIEP {num.group(1)}")           # a numeração dos CIEPs é única no estado
                    chaves.add(f"CIEP BRIZOLAO {num.group(1)}")
            elif len(resto) >= 8 and " " in resto:                 # nome próprio com 2+ palavras
                base_tipo = {"C E": "COLEGIO ESTADUAL", "CE": "COLEGIO ESTADUAL", "E E": "ESCOLA ESTADUAL",
                             "EE": "ESCOLA ESTADUAL"}.get(tipo, tipo)
                chaves.add(f"{base_tipo} {resto}")
                if base_tipo == "COLEGIO ESTADUAL":
                    chaves.update({f"C E {resto}", f"CE {resto}"})
                if base_tipo == "ESCOLA ESTADUAL":
                    chaves.update({f"E E {resto}", f"EE {resto}"})
            for k in chaves:
                achados.setdefault(k, set()).add(cod)
    unicos = sorted((k, next(iter(v))) for k, v in achados.items() if len(v) == 1)
    with open(destino, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["nome_norm", "cod_ibge", "fonte"])
        for k, cod in unicos:
            w.writerow([k, cod, "TSE — locais de votação 2026 (prédio público com município)"])
    log(f"[unidades] {len(unicos)} nomes únicos gravados em {destino.name} "
        f"({sum(1 for v in achados.values() if len(v) > 1)} descartados por existir em mais de um município)")
    return destino


_GATILHO_SAUDE = re.compile(r"\b(HOSPITAL|HOSP|UPA|INSTITUTO ESTADUAL|POLICLINICA|MATERNIDADE|PRONTO SOCORRO|HEMORIO|IECAC|IEDE)\b")
_RE_UPA = re.compile(r" (?:UNIDADE DE PRONTO ATENDIMENTO(?: UPA)?|UPA)(?: 24 ?HS?| 24 ?HORAS)?(?: D[EAO])? ")
_RE_DP = re.compile(r"\b0*(\d{1,3}) ?A? (?:DP|DELEGACIA DE POLICIA|DELEGACIA POLICIAL|DELEGACIA LEGAL)\b")
_RE_BPM = re.compile(r"\b0*(\d{1,2}) ?O? (?:BPM|BATALHAO DE POLICIA MILITAR)\b")


def carregar_unidades() -> dict:
    """Cadastros do método `unidade`: {"escolas": [(nome, cod)], "saude": [(nome, cod)], "dp": {n: cod}, "bpm": {n: cod}}.
    Fontes: TSE (escolas, cadastro local), CNES (saúde) e ISP-RJ (delegacias e batalhões) — ver `tools/v61_territorio_fontes.py`."""
    out = {"escolas": [], "saude": [], "dp": {}, "bpm": {}, "siglas": {}, "upas": []}
    p = base.DATA / "territorio_unidades.csv"
    if p.exists():
        with open(p, encoding="utf-8") as f:
            out["escolas"] = [(r["nome_norm"], r["cod_ibge"]) for r in csv.DictReader(f)]
    with open(_DADOS / "cnes_unidades.csv", encoding="utf-8") as f:
        # nome de 3+ palavras: "HOSPITAL ESTADUAL AZEVEDO LIMA" entra; "UPA CENTRO" (2) não — curto demais para ser inequívoco
        cnes = list(csv.DictReader(f))
    saude = {}
    for r in cnes:
        n = r["nome_norm"]
        if len(n.split()) >= 3:
            saude.setdefault(n, r["cod_ibge"])
            sem_titulo = re.sub(r" (?:DR|DRA|PROF|PROFA|PREF|GOV|VER|DEP|SEN) ", " ", n)      # "Hospital Estadual [Dr] Ricardo Cruz"
            if sem_titulo != n and len(sem_titulo.split()) >= 3:
                saude.setdefault(sem_titulo, r["cod_ibge"])
    # siglas de uso (HERCRUZ, IECAC…): o MUNICÍPIO vem do CNES — a tabela só liga a sigla ao nome
    with open(_DADOS / "siglas_saude.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            alvo = {x["cod_ibge"] for x in cnes if r["fragmento_cnes"] in x["nome_norm"]}
            if len(alvo) == 1:
                out["siglas"][r["sigla"]] = next(iter(alvo))
    out["saude"] = sorted(saude.items(), key=lambda x: -len(x[0]))
    # UPA ESTADUAL de nome curto ("UPA BOTAFOGO"): o corte de 3 palavras a deixava de fora. Só as do Estado (as
    # municipais não são contrato do Estado) e o nome já é único no CNES (o gerador descarta nome em 2 municípios).
    out["upas"] = sorted(((r["nome_norm"], r["cod_ibge"]) for r in cnes
                          if r["esfera"] == "ESTADUAL" and re.match(r"UPA \w", r["nome_norm"])), key=lambda x: -len(x[0]))
    with open(_DADOS / "isp_unidades.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out["dp" if r["tipo"] == "DP" else "bpm"][int(r["numero"])] = r["cod_ibge"]
    return out


def _unidades_no_texto(o: str, unidades: dict) -> tuple[list[str], list[str], str]:
    """(municípios, evidências, confiança) das unidades estaduais citadas no texto normalizado."""
    cods, evid, conf = [], [], "alta"
    alvo = f" {o} "
    def soma(cod, ev):
        if cod not in cods:
            cods.append(cod)
        evid.append(ev)
    if _GATILHO.search(o):
        for nome, cod in unidades.get("escolas", ()):
            if f" {nome} " in alvo:
                soma(cod, nome)
    if _GATILHO_SAUDE.search(o):
        # o SIGA entrega parte dos objetos SEM a letra Z ("ESPECIALIADA", "HOSPITAL ESTADUAL AEVEDO LIMA"): em texto
        # longo sem nenhum Z, o nome do cadastro é comparado também sem o Z — e a evidência diz isso
        sem_z = "Z" not in o and len(o) >= 60
        for nome, cod in unidades.get("saude", ()):
            if f" {nome} " in alvo:
                soma(cod, nome + " (CNES)")
                alvo = alvo.replace(f" {nome} ", " # ")      # o nome mais longo casa primeiro e sai do jogo
            elif sem_z and "Z" in nome and f" {nome.replace('Z', '')} " in alvo:
                soma(cod, nome + " (CNES; a fonte grafou sem a letra Z)")
                alvo = alvo.replace(f" {nome.replace('Z', '')} ", " # ")
        # "UPA de Botafogo", "UPA 24h Botafogo" → "UPA BOTAFOGO". Lista de UPAs ("UPAs …", "UPA X e Y") não casa:
        # o primeiro nome da lista não é o lugar do contrato inteiro.
        t = _RE_UPA.sub(" UPA ", alvo)
        if " UPAS " not in t:
            for nome, cod in unidades.get("upas", ()):
                i = t.find(f" {nome} ")
                if i >= 0 and not t[i + len(nome) + 2:].startswith("E "):
                    soma(cod, nome + " (CNES, unidade estadual)")
                    t = t.replace(f" {nome} ", " # ")
    for sigla, cod in unidades.get("siglas", {}).items():
        if f" {sigla} " in alvo:
            soma(cod, f"{sigla} (sigla; município pelo CNES)")
            conf = "media" if not evid[:-1] else conf
    for m in _RE_DP.finditer(o):
        cod = unidades.get("dp", {}).get(int(m.group(1)))
        if cod:
            soma(cod, f"{int(m.group(1))}ª DP (ISP-RJ)")
    for m in _RE_BPM.finditer(o):
        cod = unidades.get("bpm", {}).get(int(m.group(1)))
        if cod:
            soma(cod, f"{int(m.group(1))}º BPM (ISP-RJ, AISP de município único)")
            conf = "media"
    return cods, evid, conf


# ── abrangência: o que NÃO tem município porque é do Estado inteiro / da sede ────────────────────
# Critério EXPLÍCITO (a regra que casou vai gravada em `evidencia`). Só é consultado quando nenhum método
# achou município. Não é atribuição territorial: é a separação honesta entre "é do estado todo" e "não sei".
_ABR_FRASE = [
    (r"NO AMBITO DO ESTADO|EM TODO O ESTADO|NO ESTADO DO RIO DE JANEIRO|CREDENCIAMENTO DE|PARA CREDENCIAMENTO|PARA OS CAMPI|TODO O TERRITORIO (?:DO ESTADO|FLUMINENSE|ESTADUAL)|EM AMBITO ESTADUAL|\b92 MUNICIPIOS",
     "objeto de âmbito estadual"),
    (r"REDE (?:PUBLICA )?ESTADUAL|REDE ESTADUAL DE (?:ENSINO|SAUDE|EDUCACAO)|UNIDADES ESCOLARES DA REDE|ALUNOS DA REDE|ESTUDANTES DA REDE",
     "atende a rede estadual inteira"),
    (r"DIVERSOS MUNICIPIOS|VARIOS MUNICIPIOS|MUNICIPIOS DO ESTADO|MALHA RODOVIARIA ESTADUAL|RODOVIAS ESTADUAIS|"
     r"UNIDADES (?:PRISIONAIS|OPERACIONAIS|ADMINISTRATIVAS|DE SAUDE) D[OA] (?:ESTADO|SEAP|SES|SEPM|PMERJ|CBMERJ|SEPOL)|"
     r"TRANSPORTE AQUAVIARIO|SISTEMA FERROVIARIO|TODAS AS UNIDADES|RODOVIAS SOB CIRCUNSCRICAO|TRECHOS DESCONTINUOS", "serviço distribuído por várias localidades do Estado"),
]
_ABR_NATUREZA = [
    (r"SOFTWARE|LICENCAS? (?:DE USO|DE SOFTWARES?|DEFINITIVAS?|PERPETUAS?)|LICENCIAMENTO|SOLUCAO DE (?:TI|TECNOLOGIA)|DATA ?CENTER|COMPUTACAO EM NUVEM|\bNUVEM\b|"
     r"LINK DE DADOS|LINKS DE (?:DADOS|INTERNET)|TELEFONIA|SUPORTE TECNICO|FABRICA DE SOFTWARE|SISTEMA INTEGRADO|PLATAFORMA DIGITAL",
     "tecnologia corporativa (uso de toda a organização)", "sede"),
    (r"COMBUSTIVE(?:L|IS)|ABASTECIMENTO DA FROTA|GERENCIAMENTO D[EA] FROTA|LOCACAO DE VEICULOS|MANUTENCAO D[EA] FROTA|VIATURAS",
     "frota (circula pelo Estado)", "estado"),
    (r"SEGUROS? (?:D[EAO]S?|PREDIAL|PATRIMONIAL|VEICULAR|TOTAL|OBRIGATORIO|GARANTIA|COLETIVO)|CONTRATACAO DE SEGUROS?|APOLICES?|"
     r"VALE (?:ALIMENTACAO|REFEICAO|TRANSPORTE)|MEIOS DE PAGAMENTO|PASSAGENS AEREAS|AGENCIAMENTO DE VIAGENS|"
     r"FOLHA DE PAGAMENTO|PLANO DE SAUDE|PLANO DE ASSISTENCIA MEDIC[OA]|ASSISTENCIA A SAUDE DO SERVIDOR|ASSISTENCIA MEDICA AOS SERVIDORES|"
     r"BENEFICIO (?:REFEICAO|ALIMENTACAO)|CARTOES ELETRONICOS|SECRETARIADO|ALMOXARIFADO VIRTUAL|NA SEDE D[AO]|EDIFICIO SEDE|PREDIO SEDE",
     "despesa de pessoal/administrativa da organização", "sede"),
    (r"CONSULTORIA|ASSESSORAMENTO|ASSESSORIA TECNICA|AUDITORIA|ESTUDOS? E PESQUISAS?|PESQUISA DE AVALIACAO|AVALIACAO EDUCACIONAL|CAPACITACAO|"
     r"TREINAMENTO|FORMACAO CONTINUADA|CONCURSO PUBLICO|PROCESSO SELETIVO", "serviço intelectual prestado ao órgão (sem local de execução)", "sede"),
    (r"MATERIAL DIDATICO|MATERIAL DE APOIO PEDAGOGICO|LIVROS DIDATICOS|UNIFORMES?|KITS? (?:ESCOLAR|DE UNIFORME|DE MATERIAL ESCOLAR)|MERENDA|MOBILIARIOS? ESCOLAR(?:ES)?|SALAS? DE LEITURA|"
     r"GENEROS(?: PRODUTOS)? ALIMENTICIOS|MEDICAMENTOS|INSUMOS|MATERIAL DE CONSUMO|ARMAMENTO|MUNICAO|COLETES|"
     r"AQUISICAO DE (?:HELICOPTERO|AERONAVES?|CARABINAS|PISTOLAS|FUZIS|VEICULOS|ONIBUS|AMBULANCIAS)", "aquisição distribuída à rede (sem ponto único de entrega no objeto)", "estado"),
    (r"PUBLICIDADE|PROPAGANDA|COMUNICACAO INSTITUCIONAL|SERVICOS POSTAIS|CORREIOS|"
     r"ASSINATURAS? (?:ANUA(?:L|IS)|DIGITA(?:L|IS)|D[EAO]S? (?:PERIODICOS?|JORNA(?:L|IS)|REVISTAS?|BASES?|PLATAFORMAS?|ACESSOS?|FERRAMENTAS?))|"
     r"PUBLICACAO (?:DE|NO)|OUTSOURCING DE IMPRESSAO|SERVICOS GRAFICOS", "serviço corporativo", "sede"),
]
_ORGAO_MEIO = re.compile(r"PROCURADORIA GERAL|FAZENDA|PLANEJAMENTO|CASA CIVIL|CONTROLADORIA|PREVIDENCIA|JUNTA COMERCIAL|LOTERIA|"
                         r"CENTRO DE TECN|TRANSFORMACAO DIGITAL|GABINETE DE SEGURANCA|GOVERNO\b|REPRES DO GOV")
_RE_ABR = [(re.compile(rf"\b(?:{p})\b"), rot) for p, rot in _ABR_FRASE]
_RE_NAT = [(re.compile(rf"\b(?:{p})\b"), rot, classe) for p, rot, classe in _ABR_NATUREZA]


def natureza_corporativa(o_norm: str) -> str | None:
    """Regra de NATUREZA que casou (fonte única: o lado PCRJ usa a mesma lista)."""
    for rg, rot, _classe in _RE_NAT:
        m = rg.search(o_norm)
        if m:
            return f"{rot}: “{m.group(0).lower()}”"
    return None


def abrangencia(objeto: str | None, orgao: str | None) -> tuple[str, str] | None:
    """('estado' | 'sede', motivo) — ou None (aí é "sem município identificado").

    'estado' = o objeto é do Estado inteiro (âmbito estadual, rede, frota, aquisição distribuída): NUNCA ganha
    município. 'sede' = o objeto é da própria organização (serviço na sede, tecnologia corporativa, despesa
    administrativa, órgão-meio): pode ser atribuído à sede do órgão, no grau mais fraco."""
    o = norm(objeto)
    for rg, rot in _RE_ABR:
        m = rg.search(o)
        if m:
            return "estado", f"Estado inteiro — {rot}: “{m.group(0).lower()}”"
    for rg, rot, classe in _RE_NAT:
        m = rg.search(o)
        if m:
            return classe, f"{'Estado inteiro' if classe == 'estado' else 'objeto da organização'} — {rot}: “{m.group(0).lower()}”"
    if _ORGAO_MEIO.search(norm(orgao)):
        return "sede", f"sede — órgão-meio sem atividade territorial ({(orgao or '').strip()})"
    return None


def abrangencia_estado(objeto: str | None, orgao: str | None) -> str | None:
    """Só o motivo (compatibilidade): ver `abrangencia`."""
    ab = abrangencia(objeto, orgao)
    return ab[1] if ab else None


def carregar_sedes() -> dict[str, tuple[str, str]]:
    """unidade normalizada → (cod_ibge, fonte) de `dados/sedes_orgaos.csv` (cadastro de unidades do PNCP). Linha sem
    `cod_ibge` = sede DIVERGENTE ou não conferida: não atribui (o contrato fica sem município)."""
    with open(_DADOS / "sedes_orgaos.csv", encoding="utf-8") as f:
        return {r["unidade_norm"]: (r["cod_ibge"], r["fonte"]) for r in csv.DictReader(f) if r["cod_ibge"]}


def unidade_base(orgao: str | None) -> str:
    """"UERJ - HOSPITAL UNIVERSITÁRIO - HOSPITAL UNIVERSITARIO PEDRO ERNESTO" → o último trecho (o nome que o PNCP usa)."""
    return (orgao or "").rsplit(" - ", 1)[-1].strip()


_RE_CEP = re.compile(r"\bCEP\D{0,3}(\d{5})\D?(\d{3})\b")
# Endereço da CONTRATADA não é local de execução. Medido na conferência à mão: "…em favor da Águas de Juturnaíba situada na
# Rodovia Amaral Peixoto, km 91, Araruama" atribuía a Araruama o que abastece unidades do INEA em vários municípios.
_RE_END_PARTE = re.compile(r"\b(?:COM SEDE|SEDIAD[AO]S?|ESTABELECID[AO]S?|EM FAVOR D[AEO]S?|INSCRIT[AO] NO CNPJ)\b.{0,170}", re.I | re.S)


def sem_endereco_da_parte(texto: str | None) -> str:
    """Tira do texto o trecho que qualifica a contratada ("com sede em…", "em favor da … situada na…")."""
    return _RE_END_PARTE.sub(" ", texto or "")


def atribuir(objeto: str | None, unidade: str | None, regionais, unidades, extra: str = "", sedes: dict | None = None) -> dict:
    """Aplica os métodos e decide. Função PURA (é a que os testes exercitam).

    `extra` = texto de outra fonte sobre o MESMO contrato (objeto do SIGA, extrato do DOERJ): soma chão aos métodos
    de lugar, mas a ABRANGÊNCIA lê só o `objeto` (o extrato fala em "assinatura", "publicação" — não é natureza).
    `sedes` = cadastro de sedes (`carregar_sedes`); sem ele o grau `sede` não é atribuído."""
    nomes = nome_municipio()
    metodos: list[dict] = []
    u = norm(unidade)
    so_objeto = reparar_texto(objeto)
    objeto = (so_objeto + " " + reparar_texto(extra)).strip()
    o = norm(objeto)
    cods, evid, conf = [], [], "alta"
    for padrao, cod, cf, fonte in regionais:
        if padrao in u:
            metodos.append({"metodo": "campo", "cods": [cod], "confianca": cf, "evidencia": f"unidade: {unidade} — {fonte}"})
            break
        if f" {padrao} " in f" {o} ":                # a unidade de sítio único citada no OBJETO de outro comprador
            cods.append(cod)
            evid.append(f"{padrao} — {fonte}")
            conf = cf
    if unidades:
        c2, e2, cf2 = _unidades_no_texto(o, unidades if isinstance(unidades, dict) else {"escolas": unidades})
        cods += [c for c in c2 if c not in cods]
        evid += e2
        conf = "media" if "media" in (conf, cf2) and cods else conf
    if cods:
        metodos.append({"metodo": "unidade", "cods": cods, "confianca": conf, "evidencia": "unidade citada: " + "; ".join(evid[:3])})
    lugar = sem_endereco_da_parte(objeto)          # CEP e dicionário não leem o endereço da contratada
    m = _RE_CEP.search(lugar.upper())
    if m and 20000 <= int(m.group(1)) <= 23799:
        metodos.append({"metodo": "endereco", "cods": [RIO], "confianca": "alta",
                        "evidencia": f"CEP {m.group(1)}-{m.group(2)} (faixa da capital, Correios)"})
    lei = ler_municipios(lugar)
    if lei.municipios:
        metodos.append({"metodo": "texto", "cods": [a.cod_ibge for a in lei.municipios], "confianca": "media",
                        "evidencia": "; ".join(a.evidencia for a in lei.municipios[:4])})
    metodos.sort(key=lambda x: -FORCA[x["metodo"]])
    out = {"cod_ibge": None, "multi": 0, "municipios": [], "regiao": lei.regiao, "metodo": None, "confianca": None,
           "evidencia": None, "metodos": metodos, "abrangencia": None, "grau": None}
    if not metodos:
        if lei.regiao:
            return out
        ab = abrangencia(so_objeto, unidade)
        if not ab:
            return out
        sd = (sedes or {}).get(norm(unidade_base(unidade))) if ab[0] == "sede" else None
        if not sd:
            out.update(abrangencia="estado_inteiro", evidencia=ab[1] + (" — sede do órgão não conferida: sem município"
                                                                       if ab[0] == "sede" and sedes is not None else ""))
            return out
        metodos.append({"metodo": "sede", "cods": [sd[0]], "confianca": "baixa", "evidencia": f"{ab[1]} — sede do órgão: {sd[1]}"})
    v = metodos[0]
    out.update(metodo=v["metodo"], confianca=v["confianca"], evidencia=v["evidencia"], grau=GRAU[v["metodo"]],
               municipios=[{"cod_ibge": c, "nome": nomes.get(c, c)} for c in v["cods"]])
    if len(v["cods"]) == 1:
        out["cod_ibge"] = v["cods"][0]
    else:
        out["multi"] = 1
    return out


def eh_rescisao(tipo_termo: str | None) -> bool:
    """No PNCP o termo vem como "Termo de Rescisão" (não começa por "Rescisão")."""
    return "RESCIS" in norm(tipo_termo)


def status_de(rescindido: bool, vig_fim: str | None, hoje: str) -> str:
    """`rescindido` vence tudo; senão vigência final (já com aditivo de prazo) ≥ hoje = em execução. Sem fim de
    vigência na fonte NÃO é "executado" (seria afirmar o que a fonte não diz): é `sem_vigencia`."""
    if rescindido:
        return "rescindido"
    if not vig_fim:
        return "sem_vigencia"
    return "em_execucao" if vig_fim[:10] >= hoje else "executado"


def _digitos(s: str | None) -> str:
    return re.sub(r"\D", "", s or "")


def _pagamentos(db_path, linhas: list[dict], log=print) -> dict[str, dict]:
    """contrato_id → {pago, n_obs, mensal, motivo, alerta}. O PAGO é o da perícia contábil — fonte única da casa
    (`pericia_contabil.avaliar_estado`): OB do SIAFE Contabilizada do mesmo processo SEI ao mesmo CNPJ (ou vinculada
    pelos autos, VERIFICADO), deduplicada por (número, exercício, UG), SEM a OB devolvida pelo banco e sem a OB
    anterior ao contrato. Até 14/11/2026 este motor tinha uma cópia própria da regra: somava OB devolvida, não
    canonizava o ano de 2 dígitos do processo e descartava em silêncio o que passava de 125%.

    A perícia avalia registros do SIGA/TCE-RJ; o contrato daqui herda o pago do(s) registro(s) que o compõem
    (`tce_ids`). Contrato só do PNCP não tem processo SEI na base → pago INDISPONÍVEL, com o motivo.
    Fica SEM pago (com motivo) o que a perícia marca como desproporcional (erro de registro provável).
    `mensal` (AAAA-MM → valor) só é publicado quando a soma das OBs relidas FECHA com o pago da perícia."""
    from compliance_agent import pericia_contabil as P
    from compliance_agent.vinculo_ob_contrato import vinculos_verificados
    res = {r["id"]: r for r in P.avaliar_estado(db_path)}
    log(f"[pago] perícia contábil: {len(res)} registros avaliados, {sum(1 for r in res.values() if r['pago'] is not None)} com pago")
    con = P._con_ro(db_path)
    try:
        chave_cred = {}
        for cid, proc, sei, ini, dcon, cnpj in con.execute(
                "SELECT id, processo, sei_norm, vig_inicio, data_contratacao, cnpj FROM contratos_tcerj"):
            datas = [d for d in (P.parse_data(ini), P.parse_data(dcon)) if d]
            chave_cred[cid] = (P.chave_sei(sei or proc), _digitos(cnpj), min(datas) if datas else None)
        usados = {t for k in linhas for t in k.get("tce_ids", ()) if res.get(t, {}).get("pago") is not None}
        obs, _ = P._obs_por_credor(con, {chave_cred[t][1] for t in usados if t in chave_cred})
        vinc = vinculos_verificados(con)
    finally:
        con.close()
    corte = max((P.parse_data(r["corte"]) for r in res.values() if r.get("corte")), default=None)

    def mensal(tid: str) -> dict | None:
        r = res[tid]
        k_proc, k_cred, ini = chave_cred.get(tid, (None, None, None))
        if not (k_proc and k_cred and ini and corte):
            return None
        sel = [o for o in obs.get(k_cred, ()) if o[0] and ini <= o[0] <= corte
               and (o[1] == k_proc or vinc.get(P._chave_ob(o)) == tid)]
        if len(sel) != r["n_obs"] or abs(sum(o[3] for o in sel) - r["pago"]) > 0.01:
            return None                       # não fecha com a perícia: a série não é publicada (o total continua)
        m: dict[str, float] = {}
        for o in sel:
            m[o[0].strftime("%Y-%m")] = round(m.get(o[0].strftime("%Y-%m"), 0.0) + o[3], 2)
        return m

    out, sem_serie = {}, 0
    for k in linhas:
        rs = [res[t] for t in k.get("tce_ids", ()) if t in res]
        if not rs:
            out[k["contrato_id"]] = {"pago": None, "n_obs": 0, "mensal": None, "alerta": None,
                                     "motivo": "contrato só do PNCP: sem registro no SIGA/TCE-RJ, não há processo SEI para ligar a OB"}
            continue
        ok = [r for r in rs if r["pago"] is not None and r["motivo"] != "valor_desproporcional"]
        if not ok:
            r = rs[0]
            mot = ("OBs do processo desproporcionais ao valor do contrato (erro de registro provável)" if r["pago"] is not None
                   else P.MOTIVOS.get(r["motivo"], r["motivo"] or "sem vínculo com OB"))
            out[k["contrato_id"]] = {"pago": None, "n_obs": 0, "mensal": None, "motivo": mot, "alerta": None}
            continue
        series = [mensal(r["id"]) for r in ok]
        serie = None
        if all(s is not None for s in series):
            serie = {}
            for s in series:
                for mes, v in s.items():
                    serie[mes] = round(serie.get(mes, 0.0) + v, 2)
        else:
            sem_serie += 1
        maior = [r for r in ok if r["categoria"] == "A_MAIOR" and r.get("excesso_global")]
        alerta = None
        if maior:
            alerta = (f"Indício (perícia contábil): pago R$ {P.fmt_brl(sum(r['pago'] for r in maior))} supera o valor registrado em "
                      f"R$ {P.fmt_brl(sum(r['excesso_global'] for r in maior))}. " + "; ".join(r["ressalvas"] for r in maior if r["ressalvas"])[:400])
        out[k["contrato_id"]] = {"pago": round(sum(r["pago"] for r in ok), 2), "n_obs": sum(r["n_obs"] for r in ok), "mensal": serie,
                                 "motivo": "; ".join(dict.fromkeys(r["ressalvas"] for r in ok if r["ressalvas"]))[:500] or None,
                                 "alerta": alerta}
    com = sum(1 for v in out.values() if v["pago"] is not None)
    log(f"[pago] {com} contratos com pagamento vinculado (R$ {sum(v['pago'] or 0 for v in out.values()):,.2f}); "
        f"{sem_serie} sem série mensal (a releitura das OBs não fechou com a perícia)")
    return out


def _pagos_guardados(db: sqlite3.Connection, linhas: list[dict], hoje: str, log=print) -> dict[str, dict] | None:
    """No incremental, a perícia (≈5 min de CPU) roda no máximo UMA vez por dia: se o pago já foi apurado hoje, reusa
    o que está gravado. Contrato novo fica sem pago até a próxima apuração — com o motivo, nunca zero."""
    if (base.meta(db, "estado_pago_em") or "")[:10] != hoje or base.meta(db, "estado_versao") != "12":
        return None
    ja = {r["contrato_id"]: {"pago": r["pago"], "n_obs": r["n_obs"] or 0, "motivo": r["pago_motivo"], "alerta": r["alerta"],
                             "mensal": json.loads(r["pago_mensal_json"]) if r["pago_mensal_json"] else None}
          for r in db.execute("SELECT contrato_id, pago, n_obs, pago_motivo, alerta, pago_mensal_json FROM territorio_contrato_estado")}
    novo = {"pago": None, "n_obs": 0, "mensal": None, "alerta": None,
            "motivo": "contrato novo na base: o pago é apurado uma vez por dia (próxima rodada)"}
    log(f"[pago] reusado o pago apurado hoje ({len(ja)} contratos guardados)")
    return {k["contrato_id"]: ja.get(k["contrato_id"], novo) for k in linhas}


_ISO_BR = re.compile(r"(\d{2})/(\d{2})/(\d{4})")


def _iso(d: str | None) -> str | None:
    m = _ISO_BR.match(d or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def _dias(a: str | None, b: str | None) -> int | None:
    """|a − b| em dias para duas datas ISO (AAAA-MM-DD…); None se faltar uma ou for inválida."""
    try:
        return abs((date.fromisoformat(a[:10]) - date.fromisoformat(b[:10])).days)
    except (TypeError, ValueError):
        return None


def mesma_data(pncp: dict, vig_ini: str | None, contratacao: str | None, folga: int = 7) -> int | None:
    """Menor diferença (dias) entre as datas do registro do SIGA e as do contrato do PNCP, se ≤ `folga`; senão None.
    Medido em 14/11/2026: de 14.213 registros do SIGA com par de mesmo CNPJ, órgão e valor ±1% no PNCP, 13.107 (92%)
    têm data IDÊNTICA em uma destas comparações — é a data que separa o mesmo contrato da recontratação de igual valor."""
    ds = [d for d in (_dias(vig_ini, pncp["vig_ini"]), _dias(contratacao, pncp["data_assinatura"]),
                      _dias(vig_ini, pncp["data_assinatura"])) if d is not None]
    return min(ds) if ds and min(ds) <= folga else None


def _integrar_tcerj(src: sqlite3.Connection, linhas: list[dict], hoje: str, fora: dict) -> dict:
    """Segunda fonte: `contratos_tcerj` (SIGA/TCE-RJ). Entra todo registro que é contratação firmada — inclusive
    "Em Aberto" (contratação sem termo/por empenho, que a perícia contábil da casa também avalia: 15.775 registros,
    R$ 12,25 bi, ficavam fora). Cancelado e em elaboração (`_SIGA_FORA`) não entram e são contados.

    JUNÇÃO com o PNCP, UM PARA UM: mesmo CNPJ + valor ±1% + data coincidente (`mesma_data`). Cada contrato do PNCP
    recebe no máximo UM registro do SIGA; um segundo registro que fecharia a MESMA chave é repetição do mesmo contrato.
    REPETIÇÃO interna do SIGA: mesmo processo + CNPJ + valor + vigência; e credenciamento (mesmo processo + mesmo valor
    com CNPJs diferentes: o SIGA repete o valor GLOBAL para cada credenciado).
    O que parece o mesmo contrato mas não fecha a chave (CNPJ e órgão iguais, valor ±10%, data ≤ 45 dias) fica nas
    DUAS fontes e é contado em `possivel_duplicidade` — declarado na tela, não escondido."""
    por_cnpj: dict[str, list] = {}
    for k in linhas:
        if k["fornecedor_cnpj"]:
            por_cnpj.setdefault(k["fornecedor_cnpj"], []).append(k)
    est = {"juntados": 0, "novos": 0, "repetidos": 0, "rascunho": 0, "cancelado": 0, "em_aberto": 0,
           "dup_n": 0, "dup_valor": 0.0, "siglas": {}}
    vistos: set = set()
    ordem = {"Ativo": 0, "Encerrado": 1}
    regs = src.execute("SELECT id, sei_norm, valor_contrato, status, unidade, objeto, fornecedor, cnpj, vig_inicio, vig_fim, "
                       "data_contratacao FROM contratos_tcerj WHERE valor_contrato>0").fetchall()
    for r in sorted(regs, key=lambda r: (ordem.get(r["status"], 2), r["id"])):
        st = (r["status"] or "").strip()
        if st in _SIGA_FORA:
            est["cancelado" if st == "Cancelado" else "rascunho"] += 1
            continue
        base_u = unidade_base(r["unidade"])
        esf = esfera_unidade(base_u)
        if esf != "estadual":
            fora[esf] += 1
            continue
        est["siglas"].setdefault(norm(base_u), (r["unidade"] or "").strip())
        cnpj, valor = _digitos(r["cnpj"]), float(r["valor_contrato"])
        proc = r["sei_norm"] or ""
        ini, fim, dcon = _iso(r["vig_inicio"]), _iso(r["vig_fim"]), (r["data_contratacao"] or "")[:10] or None
        cands = [(mesma_data(k, ini, dcon), abs(k["valor"] - valor), k) for k in por_cnpj.get(cnpj, ())
                 if "pncp" in k["fontes"] and k["valor"] and abs(k["valor"] - valor) <= 0.01 * valor] if cnpj else []
        cands = sorted((c for c in cands if c[0] is not None), key=lambda c: (c[0], c[1]))
        if cands:
            livre = next((c[2] for c in cands if "tcerj" not in c[2]["fontes"]), None)
            if livre is None:                     # a chave já foi fechada por outro registro: repetição do mesmo contrato
                est["repetidos"] += 1
                continue
            livre["fontes"].append("tcerj")
            livre["extra"] += " " + (r["objeto"] or "")
            livre["tce_ids"].append(r["id"])
            livre["situacao_fonte"] = st
            if st == "Encerrado" and livre["status"] == "em_execucao":
                livre["status"] = "executado"     # o SIGA encerrou o contrato: a vigência publicada no PNCP não o mantém vivo
            if proc:
                livre["processos"].add(proc)
            est["juntados"] += 1
            continue
        chave = (cnpj, round(valor), ini, fim, proc)
        chave_proc = ("proc", proc, round(valor)) if proc else None
        if chave in vistos or (chave_proc and chave_proc in vistos):
            est["repetidos"] += 1
            continue
        vistos.add(chave)
        if chave_proc:
            vistos.add(chave_proc)
        if any("pncp" in k["fontes"] and "tcerj" not in k["fontes"] and k["valor"] and abs(k["valor"] - valor) <= 0.10 * valor
               and norm(unidade_base(k["orgao"]))[:20] == norm(base_u)[:20] and mesma_data(k, ini, dcon, 45) is not None
               for k in por_cnpj.get(cnpj, ())):
            est["dup_n"] += 1
            est["dup_valor"] += valor
        novo = {"contrato_id": f"TCERJ-{r['id']}", "orgao": (r["unidade"] or "").strip(), "fornecedor_cnpj": cnpj,
                "fornecedor_nome": r["fornecedor"], "objeto": r["objeto"], "valor": valor, "vig_ini": ini, "vig_fim": fim,
                "data_assinatura": dcon, "status": "executado" if st == "Encerrado" else status_de(False, fim, hoje),
                "fontes": ["tcerj"], "processos": {proc} if proc else set(), "extra": "", "tce_ids": [r["id"]],
                "situacao_fonte": st}
        linhas.append(novo)
        est["novos"] += 1
        est["em_aberto"] += st == "Em Aberto"
    return est


_RE_ATO_ID = re.compile(r"\bId: ?\d{6,8}\b")
_RE_PROC_DOE = re.compile(r"(?<!\d)(\d{6})\s*/\s*(\d{6})\s*/\s*(\d{4})(?!\d)")
_RE_ESPACADO = re.compile(r"((?:\b[A-ZÇÃÊÉ]{1,2} ){2,}[A-ZÇÃÊÉ]{1,2}) ?:")          # "O B J E TO :", "VA L O R :", "PA R T E S :"
_RE_OBJ_DOE = re.compile(
    r"OBJETO: ?(.{10,700}?)(?=\b(?:VALOR|PRAZO|VIG[ÊE]NCIA|DATA D[AE] ASSINATURA|FUNDAMENTO|PARTES|GESTOR|FISCAL|NOTA DE EMPENHO|"
    r"PROGRAMA DE TRABALHO|NATUREZA D[AE] DESPESA|PROCESSO|INSTRUMENTO)\b[^:.]{0,40}:|$)", re.S)


def objeto_do_extrato(texto: str | None, processo: str) -> list[str]:
    """Cláusula OBJETO do(s) ato(s) do DOERJ que citam `processo` (16 dígitos) — e nada além dela.

    `publicacoes_doerj.texto` NÃO é um extrato: é um trecho corrido do Diário com VÁRIOS atos (média de 8,5 mil
    caracteres), e `processos_sei_extraidos` lista todo processo citado em qualquer um deles. Até 14/11/2026 este motor
    colava os primeiros 1.500 caracteres do trecho em todo contrato cujo processo aparecesse ali — texto de OUTROS atos.
    Conferência à mão achou os frutos: "GE HEAL-THCARE" (quebra de linha) virava a sigla HEAL → Niterói; a servidora
    "…Monnerat…" virava o distrito de Monnerat → Duas Barras; o aviso do HUPE levava um show da FUNARJ para o hospital.
    Regra: o trecho é cortado nos marcadores de ato ("Id: 2763020"); só vale o ato que cita o processo; dele, só o
    texto entre "OBJETO:" e o próximo rótulo. Ato sem cláusula OBJETO não dá texto nenhum."""
    t = re.sub(r"(?<=\w)- (?=\w)", "", texto or "")              # desfaz a hifenização de quebra de linha ("lo- cação")
    t = _RE_ESPACADO.sub(lambda m: m.group(1).replace(" ", "") + ":", t)
    out = []
    for ato in _RE_ATO_ID.split(t):
        if not any("".join(m.groups()) == processo for m in _RE_PROC_DOE.finditer(ato)):
            continue
        m = _RE_OBJ_DOE.search(ato)
        if m:
            out.append(" ".join(m.group(1).split()))
    return out


def _enriquecer_doerj(src: sqlite3.Connection, linhas: list[dict]) -> int:
    """Extrato publicado no DOERJ soma TEXTO ao contrato do mesmo processo — só a cláusula OBJETO do ato que cita o
    processo (`objeto_do_extrato`). Não cria contrato: só dá mais chão para os métodos `unidade` e `texto`."""
    alvo = {p for k in linhas for p in k["processos"]}
    por_proc: dict[str, list] = {}
    for r in src.execute("SELECT processos_sei_extraidos, texto FROM publicacoes_doerj WHERE tipo_ato='contrato' "
                         "AND processos_sei_extraidos IS NOT NULL AND processos_sei_extraidos NOT IN ('', '[]')"):
        try:
            procs = json.loads(r[0])
        except ValueError:
            procs = [r[0]]
        for pr in procs if isinstance(procs, list) else [procs]:
            d = _digitos(str(pr))
            if d in alvo and len(por_proc.get(d, ())) < 2:
                por_proc.setdefault(d, []).extend(o for o in objeto_do_extrato(r[1], d) if o not in por_proc.get(d, ()))
    n = 0
    for k in linhas:
        txt = [o for p in sorted(k["processos"]) for o in por_proc.get(p, ())[:2]]
        if txt:
            k["extra"] += " " + " ".join(txt)
            if "doerj" not in k["fontes"]:
                k["fontes"].append("doerj")
            n += 1
    return n


def _versao_regras() -> str:
    """Impressão digital das REGRAS (este módulo, o dicionário e os cadastros). Entra na assinatura do contrato: mudou
    regra ou cadastro, o incremental reatribui tudo sozinho — antes, alias novo só valia depois de um `--full` manual."""
    h = hashlib.sha1(b"12")
    arqs = [Path(__file__), Path(__file__).with_name("dicionario.py"), base.DATA / "territorio_unidades.csv", *sorted(_DADOS.glob("*.csv"))]
    for a in arqs:
        if a.exists():
            h.update(a.name.encode() + a.read_bytes())
    return h.hexdigest()[:12]


def rodar(incremental: bool = False, log=print) -> dict:
    hoje = date.today().isoformat()
    src = base.fonte_ro("compliance.db")
    montar_unidades(log)
    regionais, unidades, sedes = _unidades_regionais(), carregar_unidades(), carregar_sedes()
    adit: dict[str, dict] = {}
    for r in src.execute("SELECT numero_controle_pncp, tipo_termo, vigencia_fim, processo FROM contrato_aditivo"):
        a = adit.setdefault(r[0], {"resc": False, "fim": None, "procs": set()})
        if eh_rescisao(r[1]):
            a["resc"] = True
        if r[2] and (a["fim"] is None or r[2] > a["fim"]):
            a["fim"] = r[2]
        if len(_digitos(r[3])) >= 12:
            a["procs"].add(_digitos(r[3]))
    linhas, fora = [], {"municipal": 0, "outro": 0}
    for r in src.execute("SELECT numero_controle_pncp, unidade, fornecedor_documento, fornecedor_nome, objeto, valor_global, "
                         "valor_inicial, vigencia_ini, vigencia_fim, data_assinatura, fonte FROM pcrj_contratos WHERE orgao_cnpj=?",
                         (CNPJ_ESTADO,)):
        esf = esfera_unidade(r["unidade"])
        if esf != "estadual":
            fora[esf] += 1
            continue
        a = adit.get(r["numero_controle_pncp"], {})
        fim = max(x for x in (r["vigencia_fim"], a.get("fim")) if x) if (r["vigencia_fim"] or a.get("fim")) else None
        status = status_de(bool(a.get("resc")), fim, hoje)
        valor = r["valor_global"] if r["valor_global"] is not None else r["valor_inicial"]
        linhas.append({"contrato_id": r["numero_controle_pncp"], "orgao": (r["unidade"] or "").strip(),
                       "fornecedor_cnpj": _digitos(r["fornecedor_documento"]), "fornecedor_nome": r["fornecedor_nome"],
                       "objeto": r["objeto"], "valor": valor, "vig_ini": (r["vigencia_ini"] or "")[:10] or None,
                       "vig_fim": (fim or "")[:10] or None, "data_assinatura": (r["data_assinatura"] or "")[:10] or None,
                       "status": status, "fontes": ["pncp"], "processos": set(a.get("procs", ())), "extra": "", "tce_ids": [],
                       "situacao_fonte": None})
    n_pncp = len(linhas)
    log(f"[estado] PNCP: {n_pncp} contratos do Executivo estadual; fora do escopo: {fora['municipal']} de unidade municipal, "
        f"{fora['outro']} de órgão fora do Executivo")
    est = _integrar_tcerj(src, linhas, hoje, fora)
    log(f"[estado] TCE-RJ/SIGA: {est['juntados']} registros casaram um-para-um com contrato do PNCP (CNPJ, valor ±1%, data), "
        f"{est['novos']} contratos novos ({est['em_aberto']} deles 'Em Aberto'), {est['repetidos']} repetições descartadas; "
        f"fora: {est['cancelado']} cancelados, {est['rascunho']} em elaboração; possível duplicidade entre fontes: "
        f"{est['dup_n']} (R$ {est['dup_valor']:,.2f})")
    # o MESMO órgão chega "ADMINISTRACAO CENTRAL" do PNCP e "UERJ - ADMINISTRACAO CENTRAL" do SIGA: exibe o do SIGA (com a sigla)
    for k in linhas:
        k["orgao"] = est["siglas"].get(norm(unidade_base(k["orgao"])), k["orgao"])
    n_doe = _enriquecer_doerj(src, linhas)
    log(f"[estado] DOERJ: {n_doe} contratos ganharam a cláusula OBJETO do extrato publicado (ato que cita o processo SEI)")
    src.close()
    db = base.abrir(escrita=True)
    pagos = _pagos_guardados(db, linhas, hoje, log) if incremental else None
    if pagos is None:
        db.close()                            # a perícia leva minutos: não segura o banco aberto para escrita
        pagos = _pagamentos(base.DATA / "compliance.db", linhas, log)
        db = base.abrir(escrita=True)
        base.por_meta(db, "estado_pago_em", base.agora())
    ja = {r[0]: r[1] for r in db.execute("SELECT contrato_id, assinatura FROM territorio_contrato_estado")} if incremental else {}
    agora, n_grav = base.agora(), 0
    rot = {"pncp": "PNCP", "tcerj": "TCE-RJ/SIGA", "doerj": "DOERJ"}
    regras = _versao_regras()
    for k in linhas:
        pg = pagos[k["contrato_id"]]
        ass = hashlib.sha1(json.dumps([k["objeto"], k["extra"], k["orgao"], k["valor"], k["vig_fim"], k["status"], pg, k["fontes"],
                                       k["situacao_fonte"], regras], ensure_ascii=False, default=str, sort_keys=True).encode()).hexdigest()
        if incremental and ja.get(k["contrato_id"]) == ass:
            continue
        at = atribuir(k["objeto"], k["orgao"], regionais, unidades, extra=k["extra"], sedes=sedes)
        db.execute("INSERT OR REPLACE INTO territorio_contrato_estado(contrato_id,fonte,orgao,fornecedor_cnpj,fornecedor_nome,objeto,"
                   "valor,vig_ini,vig_fim,status,pago,cod_ibge,multi,municipios_json,regiao,metodo,confianca,evidencia,metodos_json,"
                   "pago_evidencia,assinatura,atualizado_em,fontes_json,abrangencia,grau,situacao_fonte,data_assinatura,processo,"
                   "n_obs,pago_mensal_json,pago_motivo,alerta) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (k["contrato_id"], " + ".join(rot[f] for f in k["fontes"]), k["orgao"], k["fornecedor_cnpj"], k["fornecedor_nome"],
                    k["objeto"], k["valor"], k["vig_ini"], k["vig_fim"], k["status"], pg["pago"], at["cod_ibge"], at["multi"],
                    json.dumps(at["municipios"], ensure_ascii=False), at["regiao"], at["metodo"], at["confianca"], at["evidencia"],
                    json.dumps(at["metodos"], ensure_ascii=False),
                    f"{pg['n_obs']} OB(s) do SIAFE, Contabilizadas, sem devolvidas (perícia contábil)" if pg["pago"] is not None else None,
                    ass, agora, json.dumps(k["fontes"]), at["abrangencia"], at["grau"], k["situacao_fonte"], k["data_assinatura"],
                    ", ".join(sorted(k["processos"])[:3]) or None, pg["n_obs"],
                    json.dumps(pg["mensal"], sort_keys=True) if pg["mensal"] is not None else None, pg["motivo"], pg["alerta"]))
        n_grav += 1
    # contrato que saiu da fonte, do escopo ou foi absorvido pela junção sai daqui — também no incremental: `linhas` é
    # sempre a base inteira (o incremental só pula a REatribuição do que não mudou)
    vivos = {k["contrato_id"] for k in linhas}
    mortos = [r[0] for r in db.execute("SELECT contrato_id FROM territorio_contrato_estado") if r[0] not in vivos]
    db.executemany("DELETE FROM territorio_contrato_estado WHERE contrato_id=?", [(m,) for m in mortos])
    for chave, v in (("estado_fora_municipal", fora["municipal"]), ("estado_fora_outro", fora["outro"]),
                     ("estado_siga_cancelado", est["cancelado"]), ("estado_siga_rascunho", est["rascunho"]),
                     ("estado_siga_repetidos", est["repetidos"]), ("estado_possivel_duplicidade_n", est["dup_n"]),
                     ("estado_possivel_duplicidade_valor", f"{est['dup_valor']:.2f}"), ("estado_versao", "12")):
        base.por_meta(db, chave, str(v))
    base.por_meta(db, "estado_rodado_em", agora)
    db.commit()
    db.close()
    log(f"[estado] {n_grav} contratos gravados em territorio.db ({'incremental' if incremental else 'completo'}); {len(mortos)} removidos")
    return {"contratos": len(linhas), "gravados": n_grav, "fora": fora, "com_pago": sum(1 for v in pagos.values() if v["pago"] is not None),
            "siga": {k: v for k, v in est.items() if k != "siglas"}}
