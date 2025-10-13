import threading
import time
import Pyro5

import utils


HEARTBEAT_INTERVAL = 3
HEARTBEAT_TIMEOUT = 5

def send_heartbeat(peer):
    while True:
        peer.check_registered_peers()
        with peer.heartbeat_lock:
            for peer_name in peer.active_peers:
                try:
                    with Pyro5.api.Proxy(f"PYRONAME:{peer_name}") as other_peer:
                        other_peer.receive_heartbeat(peer.name)
                except Exception as e:
                    utils.log(peer.name, f"Erro ao enviar heartbeat para {peer_name}: {e}")
        time.sleep(HEARTBEAT_INTERVAL)

def heartbeat_monitor(peer):
    while True:
        now = time.time()
        with peer.heartbeat_lock:
            for peer_name in list(peer.active_peers.keys()):
                last_heartbeat = peer.active_peers[peer_name]
                if now - last_heartbeat > HEARTBEAT_TIMEOUT:
                    utils.log(peer.name, f"Peer {peer_name} parece inativo. Removendo...")
                    peer.remove_inactive_peer(peer_name)
                    utils.log(peer.name, f"Peer {peer_name} removido.")
        time.sleep(2)

def start_heartbeat(peer):
    threading.Thread(target=send_heartbeat, args=(peer,), daemon=True).start()
    threading.Thread(target=heartbeat_monitor, args=(peer,), daemon=True).start()