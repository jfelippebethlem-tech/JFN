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
