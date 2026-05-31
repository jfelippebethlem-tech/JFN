"""
Database models for the compliance agent.

Uses SQLite via SQLAlchemy. All public-servant, company, contract,
payroll, and relationship data is stored here before graph analysis.
"""

from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Float, Date, DateTime, Boolean,
    Text, ForeignKey, Index, create_engine, event
)
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker
from pathlib import Path


DB_PATH = Path(__file__).parent.parent.parent / "data" / "compliance.db"


class Base(DeclarativeBase):
    pass


# ── Pessoas (servidores, políticos, sócios de empresa) ────────────────────────

class Pessoa(Base):
    __tablename__ = "pessoas"

    id          = Column(Integer, primary_key=True)
    cpf         = Column(String(11), unique=True, index=True)
    nome        = Column(String(200), nullable=False, index=True)
    nome_mae    = Column(String(200))
    data_nasc   = Column(Date)
    tipo        = Column(String(30))   # servidor | político | sócio | parente
    cargo       = Column(String(200))
    orgao       = Column(String(200))
    matricula   = Column(String(50))
    ativo       = Column(Boolean, default=True)
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    registros_folha  = relationship("RegistroFolha",  back_populates="pessoa")
    empresas_socias  = relationship("EmpresaSocio",   back_populates="pessoa")
    alertas          = relationship("Alerta",         back_populates="pessoa")

    def __repr__(self):
        return f"<Pessoa {self.nome} CPF={self.cpf}>"


class Relacionamento(Base):
    """Grafo de relacionamentos entre pessoas."""
    __tablename__ = "relacionamentos"

    id          = Column(Integer, primary_key=True)
    pessoa_a_id = Column(Integer, ForeignKey("pessoas.id"), nullable=False)
    pessoa_b_id = Column(Integer, ForeignKey("pessoas.id"), nullable=False)
    tipo        = Column(String(50))   # parente | sócio | cônjuge | indicado | contratante
    descricao   = Column(Text)
    fonte       = Column(String(100))  # DOERJ | CNPJ | folha | SEI
    data_inicio = Column(Date)
    data_fim    = Column(Date)
    created_at  = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_rel_ab", "pessoa_a_id", "pessoa_b_id"),
    )


# ── Empresas ──────────────────────────────────────────────────────────────────

class Empresa(Base):
    __tablename__ = "empresas"

    id              = Column(Integer, primary_key=True)
    cnpj            = Column(String(14), unique=True, index=True)
    razao_social    = Column(String(300), nullable=False, index=True)
    nome_fantasia   = Column(String(300))
    situacao        = Column(String(50))   # ATIVA | BAIXADA | SUSPENSA
    data_abertura   = Column(Date)
    porte           = Column(String(50))
    natureza_jur    = Column(String(100))
    atividade_princ = Column(String(200))
    cep             = Column(String(8))
    municipio       = Column(String(100))
    uf              = Column(String(2))
    capital_social  = Column(Float)
    raw_json        = Column(Text)   # resposta completa da BrasilAPI
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    socios    = relationship("EmpresaSocio",  back_populates="empresa")
    contratos = relationship("Contrato",      back_populates="empresa")
    alertas   = relationship("Alerta",        back_populates="empresa")


class EmpresaSocio(Base):
    __tablename__ = "empresa_socios"

    id         = Column(Integer, primary_key=True)
    empresa_id = Column(Integer, ForeignKey("empresas.id"), nullable=False)
    pessoa_id  = Column(Integer, ForeignKey("pessoas.id"))
    cpf_cnpj   = Column(String(14))
    nome       = Column(String(200))
    qualific   = Column(String(100))   # sócio-adm | representante | etc.
    data_entrada = Column(Date)

    empresa = relationship("Empresa",  back_populates="socios")
    pessoa  = relationship("Pessoa",   back_populates="empresas_socias")


# ── Folha de pagamento ────────────────────────────────────────────────────────

class RegistroFolha(Base):
    __tablename__ = "registros_folha"

    id              = Column(Integer, primary_key=True)
    pessoa_id       = Column(Integer, ForeignKey("pessoas.id"), index=True)
    cpf             = Column(String(11), index=True)
    nome            = Column(String(200))
    orgao_codigo    = Column(String(20))
    orgao_nome      = Column(String(200))
    cargo           = Column(String(200))
    vinculo         = Column(String(50))   # efetivo | comissionado | estagiário
    competencia     = Column(String(7))    # AAAA-MM
    remuneracao_bruta = Column(Float)
    remuneracao_liquida = Column(Float)
    abonos          = Column(Float, default=0)
    descontos       = Column(Float, default=0)
    fonte           = Column(String(50))   # transparencia_rj | siafe
    created_at      = Column(DateTime, default=datetime.utcnow)

    pessoa = relationship("Pessoa", back_populates="registros_folha")

    __table_args__ = (
        Index("ix_folha_cpf_comp", "cpf", "competencia"),
    )


# ── Contratos e licitações ─────────────────────────────────────────────────────

class Contrato(Base):
    __tablename__ = "contratos"

    id              = Column(Integer, primary_key=True)
    numero          = Column(String(100), index=True)
    objeto          = Column(Text)
    empresa_id      = Column(Integer, ForeignKey("empresas.id"))
    orgao_contrat   = Column(String(200))
    modalidade      = Column(String(50))   # pregão | concorrência | dispensa | inexigível
    valor_estimado  = Column(Float)
    valor_total     = Column(Float)
    data_assinatura = Column(Date)
    data_inicio     = Column(Date)
    data_fim        = Column(Date)
    numero_sei      = Column(String(50), index=True)
    numero_processo = Column(String(50))
    edital_url      = Column(Text)
    status          = Column(String(50))
    fonte           = Column(String(50))
    created_at      = Column(DateTime, default=datetime.utcnow)

    empresa = relationship("Empresa", back_populates="contratos")
    alertas = relationship("Alerta",  back_populates="contrato")


# ── DOERJ — publicações diárias ───────────────────────────────────────────────

class PublicacaoDOERJ(Base):
    __tablename__ = "publicacoes_doerj"

    id              = Column(Integer, primary_key=True)
    data_publicacao = Column(Date, nullable=False, index=True)
    edicao          = Column(String(20))
    secao           = Column(String(10))   # 1 | 2 | 3 | 4E
    orgao           = Column(String(200))
    tipo_ato        = Column(String(100))  # nomeação | exoneração | contrato | licitação
    titulo          = Column(String(500))
    texto           = Column(Text)
    cpfs_extraidos  = Column(Text)   # JSON list de CPFs encontrados no texto
    cnpjs_extraidos = Column(Text)   # JSON list de CNPJs
    url_fonte       = Column(Text)
    processado      = Column(Boolean, default=False)
    created_at      = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_doerj_data_tipo", "data_publicacao", "tipo_ato"),
    )


# ── SEI — processos ───────────────────────────────────────────────────────────

class ProcessoSEI(Base):
    __tablename__ = "processos_sei"

    id              = Column(Integer, primary_key=True)
    numero_sei      = Column(String(50), unique=True, index=True)
    tipo            = Column(String(100))
    assunto         = Column(Text)
    orgao_origem    = Column(String(200))
    interessado     = Column(String(200))
    data_abertura   = Column(Date)
    status          = Column(String(50))
    nivel_acesso    = Column(String(20))   # público | restrito | sigiloso
    documentos      = Column(Text)   # JSON list
    created_at      = Column(DateTime, default=datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    alertas = relationship("Alerta", back_populates="processo_sei")


# ── Alertas ───────────────────────────────────────────────────────────────────

class Alerta(Base):
    __tablename__ = "alertas"

    id              = Column(Integer, primary_key=True)
    tipo            = Column(String(100), nullable=False, index=True)
    # Tipos: fantasma | nepotismo | fracionamento | direcionamento | acumulacao
    #        enriquecimento | nomeacao_suspeita | contrato_parente | doerj_anomalia
    severidade      = Column(String(20))   # alta | média | baixa
    titulo          = Column(String(300))
    descricao       = Column(Text)
    evidencias      = Column(Text)   # JSON com lista de evidências
    status          = Column(String(20), default="novo")   # novo | investigando | descartado
    pessoa_id       = Column(Integer, ForeignKey("pessoas.id"))
    empresa_id      = Column(Integer, ForeignKey("empresas.id"))
    contrato_id     = Column(Integer, ForeignKey("contratos.id"))
    processo_sei_id = Column(Integer, ForeignKey("processos_sei.id"))
    data_referencia = Column(Date)
    created_at      = Column(DateTime, default=datetime.utcnow)

    pessoa       = relationship("Pessoa",      back_populates="alertas")
    empresa      = relationship("Empresa",     back_populates="alertas")
    contrato     = relationship("Contrato",    back_populates="alertas")
    processo_sei = relationship("ProcessoSEI", back_populates="alertas")

    __table_args__ = (
        Index("ix_alertas_tipo_sev", "tipo", "severidade"),
    )


# ── Doações eleitorais (TSE) ──────────────────────────────────────────────────

class DoacaoEleitoral(Base):
    __tablename__ = "doacoes_eleitorais"

    id               = Column(Integer, primary_key=True)
    cpf_cnpj_doador  = Column(String(14), index=True)
    nome_doador      = Column(String(300))
    nome_candidato   = Column(String(300))
    cargo_candidato  = Column(String(100))
    partido          = Column(String(20))
    uf               = Column(String(2))
    valor            = Column(Float)
    data_doacao      = Column(Date)
    ano_eleicao      = Column(Integer, index=True)
    created_at       = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_doacao_cpfcnpj_ano", "cpf_cnpj_doador", "ano_eleicao"),
    )


# ── Decisões do TCE-RJ ────────────────────────────────────────────────────────

class DecisaoTCE(Base):
    __tablename__ = "decisoes_tce"

    id               = Column(Integer, primary_key=True)
    numero_acordao   = Column(String(50), unique=True, index=True)
    data_julgamento  = Column(Date)
    relator          = Column(String(200))
    ementa           = Column(Text)
    tipo_decisao     = Column(String(50))   # condenação | arquivamento | acórdão
    valor_debito     = Column(Float)
    cpfs_envolvidos  = Column(Text)         # JSON list
    cnpjs_envolvidos = Column(Text)         # JSON list
    url_fonte        = Column(Text)
    created_at       = Column(DateTime, default=datetime.utcnow)


# ── DB helpers ─────────────────────────────────────────────────────────────────

def get_engine(db_path: Path = DB_PATH):
    db_path.parent.mkdir(exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    # Enable WAL mode for concurrent reads
    @event.listens_for(engine, "connect")
    def set_wal(conn, _):
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
    return engine


def get_session(engine=None):
    if engine is None:
        engine = get_engine()
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def init_db(db_path: Path = DB_PATH):
    """Create all tables. Safe to call multiple times."""
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)
    return engine
