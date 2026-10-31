from flask import Flask, render_template, request, redirect, url_for, session, send_file, jsonify
import sqlite3
import csv
import io
import os
import shutil
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = 'jallcard_secret_key_dash'

# ==========================================
# ROTINAS DE BACKUP E INICIALIZAÇÃO
# ==========================================
def gerenciar_backup_automatico():
    backup_dir = 'backups'
    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir)
        
    backups = [os.path.join(backup_dir, f) for f in os.listdir(backup_dir) if f.startswith('producao_')]
    fazer_backup = True
    if backups:
        ultimo_backup = max(backups, key=os.path.getmtime)
        data_ultimo_backup = datetime.fromtimestamp(os.path.getmtime(ultimo_backup))
        if datetime.now() - data_ultimo_backup < timedelta(days=3):
            fazer_backup = False
            
    if fazer_backup and os.path.exists('producao.db'):
        data_str = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        destino = os.path.join(backup_dir, f'producao_{data_str}.db')
        shutil.copy('producao.db', destino)
        limpar_backups_antigos(backup_dir, manter=10)

def limpar_backups_antigos(backup_dir, manter=10):
    backups = sorted([os.path.join(backup_dir, f) for f in os.listdir(backup_dir) if f.startswith('producao_')], key=os.path.getmtime)
    if len(backups) > manter:
        for antigo in backups[:-manter]:
            try:
                os.remove(antigo)
            except Exception:
                pass

def init_db():
    gerenciar_backup_automatico()
    conexao = sqlite3.connect('producao.db')
    cursor = conexao.cursor()
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL, login TEXT UNIQUE NOT NULL, senha TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0, acesso_gravacao INTEGER DEFAULT 0, acesso_impressao INTEGER DEFAULT 0,
            acesso_insertadora INTEGER DEFAULT 0, acesso_manuseio INTEGER DEFAULT 0, acesso_pre_expedicao INTEGER DEFAULT 0, nome_usuario TEXT)''')
    
    try: cursor.execute("ALTER TABLE usuarios ADD COLUMN primeiro_acesso INTEGER DEFAULT 1")
    except sqlite3.OperationalError: pass
    try: cursor.execute("ALTER TABLE usuarios ADD COLUMN tentativas_falhas INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass
    try: cursor.execute("ALTER TABLE usuarios ADD COLUMN bloqueado INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass
    
    # NOVA COLUNA: Avatar do utilizador
    try: cursor.execute("ALTER TABLE usuarios ADD COLUMN avatar TEXT DEFAULT '👤'")
    except sqlite3.OperationalError: pass
        
    cursor.execute('''CREATE TABLE IF NOT EXISTS maquinas (id INTEGER PRIMARY KEY AUTOINCREMENT, setor TEXT NOT NULL, nome TEXT NOT NULL)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS producao_geral (
            id INTEGER PRIMARY KEY AUTOINCREMENT, data_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP, turno TEXT NOT NULL,
            setor TEXT NOT NULL, maquina TEXT NOT NULL, quantidade INTEGER NOT NULL, usuario_id INTEGER,
            FOREIGN KEY(usuario_id) REFERENCES usuarios(id))''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS producao_manuseio (
            id INTEGER PRIMARY KEY AUTOINCREMENT, data_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP, turno TEXT NOT NULL,
            op TEXT NOT NULL, hora_inicio TEXT, hora_fim TEXT, envelopado INTEGER DEFAULT 0, auditado INTEGER DEFAULT 0,
            usuario_id INTEGER, usuario_id_2 INTEGER, FOREIGN KEY(usuario_id) REFERENCES usuarios(id), FOREIGN KEY(usuario_id_2) REFERENCES usuarios(id))''')

    cursor.execute('''INSERT INTO usuarios (nome, login, senha, is_admin, acesso_gravacao, acesso_impressao, acesso_insertadora, acesso_manuseio, acesso_pre_expedicao, nome_usuario, primeiro_acesso)
        VALUES ('Administrador', 'admin', 'admin', 1, 1, 1, 1, 1, 1, 'Administrador', 0) ON CONFLICT(login) DO UPDATE SET 
        senha='admin', is_admin=1, acesso_gravacao=1, acesso_impressao=1, acesso_insertadora=1, acesso_manuseio=1, acesso_pre_expedicao=1, primeiro_acesso=0, bloqueado=0, tentativas_falhas=0''')

    conexao.commit()
    conexao.close()

# ==========================================
# ROTAS DE AUTENTICAÇÃO E DASHBOARD
# ==========================================
@app.route('/')
def index():
    if 'id_usuario' in session: return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    erro = None
    if request.method == 'POST':
        username = request.form.get('usuario') or request.form.get('login')
        password = request.form.get('senha')
        
        conexao = sqlite3.connect('producao.db')
        conexao.row_factory = sqlite3.Row
        cursor = conexao.cursor()
        cursor.execute('SELECT * FROM usuarios WHERE LOWER(login) = LOWER(?)', (username,))
        user = cursor.fetchone()
        
        if user:
            bloqueado = user['bloqueado'] if 'bloqueado' in user.keys() else 0
            tentativas = user['tentativas_falhas'] if 'tentativas_falhas' in user.keys() else 0
            
            if bloqueado == 1:
                erro = 'Conta bloqueada por excesso de tentativas. Contacte o administrador.'
            elif str(user['senha']) == str(password):
                cursor.execute('UPDATE usuarios SET tentativas_falhas = 0 WHERE id = ?', (user['id'],))
                conexao.commit()
                
                session['id_usuario'] = user['id']
                session['login'] = user['login']
                session['nome_usuario'] = user['nome_usuario'] if 'nome_usuario' in user.keys() and user['nome_usuario'] else user['nome']
                # Carrega o avatar para a sessão
                session['avatar'] = user['avatar'] if 'avatar' in user.keys() and user['avatar'] else '👤'
                
                session['is_admin'] = user['is_admin'] or 0
                session['acesso_gravacao'] = user['acesso_gravacao'] or 0
                session['acesso_impressao'] = user['acesso_impressao'] or 0
                session['acesso_insertadora'] = user['acesso_insertadora'] or 0
                session['acesso_manuseio'] = user['acesso_manuseio'] or 0
                session['acesso_pre_expedicao'] = user['acesso_pre_expedicao'] or 0
                
                primeiro_acesso = user['primeiro_acesso'] if 'primeiro_acesso' in user.keys() else 0
                conexao.close()
                
                if primeiro_acesso == 1:
                    return redirect(url_for('mudar_senha'))
                return redirect(url_for('dashboard'))
            else:
                tentativas += 1
                if tentativas >= 5:
                    cursor.execute('UPDATE usuarios SET tentativas_falhas = ?, bloqueado = 1 WHERE id = ?', (tentativas, user['id']))
                    conexao.commit()
                    erro = 'Conta bloqueada! Excedeu as 5 tentativas.'
                else:
                    cursor.execute('UPDATE usuarios SET tentativas_falhas = ? WHERE id = ?', (tentativas, user['id']))
                    conexao.commit()
                    erro = f'Palavra-passe inválida. Tentativa {tentativas} de 5.'
        else:
            erro = 'Credenciais inválidas. Verifique o utilizador.'
            
        conexao.close()
    return render_template('login.html', erro=erro)

@app.route('/mudar_senha', methods=['GET', 'POST'])
def mudar_senha():
    if 'id_usuario' not in session: return redirect(url_for('login'))
    erro = None
    if request.method == 'POST':
        nova_senha = request.form.get('nova_senha')
        confirmar = request.form.get('confirmar_senha')
        if nova_senha != confirmar:
            erro = "As palavras-passe não coincidem. Tente novamente."
        elif len(nova_senha) < 4:
            erro = "A palavra-passe deve ter pelo menos 4 caracteres."
        else:
            conexao = sqlite3.connect('producao.db')
            cursor = conexao.cursor()
            cursor.execute('UPDATE usuarios SET senha = ?, primeiro_acesso = 0, tentativas_falhas = 0, bloqueado = 0 WHERE id = ?', (nova_senha, session['id_usuario']))
            conexao.commit()
            conexao.close()
            return redirect(url_for('dashboard'))
    return render_template('mudar_senha.html', erro=erro)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ==========================================
# ROTA DO PERFIL DO UTILIZADOR
# ==========================================
@app.route('/perfil', methods=['GET', 'POST'])
def perfil():
    if 'id_usuario' not in session: return redirect(url_for('login'))
    
    conexao = sqlite3.connect('producao.db')
    conexao.row_factory = sqlite3.Row
    cursor = conexao.cursor()
    
    mensagem = None
    erro = None
    
    if request.method == 'POST':
        acao = request.form.get('acao')
        
        if acao == 'atualizar_perfil':
            novo_nome = request.form.get('nome_usuario')
            novo_avatar = request.form.get('avatar')
            
            cursor.execute('UPDATE usuarios SET nome_usuario = ?, avatar = ? WHERE id = ?', (novo_nome, novo_avatar, session['id_usuario']))
            conexao.commit()
            
            # Atualiza a sessão para refletir as mudanças instantaneamente no menu
            session['nome_usuario'] = novo_nome
            session['avatar'] = novo_avatar
            mensagem = "Perfil atualizado com sucesso!"
            
        elif acao == 'mudar_senha':
            senha_atual = request.form.get('senha_atual')
            nova_senha = request.form.get('nova_senha')
            confirmar = request.form.get('confirmar_senha')
            
            cursor.execute('SELECT senha FROM usuarios WHERE id = ?', (session['id_usuario'],))
            user = cursor.fetchone()
            
            if str(user['senha']) != str(senha_atual):
                erro = "A palavra-passe atual está incorreta."
            elif nova_senha != confirmar:
                erro = "As novas palavras-passe não coincidem."
            elif len(nova_senha) < 4:
                erro = "A palavra-passe deve ter pelo menos 4 caracteres."
            else:
                cursor.execute('UPDATE usuarios SET senha = ? WHERE id = ?', (nova_senha, session['id_usuario']))
                conexao.commit()
                mensagem = "Palavra-passe alterada com sucesso!"
                
    cursor.execute('SELECT * FROM usuarios WHERE id = ?', (session['id_usuario'],))
    usuario_atual = cursor.fetchone()
    conexao.close()
    
    return render_template('perfil.html', usuario=usuario_atual, mensagem=mensagem, erro=erro)

# ==========================================
# DASHBOARD E ROTAS DA PRODUÇÃO...
# ==========================================
@app.route('/dashboard')
def dashboard():
    if 'id_usuario' not in session: return redirect(url_for('login'))
    
    data_inicio = request.args.get('data_inicio')
    data_fim = request.args.get('data_fim')
    filtro_setor = request.args.get('setor')
    filtro_turno = request.args.get('turno')
    
    conexao = sqlite3.connect('producao.db')
    cursor = conexao.cursor()
    
    query_tabela = '''
        SELECT DATE(data_registro) as data, turno, setor, SUM(quantidade) as total
        FROM (
            SELECT data_registro, turno, setor, quantidade FROM producao_geral
            UNION ALL
            SELECT data_registro, turno, 'Manuseio' as setor, (COALESCE(envelopado, 0) + COALESCE(auditado, 0)) as quantidade FROM producao_manuseio
        ) WHERE 1=1
    '''
    params_tabela = []
    
    if data_inicio:
        query_tabela += ' AND DATE(data_registro) >= ?'
        params_tabela.append(data_inicio)
    if data_fim:
        query_tabela += ' AND DATE(data_registro) <= ?'
        params_tabela.append(data_fim)
    if filtro_setor and filtro_setor != 'todos':
        query_tabela += ' AND setor = ?'
        params_tabela.append(filtro_setor)
    if filtro_turno and filtro_turno != 'todos':
        query_tabela += ' AND turno = ?'
        params_tabela.append(filtro_turno)
        
    query_tabela += ' GROUP BY DATE(data_registro), turno, setor ORDER BY data DESC, turno ASC, setor ASC'
    cursor.execute(query_tabela, params_tabela)
    tabela_resumo = cursor.fetchall()
    
    cursor.execute('''SELECT setor, SUM(quantidade) FROM (SELECT setor, quantidade FROM producao_geral UNION ALL
        SELECT 'Manuseio', (COALESCE(envelopado, 0) + COALESCE(auditado, 0)) FROM producao_manuseio) GROUP BY setor''')
    dados_grafico = cursor.fetchall()
    conexao.close()
    
    return render_template('dashboard.html', nome=session.get('nome_usuario'), is_admin=session.get('is_admin'),
                           tabela_resumo=tabela_resumo, labels_rosca=[l[0] for l in dados_grafico], valores_rosca=[l[1] for l in dados_grafico],
                           data_inicio=data_inicio, data_fim=data_fim, filtro_setor=filtro_setor, filtro_turno=filtro_turno)

def renderizar_setor(nome_setor, setor_db):
    conexao = sqlite3.connect('producao.db')
    conexao.row_factory = sqlite3.Row
    cursor = conexao.cursor()
    
    mensagem = None
    if request.method == 'POST':
        turno = request.form.get('turno')
        maquina = request.form.get('maquina')
        quantidade = request.form.get('quantidade')
        if turno and maquina and quantidade:
            cursor.execute('INSERT INTO producao_geral (turno, setor, maquina, quantidade, usuario_id) VALUES (?, ?, ?, ?, ?)',
                           (turno, setor_db, maquina, int(quantidade), session.get('id_usuario')))
            conexao.commit()
            mensagem = "Apontamento salvo com sucesso!"

    cursor.execute("SELECT nome FROM maquinas WHERE setor LIKE ?", (f"{setor_db}%",))
    lista_maquinas = [row['nome'] for row in cursor.fetchall()]
    
    cursor.execute('''
        SELECT p.id, p.turno, p.maquina, p.quantidade, p.usuario_id, COALESCE(u.nome_usuario, u.nome) 
        FROM producao_geral p 
        LEFT JOIN usuarios u ON p.usuario_id = u.id 
        WHERE p.setor = ? ORDER BY p.data_registro DESC LIMIT 15
    ''', (setor_db,))
    ultimos = cursor.fetchall()

    cursor.execute("SELECT SUM(quantidade) FROM producao_geral WHERE setor = ? AND date(data_registro) = date('now', 'localtime')", (setor_db,))
    total_hoje = cursor.fetchone()[0] or 0

    cursor.execute("SELECT maquina, SUM(quantidade) FROM producao_geral WHERE setor = ? AND strftime('%Y-%m', data_registro) = strftime('%Y-%m', 'now', 'localtime') GROUP BY maquina", (setor_db,))
    dados_maq = cursor.fetchall()
    
    cursor.execute("SELECT turno, SUM(quantidade) FROM producao_geral WHERE setor = ? AND strftime('%Y-%m', data_registro) = strftime('%Y-%m', 'now', 'localtime') GROUP BY turno", (setor_db,))
    dados_turno = cursor.fetchall()
    conexao.close()

    return render_template('apontamento.html', setor=nome_setor, mensagem=mensagem, lista_maquinas=lista_maquinas,
                           ultimos_lancamentos=ultimos, session_user_id=session.get('id_usuario'), is_admin=session.get('is_admin'),
                           total_hoje=total_hoje, labels_maq=[d[0] for d in dados_maq], valores_maq=[d[1] for d in dados_maq],
                           labels_turno=[d[0] for d in dados_turno], valores_turno=[d[1] for d in dados_turno])

@app.route('/gravacao', methods=['GET', 'POST'])
def gravacao():
    if 'id_usuario' not in session or (not session.get('acesso_gravacao') and not session.get('is_admin')): return redirect(url_for('dashboard'))
    return renderizar_setor('GRAVAÇÃO', 'Gravacao')

@app.route('/impressao', methods=['GET', 'POST'])
def impressao():
    if 'id_usuario' not in session or (not session.get('acesso_impressao') and not session.get('is_admin')): return redirect(url_for('dashboard'))
    return renderizar_setor('IMPRESSÃO', 'Impressao')

@app.route('/insertadora', methods=['GET', 'POST'])
def insertadora():
    if 'id_usuario' not in session or (not session.get('acesso_insertadora') and not session.get('is_admin')): return redirect(url_for('dashboard'))
    return renderizar_setor('INSERTADORA', 'Insertadora')

@app.route('/pre_expedicao', methods=['GET', 'POST'])
def pre_expedicao():
    if 'id_usuario' not in session or (not session.get('acesso_pre_expedicao') and not session.get('is_admin')): return redirect(url_for('dashboard'))
    conexao = sqlite3.connect('producao.db')
    cursor = conexao.cursor()
    mensagem = None
    if request.method == 'POST':
        turno = request.form.get('turno')
        quantidade = request.form.get('quantidade')
        if turno and quantidade:
            cursor.execute("INSERT INTO producao_geral (turno, setor, maquina, quantidade, usuario_id) VALUES (?, 'Pre-Expedicao', 'N/A', ?, ?)", 
                           (turno, int(quantidade), session.get('id_usuario')))
            conexao.commit()
            mensagem = "Lançamento salvo com sucesso!"
            
    cursor.execute('''
        SELECT p.id, p.turno, p.maquina, p.quantidade, p.usuario_id, COALESCE(u.nome_usuario, u.nome) 
        FROM producao_geral p 
        LEFT JOIN usuarios u ON p.usuario_id = u.id 
        WHERE p.setor = 'Pre-Expedicao' ORDER BY p.data_registro DESC LIMIT 15
    ''')
    ultimos = cursor.fetchall()
    
    cursor.execute("SELECT turno, SUM(quantidade) FROM producao_geral WHERE setor = 'Pre-Expedicao' AND strftime('%Y-%m', data_registro) = strftime('%Y-%m', 'now', 'localtime') GROUP BY turno")
    dados_turno = cursor.fetchall()
    conexao.close()
    
    return render_template('pre_expedicao.html', mensagem=mensagem, ultimos_lancamentos=ultimos, session_user_id=session.get('id_usuario'),
                           is_admin=session.get('is_admin'), labels_turno=[d[0] for d in dados_turno], valores_turno=[d[1] for d in dados_turno])

@app.route('/manuseio', methods=['GET'])
def manuseio_tela():
    if 'id_usuario' not in session or (not session.get('acesso_manuseio') and not session.get('is_admin')): return redirect(url_for('dashboard'))
    conexao = sqlite3.connect('producao.db')
    cursor = conexao.cursor()
    cursor.execute("SELECT turno, SUM(envelopado + auditado) FROM producao_manuseio WHERE strftime('%Y-%m', data_registro) = strftime('%Y-%m', 'now', 'localtime') GROUP BY turno")
    dados_turno = cursor.fetchall()
    
    cursor.execute('''SELECT COALESCE(u.nome_usuario, u.nome), SUM(t.qtd) as total FROM (
            SELECT usuario_id AS uid, (COALESCE(envelopado, 0) + COALESCE(auditado, 0)) AS qtd, data_registro FROM producao_manuseio
            UNION ALL
            SELECT usuario_id_2 AS uid, (COALESCE(envelopado, 0) + COALESCE(auditado, 0)) AS qtd, data_registro FROM producao_manuseio WHERE usuario_id_2 IS NOT NULL
        ) t JOIN usuarios u ON t.uid = u.id WHERE strftime('%Y-%m', t.data_registro) = strftime('%Y-%m', 'now', 'localtime') GROUP BY t.uid ORDER BY total DESC LIMIT 10''')
    top_op = cursor.fetchall()
    conexao.close()
    return render_template('manuseio.html', nome_usuario=session.get('nome_usuario'), labels_turno=[d[0] for d in dados_turno], 
                           valores_turno=[d[1] for d in dados_turno], top_operadores=top_op)

@app.route('/validar_dupla', methods=['POST'])
def validar_dupla():
    dados = request.get_json()
    conexao = sqlite3.connect('producao.db')
    conexao.row_factory = sqlite3.Row
    cursor = conexao.cursor()
    cursor.execute('SELECT id, nome_usuario, nome, bloqueado FROM usuarios WHERE LOWER(login) = LOWER(?) AND senha = ?', (dados.get('login'), dados.get('senha')))
    u = cursor.fetchone()
    conexao.close()
    
    if u:
        bloqueado = u['bloqueado'] if 'bloqueado' in u.keys() else 0
        if bloqueado == 1:
            return jsonify({'sucesso': False, 'erro': 'A conta desta dupla encontra-se bloqueada.'})
        return jsonify({'sucesso': True, 'nome': u['nome_usuario'] or u['nome'], 'id': u['id']})
    return jsonify({'sucesso': False, 'erro': 'Credenciais inválidas'})

@app.route('/salvar_manuseio', methods=['POST'])
def salvar_manuseio():
    if 'id_usuario' not in session: return jsonify({'sucesso': False, 'erro': 'Não autenticado'})
    dados = request.get_json()
    usuario_id_2 = None
    conexao = sqlite3.connect('producao.db')
    cursor = conexao.cursor()
    if dados.get('login_dupla') and dados.get('senha_dupla'):
        cursor.execute('SELECT id FROM usuarios WHERE LOWER(login) = LOWER(?) AND senha = ?', (dados.get('login_dupla'), dados.get('senha_dupla')))
        u2 = cursor.fetchone()
        if u2: usuario_id_2 = u2[0]
            
    for op in dados.get('ops', []):
        cursor.execute('''INSERT INTO producao_manuseio (turno, op, hora_inicio, hora_fim, envelopado, auditado, usuario_id, usuario_id_2)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', (dados.get('turno'), op['numero'], op['inicio'], op['fim'], op['envelopado'], op['auditado'], session.get('id_usuario'), usuario_id_2))
    conexao.commit()
    conexao.close()
    return jsonify({'sucesso': True})

@app.route('/editar_geral/<int:id>', methods=['POST'])
def editar_geral(id):
    if 'id_usuario' not in session: return redirect(url_for('login'))
    turno = request.form.get('turno')
    maquina = request.form.get('maquina') or 'N/A'
    quantidade = request.form.get('quantidade')
    if turno and quantidade:
        conexao = sqlite3.connect('producao.db')
        cursor = conexao.cursor()
        cursor.execute('UPDATE producao_geral SET turno = ?, maquina = ?, quantidade = ? WHERE id = ?', (turno, maquina, int(quantidade), id))
        conexao.commit()
        cursor.execute('SELECT setor FROM producao_geral WHERE id = ?', (id,))
        res = cursor.fetchone()
        conexao.close()
        if res:
            s = res[0].lower()
            if s == 'gravacao': return redirect(url_for('gravacao'))
            if s == 'impressao': return redirect(url_for('impressao'))
            if s == 'insertadora': return redirect(url_for('insertadora'))
            if s == 'pre-expedicao': return redirect(url_for('pre_expedicao'))
    return redirect(url_for('dashboard'))

@app.route('/excluir/<tipo>/<int:id_registro>', methods=['POST'])
def excluir(tipo, id_registro):
    if 'id_usuario' not in session or not session.get('is_admin'): return redirect(url_for('dashboard'))
    conexao = sqlite3.connect('producao.db')
    cursor = conexao.cursor()
    if tipo == 'geral': cursor.execute('DELETE FROM producao_geral WHERE id = ?', (id_registro,))
    elif tipo == 'manuseio': cursor.execute('DELETE FROM producao_manuseio WHERE id = ?', (id_registro,))
    conexao.commit()
    conexao.close()
    return redirect(url_for('auditoria'))

@app.route('/auditoria')
def auditoria():
    if 'id_usuario' not in session or not session.get('is_admin'): return redirect(url_for('dashboard'))
    conexao = sqlite3.connect('producao.db')
    conexao.row_factory = sqlite3.Row
    cursor = conexao.cursor()
    cursor.execute('''SELECT p.*, u.nome as operador FROM producao_geral p LEFT JOIN usuarios u ON p.usuario_id = u.id ORDER BY p.data_registro DESC LIMIT 30''')
    prod_geral = cursor.fetchall()
    cursor.execute('''SELECT m.*, u1.nome as operador, u2.nome as operador2 FROM producao_manuseio m 
        LEFT JOIN usuarios u1 ON m.usuario_id = u1.id LEFT JOIN usuarios u2 ON m.usuario_id_2 = u2.id ORDER BY m.data_registro DESC LIMIT 30''')
    prod_manuseio = cursor.fetchall()
    conexao.close()
    
    gravacao = [p for p in prod_geral if p['setor'] == 'Gravacao']
    impressao = [p for p in prod_geral if p['setor'] == 'Impressao']
    insertadora = [p for p in prod_geral if p['setor'] == 'Insertadora']
    pre = [p for p in prod_geral if p['setor'] == 'Pre-Expedicao']
    
    return render_template('auditoria.html', manuseio=prod_manuseio, gravacao=gravacao, impressao=impressao, insertadora=insertadora, pre_expedicao=pre)

@app.route('/usuarios', methods=['GET'])
def usuarios():
    if 'id_usuario' not in session or not session.get('is_admin'): return redirect(url_for('dashboard'))
    conexao = sqlite3.connect('producao.db')
    conexao.row_factory = sqlite3.Row
    cursor = conexao.cursor()
    cursor.execute('SELECT * FROM usuarios')
    lista = cursor.fetchall()
    conexao.close()
    return render_template('usuarios.html', usuarios=lista)

@app.route('/salvar_usuario', methods=['POST'])
def salvar_usuario():
    if 'id_usuario' not in session or not session.get('is_admin'): return redirect(url_for('dashboard'))
    conexao = sqlite3.connect('producao.db')
    cursor = conexao.cursor()
    cursor.execute('''INSERT INTO usuarios (nome, login, senha, is_admin, acesso_gravacao, acesso_impressao, acesso_insertadora, acesso_manuseio, acesso_pre_expedicao, nome_usuario, primeiro_acesso, tentativas_falhas, bloqueado, avatar)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0, 0, '👤')''', (request.form.get('nome'), request.form.get('login'), request.form.get('senha'),
        1 if request.form.get('is_admin') else 0, 1 if request.form.get('acesso_gravacao') else 0, 1 if request.form.get('acesso_impressao') else 0,
        1 if request.form.get('acesso_insertadora') else 0, 1 if request.form.get('acesso_manuseio') else 0, 1 if request.form.get('acesso_pre_expedicao') else 0, request.form.get('nome')))
    conexao.commit()
    conexao.close()
    return redirect(url_for('usuarios'))

@app.route('/editar_usuario/<int:id>', methods=['POST'])
def editar_usuario(id):
    if 'id_usuario' not in session or not session.get('is_admin'): return redirect(url_for('dashboard'))
    senha = request.form.get('senha')
    query = '''UPDATE usuarios SET nome=?, login=?, is_admin=?, acesso_gravacao=?, acesso_impressao=?, acesso_insertadora=?, acesso_manuseio=?, acesso_pre_expedicao=?'''
    params = [request.form.get('nome'), request.form.get('login'), 1 if request.form.get('is_admin') else 0, 1 if request.form.get('acesso_gravacao') else 0,
              1 if request.form.get('acesso_impressao') else 0, 1 if request.form.get('acesso_insertadora') else 0, 1 if request.form.get('acesso_manuseio') else 0, 1 if request.form.get('acesso_pre_expedicao') else 0]
    
    if senha:
        query += ', senha=?, primeiro_acesso=1'
        params.append(senha)
    
    query += ' WHERE id=?'
    params.append(id)
    
    conexao = sqlite3.connect('producao.db')
    cursor = conexao.cursor()
    cursor.execute(query, params)
    conexao.commit()
    conexao.close()
    return redirect(url_for('usuarios'))

@app.route('/excluir_usuario/<int:id_usuario>', methods=['POST'])
def excluir_usuario(id_usuario):
    if 'id_usuario' not in session or not session.get('is_admin'): return redirect(url_for('dashboard'))
    conexao = sqlite3.connect('producao.db')
    cursor = conexao.cursor()
    cursor.execute('DELETE FROM usuarios WHERE id = ?', (id_usuario,))
    conexao.commit()
    conexao.close()
    return redirect(url_for('usuarios'))

@app.route('/desbloquear_usuario/<int:id_usuario>', methods=['POST'])
def desbloquear_usuario(id_usuario):
    if 'id_usuario' not in session or not session.get('is_admin'): return redirect(url_for('dashboard'))
    conexao = sqlite3.connect('producao.db')
    cursor = conexao.cursor()
    cursor.execute('UPDATE usuarios SET senha = ?, primeiro_acesso = 1, bloqueado = 0, tentativas_falhas = 0 WHERE id = ?', ('1234', id_usuario))
    conexao.commit()
    conexao.close()
    return redirect(url_for('usuarios'))

@app.route('/maquinas', methods=['GET'])
def maquinas():
    if 'id_usuario' not in session or not session.get('is_admin'): return redirect(url_for('dashboard'))
    conexao = sqlite3.connect('producao.db')
    conexao.row_factory = sqlite3.Row
    cursor = conexao.cursor()
    cursor.execute('SELECT * FROM maquinas')
    lista = cursor.fetchall()
    conexao.close()
    return render_template('maquinas.html', maquinas=lista)

@app.route('/salvar_maquina', methods=['POST'])
def salvar_maquina():
    if 'id_usuario' not in session or not session.get('is_admin'): return redirect(url_for('dashboard'))
    conexao = sqlite3.connect('producao.db')
    cursor = conexao.cursor()
    cursor.execute('INSERT INTO maquinas (setor, nome) VALUES (?, ?)', (request.form.get('setor'), request.form.get('nome')))
    conexao.commit()
    conexao.close()
    return redirect(url_for('maquinas'))

@app.route('/excluir_maquina/<int:id>', methods=['POST'])
def excluir_maquina(id):
    if 'id_usuario' not in session or not session.get('is_admin'): return redirect(url_for('dashboard'))
    conexao = sqlite3.connect('producao.db')
    cursor = conexao.cursor()
    cursor.execute('DELETE FROM maquinas WHERE id = ?', (id,))
    conexao.commit()
    conexao.close()
    return redirect(url_for('maquinas'))

@app.route('/exportar')
def exportar():
    if 'id_usuario' not in session or not session.get('is_admin'): return redirect(url_for('dashboard'))
    return render_template('exportar.html')

@app.route('/baixar_relatorio')
def baixar_relatorio():
    if 'id_usuario' not in session or not session.get('is_admin'): return redirect(url_for('dashboard'))
    conexao = sqlite3.connect('producao.db')
    cursor = conexao.cursor()
    cursor.execute('''SELECT data_registro, setor, turno, maquina, quantidade, NULL, NULL FROM producao_geral UNION ALL
        SELECT data_registro, 'Manuseio', turno, 'OP: ' || op, NULL, envelopado, auditado FROM producao_manuseio ORDER BY data_registro DESC''')
    dados = cursor.fetchall()
    conexao.close()
    
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['Data e Hora', 'Setor', 'Turno', 'Máquina / OP', 'Quantidade Geral', 'Envelopado', 'Auditado'])
    cw.writerows(dados)
    
    output = io.BytesIO()
    output.write(si.getvalue().encode('utf-8'))
    output.seek(0)
    return send_file(output, mimetype='text/csv', as_attachment=True, download_name='relatorio_producao.csv')

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=False)