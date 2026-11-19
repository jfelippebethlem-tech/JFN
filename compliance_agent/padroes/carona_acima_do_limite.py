"""carona_acima_do_limite — adesão (carona) que passa o limite legal da ata, ou ata usada fora do regime/vigência.

Origem: SEI-420001/006323/2025 (STEM × SEGOV): ARP 90048/2024 do IFMT homologou 5.000.000 un a R$ 0,66 = R$ 3,3 mi
(PNCP); a SEGOV pagou R$ 25.662.000,00 (2025OB06215). E Globaltec SEI-260005/010324/2025: contrato de 2025 com
"FUNDAMENTO: Lei nº 8.666" por adesão a ata de 2023.

Sinais:
  L1 acima_50pct_aderente  — valor desta adesão (OB paga, piso) > 50% do valor HOMOLOGADO da ata no PNCP
                             (Lei 14.133 art. 86 §4º; Dec. 7.892/2013 art. 22 §3º na Lei 8.666). Com preço unitário
                             igual ao da ata, valor > 50% do total ⇒ algum item passou 50% da quantidade.
  L2 acima_dobro_total     — soma das adesões DO ACERVO à mesma ata > 2× o homologado (art. 86 §5º; Dec. 7.892
                             art. 22 §4º). Só o que o acervo vê: outras caronas no país somam mais (piso).
  L3 ata_fora_de_vigencia  — NE de adesão emitida depois do fim da vigência da ata no PNCP.
  L4 lei_revogada          — extrato/contrato assinado em 2025+ com fundamento na Lei 8.666 (revogada em 30/12/2023;
                             art. 191 da 14.133 só preserva o que foi licitado sob ela — pedir a ata e a vigência).
Limites normativos: os mesmos do X4 (`detectores.x4_carona_abusiva`), importados — não duplicados.
"""
from __future__ import annotations

import json
import re
import time
from datetime import date

import requests

from compliance_agent.detectores.x4_carona_abusiva import LIMITE_ADESAO_INDIVIDUAL, LIMITE_TOTAL_ADESOES
from compliance_agent.padroes import _carona_comum as cc
from compliance_agent.reporting.intel_base import moeda
from compliance_agent.padroes import carona_aderente_vedado as cav

ID = "carona_acima_do_limite"
VICIO = "carona_abusiva"  # knowledge/catalogo_vicios.py
PNCP = "https://pncp.gov.br/api"
CACHE_PNCP = cc.RAIZ / "data" / "padroes" / "_cache_pncp_atas.json"
_H = {"User-Agent": "Mozilla/5.0 (JFN padroes)"}

RX_ATA_NUM = re.compile(
    r"(?:Ata\s+de\s+Registro\s+de\s+Pre[çc]os|\bARP)\s*(?:\(ARP\)\s*)?(?:(?:n[º°o.]*|n[úu]mero)\s*)?:?\s*"
    r"0*(\d{1,6})\s*/\s*(20\d{2})\b", re.I)
RX_CNPJ = re.compile(r"\b(\d{2})\.(\d{3})\.(\d{3})/(\d{4})-(\d{2})\b")
RX_CNPJ_UG = re.compile(r"\(CNPJ:?\s*(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})\)")   # cabeçalho da NE = o próprio órgão
RX_NE_EXTERNO = re.compile(r"ades[ãa]o\s+ao\s+registro\s+de\s+pre[çc]os\s+externo", re.I)
RX_EMISSAO = re.compile(r"Emiss[ãa]o\s*\n?\s*(?:[^\n]*\n){0,3}?\s*(\d{2})/(\d{2})/(\d{2,4})", re.I)
def _espacado(palavras: str) -> str:
    """'DATA DA ASSINATURA' tolerando o DOERJ que espaça letras ('A S S I N AT U R A')."""
    return r"\s+".join(r"\s*".join(re.escape(c) for c in p) for p in palavras.split())


RX_ASSINATURA = re.compile(_espacado("DATA DA ASSINATURA") + r"\s*:?\s*(\d{2})/(\d{2})/(20\d{2})", re.I)
RX_FUND_8666 = re.compile(r"FUNDAMENTO\s*(?:LEGAL)?\s*:?\s*(?:[^\n]{0,30})Lei\s*(?:Federal\s*)?(?:n[º°o.]*\s*)?8\.?666", re.I)
RX_ADESAO_QQ = re.compile(r"ades[ãa]o\s+ao\s+registro\s+de\s+pre[çc]os|ades[ãa]o\s+(?:à|a)\s+(?:ata|arp)", re.I)


# ─────────────────────────────── PNCP (com cache em disco; INDISPONÍVEL ≠ 0) ───────────────────────────────
def _get(url: str, params: dict | None = None):
    """GET no PNCP em SÉRIE, com pausa: em paralelo (6 threads) o PNCP devolve 429 'Limite de requisições
    excedido' em segundos (medido 19/11/2026). 429 espera e tenta de novo; None = indisponível."""
    for tent in range(6):
        time.sleep(0.4)
        try:
            r = requests.get(url, params=params, headers=_H, timeout=60)
        except requests.RequestException:
            time.sleep(3 * (tent + 1))
            continue
        if r.status_code == 200:
            try:
                return r.json()
            except ValueError:
                return None
        if r.status_code in (204, 404):
            return []
        time.sleep((20 if r.status_code == 429 else 3) * (tent + 1))
    return None          # indisponível


def _cache() -> dict:
    try:
        return json.loads(CACHE_PNCP.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _salvar_cache(c: dict) -> None:
    CACHE_PNCP.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_PNCP.with_suffix(".tmp")
    tmp.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
    tmp.replace(CACHE_PNCP)


_LISTAS: dict[tuple[str, int], list | None] = {}
# teto de tempo das consultas ao PNCP por varredura (o PNCP limita a taxa e oscila): o que passar do teto vira
# "pncp_indisponivel" na cobertura — INDISPONÍVEL ≠ 0, e o cache em disco faz a próxima rodada continuar dali
ORCAMENTO_PNCP_S = 3600
_INICIO_PNCP: list[float] = []


def lista_atas(cnpj: str, aa: int) -> list | None:
    """Todas as atas do órgão publicadas no ano `aa` (PNCP /consulta/v1/atas). None = indisponível. Memória do
    processo: o mesmo gerenciador aparece em vários processos de adesão."""
    k = (cnpj, int(aa))
    if k in _LISTAS:
        return _LISTAS[k]
    if not _INICIO_PNCP:
        _INICIO_PNCP.append(time.time())
    if time.time() - _INICIO_PNCP[0] > ORCAMENTO_PNCP_S:
        return None                                   # sem tempo: indisponível nesta rodada (não grava)
    out: list = []
    for p in range(1, 41):
        j = _get(f"{PNCP}/consulta/v1/atas", {"dataInicial": f"{aa}0101", "dataFinal": f"{aa}1231",
                                               "cnpj": cnpj, "pagina": p, "tamanhoPagina": 50})
        if j is None:
            _LISTAS[k] = None
            return None
        if not j:
            break
        out.extend(j.get("data") or [])
        if p >= int(j.get("totalPaginas") or 1):
            break
    _LISTAS[k] = out
    return out


def ata_pncp(cnpj: str, numero: str, ano: str, cache: dict) -> dict | None | str:
    """Ata (numero/ano) do órgão `cnpj` no PNCP com itens e resultados. None = não achou; "indisponivel" = falha."""
    k = f"{cnpj}|{int(numero)}|{ano}"
    if k in cache:
        return cache[k]
    achada = None
    for aa in (int(ano), int(ano) + 1):                  # a consulta aceita no máximo 365 dias por janela
        lst = lista_atas(cnpj, aa)
        if lst is None:
            return "indisponivel"
        achada = next((it for it in lst if str(it.get("anoAta")) == str(ano) and
                       re.sub(r"\D", "", str(it.get("numeroAtaRegistroPreco"))).lstrip("0") == str(int(numero))), None)
        if achada:
            break
    if not achada:
        cache[k] = None
        return None
    m = re.match(r"(\d{14})-\d-0*(\d+)/(\d{4})", achada.get("numeroControlePNCPCompra") or "")
    itens_out = []
    if m:
        cn, seq, an = m.groups()
        itens = _get(f"{PNCP}/pncp/v1/orgaos/{cn}/compras/{an}/{seq}/itens", {"pagina": 1, "tamanhoPagina": 500})
        if itens is None:
            return "indisponivel"
        for it in itens or []:
            res = []
            if it.get("temResultado"):
                rr = _get(f"{PNCP}/pncp/v1/orgaos/{cn}/compras/{an}/{seq}/itens/{it['numeroItem']}/resultados")
                if rr is None:
                    return "indisponivel"
                res = [{"fornecedor": x.get("nomeRazaoSocialFornecedor"), "ni": x.get("niFornecedor"),
                        "qtd": x.get("quantidadeHomologada"), "unit": x.get("valorUnitarioHomologado"),
                        "total": x.get("valorTotalHomologado"), "desconto": x.get("percentualDesconto")}
                       for x in rr or []]
            itens_out.append({"item": it.get("numeroItem"), "descricao": it.get("descricao"),
                              "qtd": it.get("quantidade"), "unit_estimado": it.get("valorUnitarioEstimado"),
                              "resultados": res})
    out = {"controle_ata": achada.get("numeroControlePNCPAta"), "controle_compra": achada.get("numeroControlePNCPCompra"),
           "orgao": achada.get("nomeOrgao"), "cnpj": cnpj, "vig_ini": achada.get("vigenciaInicio"),
           "vig_fim": achada.get("vigenciaFim"), "cancelada": achada.get("cancelado"),
           "objeto": (achada.get("objetoContratacao") or "")[:300], "itens": itens_out,
           "total_homologado": round(sum(float(r.get("total") or 0) for i in itens_out for r in i["resultados"]), 2)}
    cache[k] = out
    return out


# ─────────────────────────────── leitura dos autos ───────────────────────────────
def ata_citada(ds: list[cc.Doc]) -> tuple[str, str, str] | None:
    """(numero, ano, prova) da ata mais citada nos autos."""
    cont: dict[tuple, list] = {}
    for d in ds:
        for m in RX_ATA_NUM.finditer(d.texto):
            cont.setdefault((m.group(1), m.group(2)), []).append((d, m))
    if not cont:
        return None
    (n, a), lst = max(cont.items(), key=lambda kv: len(kv[1]))
    d, m = lst[0]
    return n, a, f'{d.ref} — "{cc.trecho(d.texto, m.start(), m.end(), 50)[:220]}"'


def cnpjs_candidatos(ds: list[cc.Doc], excluir: set[str]) -> list[str]:
    """CNPJs dos autos, os da ata/edital/TR primeiro; tira credor(es) e o próprio Estado do RJ (raiz 42.498)."""
    cont: dict[str, int] = {}
    excluir = set(excluir) | {re.sub(r"\D", "", m.group(1)) for d in ds for m in RX_CNPJ_UG.finditer(d.texto)}
    for d in ds:
        peso = 5 if cc.tipo_doc(d.titulo) in ("ata", "edital") or "ata" in cc.sem_acento(d.titulo).lower() else 1
        for m in RX_CNPJ.finditer(d.texto):
            c = "".join(m.groups())
            if c in excluir or c.startswith("42498") or len(set(c)) == 1:
                continue
            cont[c] = cont.get(c, 0) + peso
    return [c for c, _ in sorted(cont.items(), key=lambda kv: -kv[1])][:3]


def _data_ne_adesao(ds: list[cc.Doc]) -> tuple[date, str] | None:
    for d in ds:
        if RX_NE_EXTERNO.search(d.texto):
            m = RX_EMISSAO.search(d.texto)
            if m:
                dd, mm, aa = m.groups()
                aa = int(aa) + (2000 if len(aa) == 2 else 0)
                try:
                    return date(aa, int(mm), int(dd)), f'{d.ref} — "{cc.trecho(d.texto, m.start(), m.end(), 20)[:160]}"'
                except ValueError:
                    return None
    return None


def lei_revogada(ds: list[cc.Doc], credor: str | None = None) -> dict | None:
    """Contrato/extrato assinado em 2025+ com fundamento na Lei 8.666, num processo de adesão. Data e fundamento no
    MESMO extrato (≤ 900 caracteres) e, sabendo o credor, o nome dele no extrato — página do DOERJ traz extratos
    vizinhos de outros contratos."""
    if not any(RX_ADESAO_QQ.search(d.texto) for d in ds):
        return None
    tok = [w for w in re.findall(r"[A-Z]{4,}", cc.sem_acento(credor or "").upper()) if w not in ("LTDA", "COMERCIO", "SERVICOS")][:2]
    for d in ds:
        for a in RX_ASSINATURA.finditer(d.texto):
            if int(a.group(3)) < 2025:
                continue
            jan = d.texto[max(0, a.start() - 1500): a.end() + 900]
            f = RX_FUND_8666.search(d.texto, a.end(), a.end() + 900)
            if not f:
                continue
            if tok and not any(w in cc.sem_acento(jan).upper() for w in tok):
                continue
            return {"sinal": "lei_revogada", "grau": "medio", "data_assinatura": "/".join(a.groups()),
                    "prova": f'{d.ref} ({d.titulo[:60]}) — "{cc.trecho(d.texto, a.start(), a.end(), 10)[:120]}" … '
                             f'"{cc.trecho(d.texto, f.start(), f.end(), 10)[:120]}"'}
    return None


def limite_aderente(pago: float, ata: dict) -> dict | None:
    """§4º: valor desta adesão (OB paga) acima de 50% do homologado da ata. >1× → forte (nem com o preço da ata
    a quantidade cabe na ata inteira); 0,5–1× → médio."""
    tot = ata.get("total_homologado") or 0
    if not tot or not pago:
        return None
    razao = pago / tot
    if razao <= LIMITE_ADESAO_INDIVIDUAL:
        return None
    itens = "; ".join(f"item {i['item']} {str(i.get('descricao'))[:40]!r} qtd {r['qtd']} × R$ {r['unit']}"
                      for i in ata.get("itens", [])[:4] for r in i.get("resultados", [])[:2])
    return {"sinal": "acima_50pct_aderente", "grau": "forte" if razao > 1 else "medio",
            "razao_pago_sobre_homologado": round(razao, 2),
            "prova": f"PNCP ata {ata.get('controle_ata')} ({ata.get('orgao')}): homologado R$ {moeda(tot)}; {itens}"
                     f" | SIAFE pago (piso) R$ {moeda(pago)} = {str(round(razao, 2)).replace(".", ",")}× o homologado"
                     + (f" | autos: {ata['_prova_autos']}" if ata.get("_prova_autos") else "")}


def varrer(limite: int | None = None) -> dict:
    adesoes, cob0 = cav.base_adesao(limite)
    base: list[tuple[str, list[cc.Doc], str]] = []
    sem_texto = 0
    cods = {t: cc.codigo_mod(ne) for t, ne in adesoes}
    # interna (ata do RJ, Mod. 10): só o sinal da lei revogada — basta ler contrato/extrato/NE
    pedidos = [(t, ("contrato", "empenho", "outro") if cods[t] == "10" else None) for t, _ in adesoes]
    for t, ds in cc.docs_em_paralelo(pedidos):
        cod = cods[t]
        if not ds:
            sem_texto += 1
            continue
        if cod == "10":
            base.append((t, ds, "interna"))
            continue
        r = cav.avaliar(t, ds)
        if r["adesao"]:
            base.append((t, ds, r["adesao"]))
    obs = cc.ob_pagas({cc.canon(t) for t, _, _ in base})
    cache = _cache()
    cob = {**cob0, "sem_texto": sem_texto, "adesoes": len(base),
           "externas": sum(1 for b in base if b[2] == "externa"), "sem_numero_de_ata": 0, "ata_nao_achada_pncp": 0,
           "pncp_indisponivel": 0, "sem_ob_paga": 0, "atas_pncp": 0}
    por_ata: dict[str, list] = {}
    # listas de atas por (gerenciador, ano), uma vez cada — o mesmo gerenciador aparece em vários processos
    pares = set()
    for t, ds, tipo in base:
        if tipo != "externa":
            continue
        ac = ata_citada(ds)
        if ac:
            excl = {re.sub(r"\D", "", o.get("cnpj") or "") for o in (obs.get(cc.canon(t)) or {}).get("obs", [])}
            for cn in cnpjs_candidatos(ds, excl):
                if f"{cn}|{int(ac[0])}|{ac[1]}" not in cache:
                    pares |= {(cn, int(ac[1])), (cn, int(ac[1]) + 1)}
    for pa in sorted(pares):                       # em série: o PNCP limita a taxa (429)
        lista_atas(*pa)
    achados: list[dict] = []
    for t, ds, tipo in base:
        canon = cc.canon(t)
        ob = obs.get(canon)
        sinais: list[dict] = []
        lr = lei_revogada(ds, cc.credor_principal(ob))
        if lr:
            sinais.append(lr)
        ata = None
        if tipo == "externa":
            ac = ata_citada(ds)
            if not ac:
                cob["sem_numero_de_ata"] += 1
            else:
                excl = {re.sub(r"\D", "", o.get("cnpj") or "") for o in (ob or {}).get("obs", [])}
                for cn in cnpjs_candidatos(ds, excl):
                    a = ata_pncp(cn, ac[0], ac[1], cache)
                    _salvar_cache(cache)          # a consulta ao PNCP é o passo caro: não perder num erro adiante
                    if a == "indisponivel":
                        cob["pncp_indisponivel"] += 1
                        break
                    if a:
                        ata = a
                        break
                if ata is None:
                    cob["ata_nao_achada_pncp"] += 1
                else:
                    cob["atas_pncp"] += 1
                    ata["_prova_autos"] = ac[2]
        if ata and ata.get("total_homologado"):
            if ob and ob.get("total"):
                por_ata.setdefault(ata["controle_ata"], []).append((canon, ob["total"]))
                s50 = limite_aderente(ob["total"], ata)
                if s50:
                    sinais.append(s50)
            else:
                cob["sem_ob_paga"] += 1
            ne = _data_ne_adesao(ds)
            if ne and ata.get("vig_fim"):
                try:
                    fim = date.fromisoformat(str(ata["vig_fim"])[:10])
                except ValueError:
                    fim = None
                if fim and ne[0] > fim:
                    sinais.append({"sinal": "ata_fora_de_vigencia", "grau": "medio",
                                   "prova": f"PNCP vigência até {fim.isoformat()}; NE de adesão {ne[1]}"})
        if sinais:
            achados.append({"processo": canon, "sinais": sinais, "ata_pncp": ata and {k: v for k, v in ata.items() if k != "itens"},
                            "orgao": cc.orgao_ou_ug(ds, ob), "credor": cc.credor_principal(ob),
                            "valor_pago_ob": ob["total"] if ob else None, "obs": (ob or {}).get("obs", [])[:20]})
    _salvar_cache(cache)
    # L2 — soma das adesões do acervo à mesma ata
    for ctrl, lst in por_ata.items():
        tot = next((a for a in cache.values() if isinstance(a, dict) and a.get("controle_ata") == ctrl), {}).get("total_homologado")
        soma = sum(v for _, v in lst)
        if tot and soma > LIMITE_TOTAL_ADESOES * tot and len(lst) > 1:
            for canon, v in lst:
                ach = next((a for a in achados if a["processo"] == canon), None)
                s = {"sinal": "acima_dobro_total", "grau": "forte",
                     "prova": f"PNCP ata {ctrl}: homologado R$ {moeda(tot)}; {len(lst)} adesões no acervo somam "
                              f"R$ {moeda(soma)} ({str(round(soma / tot, 2)).replace(".", ",")}×): " + ", ".join(f"{c} R$ {moeda(x)}" for c, x in lst)}
                if ach:
                    ach["sinais"].append(s)
    ordem = {"forte": 0, "medio": 1, "fraco": 2}
    for a in achados:
        a["sinais"].sort(key=lambda s: ordem[s["grau"]])
        a["grau"] = a["sinais"][0]["grau"]
        a["sinal"] = a["sinais"][0]["sinal"]
        a["prova"] = " | ".join(s["prova"] for s in a["sinais"])
        a["porque"] = ("Inocente possível: OB do processo pode somar mais de uma ata/contrato; preço da ata em 'valor de "
                       "capa'/desconto muda a unidade (medir em unidades de capa: pago ÷ (1 − desconto)); 8.666 pode ser "
                       "ata licitada até 29/12/2023 ainda vigente. Não afasta: a ata no PNCP não comporta o valor pago.")
        a["fonte"] = "SEI (autos) + PNCP (atas/itens/resultados) + SIAFE (_ob_paga, piso)"
    achados.sort(key=lambda a: (ordem[a["grau"]], -(a["valor_pago_ob"] or 0)))
    cc.ligar(achados, VICIO, lambda a: a.get("sinal") in ("acima_50pct_aderente", "acima_dobro_total"))
    return cc.resultado(ID, len(base), cob, achados)
