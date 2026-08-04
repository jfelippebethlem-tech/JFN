# RUNBOOK — o que rodar, em que ordem, e como saber se deu certo

> Escrito para ser seguido **sem julgamento**: por uma IA fraca, por um operador apressado, ou por
> ninguém (o cron). Cada passo tem comando, resultado esperado e o que fazer se falhar.
> Se um passo exigir decisão, ele está marcado com 🧑 **PARE e pergunte ao dono**.

---

## 0. Antes de qualquer coisa pesada

```bash
cat /proc/loadavg
```

**Regra dura da casa:** primeiro número **≥ 4** → *adiar*, nunca paralelizar. São 2 vCPU. Já
derrubou a VM quatro vezes. Nada abaixo nesta página vale mais do que essa regra.

O que conta como pesado: suíte de testes, Chromium/OCR, DuckDB, reavaliação do acervo.

---

## 1. "Mexi num detector. E agora?"

```bash
python -m tools.pos_correcao
```

Faz o ciclo inteiro sozinho: fotografa o estado → reavalia os 2.174 processos → regrava
`data/fila_fiscal_360.md` → imprime **só o que mudou**.

- É retomável: se cair no meio, rode de novo e ele continua de onde parou.
- Não começa com load ≥ 4 (avisa e sai com código 1).
- **Não roda a suíte** — isso é o passo 2, e é decisão de quem está no teclado.

Se você só quer ver o estado sem escrever nada:

```bash
python -m tools.pos_correcao --so-medir
```

O mesmo retrato está no painel em **Instrumentação → Estado do motor**. Painel e diff usam a
mesma função, então não podem divergir.

---

## 2. Testes — SEMPRE em lotes

```bash
for k in 1 2 3 4; do
  .venv/bin/python -m pytest -q -p no:randomly $(.venv/bin/python -m tools.ci_lote $k 4)
done
```

Nunca rodar a suíte monolítica: ela já derrubou a VM quatro vezes. Esperado hoje: ~5.720 passed,
6 skipped, **0 failures**.

Falhou? Leia a mensagem — as catracas desta casa explicam o motivo no próprio texto do erro
(`except Exception` a mais, formato de moeda americano, rota sem superfície, painel desatualizado).

---

## 3. "O sistema está rodando sozinho?"

```bash
crontab -l | grep -c sweep          # sweeps agendados
tail -3 data/sweep_sei.log          # captura SEI (*/30)
tail -3 data/sweep_dados.log        # reparos e rankings (10h e 16h)
tail -3 data/sweep_360.log          # avaliação e fila do fiscal (a cada 4h)
```

O que cada um garante, sem ninguém empurrar:

| Sweep | Faz | Por que importa |
|---|---|---|
| `sweep_sei.sh` | captura processos do SEI | é o gargalo: a fila está em anos de atraso |
| `sweep_dados.sh` | repara documento vazio pelo PDF em cache, recaptura o cortado em 20k, recalcula o ranking de TAC | tudo isso já ficou pronto e sem caller — hoje tem catraca (`test_ferramenta_tem_quem_a_rode`) |
| `sweep_360.sh` | avalia em **rodízio** (nunca avaliado primeiro, depois o mais desatualizado) e regrava a fila do fiscal | é o que faz o acervo CONVERGIR sozinho depois de uma correção |

---

## 4. Rodar sem IA nenhuma

O caminho determinístico **não depende de LLM**: `processo_360.avaliar()` tem `com_llm=False` por
padrão e o lote do cron não passa `--com-llm`. Sem chave de API, o motor continua produzindo
faixa de risco, achados e lacunas. Dois testes protegem isso
(`test_ferramenta_tem_quem_a_rode.py`).

O que a IA acrescenta quando existe: juízo por documento e narrativa dos produtos. O que ela
**nunca** decide: se um achado existe.

---

## 5. As três perguntas que evitam relatório errado

1. **De onde veio o número?** OB do SIAFE é pagamento; empenho e liquidação não são.
2. **Quem afirmou isso, e sobre o quê?** Citar a PGE não faz o documento ser da PGE; "reitera-se"
   sozinho não é descumprimento; situação cadastral de hoje não vale para o ato de 2023.
3. **A contagem é redonda?** 1.000, 500, 10.000 repetidos = teto de coleta, não realidade.

Detalhe de cada uma em `~/vault/aprendizados/CATALOGO-DE-FALHAS.md` (famílias 12 a 16).

---

## 6. Quando PARAR e perguntar 🧑

- Qualquer coisa que **apague** dado (o padrão da casa é declarar e quarentenar, nunca apagar).
- `--aplicar`/`--force` em ferramenta que você não rodou antes em modo relatório.
- Publicar número para fora: antes, conferir se a fonte é a canônica e se a janela de cobertura
  está declarada.
- Mexer na VM-2, no painel de outro dono, ou em qualquer coisa fora de `~/JFN`.
