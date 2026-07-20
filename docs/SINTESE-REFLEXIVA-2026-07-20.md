# Síntese reflexiva do projeto — 2026-07-20 (pós pacote completo)

> Análise estratégica de fechamento dos loops (catálogo de vícios → dossiê mestre F1-F5 →
> pacote completo G1-G7). Não é lista de features (essas estão nos commits `7942959b`→`90e00b65`);
> é o que APRENDEMOS sobre como o sistema deve ser construído e usado. Foco: uso humano (Yoda + painel).

## 1. Padrões que viraram doutrina (padronizar sempre)

- **Epistemologia em camadas (flags A-E).** Todo achado carrega seu grau: A CERTO (determinístico
  com número+fonte+teto), B FORTE (convergência ≥2 famílias), C SUSPEITO (juízo de IA), D
  NÃO-AFERÍVEL, E EXCULPADO. **IA nunca produz A** — teto é C; C→B só com corroboração determinística.
  `editais/flags.grau_flag` é a fonte única. Vale para QUALQUER produto novo.
- **Gabarito em código > LLM fraca.** `motivo_inabilitacao` (trivial×substancial), `teste_finalistico`
  (tetos sumulados), `neutralidade` (termos proibidos): o limiar mora no código, a IA só classifica
  com citação obrigatória. Substancial vence empate (precisão > cobertura).
- **INDISPONÍVEL ≠ 0, sempre.** Toda seção/detector degrada honesto e o diz. O dossiê só anexa o que
  existe; o índice não zera família sem dado (reduz confiança). Score sempre pareado com confiança.
- **Fonte única > catálogos paralelos.** `catalogo_vicios.py` uniu 3 acervos que viviam soltos; a
  lição repete em `neutralidade.py` (gate antes espalhado em dossie_master). Unificar > empilhar.
- **Foco > despejo.** O capítulo de cláusulas mostrava 121 linhas NÃO-AFERÍVEL; refinado para as com
  veredito + tier forte, resto resumido. Produto que grita tudo não prioriza nada.

## 2. Debug patterns (assinaturas dos bugs desta sessão — reconhecer de novo)

| Sintoma | Causa raiz | Lição |
|---|---|---|
| Rota trava >60s, /api/lista instantâneo | `LEFT JOIN pncp_resultado` explodia no CNPJ guarda-chuva (milhares de linhas × GROUP BY) | JOIN para "pegar 1 nome" → subquery escalar com LIMIT 1 |
| "Carregando…" eterno no painel, rota lenta só às vezes | enxame ESCREVENDO no compliance.db trava leituras mode=ro (lock) | jobs de escrita (enxame) rodam OFF-HOURS; nunca junto do uso do painel |
| `storage_state` nunca salvo (SIAFE anti-MFA) | `except: pass` mudo sobre variável errada (`ctx`→`b`, F821) | F821 do ruff em arquivo "alheio" pode ser bug SEU; try/except mudo esconde por meses |
| Enxame poluía log, sinal de beneficiário morto | query em coluna inexistente (`raiz`) degradava silencioso | conferir schema real (`cnpjs_basicos`), não presumir nome de coluna |
| Golden diverge após mudança de texto | edição intencional de saída | regravar golden DE PROPÓSITO e documentar no commit |
| IGNORADO falso em acatamento | boilerplate de PGE + "encaminhamento" contado como decisão | teste com DADO REAL antes de dar por pronto — FP estrutural só aparece no real |

## 3. Wiring — como o produto chega ao humano (Yoda + painel, o único acesso do dono)

- **Contrato único = `capabilities.yaml`** (v2.3.0). O Yoda só chama id presente ali; menu curado ≤24
  itens (o resto por linguagem natural). Toda rota nova precisa: entrada no yaml + golden de rotas
  regravado + (se for produto) `enviar_telegram: [path_pdf]`.
- **Assíncrono empurra no Telegram.** `/api/dossie/completo`, `/api/dossie/mestre`, `/orgao` seguem o
  padrão: responde `{status:"gerando"}` na hora, dispara `asyncio.create_task`, empurra PDF quando
  pronto. Pausa sweeps durante a geração; retoma no `finally`.
- **Painel = espelho determinístico.** Cada aba lê uma rota GET rápida (<1s). Regra dura descoberta
  hoje: aba não pode encadear await em rota que possa contender com escrita — se contender, trava.
- **Neutralidade é gate de saída, não de intenção.** `garantir_neutro(render_html(ctx))` ANTES de
  enviar QUALQUER PDF; teste trava os goldens. Deliverables e painel = zero "JFN"/"Lex"/paths internos.

## 4. Segundo cérebro (organização profissional da memória)

- **Camadas:** vault `aprendizados/` (lições com Why/How), `casos/` (44 casos), `codigo/` (pipelines);
  memória persistente `~/.claude/.../memory/` (MEMORY.md índice + 1 fato por arquivo, frontmatter).
- **Regra:** reescrever a nota relevante (não empilhar); linkar `[[nome]]`; converter data relativa em
  absoluta. Notas desta sessão: `dossie-completo-pacote`, `dossie-mestre-f5`, `catalogo-vicios-canonico`,
  `loops-dado-real-dossie-mestre`.
- **O que registrar:** o não-óbvio (por que uma decisão, uma armadilha de dado), nunca o que o código
  já conta. As lições de contenção/debug acima estão gravadas — é o que evita repetir o erro.

## 5. GitNexus + graphify (cérebros de código)

- **GitNexus** reindexado hoje: 29.576 nós / 45.004 arestas / 300 fluxos. Usar `gitnexus_impact` antes
  de editar símbolo compartilhado e `gitnexus_detect_changes` antes de todo commit (fiz nesta sessão —
  pegou o escopo real das mudanças, risco baixo/médio confirmado).
- **graphify** rodou 2026-07-20; cobre documentos/conhecimento, complementar ao GitNexus (código).
  Não re-ingerir por rotina (custo de token) — só quando entrar corpo NOVO de documentos.

## 6. Playbook — ajustes feitos

- `CLAUDE.md` (JFN) ganhou o gatilho NÃO-REINVENTAR nº 5 (catálogo de vícios/flags/escalada) e agora o
  nº 6 (dossiê completo + gate de neutralidade + enxame off-hours) — ver abaixo.
- `capabilities.yaml` 2.3.0 (+dossie_completo, +conjunto/*, +sei_acatamento, +certame_indice).
- Changelog em `docs/REFERENCIA-PROJETO.md` §10.

## 7. Recomendações de uso humano (o que o dono precisa saber)

1. **Pedir "dossiê completo do CNPJ X"** no Yoda → PDF único (fachada + cláusulas íntegra + suspeitas +
   SEI) + análise jurídica + planilha, tudo neutro, no Telegram.
2. **Pedir "/orgao <nome>"** → inteligência + Lex + planilha + conjunto por unidade + nomeações datadas.
3. **Painel → Estado/Prefeitura → Certames** → ranking por órgão E por secretaria (INEA, Fundo Saúde…).
4. **O índice do RJ acende com o tempo** — o enxame roda off-hours e enriquece a restritividade; hoje
   136 certames RJ têm veredito, subindo. Não rodar o enxame à mão durante o uso do painel (trava).
5. **Tudo que sai é neutro** — nenhum documento menciona a ferramenta; podem ir a terceiros/CPI.

## 8. Dívidas remanescentes (honestas, para a próxima onda)

1. Índice RJ ainda sub-powered (só 136/1400 certames com veredito) — o enxame off-hours resolve com tempo.
2. Nomeações do órgão casam por sigla (dado municipal); UGs estaduais sem match → seção degrada honesta.
3. `avaliar_portfolio`/`unidades` deveriam ter timeout/lock-graceful para não travar 30s sob contenção
   de escrita (mitigado por rodar enxame off-hours; robustez fina fica para depois).
4. Lacuna `proposta_dia_nao_util` do catálogo (falta timestamp de envio no PNCP).
