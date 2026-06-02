
import json
from sqlalchemy.orm import Session
from compliance_agent.database.models import OrdemBancaria

def upgrade(session: Session):
    print("Executando migração: 001_extract_raw_json_data")
    updated_count = 0
    for ob in session.query(OrdemBancaria).filter(OrdemBancaria.raw_json.isnot(None)):
        try:
            raw_data = json.loads(ob.raw_json)
            changed = False

            if not ob.ug_nome and raw_data.get("UG Emitente"):
                ob.ug_nome = raw_data["UG Emitente"]
                changed = True
            if not ob.ug_codigo and raw_data.get("UG Emitente"): # Assuming UG Emitente is the code for now
                ob.ug_codigo = raw_data["UG Emitente"]
                changed = True
            if not ob.favorecido_nome and raw_data.get("Nome do Credor"):
                ob.favorecido_nome = raw_data["Nome do Credor"]
                changed = True
            if not ob.valor and raw_data.get("Valor"):
                try:
                    # Remove dots, replace comma with dot for float conversion
                    ob.valor = float(raw_data["Valor"].replace(".", "").replace(",", "."))
                    changed = True
                except ValueError:
                    pass # Ignore if conversion fails
            if not ob.numero_processo and raw_data.get("Processo"):
                ob.numero_processo = raw_data["Processo"]
                changed = True
            if not ob.numero_sei and raw_data.get("SEI"):
                ob.numero_sei = raw_data["SEI"]
                changed = True
            
            if changed:
                session.add(ob)
                updated_count += 1
        except json.JSONDecodeError:
            print(f"Erro ao decodificar JSON para OB {ob.id}: {ob.raw_json[:100]}...")
            continue
    session.commit()
    print(f"Migração 001 concluída. {updated_count} Ordens Bancárias atualizadas.")

def downgrade(session: Session):
    print("Revertendo migração: 001_extract_raw_json_data (Não implementado para esta migração)")
    # Reversão não é crítica para este tipo de migração de dados enriquecidos
    pass
