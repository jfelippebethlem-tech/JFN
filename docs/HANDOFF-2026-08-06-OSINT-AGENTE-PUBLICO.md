# HANDOFF — 2026-08-06 · OSINT ligado, cadeia societária consertada, fila de agente público

> Sessão de nove commits. O fio condutor não foi construir detector novo: foi descobrir que os
> maiores ativos da casa estavam **ligados ao contrário, quebrados no meio ou parados no disco** —
> e que três deles eram invisíveis porque nada os exercitava com dado real.

---

## 1. Quadro geral

| # | Commit | O que estava errado | Efeito medido |
|---|---|---|---|
| 1 | `95900891` | 6,17 mi de telefones/e-mails indexados, **zero consumidores** | 221 arestas limpas; cartão no painel |
| 2 | `b57daa2a` | Cadeia societária **partia no degrau** que existe para subir | Cadeias 2+ saltos **0 → 14**; beneficiários **20 → 66** |
| 3 | `2bf5baaa` | Reverso de sócios **semeado ao contrário** (empresa→pessoa) | 1.707 → **72.456 pessoas**, 686.964 vínculos |
| 4 | `d46cce95` | Base tinha 6,17 mi de estabelecimentos e **razão social de nenhum** | **5.859.921 empresas**; 3ºsetor 3.861 → **158.728** |
| 5 | `18aded5b` | Fila via **uma torneira** (SIAFE) — o caso motivador não passa por ela | 296 → **538 pares**, 18 → **68 comissionados** |
| 6 | `1d58eacb` | Fila só em linha de comando | Rota + painel; **22,3 s → 0,30 s** |
| 7 | `4ce565c0` | Faltava o eixo que separa o comum do grave | **7 pares** com conflito de órgão (art. 9º, III) |
| 8 | `e3845fbf` | "10 servidores no QSA" media **tamanho da empresa** | Eixo medido e **removido** da ordem |
| 9 | `e6ce6851` | Slot de processos-pai morria de SIGKILL **em todas as rodadas** | Orçamento de 700 s; três mensagens deixam de culpar o WAF |

Suíte em 4 lotes, verde em cada commit. Nenhuma catraca afrouxada; duas apertadas.

---

## 2. Os defeitos que só o dado real (ou a tela) mostrou

### 2.1 A chave partiu o nó — família 25 do catálogo

`montar_grafo_societario` põe o alvo de cada nível como `no_pj(raiz)` — **8 dígitos** — e trazia o
sócio PJ com os **14** do CNPJ íntegro. A mesma empresa virava **dois nós**: um recebendo a aresta
`socio_de` do nível de cima, outro emitindo a do nível de baixo. Como `beneficiario_final` sobe
seguindo as arestas em que o nó é DESTINO, ela parava **sempre no primeiro salto**.

Medido nos 400 maiores credores do SIAFE: dos 17 com cadeia de duas ou mais empresas, **17** tinham
o nó partido. **Nenhum teste pegava** — os cinco testes de `beneficiario_final` montavam o grafo à
mão, com as chaves já coerentes. O defeito morava no **construtor**, não no motor.

> **A pergunta que desarma:** *duas partes deste grafo chamam a mesma coisa pelo mesmo nome?*

O irmão apareceu no mesmo dia ao persistir o grafo: arestas de contato com 14 dígitos, societárias
com 8 — **zero** empresas com as duas naturezas de aresta. Corrigido: **103**.

### 2.2 A tela achou o que o teste não achava

Renderizado o cartão da fila, o **primeiro item** era `EMPRESA PÚBLICA DE SAÚDE DO RIO DE JANEIRO
S/A — RIOSAÚDE` com dois Capitães BM no "quadro societário". Ente público **não tem sócio** — tem
dirigente nomeado. Veto por natureza jurídica (`1xxx`, `2011`, `2038`), e **para aí**: `2054` é S/A
fechada e pegaria CONDOR e CABERJ, que são privadas.

E a **ordem** também estava errada: ordenar por valor punha a RIOSAÚDE no topo, à frente de todo par
que precisa de diligência. Fila de trabalho ordena pelo que precisa de trabalho.

### 2.3 O eixo que eu mesmo promovi, e depois removi

"10 servidores no QSA da MEDVIVA" parecia o sinal mais forte. Com o denominador: a MEDVIVA tem
**125 sócios** (8%); a B&B MED tem **203** (3%). A contagem ordenava por **tamanho da empresa**.
A fração também não salva — exigindo ≥5 sócios e maioria de servidores sobram 5 entidades, **4 já
explicadas**. Saiu da ordenação, ficou na tela com denominador. Catraca lê o próprio `sorted()`.

### 2.4 O slot que morria calado e culpava a fonte

`sei_pais rc=137` nas **dez** últimas rodadas, sem uma linha `[pais] FIM`. `_PARAR` só é consultado
entre processos e uma leitura de pai tem p90 de 137 s (máx. 502 s) — o SIGKILL sempre vencia,
o browser nunca fechava, a sessão itkava ficava pendurada e os **dois slots seguintes** falhavam no
login dizendo *"não venceu o WAF"*. Conferido na fonte: às 16:03:26 o login funcionou e leu 67
documentos. **O acesso estava bom o tempo todo.**

---

## 3. O que existe agora (e como se aciona)

| Ferramenta | O que faz | Rotina |
|---|---|---|
| `tools/grafo_persistir` | grafo dos credores do SIAFE em `pessoas`/`relacionamentos` | `sweep_dados.sh`, fatias de 300 |
| `tools/empresas_rj_build` | razão social + natureza de 5,86 mi de raízes | `socios_dump_refresh.sh` passo 5.1 |
| `tools/agente_publico_reverso` | fila agente público × entidade paga | `sweep_dados.sh` |
| `/api/osint/contato_compartilhado` | telefone/e-mail compartilhado por CNPJ | painel, aba Vínculos |
| `/api/osint/agente_publico` | a fila de 538, lida do JSON | painel, aba Vínculos |

**Estado da fila (2026-08-06):** 538 pares · 68 comissionados · 201 em terceiro setor · 125 com
explicação institucional declarada · **7 com conflito de órgão**.

---

## 4. Os sete pares com conflito de órgão

A unidade que **pagou** é a unidade onde o agente **serve** — art. 9º, III da Lei 8.429/1992 e o
dever de impedimento do art. 20 da Lei 9.784/1999.

| Agente | Cargo | Órgão | Entidade paga pelo próprio órgão |
|---|---|---|---|
| MARIA ISABEL ALVES PEIXOTO | Especialista em Educação | Fundação p/ Infância e Adolescência | LAR MARIA DE LOURDES |
| PAULO DO COUTO PFEIL JUNIOR | Engenheiro | Fundação DER | MULTICON CONSTRUÇÕES |
| MAX WALTER PEIXOTO ZULCHNER | Engenheiro | Fundação DER | ENEX CONSTRUÇÕES |
| CLAUBER DA SILVA NOGUEIRA | Major PM | SEPM | CASA DE SAÚDE STA. MÔNICA |
| LUCIANO DA SILVA BOTELHO | 3º Sargento PM | SEPM | PIT STOP MOTO SERVICE |
| MARCO AURELIO DAMATO PORTO | Arquiteto | Fundação DER | CEDAE *(estatal — explicado)* |
| *(+1 em entidade com explicação)* | | | |

> **Indício, nunca prova.** O casamento é por **nome normalizado**: a folha não traz CPF utilizável
> e a Receita entrega o CPF do sócio mascarado. Nomes com mais de um CPF no índice já saíram, mas os
> que ficam podem ser homônimos sem que a base o mostre. Servidor **pode** ser sócio. A diligência
> que fecha está em cada item: ficha funcional com CPF, QSA integral na JUCERJA, e se a sociedade
> antecede ou sucede a posse.

---

## 5. O caso usado como controle positivo

A casa foi testada contra uma matéria publicada (6Max Sports e Gestão Esportiva). **Antes** do
commit 4 ela não achava a empresa — e a resposta honesta não era "não encontrei", era *"não tenho
como procurar"*. **Depois**, buscando pelo nome: `55801870000151 · capital R$ 500.000,00 · aberta em
04/07/2024 · Rio de Janeiro · ATIVA`, com os cinco sócios-administradores no QSA nacional.

O reverso dos cinco trouxe o que a matéria não tinha: **WAGNER COELHO DE ASEVEDO**, um dos sócios, é
`ASSISTENTE II` na **Câmara Municipal do Rio**, vínculo *Requisitados com Cargo*, sem homônimo no
índice. **Ressalva que não pode cair:** o registro de folha é de **competência 2021** e a sociedade
é de 07/2024 — a sobreposição temporal está **por verificar**.

---

## 6. Limites de fonte declarados

- **`socios_full.csv.zst` não traz `data_entrada`.** Só 5 colunas. "Era sócio na data da posse?" é
  **INDISPONÍVEL** por esta via — cabe JUCERJA.
- **`pcrj_despesa` cobre 2019–2023** e o campo `pago` é declaração do portal municipal, **não uma
  OB**. Conferido: diverge de `empenhado` em 8.404 das 78.595 linhas e, onde diverge, acompanha o
  liquidado — é pagamento, não cópia do empenho.
- **Emenda federal não passa pelo SIAFE estadual.** A SOLAZER recebeu R$ 0 no SIAFE: **não
  observado**, nunca "não recebeu".
- **Parentesco não é estabelecido.** Sobrenome compartilhado não é sinal (16,9%). O eixo com
  prevalência medida vive em `osint/parentesco` e só corrobora.

---

## 7. Aberto

1. **Automação do OSINT** — pedido do dono nesta sessão: ainda depende de sweep diário e de leitura
   manual da fila; falta gatilho por evento (OB nova, contrato novo) e alerta.
2. **Ingerir `data_entrada`** regerando o `.zst` com a coluna 6 — destrava o eixo temporal.
3. **Bloco C do plano** — mover sweeps de OSINT com browser para a VM-2.
4. **Órfãos restantes** — `osint/timeline`, `osint/qsa_certame`, `enrich/exif`: ligar ou apagar.
5. **`MEMORY.md` em 23,1 KB** (limite 24,4) — compactar exige apagar memórias: decisão do dono.

---

# PARTE II — O painel: da métrica muda à métrica que leva ao dado

> Sete commits depois da Parte I. O pedido do dono foi direto: *"tá tudo sambando, solto quando
> puxa"* — e a medição deu razão a ele de forma exata.

## 8. O estado inicial, medido

O painel tem **198 chamadas de `kpi()`**. O helper sempre teve um 5º parâmetro para o destino, e
**nenhuma das 198 o passava**. Quem lia "68 comissionados" não tinha como ver os 68.

## 9. As três vezes em que a métrica mentiu — família 26 do catálogo

| Métrica | KPI dizia | O clique mostrava | Por quê |
|---|---:|---:|---|
| Agentes comissionados | 68 | **55** | número da fila inteira, filtro sobre a página |
| Em terceiro setor | 201 | **22** | idem |
| Sem cadastro ainda | 647 | **0** | total do servidor, página com 60 |

**Nenhum teste unitário pega isso**: o JS está certo, a rota está certa, e o erro nasce da
combinação. As duas primeiras foram corrigidas movendo a fatia para o servidor. A terceira **não
tem conserto sem trabalho de rota** — e a decisão foi **tirar o clique**, com o motivo escrito no
código. *KPI sem clique é honesto; gaveta que mostra 0 para 647 é mentira.*

## 10. O verificador que clica

`tools/painel_drill_check` abre o painel de verdade, navega por **13 abas**, clica em cada
`[data-drill]`, lê o KPI e conta as linhas da gaveta. Divergência é falha; `pageerror` também.
Hoje: **22 métricas clicadas, zero divergências**. Está no sweep diário.

Ele já se corrigiu uma vez: acusou 336 contra 341 e a divergência **não se reproduziu** — o
contador leu durante a montagem. Agora só conta depois de o número parar de mudar, e relê antes de
acusar. *Verificador que dá falso alarme é verificador que ninguém lê.*

## 11. Nove conversões nasceram mortas — família 27

Inserir `registrarDrill(...)` na linha anterior ao KPI fez a chamada cair **dentro de uma template
string**: virou texto na página. O KPI ganhou o atributo, o build passou, o clique não fazia nada.
Quem acusou foi o verificador: *KPI 9, gaveta None*. Catraca nova conta crases.

**Build verde não prova que executou** — é a prima do "construído, testado, nunca rodado", agora na
camada da tela.

## 12. A catraca mediu errado a própria dívida — três vezes

1. contava como mudo o KPI que **já navegava** (`kpi-go` nasce em runtime, não aparece na chamada);
2. contava como convertível o que exibia um **máximo** (`a.length ? fmtN(a[0].hhi) : '—'`);
3. não via **contagem guardada em variável** (`const alta = g.filter(...).length`).

Uma catraca que mede errado protege o que não existe.

## 13. Onde parou

| | |
|---|---:|
| KPIs no painel | 198 |
| **Convertíveis sem caminho** | **0** |
| Com caminho | 46 |
| Sem gaveta **por serem escalares** | 152 |

Os 152 leem mediana, F1 macro, percentual, "SIAFE ok/off" — número que não conta linhas **não tem
gaveta possível**, e um teste de controle impede que sejam cobrados como dívida.

**Quatro métricas ficaram deliberadamente sem caminho**, cada uma com o motivo no código: "sem
cadastro (647)", "CNPJs envolvidos", "certames analisados" e "cidades de candidatura".

## 14. Aberto no painel

1. Os **74 totais do servidor** que têm linhas do outro lado da rota — cada um exige `?filtro=` como
   o de agente público. É trabalho de rota, um endpoint por vez.
2. Cobertura do verificador: 13 das ~40 abas. As demais só entram quando tiverem métrica clicável.
3. Métricas escalares (mediana, F1) pedem outra afordância — **procedência**, não gaveta: de onde
   veio o número e como se recalcula.
