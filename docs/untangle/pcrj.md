# Decision log — untangle de `compliance_agent/pcrj/` (20/11/2026)

Escopo: `compliance_agent/pcrj/` (50 arquivos — perícia de gastos D7–D12, coletores da Prefeitura/Câmara/
TSE, cruzamentos nominais, perícias de benefício e de PPP). Escolhas do dono: **Comentários = sim** (só os
que repetem o código saem; medição datada, decisão do dono, norma e porquê de workaround ficam),
**Testes = não**. Restrições da casa: comportamento pretendido igual, título do alerta e chaves de evidência
não mudam, constante normativa com fonte única, pagamento da Prefeitura só de `pcrj_despesa.pago`.
`d9_socio_na_folha` (identidade_pessoa, "NÃO é acusação" para sócio posterior e credor sem pagamento) não foi
tocado.

Formato: o fix fica acima dos problemas que resolve. `[feito]` = aplicado nesta passada; `[pendente]` =
precisa de decisão do dono, muda resultado ou é redesenho; `[planejado]` = próximo lote; `[fora do escopo]` = anotado só.

## 1. D7: o teto do ano vem de `limite_dispensa`, inclusive a regra de ano fora da tabela  `[feito]`

- `d7_fracionamento` compara cada contratação com `teto_dispensa(ano)` (que é `limite_dispensa(ano,
  "compras")`), em Python, em vez de montar um `CASE` SQL a partir de `LIMITES`.
  - `pericia_gastos.py:91-93` reconstruía em SQL a tabela de `limites_dispensa` **e** a regra "ano fora da
    tabela → o mais recente" (`ELSE LIMITES[max(LIMITES)]`), que é de `limite_dispensa`. Mudar a regra lá
    deixaria o D7 com a antiga, sem aviso.
  - `TETO_DISPENSA_COMPRAS = teto_dispensa(2026)` ("compat: consumidores antigos") — nenhum importador em
    código, teste, yaml ou shell.
  - Conferido no banco real (somente leitura): versão antiga × nova → 1.019 achados idênticos (JSON igual),
    e idênticos com `teto=50000` explícito.

## 2. Formatação em um lugar: `pcrj/formato.py`  `[feito]`

- `formato.py` com `e` (escape HTML), `brl` (= `reporting.intel_base.moeda`), `comp` (mm/aaaa),
  `comp_legivel` (jan/2025), `data` (dd/mm/aaaa ou ISO → date) e `fmt_data` (`brl_rs` = "R$ " + `brl`). Os módulos importam com o
  nome privado que já usavam (`_e`, `_d`…), então nenhuma linha de uso muda e os testes que importam
  `alternancia._d` seguem valendo.
  - `_e` definido 7 vezes (`alternancia`, `candidatos_nominais`, `comissionados_gestao`, `movimentacoes`,
    `relatorio`, `relatorio_gabinete`, `dossie_prioritarios`); `pericia.py` o importava de `relatorio`.
  - `_brl` em `candidatos_nominais`, `comissionados_gestao` (com "R$ "), `pericia_gastos` e `_moeda` em
    `pericia_socios_beneficio` — a mesma fórmula de `intel_base.moeda`.
  - `_comp` em `candidatos_nominais` e `comissionados_gestao`.
  - `_MESES` + `_comp_legivel` em `pericia_beneficios` e `pericia_socios_beneficio`; `pericia_pcrj` usava o
    privado `_pb._comp_legivel`.
  - `_d` idêntico em `pericia` e `movimentacoes`; `alternancia._d` era o subconjunto dd/mm/aaaa (a fonte,
    `pcrj_camara_servidores.data1`, só tem esse formato — mesmo resultado).
  - `_fmt` idêntico em `pericia` e `movimentacoes`.

## 3. A observação do vínculo cruzado tem um escritor e um leitor, juntos  `[feito]`

- `db.observacao_vinculo(...)` monta e `db.ler_observacao(...)` lê o texto
  `admissao=… exoneracao=… matricula=… valor_liq=…` de `pcrj_vinculo_cruzado.observacao` — o módulo que
  declara a tabela é o dono do formato.
  - Escritor: `cruzamento.py:138` (f-string).
  - Quatro leitores com regex própria: `pericia._posts_pref`, `movimentacoes._postos_pref` (cópia),
    `relatorio._datas_pcrj` (`_RE_OBS`, via `__import__("re")`) e `relatorio._ativo` (por substring
    `"exoneracao= "`/`"exoneracao=None"`), mais `dossie_completo` (só o ano).
  - Mudar o texto gravado quebrava os quatro sem aviso; `str(None)` virando `"None"` era convenção que cada
    leitor tinha de saber.
  - Conferido nas 644 observações reais de `data/pcrj.db` (+5 casos de borda): os cinco leitores devolvem
    exatamente o mesmo que antes. O leitor exige `matricula=` — todas as linhas gravadas a têm (o escritor
    sempre a escreveu).

## 4. Natureza do cargo num módulo estável: `pcrj/cargos.py`  `[feito]`

- `cargos.py` com `cargo_comissionado`, `vinculo_efetivo` e `cessao_provavel`. `pericia_beneficios`
  (`_cargo_comissionado`) e `relatorio` (`_vinculo_efetivo`, `_cessao_provavel`) re-exportam com o nome
  antigo porque testes e `tools/consulta_nominal_alta.py` (fora do escopo) os importam.
  - `comissionados_candidatos` e `comissionados_gestao` importavam o privado `_cargo_comissionado` de
    `pericia_beneficios` (relatório de 720 linhas que muda muito) — coletor estável dependendo de relatório.
  - `pericia.py` e `relatorio_gabinete.py` importavam os privados `_cessao_provavel`/`_vinculo_efetivo` de
    `relatorio`.
  - Comentário em `pericia_beneficios.py:47` citava um "`_RE_COMISSIONADO` canônico" que não existe.

## 5. Um caminho por banco  `[feito]`

- `db.BENEF_DB` e `db.COMPLIANCE_DB` ao lado de `db.DB_PATH`, e `db.abrir_leitura(caminho)` para a conexão
  somente-leitura a esses bancos. `beneficio_pcrj.BENEF_DB` continua como global do módulo (o teste
  `test_beneficio_pcrj_nao_apaga_no_download_falho` o substitui com monkeypatch).
  - `BENEF_DB = _db.DB_PATH.parent / "pcrj_benef.db"` em `beneficio_pcrj`, `pericia_pcrj`,
    `pericia_beneficios`, `pericia_socios_beneficio` e, inline, `fantasma_servidor`.
  - `COMPLIANCE_DB` em `pericia_socios_beneficio`; `resolvedor_municipio` e `beneficio_pcrj` remontavam
    `_db.DB_PATH.parent / "compliance.db"`.
  - Quatro módulos abriam esses bancos com `_db.sqlite3.connect(f"file:{…}?mode=ro", uri=True)` — usando o
    `import sqlite3` de **outro** módulo.

## 6. Número de processo: um extrator  `[feito]`

- `doe_minerador._processos_no_texto` passa a ser `doweb.extrair_processos`.
  - Reimplementava o laço sobre `doweb._RE_PROCESSO` (privado) **sem** o filtro de submatch que o `doweb`
    ganhou ('61/000.285/2023' contido em '09/61/000.285/2023'). Efeito: extratos do D.O. deixam de listar o
    pedaço do processo como um segundo processo. Medido no corpo de `pcrj_doe_materia` (3.471 matérias):
    224 tinham ao menos um processo-fantasma (ex.: `61/000.285/2023`, pedaço de `09/61/000.285/2023`), que
    deixa de sair. É a única mudança de resultado desta passada; testes casados passam sem alteração.

## 7. Sobras e comentários que repetiam o código  `[feito]`

- Tirar o que não tem razão própria para mudar; o SQL do universo contratual sai das constantes que o
  nomeiam.
  - `universo.py`: `GRUPOS_CONTRATUAIS`/`MODALIDADE_DIRETA` eram declarados e não usados — `_FILTRO_SQL` e as
    três consultas de `resumo()` repetiam `'3','4'` e `'90'` à mão. Agora `_GRUPO_SQL`/`_MODALIDADE_SQL` vêm
    das constantes (SQL gerado idêntico; `resumo()` no banco real: mesmo resultado). `ELEMENTOS_DENTRO`
    (sem leitor) saiu — e dizia "63 = obras em andamento", contradizendo `natureza_despesa.ELEMENTOS["63"]`
    ("Aquisição de Títulos de Crédito").
  - `esfera.esfera_do_cnpj`: nenhum chamador (grep em compliance_agent, tools, rotas, tests, deploy, *.sh).
  - `doe_minerador`: `_RE_OBJETO` e `_RE_VENCEDOR` sem uso; `isinstance(r, (tuple, list))` em
    `minerar_corpus` nunca é verdadeiro (`_ro` devolve `sqlite3.Row`).
  - `pericia_beneficios`: `import decodificar  # noqa: F401 (usado via _orgaos_do_nome)` — não é usado lá
    nem em lugar nenhum por esse caminho; `_LEGISLATURA_YM` sem uso.
  - `dossie_ppp._RE_VALOR` sem uso.
  - Comentários que só repetiam a linha: `camara_servidores:81`, `camara_gabinetes:49`,
    `filiados_brasilio:144`, `resolvedor_municipio:95`, `sei_prefeitura:51`, `esfera:60`, `nomes:34`,
    `cruzamento:111,127`, `comissionados_candidatos:129,132`, `dossie_completo:28`; `folha_pref:74` além de
    repetir era falso ("em streaming" — acumula num `StringIO`). Ficaram os de medição datada, norma,
    decisão do dono e porquê de workaround.
- Segunda volta (revisão independente, etapa 5): `camara_servidores.bridge_para_folha` remontava o caminho
  do compliance.db à mão → `_db.COMPLIANCE_DB`; `os_panorama._reais` era cópia de `formato.brl_rs`.
  Revisão não achou mudança de comportamento não intencional (símbolos removidos sem referência; monkeypatch
  de `beneficio_pcrj.BENEF_DB` segue valendo; sem import circular). Ficaram anotados, porque mudam
  comportamento: `fantasma_servidor:146` e `resolvedor_municipio:70` abrem banco alheio em leitura-escrita
  (o resto usa `db.abrir_leitura`); `dossie_ppp._fmt_reais` devolve `str(v)` para não-número (o `brl`
  devolve 0); `pericia_mestre._q(0)` dá "0" e `formato.e(0)` dá "".
- Mantidos de propósito (parecem mortos, mas têm razão de existir — ver pendências):
  `doweb.reprocessar` (51 das 3.471 matérias guardadas estão desatualizadas e só ele as corrige) e
  `contasrio.carregar_desp_csv` (a tabela `pcrj_despesa_dotacao` existe no compliance.db; é o único
  carregador).

## 8. Pendente — decisão do dono, muda resultado, ou redesenho  `[pendente]`

Defeitos que o levantamento (três leituras independentes do pacote) achou e que mudam resultado — não são
refatoração e não foram reconferidos um a um; cada item precisa de reprodução antes de corrigir:
- `comissionados_candidatos.py:304` — no coletor mensal, `or []` transforma consulta INDISPONÍVEL em "sem
  resultado" e `:345` marca a competência como feita no checkpoint (INDISPONÍVEL ≠ 0). `comissionados_gestao`
  já distingue os dois.
- `doe_minerador.py:169` — `except Exception: rows = []`: banco/tabela ausente vira `{"ok": True, "n": 0}`
  nas rotas `/api/pcrj/doe_*`.
- `analise.py:74-139` — falha de cada motor vira `{"erro":…}`, mas `_consolidar` ignora; todos falhando sai
  "🟢 baixo", score 0. `dossie_ppp.py:216` usa "🟢 baixo" sem análise nenhuma.
- `pericia_beneficios.py:317-321` — erro na contagem de matrículas dá `n_mat=0` e a certeza sobe para ALTA.
- `pericia_socios_beneficio.py:149-157` — erro na leitura das OB vira "sem OB estadual na base" no PDF; e
  para fornecedor municipal o pago devia vir de `pcrj_despesa.pago`, não da OB estadual.
- `fantasma_servidor._faixa` nunca recebe `identidade` (`:243`) → faixa `forte` inalcançável; `dossie_prioritarios`
  (faixa forte) e o KPI "Faixa FORTE" do painel saem sempre vazios/0. A descrição "8 sinais (múltiplos
  gabinetes, cargo incompatível, geografia impossível…)" em `rotas/investigacao.py`, `intel_relatorio.py` e
  `static/js` não bate com os 7 sinais do código.
- `candidatos_nominais.py:62,204` — cargo escapado duas vezes (entidade literal no PDF); `:58-70`
  `except Exception: pass` sobre o laço inteiro.
- `cruzamento.py:116,134` — `zip(gabinetes, vereadores)` desalinha quando um gabinete não tem vereador.
- `triagem_ppp.py:29` — fallback do D.O. com "Smart Hospital" fixo: todo projeto sem edital puxa os atos do
  Souza Aguiar.
- `dossie_ppp.py:160` rotula "Contraprestação mensal" o valor que `pericia_mestre.py:149,238-252` demonstra ser
  ANUAL (R$ 191.773.351,61); `pericia_mestre.py:302-312` chama de "pagamento" valor tirado do texto do D.O.
  (não de `pcrj_despesa.pago`).
- `dossie_ppp.py:214` grava `"analista": "Núcleo de Fiscalização JFN"` — vai ao PDF sem passar por
  `reporting/neutralidade.garantir_neutro`. As três cópias de `_PROIBIDOS` (`pericia_pcrj:26`,
  `pericia_beneficios:692`, `pericia_socios_beneficio:317`) divergem entre si e da régua canônica
  `reporting/neutralidade.py` (uma só avisa, duas levantam exceção); unificar muda o que bloqueia.
- `pcrj_remuneracao.py:135` inventa `(5, 2025)` quando não há competência; `contasrio.py:280` inventa
  `num_aditivos = 1`; `camara_servidores.bridge_para_folha:166` grava remuneração 0 (devia ser NULL).
- `filiados_brasilio.py:83-85` — em 429, `sleep(5)` + `continue` sem limite.
- `universo.DB` e `esfera.construir_mapa(compliance_db="data/compliance.db")` dependem do diretório corrente;
  trocar por `db.COMPLIANCE_DB` muda o banco lido quando rodado de outro cwd.

Redesenhos que pedem decisão:
- DDL do `pcrj.db` em cinco módulos (`db.py`, `leitura_campos`, `folha_pref`, `esfera`,
  `resolvedor_municipio`) → leitores com `try/except` porque a tabela pode não existir. Concentrar em
  `db.inicializar` muda quando as tabelas nascem.
- Universo de "nomes-alvo" com quatro composições diferentes (`tse_candidatos._nomes_servidores`,
  `filiados_brasilio._alvos`, `resolvedor_municipio._nomes_alvo`, `beneficio_pcrj._alvo_nomeados`).
- Download/parse do CSV do TSE duplicado: `tse_candidatos._csv_do_ano` (por cabeçalho) × `comissionados_candidatos._candidatos`
  (por posição) — mesma URL e cache.
- Regras de confiança/homônimo copiadas: `freq_top` e ALTA/MÉDIA em `candidatos_nominais:148-173` ×
  `comissionados_gestao:256-332` (já divergem); limiar "≥3 cidades" em 5 lugares; "inativo" com três
  definições (`candidato_x_folha:71` × `folha_pref._INATIVO`); "eleito" com duas; `_ADM_MIN`/`INICIO`/
  `desde="202101"` (ano 2021) em quatro lugares; `COMPETENCIAS_HISTORICO` (6/2021) × `[(6,2024),(6,2022)]`.
  Unificar muda contagens dos relatórios.
- Onze formatos de `coletado_em` (local sem fuso, ISO com `T` em UTC) misturados no mesmo banco.
- `pericia_mestre.montar_html/gerar_pdf(slug)`: todo o texto é do Souza Aguiar; o `slug` só serve à busca.
- Produtores sem gatilho: `resolvedor_municipio.montar` (lido por `fantasma_servidor`), `doweb.reprocessar`
  (51 matérias desatualizadas hoje), `contasrio.carregar_desp_csv`; `esfera.construir_mapa` grava
  `pcrj_orgao_esfera`, que ninguém mais lê.
- `pericia_gastos._brl/_sev/_achado` são o mesmo contrato de `emendas/pericia.py` (os dois gravam por
  `alertas_persistencia`); a casa natural é o módulo de persistência — cruza áreas.

## 9. Fora do escopo (anotado, não mexido)

- `tools/consulta_nominal_alta.py:117` usa `pb._cargo_comissionado` (privado) — por isso o apelido segue em
  `pericia_beneficios`; o certo é importar `pcrj.cargos.cargo_comissionado`.
- `tools/audit_fairness_pericia.py:15-33` faz parse do texto humano `vinculos` de `pericia_beneficios`.
- `rotas/produtos.py:358,371,373,383,412,708` fixa `"data/pcrj.db"` (dependente de cwd) em vez de
  `pcrj.db.DB_PATH`.
- `pericia_socios_beneficio.py:23` importa o privado `cruzamentos_intel._ob_paga` (módulo de 2.400 linhas).
- `reporting/relatorio_direcionamento.py:71` tem mais uma regex de número de processo.
- `deploy/vm2/sei_pcrj_busca.py:45` reimplementa em JS o parser de `sei_prefeitura.parse_resultado_html`.
- `contasrio.py:24` importa `emendas.coletor.parse_brl` só para converter moeda.
