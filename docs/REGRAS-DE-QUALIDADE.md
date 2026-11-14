<!-- GERADO por `python -m compliance_agent.qualidade doc` a partir de config/qualidade_regras.yaml. NÃO EDITE À MÃO: mude o YAML e regenere (a catraca tests/test_regra_registro.py confere). -->

# Regras de Qualidade do Ecossistema JFN
**Padrão · Conformidade · Correção · Constância · Juízo — o que toda afirmação ao dono precisa cumprir**

| | |
|---|---|
| **Versão** | 1 · 13/11/2026 |
| **Alcança** | Painel, detectores, perícias, relatórios e dossiês, Lex, Yoda/Hermes, AO VIVO, vault, coletores e modelos |
| **Regras** | 70 — Padrão 12 · Conformidade 17 · Correção 17 · Constância 15 · Subjetivas 9 |
| **Verificação automática** | 70 de 70 regras têm verificador que roda sozinho; 4 ainda têm parte manual (seção 7) |
| **Fonte única** | `config/qualidade_regras.yaml` (este documento é gerado dele) |
| **Onde ver o estado** | Painel → Conformidade (`/api/qualidade/conformidade`) · Yoda `/melhorias` · `python -m compliance_agent.qualidade estado` |

> **Leitura obrigatória para toda sessão — humana ou de IA — que mexa em qualquer sistema do JFN.**
> O dono fiscaliza o Poder Executivo com o que estes sistemas afirmam. Em 13/11/2026 ele determinou: *"não pode ter margem pra erro em nada. esse é um projeto de governo"* e *"rever tudo com olhar cauteloso, desconfiando de tudo… caso a caso… nas fontes primárias"*. No mesmo dia, a revisão cética mostrou que, de 56 conclusões sobre terceiros, **nenhuma** se confirmava no sentido estrito em fonte primária: 21 refutadas, 27 com número ou moldura errados, 7 inconclusivas. Estas regras existem para que isso não se repita — e cada uma roda como verificação automática, porque **regra que não roda é enfeite**.

---

## Sumário

1. [Como usar](#1-como-usar)
2. [Inventário — o que afirma algo ao dono](#2-inventário--o-que-afirma-algo-ao-dono)
3. [Vocabulário obrigatório](#3-vocabulário-obrigatório)
4. [As regras](#4-as-regras)
5. [Rubricas do juiz](#5-rubricas-do-juiz)
6. [Como as regras rodam](#6-como-as-regras-rodam)
7. [Dívida declarada](#7-dívida-declarada)
8. [Como mudar uma regra](#8-como-mudar-uma-regra)

## 1. Como usar

| Você vai… | Antes de entregar |
|---|---|
| criar ou mudar um **card, aba ou rota** | inventariar em `config/qualidade_inventario.yaml` (CST-11); a rota devolve `proveniencia` (PAD-01, 02, 06, 07); rótulo em linguagem de indício (PAD-08); número e lista do mesmo universo (CST-13) |
| criar ou mudar um **detector, perícia ou regra** | registrar em `config/qualidade_detectores.yaml` com controle positivo **e** negativo (COR-03), hipóteses inocentes excluídas por código (COR-05), domínio (COR-10); só vira manchete com taxa de falso positivo medida em fonte primária (COR-04) |
| **somar pagamento** | só OB do SIAFE, Contabilizada, não devolvida, uma vez (CNF-02, COR-12); empenho e liquidação não são pagamento (CNF-01) |
| usar **sanção** | vigente na data do ato **e** com alcance sobre o ente, pelo módulo de abrangência (CNF-03) |
| escrever **relatório, parecer, caso ou resposta ao dono** | prova primária citada e conferida por código para todo 🔴/🟡 (COR-01); estado explícito (PAD-02); gate de neutralidade (CNF-15); passar pelas rubricas da seção 5 |
| chamar **modelo de IA** | modelo barato extrai, o de juízo julga (COR-14); dupla leitura (COR-02); nada de API paga sem teto — e o juiz só pela assinatura (CNF-10) |
| mexer no **Yoda/Hermes** | personalização commitada **e** em arquivo de diff; atualização só pelo script seguro (CNF-17) |
| **corrigir** um número já exibido | conferir o número *servido* (cache, CST-07), propagar a todas as superfícies (CST-01, CST-08) e registrar errata (CST-14) |

**Severidades.** 🔴 *Bloqueante*: barra commit/push ou tira a afirmação do ar. 🟡 *Alta*: abre item na fila de automelhoria e marca a superfície EM REVISÃO. 🟢 *Média*: abre item na fila.

## 2. Inventário — o que afirma algo ao dono

O inventário é **vivo**: `config/qualidade_inventario.yaml` (superfícies) e `config/qualidade_detectores.yaml` (quem produz achado) são confrontados com o código pelas catracas `tests/test_regra_inventario.py` e `tests/test_regra_controles_detector.py`. Superfície nova sem entrada não passa. Para os números de agora: `python -m compliance_agent.qualidade inventario`.

**Fotografia de 13/11/2026** (a contagem viva é a do comando acima):

| O que | Quantos | De que fonte | Quem consome |
|---|---:|---|---|
| Rotas `/api` do painel | 224 (159 afirmam algo sobre terceiros ou sobre o dado; 65 operacionais) | `rotas/*.py`, `server.py`, território e AO VIVO | painel; Yoda (capacidades) |
| Abas do painel | 72 | `static/js/src/entrada.js` (TABS) | dono |
| Manchetes do cockpit | 12 cards e 7 chips da mesa | rotas de cruzamento, comparador de preços, alertas e frescor | dono (primeira tela); Yoda |
| Indicadores (KPI) nas demais abas | 290 | `static/js/src/abas/` | dono |
| Detectores, perícias e regras que produzem afirmação sobre terceiros | 134 (42 detectores do registro, 23 cruzamentos, 17 regras do motor de alertas, 20 regras da análise de gestão, 32 módulos e ferramentas) | `config/qualidade_detectores.yaml` | painel, relatórios, Lex, Yoda |
| Relatórios, dossiês e pareceres | 13 produtos | `compliance_agent/reporting/`, `dossie*.py`, `lex_render.py`, `pericia_contabil.py` | dono (PDF, md, planilha); Yoda |
| Arquivos de dados que alimentam rotas | 19 | `data/` (cada um com gerador versionado) | painel |
| Peças do Lex | 14 | `compliance_agent/lex*.py`, `tools/lex_*.py` | parecer 🟢🟡🔴 em relatório; Telegram |
| Yoda/Hermes | 93 capacidades (91 ferramentas), 4 plugins com 18 comandos | `capabilities.yaml`; plugins `jfn-*` do Hermes | dono (Telegram, texto e voz) |
| Motores do AO VIVO | 33 (27 motores, 6 de infraestrutura) | `compliance_agent/aovivo/motores.yaml` | painel (reator); automelhoria |
| Agendamentos que entregam algo ao dono | 12 | cron e timers do usuário | dono (Telegram) |

## 3. Vocabulário obrigatório

| Termo | Significado | Nunca confundir com |
|---|---|---|
| **VERIFICADO** | prova primária citada literalmente e conferida por código | "saiu do detector" |
| **PENDENTE** | indício ainda não conferido na fonte primária, ou leituras que divergem | achado |
| **INDISPONÍVEL** | a fonte não permite saber (sem coleta, sem acesso, mascarado, fora da cobertura) | zero, "limpo", "sem irregularidade" |
| **REFUTADO** | a prova desmente; fica registrado o que derrubou | apagar em silêncio |
| **CONFIRMADA / PARCIAL / REFUTADA / INCONCLUSIVA** | régua de veredito de revisão; qualquer dúvida residual = INCONCLUSIVA | — |
| **Pago** | Ordem Bancária do SIAFE, Contabilizada, não devolvida, não anulada | empenhado, liquidado, contratado, teto de ata |
| **Indício** | sinal que justifica olhar o documento | acusação, conclusão |
| **Base × primária** | banco de dados é *base*; *primária* é o documento (diário oficial, autos, extrato, cadastro oficial) | — |

## 4. As regras

| Família | Pergunta que responde | Regras | Bloqueantes |
|---|---|---:|---:|
| **Padrão** (PAD) | A afirmação tem a forma obrigatória? | 12 | 3 |
| **Conformidade** (CNF) | Respeita a norma e as regras da casa? | 17 | 8 |
| **Correção** (COR) | É verdade, e foi provado? | 17 | 8 |
| **Constância** (CST) | Diz a mesma coisa em todo lugar e continua dizendo amanhã? | 15 | 3 |
| **Subjetivas** (SUB) | Um leitor exigente aceitaria? | 9 | 3 |

### 4.1 Padrão (PAD) — A afirmação tem a forma obrigatória?

| Regra | Enunciado curto | Severidade |
|---|---|---|
| PAD-01 | Proveniência em toda afirmação numérica | 🟡 Alta |
| PAD-02 | Estado explícito — VERIFICADO, PENDENTE, INDISPONÍVEL ou REFUTADO | 🟡 Alta |
| PAD-03 | Moeda com separador de milhar e duas casas | 🟢 Média |
| PAD-04 | CPF sempre mascarado e pessoa física só com vínculo documentado | 🔴 Bloqueante |
| PAD-05 | "N de M" em toda lista cortada | 🟡 Alta |
| PAD-06 | Esfera e Poder explícitos | 🟡 Alta |
| PAD-07 | Natureza do valor declarada | 🟡 Alta |
| PAD-08 | Linguagem de indício, nunca de acusação | 🔴 Bloqueante |
| PAD-09 | Data rotulada pelo que é | 🟡 Alta |
| PAD-10 | Achado com identidade — código, período, unidade | 🟢 Média |
| PAD-11 | Entregável com acabamento de consultoria e sem corte silencioso | 🟡 Alta |
| PAD-12 | Grau de risco com escala e critério, nunca fixado à mão | 🔴 Bloqueante |

#### PAD-01 — Proveniência em toda afirmação numérica

| | |
|---|---|
| **Regra** | Todo número exibido ao dono (card, manchete, tabela, mensagem, relatório) traz, no mesmo lugar ou a um clique, a FONTE (sistema e tabela/documento), a DATA DE REFERÊNCIA do dado e a COBERTURA (que fração do universo a fonte enxerga). No painel, o payload da rota carrega o bloco `proveniencia` com `fonte`, `data_ref` e `cobertura`. |
| **Por quê** | Revisão cética de 13/11/2026: "economia potencial R$ 5,98 mi" era teto teórico, 89% de outra esfera, e a tela não dizia de onde vinha; a base de OB cobria 21% do universo quando as primeiras somas foram lidas como total. |
| **Como se mede** | Sensor lê o payload de cada rota de manchete inventariada e conta as que não têm `proveniencia` completa. Meta: 0 manchete sem proveniência. |
| **Onde se aplica** | Painel, Relatórios, Yoda/Hermes, Lex, Vault |
| **Severidade** | 🟡 Alta |
| **Quando viola** | Abre item por rota; a manchete passa a ser exibida com o selo "sem proveniência" até a rota declarar. |
| **Verificação** | Sensor (produção): `proveniencia`<br>Catraca (barra commit/push): `tests/test_regra_verificadores.py::test_proveniencia_incompleta_e_acusada` |

#### PAD-02 — Estado explícito — VERIFICADO, PENDENTE, INDISPONÍVEL ou REFUTADO

| | |
|---|---|
| **Regra** | Toda afirmação sobre terceiros carrega um estado. VERIFICADO só com prova primária conferida (COR-01); o que saiu de detector e ainda não foi conferido é PENDENTE; o que a fonte não permite saber é INDISPONÍVEL — nunca zero, nunca "limpo", nunca "sem irregularidade". Ausência de dado jamais vira número. |
| **Por quê** | Perícia contábil de 13/11/2026: 452 contratos (R$ 771,27 mi, 98,4% do "pago a menor") eram "credor sem OB na base" — lacuna de coleta apresentada como déficit de pagamento. |
| **Como se mede** | Sensor conta manchetes cujo payload não traz `estado` em {VERIFICADO, PENDENTE, INDISPONIVEL, REFUTADO}; catraca prova que o verificador recusa estado ausente ou fora do vocabulário. |
| **Onde se aplica** | Painel, Detectores, Perícias, Relatórios, Yoda/Hermes, Lex, Vault |
| **Severidade** | 🟡 Alta |
| **Quando viola** | Abre item; afirmação sem estado é tratada como PENDENTE em qualquer entregável. |
| **Verificação** | Sensor (produção): `proveniencia`<br>Catraca (barra commit/push): `tests/test_regra_verificadores.py::test_estado_fora_do_vocabulario_e_acusado`<br>Verificação já existente: `compliance_agent/llm/verificacao.py` |

#### PAD-03 — Moeda com separador de milhar e duas casas

| | |
|---|---|
| **Regra** | Valor em reais sai como "R$ 1.234.567,89". Forma abreviada (mi, bi) só em manchete e sempre com o valor exato a um clique ou entre parênteses. Nunca ponto decimal, nunca valor sem "R$", nunca arredondamento que mude a ordem de grandeza. |
| **Por quê** | Regra permanente do dono (estética de consultoria). Um número abreviado sem o exato impediu conferir a manchete "empresa morta" contra a base (R$ 592,8 mi → ~R$ 16,4 mi). |
| **Como se mede** | Verificador de texto acusa "R$" seguido de número fora do padrão; sensor aplica em entregáveis e respostas amostradas. |
| **Onde se aplica** | Painel, Relatórios, Yoda/Hermes, Lex, Vault |
| **Severidade** | 🟢 Média |
| **Quando viola** | Abre item com o trecho; em relatório, o gate de entrega recusa. |
| **Verificação** | Catraca (barra commit/push): `tests/test_regra_verificadores.py::test_moeda_fora_do_padrao_e_acusada`<br>Verificação já existente: `tests/test_moeda_padrao_brasileiro.py`<br>Sensor (produção): `texto_entregue` |

#### PAD-04 — CPF sempre mascarado e pessoa física só com vínculo documentado

| | |
|---|---|
| **Regra** | CPF aparece como "***.123.456-**" em qualquer superfície. Pessoa física só é nominada quando há documento que a liga ao fato (ato de nomeação, QSA, assinatura nos autos); soma ou inferência estatística nunca nomeia pessoa. |
| **Por quê** | 13/11/2026: 58.253 alertas "de gravidade alta" nomeavam servidores por soma de remunerações de pessoas diferentes agrupadas pelo mesmo CPF mascarado — erro de fato e risco de LGPD ao mesmo tempo. |
| **Como se mede** | Verificador acusa CPF com 11 dígitos visíveis (formatado ou não, com dígito verificador válido) em texto servido; sensor aplica nos payloads amostrados, nos JSON do painel e nas respostas do Yoda. |
| **Onde se aplica** | Painel, Detectores, Relatórios, Yoda/Hermes, Lex, Vault |
| **Severidade** | 🔴 Bloqueante |
| **Quando viola** | Tira a afirmação do ar (a rota é marcada EM REVISÃO), abre item 🆘 e avisa o dono. |
| **Verificação** | Catraca (barra commit/push): `tests/test_regra_verificadores.py::test_cpf_exposto_e_acusado`<br>Sensor (produção): `texto_entregue`<br>Sensor (produção): `payloads_painel` |

#### PAD-05 — "N de M" em toda lista cortada

| | |
|---|---|
| **Regra** | Lista que não mostra tudo diz quantos mostra e de quantos ("10 de 146"), e por qual critério cortou. Total exibido ao lado de lista cortada é o total do UNIVERSO, com a lista completa acessível. Pergunta-se quais N, nunca só quantos. |
| **Por quê** | O PDF de órgão perdia ~55% do conteúdo sem avisar; a leitura do SEI informava "40 documentos" sem dizer quais; o sinal `fenix` do radar truncava em 120 em silêncio. |
| **Como se mede** | Sensor acusa payload com lista de tamanho igual a um limite conhecido (COR-07) sem campo de total; gate de entregável existente. |
| **Onde se aplica** | Painel, Relatórios, Yoda/Hermes, Lex |
| **Severidade** | 🟡 Alta |
| **Quando viola** | Abre item; em relatório, o gate de integridade recusa a entrega. |
| **Verificação** | Verificação já existente: `tests/test_entregavel_integro.py`<br>Sensor (produção): `payloads_painel` |

#### PAD-06 — Esfera e Poder explícitos

| | |
|---|---|
| **Regra** | Toda afirmação diz de que ente e Poder trata: Executivo estadual, Prefeitura do Rio, outro município, União, Judiciário, Legislativo. Somas nunca misturam esferas; card que soma mais de uma mostra a quebra. |
| **Por quê** | 13/11/2026: o herói "economia" somava Estado e Prefeitura (89% Prefeitura); um "cluster de fachada" era do Fundo do Tribunal de Justiça (outro Poder); um 🔴 10/10 era contrato federal; outro, municipal. |
| **Como se mede** | Sensor acusa manchete sem `esfera` no bloco de proveniência; juiz avalia mistura de esferas (SUB-02). |
| **Onde se aplica** | Painel, Detectores, Perícias, Relatórios, Yoda/Hermes, Lex, Vault |
| **Severidade** | 🟡 Alta |
| **Quando viola** | Abre item; afirmação de outro Poder/ente sai das manchetes do Executivo estadual. |
| **Verificação** | Sensor (produção): `proveniencia`<br>Juiz (rubrica): `moldura` |

#### PAD-07 — Natureza do valor declarada

| | |
|---|---|
| **Regra** | Todo valor diz o que é: estimado, teto de ata, contratado, empenhado, liquidado ou PAGO. "Pago" é reservado a Ordem Bancária do SIAFE (CNF-01, CNF-02). O rótulo acompanha o número na mesma frase ou coluna. |
| **Por quê** | 13/11/2026: "contrato de R$ 43 mi assinado no 3º dia" era ata de registro de preços (teto), sem nenhuma OB; "R$ 2,47 bi pagos" a ME/EPP era soma de picos anuais. |
| **Como se mede** | Verificador acusa frase com "pago/pagou/recebeu" e valor cuja natureza declarada na proveniência não é OB; sensor confere `natureza` no bloco de proveniência das manchetes. |
| **Onde se aplica** | Painel, Detectores, Perícias, Relatórios, Yoda/Hermes, Lex, Vault |
| **Severidade** | 🟡 Alta |
| **Quando viola** | Abre item; manchete sem natureza ganha o selo "natureza não declarada". |
| **Verificação** | Sensor (produção): `proveniencia`<br>Catraca (barra commit/push): `tests/test_regra_verificadores.py::test_natureza_ausente_e_acusada` |

#### PAD-08 — Linguagem de indício, nunca de acusação

| | |
|---|---|
| **Regra** | Rótulo, título, card, ticker e texto fixo usam linguagem de indício ("indício de", "a verificar", "sinal"). Os termos fraude, fantasma, fachada, laranja, desvio, corrupção, crime, criminoso, quadrilha e esquema só aparecem quando (a) citam literalmente documento oficial que usa a palavra, ou (b) nomeiam a hipótese com qualificador de indício na mesma frase. Nunca como predicado de pessoa ou empresa. |
| **Por quê** | 13/11/2026: card "concentra fraude 2,12×" media sanção de qualquer época e ente; "fachada/fantasma já registrados: R$ 103,4 mi" não tinha nenhuma fachada documentada. |
| **Como se mede** | Catraca-catraca: contagem de termos acusatórios sem qualificador em `static/js/src`, `static/*.html` e textos fixos de detectores só pode diminuir. Sensor aplica o mesmo verificador no que é servido. |
| **Onde se aplica** | Painel, Detectores, Relatórios, Yoda/Hermes, Lex, Vault |
| **Severidade** | 🔴 Bloqueante |
| **Quando viola** | Catraca barra o commit que aumenta a contagem; em produção, abre item e o gate de neutralidade recusa o entregável. |
| **Verificação** | Catraca (barra commit/push): `tests/test_regra_catracas.py::test_linguagem_painel_so_desce`<br>Verificação já existente: `compliance_agent/reporting/neutralidade.py`<br>Sensor (produção): `texto_entregue`<br>Juiz (rubrica): `presuncao` |

#### PAD-09 — Data rotulada pelo que é

| | |
|---|---|
| **Regra** | Data de assinatura, de publicação, de registro no tribunal, de emissão, de competência e de coleta são campos diferentes e são rotulados como tais. "Assinado em" só com a data do ato (diário oficial ou instrumento); data de registro nunca é apresentada como data do ato. |
| **Por quê** | 13/11/2026: `data_contratacao` (registro no TCE-RJ) foi lida como assinatura — "assinado no 3º dia da gestão" para atos de fevereiro e março, do governo anterior. |
| **Como se mede** | Juiz confere a moldura temporal das afirmações amostradas; revisão por caso quando a afirmação atribui o ato a uma gestão. |
| **Onde se aplica** | Detectores, Perícias, Relatórios, Vault, Painel |
| **Severidade** | 🟡 Alta |
| **Quando viola** | Abre item; afirmação de autoria temporal sem data do ato volta a PENDENTE. |
| **Verificação** | Juiz (rubrica): `moldura`<br>⚠ Ainda manual: falta dicionário de colunas de data por tabela (qual é ato, qual é registro) para a catraca cobrar o rótulo |

#### PAD-10 — Achado com identidade — código, período, unidade

| | |
|---|---|
| **Regra** | Todo achado tem código de regra/detector, período, unidade gestora e chave do objeto (contrato, processo, OB). Achado "sem código" ou em balde genérico não é exibido. |
| **Por quê** | Fila de achados sem código virou balde anônimo — impossível medir falso positivo por detector ou retificar. |
| **Como se mede** | Sensor conta alertas abertos sem tipo/código ou sem chave de objeto. |
| **Onde se aplica** | Detectores, Perícias, Painel, Lex |
| **Severidade** | 🟢 Média |
| **Quando viola** | Abre item com a contagem por origem. |
| **Verificação** | Sensor (produção): `alertas_base` |

#### PAD-11 — Entregável com acabamento de consultoria e sem corte silencioso

| | |
|---|---|
| **Regra** | Relatório, dossiê e parecer saem com capa, seções numeradas, tabelas alinhadas, escala de risco explícita, fontes e normas citadas, e o MESMO conteúdo em md, PDF e planilha. Nada é cortado para caber. |
| **Por quê** | Regra permanente do dono; o PDF de órgão perdia mais da metade do conteúdo sem avisar. |
| **Como se mede** | Gate de integridade do entregável (existente) e nota do juiz no critério de acabamento. |
| **Onde se aplica** | Relatórios, Lex, Vault |
| **Severidade** | 🟡 Alta |
| **Quando viola** | O gate recusa a entrega; nota baixa do juiz abre item. |
| **Verificação** | Verificação já existente: `tests/test_entregavel_integro.py`<br>Juiz (rubrica): `acabamento` |

#### PAD-12 — Grau de risco com escala e critério, nunca fixado à mão

| | |
|---|---|
| **Regra** | 🔴🟡🟢 e score saem de critério escrito e aplicado por código, com a escala visível (ex.: 0–10). É proibido fixar grau por CNPJ, nome ou processo dentro de código ou de gerador. Mudança manual de grau é registro datado no caso, com o motivo. |
| **Por quê** | 13/11/2026: o gerador da análise de gestão tinha 🔴 fixado por CNPJ; casos do vault mantinham `grau: alto` com desfecho 🟢 no corpo. |
| **Como se mede** | Catraca-catraca: literais de CNPJ (14 dígitos) em código de detector/gerador só podem diminuir; sensor do vault acusa caso com grau no frontmatter em conflito com o desfecho do corpo (CST-08). |
| **Onde se aplica** | Detectores, Perícias, Relatórios, Vault, Painel |
| **Severidade** | 🔴 Bloqueante |
| **Quando viola** | Catraca barra; no vault, abre item por caso incoerente. |
| **Verificação** | Catraca (barra commit/push): `tests/test_regra_catracas.py::test_cnpj_literal_no_codigo_so_desce`<br>Sensor (produção): `vault_casos` |

### 4.2 Conformidade (CNF) — Respeita a norma e as regras da casa?

| Regra | Enunciado curto | Severidade |
|---|---|---|
| CNF-01 | Empenho ≠ liquidação ≠ pagamento | 🔴 Bloqueante |
| CNF-02 | Pago = OB do SIAFE, Contabilizada, não devolvida e não anulada | 🔴 Bloqueante |
| CNF-03 | Sanção só se vigente na data do ato e com alcance sobre o ente | 🔴 Bloqueante |
| CNF-04 | Ata de registro de preços não é compra | 🟡 Alta |
| CNF-05 | Preço só se compara na mesma unidade e no mesmo objeto | 🟡 Alta |
| CNF-06 | Teto legal de fonte única, do ano do ato, com limite inclusivo | 🔴 Bloqueante |
| CNF-07 | Acúmulo de cargos respeita as exceções constitucionais | 🟡 Alta |
| CNF-08 | Repositório público sem dado pessoal | 🔴 Bloqueante |
| CNF-09 | Acesso ao SEI e ao SIAFE nunca é culpado | 🟡 Alta |
| CNF-10 | Nenhuma API paga sem teto; juízo do Claude só pela assinatura | 🔴 Bloqueante |
| CNF-11 | Régua contratual não se aplica a parceria, repasse ou sob demanda | 🟡 Alta |
| CNF-12 | Competência do mandato — o que é do Executivo estadual e o que se encaminha | 🟢 Média |
| CNF-13 | Limite anual se mede no exercício do ato | 🟡 Alta |
| CNF-14 | Segredo nunca em código, log, mensagem ou commit | 🔴 Bloqueante |
| CNF-15 | Presunção de legitimidade e gate de neutralidade em tudo que sai da casa | 🔴 Bloqueante |
| CNF-16 | Operação que não derruba a casa | 🟡 Alta |
| CNF-17 | Yoda/Hermes — personalização que sobrevive a atualização | 🟡 Alta |

#### CNF-01 — Empenho ≠ liquidação ≠ pagamento

| | |
|---|---|
| **Regra** | Os três estágios da despesa (Lei 4.320/1964, arts. 58 a 65) nunca se confundem. Empenho é valor bruto que pode ser anulado; liquidação reconhece o direito; só a Ordem Bancária é pagamento. Nenhuma superfície apresenta empenho ou liquidação como "pago", nem soma estágios diferentes. |
| **Por quê** | Regra de ouro do dono desde o início do projeto; empenho citado como "total pago" já inflou relatório. |
| **Como se mede** | Verificador de texto (PAD-07) e juiz no critério de moldura; catraca do verificador. |
| **Onde se aplica** | Painel, Detectores, Perícias, Relatórios, Yoda/Hermes, Lex, Vault |
| **Severidade** | 🔴 Bloqueante |
| **Quando viola** | Entregável recusado; no painel, a afirmação sai do ar até a correção. |
| **Verificação** | Catraca (barra commit/push): `tests/test_regra_verificadores.py::test_empenho_apresentado_como_pago_e_acusado`<br>Juiz (rubrica): `moldura` |

#### CNF-02 — Pago = OB do SIAFE, Contabilizada, não devolvida e não anulada

| | |
|---|---|
| **Regra** | Soma de pagamento usa só OB do SIAFE com status Contabilizado, exclui OB com Guia de Devolução ou `status_envio` de erro no pagamento, descarta linha sem número de OB e conta uma única vez a reemissão para a mesma nota de liquidação. O espelho de transparência não é fonte de pagamento. |
| **Por quê** | 13/11/2026: a perícia somou OB devolvida pelo banco e a reemissão — dos 10 maiores "pago a maior", 0 se confirmaram; 174 de 208 "duplicidades" eram devolução + reemissão. Em 24/09/2026, 7 detectores somavam OB anulada (R$ 13,99 bi na base). |
| **Como se mede** | Catraca-catraca em TODO o repositório (não em lista fixa de arquivos): consulta a `ob_orcamentaria_siafe` sem o filtro de OB paga só pode diminuir, e arquivo novo nasce em zero. |
| **Onde se aplica** | Detectores, Perícias, Relatórios, Painel, Yoda/Hermes |
| **Severidade** | 🔴 Bloqueante |
| **Quando viola** | Catraca barra o commit; número já exibido que dependia da consulta volta a PENDENTE. |
| **Verificação** | Catraca (barra commit/push): `tests/test_regra_catracas.py::test_ob_sem_filtro_de_paga_so_desce`<br>Verificação já existente: `tests/test_catraca_ob_so_contabilizada.py` |

#### CNF-03 — Sanção só se vigente na data do ato e com alcance sobre o ente

| | |
|---|---|
| **Regra** | Sanção só sustenta achado quando (a) estava vigente na data do ato examinado (contratação ou pagamento, o que a norma vedar) e (b) tem alcance sobre o ente contratante: declaração de inidoneidade alcança todos os entes; impedimento alcança o ente sancionador; suspensão alcança o órgão sancionador (Lei 14.133/2021, art. 156, §§ 4º e 5º; Lei 8.666/1993, art. 87, III e IV; Lei 13.019/2014, art. 73). Classifica-se pela fundamentação legal antes da categoria; sem data de fim ≠ vigente. |
| **Por quê** | 13/11/2026: "sancionada paga na vigência — R$ 333,3 mi" tinha 56% de sanção de outro ente sem alcance no Estado; "caro + suspeito" tinha 0 de 5 sancionados à época; uma suspensão "no órgão sancionador" federal foi lida como impedimento do Estado. |
| **Como se mede** | Catraca-catraca: módulo que lê tabela de sanções (CEIS/CNEP/TCE) sem passar por `sancao_abrangencia` só pode diminuir. |
| **Onde se aplica** | Detectores, Perícias, Relatórios, Painel, Lex |
| **Severidade** | 🔴 Bloqueante |
| **Quando viola** | Catraca barra; achado de sanção sem alcance provado vira sinal de peso baixo e PENDENTE. |
| **Verificação** | Catraca (barra commit/push): `tests/test_regra_catracas.py::test_sancao_sem_alcance_so_desce` |

#### CNF-04 — Ata de registro de preços não é compra

| | |
|---|---|
| **Regra** | Ata de registro de preços (Lei 14.133/2021, arts. 82 a 86) é teto, sem obrigação de contratar. Nunca entra em soma de "contratado", "gasto" ou "economia"; o valor só conta pelo que foi efetivamente contratado ou pago. |
| **Por quê** | 13/11/2026: ata de R$ 43 mi apresentada como contrato assinado; os maiores certames da "economia potencial" eram atas — efetivamente pago: INDISPONÍVEL. |
| **Como se mede** | Juiz no critério de moldura; revisão por caso em toda manchete de valor contratado. |
| **Onde se aplica** | Detectores, Perícias, Relatórios, Painel, Lex |
| **Severidade** | 🟡 Alta |
| **Quando viola** | Abre item; valor de ata é reclassificado como "teto de ata" (PAD-07). |
| **Verificação** | Juiz (rubrica): `moldura`<br>⚠ Ainda manual: falta marcador de ata SRP na tabela de contratos/certames para a catraca cobrar a exclusão nas somas |

#### CNF-05 — Preço só se compara na mesma unidade e no mesmo objeto

| | |
|---|---|
| **Regra** | Comparação de preço exige mesma unidade de fornecimento, mesmo objeto e mesma época (Lei 14.133/2021, art. 23). Descrição genérica não é mesmo objeto. Inexigibilidade e compra da agricultura familiar não entram em comparador de mercado. |
| **Por quê** | 25/07/2026: 60% da "economia potencial" comparava produtos diferentes sob rótulo genérico (R$ 15,6 mi → R$ 6,2 mi); 13/11/2026: caiu de R$ 5,98 mi para R$ 13 mil no conjunto confirmado. |
| **Como se mede** | Controle negativo do comparador (par de unidades diferentes não gera economia) e juiz nas manchetes de economia. |
| **Onde se aplica** | Detectores, Painel, Relatórios |
| **Severidade** | 🟡 Alta |
| **Quando viola** | Abre item; economia só vira manchete no conjunto de pares confirmados. |
| **Verificação** | Catraca (barra commit/push): `tests/test_regra_controles_detector.py`<br>Juiz (rubrica): `moldura` |

#### CNF-06 — Teto legal de fonte única, do ano do ato, com limite inclusivo

| | |
|---|---|
| **Regra** | Tetos legais (dispensa da Lei 14.133/2021, art. 75, e seus decretos de atualização; receita de ME/EPP da LC 123/2006, art. 3º; limites de aditivo do art. 125) vivem em UM módulo, indexados por ano, e são aplicados com o valor do ano do ato. "Até" é inclusivo. Nenhuma cópia literal do valor em outro arquivo. |
| **Por quê** | Três cópias divergentes do teto de dispensa; um teste travava o valor errado; nove centavos de diferença num teto legal mudavam a lista de fracionamento. |
| **Como se mede** | Catraca-catraca: literal de teto legal fora do módulo canônico só pode diminuir. |
| **Onde se aplica** | Detectores, Perícias, Lex |
| **Severidade** | 🔴 Bloqueante |
| **Quando viola** | Catraca barra o commit. |
| **Verificação** | Catraca (barra commit/push): `tests/test_regra_catracas.py::test_teto_legal_copiado_so_desce` |

#### CNF-07 — Acúmulo de cargos respeita as exceções constitucionais

| | |
|---|---|
| **Regra** | Alerta de acúmulo exclui, antes de alertar, as hipóteses lícitas da Constituição (art. 37, XVI: dois cargos de professor; professor com técnico ou científico; dois de profissional de saúde) e exige identidade provada (COR-06). |
| **Por quê** | 13/11/2026 — os alertas de acúmulo não excluíam as exceções e agrupavam pessoas diferentes. |
| **Como se mede** | Controle negativo do detector de acúmulo (dois vínculos de professor não alertam). |
| **Onde se aplica** | Detectores, Painel |
| **Severidade** | 🟡 Alta |
| **Quando viola** | Abre item; alertas da regra voltam a PENDENTE. |
| **Verificação** | Catraca (barra commit/push): `tests/test_regra_controles_detector.py` |

#### CNF-08 — Repositório público sem dado pessoal

| | |
|---|---|
| **Regra** | O repositório do JFN é público. Nenhum arquivo versionado contém CPF, nome de pessoa física investigada, endereço residencial, telefone ou e-mail pessoal (LGPD, Lei 13.709/2018, arts. 6º e 7º). Testes usam dados sintéticos. Casos, eleição e material pessoal vivem fora do repositório. |
| **Por quê** | O repositório é público; material de eleição já teve de ser retirado; fixture escrita com dado real já ocorreu. |
| **Como se mede** | Catraca-catraca: CPF com dígito verificador válido em arquivo versionado só pode diminuir (arquivo novo nasce em zero). |
| **Onde se aplica** | Infra, Detectores, Relatórios |
| **Severidade** | 🔴 Bloqueante |
| **Quando viola** | Catraca barra o commit. |
| **Verificação** | Catraca (barra commit/push): `tests/test_regra_catracas.py::test_cpf_versionado_so_desce` |

#### CNF-09 — Acesso ao SEI e ao SIAFE nunca é culpado

| | |
|---|---|
| **Regra** | Falha de coleta no SEI ou no SIAFE é defeito nosso até um controle positivo (consulta que sabidamente retorna) provar o contrário na mesma sessão. Nenhuma superfície escreve "acesso negado", "WAF" ou "indisponível na fonte" sem o controle registrado. |
| **Por quê** | Em quatro ocasiões o "bloqueio" era bug nosso (corrida de espera, índice de menu, popup engolido, senha expirada). |
| **Como se mede** | Verificador de texto acusa mensagem de culpa ao acesso sem a marca de controle positivo; sensor nos logs de coleta amostrados. |
| **Onde se aplica** | Coletores, Yoda/Hermes, AO VIVO, Relatórios |
| **Severidade** | 🟡 Alta |
| **Quando viola** | Abre item; a afirmação de bloqueio é substituída por INDISPONÍVEL com o motivo técnico medido. |
| **Verificação** | Catraca (barra commit/push): `tests/test_regra_verificadores.py::test_culpa_ao_acesso_sem_controle_e_acusada`<br>Sensor (produção): `texto_entregue` |

#### CNF-10 — Nenhuma API paga sem teto; juízo do Claude só pela assinatura

| | |
|---|---|
| **Regra** | Nenhum código chama API paga sem teto em dinheiro, registro de gasto e chave fora do código. Nunca se supõe camada gratuita. O juiz de qualidade e toda chamada feita em nome do Fable saem pela assinatura (CLI), com `backend="cli"`, sem chave no ambiente e sem `--bare`; se a assinatura não comporta o volume, reduz-se a amostra pelo valor e pelo risco. |
| **Por quê** | Cobrança real em chave que o comentário do código dizia ser gratuita (25/06/2026); ordem do dono em 13/11/2026: "fable tem que usar assinatura só". |
| **Como se mede** | Catraca: variável de chave paga só é lida no módulo de API com teto; o juiz chama o motor com `backend="cli"`. Sensor acusa gasto acumulado ≥ 80% do teto. |
| **Onde se aplica** | Modelos, Infra, Yoda/Hermes |
| **Severidade** | 🔴 Bloqueante |
| **Quando viola** | Catraca barra; em produção, o sensor avisa e o kill-switch do motor é a ação. |
| **Verificação** | Catraca (barra commit/push): `tests/test_regra_catracas.py::test_chave_paga_fora_do_teto_so_desce`<br>Catraca (barra commit/push): `tests/test_regra_juiz.py::test_juiz_so_chama_o_claude_pela_assinatura`<br>Sensor (produção): `gasto_api` |

#### CNF-11 — Régua contratual não se aplica a parceria, repasse ou sob demanda

| | |
|---|---|
| **Regra** | Parceria com organização da sociedade civil (Lei 13.019/2014), repasse a agência ou fundo, ata sob demanda e contrato em moeda estrangeira não são medidos por pró-rata linear de contrato de serviço contínuo. Fora do domínio da régua, o resultado é INDETERMINADO. |
| **Por quê** | 13/11/2026 — pró-rata aplicado a parceria, repasse a agência de bacia e ata sob demanda gerou "pago a maior" refutado. |
| **Como se mede** | Controle negativo da perícia (instrumento fora do domínio sai INDETERMINADO). |
| **Onde se aplica** | Perícias, Detectores |
| **Severidade** | 🟡 Alta |
| **Quando viola** | Abre item; resultados fora do domínio são reclassificados. |
| **Verificação** | Catraca (barra commit/push): `tests/test_regra_controles_detector.py` |

#### CNF-12 — Competência do mandato — o que é do Executivo estadual e o que se encaminha

| | |
|---|---|
| **Regra** | O mandato fiscaliza o Executivo estadual. Achado de outro Poder ou ente é marcado como tal e tem destino próprio (encaminhar ao órgão de controle competente); nunca entra em manchete, ranking ou soma do Executivo estadual. |
| **Por quê** | 13/11/2026 — casos 🔴 de município, União e Judiciário apareciam ao lado dos do Executivo estadual. |
| **Como se mede** | Sensor do vault acusa caso aberto sem `esfera` no frontmatter; juiz no critério de utilidade. |
| **Onde se aplica** | Vault, Painel, Relatórios, Lex |
| **Severidade** | 🟢 Média |
| **Quando viola** | Abre item por caso. |
| **Verificação** | Sensor (produção): `vault_casos`<br>Juiz (rubrica): `utilidade` |

#### CNF-13 — Limite anual se mede no exercício do ato

| | |
|---|---|
| **Regra** | Todo limite anual (receita bruta de ME/EPP, teto de dispensa por exercício, limites da LRF) é comparado com valores do MESMO exercício e do MESMO fato gerador. Não se somam anos, nem se usa porte atual para ato passado. |
| **Por quê** | 13/11/2026 — "ME/EPP acima do teto" somava OB de anos misturados e usava o porte atual, não o do ano do certame. |
| **Como se mede** | Controle negativo do detector (valores em exercícios diferentes não somam contra o teto). |
| **Onde se aplica** | Detectores, Perícias |
| **Severidade** | 🟡 Alta |
| **Quando viola** | Abre item; a manchete volta a PENDENTE. |
| **Verificação** | Catraca (barra commit/push): `tests/test_regra_controles_detector.py` |

#### CNF-14 — Segredo nunca em código, log, mensagem ou commit

| | |
|---|---|
| **Regra** | Chaves, tokens e senhas vivem só em arquivos de ambiente fora do git e entram por variável de ambiente. Nenhum log, mensagem ou payload exibe segredo. |
| **Por quê** | Chave fixa em script de cron e token exposto em ferramenta de índice já ocorreram. |
| **Como se mede** | Catraca-catraca: padrões de chave em arquivo versionado só podem diminuir. |
| **Onde se aplica** | Infra, Modelos, Yoda/Hermes, Coletores |
| **Severidade** | 🔴 Bloqueante |
| **Quando viola** | Catraca barra o commit; segredo exposto é revogado. |
| **Verificação** | Catraca (barra commit/push): `tests/test_regra_catracas.py::test_segredo_versionado_so_desce` |

#### CNF-15 — Presunção de legitimidade e gate de neutralidade em tudo que sai da casa

| | |
|---|---|
| **Regra** | Atos administrativos presumem-se legítimos e ninguém é tratado como culpado (Constituição, art. 5º, LVII). Todo entregável que pode sair da casa (relatório, dossiê, parecer, minuta de requerimento) passa pelo gate de neutralidade antes de ser entregue. |
| **Por quê** | O que o painel e os dossiês afirmam vira ato parlamentar; erro expõe o mandato. |
| **Como se mede** | Catraca: todo ponto de entrega inventariado como "relatório" chama o gate; juiz no critério de presunção. |
| **Onde se aplica** | Relatórios, Lex, Yoda/Hermes, Vault |
| **Severidade** | 🔴 Bloqueante |
| **Quando viola** | Entrega recusada. |
| **Verificação** | Verificação já existente: `tests/test_neutralidade.py`<br>Catraca (barra commit/push): `tests/test_regra_inventario.py`<br>Juiz (rubrica): `presuncao` |

#### CNF-16 — Operação que não derruba a casa

| | |
|---|---|
| **Regra** | Um processo pesado por vez na VM-1; suíte de testes sempre em lotes; processo se mata por PID, nunca por padrão de nome; a sessão do SIAFE é única; escrita em massa no banco principal só fora do horário de uso do painel; o serviço do painel só é reiniciado por quem integra. |
| **Por quê** | A VM caiu quatro vezes com suíte monolítica; matar por padrão de nome já matou a própria sessão. |
| **Como se mede** | Catraca-catraca: `pkill -f` em script versionado só pode diminuir. |
| **Onde se aplica** | Infra, Coletores, AO VIVO |
| **Severidade** | 🟡 Alta |
| **Quando viola** | Catraca barra o commit. |
| **Verificação** | Catraca (barra commit/push): `tests/test_regra_catracas.py::test_pkill_por_padrao_so_desce` |

#### CNF-17 — Yoda/Hermes — personalização que sobrevive a atualização

| | |
|---|---|
| **Regra** | Toda personalização do JFN no Hermes fica commitada na branch do fork E salva em arquivo de diff antes de qualquer atualização; atualiza-se pelo script seguro (merge com reversão automática), nunca pelo comando de atualização direto. Prefere-se plugin a patch em arquivo do upstream. |
| **Por quê** | Em 31/07/2026 a atualização direta apagou as quatro personalizações já commitadas; o que salvou foi o diff em arquivo. |
| **Como se mede** | Sensor confere os marcadores das personalizações no adapter do Telegram e a existência do script seguro. |
| **Onde se aplica** | Yoda/Hermes, Infra |
| **Severidade** | 🟡 Alta |
| **Quando viola** | Abre item 🆘 (o Yoda perde o menu e o teto de imagem). |
| **Verificação** | Sensor (produção): `hermes_personalizacoes` |

### 4.3 Correção (COR) — É verdade, e foi provado?

| Regra | Enunciado curto | Severidade |
|---|---|---|
| COR-01 | Conclusão acusatória só com prova primária citada e conferida por código | 🔴 Bloqueante |
| COR-02 | Dupla leitura independente; divergência é PENDENTE | 🟡 Alta |
| COR-03 | Controle positivo e controle negativo por detector | 🔴 Bloqueante |
| COR-04 | Taxa de falso positivo medida em fonte primária antes de virar manchete | 🔴 Bloqueante |
| COR-05 | Hipótese inocente testada, não só nomeada | 🟡 Alta |
| COR-06 | Identidade provada — nunca só nome, nunca só CPF mascarado | 🔴 Bloqueante |
| COR-07 | Teto de coleta não é total | 🟡 Alta |
| COR-08 | Ausência não é fato | 🟡 Alta |
| COR-09 | Atributo cadastral se avalia na data do ato | 🔴 Bloqueante |
| COR-10 | Detector declara o domínio e devolve INDETERMINADO fora dele | 🟡 Alta |
| COR-11 | Manchete refém de poucos registros diz isso | 🟢 Média |
| COR-12 | Soma sem dupla contagem | 🔴 Bloqueante |
| COR-13 | Todo número exibido é reprodutível por código versionado | 🔴 Bloqueante |
| COR-14 | Modelo barato extrai; quem julga é o modelo de juízo | 🟡 Alta |
| COR-15 | Catraca provada — ela fica vermelha com o defeito | 🔴 Bloqueante |
| COR-16 | Taxa alta de detector é defeito de leitura até prova em contrário | 🟡 Alta |
| COR-17 | Menção não é fonte; norma não é fato | 🟡 Alta |

#### COR-01 — Conclusão acusatória só com prova primária citada e conferida por código

| | |
|---|---|
| **Regra** | Toda conclusão 🔴 ou 🟡 exibida como achado traz a prova primária — documento, trecho literal, data — e a citação é conferida por código contra o texto da fonte (`verificacao.citacao_existe`, `verificacao.numero_no_trecho`). Banco de dados é base, não prova. Sem prova primária conferida o estado é PENDENTE e a superfície diz "a verificar". Qualquer dúvida residual é INCONCLUSIVA, nunca CONFIRMADA. |
| **Por quê** | Revisão cética de 13/11/2026: de 56 conclusões sobre terceiros, nenhuma se confirmou no sentido estrito; 21 foram refutadas e 27 tinham o número ou a moldura errados. |
| **Como se mede** | Sensor do vault conta casos 🔴 abertos sem bloco de prova primária (documento + trecho + data); catraca prova que a conferência recusa citação que não está na fonte. |
| **Onde se aplica** | Detectores, Perícias, Relatórios, Vault, Painel, Lex, Yoda/Hermes |
| **Severidade** | 🔴 Bloqueante |
| **Quando viola** | O achado é rebaixado a PENDENTE em todas as superfícies e abre item de revisão por caso. |
| **Verificação** | Sensor (produção): `vault_casos`<br>Catraca (barra commit/push): `tests/test_regra_verificadores.py::test_citacao_ausente_da_fonte_nao_verifica`<br>Juiz (rubrica): `auditor` |

#### COR-02 — Dupla leitura independente; divergência é PENDENTE

| | |
|---|---|
| **Regra** | Extração ou juízo que sustenta achado é feito duas vezes por leitores independentes (Claude e cascata, ou dois modelos de famílias diferentes). Só vale o que concorda. Divergência fica registrada lado a lado, vira PENDENTE e exemplo de calibração para o outro modelo — nunca é resolvida em silêncio nem por média. |
| **Por quê** | Diretriz do dono de 13/11/2026 (Claude co-motor; os vereditos se cruzam); modelo barato decidindo sozinho já produziu vereditos vazios. |
| **Como se mede** | Sensor lê o banco de cruzamento: divergências graves sem revisão há mais de 7 dias e taxa de concordância por tarefa. |
| **Onde se aplica** | Modelos, Detectores, Perícias, Lex |
| **Severidade** | 🟡 Alta |
| **Quando viola** | Abre item com a fila de revisão; tarefa com concordância abaixo do piso perde o direito de exibir veredito. |
| **Verificação** | Sensor (produção): `cruzamento_motores`<br>Verificação já existente: `compliance_agent/llm/cruzamento.py` |

#### COR-03 — Controle positivo e controle negativo por detector

| | |
|---|---|
| **Regra** | Todo detector, perícia ou regra tem ao menos um teste de controle positivo (caso sintético em que o fato existe e o detector acusa) e um de controle negativo (caso sintético com a explicação inocente mais comum, em que o detector NÃO acusa). O inventário aponta os dois testes. |
| **Por quê** | O filtro que a fonte ignorava só foi percebido pelo controle positivo; os detectores refutados em 13/11/2026 não tinham controle negativo para a hipótese inocente que os derrubou. |
| **Como se mede** | Catraca-catraca: nº de detectores do inventário sem os dois controles só pode diminuir; detector novo nasce com os dois. |
| **Onde se aplica** | Detectores, Perícias |
| **Severidade** | 🔴 Bloqueante |
| **Quando viola** | Catraca barra detector novo sem controles; os antigos ficam listados como dívida no painel de conformidade. |
| **Verificação** | Catraca (barra commit/push): `tests/test_regra_controles_detector.py` |

#### COR-04 — Taxa de falso positivo medida em fonte primária antes de virar manchete

| | |
|---|---|
| **Regra** | Detector só alimenta manchete, ranking ou alerta ao dono depois de ter a precisão medida em amostra conferida contra fonte primária (tamanho da amostra, data, taxa e quem conferiu, registrados no inventário). Sem medição, o que ele produz aparece como "não calibrado", fora das manchetes. Medição com mais de 180 dias ou anterior a mudança de lógica não vale. |
| **Por quê** | 13/11/2026: 8 manchetes do cockpit, 0 confirmadas; dois detectores eram anti-preditivos; calibrar a taxa não calibrou a lógica. |
| **Como se mede** | Catraca-catraca: nº de detectores ligados a manchete sem medição válida só pode diminuir; sensor lista as manchetes servidas por detector não calibrado. |
| **Onde se aplica** | Detectores, Perícias, Painel |
| **Severidade** | 🔴 Bloqueante |
| **Quando viola** | Manchete de detector não calibrado ganha o selo "não calibrado"; detector novo não entra em manchete sem medição. |
| **Verificação** | Catraca (barra commit/push): `tests/test_regra_controles_detector.py`<br>Sensor (produção): `calibragem_manchetes` |

#### COR-05 — Hipótese inocente testada, não só nomeada

| | |
|---|---|
| **Regra** | Para cada achado, as explicações inocentes são listadas E testadas com o documento que as confirmaria ou afastaria (devolução bancária, sucessão empresarial, homônimo, prorrogação não publicada, competência anterior, mesma família econômica). Escrever "pode haver explicação" não conta. Cada detector declara as hipóteses inocentes que exclui por código. |
| **Por quê** | 13/11/2026: 174 "duplicidades" eram devolução + reemissão; "empresa morta" incluía sucessão e órgão público; "sócio agente público" de R$ 125,9 mi era homônimo. |
| **Como se mede** | Inventário: campo `hipoteses_inocentes` por detector (catraca-catraca do nº sem); juiz no critério de hipótese inocente. |
| **Onde se aplica** | Detectores, Perícias, Relatórios, Vault, Lex |
| **Severidade** | 🟡 Alta |
| **Quando viola** | Abre item; achado sem teste de hipótese inocente fica PENDENTE. |
| **Verificação** | Catraca (barra commit/push): `tests/test_regra_controles_detector.py`<br>Juiz (rubrica): `inocente` |

#### COR-06 — Identidade provada — nunca só nome, nunca só CPF mascarado

| | |
|---|---|
| **Regra** | Pessoa jurídica casa por CNPJ (raiz de 8 dígitos para grupo/filial; 14 para estabelecimento). Pessoa física casa por CPF completo quando disponível, ou pelos dígitos visíveis do CPF mascarado E nome normalizado. Nome sozinho ou CPF mascarado sozinho geram no máximo "candidato a verificar", nunca achado. |
| **Por quê** | 13/11/2026: 99,57% dos grupos por CPF mascarado juntavam pessoas diferentes; "credor sem histórico" medido no CNPJ de 14 dígitos tratava filial e sucessora como empresa nova. |
| **Como se mede** | Controle negativo (homônimo não casa; mesmo mascarado com nomes diferentes não agrupa); catraca-catraca de agrupamento por CPF mascarado sem nome. |
| **Onde se aplica** | Detectores, Perícias, Painel |
| **Severidade** | 🔴 Bloqueante |
| **Quando viola** | Catraca barra; alertas produzidos por casamento fraco são arquivados como "a verificar". |
| **Verificação** | Catraca (barra commit/push): `tests/test_regra_catracas.py::test_grupo_por_cpf_mascarado_so_desce`<br>Catraca (barra commit/push): `tests/test_regra_controles_sinteticos.py` |

#### COR-07 — Teto de coleta não é total

| | |
|---|---|
| **Regra** | Contagem igual ao limite de página, de consulta ou de parâmetro (50, 100, 500, 1.000, 10.000; ou platô logo abaixo) é INCOMPLETA até prova em contrário. Nenhuma soma ou "total" sai de coleta que bateu no teto. |
| **Por quê** | O teto do parâmetro foi lido como limite da fonte; dias do SIAFE paravam entre 975 e 999 OBs; contagem redonda era teto de coleta. |
| **Como se mede** | Sensor acusa lista/contagem em payload ou tabela de coleta igual a limite conhecido sem marca de completude. |
| **Onde se aplica** | Coletores, Detectores, Painel, Yoda/Hermes |
| **Severidade** | 🟡 Alta |
| **Quando viola** | Abre item; o número ganha o selo "parcial (teto de coleta)". |
| **Verificação** | Sensor (produção): `payloads_painel`<br>Catraca (barra commit/push): `tests/test_regra_verificadores.py::test_contagem_no_teto_e_acusada` |

#### COR-08 — Ausência não é fato

| | |
|---|---|
| **Regra** | "Não há", "zero", "sem contrato", "sem OB" só se afirma depois de um controle positivo da MESMA consulta (um caso que sabidamente existe e retorna). Sem o controle, a resposta é INDISPONÍVEL. |
| **Por quê** | Busca por nome disse "sem contrato" onde havia; o manifesto afirmou vazio sobre 0,93 GB no disco; "0 OB" desatualizado ficou em caso. |
| **Como se mede** | Verificador de texto acusa afirmação de ausência sem marca de controle em respostas e entregáveis amostrados; juiz. |
| **Onde se aplica** | Coletores, Detectores, Yoda/Hermes, Relatórios, Vault, Lex |
| **Severidade** | 🟡 Alta |
| **Quando viola** | Abre item; a frase vira INDISPONÍVEL. |
| **Verificação** | Catraca (barra commit/push): `tests/test_regra_verificadores.py::test_ausencia_sem_controle_e_acusada`<br>Juiz (rubrica): `auditor` |

#### COR-09 — Atributo cadastral se avalia na data do ato

| | |
|---|---|
| **Regra** | Situação cadastral, sanção, porte, quadro societário e vínculo funcional são avaliados na data do ato examinado, não na data da consulta. Sem histórico, o atributo é INDISPONÍVEL para aquela data. |
| **Por quê** | "Pago a empresa morta" (R$ 4 bi → R$ 18,3 mi em julho; R$ 592,8 mi → ~R$ 16,4 mi em novembro) não checava se o pagamento era posterior à baixa. |
| **Como se mede** | Controle negativo por detector (fato anterior ao atributo não acusa); catraca de controles. |
| **Onde se aplica** | Detectores, Perícias |
| **Severidade** | 🔴 Bloqueante |
| **Quando viola** | Catraca barra detector novo sem o controle de época. |
| **Verificação** | Catraca (barra commit/push): `tests/test_regra_controles_detector.py` |

#### COR-10 — Detector declara o domínio e devolve INDETERMINADO fora dele

| | |
|---|---|
| **Regra** | Cada detector declara para que tipo de instrumento, ente e período vale. Fora do domínio, o resultado é INDETERMINADO com o motivo — nunca um valor. |
| **Por quê** | 13/11/2026 — régua de contrato contínuo aplicada a parceria, repasse e contrato em dólar. |
| **Como se mede** | Inventário com campo `dominio` por detector (catraca-catraca do nº sem). |
| **Onde se aplica** | Detectores, Perícias |
| **Severidade** | 🟡 Alta |
| **Quando viola** | Dívida listada no painel de conformidade; detector novo sem domínio é barrado. |
| **Verificação** | Catraca (barra commit/push): `tests/test_regra_controles_detector.py` |

#### COR-11 — Manchete refém de poucos registros diz isso

| | |
|---|---|
| **Regra** | Quando até 3 registros respondem por 50% ou mais de uma soma em destaque, a manchete informa a concentração ("95% em um credor") e os registros são conferidos na fonte primária antes da exibição. |
| **Por quê** | 13/11/2026 — 95% do "pago a empresa morta" era um único credor; em julho, 4 registros valiam 38% de uma manchete. |
| **Como se mede** | Sensor calcula a participação dos 3 maiores itens nos payloads de manchete que trazem lista. |
| **Onde se aplica** | Painel, Relatórios, Detectores |
| **Severidade** | 🟢 Média |
| **Quando viola** | Abre item; a manchete ganha a nota de concentração. |
| **Verificação** | Sensor (produção): `payloads_painel`<br>Catraca (barra commit/push): `tests/test_regra_verificadores.py::test_concentracao_alta_e_acusada` |

#### COR-12 — Soma sem dupla contagem

| | |
|---|---|
| **Regra** | Antes de somar: uma linha por fato (sem chave vazia), responsabilidade solidária conta uma vez, devolução e reemissão contam uma vez, picos anuais não se somam, e o mesmo fato vindo de duas coletas é deduplicado pela chave natural. |
| **Por quê** | 57 linhas sem número de OB dobravam R$ 11,47 mi em todas as somas; débito solidário contado N vezes (R$ 66 mi → R$ 28,5 mi); reconstrução que salvou páginas alheias levou a soma a 10¹⁷. |
| **Como se mede** | Sensor de base: linhas de OB com chave vazia ou duplicada na chave natural; catraca de OB paga. |
| **Onde se aplica** | Detectores, Perícias, Coletores |
| **Severidade** | 🔴 Bloqueante |
| **Quando viola** | Abre item 🆘; somas dependentes voltam a PENDENTE. |
| **Verificação** | Sensor (produção): `alertas_base`<br>Catraca (barra commit/push): `tests/test_regra_catracas.py::test_ob_sem_filtro_de_paga_so_desce` |

#### COR-13 — Todo número exibido é reprodutível por código versionado

| | |
|---|---|
| **Regra** | Todo arquivo de dados que alimenta o painel ou um relatório tem gerador versionado no repositório, e o inventário aponta para ele. Nada do que o dono vê nasce de script em pasta temporária ou de edição à mão. |
| **Por quê** | 13/11/2026 — o gerador da análise de gestão vivia em pasta temporária; o que o painel mostrava não era reprodutível. |
| **Como se mede** | Catraca: todo arquivo de dados inventariado como fonte de rota tem `gerador` existente no repositório. |
| **Onde se aplica** | Painel, Relatórios, Detectores, Vault |
| **Severidade** | 🔴 Bloqueante |
| **Quando viola** | Catraca barra superfície nova sem gerador; as antigas ficam como dívida. |
| **Verificação** | Catraca (barra commit/push): `tests/test_regra_inventario.py` |

#### COR-14 — Modelo barato extrai; quem julga é o modelo de juízo

| | |
|---|---|
| **Regra** | Modelo gratuito ou barato só extrai e tria, com citação literal conferida por código. Todo veredito 🔴 ou 🟡 exibido foi relido pelo modelo de juízo da assinatura. Resposta de modelo sem o JSON pedido, cortada ou vazia é falha — nunca veredito "sem achado". |
| **Por quê** | 616 vereditos vazios por corte de saída; 28% dos vereditos de execução negavam OB que a base tinha. |
| **Como se mede** | Sensor do cruzamento: vereditos 🔴/🟡 exibidos sem leitura do modelo de juízo; vereditos vazios. |
| **Onde se aplica** | Modelos, Perícias, Lex, Detectores |
| **Severidade** | 🟡 Alta |
| **Quando viola** | Abre item; vereditos sem releitura ficam PENDENTE. |
| **Verificação** | Sensor (produção): `cruzamento_motores` |

#### COR-15 — Catraca provada — ela fica vermelha com o defeito

| | |
|---|---|
| **Regra** | Toda catraca e todo verificador novo têm, no próprio teste, a prova de que acusam: o defeito é reintroduzido em dado sintético e o verificador responde vermelho. Catraca com falso positivo é corrigida, não ignorada. |
| **Por quê** | Cinco catracas da casa já mentiram (mediam a coisa errada, varriam a pasta errada ou quebravam quando o problema era resolvido). |
| **Como se mede** | Catraca do registro: cada catraca de regra tem um teste com "prova" no nome que injeta o defeito. |
| **Onde se aplica** | Infra, Detectores |
| **Severidade** | 🔴 Bloqueante |
| **Quando viola** | Catraca barra. |
| **Verificação** | Catraca (barra commit/push): `tests/test_regra_registro.py::test_toda_catraca_de_regra_tem_prova` |

#### COR-16 — Taxa alta de detector é defeito de leitura até prova em contrário

| | |
|---|---|
| **Regra** | Detector que acusa mais de 20% da base examinada, ou cujo volume multiplica por 3 entre execuções, fica EM REVISÃO: nada dele entra em manchete até uma amostra ser conferida na fonte primária. |
| **Por quê** | O motor de regras gravou 85.229 alertas ao ser consertado; 58.253 eram colisão de CPF mascarado. |
| **Como se mede** | Sensor compara a contagem de alertas por tipo com o snapshot anterior e com o tamanho da base. |
| **Onde se aplica** | Detectores, Painel |
| **Severidade** | 🟡 Alta |
| **Quando viola** | Abre item; o tipo de alerta é segurado fora das manchetes. |
| **Verificação** | Sensor (produção): `alertas_base` |

#### COR-17 — Menção não é fonte; norma não é fato

| | |
|---|---|
| **Regra** | Texto que MENCIONA um objeto não é o objeto; cláusula que PREVÊ um ato não é o ato praticado; metadado dentro do documento não prova o documento. Extração por janela em volta de marcador exige a âncora do próprio registro. |
| **Por quê** | Cláusula tratada como ato praticado; extrator de janela simétrica fabricou tuplas híbridas (75% dos extratos eram do vizinho). |
| **Como se mede** | Controles negativos dos extratores (texto que só menciona não gera achado); juiz. |
| **Onde se aplica** | Detectores, Coletores, Lex, Perícias |
| **Severidade** | 🟡 Alta |
| **Quando viola** | Abre item. |
| **Verificação** | Catraca (barra commit/push): `tests/test_regra_controles_detector.py`<br>Juiz (rubrica): `auditor` |

### 4.4 Constância (CST) — Diz a mesma coisa em todo lugar e continua dizendo amanhã?

| Regra | Enunciado curto | Severidade |
|---|---|---|
| CST-01 | O mesmo número é o mesmo em todo lugar | 🟡 Alta |
| CST-02 | Variação brusca de manchete dispara revisão | 🟡 Alta |
| CST-03 | Motor que roda sem efeito é falha | 🟡 Alta |
| CST-04 | Todo produtor tem consumidor e todo consumidor tem produtor | 🟡 Alta |
| CST-05 | Regressão de catraca bloqueia; a linha de base só desce | 🔴 Bloqueante |
| CST-06 | Rotina idempotente | 🟡 Alta |
| CST-07 | Cache não serve lógica antiga | 🟡 Alta |
| CST-08 | Caso do vault coerente consigo e com o que foi refutado | 🟡 Alta |
| CST-09 | Constante e lista em fonte única | 🟡 Alta |
| CST-10 | Nada falha calado | 🟡 Alta |
| CST-11 | Inventário vivo — nada afirma ao dono sem estar inventariado | 🔴 Bloqueante |
| CST-12 | Regra com verificador; documento gerado da fonte | 🔴 Bloqueante |
| CST-13 | Número e lista vêm do mesmo universo | 🟡 Alta |
| CST-14 | Afirmação refutada já entregue gera errata | 🟡 Alta |
| CST-15 | O juiz de qualidade roda, e o silêncio dele é falha | 🟡 Alta |

#### CST-01 — O mesmo número é o mesmo em todo lugar

| | |
|---|---|
| **Regra** | Uma métrica tem UMA definição e UM gerador. Painel, PDF, Yoda e vault leem do mesmo lugar; divergência entre superfícies acima de R$ 0,01 (valor) ou 1 unidade (contagem), na mesma data de referência, é violação. |
| **Por quê** | 13/11/2026: o card "órgão que mais economiza" contradizia o herói da mesma tela; um caso do vault dizia "R$ 375 mi canônico" e R$ 568,2 mi no mesmo arquivo. |
| **Como se mede** | Sensor compara cada métrica do mapa de métricas entre as superfícies declaradas. |
| **Onde se aplica** | Painel, Relatórios, Yoda/Hermes, Vault |
| **Severidade** | 🟡 Alta |
| **Quando viola** | Abre item com os dois valores e as duas fontes; as superfícies ficam EM REVISÃO. |
| **Verificação** | Sensor (produção): `constancia_superficies` |

#### CST-02 — Variação brusca de manchete dispara revisão

| | |
|---|---|
| **Regra** | Manchete que varia mais de 25% (ou muda de ordem de grandeza, ou zera) entre duas execuções sem mudança de lógica registrada fica EM REVISÃO até alguém explicar a causa. Mudança de lógica registra antes e depois. |
| **Por quê** | Manchetes já caíram de R$ 4 bi para R$ 18 mi e de 59 mil para 771 — o sistema não percebeu nenhuma das quedas, e nem as subidas. |
| **Como se mede** | Sensor guarda o histórico de cada manchete e compara com a leitura anterior. |
| **Onde se aplica** | Painel, Detectores |
| **Severidade** | 🟡 Alta |
| **Quando viola** | Abre item com valor anterior e atual; reincidência vira 🆘. |
| **Verificação** | Sensor (produção): `manchetes_variacao`<br>Catraca (barra commit/push): `tests/test_regra_verificadores.py::test_variacao_brusca_e_acusada` |

#### CST-03 — Motor que roda sem efeito é falha

| | |
|---|---|
| **Regra** | Todo motor do AO VIVO declara onde seu trabalho aparece (`efeito`). Rodar sem avanço dentro da janela é falha, não "agendado". Motor sem efeito declarado é dívida. |
| **Por quê** | 255 execuções "ok" em 7 dias com 48 de 48 capturas vazias; o motor de regras rodou 84 vezes com erro e código de saída zero. |
| **Como se mede** | Catraca-catraca: nº de motores sem `efeito` só pode diminuir; sensor lê o estado do AO VIVO e acusa efeito parado. |
| **Onde se aplica** | AO VIVO, Coletores, Detectores |
| **Severidade** | 🟡 Alta |
| **Quando viola** | Abre item; remédio automático quando o motor declara um. |
| **Verificação** | Catraca (barra commit/push): `tests/test_regra_motores.py`<br>Sensor (produção): `motores_sem_efeito` |

#### CST-04 — Todo produtor tem consumidor e todo consumidor tem produtor

| | |
|---|---|
| **Regra** | O que é produzido (tabela, arquivo, fila) tem quem leia, com agenda; o que é lido tem quem produza, com agenda. Detector novo confere se já existe e se tem chamador. Instrução enviada a outro sistema confere se há quem a trate do outro lado. |
| **Por quê** | Seis casos de "construído, testado, nunca rodado"; produtor com cron e consumidor sem; instrução sem tratador do outro lado. |
| **Como se mede** | Catraca do inventário: detector inventariado tem chamador em produção (rota, cron, timer ou motor); SLO de frescor existente. |
| **Onde se aplica** | Detectores, Coletores, AO VIVO, Yoda/Hermes, Lex |
| **Severidade** | 🟡 Alta |
| **Quando viola** | Catraca barra detector novo sem chamador; os órfãos antigos ficam como dívida. |
| **Verificação** | Catraca (barra commit/push): `tests/test_regra_inventario.py`<br>Verificação já existente: `config/pipelines.yaml` |

#### CST-05 — Regressão de catraca bloqueia; a linha de base só desce

| | |
|---|---|
| **Regra** | Catraca vermelha barra commit e push. Linha de base de dívida só diminui; aumentá-la exige motivo escrito no commit e no arquivo de base. Portão que não mediu declara que não mediu. |
| **Por quê** | O CI ficou vermelho 12 dias sem ninguém ver; um portão que declarava não ter medido guardou defeito. |
| **Como se mede** | As catracas de regra entram no portão de pre-push e no sensor de catracas da automelhoria. |
| **Onde se aplica** | Infra |
| **Severidade** | 🔴 Bloqueante |
| **Quando viola** | Push barrado; em produção, item aberto. |
| **Verificação** | Catraca (barra commit/push): `tests/test_regra_registro.py::test_catracas_de_regra_estao_no_portao`<br>Verificação já existente: `tests/test_pre_push_gate_catracas.py` |

#### CST-06 — Rotina idempotente

| | |
|---|---|
| **Regra** | Rodar duas vezes dá o mesmo resultado que rodar uma: gravação por chave natural, sem duplicar linha, sem destruir progresso anterior, sem reenviar a mesma mensagem. |
| **Por quê** | Chave primária incompleta apagava OB de outra unidade; guarda de invalidação destruía o próprio progresso a cada passada; fila de 3.074 itens era 9. |
| **Como se mede** | Os sensores e o juiz de qualidade têm teste de idempotência; para as rotinas da casa, revisão por caso. |
| **Onde se aplica** | Coletores, Detectores, AO VIVO, Lex, Yoda/Hermes |
| **Severidade** | 🟡 Alta |
| **Quando viola** | Abre item. |
| **Verificação** | Catraca (barra commit/push): `tests/test_regra_sensores.py::test_rodar_duas_vezes_nao_duplica`<br>⚠ Ainda manual: falta harness que rode cada coletor duas vezes sobre base sintética e compare |

#### CST-07 — Cache não serve lógica antiga

| | |
|---|---|
| **Regra** | Todo cache de número exibido tem prazo, e a correção de lógica invalida o cache (chave com versão da lógica, ou limpeza explícita no mesmo commit). Depois de corrigir, confere-se o número SERVIDO, não o código. |
| **Por quê** | Correções de manchete continuaram invisíveis até o cache ser regenerado; consertar o artefato em vez da fonte fez oito correções sumirem num rebuild. |
| **Como se mede** | Sensor compara o número servido pela rota com o recalculado pela função de origem nas métricas do mapa (CST-01). |
| **Onde se aplica** | Painel, Relatórios |
| **Severidade** | 🟡 Alta |
| **Quando viola** | Abre item com remédio de regeneração do cache. |
| **Verificação** | Sensor (produção): `constancia_superficies`<br>⚠ Ainda manual: falta versão de lógica na chave dos caches de rota; hoje só o prazo protege |

#### CST-08 — Caso do vault coerente consigo e com o que foi refutado

| | |
|---|---|
| **Regra** | Frontmatter (grau, status, valor) e resumo de um caso dizem o mesmo que o corpo. Caso com desfecho no corpo não fica "aberto/alto". Achado REFUTADO é rebaixado em todas as superfícies que o exibem, com nota do que o derrubou. |
| **Por quê** | 13/11/2026 — casos com `grau: alto` e desfecho 🟢 no corpo; resumo com valor antigo; quatro casos refutados ainda exibidos como 🔴. |
| **Como se mede** | Sensor lê os casos do vault e acusa conflito grau × desfecho e valores divergentes entre resumo e corpo. |
| **Onde se aplica** | Vault, Painel |
| **Severidade** | 🟡 Alta |
| **Quando viola** | Abre item por caso. |
| **Verificação** | Sensor (produção): `vault_casos` |

#### CST-09 — Constante e lista em fonte única

| | |
|---|---|
| **Regra** | Constante legal, lista de termos, mapa de órgãos e tabela de modelos existem em um lugar; os demais importam. Derivado é regenerado, nunca editado à mão. |
| **Por quê** | Cópias divergentes de teto, de lista de detectores e de capacidades; derivado editado à mão sumiu no rebuild. |
| **Como se mede** | Catracas de constantes legais (CNF-06) e de derivados regenerados (existente). |
| **Onde se aplica** | Detectores, Infra, Painel, Yoda/Hermes |
| **Severidade** | 🟡 Alta |
| **Quando viola** | Catraca barra. |
| **Verificação** | Catraca (barra commit/push): `tests/test_regra_catracas.py::test_teto_legal_copiado_so_desce` |

#### CST-10 — Nada falha calado

| | |
|---|---|
| **Regra** | Todo job mede o próprio efeito e sai com código diferente de zero quando não produz. Sensor que não consegue medir vira problema `sensor:<nome>`, nunca "ok". Zero vem sempre com o motivo. |
| **Por quê** | Coleta diária morta quatro dias em silêncio; drenador parado 16 dias por um número gravado como texto; tratador de popup zerou a coleta por 7 dias. |
| **Como se mede** | O laço de automelhoria trata sensor cego como problema (existente); os sensores de qualidade seguem o mesmo contrato e têm teste. |
| **Onde se aplica** | Infra, Coletores, AO VIVO, Yoda/Hermes, Lex |
| **Severidade** | 🟡 Alta |
| **Quando viola** | Abre item `sensor:<nome>`. |
| **Verificação** | Catraca (barra commit/push): `tests/test_regra_sensores.py::test_sensor_cego_vira_problema`<br>Verificação já existente: `tools/automelhoria_geral.py` |

#### CST-11 — Inventário vivo — nada afirma ao dono sem estar inventariado

| | |
|---|---|
| **Regra** | Toda rota, card, detector, relatório, motor, comando do Yoda e peça do Lex que afirma algo ao dono está no inventário, com o que afirma, a fonte e quem consome. Superfície nova sem entrada é barrada. |
| **Por quê** | As conclusões erradas de 13/11/2026 estavam em superfícies que ninguém listava juntas; o que não está listado não é conferido. |
| **Como se mede** | Catraca enumera rotas, cards, detectores e motores por código e compara com o inventário. |
| **Onde se aplica** | Painel, Detectores, Perícias, Relatórios, Lex, Yoda/Hermes, AO VIVO |
| **Severidade** | 🔴 Bloqueante |
| **Quando viola** | Catraca barra o commit. |
| **Verificação** | Catraca (barra commit/push): `tests/test_regra_inventario.py` |

#### CST-12 — Regra com verificador; documento gerado da fonte

| | |
|---|---|
| **Regra** | Toda regra deste arquivo tem verificador que existe e roda; o que ainda é manual aparece como dívida. O documento canônico é gerado deste arquivo e não diverge dele. |
| **Por quê** | Regra que não roda é enfeite (pedido do dono de 13/11/2026). |
| **Como se mede** | Catraca do registro. |
| **Onde se aplica** | Infra |
| **Severidade** | 🔴 Bloqueante |
| **Quando viola** | Catraca barra. |
| **Verificação** | Catraca (barra commit/push): `tests/test_regra_registro.py` |

#### CST-13 — Número e lista vêm do mesmo universo

| | |
|---|---|
| **Regra** | O total de um card e a lista que abre ao clicar nele saem da mesma consulta e do mesmo filtro. Card com número tem lista auditável atrás. |
| **Por quê** | Número e lista vinham de universos diferentes; KPI sem clique não podia ser conferido. |
| **Como se mede** | Catraca de KPI clicável (existente); sensor confere total × soma da lista nas métricas do mapa. |
| **Onde se aplica** | Painel |
| **Severidade** | 🟡 Alta |
| **Quando viola** | Abre item. |
| **Verificação** | Verificação já existente: `tests/test_painel_kpi_clicavel.py`<br>Sensor (produção): `constancia_superficies` |

#### CST-14 — Afirmação refutada já entregue gera errata

| | |
|---|---|
| **Regra** | Quando uma afirmação já mostrada ao dono é refutada ou rebaixada, registra-se a errata (o que foi dito, onde, o que a fonte mostra, data) e o dono é avisado pelo mesmo canal. Mensagem antiga não se retifica sozinha. |
| **Por quê** | 13/11/2026 — 48 conclusões refutadas ou parciais já tinham sido mostradas no painel, em relatórios e em mensagens. |
| **Como se mede** | Sensor do vault: nota de revisão com vereditos REFUTADA/PARCIAL sem a errata correspondente registrada. |
| **Onde se aplica** | Vault, Yoda/Hermes, Relatórios, Painel |
| **Severidade** | 🟡 Alta |
| **Quando viola** | Abre item pedindo a errata. |
| **Verificação** | Sensor (produção): `vault_casos` |

#### CST-15 — O juiz de qualidade roda, e o silêncio dele é falha

| | |
|---|---|
| **Regra** | O juiz subjetivo roda todo dia sobre amostra escolhida por valor e risco. Mais de 48 h sem rodada concluída é problema; nota que cai entre rodadas sobre a mesma afirmação é variação a explicar. |
| **Por quê** | Sensores que ninguém olhava; verificador "anti-teto" que nunca disparou. |
| **Como se mede** | Sensor confere a data da última rodada e a tendência das notas. |
| **Onde se aplica** | Modelos, Infra |
| **Severidade** | 🟡 Alta |
| **Quando viola** | Abre item `sensor:juiz`. |
| **Verificação** | Sensor (produção): `juiz_qualidade` |

### 4.5 Subjetivas (SUB) — Um leitor exigente aceitaria?

| Regra | Enunciado curto | Severidade |
|---|---|---|
| SUB-01 | Proporcionalidade | 🟡 Alta |
| SUB-02 | A moldura não afirma mais que o dado | 🔴 Bloqueante |
| SUB-03 | A explicação inocente foi realmente descartada | 🔴 Bloqueante |
| SUB-04 | Um auditor do tribunal de contas ou da controladoria aceitaria | 🟡 Alta |
| SUB-05 | Um jornalista hostil não derrubaria | 🟡 Alta |
| SUB-06 | A linguagem respeita a presunção de inocência | 🔴 Bloqueante |
| SUB-07 | É útil para ato parlamentar | 🟢 Média |
| SUB-08 | O dono entende sem contexto | 🟢 Média |
| SUB-09 | Acabamento de entregável corporativo | 🟢 Média |

#### SUB-01 — Proporcionalidade

| | |
|---|---|
| **Regra** | O destaque dado à afirmação (cor, posição, adjetivo, grau) é proporcional à força da prova e à materialidade do valor. |
| **Por quê** | 13/11/2026 — 🔴 em itens de R$ 1,32 mi sem prova de alcance da sanção; cluster 🔴 com 0 fachadas comprovadas. |
| **Como se mede** | Nota do juiz no critério `proporcao`. |
| **Onde se aplica** | Painel, Relatórios, Vault, Yoda/Hermes, Lex |
| **Severidade** | 🟡 Alta |
| **Quando viola** | Nota ≤ 1 abre item e rebaixa o destaque; nota 2 abre ressalva. |
| **Verificação** | Juiz (rubrica): `proporcao` |

#### SUB-02 — A moldura não afirma mais que o dado

| | |
|---|---|
| **Regra** | Título, rótulo e frase dizem exatamente o que o número mede — universo, natureza do valor, época, esfera — e nada além. |
| **Por quê** | Julho e novembro de 2026 — em todas as manchetes auditadas o dado estava certo e a moldura afirmava mais do que ele sustentava. |
| **Como se mede** | Nota do juiz no critério `moldura`. |
| **Onde se aplica** | Painel, Relatórios, Vault, Yoda/Hermes, Lex |
| **Severidade** | 🔴 Bloqueante |
| **Quando viola** | Nota ≤ 1 tira a manchete das afirmações VERIFICADAS e abre item 🆘. |
| **Verificação** | Juiz (rubrica): `moldura` |

#### SUB-03 — A explicação inocente foi realmente descartada

| | |
|---|---|
| **Regra** | As explicações inocentes plausíveis foram testadas com documento, e o texto diz qual documento afastou cada uma. |
| **Por quê** | 13/11/2026 — devolução bancária, sucessão, homônimo e prorrogação não publicada derrubaram dezenas de achados. |
| **Como se mede** | Nota do juiz no critério `inocente`. |
| **Onde se aplica** | Relatórios, Vault, Lex, Perícias, Painel |
| **Severidade** | 🔴 Bloqueante |
| **Quando viola** | Nota ≤ 1 rebaixa o achado a PENDENTE. |
| **Verificação** | Juiz (rubrica): `inocente` |

#### SUB-04 — Um auditor do tribunal de contas ou da controladoria aceitaria

| | |
|---|---|
| **Regra** | A afirmação resistiria como achado de auditoria — critério, condição, causa, efeito e evidência identificados; fonte primária citada. |
| **Por quê** | O destino dos achados é representação e requerimento; o padrão de prova é o do controle externo. |
| **Como se mede** | Nota do juiz no critério `auditor`. |
| **Onde se aplica** | Relatórios, Vault, Lex, Perícias |
| **Severidade** | 🟡 Alta |
| **Quando viola** | Nota ≤ 1 abre item; o achado não vira minuta. |
| **Verificação** | Juiz (rubrica): `auditor` |

#### SUB-05 — Um jornalista hostil não derrubaria

| | |
|---|---|
| **Regra** | Lida por quem quer desmentir o mandato, a afirmação não tem ponto fraco evidente — número conferível, sem exagero, sem alvo errado. |
| **Por quê** | O que sai do painel vira fala pública; uma única manchete inflada desmoraliza as corretas. |
| **Como se mede** | Nota do juiz no critério `hostil`. |
| **Onde se aplica** | Painel, Relatórios, Vault, Yoda/Hermes |
| **Severidade** | 🟡 Alta |
| **Quando viola** | Nota ≤ 1 abre item e marca "não usar em público". |
| **Verificação** | Juiz (rubrica): `hostil` |

#### SUB-06 — A linguagem respeita a presunção de inocência

| | |
|---|---|
| **Regra** | O texto descreve fatos e indícios, atribui condutas só com documento, e não qualifica pessoa ou empresa. |
| **Por quê** | Constituição, art. 5º, LVII; risco jurídico e reputacional do mandato. |
| **Como se mede** | Nota do juiz no critério `presuncao`. |
| **Onde se aplica** | Painel, Relatórios, Vault, Yoda/Hermes, Lex |
| **Severidade** | 🔴 Bloqueante |
| **Quando viola** | Nota ≤ 1 recusa o entregável e abre item 🆘. |
| **Verificação** | Juiz (rubrica): `presuncao` |

#### SUB-07 — É útil para ato parlamentar

| | |
|---|---|
| **Regra** | A afirmação diz o que o mandato pode fazer com ela — requerimento de informação, representação, encaminhamento, ou "nada ainda: falta o documento X". |
| **Por quê** | O dono usa o sistema para fiscalizar o Executivo; achado sem próximo passo é ruído. |
| **Como se mede** | Nota do juiz no critério `utilidade`. |
| **Onde se aplica** | Relatórios, Vault, Lex, Yoda/Hermes, Painel |
| **Severidade** | 🟢 Média |
| **Quando viola** | Nota ≤ 1 abre item de melhoria. |
| **Verificação** | Juiz (rubrica): `utilidade` |

#### SUB-08 — O dono entende sem contexto

| | |
|---|---|
| **Regra** | A afirmação é compreensível por quem não acompanhou a apuração — sem jargão interno, sem sigla não explicada, com o período e o órgão ditos. |
| **Por quê** | O dono lê pelo celular, entre compromissos; resposta do Yoda com jargão de código já falhou com ele. |
| **Como se mede** | Nota do juiz no critério `clareza`. |
| **Onde se aplica** | Yoda/Hermes, Painel, Relatórios, Lex |
| **Severidade** | 🟢 Média |
| **Quando viola** | Nota ≤ 1 abre item de melhoria. |
| **Verificação** | Juiz (rubrica): `clareza` |

#### SUB-09 — Acabamento de entregável corporativo

| | |
|---|---|
| **Regra** | O entregável seria aceito por cliente corporativo — hierarquia visual, tabelas alinhadas, escala explícita, fontes e normas citadas. |
| **Por quê** | Regra permanente do dono (padrão de consultoria de topo). |
| **Como se mede** | Nota do juiz no critério `acabamento`. |
| **Onde se aplica** | Relatórios, Lex, Vault |
| **Severidade** | 🟢 Média |
| **Quando viola** | Nota ≤ 1 abre item de melhoria. |
| **Verificação** | Juiz (rubrica): `acabamento` |

## 5. Rubricas do juiz

O juiz é o Claude **pela assinatura** (nunca API paga), como juiz e co-motor: ele amostra por valor e risco o que o painel, o vault e o Yoda afirmam e dá nota em cada critério. Nas afirmações já públicas no painel, a cascata gratuita julga a mesma entrada e os dois vereditos ficam lado a lado no banco de cruzamento — a divergência calibra os outros modelos. O veredito da cascata nunca vale sozinho. Material do vault vai só ao Claude.

**Escala (vale para todos os critérios)**

| Nota | Significado | Consequência |
|---:|---|---|
| 0 | Inaceitável — afirma o que o dado desmente, ou expõe pessoa. Sai do ar. | sai do ar; escala ao dono |
| 1 | Falha — a afirmação central não se sustenta do jeito que foi dita. | violação da regra SUB; abre item |
| 2 | Ressalva — o núcleo se sustenta; número, moldura ou linguagem precisam de ajuste. | ressalva; ajuste recomendado |
| 3 | Bom — sustenta-se; melhorias de forma. | — |
| 4 | Exemplar — um auditor assinaria embaixo. | — |

### SUB-01 · `proporcao` — O destaque é proporcional à prova e ao valor?

| | |
|---|---|
| **Âncora ruim** | Quatro itens somando R$ 1,32 mi marcados 🔴 por "sanção vigente" sem alcance provado sobre o Estado; um "cluster de fachada" 🔴 com oito fornecedores e nenhuma fachada documentada. (nota 1) |
| **Âncora boa** | "Indício 🟡 — R$ 15,59 mi em 32 OB a um credor declarado INAPTO pela Receita em 28/01/2026; 95% do total da métrica; a irregularidade em si ainda é inconclusiva." (nota 4) |

### SUB-02 · `moldura` — O título e a frase dizem só o que o número mede?

| | |
|---|---|
| **Âncora ruim** | "Pago a empresa morta: R$ 592,8 mi / 146 empresas" — o número somava pagamentos ANTERIORES à baixa, sucessões e órgãos públicos; "Contrato de R$ 43 mi assinado no 3º dia da gestão" — era ata de registro de preços de fevereiro, sem pagamento. (nota 0–1) |
| **Âncora boa** | "Pago após a baixa ou inaptidão do CNPJ (Receita): ~R$ 16,4 mi em 14 CNPJs, OB do SIAFE contabilizadas e não devolvidas, Executivo estadual, até 12/11/2026 — 95% em um credor." (nota 4) |

### SUB-03 · `inocente` — As explicações inocentes foram testadas com documento?

| | |
|---|---|
| **Âncora ruim** | "208 contratos com duplicidade (R$ 17,6 mi)" sem checar Guia de Devolução — 174 eram devolução bancária seguida de reemissão; "sócio é agente público" casado só pelo nome — era homônimo. (nota 0–1) |
| **Âncora boa** | "Par de OB de mesmo valor para a mesma nota de liquidação; a primeira tem Guia de Devolução e status de erro no pagamento, a segunda diz 'paga por ofício' — não é duplicidade. Restam 14 pares sem explicação na base: pedir extrato e notas fiscais." (nota 4) |

### SUB-04 · `auditor` — Um auditor do tribunal de contas ou da controladoria aceitaria como achado?

| | |
|---|---|
| **Âncora ruim** | "Pagamento sem prova de execução é padrão na saúde estadual — R$ 2,66 bi" — nas três âncoras de maior score a evidência de execução estava nos autos. (nota 0) |
| **Âncora boa** | "Nenhum dos 64 processos examinados pela controladoria tinha os autos lidos pelo sistema" — afirmação sobre o próprio sistema, conferida processo a processo. (nota 4) |

### SUB-05 · `hostil` — Um jornalista hostil derrubaria?

| | |
|---|---|
| **Âncora ruim** | "59.024 alertas de gravidade alta" — 58.253 eram pessoas diferentes agrupadas pelo CPF mascarado; uma checagem de dez minutos desmonta. (nota 0) |
| **Âncora boa** | "Limpeza escolar paga por termo de ajuste de contas quase todo mês em 2026, sem contrato vigente; os termos estão publicados no diário oficial (datas e números citados)." (nota 4) |

### SUB-06 · `presuncao` — A linguagem respeita a presunção de inocência?

| | |
|---|---|
| **Âncora ruim** | "Melhor detector: concentra fraude 2,12×"; "fachada/fantasma já registrados". (nota 0–1) |
| **Âncora boa** | "Detector com 2,1× mais fornecedores sancionados (qualquer época e ente), n = 88 — sinal para priorizar leitura, não conclusão." (nota 4) |

### SUB-07 · `utilidade` — Diz o que o mandato pode fazer com isso?

| | |
|---|---|
| **Âncora ruim** | "🔴 10/10 — sobrepreço" em contrato federal, sem comparador de preço e sem destino. (nota 1) |
| **Âncora boa** | "Inconclusivo: falta saber se o par de OB é duplicidade ou regularização. Resolve: requerimento à secretaria pedindo extrato da conta pagadora de março/2026 e a guia de devolução." (nota 4) |

### SUB-08 · `clareza` — O dono entende sem contexto?

| | |
|---|---|
| **Âncora ruim** | "D14: 100 no Executivo, 4 itens 🔴 do JSON" — código interno, sem período nem órgão. (nota 1) |
| **Âncora boa** | "Entre março e novembro de 2026, o Estado pagou R$ X a N fornecedores que estavam impedidos de contratar com o próprio Estado." (nota 4) |

### SUB-09 · `acabamento` — Seria aceito como entregável corporativo?

| | |
|---|---|
| **Âncora ruim** | Relatório em texto corrido, valores sem separador, sem fonte nem data. (nota 1) |
| **Âncora boa** | Capa, placar, fichas por conclusão com fonte e trecho, tabela-resumo, o que falta e o que resolve. (nota 4) |

**Quando escalar para humano (o dono decide; o sistema não resolve sozinho)**

- Qualquer critério com nota 0.
- Afirmação 🔴 de valor igual ou superior a R$ 10.000.000,00 com nota ≤ 2 em moldura, inocente ou auditor.
- Pessoa física nominada.
- Outro Poder ou outro ente.
- Claude e a cascata divergem em 2 pontos ou mais no mesmo critério.
- A mesma afirmação reprovada em duas rodadas seguidas.
- Qualquer minuta que vá sair da casa (requerimento, representação, fala pública).

## 6. Como as regras rodam

| Camada | O que é | Quando roda | Onde ver |
|---|---|---|---|
| **Catracas** | `tests/test_regra_*.py` — contam o defeito por arquivo versionado; a dívida só desce, arquivo novo nasce em zero; cada uma tem a prova de que fica vermelha com o defeito | no portão de pre-push (`tools/pre_push_gate.sh`), no CI e no sensor de catracas da automelhoria | saída do pytest; base em `tests/golden/qualidade_base.json` |
| **Sensores** | `compliance_agent/qualidade/sensores.py` — rodam sobre o dado servido (payload das manchetes, casos do vault, respostas do Yoda, motores, cruzamento) | a cada 3 h, dentro do laço de automelhoria (`tools/automelhoria_geral.py`), e como motor do AO VIVO | `data/qualidade_estado.json`; fila do Yoda (`/melhorias`); painel de conformidade |
| **Juiz** | `compliance_agent/qualidade/juiz.py` — rubricas da seção 5, Claude pela assinatura, amostra por valor e risco | uma vez por dia (cron), dentro do orçamento diário do motor | `data/qualidade_juiz.json`; painel de conformidade |
| **Painel de conformidade** | `compliance_agent/qualidade/estado.py` → `/api/qualidade/conformidade` — por sistema: regras, violações abertas, tendência | sob demanda | aba Conformidade |

Comandos: `python -m compliance_agent.qualidade {regras|inventario|sensores|juiz|estado|doc|base --apertar}`.

**Contratos que os verificadores também cumprem.** Sensor que não consegue medir vira problema `sensor:<nome>`, nunca "ok" (CST-10). Sem fotografia dos sensores, o painel de conformidade responde INDISPONÍVEL, não "0 violações" (PAD-02). Rodar duas vezes não duplica (CST-06). Nenhum verificador devolve dado pessoal: CPF sai mascarado na própria mensagem (PAD-04).

## 7. Dívida declarada

Regras cuja verificação ainda tem parte manual. Aparecem no painel de conformidade como dívida — nunca como "ok".

| Regra | O que falta automatizar |
|---|---|
| PAD-09 — Data rotulada pelo que é | falta dicionário de colunas de data por tabela (qual é ato, qual é registro) para a catraca cobrar o rótulo |
| CNF-04 — Ata de registro de preços não é compra | falta marcador de ata SRP na tabela de contratos/certames para a catraca cobrar a exclusão nas somas |
| CST-06 — Rotina idempotente | falta harness que rode cada coletor duas vezes sobre base sintética e compare |
| CST-07 — Cache não serve lógica antiga | falta versão de lógica na chave dos caches de rota; hoje só o prazo protege |

A dívida de **código** (o que já existia quando cada catraca nasceu e só pode descer) está em `tests/golden/qualidade_base.json` e aparece no painel de conformidade por catraca.

## 8. Como mudar uma regra

1. Edite `config/qualidade_regras.yaml` (id novo nunca reutiliza id aposentado). Toda regra precisa de caso real em `porque` e de verificador em `verificadores`.
2. Escreva o verificador **com a prova** (o defeito injetado em dado sintético tem de deixá-lo vermelho — COR-15). O repositório é público: nada de dado real, nome ou CPF em teste.
3. `python -m compliance_agent.qualidade doc` regenera este documento; `pytest tests/test_regra_registro.py` confere.
4. Regra nova que nasce com violações antigas: grave a base uma vez (`base --apertar` só desce) e diga no commit quanto ficou de dívida.
5. Afrouxar regra, subir base ou aposentar regra exige decisão do dono, registrada no commit.

---

*Indício ≠ acusação. INDISPONÍVEL ≠ zero. "Pago" é OB Contabilizada, não devolvida. O que vem do banco é base, não primária. CPF sempre mascarado. Regra que não roda é enfeite.*
