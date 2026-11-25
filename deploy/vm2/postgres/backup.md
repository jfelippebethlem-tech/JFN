# Backup do PostgreSQL de evidências (VM-2) — WAL-G em nuvem GRÁTIS

> Plano: `docs/PLANO-PLATAFORMA-EVIDENCIAS.md`, Fase 3 ("WAL contínuo para nuvem grátis e restauração testada toda
> semana na VM-1"). Escrito em 23/11/2026; **nada disto foi executado ainda** (o PostgreSQL não existe até o disco
> da VM-2 sair dos 96%).

> **TETO DE GASTO = ZERO (regra do dono, 21/11/2026).** Só armazenamento já ligado no rclone e dentro do plano
> grátis. Nenhum provedor pago, nenhum cap acima de zero, nenhum cartão novo. Os limites valem o que diz
> `config/armazenamento_nuvens.json` (fonte oficial citada lá) — conferir de novo na página oficial antes de
> ligar (regra "nunca assumir free tier").

## 1. Recomendação

| Item | Escolha | Por quê |
|---|---|---|
| Ferramenta | **WAL-G** (binário único, Go) | Fala S3 direto (sem disco intermediário na VM-2, que é o recurso escasso); compressão zstd; `backup-push` base + `wal-push` contínuo; `delete retain` para caber na cota; restauração por `backup-fetch` + `wal-fetch`. pgBackRest exigiria repositório local ou S3 igualmente, sem ganho aqui. |
| Destino principal | **Cloudflare R2** (`r2:` do rclone, bucket `jorgefelippe`, prefixo `pg-evidencias/`) | API S3 nativa do WAL-G; **saída grátis** (o teste semanal de restauração baixa o backup inteiro toda semana — no B2 isso gastaria a cota de 1 GB/dia de download); grátis: 10 GB armazenados, 1 M operações classe A/mês, 10 M classe B/mês. |
| 2ª cópia | **Google Drive** (`gdrive:`), pela porta única `compliance_agent.armazenamento` (classe insubstituível) | Drive = destino principal da casa (~390 GB livres). Nunca `rclone` avulso (CLAUDE.md, NÃO REINVENTAR #11). |
| Não usar | B2 (download 1 GB/dia trava a restauração semanal), MEGA/TeraBox/Blomp (sem S3), qualquer plano pago | — |

**Orçamento no R2.** O bucket `jorgefelippe` já guarda `frio/` e `indice/` e a cota de 10 GB é do bucket todo.
Reservar **até 3 GB** para `pg-evidencias/` (o esquema atual — metadado de 518 mil documentos, filas, fatos — fica na
casa das centenas de MB comprimido). Operações: `archive_timeout = 600` gera no máximo ~4,4 mil segmentos/mês num banco
parado, mais os ativos — ordem de dezenas de milhares de PUT (classe A), muito abaixo de 1 M.

## 2. Instalação do WAL-G (na VM-2 e, para o teste de restauração, na VM-1)

1. Baixar o binário **arm64** da release oficial (`github.com/wal-g/wal-g/releases`, artefato
   `wal-g-pg-ubuntu-24.04-aarch64`), **conferir o sha256 publicado na release** e instalar em
   `/usr/local/bin/wal-g` (root:root 755). Nada de `curl | sh`.
2. Criar a chave S3 do R2 **restrita ao bucket** (painel Cloudflare → R2 → API tokens, permissão Object Read & Write
   só em `jorgefelippe`). As credenciais vão para `/etc/wal-g/walg.yaml` (postgres:postgres **600**) e para o
   `~/CREDENCIAIS.md`; nunca para o git.

```yaml
# /etc/wal-g/walg.yaml — modelo (valores reais só no arquivo da máquina)
WALG_S3_PREFIX: s3://jorgefelippe/pg-evidencias
AWS_ENDPOINT: https://<ID_DA_CONTA>.r2.cloudflarestorage.com
AWS_REGION: auto
AWS_S3_FORCE_PATH_STYLE: "true"
AWS_ACCESS_KEY_ID: <da chave R2 restrita>
AWS_SECRET_ACCESS_KEY: <da chave R2 restrita>
WALG_COMPRESSION_METHOD: zstd
WALG_DELTA_MAX_STEPS: "0"         # só backups completos: restauração simples e previsível
PGHOST: /var/run/postgresql
PGUSER: postgres
PGDATABASE: jfn_evidencias
```

3. Rodar `deploy/vm2/postgres/instalar.sh` (ele recusa ligar `archive_mode` sem este arquivo — senão o `pg_wal`
   cresceria até encher o disco).
4. Conferir que o arquivamento anda: `SELECT archived_count, failed_count, last_failed_wal FROM pg_stat_archiver;`
   (`failed_count` subindo = WAL acumulando na VM-2; o sensor da automelhoria deve olhar isso — "atraso do WAL").

## 3. Rotina semanal (VM-2, timer systemd, fora do horário do sweep)

```bash
# 1) contagens no momento do backup vão JUNTO com ele (user-data) — o teste de restauração confere contra elas
CONT=$(sudo -u postgres psql -d jfn_evidencias -qAt -c "SELECT json_build_object(
  'processos',(SELECT count(*) FROM processos), 'arvores',(SELECT count(*) FROM arvores),
  'documentos',(SELECT count(*) FROM documentos), 'versoes',(SELECT count(*) FROM versoes),
  'jobs',(SELECT count(*) FROM jobs))")
# 2) pré-voo do teto zero: prefixo + novo backup têm de caber em 3 GB (senão NÃO sobe e avisa)
rclone size r2:jorgefelippe/pg-evidencias --json     # comparar bytes + pg_database_size com 3 GB
# 3) backup base
sudo -u postgres wal-g --config /etc/wal-g/walg.yaml backup-push /var/lib/postgresql/16/main \
     --add-user-data "{\"contagens\": $CONT}"
# 4) retenção: 2 backups completos + o WAL entre eles (o resto é apagado; DeleteObject é grátis no R2)
sudo -u postgres wal-g --config /etc/wal-g/walg.yaml delete retain FULL 2 --confirm
# 5) 2ª cópia pela porta única (Drive), com hash conferido
```

Depois do backup, a **VM-1** roda `deploy/vm2/postgres/restaurar_teste.sh` (timer semanal, 1 h depois): restaura o
último backup numa instância temporária, reaplica o WAL até o fim, confere as contagens contra o `user-data` e grava
o resultado em `data/plataforma/restauracao_pg.json` (sensor "resultado do último teste de restauração").

## 4. Dúvidas abertas (decisão do dono)

- O R2 é dividido com `frio/` e `indice/`: confirmar a reserva de 3 GB para o banco.
- A VM-1 precisa de `postgresql-16` (só os binários, sem serviço ativo) e do `wal-g` para o teste de restauração —
  instalar só com ok do dono e com a VM-1 aliviada.

## 5. Estado em 24/11/2026 (decisão delegada; `~/vault/refatoracao/decisoes-delegadas-infra-20261124.md`)

**Feito (sem tocar no PostgreSQL):**

- **R2 liberado:** `armazenamento consolidar-legado --aplicar` tirou do R2 os dois re-obtíveis que o `encher` pusera lá
  (`compliance_analitico.db.gz` 1,67 GB e `receita_estab.db.gz` 1,47 GB; md5 da listagem do Drive igual ao do R2
  antes de apagar). Bucket: 8,09 GiB → 5,17 GiB. `config/armazenamento_nuvens.json` ganhou `r2.reserva_gb = 3.5`
  para o `pg-evidencias/` — o pré-voo da porta única não deixa a 2ª cópia nem o `encher` ocupar esse espaço.
- **WAL-G v3.0.9** instalado em `/usr/local/bin/wal-g` da VM-2 por `deploy/vm2/postgres/walg_preparar.sh instalar`
  (sha256 da release conferido: `1edd72c3…5d64`). A v3.0.10 (17/11) foi preterida por ser nova demais.
- **`/etc/wal-g/walg.yaml`** (postgres 600) por `walg_preparar.sh config`, com a chave do R2 **que já existia** no
  `rclone.conf` — a regra do dono de 24/11 proíbe criar chave nova, então o passo 2 da §2 ("chave restrita ao
  bucket") fica **substituído** por esta reutilização. Risco aceito e registrado: o escopo da chave é o do
  `rclone.conf` (o mesmo que a porta única já usa); restringir exige chave nova = decisão do dono.
- **Prova:** `walg_preparar.sh provar` — `st put` → `st ls` → `st get` (cmp de 4 096 bytes) → `st rm`, OK.

**Falta (janela do dono — restart do PG derruba o brain por alguns segundos):**

1. `sudo -u postgres psql -c "SELECT pg_size_pretty(sum(pg_database_size(datname))) FROM pg_database"` — conferir
   que o cluster comprimido cabe em 3,5 GB × 2 backups (3,0 GB cru em 24/11; zstd deve ficar ≈ 1 GB).
2. Em `/etc/postgresql/16/main/conf.d/jfn.conf` (ou por `instalar.sh`): `archive_mode = on`,
   `archive_command = '/usr/local/bin/wal-g --config /etc/wal-g/walg.yaml wal-push %p'`, `archive_timeout = 600`.
   `archive_mode` só vale no start do servidor (doc do PG 16, runtime-config-wal) → `sudo systemctl restart
   postgresql@16-main` NA JANELA. `archive_command` e `archive_timeout` mudam depois só com reload.
3. Logo após: `SELECT archived_count, failed_count FROM pg_stat_archiver;` (failed_count = 0) e
   `sudo -u postgres wal-g --config /etc/wal-g/walg.yaml backup-push /var/lib/postgresql/16/main`.
4. Retenção `delete retain FULL 2 --confirm` e o teste de restauração da §3 (`restaurar_teste.sh`).
5. **Desfazer:** `archive_mode = off` + restart; `sudo rm -rf /etc/wal-g /usr/local/bin/wal-g`;
   `rclone purge r2:jorgefelippe/pg-evidencias` (DeleteObject é grátis no R2); tirar `reserva_gb` do r2.

**Criptografia do WAL-G: BLOQUEADA pela regra do dono.** O WAL-G só cifra com chave libsodium de 32 bytes
(`WALG_LIBSODIUM_KEY`) ou chave OpenPGP (`WALG_PGP_KEY`) — as duas seriam chave NOVA (doc oficial
wal-g.readthedocs.io, seção Encryption; nenhuma opção aceita chave SSH ou `age`). Fica a cifra em repouso do próprio
R2 (AES-256-GCM, chaves da Cloudflare — developers.cloudflare.com/r2/reference/data-security/) e o TLS em trânsito.
