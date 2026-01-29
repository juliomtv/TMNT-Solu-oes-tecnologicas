import sqlite3
import os

def migrate():
    # O caminho do banco de dados no ambiente do usuário parece ser instance/barbearia.db
    db_path = 'instance/barbearia.db'
    
    if not os.path.exists(db_path):
        print(f"Banco de dados não encontrado em {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Verifica colunas existentes
    cursor.execute("PRAGMA table_info(configuracao)")
    columns = [column[1] for column in cursor.fetchall()]
    
    if 'ativo' not in columns:
        print("Adicionando coluna 'ativo' à tabela 'configuracao'...")
        try:
            cursor.execute("ALTER TABLE configuracao ADD COLUMN ativo BOOLEAN DEFAULT 1")
            conn.commit()
            print("Coluna 'ativo' adicionada com sucesso!")
        except Exception as e:
            print(f"Erro ao adicionar coluna: {e}")
    else:
        print("A coluna 'ativo' já existe.")
    
    conn.close()

if __name__ == "__main__":
    migrate()
