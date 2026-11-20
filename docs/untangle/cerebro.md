# Untangle — segundos cérebros (registro de decisões)

| | |
|---|---|
| **Escopo** | `compliance_agent/cerebro_{compartilhado,busca,fts,ponte,consolidacao}.py` · `certeza/` · `propagacao.py` (descobertas → cérebro) · `memoria.py` · `casos_vault.py` · `requerimentos_vault.py` · `vault_retratos.py` · `tools/cerebro_bateria.py` · `deploy/vm2/brain/` |
| **Data** | 20/11/2026 — worktree `agent-a85508a7901f2c8e6`, base `origin/ui/painel-v61-tron-claro` (`4b9d1d39`) |
| **Opções** | Comentários = SIM (mantida medição datada e decisão do dono) · Testes = NÃO (nenhum teste removido; só renome mecânico onde o símbolo mudou) |
| **Pergunta única** | "Estas peças devem mudar juntas?" |
| **Levantamento** | 46 problemas, por subagente só-leitura + leitura própria; prova `arquivo:linha` da árvore de base |

Legenda: **FEITO** (commit) · **MANTIDO** (caso especial que o sistema ainda precisa, com o motivo) · **ANOTADO**
(fora do escopo desta frente ou preso a teste que não pode ser reescrito aqui).

---

## 1. Consertos, com os problemas que cada um resolve

### 1.1 O cliente do cérebro tem API pública; ninguém mais usa o interno nem remonta o caminho do banco — FEITO (`0b532159`, `5335e49e`)

`cerebro_compartilhado` é dono do transporte, do portão de saída e do registro local. Ganhou `conectar`, `banco`,
`preparar`, `RECUSAS`, `RX_CNPJ`, `gravar_memoria`, `pares_semelhantes`.

- `cerebro_ponte.py:55` usava `cerebro._RECUSAS`; `:270`, `:292`, `:403` usavam `cerebro._con()`.
- `cerebro_consolidacao.py:94`, `:185`, `:203` chamavam `cerebro._http` com a rota escrita à mão.
- `cerebro_ponte.py:56` e `cerebro_compartilhado.py:74` tinham a MESMA regex de CNPJ, cada um a sua cópia.
- `certeza/citacoes.py:225` montava `config.REPO/'data'/'propagacao.db'` (ignorava `JFN_DATA_DIR`);
  `cerebro_busca.py:145` montava `cerebro.DATA/'propagacao.db'`.
- `propagacao.py:138` criava a tabela `cerebro` por fora (`con.execute(cerebro.DDL)`): esquema novo exigia lembrar
  dos dois lugares. Agora os dois chamam `cerebro.preparar`, que também migra o banco antigo.
- `cerebro_ponte.py:283` (`_cnpj_fmt`) repetia `cerebro_fts.grafias`.

### 1.2 `caso` mora na busca, não no cliente — some o import circular — FEITO (`0b532159`)

`caso` compõe recall + busca fundida + registro de fatos; quem compõe é a camada de cima.

- `cerebro_compartilhado.py:273` importava `cerebro_busca` de forma tardia porque `cerebro_busca.py:43` importa o
  cliente (ciclo escondido atrás de um import dentro da função).
- `certeza/orquestrador.py:78` e `:141` importavam o cliente dentro da função sem haver ciclo.
- A CLI documentada no `CLAUDE.md` (regra 9) continua igual: só a borda da CLI alcança a busca.

### 1.3 Uma leitura de "menção a valor superado", com a data como parte do fato — FEITO (`4abefb5d`, `0b532159`)

O verificador e a recuperação precisam da mesma resposta ("este texto traz valor superado? é histórico?"). Passou
a existir uma função (`citacoes.mencoes`, com `historico`) e duas leituras dela: divergência (`mencoes_superadas`)
e aviso na resposta (`cerebro_busca.caso`).

- `certeza/citacoes.py:135` tratava memória imutável e nota viva do mesmo jeito → 4 falsos alarmes (histórico datado).
- `certeza/citacoes.py:180` (`arquivos`) e o laço da busca tinham regras de "ignorar" diferentes → o alarme se
  realimentava pela nota diária da automelhoria.
- `certeza/citacoes.py:233–258`: a unidade de "lido" era a superfície inteira; com teto de 12 buscas para 34
  valores a superfície nunca era lida → divergência do índice nunca curava. A unidade passou a ser a busca.
- O verificador só via o registro LOCAL de memórias; a memória gravada à mão pelo MCP (#456) ficava de fora.

### 1.4 O aceite da consolidação respeita o dono da chave — FEITO (`0c6352c7`)

- `cerebro_consolidacao.py:203–206` gravava a versão aceita direto no cérebro, com a `chave` de A, sem passar pelo
  registro local: o `mem_id` de lá ficava velho e a correção seguinte da rotina substituiria uma versão já saída.

### 1.5 O ponteiro de prova viaja com o fato — FEITO (`5335e49e`)

- `cerebro_ponte.py:80` devolvia só verdadeiro/falso; o trecho localizado era jogado fora e reconstruído em prosa
  no texto do fato ("citação literal localizada"). `cerebro_compartilhado.py:197` não tinha campo para a prova.

### 1.6 Comentários que só repetiam o código — FEITO (commit do untangle)

- `cerebro_busca.py` (`_perna_entidade`), `cerebro_ponte.py:404`, `memoria.py:15` e `:24`. Mantidos todos os que registram medição
  datada, decisão do dono ou fato externo (proxy, limite do serviço, WAF).

---

## 2. Casos especiais MANTIDOS (o sistema ainda precisa deles)

| Onde | Caso especial | Por que fica |
|---|---|---|
| `cerebro_busca.py` — perna `khoj`, `K_RRF`, parâmetro `com`, `_nota` | perna de um serviço aposentado | Aposentadoria **reversível** e decisões D1/D2 do dono em aberto; a Fase 3 usa o Khoj como régua (14 de 20). Sai quando D1 for confirmada |
| `JFN_CEREBRO_FUNDIDO=0` · `BRAIN_BUSCA=antiga` | segundo caminho vivo | São a reversão escrita no plano de fases (§8); usados em 19/11 para medir o "antes" |
| `cerebro_consolidacao.py:164` — nova tentativa por `"ocupado" in motivo` | retry por substring | O motor só expõe o motivo como texto (`claude_motor.ultimo_motivo`); mudar é no motor (fora desta frente) |
| `cerebro_consolidacao.py:170` — `endswith("@api")` | cinto e suspensório | Regra do dono: nunca API paga. Custa uma linha e é a última barreira |
| `cerebro_compartilhado.enviar_pendentes` — ramo `duplicada` | `if` para um status | O serviço funde por semelhança > 0,96 e devolve o id de OUTRO fato; herdar o id corromperia a próxima correção |
| `cerebro_ponte.sincronizar(max_novos=…)` | parâmetro que o despachante não usa | É o freio da carga inicial (leitura do processo é o custo: 50 min em 18/11) |
| `propagacao._descoberta_da_fonte` — `de == "memoria" / "commit"` | despacho por valor | Dois produtores com extração diferente; um terceiro justificaria tabela, dois não |
| `cerebro_busca._perna_entidade` — `OperationalError: pass` | exceção engolida | Banco sem `ponte_entidade` = ponte nunca rodou; a perna vazia é a resposta certa e a frase exata no FTS cobre |

---

## 3. ANOTADO — não mexido aqui

| # | Problema | Onde | Por que não agora |
|---|---|---|---|
| A1 | Constantes `RAIZ`/`DATA`/`VAULT` redefinidas por módulo (4 cópias de cada) | `cerebro_compartilhado:45`, `cerebro_ponte:45–47`, `vault_retratos:53–55`, `propagacao:56–57`, `cerebro_busca:47`, `cores_orgaos:30` | Os testes trocam cada cópia por `monkeypatch` (`ponte.DATA`, `P.DATA`, `B.VAULT`); unificar exige reescrever teste (Testes = NÃO) |
| A2 | 6 leitores de frontmatter no escopo (10 no repo), com contratos diferentes (lista × escalar; YAML × regex) | `cerebro_fts:81`, `casos_vault:30`, `requerimentos_vault:29`, `vault_retratos:799`, `propagacao:356`, `deploy/vm2/brain/indexer.py:23` | `cerebro_fts` vai como está para a VM-2 (md5); `casos_vault` devolve escalar e `requerimentos_vault` lista — unificar muda o que a aba Casos lê. Precisa de rodada própria com as notas reais |
| A3 | Grau e situação do caso classificados de 3 maneiras sobre as mesmas notas | `casos_vault:24,44,54` × `vault_retratos:804,815,870,953` | A aba Casos e o Bases do Obsidian podem divergir; `vault_retratos` tem dono em outra frente |
| A4 | Privados de `casos_vault` importados por fora | `requerimentos_vault:98`, `governo_couto.py:425` | `governo_couto` é de outra frente |
| A5 | 5 regex de CNPJ com 3 critérios (só `cerebro_fts` confere dígito verificador) | `cerebro_fts:29`, `cerebro_compartilhado:63`, `vault_retratos:147`, `casos_vault:26`, `orgao_fonte` | Restam 4 depois de 1.1; trocar o critério de `recusar` muda o que sai da máquina — medir antes |
| A6 | Busca fundida implementada duas vezes (VM-1 e VM-2) com as constantes copiadas (`RESGATE=2`, profundidade 40, 60) | `cerebro_busca:181–223` × `deploy/vm2/brain/brain_core.py:118–157` | Mexe no serviço da VM-2 (deploy é ato do dono). Alvo: a VM-1 só chamar `/api/search` quando a Fase 3 fechar |
| A7 | Prefixos de chave são contrato implícito entre 9 produtores e a lista `_SERIE` da VM-2 (que não tem `fato`, `memoria`, `alerta-humano`) | `brain_core.py:267` | Idem A6 |
| A8 | Pastas ignoradas pelo índice divergem (VM-1 pula `.claude`; VM-2 não) | `cerebro_busca:56` × `indexer.py:20` | Idem A6 |
| A9 | `KINDS` copiado nas duas VMs | `cerebro_compartilhado:49` × `brain_core.py:179` | Idem A6 |
| A10 | `ug_cores.json` implantado sem gerador no repositório | `deploy/vm2/brain/ug_cores.json` | Precisa de `cores_orgaos` exportar; outra frente |
| A11 | Dois escritores no mesmo bloco gerado do frontmatter dos casos | `cores_orgaos:35,194` × `vault_retratos:797,909` | Fora do escopo |
| A12 | `cerebro_ponte entidade` (CLI) sem chamador em código; `brain_entity` cobre, menos o PAPEL (credor/licitante) | `cerebro_ponte:267` | Só o `ponte_entidade` guarda o papel; aposentar quando o papel for para a aresta da VM-2 |
| A13 | `memoria.py` é raso, com nome enganoso (não é o segundo cérebro), parâmetro `limite` morto e texto citando Massare | `memoria.py:11,18` · `rotas/sistema.py:448` | Alimenta `/api/memoria`, lida pelo painel (frente do painel) |
| A14 | Reexportações só para teste (`termos`, `entidades`) e teste amarrado a privado (`_perna_khoj`, `_perna_local`, `_soma_dif`, `_MARCA`) | `cerebro_busca:65–66`, `tools/cerebro_bateria.py:79–80`, `tests/test_vault_retratos.py` | Testes = NÃO |
| A15 | A regra "WhatsApp não entra em nenhuma camada" só existe num produtor | `cerebro_ponte.py:167` | **Decisão do dono**: pôr a palavra no portão comum barraria as 3 memórias de REGRA sobre WhatsApp que já estão no cérebro (#222, #223, #261). Ver relatório |
| A16 | Sentinelas de injeção (`ob_siafe="padrao"`, `buscar="cerebro"`) | `cerebro_ponte:287`, `certeza/orquestrador:94` | Os testes dependem da assinatura |
| A17 | `JFN_CERTEZA_CEREBRO` nunca ligado: `_publicar_cerebro` e `TETO_CEREBRO_CICLO` não têm efeito | `certeza/orquestrador.py:73` | **Decisão do dono** (ligar = o valor vigente passa a existir no cérebro para quem lê pelo MCP) |

---

## 4. Estado ao fechar

| Critério da skill | Estado |
|---|---|
| Mudança típica cai num lugar só | Esquema do registro: 1 lugar (`preparar`). Regra de menção: 1 (`mencoes`). Regra de "ignorar": 1 (`_ignorado`). Caminho do banco: 1 (`banco`) no escopo do cérebro; `propagacao` ainda tem a sua cópia (A1) |
| Nenhum import de algo mais volátil | Sem ciclo; `certeza` importa o cliente no topo; a busca importa cliente + certeza; o cliente não importa ninguém do projeto |
| Casos especiais restantes | 8 mantidos com motivo (§2) |
| Comportamento | 202 testes das áreas tocadas passam (cérebro, certeza, propagação, vault, memória), rodados em 2 lotes em 20/11/2026; mudanças de comportamento são as dos commits `fix`/`feat` |
