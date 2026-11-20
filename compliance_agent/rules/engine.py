"""
Motor de regras de compliance: cada `_regra_*` consulta o banco e emite alertas na tabela `alertas`.

Folha (precisam da competência AAAA-MM):
  - acúmulo de cargos em mais de 2 órgãos e emprego em 2+ órgãos (CF/88 art. 37, XVI)
  - servidor com remuneração zero (indício de fantasma)
  - remuneração acima do teto (CF/88 art. 37, XI e §11 — régua `acima_do_teto`)
  - CPF em várias fontes de remuneração (delegada a `collectors.terceirizados`)
Contratos e sócios:
  - soma de dispensas do par órgão × empresa acima do teto (Lei 14.133/21, arts. 8º e 75)
  - servidor/político sócio de contratada do próprio órgão (Súmula Vinculante 13)
  - servidor sócio de empresa contratada (`_regra_empresa_mesmo_cep_servidor`)
  - empresa aberta há menos de 180 dias ao assinar contrato
Ordens bancárias (espelho TFE `ordens_bancarias`, janela recente, candidatos filtrados no SQL):
  - fracionamento mensal, OB sem processo, favorecido em 3+ UGs, empresa nova, valor redondo,
    favorecido com termo de risco no MESMO ato do DOERJ (`doerj_casamento`)

Toda regra emite pelo `LoteAlertas` (`rules/alerta.py`): o título é a identidade do alerta.
"""

import json
import logging
from datetime import date as _date, timedelta
from typing import Optional

from sqlalchemy import Integer, func
from sqlalchemy.orm import Session

from compliance_agent.database.models import (
    Alerta, Contrato, Empresa, EmpresaSocio, OrdemBancaria, Pessoa,
    PublicacaoDOERJ, RegistroFolha,
)
from compliance_agent.acima_do_teto import TETO_CF_37_XI, classificar as classificar_teto
from compliance_agent.credor_institucional import institucional
from compliance_agent.limites_dispensa import LIMITES, ato_normativo, limite_dispensa
from compliance_agent.reporting.intel_base import moeda
from compliance_agent.rules.alerta import LoteAlertas


# Teto remuneratório: o número é o da régua `acima_do_teto` (CF art. 37, XI), não uma cópia — o nome
# antigo segue exportado porque tools/regravar_alertas_teto.py e os testes o importam daqui.
TETO_REMUNERATORIO_RJ = TETO_CF_37_XI

# Empresa aberta há menos que isto ao contratar/receber é "empresa nova" (regras de contrato e de OB).
DIAS_EMPRESA_NOVA = 180

logger = logging.getLogger(__name__)


def _mesma_pessoa_na_folha():
    """Chave de agrupamento de "mesma pessoa" na folha: CPF mascarado E nome.

    O CPF da folha vem MASCARADO (6 dígitos do meio): agrupar só por ele juntava pessoas diferentes (revisão
    de 13/11/2026: 99,57% dos 70.533 grupos eram de pessoas distintas, e o alerta publicava o nome de uma somado
    à remuneração de outras)."""
    return (RegistroFolha.cpf, func.upper(func.trim(RegistroFolha.nome)))


class MotorCompliance:
    """
    Executa todas as regras de compliance contra o banco de dados
    e gera alertas persistidos na tabela `alertas`.
    """

    def __init__(self, session: Session):
        self.session = session
        self._lote = LoteAlertas(session)

    @property
    def _alertas_novos(self) -> list[Alerta]:
        return self._lote.novos

    @_alertas_novos.setter
    def _alertas_novos(self, alertas: list[Alerta]):
        """Recomeça a execução (os testes zeram a lista entre uma regra e outra)."""
        self._lote = LoteAlertas(self.session, alertas)

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
            .group_by(*_mesma_pessoa_na_folha())
            .having(func.count(func.distinct(RegistroFolha.orgao_codigo)) > 2)
        )

        for row in q.all():
            pessoa = self.session.query(Pessoa).filter_by(cpf=row.cpf).first()
            self._lote.criar(
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
        """Servidor na folha da competência com remuneração bruta e líquida iguais a zero."""
        if not competencia:
            return

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
            self._lote.criar(
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
        # Régua única `acima_do_teto.classificar` (17/11/2026): a folha da base não traz a composição do
        # contracheque, e indenizatórias/férias/13º/retroativos não contam para o teto (CF art. 37 §11) — sem
        # composição é VERIFICAR (média), ≥2,5× o teto é RRA provável (baixa); nunca "alta". Antes: 403 alertas
        # "alta" (53% dos "alta" do Início) pelo líquido cru.
        for reg in acima_teto:
            cls = classificar_teto(reg.remuneracao_bruta or reg.remuneracao_liquida, None)
            if not cls.get("acima"):
                continue
            pessoa = self.session.query(Pessoa).filter_by(cpf=reg.cpf).first() if reg.cpf else None
            self._lote.criar(
                tipo       = "enriquecimento",
                severidade = "baixa" if cls["status"] == "RRA_RETROATIVO_PROVAVEL" else "média",
                titulo     = f"Remuneração acima do teto — {reg.nome}",
                descricao  = (
                    f"'{reg.nome}' recebeu R$ {moeda(reg.remuneracao_liquida)} líquidos "
                    f"(R$ {moeda(reg.remuneracao_bruta)} brutos) em {competencia}; teto de referência "
                    f"R$ {moeda(TETO_REMUNERATORIO_RJ)}. {cls['status']}: {cls['motivo']} "
                    "(verba indenizatória não entra no teto — CF art. 37 §11). Indício a conferir, não acusação."
                ),
                evidencias = {
                    "nome": reg.nome, "cpf": reg.cpf,
                    "remuneracao": reg.remuneracao_liquida,
                    "remuneracao_bruta": reg.remuneracao_bruta,
                    "teto": TETO_REMUNERATORIO_RJ,
                    "excesso": reg.remuneracao_liquida - TETO_REMUNERATORIO_RJ,
                    "status_teto": cls["status"],
                },
                pessoa = pessoa,
            )

    # ── Regra 4: Fracionamento de contrato ───────────────────────────────────
    def _regra_fracionamento_contrato(self):
        """
        Lei 14.133/21 art. 8º: proibido fracionar compras para fugir da licitação.
        Detecta: mesmo órgão + mesma empresa com contratos por dispensa cuja soma supera o teto de dispensa.
        """
        # RESSALVA de precisão, declarada em vez de silenciada: o agrupamento abaixo NÃO tem
        # janela temporal — soma todos os contratos por dispensa do par órgão×empresa, de
        # qualquer ano. Enquanto a janela não existir, o teto usado é o do exercício MAIS RECENTE
        # (o maior), que é a leitura conservadora:
        # erra para menos achados, nunca para acusação indevida. Corrigir a janela é mudança de
        # desenho do detector, não desta correção de fonte única.
        _exercicio_ref = _date.today().year
        _teto_dispensa = limite_dispensa(_exercicio_ref, "compras")

        q = (
            self.session.query(
                Contrato.orgao_contrat,
                Contrato.empresa_id,
                func.sum(Contrato.valor_total).label("soma"),
                func.count(Contrato.id).label("qtd"),
            )
            .filter(func.lower(Contrato.modalidade).in_(["dispensa", "dispensada"]))
            .group_by(Contrato.orgao_contrat, Contrato.empresa_id)
            .having(func.sum(Contrato.valor_total) > _teto_dispensa)
        )

        for row in q.all():
            empresa = self.session.query(Empresa).get(row.empresa_id)
            nome_emp = empresa.razao_social if empresa else f"ID {row.empresa_id}"
            self._lote.criar(
                tipo       = "fracionamento",
                severidade = "alta",
                titulo     = f"Possível fracionamento — {row.orgao_contrat} × {nome_emp}",
                descricao  = (
                    f"Órgão '{row.orgao_contrat}' possui {row.qtd} contratos por dispensa "
                    f"com '{nome_emp}' totalizando R$ {moeda(row.soma)}, acima do limite de "
                    f"dispensa de {_exercicio_ref} (R$ {moeda(_teto_dispensa)} — "
                    f"{ato_normativo(_exercicio_ref)})."
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

            contratos = (
                self.session.query(Contrato)
                .filter(
                    Contrato.empresa_id == empresa.id,
                    Contrato.orgao_contrat.ilike(f"%{socio.pessoa.orgao or ''}%"),
                )
                .all()
            )

            for contrato in contratos:
                self._lote.criar(
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
                        f"no valor de R$ {moeda(contrato.valor_total)}."
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
        Empresa com servidor no quadro societário e com contrato com o governo.

        Apesar do nome e do título ("possivelmente residencial"), NÃO compara endereço: `Pessoa` não tem CEP, e
        o filtro só exige que a empresa tenha algum CEP. Título mantido por ser a identidade dos alertas já
        gravados; ver docs/untangle/rules.md.
        """
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
                self._lote.criar(
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
        Empresa aberta menos de DIAS_EMPRESA_NOVA dias antes de assinar contrato público
        é padrão clássico de empresa de fachada.
        """
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
            delta = (contrato.data_assinatura - empresa.data_abertura).days
            if 0 <= delta < DIAS_EMPRESA_NOVA:
                self._lote.criar(
                    tipo       = "direcionamento",
                    severidade = "alta",
                    titulo     = f"Empresa nova com contrato imediato — {empresa.razao_social}",
                    descricao  = (
                        f"'{empresa.razao_social}' (CNPJ {empresa.cnpj}) foi aberta em "
                        f"{empresa.data_abertura} e assinou contrato apenas {delta} dias depois "
                        f"(contrato nº {contrato.numero}, R$ {moeda(contrato.valor_total)})."
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
                    continue

                pessoa = (
                    self.session.query(Pessoa).filter_by(cpf=item["cpf"]).first()
                    if item.get("cpf") else None
                )
                self._lote.criar(
                    tipo="acumulacao",
                    severidade="alta",
                    titulo=f"CPF em múltiplas fontes de remuneração — {item['cpf']}",
                    descricao=(
                        f"'{item['nome']}' (CPF {item['cpf']}) recebe remuneração de "
                        f"{item['n_fontes']} fontes públicas distintas: "
                        f"{', '.join(item['fontes'])}. "
                        f"Remuneração total: R$ {moeda(item['remuneracao_total'])}. "
                        f"{item['motivo']}"
                    ),
                    evidencias=item,
                    pessoa=pessoa,
                )
        except Exception as exc:
            # Regra delegada a outro módulo: a falha dela não pode derrubar as demais regras da execução.
            logger.error("Erro em _regra_cpf_duplicado_fontes: %s", exc)

    # ── Regra 9: Emprego múltiplo em órgãos distintos ────────────────────────
    def _regra_emprego_multiplo_orgaos(self, competencia: Optional[str]):
        """
        Detecta CPFs ativos em múltiplos órgãos do estado simultaneamente
        além do acúmulo permitido (técnico + magistério).
        Cruza TODOS os órgãos: secretarias, ALERJ, TJRJ, MPRJ, Defensoria, etc.
        """
        if not competencia:
            return
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
            .group_by(*_mesma_pessoa_na_folha())
            .having(func.count(func.distinct(RegistroFolha.orgao_nome)) > 1)
        )
        for row in q.all():
            pessoa = self.session.query(Pessoa).filter_by(cpf=row.cpf).first()
            self._lote.criar(
                tipo="acumulacao",
                # média, não alta: acumular é lícito nos casos da CF art. 37, XVI (professor, técnico-científico,
                # saúde), e a folha não diz o cargo com segurança para separar.
                severidade="média",
                titulo=f"Emprego múltiplo a verificar — {row.nome} (CPF {row.cpf})",
                descricao=(
                    f"'{row.nome}' (CPF {row.cpf}) aparece com remuneração ativa em "
                    f"{row.n_orgaos} órgãos distintos na competência {competencia}, "
                    f"totalizando R$ {moeda(row.total_bruto)}. Órgãos: {row.lista_orgaos}. "
                    "Verificar se é acumulação lícita (CF art. 37, XVI) e se é a mesma pessoa "
                    "(o CPF da folha é mascarado; o casamento usa CPF parcial + nome)."
                ),
                evidencias={
                    "cpf": row.cpf, "nome": row.nome,
                    "n_orgaos": row.n_orgaos,
                    "orgaos": row.lista_orgaos,
                    "total_bruto": row.total_bruto,
                },
                pessoa=pessoa,
            )

    # ══════════════════════════════════════════════════════════════════════════
    # Regras baseadas em Ordens Bancárias (dados do SIAFE2)
    # ══════════════════════════════════════════════════════════════════════════

    # ── Janela e teto das regras de OB (10/09/2026) ─────────────────────────────────────────
    # Quatro regras abaixo faziam `.query(OrdemBancaria).all()` sobre 1,18 milhão de OBs (1,7 GB de
    # RAM) e uma consulta por OB (N+1): nunca terminavam nos 900 s do cron — o passo "regras" dava
    # rc=124 e, antes do reparo do banco, morria antes por um erro de tipo com rc=0 (84 vezes).
    # Regra da casa: candidatos filtrados NO SQL, janela recente e teto por execução. O `LoteAlertas`
    # já deduplica por título, então rodar de novo não repete o alerta.
    JANELA_OB_DIAS = 90
    TETO_CANDIDATOS = 300

    def _desde(self) -> _date:
        return _date.today() - timedelta(days=self.JANELA_OB_DIAS)

    # Favorecido que é ENTE PÚBLICO (transferência, tributo, fundo) não é fornecedor: "MINISTÉRIO DA
    # FAZENDA em 3 UGs" e "FUNDO DE EQUALIZAÇÃO fracionado" eram os primeiros alertas da lista (10/09).
    _PREFIXOS_ENTE = ("MINIST", "FUNDO ", "SECRETARIA", "TRIBUNAL", "PREFEITURA", "UNIVERSIDADE", "INSTITUTO NACIONAL",
                      "CAIXA ECONOMICA", "BANCO DO BRASIL", "UNIAO", "ESTADO DO", "MUNICIPIO", "CAMARA", "ASSEMBLEIA",
                      "DEFENSORIA", "PROCURADORIA", "GOVERNO", "FUNDACAO ", "RECEITA FEDERAL", "INSS", "TESOURO")

    @classmethod
    def _eh_ente_publico(cls, nome: str | None) -> bool:
        import unicodedata
        n = unicodedata.normalize("NFKD", (nome or "").upper()).encode("ascii", "ignore").decode()
        return n.startswith(cls._PREFIXOS_ENTE)

    def _regra_ob_fracionamento(self):
        """
        Fracionamento de pagamentos via OB: mesmo favorecido recebe múltiplos
        pagamentos em 30 dias cujo total ultrapassa o limite de dispensa de
        licitação do EXERCÍCIO (Lei 14.133/21 art. 75, corrigido por decreto anual).

        Padrão clássico para burlar obrigação de licitar.

        O teto estava congelado em R$ 50.000 — o valor original de 2021 — aplicado a todos os
        anos. Era mais uma cópia divergente da tabela que `limites_dispensa.py` centraliza: em
        2026 o teto de compras é R$ 65.492,11, ou seja, a regra acusava fracionamento em grupos
        até 31% abaixo do limite legal, com severidade "alta".
        """
        # O SQL não sabe o exercício de cada grupo, então filtra pelo MENOR teto conhecido (piso
        # que não descarta nada) e o enquadramento exato é feito no laço, ano a ano.
        LIMITE_DISPENSA = min(float(LIMITES[a]["compras"]) for a in LIMITES)

        # Janela de ~30 dias aproximada pelo mês-calendário (strftime no group_by).
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
                OrdemBancaria.data_emissao >= self._desde(),
            )
            .group_by(
                OrdemBancaria.favorecido_cpf,
                OrdemBancaria.ug_codigo,
                func.strftime("%Y-%m", OrdemBancaria.data_emissao),
            )
            .having(
                func.count(OrdemBancaria.id) >= 2,
                func.sum(OrdemBancaria.valor) > LIMITE_DISPENSA,
            )
            # sem janela e sem teto esta regra gravou 68.893 alertas "alta" numa execução (10/09) —
            # o painel lista os 40 mais novos: o resto vira ruído que enterra os alertas de verdade
            .order_by(func.sum(OrdemBancaria.valor).desc())
            .limit(100)
            .all()
        )

        for row in subq:
            if self._eh_ente_publico(row.favorecido_nome):
                continue
            exercicio = getattr(row.data_ini, "year", None) or _date.today().year
            teto = limite_dispensa(exercicio, "compras")
            if row.total <= teto:
                continue
            empresa = (
                self.session.query(Empresa).filter_by(cnpj=row.favorecido_cpf).first()
                if row.favorecido_cpf else None
            )
            self._lote.criar(
                tipo       = "fracionamento",
                severidade = "média",   # soma mensal > teto de dispensa com 2+ OBs é INDÍCIO fraco; o detector de verdade é o P4/pcrj_d7
                titulo     = f"Fracionamento OB — {row.favorecido_nome or row.favorecido_cpf} / UG {row.ug_codigo}",
                descricao  = (
                    f"{row.n_obs} OBs para '{row.favorecido_nome}' (CPF/CNPJ {row.favorecido_cpf}) "
                    f"na UG {row.ug_codigo} totalizaram R$ {moeda(row.total)} "
                    f"entre {row.data_ini} e {row.data_fim}. "
                    f"Valor ultrapassa o limite de dispensa de {exercicio} "
                    f"(R$ {moeda(teto)} — {ato_normativo(exercicio)}), "
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
                    "exercicio": exercicio,
                    "limite_dispensa": teto,
                    "limite_dispensa_ato": ato_normativo(exercicio),
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
                OrdemBancaria.data_emissao >= self._desde(),
            )
            .order_by(OrdemBancaria.valor.desc())
            .limit(self.TETO_CANDIDATOS)
            .all()
        )

        for ob in obs_sem_sei:
            self._lote.criar(
                tipo            = "ob_sem_processo",
                severidade      = "média",
                titulo          = f"OB sem processo SEI — R$ {moeda(ob.valor)} para {ob.favorecido_nome or ob.favorecido_cpf}",
                descricao       = (
                    f"OB nº {ob.numero_ob} (UG {ob.ug_codigo}, {ob.data_emissao}) "
                    f"no valor de R$ {moeda(ob.valor)} para '{ob.favorecido_nome}' "
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
                OrdemBancaria.data_emissao >= self._desde(),
            )
            .group_by(
                OrdemBancaria.favorecido_cpf,
                func.strftime("%Y-%m", OrdemBancaria.data_emissao),
            )
            .having(func.count(func.distinct(OrdemBancaria.ug_codigo)) >= 3)
            # 16.336 alertas numa execução sem janela (10/09) — ver _regra_ob_fracionamento
            .order_by(func.sum(OrdemBancaria.valor).desc())
            .limit(50)
            .all()
        )

        for row in resultados:
            if self._eh_ente_publico(row.favorecido_nome):
                continue
            empresa = (
                self.session.query(Empresa).filter_by(cnpj=row.favorecido_cpf).first()
                if row.favorecido_cpf else None
            )
            fato = (f"'{row.favorecido_nome}' (CPF/CNPJ {row.favorecido_cpf}) recebeu OBs de "
                    f"{row.n_ugs} UGs diferentes em {row.mes}, totalizando R$ {moeda(row.total)}. "
                    f"UGs: {row.ugs}. ")
            # Credor institucional (concessionária, estatal, S.A. aberta, previdência dos servidores) recebe de
            # várias UGs por natureza: 107 de 230 triagens desta regra eram falso positivo (20/11/2026). O alerta
            # fica como rastro, mas declara que não acusa — a triagem pula o prefixo "NÃO é acusação".
            inst = institucional(row.favorecido_cpf)
            if inst["institucional"]:
                descricao = (f"NÃO é acusação — credor institucional: {inst['motivo']}; receber de várias UGs "
                             f"é esperado. " + fato)
            else:
                descricao = fato + "Padrão atípico — favorecido possivelmente 'carimbado' em todo o estado."
            self._lote.criar(
                tipo       = "direcionamento",
                severidade = "baixa",   # fornecedor grande atende várias UGs; só vira notícia com outro sinal
                titulo     = f"Favorecido em {row.n_ugs} UGs distintas — {row.favorecido_nome or row.favorecido_cpf} ({row.mes})",
                descricao  = descricao,
                evidencias = {
                    "favorecido_cpf": row.favorecido_cpf,
                    "favorecido_nome": row.favorecido_nome,
                    "mes": row.mes,
                    "n_ugs": row.n_ugs,
                    "ugs": row.ugs,
                    "total": row.total,
                    "credor_institucional": inst["motivo"] if inst["institucional"] else None,
                },
                empresa = empresa,
            )

    def _regra_ob_empresa_nova(self):
        """
        OB paga a empresa aberta há menos de DIAS_EMPRESA_NOVA dias.
        Cruza OrdemBancaria.favorecido_cpf com Empresa.cnpj e Empresa.data_abertura.
        """
        dias = func.julianday(OrdemBancaria.data_emissao) - func.julianday(Empresa.data_abertura)
        pares = (
            self.session.query(OrdemBancaria, Empresa)
            .join(Empresa, Empresa.cnpj == OrdemBancaria.favorecido_cpf)
            .filter(
                OrdemBancaria.favorecido_cpf.isnot(None),
                OrdemBancaria.valor > 0,
                OrdemBancaria.data_emissao >= self._desde(),
                Empresa.data_abertura.isnot(None),
                dias >= 0,
                dias < DIAS_EMPRESA_NOVA,
            )
            .order_by(OrdemBancaria.valor.desc())
            .limit(self.TETO_CANDIDATOS)
            .all()
        )

        for ob, empresa in pares:
            delta = (ob.data_emissao - empresa.data_abertura).days
            self._lote.criar(
                tipo            = "direcionamento",
                severidade      = "alta",
                titulo          = f"OB para empresa nova ({delta}d) — {empresa.razao_social}",
                descricao       = (
                    f"OB nº {ob.numero_ob} no valor de R$ {moeda(ob.valor)} foi paga a "
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
                OrdemBancaria.data_emissao >= self._desde(),
                # "redondo" decidido no SQL: múltiplo de 1000 sem centavos (valor em centavos % 100000)
                (func.cast(func.round(OrdemBancaria.valor * 100), Integer) % 100000) == 0,
            )
            .order_by(OrdemBancaria.valor.desc())
            .limit(self.TETO_CANDIDATOS)
            .all()
        )

        for ob in obs:
            self._lote.criar(
                tipo            = "ob_valor_atipico",
                severidade      = "baixa",
                titulo          = f"OB com valor exatamente redondo — R$ {ob.valor:,.0f} / {ob.favorecido_nome or ob.favorecido_cpf}",
                descricao       = (
                    f"OB nº {ob.numero_ob} (UG {ob.ug_codigo}, {ob.data_emissao}) tem "
                    f"valor exatamente redondo de R$ {moeda(ob.valor)} para "
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

        # Termo e favorecido têm de estar no MESMO ato e ligados entre si (ver doerj_casamento):
        # casar o nome num ato e 'multa' em outro ato do mesmo bloco do diário gerou 29/49 FP.
        from compliance_agent.rules.doerj_casamento import eh_orgao_publico, ocorrencias

        # Um favorecido por vez (não uma OB por vez): os 100 maiores da janela. O casamento com o
        # D.O. usa `cnpjs_extraidos` (coluna curta, já minerada), nunca ILIKE no `texto` de 500 mil
        # caracteres por edição — era 1,18 milhão de OBs × 39 mil páginas.
        favorecidos = (
            self.session.query(OrdemBancaria.favorecido_cpf, func.sum(OrdemBancaria.valor).label("total"))
            .filter(
                OrdemBancaria.favorecido_nome.isnot(None),
                OrdemBancaria.favorecido_cpf.isnot(None),
                OrdemBancaria.valor > 1000,
                OrdemBancaria.data_emissao >= self._desde(),
            )
            .group_by(OrdemBancaria.favorecido_cpf)
            .order_by(func.sum(OrdemBancaria.valor).desc())
            .limit(100)
            .all()
        )

        for cpf_cnpj, _total in favorecidos:
            cpf_cnpj = (cpf_cnpj or "").strip()
            if len(cpf_cnpj) != 14 or not cpf_cnpj.isdigit():
                continue   # CPF (mascarado ou não) não se cruza com o D.O. por número
            ob = (
                self.session.query(OrdemBancaria)
                .filter(OrdemBancaria.favorecido_cpf == cpf_cnpj, OrdemBancaria.data_emissao >= self._desde())
                .order_by(OrdemBancaria.valor.desc())
                .first()
            )
            if ob is None:
                continue
            nome = (ob.favorecido_nome or "").strip()
            if len(nome) < 5 or eh_orgao_publico(nome):
                continue  # o próprio ente (Secretaria etc.) não é fornecedor sancionável

            doerj_hits = (
                self.session.query(PublicacaoDOERJ)
                .filter(PublicacaoDOERJ.cnpjs_extraidos.like(f"%{cpf_cnpj}%"))
                .order_by(PublicacaoDOERJ.data_publicacao.desc())
                .limit(5)
                .all()
            )

            if not doerj_hits:
                continue

            # Todas as ocorrências (termo ligado ao favorecido no mesmo ato) — nenhuma é cortada:
            # antes parava no 1º termo de cada publicação e o contado não batia com o exibido.
            suspeitos = []
            for hit in doerj_hits:
                for oc in ocorrencias(hit.texto or "", nome, cpf_cnpj):
                    suspeitos.append({
                        "publicacao_id": hit.id,
                        "data": str(hit.data_publicacao),
                        "tipo_ato": hit.tipo_ato,
                        "titulo": hit.titulo,
                        "termo_suspeito": oc["termo"],
                        "criterio": oc["criterio"],
                        "trecho": oc["trecho"],
                    })

            if suspeitos:
                n_pubs = len({s["publicacao_id"] for s in suspeitos})
                self._lote.criar(
                    tipo            = "doerj_anomalia",
                    severidade      = "alta",
                    titulo          = f"OB para favorecido com publicação suspeita no DOERJ — {nome}",
                    descricao       = (
                        f"OB nº {ob.numero_ob} (R$ {moeda(ob.valor)}, UG {ob.ug_codigo}) "
                        f"tem como favorecido '{nome}', citado em {n_pubs} "
                        f"publicação(ões) do DOERJ com termo de risco no MESMO ato que o cita: "
                        f"{sorted({s['termo_suspeito'] for s in suspeitos})} "
                        f"({len(suspeitos)} ocorrência(s), trechos na evidência). "
                        f"Indício, não acusação: verificar se os pagamentos são compatíveis com o "
                        f"status do favorecido."
                    ),
                    evidencias      = {
                        "numero_ob": ob.numero_ob,
                        "valor": ob.valor,
                        "favorecido": nome,
                        "cpf_cnpj": cpf_cnpj,
                        "doerj_suspeitos": suspeitos,
                        "doerj_total_ocorrencias": len(suspeitos),
                        "doerj_total_hits": len(doerj_hits),
                        "doerj_publicacoes_consultadas": [
                            {"publicacao_id": h.id, "data": str(h.data_publicacao),
                             "titulo": h.titulo}
                            for h in doerj_hits
                        ],
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
