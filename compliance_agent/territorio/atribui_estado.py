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
FONTE = "PNCP — contratos do Estado do RJ (Poder Executivo)"
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


def carregar_unidades() -> list[tuple[re.Pattern, str, str]]:
    p = base.DATA / "territorio_unidades.csv"
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        return [(re.compile(rf"\b{re.escape(r['nome_norm'])}\b"), r["cod_ibge"], r["nome_norm"]) for r in csv.DictReader(f)]


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
    if unidades and _GATILHO.search(o):
        cods, evid = [], []
        for rg, cod, nome in unidades:
            if rg.search(o) and cod not in cods:
                cods.append(cod)
                evid.append(nome)
        if cods:
            metodos.append({"metodo": "unidade", "cods": cods, "confianca": "alta", "evidencia": "unidade citada: " + "; ".join(evid[:3])})
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
           "evidencia": None, "metodos": metodos}
    if not metodos:
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
                       "vig_fim": (fim or "")[:10] or None, "status": status})
    log(f"[estado] {len(linhas)} contratos do Executivo estadual; fora do escopo: {fora['municipal']} de unidade municipal, "
        f"{fora['outro']} de órgão fora do Executivo")
    pagos = _pagamentos(src, linhas, log)
    src.close()

    db = base.abrir(escrita=True)
    ja = {r[0]: r[1] for r in db.execute("SELECT contrato_id, assinatura FROM territorio_contrato_estado")} if incremental else {}
    agora, n_grav = base.agora(), 0
    for k in linhas:
        pago, pago_ev = pagos.get(k["contrato_id"], (None, None))
        ass = hashlib.sha1(json.dumps([k["objeto"], k["orgao"], k["valor"], k["vig_fim"], k["status"], pago], ensure_ascii=False,
                                      default=str).encode()).hexdigest()
        if incremental and ja.get(k["contrato_id"]) == ass:
            continue
        at = atribuir(k["objeto"], k["orgao"], regionais, unidades)
        db.execute("INSERT OR REPLACE INTO territorio_contrato_estado(contrato_id,fonte,orgao,fornecedor_cnpj,fornecedor_nome,objeto,"
                   "valor,vig_ini,vig_fim,status,pago,cod_ibge,multi,municipios_json,regiao,metodo,confianca,evidencia,metodos_json,"
                   "pago_evidencia,assinatura,atualizado_em) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (k["contrato_id"], FONTE, k["orgao"], k["fornecedor_cnpj"], k["fornecedor_nome"], k["objeto"], k["valor"],
                    k["vig_ini"], k["vig_fim"], k["status"], pago, at["cod_ibge"], at["multi"],
                    json.dumps(at["municipios"], ensure_ascii=False), at["regiao"], at["metodo"], at["confianca"], at["evidencia"],
                    json.dumps(at["metodos"], ensure_ascii=False), pago_ev, ass, agora))
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
