# -*- coding: utf-8 -*-
"""Gestão Couto (23/03/2026 →) — as 20 regras determinísticas (D01–D20) + a camada subjetiva (H*) pelo motor Claude.

Origem: análise feita à mão em 13/11/2026 (dossiê `~/vault/casos/gestao-couto-analise-2026-11-13.md`). Este módulo é
a mesma régua, recalculada SEMANALMENTE, que regrava `data/governo_couto_suspeitas.json` no MESMO formato que a aba
Estado › Governo Couto já lê (envelope `{"achados": [...]}`; cada item com id, camada, regra_ou_hipotese, grau, orgao,
processo, valor_ob, fonte, explicacao_inocente, proximo_passo).

Camadas:
  · DETERMINÍSTICA — D01..D20 (critério declarado em cada regra) + os casos por regra (D14, D05, D10, D18, D02);
  · SUBJETIVA — hipóteses H* geradas pelo motor Claude a partir dos achados determinísticos, SEMPRE com explicação
    inocente e próximo passo. Sem o motor (ausente, sem cota) as hipóteses anteriores são mantidas e marcadas
    `pendente` — a determinística segue de qualquer jeito;
  · CURADORIA MANUAL — o "top 10" (T01..T10) é seleção editorial lida de `data/governo_couto_curadoria.json` (dado
    real, fora do git — repositório público). Cada item declara o estado da verificação (SUSTENTADO, PARCIAL,
    REFUTADO); sem estado ele sai PENDENTE e ⚪. Não é mais preservado do arquivo anterior: era assim que títulos com
    números já refutados sobreviviam a cada rodada.

Regras da casa: pago = SÓ OB com status Contabilizado do SIAFE (`ob_orcamentaria_siafe`); TAC e contrato não são OB
(valor_ob nulo); INDISPONÍVEL ≠ zero (regra cuja fonte falha sai "INDISPONÍVEL", não zero); CPF mascarado; indício ≠
acusação. Somente leitura nas bases do JFN — a OB é copiada para uma base de trabalho temporária (datas ISO, índices).

Uso:  nice -n 15 timeout 3600 python -m compliance_agent.governo_couto_regras [--sem-motor] [--saida ...]
"""
from __future__ import annotations

import argparse
import collections
import datetime as D
import logging
import os
import re
import sqlite3
import statistics
import tempfile
import unicodedata
from pathlib import Path

from compliance_agent import rotina_base
from compliance_agent.rotina_base import DATA, RAIZ, agora_iso, executar, gravar_json, ler_json, pensar

logger = logging.getLogger(__name__)

NOME = "governo_couto_regras"
SAIDA = DATA / "governo_couto_suspeitas.json"
DETALHE = DATA / "governo_couto_regras.json"
CURADORIA = DATA / "governo_couto_curadoria.json"

DB = Path(os.environ.get("JFN_DB") or RAIZ / "data" / "compliance.db")
DB_RECEITA = Path(os.environ.get("JFN_DB_RECEITA") or RAIZ / "data" / "receita_estab.db")
DB_TSE = Path(os.environ.get("JFN_DB_TSE") or RAIZ / "data" / "doacao_tse.db")

G0 = "2026-03-23"                    # início da gestão (DOERJ 24/03/2026 — ver governo_couto.GESTAO)
P0, P1 = "2026-01-01", "2026-03-22"  # 2026 sob o governador anterior
SIAFE = "SIAFE-Rio, OB Orçamentária (status Contabilizado)"
TETO_PORTE = {"Microempresa": 360_000.0, "Empresa de Pequeno Porte": 4_800_000.0}
_OUTRO_PODER = re.compile(r"TRIBUNAL|ASSEMBLEIA|MINIST[EÉ]RIO P[UÚ]BLICO|PROCURADORIA.GERAL DE JUSTI|DEFENSORIA|"
                          r"JUSTI[CÇ]A|ENCARGOS GERAIS|FUNDO ESPECIAL DO MINISTERIO", re.I)
_OUT_CASO = re.compile(r"TRIBUNAL|ASSEMBLEIA|MINIST[EÉ]RIO P[UÚ]BLICO|MINISTERIO P|DEFENSORIA|DPGE|JUSTI[CÇ]A|"
                       r"FUNDO ESPECIAL DO MINISTERIO|MP -", re.I)
_RESTRINGE = re.compile(r"impedimento|suspens|inidone|proibi", re.I)
_MESES = {m: i + 1 for i, m in enumerate("JANEIRO FEVEREIRO MARÇO ABRIL MAIO JUNHO JULHO AGOSTO SETEMBRO OUTUBRO "
                                         "NOVEMBRO DEZEMBRO".split())}

# Grau da RÉGUA (atribuído na análise de 13/11/2026 ao tipo de sinal). Regra sem caso sai ⚪.
GRAU_REGRA = {"D01": "⚪", "D02": "🟡", "D03": "🟡", "D04": "🟡", "D05": "🟡", "D06": "⚪", "D07": "🟡", "D08": "⚪",
              "D09": "🟡", "D10": "🟡", "D11": "⚪", "D12": "⚪", "D13": "🟡", "D14": "🟡", "D15": "⚪", "D16": "🔴",
              "D17": "🟡", "D18": "🟡", "D19": "⚪", "D20": "⚪"}
# D14 (regra agregada) é 🟡: ela soma PAGAMENTOS na vigência, e o que a sanção veda é contratar. O 🔴 fica no CASO
# que tem contrato com ato na vigência (`_d14_vermelho`) — verificação independente de 13/11/2026.
# D18 rebaixado a 🟡 na revisão cética de 13/11/2026: "fantasma_score alto" não é fachada documentada (0 de 6 eram);
# 🔴 só com veredito de fachada registrado (ver achados_deterministicos).

# Curadoria T01..T10: o estado da verificação vem DECLARADO em cada item do arquivo de curadoria (verificação
# independente de 13/11/2026, `~/vault/notas/verificacao-fable-correcoes-2026-11-13.md` §6.1). Curadoria nunca carrega
# 🔴 — o 🔴 é da régua (caso D14 com contrato na vigência); PARCIAL sai no máximo 🟡; REFUTADO e PENDENTE saem ⚪.
ESTADOS_CURADORIA = ("SUSTENTADO", "PARCIAL", "REFUTADO")
INOCENTE_REGRA = {
    "D01": "contratação direta legítima (concessionária, inexigibilidade real) ou mudança de mix de objetos",
    "D02": "continuidade do serviço essencial enquanto a licitação corre",
    "D03": "empresa nova de grupo antigo (cisão, SPE) ou capital social desatualizado no cadastro",
    "D04": "porte desatualizado na Receita; certame sem benefício de ME/EPP",
    "D05": "contrato único grande (concessão/programa) ou licitação ampla vencida por um só",
    "D06": "acréscimo dentro do teto legal de reforma (50%) ou reajuste lançado como aditivo",
    "D07": "compras de objetos distintos ao mesmo credor; série de pequenas despesas legítimas",
    "D08": "continuidade administrativa ordinária na transição; folha e previdência",
    "D09": "pagamento de obrigações vencidas antes da troca de governo",
    "D10": "mudança estrutural (nova concessão, nova OS, compra de bens)",
    "D11": "sazonalidade do 2º semestre e remanejamento por anulação sem gasto novo",
    "D12": "troca de comando é prerrogativa do governador",
    "D13": "homônimo; agente público pode ser sócio quando não há vedação nem participação na contratação",
    "D14": "sanção de outro ente ou de alcance controvertido; efeito ex nunc; pagamento de serviço anterior",
    "D15": "doação eleitoral lícita e declarada",
    "D16": "serviço contínuo essencial sem contrato vigente durante a licitação",
    "D17": "emergências reais e distintas na mesma unidade",
    "D18": "sede administrativa diversa do local de execução",
    "D19": "verbas indenizatórias, abono e retroativos não entram no teto (sem composição não se conclui)",
    "D20": "reemissão (OB anulada e reemitida) ou correção de domicílio bancário",
}
PASSO_REGRA = {
    "D01": "ler os processos de dispensa/inexigibilidade das unidades que subiram",
    "D02": "verificar licitação em curso e há quanto tempo",
    "D03": "conferir QSA, sede e capacidade operacional antes de concluir",
    "D04": "requerer declaração de porte e ata dos certames",
    "D05": "identificar o instrumento (licitação, dispensa, TAC, permissão)",
    "D06": "conferir o percentual sobre o valor inicial atualizado e a natureza (reforma/serviço)",
    "D07": "ler as séries rentes ao teto de dispensa",
    "D08": "ler quem assinou e quando o processo chegou ao gabinete",
    "D09": "conferir as NL e a competência das OB da última semana",
    "D10": "ler o processo de origem",
    "D11": "requerer uso do limite de suplementação da LOA 2026",
    "D12": "cruzar as trocas com os contratos das pastas",
    "D13": "confirmar CPF do sócio e participação na contratação",
    "D14": "conferir competência das NL e consulta ao CEIS antes da OB",
    "D15": "conferir se o doador participa da contratação",
    "D16": "requerer o estágio das licitações e o plano de saída do TAC",
    "D17": "ler os processos da série emergencial",
    "D18": "vistoria e leitura do processo",
    "D19": "obter a composição de verbas da folha",
    "D20": "conferir a OB reemitida correspondente",
}


# ── utilidades ──────────────────────────────────────────────────────────────────────────────────────────────────

def dig(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def norm_nome(s) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper().replace("LTDA", "").replace("EIRELI", ""))


def nn(s) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
                  .upper()).strip()


def brl(v) -> str:
    if v is None:
        return "—"
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def pct(v) -> str:
    return "—" if v is None else f"{v * 100:.1f}%".replace(".", ",")


def iso_br(s: str | None) -> str | None:
    """'dd/mm/aaaa...' → 'aaaa-mm-dd'; ISO passa direto."""
    s = str(s or "")
    if len(s) >= 10 and s[2] == "/" and s[5] == "/":
        return f"{s[6:10]}-{s[3:5]}-{s[0:2]}"
    return s[:10] or None


def fim_mes_anterior(dia: str) -> str:
    d = D.date.fromisoformat(dia)
    return (d.replace(day=1) - D.timedelta(days=1)).isoformat()


def menos_um_ano(dia: str) -> str:
    d = D.date.fromisoformat(dia)
    try:
        return d.replace(year=d.year - 1).isoformat()
    except ValueError:                        # 29/02
        return d.replace(year=d.year - 1, day=28).isoformat()


# ── contexto (base de trabalho) ─────────────────────────────────────────────────────────────────────────────────

class Ctx:
    """Base de trabalho temporária com a OB (exercício ≥ 2024, data ISO) e as bases do JFN anexadas SÓ LEITURA."""

    def __init__(self, db: Path = DB, *, receita: Path | None = DB_RECEITA, tse: Path | None = DB_TSE,
                 dir_tmp: Path | None = None):
        self._tmp = tempfile.TemporaryDirectory(prefix="couto_", dir=dir_tmp)
        self.W = sqlite3.connect(f"file:{os.path.join(self._tmp.name, 'work.db')}", uri=True, timeout=120)
        self.W.execute(f"ATTACH 'file:{db}?mode=ro' AS m")
        self.tem_receita = bool(receita and Path(receita).exists())
        self.tem_tse = bool(tse and Path(tse).exists())
        if self.tem_receita:
            self.W.execute(f"ATTACH 'file:{receita}?mode=ro' AS r")
        if self.tem_tse:
            self.W.execute(f"ATTACH 'file:{tse}?mode=ro' AS t")
        # Revisão cética 13/11/2026:
        #  · desde 2021 (o "sem histórico" do D10 olhava só 2024+ e chamava de novo quem recebeu R$ 709 mi em 2021-22);
        #  · OB sem número é linha-fantasma da coleta (57 linhas de 07/08/2026 = R$ 11.469.492,62 em dobro em TODA soma);
        #  · OB devolvida pelo banco (GD / 'Erro no Pagamento') continua 'Contabilizado' — vale o efetivamente pago
        #    (mesma régua de `pericia_contabil.valor_efetivo_ob`), senão devolução + reemissão soma duas vezes.
        cols = {r[1] for r in self.W.execute("PRAGMA m.table_info(ob_orcamentaria_siafe)")}
        c_gd = "gd" if "gd" in cols else "''"
        c_env = "status_envio" if "status_envio" in cols else "''"
        self.W.execute(
            "CREATE TABLE ob AS SELECT numero_ob, ug_emitente, "
            "substr(data_emissao,7,4)||'-'||substr(data_emissao,4,2)||'-'||substr(data_emissao,1,2) AS dt, "
            f"status, nl, credor, nome_credor, processo, valor, exercicio, {c_gd} AS gd, {c_env} AS status_envio "
            "FROM m.ob_orcamentaria_siafe WHERE exercicio >= 2021 AND trim(coalesce(numero_ob,'')) <> ''")
        self._abater_devolucoes()
        for ix in ("dt", "credor", "ug_emitente"):
            self.W.execute(f"CREATE INDEX ix_ob_{ix} ON ob({ix})")
        self.W.commit()
        self.GFIM = self.W.execute("SELECT max(dt) FROM ob WHERE status='Contabilizado'").fetchone()[0]
        self.G1 = fim_mes_anterior(self.GFIM)           # janela de comparação = meses completos coletados
        self.B0, self.B1 = menos_um_ano(G0), menos_um_ano(self.G1)
        self.UG = {}
        try:
            for ug, nome in self.W.execute("SELECT ug, max(nome_ug) FROM m.despesa_execucao GROUP BY ug"):
                self.UG[str(ug).zfill(6)] = nome
        except sqlite3.OperationalError as exc:      # sem nome de UG: casos saem com '?' e o Executivo fica vazio
            logger.warning("despesa_execucao indisponível para nomes de UG: %s", exc)

    def _abater_devolucoes(self) -> None:
        from compliance_agent.pericia_contabil import situacao_devolucao, valor_efetivo_ob
        dev = [(rid, num, str(ug), v, situacao_devolucao(gd, env)) for rid, num, ug, v, gd, env in self.W.execute(
            "SELECT rowid, numero_ob, ug_emitente, valor, gd, status_envio FROM ob WHERE status='Contabilizado' "
            "AND (status_envio='Erro no Pagamento' OR gd GLOB '[0-9][0-9][0-9][0-9]GD*')")]
        self.n_devolvidas = len(dev)
        if not dev:
            return
        # só SIAFE (regra da casa: fonte de OB nunca é o espelho do TFE): erro no pagamento = 0,00; GD com outro
        # status = valor da devolução desconhecido → fora da soma (o pago da gestão é PISO nesses credores)
        self.n_devolvidas_sem_valor = sum(1 for d in dev if d[4] == "gd")
        self.W.executemany("UPDATE ob SET valor=? WHERE rowid=?",
                           [(valor_efetivo_ob(float(v or 0), sit)[0], rid) for rid, num, ug, v, sit in dev])

    def fechar(self):
        self.W.close()
        self._tmp.cleanup()

    def ugn(self, u) -> str:
        return self.UG.get(str(u).zfill(6), "?")

    def executivo(self, ug) -> bool:
        n = self.ugn(ug)
        return n != "?" and not _OUTRO_PODER.search(n)

    def obs(self, d0, d1):
        return self.W.execute("SELECT ug_emitente, credor, nome_credor, valor, dt, processo FROM ob "
                              "WHERE status='Contabilizado' AND dt BETWEEN ? AND ?", (d0, d1)).fetchall()

    def refs_ob(self, doc, limite: int = 3, d0: str = G0, d1: str | None = None) -> list[str]:
        """Prova primária: as maiores OB Contabilizadas do credor (CNPJ de 14 dígitos ou raiz de 8) desde P0, com nº,
        UG, data e valor — o leitor confere uma a uma no SIAFE. Índice montado uma vez, sob demanda."""
        if not hasattr(self, "_idx_ob"):
            idx: dict[str, list] = collections.defaultdict(list)
            for num, ug, dt, cr, v in self.W.execute("SELECT numero_ob, ug_emitente, dt, credor, valor FROM ob "
                                                     "WHERE status='Contabilizado' AND dt >= ?", (P0,)):
                d = dig(cr)
                if len(d) == 14:
                    idx[d].append((v or 0, num, ug, dt))
                    idx[d[:8]].append((v or 0, num, ug, dt))
            self._idx_ob = idx
        d = dig(doc)
        # só OB DENTRO da janela da regra — prova fora dela não prova o caso
        fim = d1 or self.GFIM
        top = sorted((x for x in self._idx_ob.get(d, ()) if d0 <= x[3] <= fim), key=lambda x: -x[0])[:limite]
        return [f"OB {num} · UG {ug} · {dt} · {brl(round(v, 2))} (SIAFE, Contabilizado)" for v, num, ug, dt in top]

    @staticmethod
    def fornecedor(credor, nome) -> bool:
        from compliance_agent.entidades_gov import eh_nao_fornecedor
        return len(dig(credor)) == 14 and not eh_nao_fornecedor(nome or "")


# ── data do ATO (DOERJ) × data de registro (TCE-RJ) ─────────────────────────────────────────────────────────────
# `contratos_tcerj.data_contratacao` é a data de REGISTRO no TCE-RJ, não a da assinatura. A revisão cética de
# 13/11/2026 achou "assinado no 3º/5º dia da gestão" para atos de fevereiro e março (ata da CEHAB assinada 24/02,
# contrato da EMOP com efeitos desde 10/03, Procon de 01/01). Quando o DOERJ publica o extrato com "DATA DA
# ASSINATURA", vale ela; ata de registro de preços e pedido de empenho não são "contrato assinado".

_RE_NAO_CONTRATO = re.compile(r"ATA\s+DE\s+REGISTRO\s+DE\s+PRE[ÇC]|SOLICITA[ÇC][ÃA]O\s+DE\s+EMPENHO|"
                              r"PEDIDO\s+DE\s+EMPENHO", re.I)
_RE_ASSIN = re.compile(r"DATA\s+D[AE]\s+ASSINATURA\s*[:\-]?\s*(\d{1,2})[/\.](\d{1,2})[/\.](\d{4})", re.I)
JANELA_DOERJ_DIAS = 120     # extrato publicado até 120 dias antes do registro no TCE-RJ é do mesmo instrumento


def assinaturas_no_texto(texto: str) -> list[tuple[str, str, bool]]:
    """[(chave SEI de 16 dígitos, data ISO da assinatura, é ata/empenho)] de um texto do DOERJ. A data é atribuída ao
    último processo SEI citado ANTES dela no mesmo texto (o extrato traz o processo e depois a assinatura)."""
    from compliance_agent.pericia_contabil import _RE_SEI, chave_sei
    t = texto or ""
    seis = [(m.start(), chave_sei(m.group(0))) for m in _RE_SEI.finditer(t)]
    out, ini_trecho = [], 0
    for m in _RE_ASSIN.finditer(t):
        antes = [k for pos, k in seis if pos < m.start() and k]
        if antes:
            try:
                d = D.date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
            except ValueError:
                d = None
            if d:
                out.append((antes[-1], d, bool(_RE_NAO_CONTRATO.search(t[ini_trecho:m.end()]))))
        ini_trecho = m.end()
    return out


def _assinaturas_doerj(c) -> dict[str, list]:
    if not hasattr(c, "_assin"):
        idx: dict[str, list] = collections.defaultdict(list)
        try:
            for (texto,) in c.W.execute("SELECT texto FROM m.publicacoes_doerj WHERE texto LIKE '%ASSINATURA%'"):
                for k, d, arp in assinaturas_no_texto(texto):
                    idx[k].append((d, arp))
        except sqlite3.OperationalError as exc:      # sem DOERJ: vale a data de registro, declarada como tal
            logger.warning("publicacoes_doerj indisponível — data do ato = data de registro no TCE-RJ: %s", exc)
        c._assin = idx
    return c._assin


def ato_do_contrato(c, sei, processo, data_registro, objeto="", status="") -> dict:
    """{data, fonte, nao_contrato, cancelado}: data da assinatura pelo DOERJ (extrato do mesmo processo publicado até
    `JANELA_DOERJ_DIAS` antes do registro), senão a data de registro no TCE-RJ — declarada."""
    from compliance_agent.pericia_contabil import chave_sei
    reg = str(data_registro or "")[:10]
    k = chave_sei(sei) or chave_sei(processo)
    out = {"data": reg, "fonte": "registro no TCE-RJ", "nao_contrato": bool(_RE_NAO_CONTRATO.search(objeto or "")),
           "cancelado": (status or "").strip() == "Cancelado"}
    if not k or not reg:
        return out
    try:
        d0 = (D.date.fromisoformat(reg) - D.timedelta(days=JANELA_DOERJ_DIAS)).isoformat()
    except ValueError:
        return out
    cand = [(d, arp) for d, arp in _assinaturas_doerj(c).get(k, ()) if d0 <= d <= reg]
    if cand:
        d, arp = max(cand)
        out.update(data=d, fonte="DOERJ (data da assinatura no extrato)", nao_contrato=out["nao_contrato"] or arp)
    return out


def contrato_da_gestao(c, sei, processo, data_registro, objeto="", status="") -> bool:
    """Contrato assinado NA gestão: não cancelado, não ata/empenho, e data do ato (DOERJ quando houver) >= G0.
    Transição decidida antes da gestão (assinatura anterior a G0) não conta como ato da gestão."""
    a = ato_do_contrato(c, sei, processo, data_registro, objeto, status)
    return not a["cancelado"] and not a["nao_contrato"] and bool(a["data"]) and a["data"] >= G0


# ── regras ──────────────────────────────────────────────────────────────────────────────────────────────────────

def d05(c: Ctx) -> dict:
    def agreg(d0, d1):
        tot, por, nome = collections.Counter(), collections.Counter(), {}
        for ug, cr, nm, v, dt, pr in c.obs(d0, d1):
            if not c.fornecedor(cr, nm) or not c.executivo(ug):
                continue
            tot[ug] += v or 0
            por[(ug, dig(cr))] += v or 0
            nome[dig(cr)] = nm
        return tot, por, nome
    tg, pg, ng = agreg(G0, c.G1)
    tb, pb, _ = agreg(c.B0, c.B1)
    casos = []
    for (ug, cr), v in pg.items():
        if tg[ug] < 10e6 or v < 5e6:
            continue
        sh = v / tg[ug]
        if sh < 0.30:
            continue
        shb = pb.get((ug, cr), 0) / tb[ug] if tb.get(ug) else None
        casos.append(dict(ug=ug, orgao=c.ugn(ug), cnpj=cr, credor=ng[cr], pago_ob=round(v, 2), total_ug=round(tg[ug], 2),
                          share=round(sh, 4), share_2025=None if shb is None else round(shb, 4),
                          pago_2025=round(pb.get((ug, cr), 0), 2),
                          tipo="NOVA" if (shb is None or shb < 0.10) else ("SUBIU" if sh - shb >= 0.15 else "PERSISTENTE")))
    casos.sort(key=lambda x: -x["pago_ob"])
    soma = round(sum(x["pago_ob"] for x in casos), 2)
    return dict(criterio=f"credor PJ fornecedor com >=30% do pago (OB contabilizada) da UG em {G0}→{c.G1}; UG>=R$10 mi; "
                         f"credor>=R$5 mi; comparado a {c.B0}→{c.B1}",
                n=len(casos), n_nova=sum(x["tipo"] == "NOVA" for x in casos),
                n_subiu=sum(x["tipo"] == "SUBIU" for x in casos), soma=soma, casos=casos,
                resumo=f"Concentração ≥30% por órgão: {len(casos)} ({sum(x['tipo'] == 'NOVA' for x in casos)} novas, "
                       f"{sum(x['tipo'] == 'SUBIU' for x in casos)} em alta)", valor_ob=soma)


_EMAIL_GENERICO = re.compile(r"@(gmail|hotmail|outlook|yahoo|uol|bol|terra|ig|live|icloud|globo|msn)\.", re.I)
MAX_RAIZES_NO_CONTATO = 15     # acima disso o e-mail é de contador/consultoria (medido: um e-mail em 44 raízes)


def rotulo_estreia(c, cnpj: str, nome: str, hist: set) -> tuple[str, str | None]:
    """('consorcio' | 'grupo_com_historico' | 'estreia', base). Consórcio: natureza 215-1 na Receita ou o nome.
    Grupo: outro CNPJ (raiz diferente) COM histórico de OB no mesmo e-mail de contato — não genérico e usado por no
    máximo `MAX_RAIZES_NO_CONTATO` raízes. É indício de grupo ou sucessão, não prova societária. Mesmo ENDEREÇO de
    credor antigo sozinho não tira ninguém da estreia (sala comercial dividida): só vai anotado na base."""
    raiz = dig(cnpj)[:8]
    if re.match(r"CONS[OÓ]RCIO\b", (nome or "").strip(), re.I):
        return "consorcio", "nome do credor"
    if not getattr(c, "tem_receita", False):
        return "estreia", None
    nota = None
    try:
        nat = c.W.execute("SELECT natureza_cod FROM r.empresas WHERE cnpj_basico=?", (raiz,)).fetchone()
        if nat and str(nat[0]) == "2151":
            return "consorcio", "natureza jurídica 215-1 (Receita)"
        for end, mail in c.W.execute("SELECT endereco_norm, correio_eletronico FROM r.estabelecimentos "
                                     "WHERE cnpj_basico=?", (raiz,)).fetchall():
            if mail and "@" in mail and not _EMAIL_GENERICO.search(mail):
                outras = [b for (b,) in c.W.execute("SELECT DISTINCT cnpj_basico FROM r.estabelecimentos "
                                                    "WHERE correio_eletronico=? AND cnpj_basico<>?", (mail, raiz))]
                if len(outras) <= MAX_RAIZES_NO_CONTATO:
                    for b in outras:
                        if b in hist:
                            return "grupo_com_historico", (f"mesmo e-mail de contato da raiz {b} "
                                                           "(credor com OB desde 2021)")
            if end and not nota:
                outras = [b for (b,) in c.W.execute("SELECT DISTINCT cnpj_basico FROM r.estabelecimentos "
                                                    "WHERE endereco_norm=? AND cnpj_basico<>?", (end, raiz))]
                if len(outras) <= MAX_RAIZES_NO_CONTATO:
                    for b in outras:
                        if b in hist:
                            nota = f"mesmo endereço da raiz {b}, credor com OB desde 2021 — conferir relação"
                            break
    except sqlite3.OperationalError as exc:
        logger.warning("Receita indisponível para rotular estreia do D10: %s", exc)
    return "estreia", nota


def d10(c: Ctx) -> dict:
    # histórico pela RAIZ do CNPJ (8 dígitos) desde 2021: filial de fornecedora antiga não é "credor novo"
    # (revisão cética 13/11/2026 — 63,3% do valor do D10 era filial, grupo ou credor de 2021-22)
    hist = {dig(x)[:8] for (x,) in c.W.execute("SELECT DISTINCT credor FROM ob WHERE status='Contabilizado' AND dt < ? "
                                                "AND valor > 0", (G0,)) if len(dig(x)) == 14}
    agg = collections.defaultdict(lambda: [0.0, 0, None, None, collections.Counter(), set()])
    for ug, cr, nm, v, dt, pr in c.obs(G0, c.GFIM):
        if not c.fornecedor(cr, nm) or dig(cr)[:8] in hist or not c.executivo(ug):
            continue
        a = agg[dig(cr)]
        a[0] += v or 0
        a[1] += 1
        a[2] = nm
        a[3] = min(a[3] or dt, dt)
        a[4][ug] += v or 0
        a[5].add(pr)
    casos = []
    for cr, (v, n, nm, p, ugs, prs) in agg.items():
        if v < 5e6:
            continue
        ug = ugs.most_common(1)[0][0]
        rot, base_rot = rotulo_estreia(c, cr, nm, hist)
        casos.append(dict(cnpj=cr, credor=nm, pago_ob=round(v, 2), n_ob=n, primeira_ob=p, ug=ug, orgao=c.ugn(ug),
                          n_ugs=len(ugs), processos=sorted(x for x in prs if x)[:6], rotulo=rot, base_rotulo=base_rot))
    casos.sort(key=lambda x: -x["pago_ob"])
    # Verificação de 13/11/2026: consórcio tem CNPJ que nasce com o contrato; SPE/subsidiária no endereço ou e-mail
    # de credor antigo é o mesmo grupo. Nenhum dos dois é "credor sem histórico" — contados à parte, fora da soma.
    a_parte = [x for x in casos if x["rotulo"] != "estreia"]
    estreia = [x for x in casos if x["rotulo"] == "estreia"]
    soma = round(sum(x["pago_ob"] for x in estreia), 2)
    v_parte = round(sum(x["pago_ob"] for x in a_parte), 2)
    n_cons = sum(x["rotulo"] == "consorcio" for x in a_parte)
    return dict(criterio=f"CNPJ fornecedor cuja RAIZ (8 dígitos — matriz e filiais) não tem NENHUMA OB contabilizada de "
                         f"01/01/2021 até a véspera da gestão e que recebeu >=R$5 mi em OB de {G0} a {c.GFIM}; consórcio "
                         "(CNPJ criado para o contrato) e CNPJ no mesmo endereço ou e-mail de credor com histórico "
                         "(grupo/sucessão provável) ficam à parte, fora da soma",
                n=len(estreia), soma=soma, n_universo_novos=len(agg), casos=casos, valor_ob=soma,
                n_consorcio=n_cons, n_grupo_com_historico=len(a_parte) - n_cons, soma_a_parte=v_parte,
                resumo=f"Credor sem histórico ≥ R$ 5 mi: {len(estreia)} ({brl(soma)}); à parte, {n_cons} consórcio(s) e "
                       f"{len(a_parte) - n_cons} de grupo com histórico ({brl(v_parte)}) — não são estreia")


def d03(c: Ctx) -> dict:
    from compliance_agent.entidades_gov import eh_nao_fornecedor
    if not c.tem_receita:
        return dict(indisponivel="receita_estab.db ausente", n=None, casos=[])
    prim = {}
    for cr, nm, p, v in c.W.execute("SELECT credor, max(nome_credor), min(dt), "
                                    "sum(CASE WHEN dt>=? THEN valor ELSE 0 END) FROM ob WHERE status='Contabilizado' "
                                    "GROUP BY credor", (G0,)):
        d = dig(cr)
        if len(d) == 14 and p >= G0 and v >= 500e3 and not eh_nao_fornecedor(nm or ""):
            prim[d] = (nm, p, v)
    casos = []
    for d, (nm, p, v) in prim.items():
        r = c.W.execute("SELECT data_inicio_atividade, situacao_cadastral FROM r.estabelecimentos WHERE cnpj=?",
                        (d,)).fetchone()
        e = c.W.execute("SELECT capital_social, porte_txt FROM m.empresas_cadastro WHERE cnpj_basico=?",
                        (d[:8],)).fetchone()
        if not r or not r[0]:
            continue
        ini = str(r[0])
        ini = f"{ini[:4]}-{ini[4:6]}-{ini[6:8]}" if len(ini) == 8 and "-" not in ini else ini[:10]
        try:
            dias = (D.date.fromisoformat(p) - D.date.fromisoformat(ini)).days
        except ValueError:
            continue
        cap = e[0] if e else None
        recente = dias <= 365
        cap_baixo = cap is not None and cap > 0 and v / cap >= 20 and v >= 1e6
        if recente or cap_baixo:
            casos.append(dict(cnpj=d, credor=nm, abertura=ini, primeira_ob=p, dias_ate_1a_ob=dias, pago_ob=round(v, 2),
                              capital_social=cap, porte=e[1] if e else None,
                              razao_pago_capital=round(v / cap, 1) if cap else None, situacao=r[1],
                              sinal=("RECENTE" if recente else "") + ("+CAPITAL" if cap_baixo else "")))
    casos.sort(key=lambda x: -x["pago_ob"])
    return dict(criterio="1a OB da história (desde 2024) na gestão, >=R$500 mil; RECENTE = aberta <=365 dias antes da 1a OB; "
                         "CAPITAL = pago >=20x capital social e >=R$1 mi",
                n_universo=len(prim), n=len(casos), casos=casos,
                resumo=f"Empresa recém-aberta ou capital incompatível: {len(casos)} de {len(prim)} estreantes")


def d04(c: Ctx) -> dict:
    porte = {b: (p, cap) for b, p, cap in c.W.execute("SELECT cnpj_basico, porte_txt, capital_social FROM m.empresas_cadastro")}
    a26 = collections.defaultdict(lambda: [0.0, 0.0, "", collections.Counter()])
    ano = c.GFIM[:4]
    for ug, cr, nm, v, dt, pr in c.obs(f"{ano}-01-01", c.GFIM):
        d = dig(cr)
        if len(d) != 14:
            continue
        p = porte.get(d[:8])
        if not p or p[0] not in TETO_PORTE:
            continue
        a = a26[d[:8]]
        a[0] += v or 0
        a[2] = nm
        if dt >= G0:
            a[1] += v or 0
            a[3][ug] += v or 0
    casos = []
    for b, (tot, g, nm, ugs) in a26.items():
        t = TETO_PORTE[porte[b][0]]
        if tot > t and g > 0:
            ug = ugs.most_common(1)[0][0] if ugs else None
            casos.append(dict(cnpj_basico=b, credor=nm, porte=porte[b][0], teto=t, pago_ano=round(tot, 2),
                              pago_gestao=round(g, 2), razao_teto=round(tot / t, 1), ug=ug, orgao=c.ugn(ug) if ug else None))
    casos.sort(key=lambda x: -x["pago_ano"])
    ct, vistos = [], set()
    for proc, data, uni, val, cnpj, forn, sei, obj, st in c.W.execute(
            "SELECT processo, data_contratacao, unidade, valor_contrato, cnpj, fornecedor, sei_norm, objeto, status "
            "FROM m.contratos_tcerj WHERE substr(data_contratacao,1,10)>=?", (G0,)):
        d = dig(cnpj)
        p = porte.get(d[:8]) if len(d) >= 8 else None
        if not (p and p[0] in TETO_PORTE and val and val > TETO_PORTE[p[0]]):
            continue
        if not contrato_da_gestao(c, sei, proc, data, obj, st) or (d, val, uni) in vistos:
            continue                    # ata/empenho/cancelado, assinado antes da gestão, ou o mesmo registro repetido
        vistos.add((d, val, uni))
        ato = ato_do_contrato(c, sei, proc, data, obj, st)
        ct.append(dict(processo=proc, data=ato["data"], fonte_data=ato["fonte"], unidade=uni, valor_contrato=val, cnpj=d,
                       fornecedor=forn, porte=p[0], razao_teto=round(val / TETO_PORTE[p[0]], 1)))
    ct.sort(key=lambda x: -x["razao_teto"])
    sg = round(sum(x["pago_gestao"] for x in casos), 2)
    return dict(criterio=f"porte ME/EPP no cadastro RFB; OB contabilizada {ano} (ano-calendário) > teto LC 123 art.3º; recebeu "
                         "algo na gestão. Contratos: espelho TCE-RJ assinados na gestão (data do DOERJ quando houver; sem ata de registro "
                         "de preços, pedido de empenho, cancelado nem registro repetido) e valor > teto",
                n=len(casos), soma_ano=round(sum(x["pago_ano"] for x in casos), 2), soma_gestao=sg, n_contratos=len(ct),
                soma_contratos=round(sum(x["valor_contrato"] for x in ct), 2), casos=casos, contratos=ct, valor_ob=sg,
                resumo=f"ME/EPP acima do teto: {len(casos)} credores ({brl(sg)} em OB na gestão) e {len(ct)} contratos "
                       f"({brl(round(sum(x['valor_contrato'] for x in ct), 2))})")


def d01_02_17(c: Ctx) -> dict:
    from compliance_agent.fracionamento_emergencia import agrupar_emergencias, eh_emergencial
    diretas = collections.defaultdict(list)
    for sei, ano, val, obj, af, enq, uni, forn in c.W.execute(
            "SELECT sei_norm, ano_processo, valor, objeto, afastamento, enquadramento_legal, unidade, fornecedor "
            "FROM m.compras_diretas_tcerj"):
        diretas[sei].append((ano, val, obj, af, enq, uni, forn))
    # o espelho de compras diretas tem data de ingestão: a janela termina no último mês completo antes dela
    # (contrato assinado depois disso pareceria "não direto" só porque a dispensa ainda não foi ingerida)
    ult = (c.W.execute("SELECT max(substr(ingerido_em,1,10)) FROM m.compras_diretas_tcerj").fetchone()[0] or c.G1)[:10]
    fim = min(fim_mes_anterior(ult), c.G1)
    fim_b = menos_um_ano(fim)

    def janela(d0, d1):
        t = collections.defaultdict(lambda: [0, 0.0, 0, 0.0])
        for sei, val, uni, proc, dc, obj, st in c.W.execute(
                "SELECT sei_norm, valor_contrato, unidade, processo, data_contratacao, objeto, status FROM m.contratos_tcerj "
                "WHERE substr(data_contratacao,1,10) BETWEEN ? AND ?", (d0, d1)):
            ato = ato_do_contrato(c, sei, proc, dc, obj, st)
            if ato["cancelado"] or ato["nao_contrato"] or not (d0 <= ato["data"] <= d1):
                continue                # ata/empenho/cancelado, ou assinado fora da janela (data do DOERJ)
            a = t[uni]
            a[0] += 1
            a[1] += val or 0
            if sei in diretas:
                a[2] += 1
                a[3] += val or 0
        return t
    tg, tb = janela(G0, fim), janela(c.B0, fim_b)
    tab = []
    for uni, (n, v, nd, vd) in tg.items():
        nb, vb, ndb, vdb = tb.get(uni, [0, 0, 0, 0])
        sh = vd / v if v else 0
        shb = vdb / vb if vb else None
        tab.append(dict(unidade=uni, n=n, valor=round(v, 2), n_direta=nd, valor_direta=round(vd, 2), share_direta=round(sh, 4),
                        n_2025=nb, valor_2025=round(vb, 2), valor_direta_2025=round(vdb, 2),
                        share_direta_2025=None if shb is None else round(shb, 4)))

    def tot(t, i):
        return sum(x[i] for x in t.values())
    flag = [x for x in tab if x["valor_direta"] >= 10e6 and x["share_direta"] >= 0.5 and
            (x["share_direta_2025"] is None or x["share_direta"] - x["share_direta_2025"] >= 0.2)]
    flag.sort(key=lambda x: -x["valor_direta"])
    ag = tot(tg, 3) / tot(tg, 1) if tot(tg, 1) else None
    ab = tot(tb, 3) / tot(tb, 1) if tot(tb, 1) else None
    r01 = dict(criterio=f"contratos do espelho TCE-RJ assinados {G0}→{fim}; \"direta\" = processo no espelho de compras "
                        "diretas do TCE-RJ. Sinal: unidade com >=R$10 mi diretos, >=50% do valor e +20 p.p. sobre o ano anterior",
               geral=dict(n=tot(tg, 0), valor=round(tot(tg, 1), 2), n_direta=tot(tg, 2), valor_direta=round(tot(tg, 3), 2)),
               geral_ano_anterior=dict(n=tot(tb, 0), valor=round(tot(tb, 1), 2), n_direta=tot(tb, 2),
                                       valor_direta=round(tot(tb, 3), 2)),
               n=len(flag), casos=flag, tabela=sorted(tab, key=lambda x: -x["valor_direta"])[:40],
               resumo=f"Contratação direta por unidade × ano anterior: agregado {pct(ag)} × {pct(ab)}; "
                      f"{len(flag)} unidade(s) com salto")
    antes = collections.defaultdict(set)
    for uni, forn, cnpj in c.W.execute("SELECT unidade, fornecedor, cnpj FROM m.contratos_tcerj "
                                       "WHERE substr(data_contratacao,1,10) < ?", (G0,)):
        antes[uni].add(dig(cnpj) or norm_nome(forn))
    todos = []
    for sei, data, val, uni, forn, cnpj, obj, proc, st in c.W.execute(
            "SELECT sei_norm, data_contratacao, valor_contrato, unidade, fornecedor, cnpj, objeto, processo, status "
            "FROM m.contratos_tcerj WHERE substr(data_contratacao,1,10) >= ?", (G0,)):
        if sei not in diretas or not any(eh_emergencial(o, e) for (_, _, o, _, e, _, _) in diretas[sei]):
            continue
        if not contrato_da_gestao(c, sei, proc, data, obj, st):
            continue                    # transição decidida antes da gestão não é ato da gestão
        todos.append(dict(processo=proc, data=ato_do_contrato(c, sei, proc, data, obj, st)["data"], unidade=uni,
                          fornecedor=forn, cnpj=dig(cnpj),
                          valor_contrato=val, objeto=(obj or "")[:160],
                          incumbente=(dig(cnpj) or norm_nome(forn)) in antes[uni]))
    todos.sort(key=lambda x: -(x["valor_contrato"] or 0))
    inc = [x for x in todos if x["incumbente"]]
    vinc = round(sum(x["valor_contrato"] or 0 for x in inc), 2)
    r02 = dict(criterio="contrato do espelho TCE-RJ assinado na gestão cujo processo está no espelho de compras diretas com "
                        "enquadramento emergencial ou objeto \"emergenc\"; incumbente = mesmo CNPJ já tinha contrato na MESMA "
                        "unidade antes da gestão",
               n_emergenciais=len(todos), n=len(inc), valor_incumbente=vinc, casos=inc, todos=todos,
               resumo=f"Emergencial ao incumbente: {len(inc)} de {len(todos)} emergenciais ({brl(vinc)} em contrato)")
    ano = c.GFIM[:4]
    linhas = [(uni, a, forn, val, obj, enq) for sei, L in diretas.items() for (a, val, obj, af, enq, uni, forn) in L
              if str(a) == ano]
    grupos = agrupar_emergencias(linhas, minimo=3)
    v17 = round(sum(float(g.get("total") or 0) for g in grupos), 2)
    r17 = dict(criterio=f"régua fracionamento_emergencia.agrupar_emergencias, processos de {ano} no espelho de compras "
                        f"diretas (ingerido até {ult}), >=3 emergências na mesma unidade",
               n=len(grupos), casos=grupos,
               resumo=f"Emergência recorrente {ano}: {len(grupos)} grupos" + (f" ({brl(v17)} em contrato)" if v17 else ""))
    return {"D01": r01, "D02": r02, "D17": r17}


def d08_09(c: Ctx) -> dict:
    g0 = D.date.fromisoformat(G0)
    g15 = (g0 + D.timedelta(days=14)).isoformat()

    def ctr(d0, d1):
        # registro no TCE-RJ até 120 dias depois da janela pode ser de contrato ASSINADO nela; vale a data do DOERJ
        d1_reg = (D.date.fromisoformat(d1) + D.timedelta(days=JANELA_DOERJ_DIAS)).isoformat()
        out = []
        for proc, dc, uni, forn, cnpj, val, obj, sei, st in c.W.execute(
                "SELECT processo, substr(data_contratacao,1,10), unidade, fornecedor, cnpj, valor_contrato, objeto, sei_norm, "
                "status FROM m.contratos_tcerj WHERE substr(data_contratacao,1,10) BETWEEN ? AND ? "
                "ORDER BY valor_contrato DESC", (d0, d1_reg)):
            ato = ato_do_contrato(c, sei, proc, dc, obj, st)
            if ato["cancelado"] or ato["nao_contrato"] or not (d0 <= ato["data"] <= d1):
                continue
            if ato["fonte"].startswith("registro") and dc > d1:
                continue                # sem DOERJ, só o registro dentro da janela conta
            out.append((proc, ato["data"], uni, forn, cnpj, val, obj))
        return out
    g, b = ctr(G0, g15), ctr(menos_um_ano(G0), menos_um_ano(g15))
    dia = {d: (n, v) for d, n, v in c.W.execute("SELECT dt, count(*), sum(valor) FROM ob WHERE status='Contabilizado' "
                                                 "AND dt BETWEEN ? AND ? GROUP BY dt", (P0, c.GFIM))}
    vals = [v for d, (n, v) in dia.items() if d < G0]
    med = statistics.median(vals) if vals else 0
    picos = [dict(dia=d, n_ob=n, valor=round(v, 2), x_mediana=round(v / med, 1))
             for d, (n, v) in sorted(dia.items()) if med and v >= 4 * med and d >= G0]
    vg = round(sum(x[5] or 0 for x in g), 2)
    r08 = dict(criterio=f"contratos assinados nos 15 primeiros dias ({G0}→{g15}; data da assinatura no DOERJ quando houver, "
                        "senão a de registro no TCE-RJ; sem ata de registro de preços, empenho ou cancelado) × mesmo "
                        f"intervalo do ano anterior; dias de OB "
                        ">= 4x a mediana diária pré-gestão",
               n=len(g), valor=vg, n_ano_anterior=len(b), valor_ano_anterior=round(sum(x[5] or 0 for x in b), 2),
               mediana_dia_pre=round(med, 2), n_picos=len(picos), picos=picos,
               casos=[dict(processo=x[0], data=x[1], unidade=x[2], fornecedor=x[3], cnpj=dig(x[4]), valor_contrato=x[5],
                           objeto=(x[6] or "")[:150]) for x in g[:25]],
               resumo=f"Primeiros 15 dias: {len(g)} contratos ({brl(vg)}) × {len(b)} no ano anterior; {len(picos)} picos de OB")
    base, ult, nome, ugc = collections.Counter(), collections.Counter(), {}, {}
    ini_ult = (D.date.fromisoformat(P1) - D.timedelta(days=6)).isoformat()
    for ug, cr, nm, v, dt, pr in c.obs(P0, P1):
        if not c.fornecedor(cr, nm):
            continue
        d = dig(cr)
        nome[d], ugc[d] = nm, ug
        if dt >= ini_ult:
            ult[d] += v or 0
        else:
            base[d] += v or 0
    semanas = ((D.date.fromisoformat(ini_ult) - D.date.fromisoformat(P0)).days) / 7
    casos = []
    for d, v in ult.items():
        mw = base[d] / semanas
        if v >= 3e6 and v >= 5 * max(mw, 1):
            casos.append(dict(cnpj=d, credor=nome[d], ug=ugc[d], orgao=c.ugn(ugc[d]), pago_semana=round(v, 2),
                              media_semanal_antes=round(mw, 2), x=round(v / mw, 1) if mw else None))
    casos.sort(key=lambda x: -x["pago_semana"])
    soma = round(sum(x["pago_semana"] for x in casos), 2)
    r09 = dict(criterio=f"OB contabilizada a fornecedor PJ {ini_ult}→{P1} (última semana do governador anterior): credor com "
                        ">=R$3 mi na semana e >=5x a média semanal anterior",
               total_semana=round(sum(ult.values()), 2), n=len(casos), casos=casos, valor_ob=soma,
               resumo=f"Última semana do governador anterior: {len(casos)} credores com pico ({brl(soma)})")
    return {"D08": r08, "D09": r09}


_STOP = set("ESTADO SECRETARIA FUNDO FUNDACAO ESPECIAL GERAL CENTRAL ADMINISTRACAO JANEIRO INSTITUTO DEPARTAMENTO "
            "ESTADUAL".split())


def _pal(t) -> set:
    return {w for w in re.findall(r"[A-Z]{5,}", nn(t)) if w not in _STOP}


def mascarar_doc_socio(doc) -> str | None:
    d = dig(doc)
    return f"***{d[3:6]}***" if d else None


def cpf_confere(doc_socio, cpf_folha, fonte: str | None) -> bool | None:
    """Os dígitos VISÍVEIS do CPF do sócio (QSA: `***123456**` = dígitos 4–9) conferem com os da folha?

    A folha grava `XX123456XXX`, mas ONDE esses 6 dígitos caem no CPF varia por fonte (medido em 13/11/2026 —
    `nomeados_candidatos.DESLOC_CPF_FONTE`: Executivo/GESPERJ dígitos 4–9, Defensoria 3–8). Compara-se só a
    sobreposição real das duas janelas. None = não testável (fonte sem deslocamento aferido, sem CPF, formato
    estranho) — e não testável NÃO vira confirmado."""
    from compliance_agent.nomeados_candidatos import DESLOC_CPF_FONTE, fragmento_folha
    q = str(doc_socio or "").strip()
    m = re.fullmatch(r"\*{3}(\d{6})\*{2}", q)
    frag = fragmento_folha(str(cpf_folha or ""))
    desl = DESLOC_CPF_FONTE.get(fonte or "")
    if not m or not frag or desl is None:
        return None
    qsa = {3 + k: ch for k, ch in enumerate(m.group(1))}
    fol = {desl + k: ch for k, ch in enumerate(frag)}
    comuns = sorted(set(qsa) & set(fol))
    if len(comuns) < 5:
        return None
    return all(qsa[k] == fol[k] for k in comuns)


def _cpfs_folha(c: Ctx, nomes: set[str]) -> dict[str, set]:
    """nome normalizado (régua de `agente_publico_reverso.norm`) → {(fonte, cpf mascarado)} da folha do Estado."""
    from tools.agente_publico_reverso import norm
    out: dict[str, set] = collections.defaultdict(set)
    for nome, cpf, fonte in c.W.execute("SELECT DISTINCT nome, cpf, fonte FROM m.registros_folha WHERE cpf IS NOT NULL"):
        n = norm(nome)
        if n in nomes:
            out[n].add((fonte, cpf))
    return out


_RE_UEX = re.compile(r"^(A ?A ?E?\b|ASSOCIACAO DE APOIO|CAIXA ESCOLAR|CONSELHO ESCOLAR|CIEP\b|C ?E\b|E ?E ?E ?S?\b|"
                     r"COLEGIO ESTADUAL|ESCOLA ESTADUAL|GINASIO PUBLICO)")


def unidade_executora_escolar(nome_credor, nome_ug) -> bool:
    """Associação de Apoio à Escola / caixa escolar paga pela Educação: unidade executora, não fornecedor."""
    n = re.sub(r"[^A-Z0-9 ]", " ", nn(nome_credor))
    return "EDUCACAO" in nn(nome_ug) and bool(_RE_UEX.match(re.sub(r"\s+", " ", n).strip()))


def d13(c: Ctx) -> dict:
    """Sócio de credor que é agente público. Revisão cética 13/11/2026: casar só pelo nome gera homônimo — agora o
    sócio só conta se os dígitos VISÍVEIS do CPF do QSA conferem com os da folha (posição por fonte); ALERJ e folha
    sem CPF ficam "não testável" (contados à parte, fora da soma); pagador só do Executivo."""
    ap = collections.defaultdict(list)
    rows = c.W.execute("SELECT nome_norm, nome_socio, doc_socio, cnpj_basico, origem, cargo, vinculo, orgao, comissionado "
                       "FROM m.agente_publico_societario WHERE origem IN ('folha_estado','alerj')").fetchall()
    folha = _cpfs_folha(c, {r[0] for r in rows if r[4] == "folha_estado"})
    nao_testavel, homonimo = set(), 0
    for nnm, ns, doc, cb, orig, cargo, vinc, org, com in rows:
        vered = [cpf_confere(doc, cpf, fonte) for fonte, cpf in folha.get(nnm, ())] if orig == "folha_estado" else []
        if not any(v is True for v in vered):
            if any(v is False for v in vered) and not any(v is None for v in vered):
                homonimo += 1                          # os dígitos provam que é OUTRA pessoa
            else:
                nao_testavel.add(str(cb).zfill(8))
            continue
        ap[str(cb).zfill(8)].append(dict(socio=ns, doc_mascarado=mascarar_doc_socio(doc), origem=orig, cargo=cargo,
                                         vinculo=vinc, orgao_agente=org, comissionado=com,
                                         verificacao="dígitos visíveis do CPF conferem (QSA × folha)"))
    agg = collections.defaultdict(lambda: [0.0, "", collections.Counter()])
    for ug, cr, nm, v, dt, pr in c.obs(G0, c.GFIM):
        d = dig(cr)
        if len(d) == 14 and d[:8] in ap and c.executivo(ug):
            a = agg[d[:8]]
            a[0] += v or 0
            a[1] = nm
            a[2][ug] += v or 0
    casos, escolares = [], []
    for b, (v, nm, ugs) in agg.items():
        if v < 100e3:
            continue
        ug = ugs.most_common(1)[0][0]
        if unidade_executora_escolar(nm, c.ugn(ug)):
            # Associação de Apoio à Escola: o "sócio" é o diretor/professor da própria escola, por desenho —
            # não é sócio de fornecedor (verificação 13/11/2026: 225 dos 246 "no mesmo órgão" eram isso)
            escolares.append(v)
            continue
        # mesmo órgão = o nome do órgão do agente é IGUAL ao de uma UG que pagou (antes: uma palavra em comum —
        # "EDUCACAO", "SAUDE" — bastava)
        casos.append(dict(cnpj_basico=b, credor=nm, pago_ob=round(v, 2), ug=ug, orgao=c.ugn(ug), socios_agentes=ap[b][:5],
                          mesmo_orgao=any(nn(s["orgao_agente"]) == nn(c.ugn(u)) for s in ap[b] for u in ugs)))
    casos.sort(key=lambda x: -x["pago_ob"])
    soma = round(sum(x["pago_ob"] for x in casos), 2)
    nmo = sum(x["mesmo_orgao"] for x in casos)
    ncom = sum(any(s["comissionado"] for s in x["socios_agentes"]) for x in casos)
    return dict(criterio="CNPJ com sócio que é agente público da folha do Estado — nome E dígitos visíveis do CPF conferem "
                         "(QSA × folha, posição por fonte) — e recebeu >=R$100 mil em OB do Executivo na gestão; homônimo "
                         "provado pelos dígitos excluído; ALERJ/folha sem CPF = não testável, fora da soma",
                n=len(casos), soma=soma, n_mesmo_orgao=nmo, n_comissionado=ncom, casos=casos, valor_ob=soma,
                n_homonimos_descartados=homonimo, n_cnpj_nao_testavel=len(nao_testavel - set(ap)),
                n_unidade_executora_escolar=len(escolares), soma_unidade_executora_escolar=round(sum(escolares), 2),
                resumo=f"Sócio agente público (CPF confere): {len(casos)} credores ({brl(soma)}), {nmo} com agente do "
                       f"mesmo órgão que paga, {ncom} comissionados; à parte, {len(escolares)} associações de apoio à "
                       f"escola ({brl(round(sum(escolares), 2))}) — dirigente é servidor da escola por desenho")


def contratos_na_vigencia(c, cnpj: str, inicio: str, fim: str | None) -> list[str]:
    """Contratos do espelho do TCE-RJ com o CNPJ cujo ATO (assinatura no DOERJ, senão registro) caiu na vigência da
    sanção — não cancelados, não ata/pedido de empenho."""
    if not hasattr(c, "_contr_cnpj"):
        idx: dict[str, list] = collections.defaultdict(list)
        try:
            cols = {r[1] for r in c.W.execute("PRAGMA m.table_info(contratos_tcerj)")}
            c_un = "unidade" if "unidade" in cols else "''"
            for sei, proc, dreg, obj, st, cn, un in c.W.execute(
                    f"SELECT sei_norm, processo, data_contratacao, objeto, status, cnpj, {c_un} FROM m.contratos_tcerj"):
                idx[dig(cn)].append((sei, proc, dreg, obj, st, un))
        except sqlite3.OperationalError as exc:
            logger.warning("contratos_tcerj indisponível para o D14: %s", exc)
        c._contr_cnpj = idx
    out = []
    for sei, proc, dreg, obj, st, un in c._contr_cnpj.get(dig(cnpj), ()):
        a = ato_do_contrato(c, sei, proc, dreg, obj or "", st or "")
        if a["cancelado"] or a["nao_contrato"] or not a["data"]:
            continue
        if a["data"] >= inicio and (not fim or a["data"] <= fim):
            out.append(f"{proc or sei} · {(un or '').strip()[:50]} · ato em {a['data']} ({a['fonte']})")
    return sorted(out)


def d14(c: Ctx) -> dict:
    """OB na gestão a CNPJ com sanção que, NA DATA DA OB, estava vigente E alcançava o Estado do RJ.

    Revisão cética 13/11/2026: 56% do valor era sanção de outro ente sem alcance no RJ (Enge Prat-like: suspensão
    "No órgão sancionador" do IFRJ), e "com prazo determinado" sem data final era lido como vigente. Agora a régua é
    a de `sancao_abrangencia` (fundamentação antes da categoria; abrangência e esfera declaradas no CEIS); o grau sai
    da abrangência apurada, não da palavra "inidoneidade". Vigente sem alcance é contado à parte (não é vedação)."""
    from compliance_agent.sancao_abrangencia import CAMPOS_CEIS, veda_ente, vigente_em
    cols = {r[1] for r in c.W.execute("PRAGMA m.table_info(sancoes_federais)")}
    c_uf = "uf" if "uf" in cols else "NULL AS uf"
    campos = ", ".join(x if x in cols else f"NULL AS {x}" for x in CAMPOS_CEIS)
    sanc = collections.defaultdict(list)
    for r in c.W.execute(
            f"SELECT cadastro, cpf_cnpj, nome, categoria, data_inicio, data_fim, orgao, fundamentacao, {c_uf}, "
            f"{campos} FROM m.sancoes_federais"):
        s = dict(zip(("cadastro", "cpf_cnpj", "nome", "categoria", "data_inicio", "data_fim", "orgao", "fundamentacao",
                      "uf", "abrangencia", "esfera_sancionador", "data_publicacao"), r))
        d = dig(s["cpf_cnpj"])
        if len(d) == 14 and s["data_inicio"] and _RESTRINGE.search(s["categoria"] or ""):
            s["data_inicio"] = str(s["data_inicio"])[:10]
            s["data_fim"] = str(s["data_fim"])[:10] if s["data_fim"] else None
            sanc[d].append(s)
    agg, sem_alcance = {}, collections.defaultdict(lambda: [0.0, 0, ""])
    for ug, cr, nm, v, dt, pr in c.obs(G0, c.GFIM):
        d = dig(cr)
        vig = [s for s in sanc.get(d, []) if vigente_em(s, dt)]
        if not vig:
            continue
        alc = [(s, veda_ente(s, "estadual", "RJ")) for s in vig]
        alc = [(s, va) for s, va in alc if va["veda"]]
        if not alc:
            x = sem_alcance[d]
            x[0] += v or 0
            x[1] += 1
            x[2] = nm
            continue
        s, va = max(alc, key=lambda t: {"total": 2}.get(t[1]["abrangencia"], 1))
        a = agg.setdefault((d, s["categoria"], s["data_inicio"]), dict(
            cnpj=d, credor=nm, cadastro=s["cadastro"], categoria=s["categoria"], inicio=s["data_inicio"], fim=s["data_fim"],
            orgao_sancionador=s["orgao"], fundamentacao=(s["fundamentacao"] or "")[:160], abrangencia=va["abrangencia"],
            abrangencia_ceis=s.get("abrangencia"), alcance=va["motivo"], pago_ob=0.0, n_ob=0, primeira=dt,
            ugs=collections.Counter()))
        a["pago_ob"] += v or 0
        a["n_ob"] += 1
        a["primeira"] = min(a["primeira"], dt)
        a["ugs"][ug] += v or 0
    casos = []
    for a in agg.values():
        ug = a.pop("ugs").most_common(1)[0][0]
        a.update(ug=ug, orgao=c.ugn(ug), pago_ob=round(a["pago_ob"], 2))
        a["grau_sancao"] = "inidoneidade" if a["abrangencia"] == "total" else "impedimento"
        a["sancao_iniciou_na_gestao"] = a["inicio"] >= G0
        # O que a sanção veda é CONTRATAR (efeito ex nunc: não rescinde contrato em curso). Pagamento na vigência
        # é sinal; contrato NOVO na vigência é o indício forte. Sem contrato no espelho = não localizado, não zero.
        novos = contratos_na_vigencia(c, a["cnpj"], a["inicio"], a["fim"])
        a["contratos_na_vigencia"] = novos[:3]
        a["n_contratos_na_vigencia"] = len(novos)
        casos.append(a)
    casos.sort(key=lambda x: -x["pago_ob"])
    exe = [x for x in casos if not _OUT_CASO.search(x["orgao"] or "")]
    soma = round(sum(x["pago_ob"] for x in exe), 2)
    v_sem = round(sum(x[0] for x in sem_alcance.values()), 2)
    return dict(criterio="OB contabilizada na gestão a CNPJ com sanção CEIS/CNEP restritiva VIGENTE na data da OB e com "
                         "ALCANCE sobre o Estado do RJ (abrangência declarada no CEIS, esfera do sancionador, fundamentação "
                         "antes da categoria — sancao_abrangencia.veda_ente); vigente sem alcance contada à parte",
                n=len(casos), n_executivo=len(exe), soma_executivo=soma,
                n_inidoneidade=sum(x["grau_sancao"] == "inidoneidade" for x in casos), casos=casos, valor_ob=soma,
                n_sem_alcance=len(sem_alcance), soma_sem_alcance=v_sem,
                resumo=f"Sancionada (com alcance sobre o RJ) paga na vigência: {len(exe)} no Executivo ({brl(soma)}); "
                       f"{len(sem_alcance)} com sanção vigente SEM alcance sobre o Estado ({brl(v_sem)}) — não é vedação")


def d18(c: Ctx) -> dict:
    fs = {dig(x): s for x, s in c.W.execute("SELECT cnpj, score FROM m.fantasma_score WHERE classificacao='alto'")}
    # veredito "fachada" só é CONFIRMADO com o registro do juízo (veredito_raw); status sem conteúdo é marcação, não
    # prova (revisão cética 13/11/2026: 0 dos credores do D18 tinham fachada documentada)
    fv, fv_conf = set(), set()
    for x, raw in c.W.execute("SELECT cnpj, veredito_raw FROM m.fachada_veredito WHERE status='fachada'"):
        fv.add(dig(x))
        if str(raw or "").strip():
            fv_conf.add(dig(x))
    agg = collections.defaultdict(lambda: [0.0, ""])
    for ug, cr, nm, v, dt, pr in c.obs(G0, c.GFIM):
        d = dig(cr)
        if d in fs or d in fv:
            agg[d][0] += v or 0
            agg[d][1] = nm
    casos = [dict(cnpj=d, credor=nm, pago_ob=round(v, 2), fantasma_alto=d in fs, score=fs.get(d), fachada_confirmada=d in fv_conf)
             for d, (v, nm) in agg.items() if v >= 100e3]
    casos.sort(key=lambda x: -x["pago_ob"])
    soma = round(sum(x["pago_ob"] for x in casos), 2)
    return dict(criterio="credor pago na gestão (>=R$100 mil) com fantasma_score=alto ou fachada_veredito=fachada "
                         "(vereditos já registrados)", n=len(casos), soma=soma, casos=casos, valor_ob=soma,
                resumo=f"Fachada/fantasma já registrados: {len(casos)} credores ({brl(soma)})")


def d16(c: Ctx) -> dict:
    rows = c.W.execute("SELECT data_doe, orgao, fornecedor, cnpj, valor FROM m.doerj_tac WHERE data_doe >= ?", (P0,)).fetchall()
    if not rows:
        return dict(indisponivel="doerj_tac sem extratos no ano", n=None, casos=[])
    serie = collections.defaultdict(lambda: [0, 0.0])
    for d, o, f, cj, v in rows:
        s = serie[d[:7]]
        s[0] += 1
        s[1] += v or 0
    pre = [r for r in rows if r[0] < G0]
    pos = [r for r in rows if r[0] >= G0]
    dias_pre = (D.date.fromisoformat(P1) - D.date.fromisoformat(P0)).days + 1
    ult = max(r[0] for r in rows)
    dias_pos = max(1, (D.date.fromisoformat(ult) - D.date.fromisoformat(G0)).days + 1)
    fpre = {norm_nome(r[2]) for r in pre}
    porf = collections.defaultdict(lambda: [0, 0.0, "", set()])
    novos = collections.defaultdict(lambda: [0, 0.0, "", set()])
    for d, o, f, cj, v in pos:
        for alvo in ((porf,) if norm_nome(f) in fpre else (porf, novos)):
            a = alvo[norm_nome(f)]
            a[0] += 1
            a[1] += v or 0
            a[2] = f
            a[3].add((o or "")[:60])
    top = sorted([dict(fornecedor=f, n_tac=n, valor=round(v, 2), orgaos=sorted(o)) for (n, v, f, o) in porf.values()],
                 key=lambda x: -x["valor"])[:20]
    nv = sorted([dict(fornecedor=f, n_tac=n, valor=round(v, 2), orgaos=sorted(o)) for (n, v, f, o) in novos.values()
                 if v >= 1e6], key=lambda x: -x["valor"])
    vpre, vpos = sum(r[4] or 0 for r in pre), sum(r[4] or 0 for r in pos)
    vd_pre, vd_pos = vpre / dias_pre, vpos / dias_pos
    var = (vd_pos / vd_pre - 1) if vd_pre else None
    return dict(criterio="extratos de Termo de Ajuste de Contas no DOERJ (pagamento de serviço sem cobertura contratual). "
                         "Valor = reconhecido no TAC, NÃO é OB",
                n_pre=len(pre), valor_pre=round(vpre, 2), n_gestao=len(pos), valor_gestao=round(vpos, 2), ultima=ult,
                valor_dia_pre=round(vd_pre, 2), valor_dia_gestao=round(vd_pos, 2), variacao_dia=var, n=len(nv),
                serie={k: [v[0], round(v[1], 2)] for k, v in sorted(serie.items())}, top=top, casos=nv,
                resumo=f"TAC: {len(pos)} na gestão, {brl(round(vpos, 2))} reconhecidos ({'+' if (var or 0) >= 0 else ''}"
                       f"{pct(var)}/dia)")


def d07(c: Ctx) -> dict:
    ano = int(c.GFIM[:4])
    rows = c.W.execute("SELECT ug_emitente, credor, nome_credor, n_obs, n_processos, soma, limite_dispensa, "
                       "razao_soma_limite, n_rente_ao_teto, primeira_ob, ultima_ob, prioridade, resumo "
                       "FROM m.siafe_fracionamento WHERE exercicio=?", (ano,)).fetchall()
    casos = [dict(ug=r[0], orgao=c.ugn(r[0]), cnpj=dig(r[1]), credor=r[2], n_obs=r[3], n_processos=r[4], soma=r[5],
                  limite=r[6], razao=r[7], rente_teto=r[8], primeira_ob=iso_br(r[9]), ultima_ob=iso_br(r[10]),
                  prioridade=r[11], resumo=(r[12] or "")[:200]) for r in rows]
    na = sorted((x for x in casos if (x["primeira_ob"] or "") >= G0), key=lambda x: -(x["prioridade"] or 0))
    soma = round(sum(x["soma"] or 0 for x in na), 2)
    nr = sum((x["rente_teto"] or 0) >= 2 for x in na)
    return dict(criterio=f"tabela siafe_fracionamento (régua do sistema) exercício {ano}; recorte: série iniciada na gestão",
                n_ano=len(casos), n=len(na), soma=soma, n_rente=nr, casos=na[:40], valor_ob=soma,
                resumo=f"Fracionamento: {len(na)} séries iniciadas na gestão ({brl(soma)}), {nr} rentes ao teto")


def d06(c: Ctx) -> dict:
    rows = c.W.execute(
        "SELECT a.numero_controle_pncp, a.numero_termo, a.objeto, a.valor_acrescido, a.data_assinatura, p.orgao_nome, "
        "p.fornecedor_nome, p.fornecedor_documento, p.valor_inicial FROM m.contrato_aditivo a "
        "JOIN m.pcrj_contratos p ON p.numero_controle_pncp=a.numero_controle_pncp "
        "WHERE a.data_assinatura>=? AND a.valor_acrescido>0", (G0,)).fetchall()
    sem_valor = c.W.execute("SELECT count(*), sum(valor_acrescido IS NULL) FROM m.contrato_aditivo WHERE data_assinatura>=?",
                            (G0,)).fetchone()
    casos = []
    for cn, termo, obj, acr, dt, org, forn, doc, vi in rows:
        if not vi or re.search(r"MUNIC|PREFEITURA", org or "", re.I) or not re.search(r"ESTADO", org or "", re.I) \
                or _OUTRO_PODER.search(org or ""):
            continue
        # prorrogação/renovação soma o valor de um NOVO período — não é acréscimo do art. 125 (medido: 14 de 15
        # "estouros" da 1ª rodada eram prorrogação ou reajuste, quase todos de outro Poder)
        if re.search(r"prorroga|renova|reajust|repactua", obj or "", re.I) and \
                not re.search(r"acr[ée]scimo\s+quantitativ", obj or "", re.I):
            continue
        p = acr / vi * 100
        if p > 25:
            casos.append(dict(contrato=cn, termo=termo, objeto=(obj or "")[:160], acrescimo=acr, data_termo=str(dt)[:10],
                              orgao=org, fornecedor=forn, cnpj=dig(doc), valor_inicial=vi, pct=round(p, 2)))
    casos.sort(key=lambda x: -x["pct"])
    parcial = f"{sem_valor[1] or 0} de {sem_valor[0] or 0} termos da gestão sem valor no PNCP"
    return dict(criterio="termo aditivo (PNCP) assinado na gestão, contrato de órgão estadual, acréscimo > 25% do valor inicial. "
                         "FONTE PARCIAL: " + parcial,
                n=len(casos), casos=casos,
                resumo=f"Aditivo >25%: {len(casos)} no Executivo estadual — fonte parcial ({parcial})")


_HDR_DEC = re.compile(r"DECRETO\s+N[ºo°]\s*([\d\.\s]{5,9})\s*,?\s*DE\s+(\d{1,2})\s+DE\s+([A-ZÇ]+)\s+DE\s+(20\d\d)", re.I)


def extrair_creditos(texto: str) -> list[dict]:
    """Decretos que ABREM crédito (suplementar/especial/extraordinário) num texto do DOERJ. Função pura."""
    out = []
    ms = list(_HDR_DEC.finditer(texto))
    for k, m in enumerate(ms):
        seg = texto[m.start(): ms[k + 1].start() if k + 1 < len(ms) else m.start() + 6000][:6000]
        head = re.sub(r"[\s\-]+", "", seg[m.end() - m.start(): m.end() - m.start() + 120]).upper()
        if "ABRECR" not in head[:20]:
            continue
        mes = _MESES.get(m.group(3).upper().replace("MARCO", "MARÇO"), 0)
        if not mes:
            continue
        em = re.sub(r"-\s+", "", seg[:700])
        v = re.search(r"VALOR(?:\s+GLOBAL)?\s+DE\s*R\$\s*([\d\.]+,\d{2})(?![\d\.])", em, re.I)
        tipo = re.search(r"cr[ée]dito\s+(suplementar|especial|extraordin\w*)", em, re.I)
        out.append(dict(decreto=re.sub(r"\D", "", m.group(1)), data=f"{m.group(4)}-{mes:02d}-{int(m.group(2)):02d}",
                        tipo=tipo.group(1).lower() if tipo else None,
                        valor=float(v.group(1).replace(".", "").replace(",", ".")) if v else None))
    return out


def d11(c: Ctx) -> dict:
    out = {}
    for (texto,) in c.W.execute(
            "SELECT p.texto FROM m.fts_doerj f JOIN m.publicacoes_doerj p ON p.id=f.rowid WHERE fts_doerj MATCH "
            "'\"crédito suplementar\" OR \"credito suplementar\" OR \"crédito especial\" OR \"crédito extraordinário\"' "
            "AND p.data_publicacao >= ?", (P0,)):
        for x in extrair_creditos(texto or ""):
            out.setdefault(x["decreto"], x)
    a = [x for x in out.values() if x["data"] >= G0]
    b = [x for x in out.values() if P0 <= x["data"] < G0]
    va, vb = round(sum(x["valor"] or 0 for x in a), 2), round(sum(x["valor"] or 0 for x in b), 2)
    return dict(criterio="decretos que abrem crédito suplementar/especial/extraordinário extraídos do texto do DOERJ (valor "
                         "da ementa; crédito aberto ≠ gasto)",
                n=len(a), valor=va, n_pre=len(b), valor_pre=vb, n_valor_ilegivel=sum(x["valor"] is None for x in a),
                casos=sorted(a, key=lambda x: x["data"]),
                resumo=f"Créditos adicionais: {len(a)} decretos {brl(va)} (gestão) × {len(b)} {brl(vb)} (ano, governo "
                       "anterior); sem série do ano anterior")


_ATO12 = re.compile(r"(NOMEAR|EXONERAR)\s*,?\s*(?:com validade[^,]{0,60},\s*)?([A-ZÀ-Ü][A-ZÀ-Ü'\s\.]{8,80}?)\s*,?\s*"
                    r"(?:ID[^,]{0,40},\s*)?(?:para exercer|do cargo|,\s*a pedido|para o cargo)[^.;]{0,120}?"
                    r"(?:cargo|fun[çc][ãa]o)[^.;]{0,40}?\b(?:de|da)\s+(Secret[áa]ri[oa] de Estado d[aeo]s?\s[^,.;]{3,90}|"
                    r"Presidente d[aeo]\s[^,.;]{3,120}|Diretor[a]?[- ]Presidente d[aeo]\s[^,.;]{3,120})", re.S)


def d12(c: Ctx) -> dict:
    out = {}
    for d, t in c.W.execute(
            "SELECT p.data_publicacao, p.texto FROM m.fts_doerj f JOIN m.publicacoes_doerj p ON p.id=f.rowid "
            "WHERE fts_doerj MATCH '(NOMEAR OR EXONERAR) AND (\"Secretário de Estado\" OR \"Secretária de Estado\" OR "
            "Presidente)' AND p.data_publicacao >= ?", (G0,)):
        t2 = re.sub(r"\s+", " ", re.sub(r"-\s+", "", t or ""))
        for m in _ATO12.finditer(t2):
            if re.search(r"Adjunt|Subsecret|Chefe|Assessor|Vice", t2[m.start():m.end()], re.I):
                continue
            out.setdefault((m.group(1), m.group(2).strip(), m.group(3).strip()[:60]),
                           dict(ato=m.group(1), nome=m.group(2).strip(), cargo=m.group(3).strip()[:120], data=d))
    L = sorted(out.values(), key=lambda x: x["data"])
    return dict(criterio="atos NOMEAR/EXONERAR de secretário de Estado e presidente de entidade extraídos do DOERJ",
                n=len(L), casos=L, resumo=f"Mudança de comando: {len(L)} atos extraídos do DOERJ")


def d15(c: Ctx) -> dict:
    if not c.tem_tse:
        return dict(indisponivel="doacao_tse.db ausente", n=None, casos=[])
    cred = collections.defaultdict(lambda: [0.0, ""])
    for cr, nm, v in c.W.execute("SELECT credor, max(nome_credor), sum(valor) FROM ob WHERE status='Contabilizado' AND dt>=? "
                                 "GROUP BY credor", (G0,)):
        d = dig(cr)
        if len(d) == 14 and v >= 1e6:
            cred[d[:8]][0] += v
            cred[d[:8]][1] = nm
    doa = collections.defaultdict(list)
    for ano, nome, doc, ben, part, val in c.W.execute("SELECT ano, doador_nome, doador_doc, beneficiario, partido, valor "
                                                       "FROM t.doacao_tse WHERE length(doador_doc)=11"):
        doa[(nn(nome), doc[3:9])].append((ano, ben, part, val))
    out = []
    for b, (v, nm) in cred.items():
        for nome, doc, q in c.W.execute("SELECT nome_socio, doc_socio, qualificacao_txt FROM m.socios_receita "
                                        "WHERE cnpj_basico=? AND ident='2'", (b,)):
            d = dig(doc)
            k = (nn(nome), d[:6])
            if len(d) == 6 and k in doa:
                out.append(dict(cnpj_basico=b, credor=nm, pago_gestao=round(v, 2), socio=nome, doc_mascarado=f"***{d[:3]}***",
                                qualificacao=q, doacoes=[dict(ano=a, beneficiario=be, partido=p, valor=va)
                                                          for a, be, p, va in doa[k]][:6],
                                total_doado=round(sum(x[3] or 0 for x in doa[k]), 2)))
    out.sort(key=lambda x: -x["pago_gestao"])
    return dict(criterio="sócio PF (nome normalizado + 6 dígitos centrais do CPF) de credor que recebeu >=R$1 mi na gestão, "
                         "presente como doador PF nas prestações de contas do TSE (base local)",
                n=len(out), n_credores=len(cred), casos=out, resumo=f"Doação eleitoral de sócio: {len(out)} vínculos")


def d19(c: Ctx) -> dict:
    from compliance_agent.acima_do_teto import TETO_CF_37_XI, classificar
    comp0, comp1 = G0[:7], c.G1[:7]
    n_reg = c.W.execute("SELECT count(*) FROM m.registros_folha WHERE competencia BETWEEN ? AND ?", (comp0, comp1)).fetchone()[0]
    if not n_reg:
        return dict(indisponivel=f"registros_folha sem competências {comp0}→{comp1}", n=None, casos=[])
    st, org = collections.Counter(), collections.Counter()
    n = 0
    for bruto, o in c.W.execute("SELECT remuneracao_bruta, orgao_nome FROM m.registros_folha WHERE competencia BETWEEN ? AND ? "
                                "AND remuneracao_bruta > ?", (comp0, comp1, TETO_CF_37_XI)):
        n += 1
        st[classificar(bruto).get("status") or "?"] += 1
        org[o or "—"] += 1
    return dict(criterio=f"remuneração bruta > teto CF 37 XI ({brl(TETO_CF_37_XI)}) nas competências {comp0}→{comp1}; "
                         "classificação compliance_agent.acima_do_teto SEM composição de verbas",
                n_registros=n_reg, n_acima=n, por_status=dict(st), top_orgaos=org.most_common(15), n=n, casos=[],
                resumo=f"Remuneração > teto: {n} registros sem composição de verbas — INDISPONÍVEL para conclusão")


def d20(c: Ctx) -> dict:
    def soma(d0, d1):
        return c.W.execute("SELECT count(*), coalesce(sum(valor),0) FROM ob WHERE status IN ('Anulado','Excluído') "
                           "AND dt BETWEEN ? AND ?", (d0, d1)).fetchone()
    ng, vg = soma(G0, c.G1)
    nb, vb = soma(c.B0, c.B1)
    top = [dict(ug=u, orgao=c.ugn(u), n=n, valor=round(v, 2)) for u, n, v in c.W.execute(
        "SELECT ug_emitente, count(*), sum(valor) FROM ob WHERE status IN ('Anulado','Excluído') AND dt BETWEEN ? AND ? "
        "GROUP BY 1 ORDER BY 3 DESC LIMIT 10", (G0, c.G1))]
    dif = round(vg - vb, 2)
    return dict(criterio=f"OB com status Anulado/Excluído (NÃO é pagamento) em {G0}→{c.G1} × {c.B0}→{c.B1}",
                n=ng, valor=round(vg, 2), n_ano_anterior=nb, valor_ano_anterior=round(vb, 2), diferenca=dif, top_ugs=top,
                casos=[], resumo=f"OB anulada/excluída: {ng} ({brl(round(vg, 2))}), {'+' if dif >= 0 else ''}{brl(dif)} "
                                 f"sobre o ano anterior — ver UGs (reemissão?)")


REGRAS = ("D01", "D02", "D03", "D04", "D05", "D06", "D07", "D08", "D09", "D10", "D11", "D12", "D13", "D14", "D15", "D16",
          "D17", "D18", "D19", "D20")
_FUNCS = [("D05", d05), ("D10", d10), ("D03", d03), ("D04", d04), (("D01", "D02", "D17"), d01_02_17),
          (("D08", "D09"), d08_09), ("D13", d13), ("D14", d14), ("D18", d18), ("D16", d16), ("D07", d07), ("D06", d06),
          ("D11", d11), ("D12", d12), ("D15", d15), ("D19", d19), ("D20", d20)]


def calcular(c: Ctx, log=None) -> dict:
    """Roda as 20 regras. Regra cuja fonte falha sai {'indisponivel': erro} — nunca zero."""
    res = {}
    for chave, fn in _FUNCS:
        try:
            r = fn(c)
            if isinstance(chave, tuple):
                res.update(r)
            else:
                res[chave] = r
        except (sqlite3.Error, ValueError, KeyError, TypeError, ImportError) as exc:
            for k in (chave if isinstance(chave, tuple) else (chave,)):
                res[k] = dict(indisponivel=f"{type(exc).__name__}: {exc}", n=None, casos=[])
        if log:
            for k in (chave if isinstance(chave, tuple) else (chave,)):
                log.info("%s: %s", k, res[k].get("resumo") or res[k].get("indisponivel"))
    anexar_provas(c, res)
    return res


# Diretriz do dono (13/11/2026): "não pode ter margem pra erro". Todo caso cita a PROVA PRIMÁRIA que o leitor confere
# na fonte (nº da OB no SIAFE, registro no CEIS/CNEP, processo no espelho do TCE-RJ). Sem prova citada, 🔴/🟡 não sobe
# como achado — vai como "pendente de verificação" (ver `aplicar_verificacao`).
_CHAVE_DOC = {"D14": "cnpj", "D05": "cnpj", "D10": "cnpj", "D18": "cnpj", "D03": "cnpj", "D09": "cnpj",
              "D04": "cnpj_basico", "D13": "cnpj_basico", "D15": "cnpj_basico"}


def anexar_provas(c: Ctx, res: dict) -> None:
    for rid, campo in _CHAVE_DOC.items():
        for x in (res.get(rid) or {}).get("casos", []):
            if rid == "D09":
                p = c.refs_ob(x.get(campo), d0=P0, d1=P1)
            elif rid == "D14":      # prova só de OB DENTRO da vigência da sanção (antes: OB de meses anteriores)
                p = c.refs_ob(x.get(campo), d0=max(G0, x.get("inicio") or G0), d1=x.get("fim") or None)
                p += [f"contrato na vigência da sanção: {k}" for k in x.get("contratos_na_vigencia") or []]
            else:
                p = c.refs_ob(x.get(campo))
            if rid == "D14" and p:
                p.append(f"{x.get('cadastro')} — {x.get('categoria')} desde {x.get('inicio')} ({x.get('orgao_sancionador')})")
            if rid == "D18" and p:
                p.append("veredito de fachada registrado (fachada_veredito)" if x.get("fachada_confirmada")
                         else f"fantasma_score = {x.get('score')} (alto)")
            x["prova_primaria"] = p
    for x in (res.get("D02") or {}).get("casos", []):
        x["prova_primaria"] = [f"contrato no espelho do TCE-RJ, processo {x['processo']}, assinado {x['data']}; "
                               "processo no espelho de compras diretas"] if x.get("processo") else []
    for rid, r in res.items():
        if r.get("indisponivel"):
            continue
        casos = [x for x in r.get("casos") or [] if isinstance(x, dict) and x.get("prova_primaria")]
        r["prova_primaria"] = [f"amostra conferível (1º caso): {q}" for q in casos[0]["prova_primaria"][:2]] if casos else []


# ── montagem do JSON da aba ─────────────────────────────────────────────────────────────────────────────────────

def _base(**k) -> dict:
    b = dict(id=None, camada=None, regra_ou_hipotese=None, grau=None, orgao=None, processo=None, valor_ob=None, fonte=None,
             explicacao_inocente=None, proximo_passo=None)
    b.update(k)
    return b


def _d14_vermelho(x: dict) -> bool:
    """🔴 só com sanção de alcance total (não TCU) E contrato com ato na vigência — e no Executivo."""
    tcu = "TRIBUNAL DE CONTAS DA UNI" in (x.get("orgao_sancionador") or "").upper()
    return (x.get("grau_sancao") == "inidoneidade" and not tcu and bool(x.get("n_contratos_na_vigencia"))
            and not _OUT_CASO.search(x.get("orgao") or ""))


def achados_deterministicos(res: dict, ugn=lambda u: "?") -> list[dict]:
    A = []
    for rid in REGRAS:
        r = res.get(rid) or {"indisponivel": "não calculada"}
        if r.get("indisponivel"):
            A.append(_base(id=rid, camada="deterministica", regra_ou_hipotese=f"{rid} · INDISPONÍVEL — {r['indisponivel']}",
                           grau="⚪", fonte="régua determinística (fonte indisponível — não é zero)",
                           explicacao_inocente=INOCENTE_REGRA[rid], proximo_passo="restabelecer a fonte", tipo="regra"))
            continue
        grau = GRAU_REGRA[rid] if (r.get("n") or 0) > 0 else "⚪"
        A.append(_base(id=rid, camada="deterministica", regra_ou_hipotese=f"{rid} · {r.get('resumo') or ''}", grau=grau,
                       valor_ob=r.get("valor_ob"), fonte=r.get("criterio"), explicacao_inocente=INOCENTE_REGRA[rid],
                       proximo_passo=PASSO_REGRA[rid], tipo="regra", prova_primaria=r.get("prova_primaria") or []))
    for x in (res.get("D14") or {}).get("casos", []):
        if _OUT_CASO.search(x.get("orgao") or ""):
            continue
        nv = x.get("n_contratos_na_vigencia") or 0
        A.append(_base(id=f"D14-{x['cnpj']}-{x['inicio']}", camada="deterministica",
                       regra_ou_hipotese=f"D14 · {x['credor']} paga na vigência de {x['categoria']} ({x['orgao_sancionador']}, "
                                         f"{x['inicio']}→{x['fim'] or 'sem prazo'}) — "
                                         + (f"{nv} contrato(s) com ato NA vigência da sanção" if nv else
                                            "sem contrato novo localizado no espelho do TCE-RJ: pagamento de contrato "
                                            "anterior não é a vedação (efeito ex nunc) — conferir prorrogação"),
                       grau="🔴" if _d14_vermelho(x) else "🟡",
                       orgao=f"{x['orgao']} ({x['ug']})", valor_ob=x["pago_ob"], fonte=SIAFE + "; CEIS/CNEP",
                       explicacao_inocente=INOCENTE_REGRA["D14"], proximo_passo=PASSO_REGRA["D14"], tipo="caso", cnpj=x["cnpj"],
                       prova_primaria=x.get("prova_primaria") or []))
    for x in (res.get("D05") or {}).get("casos", []):
        if x["tipo"] == "PERSISTENTE":
            continue
        A.append(_base(id=f"D05-{x['ug']}-{x['cnpj']}", camada="deterministica",
                       regra_ou_hipotese=f"D05 · {x['credor']} concentra {pct(x['share'])} do pago pela UG ({x['tipo']}; ano "
                                         f"anterior: {pct(x['share_2025'])})",
                       grau="🟡", orgao=f"{x['orgao']} ({x['ug']})", valor_ob=x["pago_ob"], fonte=SIAFE,
                       explicacao_inocente=INOCENTE_REGRA["D05"], proximo_passo=PASSO_REGRA["D05"], tipo="caso", cnpj=x["cnpj"],
                       prova_primaria=x.get("prova_primaria") or []))
    for x in (res.get("D10") or {}).get("casos", []):
        rot = x.get("rotulo") or "estreia"
        A.append(_base(id=f"D10-{x['cnpj']}", camada="deterministica",
                       regra_ou_hipotese=f"D10 · {x['credor']} sem OB à raiz do CNPJ desde 2021; 1ª OB {x['primeira_ob']}"
                                         + (f" ({x['base_rotulo']})" if rot == "estreia" and x.get("base_rotulo") else "")
                                         + ({"consorcio": " — CONSÓRCIO: o CNPJ nasce com o contrato, não é estreia",
                                             "grupo_com_historico": f" — GRUPO COM HISTÓRICO ({x.get('base_rotulo')}): "
                                                                    "sucessão provável, não é estreia"}.get(rot, "")),
                       grau="🟡" if rot == "estreia" else "⚪", orgao=f"{x['orgao']} ({x['ug']})", processo="; ".join(x["processos"][:3]) or None,
                       valor_ob=x["pago_ob"], fonte=SIAFE, explicacao_inocente=INOCENTE_REGRA["D10"],
                       proximo_passo=PASSO_REGRA["D10"], tipo="caso", cnpj=x["cnpj"],
                       prova_primaria=x.get("prova_primaria") or []))
    for x in (res.get("D18") or {}).get("casos", []):
        A.append(_base(id=f"D18-{x['cnpj']}", camada="deterministica",
                       regra_ou_hipotese=f"D18 · {x['credor']} — fachada confirmada: {'sim' if x['fachada_confirmada'] else 'não'}; " +
                                         (f"score {x['score']}" if x.get("score") is not None else "sem score de fantasma"),
                       grau="🔴" if x["fachada_confirmada"] else "🟡", valor_ob=x["pago_ob"],
                       fonte=SIAFE + "; registro de vistoria de sede", explicacao_inocente=INOCENTE_REGRA["D18"],
                       proximo_passo=PASSO_REGRA["D18"], tipo="caso", cnpj=x["cnpj"],
                       prova_primaria=x.get("prova_primaria") or []))
    for x in (res.get("D02") or {}).get("casos", []):
        A.append(_base(id=f"D02-{x['processo']}-{x['cnpj']}", camada="deterministica",
                       regra_ou_hipotese=f"D02 · emergencial ao incumbente {x['fornecedor']} ({x['data']})", grau="🟡",
                       orgao=x["unidade"], processo=x["processo"],
                       fonte="espelhos de contratos e compras diretas do TCE-RJ (valor de contrato, não OB)",
                       explicacao_inocente=INOCENTE_REGRA["D02"], proximo_passo=PASSO_REGRA["D02"], tipo="caso",
                       cnpj=x["cnpj"], valor_contrato=x["valor_contrato"], prova_primaria=x.get("prova_primaria") or []))
    return A


ESQUEMA_H = {
    "type": "object",
    "properties": {"hipoteses": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "string"}, "regra_ou_hipotese": {"type": "string"},
                       "grau": {"type": "string", "enum": ["🔴", "🟡", "⚪"]}, "confianca": {"type": "string"},
                       "orgao": {"type": "string"}, "regras_base": {"type": "array", "items": {"type": "string"}},
                       "explicacao_inocente": {"type": "string"}, "proximo_passo": {"type": "string"}},
        "required": ["id", "regra_ou_hipotese", "grau", "confianca", "explicacao_inocente", "proximo_passo"]}}},
    "required": ["hipoteses"],
}


def prompt_hipoteses(res: dict, top_casos: list[dict]) -> str:
    linhas = [f"- {k}: {(res.get(k) or {}).get('resumo') or (res.get(k) or {}).get('indisponivel')}" for k in REGRAS]
    casos = [f"- [{x['grau']}] {x['regra_ou_hipotese']} | {x.get('orgao') or ''} | OB {brl(x.get('valor_ob'))}"
             for x in top_casos[:40]]
    return (
        "Você é perito de controle externo (TCE/ALERJ) analisando a gestão do governador em exercício do Estado do RJ "
        f"(desde {G0}). Abaixo estão os resultados de 20 regras DETERMINÍSTICAS e os maiores casos.\n\n"
        "REGRAS:\n" + "\n".join(linhas) + "\n\nCASOS:\n" + "\n".join(casos) + "\n\n"
        "Formule de 5 a 9 HIPÓTESES analíticas (camada subjetiva) que liguem os achados — padrões, não pessoas. Para cada "
        "uma: id H1..H9; texto curto; grau (🔴 forte, 🟡 médio, ⚪ fraco); confiança separando fato de motivação (ex.: "
        "'alta (padrão) / baixa (motivação)'); órgão(s); regras_base (ids D..); explicação INOCENTE plausível (obrigatória) "
        "e próximo passo verificável (requerimento, leitura de processo). Regras: indício não é acusação; não invente "
        "número que não esteja acima; pagamento = OB; TAC e contrato não são OB; INDISPONÍVEL não é zero; não cite CPF.")


def hipoteses_validas(bruto) -> list[dict]:
    """Só entra hipótese com texto, grau válido, explicação inocente E próximo passo. Função pura."""
    if isinstance(bruto, dict):
        bruto = bruto.get("hipoteses")
    out = []
    for i, h in enumerate(bruto or []):
        if not isinstance(h, dict):
            continue
        txt, ino, prox = (str(h.get(k) or "").strip() for k in ("regra_ou_hipotese", "explicacao_inocente", "proximo_passo"))
        if not (txt and ino and prox) or h.get("grau") not in ("🔴", "🟡", "⚪"):
            continue
        out.append(_base(id=f"H{i + 1}", camada="subjetiva", regra_ou_hipotese=txt[:400], grau=h["grau"],
                         orgao=(str(h.get("orgao") or "") or None), explicacao_inocente=ino[:400], proximo_passo=prox[:400],
                         confianca=str(h.get("confianca") or "")[:120], regras_base=list(h.get("regras_base") or [])[:10],
                         tipo="hipotese"))
    return out


ROTULO_PENDENTE = "PENDENTE DE VERIFICAÇÃO — "
ROTULO_HIPOTESE = "HIPÓTESE (gerada por modelo; não é fato) — "
VERIFICACAO_DEF = ("VERIFICADO = o número foi reproduzido da fonte primária citada em `prova_primaria` (nº da OB no SIAFE, "
                   "registro CEIS/CNEP, processo no espelho do TCE-RJ) — é conferível, NÃO é juízo de irregularidade. "
                   "PENDENTE = sem prova primária citada: grau 🔴/🟡 rebaixado a ⚪ (o original fica em grau_proposto) e o "
                   "texto rotulado. Hipótese do modelo é sempre PENDENTE. INDISPONÍVEL = a fonte falhou (não é zero).")


def aplicar_verificacao(x: dict) -> dict:
    """Estado de verificação visível em cada item. Função pura — idempotente (não rotula duas vezes)."""
    x = dict(x)
    txt = str(x.get("regra_ou_hipotese") or "")
    for r in (ROTULO_PENDENTE, ROTULO_HIPOTESE):
        txt = txt.replace(r, "")
    if x.get("camada") == "subjetiva" or x.get("tipo") == "hipotese":
        x["verificacao"] = "PENDENTE"
        x["natureza"] = "hipótese gerada por modelo — não é fato; exige o próximo passo para ser confirmada ou descartada"
        if x.get("grau") in ("🔴", "🟡"):
            x.setdefault("grau_proposto", x["grau"])
            x["grau"] = "⚪"
        x["regra_ou_hipotese"] = ROTULO_HIPOTESE + txt
        return x
    if "INDISPONÍVEL" in txt and x.get("tipo") == "regra" and not x.get("valor_ob"):
        x["verificacao"] = "INDISPONÍVEL"
        x["regra_ou_hipotese"] = txt
        return x
    prova = [p for p in (x.get("prova_primaria") or []) if str(p).strip()]
    x["prova_primaria"] = prova
    if x.get("top10"):
        # o título já carrega o estado (curar_top10); VERIFICADO só o que a verificação sustentou com prova primária
        x["verificacao"] = "VERIFICADO" if x.get("estado_verificacao") == "SUSTENTADO" and prova else "PENDENTE"
        x["regra_ou_hipotese"] = txt
        return x
    if prova:
        x["verificacao"] = "VERIFICADO"
        x["regra_ou_hipotese"] = txt
    else:
        x["verificacao"] = "PENDENTE"
        if x.get("grau") in ("🔴", "🟡"):
            x.setdefault("grau_proposto", x["grau"])
            x["grau"] = "⚪"
        if x.get("grau_proposto"):
            x["regra_ou_hipotese"] = ROTULO_PENDENTE + txt
        else:
            x["regra_ou_hipotese"] = txt
    return x


def curar_top10(x: dict) -> dict:
    """Item da curadoria manual. Função pura e idempotente: estado de verificação obrigatório (sem ele, PENDENTE e ⚪),
    estado no início do título, nunca 🔴 fixado à mão, REFUTADO/PENDENTE → ⚪, PARCIAL/SUSTENTADO → no máximo 🟡."""
    x = dict(x, top10=True, camada=x.get("camada") or "deterministica")
    x.setdefault("curadoria", "manual — seleção editorial com estado da verificação de 13/11/2026")
    est = str(x.get("estado_verificacao") or "").upper()
    est = est if est in ESTADOS_CURADORIA else "PENDENTE"
    x["estado_verificacao"] = est
    txt = str(x.get("regra_ou_hipotese") or "")
    for e in ESTADOS_CURADORIA + ("PENDENTE",):
        if txt.startswith(f"{e} · "):
            txt = txt[len(e) + 3:]
    x["regra_ou_hipotese"] = f"{est} · {txt}"
    alvo = "⚪" if est in ("REFUTADO", "PENDENTE") else ("🟡" if x.get("grau") in ("🔴", "🟡", None) else x["grau"])
    if alvo != x.get("grau"):
        x.setdefault("grau_proposto", x.get("grau"))
        x["grau"] = alvo
    return x


def carregar_curadoria(caminho: Path = CURADORIA) -> list[dict] | None:
    """Itens do arquivo de curadoria (`{"itens": [...]}` ou lista). Ausente ou ilegível → None (top 10 fica de fora,
    dito em `curadoria.estado` — nunca se volta a preservar o título antigo)."""
    d = ler_json(caminho)
    itens = d.get("itens") if isinstance(d, dict) else d
    return [x for x in itens if isinstance(x, dict)] if isinstance(itens, list) else None


def _estado_curadoria(curadoria: list[dict] | None) -> dict:
    if curadoria is None:
        return {"estado": "ausente", "arquivo": CURADORIA.name,
                "motivo": "arquivo de curadoria ausente — o top 10 não é publicado sem estado de verificação"}
    return {"estado": "ok", "arquivo": CURADORIA.name, "n": len(curadoria)}


def reaplicar_curadoria(saida: Path = SAIDA, curadoria: Path = CURADORIA) -> int:
    """Troca SÓ o top 10 do arquivo publicado pela curadoria atual, sem recalcular as 20 regras (que leva até 1 h).
    Devolve quantos itens curados foram gravados; sem curadoria legível não toca o arquivo (→ -1)."""
    doc, cur = ler_json(saida), carregar_curadoria(curadoria)
    if not isinstance(doc, dict) or cur is None:
        return -1
    from compliance_agent.governo_couto import _mascarar_tudo
    top = [aplicar_verificacao(curar_top10(x)) for x in cur]
    A = top + [x for x in doc.get("achados", []) if isinstance(x, dict) and not x.get("top10")]
    doc.update(achados=A, n_achados=len(A), curadoria=_estado_curadoria(cur),
               por_verificacao=dict(collections.Counter(x.get("verificacao") for x in A)))
    gravar_json(saida, _mascarar_tudo(doc))
    return len(top)


def montar(res: dict, *, anterior: dict | None, hipoteses: list[dict] | None, motivo_subj: str | None, ctx_info: dict,
           curadoria: list[dict] | None = None) -> dict:
    from compliance_agent.governo_couto import _mascarar_tudo
    anterior = anterior or {}
    ant = [x for x in anterior.get("achados", []) if isinstance(x, dict)]
    top = [curar_top10(x) for x in (curadoria or [])]
    det = achados_deterministicos(res)
    if hipoteses:
        mod = ctx_info.get("modelo") or "modelo não informado"
        subj = [dict(h, fonte=f"motor Claude ({mod}) sobre a camada determinística de {ctx_info['gerado_em'][:10]}",
                     modelo=mod) for h in hipoteses]
        estado_subj = {"estado": "ok", "gerado_em": ctx_info["gerado_em"], "modelo": mod}
    else:
        subj = [dict(x, pendente=True) for x in ant if x.get("camada") == "subjetiva"]
        estado_subj = {"estado": "pendente", "motivo": motivo_subj or "motor indisponível",
                       "mantidas_do_arquivo_anterior": len(subj)}
    A = [aplicar_verificacao(x) for x in top + det + subj]
    doc = dict(gerado_em=ctx_info["gerado_em"], titulo="Gestão Couto — camadas determinística e subjetiva",
               inicio_gestao=G0, fonte_inicio=anterior.get("fonte_inicio") or "DOERJ 24/03/2026 Parte I e II",
               recorte=dict(gestao=f"{G0}→{ctx_info['G1']} (OB até {ctx_info['GFIM']})",
                            base=f"{ctx_info['B0']}→{ctx_info['B1']}", pre=f"{P0}→{P1}"),
               valor_ob_definicao=("valor_ob = soma de OB com status Contabilizado no SIAFE-Rio; TAC e contrato não são OB "
                                   "(valor_ob nulo nesses casos)"),
               relatorio=anterior.get("relatorio") or "~/vault/casos/gestao-couto-analise-2026-11-13.md",
               regua="compliance_agent.governo_couto_regras (recalculada semanalmente)",
               camada_subjetiva=estado_subj, curadoria=_estado_curadoria(curadoria), verificacao_definicao=VERIFICACAO_DEF,
               por_verificacao=dict(collections.Counter(x["verificacao"] for x in A)),
               indisponivel=[f"{k}: {v['indisponivel']}" for k, v in res.items() if v.get("indisponivel")],
               n_achados=len(A), achados=A)
    return _mascarar_tudo(doc)


def _rodar(log, saida: Path, detalhe: Path, usar_motor: bool) -> int:
    c = Ctx(dir_tmp=DATA / "tmp" if (DATA / "tmp").is_dir() else None)
    try:
        log.info("base de trabalho pronta: OB até %s, janela %s→%s", c.GFIM, G0, c.G1)
        res = calcular(c, log)
        info = dict(gerado_em=agora_iso(), GFIM=c.GFIM, G1=c.G1, B0=c.B0, B1=c.B1)
    finally:
        c.fechar()
    anterior = ler_json(saida)
    hip, motivo = None, "desligado por --sem-motor"
    if usar_motor:
        det = sorted((x for x in achados_deterministicos(res) if x.get("tipo") == "caso"),
                     key=lambda x: ({"🔴": 0, "🟡": 1}.get(x["grau"], 2), -(x.get("valor_ob") or 0)))
        # tarefa `camada_subjetiva` tem teto próprio no motor; juízo analítico → modelo de juízo
        bruto, motivo = pensar("camada_subjetiva", prompt_hipoteses(res, det), schema=ESQUEMA_H,
                               modelo="claude-opus-5-5", timeout=600.0)
        info["modelo"] = rotina_base.ULTIMO_MODELO
        hip = hipoteses_validas(bruto) if bruto is not None else None
        if bruto is not None and not hip:
            motivo = "motor respondeu sem hipótese válida (faltou explicação inocente ou próximo passo)"
    log.info("camada subjetiva: %s", f"{len(hip)} hipóteses do motor" if hip else f"PENDENTE — {motivo}")
    cur = carregar_curadoria()
    if cur is None:
        log.warning("curadoria ausente (%s): o top 10 sai do arquivo até ser declarado com estado de verificação", CURADORIA)
    doc = montar(res, anterior=anterior, hipoteses=hip, motivo_subj=motivo, ctx_info=info, curadoria=cur)
    n_det = sum(1 for x in doc["achados"] if x.get("camada") == "deterministica" and not x.get("top10"))
    doc["efeito"] = {"achados": len(doc["achados"]), "deterministicos": n_det, "hipoteses_motor": len(hip or [])}
    doc["ultimo_efeito_iso"] = info["gerado_em"] if n_det else (anterior or {}).get("ultimo_efeito_iso")
    from compliance_agent.governo_couto import _mascarar_tudo
    gravar_json(detalhe, _mascarar_tudo({"gerado_em": info["gerado_em"], "recorte": doc["recorte"], "regras": res}))
    gravar_json(saida, doc)
    log.info("gravado %s (%d achados: %d determinísticos, %d hipóteses)", saida, len(doc["achados"]), n_det, len(hip or []))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Gestão Couto — 20 regras determinísticas + hipóteses pelo motor Claude.")
    ap.add_argument("--saida", default=str(SAIDA))
    ap.add_argument("--detalhe", default=str(DETALHE))
    ap.add_argument("--sem-motor", action="store_true", help="não chama o motor Claude (camada subjetiva fica pendente)")
    ap.add_argument("--so-curadoria", action="store_true",
                    help="só troca o top 10 do arquivo publicado pela curadoria atual (sem recalcular as regras)")
    a = ap.parse_args(argv)
    if a.so_curadoria:
        n = reaplicar_curadoria(Path(a.saida))
        print(f"curadoria: {n} itens gravados em {a.saida}" if n >= 0 else "curadoria ou arquivo publicado ilegível")
        return 0 if n >= 0 else 1
    return executar(NOME, lambda log: _rodar(log, Path(a.saida), Path(a.detalhe), not a.sem_motor))


if __name__ == "__main__":
    raise SystemExit(main())
