from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, g, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os
import re
import unicodedata
import urllib
from dotenv import load_dotenv

# Carrega variáveis de ambiente do arquivo .env
load_dotenv()

# Inicialização da aplicação Flask
app = Flask(__name__)

# Configurações de Domínio para Multi-tenant
# O BASE_DOMAIN deve ser algo como 'meudominio.com.br' ou 'localhost:5000'
app.config['SERVER_NAME'] = os.getenv('BASE_DOMAIN', 'localhost:5000')
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'chave-secreta-barbearia')

# Adiciona hasattr e getattr ao contexto do Jinja2 para uso nos templates
app.jinja_env.globals.update(hasattr=hasattr, getattr=getattr)

# Configuração do Banco de Dados SQL Server
connection_string = (
    f"DRIVER={os.getenv('DB_DRIVER', '{ODBC Driver 18 for SQL Server}')};"
    f"SERVER={os.getenv('DB_SERVER', '100.66.160.34,1433')};"
    f"DATABASE={os.getenv('DB_DATABASE', 'master')};"
    f"UID={os.getenv('DB_USER', 'APIuser')};"
    f"PWD={os.getenv('DB_PASSWORD', 'TMNTdb')};"
    "TrustServerCertificate=yes;"
)
params = urllib.parse.quote_plus(connection_string)
app.config['SQLALCHEMY_DATABASE_URI'] = f"mssql+pyodbc:///?odbc_connect={params}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Configurações de Pool para evitar erros de conexão
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "pool_pre_ping": True,
    "pool_recycle": 300,
    "pool_timeout": 30,
    "pool_size": 10,
    "max_overflow": 5,
}

db = SQLAlchemy(app)

# Configuração do Sistema de Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login_global'

# --- Funções auxiliares ---

def slugify(text):
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')
    text = re.sub(r'[^\w\s-]', '', text).strip().lower()
    return re.sub(r'[-\s]+', '-', text)

def title_case(text):
    if not text: return text
    return ' '.join(word.capitalize() for word in text.split())

def validar_senha(password):
    if len(password) < 6: return False, "A senha deve ter no mínimo 6 dígitos."
    if not any(c.isupper() for c in password): return False, "A senha deve conter pelo menos uma letra maiúscula."
    if not any(c.isdigit() for c in password): return False, "A senha deve conter pelo menos um número."
    return True, ""

# --- Modelos de Banco de Dados ---

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
    ativo = db.Column(db.Boolean, default=True)
    
    usuarios = db.relationship('Usuario', backref='barbearia', lazy=True, cascade="all, delete-orphan")
    clientes = db.relationship('Cliente', backref='barbearia', lazy=True, cascade="all, delete-orphan")
    servicos = db.relationship('Servico', backref='barbearia', lazy=True, cascade="all, delete-orphan")

class Administrador(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    @property
    def is_superadmin(self): return True
    def get_id(self): return f"a_{self.id}"

class Usuario(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=True)
    barbearia_id = db.Column(db.Integer, db.ForeignKey('configuracao.id'), nullable=True)
    def get_id(self): return f"u_{self.id}"

class Cliente(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    telefone = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(100))
    cortes_realizados = db.Column(db.Integer, default=0)
    fidelidade_pontos = db.Column(db.Integer, default=0)
    barbearia_id = db.Column(db.Integer, db.ForeignKey('configuracao.id'), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    def get_id(self): return f"c_{self.id}"
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
    status = db.Column(db.String(20), default='aguardando')
    posicao = db.Column(db.Integer)
    criado_em = db.Column(db.DateTime, default=datetime.now)
    barbeiro_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=True)
    servico = db.relationship('Servico')
    barbeiro = db.relationship('Usuario')

@login_manager.user_loader
def load_user(user_id):
    user_id_str = str(user_id)
    if user_id_str.startswith('a_'):
        return Administrador.query.get(int(user_id_str[2:]))
    elif user_id_str.startswith('u_'):
        return Usuario.query.get(int(user_id_str[2:]))
    elif user_id_str.startswith('c_'):
        return Cliente.query.get(int(user_id_str[2:]))
    return None

# --- Middleware Multi-tenant ---

@app.before_request
def get_tenant():
    if request.path.startswith('/static'):
        return
    host = request.host.split(':')[0]
    base_domain = app.config['SERVER_NAME'].split(':')[0]
    if host != base_domain and host.endswith(base_domain):
        subdomain = host.replace(f".{base_domain}", "")
        tenant = Configuracao.query.filter_by(slug=subdomain).first()
        if tenant:
            g.tenant = tenant
            return
    g.tenant = None

# Inicialização do Banco de Dados
with app.app_context():
    if not os.path.exists(app.instance_path):
        os.makedirs(app.instance_path)
    db.create_all()
    if not Administrador.query.filter_by(username='admin').first():
        admin = Administrador(
            username='admin',
            password=generate_password_hash('Admin123', method='pbkdf2:sha256')
        )
        db.session.add(admin)
        db.session.commit()

# --- ROTAS GLOBAIS ---

@app.route('/login_master', methods=['GET', 'POST'])
def login_global():
    if current_user.is_authenticated and hasattr(current_user, 'is_superadmin'):
        return redirect(url_for('index_root'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        admin = Administrador.query.filter_by(username=username).first()
        if admin and check_password_hash(admin.password, password):
            login_user(admin)
            return redirect(url_for('index_root'))
        flash('Acesso negado.', 'danger')
    return render_template('login_global.html')

@app.route('/')
def index_root():
    if g.get('tenant'):
        return redirect(url_for('home_cliente', subdomain=g.tenant.slug))
    if not (current_user.is_authenticated and hasattr(current_user, 'is_superadmin')):
        barbearias = Configuracao.query.filter_by(ativo=True).all()
        return render_template('index_global.html', barbearias=barbearias)
    barbearias = Configuracao.query.all()
    return render_template('index_global.html', barbearias=barbearias)

@app.route('/cadastrar_barbearia', methods=['GET', 'POST'])
@login_required
def cadastrar_barbearia():
    if not hasattr(current_user, 'is_superadmin'): abort(403)
    if request.method == 'POST':
        nome = title_case(request.form.get('nome'))
        slug = slugify(request.form.get('nome'))
        username = request.form.get('username')
        password = request.form.get('password')
        if Configuracao.query.filter_by(slug=slug).first():
            flash('Já existe uma barbearia com este nome/slug.', 'danger')
        else:
            nova_config = Configuracao(nome_barbearia=nome, slug=slug)
            db.session.add(nova_config)
            db.session.flush()
            novo_usuario = Usuario(username=username, password=generate_password_hash(password, method='pbkdf2:sha256'), barbearia_id=nova_config.id)
            db.session.add(novo_usuario)
            db.session.commit()
            flash(f'Barbearia {nome} cadastrada com sucesso!', 'success')
            return redirect(url_for('index_root'))
    return render_template('cadastrar_barbearia.html')

@app.route('/editar_barbearia/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_barbearia(id):
    if not hasattr(current_user, 'is_superadmin'): abort(403)
    barbearia = Configuracao.query.get_or_404(id)
    if request.method == 'POST':
        barbearia.nome_barbearia = title_case(request.form.get('nome'))
        barbearia.ativo = 'ativo' in request.form
        db.session.commit()
        flash('Barbearia atualizada!', 'success')
        return redirect(url_for('index_root'))
    return render_template('cadastrar_barbearia.html', barbearia=barbearia)

@app.route('/excluir_barbearia/<int:id>')
@login_required
def excluir_barbearia(id):
    if not hasattr(current_user, 'is_superadmin'): abort(403)
    barbearia = Configuracao.query.get_or_404(id)
    db.session.delete(barbearia)
    db.session.commit()
    flash('Barbearia excluída!', 'warning')
    return redirect(url_for('index_root'))

# --- ROTAS DO TENANT (SUBDOMÍNIO) ---

@app.route('/', subdomain='<subdomain>')
def home_cliente(subdomain):
    config = Configuracao.query.filter_by(slug=subdomain).first_or_404()
    return render_template('index.html', config=config)

@app.route('/login', subdomain='<subdomain>', methods=['GET', 'POST'])
def login(subdomain):
    config = Configuracao.query.filter_by(slug=subdomain).first_or_404()
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = Usuario.query.filter_by(username=username, barbearia_id=config.id).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('index_admin', subdomain=subdomain))
        flash('Credenciais inválidas.', 'danger')
    return render_template('login.html', config=config)

@app.route('/admin', subdomain='<subdomain>')
@login_required
def index_admin(subdomain):
    config = Configuracao.query.filter_by(slug=subdomain).first_or_404()
    if not (hasattr(current_user, 'is_superadmin') or (getattr(current_user, 'barbearia_id', None) == config.id)):
        abort(403)
    return render_template('cliente_painel.html', config=config)

@app.route('/agendar', subdomain='<subdomain>', methods=['GET', 'POST'])
def agendar(subdomain):
    config = Configuracao.query.filter_by(slug=subdomain).first_or_404()
    servicos = Servico.query.filter_by(barbearia_id=config.id).all()
    barbeiros = Usuario.query.filter_by(barbearia_id=config.id, is_admin=False).all()
    if request.method == 'POST':
        # Lógica de agendamento aqui...
        flash('Agendamento realizado!', 'success')
        return redirect(url_for('home_cliente', subdomain=subdomain))
    return render_template('cliente_agendar.html', config=config, servicos=servicos, barbeiros=barbeiros)

@app.route('/agendamento/confirmacao/<int:agendamento_id>', subdomain='<subdomain>')
def agendamento_confirmacao(subdomain, agendamento_id):
    config = Configuracao.query.filter_by(slug=subdomain).first_or_404()
    agendamento = Agendamento.query.filter_by(id=agendamento_id, barbearia_id=config.id).first_or_404()
    return render_template('agendamento_confirmacao.html', config=config, agendamento=agendamento)

@app.route('/agendamentos', subdomain='<subdomain>')
@login_required
def listar_agendamentos(subdomain):
    config = Configuracao.query.filter_by(slug=subdomain).first_or_404()
    if not (hasattr(current_user, 'is_superadmin') or (getattr(current_user, 'barbearia_id', None) == config.id)): abort(403)
    agendamentos = Agendamento.query.filter_by(barbearia_id=config.id).order_by(Agendamento.data_hora.desc()).all()
    return render_template('agendamentos.html', agendamentos=agendamentos, config=config)

@app.route('/configuracoes', subdomain='<subdomain>', methods=['GET', 'POST'])
@login_required
def configuracoes(subdomain):
    config = Configuracao.query.filter_by(slug=subdomain).first_or_404()
    if not (hasattr(current_user, 'is_superadmin') or (getattr(current_user, 'barbearia_id', None) == config.id)): abort(403)
    if request.method == 'POST':
        config.nome_barbearia = title_case(request.form.get('nome_barbearia'))
        config.horario_abertura = request.form.get('horario_abertura')
        config.horario_fechamento = request.form.get('horario_fechamento')
        db.session.commit()
        flash('Configurações atualizadas!', 'success')
    servicos = Servico.query.filter_by(barbearia_id=config.id).all()
    return render_template('configuracoes.html', config=config, servicos=servicos)

@app.route('/clientes', subdomain='<subdomain>')
@login_required
def listar_clientes(subdomain):
    config = Configuracao.query.filter_by(slug=subdomain).first_or_404()
    if not (hasattr(current_user, 'is_superadmin') or (getattr(current_user, 'barbearia_id', None) == config.id)): abort(403)
    clientes = Cliente.query.filter_by(barbearia_id=config.id).all()
    return render_template('clientes.html', clientes=clientes, config=config)

@app.route('/fila', subdomain='<subdomain>')
def fila_publica(subdomain):
    config = Configuracao.query.filter_by(slug=subdomain).first_or_404()
    fila = Fila.query.filter_by(barbearia_id=config.id, status='aguardando').order_by(Fila.posicao).all()
    return render_template('fila_acompanhar.html', config=config, fila=fila)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index_root'))

if __name__ == '__main__':
    app.run(debug=True)
