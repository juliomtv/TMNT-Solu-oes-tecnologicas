from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, g, abort
from werkzeug.middleware.proxy_fix import ProxyFix
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
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)

# Configurações de Cookie para permitir HTTPS (ngrok)
app.config.update(
    SESSION_COOKIE_SECURE=False,  # Mantemos False para não quebrar se acessar via HTTP local
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
)

# Configurações de Domínio para Multi-tenant
# O BASE_DOMAIN é lido do .env. Se não existir, tentamos usar o host da requisição.
app.config['BASE_DOMAIN'] = os.getenv('BASE_DOMAIN', None)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'chave-secreta-barbearia')

# Adiciona utilitários ao contexto do Jinja2 para uso nos templates
app.jinja_env.globals.update(hasattr=hasattr, getattr=getattr, datetime=datetime)

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
    # Colunas de cores removidas do modelo para evitar erros de SELECT automático no SQL Server
    # A gestão de cores será feita via SQL puro para garantir estabilidade.
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
    
    # Host atual da requisição (ex: barbearia.abc.ngrok-free.app)
    # Mantemos a porta para comparação se ela estiver no BASE_DOMAIN
    host_full = request.host
    host_only = host_full.split(':')[0]
    
    # O BASE_DOMAIN é lido do .env (ex: localhost:5000 ou tmnt.com.br)
    base_domain = app.config.get('BASE_DOMAIN')
    
    subdomain = None
    if base_domain:
        # Se o host atual termina com o domínio base e há algo antes (o subdomínio)
        if host_full.endswith(base_domain) and host_full != base_domain:
            subdomain = host_full.replace(f".{base_domain}", "")
    
    # Fallback para detecção de subdomínio genérica (ex: sub.domain.com -> sub)
    if not subdomain:
        parts = host_only.split('.')
        # Se tiver 3 partes (sub.dominio.com) ou for ngrok (sub.ngrok-free.app)
        if len(parts) >= 3:
            subdomain = parts[0]
        # Se for localhost com subdomínio (ex: barbearia.localhost)
        elif len(parts) == 2 and parts[1] == 'localhost':
            subdomain = parts[0]
        
    if subdomain:
        # Força o recarregamento do tenant para evitar cache de sessões anteriores
        tenant = Configuracao.query.filter_by(slug=subdomain).populate_existing().first()
        if tenant:
            g.tenant = tenant
            # Lógica de cores via SQL puro para evitar erros de mapeamento
            from sqlalchemy import text
            # Define padrões
            g.tenant.cor_primaria = '#0d6efd'
            g.tenant.cor_secundaria = '#212529'
            g.tenant.cor_fundo = '#f8f9fa'
            g.tenant.cor_texto = '#212529'
            try:
                # Busca as cores diretamente do banco para garantir que são as mais recentes
                result = db.session.execute(text("SELECT cor_primaria, cor_secundaria, cor_fundo, cor_texto FROM configuracao WHERE id = :id"), {"id": tenant.id}).fetchone()
                if result:
                    if result[0]: g.tenant.cor_primaria = result[0]
                    if result[1]: g.tenant.cor_secundaria = result[1]
                    if result[2]: g.tenant.cor_fundo = result[2]
                    if result[3]: g.tenant.cor_texto = result[3]
            except Exception:
                pass 
            return
    
    g.tenant = None

# Inicialização do Banco de Dados
# db.create_all() removido do fluxo automático para evitar erros em produção com SQL Server
# Recomenda-se usar migrações manuais ou scripts controlados.

# --- ROTAS GLOBAIS ---

@app.route('/migrar_cores')
def migrar_cores():
    from sqlalchemy import text
    results = []
    commands = [
        "ALTER TABLE configuracao ADD cor_primaria VARCHAR(7) DEFAULT '#0d6efd'",
        "ALTER TABLE configuracao ADD cor_secundaria VARCHAR(7) DEFAULT '#212529'",
        "ALTER TABLE configuracao ADD cor_fundo VARCHAR(7) DEFAULT '#f8f9fa'",
        "ALTER TABLE configuracao ADD cor_texto VARCHAR(7) DEFAULT '#212529'",
        "UPDATE configuracao SET cor_primaria = '#0d6efd' WHERE cor_primaria IS NULL",
        "UPDATE configuracao SET cor_secundaria = '#212529' WHERE cor_secundaria IS NULL",
        "UPDATE configuracao SET cor_fundo = '#f8f9fa' WHERE cor_fundo IS NULL",
        "UPDATE configuracao SET cor_texto = '#212529' WHERE cor_texto IS NULL"
    ]
    for cmd in commands:
        try:
            db.session.execute(text(cmd))
            db.session.commit()
            results.append(f"Sucesso: {cmd}")
        except Exception as e:
            db.session.rollback()
            results.append(f"Erro ({cmd}): {str(e)}")
    return "<br>".join(results)

@app.route('/venda')
def pagina_venda():
    # A página de venda deve ser acessível globalmente
    return render_template('venda.html')

@app.route('/login_master', methods=['GET', 'POST'])
def login_master():
    if current_user.is_authenticated and hasattr(current_user, 'is_superadmin'):
        return redirect(url_for('index_root'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        admin = Administrador.query.filter_by(username=username).first()
        if admin and check_password_hash(admin.password, password):
            login_user(admin, remember=True)
            # Se o usuário estava tentando acessar uma barbearia específica, podemos redirecionar de volta
            next_page = request.args.get('next')
            return redirect(next_page or url_for('index_root'))
        flash('Acesso negado.', 'danger')
    return render_template('login_global.html')

@app.route('/')
def index_root():
    if g.get('tenant'):
        return home_cliente()
    
    # Se não houver tenant (acesso ao domínio principal), exige login do Master Admin
    if not current_user.is_authenticated or not hasattr(current_user, 'is_superadmin'):
        return redirect(url_for('login_master', next=request.url))
    
    barbearias = Configuracao.query.all()
    return render_template('index_global.html', barbearias=barbearias)

@app.route('/cadastrar_barbearia', methods=['GET', 'POST'])
def cadastrar_barbearia():
    if Administrador.query.count() > 0:
        if not current_user.is_authenticated or not hasattr(current_user, 'is_superadmin'):
            return redirect(url_for('login_global'))
            
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

@app.route('/cadastrar_admin', methods=['POST'])
@login_required
def cadastrar_admin():
    if not hasattr(current_user, 'is_superadmin'): abort(403)
    username = request.form.get('username_admin')
    password = request.form.get('password_admin')
    valida, msg = validar_senha(password)
    if not valida:
        flash(msg, 'danger')
    elif Administrador.query.filter_by(username=username).first():
        flash('Este usuário administrador já existe.', 'danger')
    else:
        novo = Administrador(username=username, password=generate_password_hash(password, method='pbkdf2:sha256'))
        db.session.add(novo)
        db.session.commit()
        flash('Novo administrador cadastrado!', 'success')
    return redirect(url_for('index_root'))

# --- ROTAS DO TENANT (USAM g.tenant) ---

@app.route('/home')
def home_cliente():
    if not g.tenant: abort(404)
    servicos = Servico.query.filter_by(barbearia_id=g.tenant.id).all()
    return render_template('cliente_home.html', config=g.tenant, servicos=servicos)

@app.route('/login', methods=['GET', 'POST'])
def login_cliente():
    if not g.tenant: abort(404)
    if current_user.is_authenticated:
        return redirect(url_for('index_admin'))
        
    if request.method == 'POST':
        telefone = request.form.get('telefone')
        cliente = Cliente.query.filter_by(telefone=telefone, barbearia_id=g.tenant.id).first()
        if cliente:
            login_user(cliente)
            return redirect(url_for('index_admin'))
        flash('Nenhum agendamento encontrado para este número.', 'warning')
    return render_template('cliente_login.html', config=g.tenant)

@app.route('/admin/login', methods=['GET', 'POST'])
def login_admin():
    if not g.tenant: abort(404)
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = Usuario.query.filter_by(username=username, barbearia_id=g.tenant.id).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('index_admin'))
        flash('Credenciais inválidas.', 'danger')
    return render_template('login.html', config=g.tenant)

@app.route('/admin')
@login_required
def index_admin():
    if not g.tenant: abort(404)
    if not (hasattr(current_user, 'is_superadmin') or (getattr(current_user, 'barbearia_id', None) == g.tenant.id)):
        abort(403)
    
    # Se for um administrador ou superadmin, mostra a agenda do dia (index.html)
    if getattr(current_user, 'is_admin', False) or hasattr(current_user, 'is_superadmin'):
        hoje = datetime.now().date()
        inicio_dia = datetime.combine(hoje, datetime.min.time())
        fim_dia = datetime.combine(hoje, datetime.max.time())
        
        agendamentos = Agendamento.query.filter(
            Agendamento.barbearia_id == g.tenant.id,
            Agendamento.data_hora >= inicio_dia,
            Agendamento.data_hora <= fim_dia
        ).order_by(Agendamento.data_hora.asc()).all()
        return render_template('index.html', config=g.tenant, agendamentos=agendamentos)
    
    # Se for um cliente, mostra o painel do cliente
    agendamentos = Agendamento.query.filter_by(cliente_id=current_user.id).order_by(Agendamento.data_hora.desc()).all()
    return render_template('cliente_painel.html', config=g.tenant, cliente=current_user, agendamentos=agendamentos)

@app.route('/agendar', methods=['GET', 'POST'])
def agendar():
    if not g.tenant: abort(404)
    servicos = Servico.query.filter_by(barbearia_id=g.tenant.id).all()
    barbeiros = Usuario.query.filter_by(barbearia_id=g.tenant.id, is_admin=False).all()
    if request.method == 'POST':
        telefone = request.form.get('telefone')
        nome = title_case(request.form.get('nome'))
        cliente = Cliente.query.filter_by(telefone=telefone, barbearia_id=g.tenant.id).first()
        if not cliente:
            cliente = Cliente(nome=nome, telefone=telefone, barbearia_id=g.tenant.id)
            db.session.add(cliente)
            db.session.flush()
        
        servico_id = request.form.get('servico_id')
        data_str = request.form.get('data')
        horario_str = request.form.get('horario')
        data_hora = datetime.strptime(f"{data_str} {horario_str}", '%Y-%m-%d %H:%M')
        
        novo = Agendamento(
            data_hora=data_hora,
            cliente_id=cliente.id,
            servico_id=servico_id,
            barbearia_id=g.tenant.id,
            barbeiro_id=request.form.get('barbeiro_id')
        )
        db.session.add(novo)
        db.session.commit()
        flash('Agendamento realizado!', 'success')
        return redirect(url_for('agendamento_confirmacao', agendamento_id=novo.id))
    return render_template('cliente_agendar.html', config=g.tenant, servicos=servicos, barbeiros=barbeiros)

@app.route('/agendamento/confirmacao/<int:agendamento_id>')
def agendamento_confirmacao(agendamento_id):
    if not g.tenant: abort(404)
    agendamento = Agendamento.query.filter_by(id=agendamento_id, barbearia_id=g.tenant.id).first_or_404()
    return render_template('agendamento_confirmacao.html', config=g.tenant, agendamento=agendamento)

@app.route('/agendamentos')
@login_required
def listar_agendamentos():
    if not g.tenant: abort(404)
    if not (hasattr(current_user, 'is_superadmin') or (getattr(current_user, 'barbearia_id', None) == g.tenant.id)): abort(403)
    agendamentos = Agendamento.query.filter_by(barbearia_id=g.tenant.id).order_by(Agendamento.data_hora.desc()).all()
    return render_template('agendamentos.html', agendamentos=agendamentos, config=g.tenant)

@app.route('/admin/agendamento/novo', methods=['GET', 'POST'])
@login_required
def novo_agendamento():
    if not g.tenant: abort(404)
    if not (hasattr(current_user, 'is_superadmin') or (getattr(current_user, 'barbearia_id', None) == g.tenant.id)): abort(403)
    if request.method == 'POST':
        flash('Agendamento criado!', 'success')
        return redirect(url_for('listar_agendamentos'))
    clientes = Cliente.query.filter_by(barbearia_id=g.tenant.id).all()
    servicos = Servico.query.filter_by(barbearia_id=g.tenant.id).all()
    return render_template('agendamento_form.html', config=g.tenant, clientes=clientes, servicos=servicos)

@app.route('/agendamento/concluir/<int:id>')
@login_required
def concluir_agendamento(id):
    if not g.tenant: abort(404)
    agendamento = Agendamento.query.filter_by(id=id, barbearia_id=g.tenant.id).first_or_404()
    agendamento.status = 'Concluído'
    db.session.commit()
    flash('Atendimento concluído!', 'success')
    return redirect(request.referrer or url_for('index_admin'))

@app.route('/agendamento/cancelar_admin/<int:id>')
@login_required
def cancelar_agendamento_admin(id):
    if not g.tenant: abort(404)
    agendamento = Agendamento.query.filter_by(id=id, barbearia_id=g.tenant.id).first_or_404()
    agendamento.status = 'Cancelado'
    db.session.commit()
    flash('Agendamento cancelado!', 'warning')
    return redirect(request.referrer or url_for('index_admin'))

@app.route('/agendamento/cancelar_cliente/<int:id>')
@login_required
def cancelar_agendamento_cliente(id):
    agendamento = Agendamento.query.filter_by(id=id, cliente_id=current_user.id).first_or_404()
    agendamento.status = 'Cancelado'
    db.session.commit()
    flash('Seu agendamento foi cancelado.', 'success')
    return redirect(url_for('index_admin'))

@app.route('/agendamento/alterar_data/<int:id>', methods=['POST'])
@login_required
def alterar_data_agendamento(id):
    if not g.tenant: abort(404)
    agendamento = Agendamento.query.filter_by(id=id, barbearia_id=g.tenant.id).first_or_404()
    nova_data = request.form.get('nova_data_hora')
    if nova_data:
        agendamento.data_hora = datetime.strptime(nova_data, '%Y-%m-%dT%H:%M')
        db.session.commit()
        flash('Data atualizada!', 'success')
    return redirect(url_for('listar_agendamentos'))

@app.route('/configuracoes', methods=['GET', 'POST'])
@login_required
def configuracoes():
    if not g.tenant: abort(404)
    if not (hasattr(current_user, 'is_superadmin') or (getattr(current_user, 'barbearia_id', None) == g.tenant.id)): abort(403)
    if request.method == 'POST':
        g.tenant.nome_barbearia = title_case(request.form.get('nome_barbearia'))
        g.tenant.horario_abertura = request.form.get('horario_abertura')
        g.tenant.horario_fechamento = request.form.get('horario_fechamento')
        db.session.commit()
        
        # Tenta salvar as cores via SQL puro
        from sqlalchemy import text
        try:
            cor_p = request.form.get('cor_primaria')
            cor_s = request.form.get('cor_secundaria')
            cor_f = request.form.get('cor_fundo')
            cor_t = request.form.get('cor_texto')
            db.session.execute(text("UPDATE configuracao SET cor_primaria = :p, cor_secundaria = :s, cor_fundo = :f, cor_texto = :t WHERE id = :id"), 
                             {"p": cor_p, "s": cor_s, "f": cor_f, "t": cor_t, "id": g.tenant.id})
            db.session.commit()
            
            # Atualiza os valores no objeto g.tenant em memória para evitar inconsistência imediata
            g.tenant.cor_primaria = cor_p
            g.tenant.cor_secundaria = cor_s
            g.tenant.cor_fundo = cor_f
            g.tenant.cor_texto = cor_t
            
            # Força a expiração para que a próxima consulta busque do banco
            db.session.expire(g.tenant)
        except Exception:
            db.session.rollback()
        flash('Configurações atualizadas!', 'success')
    servicos = Servico.query.filter_by(barbearia_id=g.tenant.id).all()
    barbeiros = Usuario.query.filter_by(barbearia_id=g.tenant.id).all()
    return render_template('configuracoes.html', config=g.tenant, servicos=servicos, usuarios=barbeiros)

@app.route('/barbeiro/novo', methods=['POST'])
@login_required
def novo_barbeiro():
    if not g.tenant: abort(404)
    username = request.form.get('username')
    novo = Usuario(username=username, password=generate_password_hash('Barbeiro123'), is_admin=False, barbearia_id=g.tenant.id)
    db.session.add(novo)
    db.session.commit()
    flash('Barbeiro adicionado!', 'success')
    return redirect(url_for('configuracoes'))

@app.route('/barbeiro/editar/<int:id>', methods=['POST'])
@login_required
def editar_barbeiro(id):
    barbeiro = Usuario.query.get_or_404(id)
    barbeiro.username = request.form.get('username')
    db.session.commit()
    flash('Barbeiro atualizado!', 'success')
    return redirect(url_for('configuracoes'))

@app.route('/barbeiro/excluir/<int:id>')
@login_required
def excluir_barbeiro(id):
    barbeiro = Usuario.query.get_or_404(id)
    db.session.delete(barbeiro)
    db.session.commit()
    flash('Barbeiro removido!', 'warning')
    return redirect(url_for('configuracoes'))

@app.route('/servico/novo', methods=['POST'])
@login_required
def novo_servico():
    if not g.tenant: abort(404)
    nome = request.form.get('nome')
    preco = float(request.form.get('preco', 0))
    novo = Servico(nome=nome, preco=preco, barbearia_id=g.tenant.id)
    db.session.add(novo)
    db.session.commit()
    flash('Serviço adicionado!', 'success')
    return redirect(url_for('configuracoes'))

@app.route('/servico/editar/<int:id>', methods=['POST'])
@login_required
def editar_servico(id):
    servico = Servico.query.get_or_404(id)
    servico.nome = request.form.get('nome')
    servico.preco = float(request.form.get('preco', 0))
    db.session.commit()
    flash('Serviço atualizado!', 'success')
    return redirect(url_for('configuracoes'))

@app.route('/servico/excluir/<int:id>')
@login_required
def excluir_servico(id):
    servico = Servico.query.get_or_404(id)
    db.session.delete(servico)
    db.session.commit()
    flash('Serviço removido!', 'warning')
    return redirect(url_for('configuracoes'))

@app.route('/clientes')
@login_required
def listar_clientes():
    if not g.tenant: abort(404)
    if not (hasattr(current_user, 'is_superadmin') or (getattr(current_user, 'barbearia_id', None) == g.tenant.id)): abort(403)
    clientes = Cliente.query.filter_by(barbearia_id=g.tenant.id).all()
    return render_template('clientes.html', clientes=clientes, config=g.tenant)

@app.route('/admin/cliente/novo', methods=['GET', 'POST'])
@login_required
def novo_cliente():
    if not g.tenant: abort(404)
    if request.method == 'POST':
        flash('Cliente cadastrado!', 'success')
        return redirect(url_for('listar_clientes'))
    return render_template('cliente_form.html', config=g.tenant)

@app.route('/admin/cliente/excluir/<int:id>')
@login_required
def excluir_cliente(id):
    cliente = Cliente.query.get_or_404(id)
    db.session.delete(cliente)
    db.session.commit()
    flash('Cliente excluído!', 'warning')
    return redirect(url_for('listar_clientes'))

@app.route('/fila/painel')
@login_required
def fila_painel():
    if not g.tenant: abort(404)
    fila = Fila.query.filter_by(barbearia_id=g.tenant.id).order_by(Fila.posicao).all()
    return render_template('fila_painel.html', config=g.tenant, fila=fila)

@app.route('/fila/entrar', methods=['GET', 'POST'])
def entrar_fila():
    if not g.tenant: abort(404)
    if request.method == 'POST':
        flash('Você entrou na fila!', 'success')
        return redirect(url_for('home_cliente'))
    servicos = Servico.query.filter_by(barbearia_id=g.tenant.id).all()
    return render_template('fila_entrar.html', config=g.tenant, servicos=servicos)

@app.route('/fila/chamar/<int:id>')
@login_required
def fila_chamar(id):
    item = Fila.query.get_or_404(id)
    item.status = 'chamado'
    db.session.commit()
    return redirect(url_for('fila_painel'))

@app.route('/fila/atender/<int:id>')
@login_required
def fila_atender(id):
    item = Fila.query.get_or_404(id)
    item.status = 'atendendo'
    db.session.commit()
    return redirect(url_for('fila_painel'))

@app.route('/fila/finalizar/<int:id>')
@login_required
def fila_finalizar(id):
    item = Fila.query.get_or_404(id)
    item.status = 'finalizado'
    db.session.commit()
    return redirect(url_for('fila_painel'))

@app.route('/fila/ausente/<int:id>')
@login_required
def fila_ausente(id):
    item = Fila.query.get_or_404(id)
    item.status = 'ausente'
    db.session.commit()
    return redirect(url_for('fila_painel'))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index_root'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
