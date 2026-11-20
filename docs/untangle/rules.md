# Decision log — untangle de `compliance_agent/rules/` (20/11/2026)

Escopo: `compliance_agent/rules/` (motor `engine.py`, `preco.py`, `generate_alerts.py`, `doerj_casamento.py`,
`obra.py`, `default_audit_config.py`) e as réguas que ele usa (`credor_institucional`, `limites_dispensa`,
`acima_do_teto`, `entidades_gov`). Escolhas do dono: **Comentários = sim** (só os que repetem o código saem;
fato externo, medição datada, decisão do dono, norma e porquê de workaround ficam), **Testes = não**.
Restrições da casa: comportamento pretendido igual, título do alerta é identidade (não muda), chaves de
evidência não mudam, constante normativa com fonte única.

Formato: o fix fica acima dos problemas que resolve. `[feito]` = aplicado nesta passada; `[pendente]` =
precisa de decisão do dono ou é redesenho de detector, não refatoração; `[fora do escopo]` = anotado só.

## 1. Constante normativa com uma fonte só  `[feito]`

- O motor passa a ler o teto remuneratório de `acima_do_teto.TETO_CF_37_XI` (o nome
  `TETO_REMUNERATORIO_RJ` segue exportado como apelido, porque `tools/regravar_alertas_teto.py` e os testes o
  importam). `generate_alerts` passa a usar `limite_dispensa(ano_da_OB, "compras")`.
  - `rules/engine.py:55` tinha `TETO_REMUNERATORIO_RJ = 46_366.19`, cópia literal de
    `acima_do_teto.TETO_CF_37_XI = 46366.19`; o reajuste anual teria de ser lembrado nos dois lugares, e a
    régua `classificar` recebia o teto do motor como parâmetro.
  - `rules/generate_alerts.py:134` testava `total > 60_000 and menor < 50_000` — 50.000 é o teto de 2021
    congelado (a trava `test_teto_dispensa_fonte_unica` só pega os tetos corrigidos, por isso escapou).
    Efeito: acusava fracionamento em 2025/2026 abaixo do teto legal (R$ 62.725,59 / R$ 65.492,11) e ignorava
    parcelas entre 50 mil e o teto do ano.
  - `rules/engine.py:42` `LIMITES_LICITACAO` (faixas convite/tomada da Lei 8.666) — código morto, ninguém
    importa; o próprio comentário já dizia que estava errado ("30.000 para obras", corrigido) e que só servia a
    contratos antigos que nenhum código consulta.

## 2. Tirar o que não tem razão própria para mudar  `[feito]`

- Apagar `rules/obra.py` e `rules/default_audit_config.py`; os três limiares que `generate_alerts` lia viram
  constantes nomeadas no próprio módulo.
  - `rules/obra.py` (`auditar_obras`, `REGRAS_OBRAS`, `LIMITE_DISPENSA_OBRAS`): nenhum importador em código,
    teste, yaml ou shell (impacto GitNexus = 0 chamadores; conferido por texto). Era a 4ª cópia do teto de
    obras, já reduzida a apelido em 27/07.
  - `rules/default_audit_config.py` (180 linhas, `ConfiguracaoAuditoria`): só `generate_alerts` importava, e
    só lia 3 campos. O resto era configuração especulativa: `limites_dispensa` e `regras_dispensa` eram a
    MESMA lista duas vezes; `limites_convite` (176.000/80.000) citava "Lei 14.133/2021, art. 75" para a
    modalidade convite, que a 14.133 não tem; `obter_limite_por_categoria`, `regras_resumidas`, domínios,
    palavras-chave, UGs "comuns" — sem leitor.
  - `generate_alerts.py`: docstring era cópia da do arquivo de configuração ("Arquivo único de referência…");
    variável `DB` sem uso.
  - `README.md` listava `default_audit_config.py` e `obra.py` na árvore de `rules/`.

## 3. O título é a identidade do alerta — uma regra de dedup, num lugar  `[feito]`

- `rules/alerta.py::LoteAlertas` guarda os alertas de uma execução e recusa título repetido no banco **ou na
  própria execução**; motor e `preco.py` usam o mesmo lote. Título, tipo, severidade e chaves de evidência
  ficam como estavam.
  - `rules/engine.py:_criar_alerta` deduplicava só contra o banco; como o motor grava tudo no fim
    (`add_all` + `commit`), dois alertas de mesmo título na mesma rodada passavam os dois. Ex.: a regra 5
    ("Servidor sócio de empresa contratada — X / Y") gera o mesmo título para cada contrato da empresa.
  - `rules/preco.py:139` tinha a sua própria cópia da dedup por título (mesmo `[:300]`, mesmo `json.dumps`) e
    o mesmo defeito: "Superfaturamento — {categoria} — {órgão}" saía uma vez por contrato fora da curva
    (reproduzido com dados sintéticos: 2 alertas iguais antes, 1 depois).
  - `rules/preco.py`: `import json` e `Alerta` passam a não ser necessários.
  - Os testes zeram `m._alertas_novos = []` entre regras; virou propriedade com setter que recomeça o lote.

## 4. "Mesma pessoa na folha" definido uma vez  `[feito]`

- `_mesma_pessoa_na_folha()` (CPF mascarado + nome normalizado) é a chave de agrupamento das duas regras de
  acúmulo. Título e evidências inalterados.
  - `rules/engine.py:_regra_acumulo_cargo` agrupava só por `RegistroFolha.cpf` e acusava "alta" juntando
    pessoas diferentes; a correção de 13/11 tinha chegado só a `_regra_emprego_multiplo_orgaos` — cópia da
    lógica com uma das duas consertada. A catraca `test_acumulo_cargo_cpf_mascarado_nomes_diferentes_nao_agrupa`
    estava `xfail(strict=True)` com o motivo "ACHADO: …"; passou a passar (XPASS estrito = falha), então o
    marcador xfail saiu — o corpo do teste não mudou. É a única linha de teste tocada nesta passada.
  - `from sqlalchemy import func` repetido dentro de 6 métodos → um import no topo.

## 5. Casos especiais que o desenho já torna desnecessários; comentários que mentiam  `[feito]`

- O SQL de cada regra já decide o candidato; o laço Python não repete o filtro. `DIAS_EMPRESA_NOVA = 180`
  é a régua das duas regras de "empresa nova". Docstrings passam a descrever o que o código faz.
  - `_regra_ob_valor_redondo`: o "redondo" era decidido no SQL (`round(valor*100) % 100000 == 0`) e de novo
    no Python (`round(valor % 1000, 2) == 0`), e `if ob.valor is None` depois de `valor >= 50.000` no SQL.
    As duas definições divergiam na borda (R$ 50.999,996 passa no SQL e caía no Python); vale a do SQL.
  - `_regra_ob_empresa_nova`: `0 <= dias < 180` no SQL (julianday) e de novo no Python, mais `try/except
    Exception: continue` em torno de uma subtração de duas colunas `Date` e um teste de nulo que o SQL já faz.
  - `_regra_cnpj_abertura_recente_contrato`: `try/except Exception: pass` engolia qualquer erro do bloco
    inteiro (inclusive da emissão do alerta); as duas colunas são `Date`, a subtração não falha.
  - `_regra_ob_fracionamento`: `if not row.total: continue` depois de `HAVING sum(valor) > piso`.
  - `_regra_ob_favorecido_doerj_cruzado`: `cpf_cnpj` recalculado da OB com o mesmo valor.
  - `_regra_fracionamento_contrato`: `modalidade IN ('dispensa','Dispensa','dispensada','Dispensada')` — um
    caso por grafia; agora `lower(modalidade)`. Efeito: "DISPENSA" em caixa alta passa a contar (era perdida).
  - `_regra_cpf_duplicado_fontes`: `import logging` dentro do `except`; o `except` fica (regra delegada a outro
    módulo não pode derrubar as demais), agora com o porquê escrito.
  - Docstring do módulo listava regras que não existem ("nomeação suspeita após doação", "direcionamento de
    edital por histórico", "evolução patrimonial"); docstring de `_regra_funcionario_fantasma` prometia três
    padrões e o código tem um; a de `_regra_fracionamento_contrato` falava em "contratos próximos no tempo" e
    um comentário em "janela de 12 meses" (não há janela — a RESSALVA logo acima já dizia isso);
    `preco.py` dizia usar "TF-IDF + cosine similarity" e comparar com SIASG/PNCP — é palavra-chave e mediana.
  - Comentários que só repetiam a linha seguinte ("Zero bruto mas ativo", "Sócios que são servidores",
    "Agrupa por…", "sqlite: group by month", "OB-based rules (run only when SIAFE2 data is available)" —
    este também falso: as regras rodam sempre). Ficaram todos os que registram medição datada (10/09, 13/11,
    17/11, 20/11), norma, decisão ou porquê de limite.

Verificação extra com dados sintéticos (sem teste novo): 3 contratos da mesma empresa nova geravam 3 alertas
"Empresa nova com contrato imediato — X" e 3 "Servidor sócio de empresa contratada — S / X" na mesma rodada;
agora 1 de cada (efeito do item 3).

## 6. Segunda volta (revisão independente, etapa 5 da skill)  `[feito]`

- Ligações escondidas e sobras que a revisão achou e que se resolvem sem mudar comportamento:
  - `doerj_casamento.py:29` `TERMOS_RISCO` e as chaves de `_RX_TERMO` tinham de mudar juntos (termo só na
    tupla dava `KeyError` em `ocorrencias`); agora `TERMOS_RISCO = tuple(_RX_TERMO)`. Docstring "módulo puro
    (só re/unicodedata)" ignorava o import de `entidades_gov`.
  - `engine.py`: import local de `classificar` e de `limites_dispensa` (2×) dentro dos métodos → topo;
    `teto=TETO_REMUNERATORIO_RJ` repassava o próprio default da régua; comentário citava `_criar_alerta`.
  - `preco.py`: `valor_total > 0` repetido em três laços depois de a consulta já filtrar `valor_total > 0`;
    `try/except StatisticsError` em `stdev` de lista que já tem ≥ 2 itens; comentário "Categoriza cada
    contrato".
  - `generate_alerts.py`: `ids = [...itens[:3]]` montado para usar só `ids[0]` (2×).

## 7. Pendente — precisa de decisão do dono ou é redesenho de detector  `[pendente]`

- Uma definição de "favorecido é o próprio ente público" (hoje são três):
  - `engine.py:_PREFIXOS_ENTE`/`_eh_ente_publico` (prefixo, usado por fracionamento OB e "N UGs");
  - `doerj_casamento.eh_orgao_publico` (regex canônica de `entidades_gov` + guarda de sufixo societário);
  - `entidades_gov.eh_nao_fornecedor` (regex, usada por anomalias e grafo_cartel).
  - Unificar muda o resultado: o prefixo `"UNIAO"` exclui hoje "UNIAO NORTE FLUMINENSE ENG. E COMERCIO LTDA"
    (fornecedor real) das regras de OB — defeito que a guarda de `doerj_casamento` já evita; e `"FUNDACAO "`
    exclui fundações privadas (FGV, Cesgranrio) que a regra do DOERJ hoje examina. Qual lista vale é decisão
    de política, não de refatoração.
- `_regra_empresa_mesmo_cep_servidor`: o título promete "possivelmente residencial", mas `Pessoa` não tem CEP
  e a regra não compara endereço — é "servidor sócio de empresa com contrato", sobrepondo a regra 5. Mudar o
  título é mudar a identidade dos alertas gravados; corrigir exige CEP do servidor (fonte inexistente hoje).
- `_regra_ob_sem_processo_sei` e `_regra_ob_valor_redondo`: `status != 'cancelada'` descarta as 1.178.802 OB
  de `status` NULL do espelho TFE — as duas regras estão mortas de propósito (memória
  `regras-mortas-por-null-no-status`, 23/09: ligá-las sobre o TFE inundaria de falso positivo; 60% das OB
  "sem processo" têm processo no SIAFE). Redesenho previsto: sobre `ob_orcamentaria_siafe` com
  `cruzamentos_intel._ob_paga`. As outras quatro regras de OB também leem o TFE e não filtram OB anulada —
  a mesma régua (`_ob_paga`) resolveria as seis de uma vez; é redesenho de detector, fora desta passada.
- `_regra_acumulo_cargo`: `Pessoa` é buscada por `cpf=row.cpf` com CPF mascarado — pode ligar o alerta à
  pessoa errada (também em `_regra_emprego_multiplo_orgaos` e `_regra_remuneracao_acima_teto`).
- `_regra_ob_fracionamento` usa o teto simples; ente com teto dobrado (art. 75 §2º — consórcio público,
  agência executiva) seria acusado pela metade do limite. `limite_dispensa(..., duplicado=True)` existe, falta
  saber quais UGs se enquadram.
- `generate_alerts.gerar_alertas`: carrega as 1,18 milhão de OB na memória (o problema que o motor resolveu em
  10/09), não deduplica (o título é o número da OB, compartilhado por `sem_sei` e `valor_redondo`) e nunca
  gravou um alerta na base (0 linhas dos cinco tipos em `alertas`, medido hoje). O único chamador é o
  ciclo do Auditor 24h em `hermes_goal`, dentro de `try/except`. Candidato a "construído, nunca rodado":
  aposentar ou religar é decisão do dono.

- `_regra_remuneracao_acima_teto` filtra por LÍQUIDO > teto mas classifica pelo BRUTO (`acima_do_teto` é
  régua de bruto) e calcula `excesso` pelo líquido: bruto acima e líquido abaixo nunca é avaliado. Corrigir
  aumenta alertas — decisão do dono (a regravação de 17/11 foi calibrada assim).
- `acima_do_teto.classificar` trata `componentes={}` diferente de `None` (dict vazio cai em
  INDICIO_SUPERSALARIO com R$ 0 excluído). O motor passa `None`; quem passar `{}` acusa sem composição.
- `generate_alerts` × motor: "OB sem SEI" e "valor redondo" têm critérios diferentes com o mesmo nome
  (lá: só `numero_sei` vazio, qualquer valor; ≥ R$ 5 mil a menos de R$ 50 de múltiplo de 100 — pega ~metade
  dos valores); severidade `"media"` sem acento (o resto usa `"média"`); cada `gerar_alerta` abre e commita a
  própria sessão, ignorando a recebida. Vai junto com a decisão sobre aposentar/religar o módulo.
- `doerj_casamento.padrao_nome` corta o nome em 30 caracteres "como a busca SQL" — a busca por nome no
  `texto` não existe mais (o motor casa por `cnpjs_extraidos`). Tirar o corte muda casamentos.
- `doerj_casamento._CABECALHO` (600) serve a dois limiares diferentes (cabeçalho do ato de pessoal e posição
  de "termo é título do ato"); separar é trivial, mas a calibração de 20/11 foi feita com os dois iguais.
- `preco.py` ordena suspeitos convertendo de volta a string `"acima_por"` ("12.3%") — formato de exibição
  servindo de chave de ordenação.

## 8. Fora do escopo (anotado, não mexido)

- `compliance_agent/hermes_goal.py:228` `_CONFIG_PADRAO_PATH` aponta para `compliance_agent/default_audit_config.py`,
  arquivo que nunca existiu nesse caminho, e não é lido por ninguém.
- `compliance_agent/collectors/terceirizados.py::detectar_cpf_duplicado_entre_fontes` agrupa por CPF (mascarado)
  sozinho — o mesmo defeito do item 4, numa regra que o motor consome.
- `cruzamentos_intel._SQL_NAO_PUBLICO` (lista de `NOT LIKE` por nome) é uma quarta lista de "ente público",
  em SQL.
- Natureza jurídica 2011/2038 (estatal) copiada fora de `credor_institucional` (que se declara régua única):
  `compliance_agent/esfera_orgao.py:87`, `compliance_agent/ordem_cronologica_siafe.py:44`,
  `tools/agente_publico_reverso.py:227`. Unificar exige mexer nesses módulos.
- `entidades_gov.py:9` diz "Usado por: anomalias.py, grafo_cartel.py" — há ao menos 8 importadores.
