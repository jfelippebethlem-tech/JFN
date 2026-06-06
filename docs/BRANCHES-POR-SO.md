# Branches por Sistema Operacional — guia para IAs futuras

> Decisão do Mestre Jorge (2026-06-06): **separar o repositório por sistema operacional**, com **uma branch
> para cada alvo**. A VM usa a branch `linux` por padrão. Merges entre SOs são **seletivos** (cherry-pick do
> que for cabível), não merges cegos.

## As três branches

| Branch | Alvo | Contém (além do compartilhado) | NÃO contém |
|---|---|---|---|
| **`linux`** ⭐ | A VM Ubuntu (GCP) — **default de trabalho aqui** | `*.sh`, `deploy/systemd/*.service`+`*.timer`, `start_linux.sh`, `iniciar.sh`, `setup_oracle_cloud.sh`, `_SANDBOX/gcp/*.sh` | scripts Windows (`.bat/.cmd/.ps1`), `.github/workflows/` |
| **`windows`** | PC Windows do Mestre Jorge (ambiente legado) | `*.bat`, `*.cmd`, `*.ps1` (HERMES.bat, JFN.bat, `_PROTEGIDO/scripts/`, `hermes-yoda/scripts/`) | infra Linux (`*.sh`, `deploy/systemd/`), `.github/workflows/` |
| **`gitactions`** | CI no GitHub (runner Ubuntu) | `.github/workflows/` (coletar-obs-siafe.yml) | scripts Windows, infra systemd/`.sh` |

**Compartilhado entre TODAS as branches** (não pertence a nenhum SO): todo o código Python dos agentes
(`compliance_agent/`, `relatorio_riscos/`, `massare/`, `siafe_agent/`, `server.py`, `lex.py`…), os documentos
(`docs/`, `CLAUDE.md`, `AMBIENTE.md`), os dados (`data/`, bancos SQLite) e os schemas.

## Regra para a IA que trabalha NESTA VM

1. **Trabalhe sempre na branch `linux`.** É a que está em checkout aqui. Confirme com `git rev-parse --abbrev-ref HEAD` → deve ser `linux`.
2. **Mudança de código de agente / doc / dado (compartilhado):** commite na `linux` e, se for cabível a outro
   SO, faça `git cherry-pick <sha>` para `windows`/`gitactions`.
3. **Mudança de infra Linux** (`.sh`, systemd): só na `linux`.
4. **Nunca** traga `.bat/.cmd/.ps1` nem `.github/workflows/` de volta para a `linux` (foi removido de propósito).
5. A branch histórica `claude/ambiente-e-relatorio` é a **base** de onde as três saíram (mesmo HEAD). A
   `claude/rj-finance-agent-BYlhJ` era a canônica antiga.

## Por que (storage e clareza)

- **Clareza:** a VM não carrega mais scripts de um SO que não roda aqui; menos confusão para a próxima IA.
- **Storage:** a separação em si **quase não libera disco** — o Git deduplica objetos entre branches (o
  `.git/` é compartilhado). O working tree da `linux` perde só os ~35 scripts Windows (poucos KB). O peso real
  do disco é `data/` (~969 MB, bancos SQLite legítimos do Linux) e `node_modules/` (~29 MB, **versionado por
  engano** — candidato a `git rm --cached` + `.gitignore`; ver `docs/STORAGE.md`).

## Pendências conhecidas

- `node_modules/` está **versionado** (2.195 arquivos). Não é de nenhum SO (é dependência JS do Playwright/
  puppeteer). Deveria sair do git (`git rm -r --cached node_modules && echo node_modules/ >> .gitignore`).
  Não foi removido automaticamente para não reescrever história sem combinar.
