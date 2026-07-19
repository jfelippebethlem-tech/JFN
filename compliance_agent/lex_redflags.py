# -*- coding: utf-8 -*-
"""Lex — CONHECIMENTO estático dos red flags + helpers puros (zero I/O).

Catálogo _RF/_MATRIZ, ramos de objeto, grau 🟢🟡🔴, passo exculpatório,
destinatários e elemento subjetivo. Extraído de lex.py (split 2026-07-06);
comportamento idêntico, coberto por tests/test_lex_snapshot.py.
"""
from __future__ import annotations

import re


# Red flags (resumo operacional; detalhe em docs/LEX-BASE-JURIDICA.md)
_RF = {
    "R2": ("Fracionamento de despesa", "Art. 75 §1º Lei 14.133/2021; Art. 23 §§1º-5º Lei 8.666/93"),
    "R3": ("Pesquisa de preços frágil / possível sobrepreço", "Art. 23 Lei 14.133; Acórdão 1875/2021-TCU (cesta de preços)"),
    "R4": ("Sobrepreço / superfaturamento (valores fora de referência)", "Art. 11 III Lei 14.133; Acórdão 2622/2013-TCU (BDI)"),
    "R5": ("Inexigibilidade/dispensa possivelmente indevida", "Art. 74 Lei 14.133 / Art. 25 Lei 8.666; art. 337-E CP"),
    "R6": ("Alteração de controle societário após receita pública relevante", "Art. 14 Lei 14.133/2021 (idoneidade); art. 11 Lei 8.429/92; ACFE — change-of-control/nominee"),
    "R7": ("Restrição de competitividade", "Art. 9º I Lei 14.133; Art. 3º §1º Lei 8.666"),
    "R8": ("Concentração de fornecedor / risco de captura (bid rigging)", "Art. 37 CF/88; Art. 36 §3º I 'd' Lei 12.529; ACFE/OCDE"),
    "R9": ("Aditivos sucessivos acima dos limites", "Arts. 125-126 Lei 14.133; Art. 65 §1º Lei 8.666"),
    "R10": ("Liquidação irregular / pagamento atípico (estornos)", "Arts. 62-63 Lei 4.320/64; Decreto 93.872/86 art. 38"),
    "R11": ("Atividade-fim (CNAE) incompatível com o objeto contratado", "Arts. 62-63 Lei 14.133 (qualificação técnica); art. 337-F CP; ACFE — shell company"),
    "R12": ("Planejamento de fachada (DFD/ETP/TR genéricos)", "Art. 5º e Art. 18 Lei 14.133"),
    "R13": ("Jogo de planilha (sobrepreço recuperado por aditivo após mergulho na licitação)",
            "Arts. 125-126 Lei 14.133/2021; Acórdãos TCU 1.755/2004 e 2.988/2018-Plenário (independe de dolo)"),
    "R14": ("Conluio entre licitantes (rodízio/cobertura/supressão — OCDE)",
            "Art. 90 Lei 14.133/2021 (frustrar/fraudar licitação); Art. 337-F CP; Art. 36 Lei 12.529/2011 (CADE)"),
    # Investigação de Due Diligence (fachada/laranja) — motor investigacao_dd; detalhe na seção II-E.
    "DD/H-END-RESID": ("Sede em endereço de natureza residencial", "art. 337-F CP; art. 11 Lei 8.429/92"),
    "DD/H-END-EXISTE": ("Endereço não confirmado fisicamente (geocodificação)", "art. 337-F CP"),
    "DD/H-COEND": ("Outros fornecedores do Estado na mesma sede", "art. 337-F CP; art. 11 Lei 8.429/92"),
    "DD/H-CAPITAL": ("Capital social ínfimo frente ao recebido", "art. 11 Lei 8.429/92; Art. 69 Lei 14.133"),
    "DD/H-RECENTE": ("Empresa recém-aberta antes do 1º recebimento", "art. 337-F CP"),
    "DD/H-SITUACAO": ("Situação cadastral irregular na Receita", "Art. 14 Lei 14.133; Art. 87 Lei 8.666/93"),
    "DD/H-PORTE": ("Volume recebido acima do teto do porte declarado", "LC 123/2006; Art. 4º Lei 14.133"),
    "DD/H-SOCIO-UNICO": ("Sócio único com sinais de fachada", "art. 337-F CP; art. 11 Lei 8.429/92"),
    "DD/H-PEP": ("Sócio politicamente exposto (PEP) — relação política", "Art. 9º Lei 14.133; Lei 12.813/13; art. 11 Lei 8.429/92"),
    "DD/H-BENEFICIO": ("Beneficiário de programa social de subsistência (laranja)", "art. 337-F CP; art. 11 Lei 8.429/92"),
}


# Anatomia do achado (modelo TCU/ISSAI/CGU — ver docs/PESQUISA-DIREITO-ADMIN-CGE.md e
# docs/PESQUISA-DIREITO-ADMIN-DOUTRINA-RJ.md): critério × condição → causa → efeito, com evidência e
# recomendação. Causa/efeito/recomendação por red flag. Base citável (doutrina/improbidade/controle/RJ) no 2º doc.

# Serviços CONTÍNUOS (Lei 14.133 art. 6º XV; contratos de até 10 anos, arts. 106-107): pluralidade de contratos
# por órgão é NORMAL e NÃO é fracionamento. Usado p/ calibrar o red flag R2 (fracionamento × serviço contínuo).
_SERV_CONTINUO_KW = (
    "limpeza", "conserva", "higieniz", "asseio", "zeladoria", "vigilanc", "vigilânc", "seguranca patrimon",
    "segurança patrimon", "manutenc", "manutenç", "mao de obra", "mão de obra", "mao-de-obra", "posto de trabalho",
    "postos de trabalho", "apoio administrativo", "apoio operacional", "recepc", "recepç", "copeir", "brigad",
    "facilit", "terceiriz", "servico continuad", "serviço continuad", "servicos continu", "serviços contínu",
    "jardinagem", "portaria", "dedetiz", "transporte", "lavanderia", "nutric", "alimentac", "alimentaç",
)


def _eh_servico_continuo(objetos) -> bool:
    """True se os objetos contratuais indicam serviço CONTÍNUO (calibra o R2: não acusar fracionamento)."""
    txt = " ".join((o or "") for o in objetos).lower()
    return any(k in txt for k in _SERV_CONTINUO_KW)


# Classificação grosseira de "ramo/natureza" do objeto — núcleo do teste de fracionamento (mesma natureza).
_RAMOS = {
    "limpeza/conservação": ("limpeza", "conserva", "higieniz", "asseio", "zeladoria", "jardinagem", "dedetiz"),
    "vigilância/segurança": ("vigilanc", "vigilânc", "seguranca", "segurança", "portaria", "brigad"),
    "manutenção/reparo": ("manutenc", "manutenç", "reparo", "reforma", "predial"),
    "obras/engenharia": ("obra", "engenharia", "construç", "construc", "paviment", "infraestrutura"),
    "informática/TI": ("informat", "software", "computad", "notebook", "licenç", "tecnologia da inf"),
    "veículos/transporte": ("veicul", "frota", "transporte", "combustiv", "locaç de veic", "locacao de veic"),
    "material/insumos": ("material", "insumo", "aquisic", "aquisiç", "gênero", "genero", "aliment", "medicament"),
    "mão de obra/apoio": ("mao de obra", "mão de obra", "apoio administrativo", "apoio operacional",
                          "terceiriz", "posto de trabalho", "recepc", "recepç", "copeir"),
    "saúde/serviços médicos": ("hospital", "médic", "medic", "saude", "saúde", "leito", "exame"),
}


def _ramo_objeto(obj) -> str:
    """Natureza grosseira do objeto (p/ agrupar 'mesma natureza' no teste de fracionamento)."""
    t = (obj or "").lower()
    for ramo, kws in _RAMOS.items():
        if any(k in t for k in kws):
            return ramo
    palavras = [w for w in re.findall(r"[a-zçãõáéíóúâêô]+", t) if len(w) > 4][:2]
    return " ".join(palavras) or "objeto"
_MATRIZ = {
    "R2": ("possível divisão da despesa para fugir da modalidade/teto de dispensa",
           "elisão do dever de licitar; restrição à competição e risco de sobrepreço",
           "consolidar a demanda e licitar; apurar o planejamento (DFD/ETP)"),
    "R3": ("instrução deficiente do valor estimado (sem cesta de preços)",
           "risco de sobrepreço não detectado na contratação",
           "exigir pesquisa/cesta de preços (Acórdão 1875/2021-TCU)"),
    "R4": ("ausência de referência de mercado / BDI fora de parâmetro",
           "potencial dano ao erário por preço acima do mercado",
           "recompor preços e, se confirmado, glosar a diferença"),
    "R5": ("enquadramento possivelmente indevido de contratação direta",
           "afastamento da licitação sem amparo legal robusto",
           "verificar a fundamentação (art. 74/75 Lei 14.133); se indevida, anular"),
    "R6": ("controle/administração alterado após a empresa já receber vulto do Estado",
           "possível sucessão/interposição de pessoas (laranja) ou aquisição de empresa 'com contratos'",
           "levantar o histórico de controle (QSA pretérito) e cotejar a troca com a escalada de pagamentos"),
    "R7": ("especificação/habilitação restritiva ou direcionada",
           "redução da competitividade; possível direcionamento",
           "revisar o edital; admitir 'ou equivalente' (art. 9º Lei 14.133)"),
    "R8": ("baixa rotatividade/captura de fornecedor por um órgão",
           "risco de cartel/sobrepreço e dependência do prestador",
           "ampliar a competição; cruzar sócios/endereços dos licitantes"),
    "R9": ("execução além do valor contratado (aditivos sucessivos)",
           "elisão do limite de aditivo (25%/50%) e burla à licitação",
           "auditar os aditivos e os limites (arts. 125-126 Lei 14.133)"),
    "R10": ("falha de liquidação/regularização (estornos, OB R$ 0,00)",
            "risco de pagamento sem liquidação regular",
            "conferir ateste e NL (arts. 62-63 Lei 4.320/64)"),
    "R11": ("atividade econômica de registro (CNAE) diversa do objeto efetivamente contratado",
            "habilitação técnica frágil / empresa de prateleira ou fachada para fim diverso",
            "exigir comprovação de qualificação técnica para o objeto (arts. 62-63 Lei 14.133); "
            "verificar adequação do CNAE e a aptidão operacional real"),
    "R12": ("planejamento de fachada (DFD/ETP/TR genéricos) ou crescimento sem lastro",
            "contratação sem planejamento real; sobre/subdimensionamento",
            "exigir ETP robusto e justificativa da demanda (art. 18 Lei 14.133)"),
}


def _fmt_proc(s: str) -> str:
    """Encurta nº de processo concatenado (a base TCE-RJ às vezes junta vários numa célula)."""
    s = (s or "").strip()
    partes = [p.strip() for p in s.split(",") if p.strip()]
    if len(partes) <= 1:
        return s or "—"
    return f"{partes[0]} (+{len(partes)-1})"


def _anatomia(a: dict) -> dict:
    """Decompõe um indício na anatomia do achado de auditoria (critério/condição/causa/efeito/recomendação)."""
    nome, criterio = _RF.get(a["rf"], (a["rf"], "—"))
    causa, efeito, recom = _MATRIZ.get(a["rf"], ("a apurar", "a apurar", "diligência documental"))
    return {"rf": a["rf"], "nome": nome, "criterio": criterio, "condicao": a["obs"],
            "causa": causa, "efeito": efeito, "recomendacao": recom, "grav": a["grav"]}


def _grau(achados: list) -> tuple:
    """(emoji, rótulo, justificativa) conforme convergência + gravidade dos indícios."""
    n = len(achados)
    gmax = max((a["grav"] for a in achados), default=0)
    if n >= 3 and gmax >= 4:
        return "🔴", "VERMELHO", "convergência de 3+ indícios, ao menos um grave — recomenda-se controle externo"
    if n >= 1 and (gmax >= 4 or n >= 2):
        return "🟡", "AMARELO", "indícios pontuais a esclarecer mediante diligência"
    if n >= 1:
        return "🟡", "AMARELO", "indício isolado de baixa gravidade"
    return "🟢", "VERDE", "sem indícios relevantes nos dados disponíveis — presunção de regularidade mantida"


# ── Passo EXCULPATÓRIO (defesa contra si mesmo) ───────────────────────────────────────────────────
# Para CADA indício, a explicação inocente mais plausível + se os DADOS a refutam. Achado cuja própria
# defesa NÃO é refutada pelos dados (a explicação inocente sobrevive) → rebaixado a "monitoramento" (não
# representação). Protege a credibilidade: indício ≠ acusação; presunção de regularidade. Por família de RF.
_EXCULPATORIO = {
    "R2": "Em serviços contínuos, dispensas emergenciais sucessivas podem cobrir o intervalo entre o fim de "
          "um contrato e a conclusão de novo pregão — fracionamento só se confirma com mesmo objeto/local sob o teto.",
    "R3": "A pesquisa de preços pode existir no processo SEI e apenas não ter sido lida nesta varredura "
          "(documento ausente do recorte ≠ ausência do documento).",
    "R4": "O preço pode refletir composição de custo legítima (BDI, encargos, logística regional) — só há "
          "sobrepreço frente a uma referência de mercado efetivamente apurada.",
    "R5": "A contratação direta pode ter amparo legal robusto e justificado (urgência real documentada, "
          "exclusividade de fato do objeto/marca) — afastamento da licitação nem sempre é irregular.",
    "R6": "A troca de controle societário pode ser sucessão empresarial legítima (herança, venda regular) "
          "sem qualquer interposição de pessoas.",
    "R7": "A especificação restritiva pode decorrer de exigência técnica real do objeto, não de direcionamento.",
    "R8": "A concentração/co-ocorrência pode refletir um mercado regional naturalmente concentrado ou um "
          "ramo de poucos players (ex.: engenharia/consórcio legítimo), sem qualquer conluio.",
    "R9": "Aditivos podem decorrer de fato superveniente legítimo dentro dos limites legais (25%/50%).",
    "R10": "OBs de R$ 0,00 e estornos são, em regra, regularizações contábeis ordinárias, não pagamento irregular.",
    "R11": "O CNAE pode estar desatualizado no cadastro sem que a empresa careça de aptidão operacional real "
           "para o objeto.",
    "R12": "DFD/ETP genéricos podem refletir padronização administrativa, não ausência de planejamento real.",
    "DD": "Sinais cadastrais isolados (endereço residencial, capital baixo, empresa recente) são comuns em "
          "microempresas legítimas e, sozinhos, não caracterizam fachada/laranja.",
}


def _fam_exculpatorio(rf: str) -> str:
    return "DD" if str(rf).startswith("DD/") else str(rf)


def _exculpatorio(achados: list) -> list[dict]:
    """Para cada achado, gera a explicação inocente mais plausível e avalia se os DADOS a refutam.

    A defesa é considerada REFUTADA (achado sobrevive → representação) quando o próprio indício já traz
    convergência/cruzamento confirmatório: gravidade alta (≥3) OU achado de conluio COM sócio em comum.
    Caso contrário a defesa SOBREVIVE → o achado é rebaixado a 'monitoramento' (sobrevive=True). Degrada
    honesto: qualquer falha devolve o achado como representação (não silencia indício). Honestidade: a
    dúvida sobre a economicidade favorece o gestor (presunção de regularidade)."""
    out = []
    for a in achados or []:
        try:
            rf = a.get("rf", "")
            defesa = _EXCULPATORIO.get(_fam_exculpatorio(rf), "Pode haver explicação administrativa regular para o fato.")
            grav = int(a.get("grav", 0) or 0)
            obs = (a.get("obs") or "").lower()
            socio_comum = "sócio" in obs and ("comum" in obs or "irmã" in obs or "compartilh" in obs)
            # Refuta a defesa quando há convergência/cruzamento: gravidade alta OU sócio em comum (cartel forte).
            refuta = grav >= 3 or socio_comum
            sobrevive = not refuta  # defesa sobrevive → achado fraco → monitoramento
            out.append({"rf": rf, "grav": grav, "defesa": defesa,
                        "refuta": ("os dados refutam a defesa (convergência/cruzamento confirmatório) — o "
                                   "indício sobrevive à própria defesa" if refuta else
                                   "os dados NÃO refutam a defesa — a explicação inocente é plausível e não foi "
                                   "afastada"),
                        "sobrevive": sobrevive,
                        "encaminhamento": "monitoramento" if sobrevive else "representação"})
        except Exception:
            out.append({"rf": a.get("rf", ""), "grav": int(a.get("grav", 0) or 0),
                        "defesa": "—", "refuta": "avaliação exculpatória indisponível",
                        "sobrevive": False, "encaminhamento": "representação"})
    return out


# ── Destinatário recomendado por TIPO/família de achado (enquadramento do playbook) ──────────────
# conluio/cartel → MP + CADE · débito/cautelar → TCE-RJ/TCU · improbidade/penal → MP · PAR anticorrupção → CGU/CGE.
_DESTINATARIO_FAMILIA = {
    # família → (rótulo do destinatário, base/motivo). O 'motivo' da família 'improbidade' é DERIVADO dos RFs
    # efetivamente presentes (não cita crime que não disparou) — ver _MOTIVO_IMPROBIDADE_RF e _destinatarios.
    "conluio":     ("MP-RJ + CADE", "conluio/cartel (bid rigging) — atuação simultânea (art. 36 Lei 12.529; art. 337-F CP)"),
    "debito":      ("TCE-RJ / TCU", "débito/medida cautelar — dano ao erário/sobrepreço/liquidação (jurisdição de contas)"),
    "improbidade": ("MP-RJ", "improbidade/penal (Lei 8.429; CP arts. 337-E ss.)"),
    "par":         ("CGU / CGE-RJ", "PAR anticorrupção — fachada/laranja/idoneidade (Lei 12.846; controle interno)"),
}
# Descritor curto por RF para compor o 'motivo' da família 'improbidade' a partir dos achados REAIS (honesto:
# não imputar fracionamento/dispensa/direcionamento se o RF correspondente não disparou). Usa o rótulo de _RF.
_MOTIVO_IMPROBIDADE_RF = {
    "R2": "fracionamento",
    "R5": "dispensa/inexigibilidade indevida",
    "R6": "sucessão/interposição de pessoas (troca de controle)",
    "R7": "direcionamento/restrição à competitividade",
    "R11": "qualificação técnica frágil / empresa de fachada",
    "R12": "planejamento deficiente / escalada de faturamento a justificar",
    "R14": "conluio/fraude à licitação (cartel entre licitantes)",
    "DD": "fachada/laranja",
}
# RF → famílias de destinatário (um achado pode disparar mais de uma família).
_RF_DESTINATARIO = {
    "R2": ("improbidade",),
    "R3": ("debito",),
    "R4": ("debito",),
    "R5": ("improbidade",),
    "R6": ("improbidade", "par"),
    "R7": ("improbidade",),
    "R8": ("conluio",),
    "R9": ("debito",),
    "R10": ("debito",),
    "R11": ("improbidade", "par"),
    "R12": ("improbidade",),
    "R13": ("debito",),
    "R14": ("conluio", "improbidade"),
    "DD": ("par", "improbidade"),
}


# ── Triagem do ELEMENTO SUBJETIVO (ilegalidade × improbidade) — doutrina §5.1 ──────────────────
# Improbidade = ilegalidade QUALIFICADA pelo dolo (Garcia & Pacheco; Medina Osório). Pós-Lei
# 14.230/2021: não há improbidade culposa; exige-se dolo específico; art. 10 exige dano efetivo
# comprovado; art. 11 é rol taxativo. O Lex SÓ aponta indício a apurar — NUNCA afirma dolo. Default =
# irregularidade/erro de gestão (controle de contas/TCE-RJ); só sobe a 'dolo a apurar' quando há SINAL
# de elemento subjetivo desonesto (fachada/laranja/cartel/interposição). NUNCA superdimensiona.
_DOLO_RF = {"R11", "R14"}  # R14 (conluio) é intrinsecamente doloso; R13 (jogo de planilha) NÃO — TCU: independe de dolo
_DOLO_OBS = ("sócio em comum", "socio em comum", "sócios em comum", "irmã", "laranja", "fachada",
             "interposi", "nominee", "cartel", "conluio", "compartilh", "mesma sede", "co-endereço",
             "coendereço", "co-endereco", "testa de ferro")


def _elemento_subjetivo(a: dict) -> tuple[str, str]:
    """Classifica o achado por elemento subjetivo (triagem ilegalidade×improbidade). Conservador:
    só 'dolo a apurar' com sinal desonesto; senão é controle de contas (não improbidade)."""
    rf = a.get("rf", "") or ""
    obs = (a.get("obs") or "").lower()
    dolo = rf in _DOLO_RF or rf.startswith("DD") or rf == "FRAUDE" or any(t in obs for t in _DOLO_OBS)
    if dolo:
        return ("dolo a apurar",
                "há sinal de elemento subjetivo (fachada/laranja/cartel/interposição) — SE confirmados o dolo e "
                "(quando exigível) o dano efetivo, pode tocar improbidade (Lei 8.429 pós-14.230). Apurar antes de afirmar.")
    return ("irregularidade / erro de gestão",
            "sem sinal de dolo → **controle de contas (TCE-RJ), NÃO improbidade**. Improbidade pressupõe elemento "
            "subjetivo desonesto (dolo específico; não há forma culposa pós-Lei 14.230/2021).")


def _destinatarios(achados: list) -> list[dict]:
    """Destinatário(s) recomendado(s) derivado(s) das FAMÍLIAS dos achados presentes (sem duplicar).

    Cartel COM sócio em comum reforça 'conluio'. Degrada honesto: sem achado → lista vazia (presunção
    de regularidade, sem encaminhamento)."""
    fams: list[str] = []
    rfs_por_fam: dict[str, list[str]] = {}
    try:
        for a in achados or []:
            rf = _fam_exculpatorio(a.get("rf", ""))
            for f in _RF_DESTINATARIO.get(rf, ()):
                if f not in fams:
                    fams.append(f)
                if rf not in rfs_por_fam.setdefault(f, []):
                    rfs_por_fam[f].append(rf)
    except Exception:
        fams = []
        rfs_por_fam = {}
    out = []
    for f in fams:
        rotulo, motivo = _DESTINATARIO_FAMILIA.get(f, (f, ""))
        if f == "improbidade":  # motivo DERIVADO dos RFs presentes (honesto: não cita crime que não disparou)
            descr = [d for rf in rfs_por_fam.get(f, []) if (d := _MOTIVO_IMPROBIDADE_RF.get(rf))]
            if descr:
                # de-dup preservando ordem
                vistos: list[str] = []
                for d in descr:
                    if d not in vistos:
                        vistos.append(d)
                motivo = f"improbidade/penal — {'; '.join(vistos)} (Lei 8.429; CP arts. 337-E ss.)"
        out.append({"familia": f, "destinatario": rotulo, "motivo": motivo})
    return out


# ── Jurisdição por ESFERA (federal / estadual-RJ / municipal-Rio) ────────────────────────────────
# Correção de competência: o controle EXTERNO da despesa municipal do Rio é do **TCM-RJ**, não do
# TCE-RJ; o controle interno municipal é a **CGM-Rio** (não a CGE-RJ); o processo administrativo
# sancionador segue o regulamento municipal da Lei 14.133 (e, p/ OS, a Lei Rio 5.026/2019), não a
# Lei estadual 5.427/2009. Default = comportamento estadual atual (não muda parecer de Estado/União).
_JURISDICAO = {
    "municipal-rio": {
        "contas": "TCM-RJ",
        "contas_nome": "Tribunal de Contas do Município do Rio de Janeiro (TCM-RJ)",
        "controle_interno": "CGM-Rio",
        "representacao": "TCM-RJ/MP-RJ",
        "proc_adm": ("regulamento municipal da Lei 14.133/2021 (Decreto Rio) e, p/ organizações "
                     "sociais, a Lei Rio 5.026/2019"),
        "base_competencia": ("art. 31, §1º, CF/88 c/c Lei Orgânica do Município do Rio — controle "
                             "externo da despesa municipal pelo TCM-RJ"),
    },
}
_JURISDICAO_DEFAULT = {   # estadual-rj / federal / indefinido → preserva o comportamento atual
    "contas": "TCE-RJ",
    "contas_nome": "Tribunal de Contas do Estado do Rio de Janeiro (TCE-RJ)",
    "controle_interno": "CGE-RJ",
    "representacao": "TCE-RJ/MP-RJ",
    "proc_adm": "Lei RJ 5.427/2009",
    "base_competencia": "jurisdição de contas sobre a despesa estadual",
}


def jurisdicao(esfera: str) -> dict:
    """Órgão de controle externo/interno e norma sancionatória competentes por esfera.

    ``municipal-rio`` → TCM-RJ / CGM-Rio; demais esferas → TCE-RJ / CGE-RJ (comportamento atual).
    Honestidade: esfera desconhecida cai no default (não chuta competência municipal sem sinal).
    """
    return {"esfera": esfera, **_JURISDICAO.get(esfera, _JURISDICAO_DEFAULT)}


def _primeira_data_pag(p: dict) -> str:
    """Data do PRIMEIRO pagamento (menor `data` entre as linhas das OBs) em ISO, ou '' se indisponível.

    Usada pela investigação de fachada/laranja (H-RECENTE: empresa aberta pouco antes de receber)."""
    import datetime as _dt
    melhor = None
    for ano in (p.get("anos") or []):
        for ln in (p.get("por_ano", {}).get(ano, {}).get("linhas") or []):
            s = str(ln.get("data") or "").strip()
            if not s:
                continue
            d = None
            for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
                try:
                    d = _dt.datetime.strptime(s[:10], fmt).date()
                    break
                except ValueError:
                    continue
            if d and (melhor is None or d < melhor):
                melhor = d
    return melhor.isoformat() if melhor else ""


