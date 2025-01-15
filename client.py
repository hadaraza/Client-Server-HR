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
        # Save the port to listen on
        self.listen_port = listen_port
        # Set the initial state to STARTUP
        self.state = ClientState.STARTUP
        # Magic number for identifying valid packets
        self.magic_cookie = 0xabcddcba
        # Flag to control whether the client is running
        self.running = True
        # Queue to hold messages between threads
        self.message_queue = queue.Queue()

        # Dictionary to track performance metrics
        self.statistics = {
            'tcp_times': [],  # List to store TCP transfer times
            'udp_times': [],  # List to store UDP transfer times
            'udp_packets_received': 0,  # Count of received UDP packets
            'udp_packets_lost': 0  # Count of lost UDP packets
        }

        # Set up signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)  # Handle Ctrl+C
        signal.signal(signal.SIGTERM, self._signal_handler)  # Handle termination signal

    def _signal_handler(self, signum, frame):
        """
        Handle system signals for graceful shutdown.
        Args:
            signum: Signal number
            frame: Current stack frame
        """
        print("\n\033[93mShutting down client...\033[0m")  # Display shutdown message
        self.running = False  # Stop the client

    def start(self):
        """
        Start the speed test client and enter main operation loop.
        This method controls the overall flow of the client operation.
        """
        print("\033[95mStarting Speed Test Client\033[0m")
        print("\033[95mPress Ctrl+C to exit\033[0m")

        # Main loop for client operation
        while self.running:
            try:
                # Get the file size for the speed test from the user
                self.file_size = self._get_file_size()
                # Set state to looking for server
                self.state = ClientState.LOOKING_FOR_SERVER

                # Set up the UDP socket for communication
                self._setup_udp_socket()

                # Begin looking for a speed test server
                self._discover_server()

            except KeyboardInterrupt:
                break  # Stop the client when interrupted
            except Exception as e:
                print(f"\033[91mError in main loop: {e}\033[0m")  # Print errors
                time.sleep(1)  # Wait before retrying

        # Clean up resources before exiting
        self._cleanup()

    def _setup_udp_socket(self):
        """
        Setup UDP socket with appropriate options for broadcast reception.
        Configures socket for non-blocking operation and port reuse.
        """
        # Create a new UDP socket
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Allow multiple clients to use the same port
        self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Bind the socket to all interfaces and the specified port
        self.udp_socket.bind(('', self.listen_port))
        # Set the socket to non-blocking mode
        self.udp_socket.setblocking(False)

    def _get_file_size(self):
        """
        Get desired file size from user input.
        Returns:
            int: File size in bytes
        """
        while True:
            try:
                # Prompt the user to enter the file size
                size = input("\033[96mEnter file size for speed test (in bytes): \033[0m")
                return int(size)  # Convert the input to an integer
            except ValueError:
                print("\033[91mPlease enter a valid number\033[0m")  # Ask for valid input

    def _discover_server(self):
        """
        Discover speed test servers using select() for non-blocking I/O.
        Uses event-driven approach to avoid busy waiting.
        """
        print("\033[93mLooking for speed test server...\033[0m")

        while self.running and self.state == ClientState.LOOKING_FOR_SERVER:
            # Wait for incoming data with a timeout
            readable, _, _ = select.select([self.udp_socket], [], [], 1.0)

            if readable:
                try:
                    # Receive broadcast message from server
                    data, addr = self.udp_socket.recvfrom(1024)

                    if len(data) == 9:
                        # Unpack the received data to extract server details
                        magic_cookie, msg_type, udp_port, tcp_port = struct.unpack('!IbHH', data)

                        # Check if the data is a valid server offer
                        if magic_cookie == self.magic_cookie and msg_type == 0x2:
                            print(f"\033[92mReceived offer from {addr[0]}\033[0m")
                            # Switch to SPEED_TEST state
                            self.state = ClientState.SPEED_TEST
                            # Run the speed test with the server
                            self._run_speed_test(addr[0], udp_port, tcp_port)
                            break

                except Exception as e:
                    print(f"\033[91mError processing server offer: {e}\033[0m")

    def _run_tcp_test(self, server_host, server_port, transfer_num):
        """
        Perform a TCP speed test with the server.
        Args:
            server_host (str): Server's host address
            server_port (int): Server's TCP port
            transfer_num (int): Transfer test number
        """
        tcp_socket = None
        try:
            # Create a TCP socket and connect to the server
            tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            tcp_socket.settimeout(10.0)
            tcp_socket.connect((server_host, server_port))

            # Send the file size to the server
            tcp_socket.send(f"{self.file_size}\n".encode())

            # Record the start time
            start_time = time.time()
            received = 0

            # Receive the file data from the server
            while received < self.file_size:
                readable, _, _ = select.select([tcp_socket], [], [], 5.0)
                if not readable:
                    raise TimeoutError("TCP test timed out")

                # Receive a chunk of data
                chunk = tcp_socket.recv(min(4096, self.file_size - received))
                if not chunk:
                    break
                received += len(chunk)

            # Record the end time
            end_time = time.time()
            transfer_time = end_time - start_time

            # Calculate and display the speed
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
                tcp_socket.close()  # Ensure the socket is closed

    def _run_udp_test(self, server_host, server_port, transfer_num):
        """
        Perform a UDP speed test with the server.
        Args:
            server_host (str): Server's host address
            server_port (int): Server's UDP port
            transfer_num (int): Transfer test number
        """
        udp_socket = None
        try:
            # Create a UDP socket
            udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            udp_socket.settimeout(5.0)


            # Send a request to the server with the file size
            request = struct.pack('!IbQ', self.magic_cookie, 0x3, self.file_size)
            udp_socket.sendto(request, (server_host, server_port))

            received_segments = set()  # Track received segments
            total_segments = None  # Total segments to receive
            start_time = time.time()

            # Receive data from the server
            while True:
                try:
                    readable, _, _ = select.select([udp_socket], [], [], 5.0)
                    if not readable:
                        break

                    # Receive data
                    data, _ = udp_socket.recvfrom(4096)
                    if len(data) < 21:
                        continue

                    # Extract the header and segment information
                    header = data[:21]
                    magic_cookie, msg_type, total_segs, current_seg = struct.unpack('!IbQQ', header)

                    # Verify the data
                    if magic_cookie != self.magic_cookie or msg_type != 0x4:
                        continue

                    # Store the total segments if not already set
                    if total_segments is None:
                        total_segments = total_segs

                    received_segments.add(current_seg)  # Add the segment to the set
                    self.statistics['udp_packets_received'] += 1

                    # Break if all segments are received
                    if len(received_segments) == total_segments:
                        break

                except socket.timeout:
                    break

            # Record the end time
            end_time = time.time()
            transfer_time = end_time - start_time

            # Calculate and display the results
            if total_segments:
                packets_lost = total_segments - len(received_segments)
                loss_rate = (packets_lost / total_segments) * 100
                speed = (self.file_size * 8) / transfer_time

                self.statistics['udp_times'].append(transfer_time)
                self.statistics['udp_packets_lost'] = packets_lost

                print(f"\033[92m\nUDP transfer #{transfer_num} finished, total time: {transfer_time:.3f} seconds, total speed: {speed:.2f} bits/second, percentage of packets received successfully: {100 - loss_rate:.2f}%\033[0m")
            else:
                print(f"\033[91m\nUDP transfer #{transfer_num} finished, but no segments were received.\033[0m")

        except Exception as e:
            print(f"\033[91mError in UDP test: {e}\033[0m")
        finally:
            if udp_socket:
                udp_socket.close()  # Ensure the socket is closed

    def _run_speed_test(self, server_host, udp_port, tcp_port):
        """
        Perform speed tests using both TCP and UDP.
        Args:
            server_host (str): Server's host address
            udp_port (int): Server's UDP port
            tcp_port (int): Server's TCP port
        """
        tcp_threads = []  # List to track TCP threads
        udp_threads = []  # List to track UDP threads

        # Ask the user how many connections to create
        num_tcp = int(input("Enter number of TCP connections: "))
        num_udp = int(input("Enter number of UDP connections: "))

        # Start TCP test threads
        for i in range(num_tcp):
            tcp_thread = threading.Thread(target=self._run_tcp_test, args=(server_host, tcp_port, i + 1))
            tcp_threads.append(tcp_thread)
            tcp_thread.start()

        # Start UDP test threads
        for i in range(num_udp):
            udp_thread = threading.Thread(target=self._run_udp_test, args=(server_host, udp_port, i + 1))
            udp_threads.append(udp_thread)
            udp_thread.start()

        # Wait for all threads to complete
        for thread in tcp_threads + udp_threads:
            thread.join()

        # Print statistics after all tests are done
        self._print_statistics()
        print("\033[93mAll transfers complete, listening to offer requests\033[0m")
        self.state = ClientState.LOOKING_FOR_SERVER

    def _print_statistics(self):
        """
        Display the speed test results and statistics.
        """
        print("\n\033[95m=== Speed Test Statistics ===\033[0m")

        # Display TCP statistics if available
        if self.statistics['tcp_times']:
            avg_tcp = statistics.mean(self.statistics['tcp_times'])
            print(f"\033[96mTCP Average Time: {avg_tcp:.3f}s")
            print(f"TCP Average Speed: {(self.file_size * 8 / avg_tcp):.2f} bits/second\033[0m")

        # Display UDP statistics if available
        if self.statistics['udp_times']:
            avg_udp = statistics.mean(self.statistics['udp_times'])
            loss_rate = (self.statistics['udp_packets_lost'] / (self.statistics['udp_packets_received'] + self.statistics['udp_packets_lost'])) * 100
            print(f"\033[96mUDP Average Time: {avg_udp:.3f}s")
            print(f"UDP Packet Loss Rate: {loss_rate:.2f}%\033[0m")

    def _cleanup(self):
        """
        Clean up resources before exiting.
        """
        try:
            # Close the UDP socket if it exists
            if hasattr(self, 'udp_socket'):
                self.udp_socket.close()
        except Exception as e:
            print(f"\033[91mError during cleanup: {e}\033[0m")


if __name__ == "_main_":
    # Create an instance of the client and start it
    client = SpeedTestClient()
    client.start()