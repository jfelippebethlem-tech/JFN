# ADR-008 — Segurança de produção

| Campo | Valor |
|---|---|
| **Estado** | Proposto (esqueleto da O1.4, 24/11/2026). A decisão final sai na onda indicada no plano |
| **Plano** | `~/vault/refatoracao/PLANO-MESTRE-v2-esteira-unica.md`; questão do doc 2 §31 |
| **Questão** | Como autenticar, autorizar, segregar a rede, gerir segredos e auditar a exportação? |
| **Relacionados** | ADR-001 (autoridade de dados), ADR-012 (motor `jfn-fluxo`) |

## Contexto

Na linha de base: autenticação que falhava aberta, bind em todas as interfaces, sem cookie Secure, SSRF no solucionador de captcha, um workflow que aceitava credencial como input, nenhum scanner de PII ou segredo. A O0.3 já fechou bind, cookie e modo manutenção (§16.8).

## Decisão

- Boot falha-fechado sem senha forte (mínimo de 20 caracteres em produção).
- Bind local; acesso externo só pelo túnel autenticado.
- Segredos só em arquivo fora do git, lidos por variável de ambiente.
- Scanner de CPF e de segredo no pre-commit e no CI.
- Egress com lista de permissão para quem busca URL (SSRF).
- Egress de rede dos jobs restrito no kernel (O0.4, aplicado em 24/11/2026 — seção abaixo).
- Exportação de dossiê registrada (quem, quando, hash).

## Egress dos jobs por cgroup v2 (O0.4, aplicado na VM-1 e na VM-2 em 24/11/2026)

O commit 02707398 casava a regra por uid (`meta skuid`), o que exigia criar o usuário `jfn-coletor`, e o dono
vetou criar usuário. A regra agora casa por **cgroup v2**: `socket cgroupv2 level 5
"user.slice/user-1001.slice/user@1001.service/jfn.slice/jfn-coletor.slice" jump coletor` (tabela própria
`inet jfn_egress`, `deploy/seguranca/nftables-egress.nft`). Todos os jobs do motor de fluxo rodam nessa fatia de
usuário: o supervisor lança cada um com `systemd-run --user --scope --slice=jfn-coletor.slice`. A fatia é a antiga
`jfn-jobs.slice`, renomeada com os mesmos limites. Dentro da fatia ficam recusados a metadata e todo o link-local,
o loopback (fora PG 5432, CDP 9222/9333 e DNS do stub), a RFC1918 e a Tailnet, salvo PG e túnel 2222 da VM-2. O resto
do mesmo uid (painel, PG client, Tailscale, ssh, CDP, polimonitor, brain) não muda, e isso foi medido nas duas VMs.

- **Armadilha medida 1.** O nft converte o caminho no ID (inode) do cgroup **na carga**. Por isso o cgroup tem de
  existir: sem ele a carga dá `cgroupv2 path fails: No such file or directory`. Com a fatia parada e religada, o ID
  muda e a regra para de casar, o que é **falha aberta** (o `ensaio_netns.sh --religar` prova isso nas duas VMs).
  `egress.sh estado` acusa: o `nft list` mostra o número no lugar do caminho.
- **Como volta sozinha.** `deploy/systemd/jfn-egress.service` é uma unit de **usuário** (nada em `/etc`).
  É `PartOf=` e `Requires=`/`After=` da fatia, e a fatia tem `Wants=` dela. Assim, a fatia que sobe (no boot pelo
  linger, ou religada) recarrega a regra com `sudo -n egress.sh carregar`. O dono já tem NOPASSWD, então nada novo é
  concedido. O escopo de cada job tem `Wants=`/`After=jfn-egress.service`, o que fecha a janela de milissegundos
  medida entre a fatia nascer e a regra recarregar. O `jfn-fluxo@.service` sobe depois do jfn-egress.
- **Desfazer.** `systemctl --user disable --now jfn-egress.service` (o ExecStop remove a tabela) ou
  `sudo deploy/seguranca/egress.sh desfazer`. Na VM-2 a cópia fica em `~/.local/share/jfn-egress`, com o drop-in
  `EGRESS_DIR`, até a árvore `~/JFN-worker` receber o commit.
- **Fora do escopo.** No it-campo (WSL, sem sudo do lado Linux) a unit não é instalada. A unit ausente não bloqueia
  o escopo (`Wants=`), então lá os jobs rodam sem egress restrito, como antes.

## Backup, restauração, retenção e criptografia (O8.2, 24/11/2026)

Regra 3-2-1-1-0 (plano mestre v2 §14): 3 cópias, 2 meios, 1 fora da máquina, 1 offline (HD do it-campo, camada
morna) e **0 erro na restauração conferida**. Backup sem restauração medida não conta.

### RPO/RTO por classe

| Classe | O que é | RPO alvo | RTO alvo | Hoje (medido em 24/11/2026) |
|---|---|---|---|---|
| Metadados | PG `jfn_evidencias` (public, dominio, fluxo) e `compliance.db` | 24 h | 4 h | PG: dump diário às 02:40, então RPO de 24 h. `compliance.db`: backup **diário** às 03:50 desde 24/11/2026, pela porta única (`tools/backup_compliance.sh`), então RPO de 24 h. Até então era semanal (RPO de 7 dias). RTO medido no it-campo: pg_restore de 155 MB em 15,3 s, cópia + quick_check de 6,4 GB em 79,9 s, mais o transporte |
| Originais | PDFs e íntegras SEI pela porta única (ADR-003) | zero perda depois da conferência | 8 h | 2 cópias grátis com hash conferido antes de apagar o local. A restauração em massa não foi medida |
| Fila | `fluxo.jobs`, `fluxo.eventos`, `fluxo.agenda` | — (o estado se refaz pela propagação) | 2 h | entra no dump do PG (23 tabelas conferidas em 24/11) |
| Índices | `armazenamento_indice.db`, índices derivados | — (são regeneráveis) | 24 h | cópia em `gdrive:indice/` e num remoto grátis |

### Restauração semanal

- A rotina `restauracao_semanal` (E17, `tools/restauracao_semanal.py`) roda no it-campo e volta para a VM-2. Ela
  confere o md5 contra o `MD5SUMS`, sobe um PostgreSQL temporário (só socket, sem rede, `archive_mode=off`) e faz
  `pg_restore`. Também copia o `compliance.db`, confere o md5 da cópia e roda o `quick_check`. As contagens têm de
  ser **iguais** às da origem, e essas contagens viajam com o backup, tiradas no mesmo instante. O resultado vai para
  `fluxo.metricas` como `backup.restauracao_ok` e `backup.restauracao_quando`.
- A régua é a contagem gravada **junto com o backup**, não a contagem viva. Em 24/11, o dump noturno das 02:40
  restaurou 0 linhas em `processos`, `arvores`, `documentos` e `versoes`. O banco vivo tinha 16.594, 16.594, 595.092
  e 586.311 linhas, carregadas depois do dump, entre 15:55 e 16:12 UTC. O dump não estava errado: estava velho.
  Comparar com o vivo acusaria falha falsa, e com um piso deixaria passar perda.
- Primeira restauração real: 24/11/2026, 18:22–18:24 (-03), no it-campo. Resultado ok: 28 de 28 tabelas conferidas
  (PG 23/23, SQLite 5/5) e `quick_check = ok`. A métrica é `fluxo.metricas` id 64 e 65, execução `6dd5cac8c83f`.

### WAL-G (arquivamento contínuo): PREPARADO, não ligado (atualizado em 24/11/2026, noite)

Atualização: o R2 foi liberado (8,09 → 5,17 GiB). A porta única tirou de lá os dois re-obtíveis do `encher`
(3,14 GB), com o md5 do Drive conferido antes. `r2.reserva_gb = 3.5` guarda o espaço do `pg-evidencias/`. O WAL-G
v3.0.9 foi instalado na VM-2 com o sha256 da release, e `/etc/wal-g/walg.yaml` (postgres 600) usa a chave R2 **que já
existia** no `rclone.conf`. A ida e volta foi provada (`deploy/vm2/postgres/walg_preparar.sh provar`). O
`archive_mode` **não** foi ligado: ele exige restart do PG, que é compartilhado com o brain, e a janela é do dono
(passo a passo em `deploy/vm2/postgres/backup.md` §5). Há dois desvios do plano abaixo, os dois por causa da regra
do dono de 24/11, "não criar chave": a chave não é restrita ao bucket e o `walg.yaml` leva a chave, que é a mesma
que já está em claro no `rclone.conf` da máquina. Os passos 1 e 3 abaixo ficam pendentes de decisão.

Texto de 24/11 (tarde), mantido como histórico: Em 24/11/2026 nenhum remoto S3 de `config/armazenamento_nuvens.json` comprovou ser grátis para uma
base de ~1,8 GB descomprimida (2 completas retidas) mais o WAL:

- **R2.** O free tier e a saída grátis estão confirmados em <https://developers.cloudflare.com/r2/pricing/>
  (`dateModified` 2026-10-30, lida em 24/11/2026): "10 GB-month / month", "There are no charges for egress
  bandwidth for any storage class". Mas o bucket já usa 8,69 GB dos 10 GB e a folga é de 0,81 GB com margem.
  O que passar disso custa US$ 0,015/GB-mês, e a página não fala de teto rígido. A chave S3 também não está no
  resolvedor de credenciais.
- **B2.** Usa 7,19 GB dos 10 GB e ainda tem a reserva de 1,7 GB do `backup_compliance.sh`. A conta tem teto de
  US$ 0, mas não sobra espaço.
- **IDrive e2.** Está vazio, mas <https://www.idrive.com/s3-storage-e2/pricing> só diz "Try with 10GB Free". Nenhuma
  página prova que o plano é permanente, e <https://www.idrive.com/s3-storage-e2/faq-pricing> diz que o excedente
  é cobrado ("overuse charge of $0.006/GB/Month", "$0.01 per GB") sem teto.

O estado está registrado em `fluxo.metricas` como `backup.walg_remoto_gratis = NaN` com `estado = INDISPONIVEL`.

Para religar, o dono decide liberar pelo menos 3 GB no R2, por exemplo movendo `frio/` para o Drive pela porta única.
Depois, a sessão principal segue estes passos:

1. Criar uma chave R2 restrita ao bucket e registrá-la no `~/CREDENCIAIS.md` da VM-1.
2. Instalar o `wal-g` com o sha256 da release na VM-2.
3. Criar um serviço que resolve a credencial uma única vez pelo `compliance_agent.credenciais com …` e sobe
   `wal-g daemon`. O `archive_command` usa o cliente do daemon. Nenhum arquivo de credencial é copiado entre
   máquinas, e o `walg.yaml` não leva chave.
4. Fazer o pré-voo de 3 GB do `backup.md` §3.
5. Ligar `archive_mode` e reiniciar o PG, o que exige janela, porque o PG é compartilhado com o brain.

### Retenção, criptografia e legal hold

- **Retenção.** Diário do PG: os 7 últimos e 4 semanais. `compliance.db` (diário desde 24/11/2026): no Drive ficam
  os 7 mais novos, e em cada outro remoto os 2 mais novos dele (`armazenamento podar`). Nada sai se o backup do dia
  não cumpriu a política. Os 3 semanais antigos em `b2:…/compliance/` ficam até a O8.2. Snapshot no HD:
  4 semanais e 1 mensal por 12 meses. Nada sai da rotação sem uma cópia mais nova conferida por hash.
- **Criptografia, atualizada em 24/11/2026 (noite).** O dono proibiu criar chave nova, então a chave privada
  offline abaixo **não** pode ser gerada. Proposta, com prova feita, pendente do ok do dono: cifrar com `age` para as
  chaves SSH ed25519 que **já existem**, `-R` com três destinatários (VM-1 `id_ed25519`, VM-2 `id_ed25519` e a do
  WSL do it-campo). Qualquer uma das três máquinas decifra. Prova: `achados.db.gz` (1,75 MB) foi cifrado e decifrado
  na VM-1 e na VM-2 com sha256 igual e `quick_check = ok`. Uma chave que não está entre os destinatários foi recusada.
  Os riscos ficam registrados: quem tiver uma das chaves SSH decifra tudo, e perder as três perde os backups
  cifrados. O WAL-G **não** aceita `age` nem SSH, só libsodium ou PGP, que seriam chave nova. Por isso a cifra do
  WAL-G fica BLOQUEADA, e vale a cifra em repouso do R2 (AES-256-GCM). `age` 1.1.1 foi instalado por apt na VM-1 e
  na VM-2.
- **Criptografia (`age`), plano original.** Todo backup que sai para a nuvem sai cifrado. A chave pública fica no repo, porque não
  é segredo. A chave privada fica **offline** com o dono, em papel ou no cofre, e o dono ainda tem de decidir onde.
  Hoje os `.gz` e `.dump` vão **em claro** para o B2 e o Drive, e o `compliance.db` contém CPF de sócio. Essa é a
  lacuna principal, e o `age` ainda não está instalado nas máquinas. O HD local pode ficar em claro, porque é
  offline e do dono. A restauração semanal decifra só no disco de trabalho e apaga no fim.
- **Legal hold.** Pode ser a evidência citada em dossiê exportado, em representação ou em parecer Lex, ou o backup
  do período dessa evidência. Um item assim nunca sai pela rotação: fica marcado no índice da porta única até o dono
  liberar.

## Consequências

Superfície mínima num repo público. O custo é que a troca de senha e a ativação de `JFN_ENV=producao` dependem do dono.

## Não adotar

Limpar o histórico do repo agora (é a decisão 5 do dono: só na O9.4, com ok). Expor a porta do painel na rede privada sem login.

## Gatilho de reavaliação

Incidente ou tentativa registrada, um segredo achado pelo scanner, ou uma mudança de exposição (porta nova ou túnel novo).
