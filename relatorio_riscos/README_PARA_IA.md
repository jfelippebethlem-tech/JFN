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

## O que falta implementar

1. **Busca reversa por CPF/sócio** — nenhuma API pública gratuita brasileira oferece busca de empresas
   por CPF do sócio. Para expansão automática da rede, seria necessário:
   - API privada (ex: Serpro DataValid, Receita Web Service)
   - Scraping do portal Receita Federal (risco de bloqueio)
   - Base local com dump do CNPJ (disponível via dados.gov.br — arquivos pesados)

2. **Análise de múltiplos endereços** — o sinal de concentração de endereço só funciona com
   CNPJs adicionais fornecidos manualmente.

3. **Monitoramento contínuo** — sem scheduler; executar periodicamente é responsabilidade do chamador.

4. **Cache de resultados** — cada chamada consulta as APIs ao vivo; sem TTL ou banco local.

5. **CNEP e CEPIM por CPF** — o módulo `sancoes.py` consulta por CNPJ; pessoas físicas (sócios)
   não são verificadas individualmente.

6. **Relatório em PDF** — apenas Markdown e TXT gerados; converter para PDF requer `fpdf2` ou `weasyprint`.

7. **Paginação completa de contratos** — busca apenas a primeira página (20 contratos padrão);
   empresas com muitos contratos podem ter dados incompletos.

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
