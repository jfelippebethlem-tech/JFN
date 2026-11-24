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
- Exportação de dossiê registrada (quem, quando, hash).

## Backup, restauração, retenção e criptografia (O8.2, 24/11/2026)

Regra 3-2-1-1-0 (plano mestre v2 §14): 3 cópias, 2 meios, 1 fora da máquina, 1 offline (HD do it-campo, camada
morna) e **0 erro na restauração conferida**. Backup sem restauração medida não conta.

### RPO/RTO por classe

| Classe | O que é | RPO alvo | RTO alvo | Hoje (medido em 24/11/2026) |
|---|---|---|---|---|
| Metadados | PG `jfn_evidencias` (public, dominio, fluxo) e `compliance.db` | 24 h | 4 h | PG: dump diário às 02:40, então RPO de 24 h. `compliance.db`: backup **semanal**, então RPO real de **7 dias** (lacuna). RTO medido no it-campo: pg_restore de 155 MB em 15,3 s, cópia + quick_check de 6,4 GB em 79,9 s, mais o transporte |
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

### WAL-G (arquivamento contínuo): INDISPONÍVEL

Não está ligado. Em 24/11/2026 nenhum remoto S3 de `config/armazenamento_nuvens.json` comprovou ser grátis para uma
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

- **Retenção.** Diário do PG: os 7 últimos e 4 semanais. `compliance.db`: os 3 semanais de hoje. Snapshot no HD:
  4 semanais e 1 mensal por 12 meses. Nada sai da rotação sem uma cópia mais nova conferida por hash.
- **Criptografia (`age`).** Todo backup que sai para a nuvem sai cifrado. A chave pública fica no repo, porque não
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
