import socket  # For network communication
import threading  # For handling multiple clients simultaneously
import struct  # For packing/unpacking binary data
import time  # For timing operations
import random  # For generating random port numbers
import select  # For non-blocking I/O
import signal  # For handling system signals

class SpeedTestServer:
    """
    A server class that handles network speed testing using both TCP and UDP protocols.
    """

    def __init__(self, host='', offer_port=13117):
        """
        Initialize the server with specified host and port.
        Args:
            host (str): The server's host address (default: all interfaces)
            offer_port (int): Port for broadcasting server offers (default: 13117)
        """
        self.host = host  # Store the server's host address
        self.offer_port = offer_port  # Port for broadcasting offers
        self.udp_port = random.randint(20000, 65000)  # Random UDP port for speed tests
        self.tcp_port = random.randint(20000, 65000)  # Random TCP port for speed tests
        self.running = False  # Flag to indicate whether the server is running
        self.magic_cookie = 0xabcddcba  # Unique identifier for valid packets
        self.msg_type_offer = 0x2  # Message type for server offer packets

        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """
        Handle system signals for graceful shutdown.
        Args:
            signum: Signal number
            frame: Current stack frame
        """
        print("\n\033[93mShutting down server...\033[0m")  # Inform about shutdown
        self.stop()  # Stop the server

    def start(self):
        """
        Start the server and initialize all necessary sockets and threads.
        """
        self.running = True  # Set the running flag to True

        try:
            # Create and bind a UDP socket for speed test communication
            self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp_socket.bind((self.host, self.udp_port))

            # Create and bind a TCP socket for speed test communication
            self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.tcp_socket.bind((self.host, self.tcp_port))
            self.tcp_socket.listen(5)  # Listen for incoming connections

            # Start a thread to broadcast server offers
            self.broadcast_thread = threading.Thread(target=self._broadcast_offer)
            self.broadcast_thread.daemon = True  # Ensure thread exits with the program
            self.broadcast_thread.start()

            # Get and print the server's IP address
            server_ip = socket.gethostbyname(socket.gethostname())
            print(f"\033[92mWonder Woman's - Server started, listening on IP address {server_ip}\033[0m")
            print(f"\033[92mPort: {self.udp_port}, TCP Port: {self.tcp_port}\033[0m")

            # Handle client requests
            self._handle_requests()

        except Exception as e:
            print(f"\033[91mError starting server: {e}\033[0m")
            self.stop()  # Stop the server on error

    def _broadcast_offer(self):
        """
        Continuously broadcast server offer messages using non-blocking sockets.
        """
        try:
            # Create a UDP socket for broadcasting
            offer_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            offer_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

            # Prepare the offer message with server details
            offer_message = struct.pack('!IbHH',
                                        self.magic_cookie,
                                        self.msg_type_offer,
                                        self.udp_port,
                                        self.tcp_port)

            while self.running:
                try:
                    # Send the offer message as a broadcast
                    offer_socket.sendto(offer_message, ('<broadcast>', self.offer_port))
                    time.sleep(1)  # Wait before sending the next offer
                except Exception as e:
                    print(f"\033[91mError broadcasting offer: {e}\033[0m")

        except Exception as e:
            print(f"\033[91mError in broadcast thread: {e}\033[0m")
        finally:
            offer_socket.close()  # Ensure the socket is closed

    def _handle_requests(self):
        """
        Main loop for handling incoming client requests.
        """
        # Set sockets to non-blocking mode
        self.udp_socket.setblocking(False)
        self.tcp_socket.setblocking(False)

        inputs = [self.udp_socket, self.tcp_socket]  # List of sockets to monitor

        while self.running:
            try:
                # Wait for socket activity
                readable, _, exceptional = select.select(inputs, [], inputs, 1.0)

                for sock in readable:
                    if sock is self.udp_socket:
                        try:
                            # Handle incoming UDP data in a new thread
                            data, addr = sock.recvfrom(1024)
                            threading.Thread(target=self._handle_udp_speed_test, args=(data, addr)).start()
                        except Exception as e:
                            print(f"\033[91mError handling UDP request: {e}\033[0m")

                    elif sock is self.tcp_socket:
                        try:
                            # Accept a new TCP connection and handle it in a new thread
                            client_socket, addr = sock.accept()
                            threading.Thread(target=self._handle_tcp_client, args=(client_socket, addr)).start()
                        except Exception as e:
                            print(f"\033[91mError handling TCP connection: {e}\033[0m")

                for sock in exceptional:
                    print(f"\033[91mException condition on {sock.getsockname()}\033[0m")
                    inputs.remove(sock)  # Remove the socket from the monitored list
                    sock.close()  # Close the problematic socket

            except Exception as e:
                print(f"\033[91mError in request handling: {e}\033[0m")

    def _handle_udp_speed_test(self, data, addr):
        """
        Handle a UDP speed test request from a client.
        Args:
            data: The data received from the client
            addr: The client's address
        """
        try:
            # Unpack the client's request
            magic_cookie, msg_type, file_size = struct.unpack('!IbQ', data)

            if magic_cookie != self.magic_cookie or msg_type != 0x3:
                print(f"\033[91mInvalid UDP request from {addr}\033[0m")
                return

            print(f"\033[94mUDP test request from {addr}, size: {file_size} bytes\033[0m")

            # Calculate the number of segments to send
            segment_size = 1024
            total_segments = (file_size + segment_size - 1) // segment_size

            for i in range(total_segments):
                remaining = min(segment_size, file_size - i * segment_size)  # Calculate remaining bytes
                payload = b'X' * remaining  # Create a payload of 'X' characters

                # Create the segment header
                header = struct.pack('!IbQQ',
                                     self.magic_cookie,
                                     0x4,
                                     total_segments,
                                     i)

                # Send the segment to the client
                self.udp_socket.sendto(header + payload, addr)

        except Exception as e:
            print(f"\033[91mError handling UDP request: {e}\033[0m")

    def _handle_tcp_client(self, client_socket, addr):
        """
        Handle a TCP speed test request from a client.
        Args:
            client_socket: The socket connected to the client
            addr: The client's address
        """
        try:
            client_socket.settimeout(5.0)  # Set a timeout for the client socket

            # Receive the file size from the client
            data = client_socket.recv(1024).decode().strip()
            file_size = int(data)

            print(f"\033[94mTCP test request from {addr}, size: {file_size} bytes\033[0m")

            # Send the requested amount of data to the client
            data = b'X' * file_size
            client_socket.sendall(data)

        except Exception as e:
            print(f"\033[91mError handling TCP client: {e}\033[0m")
        finally:
            client_socket.close()  # Close the client socket

    def stop(self):
        """
        Stop the server and clean up resources.
        """
        self.running = False  # Set the running flag to False
        try:
            if hasattr(self, 'udp_socket'):
                self.udp_socket.close()  # Close the UDP socket
            if hasattr(self, 'tcp_socket'):
                self.tcp_socket.close()  # Close the TCP socket
        except Exception as e:
            print(f"\033[91mError during cleanup: {e}\033[0m")

if __name__ == "__main__":
    server = SpeedTestServer()  # Create an instance of the server
    try:
        server.start()  # Start the server
    except KeyboardInterrupt:
        server.stop()  # Stop the server on interruption