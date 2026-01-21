from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'chave-secreta-barbearia'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(app.instance_path, 'barbearia.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Configuração do Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Modelos de Banco de Dados
class Usuario(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=True)

class Cliente(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    telefone = db.Column(db.String(20), unique=True, nullable=False)
    email = db.Column(db.String(100))
    cortes_realizados = db.Column(db.Integer, default=0)
    fidelidade_pontos = db.Column(db.Integer, default=0) # 10 pontos = 1 corte grátis
    agendamentos = db.relationship('Agendamento', backref='cliente', lazy=True)
    is_admin = db.Column(db.Boolean, default=False)

@login_manager.user_loader
def load_user(user_id):
    user = Usuario.query.get(int(user_id))
    if user:
        return user
    return Cliente.query.get(int(user_id))

class Servico(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    preco = db.Column(db.Float, nullable=False)
    duracao = db.Column(db.Integer, default=30) # em minutos

class Agendamento(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    data_hora = db.Column(db.DateTime, nullable=False)
    cliente_id = db.Column(db.Integer, db.ForeignKey('cliente.id'), nullable=False)
    servico_id = db.Column(db.Integer, db.ForeignKey('servico.id'), nullable=False)
    status = db.Column(db.String(20), default='Pendente') # Pendente, Confirmado, Concluído, Cancelado
    
    servico = db.relationship('Servico')

class Configuracao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome_barbearia = db.Column(db.String(100), default='Minha Barbearia')
    slug = db.Column(db.String(100), unique=True, nullable=False, default='minha-barbearia')
    horario_abertura = db.Column(db.String(5), default='09:00')
    horario_fechamento = db.Column(db.String(5), default='19:00')
    intervalo_minutos = db.Column(db.Integer, default=30)

# Inicialização do Banco de Dados
with app.app_context():
    db.create_all()
    if not Configuracao.query.first():
        config = Configuracao(nome_barbearia='Minha Barbearia', slug='minha-barbearia')
        db.session.add(config)
        db.session.commit()
    
    if not Usuario.query.filter_by(username='admin').first():
        admin = Usuario(
            username='admin',
            password=generate_password_hash('admin123', method='pbkdf2:sha256'),
            is_admin=True
        )
        db.session.add(admin)
        db.session.commit()

    if not Servico.query.first():
        servicos = [
            Servico(nome='Corte Masculino', preco=35.00),
            Servico(nome='Barba', preco=25.00),
            Servico(nome='Corte + Barba', preco=50.00),
            Servico(nome='Sobrancelha', preco=15.00)
        ]
        db.session.bulk_save_objects(servicos)
        db.session.commit()

# --- API PARA VERIFICAR HORÁRIOS OCUPADOS ---
@app.route('/api/horarios_ocupados')
def horarios_ocupados():
    data_str = request.args.get('data')
    if not data_str:
        return jsonify([])
    
    try:
        data_selecionada = datetime.strptime(data_str, '%Y-%m-%d').date()
    except:
        return jsonify([])

    agendamentos = Agendamento.query.filter(
        db.func.date(Agendamento.data_hora) == data_selecionada,
        Agendamento.status.in_(['Pendente', 'Confirmado', 'Concluído'])
    ).all()
    
    horarios = [a.data_hora.strftime('%H:%M') for a in agendamentos]
    return jsonify(horarios)

# Rotas de Autenticação Admin
@app.route('/login', methods=['GET', 'POST'])
def login():
    config = Configuracao.query.first()
    if current_user.is_authenticated and getattr(current_user, 'is_admin', False):
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = Usuario.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('index'))
        flash('Usuário ou senha inválidos', 'danger')
    return render_template('login.html', config=config)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# --- ÁREA DO CLIENTE ---
@app.route('/<slug>/login_cliente', methods=['GET', 'POST'])
def login_cliente(slug):
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    if current_user.is_authenticated and not getattr(current_user, 'is_admin', False):
        return redirect(url_for('cliente_painel', slug=slug))
    if request.method == 'POST':
        telefone = request.form.get('telefone')
        cliente = Cliente.query.filter_by(telefone=telefone).first()
        if cliente:
            login_user(cliente)
            return redirect(url_for('cliente_painel', slug=slug))
        else:
            flash('Número não encontrado. Faça um agendamento primeiro!', 'warning')
            return redirect(url_for('agendar_cliente', slug=slug))
    return render_template('cliente_login.html', config=config)

@app.route('/<slug>/cliente/painel')
@login_required
def cliente_painel(slug):
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    if getattr(current_user, 'is_admin', False):
        return redirect(url_for('index'))
    agendamentos = Agendamento.query.filter_by(cliente_id=current_user.id).order_by(Agendamento.data_hora.desc()).all()
    return render_template('cliente_painel.html', cliente=current_user, agendamentos=agendamentos, config=config)

@app.route('/<slug>/cliente/cancelar/<int:id>')
@login_required
def cancelar_agendamento_cliente(slug, id):
    agendamento = Agendamento.query.get_or_404(id)
    if agendamento.cliente_id != current_user.id:
        flash('Acesso negado.', 'danger')
        return redirect(url_for('cliente_painel', slug=slug))
    if agendamento.status in ['Pendente', 'Confirmado']:
        agendamento.status = 'Cancelado'
        db.session.commit()
        flash('Agendamento cancelado com sucesso.', 'success')
    else:
        flash('Este agendamento não pode mais ser cancelado.', 'warning')
    return redirect(url_for('cliente_painel', slug=slug))

@app.route('/<slug>/logout_cliente')
def logout_cliente(slug):
    logout_user()
    return redirect(url_for('home_cliente', slug=slug))

@app.route('/<slug>')
def home_cliente(slug):
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
    servicos = Servico.query.all()
    return render_template('cliente_home.html', servicos=servicos, config=config)

@app.route('/<slug>/agendar', methods=['GET', 'POST'])
def agendar_cliente(slug):
    config = Configuracao.query.filter_by(slug=slug).first_or_404()
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

        cliente_existente_nome = Cliente.query.filter_by(nome=nome).first()
        cliente_existente_tel = Cliente.query.filter_by(telefone=telefone).first()

        if cliente_existente_nome and (not cliente_existente_tel or cliente_existente_tel.nome != nome):
            flash('Já existe um cliente cadastrado com este nome.', 'danger')
            return redirect(url_for('agendar_cliente', slug=slug))

        conflito = Agendamento.query.filter(
            Agendamento.data_hora == data_hora,
            Agendamento.status.in_(['Pendente', 'Confirmado', 'Concluído'])
        ).first()
        
        if conflito:
            flash('Este horário já foi reservado. Por favor, escolha outro.', 'danger')
            return redirect(url_for('agendar_cliente', slug=slug))

        cliente = cliente_existente_tel
        if not cliente:
            cliente = Cliente(nome=nome, telefone=telefone)
            db.session.add(cliente)
            db.session.flush()

        novo = Agendamento(cliente_id=cliente.id, servico_id=servico_id, data_hora=data_hora, status='Pendente')
        db.session.add(novo)
        db.session.commit()
        flash('Agendamento solicitado! Aguarde a confirmação do barbeiro.', 'success')
        
        login_user(cliente)
        return redirect(url_for('cliente_painel', slug=slug))

    servicos = Servico.query.all()
    return render_template('cliente_agendar.html', servicos=servicos, config=config)

# --- PAINEL ADMINISTRATIVO ---
@app.route('/admin')
@login_required
def index():
    config = Configuracao.query.first()
    if not getattr(current_user, 'is_admin', False):
        return redirect(url_for('cliente_painel', slug=config.slug))
    
    hoje = datetime.now().date()
    agendamentos = Agendamento.query.filter(
        db.or_(
            Agendamento.status == 'Pendente',
            Agendamento.status == 'Confirmado',
            db.func.date(Agendamento.data_hora) == hoje
        )
    ).order_by(Agendamento.data_hora).all()
    
    return render_template('index.html', agendamentos=agendamentos, datetime=datetime, config=config)

@app.route('/admin/agendamentos')
@login_required
def listar_agendamentos():
    config = Configuracao.query.first()
    if not getattr(current_user, 'is_admin', False):
        return redirect(url_for('home_cliente', slug=config.slug))
    agendamentos = Agendamento.query.order_by(Agendamento.data_hora.desc()).all()
    return render_template('agendamentos.html', agendamentos=agendamentos, config=config)

@app.route('/admin/agendamento/novo', methods=['GET', 'POST'])
@login_required
def novo_agendamento():
    config = Configuracao.query.first()
    if not getattr(current_user, 'is_admin', False):
        return redirect(url_for('home_cliente', slug=config.slug))
    
    if request.method == 'POST':
        cliente_id = request.form.get('cliente_id')
        servico_id = request.form.get('servico_id')
        data_hora_str = request.form.get('data_hora')
        data_hora = datetime.strptime(data_hora_str, '%Y-%m-%dT%H:%M')
        
        novo = Agendamento(cliente_id=cliente_id, servico_id=servico_id, data_hora=data_hora, status='Confirmado')
        db.session.add(novo)
        db.session.commit()
        flash('Agendamento realizado com sucesso!', 'success')
        return redirect(url_for('index'))
        
    clientes = Cliente.query.all()
    servicos = Servico.query.all()
    return render_template('agendamento_form.html', clientes=clientes, servicos=servicos, config=config)

@app.route('/admin/agendamento/alterar/<int:id>', methods=['POST'])
@login_required
def alterar_data_agendamento(id):
    config = Configuracao.query.first()
    if not getattr(current_user, 'is_admin', False):
        return redirect(url_for('home_cliente', slug=config.slug))
    agendamento = Agendamento.query.get_or_404(id)
    nova_data_str = request.form.get('nova_data_hora')
    try:
        nova_data = datetime.strptime(nova_data_str, '%Y-%m-%dT%H:%M')
        agendamento.data_hora = nova_data
        db.session.commit()
        flash('Data alterada com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao alterar data: {str(e)}', 'danger')
    return redirect(request.referrer or url_for('listar_agendamentos'))

@app.route('/agendamento/confirmar/<int:id>')
@login_required
def confirmar_agendamento(id):
    config = Configuracao.query.first()
    if not getattr(current_user, 'is_admin', False): 
        return redirect(url_for('home_cliente', slug=config.slug))
    agendamento = Agendamento.query.get_or_404(id)
    agendamento.status = 'Confirmado'
    db.session.commit()
    flash('Agendamento confirmado com sucesso!', 'success')
    return redirect(request.referrer or url_for('index'))

@app.route('/agendamento/concluir/<int:id>')
@login_required
def concluir_agendamento(id):
    config = Configuracao.query.first()
    if not getattr(current_user, 'is_admin', False): 
        return redirect(url_for('home_cliente', slug=config.slug))
    agendamento = Agendamento.query.get_or_404(id)
    if agendamento.status != 'Concluído':
        agendamento.status = 'Concluído'
        cliente = Cliente.query.get(agendamento.cliente_id)
        cliente.cortes_realizados += 1
        cliente.fidelidade_pontos += 1
        if cliente.fidelidade_pontos >= 11:
             cliente.fidelidade_pontos = 0
             flash(f'Parabéns! {cliente.nome} ganhou um corte grátis!', 'info')
        db.session.commit()
        flash('Atendimento concluído!', 'success')
    return redirect(request.referrer or url_for('index'))

@app.route('/agendamento/cancelar_admin/<int:id>')
@login_required
def cancelar_agendamento_admin(id):
    config = Configuracao.query.first()
    if not getattr(current_user, 'is_admin', False): 
        return redirect(url_for('home_cliente', slug=config.slug))
    agendamento = Agendamento.query.get_or_404(id)
    agendamento.status = 'Cancelado'
    db.session.commit()
    flash('Agendamento cancelado.', 'info')
    return redirect(request.referrer or url_for('index'))

@app.route('/clientes')
@login_required
def listar_clientes():
    config = Configuracao.query.first()
    if not getattr(current_user, 'is_admin', False): 
        return redirect(url_for('home_cliente', slug=config.slug))
    clientes = Cliente.query.all()
    return render_template('clientes.html', clientes=clientes, config=config)

@app.route('/admin/cliente/novo', methods=['GET', 'POST'])
@login_required
def novo_cliente():
    config = Configuracao.query.first()
    if not getattr(current_user, 'is_admin', False):
        return redirect(url_for('home_cliente', slug=config.slug))
    
    if request.method == 'POST':
        nome = request.form.get('nome')
        telefone = request.form.get('telefone')
        email = request.form.get('email')
        
        if Cliente.query.filter_by(telefone=telefone).first():
            flash('Este telefone já está cadastrado!', 'danger')
        else:
            novo = Cliente(nome=nome, telefone=telefone, email=email)
            db.session.add(novo)
            db.session.commit()
            flash('Cliente cadastrado com sucesso!', 'success')
            return redirect(url_for('listar_clientes'))
            
    return render_template('cliente_form.html', config=config)

@app.route('/configuracoes', methods=['GET', 'POST'])
@login_required
def configuracoes():
    config = Configuracao.query.first()
    if not getattr(current_user, 'is_admin', False): 
        return redirect(url_for('home_cliente', slug=config.slug))
    servicos = Servico.query.all()
    if request.method == 'POST':
        config.nome_barbearia = request.form.get('nome_barbearia')
        config.slug = request.form.get('slug')
        config.horario_abertura = request.form.get('horario_abertura')
        config.horario_fechamento = request.form.get('horario_fechamento')
        config.intervalo_minutos = int(request.form.get('intervalo_minutos', 30))
        db.session.commit()
        flash('Configurações atualizadas!', 'success')
        return redirect(url_for('configuracoes'))
    return render_template('configuracoes.html', config=config, servicos=servicos)

@app.route('/servico/novo', methods=['POST'])
@login_required
def novo_servico():
    config = Configuracao.query.first()
    if not getattr(current_user, 'is_admin', False): 
        return redirect(url_for('home_cliente', slug=config.slug))
    nome = request.form.get('nome')
    preco = float(request.form.get('preco'))
    novo = Servico(nome=nome, preco=preco)
    db.session.add(novo)
    db.session.commit()
    flash('Serviço adicionado!', 'success')
    return redirect(url_for('configuracoes'))

@app.route('/servico/excluir/<int:id>')
@login_required
def excluir_servico(id):
    config = Configuracao.query.first()
    if not getattr(current_user, 'is_admin', False): 
        return redirect(url_for('home_cliente', slug=config.slug))
    servico = Servico.query.get_or_404(id)
    if Agendamento.query.filter_by(servico_id=id).first():
        flash('Não é possível excluir um serviço com agendamentos.', 'danger')
    else:
        db.session.delete(servico)
        db.session.commit()
        flash('Serviço excluído!', 'success')
    return redirect(url_for('configuracoes'))

@app.route('/cliente/excluir/<int:id>')
@login_required
def excluir_cliente(id):
    config = Configuracao.query.first()
    if not getattr(current_user, 'is_admin', False): 
        return redirect(url_for('home_cliente', slug=config.slug))
    cliente = Cliente.query.get_or_404(id)
    Agendamento.query.filter_by(cliente_id=id).delete()
    db.session.delete(cliente)
    db.session.commit()
    flash('Cliente excluído.', 'success')
    return redirect(url_for('listar_clientes'))

if __name__ == '__main__':
    app.run(debug=True)