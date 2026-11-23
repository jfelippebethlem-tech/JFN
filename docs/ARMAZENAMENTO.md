# ARMAZENAMENTO DO JFN — camadas, política, índice e zeladores

> **Pedido do dono (21/11/2026):** "monta uma arquitetura que use o r2 e b2, drive, it campo e tenhamos
> detectores semanais […] pra liberar storage" · "mantendo tudo disponível pra vm1 e 2, mesmo que o it campo esteja
> desligado" · "vamos usar e ensinar todos a usarem os armazenamentos em cloud" · "tem que indexar tudo e organizar
> pra todos saberem" · "duas cópias na nuvem? assim gasta o dobro" · "automatize isso sem margem pra erro".
>
> **Código:** `compliance_agent/armazenamento.py` (porta única + índice + pré-voo por nuvem) ·
> `config/armazenamento_nuvens.json` (fonte ÚNICA dos remotos e dos limites grátis, §6) · `tools/zelador/zelador.py`
> (ciclo semanal, um perfil por máquina) · testes `tests/test_armazenamento_zelador.py` (controle positivo e
> negativo de cada trava e de cada limite grátis).

---

## 1. Regra para todos (sessões Claude, ferramentas, Yoda/Hermes)

1. **A VM não é depósito.** VM-1 e VM-2 guardam só o que o JFN lê/escreve hoje. Arquivo parado vai para a nuvem
   pela porta única — nunca por `rclone`/`rsync` avulso, nunca para o it-campo.
2. **Guardar:** `python -m compliance_agent.armazenamento guardar <arquivo> --classe <classe> [--apagar-local]`
   (ou `from compliance_agent.armazenamento import guardar`). Sobe, confere o hash na nuvem, indexa; só apaga o
   local com `--apagar-local` e com TODAS as cópias exigidas conferidas naquela hora.
3. **Achar:** `python -m compliance_agent.armazenamento onde <caminho | processo 070002/021988/2025 | CNPJ>`.
4. **Trazer de volta:** `obter(caminho)` devolve o próprio arquivo se ele existe; senão baixa do frio, confere o md5
   e entrega em `~/.cache/jfn-frio/…` (ou no lugar original com `--restaurar`). Leitor novo que não acha um arquivo
   local deve chamar `obter()` antes de concluir "não existe".
5. **Visão geral:** `python -m compliance_agent.armazenamento resumo`.

---

## 2. Camadas

| Camada | Onde | O que mora | Quem garante |
|---|---|---|---|
| **Quente** | VM-1 (`~/JFN/data`), VM-2 (`~/JFN`, `~/JFN-worker`) | bancos vivos, `sei_arquivo`, caches em uso, filas | cada pipeline |
| **Morno** | VM-2 `~/arquivo_frio` | PDFs escaneados à espera do OCR da GPU (a fila `tools/sei_ocr_gpu_fila.py` só enxerga o que existe aqui) | `tools/sei_arquivo_frio.sh` (VM-1 → VM-2, de hora em hora) |
| **Frio** | **Google Drive** pasta `JFN/` (cota 400 GiB da conta do dono) + 2ª cópia no grátis: **B2** `jfn-backup-jorge`, **R2** `jorgefelippe`, **MEGA** `JFN/` (e as próximas, só por config) | tudo o que não é lido no dia a dia; backups | zelador semanal, com índice e pré-voo de limite grátis (§6) |
| **Serviço** | R2 `jorgefelippe` (`fachadas/`, `anexos/`) | arquivos servidos por URL (saída sem custo) | quem publica |
| **Cache/processamento** | it-campo (GPU, OCR, réplicas de sessão) | nada que as VMs precisem; pode desligar sem perda | — |

**Pasta do Drive** (`gdrive:` no rclone = pasta `JFN`, `root_folder_id` no `rclone.conf`):
`frio/<maquina>/<caminho relativo a ~>` · `indice/<maquina>.db` · `backups/` · `relatorios/` · `artes/`.

---

## 3. Política por natureza do arquivo

| Natureza | Classes | Cópias | Destino(s) | Por quê |
|---|---|---|---|---|
| **Re-obtível** (a fonte pública tem) | `sei_pdf`, `sei_foto`, `sei_cache`, `sei_arvore`, `quarentena`, `substituido`, `tse`, `pncp`, `receita`, `coleta_cache` | **1** | Drive | o provedor já replica internamente; perder = baixar de novo da fonte (índice guarda origem e hash) |
| **Insubstituível** (trabalho próprio) | `backup_db`, `trabalho`, `sessao_claude`, `indice`, `relatorio`, `midia` | **2, provedores diferentes** | Drive + o 1º de `segunda_copia` que couber no grátis (B2 → R2 → MEGA → … → TeraBox, ordem da config) | falha de UM provedor (conta, cobrança, exclusão) não pode levar a única cópia |

Retenção e gatilhos (perfis em `tools/zelador/zelador.py::perfis()`):

| Máquina | Raiz | Classe | Sai após | Observação |
|---|---|---|---|---|
| VM-1 | `data/vm2_quarentena/*`, `data/vm2_entrega/_substituidos/*` | quarentena/substituido | 2 dias parado | nenhum cron lê; `rever_quarentena` é manual → `obter()` |
| VM-1 | `data/sei_arquivo/_substituido/*` | substituido | 7 dias | |
| VM-1 | `~/Desktop/it-campo/vm1/*` (sshfs) | quarentena | já | o que a mudança de 21/11 levou ao it-campo; caminho lógico = o ORIGINAL da VM-1 |
| VM-1 | `~/.claude/projects/**/*.jsonl` | sessao_claude | 21 dias | antes da limpeza de 30 dias do próprio Claude Code |
| VM-1 | `/tmp/claude-1001/-home-ubuntu/<sessão>` | trabalho | 14 dias | scratchpad de sessão encerrada |
| VM-1 | `~/*.db.gz`, `data/backups/*` | backup_db | 30 / 14 dias | |
| VM-2 | `arquivo_frio/vm2_quarentena`, `vm2_substituidos`, `sei_arquivo_substituido` | quarentena/substituido | 2 dias | |
| VM-2 | `arquivo_frio/sei_fotos` | sei_foto | 7 dias | páginas que o `foto_medicao` descarta |
| VM-2 | `arquivo_frio/sei_pdfs`, `sei_cache` | sei_pdf/sei_cache | **só backup** | insumo do OCR; apagar tiraria o documento da fila em silêncio. Libera quando o OCR buscar pelo `obter()` |
| it-campo | `C:\JFN-Arquivo\{sei_fotos, sei_fotos_orig, vm2_quarentena, vm2_substituidos, sei_arquivo_substituido}` | | 1 dia | sobe ao Drive e libera o it-campo |
| it-campo | `C:\JFN-Arquivo\sei_pdfs` | sei_pdf | **só backup** | `sei_ocr_gpu_fila --itcampo-local` lê daqui |

Compressão: pastas viram **um `.tar` por pasta de processo** (sem compressão — PDF/JPG já são comprimidos) para não
subir 250 mil objetos pequenos (o Drive faz ~3 arquivos/s; o tar sobe a ~3 MiB/s por fluxo). A chave do pacote
inclui o md5 do conteúdo: pasta que não mudou não sobe de novo (assinatura nome+tamanho+mtime no índice).

Nunca saem (lista de exclusão testada): `compliance.db`, `compliance_analitico.db`, `pcrj.db`, `pcrj_benef.db`,
`receita_estab.db`, `territorio.db`, `achados.db`, o próprio índice, qualquer `*.db`/`-wal`/`-shm`/`-journal`/
`*.sqlite*`, `.env*`, `rclone.conf`, chaves SSH, código (`*.py *.sh *.js *.ts *.ps1`), `.git`, `.venv`,
`node_modules`, worktrees, `~/.config`, `~/.ssh`, `~/JFN-test` (VM-2), `C:\up\v69` (e todo `C:\up`), perfis de
navegador logado (`chrome-jfn`, `navegador-claude`, `siafe_profile`, `yt-login`).

---

## 4. Índice único

`data/armazenamento_indice.db` (VM-1; nas outras máquinas, o `data/` do repositório ou `~/.zelador/`). Tabelas:

* `unidades` — o que subiu (arquivo ou pacote): chave `<maquina>/<caminho>`, classe, natureza, processo SEI, CNPJ,
  bytes, md5, sha1, assinatura.
* `membros` — **uma linha por arquivo original** (caminho lógico, md5, processo, CNPJ, quando o local foi apagado).
  É por ela que `onde` e `obter` acham qualquer arquivo, inclusive dentro de um pacote.
* `copias` — onde está cada cópia (`gdrive`, `b2`, `r2`), status (`ok`/`sumida`/`divergente`), hash conferido, ciclo
  da conferência.
* `externos` — o que veio antes deste sistema: `~/.zelador/manifesto-nuvem.tsv` (109 arquivos em R2+B2),
  `manifesto-itcampo.tsv` (1.180 arquivos levados ao it-campo em 21/11), `data/sei_arquivo_frio.jsonl` (pastas
  levadas à VM-2/it-campo pela lane horária).
* `remotos` — foto do que existe em cada nuvem (`rclone lsjson -R`), para achar divergência.
* `journal` — toda ação (enviar, apagar, falha) gravada ANTES de acontecer.
* `ciclos` — cada rodada do zelador, com o resumo.

Cada zelador sobe o seu índice a **duas** nuvens (`gdrive:indice/<maq>.db`, `b2:…/indice/<maq>.db`);
`python -m compliance_agent.armazenamento sincronizar` traz os das outras máquinas para `~/.zelador/indices/`, e
`onde`/`obter` consultam todos.

---

## 5. Zelador mensal (1º domingo; dono 22/11/2026) — o ciclo e as travas

`python tools/zelador/zelador.py --perfil {vm1|vm2|itcampo} {--ensaio|--aplicar} [--teto-gb N]`

1. **Pré-voo** — binário do rclone (o oficial em `~/.local/bin` primeiro) responde; em cada vaga da política, ao
   menos um remoto acessível; **por nuvem**: uso real medido no remoto e consumo do dia/mês contra os limites grátis
   (§6); montagens do perfil presentes (VM-1: sshfs do it-campo; it-campo: `/mnt/c`); ≥ 5 GB para empacotar.
   Falhou → aborta. O que o pré-voo recusar no meio do ciclo não é feito e é escalado.
2. **Recuperação** — confere pela listagem (hash do provedor) uma amostra de cada remoto e baixa UMA cópia pequena
   por remoto dentro do teto de amostra (B2 ≤ 50 MB/dia). Hash errado → aborta.
3. **Candidatos** — só raízes da lista branca; por arquivo: exclusão explícita, não-symlink, idade mínima
   (mtime **e** ctime), ninguém com o arquivo aberto (foto única de `/proc/*/fd`), fora da fila viva (VM-2: fila do
   OCR, recusada se tiver mais de 2 dias); um arquivo preso segura a pasta inteira. Teto de GB e de arquivos por
   ciclo (VM-1/VM-2: 40 GB; it-campo: 60 GB).
4. **Envio** — cada unidade sobe a todos os destinos da política; cada cópia é **listada** e o tamanho e o hash
   (md5 no Drive/R2, sha1 no B2; sem hash na listagem → hash por download) conferidos. O código de saída do rclone
   **nunca** é prova. Primeira falha encerra o envio.
5. **Índice** — importa manifestos antigos.
6. **Liberar** (só `--aplicar`, só sem nenhuma falha no ciclo, só depois de um `--ensaio` limpo nesta máquina, e só depois de o índice — com o que vai sair — estar conferido nas DUAS nuvens) —
   por unidade, `liberado_para_apagar()`: todas as cópias exigidas conferidas **neste ciclo**; por arquivo, mesmo
   tamanho, mesmo mtime e mesmo md5 do que subiu e não aberto agora; linha no `journal` antes do `unlink`. Depois, o
   regenerável: caches de pip/uv/npm, revisões do Playwright que nenhum `browsers.json` instalado referencia e que
   não estão rodando, `/tmp/pytest-of-*` parado há 2 dias.
7. **Exportar** o índice às duas nuvens. Falhou → ciclo marcado abortado.
8. **Relatório** em `~/.zelador/relatorio-<ciclo>.json`; aviso ao dono (Telegram, entrega conferida por
   `message_id`) só se houve ação, falha (🆘 ESCALADO) ou disco > 85%.

---

## 6. Nuvens SÓ no grátis — limites, pré-voo e contador (decisão do dono, 21/11/2026)

> **Dono, 21/11:** "o teto é zero mesmo, quero tudo grátis ali" · "use o grátis do backblaze… tudo dele".
> **Nunca** subir cap no Backblaze nem habilitar cobrança em nuvem nenhuma. Drive = principal; B2/R2 (e as nuvens
> grátis que forem sendo ligadas) = 2ª cópia do insubstituível e o grátis que sobra, cheio até o alvo.

**Fonte única:** `config/armazenamento_nuvens.json` — caminho (`raiz`, `frio`, `indice`), como medir o uso
(`about` | `size`), capacidade, margem, reserva, limites grátis e a URL oficial de cada número. Nenhum outro lugar
repete esses números. **Remoto novo** (koofr, pcloud, box, idrive e2, filen, yandex, jottacloud, protondrive,
onedrive, dropbox, internxt…) entra **só** por config: um bloco em `remotos` + o nome em `segunda_copia` (ordem =
preferência) — testado em `test_remoto_novo_entra_so_pela_config`.

### 6.1 Limites aplicados (conferidos nas páginas oficiais em 21/11/2026)

| Remoto | Armazenamento (alvo = limite − margem − reserva) | Operações / download | Fonte oficial |
|---|---|---|---|
| **Drive** (`gdrive:`, principal) | cota da conta pelo `rclone about` (429,5 GB); margem 5 GB | — | one.google.com/about/plans |
| **B2** (`b2:jfn-backup-jorge`) | 10 GB − 0,5 margem − 1,7 reserva* = **7,8 GB** | **1 GB/dia** de download · **2.500 Classe B/dia** · **2.500 Classe C/dia** · amostra de recuperação **≤ 50 MB/dia** | backblaze.com/cloud-storage/pricing ("First 10GB storage is always free") · backblaze.com/cloud-storage/transaction-pricing (classe de cada chamada) · backblaze.com/docs/cloud-storage-data-caps-and-alerts ("Usage counters reset daily at 12:00 AM GMT") · Caps & Alerts da conta (teto US$ 0,00; grátis 1 GB / 2.500 B / 2.500 C por dia; `403 download_cap_exceeded` medido) |
| **R2** (`r2:jorgefelippe`) | 10 GB − 0,5 = **9,5 GB** | **1 milhão Classe A/mês** · **10 milhões Classe B/mês** · saída grátis | developers.cloudflare.com/r2/pricing ("Storage 10 GB-month / month", "Class A Operations 1 million requests / month", "Class B Operations 10 million requests / month", "no charges for egress") |
| **MEGA** (`mega:JFN`) | o `rclone about` (20 GiB = 21,47 GB) − 0,5 = **20,97 GB** | **1 GB/dia** de download (teto NOSSO: o MEGA não publica número para a conta grátis) | mega.io/pricing ("Transfer: Free — Limited") · help.mega.io/plans-storage/space-storage/transfer-quota ("based on the data transferred to your IP address during the last six hours"; "Uploading files uses your storage quota, but not your transfer quota") |

| **TeraBox** (`terabox:JFN`, WebDAV local do OpenList na VM-1) | 1.024 GiB (1.099,5 GB, medido por `size` — o `about` não informa a cota) − 5 = **1.094,5 GB** | **4 GB por arquivo** (teto aplicado, ainda não confirmado) · ~0,65 MB/s | coordenador da sessão, 21/11 (remoto provado por hash); limites do grátis não conferidos em página oficial |

**Remotos grátis ligados em 21/11 (coordenador; todos com prova de sha256; cota pelo `rclone about`):**

| Remoto | Cota grátis | Restrição aplicada pela config | Hash na listagem |
|---|---|---|---|
| `dropbox:JFN` | 102 GiB (Basic) | a raiz tem pastas PESSOAIS do dono — o JFN só escreve em `JFN/` | só o do Dropbox → confere por download |
| `blomp:JFN` | 40 GiB | — | md5 |
| `koofr:JFN` | 10 GiB | `extensoes_proibidas: [".bin"]` — o Koofr recusa baixar `.bin` (aceita `.dat`, `.zst`, `.gz`): não sobe o que não volta | md5 |
| `box:JFN` | 10 GiB | `max_arquivo_gb: 0.25` (250 MB por arquivo) | sha1 |
| `pcloud:JFN` | 4 GiB | — | md5, sha1 |
| `jottacloud:JFN` | 4,66 GiB | `apagar_libera: false` (apagado vai para a lixeira e continua ocupando) | md5 |
| `yandex:` | — | **fora** (`remotos_fora`): 403 até o dono confirmar o telefone | — |

Ordem da 2ª cópia (`segunda_copia`): B2 → R2 → MEGA → Dropbox → Blomp → Koofr → Box → pCloud → Jottacloud →
… → Dosya → MediaFire → Proton → TeraBox (lento, nunca cópia única: sempre o último).

**TeraBox — restrições (21/11):** `so_copia_extra: true` → **nunca cópia única** (o `configurar()` recusa como
principal ou como destino do re-obtível; é o último de `segunda_copia`, só 2ª/3ª cópia) · `max_arquivo_gb: 4`
(o pré-voo recusa arquivo maior) · `apagar_libera: false` (apagado vai para a lixeira: o contador não devolve a
cota) · só a VM-1 alcança (127.0.0.1:5244); na VM-2 ele aparece como inacessível e a vaga segue com os outros.

**Proton e MediaFire (23/11, WebDAV do OpenList na VM-1, penúltimos de `segunda_copia`, antes do TeraBox):**

* **Proton** (`proton:JFN`, 5 GB grátis — proton.me/drive/pricing) · `tamanho_listado_confiavel: false`: a listagem
  dá o tamanho **cifrado** e nenhum hash. Medido em 4 arquivos: 1.000 B → +53, 1 MiB → +56, 5.000.000 B → +116,
  12 MiB → +168 — **não é constante** (cresce por bloco), então não há tolerância de tamanho: o rclone roda com
  `--ignore-size` só nesse remoto (sem isso ele mesmo apaga a cópia boa: "corrupted on transfer: sizes differ") e a
  cópia **só vale conferida por download + md5** (`conferir_copia`; sem download = `sem_hash`, não conta). Gasta um
  download por cópia — o Proton não publica limite de download no grátis.
* **MediaFire** (`mediafire:JFN`): o driver do OpenList só aceita **cookie** (nem e-mail/senha nem token renovável)
  e o `session_token` que ele tira do cookie morre em horas sem se renovar. `tools/zelador/mediafire_sessao.py`
  (cron 04:20, antes do zelador) recarrega o storage com token vazio; se o remoto não listar, faz **login headless**
  (patchright + Chromium em xvfb, e-mail/senha de `~/.config/jfn/nuvens.env`, sem captcha medido em 23/11) e grava o
  cookie novo (`~/.config/jfn/mediafire.cookie`, 0600). Não voltou → escreve `mediafire` em
  `~/.zelador/nuvens_suspensas.json` e o `configurar()` o tira da 2ª cópia até um dia em que volte (sem aviso ao
  Yoda; registro em `data/mediafire_sessao.log`). Se o MediaFire passar a exigir captcha/2FA, o remoto fica suspenso
  sozinho — aí é tirá-lo da config para `remotos_fora`.

\* reserva do B2: `tools/backup_compliance.sh` (domingo 03:50) sobe a 4ª cópia semanal (~1,5 GB) **antes** de girar
para 3. Observação: a página de preços do B2 hoje diz "Class A, B, and C API calls are free for pay-as-you-go"; a
conta do dono está no grátis com teto US$ 0,00 e o Caps & Alerts dela mostra o grátis diário de 1 GB / 2.500 B /
2.500 C — vale o MAIS restritivo.

### 6.2 Como o pré-voo decide (`compliance_agent/armazenamento.py::Orcamento`)

* **Antes de cada chamada do rclone** a um remoto da config: `custo_operacao()` estima o que ela gasta (B2: HEAD,
  download e `get_file_info` = Classe B; `authorize_account` + `list_buckets` + listagem = Classe C, 2 por
  invocação; upload = Classe A, grátis. R2: Put/List/Copy/multipart = Classe A; Get/Head = Classe B; Delete grátis.
  MEGA: só os bytes baixados). Se `gasto do período + custo > limite × partilha da máquina` → **não faz**.
* **Contador local** por remoto e período (dia e mês **UTC** — o B2 zera às 00:00 GMT) em
  `~/.zelador/consumo_nuvens.json` (com trava de arquivo). A chamada que aconteceu conta, mesmo se falhou.
* **Partilha** (as três máquinas falam com a MESMA conta): VM-1 60 %, VM-2 30 %, it-campo 10 % de cada limite
  diário/mensal (`partilha_por_maquina`; somadas nunca passam do grátis — testado).
* **Uso real** medido no remoto no início do processo (`rclone about` no Drive/MEGA; `rclone size` da raiz no
  B2/R2 — conta TUDO do bucket, inclusive `compliance/` e `fachadas/`), somado a cada upload. **Sem medida = não
  sobe** (fechado por padrão).
* **O provedor disse "cap exceeded" / 403** → o remoto fica **esgotado até 00:00 UTC** e nada mais é pedido a ele.
* **Insubstituível**: principal + a 2ª cópia no **primeiro remoto de `segunda_copia` que couber** (B2 → R2 → MEGA → … → TeraBox, ordem da config);
  se o escolhido falhar, o próximo. Nenhum coube → `recusado`, o local fica e o ciclo escala.
* **Resolve antes de escalar** (dono, 21/11: "resolva quando der esse erro"): quem tem alternativa consulta o
  pré-voo **sem** registrar recusa (`Rclone.pode()`, `pode_enviar()`) e só chama o rclone no remoto que cabe —
  a 2ª cópia vai para o próximo remoto; o índice, para o próximo remoto grátis; o `obter()` baixa do próximo
  remoto que tem a cópia; a amostra de recuperação escolhe a menor cópia que cabe no saldo do dia e, se
  nenhuma couber, **adia para o dia seguinte** (`download adiado`; a listagem já provou o hash). Caso que
  originou a regra (ensaio da VM-1, 21/11): amostra do B2 de 39.125.860 B contra saldo de 30.000.000 B —
  reproduzido em `test_caso_do_dono_*` (positivo: escolhe a que cabe; sem saída: adia e NÃO avisa).
* **Recusa sem saída nunca é silenciosa**: vai para `journal` (`recusado` / `recusado_prevoo`), para o relatório
  (`recusas_prevoo`) e para o dono pelo canal de escalados (Telegram do zelador, `🆘 ESCALADO — recusado pelo
  pré-voo`), mesmo num ciclo sem nenhuma outra falha.
* **Recuperação de teste** (`testar_recuperacao`): confere o hash pela **listagem** (`lsjson --hash`, sem baixar)
  de até N cópias por remoto e baixa **uma** amostra (a menor) só se o pré-voo deixar (B2 ≤ 50 MB/dia × partilha).
  Remoto sem hash na listagem (MEGA) só se confere por download — mesmo teto. Download recusado com a listagem ok
  não é falha; hash errado é.

Comandos: `python -m compliance_agent.armazenamento nuvens` (uso × alvo × consumo de cada remoto) ·
`… consolidar-legado [--aplicar]` (re-obtível do R2/B2 → Drive, hash conferido, só então apaga do R2/B2; roda em
cada máquina sobre o prefixo dela, porque o índice dela é quem conhece os pacotes) · `… encher [--aplicar] [--item
nome…]` (ocupa o grátis que sobra nos remotos de `enchimento.remotos`, na ordem de `enchimento.itens`:
insubstituível primeiro — snapshots consistentes dos bancos de trabalho próprio —, depois o re-obtível mais caro;
cada item também no Drive; chave estável por item, o novo substitui o velho).

### 6.3 Uso por nuvem — antes × depois (medido pelo próprio pré-voo)

Uso em GB (10⁹ bytes), medido pelo pré-voo (`rclone about` no Drive e nas cotas de conta; `rclone size` da raiz
no B2/R2, que conta o bucket inteiro). **Antes** = pré-voo de 21/11 19:56 (Drive/B2/R2/MEGA) e, para os remotos
ligados depois, a 1ª medição (ensaio de 21/11 22:57). **Depois** = pré-voo do ciclo real da VM-1, 22/11 05:45.

| Remoto | Antes | Após consolidar (22/11 00:10) | Depois | Alvo grátis | Situação |
|---|---:|---:|---:|---:|---|
| Drive (`gdrive:`) | 10,92 | 29,48 | 39,49 | 424,50 | principal: recebeu todo o re-obtível |
| B2 | **14,19** | 6,09 | 7,13 | 7,80 | era 4,19 acima do limite de 10; agora dentro do alvo |
| R2 | **22,20** | 2,01 | 8,69 | 9,50 | era 12,20 acima; agora dentro do alvo |
| MEGA | 0,00 | — | 0,00 | 20,97 | reserva da 2ª cópia (B2/R2 couberam) |
| Dropbox (`JFN/`) | 0,08 | — | 0,08 | 107,52 | reserva |
| Blomp | 0,00 | — | 0,00 | 41,95 | reserva |
| Koofr | 0,00 | — | 0,00 | 10,24 | reserva |
| Box | 0,02 | — | 0,02 | 10,24 | reserva |
| pCloud | 0,09 | — | 0,09 | 3,99 | reserva |
| Jottacloud | 0,01 | — | 0,01 | 4,70 | reserva |
| TeraBox | 0,00 | — | 0,00 | 1.094,50 | só cópia extra, nunca única |

**O que foi para onde (21–22/11):**

* **Consolidação** (`consolidar-legado --aplicar`, md5 do Drive conferido pela listagem antes de apagar):
  VM-1 — 82 re-obtíveis (8,11 GB) R2+B2 → Drive (80 em 21/11, os 2 que deram timeout em 22/11); VM-2 — 403
  re-obtíveis do prefixo `vm2/` (12,08 GB) R2 → Drive. Nada apagado sem a cópia conferida.
* **Enchimento** (`encher --aplicar`, snapshot consistente + gzip, sempre também no Drive): insubstituível
  primeiro — 14 bancos (3,54 GB .gz; o `compliance.db` de 6,19 GB vira 1,68 GB e vai só ao R2, porque o B2 já guarda os
  semanais do `backup_compliance.sh`); depois o re-obtível mais caro — `receita_estab.db` (1,47 GB) e
  `compliance_analitico.db` (1,67 GB), no R2. B2 recebeu 0,64 GB (o que cabia no alvo), R2 6,68 GB. Sobra
  0,67 GB no B2 e 0,81 GB no R2: nenhum item restante cabe (o pré-voo pulou, sem recusa).
* **Ciclo real da VM-1** (22/11 05:35): 20 unidades guardadas, 0,01 GB liberado + 0,2 GB regenerável, sem falha
  e sem recusa do pré-voo.

Atenção (1): o rclone usa o **cliente OAuth padrão do próprio rclone**, compartilhado no mundo todo (e que o rclone
avisa que será aposentado em 2026); o Drive responde `403 rateLimitExceeded` ("Queries per minute" do projeto
202264815644) e um tar de 80 MB chegou a ficar 10 min em backoff (21/11). Enquanto o dono não criar o cliente próprio
(passo em §9), o destino do re-obtível pode ser trocado por `JFN_DESTINO_REOBTIVEL=r2` (mesma regra de 1 cópia) —
**dentro do alvo grátis do R2**: o pré-voo recusa o que passar de 9,5 GB. O que ainda está no disco volta ao Drive
sozinho no ciclo seguinte; o que já saiu do disco migra R2 → Drive com `consolidar-legado`.

---

## 7. Agendamento

| Máquina | Como | Quando |
|---|---|---|
| VM-1 | crontab (`deploy/zelador/crontab-vm1.txt`) | 1º domingo do mês 04:30 |
| VM-2 | timer do systemd do usuário (`deploy/zelador/zelador-armazenamento.{service,timer}`) | 1º domingo do mês 05:30 |
| it-campo | cron do WSL (`deploy/zelador/crontab-itcampo.txt`), precisa de rclone no WSL | 1º domingo do mês 06:30 |

Primeira rodada de cada máquina: `--ensaio` (grava `~/.zelador/ensaio_ok-<perfil>.json`); sem ele, `--aplicar`
recusa.

---

## 8. O que NÃO é automático (decisão do dono, listado no relatório)

* Bancos parados soltos na home da VM-1 (`ordens_bancarias_salvo.db` 493 MB, `ob_raw.db` 156 MB) e zips antigos
  (`fornecedor_ob.zip.antigo-20260621`, `consulta_cand_2024.zip`): `*.db` nunca sai sozinho.
* Venvs quebrados da VM-2 (`*-py310-quebrado`, 2,7 GB), pilotos (`khoj-piloto`, `ocr-bench`).
* it-campo: `~/JFN-sessoes` (100 GB, s1/s2 rodando), `~/jfn-replica` (22 GB), `~/.cache/uv` (30 GB, os venvs da GPU
  apontam para ele), distribuição `kali-linux` no WSL (vhdx de 186 GB).
* Worktrees integrados (`tools/integracao_conferir.py`) — o zelador só lista.

---

## 9. Passos do dono (uma vez)

1. ~~B2 › Caps & Alerts: subir o teto~~ — **revogado pelo dono em 21/11: o teto fica em US$ 0,00.** Em vez disso
   o pré-voo (§6) não deixa o JFN passar do grátis diário; se o B2 responder 403/cap, o remoto fica esgotado até
   00:00 UTC e a 2ª cópia vai para o próximo remoto grátis.
2. **Cliente OAuth próprio do Drive** (tira o gargalo do cliente compartilhado): console.cloud.google.com → projeto
   novo "jfn-rclone" → APIs e serviços → ativar *Google Drive API* → Tela de consentimento OAuth (Externo, adicionar
   o próprio e-mail como usuário de teste) → Credenciais → *ID do cliente OAuth* → tipo **App para computador** →
   copiar ID e segredo. Depois, num computador com navegador e rclone (o it-campo já tem rclone no WSL; no Windows,
   `rclone.exe`): `rclone authorize "drive" "<ID>" "<SEGREDO>"` → clicar em Permitir → colar o bloco `{...}` que
   aparece. Na VM-1 (o Claude faz): `rclone config update gdrive client_id=<ID> client_secret=<SEGREDO>
   token='<bloco>'` e copia o `rclone.conf` para a VM-2 e o it-campo.
