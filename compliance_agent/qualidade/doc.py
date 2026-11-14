# -*- coding: utf-8 -*-
"""Gera `docs/REGRAS-DE-QUALIDADE.md` a partir de `config/qualidade_regras.yaml` — o documento não se edita à mão.

Determinístico: depende SÓ do YAML das regras (nada de data de hoje, nada de contagem do código), para que a
catraca de sincronia (`tests/test_regra_registro.py`) não fique vermelha por motivo alheio à regra.
"""
from __future__ import annotations

from pathlib import Path

from compliance_agent.qualidade import regras

SAIDA = regras.REPO / "docs" / "REGRAS-DE-QUALIDADE.md"
_SEV = {"bloqueante": "🔴 Bloqueante", "alta": "🟡 Alta", "media": "🟢 Média"}
_TIPO = {"catraca": "Catraca (barra commit/push)", "sensor": "Sensor (produção)", "juiz": "Juiz (rubrica)",
         "existente": "Verificação já existente", "manual": "⚠ Ainda manual"}
_SIS = {"painel": "Painel", "detectores": "Detectores", "pericias": "Perícias", "relatorios": "Relatórios",
        "lex": "Lex", "yoda": "Yoda/Hermes", "aovivo": "AO VIVO", "vault": "Vault", "coletores": "Coletores",
        "llm": "Modelos", "infra": "Infra"}


def _data_br(iso: str) -> str:
    a, m, d = iso.split("-")
    return f"{d}/{m}/{a}"


def _cel(t: str) -> str:
    return " ".join(str(t).split()).replace("|", "\\|")


def _verificadores(r: regras.Regra) -> str:
    return "<br>".join(f"{_TIPO[v['tipo']]}: `{_cel(v['ref'])}`" if v["tipo"] != "manual"
                       else f"{_TIPO['manual']}: {_cel(v['ref'])}" for v in r.verificadores)


def _ficha(r: regras.Regra) -> list[str]:
    return [
        f"#### {r.id} — {r.titulo}", "",
        "| | |", "|---|---|",
        f"| **Regra** | {_cel(r.enunciado)} |",
        f"| **Por quê** | {_cel(r.porque)} |",
        f"| **Como se mede** | {_cel(r.medida)} |",
        f"| **Onde se aplica** | {', '.join(_SIS[s] for s in r.aplica)} |",
        f"| **Severidade** | {_SEV[r.severidade]} |",
        f"| **Quando viola** | {_cel(r.acao)} |",
        f"| **Verificação** | {_verificadores(r)} |", "",
    ]


def gerar(arq: Path = regras.ARQ) -> str:
    d = regras.bruto(arq)
    rs = regras.carregar(arq)
    res = regras.resumo(arq)
    fam = d["familias"]
    foto = d.get("fotografia_inicial") or {}
    L: list[str] = []
    a = L.append
    a("<!-- GERADO por `python -m compliance_agent.qualidade doc` a partir de config/qualidade_regras.yaml. "
      "NÃO EDITE À MÃO: mude o YAML e regenere (a catraca tests/test_regra_registro.py confere). -->")
    a("")
    a("# Regras de Qualidade do Ecossistema JFN")
    a("**Padrão · Conformidade · Correção · Constância · Juízo — o que toda afirmação ao dono precisa cumprir**")
    a("")
    a("| | |")
    a("|---|---|")
    a(f"| **Versão** | {d['versao']} · {_data_br(str(d['atualizado']))} |")
    a("| **Alcança** | Painel, detectores, perícias, relatórios e dossiês, Lex, Yoda/Hermes, AO VIVO, vault, coletores e modelos |")
    a(f"| **Regras** | {res['total']} — " + " · ".join(f"{fam[f]['nome']} {res['por_familia'][f]}" for f in regras.FAMILIAS) + " |")
    a(f"| **Verificação automática** | {res['automaticas']} de {res['total']} regras têm verificador que roda sozinho; "
      f"{len(res['com_divida'])} ainda têm parte manual (seção 7) |")
    a("| **Fonte única** | `config/qualidade_regras.yaml` (este documento é gerado dele) |")
    a("| **Onde ver o estado** | Painel → Conformidade (`/api/qualidade/conformidade`) · Yoda `/melhorias` · `python -m compliance_agent.qualidade estado` |")
    a("")
    a("> **Leitura obrigatória para toda sessão — humana ou de IA — que mexa em qualquer sistema do JFN.**")
    a("> O dono fiscaliza o Poder Executivo com o que estes sistemas afirmam. Em 13/11/2026 ele determinou: "
      "*\"não pode ter margem pra erro em nada. esse é um projeto de governo\"* e *\"rever tudo com olhar cauteloso, "
      "desconfiando de tudo… caso a caso… nas fontes primárias\"*. No mesmo dia, a revisão cética mostrou que, de 56 "
      "conclusões sobre terceiros, **nenhuma** se confirmava no sentido estrito em fonte primária: 21 refutadas, 27 "
      "com número ou moldura errados, 7 inconclusivas. Estas regras existem para que isso não se repita — e cada uma "
      "roda como verificação automática, porque **regra que não roda é enfeite**.")
    a("")
    a("---")
    a("")
    a("## Sumário")
    a("")
    a("1. [Como usar](#1-como-usar)")
    a("2. [Inventário — o que afirma algo ao dono](#2-inventário--o-que-afirma-algo-ao-dono)")
    a("3. [Vocabulário obrigatório](#3-vocabulário-obrigatório)")
    a("4. [As regras](#4-as-regras)")
    a("5. [Rubricas do juiz](#5-rubricas-do-juiz)")
    a("6. [Como as regras rodam](#6-como-as-regras-rodam)")
    a("7. [Dívida declarada](#7-dívida-declarada)")
    a("8. [Como mudar uma regra](#8-como-mudar-uma-regra)")
    a("")
    a("## 1. Como usar")
    a("")
    a("| Você vai… | Antes de entregar |")
    a("|---|---|")
    a("| criar ou mudar um **card, aba ou rota** | inventariar em `config/qualidade_inventario.yaml` (CST-11); a rota devolve `proveniencia` "
      "(PAD-01, 02, 06, 07); rótulo em linguagem de indício (PAD-08); número e lista do mesmo universo (CST-13) |")
    a("| criar ou mudar um **detector, perícia ou regra** | registrar em `config/qualidade_detectores.yaml` com controle positivo **e** negativo "
      "(COR-03), hipóteses inocentes excluídas por código (COR-05), domínio (COR-10); só vira manchete com taxa de falso positivo medida em "
      "fonte primária (COR-04) |")
    a("| **somar pagamento** | só OB do SIAFE, Contabilizada, não devolvida, uma vez (CNF-02, COR-12); empenho e liquidação não são pagamento (CNF-01) |")
    a("| usar **sanção** | vigente na data do ato **e** com alcance sobre o ente, pelo módulo de abrangência (CNF-03) |")
    a("| escrever **relatório, parecer, caso ou resposta ao dono** | prova primária citada e conferida por código para todo 🔴/🟡 (COR-01); estado "
      "explícito (PAD-02); gate de neutralidade (CNF-15); passar pelas rubricas da seção 5 |")
    a("| chamar **modelo de IA** | modelo barato extrai, o de juízo julga (COR-14); dupla leitura (COR-02); nada de API paga sem teto — e o "
      "juiz só pela assinatura (CNF-10) |")
    a("| mexer no **Yoda/Hermes** | personalização commitada **e** em arquivo de diff; atualização só pelo script seguro (CNF-17) |")
    a("| **corrigir** um número já exibido | conferir o número *servido* (cache, CST-07), propagar a todas as superfícies (CST-01, CST-08) e "
      "registrar errata (CST-14) |")
    a("")
    a("**Severidades.** 🔴 *Bloqueante*: barra commit/push ou tira a afirmação do ar. 🟡 *Alta*: abre item na fila de automelhoria e marca a "
      "superfície EM REVISÃO. 🟢 *Média*: abre item na fila.")
    a("")
    a("## 2. Inventário — o que afirma algo ao dono")
    a("")
    a("O inventário é **vivo**: `config/qualidade_inventario.yaml` (superfícies) e `config/qualidade_detectores.yaml` (quem produz achado) são "
      "confrontados com o código pelas catracas `tests/test_regra_inventario.py` e `tests/test_regra_controles_detector.py`. Superfície nova "
      "sem entrada não passa. Para os números de agora: `python -m compliance_agent.qualidade inventario`.")
    a("")
    if foto:
        a(f"**Fotografia de {_data_br(str(foto['data']))}** (a contagem viva é a do comando acima):")
        a("")
        a("| O que | Quantos | De que fonte | Quem consome |")
        a("|---|---:|---|---|")
        for it in foto["itens"]:
            a(f"| {_cel(it['o_que'])} | {_cel(it['quantos'])} | {_cel(it['fonte'])} | {_cel(it['consome'])} |")
        a("")
    a("## 3. Vocabulário obrigatório")
    a("")
    a("| Termo | Significado | Nunca confundir com |")
    a("|---|---|---|")
    a("| **VERIFICADO** | prova primária citada literalmente e conferida por código | \"saiu do detector\" |")
    a("| **PENDENTE** | indício ainda não conferido na fonte primária, ou leituras que divergem | achado |")
    a("| **INDISPONÍVEL** | a fonte não permite saber (sem coleta, sem acesso, mascarado, fora da cobertura) | zero, \"limpo\", \"sem irregularidade\" |")
    a("| **REFUTADO** | a prova desmente; fica registrado o que derrubou | apagar em silêncio |")
    a("| **CONFIRMADA / PARCIAL / REFUTADA / INCONCLUSIVA** | régua de veredito de revisão; qualquer dúvida residual = INCONCLUSIVA | — |")
    a("| **Pago** | Ordem Bancária do SIAFE, Contabilizada, não devolvida, não anulada | empenhado, liquidado, contratado, teto de ata |")
    a("| **Indício** | sinal que justifica olhar o documento | acusação, conclusão |")
    a("| **Base × primária** | banco de dados é *base*; *primária* é o documento (diário oficial, autos, extrato, cadastro oficial) | — |")
    a("")
    a("## 4. As regras")
    a("")
    a("| Família | Pergunta que responde | Regras | Bloqueantes |")
    a("|---|---|---:|---:|")
    for f in regras.FAMILIAS:
        do = [r for r in rs if r.familia == f]
        a(f"| **{fam[f]['nome']}** ({f}) | {fam[f]['pergunta']} | {len(do)} | {sum(r.severidade == 'bloqueante' for r in do)} |")
    a("")
    for i, f in enumerate(regras.FAMILIAS, 1):
        do = [r for r in rs if r.familia == f]
        a(f"### 4.{i} {fam[f]['nome']} ({f}) — {fam[f]['pergunta']}")
        a("")
        a("| Regra | Enunciado curto | Severidade |")
        a("|---|---|---|")
        for r in do:
            a(f"| {r.id} | {_cel(r.titulo)} | {_SEV[r.severidade]} |")
        a("")
        for r in do:
            L.extend(_ficha(r))
    a("## 5. Rubricas do juiz")
    a("")
    a("O juiz é o Claude **pela assinatura** (nunca API paga), como juiz e co-motor: ele amostra por valor e risco o que o painel, o vault e "
      "o Yoda afirmam e dá nota em cada critério. Nas afirmações já públicas no painel, a cascata gratuita julga a mesma entrada e os dois "
      "vereditos ficam lado a lado no banco de cruzamento — a divergência calibra os outros modelos. O veredito da cascata nunca vale "
      "sozinho. Material do vault vai só ao Claude.")
    a("")
    a("**Escala (vale para todos os critérios)**")
    a("")
    a("| Nota | Significado | Consequência |")
    a("|---:|---|---|")
    cons = {0: "sai do ar; escala ao dono", 1: "violação da regra SUB; abre item", 2: "ressalva; ajuste recomendado", 3: "—", 4: "—"}
    for n, desc in d["escala"].items():
        a(f"| {n} | {_cel(desc)} | {cons[int(n)]} |")
    a("")
    for nome, r in d["rubricas"].items():
        a(f"### {r['regra']} · `{nome}` — {r['pergunta']}")
        a("")
        a("| | |")
        a("|---|---|")
        a(f"| **Âncora ruim** | {_cel(r['ancora_ruim'])} |")
        a(f"| **Âncora boa** | {_cel(r['ancora_boa'])} |")
        a("")
    a("**Quando escalar para humano (o dono decide; o sistema não resolve sozinho)**")
    a("")
    for e in d["escalar_humano"]:
        a(f"- {e}")
    a("")
    a("## 6. Como as regras rodam")
    a("")
    a("| Camada | O que é | Quando roda | Onde ver |")
    a("|---|---|---|---|")
    a("| **Catracas** | `tests/test_regra_*.py` — contam o defeito por arquivo versionado; a dívida só desce, arquivo novo nasce em zero; cada uma "
      "tem a prova de que fica vermelha com o defeito | no portão de pre-push (`tools/pre_push_gate.sh`), no CI e no sensor de catracas da "
      "automelhoria | saída do pytest; base em `tests/golden/qualidade_base.json` |")
    a("| **Sensores** | `compliance_agent/qualidade/sensores.py` — rodam sobre o dado servido (payload das manchetes, casos do vault, respostas "
      "do Yoda, motores, cruzamento) | a cada 3 h, dentro do laço de automelhoria (`tools/automelhoria_geral.py`), e como motor do AO VIVO | "
      "`data/qualidade_estado.json`; fila do Yoda (`/melhorias`); painel de conformidade |")
    a("| **Juiz** | `compliance_agent/qualidade/juiz.py` — rubricas da seção 5, Claude pela assinatura, amostra por valor e risco | uma vez por dia "
      "(cron), dentro do orçamento diário do motor | `data/qualidade_juiz.json`; painel de conformidade |")
    a("| **Painel de conformidade** | `compliance_agent/qualidade/estado.py` → `/api/qualidade/conformidade` — por sistema: regras, violações "
      "abertas, tendência | sob demanda | aba Conformidade |")
    a("")
    a("Comandos: `python -m compliance_agent.qualidade {regras|inventario|sensores|juiz|estado|doc|base --apertar}`.")
    a("")
    a("**Contratos que os verificadores também cumprem.** Sensor que não consegue medir vira problema `sensor:<nome>`, nunca \"ok\" (CST-10). "
      "Sem fotografia dos sensores, o painel de conformidade responde INDISPONÍVEL, não \"0 violações\" (PAD-02). Rodar duas vezes não duplica "
      "(CST-06). Nenhum verificador devolve dado pessoal: CPF sai mascarado na própria mensagem (PAD-04).")
    a("")
    a("## 7. Dívida declarada")
    a("")
    a("Regras cuja verificação ainda tem parte manual. Aparecem no painel de conformidade como dívida — nunca como \"ok\".")
    a("")
    a("| Regra | O que falta automatizar |")
    a("|---|---|")
    for r in rs:
        for falta in r.divida:
            a(f"| {r.id} — {_cel(r.titulo)} | {_cel(falta)} |")
    a("")
    a("A dívida de **código** (o que já existia quando cada catraca nasceu e só pode descer) está em `tests/golden/qualidade_base.json` e "
      "aparece no painel de conformidade por catraca.")
    a("")
    a("## 8. Como mudar uma regra")
    a("")
    a("1. Edite `config/qualidade_regras.yaml` (id novo nunca reutiliza id aposentado). Toda regra precisa de caso real em `porque` e de "
      "verificador em `verificadores`.")
    a("2. Escreva o verificador **com a prova** (o defeito injetado em dado sintético tem de deixá-lo vermelho — COR-15). O repositório é "
      "público: nada de dado real, nome ou CPF em teste.")
    a("3. `python -m compliance_agent.qualidade doc` regenera este documento; `pytest tests/test_regra_registro.py` confere.")
    a("4. Regra nova que nasce com violações antigas: grave a base uma vez (`base --apertar` só desce) e diga no commit quanto ficou de dívida.")
    a("5. Afrouxar regra, subir base ou aposentar regra exige decisão do dono, registrada no commit.")
    a("")
    a("---")
    a("")
    a("*Indício ≠ acusação. INDISPONÍVEL ≠ zero. \"Pago\" é OB Contabilizada, não devolvida. O que vem do banco é base, não primária. "
      "CPF sempre mascarado. Regra que não roda é enfeite.*")
    return "\n".join(L) + "\n"


def gravar(saida: Path = SAIDA) -> Path:
    saida.write_text(gerar(), encoding="utf-8")
    return saida


def em_sincronia(saida: Path = SAIDA) -> bool:
    return saida.exists() and saida.read_text(encoding="utf-8") == gerar()
