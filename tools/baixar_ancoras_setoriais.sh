#!/usr/bin/env bash
# Download DOCUMENTADO dos dumps de âncora setorial (Task 1.4) → data/cnes.db e data/antt.db.
#
# ⚠ NÃO roda em CI/testes — operação manual/agendada (dumps de centenas de MB; VM 2 vCPU).
#   A lógica (compliance_agent/enriquecimento/ancora_setorial.py) degrada HONESTA sem os dumps:
#   presente=None (INDISPONÍVEL), nunca False sem dado.
#
# Fontes (dados abertos):
#   CNES  — Estabelecimentos de saúde: https://dadosabertos.saude.gov.br/dataset/cnes-cadastro-nacional-de-estabelecimentos-de-saude
#           (CSV mensal "cnes_estabelecimentos"; alternativa: ftp.datasus.gov.br/cnes/BASE_DE_DADOS_CNES_AAAAMM.ZIP)
#   RNTRC — Transportadores ANTT: https://dados.antt.gov.br/dataset/rntrc-registro-nacional-de-transportadores-rodoviarios-de-cargas
#           (CSV "transportadores"; atualização periódica)
#
# Saída sqlite (colunas mínimas que a âncora consulta): cnpj TEXT, nome TEXT, municipio TEXT, uf TEXT
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data

# ── CNES → data/cnes.db (tabela cnes_estabelecimentos) ──────────────────────
# Ajustar a URL p/ o recorte mensal vigente no portal (o nome do arquivo muda com a competência).
CNES_CSV_URL="${CNES_CSV_URL:-https://dadosabertos.saude.gov.br/dataset/cnes-cadastro-nacional-de-estabelecimentos-de-saude/resource/cnes_estabelecimentos.csv}"
curl -fL --retry 3 -o data/cnes_estabelecimentos.csv "$CNES_CSV_URL"

.venv/bin/python - <<'PY'
import csv, sqlite3, re
conn = sqlite3.connect("data/cnes.db")
conn.execute("DROP TABLE IF EXISTS cnes_estabelecimentos")
conn.execute("CREATE TABLE cnes_estabelecimentos (cnpj TEXT, nome TEXT, municipio TEXT, uf TEXT)")
with open("data/cnes_estabelecimentos.csv", encoding="latin-1", newline="") as f:
    r = csv.DictReader(f, delimiter=";")
    rows = []
    for lin in r:
        # nomes de coluna do layout CNES (checar no CSV baixado; variam por competência)
        cnpj = re.sub(r"\D", "", lin.get("CO_CNPJ") or lin.get("NU_CNPJ") or "")
        if len(cnpj) != 14:
            continue
        rows.append((cnpj, lin.get("NO_FANTASIA") or lin.get("NO_RAZAO_SOCIAL") or "",
                     lin.get("CO_MUNICIPIO") or "", lin.get("CO_SIGLA_ESTADO") or lin.get("UF") or ""))
conn.executemany("INSERT INTO cnes_estabelecimentos VALUES (?,?,?,?)", rows)
conn.execute("CREATE INDEX ix_cnes_cnpj ON cnes_estabelecimentos(cnpj)")
conn.commit(); conn.close()
print(f"cnes.db: {len(rows)} estabelecimentos")
PY
rm -f data/cnes_estabelecimentos.csv

# ── RNTRC (ANTT) → data/antt.db (tabela antt_transportadores) ───────────────
RNTRC_CSV_URL="${RNTRC_CSV_URL:-https://dados.antt.gov.br/dataset/rntrc-registro-nacional-de-transportadores-rodoviarios-de-cargas/resource/transportadores.csv}"
curl -fL --retry 3 -o data/antt_transportadores.csv "$RNTRC_CSV_URL"

.venv/bin/python - <<'PY'
import csv, sqlite3, re
conn = sqlite3.connect("data/antt.db")
conn.execute("DROP TABLE IF EXISTS antt_transportadores")
conn.execute("CREATE TABLE antt_transportadores (cnpj TEXT, nome TEXT, municipio TEXT, uf TEXT)")
with open("data/antt_transportadores.csv", encoding="latin-1", newline="") as f:
    r = csv.DictReader(f, delimiter=";")
    rows = []
    for lin in r:
        cnpj = re.sub(r"\D", "", lin.get("CNPJ") or lin.get("NR_DOCUMENTO") or "")
        if len(cnpj) != 14:  # só PJ (ETC/CTC); TAC (CPF) fora do escopo da âncora
            continue
        rows.append((cnpj, lin.get("RAZAO_SOCIAL") or lin.get("NOME") or "",
                     lin.get("MUNICIPIO") or "", lin.get("UF") or ""))
conn.executemany("INSERT INTO antt_transportadores VALUES (?,?,?,?)", rows)
conn.execute("CREATE INDEX ix_antt_cnpj ON antt_transportadores(cnpj)")
conn.commit(); conn.close()
print(f"antt.db: {len(rows)} transportadores PJ")
PY
rm -f data/antt_transportadores.csv

echo "OK — dumps de âncora setorial em data/cnes.db e data/antt.db"
