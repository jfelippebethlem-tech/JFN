
import json
from sqlalchemy import text
from sqlalchemy.orm import Session
from compliance_agent.database.models import OrdemBancaria

CATEGORIAS_OB = {
    "obras": ["obra", "reforma", "construção", "pavimentação", "calçamento", "engenharia", "edificação", "infra"],
    "alimentação": ["alimentação", "refeição", "marmita", "kit lanche", "merenda", "gêneros alimentícios", "aliment"],
    "veículos": ["veículo", "carro", "automóvel", "caminhão", "ônibus", "van", "ambulância", "viatura"],
    "combustível": ["combustível", "diesel", "gasolina", "etanol", "abastecimento"],
    "informática": ["computador", "notebook", "laptop", "servidor", "impressora", "informática", "ti ", "software"],
    "limpeza": ["limpeza", "higienização", "conservação", "faxina", "material de limpeza"],
    "saúde": ["medicamento", "remédio", "material hospitalar", "equipamento médico", "insumo médico", "hospitalar", "clínica"],
    "segurança": ["vigilância", "segurança", "monitoramento", "câmera", "cftv"],
    "consultoria": ["consultoria", "assessoria", "treinamento", "capacitação", "curso"],
    "mobiliário": ["móvel", "cadeira", "mesa", "armário", "arquivo", "estante"],
    "telefonia": ["telefonia", "internet", "link dedicado", "banda larga", "telecomunicação"],
    "transporte": ["transporte", "fretamento", "passagem", "locomoção", "translado"],
}

def _categorizar_ob(ob) -> str:
    if not ob.favorecido_nome and not ob.raw_json:
        return "outros"

    texto = " ".join(filter(None, [ob.favorecido_nome or "", ob.observacao or "", ob.raw_json or ""])).lower()

    for cat, keywords in CATEGORIAS_OB.items():
        for kw in keywords:
            if kw in texto:
                return cat
    return "outros"

def upgrade(session: Session):
    print("Executando migração: 002_categorize_ordens_bancarias")
    try:
        session.execute(text("ALTER TABLE ordens_bancarias ADD COLUMN categoria VARCHAR(50)"))
        session.commit()
    except Exception:
        session.rollback()
        # Coluna já existe ou banco temporariamente indisponível; seguimos

    updated = 0
    for ob in session.query(OrdemBancaria).all():
        cat = _categorizar_ob(ob)
        if ob.categoria != cat:
            ob.categoria = cat
            session.add(ob)
            updated += 1
    session.commit()
    print(f"Migração 002 concluída. {updated} OBs categorizadas.")

def downgrade(session: Session):
    print("Revertendo migração: 002_categorize_ordens_bancarias")
    session.query(OrdemBancaria).update({OrdemBancaria.categoria: None})
    session.commit()
