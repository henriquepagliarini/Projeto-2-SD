import threading
import Pyro5.api
import utils
from state import State

class CriticalSection:
    def __init__(self, peer):
        self.peer = peer

        self.state = State.RELEASED
        self.timestamp = 0
        self.request_timestamp = None

        self.replies_received = 0
        self.deferred_replies = []
        self.request_event = threading.Event()

        self.lock = threading.Lock()
        self.MAX_WAIT_TIME = 15
        self.MAX_ACCESS_TIME = 8

    def increment_timestamp(self):
        self.timestamp += 1
        return self.timestamp

    def update_timestamp(self, request_timestamp):
        self.timestamp = max(self.timestamp, request_timestamp) + 1

    def request_resource(self, requester_timestamp, requester_peer_name):
        with self.lock:
            utils.log(self.peer.name, f"Requisição recebida - ({requester_peer_name}, {requester_timestamp})")

            denied = self.state == State.HELD or (
                self.state == State.WANTED and utils.has_priority(
                    self.request_timestamp, self.peer.name, requester_timestamp, requester_peer_name
                )
            )
            self.update_timestamp(requester_timestamp)

            if denied:
                self.deferred_replies.append(requester_peer_name)
                utils.log(self.peer.name, f"Resposta de {requester_peer_name} adiada.")
                return False
            else:
                utils.log(self.peer.name, f"Respondendo {requester_peer_name} imediatamente.")
                return True

    def receive_reply(self, receiving_from_peer_name):
        with self.lock:
            if self.state == State.WANTED:
                self.replies_received += 1
                total = self.peer.get_peers_count()
                utils.log(self.peer.name, f"Resposta de {receiving_from_peer_name} recebida ({self.replies_received}/{total})")

                if self.replies_received >= total:
                    self.request_event.set()

    def send_request_notification(self, request_timestamp, active_peer_name):
        try:
            with Pyro5.api.Proxy(f"PYRONAME:{active_peer_name}") as other_peer:
                if other_peer.request_resource(request_timestamp, self.peer.name):
                    self.receive_reply(active_peer_name)
        except Exception as e:
            utils.log(self.peer.name, f"Erro ao requisitar {active_peer_name}: {e}")

    def send_release_notification(self):
        for peer_name in self.deferred_replies:
            try:
                with Pyro5.api.Proxy(f"PYRONAME:{peer_name}") as other_peer:
                    other_peer.receive_reply(self.peer.name)
                    utils.log(self.peer.name, f"Enviou resposta adiada para {peer_name}")
            except Exception as e:
                utils.log(self.peer.name, f"Erro ao enviar resposta adiada para {peer_name}: {e}")
        self.deferred_replies.clear()

    def enter_critical_section(self):
        with self.lock:
            if self.state == State.HELD:
                utils.log(self.peer.name, "Já está na seção crítica.")
                return True

            self.state = State.WANTED
            self.replies_received = 0
            self.request_event.clear()
            self.request_timestamp = self.increment_timestamp()

        utils.log(self.peer.name, "Solicitando recurso...")

        active_peers = self.peer.get_active_peers()
        for active_peer_name in active_peers:
            if active_peer_name != self.peer.name:
                threading.Thread(
                    target=self.send_request_notification,
                    args=(self.request_timestamp, active_peer_name),
                    daemon=True
                ).start()

        utils.log(self.peer.name, f"Aguardando {self.peer.get_peers_count()} respostas...")
        self.request_event.wait(timeout=self.MAX_WAIT_TIME)

        with self.lock:
            if self.replies_received >= self.peer.get_peers_count():
                self.state = State.HELD
                self.request_timestamp = None

                timer = threading.Timer(self.MAX_ACCESS_TIME, self.exit_critical_section)
                timer.daemon = True
                timer.start()
                return True
            else:
                utils.log(self.peer.name, "Timeout ao obter todas as respostas. Liberando peers em espera.")
                self.state = State.RELEASED
                if self.deferred_replies:
                    self.send_release_notification()
                self.request_timestamp = None
                return False

    def exit_critical_section(self):
        with self.lock:
            if self.state != State.HELD:
                utils.log(self.peer.name, "Não está na seção crítica.")
                return False

            utils.log(self.peer.name, "Liberando recurso...")
            self.state = State.RELEASED
            if self.deferred_replies:
                self.send_release_notification()
            return True
