# Módulo: Relatório de Riscos Corporativos

> **Destinado a revisão independente por outra IA.**
> Este módulo está isolado do código principal do repositório JFN.

---

## O que é este módulo

Gerador automático de relatórios de due diligence e risco corporativo para empresas brasileiras,
inspirado no relatório LiciNexus que analisou a **CASHPAGO SOLUCOES LTDA** (CNPJ 28.584.601/0001-08).

O módulo coleta dados de múltiplas APIs públicas gratuitas, analisa sinais de risco e gera
relatórios estruturados em Markdown/texto, úteis para:

- Compliance e due diligence em processos licitatórios
- Análise de fornecedores e parceiros comerciais
- Investigação jornalística ou acadêmica sobre empresas públicas
- Monitoramento de integridade de entidades contratadas pelo setor público

---

## Estrutura de arquivos

```
relatorio_riscos/
├── __init__.py                         # Exporta gerar_relatorio_risco()
├── main.py                             # Entry point principal (orquestra tudo)
├── README_PARA_IA.md                   # Este arquivo
│
├── collectors/                         # Coletores de dados externos
│   ├── __init__.py
│   ├── cnpj_receita.py                 # Dados da Receita Federal (BrasilAPI + ReceitaWS)
│   ├── contratos_pncp.py               # Contratos públicos (PNCP)
│   ├── sancoes.py                      # Sanções federais (CEIS/CNEP/CEPIM)
│   └── whois_br.py                     # WHOIS de domínios .br (Registro.br RDAP)
│
├── analise/                            # Módulos de análise
│   ├── __init__.py
│   ├── rede_societaria.py              # Expansão e análise da rede de sócios
│   └── sinais_risco.py                 # Detecção e classificação de sinais de risco
│
└── relatorio/                          # Geração de output
    ├── __init__.py
    └── gerador.py                      # Formata Markdown / TXT / salva arquivo
```

---

## Como usar

```python
import asyncio
from relatorio_riscos import gerar_relatorio_risco

# Uso básico
resultado = asyncio.run(gerar_relatorio_risco("28.584.601/0001-08"))

print(resultado["risco"])           # "ALTO" / "MÉDIO" / "BAIXO"
print(resultado["empresa"])         # "CASHPAGO SOLUCOES LTDA"
print(resultado["score"])           # 0-100
print(resultado["relatorio_path"])  # /home/user/JFN/reports/risco_28584601000108_2026-06-04.md

# Com CNPJs adicionais para expandir rede societária
resultado = asyncio.run(gerar_relatorio_risco(
    "28.584.601/0001-08",
    cnpjs_adicionais=["12.345.678/0001-99", "98.765.432/0001-11"],
    formato="md",
))

# Apenas dados brutos sem salvar arquivo
resultado = asyncio.run(gerar_relatorio_risco(
    "28.584.601/0001-08",
    formato="json",
    salvar=False,
))
dados = resultado["dados"]          # dict com empresa/rede/contratos/sancoes/sinais/whois
```

---

## Fontes de dados utilizadas

| Fonte | URL Base | Auth | Uso |
|---|---|---|---|
| BrasilAPI | `https://brasilapi.com.br/api/cnpj/v1/` | Nenhuma | Dados da Receita Federal |
| ReceitaWS | `https://www.receitaws.com.br/v1/cnpj/` | Nenhuma | Fallback da Receita Federal |
| PNCP | `https://pncp.gov.br/api/consulta/v1/contratos` | Nenhuma | Contratos públicos federais |
| Portal da Transparência | `https://api.portaldatransparencia.gov.br/api-de-dados/` | `TRANSPARENCIA_API_KEY` (env) | Sanções CEIS/CNEP/CEPIM |
| Registro.br RDAP | `https://rdap.registro.br/domain/` | Nenhuma | WHOIS de domínios .br |

**Variáveis de ambiente necessárias:**
- `TRANSPARENCIA_API_KEY` — chave gratuita obtida em https://portaldatransparencia.gov.br/api-de-dados/cadastrar-email
  (se ausente, a verificação de sanções é pulada graciosamente)

---

## Sinais de risco detectados

### Nível ALTO
| Código | Descrição | Lógica |
|---|---|---|
| CONTRATO_SIMBOLICO | Contrato simbólico (possível remuneração oculta) | Valor ≤ R$ 0,01 |
| INEXIGIBILIDADE | Contratação por inexigibilidade detectada | Modalidade = INEXIGIBILIDADE |
| CAPITAL_DESPROPORCIONAL | Capital social desproporcional ao porte | Capital ≥ R$ 5M em micro/pequena |
| EMPRESA_JOVEM_VULTOSO | Empresa jovem com contratos vultosos | Empresa < 2 anos + contrato ≥ R$ 1M |
| SANCAO_ATIVA | Sanções identificadas nos cadastros federais | n_sancoes > 0 |

### Nível MÉDIO
| Código | Descrição | Lógica |
|---|---|---|
| REDE_BAIXADAS | Alto índice de empresas encerradas | ≥ 40% da rede baixada/inapta |
| EMAIL_GENERICO | Email administrativo não-corporativo | gmail/hotmail/etc. como contato fiscal |
| CONCENTRACAO_ENDERECO | Concentração de empresas no mesmo endereço | ≥ 3 CNPJs no mesmo endereço |
| SA_CAPITAL_ZERO | S/A com capital zero (irregular) | Natureza S/A + capital = R$ 0 |

### Nível BAIXO
| Código | Descrição | Lógica |
|---|---|---|
| ESTRUTURA_HOLDING | Estrutura holding identificada | Natureza jurídica contém "HOLDING" |
| SOCIO_CONCENTRADO | Sócio com alta concentração societária | Sócio em ≥ 5 empresas |

---

## Implementado — soluções gratuitas

### 1. Dump da Receita Federal → busca reversa por nome de sócio

**Arquivo:** `collectors/cnpj_dump_rf.py`

A Receita Federal disponibiliza gratuitamente todos os dados do CNPJ em:
`https://dadosabertos.rfb.gov.br/CNPJ/dados_abertos_cnpj/YYYY-MM/`

Arquivos relevantes: `Socios0.zip` … `Socios9.zip` (~10 GB expandidos, ~1 GB comprimidos)

```python
from relatorio_riscos.collectors.cnpj_dump_rf import baixar_e_indexar, buscar_empresas_por_nome_socio

# 1. Indexar uma vez por mês (cria SQLite em data/cnpj_socios.db)
asyncio.run(baixar_e_indexar())  # ~10 min na primeira vez

# 2. Busca reversa por nome do sócio (offline, instantânea)
empresas = buscar_empresas_por_nome_socio("EDUARDO DA SILVA AZEVEDO")
# → [{"cnpj_base": "19088605", "nome": "EDUARDO...", "qualificacao": "..."}]

# 3. Busca por fragmento de CPF mascarado
empresas = buscar_empresas_por_cpf_parcial("67759")
```

> **Limitação:** Os CPFs no dump da RF vêm mascarados (`***XXX.XX**`). Busca exata de CPF não é
> possível, mas busca por nome completo permite expansão da rede de 3 graus.

---

### 2. Paginação completa de contratos PNCP

**Arquivo:** `collectors/contratos_pncp.py` — parâmetro `todas_paginas=True` (padrão)

Agora busca todas as páginas automaticamente via `asyncio.gather` em lotes de 10, limitando
sobrecarga na API. Empresas com centenas de contratos recebem dados completos.

---

### 3. Cache SQLite com TTL

**Arquivo:** `collectors/cache.py`

```python
from relatorio_riscos.collectors.cache import cached, get, set

# Usar decorator:
@cached("cnpj", ttl=86400)  # 24 horas
async def buscar_cnpj(cnpj: str) -> dict:
    ...

# Ou usar direto:
resultado = get("cnpj", "19088605000104")
set("cnpj", dados, "19088605000104", ttl=3600)
```

Cache armazenado em `data/coleta_cache.db`. Entradas expiradas são limpas automaticamente
a cada chamada de `gerar_relatorio_risco()`.

---

### 4. Relatório em PDF (fpdf2)

**Arquivo:** `relatorio/pdf.py`

```python
# Instalar: pip install fpdf2
resultado = asyncio.run(gerar_relatorio_risco("19088605000104", formato="pdf"))
print(resultado["relatorio_path"])  # reports/risco_19088605000104_2026-06-04.pdf
```

Gera PDF com: cabeçalho colorido por nível de risco, dados cadastrais, tabela de contratos,
status de sanções, lista de sinais classificados.

---

## O que ainda falta (sem solução gratuita fácil)

1. **Busca reversa por CPF completo** — CPFs no dump RF são mascarados por design. Para desmascarar
   seria necessário acesso à base da Receita via Serpro (pago) ou cruzamento com outras bases.

2. **Análise automática de endereço** — Requer download adicional do dump de Estabelecimentos (~5GB)
   e indexação por logradouro/CEP.

3. **Monitoramento contínuo** — Adicionar integração com `APScheduler` ou `cron` é responsabilidade
   do chamador.

4. **CNEP e CEPIM por CPF de sócios** — A API do Portal da Transparência aceita busca por CPF
   (endpoint `/ceis?cpfCnpjSancionado=`), mas requer `TRANSPARENCIA_API_KEY`.

---

## Referência ao relatório LiciNexus

Este módulo foi modelado com base no relatório gerado pela plataforma **LiciNexus** para a empresa
**CASHPAGO SOLUCOES LTDA** (CNPJ 28.584.601/0001-08), que cobriu:

1. Dados cadastrais da Receita Federal
2. Rede de empresas vinculadas por sócios comuns (3 graus)
3. Pessoas-chave (sócios com ≥ 2 empresas)
4. Contratos públicos no PNCP (ao vivo)
5. Sanções CEIS/CNEP/CEPIM
6. Sinais de risco classificados ALTO/MÉDIO/BAIXO
7. Evidência digital (domínios WHOIS .br)
8. Conclusões e recomendações

Os sinais detectados para a CASHPAGO incluíam: contratação por inexigibilidade, capital social
desproporcional, e domínio registrado com e-mail genérico (gmail).

---

## Decisões técnicas

- **httpx (assíncrono)**: todas as chamadas HTTP usam `httpx.AsyncClient`; o módulo não bloqueia.
- **asyncio.gather**: coletores paralelos para minimizar latência total.
- **Graceful degradation**: cada coletor retorna `{"ok": False, "erro": "..."}` em caso de falha,
  sem propagar exceções para o chamador.
- **CPF mascarado**: apenas 3 primeiros e 2 últimos dígitos visíveis para preservar privacidade.
- **Sem chaves hard-coded**: todas as credenciais via `os.environ.get(...)`.

---

## Testes

```bash
# Rodar os testes offline (sem chamadas reais de API):
cd /home/user/JFN
python -m pytest tests/test_relatorio_riscos.py -v
```

Os testes usam `unittest.mock.patch` para simular respostas das APIs.
