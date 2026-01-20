# Sistema de Gerenciamento de Barbearia (BarberManager)

Este é um sistema completo desenvolvido em Python com Flask para gestão de barbearias. Ideal para rodar localmente e gerenciar clientes, agendamentos e fidelidade.

## Funcionalidades

- **Controle de Clientes:** Cadastro e histórico.
- **Agendamentos:** Gestão de horários e serviços.
- **Sistema de Fidelidade:** A cada 10 cortes concluídos, o sistema alerta sobre o corte grátis.
- **Área do Cliente:** Página pública para clientes agendarem horários sem precisar de login.
- **Gestão de Preços:** Adicione, edite e exclua serviços e valores.
- **Controle Total ADM:** Exclua clientes, gerencie serviços e visualize a agenda de hoje.
- **Configuração Customizável:** Altere o nome da barbearia e horários de funcionamento.

## Acesso Administrativo
O sistema agora conta com uma tela de login para proteger os dados da barbearia.
- **Usuário padrão:** `admin`
- **Senha padrão:** `admin123`

*Dica: Você pode alterar essas credenciais diretamente no banco de dados ou expandir o sistema para ter uma tela de perfil.*

## Como Rodar Localmente

### 1. Pré-requisitos
Certifique-se de ter o Python instalado em sua máquina.

### 2. Instalar Dependências
Abra o terminal na pasta do projeto e execute:
```bash
pip install flask flask-sqlalchemy flask-login werkzeug
```

### 3. Executar o Sistema
No terminal, execute:
```bash
python app.py
```
- **Área do Cliente:** `http://127.0.0.1:5000/`
- **Painel Administrativo:** `http://127.0.0.1:5000/admin`

## Estrutura do Projeto
- `app.py`: Lógica principal e banco de dados (SQLite).
- `templates/`: Arquivos HTML da interface.
- `barbearia.db`: Banco de dados criado automaticamente na primeira execução.

## Dicas para Venda
Como o sistema usa SQLite, ele é "portátil". Você pode entregar a pasta para o cliente e ele terá tudo pronto. Para escalar, você pode hospedar em serviços como PythonAnywhere ou Heroku.
