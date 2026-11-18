# -*- coding: utf-8 -*-
"""certeza — controle de qualidade e certeza sobre TUDO o que o JFN afirma (docs/ARQUITETURA-DE-CERTEZA.md).

Estende o autoaprimoramento da perícia (ledger com nível de prova, portão determinístico) e a propagação
(config/propagacao.yaml) a qualquer número: cada FATO tem identidade, proveniência, estado e nível de prova; toda
escrita passa por portão; o grafo de dependências é auditado; vault, cérebro e painel citam o fato pelo id e um
verificador acusa onde um texto repete número diferente. Sem LLM, sem API paga, sem serviço novo."""
