# Programa de Autoauditoria (direção humana)

> Padrão `program.md` do **karpathy/autoresearch**: o HUMANO declara as direções de investigação
> aqui; o executor (`tools/autoauditoria.py`) roda o loop determinístico e recomenda. Aplicar uma
> recomendação é decisão do dono (autonomy slider — o harness nunca edita detector sozinho).

## O que o harness faz

1. **`baseline`** (verificador barato, toda noite): retrato de cada detector no DB real
   (n_achados, mediana/máx de score, top-10 CNPJs) → grava em `data/autoauditoria/` e sinaliza
   **drift** (ex.: um detector que salta 40→400 achados = provável bug ou mudança de dado).
2. **`sintonia`** (loop autoresearch): para cada direção abaixo, varre a grade do parâmetro,
   mede n_achados no DB real e se os TESTES do detector seguem verdes, e recomenda o valor **mais
   conservador** (menos falso-positivo) que ainda passa em todos os testes rotulados.

## Direções de sintonia ativas

> Sintaxe (lida pelo harness): `- sintonia: <detector> <param> <v1> <v2> <v3> ...`
> A prosa ao redor é só para o humano.

- sintonia: fracionamento min_colado 2 3 4 5
- sintonia: sobrepreco min_certames 3 4 5 6
- sintonia: socio_oculto min_empresas 3 4 5
- sintonia: nepotismo max_raridade 12 20 30

**Racional de cada uma:**
- `fracionamento.min_colado` — quantas OBs coladas no teto exige-se para o grupo virar indício.
  Muito baixo → fornecimento contínuo vira "fracionamento"; buscar o piso que ainda passa nos testes.
- `sobrepreco.min_certames` — tamanho mínimo do grupo comparável para a mediana ser confiável.
- `socio_oculto.min_empresas` — nº de empresas do mesmo sócio para acender o sinal.
- `nepotismo.max_raridade` — quão raro o sobrenome precisa ser (acima disso, sobrenome comum polui).

## Como ler uma recomendação

"Mais conservador que mantém os testes verdes" = **não perdeu nenhuma detecção que os testes
protegem, e produz menos achados no dado real** (menos FP). Antes de aplicar: conferir no painel
que os achados que sumiram eram ruído, não fraude real. Menos achados NÃO é sempre melhor.

## Próximas direções (backlog)

- Rotular um gabarito real (`data/autoauditoria/gabarito.jsonl`) de achados confirmados/refutados
  pelo dono → trocar a métrica "n_achados" por precisão/recall verdadeiros (eval-set 60/30/10).
- Retro-auditoria estilo hn-time-capsule: achado antigo de fantasma/sobrepreço → a empresa foi
  sancionada/o contrato rescindido depois? Calibra a taxa de acerto por detector.
