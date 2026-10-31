import sqlite3

# Conecta ao banco de dados
conn = sqlite3.connect('producao.db')
cursor = conn.cursor()

# Busca as informações da tabela usuarios (tente sem acento primeiro, se der erro coloque 'usuários')
cursor.execute("PRAGMA table_info(usuarios)")
colunas = cursor.fetchall()

print("As colunas da sua tabela são:")
for coluna in colunas:
    print(f"- {coluna[1]}")

conn.close()