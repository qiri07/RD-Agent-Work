#!/usr/bin/env python3
import socket
import sys
import threading
import os

def forward(src, dst):
    try:
        while True:
            data = src.recv(4096)
            if not data:
                break
            dst.sendall(data)
    except Exception:
        pass
    finally:
        src.close()
        dst.close()

def handle_client(client_sock, addr):
    try:
        # Connect to system docker socket
        server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server_sock.connect('/var/run/docker.sock')
        forward(client_sock, server_sock)
        forward(server_sock, client_sock)
    except Exception as e:
        print(f"Proxy error: {e}", file=sys.stderr)
    finally:
        client_sock.close()

if __name__ == '__main__':
    sock_path = '/tmp/docker-user.sock'
    if os.path.exists(sock_path):
        os.remove(sock_path)
    
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(sock_path)
    os.chmod(sock_path, 0o666)
    server.listen(5)
    print(f"Docker proxy listening on {sock_path}")
    
    while True:
        client_sock, addr = server.accept()
        t = threading.Thread(target=handle_client, args=(client_sock, addr))
        t.start()
