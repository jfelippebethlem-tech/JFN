# HANDOFF — Núcleo de Inteligência Progressiva (2026-07-02)

> **Para outra IA revisar / histórico.** Documenta a construção do `compliance_agent/nucleo/`
> — o motor de perícia determinística com autoaprimoramento em loop — e sua integração ao
> bot Telegram (Yoda). Branch: `claude/procurement-audit-system-mm4fra`. Ver também
> `compliance_agent/nucleo/LEIAME.md` (referência técnica completa do subsistema) e
> `docs/HANDOFF-2026-06-06-completo.md` (estado do ecossistema até então).

---

## 1. Problema que motivou o trabalho

O usuário — deputado estadual, fiscalização de governos — apontou a fragilidade central do
JFN: o sistema depende de **IAs gratuitas/fracas** (Groq, OpenRouter) para interpretar dados
e decidir o que é suspeito, e essas IAs alucinam, ignoram parâmetros e não aprendem com o
uso. O pedido evoluiu em duas etapas nesta sessão:

1. *"Quero que o sistema seja perfeito e super inteligente"* — parametrizar tudo de forma
   explícita, para que a IA fraca só precise **preencher campos**, nunca decidir limiares.
2. *"Crie um jeito dele ser inteligente progressivamente igual a você e aprender a cada
   perícia e realizar autoaprimoramento em loop"* — o sistema deveria melhorar sozinho,
   com prova, pelo mesmo método de um engenheiro: hipótese → teste → mantém se melhorar,
   reverte se piorar.
3. *"Ajuste para podermos trabalhar tudo isso com o Telegram Yoda. Ele é muito burro e
   limitado hoje"* — a inteligência construída precisava ficar operável do celular, sem
   reintroduzir a dependência de LLM que causou a burrice original.

## 2. Arquitetura entregue

```
compliance_agent/nucleo/
├─ parametros.py          Limiares com fundamento legal explícito (lei/tcu/orientativo/
│                         empírico) e faixa sã. Fonte "lei" é travada — nunca calibrável.
├─ dossie.py              Esquema de evidências + validadores determinísticos (CNPJ, CPF,
│                         datas, valores). Fronteira blindada contra lixo de IA fraca.
├─ indicadores.py         ~15 indicadores como funções PURAS: Dossiê → Achado citado
│                         (valor observado, limite aplicado, base legal, confiança).
├─ scoring.py             Agrega achados na matriz TCU Probabilidade×Impacto → rating.
├─ extracao_robusta.py    Quando HÁ edital em texto livre: schema estrito + reparo de
│                         JSON + votação por autoconsistência + validação determinística.
├─ nucleo.py              periciar(...) → Laudo. Orquestra as peças acima.
├─ adaptador_db.py        Liga o Núcleo à base real (SQLAlchemy): periciar_contrato,
│                         periciar_ob, periciar_top_obs.
├─ aprendizado.py         Feedback do perito por indicador → precisão medida → sugestão
│                         de calibração.
├─ memoria_pericial.py    Memória de casos (SQLite stdlib): referência de preço aprendida
│                         por categoria/órgão, perfil de reincidência por CNPJ.
├─ avaliacao.py           Conjunto-ouro de casos rotulados — a "suíte de testes" da
│                         perícia. Métricas F1/precisão/cobertura.
├─ autoaprimoramento.py   Loop: propõe calibrações, testa cada uma isoladamente contra o
│                         conjunto-ouro, mantém só se o F1 subir, reverte o resto. Diário
│                         auditável em data/nucleo_evolucao.json.
├─ ciclo.py               Comando único (python -m compliance_agent.nucleo.ciclo): pericia
│                         em lote → avalia → aprimora → relata.
├─ telegram_nucleo.py     Interface Yoda: comandos determinísticos + roteador de
│                         linguagem natural POR REGRAS (sem LLM).
└─ LEIAME.md              Referência técnica completa (ler antes de mexer no subsistema).
```

**Volume:** 23 arquivos, ~4.000 linhas (código + testes), 5 commits
(`a4738c4` → `14de34d`).

## 3. O ciclo de inteligência progressiva

```
 perícias diárias ──► memória pericial ──► referências de preço cada vez melhores
        │                    │
        │            veredito do perito (confirmado/descartado, via Telegram)
        │                    │
        ▼                    ▼
  conjunto-ouro ◄── casos confirmados podem virar casos-ouro (a régua também evolui)
        │
        ▼
  loop de autoaprimoramento: testa calibrações → F1 subiu? mantém : reverte
        │
        ▼
  diário de evolução (data/nucleo_evolucao.json) — 100% auditável
```

### Garantias provadas por teste (não apenas afirmadas)

| Propriedade | Prova | Teste |
|---|---|---|
| **Segurança** | Com placar F1 perfeito, o loop tenta 25 calibrações e reverte todas; zero resíduo em disco; parâmetros de fonte legal nunca são tocados. | `test_loop_com_placar_perfeito_reverte_tudo`, `test_loop_nao_toca_parametro_legal` |
| **Aprendizado real** | Um caso confirmado que o sistema perdia (quid pro quo com ROI 95×, abaixo do limiar padrão de 100×) faz o loop **encontrar sozinho** a calibração que o captura — e mantém, porque o F1 sobe — sem criar falso alarme novo. | `test_loop_aprende_com_caso_ouro_novo` |
| **Progressão** | Após 6 perícias de uma categoria, a 7ª (superfaturada) dispara **sem ninguém informar a referência de mercado** — a mediana foi aprendida sozinha. | `test_memoria_referencia_progressiva` |
| **Honestidade estatística** | Amostra menor que o mínimo → sem referência (o indicador não inventa mediana). | `test_memoria_amostra_pequena_nao_inventa_referencia` |

## 4. Integração com o Telegram (Yoda)

O ponto de partida foi o diagnóstico: o bot dependia do LLM fraco para **todo** texto
livre, inclusive pedidos de perícia — daí a "burrice". A correção foi arquitetural, não
cosmética: os fluxos periciais passaram a ser **100% determinísticos**, e a IA fraca só
responde ao que sobra.

| Comando | Função | Depende de LLM? |
|---|---|---|
| `/pericia CNPJ\|OB\|nome` | Perícia na hora, direto do banco, com laudo e base legal | Não |
| `/veredito REF confirmado\|descartado` | Feedback do perito → memória → calibração | Não |
| `/placar` | F1 no conjunto-ouro + estado da memória | Não |
| `/ciclo_nucleo` | Roda o loop de autoaprimoramento agora | Não |
| `/fornecedor CNPJ` | Perfil de reincidência aprendido | Não |
| `/parametros` | Limiares vigentes (🔒 legal / 🔧 calibrável) | Não |
| `/evolucao` | Diário do autoaprimoramento | Não |

**Roteador de linguagem natural por regras** (`interpretar_texto_livre`): frases como
*"pericia a MGS Clean"*, *"2024OB01234 procede"*, *"roda o ciclo"*, *"quanto aprendeu?"*
ou um CNPJ/nº de OB solto na mensagem são traduzidas para o comando certo via regex —
sem chamar nenhuma IA. Frases genéricas ("bom dia, tudo bem?") não são capturadas e
seguem para o LLM de conversa, como antes.

**Fechamento do ciclo pelo celular:** toda perícia disparada pelo Telegram entra na
memória automaticamente; todo veredito respondido no chat propaga para a precisão por
indicador e vira lastro da próxima calibração. Fiscalizar pelo celular passou a ser o
que treina o sistema.

## 5. Operação

```bash
# Ciclo completo manual (perícia em lote + avaliação + autoaprimoramento)
python -m compliance_agent.nucleo.ciclo

# Só o placar/estado, sem executar nada
python -m compliance_agent.nucleo.ciclo --status
```

**Agendamento (systemd --user, mesmo padrão de `jfn-ronda.timer`):**

| Unit | Papel |
|---|---|
| `deploy/systemd/jfn-nucleo-ciclo.service` | Oneshot: roda o ciclo completo. |
| `deploy/systemd/jfn-nucleo-ciclo.timer` | Diário, 06:30 UTC, `Persistent=true`. |

Instalação (adicionar aos units já existentes):
```bash
cp deploy/systemd/jfn-nucleo-ciclo.service deploy/systemd/jfn-nucleo-ciclo.timer \
   ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now jfn-nucleo-ciclo.timer
```

**Pelo Telegram:** basta `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` já configurados (como no
restante do bot) — `/ajuda` já lista a seção "🧠 Núcleo de perícia".

## 6. Estado dos testes

| Suíte | Testes | Resultado |
|---|---|---|
| `tests/test_nucleo_inteligencia.py` | 21 | ✅ todos passando |
| `tests/test_nucleo_autoaprimoramento.py` | 7 | ✅ todos passando |
| `tests/test_nucleo_telegram.py` | 19 | ✅ todos passando |
| **Total** | **47** | **✅ 100%, offline, sem rede** |

Todas offline — usam bancos SQLite temporários (`NUCLEO_MEMORIA_DB`,
`NUCLEO_EVOLUCAO_FILE`, `NUCLEO_PARAMS_FILE`, `NUCLEO_FEEDBACK_FILE`,
`NUCLEO_CASOS_OURO` via variável de ambiente), sem chamadas de rede ou de LLM.

## 7. Commits desta sessão

```
a4738c4  feat(nucleo): Núcleo de Inteligência Progressiva — perícia determinística com IA fraca
e94ebbb  feat(nucleo): adaptador banco→Dossiê para periciar a base real
e6ad820  feat(nucleo): ciclo de inteligência progressiva — aprende a cada perícia e se autoaprimora em loop
4c4e942  feat(deploy): timer systemd diário para o ciclo de inteligência progressiva
14de34d  feat(telegram): Yoda opera o Núcleo de perícia — comandos determinísticos + NL por regras
```

## 8. Status honesto — pendências e próximos passos

| Item | Status |
|---|---|
| Perícia determinística parametrizada (sem IA para decidir limiares) | ✅ |
| Memória progressiva (referência de preço, perfil de reincidência) | ✅ |
| Loop de autoaprimoramento com freio de segurança (conjunto-ouro) | ✅ |
| Operação via Telegram sem depender de LLM nos fluxos periciais | ✅ |
| Agendamento diário (systemd timer) | ✅ instalado e ativo na VM em 2026-07-01 (`jfn-nucleo-ciclo.timer`, diário 06:30) |
| Conjunto-ouro alimentado só com casos sintéticos + o que o perito confirmar em produção | ⚠️ Só 8 casos embutidos hoje; cresce com uso real via `/veredito` |
| Mineração de red flags novas (`descobrir_red_flags`) | ✅ implementado; ainda não testado contra volume real de perícias confirmadas |
| Ligação do `/pericia` a fornecedores sem OB ainda coletada (só via PNCP/contrato direto) | 🔲 não coberto — hoje `/pericia` só busca em `OrdemBancaria` |
| Promoção automática de perícia confirmada a caso-ouro (hoje é manual via `adicionar_caso_ouro`) | 🔲 pendente — decisão deliberada de expor isso ao perito ou automatizar com salvaguarda |

## 9. Adendo pós-merge (2026-07-01, sessão de ativação)

Correções aplicadas ao integrar na VM (commits `c9ee249`…):

- **Isolamento de teste**: as 3 suítes dividiam o `mem.db` (o último import na coleta
  do pytest vencia o `os.environ`) — fixtures autouse repinam por módulo/teste. 53/53.
- **Categoria real da OB**: no dado TFE, `categoria` guarda o marcador de fonte
  (`'tfe_ob'`, 1,12M linhas) e a categoria de verdade vive em `tipo_ob` — o adaptador
  agora usa `tipo_ob` normalizado e descarta `Outros`.
- **Inteligência progressiva no fluxo real**: `periciar_ob` passou a `usar_memoria=True`
  (consome referência aprendida E registra); callers pararam de registrar por fora.
- **Quid pro quo estava morto**: `_doacoes_do_fornecedor` fazia `limit(500)` ANTES do
  filtro (542 mil doações) e o enriquecimento só rodava para empresa cadastrada em
  `empresas` (que tem **1 linha**). Corrigido: filtro SQL por raiz + busca por CNPJ do
  favorecido. Prova real: OB 2023OB01363 (Studio Bras) subiu para 🔴 60/100 ALTO.
- **Formato BR** nos valores dos achados (`R$ 117.772,50`, não `R$ 117,772.50`).

**Limite de dado conhecido**: `empresas` tem 1 linha e não há tabela de sanções no
`compliance.db` — IND de empresa recém-aberta/capital/sanção não têm insumo em produção
até existir enriquecimento cadastral (Receita/QSA, CEIS/CNEP). `empresas_min` (74,5 mil)
só tem razão social + natureza jurídica.

> **RESOLVIDO em 2026-07-02** (sessão seguinte, commits `4347367`…): cadastro RFB via
> BrasilAPI (backfill top-200 + on-demand no /pericia + enricher diário consertado),
> CEIS/CNEP local (24,7 mil sanções, refresh semanal `jfn-sancoes.timer`), IND-SIT-01
> (situação cadastral), identificador único `ob:<id>`/`ct:<id>`, `/promover` (caso-ouro),
> /pericia cai p/ contratos, QPQ real (filtro SQL + sem falso-positivo de CPF-prefixo),
> varredura do ciclo mira sancionados. Achados reais da 1ª varredura: IDEAS R$ 57,5M e
> ITPLAN R$ 8,7M pagos com sanção impeditiva vigente.

## 10. Referências

- `compliance_agent/nucleo/LEIAME.md` — referência técnica linha a linha de cada peça.
- `docs/HANDOFF-2026-06-06-completo.md` — estado do ecossistema (JFN/Massare/Yoda/Hermes)
  antes desta sessão.
- Base legal citada nos indicadores: Lei 14.133/2021 (nova LLCA), Lei 8.666/93 (contratos
  legados), Lei 4.320/64, CF/88 Art. 165, metodologia TCU (matriz P×I).
