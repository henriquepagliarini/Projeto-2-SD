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

        self.replies_received = 0
        self.deferred_replies = []

        self.lock = threading.Lock()
        self.request_event = threading.Event()

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
    
    def get_peers_count(self):
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

    def request_resource(self, peer_name):
        with self.lock:
            print(f"Requisição recebida de {peer_name}.")

            if self.state == State.HELD: # Fazer comparação de timestamp e id quando 'WANTED'
                # Resposta adiada
                print(f"Adiando resposta para {peer_name}.")
                self.deferred_replies.append(peer_name)
                return False
            else:
                # Resposta imediata
                print(f"Respondendo imediatamente para {peer_name}.")
                return True

    def enter_critical_section(self):
        with self.lock:
            if self.state == State.HELD:
                print(f"{self.name} já está na seção crítica.")
                return True

            self.state = State.WANTED
            self.replies_received = 0
            self.request_event.clear()

        print(f"Solicitando recurso...")

        request_threads = []
        for peer_name in self.get_active_peers():
            if peer_name != self.name:
                thread = threading.Thread(
                    target=self.send_request_notification, 
                    args=(peer_name,)
                )
                thread.daemon = True
                request_threads.append(thread)
                thread.start()

        print(f"Aguardando respostas...")
        self.request_event.wait(timeout=10)

        with self.lock:
            if self.replies_received >= self.get_peers_count():
                self.state = State.HELD
                print(f"Entrou na seção crítica.")
                return True
            else:
                self.state = State.RELEASED
                print(f"Não conseguiu entrar na seção crítica.")
                return False

    def send_request_notification(self, peer_name):
        try:
            with Pyro5.api.Proxy(f"PYRONAME:{peer_name}") as peer:
                if peer.request_resource(self.name):
                    with self.lock:
                        self.replies_received += 1
                        print(f"Resposta imediata de {peer_name} ({self.replies_received}/{self.get_peers_count()})")

                        if self.replies_received >= self.get_peers_count():
                            self.request_event.set()
        except Exception as e:
            print(f"Erro ao requisitar {peer_name}: {e}")

def start_peer(name):
    peer = Peer(name)

    # Registra o peer no servidor
    daemon = Pyro5.api.Daemon()
    uri = daemon.register(peer)
    ns = Pyro5.api.locate_ns()
    ns.register(name, uri, safe=True)
    print(f"Peer '{name}' iniciado e registrado!")

    threading.Thread(target=daemon.requestLoop, daemon=True).start()

    while True:
        print(f"---> {name}:")
        print("1. Requisitar recurso")
        print("2. Liberar recurso")
        print("3. Listar peers ativos")
        print("4. Sair")

        option = input("Escolha uma ação: ")

        match option:
            case '1':
                if peer.enter_critical_section():
                    print(f"{name} está acessando o recurso...")
                else:
                    print(f"{name} não conseguiu acessar o recurso.")
            case '2':
                # Implementar liberação de recurso
                print("Saindo do recurso...")
            case '3':
                print(f"Peers ativos:\n{peer.get_active_peers()}")
                print(f"Testando conectividade...")
                peer.test_connection()
            case '4':
                print("Saindo...")
                ns.remove(name)
                break
            case _:
                print("Opção inválida! (1 a 4)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python peer.py <nome_do_peer>")
        sys.exit(1)

    peer_name = sys.argv[1]
    start_peer(peer_name)