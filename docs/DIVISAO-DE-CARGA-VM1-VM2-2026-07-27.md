# Divisão de carga entre a VM-1 e a VM-2
## O que migrar, o que jamais migrar, e por quê

| | |
|---|---|
| **Emissão** | 27 de julho de 2026 |
| **Pergunta** | *"será que na vm2 cabe mais coisa pra rodar sem crashar e liberar espaço aqui?"* |
| **Resposta curta** | Cabe muito. A VM-2 está **praticamente parada** enquanto a VM-1 se afoga. |
| **Ressalva** | Nada foi alterado na VM-2. Este documento é **medição e proposta**; a regra do projeto é não mexer nela sem pedido, e o pedido agora existe — mas mudança de infra merece seu aval item a item. |

---

## 1. As duas máquinas, medidas lado a lado

| | **VM-1 `jfn-core`** (100.123.89.59) | **VM-2 `JFN-Agent-2`** (100.74.228.51) |
|---|---|---|
| vCPU | 2 | 2 |
| RAM total | 11,9 GB | 11,9 GB |
| RAM disponível | ~7-8 GB (oscila; já chegou a 117 MB) | **6,7 GB estáveis** |
| Disco livre | — | **161 GB de 194 GB (18% usado)** |
| Load average | **5 a 14** ao longo do dia | **0,11** |
| Cron ativos | **~30 jobs** | **zero** |
| Uptime | reiniciada hoje após travar | 3 dias, sem incidente |
| OCR (`tesseract`) | sim | **sim** |
| Python | 3.12 | 3.12 |
| Syncthing | sim | **sim** (canal de transporte já existe) |
| JFN instalado | sim | **não** |

**As duas máquinas são idênticas em hardware.** Uma faz tudo e cai; a outra não faz nada.

---

## 2. O critério de divisão: sessão, não peso

A tentação é migrar "o que é pesado". Está errado. O critério certo é **o que depende de sessão
autenticada única**:

> O `sweep_sei.sh` traz a razão escrita no próprio código: *"se já há um sei_sweep, NÃO abrir 2ª
> sessão itkava (o SEI expulsa a duplicada)"*. Duas máquinas logando no SEI ao mesmo tempo não
> dobram a captura — **derrubam as duas**.

Daí a linha divisória:

| Fica na VM-1 (sessão / interativo) | Vai para a VM-2 (CPU puro, sem sessão) |
|---|---|
| Sweep SEI com browser (sessão itkava única) | OCR e re-extração de texto |
| `server.py` e o painel (o dono acessa) | Detectores em lote sobre dados já capturados |
| Yoda (Telegram, responde ao vivo) | Indexação da jurisprudência do TCU |
| Captura SIAFE (sessão + MFA) | Cruzamentos e grafos (cartel, QSA, endereços) |
| Geração de parecer sob demanda | Varredura órgão a órgão (a fila de 9.1) |

---

## 3. Candidatos concretos, em ordem de ganho

### 3.1 OCR e re-extração dos 4.695 documentos vazios — **maior ganho imediato**

13% do acervo tem `chars=0`. O `tesseract` é o processo que aparece consumindo 53% de CPU na VM-1
e ele **não precisa de sessão nenhuma** — recebe um PDF, devolve texto.

- **Transporte:** os PDFs já estão em disco; o Syncthing roda nas duas pontas.
- **Risco:** baixo. Nada é escrito no `compliance.db` — a saída é `.txt`.
- **Ganho na VM-1:** libera o pico de CPU que hoje concorre com o browser do sweep.

### 3.2 Indexação da jurisprudência do TCU

`jurisprudencia-selecionada.csv` tem 116 MB e `acordao-completo-{ano}.csv` tem 245 MB por ano — este
último nunca foi ingerido justamente porque é pesado demais para a VM-1. A VM-2 tem **161 GB livres**
e nenhuma disputa de CPU.

- **Risco:** baixo. Gera um SQLite próprio (`tcu_juris.db`), que volta por Syncthing.
- **Desbloqueia:** o item 1.7 do checklist (resposta-consulta e boletim) e o texto integral dos acórdãos.

### 3.3 Detectores em lote — a varredura órgão a órgão

É o pedido *"vai indo de órgão a órgão e buscando suas irregularidades"*. Os 31 detectores são
**código determinístico sobre dados já capturados** — o caso perfeito para a VM-2.

- **Risco:** médio, e é de ESCRITA. O `compliance.db` não pode ser escrito pelas duas máquinas
  (o próprio `CLAUDE.md` avisa que escrever nele trava as rotas de leitura do painel).
- **Desenho seguro:** a VM-2 recebe uma cópia só-leitura do banco, roda os detectores, e devolve
  **um arquivo de achados** (JSON/SQLite separado) que a VM-1 ingere numa janela controlada.

### 3.4 Cruzamentos e grafos

`grafo_cartel`, `rede_societaria`, dedup de endereços. São cargas de CPU e memória sobre dados
estáticos — mesmo desenho da 3.3.

---

## 4. O que **não** migrar, e a razão

| Não migrar | Por quê |
|---|---|
| Sweep SEI com browser | Sessão itkava única — a segunda sessão derruba a primeira |
| Captura SIAFE | Sessão com MFA |
| `server.py` / painel | O dono acessa por aqui; latência e rota importam |
| Yoda | Responde ao vivo no Telegram |
| **Escrita no `compliance.db`** | Duas máquinas escrevendo no mesmo SQLite corrompem o WAL — o projeto já viveu o `database is malformed` |

---

## 5. Pré-requisitos antes de ligar qualquer coisa lá

Aprendidos hoje, do jeito difícil:

1. **Guard de OOM em todo processo de background** (`tools/lib/oom_guard.sh`). A VM-2 tem a mesma
   RAM e o mesmo risco.
2. **Medir o pico de memória de cada passo** com `/usr/bin/time -v` **antes** de pôr no cron. Foi
   assim que descobrimos que o `sei_pais` pedia 10 GB.
3. **Um pesado por vez**, também lá.
4. **Nunca escrever no banco de produção a partir da VM-2.** Saída é arquivo; a ingestão é da VM-1.

---

## 6. Proposta de execução, em três passos verificáveis

| Passo | O que fazer | Como verificar |
|---|---|---|
| **1** | Instalar o JFN na VM-2 em modo só-processamento (sem cron, sem server) | `pytest` da pasta de detectores verde lá |
| **2** | Migrar OCR/re-extração: VM-2 processa, devolve `.txt` por Syncthing | Contador de `chars=0` cai na VM-1; `tesseract` some do topo de CPU |
| **3** | Varredura de detectores em lote por órgão, saída em arquivo | Arquivo de achados ingerido na VM-1 numa janela; painel não trava |

**Nada disso foi executado.** É proposta medida, esperando seu aval — mexer na infra da VM-2 é
decisão sua, e a regra do projeto sobre não atuar nela sem pedido existe por um bom motivo.
