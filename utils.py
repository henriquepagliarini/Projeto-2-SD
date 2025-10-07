def has_priority(local_timestamp, local_name, requester_timestamp, requester_peer_name):
        if local_timestamp < requester_timestamp:
            return True
        if local_timestamp == requester_timestamp and local_name < requester_peer_name:
            return True
        return False

def log(peer_name, message):
    print(f"\n[{peer_name}]: {message}")