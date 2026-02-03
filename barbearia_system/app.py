from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os
import re
import unicodedata

# Inicialização da aplicação Flask
app = Flask(__name__)
app.config['SECRET_KEY'] = 'chave-secreta-barbearia'
# Configuração do Banco de Dados SQLite
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(app.instance_path, 'barbearia.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Configuração do Sistema de Login (Flask-Login)
login_manager = LoginManager()
login_manager.init_app(app)
# Define a rota de login padrão (global/superadmin)
login_manager.login_view = 'login_global'

# Funções auxiliares para tratamento de texto e validação
def slugify(text):
    """Converte um nome (ex: Barbearia do João) em um slug (ex: barbearia-do-joao) para a URL"""
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')
    text = re.sub(r'[^\w\s-]', '', text).strip().lower()
    return re.sub(r'[-\s]+', '-', text)

def title_case(text):
    """Converte um texto para Title Case (ex: barbearia do joao -> Barbearia Do Joao)"""
    if not text:
        return text
    return ' '.join(word.capitalize() for word in text.split())

def validar_senha(password):
    """Valida se a senha atende aos requisitos mínimos de segurança"""
    if len(password) < 6:
        return False, "A senha deve ter no mínimo 6 dígitos."
    if not any(c.isupper() for c in password):
        return False, "A senha deve conter pelo menos uma letra maiúscula."
    if not any(c.isdigit() for c in password):
        return False, "A senha deve conter pelo menos um número."
    return True, ""

# --- Modelos de Banco de Dados (ORM) ---

class Configuracao(db.Model):
    """Modelo que armazena as configurações específicas de cada barbearia (unidade)"""
    id = db.Column(db.Integer, primary_key=True)
    nome_barbearia = db.Column(db.String(100), default='Minha Barbearia')
    slug = db.Column(db.String(100), unique=True, nullable=False) # Identificador na URL
    horario_abertura = db.Column(db.String(5), default='09:00')
    horario_fechamento = db.Column(db.String(5), default='19:00')
    intervalo_minutos = db.Column(db.Integer, default=30)
    fidelidade_ativa = db.Column(db.Boolean, default=True)
    fidelidade_cortes_necessarios = db.Column(db.Integer, default=10)
    notificacao_minutos = db.Column(db.Integer, default=15)
    ativo = db.Column(db.Boolean, default=True)
    
    # Relacionamentos
    usuarios = db.relationship('Usuario', backref='barbearia', lazy=True, cascade="all, delete-orphan")
    clientes = db.relationship('Cliente', backref='barbearia', lazy=True, cascade="all, delete-orphan")
    servicos = db.relationship('Servico', backref='barbearia', lazy=True, cascade="all, delete-orphan")

class Usuario(UserMixin, db.Model):
    """Modelo para usuários do sistema (Barbeiros, Admins da Unidade e Super Admin)"""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=True) # Pode gerenciar a unidade
    is_superadmin = db.Column(db.Boolean, default=False) # Pode gerenciar todas as barbearias
    barbearia_id = db.Column(db.Integer, db.ForeignKey('configuracao.id'), nullable=True)

class Cliente(UserMixin, db.Model):
    """Modelo para os clientes da barbearia"""
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    telefone = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(100))
    cortes_realizados = db.Column(db.Integer, default=0)
    fidelidade_pontos = db.Column(db.Integer, default=0)
    barbearia_id = db.Column(db.Integer, db.ForeignKey('configuracao.id'), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    
    agendamentos = db.relationship('Agendamento', backref='cliente', lazy=True, cascade="all, delete-orphan")
    # Garante que um telefone seja único dentro de uma mesma barbearia
    __table_args__ = (db.UniqueConstraint('telefone', 'barbearia_id', name='_telefone_barbearia_uc'),)

class Servico(db.Model):
    """Serviços oferecidos pela barbearia (ex: Corte, Barba)"""
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    preco = db.Column(db.Float, nullable=False)
    duracao = db.Column(db.Integer, default=30)
    barbearia_id = db.Column(db.Integer, db.ForeignKey('configuracao.id'), nullable=False)

class Agendamento(db.Model):
    """Registros de horários agendados"""
    id = db.Column(db.Integer, primary_key=True)
    data_hora = db.Column(db.DateTime, nullable=False)
    cliente_id = db.Column(db.Integer, db.ForeignKey('cliente.id'), nullable=False)
    servico_id = db.Column(db.Integer, db.ForeignKey('servico.id'), nullable=False)
    status = db.Column(db.String(20), default='Pendente') # Pendente, Confirmado, Concluído, Cancelado
    barbearia_id = db.Column(db.Integer, db.ForeignKey('configuracao.id'), nullable=False)
    barbeiro_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=True)
    
    servico = db.relationship('Servico')
    barbeiro = db.relationship('Usuario')

class Fila(db.Model):
    """Modelo para a Fila Digital (espera por ordem de chegada)"""
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
    """Carrega o usuário ou cliente logado a partir do ID na sessão"""
    user_id_str = str(user_id)
    # Identifica se é usuário (admin/barbeiro) ou cliente pelo prefixo
    if user_id_str.startswith('u_'):
        return Usuario.query.get(int(user_id_str[2:]))
    elif user_id_str.startswith('c_'):
        return Cliente.query.get(int(user_id_str[2:]))
    
    # Fallback para IDs antigos sem prefixo
    user = Usuario.query.get(int(user_id))
    if user:
        return user
    return Cliente.query.get(int(user_id))

# Inicialização do Banco de Dados e criação do Super Admin padrão
with app.app_context():
    if not os.path.exists(app.instance_path):
        os.makedirs(app.instance_path)
    
    db.create_all()
    
    # Cria o usuário desenvolvedor/superadmin se não existir
    if not Usuario.query.filter_by(username='admin').first():
        admin = Usuario(
            username='admin',
            password=generate_password_hash('Admin123', method='pbkdf2:sha256'),
            is_admin=True,
            is_superadmin=True
        )
        db.session.add(admin)
        db.session.commit()

# --- ROTAS GLOBAIS (SUPER ADMIN) ---

@app.route('/login_master', methods=['GET', 'POST'])
def login_global():
    """Login exclusivo para o Super Admin (Desenvolvedor)"""
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
    """Painel principal do Super Admin para gerenciar barbearias"""
    if not getattr(current_user, 'is_superadmin', False):
        flash('Acesso restrito ao Super Admin.', 'danger')
        logout_user()
        return redirect(url_for('login_global'))
    barbearias = Configuracao.query.all()
    return render_template('index_global.html', barbearias=barbearias)

@app.route('/cadastrar_barbearia', methods=['GET', 'POST'])
@login_required
def cadastrar_barbearia():
    """Rota para o Super Admin cadastrar uma nova unidade de barbearia"""
    if not getattr(current_user, 'is_superadmin', False):
        flash('Apenas o Super Admin pode cadastrar novas barbearias.', 'danger')
        return redirect(url_for('index_root'))
        
    if request.method == 'POST':
        nome = title_case(request.form.get('nome'))
        slug = slugify(request.form.get('nome'))
        username = title_case(request.form.get('username'))
        password = request.form.get('password')
        
        valida, msg = validar_senha(password)
        if not valida:
            flash(msg, 'danger')
            return redirect(url_for('cadastrar_barbearia'))

        if Configuracao.query.filter_by(slug=slug).first():
            slug = f"{slug}-{datetime.now().strftime('%H%M%S')}"
        
        nova_barbearia = Configuracao(nome_barbearia=nome, slug=slug)
        db.session.add(nova_barbearia)
        db.session.flush()

        if Usuario.query.filter_by(username=username, barbearia_id=nova_barbearia.id).first():
            flash('Este nome de usuário já está em uso.', 'danger')
            db.session.rollback()
            return redirect(url_for('cadastrar_barbearia'))
        
        # Cria o admin da nova barbearia
        novo_admin = Usuario(
            username=username,
            password=generate_password_hash(password, method='pbkdf2:sha256'),
            is_admin=True,
            barbearia_id=nova_barbearia.id
        )
        
        # Serviços padrão para facilitar o início
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
    """Permite ao Super Admin editar dados básicos e credenciais da barbearia"""
    if not getattr(current_user, 'is_superadmin', False):
        flash('Acesso restrito ao Super Admin.', 'danger')
        return redirect(url_for('login_global'))
    
    barbearia = Configuracao.query.get_or_404(id)
    # Busca o usuário admin principal desta barbearia
    admin_usuario = Usuario.query.filter_by(barbearia_id=barbearia.id, is_admin=True).first()
    
    if request.method == 'POST':
        nome = title_case(request.form.get('nome'))
        username = title_case(request.form.get('username'))
        password = request.form.get('password')
        ativo = 'ativo' in request.form
        
        # Atualiza dados da barbearia
        barbearia.nome_barbearia = nome
        barbearia.ativo = ativo
        
        # Atualiza credenciais do admin se fornecidas
        if admin_usuario:
            if username:
                # Verifica se o username já existe para outro usuário nesta barbearia
                existente = Usuario.query.filter_by(username=username, barbearia_id=barbearia.id).first()
                if existente and existente.id != admin_usuario.id:
                    flash('Este nome de usuário já está em uso nesta barbearia.', 'danger')
                    return render_template('cadastrar_barbearia.html', barbearia=barbearia, admin_usuario=admin_usuario)
                admin_usuario.username = username
            
            if password:
                valida, msg = validar_senha(password)
                if not valida:
                    flash(msg, 'danger')
                    return render_template('cadastrar_barbearia.html', barbearia=barbearia, admin_usuario=admin_usuario)
                admin_usuario.password = generate_password_hash(password, method='pbkdf2:sha256')
        
        db.session.commit()
        flash('Barbearia atualizada com sucesso!', 'success')
        return redirect(url_for('index_root'))
        
    return render_template('cadastrar_barbearia.html', barbearia=barbearia, admin_usuario=admin_usuario)

@app.route('/excluir_barbearia/<int:id>')
@login_required
def excluir_barbearia(id):
    """Exclui uma barbearia e todos os seus dados vinculados"""
    if not getattr(current_user, 'is_superadmin', False):
        flash('Acesso restrito ao Super Admin.', 'danger')
        return redirect(url_for('login_global'))
    
    barbearia = Configuracao.query.get_or_404(id)
    db.session.delete(barbearia)
    db.session.commit()
    flash(f'Barbearia {barbearia.nome_barbearia} excluída com sucesso.', 'success')
    return redirect(url_for('index_root'))

# --- ROTAS DA BARBEARIA (CLIENTE E ADMIN LOCAL) ---

@app.route('/<slug>')
def index(slug):
    """Página inicial administrativa de uma barbearia específica"""
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    # Se não estiver logado como admin daquela barbearia, vai para a home do cliente
    if not current_user.is_authenticated or not getattr(current_user, 'is_admin', False) or (not current_user.is_superadmin and current_user.barbearia_id != config.id):
        return redirect(url_for('home_cliente', slug=slug))
    
    # Mostra os agendamentos do dia para o admin
    hoje = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    amanha = hoje + timedelta(days=1)
    agendamentos = Agendamento.query.filter_by(barbearia_id=config.id).filter(Agendamento.data_hora >= hoje, Agendamento.data_hora < amanha).order_by(Agendamento.data_hora).all()
    
    return render_template('index.html', config=config, agendamentos=agendamentos, datetime=datetime)

@app.route('/<slug>/home')
def home_cliente(slug):
    """Página que o cliente vê ao acessar o link da barbearia"""
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    servicos = Servico.query.filter_by(barbearia_id=config.id).all()
    if not config.ativo:
        return "Esta barbearia está temporariamente desativada. Entre em contato com o administrador.", 403
    return render_template('cliente_home.html', config=config, servicos=servicos)

@app.route('/<slug>/login', methods=['GET', 'POST'])
def login_cliente(slug):
    """Login para clientes (acesso via número de WhatsApp)"""
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

@app.route('/<slug>/admin/login', methods=['GET', 'POST'])
def login_admin(slug):
    """Login administrativo da barbearia (usuário e senha)"""
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = Usuario.query.filter_by(username=username, barbearia_id=config.id, is_admin=True).first()
        
        if user and check_password_hash(user.password, password):
            user.id = f"u_{user.id}"
            login_user(user)
            return redirect(url_for('index', slug=slug))
        else:
            flash('Usuário ou senha inválidos ou acesso não permitido.', 'danger')
            
    return render_template('login.html', config=config)

@app.route('/logout')
@app.route('/<slug>/logout')
@login_required
def logout(slug=None):
    """Faz logout de qualquer tipo de usuário"""
    logout_user()
    if slug:
        return redirect(url_for('home_cliente', slug=slug))
    return redirect(url_for('index_root'))

@app.route('/<slug>/painel')
@login_required
def cliente_painel(slug):
    """Painel onde o cliente vê seus próprios agendamentos"""
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    # Verifica se o cliente logado pertence a esta barbearia
    if not hasattr(current_user, 'barbearia_id') or current_user.barbearia_id != config.id:
        logout_user()
        return redirect(url_for('login_cliente', slug=slug))
        
    agendamentos = Agendamento.query.filter_by(cliente_id=current_user.id).order_by(Agendamento.data_hora.desc()).all()
    return render_template('cliente_painel.html', agendamentos=agendamentos, config=config)

@app.route('/<slug>/agendamento/confirmacao/<int:agendamento_id>')
def agendamento_confirmacao(slug, agendamento_id):
    """Página de status que o cliente vê logo após agendar"""
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    agendamento = Agendamento.query.get_or_404(agendamento_id)
    return render_template('cliente_agendamento_status.html', agendamento=agendamento, config=config)

@app.route('/<slug>/api/agendamento/status/<int:agendamento_id>')
def api_agendamento_status(slug, agendamento_id):
    """API para o frontend verificar se o status do agendamento mudou (AJAX)"""
    agendamento = Agendamento.query.get_or_404(agendamento_id)
    return jsonify({
        'status': agendamento.status,
        'data_hora': agendamento.data_hora.strftime('%d/%m/%Y %H:%M')
    })

@app.route('/<slug>/agendar', methods=['GET', 'POST'])
def agendar_cliente(slug):
    """Cliente realizando um agendamento online"""
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    servicos = Servico.query.filter_by(barbearia_id=config.id).all()
    
    if request.method == 'POST':
        nome = title_case(request.form.get('nome'))
        telefone = request.form.get('telefone')
        servico_id = request.form.get('servico_id')
        data_hora_str = request.form.get('data_hora')
        
        # Converte string da data para objeto datetime
        data_hora = datetime.strptime(data_hora_str, '%Y-%m-%dT%H:%M')
        
        # Busca ou cria o cliente pelo telefone
        cliente = Cliente.query.filter_by(telefone=telefone, barbearia_id=config.id).first()
        if not cliente:
            cliente = Cliente(nome=nome, telefone=telefone, barbearia_id=config.id)
            db.session.add(cliente)
            db.session.flush()
        
        # Cria o agendamento
        novo_agendamento = Agendamento(
            data_hora=data_hora,
            cliente_id=cliente.id,
            servico_id=servico_id,
            barbearia_id=config.id
        )
        db.session.add(novo_agendamento)
        db.session.commit()
        
        return redirect(url_for('agendamento_confirmacao', slug=slug, agendamento_id=novo_agendamento.id))
        
    return render_template('cliente_agendar.html', config=config, servicos=servicos)

@app.route('/<slug>/admin/agendamentos')
@login_required
def listar_agendamentos(slug):
    """Lista todos os agendamentos para o admin da barbearia"""
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    if not getattr(current_user, 'is_admin', False) or (not current_user.is_superadmin and current_user.barbearia_id != config.id):
        return redirect(url_for('home_cliente', slug=slug))
    
    agendamentos = Agendamento.query.filter_by(barbearia_id=config.id).order_by(Agendamento.data_hora.desc()).all()
    return render_template('agendamentos.html', agendamentos=agendamentos, config=config)

@app.route('/<slug>/admin/agendamento/novo', methods=['GET', 'POST'])
@login_required
def novo_agendamento(slug):
    """Admin criando agendamento manualmente"""
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    if not getattr(current_user, 'is_admin', False) or (not current_user.is_superadmin and current_user.barbearia_id != config.id):
        return redirect(url_for('home_cliente', slug=slug))
    
    if request.method == 'POST':
        cliente_id = request.form.get('cliente_id')
        servico_id = request.form.get('servico_id')
        barbeiro_id = request.form.get('barbeiro_id')
        data_hora_str = request.form.get('data_hora')
        
        data_hora = datetime.strptime(data_hora_str, '%Y-%m-%dT%H:%M')
        
        novo = Agendamento(
            data_hora=data_hora,
            cliente_id=cliente_id,
            servico_id=servico_id,
            barbearia_id=config.id,
            barbeiro_id=barbeiro_id if barbeiro_id else None,
            status='Confirmado'
        )
        db.session.add(novo)
        db.session.commit()
        flash('Agendamento realizado com sucesso!', 'success')
        return redirect(url_for('listar_agendamentos', slug=slug))
        
    servicos = Servico.query.filter_by(barbearia_id=config.id).all()
    clientes = Cliente.query.filter_by(barbearia_id=config.id).all()
    return render_template('agendamento_form.html', config=config, servicos=servicos, clientes=clientes)

@app.route('/<slug>/agendamento/confirmar/<int:id>')
@login_required
def confirmar_agendamento(slug, id):
    """Admin confirmando um agendamento pendente"""
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    agendamento = Agendamento.query.filter_by(id=id, barbearia_id=config.id).first_or_404()
    agendamento.status = 'Confirmado'
    agendamento.barbeiro_id = current_user.id
    db.session.commit()
    flash('Agendamento confirmado!', 'success')
    return redirect(request.referrer or url_for('index', slug=slug))

@app.route('/<slug>/agendamento/concluir/<int:id>')
@login_required
def concluir_agendamento(slug, id):
    """Admin marcando agendamento como finalizado e pontuando fidelidade"""
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    agendamento = Agendamento.query.filter_by(id=id, barbearia_id=config.id).first_or_404()
    if agendamento.status != 'Concluído':
        agendamento.status = 'Concluído'
        cliente = agendamento.cliente
        cliente.cortes_realizados += 1
        
        # Lógica de Fidelidade
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
    """Admin cancelando um agendamento"""
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    agendamento = Agendamento.query.filter_by(id=id, barbearia_id=config.id).first_or_404()
    agendamento.status = 'Cancelado'
    db.session.commit()
    flash('Agendamento cancelado.', 'warning')
    return redirect(request.referrer or url_for('index', slug=slug))

@app.route('/<slug>/agendamento/cancelar_cliente/<int:id>')
@login_required
def cancelar_agendamento_cliente(slug, id):
    """Cliente cancelando seu próprio agendamento"""
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    agendamento = Agendamento.query.filter_by(id=id, cliente_id=current_user.id).first_or_404()
    
    if agendamento.status in ['Concluído', 'Cancelado']:
        flash('Este agendamento não pode mais ser cancelado.', 'danger')
    else:
        agendamento.status = 'Cancelado'
        db.session.commit()
        flash('Seu agendamento foi cancelado.', 'success')
    return redirect(url_for('cliente_painel', slug=slug))

@app.route('/<slug>/agendamento/alterar_data/<int:id>', methods=['POST'])
@login_required
def alterar_data_agendamento(slug, id):
    """Admin alterando a data/hora de um agendamento"""
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    if not getattr(current_user, 'is_admin', False):
        return redirect(url_for('home_cliente', slug=slug))
        
    agendamento = Agendamento.query.filter_by(id=id, barbearia_id=config.id).first_or_404()
    nova_data = request.form.get('nova_data_hora')
    if nova_data:
        agendamento.data_hora = datetime.strptime(nova_data, '%Y-%m-%dT%H:%M')
        db.session.commit()
        flash('Data do agendamento atualizada!', 'success')
    return redirect(url_for('listar_agendamentos', slug=slug))

@app.route('/<slug>/clientes')
@login_required
def listar_clientes(slug):
    """Lista todos os clientes cadastrados na barbearia"""
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    if not getattr(current_user, 'is_admin', False) or (not current_user.is_superadmin and current_user.barbearia_id != config.id):
        return redirect(url_for('home_cliente', slug=slug))
    clientes = Cliente.query.filter_by(barbearia_id=config.id).all()
    return render_template('clientes.html', clientes=clientes, config=config)

@app.route('/<slug>/admin/cliente/novo', methods=['GET', 'POST'])
@login_required
def novo_cliente(slug):
    """Admin cadastrando cliente manualmente"""
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    if not getattr(current_user, 'is_admin', False) or (not current_user.is_superadmin and current_user.barbearia_id != config.id):
        return redirect(url_for('home_cliente', slug=slug))
    
    if request.method == 'POST':
        nome = title_case(request.form.get('nome'))
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
    """Painel de configurações da barbearia (horários, fidelidade, barbeiros, serviços)"""
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    if not getattr(current_user, 'is_admin', False) or (not current_user.is_superadmin and current_user.barbearia_id != config.id):
        return redirect(url_for('home_cliente', slug=slug))
    servicos = Servico.query.filter_by(barbearia_id=config.id).all()
    if request.method == 'POST':
        config.nome_barbearia = title_case(request.form.get('nome_barbearia'))
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
    """Adiciona um novo barbeiro (usuário admin) à unidade"""
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    if not getattr(current_user, 'is_admin', False) or (not current_user.is_superadmin and current_user.barbearia_id != config.id):
        return redirect(url_for('home_cliente', slug=slug))
    
    username = title_case(request.form.get('username'))
    
    if Usuario.query.filter_by(username=username, barbearia_id=config.id).first():
        flash('Este nome de usuário já está em uso nesta barbearia.', 'danger')
    else:
        # Barbeiros agora não precisam de senha, pois não fazem login.
        # Definimos uma senha aleatória/inválida apenas para satisfazer o banco de dados.
        import uuid
        random_password = str(uuid.uuid4())
        novo = Usuario(
            username=username,
            password=generate_password_hash(random_password, method='pbkdf2:sha256'),
            is_admin=False, # Alterado para False pois barbeiros não precisam de acesso admin
            barbearia_id=config.id
        )
        db.session.add(novo)
        db.session.commit()
        flash('Barbeiro adicionado com sucesso!', 'success')
    return redirect(url_for('configuracoes', slug=slug))

@app.route('/<slug>/barbeiro/editar/<int:id>', methods=['POST'])
@login_required
def editar_barbeiro(slug, id):
    """Edita dados de um barbeiro existente"""
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    if not getattr(current_user, 'is_admin', False) or (not current_user.is_superadmin and current_user.barbearia_id != config.id):
        return redirect(url_for('home_cliente', slug=slug))
    
    barbeiro = Usuario.query.filter_by(id=id, barbearia_id=config.id).first_or_404()
    novo_username = request.form.get('username')
    
    if novo_username:
        novo_username = title_case(novo_username)
        existente = Usuario.query.filter_by(username=novo_username, barbearia_id=config.id).first()
        if existente and existente.id != barbeiro.id:
            flash('Este nome de usuário já está em uso nesta barbearia.', 'danger')
            return redirect(url_for('configuracoes', slug=slug))
        barbeiro.username = novo_username
        
    db.session.commit()
    flash('Barbeiro atualizado com sucesso!', 'success')
    return redirect(url_for('configuracoes', slug=slug))

@app.route('/<slug>/barbeiro/excluir/<int:id>')
@login_required
def excluir_barbeiro(slug, id):
    """Remove um barbeiro da unidade"""
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
    """Adiciona um novo serviço (ex: Sobrancelha)"""
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

@app.route('/<slug>/servico/editar/<int:id>', methods=['POST'])
@login_required
def editar_servico(slug, id):
    """Edita preço ou nome de um serviço"""
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
    """Remove um serviço"""
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    if not getattr(current_user, 'is_admin', False) or (not current_user.is_superadmin and current_user.barbearia_id != config.id):
        return redirect(url_for('home_cliente', slug=slug))
    
    servico = Servico.query.filter_by(id=id, barbearia_id=config.id).first_or_404()
    db.session.delete(servico)
    db.session.commit()
    flash('Serviço removido.', 'success')
    return redirect(url_for('configuracoes', slug=slug))

@app.route('/<slug>/admin/cliente/excluir/<int:id>')
@login_required
def excluir_cliente(slug, id):
    """Admin excluindo um cliente"""
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    if not getattr(current_user, 'is_admin', False):
        return redirect(url_for('home_cliente', slug=slug))
        
    cliente = Cliente.query.filter_by(id=id, barbearia_id=config.id).first_or_404()
    db.session.delete(cliente)
    db.session.commit()
    flash('Cliente excluído com sucesso.', 'success')
    return redirect(url_for('listar_clientes', slug=slug))

@app.route('/<slug>/notificacoes/verificar')
def verificar_notificacoes(slug):
    """Placeholder para verificação de notificações"""
    return jsonify({'notificar': False})# --- FILA DE ESPERA (ORDEM DE CHEGADA) ---

@app.route('/<slug>/fila/<int:id>')
def fila_acompanhar(slug, id):
    """Página pública para um cliente específico acompanhar sua posição na fila"""
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    item = Fila.query.filter_by(id=id, barbearia_id=config.id).first_or_404()
    
    # Calcula quantas pessoas estão na frente (status aguardando e posição menor)
    faltam = Fila.query.filter_by(barbearia_id=config.id, status='aguardando').filter(Fila.posicao < item.posicao).count()
    
    # Tempo estimado (ex: 20 min por pessoa na frente)
    tempo_estimado = faltam * 20
    
    return render_template('fila_acompanhar.html', item=item, config=config, faltam=faltam, tempo_estimado=tempo_estimado)

@app.route('/api/<slug>/fila/status/<int:id>')
def api_fila_status(slug, id):
    """API para o frontend verificar o status da fila em tempo real"""
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    item = Fila.query.filter_by(id=id, barbearia_id=config.id).first_or_404()
    
    faltam = Fila.query.filter_by(barbearia_id=config.id, status='aguardando').filter(Fila.posicao < item.posicao).count()
    
    return jsonify({
        'posicao': item.posicao,
        'status': item.status,
        'faltam': faltam,
        'tempo_estimado': faltam * 20
    })

@app.route('/<slug>/fila/entrar', methods=['GET', 'POST'])
def entrar_fila(slug):
    """Cliente entrando na fila digital"""
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    if request.method == 'POST':
        nome = title_case(request.form.get('nome'))
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
        return redirect(url_for('fila_acompanhar', slug=slug, id=nova_entrada.id))
        
    servicos = Servico.query.filter_by(barbearia_id=config.id).all()
    return render_template('fila_entrar.html', servicos=servicos, config=config)

@app.route('/<slug>/admin/fila')
@login_required
def fila_painel(slug):
    """Painel administrativo para gerenciar a fila (chamar, atender, finalizar)"""
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    if not getattr(current_user, 'is_admin', False) or (not current_user.is_superadmin and current_user.barbearia_id != config.id):
        return redirect(url_for('home_cliente', slug=slug))
        
    fila = Fila.query.filter_by(barbearia_id=config.id).filter(Fila.status.in_(['aguardando', 'chamado', 'atendendo'])).order_by(Fila.posicao).all()
    # Lista todos os usuários da barbearia que não são o dono (assumindo que o dono é o primeiro admin ou tem lógica específica)
    # Aqui filtramos para mostrar todos os barbeiros cadastrados na unidade
    barbeiros = Usuario.query.filter_by(barbearia_id=config.id).all()
    return render_template('fila_painel.html', fila=fila, barbeiros=barbeiros, config=config)

@app.route('/<slug>/admin/fila/chamar/<int:id>')
@login_required
def fila_chamar(slug, id):
    """Admin chamando o próximo da fila"""
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    entrada = Fila.query.filter_by(id=id, barbearia_id=config.id).first_or_404()
    entrada.status = 'chamado'
    db.session.commit()
    return redirect(url_for('fila_painel', slug=slug))

@app.route('/<slug>/admin/fila/atender/<int:id>')
@login_required
def fila_atender(slug, id):
    """Admin iniciando o atendimento de alguém da fila"""
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    entrada = Fila.query.filter_by(id=id, barbearia_id=config.id).first_or_404()
    entrada.status = 'atendendo'
    entrada.barbeiro_id = current_user.id
    db.session.commit()
    return redirect(url_for('fila_painel', slug=slug))

@app.route('/<slug>/admin/fila/finalizar/<int:id>')
@login_required
def fila_finalizar(slug, id):
    """Admin finalizando o atendimento da fila"""
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    entrada = Fila.query.filter_by(id=id, barbearia_id=config.id).first_or_404()
    entrada.status = 'finalizado'
    db.session.commit()
    return redirect(url_for('fila_painel', slug=slug))

@app.route('/<slug>/admin/fila/ausente/<int:id>')
@login_required
def fila_ausente(slug, id):
    """Admin marcando cliente como ausente na fila"""
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    entrada = Fila.query.filter_by(id=id, barbearia_id=config.id).first_or_404()
    entrada.status = 'ausente'
    db.session.commit()
    return redirect(url_for('fila_painel', slug=slug))

if __name__ == '__main__':
    # Inicia o servidor Flask
    app.run(debug=True)
