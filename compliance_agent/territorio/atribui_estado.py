# -*- coding: utf-8 -*-
"""(A) Contratos do ESTADO do RJ → município de EXECUÇÃO.

BASE: `compliance.db.pcrj_contratos` com `fonte='pncp_estado'` e `orgao_cnpj` = CNPJ do Estado
(42.498.600/0001-71) — o backfill "contratos do Estado" do PNCP. Ficam FORA, por decisão do brief:
  · unidades MUNICIPAIS que o PNCP pendura no CNPJ do Estado (prefeituras, fundos, autarquias e
    institutos de previdência municipais) — é exatamente o "contrato de prefeitura" que o dono não quer;
  · órgãos que não são do Poder Executivo (TJRJ, MPRJ, TCE-RJ, DPE, ALERJ) e entes de outra esfera.

ATRIBUIÇÃO, por ordem de força (guarda TODOS os métodos que acertaram; decide pelo mais forte):
  1. campo     unidade compradora de SÍTIO ÚNICO (`dados/unidades_regionais.csv`). Sede de órgão NÃO
               é local de execução: quase toda secretaria tem sede na capital.
  2. orçamento regionalização do empenho no SIAFE — SEM DADO LOCAL (as tabelas SIAFE coletadas não
               trazem localizador/subtítulo). O método existe no desenho e devolve nada: INDISPONÍVEL.
  3. unidade   o objeto cita unidade estadual de endereço conhecido (`data/territorio_unidades.csv`,
               montado dos locais de votação do TSE: colégios estaduais, CIEPs, escolas técnicas).
  4. endereço  CEP no objeto — só a faixa da capital (20000-000 a 23799-999) é resolvida aqui.
  5. texto     dicionário dos 92 municípios (`dicionario.py`), com as armadilhas tratadas.

Vários municípios → `multi=1`, lista guardada, VALOR NÃO DIVIDIDO. Sem município → fica sem.
STATUS: `rescindido` (termo de rescisão) · `em_execucao` (vigência final, com aditivos de prazo,
≥ hoje) · `executado`. PAGO = OBs do SIAFE (`ob_orcamentaria_siafe`, status Contabilizado) do MESMO
processo SEI pagas ao MESMO CNPJ; sem vínculo → NULL (a tela diz INDISPONÍVEL, nunca 0).
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
FORCA = {"campo": 5, "orcamento": 4, "unidade": 3, "endereco": 2, "texto": 1}

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
_RE_DP = re.compile(r"\b0*(\d{1,3}) ?A? (?:DP|DELEGACIA DE POLICIA|DELEGACIA POLICIAL|DELEGACIA LEGAL)\b")
_RE_BPM = re.compile(r"\b0*(\d{1,2}) ?O? (?:BPM|BATALHAO DE POLICIA MILITAR)\b")


def carregar_unidades() -> dict:
    """Cadastros do método `unidade`: {"escolas": [(nome, cod)], "saude": [(nome, cod)], "dp": {n: cod}, "bpm": {n: cod}}.
    Fontes: TSE (escolas, cadastro local), CNES (saúde) e ISP-RJ (delegacias e batalhões) — ver `tools/v61_territorio_fontes.py`."""
    out = {"escolas": [], "saude": [], "dp": {}, "bpm": {}, "siglas": {}}
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
        for nome, cod in unidades.get("saude", ()):
            if f" {nome} " in alvo:
                soma(cod, nome + " (CNES)")
                alvo = alvo.replace(f" {nome} ", " # ")      # o nome mais longo casa primeiro e sai do jogo
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
    (r"SOFTWARE|LICENCAS?(?: DE USO)?|LICENCIAMENTO|SOLUCAO DE (?:TI|TECNOLOGIA)|DATA ?CENTER|COMPUTACAO EM NUVEM|\bNUVEM\b|"
     r"LINK DE DADOS|LINKS DE (?:DADOS|INTERNET)|TELEFONIA|SUPORTE TECNICO|FABRICA DE SOFTWARE|SISTEMA INTEGRADO|PLATAFORMA DIGITAL",
     "tecnologia corporativa (uso de toda a organização)"),
    (r"COMBUSTIVE(?:L|IS)|ABASTECIMENTO DA FROTA|GERENCIAMENTO D[EA] FROTA|LOCACAO DE VEICULOS|MANUTENCAO D[EA] FROTA|VIATURAS",
     "frota (circula pelo Estado)"),
    (r"\bSEGUROS?\b|VALE (?:ALIMENTACAO|REFEICAO|TRANSPORTE)|MEIOS DE PAGAMENTO|PASSAGENS AEREAS|AGENCIAMENTO DE VIAGENS|"
     r"FOLHA DE PAGAMENTO|PLANO DE SAUDE|PLANO DE ASSISTENCIA MEDIC[OA]|ASSISTENCIA A SAUDE DO SERVIDOR|ASSISTENCIA MEDICA AOS SERVIDORES|"
     r"BENEFICIO (?:REFEICAO|ALIMENTACAO)|CARTOES ELETRONICOS|SECRETARIADO|ALMOXARIFADO VIRTUAL|NA SEDE D[AO]", "despesa de pessoal/administrativa da organização"),
    (r"CONSULTORIA|ASSESSORAMENTO|ASSESSORIA TECNICA|AUDITORIA|ESTUDOS? E PESQUISAS?|PESQUISA DE AVALIACAO|AVALIACAO EDUCACIONAL|CAPACITACAO|"
     r"TREINAMENTO|FORMACAO CONTINUADA|CONCURSO PUBLICO|PROCESSO SELETIVO", "serviço intelectual prestado ao órgão (sem local de execução)"),
    (r"MATERIAL DIDATICO|MATERIAL DE APOIO PEDAGOGICO|LIVROS DIDATICOS|UNIFORMES?|KITS? (?:ESCOLAR|DE UNIFORME|DE MATERIAL ESCOLAR)|MERENDA|MOBILIARIOS? ESCOLAR(?:ES)?|SALAS? DE LEITURA|"
     r"GENEROS(?: PRODUTOS)? ALIMENTICIOS|MEDICAMENTOS|INSUMOS|MATERIAL DE CONSUMO|ARMAMENTO|MUNICAO|COLETES|"
     r"AQUISICAO DE (?:HELICOPTERO|AERONAVES?|CARABINAS|PISTOLAS|FUZIS|VEICULOS|ONIBUS|AMBULANCIAS)", "aquisição distribuída à rede (sem ponto único de entrega no objeto)"),
    (r"PUBLICIDADE|PROPAGANDA|COMUNICACAO INSTITUCIONAL|SERVICOS POSTAIS|CORREIOS|ASSINATURA|PUBLICACAO (?:DE|NO)|"
     r"OUTSOURCING DE IMPRESSAO|SERVICOS GRAFICOS", "serviço corporativo"),
]
_ORGAO_MEIO = re.compile(r"PROCURADORIA GERAL|FAZENDA|PLANEJAMENTO|CASA CIVIL|CONTROLADORIA|PREVIDENCIA|JUNTA COMERCIAL|LOTERIA|"
                         r"CENTRO DE TECN|TRANSFORMACAO DIGITAL|GABINETE DE SEGURANCA|GOVERNO\b|REPRES DO GOV")
_RE_ABR = [(re.compile(rf"\b(?:{p})\b"), rot) for p, rot in _ABR_FRASE]
_RE_NAT = [(re.compile(rf"\b(?:{p})\b"), rot) for p, rot in _ABR_NATUREZA]


def natureza_corporativa(o_norm: str) -> str | None:
    """Regra de NATUREZA que casou (fonte única: o lado PCRJ usa a mesma lista)."""
    for rg, rot in _RE_NAT:
        m = rg.search(o_norm)
        if m:
            return f"{rot}: “{m.group(0).lower()}”"
    return None


def abrangencia_estado(objeto: str | None, orgao: str | None) -> str | None:
    """Motivo pelo qual o contrato é do Estado inteiro / da sede — ou None (aí é "sem município identificado")."""
    o = norm(objeto)
    for rg, rot in _RE_ABR:
        m = rg.search(o)
        if m:
            return f"Estado inteiro — {rot}: “{m.group(0).lower()}”"
    nat = natureza_corporativa(o)
    if nat:
        return f"Estado inteiro / sede — {nat}"
    if _ORGAO_MEIO.search(norm(orgao)):
        return f"sede — órgão-meio sem atividade territorial ({(orgao or '').strip()})"
    return None


_RE_CEP = re.compile(r"\bCEP\D{0,3}(\d{5})\D?(\d{3})\b")


def atribuir(objeto: str | None, unidade: str | None, regionais, unidades) -> dict:
    """Aplica os métodos e decide. Função PURA (é a que os testes exercitam)."""
    nomes = nome_municipio()
    metodos: list[dict] = []
    u = norm(unidade)
    for padrao, cod, conf, fonte in regionais:
        if padrao in u:
            metodos.append({"metodo": "campo", "cods": [cod], "confianca": conf, "evidencia": f"unidade: {unidade} — {fonte}"})
            break
    o = norm(objeto)
    if unidades:
        cods, evid, conf = _unidades_no_texto(o, unidades if isinstance(unidades, dict) else {"escolas": unidades})
        if cods:
            metodos.append({"metodo": "unidade", "cods": cods, "confianca": conf, "evidencia": "unidade citada: " + "; ".join(evid[:3])})
    m = _RE_CEP.search((objeto or "").upper())
    if m and 20000 <= int(m.group(1)) <= 23799:
        metodos.append({"metodo": "endereco", "cods": [RIO], "confianca": "alta",
                        "evidencia": f"CEP {m.group(1)}-{m.group(2)} (faixa da capital, Correios)"})
    lei = ler_municipios(objeto)
    if lei.municipios:
        metodos.append({"metodo": "texto", "cods": [a.cod_ibge for a in lei.municipios], "confianca": "media",
                        "evidencia": "; ".join(a.evidencia for a in lei.municipios[:4])})
    metodos.sort(key=lambda x: -FORCA[x["metodo"]])
    out = {"cod_ibge": None, "multi": 0, "municipios": [], "regiao": lei.regiao, "metodo": None, "confianca": None,
           "evidencia": None, "metodos": metodos, "abrangencia": None}
    if not metodos:
        if not lei.regiao:
            ab = abrangencia_estado(objeto, unidade)
            if ab:
                out.update(abrangencia="estado_inteiro", evidencia=ab)
        return out
    v = metodos[0]
    out.update(metodo=v["metodo"], confianca=v["confianca"], evidencia=v["evidencia"],
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
    """`rescindido` vence tudo; senão vigência final (já com aditivo de prazo) ≥ hoje = em execução."""
    if rescindido:
        return "rescindido"
    return "em_execucao" if vig_fim and vig_fim[:10] >= hoje else "executado"


def _digitos(s: str | None) -> str:
    return re.sub(r"\D", "", s or "")


def _pagamentos(c: sqlite3.Connection, contratos: list[dict], log=print) -> dict[str, tuple[float, str]]:
    """contrato_id → (pago, evidência). Ponte de processo: termo aditivo do próprio contrato, ou o
    registro do TCE-RJ/SIGA do mesmo CNPJ com o mesmo valor (±1%). Só fecha quando o par
    (processo, CNPJ) aponta para UM contrato: dividir a soma entre dois seria inventar número."""
    proc: dict[str, set] = {}
    for r in c.execute("SELECT numero_controle_pncp, processo FROM contrato_aditivo WHERE processo IS NOT NULL AND processo<>''"):
        d = _digitos(r[1])
        if len(d) >= 12:
            proc.setdefault(r[0], set()).add(d)
    por_cnpj: dict[str, list] = {}
    for r in c.execute("SELECT cnpj, valor_contrato, sei_norm FROM contratos_tcerj WHERE sei_norm IS NOT NULL AND sei_norm<>'' "
                       "AND cnpj IS NOT NULL AND valor_contrato>0"):
        por_cnpj.setdefault(_digitos(r[0]), []).append((float(r[1]), r[2]))
    chave_contratos: dict[tuple, list] = {}
    for k in contratos:
        cn, v = k["fornecedor_cnpj"], k["valor"] or 0
        ps = set(proc.get(k["contrato_id"], ()))
        ps.update(k.get("processos", ()))                # processo do próprio registro (fonte TCE-RJ/SIGA)
        if cn and v > 0:
            ps.update(s for val, s in por_cnpj.get(cn, ()) if abs(val - v) <= 0.01 * v)
        for p in ps:
            chave_contratos.setdefault((p, cn), []).append(k["contrato_id"])
    alvo = {k for k, v in chave_contratos.items() if len(v) == 1 and k[1]}
    log(f"[pago] {len(chave_contratos)} pares (processo, CNPJ); {len(alvo)} apontam para um único contrato")
    soma: dict[tuple, list] = {}
    n = 0
    for r in c.execute("SELECT processo, credor, valor FROM ob_orcamentaria_siafe WHERE status='Contabilizado' AND processo IS NOT NULL"):
        n += 1
        k = (_digitos(r[0]), _digitos(r[1]))
        if k in alvo:
            s = soma.setdefault(k, [0.0, 0])
            s[0] += float(r[2] or 0)
            s[1] += 1
    log(f"[pago] {n} OBs contabilizadas lidas do SIAFE; {len(soma)} pares com pagamento")
    valor = {k["contrato_id"]: k["valor"] or 0 for k in contratos}
    # um contrato pode ter MAIS de um processo vinculado (o do termo aditivo e o do TCE): soma por contrato
    por_contrato: dict[str, list] = {}
    for k, (tot, q) in soma.items():
        a = por_contrato.setdefault(chave_contratos[k][0], [0.0, 0, []])
        a[0] += tot
        a[1] += q
        a[2].append(k[0])
    out, ambiguos = {}, 0
    for cid, (tot, q, procs) in por_contrato.items():
        # soma muito acima do contrato = o processo paga MAIS do que este contrato (vínculo ambíguo).
        # Fica sem pagamento (INDISPONÍVEL) em vez de exibir 300% "executado".
        if valor[cid] > 0 and tot > 1.25 * valor[cid]:
            ambiguos += 1
            continue
        out[cid] = (round(tot, 2), f"{q} OB(s) SIAFE contabilizadas ao mesmo CNPJ no(s) processo(s) {', '.join(sorted(procs)[:3])}")
    log(f"[pago] {len(out)} contratos com pagamento vinculado; {ambiguos} descartados (OBs do processo > 125% do contrato)")
    return out


_ISO_BR = re.compile(r"(\d{2})/(\d{2})/(\d{4})")


def _iso(d: str | None) -> str | None:
    m = _ISO_BR.match(d or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def _integrar_tcerj(src: sqlite3.Connection, linhas: list[dict], hoje: str, fora: dict) -> tuple[int, int, int]:
    """Segunda fonte: `contratos_tcerj` (SIGA/TCE-RJ), só contratos com vigência (status Ativo/Encerrado).
    DEDUPLICAÇÃO conservadora — antes contar de menos do que em dobro:
      · contra o PNCP: mesmo CNPJ do fornecedor e valor dentro de ±10% → é o MESMO contrato (junta as fontes e o
        processo SEI; o objeto do TCE soma texto para a atribuição);
      · interna: mesmo CNPJ + valor + vigência (o SIGA repete credenciamentos por item/lote)."""
    por_cnpj: dict[str, list] = {}
    for k in linhas:
        if k["fornecedor_cnpj"]:
            por_cnpj.setdefault(k["fornecedor_cnpj"], []).append(k)
    vistos, juntados, novos, repetidos = set(), 0, 0, 0
    for r in src.execute("SELECT id, sei_norm, valor_contrato, status, unidade, objeto, fornecedor, cnpj, vig_inicio, vig_fim "
                         "FROM contratos_tcerj WHERE status IN ('Ativo','Encerrado') AND valor_contrato>0"):
        orgao = (r["unidade"] or "").split(" - ", 1)[-1].strip()
        esf = esfera_unidade(orgao)
        if esf != "estadual":
            fora[esf] += 1
            continue
        cnpj, valor = _digitos(r["cnpj"]), float(r["valor_contrato"])
        proc = r["sei_norm"] or ""
        par = next((k for k in por_cnpj.get(cnpj, ()) if k["valor"] and abs(k["valor"] - valor) <= 0.10 * valor), None) if cnpj else None
        if par is not None:
            if "tcerj" not in par["fontes"]:
                par["fontes"].append("tcerj")
                par["extra"] += " " + (r["objeto"] or "")
            if proc:
                par["processos"].add(proc)
            juntados += 1
            continue
        chave = (cnpj, round(valor), r["vig_inicio"], r["vig_fim"])
        # credenciamento: o SIGA repete o valor GLOBAL do processo para cada credenciado (CNPJs diferentes).
        # Mesmo processo SEI + mesmo valor = um contrato só; contar cada linha multiplicaria o valor.
        chave_proc = ("proc", proc, round(valor)) if proc else None
        if chave in vistos or (chave_proc and chave_proc in vistos):
            repetidos += 1
            continue
        vistos.add(chave)
        if chave_proc:
            vistos.add(chave_proc)
        fim = _iso(r["vig_fim"])
        novo = {"contrato_id": f"TCERJ-{r['id']}", "orgao": orgao, "fornecedor_cnpj": cnpj, "fornecedor_nome": r["fornecedor"],
                "objeto": r["objeto"], "valor": valor, "vig_ini": _iso(r["vig_inicio"]), "vig_fim": fim,
                "status": "executado" if (r["status"] == "Encerrado" or not fim or fim < hoje) else "em_execucao",
                "fontes": ["tcerj"], "processos": {proc} if proc else set(), "extra": ""}
        linhas.append(novo)
        if cnpj:
            por_cnpj.setdefault(cnpj, []).append(novo)
        novos += 1
    return juntados, novos, repetidos


def _enriquecer_doerj(src: sqlite3.Connection, linhas: list[dict]) -> int:
    """Extrato publicado no DOERJ (ato tipo `contrato` com processo SEI extraído) soma TEXTO ao contrato do
    mesmo processo. Não cria contrato: só dá mais chão para os métodos `unidade` e `texto`."""
    por_proc: dict[str, str] = {}
    for r in src.execute("SELECT processos_sei_extraidos, texto FROM publicacoes_doerj WHERE tipo_ato='contrato' "
                         "AND processos_sei_extraidos IS NOT NULL AND processos_sei_extraidos NOT IN ('', '[]')"):
        try:
            procs = json.loads(r[0])
        except ValueError:
            procs = [r[0]]
        for pr in procs if isinstance(procs, list) else [procs]:
            d = _digitos(str(pr))
            if len(d) >= 12:
                por_proc.setdefault(d, (r[1] or "")[:1500])
    n = 0
    for k in linhas:
        txt = [por_proc[p] for p in k["processos"] if p in por_proc]
        if txt:
            k["extra"] += " " + " ".join(txt)
            if "doerj" not in k["fontes"]:
                k["fontes"].append("doerj")
            n += 1
    return n


def rodar(incremental: bool = False, log=print) -> dict:
    hoje = date.today().isoformat()
    src = base.fonte_ro("compliance.db")
    montar_unidades(log)
    regionais, unidades = _unidades_regionais(), carregar_unidades()
    adit: dict[str, dict] = {}
    for r in src.execute("SELECT numero_controle_pncp, tipo_termo, vigencia_fim FROM contrato_aditivo"):
        a = adit.setdefault(r[0], {"resc": False, "fim": None})
        if eh_rescisao(r[1]):
            a["resc"] = True
        if r[2] and (a["fim"] is None or r[2] > a["fim"]):
            a["fim"] = r[2]
    linhas, fora = [], {"municipal": 0, "outro": 0}
    for r in src.execute("SELECT numero_controle_pncp, unidade, fornecedor_documento, fornecedor_nome, objeto, valor_global, "
                         "valor_inicial, vigencia_ini, vigencia_fim FROM pcrj_contratos WHERE fonte='pncp_estado' AND orgao_cnpj=?",
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
                       "vig_fim": (fim or "")[:10] or None, "status": status, "fontes": ["pncp"], "processos": set(), "extra": ""})
    n_pncp = len(linhas)
    log(f"[estado] PNCP: {n_pncp} contratos do Executivo estadual; fora do escopo: {fora['municipal']} de unidade municipal, "
        f"{fora['outro']} de órgão fora do Executivo")
    juntados, novos, repetidos = _integrar_tcerj(src, linhas, hoje, fora)
    log(f"[estado] TCE-RJ/SIGA: {juntados} registros casaram com contrato do PNCP (mesmo CNPJ, valor ±10%), {novos} contratos novos, "
        f"{repetidos} repetições internas descartadas")
    n_doe = _enriquecer_doerj(src, linhas)
    log(f"[estado] DOERJ: {n_doe} contratos ganharam o texto do extrato publicado (casados por processo SEI)")
    pagos = _pagamentos(src, linhas, log)
    src.close()

    db = base.abrir(escrita=True)
    ja = {r[0]: r[1] for r in db.execute("SELECT contrato_id, assinatura FROM territorio_contrato_estado")} if incremental else {}
    agora, n_grav = base.agora(), 0
    for k in linhas:
        pago, pago_ev = pagos.get(k["contrato_id"], (None, None))
        ass = hashlib.sha1(json.dumps([k["objeto"], k["extra"], k["orgao"], k["valor"], k["vig_fim"], k["status"], pago, k["fontes"], "7b"],
                                      ensure_ascii=False, default=str).encode()).hexdigest()
        if incremental and ja.get(k["contrato_id"]) == ass:
            continue
        at = atribuir(((k["objeto"] or "") + " " + k["extra"]).strip(), k["orgao"], regionais, unidades)
        rotulo = " + ".join({"pncp": "PNCP", "tcerj": "TCE-RJ/SIGA", "doerj": "DOERJ"}[f] for f in k["fontes"])
        db.execute("INSERT OR REPLACE INTO territorio_contrato_estado(contrato_id,fonte,orgao,fornecedor_cnpj,fornecedor_nome,objeto,"
                   "valor,vig_ini,vig_fim,status,pago,cod_ibge,multi,municipios_json,regiao,metodo,confianca,evidencia,metodos_json,"
                   "pago_evidencia,assinatura,atualizado_em,fontes_json,abrangencia) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (k["contrato_id"], rotulo, k["orgao"], k["fornecedor_cnpj"], k["fornecedor_nome"], k["objeto"], k["valor"],
                    k["vig_ini"], k["vig_fim"], k["status"], pago, at["cod_ibge"], at["multi"],
                    json.dumps(at["municipios"], ensure_ascii=False), at["regiao"], at["metodo"], at["confianca"], at["evidencia"],
                    json.dumps(at["metodos"], ensure_ascii=False), pago_ev, ass, agora, json.dumps(k["fontes"]), at["abrangencia"]))
        n_grav += 1
    if not incremental:      # contrato que saiu da fonte (ou do escopo) sai daqui
        vivos = {k["contrato_id"] for k in linhas}
        mortos = [r[0] for r in db.execute("SELECT contrato_id FROM territorio_contrato_estado") if r[0] not in vivos]
        db.executemany("DELETE FROM territorio_contrato_estado WHERE contrato_id=?", [(m,) for m in mortos])
    base.por_meta(db, "estado_fora_municipal", str(fora["municipal"]))
    base.por_meta(db, "estado_fora_outro", str(fora["outro"]))
    base.por_meta(db, "estado_rodado_em", agora)
    db.commit()
    db.close()
    log(f"[estado] {n_grav} contratos gravados em territorio.db ({'incremental' if incremental else 'completo'})")
    return {"contratos": len(linhas), "gravados": n_grav, "fora": fora, "com_pago": len(pagos)}
