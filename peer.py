import sys
import threading
import time

import Pyro5.api

import heartbeat
import nameserver
from state import State
import utils

@Pyro5.api.expose
class Peer:
    def __init__(self, name):
        self.name = name
        self.state = State.RELEASED
        self.timestamp = 0
        self.request_timestamp = None
        
        self.registered_peers = []
        self.active_peers = {}
        self.replies_received = 0
        self.deferred_replies = []

        self.lock = threading.Lock()
        self.heartbeat_lock = threading.Lock()
        self.request_event = threading.Event()

        # Todos em segundos
        self.MAX_WAIT_TIME = 15
        self.MAX_ACCESS_TIME = 8

    def hello(self):
        return f"Hi from {self.name}"

    def get_registered_peers(self):
        try:
            with Pyro5.api.locate_ns() as ns:
                peers = ns.list(prefix="Peer")
                return [p for p in peers if p != self.name]
        except Exception as e:
            utils.log(self.name, f"Erro ao consultar nameserver: {e}")
        return []

    def get_active_peers(self):
        with self.heartbeat_lock:
            return list(self.active_peers.keys())

    def get_peers_count(self):
        return len(self.get_active_peers())

    def test_connection(self):
        active_peers = self.get_active_peers()
        for peer_name in active_peers:
            try:
                with Pyro5.api.Proxy(f"PYRONAME:{peer_name}") as peer:
                    response = peer.hello()
                    utils.log(self.name, f"{response}")
            except Exception as e:
                utils.log(self.name, f"{peer_name} não respondeu: {e}")

    def check_registered_peers(self):
        registered_peers = self.get_registered_peers()
        for peer_name in registered_peers:
            try:
                with Pyro5.api.Proxy(f"PYRONAME:{peer_name}") as peer:
                    if peer.hello():
                        with self.heartbeat_lock:
                            if peer_name not in self.active_peers:
                                self.active_peers[peer_name] = time.time()
                                utils.log(self.name, f"Peer {peer_name} adicionado aos ativos.")
            except Exception:
                pass

    def receive_heartbeat(self, receiving_from_peer_name):
        with self.heartbeat_lock:
            self.active_peers[receiving_from_peer_name] = time.time()

    def increment_timestamp(self):
        self.timestamp += 1
        return self.timestamp

    def update_timestamp(self, request_timestamp):
        self.timestamp = max(self.timestamp, request_timestamp) + 1

    def request_resource(self, requester_timestamp, requester_peer_name):
        with self.lock:
            utils.log(self.name, f"Requisição recebida - ({requester_peer_name}, {requester_timestamp})")
            denied = self.state == State.HELD or (self.state == State.WANTED and utils.has_priority(self.request_timestamp, self.name, requester_timestamp, requester_peer_name))
            self.update_timestamp(requester_timestamp)

            if denied:
                self.deferred_replies.append(requester_peer_name)
                utils.log(self.name, f"Resposta de {requester_peer_name} adiada.")
                return False
            else:
                utils.log(self.name, f"Respondendo {requester_peer_name} imediatamente.")
                return True

    def receive_reply(self, receiving_from_peer_name):
        with self.lock:
            if self.state == State.WANTED:
                self.replies_received += 1
                utils.log(self.name, f"Resposta de {receiving_from_peer_name} recebida ({self.replies_received}/{self.get_peers_count()})")

                if self.replies_received >= self.get_peers_count():
                    self.request_event.set()

    def send_request_notification(self, request_timestamp, active_peer_name):
        try:
            with Pyro5.api.Proxy(f"PYRONAME:{active_peer_name}") as peer:
                if peer.request_resource(request_timestamp, self.name):
                    self.receive_reply(active_peer_name)
        except Exception as e:
            utils.log(self.name, f"Erro ao requisitar {active_peer_name}: {e}")

    def send_release_notification(self):
        for peer_name in self.deferred_replies:
            try:
                with Pyro5.api.Proxy(f"PYRONAME:{peer_name}") as peer:
                    peer.receive_reply(self.name)
                    utils.log(self.name, f"Enviou resposta adiada para {peer_name}")
            except Exception as e:
                utils.log(self.name, f"Erro ao enviar resposta adiada para {peer_name}: {e}")
        self.deferred_replies.clear()

    def enter_critical_section(self):
        with self.lock:
            if self.state == State.HELD:
                utils.log(self.name, f"Já está na seção crítica.")
                return True

            self.state = State.WANTED
            self.replies_received = 0
            self.request_event.clear()
            self.request_timestamp  = self.increment_timestamp()

        utils.log(self.name, f"Solicitando recurso...")

        active_peers = self.get_active_peers()
        for active_peer_name in active_peers:
            if active_peer_name != self.name:
                thread = threading.Thread(
                    target=self.send_request_notification, 
                    args=(self.request_timestamp, active_peer_name,)
                )
                thread.daemon = True
                thread.start()

        utils.log(self.name, f"Aguardando {self.get_peers_count()} respostas...")
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
                utils.log(self.name, f"Timeout ao obter todas as respostas. Liberando peers em espera.")
                self.state = State.RELEASED
                if self.deferred_replies:
                    self.send_release_notification()
                self.request_timestamp = None
                return False

    def exit_critical_section(self):
        with self.lock:
            if self.state != State.HELD:
                utils.log(self.name, f"Não está na seção crítica.")
                return False
            
            utils.log(self.name, f"Liberando recurso...")
            self.state = State.RELEASED
            if self.deferred_replies:
                self.send_release_notification()
            return True

def start_peer(name):
    ns = nameserver.start_nameserver()

    peer = Peer(name)
    # Registra o peer no servidor
    daemon = Pyro5.api.Daemon()
    uri = daemon.register(peer)
    ns.register(name, uri, safe=True)
    print(f"Peer '{name}' iniciado e registrado!")
    threading.Thread(target=daemon.requestLoop, daemon=True).start()

    # Iniciando heartbeat para detecção de falhas nos processos
    heartbeat.start_heartbeat(peer)

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
                    utils.log(name, f"Entrou na seção crítica.")
                else:
                    utils.log(name, f"Não conseguiu entrar na seção crítica.")
            case '2':
                if peer.exit_critical_section():
                    utils.log(name, f"Saiu da seção crítica.")
                else:
                    utils.log(name, f"Não conseguiu sair da seção crítica.")
            case '3':
                print(f"\nPeers ativos:\n{peer.get_active_peers()}")
                print(f"Testando conectividade...")
                peer.test_connection()
            case '4':
                print("Saindo...")
                ns.remove(name)

                peers = peer.get_active_peers()
                print(f"Peers restantes: {peers}")

                if not peers:
                    nameserver.kill_nameserver()
                break
            case _:
                print("Opção inválida! (1 a 4)")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python peer.py <nome_do_peer>")
        sys.exit(1)

    peer_name = sys.argv[1]
    start_peer(peer_name)