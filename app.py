from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'chave_secreta_segura'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
db = SQLAlchemy(app)

# -------------------
# MODELOS
# -------------------

class Empresa(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)


class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    cargo = db.Column(db.String(100), nullable=False)
    setor = db.Column(db.String(100), nullable=False)
    empresa_id = db.Column(db.Integer, db.ForeignKey('empresa.id'), nullable=False)
    empresa = db.relationship('Empresa')


class Veiculo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    marca_modelo = db.Column(db.String(100), nullable=False)
    placa = db.Column(db.String(10), nullable=False, unique=True)
    cor = db.Column(db.String(30), nullable=False)
    franquia_km = db.Column(db.Integer, default=2000)


class Utilizacao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    veiculo_id = db.Column(db.Integer, db.ForeignKey('veiculo.id'), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    mes = db.Column(db.String(7), nullable=False)  # formato YYYY-MM
    km_inicial = db.Column(db.Integer, nullable=False)
    km_final = db.Column(db.Integer, nullable=False)

    veiculo = db.relationship('Veiculo')
    usuario = db.relationship('Usuario')

    def km_utilizado(self):
        return self.km_final - self.km_inicial

    def excedente(self):
        franquia = self.veiculo.franquia_km
        return max(0, self.km_utilizado() - franquia)


class Multa(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    veiculo_id = db.Column(db.Integer, db.ForeignKey('veiculo.id'), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    data = db.Column(db.Date, nullable=False)
    tipo = db.Column(db.String(255), nullable=False)
    valor = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), nullable=False)  # 'aberta' ou 'paga'

    veiculo = db.relationship('Veiculo')
    usuario = db.relationship('Usuario')


# -------------------
# ROTAS
# -------------------

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/cadastro_empresa', methods=['GET', 'POST'])
def cadastro_empresa():
    if request.method == 'POST':
        nome = request.form['nome']
        empresa = Empresa(nome=nome)
        db.session.add(empresa)
        db.session.commit()
        flash('Empresa cadastrada com sucesso!')
        return redirect(url_for('cadastro_empresa'))
    return render_template('cadastro_empresa.html')


@app.route('/cadastro_usuario', methods=['GET', 'POST'])
def cadastro_usuario():
    empresas = Empresa.query.all()
    if request.method == 'POST':
        nome = request.form['nome']
        cargo = request.form['cargo']
        setor = request.form['setor']
        empresa_id = request.form['empresa_id']
        usuario = Usuario(nome=nome, cargo=cargo, setor=setor, empresa_id=empresa_id)
        db.session.add(usuario)
        db.session.commit()
        flash('Usuário cadastrado com sucesso!')
        return redirect(url_for('cadastro_usuario'))
    return render_template('cadastro_usuario.html', empresas=empresas)


@app.route('/cadastro_veiculo', methods=['GET', 'POST'])
def cadastro_veiculo():
    if request.method == 'POST':
        marca_modelo = request.form['marca_modelo']
        placa = request.form['placa']
        cor = request.form['cor']
        veiculo = Veiculo(marca_modelo=marca_modelo, placa=placa, cor=cor)
        db.session.add(veiculo)
        db.session.commit()
        flash('Veículo cadastrado com sucesso!')
        return redirect(url_for('cadastro_veiculo'))
    return render_template('cadastro_veiculo.html')


@app.route('/cadastro_utilizacao', methods=['GET', 'POST'])
def cadastro_utilizacao():
    usuarios = Usuario.query.all()
    veiculos = Veiculo.query.all()
    if request.method == 'POST':
        usuario_id = request.form['usuario_id']
        veiculo_id = request.form['veiculo_id']
        mes = request.form['mes']
        km_inicial = int(request.form['km_inicial'])
        km_final = int(request.form['km_final'])
        uso = Utilizacao(usuario_id=usuario_id, veiculo_id=veiculo_id, mes=mes,
                         km_inicial=km_inicial, km_final=km_final)
        db.session.add(uso)
        db.session.commit()
        flash('Utilização registrada com sucesso!')
        return redirect(url_for('cadastro_utilizacao'))
    return render_template('utilizacao.html', usuarios=usuarios, veiculos=veiculos)


@app.route('/cadastro_multa', methods=['GET', 'POST'])
def cadastro_multa():
    usuarios = Usuario.query.all()
    veiculos = Veiculo.query.all()
    if request.method == 'POST':
        veiculo_id = request.form['veiculo_id']
        usuario_id = request.form['usuario_id']
        data = datetime.strptime(request.form['data'], '%Y-%m-%d')
        tipo = request.form['tipo']
        valor = float(request.form['valor'])
        status = request.form['status']
        multa = Multa(veiculo_id=veiculo_id, usuario_id=usuario_id, data=data,
                      tipo=tipo, valor=valor, status=status)
        db.session.add(multa)
        db.session.commit()
        flash('Multa registrada com sucesso!')
        return redirect(url_for('cadastro_multa'))
    return render_template('multas.html', usuarios=usuarios, veiculos=veiculos)


@app.route('/relatorios')
def relatorios():
    utilizacoes = Utilizacao.query.all()
    return render_template('relatorios.html', utilizacoes=utilizacoes)


# -------------------
# DB INIT
# -------------------



# -------------------
# EXECUTAR APP
# -------------------
# ...

# db.create_all será executado antes de rodar o servidor
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
