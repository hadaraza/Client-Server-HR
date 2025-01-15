import socket  # For network communication
import threading  # For parallel execution
import struct  # For packing/unpacking binary data
import time  # For timing operations
from enum import Enum  # For state enumeration
import statistics  # For calculating averages
import select  # For non-blocking I/O
import queue  # For message queuing
import signal  # For handling system signals


class ClientState(Enum):
    """Enumeration of possible client states."""
    STARTUP = 1  # Initial state when client starts
    LOOKING_FOR_SERVER = 2  # State when searching for a server
    SPEED_TEST = 3  # State when performing speed tests


class SpeedTestClient:
    """
    A client class that performs network speed tests using both TCP and UDP protocols.
    Uses event-driven programming to avoid busy waiting.
    """

    def __init__(self, listen_port=13117):
        """
        Initialize the speed test client with default settings.
        Args:
            listen_port (int): Port to listen for server broadcasts (default: 13117)
        """
        # Basic configuration
        self.listen_port = listen_port
        self.state = ClientState.STARTUP
        self.magic_cookie = 0xabcddcba  # Magic number for packet validation
        self.running = True  # Flag to control client operation
        self.message_queue = queue.Queue()  # Queue for thread communication

        # Initialize statistics dictionary to track performance metrics
        self.statistics = {
            'tcp_times': [],  # List to store TCP transfer times
            'udp_times': [],  # List to store UDP transfer times
            'udp_packets_received': 0,  # Counter for received UDP packets
            'udp_packets_lost': 0  # Counter for lost UDP packets
        }

        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT,
                      self._signal_handler)  # Handle Ctrl+C
        signal.signal(signal.SIGTERM, self._signal_handler)  # Handle termination signal

    def _signal_handler(self, signum, frame):
        """
        Handle system signals for graceful shutdown.
        Args:
            signum: Signal number
            frame: Current stack frame
        """
        print("\n\033[93mShutting down client...\033[0m")
        self.running = False  # Set flag to stop main loop

    def start(self):
        """
        Start the speed test client and enter main operation loop.
        This method controls the overall flow of the client operation.
        """
        print("\033[95mStarting Speed Test Client\033[0m")
        print("\033[95mPress Ctrl+C to exit\033[0m")

        # Main operation loop
        while self.running:
            try:
                # Get file size from user
                self.file_size = self._get_file_size()
                # Change state to looking for server
                self.state = ClientState.LOOKING_FOR_SERVER

                # Initialize UDP socket
                self._setup_udp_socket()

                # Start looking for servers
                self._discover_server()

            except KeyboardInterrupt:
                break  # Exit on Ctrl+C
            except Exception as e:
                print(f"\033[91mError in main loop: {e}\033[0m")
                time.sleep(1)  # Wait before retrying

        self._cleanup()  # Clean up resources

    def _setup_udp_socket(self):
        """
        Setup UDP socket with appropriate options for broadcast reception.
        Configures socket for non-blocking operation and port reuse.
        """
        # Create new UDP socket
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Allow multiple clients on same port
        self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Bind to all interfaces on specified port
        self.udp_socket.bind(('', self.listen_port))
        # Set non-blocking mode
        self.udp_socket.setblocking(False)

    def _get_file_size(self):
        """
        Get desired file size from user input.
        Returns:
            int: File size in bytes
        """
        while True:
            try:
                # Prompt user for file size
                size = input("\033[96mEnter file size for speed test (in bytes): \033[0m")
                return int(size)  # Convert input to integer
            except ValueError:
                print("\033[91mPlease enter a valid number\033[0m")

    def _discover_server(self):
        """
        Discover speed test servers using select() for non-blocking I/O.
        Uses event-driven approach to avoid busy waiting.
        """
        print("\033[93mLooking for speed test server...\033[0m")

        while self.running and self.state == ClientState.LOOKING_FOR_SERVER:
            # Wait for data with timeout using select
            readable, _, _ = select.select([self.udp_socket], [], [], 1.0)

            if readable:
                try:
                    # Receive broadcast message
                    data, addr = self.udp_socket.recvfrom(1024)

                    if len(data) == 9:
                        magic_cookie, msg_type, udp_port, tcp_port = struct.unpack('!IbHH', data)

                        if magic_cookie == self.magic_cookie and msg_type == 0x2:
                            print(f"\033[92mReceived offer from {addr[0]}\033[0m")
                            self.state = ClientState.SPEED_TEST
                            self._run_speed_test(addr[0], udp_port, tcp_port)
                            break

                except Exception as e:
                    print(f"\033[91mError processing server offer: {e}\033[0m")

    def _run_tcp_test(self, server_host, server_port, transfer_num):
        tcp_socket = None
        try:
            tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            tcp_socket.settimeout(5.0)
            tcp_socket.connect((server_host, server_port))

            tcp_socket.send(f"{self.file_size}\n".encode())

            start_time = time.time()
            received = 0

            while received < self.file_size:
                readable, _, _ = select.select([tcp_socket], [], [], 5.0)
                if not readable:
                    raise TimeoutError("TCP test timed out")

                chunk = tcp_socket.recv(min(4096, self.file_size - received))
                if not chunk:
                    break
                received += len(chunk)

            end_time = time.time()
            transfer_time = end_time - start_time

            if transfer_time > 0:
                speed = (self.file_size * 8) / transfer_time
                self.statistics['tcp_times'].append(transfer_time)
                print(f"\033[92mTCP transfer #{transfer_num} finished, total time: {transfer_time:.3f} seconds, total speed: {speed:.2f} bits/second\033[0m")
            else:
                print(f"\033[91mTCP transfer #{transfer_num} finished almost instantly; skipping speed calculation.\033[0m")

        except Exception as e:
            print(f"\033[91mError in TCP test: {e}\033[0m")
        finally:
            if tcp_socket:
                tcp_socket.close()

    def _run_udp_test(self, server_host, server_port, transfer_num):
        udp_socket = None
        try:
            udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            udp_socket.settimeout(5.0)

            request = struct.pack('!IbQ', self.magic_cookie, 0x3, self.file_size)
            udp_socket.sendto(request, (server_host, server_port))

            received_segments = set()
            total_segments = None
            start_time = time.time()

            while True:
                try:
                    readable, _, _ = select.select([udp_socket], [], [], 5.0)
                    if not readable:
                        break

                    data, _ = udp_socket.recvfrom(4096)
                    if len(data) < 21:
                        continue

                    header = data[:21]
                    magic_cookie, msg_type, total_segs, current_seg = struct.unpack('!IbQQ', header)

                    if magic_cookie != self.magic_cookie or msg_type != 0x4:
                        continue

                    if total_segments is None:
                        total_segments = total_segs

                    received_segments.add(current_seg)
                    self.statistics['udp_packets_received'] += 1

                    if len(received_segments) == total_segments:
                        break

                except socket.timeout:
                    break

            end_time = time.time()
            transfer_time = end_time - start_time

            if total_segments:
                packets_lost = total_segments - len(received_segments)
                loss_rate = (packets_lost / total_segments) * 100
                speed = (self.file_size * 8) / transfer_time

                self.statistics['udp_times'].append(transfer_time)
                self.statistics['udp_packets_lost'] = packets_lost

                print(f"\033[92mUDP transfer #{transfer_num} finished, total time: {transfer_time:.3f} seconds, total speed: {speed:.2f} bits/second, percentage of packets received successfully: {100 - loss_rate:.2f}%\033[0m")
            else:
                print(f"\033[91mUDP transfer #{transfer_num} finished, but no segments were received.\033[0m")

        except Exception as e:
            print(f"\033[91mError in UDP test: {e}\033[0m")
        finally:
            if udp_socket:
                udp_socket.close()

    def _run_speed_test(self, server_host, udp_port, tcp_port):
        tcp_threads = []
        udp_threads = []

        num_tcp = int(input("Enter number of TCP connections: "))
        num_udp = int(input("Enter number of UDP connections: "))

        for i in range(num_tcp):
            tcp_thread = threading.Thread(target=self._run_tcp_test, args=(server_host, tcp_port, i + 1))
            tcp_threads.append(tcp_thread)
            tcp_thread.start()

        for i in range(num_udp):
            udp_thread = threading.Thread(target=self._run_udp_test, args=(server_host, udp_port, i + 1))
            udp_threads.append(udp_thread)
            udp_thread.start()

        for thread in tcp_threads + udp_threads:
            thread.join()

        self._print_statistics()
        print("\033[93mAll transfers complete, listening to offer requests\033[0m")
        self.state = ClientState.LOOKING_FOR_SERVER

    def _print_statistics(self):
        print("\n\033[95m=== Speed Test Statistics ===\033[0m")

        if self.statistics['tcp_times']:
            avg_tcp = statistics.mean(self.statistics['tcp_times'])
            print(f"\033[96mTCP Average Time: {avg_tcp:.3f}s")
            print(f"TCP Average Speed: {(self.file_size * 8 / avg_tcp):.2f} bits/second\033[0m")

        if self.statistics['udp_times']:
            avg_udp = statistics.mean(self.statistics['udp_times'])
            loss_rate = (self.statistics['udp_packets_lost'] / (self.statistics['udp_packets_received'] + self.statistics['udp_packets_lost'])) * 100
            print(f"\033[96mUDP Average Time: {avg_udp:.3f}s")
            print(f"UDP Packet Loss Rate: {loss_rate:.2f}%\033[0m")

    def _cleanup(self):
        try:
            if hasattr(self, 'udp_socket'):
                self.udp_socket.close()
        except Exception as e:
            print(f"\033[91mError during cleanup: {e}\033[0m")


if __name__ == "__main__":
    client = SpeedTestClient()
    client.start()