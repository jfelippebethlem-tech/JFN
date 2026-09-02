# VM-2 (JFN-Agent-2) — o que ela é, e o que NÃO é

Medido em 2026-08-29, ao atualizar as duas máquinas.

## O que ela roda

- **`~/JFN` é cópia por rsync, NÃO é repositório git** (`fatal: not a git repository`). Atualizar
  é `scp` arquivo a arquivo; `git pull` não existe lá.
- **Crontab VAZIO.** O `sei_sweep` roda comandado de fora, em `--max 12`, com **fatia própria do
  universo**: `fatia 1/2: 20695 de 41740 processos são desta máquina`.
- Roda também a suíte de testes em lote e o `massare.dashboard` (que **não é do JFN**).

## O `~/vault` da VM-2 NÃO é o segundo cérebro

Aponta para **`gitnexus.git`**, branch `main`, com estrutura própria (Bases, Boards, Daily,
Hypotheses) e **zero casos**. O segundo cérebro do JFN é o `~/vault` da **VM-1** (`vault.git`,
branch `master`, 71 casos e 76 aprendizados). São repositórios diferentes com o mesmo caminho —
mexer no da VM-2 achando que é o nosso apagaria trabalho alheio.

## Tabelas que NÃO existem na VM-2

`socio_historico` e `sei_leitura_dupla` vivem só na VM-1. Por isso `troca_de_controle` e
`pago_sem_contrato` devolvem **vazio** lá — é ausência de fonte, não erro. `contratos_tcerj` existe
(35.438 linhas) e `contrato_acima_do_porte` roda normalmente (407 empresas).

## O QUE ESTAVA QUEBRADO — e como se descobre

A VM-2 estava **capturando sem extrair ficha desde 27/08/2026 às 02:33**, e **o log não registrava
erro nenhum**. Falha silenciosa: o modelo `stepfun/step-3.7-flash:free` saiu do catálogo e passou a
devolver `400 missing tags`, mas o sweep seguia gravando "login OK — varrendo".

**Como diagnosticar isto de novo:** comparar a data da última linha com `ficha[` no
`sei_sweep_loop.out` contra a data da última captura. Se a captura é recente e a ficha é antiga, o
LLM morreu — não é cota. Teste direto: `POST {base}/chat/completions` com o modelo da constante
`STEPFUN`; se der 400/404, listar `GET {base}/models` e filtrar `pricing.prompt == 0`.

Corrigido em 29/08 (`meituan/longcat-2.0:free`), com prova de ponta a ponta: a extração devolveu
objeto, modalidade, fundamento legal e valor corretos.
