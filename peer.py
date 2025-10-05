import sys
import threading
import time

import Pyro5.api

from critical_section import CriticalSection
import heartbeat
import nameserver
import utils

@Pyro5.api.expose
class Peer:
    def __init__(self, name):
        self.name = name
        self.critical_section = CriticalSection(self)
        self.registered_peers = []
        self.active_peers = {}

        self.heartbeat_lock = threading.Lock()

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

    def request_resource(self, requester_timestamp, requester_peer_name):
        return self.critical_section.request_resource(requester_timestamp, requester_peer_name)

    def receive_reply(self, receiving_from_peer_name):
        return self.critical_section.receive_reply(receiving_from_peer_name)

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
                if peer.critical_section.enter_critical_section():
                    utils.log(name, f"Entrou na seção crítica.")
                else:
                    utils.log(name, f"Não conseguiu entrar na seção crítica.")
            case '2':
                if peer.critical_section.exit_critical_section():
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