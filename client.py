import socket
import threading
import struct
import time
import statistics
import select
import queue
import signal
from enum import Enum


class ClientState(Enum):
    """Enumeration of possible client states."""
    STARTUP = 1
    LOOKING_FOR_SERVER = 2
    SPEED_TEST = 3


class SpeedTestClient:
    """
    An improved client class that performs network speed tests using both TCP and UDP protocols.
    Includes enhanced connection handling and retry mechanisms.
    """

    def __init__(self, listen_port=13117):
        """
        Initialize the speed test client with improved configuration.
        Args:
            listen_port (int): Port to listen for server broadcasts (default: 13117)
        """
        self.listen_port = listen_port
        self.state = ClientState.STARTUP
        self.magic_cookie = 0xabcddcba
        self.running = True
        self.message_queue = queue.Queue()
        self.active_connections = 0
        self.max_retries = 3
        self.connection_lock = threading.Lock()

        # Enhanced statistics tracking
        self.statistics = {
            'tcp_times': [],
            'udp_times': [],
            'udp_packets_received': 0,
            'udp_packets_lost': 0,
            'tcp_connection_failures': 0,
            'tcp_transfer_failures': 0,
            'successful_connections': 0
        }

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """Handle system signals for graceful shutdown."""
        print("\n\033[93mShutting down client...\033[0m")
        self.running = False

    def start(self):
        """Start the speed test client with improved error handling."""
        print("\033[95mStarting Speed Test Client\033[0m")
        print("\033[95mPress Ctrl+C to exit\033[0m")

        while self.running:
            try:
                self.file_size = self._get_file_size()
                self.state = ClientState.LOOKING_FOR_SERVER
                self._setup_udp_socket()
                self._discover_server()
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"\033[91mError in main loop: {e}\033[0m")
                time.sleep(1)

        self._cleanup()

    def _setup_udp_socket(self):
        """Setup UDP socket with improved configuration."""
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8388608)  # 8MB receive buffer
        self.udp_socket.bind(('', self.listen_port))
        self.udp_socket.setblocking(False)

    def _get_file_size(self):
        """Get desired file size from user input with validation."""
        while True:
            try:
                size = input("\033[96mEnter file size for speed test (in bytes): \033[0m")
                size_value = int(size)
                if size_value <= 0:
                    print("\033[91mFile size must be positive\033[0m")
                    continue
                return size_value
            except ValueError:
                print("\033[91mPlease enter a valid number\033[0m")

    def _discover_server(self):
        """Discover speed test servers with improved timeout handling."""
        print("\033[93mLooking for speed test server...\033[0m")

        while self.running and self.state == ClientState.LOOKING_FOR_SERVER:
            try:
                readable, _, _ = select.select([self.udp_socket], [], [], 1.0)

                if readable:
                    data, addr = self.udp_socket.recvfrom(1024)

                    if len(data) == 9:
                        magic_cookie, msg_type, udp_port, tcp_port = struct.unpack('!IbHH', data)

                        if magic_cookie == self.magic_cookie and msg_type == 0x2:
                            print(f"\033[92mReceived offer from {addr[0]}\033[0m")
                            self.state = ClientState.SPEED_TEST
                            self._run_speed_test(addr[0], udp_port, tcp_port)
                            break

            except Exception as e:
                print(f"\033[91mError discovering server: {e}\033[0m")
                time.sleep(1)

    def _run_tcp_test(self, server_host, server_port, transfer_num):
        """
        Perform TCP speed test with improved error handling and retry mechanism.
        """
        tcp_socket = None
        retry_count = 0

        while retry_count < self.max_retries and self.running:
            try:
                tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                tcp_socket.settimeout(10.0)
                tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8388608)

                with self.connection_lock:
                    self.active_connections += 1

                tcp_socket.connect((server_host, server_port))
                tcp_socket.send(f"{self.file_size}\n".encode())

                start_time = time.time()
                received = 0

                while received < self.file_size and self.running:
                    readable, _, _ = select.select([tcp_socket], [], [], 5.0)
                    if not readable:
                        raise TimeoutError("TCP test timed out")

                    chunk = tcp_socket.recv(min(65536, self.file_size - received))
                    if not chunk:
                        break
                    received += len(chunk)

                end_time = time.time()
                transfer_time = end_time - start_time

                if transfer_time > 0:
                    speed = (self.file_size * 8) / transfer_time
                    with self.connection_lock:
                        self.statistics['tcp_times'].append(transfer_time)
                        self.statistics['successful_connections'] += 1
                    print(f"\033[92mTCP transfer #{transfer_num} finished:"
                          f" Time: {transfer_time:.3f}s,"
                          f" Speed: {speed:.2f} bits/second\033[0m")
                break  # Success, exit retry loop

            except (ConnectionRefusedError, TimeoutError) as e:
                retry_count += 1
                with self.connection_lock:
                    self.statistics['tcp_connection_failures'] += 1
                print(
                    f"\033[93mTCP transfer #{transfer_num} failed (attempt {retry_count}/{self.max_retries}): {e}\033[0m")
                time.sleep(1)  # Wait before retry

            except Exception as e:
                with self.connection_lock:
                    self.statistics['tcp_transfer_failures'] += 1
                print(f"\033[91mTCP transfer #{transfer_num} error: {e}\033[0m")
                break

            finally:
                if tcp_socket:
                    tcp_socket.close()
                with self.connection_lock:
                    self.active_connections -= 1

    def _run_udp_test(self, server_host, server_port, transfer_num):
        """
        Perform UDP speed test with improved packet tracking and error handling.
        """
        udp_socket = None
        try:
            udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            udp_socket.settimeout(5.0)
            udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8388608)

            request = struct.pack('!IbQ', self.magic_cookie, 0x3, self.file_size)
            udp_socket.sendto(request, (server_host, server_port))

            received_segments = set()
            total_segments = None
            start_time = time.time()
            last_packet_time = start_time

            while (time.time() - last_packet_time) < 5.0 and self.running:
                try:
                    readable, _, _ = select.select([udp_socket], [], [], 1.0)
                    if not readable:
                        continue

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
                    with self.connection_lock:
                        self.statistics['udp_packets_received'] += 1
                    last_packet_time = time.time()

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

                with self.connection_lock:
                    self.statistics['udp_times'].append(transfer_time)
                    self.statistics['udp_packets_lost'] += packets_lost

                print(f"\033[92mUDP transfer #{transfer_num} finished:"
                      f" Time: {transfer_time:.3f}s,"
                      f" Speed: {speed:.2f} bits/second,"
                      f" Success rate: {100 - loss_rate:.2f}%\033[0m")
            else:
                print(f"\033[91mUDP transfer #{transfer_num} failed: No segments received\033[0m")

        except Exception as e:
            print(f"\033[91mUDP transfer #{transfer_num} error: {e}\033[0m")
        finally:
            if udp_socket:
                udp_socket.close()

    def _run_speed_test(self, server_host, udp_port, tcp_port):
        """
        Coordinate speed tests with improved thread management and connection throttling.
        """
        tcp_threads = []
        udp_threads = []

        try:
            num_tcp = int(input("\033[96mEnter number of TCP connections: \033[0m"))
            num_udp = int(input("\033[96mEnter number of UDP connections: \033[0m"))
        except ValueError:
            print("\033[91mInvalid input, using default values (1 each)\033[0m")
            num_tcp = num_udp = 1

        # Reset statistics for new test
        with self.connection_lock:
            self.statistics = {
                'tcp_times': [],
                'udp_times': [],
                'udp_packets_received': 0,
                'udp_packets_lost': 0,
                'tcp_connection_failures': 0,
                'tcp_transfer_failures': 0,
                'successful_connections': 0
            }

        # Add delay between connection attempts to prevent overwhelming the server
        delay_between_connections = 0.05  # 50ms delay

        # Start TCP test threads with delay
        for i in range(num_tcp):
            if not self.running:
                break
            tcp_thread = threading.Thread(
                target=self._run_tcp_test,
                args=(server_host, tcp_port, i + 1)
            )
            tcp_threads.append(tcp_thread)
            tcp_thread.start()
            time.sleep(delay_between_connections)

        # Start UDP test threads with delay
        for i in range(num_udp):
            if not self.running:
                break
            udp_thread = threading.Thread(
                target=self._run_udp_test,
                args=(server_host, udp_port, i + 1)
            )
            udp_threads.append(udp_thread)
            udp_thread.start()
            time.sleep(delay_between_connections)

        # Wait for all threads to complete with timeout
        end_time = time.time() + 60  # 60 second timeout
        for thread in tcp_threads + udp_threads:
            remaining_time = max(0, end_time - time.time())
            thread.join(timeout=remaining_time)

        self._print_statistics()
        print("\033[93mAll transfers complete, listening for new offers\033[0m")
        self.state = ClientState.LOOKING_FOR_SERVER

    def _print_statistics(self):
        """Display comprehensive test results and statistics."""
        print("\n\033[95m=== Speed Test Statistics ===\033[0m")

        with self.connection_lock:
            if self.statistics['tcp_times']:
                avg_tcp = statistics.mean(self.statistics['tcp_times'])
                print(f"\033[96mTCP Statistics:")
                print(f"- Average Time: {avg_tcp:.3f}s")
                print(f"- Average Speed: {(self.file_size * 8 / avg_tcp):.2f} bits/second")
                print(f"- Successful Connections: {self.statistics['successful_connections']}")
                print(f"- Connection Failures: {self.statistics['tcp_connection_failures']}")
                print(f"- Transfer Failures: {self.statistics['tcp_transfer_failures']}\033[0m")

            if self.statistics['udp_times']:
                avg_udp = statistics.mean(self.statistics['udp_times'])
                total_packets = self.statistics['udp_packets_received'] + self.statistics['udp_packets_lost']
                loss_rate = (self.statistics['udp_packets_lost'] / total_packets * 100) if total_packets > 0 else 0
                print(f"\033[96mUDP Statistics:")
                print(f"- Average Time: {avg_udp:.3f}s")
                print(f"- Average Speed: {(self.file_size * 8 / avg_udp):.2f} bits/second")
                print(f"- Packet Loss Rate: {loss_rate:.2f}%\033[0m")

    def _cleanup(self):
        """Clean up resources before exiting."""
        try:
            if hasattr(self, 'udp_socket'):
                self.udp_socket.close()
        except Exception as e:
            print(f"\033[91mError during cleanup: {e}\033[0m")


if __name__ == "__main__":
    client = SpeedTestClient()
    client.start()