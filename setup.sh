echo "Configurando ambiente virtual..."

python3 -m venv venv

source venv/bin/activate

echo "Instalando dependências..."
pip install Pyro5

source venv/bin/activate
echo "Ambiente configurado!"

echo "Iniciando o Name Server do Pyro5..."
python -m Pyro5.nameserver