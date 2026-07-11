#!/usr/bin/env python3
"""Camada CLAUDE da perícia paralela (cruza com a Lex). Para cada contrato do FUNESBOM já coletado:
- parte do parecer da Lex (lex_execucao) + ficha (sei_ficha) + árvore (sei_arvore) + score de triagem + redes de sócios;
- CORRIGE o viés da Lex de pontuar "ausência no trecho" como risco alto (INDISPONÍVEL != irregular);
- ELEVA quando há sinal estrutural real (dispensa/inexig + alto valor + rede de sócio / valor redondo idêntico);
- detecta CAPTURA-RASA (dossiê não bate com o objeto do contrato → re-coletar árvore de contratação);
- registra divergência Lex×Claude p/ revisão humana.
Honestidade: indício != acusação; INDISPONÍVEL != 0. Determinístico (sem LLM)."""
import sqlite3
import json
import re

DB = "/home/ubuntu/JFN/data/compliance.db"
FILA = "/home/ubuntu/JFN/data/bombeiros_sei_fila.json"
OUT = "/home/ubuntu/JFN/reports/_pericia_bombeiros_reconciliacao.json"

# inexigibilidade/contratação direta tipicamente LEGÍTIMA (monopólio/exclusividade) — baixa o flag
LEGIT = ["CORREIO", "TELEGRAFO", "ECT", "LIGHT", "AMPLA", "ENEL", "CEG", "CEDAE", "AGUAS",
         "AGUA DE", "ENERGISA", "HELICOPTEROS DO BRASIL", "PETROBRAS", "IMPRENSA OFICIAL",
         "BRK AMBIENTAL", "JUTURNAIBA", "PRO LAGOS", "PROLAGOS", "SANEAMENTO", "SANEADORA"]

def _na(s):
    """Normaliza acentos p/ casar a lista LEGIT (ASCII) contra nomes acentuados (ÁGUAS ≠ AGUAS)."""
    import unicodedata
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().upper()
ABS = re.compile(r"ausênc|ausenc|não há|nao ha|impede a verifica|não foi|nao foi", re.I)

def main():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=20)
    c = con.cursor()
    fila = {x["sei"]: x for x in json.load(open(FILA))}
    # redes de sócios (cnpj base -> nome,n,total)
    redes = {}
    for nome, bases, n, tot in c.execute("SELECT nome_socio,cnpjs_basicos,n_fornecedores,total_recebido FROM rede_socios_fornecedores WHERE n_fornecedores>=2"):
        for b in (bases or "").split(","):
            redes.setdefault(b.strip(), (nome, n, tot))

    # opinião FORTE (deepseek-v4-pro) dos prioritários, se houver — tabela SEPARADA lex_aprofundado.
    # Degrada honesto: se a pista nunca rodou (tabela inexistente), segue sem.
    aprof = {}
    try:
        for ns_a, nota_a, exe_a, res_a in c.execute(
                "SELECT numero_sei,nota_risco,execucao_comprovada,resumo FROM lex_aprofundado"):
            aprof[ns_a] = {"risco": nota_a, "exec": exe_a, "resumo": res_a}
    except Exception:
        pass

    res = []
    rows = c.execute("""SELECT l.numero_sei,l.execucao_comprovada,l.coerencia,l.nota_risco,l.indicios,l.duvidas,l.resumo,
                               f.objeto, f.red_flags, f.resumo, a.nivel_risco
                        FROM lex_execucao l LEFT JOIN sei_ficha f ON f.numero_sei=l.numero_sei
                        LEFT JOIN sei_arvore a ON a.numero_sei=l.numero_sei
                        WHERE l.numero_sei LIKE 'SEI-2700%'""").fetchall()
    for ns, exe, coer, risco, ind, duv, resumo, obj_ficha, rflags_ficha, fresumo, arv_risco in rows:
        if ns not in fila:  # só os contratos do FUNESBOM (a fila); ignora vazamento do LIKE
            continue
        meta = fila.get(ns, {})
        forn = (meta.get("forn") or "")
        obj_contrato = (meta.get("obj") or obj_ficha or "")  # fila não tem 'obj' → cai p/ objeto da ficha
        flags = meta.get("flags") or []
        try: indl = json.loads(ind) if ind else []
        except Exception: indl = []
        try: risco = float(risco) if risco is not None else 0
        except Exception: risco = 0

        claude_risco = risco
        motivos = []
        acao = "ok"

        # 1) viés-de-ausência: se TODOS os indícios da Lex são de mera ausência no trecho → INDISPONÍVEL, não alto risco
        so_ausencia = bool(indl) and all(ABS.search(x or "") for x in indl)
        if risco >= 7 and so_ausencia:
            claude_risco = 4
            motivos.append("Lex pontuou ALTO só por ausência no trecho (INDISPONÍVEL≠irregular) → rebaixado")
            acao = "verificar_autos_integrais"

        # 2) inexigibilidade/direta legítima (monopólio) → baixa. legit_mono é TERMINAL: nem rede de sócio
        #    nem achado material elevam uma concessionária/monopólio (gabarito: Ampla tinha rede_socio ruído).
        legit_mono = any(k in _na(forn) for k in LEGIT) or any(k in _na(obj_ficha) for k in LEGIT)
        if legit_mono and claude_risco is not None and claude_risco > 5:
            claude_risco = min(claude_risco, 5)
            motivos.append("Fornecedor de monopólio/exclusividade (inexigibilidade típica legítima)")

        # 3) captura-rasa: o dossiê coletado é ATO DE ROTINA (arquivamento/RH; pagamento-financeiro
        #    desembolso/concessionária; ou administrativo plano-de-contingência/encaminhamento), não a
        #    árvore de contratação → indeterminado, re-coletar. (gabarito: Enge Prat desembolso R$505;
        #    ImagemVida "Plano de Contingência" p/ credenciamento.)
        of = (obj_ficha or "").upper()
        capt_blob = of + " " + (fresumo or "").upper()
        ROTINA_RH = ("ARQUIVAMENTO", "NOMEA", "REINTEGRA")
        ROTINA_NCONTRAT = ("PROGRAMAÇÃO DE DESEMBOLSO", "PROGRAMACAO DE DESEMBOLSO", "PAGAMENTO DE DESPESAS COM CONCESSION",
                           "PLANO DE CONTINGÊNCIA", "PLANO DE CONTINGENCIA", "ENCAMINHAMENTO DE SOLICITAÇÃO", "ENCAMINHAMENTO DE SOLICITACAO")
        # a fila NÃO tem objeto-do-contrato (só ficha) → sem contraste ficha×contrato; o teste é só sobre a ficha
        if any(k in of for k in ROTINA_RH) or \
           (any(k in capt_blob for k in ROTINA_NCONTRAT) and (meta.get("valor") or 0) >= 1_000_000):
            motivos.append("CAPTURA NÃO BATE (dossiê é ato de rotina, não a árvore de contratação) → re-coletar árvore")
            acao = "recoletar_arvore_contratacao"
            claude_risco = None  # indeterminado: não periciável com este dossiê

        # 4) ELEVAÇÃO por sinal estrutural real (rede de sócio / dispensa-emerg + alto valor / valor redondo)
        score = meta.get("score", 0)
        sinal = [f for f in flags if any(t in f for t in ("rede_socio", "EMERGENCIA", "domina_nicho", "pago>contrato"))]
        if claude_risco is not None and sinal and not legit_mono and (meta.get("valor") or 0) >= 1_000_000:
            claude_risco = max(claude_risco, 7)
            motivos.append("Sinal estrutural (rede/emergência/domínio/aditivo) + valor relevante → mantém atenção")

        # 5) ELEVAÇÃO por ACHADO MATERIAL PRESENTE (gabarito Claude: a Lex fraca subdetecta isto, deu 0–3).
        #    Determinístico — o portão é o layer confiável onde o modelo fraco falha. Lê o red_flags da ficha.
        try: rfl = json.loads(rflags_ficha) if rflags_ficha else []
        except Exception: rfl = []
        blob = (" ".join(str(x) for x in (rfl + indl)) + " " + (obj_ficha or "")).lower()
        mat = []
        if re.search(r"duas atas|dois empenhos|duas notas de empenho|0005.{0,8}0006|fracionament|duplicidade", blob):
            mat.append("duplicidade/fracionamento (atas/NEs mesmo objeto)")
        if re.search(r"@gmail|e-?mail pessoal|não institucional|nao institucional", blob):
            mat.append("e-mail pessoal em ato oficial")
        if re.search(r"importaç(ão|ao) direta|carta de cr[ée]dito|fornecedor estrangeir|proforma", blob):
            mat.append("importação direta/estrangeira sem licitação demonstrada")
        if claude_risco is not None and mat and not legit_mono:
            claude_risco = max(claude_risco, 7)
            motivos.append("Achado material PRESENTE (" + "; ".join(mat) + ") → eleva [gabarito: Lex fraca subdetecta]")
            if acao == "ok": acao = "verificar_autos_integrais"

        diverg = (claude_risco is None) or (abs((claude_risco or 0) - risco) >= 3)
        ds = aprof.get(ns)
        ds_risco = ds["risco"] if ds else None
        ds_diverg = bool(ds and ds_risco is not None and (
            abs(ds_risco - risco) >= 3 or (claude_risco is not None and abs(ds_risco - claude_risco) >= 3)))
        res.append({"sei": ns, "fornecedor": forn, "valor": meta.get("valor"),
                    "objeto_contrato": obj_contrato[:80], "score_triagem": score,
                    "lex_risco": risco, "lex_exec": exe, "claude_risco": claude_risco,
                    "divergencia": diverg, "acao": acao, "motivos": motivos,
                    "lex_indicios": indl[:4],
                    "deepseek_risco": ds_risco, "deepseek_exec": (ds["exec"] if ds else None),
                    "deepseek_resumo": (ds["resumo"] if ds else None), "deepseek_diverge": ds_diverg})

    res.sort(key=lambda x: (-(x["claude_risco"] or 99) if x["claude_risco"] is not None else -98, -(x.get("valor") or 0)))
    json.dump(res, open(OUT, "w"), ensure_ascii=False, indent=1)
    div = sum(1 for x in res if x["divergencia"])
    cap = sum(1 for x in res if x["acao"] == "recoletar_arvore_contratacao")
    nds = sum(1 for x in res if x.get("deepseek_risco") is not None)
    dsd = sum(1 for x in res if x.get("deepseek_diverge"))
    print(f"[reconcilia] periciados(Lex×Claude): {len(res)} | divergências: {div} | captura-rasa: {cap} | "
          f"deepseek(forte): {nds} ({dsd} divergem da Lex/heurística) -> {OUT}")
    for x in res[:12]:
        cr = "INDET" if x["claude_risco"] is None else x["claude_risco"]
        print(f"  {x['sei']:24} lex={x['lex_risco']:>4} claude={cr:>5} {'DIV' if x['divergencia'] else '   '} R$ {(x.get('valor') or 0):>12,.0f} {x['fornecedor'][:22]:22} {(x['motivos'][0] if x['motivos'] else '')[:40]}")

if __name__ == "__main__":
    main()
