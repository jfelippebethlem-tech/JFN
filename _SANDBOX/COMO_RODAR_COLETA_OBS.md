# Como Rodar a Coleta de OBs MGS CLEAN no SIAFE

Guia para IAs (Hermes, etc.) e humanos rodarem a coleta de Ordens Bancárias.

---

## O QUE ISSO FAZ

Coleta todas as Ordens Bancárias pagas para o CNPJ **19.088.605/0001-04 (MGS CLEAN)**
nos exercícios 2023, 2024, 2025 e 2026 diretamente do sistema SIAFE-Rio 2.

Resultado: arquivos em `data/sei_cache/`:
- `mgsclean_obs_todas.json` — JSON completo de todas as OBs
- `mgsclean_obs_todas.xlsx` — Excel navegável por ano
- `mgsclean_obs_resumo.md` — Relatório Markdown por mês/ano

---

## PASSO 1 — OBTER CÓDIGO MFA DO SIAFE

O SIAFE exige autenticação de dois fatores por e-mail.

1. Acesse o GitHub Actions: https://github.com/jfelippebethlem-tech/JFN/actions
2. Clique em "Coleta OBs SIAFE (MGS CLEAN 2023-2026)"
3. Clique em "Run workflow" → preencha os campos
4. Execute SEM o código MFA primeiro (deixe o campo vazio)
5. O SIAFE enviará o código para o e-mail cadastrado
6. Pegue o código no e-mail (formato: letras+números, ex: aB3xYz)
7. Execute novamente COM o código MFA no campo correto

---

## PASSO 2 — DISPARAR O WORKFLOW NO GITHUB ACTIONS

### Via API (para IAs usarem):

```bash
# Usando GitHub CLI (gh)
gh workflow run "coletar-obs-siafe.yml" \
  --repo jfelippebethlem-tech/JFN \
  --ref main \
  -f siafe_user=SEU_CPF_SEM_PONTOS \
  -f siafe_pass=SUA_SENHA \
  -f siafe_mfa_code=CODIGO_MFA_DO_EMAIL \
  -f anos=2023,2024,2025,2026
```

### Campos do workflow:
| Campo | Descrição | Obrigatório |
|-------|-----------|-------------|
| `siafe_user` | CPF sem pontos (ex: 14398839712) | SIM |
| `siafe_pass` | Senha do SIAFE | SIM |
| `siafe_mfa_code` | Código MFA recebido por e-mail | SIM (quando solicitado) |
| `anos` | Anos para coletar | Não (padrão: 2023,2024,2025,2026) |
| `telegram_token` | Token do bot Telegram para notificação | Não |
| `telegram_chat` | Chat ID do Telegram | Não |

---

## PASSO 3 — VERIFICAR RESULTADO

Após o workflow completar (~5-15 minutos):

```bash
# Verificar se OBs foram coletadas
git pull origin claude/rj-finance-agent-BYlhJ
python3 -c "
import json
d = json.load(open('data/sei_cache/mgsclean_obs_todas.json'))
print(f'Total OBs: {d[\"total_obs\"]}')
print(f'Valor total: R$ {d[\"total_valor\"]:,.2f}')
"
```

Se `total_obs > 0` → sucesso!

---

## FLUXO DE ERRO — MFA EXPIRADO OU REJEITADO

Se o workflow falhar no login:
1. Abra o arquivo `data/sei_cache/debug_login_2026.txt` no branch
2. Verifique se há "Autenticação Multifator" na saída
3. Peça novo código MFA e rode novamente

---

## FREQUÊNCIA DE COLETA RECOMENDADA

- **Mensal**: dados do mês corrente (execução rápida)
- **Trimestral**: coleta completa 2023-2026 (arquiva historico)
- **Antes de auditorias**: sempre rodar coleta completa

---

## ARQUIVOS GERADOS E ONDE ESTÃO

```
data/sei_cache/
├── mgsclean_obs_todas.json     # JSON principal (todos os anos)
├── mgsclean_obs_todas.xlsx     # Excel navegável (aba por ano)
├── mgsclean_obs_resumo.md      # Resumo por mês/ano
├── mgsclean_obs_2026.json      # JSON por ano separado
├── mgsclean_obs_2025.json
├── mgsclean_obs_2024.json
├── mgsclean_obs_2023.json
└── debug_login_*.txt           # Diagnóstico de login (se falhou)

data/compliance.db              # Banco SQLite com OBs reais (categoria: mgs_clean_real)
```

---

## ESTRUTURA DO JSON DE CADA OB

```json
{
  "numero_ob": "2026OB000123",
  "data_emissao": "15/03/2026",
  "ug_emitente": "270013",
  "favorecido_cnpj": "19088605000104",
  "favorecido_nome": "MGS CLEAN SOLUCOES E SERVICOS LTDA",
  "valor": 45230.00,
  "tipo_ob": "OBK",
  "status": "Paga",
  "processo": "E-04/...",
  "ano": 2026,
  "mes": 3
}
```

---

## PARA IAs (HERMES) — ROTINA AUTOMÁTICA

```python
# Pseudocódigo para IA rodar a coleta
import subprocess, json, time

# 1. Disparar workflow (substitua os valores)
subprocess.run([
    "gh", "workflow", "run", "coletar-obs-siafe.yml",
    "--repo", "jfelippebethlem-tech/JFN",
    "--ref", "main",
    "-f", "siafe_user=CPF_AQUI",
    "-f", "siafe_pass=SENHA_AQUI",
    "-f", "siafe_mfa_code=CODIGO_MFA_AQUI",
])

# 2. Aguardar (~10 minutos)
time.sleep(600)

# 3. Puxar resultados
subprocess.run(["git", "pull", "origin", "claude/rj-finance-agent-BYlhJ"])

# 4. Verificar
with open("data/sei_cache/mgsclean_obs_todas.json") as f:
    d = json.load(f)
    print(f"OBs coletadas: {d['total_obs']}")
```

---

## BRANCH CORRETO

Sempre use o branch: **`claude/rj-finance-agent-BYlhJ`**

O código do coletor fica em: `_SANDBOX/coletar_obs_agora.py`
