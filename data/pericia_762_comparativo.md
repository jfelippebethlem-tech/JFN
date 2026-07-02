# Perícia paralela — SEI-330020/000762/2021 (ITERJ × MGS Clean, Contrato 005/2021)

> Experimento de calibração: o MESMO processo (64 docs capturados via itkava,
> arquivados com fases) periciado por 4 vias, medido contra o **veredito-ouro**
> da auditoria exata de 2026-06-20 (100% fonte primária): *sem pagamento a
> maior; reajustes corretos; o Estado DEVE à MGS R$ 56.044,28*.

## Veredito de cada perito

| Perito | Veredito | Acertos | Erros |
|---|---|---|---|
| **Lex fraco** (groq llama-8B) | "irregular" | — | ① colapsou em lixo binário na 1ª chamada (14k chars); ② ignorou o formato JSON; ③ red flag falsa: FGTS "vencido" (armadilha temporal — certidão de 2022 lida em 2026 sempre estará vencida); ④ confundiu razões sociais da MESMA empresa |
| **Groq 70B** (tier smart, grátis) | "regular, sem flags" | sem pagamento a maior ✔; formato JSON ✔ | perdeu o único achado real (crédito de R$ 56.044,28 devido à MGS — estava no corpus) |
| **Hermes** (cadeia + RAG, via cerebras) | "indeterminado c/ fortes indícios" | honestidade formal ✔ (pede documentos antes de concluir); estrutura normativa ✔ | **reciclou hipóteses JÁ REFUTADAS da memória RAG**: "OBs duplicadas 10/2025" (a auditoria-ouro provou: OBs gêmeas = catch-up de reajuste) e "fracionamento vs teto de dispensa" (o contrato veio de licitação no processo-pai — categoria errada) |
| **Fable (gabarito)** | regular; **Estado deve R$ 56.044,28 à MGS** | cita o doc 3 do arquivo (despacho 05/05/2026, index 130341565) verbatim; fases/lacunas pelo código determinístico | — |

Triagem fantasma da MGS: **10/100 BAIXO** (só marca residencial no endereço) — coerente
com empresa real prestando serviço contínuo há 4+ anos.

## Lições — como instruir as IAs fracas (adicionadas às 5 do experimento nº1)

6. **Payload é veneno para 8B**: >8k chars → colapso em tokens degenerados
   (1.024 backspaces). Modelos de volume recebem EXCERTOS por documento
   (≤1.200 chars), nunca a íntegra.
7. **Armadilha temporal**: instrua explicitamente — *"certidão/CRF com validade
   expirada em relação a HOJE não é red flag se era válida na data do ato"*.
8. **Entidade ≠ grafia**: razão social varia entre documentos (Eireli→Ltda,
   abreviações); a IA fraca precisa da regra *"mesmo CNPJ = mesma empresa"*.
9. **RAG precisa carregar VEREDITOS, não só suspeitas**: o Hermes re-levantou
   duplicidade/fracionamento que a auditoria-ouro já refutou. Toda hipótese
   refutada deve ir à memória COM o veredito (ex.: [[asscont-saldo-56k]]), e o
   prompt deve mandar checar "isto já foi periciado?" antes de acusar.
10. **Tier certo por tarefa**: 8B só para extração/triagem com saída rígida;
    conclusão pericial exige ≥70B; veredito final continua humano/Fable.
    Custo de tudo isso: R$ 0 (groq/cerebras free tier).

## Ajustes aplicados
- Experimento reproduzível: `tools/experimento_ia_fraca.py` (fases) + este
  comparativo (perícia integral). Lições consolidadas aqui e no vault.
- O prompt de produção do sweep (`sei_ficha.py`) já segue as regras 6 e 10
  (excertos + stepfun só triagem); regras 7-9 são o próximo upgrade do prompt
  (pendência anotada — mudança em prompt de produção só com re-teste no lote).
