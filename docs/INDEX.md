# 📑 Índice de `docs/` — catálogo enxuto

> **Hub do projeto = [REFERENCIA-PROJETO.md](REFERENCIA-PROJETO.md)** (estado vivo, roadmap, lições, retomada).
> Conhecimento jurídico/orçamentário completo = [CLAUDE-REFERENCIA-COMPLETA.md](CLAUDE-REFERENCIA-COMPLETA.md).
> Os demais são **referência por tema** (consultar sob demanda). Sessões/handoffs datados → [`historico/`](historico/).
> Regra de leveza: **não ler tudo** — abrir só o doc do tema em questão.
> **Como X funciona no código** (caminho/callers/símbolos) → `gitnexus_query("X")` / `gitnexus_context({name})`
> (não está nestes docs — o GitNexus indexa o código). Fatos de dados (DB/UG/SIAFE/SEI) → CLAUDE-REFERENCIA-COMPLETA.md.

## 🎯 Canônicos (começar aqui)
| Doc | Para quê |
|---|---|
| [REFERENCIA-PROJETO.md](REFERENCIA-PROJETO.md) | Estado vivo + roadmap + lições + retomada (1 linha/sessão no §10). |
| [ARQUITETURA-AGENTICA.md](ARQUITETURA-AGENTICA.md) | **Organograma do sistema agêntico em 1 página** (Yoda→API→metabolismo→aprendizado + fontes únicas + guard-rails). |
| [CLAUDE-REFERENCIA-COMPLETA.md](CLAUDE-REFERENCIA-COMPLETA.md) | Jurídico/orçamentário completo (modalidades, ilícitos, CEIS/CNEP, P×I, SIAFE, UGs). |

## ⚙️ Operação & capacidades
| Doc | Para quê |
|---|---|
| [CAPACIDADES.md](CAPACIDADES.md) · [COMANDOS.md](COMANDOS.md) | O que o sistema faz / comandos do Yoda. |
| [PLAYBOOK-EXECUTOR.md](PLAYBOOK-EXECUTOR.md) · [PLAYBOOK-SEI.md](PLAYBOOK-SEI.md) | Como executar tarefas (passos idempotentes) / caminho único do SEI. |
| [RUNBOOK-BOOT-E-ANTIIDLE.md](RUNBOOK-BOOT-E-ANTIIDLE.md) | Boot da VM + guarda anti-idle (Oracle Always Free). |
| [METODOLOGIA-EMPRESA-FANTASMA.md](METODOLOGIA-EMPRESA-FANTASMA.md) | Método /fantasma (8 sinais determinísticos). |
| [MASSARE-SUBMODULO.md](MASSARE-SUBMODULO.md) · [MIMO-CONTEXT.md](MIMO-CONTEXT.md) · [MANUAL-FISCALIZACAO-MIMO-2026-06-28.md](MANUAL-FISCALIZACAO-MIMO-2026-06-28.md) | Submódulo Massare / contexto e manual p/ o MiMo. |
| [PREFERENCIAS-MESTRE-JORGE.md](PREFERENCIAS-MESTRE-JORGE.md) | Preferências do dono. |
| [STORAGE.md](STORAGE.md) · [OTIMIZACAO.md](OTIMIZACAO.md) · [JFN-PIPELINE-OBS.md](JFN-PIPELINE-OBS.md) | Storage, otimização, pipeline de OBs. |
| [BRANCHES-POR-SO.md](BRANCHES-POR-SO.md) · [YODA-MULTIUSUARIO.md](YODA-MULTIUSUARIO.md) · [MODELO-ESTRATEGIA.md](MODELO-ESTRATEGIA.md) | Branches por SO, multiusuário do Yoda, estratégia. |

## 🗃️ Fontes & dados
| Doc | Para quê |
|---|---|
| [CONTROLES-FONTES-DADOS.md](CONTROLES-FONTES-DADOS.md) | Catálogo de fontes e seus controles (proveniência). |
| [FONTES-FOLHA-PAGAMENTO-RJ.md](FONTES-FOLHA-PAGAMENTO-RJ.md) · [FOLHAS-FONTES.md](FOLHAS-FONTES.md) | Folha de pagamento do RJ. |
| [SCRAPING-SITES-DIFICEIS.md](SCRAPING-SITES-DIFICEIS.md) | Técnicas p/ sites com WAF/anti-bot. |

## 🏛️ SIAFE-Rio
| Doc | Para quê |
|---|---|
| [SIAFE-ARQUITETURA.md](SIAFE-ARQUITETURA.md) · [SIAFE-NAVEGACAO.md](SIAFE-NAVEGACAO.md) · [SIAFE-RIO2-GUIA-AUTOMACAO.md](SIAFE-RIO2-GUIA-AUTOMACAO.md) | Arquitetura, navegação e automação do SIAFE. |
| [PESQUISA-SIAFE-ADF-PPR.md](PESQUISA-SIAFE-ADF-PPR.md) | Pesquisa ADF/PPR. |

## ⚖️ Jurídico (Lex)
| Doc | Para quê |
|---|---|
| [LEX-BASE-JURIDICA.md](LEX-BASE-JURIDICA.md) · [LEX-DOUTRINA-IMPROBIDADE.md](LEX-DOUTRINA-IMPROBIDADE.md) | Base legal + doutrina de improbidade. |
| [LEX-APRENDIZADOS-CGE-CASHPAGO.md](LEX-APRENDIZADOS-CGE-CASHPAGO.md) | Aprendizados de caso (CGE/CashPago). |
| [PESQUISA-DIREITO-ADMIN-CGE.md](PESQUISA-DIREITO-ADMIN-CGE.md) · [PESQUISA-DIREITO-ADMIN-DOUTRINA-RJ.md](PESQUISA-DIREITO-ADMIN-DOUTRINA-RJ.md) | Direito administrativo / doutrina RJ. |

## 🤖 IA / cérebro de direcionamento
| Doc | Para quê |
|---|---|
| [DIRECIONAMENTO-CEREBRO-SPEC.md](DIRECIONAMENTO-CEREBRO-SPEC.md) | Spec do motor de raciocínio de direcionamento/fraude. |
| [BENCHMARKS.md](BENCHMARKS.md) | **Índice único de TODOS os benchmarks** (IA e produto) — começar por aqui. |
| [IAS-ECOSSISTEMA-BENCHMARK.md](IAS-ECOSSISTEMA-BENCHMARK.md) · [IAS-FRACAS-GUIA.md](IAS-FRACAS-GUIA.md) | Benchmark de modelos + guia p/ IAs fracas. |
| [vereditos_pericia.md](vereditos_pericia.md) | **GERADO** por `tools/vereditos_para_rag.py` (ledger de vereditos p/ o RAG) — não editar à mão. |

## 📈 Avaliações & evolução (contexto, baixa frequência)
| Doc | Para quê |
|---|---|
| [AVALIACAO-BR-ACC.md](AVALIACAO-BR-ACC.md) | Avaliação do br-acc (resolução de entidade). |
| [ECOSSISTEMA-EVOLUCAO.md](ECOSSISTEMA-EVOLUCAO.md) · [FLEXVISION-EVOLUCAO.md](FLEXVISION-EVOLUCAO.md) | Evolução do ecossistema. |
| [EXTREME-DIGITAL-ACHADO-E-PROXIMO-PASSO.md](EXTREME-DIGITAL-ACHADO-E-PROXIMO-PASSO.md) · [APRENDIZADOS-SESSAO-2026-06-07.md](APRENDIZADOS-SESSAO-2026-06-07.md) | Achado pontual + aprendizados. |
| [SEI-EVOLUCAO-TENTATIVAS.txt](SEI-EVOLUCAO-TENTATIVAS.txt) · [SIAFE-EVOLUCAO-TENTATIVAS.txt](SIAFE-EVOLUCAO-TENTATIVAS.txt) | Diário de tentativas SEI/SIAFE (o que já foi tentado — ler antes de reinventar). |

## 🗄️ Histórico ([`historico/`](historico/))
Handoffs e relatos de sessão datados — **superados** pelo REFERENCIA-PROJETO; mantidos só como histórico
(o git já guarda o detalhe). 22 docs: `HANDOFF-*`, `SESSAO-*`, `RESUMO-*`, `ANALISE-POS-SWEEP-*`, `LOOP-MELHORIA-*`,
`PLANO-BENCHMARKS-*`, `REAVALIACAO-*`, `PROXIMA-SESSAO`, `JFN-2.0-IMPLEMENTACAO`, `AVALIACAO-WORKFLOW-SESSAO-IAS`,
`ECOSSISTEMA-ANALISE-*`, `RELATORIO-ECOSSISTEMA-*`.
