# Integração Hermes — Como uma IA fraca opera o PolitiMonitor

Este sistema foi construído para ser **operado por um modelo fraco** (Hermes 3
405B da Nous Research). Tudo é parametrizado, rotulado em pt-BR e exposto por
duas portas simples: **captar o estado** e **executar uma ação do catálogo**.

## O fluxo mental do Hermes (3 passos)

```
1. CAPTAR  → GET /api/estado        (ou ação "captar_estado")
2. DECIDIR → escolher UMA ação do catálogo (GET /api/acoes)
3. AGIR    → POST /api/acoes { nome, params, origem:"hermes" }
```

O `hermes-worker.ts` já roda esse ciclo sozinho a cada 45 min
(`cicloAutonomo()` em `src/lib/hermes.ts`): capta o estado, manda o modelo
escolher UMA ação segura em JSON estrito, e executa.

## Porta 1 — Captar o estado completo

`GET /api/estado` devolve TUDO em um JSON rotulado (limitado a top 5 por seção
para caber no contexto de um modelo fraco):

- `deputado` — nome, partido, estado
- `redes` — perfis próprios e total de seguidores
- `apoiadores` — total, vinculados, com telefone, top por score e por influência
- `posts` — últimos 5 com engajamento e se já notificou apoiadores
- `comentarios` — pendentes
- `cobranca` — apoiadores prioritários que não engajaram
- `melhoresHorarios` — melhor hora e dia
- `adversarios` — share of voice
- `nps` — promotores/passivos/detratores
- `whatsapp` — status da conexão e fila
- `alertas` / `insightsRecentes`

## Porta 2 — Catálogo de ações

`GET /api/acoes` lista todas as ações com **nome, descrição, parâmetros e nível
de segurança**. Cada ação é auto-documentada.

Executar: `POST /api/acoes { "nome": "...", "params": {...}, "origem": "hermes" }`

### Níveis de segurança

| Nível | Significado | Hermes pode sozinho? |
|-------|-------------|----------------------|
| `auto` | Leitura/análise, sem efeito externo | ✅ Sim |
| `aprovacao` | Envia mensagem externa ou altera algo sensível | ❌ Não — vira recomendação (insight) para o humano aprovar |

A trava está em `executarAcao()` (`src/lib/acoes.ts`): se `origem === "hermes"`
e a ação é `aprovacao`, ela **não executa** — cria um insight de recomendação.

### Ações disponíveis (resumo)

**Estado:** `captar_estado`
**Apoiadores:** `ranking_apoiadores`, `metricas_apoiadores`, `quem_cobrar`, `heatmap_engajamento`
**Conteúdo:** `analisar_campanha`, `sugerir_conteudo_viral`, `melhores_horarios`, `analisar_top_posts`
**Comentários:** `comentarios_pendentes`, `sugerir_resposta_comentario`
**Redes:** `sincronizar_redes`, `gerar_relatorio_semanal`
**Adversários:** `share_of_voice`, `sincronizar_adversarios`, `adicionar_adversario`*
**WhatsApp:** `status_whatsapp`, `enviar_whatsapp`*, `broadcast_whatsapp`*, `cobrar_apoiador`*
**NPS:** `calcular_nps`, `disparar_pesquisa_nps`*, `registrar_nps`

\* = requer aprovação humana.

## Auditoria

Toda execução é gravada em `AcaoLog` (acao, origem, params, resultado, sucesso).
Toda recomendação do Hermes vira um `BondInsight` tipo `sugestao`.

## Automações já rodando (sem precisar do Hermes)

- **bond-worker**: sync 30min · notifica apoiadores de post novo (10min) ·
  checklist 6h após cada post · "quem cobrar" diário · ranking semanal ·
  sincroniza adversários (6h) · recalcula streaks.
- **whatsapp-worker**: mantém a conexão Baileys e drena a fila de mensagens.
- **hermes-worker**: jobs de análise + ciclo autônomo (captar → decidir → agir).

## Princípio de design

> Toda capacidade do sistema é uma **ação nomeada** no catálogo, com descrição
> em português simples e parâmetros explícitos. Um modelo fraco não precisa
> entender o código — só precisa ler o catálogo, captar o estado e escolher um
> nome. As ações perigosas nunca disparam sozinhas.
