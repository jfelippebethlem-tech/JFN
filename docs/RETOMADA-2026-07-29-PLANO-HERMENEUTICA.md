# Plano de hermenêutica e OSINT — execução completa, 17 commits

> Escrito em 2026-07-29 ao encerrar a execução. O que interessa aqui não é a lista do que foi
> feito (essa está no git e em `docs/REFERENCIA-PROJETO.md` §10-11): é **o que o dado real
> ensinou**, e as pendências nomeadas uma a uma, para a próxima sessão não redescobrir nada.

## 1. O que o plano mudou

O motor saiu de *"o LLM lê e dá um grau"* para um juízo **medido, travado, publicado e convertido
em peça**:

| Camada | Antes | Depois |
|---|---|---|
| medir | nenhuma métrica de juízo jurídico | conjunto-ouro de 1.530 casos do TCU, F1 macro medido |
| travar | — | catraca de F1 + prompt rastreável por hash da fonte |
| publicar | — | `/api/eval/hermeneutica` e `/api/eval/lift` |
| converter | prosa com trechos | quesitos, diligências, dosimetria, matriz sem célula vazia |

Eixos **A, B e H completos**. C, D, E, F, G e I com pendências nomeadas (§4).

## 2. Os sete achados — e o fio que os liga

1. **Perfil de laranja marcava 55% da base.** Caiu para 1,4% ao medir a *prevalência* de cada
   eixo: sócio de 0–12 anos é 0,02% da base (indício), mas sócio com mais de 80 é 1,87% e empresa
   com um só sócio é 54,9% (o normal).
2. **As 8 citações do TCU "não confirmadas" EXISTEM.** A Jurisprudência Selecionada tem 17.510
   acórdãos e é um *recorte curado*; o acervo completo tem 521.090. Correção real: o Acórdão
   3.831/2012 não é do Plenário.
3. **210 documentos de outros processos** em 7 pastas do arquivo SEI. O diagnóstico original
   publicou "7% de 103 avaliáveis"; a recontagem deu **70 avaliáveis, 10%**.
4. **SECID: HHI 0,106 por CNPJ e 0,406 por grupo.** De R$ 918.995.504,56 pagos por OB, um grupo
   levou R$ 570.850.429,64 — 62,1% — em 9 CNPJs. O **consórcio tem CNPJ próprio** e é o que torna
   a concentração invisível.
5. **Dois detectores são anti-preditivos** (`corrida_dezembro` lift 0,59; `fornecedor_dependente`
   0,48, contra base de 7,01%) e três são **circulares** (lift 11–13 porque usam sanção como
   insumo).
6. **45% dos X1 da primeira varredura eram fabricados** — art. 124, II, "d" (reequilíbrio) somado
   ao teto de acréscimo do art. 125.
7. **Benford com n=50** rotula 100% das séries perfeitamente benfordianas como "não conformidade".

**O fio comum:** o número certo sobre a **unidade errada**, ou o **recorte lido como universo**.
Nenhum era erro de cálculo. Nenhum apareceu em revisão de código — todos apareceram ao confrontar
o resultado com o acervo real.

## 3. As três regras de honestidade que mais decidiram código

- **Ausência de registro não é ausência do fato.** Certame sem concorrente registrado é
  `nao_observado`, nunca "sem vínculo" (seriam 17.128 certames declarados limpos sem ninguém ter
  olhado). Ano do acervo não indexado é lacuna de cobertura, não inexistência. Documento sem
  número no contexto **fica**.
- **Leitura parcial nunca vira cobertura.** O servidor do TCU fechou o socket com 180 MB de
  335 MB; marcar aquele ano como coberto transformaria a falha em "inexistente".
- **Eixo que acende na maioria mede a base.** Antes de dar peso a qualquer sinal novo, contar a
  prevalência dele no acervo real.

## 4. Pendências, nomeadas

| Item | O que falta, exatamente |
|---|---|
| **282 manifests de íntegra** | não avaliáveis (sem `contexto`) — não são "limpos", são não observados; só recaptura muda |
| **A.3** | conserto do desenho da tarefa de 3 classes (a máscara destrói o sinal de `vicio_por_omissao`) |
| **C** | citação TCE-RJ (exige raspagem Angular via CDP), LexML morto, tabelas EMOP/SINAPI (SINAPI 401, EMOP redireciona) |
| **D.3.1/2** | tabela `contrato_item` e extrator de planilha — sem eles a curva ABC não tem o que ler |
| **D.4.4 / D.5** | posto fantasma; aditivos ESTADUAIS via DOERJ (o TCE-RJ não traz termos aditivos) |
| **E.0.1** | ampliar coleta de propostas — **só 0,66% dos certames têm disputa registrada**, e é isso que trava o E.3.2 |
| **E.1 preço** | inviável enquanto a fonte trouxer o valor do certame e não o lance de cada licitante |
| **E.3.3** | faltam `proposta_dia_nao_util` (exige timestamp de envio) e `planejamento_fachada` |
| **F.4 / G.3 / G.5** | economicidade por unidade de resultado; beneficiário final recursivo; porta giratória ligada a quem assinou o ato (extrator de ordenador tem ~8% de cobertura) |
| **I.1.2–I.4** | CEPIM, CEAF, JUCERJA, minhaReceita auto-hospedado, SpiderFoot |

## 5. Como verificar nesta VM

A suíte monolítica **não fecha** com outra sessão trabalhando (2 vCPU; morreu quatro vezes entre
47% e 66% com dois sweeps + Chromium + graphify, load 5–8). Rode em **lotes**:

```bash
ls tests/*.py tests/*/*.py | sort | sed -n '1,60p'    # e assim por diante
```

Resultado desta sessão: **976 + 1.041 + 268 (as 14 catracas) + 1.000 passed**, 6 skipped.

Segue vermelho apenas `test_divida_except_pass`, cuja dívida vem de `_SANDBOX/walker_humano.py`,
alterado por outra sessão — **não absorvida**, porque absorver baseline alheia em silêncio é como
ela cresce.

## 6. Duas armadilhas de sessão compartilhada

- **O índice do git é compartilhado.** Três vezes um `git add`/`git commit` de outra sessão levou
  arquivos meus (o C.1 entrou sob a mensagem dela; o H.6 entrou no commit do G.8). Fazer
  `add`+`commit` na mesma chamada e conferir com `git show --stat` depois.
- **`ps | grep` com padrão frouxo mente.** Concluí três vezes que a suíte tinha morrido quando
  estava viva, e cheguei a lançar execuções duplicadas — agravando a contenção que tentava evitar.
  Padrão que funciona: `ps -eo pid,etimes,args | grep "[.]venv/bin/python -m pytest"`.
