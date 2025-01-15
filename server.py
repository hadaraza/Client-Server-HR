import socket
import threading
import struct
import time
import random
import select
import signal

class SpeedTestServer:
    """
    A server class that handles network speed testing using both TCP and UDP protocols.
    """

    def __init__(self, host='', offer_port=13117):
        """
        Initialize the server with specified host and port.
        """
        self.host = host
        self.offer_port = offer_port
        self.udp_port = random.randint(20000, 65000)
        self.tcp_port = random.randint(20000, 65000)
        self.running = False
        self.magic_cookie = 0xabcddcba
        self.msg_type_offer = 0x2

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        print("\n\033[93mShutting down server...\033[0m")
        self.stop()

    def start(self):
        """
        Start the server and initialize all necessary sockets and threads.
        """
        self.running = True

        try:
            self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp_socket.bind((self.host, self.udp_port))

            self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.tcp_socket.bind((self.host, self.tcp_port))
            self.tcp_socket.listen(5)

            self.broadcast_thread = threading.Thread(target=self._broadcast_offer)
            self.broadcast_thread.daemon = True
            self.broadcast_thread.start()

            server_ip = socket.gethostbyname(socket.gethostname())
            print(f"\033[92mWonder Woman's - Server started, listening on IP address {server_ip}\033[0m")
            print(f"\033[92mPort: {self.udp_port}, TCP Port: {self.tcp_port}\033[0m")

            self._handle_requests()

        except Exception as e:
            print(f"\033[91mError starting server: {e}\033[0m")
            self.stop()

    def _broadcast_offer(self):
        """
        Continuously broadcast server offer messages using non-blocking sockets.
        """
        try:
            offer_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            offer_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

            offer_message = struct.pack('!IbHH',
                                        self.magic_cookie,
                                        self.msg_type_offer,
                                        self.udp_port,
                                        self.tcp_port)

            while self.running:
                try:
                    offer_socket.sendto(offer_message, ('<broadcast>', self.offer_port))
                    time.sleep(1)
                except Exception as e:
                    print(f"\033[91mError broadcasting offer: {e}\033[0m")

        except Exception as e:
            print(f"\033[91mError in broadcast thread: {e}\033[0m")
        finally:
            offer_socket.close()

    def _handle_requests(self):
        """
        Main loop for handling incoming client requests.
        """
        self.udp_socket.setblocking(False)
        self.tcp_socket.setblocking(False)

        inputs = [self.udp_socket, self.tcp_socket]

        while self.running:
            try:
                readable, _, exceptional = select.select(inputs, [], inputs, 1.0)

                for sock in readable:
                    if sock is self.udp_socket:
                        try:
                            data, addr = sock.recvfrom(1024)
                            threading.Thread(target=self._handle_udp_speed_test, args=(data, addr)).start()
                        except Exception as e:
                            print(f"\033[91mError handling UDP request: {e}\033[0m")

                    elif sock is self.tcp_socket:
                        try:
                            client_socket, addr = sock.accept()
                            threading.Thread(target=self._handle_tcp_client, args=(client_socket, addr)).start()
                        except Exception as e:
                            print(f"\033[91mError handling TCP connection: {e}\033[0m")

                for sock in exceptional:
                    print(f"\033[91mException condition on {sock.getsockname()}\033[0m")
                    inputs.remove(sock)
                    sock.close()

            except Exception as e:
                print(f"\033[91mError in request handling: {e}\033[0m")

    def _handle_udp_speed_test(self, data, addr):
        try:
            magic_cookie, msg_type, file_size = struct.unpack('!IbQ', data)

            if magic_cookie != self.magic_cookie or msg_type != 0x3:
                print(f"\033[91mInvalid UDP request from {addr}\033[0m")
                return

            print(f"\033[94mUDP test request from {addr}, size: {file_size} bytes\033[0m")

            segment_size = 1024
            total_segments = (file_size + segment_size - 1) // segment_size

            for i in range(total_segments):
                remaining = min(segment_size, file_size - i * segment_size)
                payload = b'X' * remaining

                header = struct.pack('!IbQQ',
                                     self.magic_cookie,
                                     0x4,
                                     total_segments,
                                     i)

                self.udp_socket.sendto(header + payload, addr)

        except Exception as e:
            print(f"\033[91mError handling UDP request: {e}\033[0m")

    def _handle_tcp_client(self, client_socket, addr):
        try:
            client_socket.settimeout(5.0)

            data = client_socket.recv(1024).decode().strip()
            file_size = int(data)

            print(f"\033[94mTCP test request from {addr}, size: {file_size} bytes\033[0m")

            data = b'X' * file_size
            client_socket.sendall(data)

        except Exception as e:
            print(f"\033[91mError handling TCP client: {e}\033[0m")
        finally:
            client_socket.close()

    def stop(self):
        self.running = False
        try:
            if hasattr(self, 'udp_socket'):
                self.udp_socket.close()
            if hasattr(self, 'tcp_socket'):
                self.tcp_socket.close()
        except Exception as e:
            print(f"\033[91mError during cleanup: {e}\033[0m")

if __name__ == "__main__":
    server = SpeedTestServer()
    try:
        server.start()
    except KeyboardInterrupt:
        server.stop()