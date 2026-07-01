# Núcleo de Inteligência Progressiva (NIP)

> A resposta de engenharia para o problema real do JFN: **fazer a perícia ser
> super inteligente mesmo usando IAs fracas (grátis) para ler e parametrizar.**

## O problema que este módulo resolve

O JFN já tinha uma base jurídica excelente (`knowledge/fraudes_licitacao.py`:
18 padrões de fraude com fundamento legal). Mas a inteligência estava presa em
dois gargalos:

1. Os `como_detectar` de cada fraude eram **prosa**, não código. Alguém — na
   prática, uma IA fraca — precisava ler a prosa, olhar os dados e *decidir* se
   batia. Modelo fraco erra isso o tempo todo.
2. Os **limiares** (o que é "empresa nova", "sobrepreço", "aditivo excessivo")
   estavam espalhados, hardcoded ou implícitos no prompt. Calibrar era
   reescrever prompt — não-auditável e inconsistente.

Resultado: a IA fraca era usada como *perito*, papel para o qual ela é ruim.

## A virada: inverter o papel da IA

```
      Documento / dados brutos
              │
              ▼   IA FRACA (só aqui, e blindada)  ── extrai campos factuais
      Dossiê normalizado + VALIDADO por código (CNPJ, datas, R$)
              │
              ▼   100% DETERMINÍSTICO — sem IA
      Indicadores executáveis  →  Score (matriz TCU)  →  Laudo citado
```

A IA fraca faz só o que faz bem: **ler texto e devolver campos**. E mesmo isso
passa por validação determinística (dígito verificador de CNPJ, parsing de datas
e valores, votação por autoconsistência). Toda a *perícia* — aplicar as regras,
medir contra os limites legais, pontuar o risco, citar a lei — é código
reproduzível. O laudo é oponível num ofício ao TCE-RJ ou requerimento de CPI.

## Peças

| Arquivo | Papel |
|---|---|
| `parametros.py` | Store central de limiares, cada um com **fundamento legal** e faixa sã. É a "parametrização" explícita e calibrável. Limites de fonte legal ficam travados. |
| `dossie.py` | Esquema de evidências + **validadores determinísticos** (CNPJ, CPF, datas, reais). A fronteira blindada contra lixo de IA fraca. |
| `indicadores.py` | Os `como_detectar` viram **funções puras** que devolvem um `Achado` citado (valor observado, limite aplicado, base legal, confiança). |
| `scoring.py` | Agrega achados na **matriz TCU Probabilidade×Impacto** → rating defensável. |
| `extracao_robusta.py` | Extração confiável com modelo fraco: schema estrito + reparo de JSON + **votação por autoconsistência** + validação. |
| `aprendizado.py` | **Inteligência progressiva**: registra feedback do perito, mede precisão por indicador e sugere calibração de parâmetros. |
| `nucleo.py` | Orquestrador: `periciar(...) → Laudo` (com `.texto()` e `.para_dict()`). |

## Uso

### Perícia 100% determinística (sem IA), sobre dados dos collectors

```python
from compliance_agent.nucleo.nucleo import periciar

laudo = periciar(
    contratacao={"valor": 18_500_000, "data": "2024-05-20", "modalidade": "dispensa",
                 "categoria": "saúde", "propostas_validas": 1,
                 "aditivos_valor": 6_000_000, "aditivos_qtd": 2},
    fornecedor={"cnpj": "11.222.333/0001-81", "data_abertura": "2024-02-01",
                "capital_social": 10_000},
    referencia_categoria={"mediana": 4_000_000, "desvio_padrao": 1_500_000,
                          "referencia_mercado": 5_000_000},
)
print(laudo.texto())          # laudo citado, pronto para ofício
laudo.para_dict()             # JSON para API/painel
```

### Com IA fraca preenchendo campos de um edital (blindada)

```python
from compliance_agent.llm.free_llm import best_free_chat

laudo = periciar(
    contratacao={"data": "2024-05-20", "categoria": "obras"},
    fornecedor={"data_abertura": "2024-05-15", "capital_social": 1000},
    documento_edital=texto_do_edital,
    llm_fn=lambda prompt, system: best_free_chat(prompt, system=system),
)
```

A IA só entrega `valor`, `cnpj`, `modalidade`… — e cada campo é validado antes
de entrar no dossiê. Se a IA cair (429, timeout), a perícia continua com o que
veio dos dados estruturados.

### Aprendizado progressivo

```python
from compliance_agent.nucleo import aprendizado

# Perito marca o resultado de um achado:
aprendizado.registrar_feedback("IND-DIR-01", "descartado", referencia="OB 2024NE00123")

# Ver quais indicadores acertam e quais geram ruído:
for p in aprendizado.precisao_por_indicador():
    print(p.indicador_id, p.precisao, f"(n={p.amostra})")

# Sugestões de calibração (aplicação é decisão do perito):
for s in aprendizado.sugerir_calibracao():
    print(s.indicador_id, s.parametro_id, s.valor_atual, "→", s.valor_sugerido, s.direcao)
```

## Como se integra ao JFN existente

- **Não substitui** `rules/engine.py` nem `knowledge/pattern_engine.py`: complementa.
  Os `fraude_id` dos indicadores casam com os ids de `knowledge/fraudes_licitacao.py`.
- Os collectors (`tfe_ob.py`, `pncp.py`, `cnpj_enricher.py`, `ceis.py`) alimentam
  o `Dossie`. Sugestão de plugue: um adaptador que monta `Contratacao`/`Fornecedor`
  a partir dos models SQLAlchemy (`database/models.py`).
- O `Laudo.para_dict()` encaixa direto no `reports/html_report.py` (mesma linguagem
  de matriz TCU P×I e base legal já usada lá).

## Por que isto é "super inteligente" sem depender de IA forte

Porque a inteligência foi movida da IA para o **conhecimento estruturado + regras
determinísticas + calibração empírica**. O modelo fraco vira um OCR semântico
descartável; a perícia vira um instrumento de precisão, reproduzível e citável.
É o oposto de "confiar que o modelo entende" — é *não precisar* que ele entenda.

## Testes

```bash
python tests/test_nucleo_inteligencia.py     # 20 testes, offline, sem pytest
# ou
python -m pytest tests/test_nucleo_inteligencia.py -q
```
