# HANDOFF — Painel JFN v61 «TRON CLARO»

| | |
|---|---|
| **Data** | 2026-11-11 |
| **Briefs executados** | `BRIEF-painel-v61-tron-claro-2026-11-11.md` (fases 1 a 11) e `BRIEF-painel-v61-fase7b-cobertura.md` |
| **Branch** | `ui/painel-v61-tron-claro` (a partir de `ui/painel-v60-clareza` @ `9c5f44b2`) — sem merge em `main`, sem force-push |
| **Estado** | 🟡 **pronto, NÃO ligado por padrão** (`JFN_V61_DEFAULT='0'`) — ver §1.1 · ver com `/painel?v61=1` |
| **Serviço `jfn`** | **não foi reiniciado.** Sete rotas novas e o login claro só existem depois do restart (§3) |
| **Onde mora** | CSS: `static/css/src/99z2-v61-*.css` (9 estratos) · JS: `static/js/src/{ui/v61.js, ui/movimento.js, ui/aovivo.js, aovivo/, cena/abertura.js, cena/reator.js, mapa/territorio.js}` · dados: `compliance_agent/territorio/` · ao vivo: `compliance_agent/aovivo/` |

> **Em uma frase:** o painel ganhou um tema claro azul sobre a estrutura da v60, uma abertura em filme com
> o estado real dos motores, um mapa do RJ clicável (contratos do Estado por município e da Prefeitura do
> Rio por AP), um reator e um ticker que respondem ao que a máquina está fazendo — e um motor de dados
> novo que diz, com método e confiança, **onde** cada contrato é executado, ou admite que não sabe.

---

## 1. Como ligar, desligar e desfazer

| Quero… | Faço |
|---|---|
| Ver a v61 neste aparelho | abrir `/painel?v61=1` (grava `jfn_v61=1`) |
| Voltar à v60 escura neste aparelho | `/painel?v61=0` — ou "Tema escuro" na folha "⋯" / no botão de lua do cabeçalho (grava `jfn_tema=escuro`) |
| Pular a abertura neste aparelho | `localStorage.jfn_portal_off = '1'` (o mesmo escape do portal antigo) |
| Ligar/desligar para **todos** | `static/jfn-painel.html`: `window.JFN_V61_DEFAULT='1'` ↔ `'0'`; e `static/login/v61.js`: `PADRAO` (os dois têm de andar juntos) |
| Remover a v61 inteira | `git revert` dos commits da §2, do mais novo ao mais antigo |

### 1.1 Por que não foi ligada por padrão

O brief mandava ligar "se tudo passar". Não passou tudo: (i) as 7 rotas novas esperam o restart do `jfn` —
ligada agora, a v61 mostraria mapa, reator e Motores como INDISPONÍVEL para todos; (ii) Lighthouse celular
deu desempenho 27 (meta 70; a v60 deu 29 na mesma VM sem GPU) e acessibilidade 95 (meta 90); (iii) a troca de
aba ainda tem tarefas longas acima de 200 ms na VM (9; a v60 tem 10); (iv) a cobertura do território ficou em
15,3% (Estado) e 42,5% (Prefeitura) do valor, abaixo da meta de 50%. Números, tabelas e a auditoria de 60
atribuições: `_SANDBOX/v61_RELATORIO.md`. Depois do restart e de um olhar em celular real, ligar é trocar as
duas linhas da tabela acima.

A classe `html.v61` só existe junto com `html.v60` (o script do `<head>` garante). Sem ela nenhum seletor
dos estratos `99z2-v61-*` se aplica e todo JS novo sai no primeiro `if(!_v61)`.

**Build (igual ao da v60):**

```bash
cd ~/JFN
PYTHONPATH=. .venv/bin/python -m tools.painel_css_cortar --juntar   # mexeu em static/css/src
nice -n 10 npm run build:painel                                     # mexeu em static/js/src
PYTHONPATH=. .venv/bin/python tools/painel_bump_versao.py           # ?v= novo
bash tools/precommit_painel.sh                                      # gate; tem de sair 0
```

---

## 2. O que entrou, por fase

| Fase | Commit | O que muda |
|---|---|---|
| 1 | `fe369e19` | Flag `html.v61`; tema «Gelo» (tokens do brief + pares `-text` por contraste); vidro branco com colchetes; chip ativo cheio; grade Tron em perspectiva + 3 rastros; "Tema escuro" |
| 2 | `11bf5b97` | Geist + Geist Mono + Oxanium (5 woff2 locais, OFL); preload só de Geist 400/600 e só com a v61 valendo |
| 3 | `74b3d8df` | 36 vídeos + 12 pôsteres conferidos (`tools/v61_midia.sh`); o fundo da esfera toca a peça clara; corrigida corrida antiga da sonda de vídeo |
| 4 | `db5a0bd0` | Abertura nova (`cena/abertura.js`): filme, marca JFN, checklist REAL dos motores, Pular; login claro (`static/login/v61.{js,css}`) |
| 5 | `f51dfcbd` | Cockpit v61: mapa à esquerda, reator vivo + herói à direita; `ritmo.js: quadroLigar` (um laço rAF); `aovivo/estado.js` |
| 6 | `7d080aaf` | Mapa interativo: geometria oficial (IBGE, Data.Rio), coroplético, tooltip, ficha, zoom para o Rio/APs, pulsos, radar |
| 7 | `ea733bb3` `693f1daf` | Motor `territorio` (5 rotas, CLI, timer de 6 h, 65 testes); correção da rescisão |
| 8 | `87efb15c` `60f4d6b0` | AO VIVO: catálogo de 28 motores, coletor só-leitura, saneamento, SSE; ticker, grade de Motores, histórico |
| 9 | `5a25bcf7` | Movimento: tokens, View Transition no miolo, contagem, flip + lâmina, cascata; a v61 passa a obedecer ao modo sóbrio |
| 10 | `033e0e92` | Capas com o pôster da esfera; glifos próprios para 5 abas e os botões do cabeçalho (fecha pendência da v60) |
| 7b | `ff9b7554` | Cobertura: TCE-RJ/SIGA como 2ª fonte, CNES, ISP-RJ, distritos do IBGE, baldes "Estado inteiro / sede" e "Cidade inteira / sede" (84 testes) |
| 11 | (este) | Verificação, relatório, este handoff, bloco v61 no `DESIGN.md` |

---

## 3. ⚠️ O que SÓ funciona depois de reiniciar o `jfn`

O serviço não foi reiniciado (regra do brief). `static/` é servido do disco, então tema, fontes, abertura,
mapa (geometria) e ticker já estão no ar para quem ligar a flag. **O que depende de código Python novo não
está:**

| Rota / peça | Arquivo | Sem o restart a tela mostra |
|---|---|---|
| `GET /api/territorio/estado` | `compliance_agent/territorio/api.py` | mapa só com as divisas + "dados do território: INDISPONÍVEL" |
| `GET /api/territorio/estado/{cod_ibge}` | idem | ficha do município: INDISPONÍVEL |
| `GET /api/territorio/pcrj` | idem | mapa das APs sem dado |
| `GET /api/territorio/pcrj/{ap}` | idem | ficha da AP: INDISPONÍVEL |
| `GET /api/territorio/baldes` | idem | — (rota de consulta) |
| `GET /api/ao-vivo/estado` | `compliance_agent/aovivo/api.py` | reator cinza e parado, "ao vivo: INDISPONÍVEL"; abertura diz "motores: INDISPONÍVEL"; grade de Motores idem |
| `GET /api/ao-vivo/stream` (SSE) | idem | ticker "ao vivo pausado · reconectando" |
| Login claro | `server.py` (`_LOGIN_HTML` cita `/static/login/v61.js`) | login continua o escuro |

Registro dos dois routers: `server.py`, logo depois do laço `app.include_router` das `rotas/`. O inventário
de rotas (`tests/golden/server_rotas.txt`) já foi regravado com as sete. **Tudo foi exercitado com
`TestClient` e, nos prints, respondido pelos routers reais** (interceptação de rota no harness) — não pelo
serviço vivo. Depois do restart, conferir no navegador: `/api/ao-vivo/estado` e `/api/territorio/estado`.

Nada mais em `server.py` mudou.

---

## 4. Motor `territorio` — como ler

`python -m compliance_agent.territorio.cli --full | --incremental` · timer `jfn-territorio.timer` (01:20,
07:20, 13:20, 19:20; `Nice=10`, IO ocioso; a CLI segura `flock data/territorio.lock`). Só lê `compliance.db`
e `pcrj.db` (`mode=ro`); só escreve em `data/territorio.db`.

| Método | O que é | Confiança |
|---|---|---|
| `campo` | unidade compradora de sítio único (HUPE → Rio; UENF → Campos). Sede de órgão **não** é local de execução | alta / média |
| `orçamento` | regionalização do empenho no SIAFE — **INDISPONÍVEL**: as tabelas SIAFE coletadas não trazem localizador | — |
| `unidade` | o objeto cita unidade de endereço conhecido: CNES (hospitais, UPAs), ISP-RJ (DP, BPM de município único), TSE (escolas) | alta / média (sigla) |
| `endereço` | CEP no objeto — só a faixa da capital | alta |
| `texto` | dicionário dos 92 municípios + distritos do IBGE, com as armadilhas tratadas | média |
| `órgão` (PCRJ) | UG regional (CRE, "… DA AP 3.2", hospitais) ou regional citada no objeto ("AP 5.3", "XVIII R.A.") | alta / média |

Baldes (sempre visíveis no rodapé do mapa): **sem território** (não se sabe) · **vários** (valor NÃO
repartido) · **Estado inteiro / sede** e **Cidade inteira / sede** (regra explícita, motivo gravado em
`evidencia`) · **só região**. `pago` do Estado = OBs do SIAFE contabilizadas, do mesmo processo SEI, ao mesmo
CNPJ; sem vínculo = `NULL` (a tela diz INDISPONÍVEL). `pago` da PCRJ = total declarado no Contas Rio.

Cadastros versionados em `compliance_agent/territorio/dados/` (cada linha com a fonte); regerar com
`tools/v61_territorio_fontes.py` (IBGE, ISP-RJ, CNES) e `tools/v61_geo.sh` (malhas).

---

## 5. Decisões tomadas sem perguntar

| # | Decisão | Por quê |
|---|---|---|
| 1 | Tokens do brief valem para preenchimento; texto usa pares `-text` (`--ion-text`, `--ok-text`, `--warn-text`, `--crit-text`, `--money-text`) e `--muted` no lugar de `--ink-3` | o brief pede AA em todos os pares e `--ink-3`, `--ion`, `--ok`, `--warn`, `--money` não dão 4,5:1 como texto (medido em `tools/v61_contraste.py`) |
| 2 | Controle ativo = `--ion-solid #1470E6`, não `--ion #1E7BF0` | branco sobre `--ion` dá 4,08:1 |
| 3 | A grade desliza por `transform` (uma célula por ciclo), não por `background-position` | mesmo efeito, sem repintar a camada de tela cheia a cada quadro |
| 4 | Sem desfoque no celular e no modo sóbrio; barras de borda a borda por `padding`, não por sombra de 100vmax | medido: 97 tarefas longas em repouso antes; 12 depois |
| 5 | A grade de Motores é uma seção do Início com chip de atalho, não uma aba nova | aba nova mexe no registro de abas e em 4 testes de estrutura; a seção entrega o mesmo |
| 6 | Contrato de linha da ficha abre o dossiê do **fornecedor** | não existe dossiê de contrato na casa |
| 7 | `n_alertas` do território = INDISPONÍVEL | só 275 dos 62 mil alertas têm empresa vinculada; contar por território seria inventar |
| 8 | TCE-RJ/SIGA entra com deduplicação conservadora (mesmo CNPJ, valor ±10% = mesmo contrato; mesmo processo + mesmo valor = credenciamento repetido) | melhor contar de menos do que em dobro |
| 9 | DOERJ só soma texto ao contrato do mesmo processo; não cria contrato | só 185 dos 2.634 atos têm processo extraído; criar contrato de extrato livre duplicaria |
| 10 | INEP (Censo Escolar) não foi baixado | `download.inep.gov.br` apresenta cadeia TLS que não valida; baixar sem verificar certificado não é aceitável |
| 11 | Massare aparece como INDISPONÍVEL | ele saiu desta VM em 07/2026; só vira "vivo" se `JFN_MASSARE_STATUS_URL` for configurada |
| 12 | Cascata só nas 16 primeiras linhas das listas | animar milhares de linhas era parte do engasgo |

---

## 6. Avisos do GitNexus e dos portões

- `impact`/`detect-changes` rodados antes de cada commit: risco **low** nas fases 1–4, 7, 9; **medium** nas
  5 e 8 (caminho do boot e do cockpit). A mitigação é a mesma da v60: toda mudança em função antiga é um
  desvio sob `_v61`; sem a classe, o caminho antigo é o de sempre.
- Portões que barraram e foram **corrigidos na origem** (nunca contornados com `--no-verify`):
  `painel_modulo_livre` (um `esc` local em vez do da casa), `ruff` no pre-commit, a catraca de
  `except Exception` (+1, na sonda do Massare — passou a capturar exceção específica).
- `tests/test_server_snapshot.py` acusou as 7 rotas novas: golden regravado pelo caminho documentado
  (`--update-rotas`), diff conferido — só as 7.

---

## 7. Ferramentas (versionadas em `tools/`, descartáveis em `_SANDBOX/`)

| Script | Para quê |
|---|---|
| `tools/v61_contraste.py [--md]` | AA de todos os pares tinta/fundo do tema, lendo os tokens do próprio CSS |
| `tools/v61_midia.sh [conferir\|codificar]` | ffprobe, alvo de tamanho, áudio, PSNR da emenda dos loops |
| `tools/v61_geo.sh` | refaz as malhas (IBGE + Data.Rio) |
| `tools/v61_territorio_fontes.py` | refaz os cadastros (IBGE distritos, ISP-RJ, CNES) |
| `_SANDBOX/v61_rotas.py` | responde `/api/territorio` e `/api/ao-vivo` no harness pelos routers reais (o serviço não foi reiniciado) |
| `_SANDBOX/shot_painel.py` (`V61=1 V61_API=1`), `v61_probe.py`, `v61_finais.py`, `v61_abertura_shot.py`, `v61_login_shot.py` | prints |
| `_SANDBOX/v61_auditoria.py` + `v61_resumo.py`, `v61_perf.py` | checklist das 68 abas e medição de tarefas longas |
