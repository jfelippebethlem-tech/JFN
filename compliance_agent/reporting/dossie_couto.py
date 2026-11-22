# -*- coding: utf-8 -*-
"""Dossiê-mestre da gestão Couto (23/03/2026 →) — execução orçamentária, contratações, atos do governador em
exercício e achados que passaram nos portões, num PDF de padrão de controle externo, AUTOATUALIZÁVEL e VERIFICADO.

Pedido do dono (22/11/2026): "50% do esforço destinado ao período" do governo Couto e "tem que ser grandioso" —
velocidade, eficiência e perfeição. O documento é gerado pelo gerador da casa (`render_html`) e convertido em PDF
pelo mesmo Chromium (Playwright), com numeração de páginas (pedido explícito deste produto).

Três garantias, todas conferidas por código (`verificar`) antes de o PDF valer:
  1. TODO número monetário, percentual ou de tabela do HTML é um FATO com id (`dossie_couto:<chave>:valor`),
     publicado em `data/dossie_couto/fatos.json` e registrado no registro de fatos da casa pela declaração `fatos:`
     do derivado `dossie_couto` em `config/propagacao.yaml`. O texto carrega `<!--fato:ID-->` ao lado do número.
  2. Só é ACHADO o item que (a) a régua marcou VERIFICADO com grau 🔴/🟡 e (b) teve AO MENOS UMA prova primária
     RECONFERIDA agora na fonte (OB no SIAFE com o mesmo número, UG e valor, ainda paga; registro no CEIS; contrato
     no espelho do TCE-RJ) e NENHUMA prova divergente. O resto vai, declarado, para "não passou nos portões".
  3. O PDF não perdeu conteúdo do HTML: cada valor de fato e cada id de achado está no texto extraído do PDF, e a
     cobertura de palavras do HTML no PDF é ≥ 99%.

Regras da casa: pago = SÓ OB que é pagamento (`cruzamentos_intel._ob_paga`: Contabilizada, não devolvida, sem
pagamento complementar, sem reemitida, com número); empenho nunca é pago; contrato é CONTRATADO; TAC é valor
RECONHECIDO, não OB; INDISPONÍVEL ≠ zero; CPF nunca sai (pessoa física só agregada); indício ≠ acusação; escopo RJ.
Peça externa: nenhum nome interno (gate `neutralidade.garantir_neutro`).

Uso (comando único — também é o que a propagação chama, via tools/dossie_couto.sh):
  python -m compliance_agent.reporting.dossie_couto gerar [--ob-brutos ARQ]     # coleta + HTML + PDF + verificação
  python -m compliance_agent.reporting.dossie_couto coletar-ob --saida ARQ      # só a varredura pesada de OB (réplica)
  python -m compliance_agent.reporting.dossie_couto verificar                   # reconfere o último PDF
  python -m compliance_agent.reporting.dossie_couto juiz [--n 6]                # juiz de qualidade (assinatura)
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import html as H
import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

from compliance_agent import governo_couto as gc
from compliance_agent.certeza.config import BASE_PAGO_CONFIRMADO
from compliance_agent.certeza.fatos import brl
from compliance_agent.cpf_cnpj import mascarar_cpf_no_texto as mascarar
from compliance_agent.reporting.completude import campo, top_declarado, tudo

logger = logging.getLogger(__name__)

RAIZ = Path(__file__).resolve().parents[2]
DATA = RAIZ / "data"
DIR = Path(os.environ.get("JFN_DOSSIE_COUTO_DIR") or DATA / "dossie_couto")
REPORTS = Path(os.environ.get("JFN_DOSSIE_COUTO_REPORTS") or RAIZ / "reports")
BASE_ARQ = "dossie_governo_couto"
FAMILIA = "dossie_couto"
INICIO = gc.INICIO
ENVIO_CONFIRMADO = ("Processado e Pago", "Enviado Manualmente")
SEI_PESQUISA = ("https://sei.rj.gov.br/sei/modulos/pesquisa/md_pesq_processo_pesquisar.php?acao_externa="
                "protocolo_pesquisar&acao_origem_externa=protocolo_pesquisar&id_orgao_acesso_externo=6")
COBERTURA_MIN = 0.99
_ISO = gc._OB_ISO
GRAU_ROTULO = {"🔴": ("GRAVE", "g3"), "🟡": ("ATENÇÃO", "g2"), "⚪": ("INCONCLUSIVO", "g1")}
REGUA = {
    "D01": "Contratação direta por unidade, comparada ao ano anterior", "D02": "Emergencial ao fornecedor incumbente",
    "D03": "Empresa recém-aberta ou com capital incompatível", "D04": "ME/EPP acima do teto legal de faturamento",
    "D05": "Concentração de credor por órgão", "D06": "Aditivo de valor acima de 25%/50%", "D07": "Fracionamento",
    "D08": "Contratos e pagamentos nos primeiros 15 dias", "D09": "Pico de pagamento na última semana do governo anterior",
    "D10": "Credor sem histórico que passou a receber ≥ R$ 5 mi", "D11": "Créditos adicionais por decreto",
    "D12": "Mudança de comando em órgãos", "D13": "Sócio de credor que é agente público",
    "D14": "Empresa sancionada paga na vigência da sanção", "D15": "Doação eleitoral de sócio de credor",
    "D16": "Termo de Ajuste de Contas (serviço sem cobertura contratual)", "D17": "Emergência recorrente no exercício",
    "D18": "Sinais de fachada já registrados", "D19": "Remuneração acima do teto constitucional",
    "D20": "OB anulada ou excluída",
}
NORMAS = (
    ("Constituição Federal, arts. 37, 70, 71 e 75", "legalidade, impessoalidade, moralidade, publicidade e eficiência; "
     "controle externo pelo Legislativo com auxílio do Tribunal de Contas, aplicado aos Estados pelo art. 75"),
    ("Constituição Federal, art. 50, § 2º (por simetria)", "pedido escrito de informação da Casa Legislativa a "
     "Secretário de Estado — base do requerimento de informação"),
    ("Constituição Federal, art. 167, V", "vedação de crédito suplementar ou especial sem prévia autorização legislativa"),
    ("Lei nº 4.320/1964, arts. 36, 40–46 e 58–65", "restos a pagar; créditos adicionais; empenho, liquidação e pagamento — "
     "só a ordem de pagamento extingue a obrigação"),
    ("Lei Complementar nº 101/2000 (LRF), arts. 1º, § 1º, e 42", "gestão fiscal responsável; vedação de obrigação sem "
     "disponibilidade nos dois últimos quadrimestres do mandato"),
    ("Lei nº 14.133/2021, arts. 72, 74, 75, 124, 125 e 156", "instrução da contratação direta; inexigibilidade; dispensa "
     "(inclusive emergencial, art. 75, VIII); alterações e limite de acréscimo de 25%/50%; sanções"),
    ("Lei nº 12.846/2013, arts. 22 e 23", "Cadastro Nacional de Empresas Punidas e Cadastro de Empresas Inidôneas e "
     "Suspensas (CEIS)"),
    ("Lei Complementar nº 123/2006, art. 3º", "receita bruta anual que define microempresa e empresa de pequeno porte"),
    ("Lei Complementar estadual nº 63/1990", "Lei Orgânica do Tribunal de Contas do Estado do Rio de Janeiro"),
    ("Lei nº 12.527/2011 e Lei nº 13.709/2018", "acesso à informação; proteção de dados pessoais — pessoa física só "
     "aparece agregada, sem CPF"),
)


# ───────────────────────────── utilidades ─────────────────────────────
def _ano(iso: str) -> int:
    return int(str(iso).split("-")[0])


def _menos_um_ano(iso: str) -> str:
    a, m, d = str(iso).split("-")
    d = "28" if (m, d) == ("02", "29") else d
    return f"{int(a) - 1}-{m}-{d}"


def _br(iso: str | None) -> str:
    if not iso:
        return "—"
    p = str(iso).split("T")[0].split("-")
    return f"{p[2]}/{p[1]}/{p[0]}" if len(p) == 3 else str(iso)


def _dig(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _e(s) -> str:
    return H.escape(str(s if s is not None else ""), quote=False)


def _ro(caminho: Path) -> sqlite3.Connection | None:
    return gc._ro(caminho)


def exibir(valor, unidade: str) -> str:
    """A forma ÚNICA de imprimir um fato (o verificador compara o texto do HTML com esta função)."""
    if valor is None:
        return "INDISPONÍVEL"
    if unidade == "BRL":
        return brl(valor)
    if unidade == "contagem":
        return f"{int(round(valor)):,}".replace(",", ".")
    if unidade == "percentual":
        return f"{float(valor):.1f}%".replace(".", ",")
    s = f"{float(valor):+.1f}%".replace(".", ",")         # indice = variação percentual
    return s.replace("-", "−")


# ───────────────────────────── registro de fatos ─────────────────────────────
class Registro:
    """Todo número que o dossiê imprime nasce aqui, com id, fonte, consulta e estado. Mesmo id com dois valores é
    erro (o documento não pode afirmar duas coisas sobre o mesmo fato)."""

    LISTA = {"BRL": "brl", "contagem": "contagem", "percentual": "percentual", "indice": "indice"}

    def __init__(self, data_ref: str):
        self.data_ref = data_ref
        self.f: dict[str, dict] = {}
        self.por_chave: dict[str, str] = {}

    def put(self, chave: str, valor, unidade: str, rotulo: str, fonte: str, consulta: str, *, estado: str = "VERIFICADO",
            nivel: int = 2, natureza: str = "contagem", base: str = "") -> str:
        chave = re.sub(r"[^A-Za-z0-9.\-]+", "_", chave).strip("_.") or "x"
        if valor is None:
            estado = "INDISPONIVEL"
        else:
            valor = (round(float(valor), 2) if unidade == "BRL" else int(round(float(valor))) if unidade == "contagem"
                     else round(float(valor), 1))
            if unidade == "percentual" and not 0 <= valor <= 100:
                unidade = "indice"
        if estado == "VERIFICADO" and nivel != 2:
            estado = "A CONFERIR"
        if natureza == "pago" and estado == "VERIFICADO" and base != BASE_PAGO_CONFIRMADO:
            estado = "A CONFERIR"
        fid = f"{FAMILIA}:{self.LISTA[unidade]}:{chave}:valor"
        if chave in self.por_chave and self.por_chave[chave] != fid:
            raise ValueError(f"fato {chave} com duas unidades")
        self.por_chave[chave] = fid
        novo = {"chave": chave, "fato_id": fid, "valor": valor, "unidade": unidade, "rotulo": mascarar(rotulo),
                "fonte": fonte, "consulta": consulta, "estado": estado, "nivel": nivel, "natureza": natureza,
                "base": base or "", "exibido": exibir(valor, unidade)}
        ant = self.f.get(fid)
        if ant and (ant["valor"], ant["unidade"]) != (valor, unidade):
            raise ValueError(f"fato {fid} com dois valores: {ant['valor']} × {valor}")
        self.f.setdefault(fid, novo)
        return fid

    def ref(self, x: str) -> str:
        """Aceita o id completo ou a forma curta `dossie_couto:<chave>:valor` / `<chave>`."""
        if x in self.f:
            return x
        chave = x.split(":", 1)[1].rsplit(":", 1)[0] if x.startswith(FAMILIA + ":") else x
        return self.por_chave[chave]

    def tem(self, x: str) -> bool:
        try:
            return self.ref(x) in self.f
        except KeyError:
            return False

    def span(self, fid: str) -> str:
        fid = self.ref(fid)
        f = self.f[fid]
        return f'<span class="fato" data-fato="{fid}">{_e(f["exibido"])}</span><!--fato:{fid}-->'

    def v(self, chave, valor, unidade, rotulo, fonte, consulta, **k) -> str:
        return self.span(self.put(chave, valor, unidade, rotulo, fonte, consulta, **k))

    def publicar(self) -> dict:
        listas = {"brl": [], "contagem": [], "percentual": [], "indice": []}
        for f in sorted(self.f.values(), key=lambda x: x["fato_id"]):
            listas[self.LISTA[f["unidade"]]].append(f)
        return {"gerado_em": self.data_ref, "n": len(self.f), **listas}


_RX_NUM_TEXTO = re.compile(r"(?P<aprox>R\$\s?\d+(?:,\d+)?(?:\s?a\s?\d+(?:,\d+)?)?\s?(?:mi|bi|mil)\b)"
                           r"|R\$\s?-?\d{1,3}(?:\.\d{3})*,\d{2}|[+\-−]?\d{1,3}(?:\.\d{3})*(?:,\d+)?\s?%")
_MULT = {"mil": 1e3, "mi": 1e6, "bi": 1e9}


def valor_aproximado(txt: str) -> float:
    """'R$ 111 a 120 mi' → 111000000.0 (o fato registra o PRIMEIRO número; o texto declara a faixa)."""
    m = re.match(r"R\$\s?(\d+(?:,\d+)?).*?(mil|mi|bi)\b", txt)
    return round(float(m.group(1).replace(",", ".")) * _MULT[m.group(2)], 2)
# limiar de critério ou de norma ("≥ R$ 5 mi", "acréscimo de 25%"): não é medida, é a régua — marcado como tal
_RX_LIMIAR = re.compile(r"R\$\s?\d+(?:,\d+)?\s?(?:mi|bi|mil)\b|\d{1,3}(?:,\d+)?\s?%")


def lim(texto: str) -> str:
    """Escapa texto ESCRITO AQUI (norma, nome de critério, aviso) marcando limiares como limiar, não como fato."""
    out, pos = [], 0
    for m in _RX_LIMIAR.finditer(str(texto)):
        out += [_e(texto[pos:m.start()]), f'<span class="limiar">{_e(m.group(0))}</span>']
        pos = m.end()
    return "".join(out) + _e(texto[pos:])


def _num_br(s: str) -> float:
    return float(s.replace("R$", "").replace("%", "").replace("−", "-").replace(".", "").replace(",", ".").strip())


def texto_com_fatos(reg: Registro, texto: str, chave_base: str, fonte: str, *, estado: str = "A CONFERIR") -> str:
    """Escapa o texto e troca cada número monetário/percentual por um fato com id (o número continua sendo o da
    régua que o escreveu — o fato declara isso na fonte e no estado)."""
    out, pos, k = [], 0, 0
    t = mascarar(str(texto or ""))
    for m in _RX_NUM_TEXTO.finditer(t):
        out.append(lim_so_valor(t[pos:m.start()]))
        bruto = m.group(0)
        k += 1
        if m.group("aprox"):
            fid = reg.put(f"{chave_base}.n{k}", valor_aproximado(bruto), "BRL",
                          f"{k}º número citado no texto ({chave_base}) — valor APROXIMADO, impresso como no original",
                          fonte, "texto publicado pela fonte/régua (aproximação do original; primeiro número da faixa)",
                          estado="A CONFERIR", nivel=1, natureza="regua")
            out.append(f'<span class="fato" data-fato="{fid}" data-aprox="1">{_e(bruto)}</span><!--fato:{fid}-->')
            pos = m.end()
            continue
        if bruto.startswith("R$"):
            un, nat = "BRL", "regua"
        elif bruto[0] in "+-−":
            un, nat = "indice", "regua"
        else:
            un, nat = "percentual", "regua"
        fid = reg.put(f"{chave_base}.n{k}", _num_br(bruto), un, f"{k}º número citado no texto ({chave_base})", fonte,
                      "texto publicado pela fonte/régua (número reproduzido, não recalculado aqui)", estado=estado,
                      nivel=1, natureza=nat)
        out.append(reg.span(fid))        # forma canônica do fato ("30%" sai "30,0%"; o valor é o mesmo)
        pos = m.end()
    out.append(lim_so_valor(t[pos:]))
    return "".join(out)


def lim_so_valor(texto: str) -> str:
    """Trecho entre números medidos: o que sobrar com R$ é limiar do critério ("≥ R$ 5 mi")."""
    out, pos = [], 0
    for m in re.finditer(r"R\$\s?\d+(?:,\d+)?\s?(?:mi|bi|mil)\b", texto):
        out += [_e(texto[pos:m.start()]), f'<span class="limiar">{_e(m.group(0))}</span>']
        pos = m.end()
    return "".join(out) + _e(texto[pos:])


# ───────────────────────────── coleta: OB (a parte pesada, roda na réplica) ─────────────────────────────
def _classe_sql(paga: str) -> str:
    conf = ",".join(f"'{x}'" for x in ENVIO_CONFIRMADO)
    return (f"CASE WHEN ({paga}) THEN CASE WHEN COALESCE(status_envio,'') IN ({conf}) THEN 'confirmada' "
            f"ELSE 'sem_confirmacao' END "
            "WHEN COALESCE(status,'')<>'Contabilizado' THEN 'status:'||COALESCE(status,'') "
            "WHEN COALESCE(status_envio,'')='Erro no Pagamento' THEN 'devolvida' "
            "WHEN COALESCE(tipo_regularizacao,'')='Pagamento Complementar' THEN 'complementar' "
            "WHEN COALESCE(numero_ob,'')='' THEN 'sem_numero' ELSE 'reemitida' END")


def _varrer(con: sqlite3.Connection, ini: str, fim: str, paga: str) -> list[list]:
    """UMA varredura da janela: agrupa por UG × credor × tipo de OB × classe (pago confirmado, pago sem confirmação
    de envio, ou o motivo de NÃO ser pagamento). Pessoa física é agregada na própria consulta (nem o nome sai)."""
    # ob-qualquer-status: a varredura CLASSIFICA cada OB (paga confirmada, paga sem confirmação ou o motivo de NÃO ser
    # pagamento, pela regra única `_ob_paga`); a soma de pago usa só as classes pagas, o resto vai a "fora da soma".
    sql = (f"SELECT ug_emitente, CASE WHEN length(credor)=11 THEN 'PF' ELSE credor END c, "
           f"CASE WHEN length(credor)=11 THEN '' ELSE MAX(nome_credor) END, COALESCE(tipo_ob,''), {_classe_sql(paga)} k, "
           # ob-qualquer-status (classifica; a soma de pago usa só as classes pagas)
           f"COUNT(*), ROUND(SUM(valor),2), MAX({_ISO}) FROM ob_orcamentaria_siafe "
           f"WHERE exercicio=? AND {_ISO} BETWEEN ? AND ? GROUP BY 1, 2, 4, 5")
    return [list(r) for r in con.execute(sql, (_ano(ini), ini, fim))]


def coletar_ob(con: sqlite3.Connection, inicio: str = INICIO, hoje: str | None = None) -> dict:
    from compliance_agent.cruzamentos_intel import _ob_paga
    paga = _ob_paga(con)
    hoje = hoje or date.today().isoformat()
    t0 = time.time()
    g = _varrer(con, inicio, hoje, paga)
    fim = max((r[7] for r in g if r[4] in ("confirmada", "sem_confirmacao") and r[7]), default=None)
    if not fim:
        return {"estado": "indisponivel", "erro": "nenhuma OB paga no período", "inicio": inicio}
    ini_a, fim_a = _menos_um_ano(inicio), _menos_um_ano(fim)
    ga = _varrer(con, ini_a, fim_a, paga)
    # ob-qualquer-status: metadado da coleta (rowid da réplica para a amostra igual), não soma
    mx = con.execute("SELECT MAX(rowid), MAX(coletado_em) FROM ob_orcamentaria_siafe").fetchone()
    return {"estado": "ok", "inicio": inicio, "fim": fim, "inicio_ant": ini_a, "fim_ant": fim_a,
            "colunas": ["ug", "credor", "nome", "tipo_ob", "classe", "n", "valor", "max_data"],
            "couto": g, "anterior": ga, "max_rowid": mx[0], "ultima_coleta": mx[1], "regra_paga": paga,
            "segundos": round(time.time() - t0, 1), "gerado_em": datetime.now().isoformat(timespec="seconds"),
            "maquina": os.uname().nodename}


def conferir_amostra(con: sqlite3.Connection, brutos: dict, n: int = 3) -> dict:
    """Amostra igual: a VM-1 recalcula, no banco vivo e limitado ao rowid que a réplica tinha, o pago de n UGs
    pequenas nas DUAS janelas e compara com o que veio da réplica. Divergiu → o JSON da réplica é recusado."""
    from compliance_agent.cruzamentos_intel import _ob_paga
    paga = _ob_paga(con)
    soma = defaultdict(lambda: [0, 0.0])
    for jan in ("couto", "anterior"):
        for r in brutos[jan]:
            if r[4] in ("confirmada", "sem_confirmacao"):
                soma[(jan, r[0])][0] += r[5]
                soma[(jan, r[0])][1] += r[6] or 0
    ugs = sorted({ug for (j, ug), (k, _v) in soma.items() if j == "couto" and k >= 3}, key=lambda u: soma[("couto", u)][0])
    escolhidas = ugs[len(ugs) // 2:len(ugs) // 2 + n] if len(ugs) > n else ugs
    det, ok = [], bool(escolhidas)
    for ug in escolhidas:
        for jan, ini, fim in (("couto", brutos["inicio"], brutos["fim"]), ("anterior", brutos["inicio_ant"], brutos["fim_ant"])):
            r = con.execute(f"SELECT COUNT(*), ROUND(COALESCE(SUM(valor),0),2) FROM ob_orcamentaria_siafe WHERE "
                            f"ug_emitente=? AND exercicio=? AND {_ISO} BETWEEN ? AND ? AND rowid<=? AND {paga}",
                            (ug, _ano(ini), ini, fim, brutos["max_rowid"])).fetchone()
            esperado = soma.get((jan, ug), [0, 0.0])
            igual = r[0] == esperado[0] and abs((r[1] or 0) - esperado[1]) < 0.01
            ok &= igual
            det.append({"ug": ug, "janela": jan, "local": [r[0], r[1]], "replica": [esperado[0], round(esperado[1], 2)],
                        "igual": igual})
    return {"ok": ok, "amostra": det}


# ───────────────────────────── coleta: o resto (leve, na VM-1) ─────────────────────────────
def _cadastro_ug(con_ab: sqlite3.Connection | None) -> tuple[dict, dict, dict]:
    from compliance_agent.comissao_orcamento import nomes_orgao, ug_para_orgao
    u2o, nomes = ug_para_orgao(con_ab), nomes_orgao(con_ab)
    nome_ug: dict[str, str] = {}
    if con_ab is not None:
        try:
            for ug, n in con_ab.execute("SELECT ug, MAX(nome_ug) FROM da_despesa WHERE COALESCE(nome_ug,'')<>'' GROUP BY ug"):
                nome_ug[str(ug)] = str(n).strip()
        except sqlite3.Error as exc:
            logger.warning("dossiê Couto: nomes de UG indisponíveis: %s", exc)
    return u2o, nomes, nome_ug


def _poder(orgao: str) -> str:
    from compliance_agent.comissao_orcamento import PODER
    return PODER.get(str(orgao), "Executivo")


def _janela_coberta(con: sqlite3.Connection, tabela: str, col: str, ini: str) -> tuple[bool, str | None]:
    """A fonte começa ANTES do início da janela? Se não, a janela é INDISPONÍVEL (a coleta não alcança), não zero."""
    d0 = con.execute(f"SELECT MIN({col}) FROM {tabela}").fetchone()[0]
    return (bool(d0) and str(d0) <= ini), (str(d0) if d0 else None)


def coletar_contratacoes(con: sqlite3.Connection) -> dict:
    diretas = {r[0]: (r[1], r[2]) for r in con.execute(
        "SELECT sei_norm, afastamento, enquadramento_legal FROM compras_diretas_tcerj WHERE sei_norm IS NOT NULL")}
    ult = con.execute("SELECT MAX(substr(data_contratacao,1,10)) FROM contratos_tcerj").fetchone()[0]
    out = {"ultimo_registro": ult, "janelas": {}}
    for jan, ini, fim in (("couto", INICIO, ult), ("anterior", _menos_um_ano(INICIO), _menos_um_ano(ult))):
        ok, d0 = _janela_coberta(con, "contratos_tcerj", "substr(data_contratacao,1,10)", ini)
        if not ok:
            out["janelas"][jan] = {"inicio": ini, "fim": fim, "indisponivel": f"o espelho começa em {d0}", "modalidades": {},
                                   "lista": [], "n_cancelados": None}
            continue
        rows = con.execute(
            "SELECT processo, sei_norm, substr(data_contratacao,1,10), valor_contrato, status, unidade, objeto, "
            "fornecedor, cnpj FROM contratos_tcerj WHERE substr(data_contratacao,1,10) BETWEEN ? AND ?", (ini, fim)).fetchall()
        mods: dict[str, list] = defaultdict(lambda: [0, 0.0])
        lista, canc = [], 0
        for p, sei, d, v, st, un, obj, forn, cnpj in rows:
            if (st or "") == "Cancelado":
                canc += 1
                continue
            mod = gc._modalidade(diretas.get(sei), obj or "")
            emerg = mod.startswith("Dispensa — emergencial") or "EMERG" in gc._sem_acento(obj or "")
            chave = ("Dispensa — emergencial" if emerg else "Inexigibilidade" if mod == "Inexigibilidade" else
                     "Dispensa (outras hipóteses)" if mod == "Dispensa" else "Licitação ou sem registro de contratação direta")
            mods[chave][0] += 1
            mods[chave][1] += float(v or 0)
            tipo, doc = gc.doc_exibivel(_dig(cnpj))
            lista.append({"processo": p, "data": d, "valor": float(v or 0), "orgao": (un or "—").strip(),
                          "objeto": mascarar(obj or ""), "fornecedor": "" if tipo == "CPF" else mascarar(forn or ""),
                          "doc": doc if tipo == "CNPJ" else ("pessoa física" if tipo == "CPF" else doc), "modalidade": chave})
        lista.sort(key=lambda x: -x["valor"])
        out["janelas"][jan] = {"inicio": ini, "fim": fim, "n_cancelados": canc,
                               "modalidades": {k: {"n": a, "valor": round(b, 2)} for k, (a, b) in mods.items()},
                               "lista": lista if jan == "couto" else []}
    return out


def coletar_aditivos(con: sqlite3.Connection) -> dict:
    from compliance_agent import esfera_orgao as eo
    ult = con.execute("SELECT MAX(substr(data_assinatura,1,10)) FROM contrato_aditivo").fetchone()[0]
    out = {"ultimo_registro": ult, "janelas": {}}
    for jan, ini, fim in (("couto", INICIO, ult), ("anterior", _menos_um_ano(INICIO), _menos_um_ano(ult))):
        ok, d0 = _janela_coberta(con, "contrato_aditivo", "substr(data_assinatura,1,10)", ini)
        if not ok:
            out["janelas"][jan] = {"inicio": ini, "fim": fim, "indisponivel": f"a coleta começa em {d0}", "n": None,
                                   "n_sem_valor": None, "valor_acrescido": None}
            continue
        n = n_sem = 0
        v = 0.0
        for ctrl, val in con.execute("SELECT numero_controle_pncp, valor_acrescido FROM contrato_aditivo WHERE "
                                     "substr(data_assinatura,1,10) BETWEEN ? AND ?", (ini, fim)):
            if eo.esfera(_dig(str(ctrl or "").split("-")[0]), "") != "estadual-rj":
                continue
            n += 1
            if val is None:
                n_sem += 1
            else:
                v += float(val)
        out["janelas"][jan] = {"inicio": ini, "fim": fim, "n": n, "n_sem_valor": n_sem, "valor_acrescido": round(v, 2)}
    return out


def coletar_tac(con: sqlite3.Connection) -> dict:
    ult = con.execute("SELECT MAX(data_doe) FROM doerj_tac").fetchone()[0]
    out = {"ultimo_registro": ult, "janelas": {}}
    for jan, ini, fim in (("couto", INICIO, ult), ("anterior", _menos_um_ano(INICIO), _menos_um_ano(ult))):
        ok, d0 = _janela_coberta(con, "doerj_tac", "data_doe", ini)
        if not ok:
            out["janelas"][jan] = {"inicio": ini, "fim": fim, "indisponivel": f"a coleta do Diário começa em {d0}",
                                   "n": None, "valor": None, "n_sem_valor": None, "fornecedores": []}
            continue
        rows = con.execute("SELECT fornecedor, cnpj, valor, orgao FROM doerj_tac WHERE data_doe BETWEEN ? AND ?",
                           (ini, fim)).fetchall()
        por = defaultdict(lambda: {"n": 0, "valor": 0.0, "orgaos": set(), "cnpj": ""})
        for forn, cnpj, val, org in rows:
            tipo, doc = gc.doc_exibivel(_dig(cnpj))
            k = "pessoa física" if tipo == "CPF" else mascarar((forn or "—").strip().upper())
            por[k]["n"] += 1
            por[k]["valor"] += float(val or 0)
            por[k]["orgaos"].add((org or "—").strip())
            por[k]["cnpj"] = por[k]["cnpj"] or (doc if tipo == "CNPJ" else "")
        lista = sorted(({"fornecedor": k, "n": x["n"], "valor": round(x["valor"], 2), "cnpj": x["cnpj"],
                         "orgaos": sorted(x["orgaos"])} for k, x in por.items()), key=lambda x: -x["valor"])
        out["janelas"][jan] = {"inicio": ini, "fim": fim, "n": len(rows),
                               "valor": round(sum(float(r[2] or 0) for r in rows), 2),
                               "n_sem_valor": sum(1 for r in rows if r[2] is None),
                               "fornecedores": lista if jan == "couto" else []}
    return out


# padrões já SEM acento e em maiúsculas: casam contra `_sem_acento(ementa)` (o padrão nunca passa por _sem_acento,
# que poria `\s` em maiúscula e o transformaria em `\S` — foi assim que os 70 decretos caíram todos no balde genérico)
_RX_CRED = (("crédito suplementar", r"CREDITOS?\s+SUPLEMENTAR"), ("crédito especial", r"CREDITOS?\s+ESPECIA"),
            ("crédito extraordinário", r"CREDITOS?\s+EXTRAORDIN"), ("remanejamento", r"REMANEJ"),
            ("contingenciamento e limites", r"CONTINGENC|LIMITES?\s+DE\s+(EMPENHO|MOVIMENTA|PAGAMENTO)"),
            ("programação orçamentária/financeira", r"PROGRAMACAO|QUADRO\s+DE\s+DETALHAMENTO|ORCAMENT"))


def tipo_orcamentario(ementa: str) -> str:
    e = re.sub(r"(?<=[A-Z])\s(?=[A-Z]\b)", "", gc._sem_acento(ementa))      # "PA R A" (hifenização do Diário)
    for rot, rx in _RX_CRED:
        if re.search(rx, e):
            return rot
    return "outro ato orçamentário"


def coletar_atos(con: sqlite3.Connection) -> dict:
    a = gc._atos(con)
    for d in a.get("decretos", []):
        if d["categoria"] == "orçamentário":
            d["tipo_orc"] = tipo_orcamentario(d["ementa"])
    return a


def coletar_controle(con: sqlite3.Connection) -> dict:
    c = gc._controle(con, None, set(), set())
    return {k: c.get(k) for k in ("auditorias_50254", "tce", "tce_decisoes", "cobertura", "fonte")}


# ───────────────────────────── achados: reconferência das provas primárias ─────────────────────────────
_RX_OB = re.compile(r"OB\s+(\d{4}OB\d{5})\s*·\s*UG\s+(\d{6})\s*·\s*(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})\s*·\s*"
                    r"R\$\s*([\d.]+,\d{2})")
_RX_SEI = re.compile(r"SEI-\d{6}/\d{5,6}/\d{2,4}")


def conferir_prova(con: sqlite3.Connection, paga: str, item: dict, prova: str) -> dict:
    """Reconfere UMA prova primária na fonte, agora. confere · diverge · ausente · nao_reconferivel."""
    m = _RX_OB.search(prova)
    if m:
        ob, ug, _d, v = m.group(1), m.group(2), m.group(3), _num_br(m.group(4))
        rows = con.execute(f"SELECT valor, status, COALESCE(status_envio,''), data_emissao, ({paga}) FROM "
                           f"ob_orcamentaria_siafe WHERE numero_ob=? AND ug_emitente=?", (ob, ug)).fetchall()
        if not rows:
            return {"tipo": "OB", "ob": ob, "ug": ug, "valor": v, "resultado": "ausente",
                    "detalhe": "a OB não está na base do SIAFE com esse número e UG"}
        bate = [r for r in rows if abs(float(r[0] or 0) - v) < 0.01]
        paga_ok = [r for r in bate if r[4]]
        if paga_ok:
            env = paga_ok[0][2]
            return {"tipo": "OB", "ob": ob, "ug": ug, "valor": v, "resultado": "confere", "envio": env,
                    "confirmada": env in ENVIO_CONFIRMADO, "data": paga_ok[0][3],
                    "detalhe": f"OB paga no SIAFE (status de envio: {env or 'não informado'})"}
        return {"tipo": "OB", "ob": ob, "ug": ug, "valor": v, "resultado": "diverge",
                "detalhe": ("a OB existe com o mesmo valor mas hoje NÃO é pagamento (status " + str(bate[0][1]) + ", envio "
                            + str(bate[0][2] or "—") + ")") if bate else "a OB existe com valor diferente do citado"}
    if re.search(r"\bCEIS\b|\bCNEP\b", prova):
        cnpj = _dig(item.get("cnpj"))
        if len(cnpj) != 14:
            return {"tipo": "CEIS", "resultado": "nao_reconferivel", "detalhe": "sem CNPJ no item para conferir"}
        # alcance pela régua única da casa (CNF-03): o registro tem de existir E vedar contratar com o Estado do RJ
        from compliance_agent.sancao_abrangencia import detalhar
        d = detalhar(cnpj, con)
        if not d["n"]:
            return {"tipo": "CEIS", "cnpj": cnpj, "resultado": "ausente", "detalhe": "sem registro no CEIS/CNEP hoje"}
        if not d["veda_contrato_alvo"]:
            return {"tipo": "CEIS", "cnpj": cnpj, "resultado": "diverge",
                    "detalhe": f"{d['n']} registro(s), mas nenhum veda contratar com o Estado do RJ pela régua de alcance"}
        return {"tipo": "CEIS", "cnpj": cnpj, "resultado": "confere",
                "detalhe": f"{d['n']} registro(s) no CEIS/CNEP; ao menos um veda contratar com o Estado do RJ"}
    s = _RX_SEI.search(prova)
    if s and "contrato" in prova.lower():
        sei = s.group(0)
        n = con.execute("SELECT COUNT(*) FROM contratos_tcerj WHERE processo=? OR sei_norm=?",
                        (sei, sei.replace("SEI-", ""))).fetchone()[0]
        return {"tipo": "contrato", "processo": sei, "resultado": "confere" if n else "ausente",
                "detalhe": f"contrato no espelho do TCE-RJ ({n} registro[s])" if n else "processo não está no espelho"}
    return {"tipo": "outro", "resultado": "nao_reconferivel", "detalhe": "prova sem chave reconferível por código"}


def coletar_achados(con: sqlite3.Connection) -> dict:
    from compliance_agent.cruzamentos_intel import _ob_paga
    if not gc.SUSPEITAS.exists():
        return {"estado": "indisponivel", "erro": "a régua da gestão ainda não gravou os pontos de atenção", "itens": []}
    bruto = json.loads(gc.SUSPEITAS.read_text(encoding="utf-8"))
    paga = _ob_paga(con)
    itens = []
    for x in bruto.get("achados") or []:
        x = {k: (mascarar(v) if isinstance(v, str) else v) for k, v in x.items()}
        provas = [{"texto": mascarar(p), **conferir_prova(con, paga, x, p)} for p in (x.get("prova_primaria") or [])]
        n_ok = sum(p["resultado"] == "confere" for p in provas)
        n_div = sum(p["resultado"] in ("diverge",) for p in provas)
        motivo = None
        if x.get("verificacao") != "VERIFICADO":
            motivo = f"a régua marcou {x.get('verificacao') or 'sem estado'} — sem prova primária citada e reproduzida"
        elif x.get("grau") not in ("🔴", "🟡"):
            motivo = "fato verificado, mas a régua não o graduou como indício (⚪ inconclusivo)"
        elif not provas:
            motivo = "sem prova primária citada"
        elif n_div:
            motivo = f"{n_div} prova(s) primária(s) DIVERGEM da fonte hoje — reconferir antes de qualquer uso"
        elif not n_ok:
            motivo = "nenhuma prova primária pôde ser reconferida por código na fonte"
        x["provas"] = provas
        x["n_provas_ok"], x["n_provas_divergentes"] = n_ok, n_div
        x["passou"] = motivo is None
        x["motivo_portao"] = motivo
        x["processos_sei"] = sorted(set(_RX_SEI.findall(" ".join([str(x.get("processo") or "")] +
                                                                [p["texto"] for p in provas]))))
        if x.get("teste_inocente"):
            try:
                from compliance_agent.governo_couto_regras import explicar_teste_d14
                x["teste_inocente_texto"] = mascarar(explicar_teste_d14(x))
            except (KeyError, TypeError, ValueError) as exc:
                x["teste_inocente_texto"] = f"teste registrado, não legível ({type(exc).__name__})"
        if isinstance(x.get("instrumento"), dict):
            from compliance_agent.governo_couto_regras import descrever_instrumento
            x["instrumento_texto"] = mascarar(descrever_instrumento(x["instrumento"]))
        x.pop("teste_inocente", None)
        itens.append(x)
    ordem = {"🔴": 0, "🟡": 1, "⚪": 2}
    itens.sort(key=lambda i: (not i["passou"], ordem.get(i.get("grau"), 3), -(float(i.get("valor_ob") or 0))))
    meta = {k: bruto.get(k) for k in ("gerado_em", "recorte", "camada_subjetiva", "por_verificacao", "indisponivel")}
    return {"estado": "ok", **meta, "itens": itens}


def _sei_status(processo: str) -> dict:
    pasta = DATA / "sei_arquivo" / processo.replace("SEI-", "").replace("/", "_")
    man = pasta / "manifest.json"
    if man.exists():
        try:
            m = json.loads(man.read_text(encoding="utf-8"))
            return {"estado": "no acervo", "docs": len(m.get("docs") or []), "completo": bool(m.get("captura_completa")),
                    "lacunas": len(m.get("lacunas") or [])}
        except (OSError, ValueError):
            return {"estado": "no acervo (manifesto ilegível)"}
    try:
        from compliance_agent import armazenamento
        if armazenamento.onde(processo):
            return {"estado": "no arquivo em nuvem (obtível)"}
    except (ImportError, OSError, sqlite3.Error, ValueError) as exc:
        logger.debug("armazenamento indisponível para %s: %s", processo, exc)
    return {"estado": "autos não capturados"}


def coletar(ob_brutos: dict | None = None) -> dict:
    con, con_ab = _ro(gc.DB), _ro(gc.DB_ABERTOS)
    if con is None:
        raise OSError(f"base indisponível: {gc.DB}")
    try:
        ob = ob_brutos or coletar_ob(con)
        u2o, nomes_org, nome_ug = _cadastro_ug(con_ab)
        dados = {"gerado_em": datetime.now().isoformat(timespec="seconds"), "inicio": INICIO, "gestao": gc.GESTAO,
                 "ob": ob, "cadastro": {"ug_orgao": u2o, "nome_orgao": nomes_org, "nome_ug": nome_ug}}
        for nome, fn in (("contratacoes", coletar_contratacoes), ("aditivos", coletar_aditivos), ("tac", coletar_tac),
                         ("atos", coletar_atos), ("controle", coletar_controle), ("achados", coletar_achados)):
            dados[nome] = gc._seguro(fn, con)
        procs = sorted({p for it in dados["achados"].get("itens", []) if it.get("passou") for p in it["processos_sei"]})
        dados["sei"] = {p: _sei_status(p) for p in procs}
    finally:
        con.close()
        if con_ab is not None:
            con_ab.close()
    return dados


# ───────────────────────────── agregação da OB ─────────────────────────────
def agregar_ob(ob: dict, cad: dict) -> dict:
    u2o, nomes_org, nome_ug = cad["ug_orgao"], cad["nome_orgao"], cad["nome_ug"]

    def org(ug):
        return u2o.get(str(ug)) or str(ug)[0:2]
    r = {}
    for jan in ("couto", "anterior"):
        t = {"n": 0, "valor": 0.0, "confirmada": 0.0, "sem_confirmacao": 0.0}
        poder, orgao, ugs, cred, rp, fora = (defaultdict(lambda: [0, 0.0]) for _ in range(6))
        nomes_cred, pf, intra = {}, [0, 0.0], [0, 0.0]
        gen: dict = defaultdict(lambda: [0, 0.0, ""])
        for ug, c, nome, tob, k, n, v, _d in ob[jan]:
            v = float(v or 0)
            if k not in ("confirmada", "sem_confirmacao"):
                fora[k][0] += n
                fora[k][1] += v
                continue
            t["n"] += n
            t["valor"] += v
            t[k] += v
            o = org(ug)
            for agg, chave in ((poder, _poder(o)), (orgao, o), (ugs, str(ug)), (rp, tob or "Orçamentária")):
                agg[chave][0] += n
                agg[chave][1] += v
            d = _dig(c)
            if c == "PF":
                pf[0] += n
                pf[1] += v
            elif len(d) == 14:
                cred[d][0] += n
                cred[d][1] += v
                nomes_cred.setdefault(d, mascarar(nome or ""))
            elif re.fullmatch(r"\d{6}", str(c)):
                intra[0] += n                  # credor é UG do próprio Estado: transferência intragovernamental
                intra[1] += v
            else:
                g = gen[str(c)]                # credor genérico do SIAFE (folha, previdência, benefícios, dívida…)
                g[0] += n
                g[1] += v
                g[2] = g[2] or mascarar(nome or "")
        r[jan] = {"generico": {k: list(x) for k, x in gen.items()},
                  "total": {k: (round(x, 2) if isinstance(x, float) else x) for k, x in t.items()},
                  "poder": dict(poder), "orgao": dict(orgao), "ug": dict(ugs), "credor": dict(cred),
                  "nomes_credor": nomes_cred, "pf": pf, "intra": intra,
                  "generico_total": [sum(x[0] for x in gen.values()), sum(x[1] for x in gen.values())], "rp": dict(rp), "fora": dict(fora)}
    r["nome_orgao"], r["nome_ug"], r["ug_orgao"] = nomes_org, nome_ug, u2o
    return r


# ───────────────────────────── montagem do documento ─────────────────────────────
_CSS = """<style>
.fato{white-space:nowrap}
td.n,th.n{text-align:right;white-space:nowrap}
.sumario a{color:#1f4e79;text-decoration:none} .sumario li{margin:2px 0}
.badge{display:inline-block;padding:1px 7px;border-radius:9px;font:700 8.5px Arial,sans-serif;color:#fff;letter-spacing:.04em}
.badge.g3{background:#b71c1c} .badge.g2{background:#e6a100;color:#2b2000} .badge.g1{background:#8a8f98}
.callout{margin:8px 0;padding:9px 13px;border-radius:0 5px 5px 0;page-break-inside:avoid}
.callout.g3{background:#fdecea;border-left:5px solid #b71c1c} .callout.g2{background:#fff8e1;border-left:5px solid #e6a100}
.callout.info{background:#eef3fa;border-left:5px solid #1f4e79}
.achado{border:1px solid #d7dde6;border-radius:6px;padding:9px 12px;margin:10px 0;page-break-inside:avoid}
.achado h4{margin:0 0 6px}
li.prova.ok::marker{color:#2e7d32} li.prova.diverge{color:#b71c1c}
.kpis{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0}
.kpi{flex:1 1 30%;border:1px solid #d7dde6;border-radius:6px;padding:7px 10px;background:#fbfcfe}
.kpi b{display:block;font-size:13px;color:#12335a} .kpi span{font-size:8.5px;color:#555}
table.registro td{font-size:7.5px} table.registro td.mono{font-size:7px;word-break:break-all}
</style>"""


def _k(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", gc._sem_acento(str(s)).lower()).strip("_")


def _badge(grau: str) -> str:
    rot, cls = GRAU_ROTULO.get(grau, ("INCONCLUSIVO", "g1"))
    return f'<span class="badge {cls}">{rot}</span>'


def _ancora(i: str, titulo: str) -> str:
    return f'<span id="{i}"></span>{_e(titulo)}'


def _tabela(cab: list[str], linhas: list[list[str]], num: set[int] = frozenset(), cls: str = "") -> str:
    th = "".join(f'<th class="n">{_e(c)}</th>' if i in num else f"<th>{_e(c)}</th>" for i, c in enumerate(cab))
    corpo = "".join("<tr>" + "".join(f'<td class="n">{c}</td>' if i in num else f"<td>{c}</td>"
                                     for i, c in enumerate(lin)) + "</tr>" for lin in linhas)
    return f'<table class="{cls}"><tr>{th}</tr>{corpo}</table>'


class Montador:
    def __init__(self, dados: dict):
        self.d = dados
        self.reg = Registro(dados["gerado_em"])
        self.secoes: list[dict] = []
        self.ob = dados["ob"]
        self.agg = agregar_ob(self.ob, dados["cadastro"]) if self.ob.get("estado") == "ok" else None
        self.F_SIAFE = "SIAFE-Rio 2 — Ordem Bancária (OB) que é pagamento: Contabilizada, não devolvida pelo banco, sem pagamento complementar, sem OB reemitida, com número"

    # ── fatos de OB
    def _pago(self, chave, valor, rotulo, consulta, confirmado: bool | None = None) -> str:
        base = BASE_PAGO_CONFIRMADO if confirmado else "ob_contabilizada_sem_confirmacao"
        return self.reg.v(chave, valor, "BRL", rotulo, self.F_SIAFE, consulta, natureza="pago", base=base,
                          estado="VERIFICADO" if confirmado else "A CONFERIR")

    def _n(self, chave, valor, rotulo, fonte, consulta, **k) -> str:
        return self.reg.v(chave, valor, "contagem", rotulo, fonte, consulta, **k)

    def _var(self, chave, atual, ant, rotulo, fonte) -> str:
        if not ant or atual is None:
            return "—"
        return self.reg.v(chave, (atual / ant - 1) * 100, "indice", f"variação percentual — {rotulo}", fonte,
                          "calculada: (período Couto ÷ mesma janela do ano anterior − 1) × 100",
                          estado="A CONFERIR", nivel=1)       # herda o estado mais fraco das parcelas (OB sem envio confirmado)

    def _pct(self, chave, parte, todo, rotulo, fonte) -> str:
        if not todo:
            return "—"
        return self.reg.v(chave, parte / todo * 100, "percentual", rotulo, fonte, "calculada: parte ÷ total × 100")

    def sec(self, sid: str, titulo: str, html: str, quebra: bool = True) -> None:
        self.secoes.append({"id": sid, "titulo": _ancora(sid, titulo), "titulo_txt": titulo, "html": html,
                            "page_break": quebra})

    # ── 3. panorama
    def panorama(self) -> str:
        a = self.agg
        if a is None:
            return (f'<div class="callout g2"><b>INDISPONÍVEL.</b> A execução por OB não pôde ser lida: '
                    f'{_e(self.ob.get("erro"))}. Isto não significa pagamento zero.</div>')
        ob, c, p = self.ob, a["couto"], a["anterior"]
        jan = f"OB emitidas de {_br(ob['inicio'])} a {_br(ob['fim'])}"
        jan_a = f"mesma janela do ano anterior ({_br(ob['inicio_ant'])} a {_br(ob['fim_ant'])})"
        F = self.F_SIAFE
        tot = self._pago("exec.total.couto", c["total"]["valor"], f"total pago — {jan}", "soma das OB pagas na janela")
        tot_a = self._pago("exec.total.anterior", p["total"]["valor"], f"total pago — {jan_a}", "soma das OB pagas na janela")
        conf = self._pago("exec.confirmada.couto", c["total"]["confirmada"], f"pago com envio confirmado pelo banco — {jan}",
                          "OB pagas com status de envio 'Processado e Pago' ou 'Enviado Manualmente'", confirmado=True)
        semc = self._pago("exec.sem_confirmacao.couto", c["total"]["sem_confirmacao"],
                          f"pago sem confirmação de envio — {jan}", "OB pagas com status de envio intermediário")
        h = [f"<p>Na gestão do governador em exercício, de {_br(ob['inicio'])} a {_br(ob['fim'])} (data da última OB paga "
             f"coletada), o Estado do Rio de Janeiro emitiu "
             f"{self._n('exec.n.couto', c['total']['n'], f'OB pagas — {jan}', F, 'contagem de OB pagas')} ordens bancárias "
             f"que são pagamento, no total de {tot}. Na {jan_a}, sob o governo anterior, foram "
             f"{self._n('exec.n.anterior', p['total']['n'], f'OB pagas — {jan_a}', F, 'contagem de OB pagas')} OB e {tot_a} — "
             f"variação de {self._var('exec.var', c['total']['valor'], p['total']['valor'], 'total pago', F)}.</p>",
             f"<p>Do total do período, {conf} têm o envio ao banco confirmado no SIAFE (estado VERIFICADO) e {semc} ainda "
             f"aparecem com status de envio intermediário (estado A CONFERIR: são OB contabilizadas cuja liquidação "
             f"bancária o espelho ainda não confirma). O SIAFE soma, além de fornecedores, transferências entre unidades, "
             f"repasses, folha e encargos — o total não é só compra.</p>",
             f'<div class="callout g2"><b>Dupla contagem possível nas transferências.</b> OB cujo credor é uma unidade '
             f"gestora do próprio Estado (código de UG — repasse, descentralização, aporte a fundo) pode reaparecer como OB "
             f"da unidade que recebe. Essas OB somam "
             f"{self._pago('exec.intra.valor', c['intra'][1], 'pago a credor que é UG do Estado — período Couto', 'soma')} no período "
             f"({self._pago('exec.intra.valor_ant', p['intra'][1], 'pago a credor que é UG do Estado — mesma janela do ano anterior', 'soma')} "
             f"no ano anterior). Excluídas, o pago fica em "
             f"{self._pago('exec.liquido.couto', c['total']['valor'] - c['intra'][1], 'pago excluídas as OB a credor UG do Estado — período Couto', 'total menos OB a credor UG')} "
             f"contra {self._pago('exec.liquido.anterior', p['total']['valor'] - p['intra'][1], 'pago excluídas as OB a credor UG do Estado — ano anterior', 'total menos OB a credor UG')} "
             f"({self._var('exec.liquido.var', c['total']['valor'] - c['intra'][1], p['total']['valor'] - p['intra'][1], 'pago excluídas as OB a credor UG', F)}). "
             f"Folha, previdência, benefícios e dívida saem por credor genérico do SIAFE (Capítulo 3.4) e continuam na "
             f"soma — são pagamento. As tabelas por Poder, órgão e UG mostram o total emitido por cada unidade.</div>"]
        # 3.1 por Poder
        h.append("<h3>3.1 Por Poder</h3>")
        lin = []
        for pod in sorted(set(c["poder"]) | set(p["poder"]), key=lambda k: -c["poder"].get(k, [0, 0])[1]):
            x, y = c["poder"].get(pod, [0, 0.0]), p["poder"].get(pod, [0, 0.0])
            k = _k(pod)
            lin.append([_e(pod), self._n(f"exec.poder.{k}.n", x[0], f"OB pagas — {pod} — {jan}", F, "por Poder do órgão da UG"),
                        self._pago(f"exec.poder.{k}.couto", x[1], f"pago — {pod} — {jan}", "por Poder do órgão da UG"),
                        self._pago(f"exec.poder.{k}.anterior", y[1], f"pago — {pod} — {jan_a}", "por Poder do órgão da UG"),
                        self._var(f"exec.poder.{k}.var", x[1], y[1], f"pago — {pod}", F)])
        h.append(_tabela(["Poder", "OB pagas", "Pago (Couto)", "Pago (ano anterior)", "Variação"], lin, {1, 2, 3, 4}))
        h.append('<p class="nota">Poder = Poder do órgão orçamentário dono da UG emitente (cadastro da despesa do Estado). '
                 'Repasse por OB a credor que é UG de outro Poder conta na UG que emitiu; o gasto do Poder que recebeu '
                 'aparece de novo nas OB dele (ver a ressalva de dupla contagem acima).</p>')
        # 3.2 por órgão (lista integral)
        h.append("<h3>3.2 Por órgão (lista integral)</h3>")
        lin = []
        for o in sorted(set(c["orgao"]) | set(p["orgao"]), key=lambda k: -c["orgao"].get(k, [0, 0])[1]):
            x, y = c["orgao"].get(o, [0, 0.0]), p["orgao"].get(o, [0, 0.0])
            nome = a["nome_orgao"].get(o, f"Órgão {o}")
            lin.append([_e(o), _e(campo(nome, 70)), self._n(f"exec.orgao.{o}.n", x[0], f"OB pagas — órgão {o} — {jan}", F, "por órgão"),
                        self._pago(f"exec.orgao.{o}.couto", x[1], f"pago — órgão {o} ({nome}) — {jan}", "por órgão"),
                        self._pago(f"exec.orgao.{o}.anterior", y[1], f"pago — órgão {o} ({nome}) — {jan_a}", "por órgão"),
                        self._var(f"exec.orgao.{o}.var", x[1], y[1], f"pago — órgão {o}", F)])
        h.append(_tabela(["Órgão", "Nome", "OB", "Pago (Couto)", "Pago (ano anterior)", "Variação"], lin, {2, 3, 4, 5}))
        h.append(f'<p class="nota">{len(lin)} órgãos, nenhum omitido. A abertura por unidade gestora (UG) está, integral, '
                 f'no <a href="#anexo-b">Anexo B</a>.</p>')
        # 3.3 função
        h.append("<h3>3.3 Por função de governo</h3>")
        h.append('<div class="callout g2"><b>INDISPONÍVEL — não é zero.</b> A Ordem Bancária do SIAFE não traz a '
                 'classificação funcional (função/subfunção), que nasce na dotação e no empenho. A despesa por função do '
                 'portal de dados abertos do Estado está publicada até o exercício de 2025 (não há 2026) e não é OB. '
                 'Para abrir o pago do período por função é preciso a relação OB → NL → NE → dotação, que a coleta '
                 'disponível não cobre integralmente. Diligência: requerer à SEFAZ o relatório de execução por função '
                 '(pago) do período 23/03/2026 em diante.</div>')
        # 3.4 fornecedores
        h.append("<h3>3.4 Por fornecedor (pessoa jurídica)</h3>")
        cred = sorted(c["credor"].items(), key=lambda kv: -kv[1][1])
        vistos, nota = top_declarado(cred, 150, "credores pessoa jurídica", onde="na soma 'demais' logo abaixo")
        lin = []
        for i, (cnpj, (n, v)) in enumerate(vistos, 1):
            ant = p["credor"].get(cnpj, [0, 0.0])
            nome = c["nomes_credor"].get(cnpj, "")
            lin.append([self._n(f"exec.forn.rank.{cnpj}", i, f"posição do credor {cnpj} no pago do período", F, "ordem por valor"),
                        _e(campo(nome, 60)), f'<span class="mono">{cnpj}</span>',
                        self._n(f"exec.forn.{cnpj}.n", n, f"OB pagas a {cnpj} — {jan}", F, "por credor"),
                        self._pago(f"exec.forn.{cnpj}.couto", v, f"pago a {cnpj} ({nome}) — {jan}", "por credor"),
                        self._pago(f"exec.forn.{cnpj}.anterior", ant[1], f"pago a {cnpj} ({nome}) — {jan_a}", "por credor")])
        h.append(_tabela(["#", "Credor", "CNPJ", "OB", "Pago (Couto)", "Pago (ano anterior)"], lin, {0, 3, 4, 5}))
        resto = cred[len(vistos):]
        h.append(f"<p>{_e(nota) if nota else 'Lista integral.'} Demais credores pessoa jurídica: "
                 f"{self._n('exec.forn.demais.n', len(resto), 'credores PJ fora da tabela', F, 'contagem')} credores, "
                 f"{self._pago('exec.forn.demais.valor', sum(v for _c, (_n, v) in resto), 'pago aos credores PJ fora da tabela', 'soma')}. "
                 f"Total de credores PJ no período: {self._n('exec.forn.total.n', len(cred), 'credores PJ com OB paga no período', F, 'contagem')}.</p>")
        h.append(f"<p>Pessoas físicas (agregadas, sem identificação — LGPD): "
                 f"{self._n('exec.pf.n', c['pf'][0], 'OB pagas a pessoas físicas — período Couto', F, 'contagem')} OB, "
                 f"{self._pago('exec.pf.valor', c['pf'][1], 'pago a pessoas físicas — período Couto', 'soma')}. "
                 f"Credor que é unidade gestora do próprio Estado (transferências): "
                 f"{self._n('exec.intra.n', c['intra'][0], 'OB a credor que é UG do Estado — período Couto', F, 'contagem')} OB, "
                 f"{self._pago('exec.intra.valor', c['intra'][1], 'pago a credor que é UG do Estado — período Couto', 'soma')}.</p>")
        h.append("<h3>3.4.1 Credores genéricos do SIAFE (folha, previdência, benefícios, dívida)</h3>")
        gen = sorted(c["generico"].items(), key=lambda kv: -kv[1][1])
        gvis, gnota = top_declarado(gen, 60, "credores genéricos", onde="na soma logo abaixo")
        lin = []
        for cod, (n, v, nome) in gvis:
            ant = p["generico"].get(cod, [0, 0.0, ""])
            kk = re.sub(r"[^A-Za-z0-9]+", "_", cod)
            lin.append([f'<span class="mono">{_e(cod)}</span>', texto_com_fatos(self.reg, campo(nome, 70), f"exec.gen.{kk}.nome", F, estado="VERIFICADO"),
                        self._n(f"exec.gen.{kk}.n", n, f"OB pagas ao credor genérico {cod} — {jan}", F, "por credor genérico"),
                        self._pago(f"exec.gen.{kk}.couto", v, f"pago ao credor genérico {cod} ({nome}) — {jan}", "por credor genérico"),
                        self._pago(f"exec.gen.{kk}.anterior", ant[1], f"pago ao credor genérico {cod} ({nome}) — {jan_a}", "por credor genérico")])
        h.append("<p>O SIAFE paga folha, aposentadorias e pensões, auxílios e parcelas de dívida a CREDORES GENÉRICOS (código "
                 "próprio, não CNPJ nem CPF) — o beneficiário final não aparece na OB. Período: "
                 f"{self._n('exec.gen.total.n', c['generico_total'][0], 'OB a credor genérico do SIAFE — período Couto', F, 'contagem')} OB, "
                 f"{self._pago('exec.gen.total.couto', c['generico_total'][1], 'pago a credor genérico do SIAFE — período Couto', 'soma')} "
                 f"(ano anterior: {self._pago('exec.gen.total.anterior', p['generico_total'][1], 'pago a credor genérico do SIAFE — ano anterior', 'soma')}).</p>")
        h.append(_tabela(["Código", "Credor genérico", "OB", "Pago (Couto)", "Pago (ano anterior)"], lin, {2, 3, 4}))
        if gnota:
            h.append(f"<p class='nota'>{_e(gnota)} Demais: "
                     f"{self._pago('exec.gen.demais.valor', sum(x[1] for _c, x in gen[len(gvis):]), 'pago aos credores genéricos fora da tabela', 'soma')}.</p>")
        # 3.5 restos a pagar
        h.append("<h3>3.5 Restos a pagar pagos no período</h3>")
        lin = []
        for tob in sorted(set(c["rp"]) | set(p["rp"])):
            x, y = c["rp"].get(tob, [0, 0.0]), p["rp"].get(tob, [0, 0.0])
            k = _k(tob)
            lin.append([_e(tob), self._n(f"exec.rp.{k}.n", x[0], f"OB pagas tipo '{tob}' — {jan}", F, "por tipo de OB"),
                        self._pago(f"exec.rp.{k}.couto", x[1], f"pago tipo '{tob}' — {jan}", "por tipo de OB"),
                        self._pago(f"exec.rp.{k}.anterior", y[1], f"pago tipo '{tob}' — {jan_a}", "por tipo de OB"),
                        self._var(f"exec.rp.{k}.var", x[1], y[1], f"tipo '{tob}'", F)])
        h.append(_tabela(["Tipo de OB", "OB", "Pago (Couto)", "Pago (ano anterior)", "Variação"], lin, {1, 2, 3, 4}))
        h.append('<p class="nota">RPP = restos a pagar processados; RPNP = não processados (Lei 4.320/1964, art. 36). O '
                 'tipo vem da própria OB no SIAFE. O estoque inscrito de restos a pagar não está nesta base — só o que '
                 'foi pago.</p>')
        # 3.6 fora da soma
        h.append("<h3>3.6 O que NÃO entrou na soma (e por quê)</h3>")
        rot = {"devolvida": "Devolvida pelo banco (erro no pagamento)", "complementar": "Pagamento complementar (listado "
               "na OB principal — somar contaria em dobro)", "sem_numero": "Linha sem número de OB (repetição de coleta)",
               "reemitida": "OB reemitida (a primeira não foi paga)"}
        lin = []
        for k in sorted(set(c["fora"]) | set(p["fora"]), key=lambda k: -c["fora"].get(k, [0, 0])[1]):
            x, y = c["fora"].get(k, [0, 0.0]), p["fora"].get(k, [0, 0.0])
            nome = rot.get(k, k.replace("status:", "Status no SIAFE: "))
            kk = _k(k)
            lin.append([_e(nome), self._n(f"exec.fora.{kk}.n", x[0], f"OB fora da soma — {nome} — {jan}", F, "por motivo"),
                        self.reg.v(f"exec.fora.{kk}.couto", x[1], "BRL", f"valor fora da soma — {nome} — {jan}", F, "por motivo",
                                   natureza="nao_pago"),
                        self.reg.v(f"exec.fora.{kk}.anterior", y[1], "BRL", f"valor fora da soma — {nome} — {jan_a}", F,
                                   "por motivo", natureza="nao_pago")])
        h.append(_tabela(["Motivo", "OB", "Valor (Couto)", "Valor (ano anterior)"], lin, {1, 2, 3}))
        h.append('<p class="nota">Nenhum destes valores é pagamento. Anulação/exclusão em volume pode indicar reemissão, '
                 'erro de cadastro bancário ou cancelamento — ver o critério D20 no Capítulo 7.</p>')
        return "".join(h)

    def anexo_ug(self) -> str:
        a = self.agg
        if a is None:
            return "<p>INDISPONÍVEL — ver Capítulo 3.</p>"
        c, p, F = a["couto"], a["anterior"], self.F_SIAFE
        lin = []
        for ug in sorted(set(c["ug"]) | set(p["ug"]), key=lambda k: -c["ug"].get(k, [0, 0])[1]):
            x, y = c["ug"].get(ug, [0, 0.0]), p["ug"].get(ug, [0, 0.0])
            nome = a["nome_ug"].get(ug, "")
            lin.append([f'<span class="mono">{_e(ug)}</span>', _e(campo(nome, 60)), _e(a["ug_orgao"].get(ug) or ug[0:2]),
                        self._n(f"exec.ug.{ug}.n", x[0], f"OB pagas — UG {ug}", F, "por UG"),
                        self._pago(f"exec.ug.{ug}.couto", x[1], f"pago — UG {ug} ({nome}) — período Couto", "por UG"),
                        self._pago(f"exec.ug.{ug}.anterior", y[1], f"pago — UG {ug} ({nome}) — mesma janela do ano anterior", "por UG")])
        return (f"<p>Todas as {len(lin)} unidades gestoras com OB paga em qualquer das duas janelas, em ordem de valor "
                f"pago no período Couto. Nenhuma omitida.</p>"
                + _tabela(["UG", "Nome", "Órgão", "OB", "Pago (Couto)", "Pago (ano anterior)"], lin, {3, 4, 5}))

    # ── 4. contratações
    def contratacoes(self) -> str:
        ct, ad, tac = self.d["contratacoes"], self.d["aditivos"], self.d["tac"]
        F = "Espelho de contratações do Tribunal de Contas do Estado do RJ + contratações diretas do TCE-RJ (por nº SEI)"
        h = []
        if "janelas" not in ct:
            h.append(f'<div class="callout g2"><b>INDISPONÍVEL</b>: {_e(ct.get("erro"))}</div>')
        else:
            jc, ja = ct["janelas"]["couto"], ct["janelas"]["anterior"]
            h.append(f"<p>Contratos registrados no espelho do TCE-RJ com data de contratação de {_br(jc['inicio'])} a "
                     f"{_br(jc['fim'])} (último registro do espelho), comparados à mesma janela do ano anterior "
                     f"({_br(ja['inicio'])} a {_br(ja['fim'])}). Valor = CONTRATADO, nunca pago. Contratos cancelados ficam "
                     f"fora ({self._n('ctr.cancelados.couto', jc['n_cancelados'], 'contratos cancelados no espelho — período Couto', F, 'contagem')} "
                     f"no período). A modalidade não é publicada pelo espelho: dispensa e inexigibilidade vêm do cruzamento "
                     f"com o cadastro de contratações diretas do TCE-RJ pelo número do processo SEI; emergencial = "
                     f"enquadramento no art. 75, VIII, da Lei 14.133/2021 ou \"emergencial\" no objeto.</p>")
            h.append("<h3>4.1 Por modalidade</h3>")
            lin = []
            ordem = ("Dispensa — emergencial", "Dispensa (outras hipóteses)", "Inexigibilidade",
                     "Licitação ou sem registro de contratação direta")
            tc = sum(x["valor"] for x in jc["modalidades"].values())
            for m in ordem:
                x = jc["modalidades"].get(m, {"n": 0, "valor": 0})
                y = (ja["modalidades"].get(m, {"n": 0, "valor": 0}) if not ja.get("indisponivel")
                     else {"n": None, "valor": None})
                k = _k(m)
                lin.append([_e(m), self._n(f"ctr.mod.{k}.n", x["n"], f"contratos — {m} — período Couto", F, "por modalidade"),
                            self.reg.v(f"ctr.mod.{k}.valor", x["valor"], "BRL", f"contratado — {m} — período Couto", F,
                                       "por modalidade", natureza="contratado"),
                            self._pct(f"ctr.mod.{k}.pct", x["valor"], tc, f"participação no contratado — {m}", F),
                            self._n(f"ctr.mod.{k}.n_ant", y["n"], f"contratos — {m} — ano anterior", F, "por modalidade"),
                            self.reg.v(f"ctr.mod.{k}.valor_ant", y["valor"], "BRL", f"contratado — {m} — ano anterior", F,
                                       "por modalidade", natureza="contratado"),
                            self._var(f"ctr.mod.{k}.var", x["valor"], y["valor"], f"contratado — {m}", F)])
            if ja.get("indisponivel"):
                lin.append([f"Ano anterior INDISPONÍVEL: {_e(ja['indisponivel'])}", "", "", "", "", "", ""])
            h.append(_tabela(["Modalidade", "Contratos", "Contratado (Couto)", "% do valor", "Contratos (ano ant.)",
                              "Contratado (ano ant.)", "Variação"], lin, {1, 2, 3, 4, 5, 6}))
            em = [x for x in jc["lista"] if x["modalidade"] == "Dispensa — emergencial"]
            h.append("<h3>4.2 Contratações emergenciais do período (lista integral)</h3>")
            h.append(self._lista_ctr(em, "ctr.emerg", F))
            ix = [x for x in jc["lista"] if x["modalidade"] == "Inexigibilidade"]
            h.append("<h3>4.3 Inexigibilidades do período (lista integral)</h3>")
            h.append(self._lista_ctr(ix, "ctr.inex", F))
            ds = [x for x in jc["lista"] if x["modalidade"] == "Dispensa (outras hipóteses)"]
            vis, nota = top_declarado(ds, 60, "dispensas", onde="no espelho de contratações diretas do TCE-RJ")
            h.append("<h3>4.4 Dispensas (outras hipóteses) — as de maior valor</h3>")
            h.append(self._lista_ctr(vis, "ctr.disp", F) + (f"<p class='nota'>{_e(nota)}</p>" if nota else ""))
        h.append("<h3>4.5 Termos aditivos</h3>")
        if "janelas" in ad:
            Fa = "Termos aditivos publicados no PNCP — contratos de órgão do Estado do RJ (CNPJ do órgão)"
            x, y = ad["janelas"]["couto"], ad["janelas"]["anterior"]
            h.append(f"<p>Termos aditivos assinados de {_br(x['inicio'])} a {_br(x['fim'])} (último termo coletado): "
                     f"{self._n('adit.n', x['n'], 'aditivos — período Couto', Fa, 'contagem')} termos, dos quais "
                     f"{self._n('adit.n_sem', x['n_sem_valor'], 'aditivos sem valor no PNCP — período Couto', Fa, 'contagem')} sem "
                     f"valor publicado; acréscimo declarado de "
                     f"{self.reg.v('adit.valor', x['valor_acrescido'], 'BRL', 'valor acrescido por aditivos — período Couto', Fa, 'soma', natureza='contratado')}. "
                     + (f"Mesma janela do ano anterior: INDISPONÍVEL — {_e(y['indisponivel'])} (não é zero).</p>"
                        if y.get("indisponivel") else
                        f"Mesma janela do ano anterior: {self._n('adit.n_ant', y['n'], 'aditivos — ano anterior', Fa, 'contagem')} termos, "
                        f"{self.reg.v('adit.valor_ant', y['valor_acrescido'], 'BRL', 'valor acrescido por aditivos — ano anterior', Fa, 'soma', natureza='contratado')}.</p>")
                     + '<div class="callout g2"><b>Cobertura parcial.</b> O PNCP só tem o que o órgão publicou; parte dos '
                     'termos sai sem valor. Não é o universo de aditivos do Estado e não permite afirmar ausência de '
                     'acréscimo acima de <span class="limiar">25%</span> (Lei 14.133/2021, art. 125).</div>')
        else:
            h.append(f'<div class="callout g2"><b>INDISPONÍVEL</b>: {_e(ad.get("erro"))}</div>')
        h.append("<h3>4.6 Termos de Ajuste de Contas (TAC)</h3>")
        if "janelas" in tac:
            Ft = "Diário Oficial do Estado do RJ — extratos de Termo de Ajuste de Contas (valor reconhecido, não é OB)"
            x, y = tac["janelas"]["couto"], tac["janelas"]["anterior"]
            h.append(f"<p>O Termo de Ajuste de Contas reconhece dívida por serviço prestado SEM cobertura contratual — é "
                     f"o atestado, publicado, de que houve execução fora de contrato. De {_br(x['inicio'])} a "
                     f"{_br(x['fim'])}: {self._n('tac.n', x['n'], 'TACs publicados — período Couto', Ft, 'contagem')} extratos, "
                     f"{self.reg.v('tac.valor', x['valor'], 'BRL', 'valor reconhecido em TAC — período Couto', Ft, 'soma', natureza='reconhecido')} "
                     f"reconhecidos. "
                     + (f"Mesma janela do ano anterior: INDISPONÍVEL — {_e(y['indisponivel'])}; a comparação com o governo "
                        f"anterior não é possível por esta fonte (não é zero).</p>" if y.get("indisponivel") else
                        f"Mesma janela do ano anterior: {self._n('tac.n_ant', y['n'], 'TACs publicados — ano anterior', Ft, 'contagem')} "
                        f"extratos, {self.reg.v('tac.valor_ant', y['valor'], 'BRL', 'valor reconhecido em TAC — ano anterior', Ft, 'soma', natureza='reconhecido')} "
                        f"(variação {self._var('tac.var', x['valor'], y['valor'], 'valor reconhecido em TAC', Ft)}).</p>"))
            vis, nota = top_declarado(x["fornecedores"], 40, "fornecedores com TAC", onde="no Diário Oficial")
            lin = [[_e(campo(f["fornecedor"], 60)), f'<span class="mono">{_e(f["cnpj"] or "—")}</span>',
                    self._n(f"tac.forn.{i}.n", f["n"], f"TACs — {f['fornecedor']}", Ft, "por fornecedor"),
                    self.reg.v(f"tac.forn.{i}.valor", f["valor"], "BRL", f"reconhecido em TAC — {f['fornecedor']}", Ft,
                               "por fornecedor", natureza="reconhecido"),
                    _e(campo("; ".join(f["orgaos"]), 90))] for i, f in enumerate(vis, 1)]
            h.append(_tabela(["Fornecedor", "CNPJ", "TACs", "Reconhecido", "Órgão(s)"], lin, {2, 3}))
            if nota:
                h.append(f"<p class='nota'>{_e(nota)}</p>")
        else:
            h.append(f'<div class="callout g2"><b>INDISPONÍVEL</b>: {_e(tac.get("erro"))}</div>')
        return "".join(h)

    def _lista_ctr(self, itens: list[dict], pref: str, F: str) -> str:
        if not itens:
            return "<p>Nenhum registro no espelho para esta modalidade no período (pela cobertura declarada).</p>"
        lin = []
        for i, x in enumerate(tudo(itens), 1):
            lin.append([_br(x["data"]), _e(campo(x["orgao"], 40)), _e(campo(x["fornecedor"], 40)),
                        f'<span class="mono">{_e(x["doc"])}</span>', texto_com_fatos(self.reg, campo(x["objeto"], 140), f"{pref}.{i}.obj", F, estado="VERIFICADO"),
                        f'<span class="mono">{_e(x["processo"])}</span>',
                        self.reg.v(f"{pref}.{i}", x["valor"], "BRL", f"contratado — processo {x['processo']}", F,
                                   "contrato no espelho", natureza="contratado")])
        return (f"<p>{len(lin)} contrato(s).</p>"
                + _tabela(["Data", "Órgão", "Contratado", "CNPJ", "Objeto", "Processo", "Valor"], lin, {6}))

    # ── 5. atos
    def atos(self) -> str:
        a, ctl = self.d["atos"], self.d["controle"]
        Fd = "Diário Oficial do Estado do RJ — decretos assinados \"Governador em exercício\""
        if "decretos" not in a:
            return f'<div class="callout g2"><b>INDISPONÍVEL</b>: {_e(a.get("erro"))}</div>'
        dec = a["decretos"]
        h = [f"<p>{_e(gc.GESTAO['transicao'])} {_e(a.get('cobertura'))}</p>",
             f"<p>Foram localizados {self._n('atos.decretos.n', len(dec), 'decretos numerados assinados Governador em exercício', Fd, 'contagem')} "
             f"decretos numerados; {self._n('atos.decretos.lacunas', a.get('n_faltam_no_intervalo'), 'números do intervalo de decretos não localizados no texto', Fd, 'contagem', estado='A CONFERIR', nivel=1)} "
             f"números do intervalo não foram localizados no texto coletado (não significa que não existam).</p>",
             "<h3>5.1 Decretos por categoria</h3>"]
        lin = [[_e(k), self._n(f"atos.cat.{re.sub(r'[^a-z]+', '_', gc._sem_acento(k).lower())}", n, f"decretos — {k}", Fd, "por categoria")]
               for k, n in (a.get("por_categoria") or {}).items()]
        h.append(_tabela(["Categoria", "Decretos"], lin, {1}))
        orc = [d for d in dec if d["categoria"] == "orçamentário"]
        h.append("<h3>5.2 Decretos com efeito orçamentário (lista integral)</h3>")
        por_tipo = defaultdict(lambda: [0, 0.0])
        for d in orc:
            por_tipo[d.get("tipo_orc", "outro")][0] += 1
            por_tipo[d.get("tipo_orc", "outro")][1] += d.get("valor_ementa") or 0
        lin = [[_e(k), self._n(f"atos.orc.tipo.{re.sub(r'[^a-z]+', '_', gc._sem_acento(k).lower())}.n", v[0], f"decretos — {k}", Fd, "por tipo"),
                self.reg.v(f"atos.orc.tipo.{re.sub(r'[^a-z]+', '_', gc._sem_acento(k).lower())}.valor", v[1], "BRL",
                           f"valor nas ementas — {k}", Fd, "soma do primeiro valor em R$ da ementa", natureza="autorizado",
                           estado="A CONFERIR", nivel=1)]
               for k, v in sorted(por_tipo.items(), key=lambda kv: -kv[1][1])]
        h.append(_tabela(["Tipo", "Decretos", "Valor nas ementas"], lin, {1, 2}))
        h.append('<div class="callout info">Crédito aberto não é gasto: o decreto autoriza a despesa (Lei 4.320/1964, arts. '
                 '40–46); o que foi pago está no Capítulo 3. O valor é o primeiro valor em reais da ementa, lido do texto '
                 'do Diário — estado A CONFERIR até a conferência com o QDD publicado. A suplementação exige autorização '
                 'legislativa prévia (CF, art. 167, V) — na LOA ou em lei específica: conferir o fundamento citado em '
                 'cada decreto.</div>')
        lin = []
        for d in tudo(orc):
            lin.append([f"{_e(d['numero'])}", _br(d["data"]), _e(d.get("tipo_orc", "")),
                        texto_com_fatos(self.reg, campo(d["ementa"], 260), f"atos.dec.{d['numero'].replace('.', '')}.ementa", Fd),
                        (self.reg.v(f"atos.dec.{d['numero'].replace('.', '')}.valor", d["valor_ementa"], "BRL",
                                    f"valor na ementa do Decreto {d['numero']}", Fd, f"DOERJ de {_br(d['publicado'])}",
                                    natureza="autorizado", estado="A CONFERIR", nivel=1)
                         if d.get("valor_ementa") is not None else "—"), _br(d["publicado"])])
        h.append(_tabela(["Decreto", "Data", "Tipo", "Ementa", "Valor na ementa", "DOERJ"], lin, {4}))
        pes = a.get("pessoal") or []
        h.append("<h3>5.3 Nomeações e exonerações do primeiro escalão</h3>")
        h.append(f"<p>{self._n('atos.pessoal.nomear', sum(x['ato'] == 'NOMEAR' for x in pes), 'nomeações de 1º escalão', Fd, 'contagem')} "
                 f"nomeações e {self._n('atos.pessoal.exonerar', sum(x['ato'] == 'EXONERAR' for x in pes), 'exonerações de 1º escalão', Fd, 'contagem')} "
                 f"exonerações de secretário, subsecretário, presidente/dirigente, procurador-geral e controlador-geral, "
                 f"em decretos assinados pelo governador em exercício (lista do extrator; pode estar incompleta).</p>")
        lin = [[_br(x["data"]), _e(x["ato"].title()), _e(x["nome"].title()), _e(campo(x["cargo"], 60)),
                _e(campo(x["orgao"], 70))] for x in tudo(pes)]
        h.append(_tabela(["Data", "Ato", "Nome", "Cargo", "Órgão"], lin))
        h.append("<h3>5.4 Controle: auditorias do Decreto 50.254/2026 e o TCE-RJ</h3>")
        aud, tce = (ctl.get("auditorias_50254") or {}), (ctl.get("tce") or {})
        Fc = "Diário Oficial do Estado do RJ (atos que citam o Decreto 50.254/2026); penalidades do TCE-RJ por data de sessão"
        h.append(f"<p>Atos publicados que citam o Decreto 50.254/2026 (auditorias da gestão): "
                 f"{self._n('ctl.aud.n', aud.get('n'), 'atos que citam o Decreto 50.254/2026', Fc, 'contagem')}, dos quais "
                 f"{self._n('ctl.aud.inst', aud.get('n_instauracoes'), 'atos que instauram auditoria/comissão', Fc, 'contagem')} "
                 f"instauram auditoria ou comissão. Penalidades aplicadas pelo TCE-RJ em sessões do período: "
                 f"{self._n('ctl.tce.n', tce.get('n'), 'penalidades TCE-RJ no período', Fc, 'contagem')} "
                 f"({self.reg.v('ctl.tce.valor', tce.get('valor'), 'BRL', 'valor das penalidades TCE-RJ no período', Fc, 'soma', natureza='penalidade')}; "
                 f"última sessão coletada {_br(tce.get('ultima_sessao'))}). Os autos das auditorias (respostas, termos de "
                 f"ciência) não estão na base — só a publicação.</p>")
        return "".join(h)

    # ── 6. achados
    def _ficha(self, it: dict) -> str:
        iid = str(it["id"])
        k = re.sub(r"[^A-Za-z0-9.\-]+", "_", iid)
        fonte = f"régua da gestão — {it.get('fonte') or 'SIAFE-Rio'}"
        reg = self.reg
        titulo = texto_com_fatos(reg, it.get("regra_ou_hipotese"), f"ach.{k}.titulo", fonte)
        regra = iid.split("-")[0].split("·")[0].strip()
        val = ("—" if it.get("valor_ob") is None else
               reg.v(f"ach.{k}.valor_ob", it["valor_ob"], "BRL", f"valor do indício {iid} (soma de OB da régua)", fonte,
                     "valor_ob do item", natureza="pago", estado="A CONFERIR", nivel=1))
        provas = []
        for j, p in enumerate(it["provas"], 1):
            cls = {"confere": "ok", "diverge": "diverge"}.get(p["resultado"], "")
            extra = ""
            if p["tipo"] == "OB" and p["resultado"] == "confere":
                extra = (" — reconferida agora: " + self._pago(f"ach.{k}.prova{j}", p["valor"],
                         f"OB {p['ob']} UG {p['ug']} reconferida no SIAFE", f"OB {p['ob']} · UG {p['ug']}",
                         confirmado=p.get("confirmada")) + f" ({_e(p['detalhe'])})")
            else:
                extra = f" — {_e(p['resultado'].replace('_', ' '))}: {_e(p['detalhe'])}"
            provas.append(f'<li class="prova {cls}" data-resultado="{p["resultado"]}">'
                          f'{texto_com_fatos(reg, p["texto"], f"ach.{k}.p{j}", fonte)}{extra}</li>')
        inoc = texto_com_fatos(reg, it.get("explicacao_inocente"), f"ach.{k}.inoc", fonte)
        igual = str(it.get("teste_inocente_texto") or "").strip() == str(it.get("explicacao_inocente") or "").strip()
        teste = ("" if igual else
                 f"<p><b>Teste da hipótese inocente:</b> {texto_com_fatos(reg, it['teste_inocente_texto'], f'ach.{k}.teste', fonte)}</p>"
                 if it.get("teste_inocente_texto") else
                 "<p><b>Teste da hipótese inocente:</b> não executado por código — a explicação acima foi nomeada pela "
                 "régua e precisa ser conferida na diligência.</p>")
        instr = (f"<p><b>Instrumento:</b> {texto_com_fatos(reg, it['instrumento_texto'], f'ach.{k}.instr', fonte)}</p>"
                 if it.get("instrumento_texto") else "")
        nota = (f"<p><b>Nota da verificação:</b> {texto_com_fatos(reg, (it.get('revisao') or {}).get('nota'), f'ach.{k}.rev', fonte)}</p>"
                if (it.get("revisao") or {}).get("nota") else "")
        vnota = (f"<p class='nota'>{texto_com_fatos(reg, it['valor_ob_nota'], f'ach.{k}.vnota', fonte)}</p>"
                 if it.get("valor_ob_nota") else "")
        seis = ", ".join(f'<a href="#sei-{_e(s.replace("/", "-"))}">{_e(s)}</a>' for s in it["processos_sei"]) or "—"
        orgao = _e(it.get("orgao") or "—")
        passo = texto_com_fatos(reg, it.get("proximo_passo"), f"ach.{k}.passo", fonte)
        req = (f"Requerimento de informação (CF, art. 50, § 2º, por simetria) ao titular de {orgao}: cópia integral "
               f"do(s) processo(s) {_e(', '.join(it['processos_sei']) or 'de pagamento das OB citadas')}, notas de "
               f"liquidação e atesto vinculados às OB citadas, e manifestação expressa sobre a hipótese inocente acima. "
               f"Em paralelo, comunicação ao TCE-RJ (LC estadual 63/1990) para exame no acompanhamento da gestão.")
        return (f'<div class="achado" data-achado="{_e(iid)}" data-provas-ok="{it["n_provas_ok"]}">'
                f'<h4>{_badge(it.get("grau"))} Achado {_e(iid)} — {lim(REGUA.get(regra, "critério da régua"))}</h4>'
                f"<p><b>O que se observou:</b> {titulo}</p>"
                f"<p><b>Órgão:</b> {orgao} · <b>Valor do indício:</b> {val} · <b>Processo(s):</b> {seis}</p>{vnota}"
                f"<p><b>Fonte:</b> {_e(it.get('fonte') or '—')}</p>"
                f"<p><b>Provas primárias (reconferidas por código em {_br(self.d['gerado_em'])}):</b></p><ul>{''.join(provas)}</ul>"
                f"{instr}<p><b>Hipótese inocente:</b> {inoc}</p>{teste}{nota}"
                f"<p><b>O que falta para fechar:</b> {passo}</p>"
                f'<div class="callout info"><b>Diligência sugerida.</b> {req}</div></div>')

    def achados(self) -> tuple[str, str]:
        ach = self.d["achados"]
        Fr = "régua da gestão (SIAFE-Rio, CEIS, espelho do TCE-RJ) com reconferência das provas primárias"
        if ach.get("estado") != "ok":
            return f'<div class="callout g2"><b>INDISPONÍVEL</b>: {_e(ach.get("erro"))}</div>', ""
        itens = ach["itens"]
        casos = [i for i in itens if i["passou"] and not re.fullmatch(r"D\d\d", str(i["id"]))]
        regras = [i for i in itens if re.fullmatch(r"D\d\d", str(i["id"]))]
        fora = [i for i in itens if not i["passou"] and not re.fullmatch(r"D\d\d", str(i["id"]))]
        cg = Counter(i["grau"] for i in casos)
        h = [f"<p>Achado é o indício que passou em TODOS os portões: (1) fato com identidade e proveniência; (2) prova "
             f"primária citada pela régua e reproduzida; (3) prova reconferida <i>agora</i> na fonte por código — a OB no "
             f"SIAFE com o mesmo número, UG e valor e ainda paga, o registro no CEIS, o contrato no espelho do TCE-RJ — "
             f"sem nenhuma prova divergente; (4) grau GRAVE ou ATENÇÃO na régua. Indício não é acusação: cada ficha traz a "
             f"hipótese inocente e o que falta para fechar.</p>",
             '<div class="kpis">'
             f'<div class="kpi"><b>{self._n("ach.n.passou", len(casos), "achados que passaram nos portões", Fr, "contagem")}</b><span>achados</span></div>'
             f'<div class="kpi"><b>{self._n("ach.n.grave", cg.get("🔴", 0), "achados GRAVE", Fr, "contagem")}</b><span>grau GRAVE</span></div>'
             f'<div class="kpi"><b>{self._n("ach.n.atencao", cg.get("🟡", 0), "achados ATENÇÃO", Fr, "contagem")}</b><span>grau ATENÇÃO</span></div>'
             f'<div class="kpi"><b>{self._n("ach.n.fora", len(fora), "itens que não passaram nos portões", Fr, "contagem")}</b><span>não passaram nos portões</span></div>'
             "</div>"]
        h.append("<h3>6.1 Quadro dos achados</h3>")
        lin = [[_badge(i["grau"]), f'<a href="#ach-{_e(i["id"])}">{_e(i["id"])}</a>', lim(REGUA.get(str(i["id"]).split("-")[0], "")),
                _e(campo(i.get("orgao"), 50)),
                ("—" if i.get("valor_ob") is None else self.reg.v(f"ach.{re.sub(r'[^A-Za-z0-9.-]+', '_', str(i['id']))}.valor_ob",
                                                                   i["valor_ob"], "BRL", f"valor do indício {i['id']} (soma de OB da régua)",
                                                                   f"régua da gestão — {i.get('fonte') or 'SIAFE-Rio'}", "valor_ob do item",
                                                                   natureza="pago", estado="A CONFERIR", nivel=1)),
                self._n(f"ach.{re.sub(r'[^A-Za-z0-9.-]+', '_', str(i['id']))}.provas_ok", i["n_provas_ok"],
                        f"provas reconferidas do achado {i['id']}", Fr, "contagem")] for i in casos]
        h.append(_tabela(["Grau", "Achado", "Critério", "Órgão", "Valor do indício", "Provas reconferidas"], lin, {4, 5}))
        h.append("<h3>6.2 Fichas dos achados</h3>")
        for i in casos:
            h.append(f'<span id="ach-{_e(i["id"])}"></span>' + self._ficha(i))
        h.append("<h3>6.3 Itens que não passaram nos portões (não são achados)</h3>")
        h.append("<p>Declarados para que nada se perca em silêncio: ficam em apuração e não podem ser usados como achado "
                 "até passar nos portões.</p>")
        lin = [[_e(i["id"]), _badge(i.get("grau")), texto_com_fatos(self.reg, campo(i.get("regra_ou_hipotese"), 220),
                                                                     f"fora.{re.sub(r'[^A-Za-z0-9.-]+', '_', str(i['id']))}", "régua da gestão"),
                _e(i["motivo_portao"])] for i in fora]
        h.append(_tabela(["Item", "Grau na régua", "Descrição", "Por que não passou"], lin))
        # 7. régua (indicadores agregados)
        r = ["<p>Os critérios da régua medem o comportamento do universo (agregado); não são achados por si — os casos "
             "individuais que passaram nos portões estão no Capítulo 6. O número é o da régua, reproduzido (estado A "
             "CONFERIR no registro de fatos).</p>"]
        lin = [[_e(i["id"]), lim(REGUA.get(str(i["id"]), "")), _badge(i.get("grau")),
                texto_com_fatos(self.reg, i.get("regra_ou_hipotese"), f"regua.{i['id']}", "régua da gestão"),
                _e(i.get("verificacao") or "—")] for i in sorted(regras, key=lambda x: str(x["id"]))]
        r.append(_tabela(["Critério", "Nome", "Grau", "Resultado", "Estado"], lin))
        return "".join(h), "".join(r)

    # ── 1. sumário executivo
    def sumario_executivo(self) -> str:
        a, ach = self.agg, self.d["achados"]
        h = [f"<p>Este dossiê consolida a execução orçamentária e as contratações do Estado do Rio de Janeiro desde "
             f"{_br(INICIO)}, data em que o presidente do Tribunal de Justiça assumiu, interinamente, o exercício do "
             f"cargo de Governador. {_e(gc.GESTAO['fonte'])}</p>"]
        if a:
            c, p = a["couto"]["total"], a["anterior"]["total"]
            h.append(f'<div class="callout info"><b>Pago no período:</b> {self.reg.span(FAMILIA + ":exec.total.couto:valor")} '
                     f"em {self.reg.span(FAMILIA + ':exec.n.couto:valor')} OB (até {_br(self.ob['fim'])}), contra "
                     f"{self.reg.span(FAMILIA + ':exec.total.anterior:valor')} na mesma janela do ano anterior "
                     f"({self.reg.span(FAMILIA + ':exec.var:valor')}). Só Ordem Bancária que é pagamento entra na soma — "
                     f"empenho e liquidação, nunca.</div>")
        ct = self.d["contratacoes"]
        if "janelas" in ct:
            m = ct["janelas"]["couto"]["modalidades"]
            h.append(f"<p>Contratações diretas emergenciais registradas no espelho do TCE-RJ: "
                     f"{self.reg.span(FAMILIA + ':ctr.mod.dispensa_emergencial.n:valor')} contratos, "
                     f"{self.reg.span(FAMILIA + ':ctr.mod.dispensa_emergencial.valor:valor')} contratados"
                     + (f" ({self.reg.span(FAMILIA + ':ctr.mod.dispensa_emergencial.var:valor')} sobre o ano anterior)"
                        if self.reg.tem("ctr.mod.dispensa_emergencial.var") else "")
                     + f". Termos de Ajuste de Contas — serviço executado sem contrato — somaram "
                     f"{self.reg.span(FAMILIA + ':tac.valor:valor')} reconhecidos no Diário Oficial"
                     + (f" ({self.reg.span(FAMILIA + ':tac.var:valor')} sobre a mesma janela do ano anterior)"
                        if self.reg.tem("tac.var") else "") + ".</p>")
        if ach.get("estado") == "ok":
            casos = [i for i in ach["itens"] if i["passou"] and not re.fullmatch(r"D\d\d", str(i["id"]))]
            graves = [i for i in casos if i["grau"] == "🔴"]
            aten, nota = top_declarado([i for i in casos if i["grau"] == "🟡"], 6, "achados de grau ATENÇÃO",
                                       onde="no Capítulo 6")
            h.append(f"<p>Passaram em todos os portões {self.reg.span(FAMILIA + ':ach.n.passou:valor')} achados — "
                     f"{self.reg.span(FAMILIA + ':ach.n.grave:valor')} de grau GRAVE e "
                     f"{self.reg.span(FAMILIA + ':ach.n.atencao:valor')} de grau ATENÇÃO. Outros "
                     f"{self.reg.span(FAMILIA + ':ach.n.fora:valor')} itens da régua ficaram fora por não terem prova "
                     f"primária reconferida — estão declarados, não escondidos.</p>")
            for i in graves + aten:
                k = re.sub(r"[^A-Za-z0-9.\-]+", "_", str(i["id"]))
                cls = "g3" if i["grau"] == "🔴" else "g2"
                v = (f" — {self.reg.span(f'{FAMILIA}:ach.{k}.valor_ob:valor')}" if i.get("valor_ob") is not None else "")
                h.append(f'<div class="callout {cls}">{_badge(i["grau"])} <b><a href="#ach-{_e(i["id"])}">Achado '
                         f"{_e(i['id'])}</a></b>{v}: {texto_com_fatos(self.reg, i.get('regra_ou_hipotese'), f'ach.{k}.titulo', 'régua da gestão — ' + (i.get('fonte') or 'SIAFE-Rio'))}"
                         f"<br><i>Hipótese inocente:</i> {texto_com_fatos(self.reg, i.get('explicacao_inocente'), f'ach.{k}.inoc', 'régua da gestão — ' + (i.get('fonte') or 'SIAFE-Rio'))}</div>")
            if nota:
                h.append(f"<p class='nota'>{_e(nota)}</p>")
        h.append("<p>O que está INDISPONÍVEL — e por quê — está no Capítulo 8; nada indisponível foi tratado como zero. "
                 "As diligências concretas (requerimentos à ALERJ e comunicação ao TCE-RJ) estão no Capítulo 9.</p>")
        return "".join(h)

    def metodologia(self) -> str:
        ob = self.ob
        h = ["<h3>2.1 Recortes</h3>",
             f"<p><b>Período da gestão:</b> desde {_br(INICIO)}. {_e(gc.GESTAO['transicao'])}</p>",
             (f"<p><b>Comparação:</b> a mesma janela de dias do ano anterior ({_br(ob.get('inicio_ant'))} a "
              f"{_br(ob.get('fim_ant'))}), sob o governo anterior, pela mesma fonte e a mesma regra de pagamento.</p>"
              if ob.get("estado") == "ok" else ""),
             "<h3>2.2 Fontes primárias</h3>",
             _tabela(["Fonte", "O que fornece"], [
                 ["SIAFE-Rio 2 (Ordem Bancária)", "pagamento: número da OB, UG emitente, credor, data, valor, status e "
                  "status de envio ao banco, tipo (orçamentária / restos a pagar)"],
                 ["Diário Oficial do Estado do RJ", "decretos e atos assinados \"Governador em exercício\"; extratos de "
                  "TAC; atos das auditorias do Decreto 50.254/2026"],
                 ["Tribunal de Contas do Estado do RJ", "espelho de contratações, contratações diretas, penalidades"],
                 ["Portal Nacional de Contratações Públicas (PNCP)", "termos aditivos publicados"],
                 ["CEIS/CNEP (Controladoria-Geral da União)", "sanções vigentes a empresas"],
                 ["SEI-RJ (processos eletrônicos)", "autos dos processos de contratação e pagamento"],
                 ["Portal de dados abertos do Estado", "cadastro de UG, órgão e Poder"]]),
             "<h3>2.3 Regras de honestidade</h3><ul>"
             "<li><b>Pago = Ordem Bancária que é pagamento</b>: Contabilizada no SIAFE, não devolvida pelo banco, sem "
             "pagamento complementar (que repetiria a OB principal), sem OB reemitida, com número. Empenho e liquidação "
             "nunca são \"pago\" (Lei 4.320/1964, arts. 58–65).</li>"
             "<li><b>Estado de cada número</b>: VERIFICADO (lido da fonte primária, com prova); A CONFERIR (lido da "
             "fonte, mas com etapa pendente — ex.: OB sem confirmação de envio, valor de ementa, número reproduzido da "
             "régua); INDISPONÍVEL (a fonte não tem — nunca zero). O estado de cada fato está no Anexo C.</li>"
             "<li><b>Indício não é acusação</b>: presunção de legitimidade dos atos; cada achado traz a hipótese inocente.</li>"
             "<li><b>Pessoa física</b> só aparece agregada, sem CPF nem nome (LGPD), salvo agente público no exercício "
             "do cargo em ato publicado.</li>"
             "<li><b>Escopo</b>: Estado do Rio de Janeiro. Nada federal ou de outro ente.</li></ul>",
             "<h3>2.4 Escala de risco</h3>",
             _tabela(["Grau", "Significado", "Uso"], [
                 [_badge("🔴"), "indício forte com prova primária reconferida — ex.: pagamento a empresa inidônea com "
                  "contrato firmado na vigência da sanção", "requerimento imediato e comunicação ao TCE-RJ"],
                 [_badge("🟡"), "indício que exige explicação do gestor; a hipótese inocente é plausível e não foi "
                  "descartada", "requerimento de informação"],
                 [_badge("⚪"), "fato verificado sem indício, ou indício não verificado", "monitorar; não é achado"]]),
             "<h3>2.5 Normas de referência</h3>",
             _tabela(["Norma", "Pertinência"], [[lim(n), lim(t)] for n, t in NORMAS]),
             "<h3>2.6 Rastreabilidade</h3><p>Todo número monetário, percentual e de tabela deste documento é um fato "
             "com identidade única, publicado com fonte, consulta, data de referência e estado (Anexo C). Antes de o PDF "
             "valer, um verificador automático confere que (a) cada número impresso é um fato do registro, com o mesmo "
             "valor; (b) cada achado tem prova primária reconferida; (c) o PDF contém todo o conteúdo do HTML.</p>"]
        return "".join(h)

    def lacunas(self) -> str:
        d, L = self.d, []
        L.append(["Pago por função de governo", "INDISPONÍVEL", "a OB não traz função; dados abertos por função só até 2025",
                  "requerer à SEFAZ a execução paga por função desde 23/03/2026"])
        if self.ob.get("estado") == "ok":
            L.append(["OB posteriores à última coleta", "INDISPONÍVEL", f"última OB paga coletada em {_br(self.ob['fim'])}",
                      "nova coleta do SIAFE (automática)"])
        else:
            L.append(["Execução por OB", "INDISPONÍVEL", str(self.ob.get("erro")), "coleta do SIAFE"])
        ct = d["contratacoes"]
        if "janelas" in ct:
            L.append(["Contratos depois do último registro do espelho do TCE-RJ", "INDISPONÍVEL",
                      f"espelho até {_br(ct.get('ultimo_registro'))}", "atualização do espelho"])
        for rot, bloco in (("Contratações", d.get("contratacoes")), ("Termos aditivos", d.get("aditivos")),
                           ("Termos de Ajuste de Contas", d.get("tac"))):
            ant = ((bloco or {}).get("janelas") or {}).get("anterior") or {}
            if ant.get("indisponivel"):
                L.append([f"{rot} — mesma janela do ano anterior", "INDISPONÍVEL", ant["indisponivel"],
                          "coleta retroativa da fonte; até lá, sem comparação com o governo anterior"])
        L.append(["Modalidade de licitação dos contratos sem contratação direta", "INDISPONÍVEL",
                  "o espelho do TCE-RJ não publica a modalidade", "requerer o processo SEI"])
        L.append(["Universo de termos aditivos", "PARCIAL", "o PNCP só tem o que o órgão publicou; parte sem valor",
                  "requerer aos órgãos a relação de aditivos"])
        L.append(["Estoque de restos a pagar inscritos", "INDISPONÍVEL", "a base tem só o RP pago (tipo da OB)",
                  "RREO/RGF publicados — conferir com a Comissão de Orçamento"])
        dec = (d.get("controle") or {}).get("tce_decisoes") or {}
        if dec.get("estado") == "indisponivel":
            L.append(["Acórdãos do TCE-RJ", "INDISPONÍVEL", dec.get("motivo", ""), "consulta ao TCE-RJ"])
        a = d.get("atos") or {}
        if a.get("n_faltam_no_intervalo"):
            L.append(["Decretos do intervalo não localizados", "PARCIAL", "cabeçalho partido entre páginas ou edição não "
                      "coletada", "consulta ao Diário Oficial pela numeração"])
        ach = d.get("achados") or {}
        cs = ach.get("camada_subjetiva") or {}
        n_hip = sum(1 for i in ach.get("itens", []) if i.get("camada") == "subjetiva")
        if n_hip:
            L.append(["Hipóteses analíticas da camada subjetiva", "PENDENTE",
                      f"{n_hip} hipótese(s) aguardando conferência ({cs.get('conferencia_opus') or 'sem estado'})",
                      "conferência antes de qualquer uso"])
        for x in ach.get("indisponivel") or []:
            L.append([str(x), "INDISPONÍVEL", "regra da régua cuja fonte falhou", "recoleta da fonte"])
        sem_autos = [p for p, s in (d.get("sei") or {}).items() if s.get("estado") == "autos não capturados"]
        if sem_autos:
            L.append(["Autos SEI dos achados", "PARCIAL", f"{len(sem_autos)} processo(s) sem autos capturados (Anexo A)",
                      "captura dos autos ou requerimento"])
        L.append(["Autos das auditorias do Decreto 50.254/2026", "INDISPONÍVEL", "só a publicação no Diário está na base",
                  "requerer à CGE os relatórios"])
        return ("<p>INDISPONÍVEL não é zero: é o que a fonte disponível não permite afirmar. PARCIAL: há dado, mas não é o "
                "universo. PENDENTE: há dado, aguardando conferência.</p>"
                + _tabela(["Lacuna", "Estado", "Por quê", "Como fechar"], [[_e(x) for x in lin] for lin in L]))

    def diligencias(self) -> str:
        ach = self.d["achados"]
        casos = [i for i in ach.get("itens", []) if i.get("passou") and not re.fullmatch(r"D\d\d", str(i["id"]))]
        por_org = defaultdict(list)
        for i in casos:
            por_org[i.get("orgao") or "—"].append(i)
        h = ["<p>Consolidação por órgão destinatário. Base: requerimento de informação (CF, art. 50, § 2º, por "
             "simetria, e Regimento Interno da ALERJ) e comunicação ao Tribunal de Contas do Estado (CF, arts. 71 e 75; "
             "LC estadual 63/1990). Cada item remete à ficha do achado.</p>"]
        lin = []
        for org, its in sorted(por_org.items(), key=lambda kv: -max(float(i.get("valor_ob") or 0) for i in kv[1])):
            procs = sorted({p for i in its for p in i["processos_sei"]})
            lin.append([_e(org), ", ".join(f'<a href="#ach-{_e(i["id"])}">{_e(i["id"])}</a>' for i in its),
                        _e(", ".join(procs) or "processos de pagamento das OB citadas"),
                        "cópia integral dos autos; NL, NE e atesto das OB citadas; manifestação sobre a hipótese inocente"])
        h.append(_tabela(["Destinatário", "Achados", "Processos", "O que requerer"], lin))
        h.append('<div class="callout info"><b>Pedidos gerais à SEFAZ:</b> (1) execução paga por função e subfunção desde '
                 '23/03/2026; (2) relação de OB anuladas/excluídas e reemitidas no período, com motivo; (3) estoque de '
                 'restos a pagar inscritos e cancelados; (4) QDD com a fonte de cada crédito suplementar aberto por '
                 'decreto. <b>À CGE:</b> relatórios das auditorias instauradas com base no Decreto 50.254/2026.</div>')
        return "".join(h)

    def anexo_sei(self) -> str:
        ach = self.d["achados"]
        casos = [i for i in ach.get("itens", []) if i.get("passou") and not re.fullmatch(r"D\d\d", str(i["id"]))]
        lin = []
        for p, st in sorted((self.d.get("sei") or {}).items()):
            quem = [i["id"] for i in casos if p in i["processos_sei"]]
            det = st["estado"] + (f" — {st['docs']} documento(s)" + (", captura completa" if st.get("completo") else
                                   ", captura incompleta") if "docs" in st else "")
            lin.append([f'<span id="sei-{_e(p.replace("/", "-"))}"></span><span class="mono">{_e(p)}</span>',
                        ", ".join(f'<a href="#ach-{_e(q)}">{_e(q)}</a>' for q in quem), _e(det)])
        return (f"<p>Processos SEI citados pelos achados. Consulta pública: <a href=\"{SEI_PESQUISA}\">pesquisa pública "
                f"de processos do SEI-RJ</a> (informar o número). Estado = situação dos autos no acervo de leitura.</p>"
                + _tabela(["Processo", "Achado(s)", "Autos"], lin))

    def anexo_fatos(self) -> str:
        lin = []
        for f in sorted(self.reg.f.values(), key=lambda x: x["fato_id"]):
            lin.append([f'<span class="mono">{_e(f["fato_id"])}</span>', lim(campo(f["rotulo"], 120)),
                        f'<span class="fato" data-fato="{f["fato_id"]}">{_e(f["exibido"])}</span>',
                        _e(f["estado"].replace("INDISPONIVEL", "INDISPONÍVEL")), _e(campo(f["fonte"], 90))])
        return (f"<p>Registro integral dos {len(lin)} fatos citados neste documento. O mesmo registro é publicado no "
                f"arquivo de fatos que acompanha o dossiê, com a consulta e a data de referência de cada um.</p>"
                + _tabela(["Identificador", "O que afirma", "Valor", "Estado", "Fonte"], lin, {2}, cls="registro"))

    def montar(self) -> dict:
        exe = self.panorama()
        ctr = self.contratacoes()
        atos = self.atos()
        ach, regua = self.achados()
        anexo_b = self.anexo_ug()
        sumario_exec = self.sumario_executivo()       # depois: cita fatos já registrados
        met = self.metodologia()
        lac = self.lacunas()
        dil = self.diligencias()
        sei = self.anexo_sei()
        self.sec("s1", "1. Sumário executivo", sumario_exec)
        self.sec("s2", "2. Metodologia, fontes e normas", met)
        self.sec("s3", "3. Panorama da execução orçamentária — ordens bancárias pagas", exe)
        self.sec("s4", "4. Contratações, aditivos e termos de ajuste de contas", ctr)
        self.sec("s5", "5. Decretos e atos do governador em exercício", atos)
        self.sec("s6", "6. Achados que passaram nos portões", ach)
        self.sec("s7", "7. Indicadores sistêmicos da régua", regua)
        self.sec("s8", "8. Lacunas — o que está INDISPONÍVEL e por quê", lac)
        self.sec("s9", "9. Diligências recomendadas", dil)
        self.sec("anexo-a", "Anexo A — Processos SEI que embasam os achados", sei)
        self.sec("anexo-b", "Anexo B — Execução por unidade gestora (lista integral)", anexo_b)
        self.sec("anexo-c", "Anexo C — Registro de fatos", self.anexo_fatos())
        itens = "".join(f'<li><a href="#{s["id"]}">{_e(s["titulo_txt"])}</a></li>' for s in self.secoes)
        kpis = []
        for rot, chave in (("pago no período (OB)", "exec.total.couto"), ("variação × mesma janela de 2025", "exec.var"),
                           ("pago excluídas transferências a UG do Estado", "exec.liquido.couto"),
                           ("achados GRAVE", "ach.n.grave"), ("achados ATENÇÃO", "ach.n.atencao"),
                           ("contratado por dispensa emergencial", "ctr.mod.dispensa_emergencial.valor"),
                           ("reconhecido em TAC (sem contrato)", "tac.valor"),
                           ("decretos assinados pelo governador em exercício", "atos.decretos.n")):
            fid = chave
            if self.reg.tem(fid):
                kpis.append(f'<div class="kpi"><b>{self.reg.span(fid)}</b><span>{_e(rot)}</span></div>')
        sumario = {"id": "s0", "titulo": _ancora("s0", "Sumário"), "titulo_txt": "Sumário", "page_break": False,
                   "html": _CSS + f'<div class="kpis">{"".join(kpis)}</div>'
                           f'<ol class="sumario" style="list-style:none;padding-left:0">{itens}</ol>'
                           '<p class="nota">Os itens do sumário e as remissões do texto são links clicáveis.</p>'}
        secoes = [sumario] + self.secoes
        flags = []
        if self.agg:
            flags.append("Pago no período: " + self.reg.span(f"{FAMILIA}:exec.total.couto:valor"))
        ach_d = self.d["achados"]
        if ach_d.get("estado") == "ok":
            casos = [i for i in ach_d["itens"] if i["passou"] and not re.fullmatch(r"D\d\d", str(i["id"]))]
            flags.append(self.reg.span(f"{FAMILIA}:ach.n.passou:valor") + " achados nos portões")
        flags.append("Indício ≠ acusação · INDISPONÍVEL ≠ 0")
        fim = self.ob.get("fim") or self.d["gerado_em"]
        ctx = {
            "classificacao": "RESERVADO — PEÇA DE CONTROLE EXTERNO",
            "titulo": "Dossiê-Mestre da Gestão do Governador em Exercício — Estado do Rio de Janeiro",
            "subtitulo": (f"Execução orçamentária, contratações, atos e achados · {_br(INICIO)} a {_br(fim)} · comparado à "
                          f"mesma janela do ano anterior"),
            "data": _br(self.d["gerado_em"]), "analista": "Controle Externo (automatizado, com verificação por código)",
            "metodologia": "OB paga do SIAFE-Rio · portões de prova primária · registro de fatos com identidade",
            "sem_indice": True, "top_flags": flags,
            "secoes": [{"titulo": s["titulo"], "html": s["html"], "page_break": s["page_break"]} for s in secoes],
            "proveniencia": [
                {"dado": "Ordens bancárias", "estado": "VERIFICADO / A CONFERIR (por fato)", "fonte": "SIAFE-Rio 2",
                 "data": _br(self.ob.get("ultima_coleta") or self.ob.get("fim"))},
                {"dado": "Contratações", "estado": "VERIFICADO (contratado)", "fonte": "Espelho do TCE-RJ",
                 "data": _br((self.d["contratacoes"] or {}).get("ultimo_registro"))},
                {"dado": "Decretos, TAC, auditorias", "estado": "VERIFICADO (texto publicado)", "fonte": "DOERJ",
                 "data": _br((self.d["tac"] or {}).get("ultimo_registro"))},
                {"dado": "Sanções", "estado": "VERIFICADO (reconferido)", "fonte": "CEIS/CNEP", "data": _br(self.d["gerado_em"])}],
            "ressalva": ("Indícios para apuração; presunção de legitimidade dos atos administrativos. Pago = só ordem "
                         "bancária que é pagamento; empenho nunca é pago; contrato é valor contratado; TAC é valor "
                         "reconhecido. INDISPONÍVEL não é zero. Nenhum dado indisponível foi fabricado."),
            "_dados": self.reg.publicar(),
        }
        return ctx


# ───────────────────────────── PDF com numeração de páginas ─────────────────────────────
async def _pdf_numerado(html: str, destino: str, timeout_s: float = 900.0) -> str:
    """Mesmo Chromium do gerador da casa, com rodapé numerado (pedido explícito deste produto). Não altera o
    `html_to_pdf` compartilhado (o restante da casa segue sem numeração, por diretriz anterior do dono)."""
    from playwright.async_api import async_playwright
    Path(destino).parent.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            page = await b.new_page()
            page.set_default_timeout(timeout_s * 1000)       # o padrão de 30 s não basta para ~2 MB com a VM carregada
            arq = Path(destino).with_suffix(".fonte.html")
            arq.write_text(html, encoding="utf-8")
            try:
                await asyncio.wait_for(page.goto(arq.resolve().as_uri(), wait_until="load"), timeout_s)
            finally:
                arq.unlink(missing_ok=True)
            await asyncio.wait_for(page.pdf(
                path=destino, format="A4", print_background=True, display_header_footer=True,
                header_template="<span></span>",
                footer_template=("<div style='font-family:Georgia,serif;font-size:7.5px;color:#888;width:100%;"
                                 "padding:0 12mm;display:flex;justify-content:space-between'>"
                                 "<span>Controle Externo — RJ · Dossiê-Mestre da Gestão · indícios, nunca acusação</span>"
                                 "<span>Página <span class='pageNumber'></span> de <span class='totalPages'></span></span></div>"),
                margin={"top": "14mm", "bottom": "14mm", "left": "10mm", "right": "10mm"}), timeout_s)
        finally:
            await b.close()
    return destino


def texto_pdf(pdf: Path) -> str:
    r = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise OSError(f"pdftotext falhou: {r.stderr.strip()}")
    return r.stdout


# ───────────────────────────── verificador ─────────────────────────────
_RX_SPAN = re.compile(r'<span class="fato" data-fato="([^"]+)">([^<]*)</span>')
_RX_SPAN_APROX = re.compile(r'<span class="fato" data-fato="([^"]+)" data-aprox="1">([^<]*)</span>')
_RX_CPF = re.compile(r"(?<![\d*])\d{3}\.\d{3}\.\d{3}-\d{2}(?!\d)|(?<![\d/])\d{11}(?![\d/])")


def _visivel(html: str) -> str:
    t = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", html)
    t = re.sub(r"<!--.*?-->", " ", t, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", H.unescape(t)).strip()


def verificar(html: str, fatos: dict, achados: list[dict], pdf_texto: str | None) -> dict:
    """Reprova se: número sem fato · fato com valor diferente do registro · célula numérica sem fato · achado sem
    prova primária reconferida · termo interno · CPF · PDF sem o conteúdo do HTML."""
    falhas: list[str] = []
    reg = {f["fato_id"]: f for lst in ("brl", "contagem", "percentual", "indice") for f in fatos.get(lst, [])}
    spans = _RX_SPAN.findall(html)
    for fid, txt in spans:
        f = reg.get(fid)
        if f is None:
            falhas.append(f"número {txt!r} cita fato inexistente {fid}")
        elif H.unescape(txt) != exibir(f["valor"], f["unidade"]):
            falhas.append(f"fato {fid}: impresso {txt!r}, registro diz {exibir(f['valor'], f['unidade'])!r}")
    aprox = _RX_SPAN_APROX.findall(html)
    for fid, txt in aprox:
        f = reg.get(fid)
        if f is None or abs(valor_aproximado(H.unescape(txt)) - float(f["valor"] or 0)) > 0.01:
            falhas.append(f"aproximação {txt!r} não confere com o fato {fid}")
    sem = _visivel(re.sub(r'<span class="limiar">[^<]*</span>', " ", _RX_SPAN_APROX.sub(" ", _RX_SPAN.sub(" ", html))))
    for m in re.finditer(r"R\$\s?-?\d|\d\s?%", sem):
        falhas.append(f"número sem fato: …{sem[max(0, m.start() - 60): m.end() + 30]}…")
        if len(falhas) > 200:
            break
    for cel in re.findall(r'<td class="n">(.*?)</td>', html, flags=re.S):
        if not (_RX_SPAN.search(cel) or _visivel(cel) in ("—", "INDISPONÍVEL", "")):
            falhas.append(f"célula numérica sem fato: {campo(_visivel(cel), 80)}")
    fichas = dict(re.findall(r'data-achado="([^"]+)" data-provas-ok="(\d+)"', html))
    ids_ach = {str(a["id"]) for a in achados if a.get("passou") and not re.fullmatch(r"D\d\d", str(a["id"]))}
    for a in achados:
        if str(a["id"]) in ids_ach and not a.get("n_provas_ok"):
            falhas.append(f"achado {a['id']} sem prova primária reconferida")
    for i in ids_ach - set(H.unescape(k) for k in fichas):
        falhas.append(f"achado {i} sem ficha no documento")
    for k, n in fichas.items():
        if int(n) < 1:
            falhas.append(f"ficha {k} sem prova reconferida")
        if H.unescape(k) not in ids_ach:
            falhas.append(f"ficha {k} não é achado que passou nos portões")
    from compliance_agent.reporting.neutralidade import termos_proibidos
    vis = _visivel(html)
    if termos_proibidos(vis):
        falhas.append(f"termo interno no documento: {termos_proibidos(vis)}")
    cpfs = _RX_CPF.findall(vis)
    if cpfs:
        falhas.append(f"{len(cpfs)} possível(is) CPF em claro no documento")
    cobertura = None
    if pdf_texto is not None:
        compacto = re.sub(r"\s+", "", pdf_texto)
        faltam = sorted({H.unescape(t) for _f, t in spans if re.sub(r"\s+", "", H.unescape(t)) not in compacto})
        for t in faltam:
            falhas.append(f"valor {t!r} está no HTML e não no PDF")
        for i in ids_ach:
            if re.sub(r"\s+", "", i) not in compacto:
                falhas.append(f"achado {i} está no HTML e não no PDF")
        ph = Counter(w for w in re.findall(r"[A-Za-zÀ-ÿ]{4,}", vis))
        pp = Counter(w for w in re.findall(r"[A-Za-zÀ-ÿ]{4,}", pdf_texto))
        tot = sum(ph.values())
        cobertura = round(sum(min(n, pp.get(w, 0)) for w, n in ph.items()) / tot, 4) if tot else 0.0
        if cobertura < COBERTURA_MIN:
            falhas.append(f"o PDF perdeu conteúdo do HTML: cobertura de palavras {cobertura:.2%} < {COBERTURA_MIN:.0%}")
    return {"aprovado": not falhas, "falhas": falhas, "n_falhas": len(falhas), "n_numeros_citados": len(spans) + len(aprox),
            "n_aproximados": len(aprox),
            "n_fatos_registro": len(reg), "n_achados": len(ids_ach), "cobertura_pdf": cobertura,
            "pdf_conferido": pdf_texto is not None, "em": datetime.now().isoformat(timespec="seconds")}


# ───────────────────────────── orquestração ─────────────────────────────
def _gravar(caminho: Path, obj) -> str:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_suffix(caminho.suffix + ".tmp")
    bruto = json.dumps(obj, ensure_ascii=False, default=lambda o: sorted(o) if isinstance(o, set) else str(o), indent=1)
    tmp.write_text(bruto, encoding="utf-8")
    tmp.replace(caminho)
    return hashlib.md5(bruto.encode()).hexdigest()


def _carga() -> float:
    try:
        return float(Path("/proc/loadavg").read_text().split()[0])
    except (OSError, ValueError):
        return 0.0


def gerar(ob_brutos_arq: Path | None = None, *, com_pdf: bool = True, carga_max_local: float = 7.0) -> dict:
    from compliance_agent.reporting.neutralidade import garantir_neutro
    from compliance_agent.reporting.render_html import render_html
    ob = None
    origem = "local"
    if ob_brutos_arq and Path(ob_brutos_arq).exists():
        ob = json.loads(Path(ob_brutos_arq).read_text(encoding="utf-8"))
        con = _ro(gc.DB)
        try:
            amostra = conferir_amostra(con, ob)
        finally:
            con.close()
        _gravar(DIR / "amostra_replica.json", amostra)
        if amostra["ok"]:
            origem = f"réplica ({ob.get('maquina')}) — amostra igual em {len(amostra['amostra'])} comparações"
        else:
            logger.warning("dossiê Couto: amostra da réplica DIVERGE — recusada: %s", amostra)
            ob = None
    if ob is None and _carga() > carga_max_local and ob_brutos_arq:
        return {"ok": False, "adiado": True, "motivo": f"réplica recusada/ausente e VM-1 em carga {_carga():.1f}"}
    dados = coletar(ob)
    dados["origem_ob"] = origem
    _gravar(DIR / "dados.json", dados)
    m = Montador(dados)
    ctx = m.montar()
    fatos = ctx["_dados"]
    html = render_html(ctx)
    _gravar(DIR / "fatos_candidato.json", fatos)
    garantir_neutro(_visivel(html), "dossiê da gestão")
    dia = date.today().isoformat()
    REPORTS.mkdir(parents=True, exist_ok=True)
    html_arq = DIR / f"{BASE_ARQ}_{dia}.html"
    html_arq.write_text(html, encoding="utf-8")
    pdf_arq, txt = DIR / f"{BASE_ARQ}_{dia}.pdf", None
    if com_pdf:
        asyncio.run(_pdf_numerado(html, str(pdf_arq)))
        txt = texto_pdf(pdf_arq)
    ver = verificar(html, fatos, dados["achados"].get("itens", []), txt)
    ver["origem_ob"] = origem
    _gravar(DIR / "verificacao.json", ver)
    if ver["aprovado"]:
        # só o APROVADO vira vigente: fatos publicados (registro da casa) e o par HTML/PDF em reports/
        _gravar(DIR / "fatos.json", fatos)
        (REPORTS / html_arq.name).write_bytes(html_arq.read_bytes())
        if com_pdf:
            (REPORTS / pdf_arq.name).write_bytes(pdf_arq.read_bytes())
        _gravar(DIR / "vigente.json", {"html": str(REPORTS / html_arq.name),
                                       "pdf": str(REPORTS / pdf_arq.name) if com_pdf else None,
                                       "gerado_em": dados["gerado_em"], "n_fatos": fatos["n"],
                                       "verificacao": ver})
    return {"ok": ver["aprovado"], "html": str(html_arq), "pdf": str(pdf_arq) if com_pdf else None, "verificacao": ver,
            "origem_ob": origem}


def reverificar() -> dict:
    vig = json.loads((DIR / "vigente.json").read_text(encoding="utf-8"))
    html = Path(vig["html"]).read_text(encoding="utf-8")
    fatos = json.loads((DIR / "fatos.json").read_text(encoding="utf-8"))
    dados = json.loads((DIR / "dados.json").read_text(encoding="utf-8"))
    txt = texto_pdf(Path(vig["pdf"])) if vig.get("pdf") else None
    return verificar(html, fatos, dados["achados"].get("itens", []), txt)


def juizar(n: int = 6) -> dict:
    """Juiz de qualidade da casa (Claude da ASSINATURA, `backend=cli`; `publica=False` = nenhuma cascata grátis
    decide) sobre o sumário executivo e as fichas de maior grau/valor do dossiê vigente."""
    from compliance_agent.qualidade import juiz
    vig = json.loads((DIR / "vigente.json").read_text(encoding="utf-8"))
    html = Path(vig["html"]).read_text(encoding="utf-8")
    partes = []
    m = re.search(r'id="s1"></span>.*?</h2>(.*?)<h2', html, flags=re.S)
    if m:
        partes.append(("sumario", "Sumário executivo do dossiê da gestão", _visivel(m.group(1))))
    for aid, corpo in re.findall(r'<div class="achado" data-achado="([^"]+)"[^>]*>(.*?)</div></div>', html, flags=re.S):
        partes.append((f"achado:{aid}", f"Ficha do achado {aid}", _visivel(corpo)))
    sel, _nota = top_declarado(partes, n, "afirmações do dossiê para o juiz")
    res = []
    for pid, rot, txt in sel:
        a = juiz.Afirmacao(f"produto:{BASE_ARQ}:{pid}", "relatorios", campo(rot, 90),
                           "Trecho do dossiê-mestre da gestão (peça para a Comissão de Orçamento):\n" + campo(txt, 4500),
                           "🔴" if "GRAVE" in txt else "🟡", publica=False)
        av = juiz.julgar(a)
        res.append({"id": a.id, "estado": av.estado, "juiz": av.juiz, "veredito": av.veredito, "notas": av.notas,
                    "motivos": av.motivos, "o_que_falta": av.o_que_falta, "escalar": av.escalar})
    out = {"em": datetime.now().isoformat(timespec="seconds"), "dossie": vig["html"], "avaliacoes": res}
    _gravar(DIR / "juiz.json", out)
    return out


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(prog="python -m compliance_agent.reporting.dossie_couto")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gerar")
    g.add_argument("--ob-brutos", type=Path, help="JSON da varredura de OB feita na réplica (conferido por amostra)")
    g.add_argument("--sem-pdf", action="store_true")
    c = sub.add_parser("coletar-ob")
    c.add_argument("--saida", type=Path, required=True)
    sub.add_parser("verificar")
    j = sub.add_parser("juiz")
    j.add_argument("--n", type=int, default=6)
    a = ap.parse_args(argv)
    if a.cmd == "coletar-ob":
        con = _ro(gc.DB)
        if con is None:
            print(json.dumps({"ok": False, "erro": "base indisponível"}))
            return 1
        try:
            md5 = _gravar(a.saida, coletar_ob(con))
        finally:
            con.close()
        print(json.dumps({"ok": True, "saida": str(a.saida), "md5": md5}))
        return 0
    if a.cmd == "gerar":
        r = gerar(a.ob_brutos, com_pdf=not a.sem_pdf)
        print(json.dumps({k: v for k, v in r.items() if k != "verificacao"} | {"verificacao": {
            k: v for k, v in r.get("verificacao", {}).items() if k != "falhas"}, "falhas": (r.get("verificacao") or {}).get("falhas", [])[0:30]},
            ensure_ascii=False, indent=1))
        return 75 if r.get("adiado") else (0 if r.get("ok") else 2)
    if a.cmd == "verificar":
        r = reverificar()
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0 if r["aprovado"] else 2
    if a.cmd == "juiz":
        print(json.dumps(juizar(a.n), ensure_ascii=False, indent=1))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
