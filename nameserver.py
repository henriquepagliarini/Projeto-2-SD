import subprocess
import time
import Pyro5

def start_nameserver():
    try:
        ns = Pyro5.api.locate_ns()
        print("Servidor de nomes Pyro encontrado.")
        return ns
    except Pyro5.errors.NamingError:
        print("Servidor de nomes Pyro não encontrado. Criando subprocesso...")
        subprocess.Popen(
            ["python", "-m", "Pyro5.nameserver"], 
            stdout=subprocess.DEVNULL, 
            stderr=subprocess.DEVNULL
        )
        time.sleep(3)
        ns = Pyro5.api.locate_ns()
        print("Servidor de nomes Pyro criado.")
        return ns

def kill_nameserver():
    try:
        print("Encerrando o servidor de nomes...")
        subprocess.run(
            ["pkill", "-f", "Pyro5.nameserver"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        print("Servidor de nomes encerrado com sucesso.")
    except Exception as e:
        print(f"Erro ao encerrar o servidor de nomes: {e}")
