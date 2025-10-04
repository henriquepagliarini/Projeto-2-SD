from enum import Enum
import sys
import threading

import Pyro5.api

class State(Enum):
    RELEASED = 0
    WANTED = 1
    HELD = 2

@Pyro5.api.expose
class Peer:
    def __init__(self, name):
        self.name = name
        self.state = State.RELEASED

    def hello(self):
        return f"Hi from {self.name}"
    
    def get_active_peers(self):
        try:
            ns = Pyro5.api.locate_ns()
            peers = ns.list(prefix="Peer")
            active_peers = list(peers.keys())
            return active_peers
        except Exception as e:
            print(f"Erro ao consultar nameserver: {e}")
        return []
    
    def _get_peers_count(self):
        active_peers = self.get_active_peers()
        return len([p for p in active_peers if p != self.name])
    
    def test_connection(self):
        active_peers = self.get_active_peers()
        for peer_name in active_peers:
            if peer_name != self.name:
                try:
                    with Pyro5.api.Proxy(f"PYRONAME:{peer_name}") as peer:
                        response = peer.hello()
                        print(f"{peer_name} está respondendo: {response}")
                except Exception as e:
                    print(f"{peer_name} não está respondendo: {e}")

def start_peer(name):
    peer = Peer(name)

    # Registra o peer no servidor
    daemon = Pyro5.api.Daemon()
    uri = daemon.register(peer)
    ns = Pyro5.api.locate_ns()
    ns.register(name, uri)
    print(f"Peer '{name}' iniciado e registrado!")

    threading.Thread(target=daemon.requestLoop, daemon=True).start()

    while True:
        print(f"---> {name}:")
        print("1. Requisitar recurso")
        print("2. Liberar recurso")
        print("3. Listar peers ativos")
        print("4. Sair")

        option = input("Escolha uma ação: ").strip()

        match option:
            case '1':
                # Implementar requisição de recurso
                print("Requisitando recurso...")
            case '2':
                # Implementar liberação de recurso
                print("Saindo do recurso...")
            case '3':
                print(f"Peers ativos:\n{peer.get_active_peers()}")
                print(f"Testando conectividade...")
                peer.test_connection()
            case '4':
                print("Saindo...")
                break
            case _:
                print("Opção inválida! (1 a 4)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python peer.py <nome_do_peer>")
        sys.exit(1)

    peer_name = sys.argv[1]
    start_peer(peer_name)