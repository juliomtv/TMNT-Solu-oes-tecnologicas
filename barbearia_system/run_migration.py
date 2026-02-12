import sys
import os
from sqlalchemy import text

# Adiciona o diretório atual ao path para importar o app
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import app, db

def run_migration():
    print("Iniciando migração do banco de dados...")
    with app.app_context():
        # Lista de comandos para adicionar as colunas
        commands = [
            "ALTER TABLE configuracao ADD cor_primaria VARCHAR(7) DEFAULT '#0d6efd'",
            "ALTER TABLE configuracao ADD cor_secundaria VARCHAR(7) DEFAULT '#212529'",
            "UPDATE configuracao SET cor_primaria = '#0d6efd' WHERE cor_primaria IS NULL",
            "UPDATE configuracao SET cor_secundaria = '#212529' WHERE cor_secundaria IS NULL"
        ]
        
        for cmd in commands:
            try:
                print(f"Executando: {cmd}")
                db.session.execute(text(cmd))
                db.session.commit()
                print("Sucesso!")
            except Exception as e:
                db.session.rollback()
                # Erro 2705 no SQL Server significa que a coluna já existe
                if '2705' in str(e) or 'already exists' in str(e).lower():
                    print("A coluna já existe, pulando...")
                else:
                    print(f"Erro ao executar comando: {e}")
        
    print("Processo de migração finalizado.")

if __name__ == "__main__":
    run_migration()
