# Decision log — untangle da área 15: `deploy/` e `tools/` de infraestrutura (20/11/2026)

Escopo: `deploy/` (systemd, vm2, itcampo, nominatim, hermes-config de referência), os `.sh` da raiz e de
`tools/` ligados a deploy/cron, e as famílias `tools/{painel_,v6*,gen_,hermes_,vm2_,enviar_,gerar_,backfill_,
memoria_indice}`. Fora: `tools/sei_*` e as famílias de investigação (outros agentes), `compliance_agent/territorio/`,
eleição. Escolhas do dono: **Comentários = sim** (fica medição datada, decisão do dono, norma), **Testes = não**.
Restrições: nada de crontab, `systemctl`, it-campo ou VM-2 além de rodar testes lá; sem push.

Formato igual a `pacotes-pequenos.md`: o fix fica acima dos problemas que resolve. `[feito]` = aplicado;
`[pendente]` = decisão do dono ou toca máquina/área alheia; `[anotado]` = fora do escopo.

## 0. Prova de equivalência

**Testes casados** (35 arquivos, rodados na VM-2 por `tools/testar_na_vm2.sh`: hermes, memoria_indice, painel_*,
v68/v69, vm2_conferencia, ocr_gpu, cron_*, catracas, import, ferramenta_tem_quem_a_rode, sei_integra_vm2,
pre_push_gate…): antes **240 passed, 4 skipped**; depois **240 passed, 4 skipped**. Na primeira rodada de depois
caiu `test_catraca_excepts::test_baseline_atualizada_quando_melhora` (a contagem caiu 26 com os scripts apagados
— a catraca pede para travar o ganho); travado em `072daade`.

**Validação empírica, só leitura:**

| Superfície | Como | Resultado |
|---|---|---|
| Units do repositório | `systemd-analyze verify` (sintaxe) + checagem de que todo script/`-m módulo` de `ExecStart*`/drop-in existe | 0 erro de sintaxe, 35 alvos existentes. Antes: `massare.daily`/`massare.market` não existiam |
| Espelho × instalado | `cmp` de cada unit com `~/.config/systemd/user/` (VM-1) e `ssh vm2 cat` (VM-2) | iguais, exceto `jfn.service` (§1.2) |
| `backfill_enderecos._gap` | versão antiga × nova no `compliance.db` real | 1.274 CNPJs, mesmo md5 |
| `gerar_requisicoes --resumo` | antiga × nova, `mode=ro` | byte a byte igual |
| `guardiao_db_malformed.sh` | banco falso corrompido + `notificar` falso | **muda (defeito, §4)**: antes a marca era gravada com o envio falhando; depois não |
| `painel_modulo_livre` | `ckCard` injetado sem import no `entrada.js` | **muda (defeito, §5)**: antes rc=0; depois rc=1 apontando o arquivo; sem injeção, 0 achados |
| `colher_vm2.sh` rc / `curl -m` / `while` do `testar_na_vm2` | reprodução mínima em bash/python | antes rc=0 · rota muda trava; depois rc real · `curl` sai com 28 no teto · laço sai 0 |
| `diag_telegram_poller` | processo falso com o mesmo padrão | morto por PID (137) |

## 1. `deploy/systemd/` vira o espelho do que está instalado  `[feito — 755c7970]`

- O instalado é a verdade e o repositório estava atrás dele — um `cp deploy/systemd/*` (como o README mandava)
  **desfazia correções de produção**:
  - `jfn-fisc-refresh.timer` às 05:40 — a hora que colidia com backfill/cerebro_sync/metacognição e derrubou o job
    em 2026-07-20 (instalado: 00:30; `TimeoutStartSec` 14400 × 28800);
  - `jfn-integra-fila.service` sem a fila por dinheiro (medição de 2026-07-24: R$ 2,11 bi pagos nunca tocados);
  - `jfn-tfe.service` com `--ano 2025/2026` fixos (instalado: `--latest`);
  - `chrome-jfn.service` com `google-chrome` e `--user-data-dir=/tmp/...` (instalado: Chromium snap, que não lê `/tmp`).
- 22 units/timers instalados não estavam versionados (digest-diario, intel-cache, metacognicao, pcrj-intel,
  pncp-resultados, bombeiros-supervisor, warp, notificar-falha@, sweeps-serial*, keepalive, painel-tunnel,
  handoff-watcher) + drop-ins (`onfailure.conf` em 12 units, intel-cache, pncp-resultados/atas, jfn/unbuffered).
- VM-2: 10 units sem versão (`jfn-analise`, `jfn-sei-sweep`, `jfn-sentinela-integridade`, `jfn-suite`, `jfn-sweeps`)
  e **`tools/vm2_sweep.sh` só existia na VM-2** (`git log --all` vazio) — o `jfn-sweeps.timer` ativo rodava um
  script que o repositório não tinha.
- `massare-{daily,market}.{service,timer}` apontavam para `-m massare.*`, módulo fora da VM desde 2026-07-07
  (decisão do dono) → apagados. O README ainda mandava `enable --now massare-market.timer`.
- `deploy/jfn-fisc-refresh.*` e `deploy/jfn-sei-noturno.*` soltos na raiz de `deploy/` → `deploy/systemd/`.
- Fora do espelho de propósito: `whatsapp-*` (nada do WhatsApp sai da VM) e `hermes-*` (Hermes).
- Novo README: como conferir o espelho (`cmp`) e instalar uma unit por vez.

### 1.2 Divergências que ficaram para o dono  `[pendente]`

- `jfn.service`: o instalado escuta em `0.0.0.0:8000` (há um `.bak.pre-expose`); o repositório e o CLAUDE.md dizem
  `127.0.0.1`. Não copiei — expor a API é decisão de segurança.
- `jfn-pcrj-intel.timer`: descrição "semanal (dom 06:40)", `OnCalendar=*-*-* 06:40:00` é **diário**.
- `jfn-radar.*` (Radar 24/7) existe no repositório e não está instalado nem no cron: `compliance_agent.radar` não roda.
- `sweeps-serial*.service` desligados ("lane contínuo revertido"); `tools/beneficios_supervisor.sh` e
  `tools/endereco_supervisor.sh` ficaram sem unit nem cron (o trabalho deles está em `sweeps_serial.sh`).

## 2. Código sem chamador  `[feito — dbcd4d46, 2f618601]`

Conferido por grep em código, `tests/`, `config/` (inclusive `propagacao.yaml`), units instaladas e `crontab -l`.
- `tools/enviar_sessao_telegram.py` — envio único de 2026-06-06 (arquivo de saída e chat do dono fixos no código).
- `tools/enviar_forense_telegram.py` — veredito ITERJ×MGS, caso encerrado; era a única exceção nomeada de
  `test_import_nao_executa_trabalho` (a exceção fica vazia). Os dois liam o token por regex de `~/.hermes/.env`.
- `tools/painel_extrair.py` — migração de 2026-07-30 (CSS/JS inline → arquivos); o HTML hoje tem 5,9 KB sem
  `<style>` e o script procura um `painel.js` que não existe. Levava a cópia de `_hash8` que o `painel_bump_versao`
  dizia espelhar.

## 3. Caminho do banco e "só dígitos" pelas fontes únicas  `[feito — d478f8c4]`

- `backfill_enderecos`, `backfill_verificacao_endereco`: `_REPO/"data"/"compliance.db"`; `gerar_requisicoes`:
  `"data/compliance.db"` relativo ao cwd → `collectors.arquivos.caminho_db()` (o conftest passa a valer).
- `backfill_enderecos._digs` = `cpf_cnpj.digitos`.

## 4. Falhas caladas em scripts de infra  `[feito — defeitos — d396ae19, 8c1dab48, c5f481d7, 3511cd88]`

- `guardiao_db_malformed.sh`: a marca `.guardiao_corrompido.alertado` era gravada **antes** do `notificar()` (que
  rodava com `2>/dev/null`) — um envio que falhasse calava o alerta de banco corrompido até o banco sarar. Agora a
  marca entra só quando o aviso saiu (ou foi silenciado por decisão do dono de 17/11).
- `colher_vm2.sh`: `rc=$?` dentro de `if ! rsync` sempre registrava 0; `fim (rc=$?)` era o status do último `say`.
- `prewarm_painel.sh`: `curl` sem `-m` segurava o `flock` para sempre numa rota que aceita e não responde; teto 600 s.
- `testar_na_vm2.sh`: status do `tar` ignorado (pacote parcial seguia com md5 "conferido").
- `migracao_bringup.sh`: tentava ligar os timers do Massare.
- `diag_telegram_poller.sh`: o último `pkill -f` de `tools/` (CNF-16) → `pgrep` + `kill` por PID; catraca apertada.

## 5. Gate do painel cego no entrypoint  `[feito — defeito — 46552ee4]`

- `painel_modulo_livre` pulava o `entrada.js` ("importa tudo") — onde o `jfnToast` livre passou
  (`painel.md` §9.5). Incluído; zero achados hoje, controle positivo acusa.

## 6. Pendentes — decisão do dono ou máquina/área alheia

1. **`tools/pre_push_gate.sh:23` `cd /home/ubuntu/JFN || exit 0`**: um push feito de um worktree mede o checkout
   principal, não o código empurrado; se o `cd` falhar o push passa calado; log fixo em `/tmp/pre_push.log`
   (pushes simultâneos se sobrescrevem). Não mexi: é o portão compartilhado por todas as sessões e o worktree não
   tem `.venv` (o gate diria "não medi"). Correção proposta: `git rev-parse --show-toplevel` + venv do checkout
   comum (`git rev-parse --git-common-dir`).
2. **`deploy/vm2/run_sweep.sh:57-60` (SEI-PCRJ, VM-2)**: o rc do `--merge` é ignorado e logo depois
   `rm -f data/sei_pcrj_[0-9]*.db` apaga os shards — merge que falhe perde dado; `cp ... 2>/dev/null` e o log
   "DB -> shared-brain" saem mesmo assim. O arquivo é idêntico ao instalado na VM-2: corrigir só aqui criaria
   divergência; precisa implantar lá (`if merge; then rm; fi`).
3. **Duas raízes na VM-2**: `vm2_integras/sweep_geral/ocr_reserva` usam `~/JFN-worker`; `vm2_suite`, `vm2_analise`,
   `colher_vm2` e as units `jfn-analise/suite/sweeps/sentinela` usam `~/JFN`, que `vm2_integras.sh:11` chama de
   "cópia rsync antiga". Apelidos SSH também variam (`vm2`, `vm2-ts`, `vm1`, `vm1-ts`).
4. **Biblioteca de shell comum** (redesenho, toca famílias de outros agentes): `say()` idêntico em 15 scripts;
   checagem de carga em ~22 com limiares 1,8–12 e três fórmulas (`int($1)`, `$1*10`, `printf %d`); `flock` com três
   lugares de trava (`/tmp`, `data/`, `data/locks/`); `.env` carregado de três jeitos (`. .env 2>/dev/null` segue sem
   credencial); cabeçalho da VM-2 copiado entre `vm2_integras.sh:10-38` e `vm2_sweep_geral.sh:7-24`. O lugar é
   `tools/lib/` (já tem `oom_guard.sh`, `systemd_user_env.sh`).
5. **Caminho fixo `/home/ubuntu/...` nos `hermes_*`** (`metacognicao`, `rag`, `auto_melhoria`): mantido porque
   `tests/test_hermes_metacognicao.py::test_backup_memoria_exporta_e_roda_rotacao` lê o banco REAL por esse caminho
   (na VM-2, `~/JFN/data`); derivar de `__file__` quebra o teste fora do checkout principal. Junto com Testes.
6. **`tools/hermes_model_router.py`** nunca foi ligado ao gateway ("FALTA o WIRING", JFN-2.0); só o teste o segura.
7. Candidatos a morto não apagados (na dúvida): `guardiao_failover.sh` + `desktop_disponivel.sh` (cron comentado);
   capturas avulsas de caso (`aguarda_e_captura_amc`, `captura_dirigida_amc{,2}`, `run_integras_bombeiros`,
   `mopup_refichar`, `editais_finalizar`, `rebuild_beneficios` — famílias de investigação); legado `iniciar.sh`
   (Windows; imprime o usuário do SIAFE na tela), `setup_oracle_cloud.sh` (Docker), `start_linux.sh`. Os `v6x_*.ps1/.sh`
   de render ficam: são a receita dos assets do painel, rodados à mão no it-campo.
8. Outras falhas caladas achadas (scripts fora do meu recorte ou manuais): `pos_auth_push_ci.sh:52-65` pode dizer
   "0 falhas" quando o download falhou; `sweeps_serial.sh:20` pipe sem `pipefail` mascara o rc;
   `backup_compliance.sh:31` `rclone 2>/dev/null`; `manutencao_diaria.sh:23` sai 0 na exceção; `cruzador.sh:47`
   `except: pass` por UG; `deploy/itcampo/ocr_gpu/vllm_surya.sh:11-14` sai 0 sem o vLLM subir (it-campo).
9. Token visível no `ps`: `diag_telegram_poller.sh` (token na URL do `curl`) e `rotate_telegram_token.sh` (token
   como argumento).

## 7. Anotado (fora do escopo)

- `docs/manuais/07-CRONS-TIMERS.md` e `docs/REFERENCIA-PROJETO.md` dizem `backfill_enderecos` às 05:40 — não está no
  crontab; `ambiente.json` ainda lista `massare-*` e `massare_db`; `docs/RUNBOOK-BOOT-E-ANTIIDLE.md` idem.
- `tools/backfill_enderecos` importa o privado `rede_societaria._gravar_endereco`.
- `tools/enviar_fachadas_flagueadas.py` (família fachada) sem chamador.
- Em worktree o `pre-commit` não roda ruff nem o gate de capacidades (não há `.venv`); rodei `ruff` à mão nos `.py`
  tocados.
- Comentários: nos `.py` do recorte quase todos carregam medição datada ou porquê — não achei restatement a podar
  além do que saiu com o código apagado.
- Eleição: nada tocado, nada achado.
