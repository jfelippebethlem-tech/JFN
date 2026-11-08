# PLAYBOOK — navegar o SIAFE (1 e 2) sem se perder

> Para QUALQUER IA que for tocar coleta do SIAFE — inclusive as mais fracas. Leia isto ANTES de
> abrir o código. Tudo aqui foi **medido com print de tela em 2026-08-09**, não é suposição.
> Regra-mãe da casa: **o acesso está liberado; quando falha, a culpa é do método** — nunca do WAF,
> nunca do IP. Ver `~/vault/aprendizados/` e a memória `sei-siafe-nunca-culpar-acesso-nem-waf`.

---

## 1. São DOIS sistemas. Escolher o errado dá zero linhas.

| | SIAFE 1 | SIAFE 2 |
|---|---|---|
| URL de login | `https://www5.fazenda.rj.gov.br/SiafeRio/faces/login.jsp` | `https://siafe2.fazenda.rj.gov.br/Siafe/faces/login.jsp` |
| Anos que ele tem | **2016 a 2023** | **2024 a 2026** |
| Colunas da grade de OB | **19** | 23 |
| Como apontar | `JFN_SIAFE_LOGIN_URL=<url do 1>` | é o padrão (não precisa de env) |

- **2023 é SEMPRE no SIAFE 1.** Pedir 2023 no SIAFE 2 devolve
  `"erro": "exercicio_bloqueado"` — e isso **não** é falta de permissão da conta: é o ano não
  existir naquele sistema.
- **2024 no SIAFE 1 devolve 0 linhas** e parece bug. Não é. É o mesmo erro ao contrário.
- Mesmo usuário e senha nos dois (`SIAFE_USER` / `SIAFE_PASS` no `.env`).

## 2. O caminho de menu, clique a clique

`Execução` → `Execução Financeira` → `OB Orçamentária`

**A armadilha que custou horas:** o segundo passo já foi escrito preferindo o id
`pt1:pt_np3:1:pt_cni4::disclosureAnchor`. Esse id é a **POSIÇÃO** do item no menu — e a posição
muda entre os dois sistemas. No SIAFE 1, `Execução` é o índice **3**
(`pt1:pt_np3:3:pt_cni4::disclosureAnchor`), então clicar no índice 1 abre **outro item**, a sessão
sai do sistema e cai numa página da SEFAZ que fala em bloqueio de IP.

> ⚠️ **Essa página engana.** Ela diz que o IP está em lista de bloqueio, e a leitura preguiçosa é
> "o WAF me barrou". É FALSO, e dá para provar em dois comandos:
> ```bash
> curl -s -o /tmp/w5.html -w "%{http_code} %{size_download}\n" \
>   https://www5.fazenda.rj.gov.br/SiafeRio/faces/login.jsp     # 200 e ~26 KB = página normal
> ```
> e o print pós-login mostra o SIAFE-Rio **aberto**, com o nome do usuário e "Exercício 2023".
> Quem chegou nessa página **navegou para fora** — o erro é do clique.

**Regra permanente: casar por RÓTULO, nunca por índice.** Índice de menu não é identidade; o texto
é. E normalize antes de comparar (minúsculas + com e sem acento): o mesmo item aparece como
`Execução Financeira` e `Execucao Financeira` conforme o sistema.

## 3. O painel de filtros (é onde a coleta fura o teto de 1.000)

A grade tem **teto de 1.000 registros por consulta**. Duas saídas, nesta ordem:

1. **Checkbox "Remover limite"** (`chkRemoveLimit`) — quando existe, é o caminho barato.
2. **Subdividir por prefixo do Número**: linha 0 do filtro = `UG Emitente começa com <ug>`;
   linha 1 = `Número começa com {ano}OB0…9`, subdividindo a fatia que ainda estourar.

Ids que importam (confirmados na tela):

```
pt1:tblOBOrcamentaria:sdtFilter::disAcr                                  ← abre o painel de filtros
pt1:tblOBOrcamentaria:table_rtfFilter:0:cbx_col_sel_rtfFilter::content  ← linha 0, campo
pt1:tblOBOrcamentaria:table_rtfFilter:0:cbx_op_sel_rtfFilter::content   ← linha 0, operador
pt1:tblOBOrcamentaria:table_rtfFilter:1:...                             ← linha 1 (NEM SEMPRE existe)
pt1:tblOBOrcamentaria:tabViewerDec::scroller                            ← o que rola para colher
```

**A segunda linha de filtro não nasce sozinha no SIAFE 1.** Quando ela falta, o código estoura em
`Locator.click: Timeout 30000ms ... table_rtfFilter:1`. Não insista com espera maior: ou o painel
oferece o controle de adicionar linha, ou o caminho é outro (remover limite / por data).

## 4. Colher: a tabela é VIRTUAL

Só ~50 linhas existem no DOM por vez. Rolar o corpo (`::db`) **não** basta — é o `::scroller`
(~40.000 px) que dispara o fetch do ADF. Já custou um diagnóstico inteiro de "bug de scroller"
que não existia.

**O platô é 989, não 1.000.** Em 5.893 fatias já coletadas, **nenhuma** chegou a 990 e 76 pararam
em 989 ou 984. Guard escrito em 990 nunca dispara — e fatia truncada entra no banco como se fosse
o universo. O limiar da casa é `_FATIA_CAPOU = 980`. Subdividir uma fatia legítima de 985 custa
uma consulta; aceitar uma truncada custa dado que ninguém sabe que falta.

## 5. Ingerir: o cabeçalho é da TELA, não da base

`ingerir(exercicio, header, linhas)` mapeia coluna→campo pelos **rótulos que a tela mostra**
(`_LABEL2COL` cobre os dois sistemas). Passar `_COLS_SIAFE` (os nomes internos da base) faz o mapa
não reconhecer nada, a ingestão cair no **posicional**, e no SIAFE 1 — que tem 4 colunas a menos —
tudo desloca: as linhas entram com `numero_ob` **vazio**, colapsam na mesma chave primária e sobra
**uma por fatia**. O log diz `100 OBs ✓` e o banco ganha 1. Sempre passe o header que `_colher`
devolve.

E a chave da tabela é `(numero_ob, ug_emitente, exercicio)`: o número da OB **se repete entre
unidades** (67% dos números aparecem em mais de uma UG; `2024OB00284` está em 72). Chave só no
número apaga a linha de outra unidade a cada coleta.

## 6. Sessão: uma por IP, e o login é lento

- O SIAFE aceita **uma sessão por IP**. Logar de duas máquinas derruba a que estava trabalhando —
  por isso existe lockfile (`data/sei_cache/siafe_lock.json`) e a trava de host.
- O login leva **minutos** e às vezes o ADF navega no meio de um `evaluate`, matando o contexto
  (`Execution context was destroyed`). Isso é transitório: **tente de novo**, não conclua bloqueio.
- Serializa com o sweep do SEI pelo `browser_lock` — dois Chromium nesta VM de 2 vCPU derrubam a
  máquina (já aconteceu 4×).

## 7. Receita de bolo (o que funciona hoje)

```bash
# UG única, ano do SIAFE 1 (2016-2023) — o modo que a casa provou
JFN_SIAFE_LOGIN_URL=https://www5.fazenda.rj.gov.br/SiafeRio/faces/login.jsp \
  .venv/bin/python -m compliance_agent.siafe_ob_orcamentaria \
    --exercicio 2023 --por-ug 180100 --ingerir            # sem subdividir: para no teto

# … e com subdivisão por prefixo (o que fura o teto)
JFN_SIAFE_LOGIN_URL=https://www5.fazenda.rj.gov.br/SiafeRio/faces/login.jsp \
  .venv/bin/python -m compliance_agent.siafe_ob_orcamentaria \
    --exercicio 2023 --por-ug 180100 --ug-grande --ingerir

# ano do SIAFE 2 (2024-2026): sem env nenhuma
.venv/bin/python -m compliance_agent.siafe_runner ug 294200 2025
```

**Como saber se funcionou** — nunca pelo "ok: true", sempre pelo EFEITO:

```sql
SELECT COUNT(*) FROM ob_orcamentaria_siafe WHERE ug_emitente='180100' AND exercicio=2023;
```

Se a contagem for **redonda** (1.000, 2.000, 5.000), a coleta parou no teto: é sintoma, não
resultado. E se as linhas tiverem numeração **contígua** (só `2023OB27…`, `2023OB28…`), você tem
uma única consulta capada, não o universo.

## 8. Depurar sem adivinhar

```bash
JFN_SIAFE_DEBUG=1 …   # grava /tmp/siafe_nav_*.png em cada passo da navegação
```
Olhe o print **antes** de formular hipótese. Foi um print que mostrou que a "página de bloqueio"
vinha de um clique errado, e outro que mostrou o SIAFE-Rio logado e saudável no passo anterior.

---

### Resumo para quem tem pouco contexto
1. Ano 2016–2023 → SIAFE 1 (www5). 2024+ → SIAFE 2. Errar isso dá zero e parece bloqueio.
2. Clique por **rótulo**, jamais por índice de menu.
3. Página de bloqueio da SEFAZ = você navegou para fora. Confira com `curl` antes de acusar o WAF.
4. Fatia com ≥980 linhas está **capada** — subdivida.
5. Ingira com o cabeçalho da **tela**; a chave inclui **UG e exercício**.
6. Confira pelo **banco**, não pelo `ok: true`. Contagem redonda = teto.
