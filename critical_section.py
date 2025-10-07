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

        self.permission_granted = {}
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
                utils.log(self.peer.name, f"Resposta de {requester_peer_name} negada e adiada.")
                return False
            else:
                utils.log(self.peer.name, f"Resposta de {requester_peer_name} permitida.")
                return True

    def receive_permission(self, receiving_from_peer_name):
        with self.lock:
            if self.state == State.WANTED:
                self.permission_granted[receiving_from_peer_name] = True
                utils.log(self.peer.name, f"Permissão adiada de {receiving_from_peer_name} recebida.")

                if all(self.permission_granted.values()):
                    self.request_event.set()

    def send_request_notification(self, request_timestamp, active_peer_name):
        try:
            with Pyro5.api.Proxy(f"PYRONAME:{active_peer_name}") as other_peer:
                permission_granted = other_peer.request_resource(request_timestamp, self.peer.name)
                with self.lock:
                    if self.state != State.WANTED:
                        return
                    if permission_granted:
                        utils.log(self.peer.name, f"{active_peer_name} permitiu.")
                    else:
                        utils.log(self.peer.name, f"{active_peer_name} negou.")

                    self.permission_granted[active_peer_name] = permission_granted

                    if all(self.permission_granted.values()):
                        self.request_event.set()
        except Exception as e:
            utils.log(self.peer.name, f"Erro ao requisitar {active_peer_name}: {e}")
            with self.lock:
                if self.state == State.WANTED:
                    self.permission_granted[active_peer_name] = False

    def send_release_notification(self):
        peers_to_notify = self.deferred_replies.copy()
        self.deferred_replies.clear()
        for peer_name in peers_to_notify:
            try:
                with Pyro5.api.Proxy(f"PYRONAME:{peer_name}") as other_peer:
                    other_peer.receive_permission(self.peer.name)
                    utils.log(self.peer.name, f"Enviou permissão adiada para {peer_name}")
            except Exception as e:
                utils.log(self.peer.name, f"Erro ao enviar resposta adiada para {peer_name}: {e}")

    def enter_critical_section(self):
        try:
            with self.lock:
                if self.state == State.HELD:
                    utils.log(self.peer.name, "Já está na seção crítica.")
                    return True

                self.state = State.WANTED
                self.request_event.clear()
                self.request_timestamp = self.increment_timestamp()
                self.permission_granted = {}.fromkeys(self.peer.get_active_peers())

            utils.log(self.peer.name, "Solicitando recurso...")

            for active_peer_name in self.permission_granted:
                threading.Thread(
                    target=self.send_request_notification,
                    args=(self.request_timestamp, active_peer_name),
                    daemon=True
                ).start()

            utils.log(self.peer.name, f"Aguardando {self.peer.get_peers_count()} respostas...")
            self.request_event.wait(timeout=self.MAX_WAIT_TIME)

            with self.lock:
                if all(self.permission_granted.values()):
                    self.state = State.HELD

                    timer = threading.Timer(self.MAX_ACCESS_TIME, self.exit_critical_section)
                    timer.daemon = True
                    timer.start()
                    return True
                else:
                    inactive_peers = [k for k, v, in self.permission_granted.items() if v is None]
                    if inactive_peers:
                        utils.log(self.peer.name, f"Timeout aguardando respostas de: {inactive_peers}")
                        for peer_name in inactive_peers:
                            self.peer.remove_inactive_peer(peer_name)
                    utils.log(self.peer.name, "Timeout ao obter todas as respostas. Liberando peers em espera.")
                    self.state = State.RELEASED
                    return False
        except Exception as e:
            utils.log(self.peer.name, f"Erro ao entrar na seção crítica: {e}")
        finally:
            self.request_timestamp = None
            self.permission_granted.clear()

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
