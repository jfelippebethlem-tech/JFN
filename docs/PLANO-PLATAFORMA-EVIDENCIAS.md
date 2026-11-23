---
tipo: plano
projeto: JFN
atualizado: 2026-11-23
frente: 1123-0334-jfn-core-1d82
fontes: [~/Plano_Diretor_de_Otimizacao_e_Arquitetura_Estado_da_Arte_-_Sweep_SEI.pdf (Gemini), ~/Plano_Diretor_Arquitetura_Sweep_SEI_Reescrita_Total.pdf (ChatGPT)]
---

# Plano de Reescrita — Plataforma de Evidências do Sweep SEI

> **Decisão do dono (23/11/2026):** "se for pra reescrever o sistema, vamos à luta" · "acho que deveria ler tudo
> mesmo" (resumo por IA pode omitir, inventar ou falsear). Este documento avalia os dois planos externos contra o
> código e os dados **medidos** em 23/11 e fixa o desenho executivo.

---

## 1. Veredito sobre os dois planos

| Proposta | Plano | Medido no sistema (23/11) | Decisão |
|---|---|---|---|
| Poda de restritos antes do despacho | Gemini | **Já existe** (`sei_integra_vm2.py:109-125`, reavaliação 30 d). "216/1.137" não se reproduz: 287 de 4.978 tentativas, quase todas reavaliação legítima; desperdício real ≈ 38 | Manter; estender a `sei_integra_fila.py` (não filtra) |
| Captura incremental por documento | ambos | **Parcial**: retoma por `id_documento` só se a pasta local existir; sem `tree_hash`; nó não sabe o que já está guardado → recaptura inteira | **Fase 2** |
| Guarda de convergência da recaptura | ambos | **Parcial**: 2 reprovações → 24 h fora, sem comparar árvore/motivo; 23 processos com ≥ 2, 13 com ≥ 3 | **Fase 0** |
| VM-1 só coordena; fim da "tempestade de crons" | ambos | ~105 crons; 5 pesados simultâneos com swap 100%; despachante com semáforo **já existe** (`propagacao.py:583`) mas os crons antigos correm ao lado; nenhum limite systemd em `jfn.service` | **Fase 0** |
| Disco: expurgo e gatilho | Gemini | VM-1 89%, **VM-2 96%** (frio parado: "só 8 GB livres"); `vm_guard` não olha disco | **Fase 0** (HD externo + gatilho) |
| Triagem por página antes da GPU | Gemini | **Já existe** no worker GPU (`pagina_nativa`); falta página em branco e triagem na reserva | Fase 3 |
| Conferência por recorte (ROI) | ambos | bbox **não é gravada** (Surya: só texto; RapidOCR: descartada); 2ª leitura relê página inteira | **Fase 3** |
| Confirmação pelo SIAFE | ambos | Código existe (`ocr_ia_prova.py:358-400`), **0 de 1.288** confirmações vieram dele | Fase 3 (com a ressalva do ChatGPT: "valor na fonte" ≠ "valor lido") |
| Perícia em 5 eixos numa chamada | Gemini | **Já é uma chamada, com 10 eixos** (`pericia_integral.py:427-456`) | Nada a fazer |
| Prompt caching | Gemini | API Anthropic já usa; **Opus pela assinatura lê ~9k de 127k do cache** (variável antes do fixo); Lex começa pelo variável | Fase 4 (reordenar prefixo) |
| IR resumido (`processo_ir.json`, −90% tokens) | Gemini | Não existe; `manifest.json` em 12.604 pastas é meio caminho | **Rejeitado como substituto do texto** (decisão do dono) → vira **índice determinístico + leitura integral** (§3) |
| Tirar "convergentes" da fila do Opus (5.731 → < 400) | Gemini | Fila: 5.750; entra por **falta de cota**, não por divergência; não há campo de convergência; **Opus concordou em só 28% (108/379)** dos conferidos | **Rejeitado.** Fila passa a ser por risco + amostra (Fase 5) |
| Temporal + NATS + PostgreSQL + MinIO + K8s, 16 semanas | ChatGPT | VM-1 e VM-2 com 2 vCPU/11 GB, swap cheio; um dono | **Rejeitado na forma**; adotado o **conteúdo** (idempotência, lease+fencing, estados, outbox) sobre SQLite e workers existentes (§4) |
| Dataset ouro, modo sombra, canário, gates | ChatGPT | Há bancadas pontuais (OCR 40 págs, régua do Sonnet) mas não um ouro fixo | **Adotado** (Fases 3–5) |
| Metas 2.000–3.000 proc/dia, OCR zerado em 24 h, 80 ms/campo | Gemini | — | Não são metas; são hipóteses medidas contra a linha de base |

**GPU do it-campo:** RTX 5070 **8 GB** de VRAM (o Gemini supôs 12 GB) — muda o tamanho de VLM viável.

---

## 2. Princípios (não negociáveis)

1. **Ler 100% do texto, e provar.** Nenhum estágio de IA trabalha sobre resumo feito por IA. Cobertura
   (caracteres lidos ÷ caracteres do processo) é gravada por processo; < 100% ⇒ "leitura parcial", nunca conclusão.
2. **Índice ≠ resumo.** O índice do processo é extraído **por código** (tipo, página, valores, CNPJ, datas, com
   posição literal). É mapa e verificador, nunca substituto.
3. **Toda afirmação da IA cita trecho literal**, e o código confere que o trecho existe no texto (doc, página,
   posição). Citação que não bate é descartada e registrada.
4. **Proveniência por campo:** motor, versão, página, caixa (bbox), confiança. "Valor encontrado no SIAFE" e
   "valor lido no documento" são fatos diferentes.
5. **Nada substitui o legado sem paridade:** modo sombra nos mesmos processos, comparação com o ouro, e só então
   troca. Desligar legado = decisão registrada.
6. **Idempotência antes de paralelismo:** chave única por trabalho; reserva com prazo e ficha de posse (fencing).
7. Invariantes da casa seguem: OB do SIAFE = pago; INDISPONÍVEL ≠ 0; indício ≠ acusação; só RJ; nuvem só grátis.

---

## 3. Leitura integral comprovada (substitui o "IR resumido")

```
texto completo do processo (nativo + OCR, por página)
   │
   ├─► ÍNDICE (código): docs, páginas, tipo, fase, valores/CNPJ/datas/NE/OB com posição  ── determinístico
   │
   ├─► FATIAS (≤ teto prático, sem cortar documento ao meio quando couber; 100% dos caracteres)
   │      └─► IA por fatia: fatos + citação literal  ──► verificador de citação (código)
   │
   ├─► JUNÇÃO: fatos verificados + índice + SIAFE ──► perícia / Lex / ficha (releem o trecho original quando precisam)
   │
   └─► COBERTURA gravada: chars lidos / chars totais; fatias com erro ⇒ reprocessa ou marca parcial
```

- Hoje há cortes: perícia 240k chars (12k/doc), ficha 60k (8k/peça), Lex 12k. **Medido 23/11 em 10.730
  processos arquivados:** a perícia integral não alcança o texto inteiro em **8.321 (77,5%)**; lê no máximo
  **17,3%** dos 7,19 bi de caracteres do acervo; nos cortados, cobertura mediana 52,6% (p10 14,6%); 19,4% das peças
  passam de 12k e são cortadas por dentro (corte NÃO declarado no laudo; só os docs fora do teto global são).
  Os detectores por código leem tudo. A nova leitura **remove todos os cortes** e substitui por fatiamento.
- **Imediato (antes da Fase 4):** gravar em cada laudo existente a cobertura real (chars lidos ÷ total) e tirar do
  estado VERIFICADO o laudo com cobertura baixa até ser relido.
- Economia vem de **não reler**: fatos por documento ficam guardados pela chave
  `sha256(conteúdo) + versão do prompt + modelo`; documento inalterado não é relido em captura nova.
- Despacho de rotina **é lido** (pode ir a modelo mais barato); não é podado.

---

## 4. Arquitetura-alvo (dimensionada às máquinas reais)

| Camada | Escolha | Por que não a dos planos |
|---|---|---|
| Estado canônico | `data/evidencias.db` (SQLite WAL) atrás de uma camada de acesso única com SQL portável | PostgreSQL somaria ~0,5–1 GB numa VM com swap cheio; a camada permite migrar depois sem tocar consumidores |
| Fila / workflow | tabela `jobs` com `idempotency_key` UNIQUE, `lease_ate`, `fencing` crescente, estados e tentativas classificadas; despachante existente (`propagacao.py`) | Temporal/NATS exigem servidores próprios; o ganho deles (retomada, idempotência) cabe numa tabela |
| Originais | endereçados por `sha256`; morno no **HD externo do it-campo** (ao lado da GPU); frio no Drive pela porta única | MinIO duplicaria a porta única de armazenamento |
| Trabalhadores | captura e GPU no it-campo; CPU (Tesseract, RapidOCR, compactação, depuração, testes) na VM-2; VM-1 só banco, painel, coordenação | — |

**Esquema mínimo** (Fase 1): `processos`, `arvores` (tree_hash por captura), `documentos` (processo, id_documento
SEI), `versoes` (sha256 do original), `paginas` (perfil: nativa/escaneada/branca), `artefatos` (texto por página ×
motor × versão, bbox), `fatos` (valor normalizado, trecho literal, doc, página, bbox, motor, estado de verificação),
`leituras` (cobertura por processo e estágio), `jobs`, `eventos`.

Chaves:
```
documento   = (sistema, processo, id_documento_sei)
versao      = sha256(bytes do original)
arvore      = sha256(json canônico ordenado das entradas da árvore)
job_captura = sha256(processo + arvore + versao_da_politica)
artefato    = sha256(documento + versao + tipo + motor@versão)
```

---

## 5. Fases, critérios de saída e estado

| Fase | Entregas | Critério de saída (medido) | Estado |
|---|---|---|---|
| **0. Segurança operacional** | (a) HD externo como morno: frio da VM-2 → `D:` com hash conferido, VM-2 < 80%; (b) `vm_guard` pausa captura/import com disco ≥ 85% (VM-1/VM-2); (c) crons pesados passam pela trava de carga/despachante; `MemoryHigh` no `jfn.service`; (d) `llm_trace` grava tarefa e tokens de todos os provedores (linha de base); (e) guarda de convergência: mesma árvore + mesmo motivo 2× ⇒ para e vai ao reparo | Load sem 2 pesados simultâneos por 24 h; disco VM-1/VM-2 < 80%; recaptura igual < 5% do tempo de captura; tokens por estágio visíveis | (a) em curso: cópia VM-2 → `D:\JFN-Frio` (23/11 03h46); (b) **não** no `preflight` (impacto CRÍTICO: 26 chamadores, pararia a captura da VM-2) → vigiado pelo sensor `plataforma`; (c) semáforo único `03b485e9`/`6f43c82e` (falta `MemoryHigh` no `jfn.service`); (d) `dacaa738` (falta tokens de openrouter/nous/groq); (e) `b9215330` (29 processos convergentes); vigília `ee290fa6`; cobertura no laudo `e39607ce` |
| **1. Fundação** | `evidencias.db` + camada de acesso; backfill dos 12.604 `manifest.json`; jobs com lease/fencing | Backfill bate 100% com os manifestos; teste de queda de worker sem perda nem efeito em dobro | — |
| **2. Captura por delta** | `tree_hash`; nó recebe a lista `(id_documento, sha)` já guardada; baixa só novo/retificado; versão antiga preservada | Replay 16–23/11 + A/B ao vivo: zero documento novo perdido; processos novos/h ↑ | — |
| **3. Documento e OCR** | perfil por página (incl. branca); bbox gravada; conferência por recorte; SIAFE como nível A; **ouro de ~200 páginas** estratificado com dupla conferência | Não inferior ao atual no ouro; inventado = 0 em campo crítico; tempo por campo medido | — |
| **4. Leitura integral** | índice determinístico; fatiamento 100%; verificador de citação; cache de fatos por sha; prefixo fixo antes do variável | Modo sombra em ≥ 50 processos já conferidos pelo Opus: recall de achados ≥ legado, cobertura 100%, 0 citação inexistente aceita | — |
| **5. Fila do Opus por risco** | entra por divergência, valor alto, detector grave, baixa confiança em campo crítico, **amostra estratificada** de controle; recall medido pela amostra | Vazão da fila ≥ entrada; recall da amostra registrado por mês | — |
| **6. Migração** | perícia, Lex, ficha e 360 consomem a plataforma; legado desligado módulo a módulo | Paridade + decisão registrada por módulo | — |

---

## 6. Riscos

| Risco | Mitigação |
|---|---|
| Leitura integral aumenta tokens | cache de fatos por sha (não reler), prefixo fixo, rotina em modelo barato; medir custo por processo na Fase 0 antes de ligar |
| HD externo desplugado | presença conferida antes de ler/gravar; ausência ⇒ "INDISPONÍVEL", nunca "não existe"; Drive mantém a cópia |
| Reescrita parada no meio | cada fase entrega valor sozinha e não quebra o legado |
| SQLite como gargalo de escrita | um escritor (coordenador); workers devolvem lotes; camada de acesso permite PostgreSQL depois |
