echo "Configurando ambiente virtual..."

python3 -m venv venv

source venv/bin/activate

echo "Instalando dependências..."
pip install Pyro5

echo "Ambiente configurado! - Execute nos peers (source venv/bin/activate)"