import os
import io
from datetime import datetime, date
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, send_file, send_from_directory
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, and_
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user
)

import pandas as pd

# -------------------------------------------------
# APP E CONFIG
# -------------------------------------------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "chave_secreta_segura_troque_em_producao")

# garante que a pasta instance existe
os.makedirs(app.instance_path, exist_ok=True)

# banco de dados dentro da pasta instance
db_path = os.path.join(app.instance_path, "database.db")
app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{db_path}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# uploads de checklists (PDF)
app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'uploads_checklists')
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024  # 20 MB
ALLOWED_EXTENSIONS = {'pdf'}
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)

# Flask-Login
login_manager = LoginManager(app)
login_manager.login_view = "login"  # rota de login
login_manager.login_message_category = "warning"


def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# -------------------------------------------------
# MODELOS
# -------------------------------------------------
class Empresa(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)


class Usuario(db.Model):
    """Este é o 'condutor' do seu sistema (motorista), já existente no seu app."""
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    cargo = db.Column(db.String(100), nullable=False)
    setor = db.Column(db.String(100), nullable=False)


class Veiculo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    marca_modelo = db.Column(db.String(100), nullable=False)
    placa = db.Column(db.String(10), nullable=False, unique=True)
    cor = db.Column(db.String(30), nullable=False)
    franquia_km = db.Column(db.Integer, default=2000)
    empresa_id = db.Column(db.Integer, db.ForeignKey('empresa.id'), nullable=False)
    empresa = db.relationship('Empresa')
    data_locacao = db.Column(db.Date, nullable=False)
    disponivel = db.Column(db.Boolean, default=True)


class Utilizacao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    veiculo_id = db.Column(db.Integer, db.ForeignKey('veiculo.id'), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    empresa_id = db.Column(db.Integer, db.ForeignKey('empresa.id'), nullable=False)
    data_entrega = db.Column(db.Date, nullable=False)
    km_entrega = db.Column(db.Integer, nullable=False)
    data_devolucao = db.Column(db.Date, nullable=True)
    km_devolucao = db.Column(db.Integer, nullable=True)

    veiculo = db.relationship('Veiculo')
    usuario = db.relationship('Usuario')
    empresa = db.relationship('Empresa')

    def km_utilizado(self):
        if self.km_devolucao is not None and self.km_entrega is not None:
            return self.km_devolucao - self.km_entrega
        return 0

    def excedente(self):
        if self.km_devolucao is not None and self.km_entrega is not None:
            franquia = self.veiculo.franquia_km
            return max(0, self.km_utilizado() - franquia)
        return 0


class ControleKm(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    utilizacao_id = db.Column(db.Integer, db.ForeignKey('utilizacao.id'), nullable=False)
    mes_ano = db.Column(db.String(7), nullable=False)  # Ex: '2025-08'
    km_inicial_mes = db.Column(db.Integer, nullable=False)
    km_final_mes = db.Column(db.Integer, nullable=False)

    utilizacao = db.relationship('Utilizacao')

    def km_utilizado_mes(self):
        return self.km_final_mes - self.km_inicial_mes

    def excedente_mes(self):
        franquia = self.utilizacao.veiculo.franquia_km
        return max(0, self.km_utilizado_mes() - franquia)


class Multa(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=True)
    veiculo_id = db.Column(db.Integer, db.ForeignKey('veiculo.id'), nullable=True)

    centro_custo = db.Column(db.String(100), nullable=True)
    unidade = db.Column(db.String(100), nullable=True)
    modalidade = db.Column(db.String(100), nullable=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey('empresa.id'), nullable=True)
    placa = db.Column(db.String(10), nullable=False)
    mes_referencia = db.Column(db.String(7), nullable=True)
    infracao = db.Column(db.String(255), nullable=True)
    data_infracao = db.Column(db.Date, nullable=True)
    hora_infracao = db.Column(db.String(5), nullable=True)
    valor_termo_desc = db.Column(db.Float, nullable=True)
    desconto_realizado = db.Column(db.String(3), nullable=True)  # 'Sim' ou 'Não'
    enviado_email_rh = db.Column(db.String(3), nullable=True)  # 'Sim' ou 'Não'
    observacao = db.Column(db.Text, nullable=True)

    usuario = db.relationship('Usuario')
    veiculo = db.relationship('Veiculo')
    empresa = db.relationship('Empresa')


class ChecklistArquivo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    utilizacao_id = db.Column(db.Integer, db.ForeignKey('utilizacao.id'), nullable=False, index=True)
    nome_original = db.Column(db.String(255), nullable=False)
    nome_armazenado = db.Column(db.String(255), nullable=False)
    content_type = db.Column(db.String(100), default='application/pdf')
    tamanho_bytes = db.Column(db.Integer, nullable=True)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    utilizacao = db.relationship('Utilizacao')


# ------- Usuários do sistema (login) -------
class AppUser(db.Model, UserMixin):
    __tablename__ = "app_user"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)

    # Permissões simples
    is_admin = db.Column(db.Boolean, default=False)           # tudo
    can_edit = db.Column(db.Boolean, default=True)            # criar/editar registros
    can_delete = db.Column(db.Boolean, default=False)         # excluir registros
    can_manage_users = db.Column(db.Boolean, default=False)   # gerenciar usuários

    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, raw: str):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw: str) -> bool:
        return check_password_hash(self.password_hash, raw)

    def get_id(self):
        return str(self.id)  # UserMixin já faz isso, mas garantimos string

    @property
    def is_active(self):
        return self.active


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(AppUser, int(user_id))


# -------------------------------------------------
# PERMISSÕES / DECORATORS
# -------------------------------------------------
def require_admin(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return login_manager.unauthorized()
        if not current_user.is_admin:
            flash("Acesso restrito ao administrador.", "danger")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return wrapper


def require_perm(attr):
    """Permite admin OU usuários com atributo True, ex.: @require_perm('can_delete')"""
    def deco(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return login_manager.unauthorized()
            if current_user.is_admin or getattr(current_user, attr, False):
                return f(*args, **kwargs)
            flash("Você não tem permissão para esta ação.", "danger")
            # volta para página anterior ou home
            return redirect(request.referrer or url_for("index"))
        return wrapper
    return deco


# -------------------------------------------------
# HELPERS DE DATAS / MESES
# -------------------------------------------------
def mes_para_numero(mes_str):
    meses = {
        'JANEIRO': '01', 'FEVEREIRO': '02', 'MARÇO': '03', 'ABRIL': '04',
        'MAIO': '05', 'JUNHO': '06', 'JULHO': '07', 'AGOSTO': '08',
        'SETEMBRO': '09', 'OUTUBRO': '10', 'NOVEMBRO': '11', 'DEZEMBRO': '12'
    }
    return meses.get(mes_str.upper().strip(), None)


def get_mes_ano_para_db(mes_nome, ano=None):
    if not ano:
        ano = datetime.now().year
    mes_num = mes_para_numero(mes_nome)
    if mes_num:
        return f"{ano}-{mes_num}"
    return None


def get_meses():
    return [
        "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
        "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"
    ]


# -------------------------------------------------
# AUTENTICAÇÃO
# -------------------------------------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        user = AppUser.query.filter_by(username=username).first()
        if user and user.check_password(password) and user.active:
            login_user(user)
            
            next_url = request.args.get('next')
            return redirect(next_url or url_for('index'))
        flash('Usuário ou senha inválidos.', 'danger')

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    
    return redirect(url_for('login'))


# -------------------------------------------------
# CONFIGURAÇÕES → USUÁRIOS (ADMIN)
# -------------------------------------------------
@app.route('/config/usuarios', methods=['GET', 'POST'])
@login_required
@require_admin
def config_usuarios():
    # Criação de novo usuário
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        is_admin = bool(request.form.get('is_admin'))
        can_edit = bool(request.form.get('can_edit'))
        can_delete = bool(request.form.get('can_delete'))
        can_manage_users = bool(request.form.get('can_manage_users'))

        if not username or not password:
            flash("Informe usuário e senha.", "warning")
            return redirect(url_for('config_usuarios'))

        if AppUser.query.filter_by(username=username).first():
            flash("Já existe um usuário com este login.", "danger")
            return redirect(url_for('config_usuarios'))

        user = AppUser(
            username=username,
            is_admin=is_admin,
            can_edit=can_edit,
            can_delete=can_delete,
            can_manage_users=can_manage_users,
            active=True
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash("Usuário criado com sucesso!", "success")
        return redirect(url_for('config_usuarios'))

    usuarios = AppUser.query.order_by(AppUser.username).all()
    return render_template('config_usuarios.html', usuarios=usuarios)


@app.route('/config/usuarios/<int:user_id>/permissoes', methods=['POST'])
@login_required
@require_admin
def atualizar_permissoes(user_id):
    user = db.session.get(AppUser, user_id)
    if not user:
        flash("Usuário não encontrado.", "danger")
        return redirect(url_for('config_usuarios'))

    # Não deixar remover o último admin
    if user.is_admin and not request.form.get('is_admin'):
        admins = AppUser.query.filter_by(is_admin=True, active=True).count()
        if admins <= 1:
            flash("Não é possível remover o último administrador.", "danger")
            return redirect(url_for('config_usuarios'))

    user.is_admin = bool(request.form.get('is_admin'))
    user.can_edit = bool(request.form.get('can_edit'))
    user.can_delete = bool(request.form.get('can_delete'))
    user.can_manage_users = bool(request.form.get('can_manage_users'))
    user.active = bool(request.form.get('active'))
    db.session.commit()
    flash("Permissões atualizadas.", "success")
    return redirect(url_for('config_usuarios'))


@app.route('/config/usuarios/<int:user_id>/excluir', methods=['POST'])
@login_required
@require_admin
def excluir_usuario_sistema(user_id):
    user = db.session.get(AppUser, user_id)
    if not user:
        flash("Usuário não encontrado.", "danger")
        return redirect(url_for('config_usuarios'))

    # Protege contra exclusão do último admin
    if user.is_admin:
        admins = AppUser.query.filter_by(is_admin=True, active=True).count()
        if admins <= 1:
            flash("Não é possível excluir o último administrador.", "danger")
            return redirect(url_for('config_usuarios'))

    db.session.delete(user)
    db.session.commit()
    flash("Usuário excluído.", "success")
    return redirect(url_for('config_usuarios'))


# -------------------------------------------------
# ROTAS DE NEGÓCIO (protegidinhas)
# -------------------------------------------------
@app.route('/')
@login_required
def index():
    return render_template('index.html')


# ---------- EMPRESA ----------
@app.route('/cadastro_empresa', methods=['GET', 'POST'])
@login_required
@require_perm('can_edit')
def cadastro_empresa():
    if request.method == 'POST':
        nome = request.form['nome'].strip()
        if not nome:
            flash('Informe o nome da empresa.', 'danger')
            return redirect(url_for('cadastro_empresa'))
        empresa = Empresa(nome=nome)
        db.session.add(empresa)
        db.session.commit()
        flash('Empresa cadastrada com sucesso!', 'success')
        return redirect(url_for('cadastro_empresa'))

    empresas = Empresa.query.order_by(Empresa.nome).all()
    return render_template('cadastro_empresa.html', empresas=empresas)


@app.route('/excluir_empresa/<int:id>', methods=['POST'])
@login_required
@require_perm('can_delete')
def excluir_empresa(id):
    empresa = db.session.get(Empresa, id)
    if not empresa:
        flash('Empresa não encontrada.', 'danger')
        return redirect(url_for('cadastro_empresa'))

    tem_veiculos = Veiculo.query.filter_by(empresa_id=id).first()
    tem_utilizacoes = Utilizacao.query.filter_by(empresa_id=id).first()
    tem_multas = Multa.query.filter_by(empresa_id=id).first()

    if tem_veiculos or tem_utilizacoes or tem_multas:
        flash('Não é possível excluir a empresa: existem registros vinculados (veículos, utilizações ou multas).', 'danger')
        return redirect(url_for('cadastro_empresa'))

    db.session.delete(empresa)
    db.session.commit()
    flash('Empresa excluída com sucesso!', 'success')
    return redirect(url_for('cadastro_empresa'))


# ---------- USUÁRIO (CONDUTOR) ----------
@app.route('/cadastro_usuario', methods=['GET', 'POST'])
@login_required
@require_perm('can_edit')
def cadastro_usuario():
    usuarios = Usuario.query.order_by(Usuario.nome).all()
    if request.method == 'POST':
        nome = request.form['nome']
        cargo = request.form['cargo']
        setor = request.form['setor']
        usuario = Usuario(nome=nome, cargo=cargo, setor=setor)
        db.session.add(usuario)
        db.session.commit()
        flash('Usuário cadastrado com sucesso!', 'success')
        return redirect(url_for('cadastro_usuario'))
    return render_template('cadastro_usuario.html', usuarios=usuarios)


@app.route('/excluir_usuario/<int:id>', methods=['POST'])
@login_required
@require_perm('can_delete')
def excluir_usuario(id):
    usuario = db.session.get(Usuario, id)
    if not usuario:
        flash('Usuário não encontrado.', 'danger')
        return redirect(url_for('cadastro_usuario'))

    if Utilizacao.query.filter_by(usuario_id=id).first() or Multa.query.filter_by(usuario_id=id).first():
        flash('Não é possível excluir o usuário: existem registros vinculados (utilizações ou multas).', 'danger')
    else:
        db.session.delete(usuario)
        db.session.commit()
        flash('Usuário excluído com sucesso!', 'success')
    return redirect(url_for('cadastro_usuario'))


# ---------- VEÍCULO ----------
@app.route('/cadastro_veiculo', methods=['GET', 'POST'])
@login_required
@require_perm('can_edit')
def cadastro_veiculo():
    empresas = Empresa.query.order_by(Empresa.nome).all()
    if request.method == 'POST':
        marca_modelo = request.form['marca_modelo'].strip()
        placa = request.form['placa'].strip().upper()
        cor = request.form['cor'].strip()
        empresa_id = request.form['empresa_id']
        data_locacao = datetime.strptime(request.form['data_locacao'], '%Y-%m-%d').date()

        franquia_km_str = request.form.get('franquia_km')
        franquia_km = int(franquia_km_str) if franquia_km_str and franquia_km_str.isdigit() else 2000

        if Veiculo.query.filter(func.lower(Veiculo.placa) == func.lower(placa)).first():
            flash('Já existe um veículo com esta placa.', 'danger')
            return redirect(url_for('cadastro_veiculo'))

        veiculo = Veiculo(
            marca_modelo=marca_modelo,
            placa=placa,
            cor=cor,
            empresa_id=empresa_id,
            data_locacao=data_locacao,
            disponivel=True,
            franquia_km=franquia_km
        )
        db.session.add(veiculo)
        db.session.commit()
        flash('Veículo cadastrado com sucesso!', 'success')
        return redirect(url_for('cadastro_veiculo'))

    veiculos = Veiculo.query.order_by(Veiculo.placa).all()
    return render_template('cadastro_veiculo.html', empresas=empresas, veiculos=veiculos)


@app.route('/excluir_veiculo/<int:id>', methods=['POST'])
@login_required
@require_perm('can_delete')
def excluir_veiculo(id):
    veiculo = db.session.get(Veiculo, id)
    if not veiculo:
        flash('Veículo não encontrado.', 'danger')
        return redirect(url_for('cadastro_veiculo'))

    tem_utilizacoes = Utilizacao.query.filter_by(veiculo_id=id).first()
    tem_multas = Multa.query.filter_by(veiculo_id=id).first()

    if tem_utilizacoes or tem_multas:
        flash('Não é possível excluir o veículo: existem utilizações ou multas vinculadas a ele.', 'danger')
        return redirect(url_for('cadastro_veiculo'))

    db.session.delete(veiculo)
    db.session.commit()
    flash('Veículo excluído com sucesso!', 'success')
    return redirect(url_for('cadastro_veiculo'))


@app.route('/get_veiculo_data/<int:veiculo_id>')
@login_required
def get_veiculo_data(veiculo_id):
    veiculo = db.session.get(Veiculo, veiculo_id)
    if veiculo:
        ultimo_uso = Utilizacao.query.filter_by(veiculo_id=veiculo_id).order_by(Utilizacao.data_entrega.desc()).first()
        km_entrega_proximo = 0
        if ultimo_uso:
            if ultimo_uso.km_devolucao:
                km_entrega_proximo = ultimo_uso.km_devolucao
            else:
                ultimo_controle_km = ControleKm.query.join(Utilizacao).filter(Utilizacao.veiculo_id == veiculo_id).order_by(ControleKm.mes_ano.desc()).first()
                if ultimo_controle_km:
                    km_entrega_proximo = ultimo_controle_km.km_final_mes
                else:
                    km_entrega_proximo = ultimo_uso.km_entrega
        return {'empresa_id': veiculo.empresa_id, 'empresa_nome': veiculo.empresa.nome, 'km_entrega_proximo': km_entrega_proximo}
    return {'error': 'Veículo não encontrado'}


# ---------- UTILIZAÇÃO ----------
@app.route('/cadastro_utilizacao', methods=['GET', 'POST'])
@login_required
@require_perm('can_edit')
def cadastro_utilizacao():
    usuarios = Usuario.query.order_by(Usuario.nome).all()
    veiculos = Veiculo.query.filter_by(disponivel=True).order_by(Veiculo.placa).all()
    if request.method == 'POST':
        usuario_id = request.form['usuario_id']
        veiculo_id = request.form['veiculo_id']
        empresa_id = request.form['empresa_id']
        data_entrega = datetime.strptime(request.form['data_entrega'], '%Y-%m-%d').date()
        km_entrega = int(request.form['km_entrega'])

        uso = Utilizacao(
            usuario_id=usuario_id,
            veiculo_id=veiculo_id,
            empresa_id=empresa_id,
            data_entrega=data_entrega,
            km_entrega=km_entrega
        )
        db.session.add(uso)

        veiculo = db.session.get(Veiculo, veiculo_id)
        if veiculo:
            veiculo.disponivel = False

        db.session.commit()
        flash('Utilização registrada com sucesso!', 'success')
        return redirect(url_for('controle_utilizacao'))

    return render_template('utilizacao.html', usuarios=usuarios, veiculos=veiculos)


@app.route('/upload_checklist/<int:utilizacao_id>', methods=['POST'])
@login_required
@require_perm('can_edit')
def upload_checklist(utilizacao_id):
    utilizacao = db.session.get(Utilizacao, utilizacao_id)
    if not utilizacao:
        flash('Utilização não encontrada.', 'danger')
        return redirect(url_for('controle_utilizacao'))

    if 'arquivo' not in request.files:
        flash('Nenhum arquivo enviado.', 'danger')
        return redirect(url_for('controle_utilizacao'))

    file = request.files['arquivo']
    if file.filename == '':
        flash('Nenhum arquivo selecionado.', 'danger')
        return redirect(url_for('controle_utilizacao'))

    if not allowed_file(file.filename):
        flash('Formato inválido. Envie um PDF.', 'danger')
        return redirect(url_for('controle_utilizacao'))

    filename_seguro = secure_filename(file.filename)
    ts = datetime.utcnow().strftime('%Y%m%d%H%M%S%f')
    nome_armazenado = f"util_{utilizacao_id}_{ts}_{filename_seguro}"

    caminho = os.path.join(app.config['UPLOAD_FOLDER'], nome_armazenado)
    file.save(caminho)
    tamanho = os.path.getsize(caminho)

    registro = ChecklistArquivo(
        utilizacao_id=utilizacao_id,
        nome_original=filename_seguro,
        nome_armazenado=nome_armazenado,
        tamanho_bytes=tamanho
    )
    db.session.add(registro)
    db.session.commit()
    flash('Checklist (PDF) enviado com sucesso!', 'success')
    return redirect(url_for('controle_utilizacao'))


@app.route('/download_checklist/<int:arquivo_id>')
@login_required
def download_checklist(arquivo_id):
    arq = db.session.get(ChecklistArquivo, arquivo_id)
    if not arq:
        flash('Arquivo não encontrado.', 'danger')
        return redirect(url_for('controle_utilizacao'))

    return send_from_directory(
        app.config['UPLOAD_FOLDER'],
        arq.nome_armazenado,
        as_attachment=True,
        download_name=arq.nome_original,
        mimetype=arq.content_type
    )


@app.route('/excluir_checklist/<int:arquivo_id>', methods=['POST'])
@login_required
@require_perm('can_delete')
def excluir_checklist(arquivo_id):
    arq = db.session.get(ChecklistArquivo, arquivo_id)
    if not arq:
        flash('Arquivo não encontrado.', 'danger')
        return redirect(url_for('controle_utilizacao'))

    try:
        os.remove(os.path.join(app.config['UPLOAD_FOLDER'], arq.nome_armazenado))
    except FileNotFoundError:
        pass

    db.session.delete(arq)
    db.session.commit()
    flash('Arquivo excluído com sucesso!', 'success')
    return redirect(url_for('controle_utilizacao'))


@app.route('/controle_utilizacao')
@login_required
def controle_utilizacao():
    filtro = request.args.get('filtro', 'em_uso')

    if filtro == 'devolvidos':
        utilizacoes = (Utilizacao.query.filter(Utilizacao.data_devolucao.isnot(None))
                       .order_by(Utilizacao.data_devolucao.desc()).all())
    elif filtro == 'todos':
        utilizacoes = Utilizacao.query.order_by(Utilizacao.data_entrega.desc()).all()
    else:  # em_uso
        utilizacoes = (Utilizacao.query.filter(Utilizacao.data_devolucao.is_(None))
                       .order_by(Utilizacao.data_entrega.desc()).all())

    return render_template('controle_utilizacao.html',
                           utilizacoes=utilizacoes,
                           filtro_atual=filtro,
                           ChecklistArquivo=ChecklistArquivo)


@app.route('/controle_km_mensal/<int:utilizacao_id>', methods=['GET', 'POST'])
@login_required
@require_perm('can_edit')
def controle_km_mensal(utilizacao_id):
    utilizacao = db.session.get(Utilizacao, utilizacao_id)
    registros_km = ControleKm.query.filter_by(utilizacao_id=utilizacao_id).order_by(ControleKm.mes_ano.desc()).all()

    km_inicial_proximo = registros_km[0].km_final_mes if registros_km else utilizacao.km_entrega

    if request.method == 'POST':
        mes_ano = request.form['mes_ano']
        km_final_mes = int(request.form['km_final_mes'])
        km_inicial_mes = int(request.form['km_inicial_mes'])

        novo_registro = ControleKm(
            utilizacao_id=utilizacao_id,
            mes_ano=mes_ano,
            km_inicial_mes=km_inicial_mes,
            km_final_mes=km_final_mes
        )
        db.session.add(novo_registro)
        db.session.commit()
        flash('Registro de KM mensal salvo com sucesso!', 'success')
        return redirect(url_for('controle_km_mensal', utilizacao_id=utilizacao_id))

    return render_template('controle_km_mensal.html',
                           utilizacao=utilizacao,
                           registros_km=registros_km,
                           km_inicial_proximo=km_inicial_proximo)


@app.route('/excluir_controle_km/<int:id>', methods=['POST'])
@login_required
@require_perm('can_delete')
def excluir_controle_km(id):
    registro = db.session.get(ControleKm, id)
    utilizacao_id = registro.utilizacao_id
    db.session.delete(registro)
    db.session.commit()
    flash('Registro de KM mensal excluído com sucesso!', 'success')
    return redirect(url_for('controle_km_mensal', utilizacao_id=utilizacao_id))


@app.route('/devolucao/<int:id>', methods=['GET', 'POST'])
@login_required
@require_perm('can_edit')
def devolucao(id):
    utilizacao = db.session.get(Utilizacao, id)

    ultimo_registro_km_mensal = (ControleKm.query.join(Utilizacao)
                                 .filter(Utilizacao.id == id)
                                 .order_by(ControleKm.mes_ano.desc()).first())
    km_minimo = ultimo_registro_km_mensal.km_final_mes if ultimo_registro_km_mensal else utilizacao.km_entrega

    if request.method == 'POST':
        data_devolucao_str = request.form['data_devolucao']
        km_devolucao = int(request.form['km_devolucao'])

        if km_devolucao < km_minimo:
            flash(f"O KM de devolução não pode ser menor que o último KM registrado: {km_minimo}.", 'danger')
            return redirect(url_for('devolucao', id=id))

        data_devolucao = datetime.strptime(data_devolucao_str, '%Y-%m-%d').date()
        if data_devolucao > date.today():
            flash("A data de devolução não pode ser uma data futura.", 'danger')
            return redirect(url_for('devolucao', id=id))

        utilizacao.data_devolucao = data_devolucao
        utilizacao.km_devolucao = km_devolucao

        veiculo = db.session.get(Veiculo, utilizacao.veiculo_id)
        if veiculo:
            veiculo.disponivel = True

        db.session.commit()
        flash('Devolução registrada com sucesso!', 'success')
        return redirect(url_for('controle_utilizacao'))

    return render_template('devolucao.html', utilizacao=utilizacao, km_minimo=km_minimo)


@app.route('/excluir_utilizacao/<int:id>', methods=['POST'])
@login_required
@require_perm('can_delete')
def excluir_utilizacao(id):
    utilizacao = db.session.get(Utilizacao, id)
    veiculo = db.session.get(Veiculo, utilizacao.veiculo_id)
    if veiculo:
        veiculo.disponivel = True

    db.session.delete(utilizacao)
    db.session.commit()
    flash('Registro de utilização excluído com sucesso!', 'success')
    return redirect(url_for('controle_utilizacao'))


@app.route('/editar_utilizacao/<int:id>', methods=['GET', 'POST'])
@login_required
@require_perm('can_edit')
def editar_utilizacao(id):
    utilizacao = db.session.get(Utilizacao, id)
    usuarios = Usuario.query.order_by(Usuario.nome).all()

    veiculo_atual = db.session.get(Veiculo, utilizacao.veiculo_id)

    if utilizacao.data_devolucao:
        veiculos = Veiculo.query.order_by(Veiculo.placa).all()
    else:
        veiculos_disponiveis = Veiculo.query.filter_by(disponivel=True).order_by(Veiculo.placa).all()
        if veiculo_atual and veiculo_atual not in veiculos_disponiveis:
            veiculos = veiculos_disponiveis + [veiculo_atual]
        else:
            veiculos = veiculos_disponiveis

    if request.method == 'POST':
        veiculo_antigo = db.session.get(Veiculo, utilizacao.veiculo_id)
        if veiculo_antigo:
            veiculo_antigo.disponivel = True

        utilizacao.usuario_id = request.form['usuario_id']
        utilizacao.veiculo_id = request.form['veiculo_id']
        utilizacao.empresa_id = request.form['empresa_id']
        utilizacao.data_entrega = datetime.strptime(request.form['data_entrega'], '%Y-%m-%d').date()
        utilizacao.km_entrega = int(request.form['km_entrega'])

        veiculo_novo = db.session.get(Veiculo, utilizacao.veiculo_id)
        if veiculo_novo:
            veiculo_novo.disponivel = False

        db.session.commit()
        flash('Registro de utilização atualizado com sucesso!', 'success')
        return redirect(url_for('controle_utilizacao'))

    return render_template('editar_utilizacao.html', utilizacao=utilizacao, usuarios=usuarios, veiculos=veiculos)


# ---------- MULTAS ----------
@app.route('/cadastro_multa', methods=['GET', 'POST'])
@login_required
@require_perm('can_edit')
def cadastro_multa():
    empresas = Empresa.query.order_by(Empresa.nome).all()
    usuarios = Usuario.query.order_by(Usuario.nome).all()
    meses = get_meses()

    if request.method == 'POST':
        try:
            placa = request.form.get('placa')
            if not placa:
                raise ValueError("O campo 'Placa' é obrigatório e não pode ser vazio.")

            usuario_id = request.form.get('usuario_id')
            if not usuario_id or not usuario_id.isdigit():
                raise ValueError("ID do usuário inválido.")

            empresa_id = request.form.get('empresa_id')

            veiculo = Veiculo.query.filter(func.lower(Veiculo.placa) == func.lower(placa)).first()
            if not veiculo:
                raise ValueError(f"Veículo com a placa '{placa}' não encontrado.")

            usuario = db.session.get(Usuario, int(usuario_id))
            if not usuario:
                raise ValueError("Condutor não encontrado.")

            empresa = db.session.get(Empresa, int(empresa_id))
            if not empresa:
                raise ValueError("Empresa não encontrada.")

            mes_referencia_nome = request.form.get('mes_referencia_nome')
            mes_referencia = get_mes_ano_para_db(mes_referencia_nome)

            hora_infracao_str = request.form.get('hora_infracao')
            if hora_infracao_str:
                hora_infracao = datetime.strptime(hora_infracao_str, '%H:%M').strftime('%H:%M')
            else:
                hora_infracao = None

            nova_multa = Multa(
                usuario_id=usuario.id,
                veiculo_id=veiculo.id,
                empresa_id=empresa.id,
                centro_custo=usuario.setor,
                unidade=request.form.get('unidade'),
                modalidade=request.form.get('modalidade'),
                data_infracao=datetime.strptime(request.form.get('data_infracao'), '%Y-%m-%d').date(),
                hora_infracao=hora_infracao,
                placa=placa,
                mes_referencia=mes_referencia,
                infracao=request.form.get('infracao'),
                valor_termo_desc=float(request.form.get('valor_termo_desc')),
                desconto_realizado=request.form.get('desconto_realizado'),
                enviado_email_rh=request.form.get('enviado_email_rh'),
                observacao=request.form.get('observacao')
            )

            db.session.add(nova_multa)
            db.session.commit()
            flash('Multa registrada com sucesso!', 'success')
            return redirect(url_for('cadastro_multa'))

        except (ValueError, TypeError) as e:
            flash(f"Erro ao registrar a multa: {e}", 'danger')
            return redirect(url_for('cadastro_multa'))
        except Exception as e:
            db.session.rollback()
            flash(f"Ocorreu um erro inesperado: {e}", 'danger')
            return redirect(url_for('cadastro_multa'))

    return render_template('multas.html', empresas=empresas, usuarios=usuarios, meses=meses)


@app.route('/consultar_multas_por_condutor/<int:usuario_id>')
@login_required
def consultar_multas_por_condutor(usuario_id):
    usuario = db.session.get(Usuario, usuario_id)
    if not usuario:
        flash('Condutor não encontrado.', 'danger')
        return redirect(url_for('cadastro_multa'))
    multas_usuario = Multa.query.filter_by(usuario_id=usuario_id).order_by(Multa.data_infracao.desc()).all()
    return render_template('consultar_multas_por_condutor.html', usuario=usuario, multas=multas_usuario)


@app.route('/importar_multas', methods=['GET', 'POST'])
@login_required
@require_perm('can_edit')
def importar_multas():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('Nenhum arquivo enviado!', 'danger')
            return redirect(url_for('importar_multas'))

        file = request.files['file']
        if file.filename == '':
            flash('Nenhum arquivo selecionado!', 'danger')
            return redirect(url_for('importar_multas'))

        filename = file.filename
        try:
            if filename.endswith('.xlsx') or filename.endswith('.xls'):
                df = pd.read_excel(file)
            elif filename.endswith('.csv'):
                df = pd.read_csv(file)
            else:
                flash('Formato de arquivo não suportado. Use .xlsx ou .csv', 'danger')
                return redirect(url_for('importar_multas'))

            df.columns = df.columns.str.strip().str.replace('  ', ' ')
            df = df.rename(columns={
                'Condutor (a)': 'condutor',
                'Centro de Custo': 'centro_custo',
                'Unidade': 'unidade',
                'Modalidade': 'modalidade',
                'Empresa': 'empresa',
                'Placa': 'placa',
                'Mês de Referência': 'mes_referencia',
                'Infração': 'infracao',
                'Data da Infração': 'data_infracao',
                'Hora': 'hora_infracao',
                'Valor Termo Desc.': 'valor_termo_desc',
                'Desconto Realizado': 'desconto_realizado',
                'ENVIADO E-MAIL AO RH?': 'enviado_email_rh',
                'Observação': 'observacao'
            })

            if 'Unnamed: 0' in df.columns:
                df = df.drop(columns=['Unnamed: 0'])

            for _, row in df.iterrows():
                try:
                    condutor_nome = str(row['condutor']).strip() if pd.notna(row['condutor']) else None
                    placa_multa = str(row['placa']).strip() if pd.notna(row['placa']) else None
                    infracao_multa = str(row['infracao']).strip() if pd.notna(row['infracao']) else None
                    data_infracao_multa = pd.to_datetime(row['data_infracao'], errors='coerce').date() if pd.notna(row['data_infracao']) else None

                    if Multa.query.filter(
                        Multa.placa == placa_multa,
                        Multa.data_infracao == data_infracao_multa,
                        Multa.infracao == infracao_multa
                    ).first():
                        flash(f'Registro duplicado ignorado para a placa {row["placa"]}.', 'warning')
                        continue

                    usuario = Usuario.query.filter(func.lower(Usuario.nome) == func.lower(condutor_nome)).first()
                    usuario_id = usuario.id if usuario else None

                    veiculo = Veiculo.query.filter(func.lower(Veiculo.placa) == func.lower(placa_multa)).first()
                    veiculo_id = veiculo.id if veiculo else None

                    empresa = Empresa.query.filter(func.lower(Empresa.nome) == func.lower(str(row['empresa']).strip())).first()
                    empresa_id = empresa.id if empresa else None

                    hora_infracao = None
                    if pd.notna(row['hora_infracao']):
                        try:
                            time_obj = pd.to_datetime(str(row['hora_infracao']), format='%H:%M:%S', errors='coerce').time()
                            if time_obj:
                                hora_infracao = time_obj.strftime('%H:%M')
                            else:
                                hora_infracao = str(row['hora_infracao']).strip()[:5]
                        except Exception:
                            hora_infracao = str(row['hora_infracao']).strip()[:5]

                    valor_termo_desc = pd.to_numeric(str(row['valor_termo_desc']).replace('R$', '').replace(',', '.'), errors='coerce') if pd.notna(row['valor_termo_desc']) else None

                    mes_referencia_str = str(row['mes_referencia']) if pd.notna(row['mes_referencia']) else None
                    mes_referencia = None
                    if mes_referencia_str:
                        partes = mes_referencia_str.split()
                        if len(partes) >= 2:
                            mes_nome = partes[0]
                            ano = partes[-1]
                            mes_referencia = get_mes_ano_para_db(mes_nome, ano)
                        elif len(partes) == 1:
                            mes_nome = partes[0]
                            mes_referencia = get_mes_ano_para_db(mes_nome)

                    if not (usuario_id and veiculo_id and empresa_id):
                        flash(f'Atenção: Não foi possível encontrar um usuário, veículo ou empresa para o registro de placa {str(row['placa'])}. Registro ignorado.', 'warning')
                        continue

                    multa = Multa(
                        usuario_id=usuario_id,
                        veiculo_id=veiculo_id,
                        centro_custo=str(row['centro_custo']).strip() if pd.notna(row['centro_custo']) else None,
                        unidade=str(row['unidade']).strip() if pd.notna(row['unidade']) else None,
                        modalidade=str(row['modalidade']).strip() if pd.notna(row['modalidade']) else None,
                        empresa_id=empresa_id,
                        placa=placa_multa,
                        mes_referencia=mes_referencia,
                        infracao=infracao_multa,
                        data_infracao=data_infracao_multa,
                        hora_infracao=hora_infracao,
                        valor_termo_desc=valor_termo_desc,
                        desconto_realizado=str(row['desconto_realizado']).strip() if pd.notna(row['desconto_realizado']) else None,
                        enviado_email_rh=str(row['enviado_email_rh']).strip() if pd.notna(row['enviado_email_rh']) else None,
                        observacao=str(row['observacao']).strip() if pd.notna(row['observacao']) else None
                    )
                    db.session.add(multa)

                except Exception as e:
                    flash(f'Erro ao processar a linha da planilha. Detalhes: {e}', 'warning')
                    continue

            db.session.commit()
            flash('Planilha importada com sucesso!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao processar a planilha: {e}', 'danger')

        return redirect(url_for('cadastro_multa'))

    return render_template('importar_multas.html')


@app.route('/relatorio_multas', methods=['GET'])
@login_required
def relatorio_multas():
    multas = []
    veiculos = Veiculo.query.order_by(Veiculo.placa).all()

    if any(request.args.get(key) for key in ['data_inicio', 'data_fim', 'veiculo_id']):
        query = Multa.query

        data_inicio_str = request.args.get('data_inicio')
        data_fim_str = request.args.get('data_fim')
        veiculo_id = request.args.get('veiculo_id')

        if data_inicio_str:
            data_inicio = datetime.strptime(data_inicio_str, '%Y-%m-%d').date()
            query = query.filter(Multa.data_infracao >= data_inicio)

        if data_fim_str:
            data_fim = datetime.strptime(data_fim_str, '%Y-%m-%d').date()
            query = query.filter(Multa.data_infracao <= data_fim)

        if veiculo_id and veiculo_id.isdigit():
            query = query.filter(Multa.veiculo_id == int(veiculo_id))

        multas = query.order_by(Multa.data_infracao.desc()).all()

    return render_template('relatorio_multas.html', multas=multas, veiculos=veiculos)


@app.route('/exportar_multas_excel', methods=['GET'])
@login_required
def exportar_multas_excel():
    query = Multa.query

    data_inicio_str = request.args.get('data_inicio')
    data_fim_str = request.args.get('data_fim')
    veiculo_id = request.args.get('veiculo_id')

    if data_inicio_str:
        data_inicio = datetime.strptime(data_inicio_str, '%Y-%m-%d').date()
        query = query.filter(Multa.data_infracao >= data_inicio)

    if data_fim_str:
        data_fim = datetime.strptime(data_fim_str, '%Y-%m-%d').date()
        query = query.filter(Multa.data_infracao <= data_fim)

    if veiculo_id and veiculo_id.isdigit():
        query = query.filter(Multa.veiculo_id == int(veiculo_id))

    multas = query.order_by(Multa.data_infracao.desc()).all()

    data_list = []
    for multa in multas:
        mes_extenso = '-'
        if multa.mes_referencia:
            mes_num = multa.mes_referencia.split('-')[1]
            meses_por_extenso = {
                '01': 'Janeiro', '02': 'Fevereiro', '03': 'Março', '04': 'Abril',
                '05': 'Maio', '06': 'Junho', '07': 'Julho', '08': 'Agosto',
                '09': 'Setembro', '10': 'Outubro', '11': 'Novembro', '12': 'Dezembro'
            }
            mes_extenso = meses_por_extenso.get(mes_num, '-')

        data_list.append({
            'Condutor': multa.usuario.nome if multa.usuario else '-',
            'Centro de Custo': multa.centro_custo if multa.centro_custo else '-',
            'Unidade': multa.unidade if multa.unidade else '-',
            'Modalidade': multa.modalidade if multa.modalidade else '-',
            'Empresa': multa.empresa.nome if multa.empresa else '-',
            'Placa': multa.placa,
            'Mês de Referência': mes_extenso,
            'Infração': multa.infracao,
            'Data da Infração': multa.data_infracao.strftime('%d/%m/%Y') if multa.data_infracao else '-',
            'Hora': multa.hora_infracao if multa.hora_infracao else '-',
            'Valor Termo Desc.': multa.valor_termo_desc if multa.valor_termo_desc else '-',
            'Desconto Realizado': multa.desconto_realizado if multa.desconto_realizado else '-',
            'ENVIADO E-MAIL AO RH?': multa.enviado_email_rh if multa.enviado_email_rh else '-',
            'Observação': multa.observacao if multa.observacao else '-'
        })

    df = pd.DataFrame(data_list)

    output = io.BytesIO()
    writer = pd.ExcelWriter(output, engine='xlsxwriter')
    df.to_excel(writer, index=False, sheet_name='Relatório de Multas')
    writer.close()
    output.seek(0)

    filename = f"relatorio_multas_{datetime.now().strftime('%Y%m%d%H%M%S')}.xlsx"
    return send_file(output, as_attachment=True, download_name=filename, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@app.route('/consultar_multas_por_utilizacao/<int:utilizacao_id>')
@login_required
def consultar_multas_por_utilizacao(utilizacao_id):
    utilizacao = db.session.get(Utilizacao, utilizacao_id)
    if not utilizacao:
        flash('Registro de utilização não encontrado.', 'danger')
        return redirect(url_for('controle_utilizacao'))

    multas = Multa.query.filter_by(usuario_id=utilizacao.usuario_id, veiculo_id=utilizacao.veiculo_id).order_by(Multa.data_infracao.desc()).all()
    return render_template('consultar_multas_por_utilizacao.html', utilizacao=utilizacao, multas=multas)


@app.route('/consultar_multas_por_condutor_relatorio/<int:usuario_id>')
@login_required
def consultar_multas_por_condutor_relatorio(usuario_id):
    usuario = db.session.get(Usuario, usuario_id)
    if not usuario:
        flash('Condutor não encontrado.', 'danger')
        return redirect(url_for('relatorio_km'))

    multas = Multa.query.filter_by(usuario_id=usuario_id).order_by(Multa.data_infracao.desc()).all()
    return render_template('consultar_multas_por_condutor.html', usuario=usuario, multas=multas)


@app.route('/editar_multa/<int:id>', methods=['GET', 'POST'])
@login_required
@require_perm('can_edit')
def editar_multa(id):
    multa = db.session.get(Multa, id)
    empresas = Empresa.query.order_by(Empresa.nome).all()
    meses_pt = [
        "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
        "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"
    ]

    back_url = url_for('relatorio_multas')
    if multa and multa.usuario_id and multa.veiculo_id:
        try:
            utilizacao = Utilizacao.query.filter_by(usuario_id=multa.usuario_id, veiculo_id=multa.veiculo_id).first()
            if utilizacao:
                back_url = url_for('consultar_multas_por_utilizacao', utilizacao_id=utilizacao.id)
            else:
                back_url = url_for('consultar_multas_por_condutor_relatorio', usuario_id=multa.usuario_id)
        except Exception:
            pass

    if request.method == 'POST':
        multa.centro_custo = request.form['centro_custo']
        multa.unidade = request.form['unidade']
        multa.modalidade = request.form['modalidade']
        multa.empresa_id = request.form['empresa_id']
        multa.placa = request.form['placa']

        mes_referencia_str = request.form['mes_referencia_nome']
        mes_referencia = get_mes_ano_para_db(mes_referencia_str)
        multa.mes_referencia = mes_referencia

        multa.infracao = request.form['infracao']
        multa.data_infracao = datetime.strptime(request.form['data_infracao'], '%Y-%m-%d').date()
        multa.hora_infracao = request.form['hora_infracao']
        multa.valor_termo_desc = float(request.form['valor_termo_desc'])
        multa.desconto_realizado = request.form['desconto_realizado']
        multa.enviado_email_rh = request.form['enviado_email_rh']
        multa.observacao = request.form['observacao']

        db.session.commit()
        flash('Multa atualizada com sucesso!', 'success')
        return redirect(back_url)

    return render_template('editar_multa.html', multa=multa, empresas=empresas, meses=meses_pt, back_url=back_url)


@app.route('/excluir_multa/<int:id>', methods=['POST'])
@login_required
@require_perm('can_delete')
def excluir_multa(id):
    multa = db.session.get(Multa, id)

    back_url = url_for('relatorio_multas')
    if multa and multa.usuario_id:
        try:
            utilizacao = Utilizacao.query.filter_by(usuario_id=multa.usuario_id, veiculo_id=multa.veiculo_id).first()
            if utilizacao:
                back_url = url_for('consultar_multas_por_utilizacao', utilizacao_id=utilizacao.id)
            else:
                back_url = url_for('consultar_multas_por_condutor_relatorio', usuario_id=multa.usuario_id)
        except Exception:
            pass

    if not multa:
        flash('Multa não encontrada.', 'danger')
        return redirect(back_url)

    db.session.delete(multa)
    db.session.commit()
    flash('Multa excluída com sucesso!', 'success')
    return redirect(back_url)


# ---------- RELATÓRIO KM ----------
@app.route('/relatorio_km', methods=['GET'])
@login_required
def relatorio_km():
    veiculos_todos = Veiculo.query.order_by(Veiculo.placa).all()
    usuarios_todos = Usuario.query.order_by(Usuario.nome).all()

    report_data = None

    mes_ano_inicio_str = request.args.get('mes_ano_inicio')
    mes_ano_fim_str = request.args.get('mes_ano_fim')
    veiculo_id_str = request.args.get('veiculo_id')
    usuario_id_str = request.args.get('usuario_id')

    if veiculo_id_str or usuario_id_str:
        veiculo_selecionado = db.session.get(Veiculo, veiculo_id_str) if veiculo_id_str and veiculo_id_str.isdigit() else None
        usuario_selecionado = db.session.get(Usuario, usuario_id_str) if usuario_id_str and usuario_id_str.isdigit() else None

        leitura_atual = 0
        if veiculo_selecionado:
            ultimo_controle_km = (ControleKm.query.join(Utilizacao)
                                  .filter(Utilizacao.veiculo_id == veiculo_selecionado.id)
                                  .order_by(ControleKm.mes_ano.desc()).first())
            if ultimo_controle_km:
                leitura_atual = ultimo_controle_km.km_final_mes
            else:
                ultimo_uso_devolvido = (Utilizacao.query
                                        .filter(Utilizacao.veiculo_id == veiculo_selecionado.id,
                                                Utilizacao.km_devolucao.isnot(None))
                                        .order_by(Utilizacao.data_devolucao.desc()).first())
                if ultimo_uso_devolvido:
                    leitura_atual = ultimo_uso_devolvido.km_devolucao
                else:
                    primeiro_uso = (Utilizacao.query.filter_by(veiculo_id=veiculo_selecionado.id)
                                    .order_by(Utilizacao.data_entrega).first())
                    leitura_atual = primeiro_uso.km_entrega if primeiro_uso else 0

        km_inicial_carro = 0
        if veiculo_selecionado:
            primeiro_uso = Utilizacao.query.filter_by(veiculo_id=veiculo_selecionado.id).order_by(Utilizacao.data_entrega).first()
            km_inicial_carro = primeiro_uso.km_entrega if primeiro_uso else 0

        km_por_motorista = []
        query_km_motorista = db.session.query(
            Usuario.nome,
            func.sum(ControleKm.km_final_mes - ControleKm.km_inicial_mes)
        ).join(Utilizacao, ControleKm.utilizacao_id == Utilizacao.id).join(Usuario, Utilizacao.usuario_id == Usuario.id)

        if mes_ano_inicio_str and mes_ano_fim_str:
            query_km_motorista = query_km_motorista.filter(ControleKm.mes_ano.between(mes_ano_inicio_str, mes_ano_fim_str))

        if veiculo_selecionado:
            query_km_motorista = query_km_motorista.filter(Utilizacao.veiculo_id == veiculo_selecionado.id)

        if usuario_selecionado:
            query_km_motorista = query_km_motorista.filter(Utilizacao.usuario_id == usuario_selecionado.id)

        km_por_motorista = query_km_motorista.group_by(Usuario.nome).all()

        km_total_rodado_periodo = 0
        if mes_ano_inicio_str and mes_ano_fim_str:
            filtros_base = [ControleKm.mes_ano.between(mes_ano_inicio_str, mes_ano_fim_str)]
            if veiculo_selecionado:
                filtros_base.append(Utilizacao.veiculo_id == veiculo_selecionado.id)
            if usuario_selecionado:
                filtros_base.append(Utilizacao.usuario_id == usuario_selecionado.id)

            primeiro_registro_periodo = (ControleKm.query.join(Utilizacao)
                                         .filter(and_(*filtros_base))
                                         .order_by(ControleKm.mes_ano).first())
            ultimo_registro_periodo = (ControleKm.query.join(Utilizacao)
                                       .filter(and_(*filtros_base))
                                       .order_by(ControleKm.mes_ano.desc()).first())

            if primeiro_registro_periodo and ultimo_registro_periodo:
                km_total_rodado_periodo = ultimo_registro_periodo.km_final_mes - primeiro_registro_periodo.km_inicial_mes

        report_data = {
            'veiculo_selecionado': veiculo_selecionado,
            'usuario_selecionado': usuario_selecionado,
            'km_inicial_carro': km_inicial_carro,
            'leitura_atual': leitura_atual,
            'km_total_rodado_periodo': km_total_rodado_periodo,
            'km_por_motorista': km_por_motorista,
            'data_inicio': mes_ano_inicio_str,
            'data_fim': mes_ano_fim_str
        }

    return render_template('relatorio_km.html',
                           veiculos=veiculos_todos,
                           usuarios=usuarios_todos,
                           report_data=report_data)


# -------------------------------------------------
# BOOTSTRAP INICIAL: cria admin/admin se não existir
# -------------------------------------------------
def ensure_initial_admin():
    if not AppUser.query.filter_by(username="admin").first():
        user = AppUser(
            username="admin",
            is_admin=True,
            can_edit=True,
            can_delete=True,
            can_manage_users=True,
            active=True
        )
        user.set_password("admin")
        db.session.add(user)
        db.session.commit()
        print(">> Usuário inicial criado: admin / admin")


# -------------------------------------------------
# EXECUTAR APP
# -------------------------------------------------
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        ensure_initial_admin()
    # Em produção, use gunicorn. Para dev local:
    app.run(host='0.0.0.0', port=5000, debug=True)
