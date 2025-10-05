from enum import Enum
import subprocess
import sys
import threading
import time

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
        self.timestamp = 0
        self.request_timestamp = None

        self.replies_received = 0
        self.deferred_replies = []

        self.lock = threading.Lock()
        self.request_event = threading.Event()

        # Todos em segundos
        self.MAX_WAIT_TIME = 10
        self.MAX_ACCESS_TIME = 6

    def hello(self):
        return f"Hi from {self.name}"

    def get_active_peers(self):
        try:
            with Pyro5.api.locate_ns() as ns:
                peers = ns.list(prefix="Peer")
                active_peers = [p for p in peers if p != self.name]
            return active_peers
        except Exception as e:
            print(f"[{self.name}]: Erro ao consultar nameserver: {e}")
        return []

    def get_peers_count(self):
        return len(self.get_active_peers())

    def test_connection(self):
        active_peers = self.get_active_peers()
        for peer_name in active_peers:
            try:
                with Pyro5.api.Proxy(f"PYRONAME:{peer_name}") as peer:
                    response = peer.hello()
                    print(f"[{self.name}]: {response}")
            except Exception as e:
                print(f"[{self.name}]: {peer_name} não respondeu: {e}")

    def increment_timestamp(self):
        self.timestamp += 1
        return self.timestamp

    def update_timestamp(self, request_timestamp):
        self.timestamp = max(self.timestamp, request_timestamp) + 1

    def has_priority(self, local_timestamp, requester_timestamp, requester_peer_name):
        if local_timestamp < requester_timestamp:
            return True
        if local_timestamp == requester_timestamp and self.name < requester_peer_name:
            return True
        return False

    def request_resource(self, requester_timestamp, requester_peer_name):
        with self.lock:
            print(f"\n[{self.name}]: Requisição recebida - ({requester_peer_name}, {requester_timestamp})")
            denied = self.state == State.HELD or (self.state == State.WANTED and self.has_priority(self.request_timestamp, requester_timestamp, requester_peer_name))
            self.update_timestamp(requester_timestamp)

            if denied:
                self.deferred_replies.append(requester_peer_name)
                print(f"[{self.name}]: Resposta de {requester_peer_name} adiada.")
                return False
            else:
                print(f"[{self.name}]: Respondendo {requester_peer_name} imediatamente.")
                return True

    def receive_reply(self, receiving_from_peer_name):
        with self.lock:
            if self.state == State.WANTED:
                self.replies_received += 1
                print(f"[{self.name}]: Resposta de {receiving_from_peer_name} recebida ({self.replies_received}/{self.get_peers_count()})")

                if self.replies_received >= self.get_peers_count():
                    self.request_event.set()

    def send_request_notification(self, request_timestamp, active_peer_name):
        try:
            with Pyro5.api.Proxy(f"PYRONAME:{active_peer_name}") as peer:
                if peer.request_resource(request_timestamp, self.name):
                    self.receive_reply(active_peer_name)
        except Exception as e:
            print(f"[{self.name}]: Erro ao requisitar {active_peer_name}: {e}")

    def send_release_notification(self):
        for peer_name in self.deferred_replies:
            try:
                with Pyro5.api.Proxy(f"PYRONAME:{peer_name}") as peer:
                    peer.receive_reply(self.name)
                    print(f"[{self.name}]: Enviou resposta adiada para {peer_name}")
            except Exception as e:
                print(f"[{self.name}]: Erro ao enviar resposta adiada para {peer_name}: {e}")
        self.deferred_replies.clear()

    def enter_critical_section(self):
        with self.lock:
            if self.state == State.HELD:
                print(f"[{self.name}]: Já está na seção crítica.")
                return True

            self.state = State.WANTED
            self.replies_received = 0
            self.request_event.clear()
            self.request_timestamp  = self.increment_timestamp()

        print(f"\n[{self.name}]: Solicitando recurso...")

        active_peers = self.get_active_peers()
        request_threads = []
        for active_peer_name in active_peers:
            if active_peer_name != self.name:
                thread = threading.Thread(
                    target=self.send_request_notification, 
                    args=(self.request_timestamp, active_peer_name,)
                )
                thread.daemon = True
                request_threads.append(thread)
                thread.start()

        print(f"[{self.name}]: Aguardando {self.get_peers_count()} respostas...")
        self.request_event.wait(timeout=self.MAX_WAIT_TIME)

        with self.lock:
            if self.replies_received >= self.get_peers_count():
                self.state = State.HELD
                self.request_timestamp = None

                timer = threading.Timer(self.MAX_ACCESS_TIME, self.exit_critical_section)
                timer.daemon = True
                timer.start()
                return True
            else:
                print(f"[{self.name}]: Timeout ao obter todas as respostas. Liberando peers em espera.")
                self.state = State.RELEASED
                self.send_release_notification()
                self.request_timestamp = None
                return False

    def exit_critical_section(self):
        with self.lock:
            if self.state != State.HELD:
                print(f"\n[{self.name}]: Não está na seção crítica.")
                return False
            
            print(f"\n[{self.name}]: Liberando recurso...")
            self.state = State.RELEASED
            self.send_release_notification()
            return True

def start_nameserver():
    try:
        ns = Pyro5.api.locate_ns()
        print("Servidor de nomes Pyro encontrado.")
        return ns
    except Pyro5.errors.NamingError:
        print("Servidor de nomes Pyro não encontrado. Criando subprocesso...")
        subprocess.Popen(["python", "-m", "Pyro5.nameserver"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)
        ns = Pyro5.api.locate_ns()
        print("Servidor de nomes Pyro criado.")
        return ns

def start_peer(name):
    ns = start_nameserver()

    peer = Peer(name)
    # Registra o peer no servidor
    daemon = Pyro5.api.Daemon()
    uri = daemon.register(peer)
    ns.register(name, uri, safe=True)
    print(f"Peer '{name}' iniciado e registrado!")
    threading.Thread(target=daemon.requestLoop, daemon=True).start()

    while True:
        print(f"\n---> {name}:")
        print("1. Requisitar recurso")
        print("2. Liberar recurso")
        print("3. Listar peers ativos")
        print("4. Sair")
        option = input("Escolha uma ação: ")

        match option:
            case '1':
                if peer.enter_critical_section():
                    print(f"[{name}]: Entrou na seção crítica.")
                else:
                    print(f"[{name}]: Não conseguiu entrar na seção crítica.")
            case '2':
                if peer.exit_critical_section():
                    print(f"[{name}]: Saiu da seção crítica.")
                else:
                    print(f"[{name}]: Não conseguiu sair da seção crítica.")
            case '3':
                print(f"\nPeers ativos:\n{peer.get_active_peers()}")
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