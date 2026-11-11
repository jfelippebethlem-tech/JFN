# BRIEF complementar v61 · Fase 7b — COBERTURA do motor território

Contexto: a Fase 7 ficou correta mas rasa. Medido em `data/territorio.db`:
- Estado: só fonte PNCP (9.208 contratos). 7.068 **sem município** (R$ 13,1 bi), 77%. Atribuídos 2.056: 1.704 por `campo` (quase todos UERJ/HUPE → Rio e UENF → Campos), 388 por `texto`, 7 por `endereco`.
- PCRJ: 11.514 de 14.420 **sem AP** (R$ 46,7 bi), 80%.

Meta: **≥ 50% do VALOR contratado** atribuído no Estado e na PCRJ, com precisão ≥ 85% na amostra auditada. Se não chegar, dizer quanto chegou e por quê. Nenhum chute para inflar a cobertura.

## Estado

1. **Mais fontes de contrato**: localizar onde está gravado o backfill `contratos-estado` (log `data/backfill_contratos_estado.log`: 17.467 contratos, 10 entes, aditivos) e integrar como fonte, deduplicando com PNCP (nº do contrato + CNPJ do órgão + CNPJ do fornecedor; ou processo SEI). Integrar também os extratos do DOERJ que já são coletados. Campo `fonte` passa a ser lista.
2. **Unidades** (o método que mais rende): montar `data/territorio_unidades.csv` com fontes oficiais gratuitas:
   - Escolas estaduais RJ: microdados do Censo Escolar/INEP (dependência estadual, UF 33) → nome + município. Casar com "C.E.", "Colégio Estadual", "CIEP" (CIEP é estadual ou municipal: usar o número + dependência).
   - Saúde: CNES (estabelecimentos de gestão estadual/dupla, UF 33): hospitais estaduais, UPAs 24h, IECAC, IEDE etc.
   - Segurança: batalhões PMERJ (nº BPM → município sede), delegacias PCERJ (nº DP → município), DEGASE, SEAP (unidades prisionais), Corpo de Bombeiros (GBM).
   - FAETEC (unidades), DETRAN (postos), CEDAE (ETAs/ETEs), DER (residências de conservação), UERJ/UENF/UEZO (campi).
   Normalizar e casar no objeto/extrato. Guardar a fonte de cada linha.
3. **Orçamento/UG**: ligar contrato → empenho → OB (SIAFE/TFE). Usar a UG executora quando ela for regional e a regionalização da ação (localizador) quando existir.
4. **Texto**: incluir os **distritos e localidades** do IBGE (ex.: Itaipava → Petrópolis, Barra de São João → Casimiro de Abreu, Conservatória → Valença). Manter as armadilhas da Fase 7.
5. **Abrangência**: separar honestamente o que NÃO tem município porque é do estado inteiro (software corporativo, combustível da frota, folha, seguro, consultoria da secretaria) num balde novo **"Estado inteiro / sede"**. Critério explícito em regras (palavras-chave + órgão-meio), com o motivo gravado em `evidencia`. O balde "sem município identificado" fica só para o que realmente não se sabe.

## PCRJ por AP

1. Completar `territorio_pcrj_orgao_ap.csv`: SME (11 CREs), SMS (10 CAPs 1.0…5.3), Subprefeituras, COMLURB (gerências), Conservação (coordenadorias por AP), RioÁguas, GEO-Rio, Guarda Municipal (inspetorias). Fonte oficial de cada linha.
2. **Unidades municipais**: escolas municipais do Rio (INEP, dependência municipal, código 3304557) e unidades de saúde municipais (CNES: clínicas da família, CMS, hospitais, UPAs municipais, CER) → endereço → bairro → RA → AP.
3. **Texto**: "AP 3.1" literal, nomes de RAs, todos os bairros oficiais (lista IPP) e sub-bairros conhecidos.
4. Abrangência **"Cidade inteira"** separada de "sem AP identificada", com o mesmo critério do Estado.

## Fechamento

- Rodar `--full` de novo (um pesado por vez, `flock`).
- Refazer a auditoria (60 casos) e atualizar a cobertura por método, em contratos e em valor.
- Mapa/UI: rodapé mostra os 3 baldes separados (sem município · vários municípios · estado inteiro). Fichas mostram o método e a confiança.
- `pytest tests/test_territorio.py` com casos novos (≥ 10 de unidades: escola, hospital, batalhão, DP, CRE, CAP).
- Commit: `feat(painel-v61): fase 7b — cobertura do território`. Push.
