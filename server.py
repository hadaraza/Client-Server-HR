import socket
import threading
import struct
import time
import random
import select
import signal
import resource
import sys


class SpeedTestServer:
    """
    An improved server class that handles network speed testing using both TCP and UDP protocols.
    Includes enhanced support for concurrent connections and better resource management.
    """

    def __init__(self, host='', offer_port=13117):
        """
        Initialize the server with specified host and port.
        Args:
            host (str): The server's host address (default: all interfaces)
            offer_port (int): Port for broadcasting server offers (default: 13117)
        """
        self.host = host
        self.offer_port = offer_port
        self.udp_port = random.randint(20000, 65000)
        self.tcp_port = random.randint(20000, 65000)
        self.running = False
        self.magic_cookie = 0xabcddcba
        self.msg_type_offer = 0x2

        # Increase system limits for better concurrent connection handling
        self._increase_system_limits()

        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _increase_system_limits(self):
        """
        Increase system limits to handle more concurrent connections.
        """
        try:
            # Increase the soft limit for number of file descriptors
            soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
            resource.setrlimit(resource.RLIMIT_NOFILE, (hard, hard))
            print(f"\033[92mIncreased file descriptor limit from {soft} to {hard}\033[0m")

            # On Linux, try to increase TCP buffer sizes
            if sys.platform.startswith('linux'):
                with open('/proc/sys/net/core/rmem_max', 'r') as f:
                    current_rmem = f.read().strip()
                with open('/proc/sys/net/core/wmem_max', 'r') as f:
                    current_wmem = f.read().strip()
                print(f"\033[92mCurrent TCP buffer sizes - Read: {current_rmem}, Write: {current_wmem}\033[0m")
        except Exception as e:
            print(f"\033[93mWarning: Could not increase system limits: {e}\033[0m")

    def _signal_handler(self, signum, frame):
        """
        Handle system signals for graceful shutdown.
        """
        print("\n\033[93mShutting down server...\033[0m")
        self.stop()

    def start(self):
        """
        Start the server with improved socket configuration and error handling.
        """
        self.running = True

        try:
            # Create and configure UDP socket
            self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8388608)  # 8MB receive buffer
            self.udp_socket.bind((self.host, self.udp_port))

            # Create and configure TCP socket
            self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)

            # Configure TCP keepalive settings
            if sys.platform.startswith('linux'):
                self.tcp_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30)
                self.tcp_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
                self.tcp_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)

            self.tcp_socket.bind((self.host, self.tcp_port))
            self.tcp_socket.listen(128)  # Increased backlog for more concurrent connections

            # Start broadcast thread
            self.broadcast_thread = threading.Thread(target=self._broadcast_offer)
            self.broadcast_thread.daemon = True
            self.broadcast_thread.start()

            # Get and display server information
            server_ip = socket.gethostbyname(socket.gethostname())
            print(f"\033[92mServer started, listening on IP address {server_ip}\033[0m")
            print(f"\033[92mUDP Port: {self.udp_port}, TCP Port: {self.tcp_port}\033[0m")

            self._handle_requests()

        except Exception as e:
            print(f"\033[91mError starting server: {e}\033[0m")
            self.stop()

    def _broadcast_offer(self):
        """
        Broadcast server offer messages with improved error handling.
        """
        try:
            offer_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            offer_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            offer_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

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
                    time.sleep(5)  # Wait longer on error before retrying

        except Exception as e:
            print(f"\033[91mError in broadcast thread: {e}\033[0m")
        finally:
            offer_socket.close()

    def _handle_requests(self):
        """
        Handle incoming client requests with improved connection management.
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
                            thread = threading.Thread(target=self._handle_udp_speed_test,
                                                      args=(data, addr))
                            thread.daemon = True
                            thread.start()
                        except Exception as e:
                            print(f"\033[91mError handling UDP request: {e}\033[0m")

                    elif sock is self.tcp_socket:
                        try:
                            client_socket, addr = sock.accept()
                            thread = threading.Thread(target=self._handle_tcp_client,
                                                      args=(client_socket, addr))
                            thread.daemon = True
                            thread.start()
                        except Exception as e:
                            print(f"\033[91mError accepting TCP connection: {e}\033[0m")

                for sock in exceptional:
                    print(f"\033[91mException condition on {sock.getsockname()}\033[0m")
                    inputs.remove(sock)
                    sock.close()

            except Exception as e:
                print(f"\033[91mError in request handling: {e}\033[0m")
                time.sleep(1)

    def _handle_udp_speed_test(self, data, addr):
        """
        Handle UDP speed test with improved error handling and flow control.
        """
        try:
            magic_cookie, msg_type, file_size = struct.unpack('!IbQ', data)

            if magic_cookie != self.magic_cookie or msg_type != 0x3:
                print(f"\033[91mInvalid UDP request from {addr}\033[0m")
                return

            print(f"\033[94mUDP test request from {addr}, size: {file_size} bytes\033[0m")

            segment_size = 1024
            total_segments = (file_size + segment_size - 1) // segment_size

            # Add flow control delay based on file size
            delay = min(0.001, file_size / (1024 * 1024 * 100))  # Scale delay with file size

            for i in range(total_segments):
                if not self.running:
                    break

                remaining = min(segment_size, file_size - i * segment_size)
                payload = b'X' * remaining

                header = struct.pack('!IbQQ',
                                     self.magic_cookie,
                                     0x4,
                                     total_segments,
                                     i)

                self.udp_socket.sendto(header + payload, addr)
                time.sleep(delay)  # Add small delay between segments

        except Exception as e:
            print(f"\033[91mError handling UDP request from {addr}: {e}\033[0m")

    def _handle_tcp_client(self, client_socket, addr):
        """
        Handle TCP client with improved error handling and performance monitoring.
        """
        try:
            client_socket.settimeout(10.0)

            # Configure TCP socket options
            client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            if sys.platform.startswith('linux'):
                client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30)
                client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
                client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)

            data = client_socket.recv(1024).decode().strip()
            file_size = int(data)

            print(f"\033[94mTCP test request from {addr}, size: {file_size} bytes\033[0m")

            # Send data in chunks for better memory management
            chunk_size = 65536  # 64KB chunks
            remaining = file_size

            while remaining > 0 and self.running:
                current_chunk = min(chunk_size, remaining)
                client_socket.sendall(b'X' * current_chunk)
                remaining -= current_chunk

        except socket.timeout:
            print(f"\033[91mTimeout handling TCP client {addr}\033[0m")
        except ConnectionError as e:
            print(f"\033[91mConnection error with TCP client {addr}: {e}\033[0m")
        except Exception as e:
            print(f"\033[91mError handling TCP client {addr}: {e}\033[0m")
        finally:
            try:
                client_socket.close()
            except:
                pass

    def stop(self):
        """
        Stop the server and clean up resources.
        """
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