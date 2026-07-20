# ANÁLISE GLOBAL DO PROJETO — 2026-07-20 (pós dossiê-mestre)

> Encomenda do dono: "analise todo o projeto com melhorias de práticas, debug, wiring, segundo
> cérebro, graphify, git nexus, ajuste de playbook — sempre pensando em uso humano (Yoda + painel)".
> Método: 3 loops de teste-real → refino → reteste executados HOJE; abaixo o retrato e o que resta.

## 1. Saúde geral — retrato honesto

| Dimensão | Estado | Evidência de hoje |
|---|---|---|
| Motor de vícios | 🟢 forte | catálogo canônico (40 vícios, `validar()` zero ponteiro quebrado); 28 detectores; distribuição saudável no dado real (500 certames: 428 BAIXO/61 MÉDIO/10 ALTO/1 EXTREMO — motor que prioriza, não grita) |
| Wiring humano (Yoda/painel) | 🟢 ligado | capabilities 2.3.0; menu curado ≤24; aba Estado→Certames validada por screenshot CDP; Lex R15 nos produtos |
| Testes | 🟢 2.0k+ | suíte completa verde após revisões CONSCIENTES de goldens (rotas +3; ITERJ auditado: sweep corrigiu valores de OB in place) |
| Guardas de qualidade | 🟢 exemplares | catracas de except (baseline auditada 1502), goldens de números/rotas/menu — pegaram TODAS as minhas mudanças de contrato; é o sistema imunológico funcionando |
| Infra/systemd | 🟡 saneada hoje | 2 unidades failed corrigidas (busy_timeout 5min no fisc; TimeoutStartSec 4h no pcrj-intel); `storage_state` do SIAFE falhava MUDO desde o split (F821 `ctx`→`b`) |
| Dados | 🟡 assimétrico | Estado rico em cláusulas (`clausula_veredito`), fraco em resultado-de-sessão (ata agora persiste via produção); PCRJ rico em vencedor (D.O.), sem cláusulas estruturadas |

## 2. Dívidas conhecidas (priorizadas; nenhuma escondida)

1. **Família `execucao` do índice sempre INDISPONÍVEL** — chave de contrato ("-2-") ≠ chave de
   compra ("-1-"): a ponte compra↔contrato não existe. PCRJ já tem `numero_compra` como modelo.
   *Valor: alto (aditivos no índice). Esforço: médio.*
2. **UG (SIAFE) ↔ CNPJ do órgão (PNCP) sem mapa** — o /orgao (UG) não puxa a avaliação de conjunto
   (CNPJ) sozinho; o CNPJ está no prefixo do nº de controle PNCP, falta materializar `ug↔cnpj`.
   *Valor: alto (conjunto dentro do produto /orgao). Esforço: baixo-médio.*
3. **certame_ata só come daqui pra frente** — os 349 processos arquivados são de EXECUÇÃO;
   as atas virão dos processos de licitação que o sweep arquivar (persist já ligado na produção).
   *Ação: nenhuma — tempo resolve; monitorar `sessoes_com_ata` na aba Certames.*
4. **Lacunas declaradas do catálogo** — `deserto_fracassado_dirigido` (precisa série de certames
   por objeto/órgão) e `proposta_dia_nao_util` (precisa timestamps de envio). *Esforço: médio.*
5. **PCRJ sem cláusulas estruturadas** — rodar coletor de editais/E7 sobre editais municipais
   (pncp fonte municipal já coletada). *Valor: paridade Estado×Município no dossiê mestre.*
6. **Curadoria do legado de excepts** — baseline 1502; meta histórica ≤1392 segue aberta.
7. **Lint legado**: `F401 defaultdict` em `pcrj/doe_minerador.py` (inofensivo, não tocado por
   regra cirúrgica).

## 3. Práticas — o que consolidar (aprendizados que viraram regra)

- **Teste real > teste sintético**: 3 FPs estruturais (boilerplate PGE, encaminhamento≠decisório,
  entidades HTML) só apareceram no dado real. Loop obrigatório para todo detector novo.
- **try/except mudo é dívida ativa**: o bug do SIAFE (storage_state nunca salvo) viveu meses atrás
  de um `except Exception: pass`. As catracas existem por isso; respeitá-las SEMPRE (rodar a suíte
  antes de commitar — dois commits históricos passaram por cima).
- **Score sem confiança engana humano**: 100/EXTREMO com confiança 0.14 é meia-verdade; padrão da
  casa: sempre o par (score, confiança) — matriz S×V já trava a verossimilhança.
- **Epistemologia em camadas** (flags A-E): IA nunca produz flag CERTO; C→B só com corroboração
  determinística. Vale para TODO produto novo.

## 4. Segundo cérebro / GitNexus / graphify

- Vault: aprendizados desta fase em `aprendizados/{catalogo-vicios-e-claude-for-legal,
  loops-dado-real-dossie-mestre}.md`; memória persistente reescrita (não empilhada).
- GitNexus: reindexado após a fase (símbolos novos: catalogo_vicios, escalada, flags,
  motivo_inabilitacao, avaliacao_conjunto, rotas conjunto/acatamento).
- graphify: re-ingestão completa NÃO rodada hoje (custo de tokens alto; GitNexus cobre o grafo de
  código; graphify fica para ingestão de DOCUMENTOS novos — decisão consciente, não esquecimento).

## 5. Próxima onda sugerida (F5, em ordem de retorno por esforço)

1. Mapa `ug↔cnpj` + seção de conjunto no produto `/orgao` (fecha o ciclo Telegram).
2. Ponte compra↔contrato → liga a família `execucao` (aditivos) no índice.
3. E7/cláusulas sobre editais MUNICIPAIS (paridade PCRJ).
4. Detector `deserto_fracassado_dirigido` (série por objeto+órgão já existe no corpus).
5. Dossiê Mestre como PRODUTO PDF único (`tools/dossie_master.py` é o esqueleto; seções prontas:
   conjunto, acatamento, fichas por certame).
