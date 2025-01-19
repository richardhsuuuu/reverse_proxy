from enum import Enum
import time
import threading
import ssl
import urllib

class HostStatus(Enum):
    NOT_INITIATED = "NOT_INITIATED"
    HEALTHY = "HEALTHY"
    UNREACHABLE = "UNREACHABLE"

class BackendServer:
    """
    Represents a backend server in the reverse proxy system, responsible for handling
    health checks and maintaining the server's status.

    Attributes:
        url (str): The URL of the backend server.
        status (HostStatus): The current health status of the server, initialized to NOT_INITIATED.
        last_check (float): The timestamp of the last health check performed.
        check_interval (int): The interval in seconds between health checks. Defaults to 1 second.
        failure_count (int): The number of consecutive failed health checks.
        max_failures (int): The maximum number of allowed consecutive failures before marking the server as unhealthy. Defaults to 3.
        last_healthy (float or None): The timestamp of the last successful health check, or None if never healthy.

    Methods:
        check_health(ssl_context, debug=False):
            Performs a health check on the backend server. Updates the server's status based on the response.
            If the server is healthy, resets the failure count and updates the last healthy timestamp.
            If the server fails the health check, increments the failure count and may mark the server as UNREACHABLE.
            Returns True if the server is healthy, False otherwise.
    """
    
    def __init__(self, url):
        self.url = url
        self.status = HostStatus.NOT_INITIATED
        self.last_check = 0
        self.check_interval = 1  # Health check interval in seconds
        self.failure_count = 0
        self.max_failures = 3  # Configurable max failures before marking unhealthy
        self.last_healthy = None  # Track last time server was healthy

    def check_health(self, ssl_context, debug=False):
        """Check if backend server is responding"""
        if time.time() - self.last_check < self.check_interval:
            return self.status == HostStatus.HEALTHY

        try:
            # Add headers to indicate request is from proxy
            headers = {
                'X-Forwarded-For': '127.0.0.1'
            }
            request = urllib.request.Request(f"{self.url}/health", headers=headers)
            with urllib.request.urlopen(request, timeout=5, context=ssl_context) as response:
                if response.status == 200:
                    was_not_healthy = self.status != HostStatus.HEALTHY
                    self.status = HostStatus.HEALTHY
                    self.failure_count = 0  # Reset failure count on success
                    self.last_healthy = time.time()  # Update last healthy timestamp
                    if was_not_healthy and debug:
                        print(f"INFO: Backend server {self.url} is healthy again and has been added back to rotation")
                else:
                    self.failure_count += 1
                    if self.failure_count >= self.max_failures and self.last_healthy and self.last_healthy > 0:
                        # Only mark as unreachable if it was healthy before
                        self.status = HostStatus.UNREACHABLE
                        if debug:
                            print(f"WARNING: Backend server {self.url} failed health check {self.failure_count} times and will be removed from rotation")
        except:
            self.failure_count += 1
            if self.failure_count >= self.max_failures and self.last_healthy and self.last_healthy > 0:
                # Only mark as unreachable if it was healthy before
                self.status = HostStatus.UNREACHABLE
                if debug:
                    print(f"WARNING: Backend server {self.url} failed health check {self.failure_count} times and will be removed from rotation")

        self.last_check = time.time()
        return self.status == HostStatus.HEALTHY

class LoadBalancer:
    """
    LoadBalancer is responsible for distributing incoming requests across multiple backend servers
    It ensures that requests are sent to healthy servers using a round-robin algorithm and continuously
    monitors the health of each backend server.

    Attributes:
        backends (list): A list of BackendServer instances representing the backend servers.
        current (int): An index to track the current backend server for round-robin selection.
        lock (threading.Lock): A lock to ensure thread-safe operations when selecting backends.
        debug (bool): A flag to enable or disable debug mode for detailed logging.
        freq_sec (int): Frequency in seconds for health checks on backend servers.
        health_check_thread (threading.Thread): A background thread that monitors the health of backends.

    Methods:
        _monitor_backends():
            Continuously checks the health of each backend server and logs their status if debug is enabled.

        get_next_backend(ssl_context):
            Returns the next healthy backend server using a round-robin algorithm. If no healthy server is found,
            it returns None.
    """

    def __init__(self, backend_urls, debug=False):
        self.backends = [BackendServer(url) for url in backend_urls]
        self.current = 0
        self.lock = threading.Lock()
        self.debug = debug
        # Start health check thread
        self.freq_sec = 1
        self.health_check_thread = threading.Thread(target=self._monitor_backends, daemon=True)
        self.health_check_thread.start()

    def _monitor_backends(self):
        """Continuously monitor backend health in background"""
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        while True:
            healthy_count = 0
            if self.debug:
                print("\n=== Backend Server Status ===")
                print("┌────────────────────────┬────────────-──┬───────────┬──────────────────┐")
                print("│ Backend URL            │ Status        │ Failures  │ Last Healthy     │")
                print("├────────────────────────┼─────────────-─┼───────────┼──────────────────┤")
            
            for backend in self.backends:
                backend.check_health(ssl_context, self.debug)
                if backend.status == HostStatus.HEALTHY:
                    healthy_count += 1
                if self.debug:
                    if not backend.last_healthy:
                        last_healthy_str = ''
                    else:
                        last_healthy_str = time.strftime('%H:%M:%S', time.localtime(backend.last_healthy))
                    print(f"│ {backend.url:<20} │ {backend.status.value:<13} │ {backend.failure_count:^9} │ {last_healthy_str:^14} │")
            
            if self.debug:
                print("└────────────────────────┴─────────-─────┴───────────┴──────────────────┘")
            
            if healthy_count == 0 and self.debug:
                print("WARNING: All backend servers are currently unhealthy!")
            
            time.sleep(self.freq_sec)  # Check every 1 second

    def get_next_backend(self, ssl_context):
        """Get next healthy backend server using round-robin"""
        with self.lock:
            start = self.current
            while True:
                self.current = (self.current + 1) % len(self.backends)
                backend = self.backends[self.current]
                if backend.status == HostStatus.HEALTHY:
                    return backend
                # If we've checked all backends and come back to start, none are healthy
                if self.current == start:
                    if self.debug:
                        print("Looped through all the hosts but None are available")
                    return None

