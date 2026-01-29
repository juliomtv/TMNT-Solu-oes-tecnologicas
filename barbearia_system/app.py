from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os
import re
import unicodedata

app = Flask(__name__)
app.config['SECRET_KEY'] = 'chave-secreta-barbearia'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(app.instance_path, 'barbearia.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Configuração do Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login_global'

# Funções auxiliares
def slugify(text):
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')
    text = re.sub(r'[^\w\s-]', '', text).strip().lower()
    return re.sub(r'[-\s]+', '-', text)

def validar_senha(password):
    if len(password) < 6:
        return False, "A senha deve ter no mínimo 6 dígitos."
    if not any(c.isupper() for c in password):
        return False, "A senha deve conter pelo menos uma letra maiúscula."
    if not any(c.isdigit() for c in password):
        return False, "A senha deve conter pelo menos um número."
    return True, ""

# Modelos de Banco de Dados
class Configuracao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome_barbearia = db.Column(db.String(100), default='Minha Barbearia')
    slug = db.Column(db.String(100), unique=True, nullable=False)
    horario_abertura = db.Column(db.String(5), default='09:00')
    horario_fechamento = db.Column(db.String(5), default='19:00')
    intervalo_minutos = db.Column(db.Integer, default=30)
    fidelidade_ativa = db.Column(db.Boolean, default=True)
    fidelidade_cortes_necessarios = db.Column(db.Integer, default=10)
    notificacao_minutos = db.Column(db.Integer, default=15)
    ativo = db.Column(db.Boolean, default=True) # Quinta alteração: campo para habilitar/desabilitar
    
    usuarios = db.relationship('Usuario', backref='barbearia', lazy=True, cascade="all, delete-orphan")
    clientes = db.relationship('Cliente', backref='barbearia', lazy=True, cascade="all, delete-orphan")
    servicos = db.relationship('Servico', backref='barbearia', lazy=True, cascade="all, delete-orphan")

class Usuario(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=True)
    is_superadmin = db.Column(db.Boolean, default=False)
    barbearia_id = db.Column(db.Integer, db.ForeignKey('configuracao.id'), nullable=True)

class Cliente(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    telefone = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(100))
    cortes_realizados = db.Column(db.Integer, default=0)
    fidelidade_pontos = db.Column(db.Integer, default=0)
    barbearia_id = db.Column(db.Integer, db.ForeignKey('configuracao.id'), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    
    agendamentos = db.relationship('Agendamento', backref='cliente', lazy=True, cascade="all, delete-orphan")
    __table_args__ = (db.UniqueConstraint('telefone', 'barbearia_id', name='_telefone_barbearia_uc'),)

class Servico(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    preco = db.Column(db.Float, nullable=False)
    duracao = db.Column(db.Integer, default=30)
    barbearia_id = db.Column(db.Integer, db.ForeignKey('configuracao.id'), nullable=False)

class Agendamento(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    data_hora = db.Column(db.DateTime, nullable=False)
    cliente_id = db.Column(db.Integer, db.ForeignKey('cliente.id'), nullable=False)
    servico_id = db.Column(db.Integer, db.ForeignKey('servico.id'), nullable=False)
    status = db.Column(db.String(20), default='Pendente')
    barbearia_id = db.Column(db.Integer, db.ForeignKey('configuracao.id'), nullable=False)
    barbeiro_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=True)
    
    servico = db.relationship('Servico')
    barbeiro = db.relationship('Usuario')

class Fila(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cliente_nome = db.Column(db.String(100), nullable=False)
    whatsapp = db.Column(db.String(20))
    servico_id = db.Column(db.Integer, db.ForeignKey('servico.id'), nullable=False)
    barbearia_id = db.Column(db.Integer, db.ForeignKey('configuracao.id'), nullable=False)
    status = db.Column(db.String(20), default='aguardando') # aguardando, chamado, atendendo, finalizado, ausente
    posicao = db.Column(db.Integer)
    criado_em = db.Column(db.DateTime, default=datetime.now)
    barbeiro_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=True)
    
    servico = db.relationship('Servico')
    barbeiro = db.relationship('Usuario')

@login_manager.user_loader
def load_user(user_id):
    user_id_str = str(user_id)
    if user_id_str.startswith('u_'):
        return Usuario.query.get(int(user_id_str[2:]))
    elif user_id_str.startswith('c_'):
        return Cliente.query.get(int(user_id_str[2:]))
    
    user = Usuario.query.get(int(user_id))
    if user:
        return user
    return Cliente.query.get(int(user_id))

# Inicialização do Banco de Dados
with app.app_context():
    db.create_all()
    # Garantir que colunas novas existam em bancos de dados antigos
    try:
        with db.engine.connect() as conn:
            from sqlalchemy import text
            # Verifica se a coluna 'ativo' existe
            result = conn.execute(text("PRAGMA table_info(configuracao)"))
            columns = [row[1] for row in result]
            if 'ativo' not in columns:
                conn.execute(text("ALTER TABLE configuracao ADD COLUMN ativo BOOLEAN DEFAULT 1"))
                conn.commit()
    except Exception as e:
        print(f"Erro na migração automática: {e}")

    if not Usuario.query.filter_by(username='admin').first():
        admin = Usuario(
            username='admin',
            password=generate_password_hash('Admin123', method='pbkdf2:sha256'),
            is_admin=True,
            is_superadmin=True
        )
        db.session.add(admin)
        db.session.commit()

# --- ROTAS GLOBAIS ---
@app.route('/login_master', methods=['GET', 'POST'])
def login_global():
    if current_user.is_authenticated and getattr(current_user, 'is_superadmin', False):
        return redirect(url_for('index_root'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = Usuario.query.filter_by(username=username, is_superadmin=True).first()
        if user and check_password_hash(user.password, password):
            user.id = f"u_{user.id}"
            login_user(user)
            return redirect(url_for('index_root'))
        else:
            flash('Acesso negado. Apenas o desenvolvedor pode acessar esta área.', 'danger')
    return render_template('login_global.html')

@app.route('/')
@login_required
def index_root():
    if not getattr(current_user, 'is_superadmin', False):
        flash('Acesso restrito ao Super Admin.', 'danger')
        logout_user()
        return redirect(url_for('login_global'))
    barbearias = Configuracao.query.all()
    return render_template('index_global.html', barbearias=barbearias)

@app.route('/cadastrar_barbearia', methods=['GET', 'POST'])
@login_required
def cadastrar_barbearia():
    if not getattr(current_user, 'is_superadmin', False):
        flash('Apenas o Super Admin pode cadastrar novas barbearias.', 'danger')
        return redirect(url_for('index_root'))
        
    if request.method == 'POST':
        nome = request.form.get('nome')
        # Segunda alteração: slug automático
        slug = slugify(nome)
        username = request.form.get('username')
        password = request.form.get('password')
        
        # Quarta alteração: validação de senha
        valida, msg = validar_senha(password)
        if not valida:
            flash(msg, 'danger')
            return redirect(url_for('cadastrar_barbearia'))

        if Configuracao.query.filter_by(slug=slug).first():
            # Se o slug base já existe, adiciona um sufixo aleatório ou numérico
            slug = f"{slug}-{datetime.now().strftime('%H%M%S')}"
        
        if Usuario.query.filter_by(username=username).first():
            flash('Este nome de usuário já está em uso.', 'danger')
            return redirect(url_for('cadastrar_barbearia'))
            
        nova_barbearia = Configuracao(nome_barbearia=nome, slug=slug)
        db.session.add(nova_barbearia)
        db.session.flush()
        
        novo_admin = Usuario(
            username=username,
            password=generate_password_hash(password, method='pbkdf2:sha256'),
            is_admin=True,
            barbearia_id=nova_barbearia.id
        )
        
        servicos = [
            Servico(nome='Corte Masculino', preco=35.00, barbearia_id=nova_barbearia.id),
            Servico(nome='Barba', preco=25.00, barbearia_id=nova_barbearia.id),
            Servico(nome='Corte + Barba', preco=50.00, barbearia_id=nova_barbearia.id)
        ]
        
        db.session.add(novo_admin)
        db.session.bulk_save_objects(servicos)
        db.session.commit()
        
        flash('Barbearia cadastrada com sucesso!', 'success')
        return redirect(url_for('index_root'))
        
    return render_template('cadastrar_barbearia.html')

@app.route('/editar_barbearia/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_barbearia(id):
    if not getattr(current_user, 'is_superadmin', False):
        flash('Acesso negado.', 'danger')
        return redirect(url_for('index_root'))
    
    barbearia = Configuracao.query.get_or_404(id)
    if request.method == 'POST':
        barbearia.nome_barbearia = request.form.get('nome')
        barbearia.ativo = 'ativo' in request.form
        db.session.commit()
        flash('Barbearia atualizada com sucesso!', 'success')
        return redirect(url_for('index_root'))
    
    return render_template('cadastrar_barbearia.html', barbearia=barbearia)

@app.route('/excluir_barbearia/<int:id>')
@login_required
def excluir_barbearia(id):
    if not getattr(current_user, 'is_superadmin', False):
        flash('Acesso negado.', 'danger')
        return redirect(url_for('index_root'))
        
    barbearia = Configuracao.query.get_or_404(id)
    db.session.delete(barbearia)
    db.session.commit()
    flash(f'Barbearia {barbearia.nome_barbearia} excluída com sucesso.', 'success')
    return redirect(url_for('index_root'))

# --- API PARA VERIFICAR HORÁRIOS OCUPADOS ---
@app.route('/api/<slug>/horarios_ocupados')
def horarios_ocupados(slug):
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    data_str = request.args.get('data')
    if not data_str:
        return jsonify([])
    
    try:
        data_selecionada = datetime.strptime(data_str, '%Y-%m-%d').date()
    except:
        return jsonify([])

    agendamentos = Agendamento.query.filter(
        Agendamento.barbearia_id == config.id,
        db.func.date(Agendamento.data_hora) == data_selecionada,
        Agendamento.status.in_(['Pendente', 'Confirmado', 'Concluído'])
    ).all()
    
    horarios = [a.data_hora.strftime('%H:%M') for a in agendamentos]
    return jsonify(horarios)

@app.route('/api/<slug>/verificar_notificacoes')
def verificar_notificacoes(slug):
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    
    cliente_id = None
    if current_user.is_authenticated and not getattr(current_user, 'is_admin', False):
        cliente_id = current_user.id
    else:
        telefone = session.get('cliente_telefone')
        if telefone:
            cliente = Cliente.query.filter_by(telefone=telefone, barbearia_id=config.id).first()
            if cliente:
                cliente_id = cliente.id

    if cliente_id:
        agora = datetime.now()
        limite = agora + timedelta(minutes=config.notificacao_minutos)
        
        agendamento = Agendamento.query.filter(
            Agendamento.cliente_id == cliente_id,
            Agendamento.barbearia_id == config.id,
            Agendamento.data_hora > agora,
            Agendamento.data_hora <= limite,
            Agendamento.status == 'Confirmado'
        ).first()
        
        if agendamento:
            return jsonify({
                'notificar': True,
                'mensagem': f"Lembrete: Seu agendamento é às {agendamento.data_hora.strftime('%H:%M')}!"
            })
            
    return jsonify({'notificar': False})

# --- ROTAS DA BARBEARIA ---
@app.route('/<slug>')
def home_cliente(slug):
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    if not config.ativo:
        return "Esta barbearia está temporariamente desativada. Entre em contato com o administrador.", 403
    return render_template('cliente_home.html', config=config)

@app.route('/<slug>/login', methods=['GET', 'POST'])
def login_cliente(slug):
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    if request.method == 'POST':
        telefone = request.form.get('telefone')
        cliente = Cliente.query.filter_by(telefone=telefone, barbearia_id=config.id).first()
        if cliente:
            cliente.id = f"c_{cliente.id}"
            login_user(cliente)
            return redirect(url_for('painel_cliente', slug=slug))
        else:
            flash('Telefone não encontrado.', 'danger')
    return render_template('cliente_login.html', config=config)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index_root'))

@app.route('/<slug>/painel')
@login_required
def painel_cliente(slug):
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    if not hasattr(current_user, 'barbearia_id') or current_user.barbearia_id != config.id:
        logout_user()
        return redirect(url_for('login_cliente', slug=slug))
        
    agendamentos = Agendamento.query.filter_by(cliente_id=current_user.id).order_by(Agendamento.data_hora.desc()).all()
    return render_template('cliente_painel.html', agendamentos=agendamentos, config=config)

@app.route('/<slug>/agendamento/confirmacao/<int:agendamento_id>')
def agendamento_confirmacao(slug, agendamento_id):
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    agendamento = Agendamento.query.get_or_404(agendamento_id)
    return render_template('cliente_agendamento_status.html', agendamento=agendamento, config=config)

@app.route('/api/agendamento/status/<int:agendamento_id>')
def api_agendamento_status(agendamento_id):
    agendamento = Agendamento.query.get_or_404(agendamento_id)
    return jsonify({
        'status': agendamento.status,
        'data_hora': agendamento.data_hora.strftime('%d/%m/%Y %H:%M')
    })

@app.route('/<slug>/agendar', methods=['GET', 'POST'])
def agendar_cliente(slug):
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    if not config.ativo:
        flash('Esta barbearia está desativada.', 'danger')
        return redirect(url_for('index_root'))

    if request.method == 'POST':
        nome = request.form.get('nome')
        telefone = request.form.get('telefone')
        servico_id = request.form.get('servico_id')
        data = request.form.get('data')
        horario = request.form.get('horario')
        
        try:
            data_hora_str = f"{data} {horario}"
            data_hora = datetime.strptime(data_hora_str, '%Y-%m-%d %H:%M')
        except:
            flash('Data ou horário inválidos.', 'danger')
            return redirect(url_for('agendar_cliente', slug=slug))

        conflito = Agendamento.query.filter(
            Agendamento.barbearia_id == config.id,
            Agendamento.data_hora == data_hora,
            Agendamento.status.in_(['Pendente', 'Confirmado', 'Concluído'])
        ).first()
        
        if conflito:
            flash('Este horário já foi reservado. Por favor, escolha outro.', 'danger')
            return redirect(url_for('agendar_cliente', slug=slug))

        cliente = Cliente.query.filter_by(telefone=telefone, barbearia_id=config.id).first()
        if not cliente:
            cliente = Cliente(nome=nome, telefone=telefone, barbearia_id=config.id)
            db.session.add(cliente)
            db.session.flush()

        session['cliente_telefone'] = telefone

        barbeiro_id = request.form.get('barbeiro_id')
        if barbeiro_id == "": barbeiro_id = None
        
        novo = Agendamento(cliente_id=cliente.id, servico_id=servico_id, barbeiro_id=barbeiro_id, data_hora=data_hora, status='Pendente', barbearia_id=config.id)
        db.session.add(novo)
        db.session.commit()
        flash('Agendamento solicitado! Aguarde a confirmação do barbeiro.', 'success')
        
        session['cliente_telefone'] = telefone
        return redirect(url_for('agendamento_confirmacao', slug=slug, agendamento_id=novo.id))

    servicos = Servico.query.filter_by(barbearia_id=config.id).all()
    barbeiros = Usuario.query.filter_by(barbearia_id=config.id, is_admin=True).all()
    return render_template('cliente_agendar.html', servicos=servicos, barbeiros=barbeiros, config=config)

@app.route('/<slug>/admin')
@login_required
def index(slug):
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    if not getattr(current_user, 'is_admin', False) or (not current_user.is_superadmin and current_user.barbearia_id != config.id):
        return redirect(url_for('home_cliente', slug=slug))
        
    hoje = datetime.now().date()
    agendamentos_hoje = Agendamento.query.filter(
        Agendamento.barbearia_id == config.id,
        db.func.date(Agendamento.data_hora) == hoje
    ).order_by(Agendamento.data_hora).all()
    
    return render_template('index.html', agendamentos=agendamentos_hoje, config=config, datetime=datetime)

@app.route('/<slug>/admin/agendamentos')
@login_required
def listar_agendamentos(slug):
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    if not getattr(current_user, 'is_admin', False) or (not current_user.is_superadmin and current_user.barbearia_id != config.id):
        return redirect(url_for('home_cliente', slug=slug))
    agendamentos = Agendamento.query.filter_by(barbearia_id=config.id).order_by(Agendamento.data_hora.desc()).all()
    return render_template('agendamentos.html', agendamentos=agendamentos, config=config)

@app.route('/<slug>/admin/agendamento/novo', methods=['GET', 'POST'])
@login_required
def novo_agendamento(slug):
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    if not getattr(current_user, 'is_admin', False) or (not current_user.is_superadmin and current_user.barbearia_id != config.id):
        return redirect(url_for('home_cliente', slug=slug))
    
    if request.method == 'POST':
        cliente_id = request.form.get('cliente_id')
        servico_id = request.form.get('servico_id')
        barbeiro_id = request.form.get('barbeiro_id')
        if barbeiro_id == "": barbeiro_id = None
        data_hora_str = request.form.get('data_hora')
        data_hora = datetime.strptime(data_hora_str, '%Y-%m-%dT%H:%M')
        
        novo = Agendamento(cliente_id=cliente_id, servico_id=servico_id, barbeiro_id=barbeiro_id, data_hora=data_hora, status='Confirmado', barbearia_id=config.id)
        db.session.add(novo)
        db.session.commit()
        flash('Agendamento realizado com sucesso!', 'success')
        return redirect(url_for('index', slug=slug))
        
    clientes = Cliente.query.filter_by(barbearia_id=config.id).all()
    servicos = Servico.query.filter_by(barbearia_id=config.id).all()
    return render_template('agendamento_form.html', clientes=clientes, servicos=servicos, config=config)

@app.route('/<slug>/admin/agendamento/alterar/<int:id>', methods=['POST'])
@login_required
def alterar_data_agendamento(slug, id):
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    agendamento = Agendamento.query.filter_by(id=id, barbearia_id=config.id).first_or_404()
    nova_data_str = request.form.get('nova_data_hora')
    try:
        nova_data = datetime.strptime(nova_data_str, '%Y-%m-%dT%H:%M')
        agendamento.data_hora = nova_data
        db.session.commit()
        flash('Data alterada com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao alterar data: {str(e)}', 'danger')
    return redirect(request.referrer or url_for('listar_agendamentos', slug=slug))

@app.route('/<slug>/agendamento/confirmar/<int:id>')
@login_required
def confirmar_agendamento(slug, id):
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    agendamento = Agendamento.query.filter_by(id=id, barbearia_id=config.id).first_or_404()
    agendamento.status = 'Confirmado'
    db.session.commit()
    flash('Agendamento confirmado com sucesso!', 'success')
    return redirect(request.referrer or url_for('index', slug=slug))

@app.route('/<slug>/agendamento/concluir/<int:id>')
@login_required
def concluir_agendamento(slug, id):
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    agendamento = Agendamento.query.filter_by(id=id, barbearia_id=config.id).first_or_404()
    if agendamento.status != 'Concluído':
        agendamento.status = 'Concluído'
        cliente = Cliente.query.get(agendamento.cliente_id)
        cliente.cortes_realizados += 1
        
        if config.fidelidade_ativa:
            cliente.fidelidade_pontos += 1
            if cliente.fidelidade_pontos >= config.fidelidade_cortes_necessarios:
                 cliente.fidelidade_pontos = 0
                 flash(f'Parabéns! {cliente.nome} ganhou um corte grátis!', 'info')
        
        db.session.commit()
        flash('Atendimento concluído!', 'success')
    return redirect(request.referrer or url_for('index', slug=slug))

@app.route('/<slug>/agendamento/cancelar_admin/<int:id>')
@login_required
def cancelar_agendamento_admin(slug, id):
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    agendamento = Agendamento.query.filter_by(id=id, barbearia_id=config.id).first_or_404()
    agendamento.status = 'Cancelado'
    db.session.commit()
    flash('Agendamento cancelado.', 'info')
    return redirect(request.referrer or url_for('index', slug=slug))

@app.route('/<slug>/clientes')
@login_required
def listar_clientes(slug):
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    if not getattr(current_user, 'is_admin', False) or (not current_user.is_superadmin and current_user.barbearia_id != config.id):
        return redirect(url_for('home_cliente', slug=slug))
    clientes = Cliente.query.filter_by(barbearia_id=config.id).all()
    return render_template('clientes.html', clientes=clientes, config=config)

@app.route('/<slug>/admin/cliente/novo', methods=['GET', 'POST'])
@login_required
def novo_cliente(slug):
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    if not getattr(current_user, 'is_admin', False) or (not current_user.is_superadmin and current_user.barbearia_id != config.id):
        return redirect(url_for('home_cliente', slug=slug))
    
    if request.method == 'POST':
        nome = request.form.get('nome')
        telefone = request.form.get('telefone')
        email = request.form.get('email')
        
        if Cliente.query.filter_by(telefone=telefone, barbearia_id=config.id).first():
            flash('Este telefone já está cadastrado nesta barbearia!', 'danger')
        else:
            novo = Cliente(nome=nome, telefone=telefone, email=email, barbearia_id=config.id)
            db.session.add(novo)
            db.session.commit()
            flash('Cliente cadastrado com sucesso!', 'success')
            return redirect(url_for('listar_clientes', slug=slug))
            
    return render_template('cliente_form.html', config=config)

@app.route('/<slug>/configuracoes', methods=['GET', 'POST'])
@login_required
def configuracoes(slug):
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    if not getattr(current_user, 'is_admin', False) or (not current_user.is_superadmin and current_user.barbearia_id != config.id):
        return redirect(url_for('home_cliente', slug=slug))
    servicos = Servico.query.filter_by(barbearia_id=config.id).all()
    if request.method == 'POST':
        config.nome_barbearia = request.form.get('nome_barbearia')
        config.horario_abertura = request.form.get('horario_abertura')
        config.horario_fechamento = request.form.get('horario_fechamento')
        config.intervalo_minutos = int(request.form.get('intervalo_minutos', 30))
        config.fidelidade_ativa = 'fidelidade_ativa' in request.form
        config.fidelidade_cortes_necessarios = int(request.form.get('fidelidade_cortes_necessarios', 10))
        config.notificacao_minutos = int(request.form.get('notificacao_minutos', 15))
        db.session.commit()
        flash('Configurações atualizadas!', 'success')
        return redirect(url_for('configuracoes', slug=slug))
    return render_template('configuracoes.html', config=config, servicos=servicos)

@app.route('/<slug>/barbeiro/novo', methods=['POST'])
@login_required
def novo_barbeiro(slug):
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    if not getattr(current_user, 'is_admin', False) or (not current_user.is_superadmin and current_user.barbearia_id != config.id):
        return redirect(url_for('home_cliente', slug=slug))
    
    username = request.form.get('username')
    password = request.form.get('password')
    
    # Quarta alteração: validação de senha
    valida, msg = validar_senha(password)
    if not valida:
        flash(msg, 'danger')
        return redirect(url_for('configuracoes', slug=slug))

    if Usuario.query.filter_by(username=username).first():
        flash('Este nome de usuário já está em uso.', 'danger')
    else:
        novo = Usuario(
            username=username,
            password=generate_password_hash(password, method='pbkdf2:sha256'),
            is_admin=True,
            barbearia_id=config.id
        )
        db.session.add(novo)
        db.session.commit()
        flash('Barbeiro adicionado com sucesso!', 'success')
    return redirect(url_for('configuracoes', slug=slug))

# Primeira alteração: Edição de Barbeiro
@app.route('/<slug>/barbeiro/editar/<int:id>', methods=['POST'])
@login_required
def editar_barbeiro(slug, id):
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    if not getattr(current_user, 'is_admin', False) or (not current_user.is_superadmin and current_user.barbearia_id != config.id):
        return redirect(url_for('home_cliente', slug=slug))
    
    barbeiro = Usuario.query.filter_by(id=id, barbearia_id=config.id).first_or_404()
    novo_username = request.form.get('username')
    nova_senha = request.form.get('password')
    
    if novo_username:
        existente = Usuario.query.filter_by(username=novo_username).first()
        if existente and existente.id != barbeiro.id:
            flash('Este nome de usuário já está em uso.', 'danger')
            return redirect(url_for('configuracoes', slug=slug))
        barbeiro.username = novo_username
    
    if nova_senha:
        valida, msg = validar_senha(nova_senha)
        if not valida:
            flash(msg, 'danger')
            return redirect(url_for('configuracoes', slug=slug))
        barbeiro.password = generate_password_hash(nova_senha, method='pbkdf2:sha256')
        
    db.session.commit()
    flash('Barbeiro atualizado com sucesso!', 'success')
    return redirect(url_for('configuracoes', slug=slug))

@app.route('/<slug>/barbeiro/excluir/<int:id>')
@login_required
def excluir_barbeiro(slug, id):
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    if not getattr(current_user, 'is_admin', False) or (not current_user.is_superadmin and current_user.barbearia_id != config.id):
        return redirect(url_for('home_cliente', slug=slug))
    
    if id == current_user.id:
        flash('Você não pode excluir seu próprio usuário.', 'danger')
        return redirect(url_for('configuracoes', slug=slug))
        
    barbeiro = Usuario.query.filter_by(id=id, barbearia_id=config.id).first_or_404()
    db.session.delete(barbeiro)
    db.session.commit()
    flash('Barbeiro removido.', 'success')
    return redirect(url_for('configuracoes', slug=slug))

@app.route('/<slug>/servico/novo', methods=['POST'])
@login_required
def novo_servico(slug):
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    if not getattr(current_user, 'is_admin', False) or (not current_user.is_superadmin and current_user.barbearia_id != config.id):
        return redirect(url_for('home_cliente', slug=slug))
    
    nome = request.form.get('nome')
    preco = float(request.form.get('preco', 0))
    
    novo = Servico(nome=nome, preco=preco, barbearia_id=config.id)
    db.session.add(novo)
    db.session.commit()
    flash('Serviço adicionado!', 'success')
    return redirect(url_for('configuracoes', slug=slug))

# Primeira alteração: Edição de Serviço
@app.route('/<slug>/servico/editar/<int:id>', methods=['POST'])
@login_required
def editar_servico(slug, id):
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    if not getattr(current_user, 'is_admin', False) or (not current_user.is_superadmin and current_user.barbearia_id != config.id):
        return redirect(url_for('home_cliente', slug=slug))
    
    servico = Servico.query.filter_by(id=id, barbearia_id=config.id).first_or_404()
    servico.nome = request.form.get('nome')
    servico.preco = float(request.form.get('preco', 0))
    
    db.session.commit()
    flash('Serviço atualizado!', 'success')
    return redirect(url_for('configuracoes', slug=slug))

@app.route('/<slug>/servico/excluir/<int:id>')
@login_required
def excluir_servico(slug, id):
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    if not getattr(current_user, 'is_admin', False) or (not current_user.is_superadmin and current_user.barbearia_id != config.id):
        return redirect(url_for('home_cliente', slug=slug))
    
    servico = Servico.query.filter_by(id=id, barbearia_id=config.id).first_or_404()
    db.session.delete(servico)
    db.session.commit()
    flash('Serviço removido.', 'success')
    return redirect(url_for('configuracoes', slug=slug))

# --- FILA DE ESPERA ---
@app.route('/<slug>/fila')
def fila_acompanhar(slug):
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    fila = Fila.query.filter_by(barbearia_id=config.id).filter(Fila.status.in_(['aguardando', 'chamado', 'atendendo'])).order_by(Fila.posicao).all()
    return render_template('fila_acompanhar.html', fila=fila, config=config)

@app.route('/<slug>/fila/entrar', methods=['GET', 'POST'])
def fila_entrar(slug):
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    if request.method == 'POST':
        nome = request.form.get('nome')
        whatsapp = request.form.get('whatsapp')
        servico_id = request.form.get('servico_id')
        
        ultima_posicao = db.session.query(db.func.max(Fila.posicao)).filter_by(barbearia_id=config.id).scalar() or 0
        
        nova_entrada = Fila(
            cliente_nome=nome,
            whatsapp=whatsapp,
            servico_id=servico_id,
            barbearia_id=config.id,
            posicao=ultima_posicao + 1
        )
        db.session.add(nova_entrada)
        db.session.commit()
        flash('Você entrou na fila! Acompanhe sua posição.', 'success')
        return redirect(url_for('fila_acompanhar', slug=slug))
        
    servicos = Servico.query.filter_by(barbearia_id=config.id).all()
    return render_template('fila_entrar.html', servicos=servicos, config=config)

@app.route('/<slug>/admin/fila')
@login_required
def fila_painel(slug):
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    if not getattr(current_user, 'is_admin', False) or (not current_user.is_superadmin and current_user.barbearia_id != config.id):
        return redirect(url_for('home_cliente', slug=slug))
        
    fila = Fila.query.filter_by(barbearia_id=config.id).filter(Fila.status.in_(['aguardando', 'chamado', 'atendendo'])).order_by(Fila.posicao).all()
    barbeiros = Usuario.query.filter_by(barbearia_id=config.id, is_admin=True).all()
    return render_template('fila_painel.html', fila=fila, barbeiros=barbeiros, config=config)

@app.route('/<slug>/admin/fila/chamar/<int:id>')
@login_required
def fila_chamar(slug, id):
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    entrada = Fila.query.filter_by(id=id, barbearia_id=config.id).first_or_404()
    entrada.status = 'chamado'
    db.session.commit()
    return redirect(url_for('fila_painel', slug=slug))

@app.route('/<slug>/admin/fila/atender/<int:id>')
@login_required
def fila_atender(slug, id):
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    entrada = Fila.query.filter_by(id=id, barbearia_id=config.id).first_or_404()
    entrada.status = 'atendendo'
    entrada.barbeiro_id = current_user.id
    db.session.commit()
    return redirect(url_for('fila_painel', slug=slug))

@app.route('/<slug>/admin/fila/finalizar/<int:id>')
@login_required
def fila_finalizar(slug, id):
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    entrada = Fila.query.filter_by(id=id, barbearia_id=config.id).first_or_404()
    entrada.status = 'finalizado'
    db.session.commit()
    return redirect(url_for('fila_painel', slug=slug))

if __name__ == '__main__':
    app.run(debug=True)
