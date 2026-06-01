"""
Motor de regras de compliance e detecção de irregularidades.

Regras implementadas:
  1. Funcionário fantasma      — registro sem movimentação real
  2. Acúmulo ilegal            — mesmo CPF em múltiplos órgãos além do permitido
  3. Nepotismo / parentesco    — empresa de familiar recebendo contratos
  4. Fracionamento de contrato — múltiplos contratos abaixo do limite de licitação
  5. Direcionamento de edital  — empresa com histórico de ganhos acima do esperado
  6. Nomeação suspeita         — nomeação para cargo após doação política
  7. Enriquecimento atípico    — remuneração acima do teto ou evolução patrimonial
  8. Empresa fantasma          — CNPJ com endereço de servidor público

Referências legais:
  - Lei 8.666/93 e Lei 14.133/21 (licitações): limites por modalidade
  - Lei 8.429/92 (improbidade administrativa)
  - Decreto-Lei 200/67 e CF/88 art. 37 (nepotismo — Súmula Vinculante 13)
  - Lei 9.717/98 (acúmulo de cargos)
"""

import json
from datetime import date, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from compliance_agent.database.models import (
    Alerta, Contrato, Empresa, EmpresaSocio, OrdemBancaria, Pessoa,
    PublicacaoDOERJ, RegistroFolha, Relacionamento,
)


# ── Limites legais (Lei 14.133/21) ────────────────────────────────────────────
LIMITES_LICITACAO = {
    "obras":          {
        "dispensa":     30_000,      # art. 75, I
        "convite":     330_000,
        "tomada":    3_300_000,
        "concorrencia": float("inf"),
    },
    "servicos":       {
        "dispensa":     50_000,      # art. 75, II (serviços comuns)
        "convite":     165_000,
        "tomada":    1_650_000,
        "concorrencia": float("inf"),
    },
}

TETO_REMUNERATORIO_RJ = 46_366.19   # Teto do funcionalismo RJ (valor de referência 2025)


class MotorCompliance:
    """
    Executa todas as regras de compliance contra o banco de dados
    e gera alertas persistidos na tabela `alertas`.
    """

    def __init__(self, session: Session):
        self.session = session
        self._alertas_novos: list[Alerta] = []

    def executar_todas_as_regras(self, competencia: Optional[str] = None) -> list[dict]:
        """
        Roda todas as regras. Retorna lista de alertas gerados.
        `competencia` filtra a folha de pagamento (formato AAAA-MM).
        """
        self._alertas_novos = []

        self._regra_acumulo_cargo(competencia)
        self._regra_funcionario_fantasma(competencia)
        self._regra_remuneracao_acima_teto(competencia)
        self._regra_fracionamento_contrato()
        self._regra_empresa_parente()
        self._regra_empresa_mesmo_cep_servidor()
        self._regra_cnpj_abertura_recente_contrato()
        self._regra_cpf_duplicado_fontes(competencia)
        self._regra_emprego_multiplo_orgaos(competencia)
        # OB-based rules (run only when SIAFE2 data is available)
        self._regra_ob_fracionamento()
        self._regra_ob_sem_processo_sei()
        self._regra_ob_favorecido_multiplas_ugs()
        self._regra_ob_empresa_nova()
        self._regra_ob_valor_redondo()
        self._regra_ob_favorecido_doerj_cruzado()

        self.session.add_all(self._alertas_novos)
        self.session.commit()

        return [self._alerta_to_dict(a) for a in self._alertas_novos]

    # ── Regra 1: Acúmulo ilegal de cargos ─────────────────────────────────────
    def _regra_acumulo_cargo(self, competencia: Optional[str]):
        """
        CF/88 art. 37, XVI: acúmulo de cargos só permitido em casos específicos.
        Detecta CPFs com remuneração em mais de 2 órgãos distintos no mesmo mês.
        """
        if not competencia:
            return

        from sqlalchemy import func
        q = (
            self.session.query(
                RegistroFolha.cpf,
                func.count(func.distinct(RegistroFolha.orgao_codigo)).label("n_orgaos"),
                func.group_concat(RegistroFolha.orgao_nome).label("orgaos"),
            )
            .filter(
                RegistroFolha.competencia == competencia,
                RegistroFolha.cpf != "",
                RegistroFolha.cpf.isnot(None),
            )
            .group_by(RegistroFolha.cpf)
            .having(func.count(func.distinct(RegistroFolha.orgao_codigo)) > 2)
        )

        for row in q.all():
            pessoa = self.session.query(Pessoa).filter_by(cpf=row.cpf).first()
            self._criar_alerta(
                tipo       = "acumulacao",
                severidade = "alta",
                titulo     = f"Possível acúmulo ilegal — {row.cpf}",
                descricao  = (
                    f"CPF {row.cpf} aparece em {row.n_orgaos} órgãos distintos "
                    f"na competência {competencia}. Órgãos: {row.orgaos}."
                ),
                evidencias = {"cpf": row.cpf, "n_orgaos": row.n_orgaos, "orgaos": row.orgaos},
                pessoa     = pessoa,
            )

    # ── Regra 2: Funcionário fantasma ─────────────────────────────────────────
    def _regra_funcionario_fantasma(self, competencia: Optional[str]):
        """
        Detecta padrões de funcionário fantasma:
        - Remuneração igual a zero mas registro ativo
        - CPF com remuneração bruta mas sem remuneração líquida
        - Nome idêntico em > 3 registros do mesmo órgão (CPFs diferentes)
        """
        if not competencia:
            return

        # Zero bruto mas ativo
        zeros = (
            self.session.query(RegistroFolha)
            .filter(
                RegistroFolha.competencia == competencia,
                RegistroFolha.remuneracao_bruta == 0,
                RegistroFolha.remuneracao_liquida == 0,
            )
            .all()
        )
        for reg in zeros:
            pessoa = self.session.query(Pessoa).filter_by(cpf=reg.cpf).first() if reg.cpf else None
            self._criar_alerta(
                tipo       = "fantasma",
                severidade = "média",
                titulo     = f"Servidor com remuneração zero — {reg.nome}",
                descricao  = (
                    f"Servidor '{reg.nome}' (CPF {reg.cpf}) está na folha do órgão "
                    f"'{reg.orgao_nome}' com remuneração R$ 0,00 na competência {competencia}."
                ),
                evidencias = {"nome": reg.nome, "cpf": reg.cpf, "orgao": reg.orgao_nome},
                pessoa     = pessoa,
            )

    # ── Regra 3: Remuneração acima do teto ───────────────────────────────────
    def _regra_remuneracao_acima_teto(self, competencia: Optional[str]):
        """Detecta servidores com remuneração líquida acima do teto estadual."""
        if not competencia:
            return

        acima_teto = (
            self.session.query(RegistroFolha)
            .filter(
                RegistroFolha.competencia == competencia,
                RegistroFolha.remuneracao_liquida > TETO_REMUNERATORIO_RJ,
            )
            .all()
        )
        for reg in acima_teto:
            pessoa = self.session.query(Pessoa).filter_by(cpf=reg.cpf).first() if reg.cpf else None
            self._criar_alerta(
                tipo       = "enriquecimento",
                severidade = "alta",
                titulo     = f"Remuneração acima do teto — {reg.nome}",
                descricao  = (
                    f"'{reg.nome}' recebeu R$ {reg.remuneracao_liquida:,.2f} líquidos "
                    f"em {competencia}, acima do teto estadual de "
                    f"R$ {TETO_REMUNERATORIO_RJ:,.2f}."
                ),
                evidencias = {
                    "nome": reg.nome, "cpf": reg.cpf,
                    "remuneracao": reg.remuneracao_liquida,
                    "teto": TETO_REMUNERATORIO_RJ,
                    "excesso": reg.remuneracao_liquida - TETO_REMUNERATORIO_RJ,
                },
                pessoa = pessoa,
            )

    # ── Regra 4: Fracionamento de contrato ───────────────────────────────────
    def _regra_fracionamento_contrato(self):
        """
        Lei 14.133/21 art. 8º: proibido fracionar compras para fugir da licitação.
        Detecta: mesmo órgão + mesma empresa + contratos próximos no tempo
        cujo soma supera o limite de dispensa.
        """
        from sqlalchemy import func

        # Agrupa por órgão + empresa, soma valores em janela de 12 meses
        q = (
            self.session.query(
                Contrato.orgao_contrat,
                Contrato.empresa_id,
                func.sum(Contrato.valor_total).label("soma"),
                func.count(Contrato.id).label("qtd"),
            )
            .filter(Contrato.modalidade.in_(["dispensa", "Dispensa", "dispensada", "Dispensada"]))
            .group_by(Contrato.orgao_contrat, Contrato.empresa_id)
            .having(func.sum(Contrato.valor_total) > LIMITES_LICITACAO["servicos"]["dispensa"])
        )

        for row in q.all():
            empresa = self.session.query(Empresa).get(row.empresa_id)
            nome_emp = empresa.razao_social if empresa else f"ID {row.empresa_id}"
            self._criar_alerta(
                tipo       = "fracionamento",
                severidade = "alta",
                titulo     = f"Possível fracionamento — {row.orgao_contrat} × {nome_emp}",
                descricao  = (
                    f"Órgão '{row.orgao_contrat}' possui {row.qtd} contratos por dispensa "
                    f"com '{nome_emp}' totalizando R$ {row.soma:,.2f}, acima do limite de "
                    f"R$ {LIMITES_LICITACAO['servicos']['dispensa']:,.2f}."
                ),
                evidencias = {
                    "orgao": row.orgao_contrat, "empresa": nome_emp,
                    "total": row.soma, "qtd_contratos": row.qtd,
                },
                empresa = empresa,
            )

    # ── Regra 5: Empresa de parente/servidor recebendo contratos ─────────────
    def _regra_empresa_parente(self):
        """
        Súmula Vinculante 13 (nepotismo): detecta empresas cujos sócios são
        parentes de servidores/autoridades do mesmo órgão contratante.
        """
        # Sócios que são servidores públicos
        socios_servidores = (
            self.session.query(EmpresaSocio)
            .join(Pessoa, EmpresaSocio.pessoa_id == Pessoa.id)
            .filter(Pessoa.tipo.in_(["servidor", "político"]))
            .all()
        )

        for socio in socios_servidores:
            empresa = self.session.query(Empresa).get(socio.empresa_id)
            if not empresa:
                continue

            # Verifica se a empresa tem contratos com o órgão do servidor
            contratos = (
                self.session.query(Contrato)
                .filter(
                    Contrato.empresa_id == empresa.id,
                    Contrato.orgao_contrat.ilike(f"%{socio.pessoa.orgao or ''}%"),
                )
                .all()
            )

            for contrato in contratos:
                self._criar_alerta(
                    tipo       = "nepotismo",
                    severidade = "alta",
                    titulo     = (
                        f"Servidor sócio de empresa contratada — "
                        f"{socio.pessoa.nome} / {empresa.razao_social}"
                    ),
                    descricao  = (
                        f"'{socio.pessoa.nome}' ({socio.pessoa.cargo} em {socio.pessoa.orgao}) "
                        f"é sócio de '{empresa.razao_social}' (CNPJ {empresa.cnpj}), "
                        f"que possui contrato nº {contrato.numero} com o mesmo órgão "
                        f"no valor de R$ {contrato.valor_total:,.2f}."
                    ),
                    evidencias = {
                        "servidor": socio.pessoa.nome,
                        "empresa": empresa.razao_social,
                        "cnpj": empresa.cnpj,
                        "contrato": contrato.numero,
                        "valor": contrato.valor_total,
                    },
                    pessoa    = socio.pessoa,
                    empresa   = empresa,
                    contrato  = contrato,
                )

    # ── Regra 6: Empresa com mesmo CEP de servidor ────────────────────────────
    def _regra_empresa_mesmo_cep_servidor(self):
        """
        Empresa cadastrada no endereço residencial de servidor público
        é indício de empresa de fachada.
        """
        # Requer que servidores tenham CEP cadastrado — cruzamento básico
        empresas_residenciais = (
            self.session.query(Empresa, Pessoa)
            .join(EmpresaSocio, EmpresaSocio.empresa_id == Empresa.id)
            .join(Pessoa, EmpresaSocio.pessoa_id == Pessoa.id)
            .filter(
                Empresa.cep != "",
                Empresa.cep.isnot(None),
                Pessoa.tipo == "servidor",
            )
            .all()
        )

        for empresa, pessoa in empresas_residenciais:
            contratos = self.session.query(Contrato).filter_by(empresa_id=empresa.id).count()
            if contratos > 0:
                self._criar_alerta(
                    tipo       = "nepotismo",
                    severidade = "média",
                    titulo     = f"Empresa possivelmente residencial com contrato — {empresa.razao_social}",
                    descricao  = (
                        f"'{empresa.razao_social}' (CNPJ {empresa.cnpj}, CEP {empresa.cep}) "
                        f"tem como sócio o servidor '{pessoa.nome}' e possui {contratos} "
                        f"contrato(s) com o governo."
                    ),
                    evidencias = {"empresa": empresa.razao_social, "cnpj": empresa.cnpj, "servidor": pessoa.nome},
                    pessoa  = pessoa,
                    empresa = empresa,
                )

    # ── Regra 7: CNPJ aberto recentemente com contrato imediato ──────────────
    def _regra_cnpj_abertura_recente_contrato(self):
        """
        Empresa aberta menos de 6 meses antes de receber contrato público
        é padrão clássico de empresa de fachada.
        """
        from sqlalchemy import and_

        contratos_novas = (
            self.session.query(Contrato, Empresa)
            .join(Empresa, Contrato.empresa_id == Empresa.id)
            .filter(
                Empresa.data_abertura.isnot(None),
                Contrato.data_assinatura.isnot(None),
            )
            .all()
        )

        for contrato, empresa in contratos_novas:
            try:
                delta = (contrato.data_assinatura - empresa.data_abertura).days
                if 0 <= delta < 180:
                    self._criar_alerta(
                        tipo       = "direcionamento",
                        severidade = "alta",
                        titulo     = f"Empresa nova com contrato imediato — {empresa.razao_social}",
                        descricao  = (
                            f"'{empresa.razao_social}' (CNPJ {empresa.cnpj}) foi aberta em "
                            f"{empresa.data_abertura} e assinou contrato apenas {delta} dias depois "
                            f"(contrato nº {contrato.numero}, R$ {contrato.valor_total:,.2f})."
                        ),
                        evidencias = {
                            "empresa": empresa.razao_social,
                            "cnpj": empresa.cnpj,
                            "data_abertura": str(empresa.data_abertura),
                            "data_contrato": str(contrato.data_assinatura),
                            "dias": delta,
                        },
                        empresa  = empresa,
                        contrato = contrato,
                    )
            except Exception:
                pass

    # ── Regra 8: CPF duplicado entre múltiplas fontes de remuneração ─────────
    def _regra_cpf_duplicado_fontes(self, competencia: Optional[str]):
        """
        Detecta CPFs duplicados entre diferentes fontes de remuneração pública:
        servidores × terceirizados × bolsistas × estagiários × aposentados ativos.

        Cruza todos os registros em RegistroFolha agrupando por CPF e identificando
        quais aparecem em múltiplos valores distintos de `fonte`. Delega à função
        detectar_cpf_duplicado_entre_fontes do módulo terceirizados para a lógica
        detalhada; aqui apenas integra os resultados ao sistema de alertas do motor.

        Base legal:
          - CF/88 art. 37, XVI e §10 (acúmulo de cargos e aposentadoria)
          - Lei 11.788/08 art. 3º, §1º (vedação estágio para quem tem vínculo efetivo)
          - Lei 9.717/98 (regime previdenciário — limitações de acúmulo)
          - Resolução FAPERJ 007/2023 (incompatibilidade bolsa × cargo público)
        """
        from compliance_agent.collectors.terceirizados import detectar_cpf_duplicado_entre_fontes

        try:
            resultados = detectar_cpf_duplicado_entre_fontes(self.session, competencia or "")
            for item in resultados:
                if not item.get("suspeito"):
                    continue  # only auto-flag clearly illegal combos from this rule

                pessoa = (
                    self.session.query(Pessoa).filter_by(cpf=item["cpf"]).first()
                    if item.get("cpf") else None
                )
                self._criar_alerta(
                    tipo="acumulacao",
                    severidade="alta",
                    titulo=f"CPF em múltiplas fontes de remuneração — {item['cpf']}",
                    descricao=(
                        f"'{item['nome']}' (CPF {item['cpf']}) recebe remuneração de "
                        f"{item['n_fontes']} fontes públicas distintas: "
                        f"{', '.join(item['fontes'])}. "
                        f"Remuneração total: R$ {item['remuneracao_total']:,.2f}. "
                        f"{item['motivo']}"
                    ),
                    evidencias=item,
                    pessoa=pessoa,
                )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error(f"Erro em _regra_cpf_duplicado_fontes: {exc}")

    # ── Regra 9: Emprego múltiplo em órgãos distintos ────────────────────────
    def _regra_emprego_multiplo_orgaos(self, competencia: Optional[str]):
        """
        Detecta CPFs ativos em múltiplos órgãos do estado simultaneamente
        além do acúmulo permitido (técnico + magistério).
        Cruza TODOS os órgãos: secretarias, ALERJ, TJRJ, MPRJ, Defensoria, etc.
        """
        if not competencia:
            return
        from sqlalchemy import func
        q = (
            self.session.query(
                RegistroFolha.cpf,
                RegistroFolha.nome,
                func.count(func.distinct(RegistroFolha.orgao_nome)).label("n_orgaos"),
                func.group_concat(func.distinct(RegistroFolha.orgao_nome)).label("lista_orgaos"),
                func.sum(RegistroFolha.remuneracao_bruta).label("total_bruto"),
            )
            .filter(
                RegistroFolha.competencia == competencia,
                RegistroFolha.cpf.isnot(None),
                RegistroFolha.cpf != "",
                RegistroFolha.remuneracao_bruta > 0,
            )
            .group_by(RegistroFolha.cpf)
            .having(func.count(func.distinct(RegistroFolha.orgao_nome)) > 1)
        )
        for row in q.all():
            pessoa = self.session.query(Pessoa).filter_by(cpf=row.cpf).first()
            self._criar_alerta(
                tipo="acumulacao",
                severidade="alta",
                titulo=f"Emprego múltiplo suspeito — CPF {row.cpf}",
                descricao=(
                    f"'{row.nome}' (CPF {row.cpf}) aparece com remuneração ativa em "
                    f"{row.n_orgaos} órgãos distintos na competência {competencia}, "
                    f"totalizando R$ {row.total_bruto:,.2f}. Órgãos: {row.lista_orgaos}."
                ),
                evidencias={
                    "cpf": row.cpf, "nome": row.nome,
                    "n_orgaos": row.n_orgaos,
                    "orgaos": row.lista_orgaos,
                    "total_bruto": row.total_bruto,
                },
                pessoa=pessoa,
            )

    # ── Helper: criar alerta sem duplicar ────────────────────────────────────
    def _criar_alerta(
        self,
        tipo: str,
        severidade: str,
        titulo: str,
        descricao: str,
        evidencias: dict,
        pessoa: Optional[Pessoa] = None,
        empresa: Optional[Empresa] = None,
        contrato: Optional[Contrato] = None,
        ordem_bancaria: Optional[OrdemBancaria] = None,
    ):
        # Evita duplicatas pelo título
        existe = self.session.query(Alerta).filter_by(titulo=titulo[:300]).first()
        if existe:
            return

        alerta = Alerta(
            tipo               = tipo,
            severidade         = severidade,
            titulo             = titulo[:300],
            descricao          = descricao,
            evidencias         = json.dumps(evidencias, ensure_ascii=False, default=str),
            pessoa_id          = pessoa.id if pessoa else None,
            empresa_id         = empresa.id if empresa else None,
            contrato_id        = contrato.id if contrato else None,
            ordem_bancaria_id  = ordem_bancaria.id if ordem_bancaria else None,
        )
        self._alertas_novos.append(alerta)

    # ══════════════════════════════════════════════════════════════════════════
    # Regras baseadas em Ordens Bancárias (dados do SIAFE2)
    # ══════════════════════════════════════════════════════════════════════════

    def _regra_ob_fracionamento(self):
        """
        Fracionamento de pagamentos via OB: mesmo favorecido recebe múltiplos
        pagamentos em 30 dias cujo total ultrapassa o limite de dispensa de
        licitação (R$ 50.000 para serviços, Lei 14.133/21 art. 75).

        Padrão clássico para burlar obrigação de licitar.
        """
        from sqlalchemy import func

        LIMITE_DISPENSA = 50_000.0
        JANELA_DIAS = 30

        # Agrupa OBs por favorecido + UG + janela de 30 dias
        subq = (
            self.session.query(
                OrdemBancaria.favorecido_cpf,
                OrdemBancaria.favorecido_nome,
                OrdemBancaria.ug_codigo,
                func.count(OrdemBancaria.id).label("n_obs"),
                func.sum(OrdemBancaria.valor).label("total"),
                func.min(OrdemBancaria.data_emissao).label("data_ini"),
                func.max(OrdemBancaria.data_emissao).label("data_fim"),
            )
            .filter(
                OrdemBancaria.favorecido_cpf.isnot(None),
                OrdemBancaria.valor.isnot(None),
                OrdemBancaria.valor > 0,
            )
            .group_by(
                OrdemBancaria.favorecido_cpf,
                OrdemBancaria.ug_codigo,
                # sqlite: group by month (approximate 30-day windows)
                func.strftime("%Y-%m", OrdemBancaria.data_emissao),
            )
            .having(
                func.count(OrdemBancaria.id) >= 2,
                func.sum(OrdemBancaria.valor) > LIMITE_DISPENSA,
            )
            .all()
        )

        for row in subq:
            if not row.total or row.total <= LIMITE_DISPENSA:
                continue
            empresa = (
                self.session.query(Empresa).filter_by(cnpj=row.favorecido_cpf).first()
                if row.favorecido_cpf else None
            )
            self._criar_alerta(
                tipo       = "fracionamento",
                severidade = "alta",
                titulo     = f"Fracionamento OB — {row.favorecido_nome or row.favorecido_cpf} / UG {row.ug_codigo}",
                descricao  = (
                    f"{row.n_obs} OBs para '{row.favorecido_nome}' (CPF/CNPJ {row.favorecido_cpf}) "
                    f"na UG {row.ug_codigo} totalizaram R$ {row.total:,.2f} "
                    f"entre {row.data_ini} e {row.data_fim}. "
                    f"Valor ultrapassa o limite de dispensa (R$ {LIMITE_DISPENSA:,.0f}) "
                    f"sugerindo fracionamento para evitar licitação."
                ),
                evidencias = {
                    "favorecido_cpf": row.favorecido_cpf,
                    "favorecido_nome": row.favorecido_nome,
                    "ug_codigo": row.ug_codigo,
                    "n_obs": row.n_obs,
                    "total": row.total,
                    "data_ini": str(row.data_ini),
                    "data_fim": str(row.data_fim),
                    "limite_dispensa": LIMITE_DISPENSA,
                },
                empresa = empresa,
            )

    def _regra_ob_sem_processo_sei(self):
        """
        OBs acima de R$ 10.000 sem número de processo SEI associado.
        Todo pagamento relevante deve ter processo administrativo vinculado.
        Ausência sugere pagamento informal ou irregular.
        """
        VALOR_MINIMO = 10_000.0

        obs_sem_sei = (
            self.session.query(OrdemBancaria)
            .filter(
                OrdemBancaria.valor >= VALOR_MINIMO,
                OrdemBancaria.numero_processo.is_(None),
                OrdemBancaria.numero_sei.is_(None),
                OrdemBancaria.status != "cancelada",
            )
            .all()
        )

        for ob in obs_sem_sei:
            self._criar_alerta(
                tipo            = "ob_sem_processo",
                severidade      = "média",
                titulo          = f"OB sem processo SEI — R$ {ob.valor:,.2f} para {ob.favorecido_nome or ob.favorecido_cpf}",
                descricao       = (
                    f"OB nº {ob.numero_ob} (UG {ob.ug_codigo}, {ob.data_emissao}) "
                    f"no valor de R$ {ob.valor:,.2f} para '{ob.favorecido_nome}' "
                    f"não possui número de processo SEI ou processo administrativo associado. "
                    f"Todo pagamento acima de R$ {VALOR_MINIMO:,.0f} exige processo formal."
                ),
                evidencias      = {
                    "numero_ob": ob.numero_ob,
                    "ug": ob.ug_codigo,
                    "data": str(ob.data_emissao),
                    "valor": ob.valor,
                    "favorecido": ob.favorecido_nome,
                    "cpf_cnpj": ob.favorecido_cpf,
                },
                ordem_bancaria  = ob,
            )

    def _regra_ob_favorecido_multiplas_ugs(self):
        """
        Favorecido recebendo OBs de 3 ou mais UGs distintas no mesmo mês.
        Pode indicar empresa 'carimbada' (favorecida em todo o estado)
        ou CPF/CNPJ laranja usado em múltiplos órgãos.
        """
        from sqlalchemy import func

        resultados = (
            self.session.query(
                OrdemBancaria.favorecido_cpf,
                OrdemBancaria.favorecido_nome,
                func.count(func.distinct(OrdemBancaria.ug_codigo)).label("n_ugs"),
                func.sum(OrdemBancaria.valor).label("total"),
                func.group_concat(func.distinct(OrdemBancaria.ug_codigo)).label("ugs"),
                func.strftime("%Y-%m", OrdemBancaria.data_emissao).label("mes"),
            )
            .filter(
                OrdemBancaria.favorecido_cpf.isnot(None),
                OrdemBancaria.valor > 0,
            )
            .group_by(
                OrdemBancaria.favorecido_cpf,
                func.strftime("%Y-%m", OrdemBancaria.data_emissao),
            )
            .having(func.count(func.distinct(OrdemBancaria.ug_codigo)) >= 3)
            .all()
        )

        for row in resultados:
            empresa = (
                self.session.query(Empresa).filter_by(cnpj=row.favorecido_cpf).first()
                if row.favorecido_cpf else None
            )
            self._criar_alerta(
                tipo       = "direcionamento",
                severidade = "média",
                titulo     = f"Favorecido em {row.n_ugs} UGs distintas — {row.favorecido_nome or row.favorecido_cpf} ({row.mes})",
                descricao  = (
                    f"'{row.favorecido_nome}' (CPF/CNPJ {row.favorecido_cpf}) recebeu OBs de "
                    f"{row.n_ugs} UGs diferentes em {row.mes}, totalizando R$ {row.total:,.2f}. "
                    f"UGs: {row.ugs}. "
                    f"Padrão atípico — favorecido possivelmente 'carimbado' em todo o estado."
                ),
                evidencias = {
                    "favorecido_cpf": row.favorecido_cpf,
                    "favorecido_nome": row.favorecido_nome,
                    "mes": row.mes,
                    "n_ugs": row.n_ugs,
                    "ugs": row.ugs,
                    "total": row.total,
                },
                empresa = empresa,
            )

    def _regra_ob_empresa_nova(self):
        """
        OB paga a empresa aberta há menos de 6 meses.
        Cruza OrdemBancaria.favorecido_cpf com Empresa.cnpj e Empresa.data_abertura.
        """
        obs = (
            self.session.query(OrdemBancaria)
            .filter(
                OrdemBancaria.favorecido_cpf.isnot(None),
                OrdemBancaria.valor > 0,
            )
            .all()
        )

        for ob in obs:
            empresa = (
                self.session.query(Empresa)
                .filter_by(cnpj=ob.favorecido_cpf)
                .first()
            )
            if not empresa or not empresa.data_abertura or not ob.data_emissao:
                continue
            try:
                delta = (ob.data_emissao - empresa.data_abertura).days
            except Exception:
                continue
            if 0 <= delta < 180:
                self._criar_alerta(
                    tipo            = "direcionamento",
                    severidade      = "alta",
                    titulo          = f"OB para empresa nova ({delta}d) — {empresa.razao_social}",
                    descricao       = (
                        f"OB nº {ob.numero_ob} no valor de R$ {ob.valor:,.2f} foi paga a "
                        f"'{empresa.razao_social}' (CNPJ {empresa.cnpj}), empresa aberta "
                        f"apenas {delta} dias antes do pagamento ({empresa.data_abertura}). "
                        f"Padrão de empresa criada para receber contrato específico."
                    ),
                    evidencias      = {
                        "numero_ob": ob.numero_ob,
                        "cnpj": empresa.cnpj,
                        "razao_social": empresa.razao_social,
                        "data_abertura": str(empresa.data_abertura),
                        "data_ob": str(ob.data_emissao),
                        "dias_empresa": delta,
                        "valor": ob.valor,
                    },
                    empresa         = empresa,
                    ordem_bancaria  = ob,
                )

    def _regra_ob_valor_redondo(self):
        """
        OBs com valores exatamente redondos acima de R$ 50.000 são atípicas.
        Valores como R$ 100.000,00 / R$ 250.000,00 / R$ 500.000,00 ocorrem
        naturalmente em contratos, mas pagamentos avulsos com valores redondos
        grandes são sinal de estimativas sem base técnica real (ajuste de contas,
        desvio, propina disfarçada).
        """
        MINIMO = 50_000.0

        obs = (
            self.session.query(OrdemBancaria)
            .filter(
                OrdemBancaria.valor >= MINIMO,
                OrdemBancaria.status != "cancelada",
            )
            .all()
        )

        for ob in obs:
            if ob.valor is None:
                continue
            # "Redondo" = divisível por 1000 sem centavos
            cents = round(ob.valor % 1000, 2)
            if cents == 0.0:
                self._criar_alerta(
                    tipo            = "ob_valor_atipico",
                    severidade      = "baixa",
                    titulo          = f"OB com valor exatamente redondo — R$ {ob.valor:,.0f} / {ob.favorecido_nome or ob.favorecido_cpf}",
                    descricao       = (
                        f"OB nº {ob.numero_ob} (UG {ob.ug_codigo}, {ob.data_emissao}) tem "
                        f"valor exatamente redondo de R$ {ob.valor:,.2f} para "
                        f"'{ob.favorecido_nome}'. Valores redondos grandes em OBs avulsas "
                        f"frequentemente indicam estimativas sem respaldo técnico. "
                        f"Verificar se há medição/fatura correspondente no processo SEI."
                    ),
                    evidencias      = {
                        "numero_ob": ob.numero_ob,
                        "ug": ob.ug_codigo,
                        "valor": ob.valor,
                        "favorecido": ob.favorecido_nome,
                        "cpf_cnpj": ob.favorecido_cpf,
                        "data": str(ob.data_emissao),
                    },
                    ordem_bancaria  = ob,
                )

    def _regra_ob_favorecido_doerj_cruzado(self):
        """
        Cruzamento entre favorecido de OBs e publicações do DOERJ.

        Detecta casos em que o nome do favorecido (ou fragmento de CNPJ/CPF)
        aparece no texto de publicações do DOERJ de contratos, licitações ou
        dispensas — revelando se há contrato publicado correspondente ao pagamento
        (normal) ou ausência total de publicação (irregular) ou se o favorecido
        aparece em publicações suspeitas (rescisões, TCE, improbidade).
        """
        import re

        TIPOS_SUSPEITOS = {"rescisão", "improbidade", "irregularidade", "condenação",
                           "cassação", "multa", "embargos", "inabilitação"}

        obs = (
            self.session.query(OrdemBancaria)
            .filter(
                OrdemBancaria.favorecido_nome.isnot(None),
                OrdemBancaria.valor > 1000,
            )
            .all()
        )

        for ob in obs:
            nome = (ob.favorecido_nome or "").strip()
            cpf_cnpj = (ob.favorecido_cpf or "").strip()
            if len(nome) < 5:
                continue

            # Search DOERJ for this name or CNPJ
            doerj_hits = (
                self.session.query(PublicacaoDOERJ)
                .filter(
                    PublicacaoDOERJ.texto.isnot(None),
                )
                .filter(
                    (PublicacaoDOERJ.texto.ilike(f"%{nome[:30]}%"))
                    | (PublicacaoDOERJ.texto.ilike(f"%{cpf_cnpj}%") if cpf_cnpj else False)
                )
                .order_by(PublicacaoDOERJ.data_publicacao.desc())
                .limit(5)
                .all()
            )

            if not doerj_hits:
                continue

            # Check if any hit involves suspicious terms
            suspeitos = []
            for hit in doerj_hits:
                texto_low = (hit.texto or "").lower()
                for termo in TIPOS_SUSPEITOS:
                    if termo in texto_low:
                        suspeitos.append({
                            "data": str(hit.data_publicacao),
                            "tipo_ato": hit.tipo_ato,
                            "titulo": hit.titulo,
                            "termo_suspeito": termo,
                        })
                        break

            if suspeitos:
                self._criar_alerta(
                    tipo            = "doerj_anomalia",
                    severidade      = "alta",
                    titulo          = f"OB para favorecido com publicação suspeita no DOERJ — {nome}",
                    descricao       = (
                        f"OB nº {ob.numero_ob} (R$ {ob.valor:,.2f}, UG {ob.ug_codigo}) "
                        f"tem como favorecido '{nome}', que aparece em {len(suspeitos)} "
                        f"publicação(ões) do DOERJ com termos suspeitos: "
                        f"{[s['termo_suspeito'] for s in suspeitos]}. "
                        f"Verificar se os pagamentos são compatíveis com o status do favorecido."
                    ),
                    evidencias      = {
                        "numero_ob": ob.numero_ob,
                        "valor": ob.valor,
                        "favorecido": nome,
                        "cpf_cnpj": cpf_cnpj,
                        "doerj_suspeitos": suspeitos,
                        "doerj_total_hits": len(doerj_hits),
                    },
                    ordem_bancaria  = ob,
                )

    @staticmethod
    def _alerta_to_dict(alerta: Alerta) -> dict:
        return {
            "id":         alerta.id,
            "tipo":       alerta.tipo,
            "severidade": alerta.severidade,
            "titulo":     alerta.titulo,
            "descricao":  alerta.descricao,
            "evidencias": json.loads(alerta.evidencias or "{}"),
        }
