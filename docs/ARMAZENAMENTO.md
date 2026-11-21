# ARMAZENAMENTO DO JFN — camadas, política, índice e zeladores

> **Pedido do dono (21/11/2026):** "monta uma arquitetura que use o r2 e b2, drive, it campo e tenhamos
> detectores semanais […] pra liberar storage" · "mantendo tudo disponível pra vm1 e 2, mesmo que o it campo esteja
> desligado" · "vamos usar e ensinar todos a usarem os armazenamentos em cloud" · "tem que indexar tudo e organizar
> pra todos saberem" · "duas cópias na nuvem? assim gasta o dobro" · "automatize isso sem margem pra erro".
>
> **Código:** `compliance_agent/armazenamento.py` (porta única + índice) · `tools/zelador/zelador.py` (ciclo
> semanal, um perfil por máquina) · testes `tests/test_armazenamento_zelador.py` (controle positivo e negativo de
> cada trava).

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
| **Frio** | **Google Drive** pasta `JFN/` (cota 400 GiB da conta do dono) + **B2** `jfn-backup-jorge` | tudo o que não é lido no dia a dia; backups | zelador semanal, com índice |
| **Serviço** | R2 `jorgefelippe` (`fachadas/`, `anexos/`) | arquivos servidos por URL (saída sem custo) | quem publica |
| **Cache/processamento** | it-campo (GPU, OCR, réplicas de sessão) | nada que as VMs precisem; pode desligar sem perda | — |

**Pasta do Drive** (`gdrive:` no rclone = pasta `JFN`, `root_folder_id` no `rclone.conf`):
`frio/<maquina>/<caminho relativo a ~>` · `indice/<maquina>.db` · `backups/` · `relatorios/` · `artes/`.

---

## 3. Política por natureza do arquivo

| Natureza | Classes | Cópias | Destino(s) | Por quê |
|---|---|---|---|---|
| **Re-obtível** (a fonte pública tem) | `sei_pdf`, `sei_foto`, `sei_cache`, `sei_arvore`, `quarentena`, `substituido`, `tse`, `pncp`, `receita`, `coleta_cache` | **1** | Drive | o provedor já replica internamente; perder = baixar de novo da fonte (índice guarda origem e hash) |
| **Insubstituível** (trabalho próprio) | `backup_db`, `trabalho`, `sessao_claude`, `indice`, `relatorio`, `midia` | **2, provedores diferentes** | Drive + B2 | falha de UM provedor (conta, cobrança, exclusão) não pode levar a única cópia |

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

## 5. Zelador semanal — o ciclo e as travas

`python tools/zelador/zelador.py --perfil {vm1|vm2|itcampo} {--ensaio|--aplicar} [--teto-gb N]`

1. **Pré-voo** — rclone responde em cada destino exigido; montagens do perfil presentes (VM-1: sshfs do it-campo;
   it-campo: `/mnt/c`); ≥ 5 GB para empacotar. Falhou → aborta.
2. **Recuperação** — baixa uma amostra (2 por destino) do que já está na nuvem e confere o md5. Falhou → aborta.
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

## 6. Custo mensal (tabelas oficiais lidas em 21/11/2026)

| Provedor | Preço | Grátis | Saída | Fonte |
|---|---|---|---|---|
| Cloudflare R2 Standard | US$ 0,015/GB-mês | 10 GB-mês, 1 mi Classe A, 10 mi Classe B | grátis | developers.cloudflare.com/r2/pricing |
| Backblaze B2 | US$ 6,95/TB-mês (US$ 0,00695/GB) | 10 GB | grátis até 3× o armazenado; depois US$ 0,01/GB | backblaze.com/cloud-storage/pricing |
| Google Drive (Google One) | plano já contratado pelo dono (cota medida: 400 GiB) | 15 GB em qualquer conta | — | one.google.com/about/plans (a página lida listou 100 GB = R$ 9,99/mês; o plano de 400 GiB não aparece) |

| Cenário | R2 | B2 | Drive | Total incremental |
|---|---|---|---|---|
| **Antes** (21/11, medido): `frio/` duplicado em R2 e B2 | 13,23 GB → US$ 0,06 | 17,30 GB → US$ 0,05 | 3,53 GB | **≈ US$ 0,11/mês** |
| **Depois** (frio ~200 GB no Drive; insubstituível ~9 GB em Drive+B2; R2 só serviço) | < 10 GB → US$ 0,00 | < 10 GB → US$ 0,00 | ~210 GB de 400 GiB | **≈ US$ 0,00/mês** |
| Se o Drive encher: o excedente re-obtível vai para o B2 | — | US$ 1,39 por 200 GB | — | |
| (comparação: os mesmos 200 GB no R2) | US$ 2,85 | — | — | |

Atenção (1): o rclone usa o **cliente OAuth padrão do próprio rclone**, compartilhado no mundo todo; o Drive responde
`403 rateLimitExceeded` ("Queries per minute" do projeto 202264815644) e um tar de 80 MB chegou a ficar 10 min em
backoff (21/11). Enquanto o dono não criar o cliente próprio (passo em §9), o destino do re-obtível pode ser trocado
por `JFN_DESTINO_REOBTIVEL=r2` (mesma regra de 1 cópia; US$ 0,015/GB, saída grátis) — foi o que a VM-2 usou em 21/11
a 98% de disco. O que ainda está no disco volta ao Drive sozinho no ciclo seguinte (a reconferência não acha a cópia
no Drive e reenvia); o que já saiu do disco migra R2 → Drive com `consolidar-legado`.

Atenção (2): o B2 tem **teto diário de Classe B/download** configurado na conta (21/11: `403 download_cap_exceeded`
ao copiar B2 → Drive). Enquanto o teto estiver no mínimo, restaurar do B2 falha — o zelador testa a recuperação
de cada destino e AVISA. Ajuste em B2 › Caps & Alerts (passo do dono).

---

## 7. Agendamento

| Máquina | Como | Quando |
|---|---|---|
| VM-1 | crontab (`deploy/zelador/crontab-vm1.txt`) | domingo 04:30 |
| VM-2 | timer do systemd do usuário (`deploy/zelador/zelador-armazenamento.{service,timer}`) | domingo 05:30 |
| it-campo | cron do WSL (`deploy/zelador/crontab-itcampo.txt`), precisa de rclone no WSL | domingo 06:30 |

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

1. **B2 › Caps & Alerts**: subir o teto diário de *Download Bandwidth* e de *Class B Transactions* (ex.: US$ 1/dia
   cada). Com o teto atual, HEAD e download do B2 dão 403 — a recuperação de teste falha e o zelador ABORTA (correto:
   cópia que não volta não é cópia). Medido em 21/11: `403 download_cap_exceeded`.
2. **Cliente OAuth próprio do Drive** (tira o gargalo do cliente compartilhado): console.cloud.google.com → projeto
   novo "jfn-rclone" → APIs e serviços → ativar *Google Drive API* → Tela de consentimento OAuth (Externo, adicionar
   o próprio e-mail como usuário de teste) → Credenciais → *ID do cliente OAuth* → tipo **App para computador** →
   copiar ID e segredo. Depois, num computador com navegador e rclone (o it-campo já tem rclone no WSL; no Windows,
   `rclone.exe`): `rclone authorize "drive" "<ID>" "<SEGREDO>"` → clicar em Permitir → colar o bloco `{...}` que
   aparece. Na VM-1 (o Claude faz): `rclone config update gdrive client_id=<ID> client_secret=<SEGREDO>
   token='<bloco>'` e copia o `rclone.conf` para a VM-2 e o it-campo.
