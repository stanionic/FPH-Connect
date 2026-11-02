import json
import socket
import threading

from app import discovery as server_disc
from fph_client.discovery import discover


def _start():
    stop = threading.Event()
    ports = []
    ready = threading.Event()
    t = threading.Thread(target=server_disc.serve, kwargs=dict(
        port=0, bind="127.0.0.1", stop=stop.is_set, ready=lambda p: (ports.append(p), ready.set())), daemon=True)
    t.start()
    assert ready.wait(3)
    return stop, ports[0], t


def test_probe_finds_server_over_real_udp():
    stop, port, t = _start()
    try:
        found = discover(timeout=1.0, port=port, target="127.0.0.1")
        assert len(found) == 1 and found[0]["url"] == "http://127.0.0.1:8000"
        assert "secret" not in json.dumps(found).lower()
    finally:
        stop.set(); t.join(2)


def test_server_ignores_garbage_and_reply_is_not_an_amplifier():
    assert server_disc.handle(b"GET / HTTP/1.1") is None
    assert server_disc.handle(b"") is None
    reply = server_disc.handle(server_disc.PROBE)
    assert reply is not None and len(reply) < 200            # réponse courte
    stop, port, t = _start()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.sendto(b"garbage", ("127.0.0.1", port))
        try:
            s.recvfrom(1024)
            assert False, "ne doit pas répondre"
        except socket.timeout:
            pass
        s.close()
    finally:
        stop.set(); t.join(2)


def test_client_ignores_fake_replies():
    fake = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    fake.bind(("127.0.0.1", 0))
    port = fake.getsockname()[1]
    def run():
        fake.settimeout(2)
        try:
            _, addr = fake.recvfrom(100)
            fake.sendto(b"not json", addr)
            fake.sendto(json.dumps({"service": "other", "api_port": 1}).encode(), addr)
        except socket.timeout:
            pass
    th = threading.Thread(target=run, daemon=True); th.start()
    assert discover(timeout=0.8, port=port, target="127.0.0.1") == []
    th.join(2); fake.close()
