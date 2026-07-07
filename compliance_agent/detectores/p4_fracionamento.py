# -*- coding: utf-8 -*-
"""P4 · FRACIONAMENTO DE DESPESA (spec V2 do dono, §2).

Mecanismo: a contratação é dividida em várias DISPENSAS menores para escapar do certame competitivo. O art. 75,
§1º, da Lei 14.133/2021 VEDA considerar isoladamente parcelas de uma mesma contratação para fins de enquadramento
na dispensa por valor.

PARÂMETROS OBJETIVOS (no CÓDIGO — limiar nunca vai ao prompt do LLM, spec §1.3):
  • Soma por grupo de objeto: cluster (similaridade ≥ 0.8 ou mesmo grupo CATMAT), mesmo órgão, mesmo exercício.
    Soma do grupo > limite de dispensa vigente E ≥2 contratações por dispensa → flag .................. 0.85 (forte)
  • Clustering sob o teto: ≥2 contratações do grupo com valor individual entre 80%–100% do limite ...... 0.85
  • Mesmo fornecedor: ≥3 dispensas no ano p/ o mesmo CNPJ ou grupo societário (QSA cruzado) ............ 0.85
  • Proximidade temporal: contratações do grupo com intervalos < 30 dias entre si .................... +0.10
  • Sequência pós-limite: nova dispensa do grupo iniciada < 60 dias após a anterior ter consumido o limite . 0.60

PARTE SUBJETIVA (LLM-OPCIONAL, degrada honesto): rubrica fechada 'os objetos do grupo são parcelas de uma MESMA
contratação PREVISÍVEL?' [mesma-natureza-e-previsível / mesma-natureza-mas-demandas-independentes / naturezas-
distintas]. Só a 1ª classe CONFIRMA o flag. Sem LLM → o flag objetivo permanece como indício, mas a previsibilidade
fica `nao_avaliavel` (não inflamos o score com juízo que não temos).

TESTE EXCULPATÓRIO (spec): demandas IMPREVISÍVEIS genuínas (manutenções corretivas distintas) podem somar acima do
limite SEM fraude — sem previsibilidade, máximo 0.3. UNIDADES GESTORAS AUTÔNOMAS com orçamento próprio podem
contratar o mesmo objeto separadamente de forma lícita — verificar a estrutura ANTES de somar entre UGs.

HONESTIDADE JFN: indício ≠ acusação; campo ausente (sem marcador de dispensa, sem QSA) → `nao_avaliavel`, não 0;
limite vigente é o da DATA de cada contratação (não o atual); nunca inventa número.
"""
from __future__ import annotations

import difflib
import re
from datetime import date, datetime

from compliance_agent.detectores.base import (
    Detector,
    ResultadoDetector,
    ancora,
    avaliar_rubrica,
)

# ───────────────────────────── Limites de dispensa do art. 75, I/II (Lei 14.133/2021) ─────────────────────────────
# Valores vigentes por exercício (atualizados anualmente por DECRETO FEDERAL — §1.5: usar o da DATA da contratação).
# I = obras/serviços de engenharia · II = demais (compras/serviços). Fonte: Decreto 11.871/2023 e reajustes.
LIMITES_DISPENSA: dict[int, dict[str, float]] = {
    # exercicio: {"obras": valor, "compras": valor}
    2021: {"obras": 100_000.00, "compras": 50_000.00},   # valores originais da Lei 14.133
    2023: {"obras": 119_812.02, "compras": 59_906.02},   # Decreto 11.871/2023
    2024: {"obras": 119_812.02, "compras": 59_906.02},
    2025: {"obras": 128_722.10, "compras": 64_361.04},   # reajuste 2025 (confirmar no decreto do exercício)
    2026: {"obras": 128_722.10, "compras": 64_361.04},   # placeholder até o reajuste 2026 sair — confirmar
}
_DEFAULT_EXERCICIO = 2024


def limite_dispensa(exercicio: int | None, tipo: str = "compras") -> float | None:
    """Limite de dispensa por valor vigente no EXERCÍCIO (art. 75, I/II). `tipo`: 'obras' (engenharia) ou
    'compras' (demais). Exercício desconhecido → cai no mais próximo ≤ exercício (decretos são cumulativos).
    Retorna None se não houver tabela aplicável (→ detector marca nao_avaliavel, honesto)."""
    tipo = "obras" if (tipo or "").lower().startswith("obra") else "compras"
    if not exercicio:
        exercicio = _DEFAULT_EXERCICIO
    if exercicio in LIMITES_DISPENSA:
        return LIMITES_DISPENSA[exercicio][tipo]
    anteriores = [e for e in LIMITES_DISPENSA if e <= exercicio]
    if anteriores:
        return LIMITES_DISPENSA[max(anteriores)][tipo]
    return None


# ───────────────────────────── Normalização / similaridade de objeto ─────────────────────────────
_STOP = {"de", "da", "do", "das", "dos", "e", "para", "com", "em", "a", "o", "as", "os", "no", "na",
         "ao", "aos", "por", "ou", "um", "uma", "servico", "servicos", "aquisicao", "contratacao"}


def _norm_objeto(s: str | None) -> str:
    """Normaliza descrição de objeto: minúsculas, sem acento, sem pontuação, sem stopwords (p/ similaridade)."""
    t = (s or "").lower()
    t = (t.replace("ã", "a").replace("á", "a").replace("â", "a").replace("à", "a")
           .replace("é", "e").replace("ê", "e").replace("í", "i").replace("ó", "o").replace("ô", "o")
           .replace("õ", "o").replace("ú", "u").replace("ç", "c"))
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    toks = [w for w in t.split() if w and w not in _STOP and len(w) > 2]
    return " ".join(toks)


def _similar(a: str, b: str) -> float:
    """Similaridade textual [0,1] entre dois objetos normalizados (Ratcliff/Obershelp via difflib).
    Leve, sem embedding/dependência pesada — adequado para a VM. CATMAT casa via campo explícito (abaixo)."""
    na, nb = _norm_objeto(a), _norm_objeto(b)
    if not na or not nb:
        return 0.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


def _grupo_objeto(c: dict) -> str | None:
    """Chave de grupo EXPLÍCITA: CATMAT/CATSER ou grupo informado. Quando presente, agrupa por igualdade
    (mais robusto que similaridade textual)."""
    for k in ("catmat", "catser", "grupo_objeto", "grupo"):
        v = c.get(k)
        if v:
            return f"{k}:{str(v).strip().lower()}"
    return None


def clusterizar(contratacoes: list[dict], limiar_sim: float = 0.8) -> list[list[int]]:
    """Agrupa contratações por similaridade de objeto ≥ `limiar_sim` (ou mesmo grupo CATMAT/CATSER explícito).
    Retorna lista de clusters (cada um = lista de índices em `contratacoes`). União simples (single-linkage)."""
    n = len(contratacoes)
    pai = list(range(n))

    def find(x: int) -> int:
        while pai[x] != x:
            pai[x] = pai[pai[x]]
            x = pai[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            pai[rb] = ra

    # pré-computa normalização e grupo explícito UMA vez (era recalculado por PAR — O(n²) normalizações;
    # num sweep de ~600 contratações isso dominava o custo). Comportamento idêntico.
    grupos_expl = [_grupo_objeto(c) for c in contratacoes]
    normados = [_norm_objeto(c.get("objeto", "")) for c in contratacoes]

    for i in range(n):
        gi = grupos_expl[i]
        for j in range(i + 1, n):
            gj = grupos_expl[j]
            if gi and gj:
                if gi == gj:
                    union(i, j)
            else:
                na, nb = normados[i], normados[j]
                if not na or not nb:
                    continue
                # poda EXATA: quick_ratio/real_quick_ratio são upper bounds do ratio (difflib) —
                # se o teto já fica abaixo do limiar, o ratio caro nunca alcançaria. Zero mudança de resultado.
                sm = difflib.SequenceMatcher(None, na, nb)
                if (sm.real_quick_ratio() >= limiar_sim and sm.quick_ratio() >= limiar_sim
                        and sm.ratio() >= limiar_sim):
                    union(i, j)

    grupos: dict[int, list[int]] = {}
    for i in range(n):
        grupos.setdefault(find(i), []).append(i)
    return list(grupos.values())


# ───────────────────────────── helpers de campo ─────────────────────────────
def _is_dispensa(c: dict) -> bool | None:
    """A contratação é DISPENSA? True/False, ou None se o dado não existe (→ nao_avaliavel honesto).
    Aceita flag explícita `dispensa` (bool) ou texto de `modalidade`/`tipo` contendo 'dispensa'."""
    if "dispensa" in c and c["dispensa"] is not None:
        return bool(c["dispensa"])
    for k in ("modalidade", "tipo", "tipo_ob", "categoria"):
        v = c.get(k)
        if v:
            return "dispensa" in str(v).lower()
    return None


def _data(c: dict) -> date | None:
    v = c.get("data") or c.get("data_pagamento") or c.get("data_assinatura") or c.get("data_emissao")
    if isinstance(v, date):
        return v
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, str):
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(v[:19] if "T" in v else v[:10], fmt).date()
            except ValueError:
                continue
    return None


def _exercicio(c: dict, d: date | None) -> int | None:
    return int(c.get("exercicio")) if c.get("exercicio") else (d.year if d else None)


def _fornecedor(c: dict) -> str | None:
    v = c.get("fornecedor") or c.get("favorecido_cpf") or c.get("cnpj") or c.get("favorecido_nome")
    return str(v).strip() if v else None


def _grupo_economico(c: dict) -> str:
    """Chave de grupo econômico: usa `grupo_economico` explícito (resolvido por QSA) se houver; senão o CNPJ
    raiz (8 primeiros dígitos = mesma matriz/filiais). Permite tratar grupo societário como UM agente (spec)."""
    g = c.get("grupo_economico")
    if g:
        return f"ge:{str(g).strip().lower()}"
    f = _fornecedor(c) or ""
    digs = re.sub(r"\D", "", f)
    if len(digs) >= 8:
        return f"raiz:{digs[:8]}"
    return f"forn:{f.lower()}"


# ───────────────────────────── Detector P4 ─────────────────────────────
# Rubrica fechada da previsibilidade → nível de âncora (spec §2/P4).
_RUBRICA_PREVISIBILIDADE = {
    "mesma_natureza_e_previsivel": "forte",            # demanda contínua conhecida → CONFIRMA
    "mesma_natureza_mas_demandas_independentes": "fraco",  # imprevisível genuíno → máx 0.3
    "naturezas_distintas": "ausente",                  # agrupamento INDEVIDO do detector → descarta
}


class P4Fracionamento(Detector):
    """Detector P4 — fracionamento de despesa (art. 75, §1º, Lei 14.133/2021).

    `avaliar(contexto)` espera:
      contexto["processo"]: id do processo/órgão
      contexto["contratacoes"]: list[dict] de contratações do órgão no exercício, cada uma com pelo menos
          {objeto, valor, data|data_pagamento, fornecedor|favorecido_cpf} e opcionalmente
          {modalidade|dispensa, exercicio, catmat|catser|grupo, grupo_economico, tipo_obj('obras'|'compras')}.
      contexto["gerar"] (opcional): callable async/sync para a rubrica LLM de previsibilidade. Ausente → a
          parte subjetiva fica nao_avaliavel (degrada honesto) e o flag objetivo permanece como indício.
      contexto["ug_autonomas"] (opcional bool): se True, sinaliza UGs autônomas (exculpatória do spec).

    Honesto: sem contratações, sem marcador de dispensa, ou todas as datas ausentes → status nao_avaliavel."""

    id = "P4"
    nome = "Fracionamento de despesa"
    familia = "violacao_legal"  # art. 75 §1º — violação legal objetiva (peso 1.0 na convergência §7.2)

    def avaliar(self, contexto: dict) -> ResultadoDetector:
        processo = str(contexto.get("processo") or contexto.get("id") or "?")
        contratacoes = contexto.get("contratacoes") or []
        res = self._novo(processo, status="nao_avaliavel")

        if not contratacoes:
            res.motivo_refutacao = "nao_avaliavel: nenhuma contratação no contexto"
            res.valores = {"n_contratacoes": 0}
            return res

        # honestidade: precisamos saber QUAIS são dispensas. Se NENHUMA contratação traz o marcador, não dá
        # para avaliar fracionamento (não inventamos a modalidade) → nao_avaliavel.
        marcadores = [_is_dispensa(c) for c in contratacoes]
        if all(m is None for m in marcadores):
            res.motivo_refutacao = ("nao_avaliavel: sem marcador de modalidade/dispensa nas contratações — "
                                    "não é possível avaliar fracionamento (campo ausente ≠ 0)")
            res.valores = {"n_contratacoes": len(contratacoes), "dispensas_identificaveis": 0}
            return res

        # clusteriza por objeto e escolhe o cluster de maior valor somado de DISPENSAS como o achado principal.
        clusters = clusterizar(contratacoes)
        melhor = None
        for idxs in clusters:
            disp_idxs = [i for i in idxs if _is_dispensa(contratacoes[i]) is True]
            if len(disp_idxs) < 2:
                continue  # fracionamento exige ≥2 dispensas do mesmo grupo
            soma = sum(float(contratacoes[i].get("valor") or 0) for i in disp_idxs)
            if melhor is None or soma > melhor[1]:
                melhor = (disp_idxs, soma, idxs)

        if melhor is None:
            res.status = "descartado"
            res.motivo_refutacao = "nenhum grupo de objeto com ≥2 dispensas — sem indício de fracionamento"
            res.valores = {"n_contratacoes": len(contratacoes), "n_clusters": len(clusters)}
            res.explicacao_inocente = "as dispensas são de objetos distintos (não somam para o limite)"
            return res

        disp_idxs, soma, _todos_idxs = melhor
        disp = [contratacoes[i] for i in disp_idxs]

        # exercício e limite vigente NA DATA (spec §1.5)
        datas = [d for d in (_data(c) for c in disp) if d]
        exercicio = next((_exercicio(c, _data(c)) for c in disp if _exercicio(c, _data(c))), None)
        tipo_obj = next((c.get("tipo_obj") for c in disp if c.get("tipo_obj")), "compras")
        limite = limite_dispensa(exercicio, tipo_obj)

        valores: dict = {
            "n_dispensas_cluster": len(disp),
            "soma_cluster": round(soma, 2),
            "exercicio": exercicio,
            "tipo_objeto": tipo_obj,
            "limite_dispensa_vigente": limite,
            # rastreabilidade probatória (§7.4): QUAIS processos compõem o cluster achado — permite a
            # consumidores (ex.: sweep em lote) auditar/remover o cluster e citar os autos na evidência.
            "processos_cluster": [str(c.get("processo")) for c in disp if c.get("processo")][:50],
        }

        if limite is None:
            res.status = "nao_avaliavel"
            res.motivo_refutacao = "nao_avaliavel: sem limite de dispensa aplicável ao exercício (tabela ausente)"
            res.valores = valores
            return res

        # ── REGRAS OBJETIVAS (código, nunca prompt) ──
        score = 0.0
        razoes: list[str] = []

        # 1) Soma do grupo > limite E ≥2 dispensas → forte (0.85)
        if soma > limite and len(disp) >= 2:
            score = max(score, ancora("forte"))
            razoes.append(f"soma das {len(disp)} dispensas (R$ {soma:,.2f}) excede o limite (R$ {limite:,.2f})")

        # 2) Clustering sob o teto: ≥2 com valor individual entre 80%–100% do limite → forte
        sob_teto = [c for c in disp if limite * 0.8 <= float(c.get("valor") or 0) <= limite]
        if len(sob_teto) >= 2:
            score = max(score, ancora("forte"))
            razoes.append(f"{len(sob_teto)} dispensas com valor individual entre 80%–100% do limite (rente ao teto)")
        valores["dispensas_sob_teto_80_100"] = len(sob_teto)

        # 3) Mesmo fornecedor / grupo econômico: ≥3 dispensas no grupo → forte
        por_grupo: dict[str, int] = {}
        for c in disp:
            por_grupo[_grupo_economico(c)] = por_grupo.get(_grupo_economico(c), 0) + 1
        max_mesmo_forn = max(por_grupo.values()) if por_grupo else 0
        valores["max_dispensas_mesmo_grupo_economico"] = max_mesmo_forn
        if max_mesmo_forn >= 3:
            score = max(score, ancora("forte"))
            razoes.append(f"{max_mesmo_forn} dispensas para o mesmo fornecedor/grupo econômico (QSA)")

        # 4) Proximidade temporal: intervalos < 30 dias entre si → +0.10
        if len(datas) >= 2:
            datas_ord = sorted(datas)
            intervalos = [(datas_ord[i + 1] - datas_ord[i]).days for i in range(len(datas_ord) - 1)]
            min_intervalo = min(intervalos) if intervalos else None
            valores["min_intervalo_dias"] = min_intervalo
            if min_intervalo is not None and min_intervalo < 30 and score > 0:
                score = min(1.0, score + 0.10)
                razoes.append(f"contratações próximas no tempo (menor intervalo {min_intervalo} dias)")

        # evidência (higiene probatória §7.4): cita cada dispensa do cluster
        for c in disp[:8]:
            d = _data(c)
            res.add_evidencia(
                fonte=f"contratação {_fornecedor(c) or '?'}",
                trecho=(f"objeto='{(c.get('objeto') or '')[:80]}' valor=R$ {float(c.get('valor') or 0):,.2f} "
                        f"data={d.isoformat() if d else '?'} dispensa={_is_dispensa(c)}"),
            )

        if score <= 0:
            res.status = "descartado"
            res.motivo_refutacao = "regras objetivas não acionaram (soma sob limite, sem cluster rente ao teto)"
            res.valores = valores
            res.explicacao_inocente = "dispensas dentro do limite legal e dispersas — sem indício de fracionamento"
            return res

        # ── PARTE SUBJETIVA (LLM-opcional): rubrica de previsibilidade ──
        # Só a classe 'mesma-natureza-e-previsível' CONFIRMA. Sem LLM → previsibilidade nao_avaliavel: o flag
        # objetivo permanece (status confirmado pelo código), mas registramos que a natureza não foi auditada.
        gerar = contexto.get("gerar")
        prev = self._avaliar_previsibilidade(disp, gerar=gerar)
        valores["previsibilidade"] = prev["status"]
        if prev["status"] == "naturezas_distintas":
            # o LLM diz que o detector pareou objetos distintos → DESCARTA (exculpatória do próprio detector)
            res.status = "descartado"
            res.score = 0.0
            res.motivo_refutacao = f"rubrica previsibilidade: naturezas distintas — agrupamento indevido ({prev['motivo']})"
            res.valores = valores
            res.explicacao_inocente = "objetos de naturezas distintas, não são parcelas de uma mesma contratação"
            return res
        if prev["status"] == "mesma_natureza_mas_demandas_independentes":
            # imprevisível genuíno → o spec impõe máximo 0.3 (fraco)
            score = min(score, ancora("fraco"))
            razoes.append("rubrica: demandas independentes/imprevisíveis → score limitado a 0.3 (exculpatória do spec)")

        # exculpatória estrutural: UGs autônomas (spec) — rebaixa, não zera
        if contexto.get("ug_autonomas"):
            score = min(score, ancora("medio"))
            razoes.append("UGs autônomas com orçamento próprio — possível contratação separada lícita (verificar estrutura)")

        res.score = round(score, 4)
        res.status = "confirmado"
        res.valores = valores
        res.explicacao_inocente = ("demandas imprevisíveis distintas (manutenções corretivas) ou UGs autônomas "
                                   "podem somar acima do limite sem fraude — verificar previsibilidade/estrutura")
        res.motivo_refutacao = "; ".join(razoes)
        return res

    def _avaliar_previsibilidade(self, disp: list[dict], *, gerar=None) -> dict:
        """Rubrica fechada LLM-opcional. Sem `gerar` → nao_avaliavel honesto (não inventa o juízo subjetivo).
        Aceita também uma resposta já-classificada injetada em `disp[0]['_rubrica_previsibilidade']` (p/ teste
        determinístico sem rede)."""
        # atalho de teste: rubrica pré-fornecida no contexto (sem LLM)
        pre = None
        for c in disp:
            if c.get("_rubrica_previsibilidade"):
                pre = c["_rubrica_previsibilidade"]
                break
        if pre is not None:
            nivel, _score, motivo = avaliar_rubrica(pre, _RUBRICA_PREVISIBILIDADE)
            classe = (pre.get("nivel") or pre.get("classificacao") or "").strip().lower()
            if nivel is None:
                return {"status": "nao_avaliavel", "motivo": motivo}
            return {"status": classe, "motivo": motivo}

        if gerar is None:
            return {"status": "nao_avaliavel", "motivo": "LLM ausente — previsibilidade não auditada (honesto)"}

        # caminho com LLM: pergunta UMA coisa (decomposição §1.3), rubrica fechada + citação obrigatória.
        objetos = "\n".join(f"- {(c.get('objeto') or '')[:120]}" for c in disp[:8])
        sistema = (
            "Você é auditor de controle externo avaliando FRACIONAMENTO. Classifique se os objetos abaixo são "
            "PARCELAS DE UMA MESMA CONTRATAÇÃO PREVISÍVEL. Responda SOMENTE com JSON: "
            '{"nivel":"mesma_natureza_e_previsivel|mesma_natureza_mas_demandas_independentes|naturezas_distintas",'
            '"trecho":"<citação literal de um objeto que sustenta a classificação>"}. Sem trecho, não classifique.'
        )
        prompt = f"OBJETOS DAS DISPENSAS DO MESMO GRUPO:\n{objetos}\n\nClassifique a previsibilidade."
        try:
            raw = gerar(prompt, sistema)
        except Exception as e:  # noqa: BLE001 — degrada honesto
            return {"status": "nao_avaliavel", "motivo": f"LLM indisponível ({str(e)[:50]})"}
        from compliance_agent.detectores.base import _parse_json
        dados = _parse_json(raw)
        nivel, _score, motivo = avaliar_rubrica(dados, _RUBRICA_PREVISIBILIDADE)
        if nivel is None or not isinstance(dados, dict):
            return {"status": "nao_avaliavel", "motivo": motivo}
        classe = (dados.get("nivel") or "").strip().lower()
        return {"status": classe, "motivo": motivo}


# ───────────────────────────── Adaptador: contratações a partir da DB (degrada honesto) ─────────────────────────────
def contratacoes_do_orgao(ug_codigo: str, exercicio: int | None = None, *, con=None, limite_linhas: int = 5000) -> dict:
    """Monta o `contexto` de P4 a partir das `ordens_bancarias` de um órgão (UG). HONESTO: a base do JFN NÃO traz
    o marcador de modalidade/dispensa nas OBs (campo ausente) — então as contratações vêm SEM `dispensa`, e o
    detector marcará `nao_avaliavel` (campo ausente ≠ 0). Quando a coleta PNCP/SEI enriquecer a modalidade, basta
    preencher `dispensa`/`modalidade` que P4 passa a pontuar. Use DuckDB (read-only) p/ não pesar a VM."""
    fechar = False
    if con is None:
        from compliance_agent.duckdb_util import conectar
        con = conectar()
        fechar = True
    try:
        q = ("SELECT favorecido_cpf, favorecido_nome, valor, data_pagamento, exercicio, observacao, tipo_ob "
             "FROM db.ordens_bancarias WHERE ug_codigo = ? ")
        params: list = [str(ug_codigo)]
        if exercicio:
            q += "AND exercicio = ? "
            params.append(int(exercicio))
        q += "ORDER BY data_pagamento LIMIT ?"
        params.append(int(limite_linhas))
        rows = con.execute(q, params).fetchall()
    finally:
        if fechar:
            con.close()
    contratacoes = [{
        "favorecido_cpf": r[0], "favorecido_nome": r[1], "valor": r[2], "data_pagamento": r[3],
        "exercicio": r[4], "objeto": (r[5] or r[6] or ""),  # OB não tem 'objeto' rico → usa observação/tipo
        # SEM marcador de dispensa de propósito (a DB não tem) → P4 cai em nao_avaliavel honesto.
    } for r in rows]
    return {"processo": f"UG {ug_codigo}", "contratacoes": contratacoes}
