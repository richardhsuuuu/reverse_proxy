import http.server
import urllib.request
import urllib.error
import ssl
import hashlib
import time
from collections import OrderedDict
import threading
import gzip
import brotli
import zlib
from enum import Enum

# API key for authentication
VALID_API_KEY = "test-api-key-123"  # In production this should be more secure and configurable

class LRUCache:
    """
    A simple implementation of a Least Recently Used (LRU) cache with time-based expiration.

    This LRUCache class uses an OrderedDict to maintain the order of cache entries, ensuring
    that the least recently used items are removed first when the cache exceeds its capacity.
    Each cache entry is associated with a time-to-live (TTL) value, after which the entry is
    considered expired and will be removed upon access.

    Attributes:
        capacity (int): The maximum number of entries the cache can hold. Defaults to 1000.
        TTL (int): The time-to-live for each cache entry in seconds. Defaults to 300 seconds.
        cache (OrderedDict): An ordered dictionary to store cache entries, maintaining access order.
        expiry (dict): A dictionary to track the expiration time of each cache entry.
    """

    def __init__(self, capacity=1000):
        self.cache = OrderedDict()
        self.capacity = capacity
        self.expiry = {}
        self.TTL = 300  # Cache TTL in seconds

    def get(self, key):
        if key in self.cache:
            if time.time() - self.expiry[key] > self.TTL:
                # Remove expired entry
                self.cache.pop(key)
                self.expiry.pop(key) 
                return None
            # Move to end to show recently used
            self.cache.move_to_end(key)
            return self.cache[key]
        return None

    def put(self, key, value):
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = value
        self.expiry[key] = time.time()
        if len(self.cache) > self.capacity:
            # Remove least recently used
            oldest = next(iter(self.cache))
            self.cache.popitem(last=False)
            self.expiry.pop(oldest)

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


class SSLReverseProxyHandler(http.server.BaseHTTPRequestHandler):
    """
    SSLReverseProxyHandler is responsible for handling incoming HTTP requests and forwarding them to backend servers.
    It supports various HTTP methods, API key validation, caching, and content compression.

    Attributes:
        BACKEND_URLS (list): List of backend server URLs to forward requests to.
        ssl_context (ssl.SSLContext): SSL context for outgoing requests.
        cache (LRUCache): Cache for storing responses to reduce load on backend servers.
        load_balancer (LoadBalancer): Load balancer instance for distributing requests across backend servers.
        debug (bool): Flag to enable or disable debug mode.

    Methods:
        validate_api_key(): Validate the API key from request headers.
        do_GET(): Handle GET requests.
        do_POST(): Handle POST requests.
        do_PUT(): Handle PUT requests.
        do_DELETE(): Handle DELETE requests.
        do_PATCH(): Handle PATCH requests.
        do_HEAD(): Handle HEAD requests.
        do_OPTIONS(): Handle OPTIONS requests.
        generate_cache_key(method, path, headers, body, encoding='identity'): Generate a unique cache key based on request attributes and encoding.
        compress_content(content, encoding): Compress content using specified encoding.
        get_accepted_encoding(): Get client's accepted encoding from headers.
        proxy_request(method): Forward the request to the backend server and handle the response.
    """
    # Backend servers to forward requests to
    BACKEND_URLS = [
        f"https://127.0.0.1:{port}" 
        for port in range(8000, 8010)  # Generates URLs for ports 8000-8100
    ]
    # SSL Context for outgoing requests
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    # Initialize cache and load balancer
    cache = LRUCache()
    load_balancer = None  # Will be initialized with debug flag
    debug = False  # Class variable for debug mode

    def validate_api_key(self):
        """Validate the API key from request headers"""
        api_key = self.headers.get('X-API-Key')
        if not api_key or api_key != VALID_API_KEY:
            self.send_error(401, "Unauthorized - Invalid or missing API key")
            return False
        return True

    def do_GET(self):
        """Handle GET requests"""
        if not self.validate_api_key():
            return
        self.proxy_request("GET")

    def do_POST(self):
        """Handle POST requests"""
        if not self.validate_api_key():
            return
        self.proxy_request("POST")

    def do_PUT(self):
        """Handle PUT requests"""
        if not self.validate_api_key():
            return
        self.proxy_request("PUT")

    def do_DELETE(self):
        """Handle DELETE requests"""
        if not self.validate_api_key():
            return
        self.proxy_request("DELETE")

    def do_PATCH(self):
        """Handle PATCH requests"""
        if not self.validate_api_key():
            return
        self.proxy_request("PATCH")

    def do_HEAD(self):
        """Handle HEAD requests"""
        if not self.validate_api_key():
            return
        self.proxy_request("HEAD")

    def do_OPTIONS(self):
        """Handle OPTIONS requests"""
        if not self.validate_api_key():
            return
        self.proxy_request("OPTIONS")

    def generate_cache_key(self, method, path, headers, body, encoding='identity'):
        """Generate a unique cache key based on request attributes and encoding"""
        key_parts = [method, path, encoding]
        
        # Add relevant headers to cache key
        for header in sorted(headers.keys()):
            if header.lower() in ['accept', 'content-type']:
                key_parts.append(f"{header}:{headers[header]}")
                
        # Add body for POST requests
        if body:
            key_parts.append(str(body))
            
        key_string = '|'.join(key_parts)
        return hashlib.md5(key_string.encode()).hexdigest()

    def compress_content(self, content, encoding):
        """Compress content using specified encoding"""
        if encoding == 'gzip':
            return gzip.compress(content)
        elif encoding == 'br':
            return brotli.compress(content)
        elif encoding == 'deflate':
            return zlib.compress(content)
        return content

    def get_accepted_encoding(self):
        """Get client's accepted encoding from headers"""
        accept_encoding = self.headers.get('Accept-Encoding', '')
        if 'br' in accept_encoding:
            return 'br'
        elif 'gzip' in accept_encoding:
            return 'gzip'
        elif 'deflate' in accept_encoding:
            return 'deflate'
        return 'identity'

    def proxy_request(self, method):
        """Forward the request to the backend server and handle the response"""
        max_retries = 2  # Configurable number of retries
        retries = 0
        last_exception = None

        while retries <= max_retries:
            try:
                # Get next available backend
                backend = self.load_balancer.get_next_backend(self.ssl_context)
                if not backend:
                    raise Exception("No healthy backend servers available")

                # Construct the full URL for the backend request
                backend_url = backend.url + self.path
                
                # Get request headers
                headers = {}
                for key, value in self.headers.items():
                    if key.lower() not in ['connection', 'keep-alive', 'proxy-authenticate', 
                                         'proxy-authorization', 'te', 'trailers', 'transfer-encoding', 
                                         'upgrade']:
                        headers[key] = value

                # Add X-Forwarded headers
                headers['X-Forwarded-For'] = self.client_address[0]
                headers['X-Forwarded-Host'] = self.headers.get('Host', '')
                headers['X-Forwarded-Proto'] = 'https'

                # Read request body for POST requests
                content_length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_length) if content_length > 0 else None

                # Get client's accepted encoding
                accepted_encoding = self.get_accepted_encoding()

                # Generate cache key including encoding
                cache_key = self.generate_cache_key(method, self.path, headers, body, accepted_encoding)
                
                # Try to get response from cache for GET requests
                cached_response = None
                if method == "GET":
                    cached_response = self.cache.get(cache_key)
                
                if cached_response:
                    # Use cached response
                    status_code, headers, content = cached_response
                    self.send_response(status_code)
                    for key, value in headers:
                        if key.lower() not in ['connection', 'keep-alive', 'proxy-authenticate',
                                             'proxy-authorization', 'te', 'trailers', 'transfer-encoding',
                                             'upgrade']:
                            self.send_header(key, value)
                    self.send_header('X-Cache', 'HIT')
                    self.end_headers()
                    self.wfile.write(content)
                    if self.debug:
                        print(f"Cache HIT for {self.path}")
                    return  # Successfully used cache, no need to retry
                else:
                    # Create request
                    request = urllib.request.Request(
                        backend_url,
                        data=body,
                        headers=headers,
                        method=method
                    )

                    # Forward the request to the backend server using our SSL context
                    with urllib.request.urlopen(request, context=self.ssl_context) as response:
                        # Set response status code
                        self.send_response(response.status)
                        
                        # Get response headers before sending
                        response_headers = list(response.getheaders())
                        
                        # Read response content
                        content = response.read()

                        # Compress content if needed
                        if accepted_encoding != 'identity':
                            content = self.compress_content(content, accepted_encoding)
                            self.send_header('Content-Encoding', accepted_encoding)
                        
                        # Forward response headers
                        for key, value in response_headers:
                            if key.lower() not in ['connection', 'keep-alive', 'proxy-authenticate', 
                                                 'proxy-authorization', 'te', 'trailers', 'transfer-encoding', 
                                                 'upgrade', 'content-encoding', 'content-length']:
                                self.send_header(key, value)

                        self.send_header('Content-Length', str(len(content)))
                        self.send_header('X-Cache', 'MISS')
                        self.send_header('X-Backend-Server', backend.url)
                        if retries > 0:
                            self.send_header('X-Retry-Count', str(retries))
                        self.end_headers()
                        
                        # Cache the response for GET requests
                        if method == "GET":
                            self.cache.put(cache_key, (response.status, response_headers, content))
                        
                        # Forward response body
                        self.wfile.write(content)
                        return  # Successfully processed request, no need to retry

            except (urllib.error.HTTPError, urllib.error.URLError, Exception) as e:
                last_exception = e
                if self.debug:
                    print(f"Request failed on backend {backend.url if backend else 'None'}, attempt {retries + 1}/{max_retries + 1}: {str(e)}")
                retries += 1
                # Mark the current backend as unhealthy
                if backend:
                    backend.healthy = False
                continue

        # If we get here, we've exhausted all retries
        if isinstance(last_exception, urllib.error.HTTPError):
            self.send_error(last_exception.code, last_exception.reason)
        elif isinstance(last_exception, urllib.error.URLError):
            self.send_error(500, str(last_exception.reason))
        else:
            self.send_error(500, str(last_exception))

class SSLHTTPServer(http.server.HTTPServer):
    def __init__(self, server_address, handler_class, certfile, keyfile):
        super().__init__(server_address, handler_class)
        
        # Create SSL context for incoming connections
        self.ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        self.ssl_context.load_cert_chain(certfile=certfile, keyfile=keyfile)
        
        # Wrap socket with SSL
        self.socket = self.ssl_context.wrap_socket(self.socket, server_side=True)

def run_ssl_proxy(port=8443, certfile='ssl/server.crt', keyfile='ssl/server.key', debug=False):
    """
    Run the SSL-enabled reverse proxy server
    
    Args:
        port (int): Port to listen on (default: 8443 for HTTPS)
        certfile (str): Path to SSL certificate file
        keyfile (str): Path to SSL private key file
        debug (bool): Enable debug logging
    """
    server_address = ('', port)
    SSLReverseProxyHandler.debug = debug
    SSLReverseProxyHandler.load_balancer = LoadBalancer(SSLReverseProxyHandler.BACKEND_URLS, debug)
    try:
        httpd = SSLHTTPServer(server_address, SSLReverseProxyHandler, certfile, keyfile)
        if debug:
            print(f"Starting SSL reverse proxy server on port {port}")
            print("Press Ctrl+C to stop the server")
        httpd.serve_forever()
    except KeyboardInterrupt:
        if debug:
            print("\nShutting down the server...")
        httpd.socket.close()

def _generate_self_signed_cert():
    """
    Generate a self-signed certificate for testing purposes
    """
    from OpenSSL import crypto
    
    # Generate key
    key = crypto.PKey()
    key.generate_key(crypto.TYPE_RSA, 2048)
    
    # Generate certificate
    cert = crypto.X509()
    cert.get_subject().CN = "localhost"
    cert.set_serial_number(1000)
    cert.gmtime_adj_notBefore(0)
    cert.gmtime_adj_notAfter(365*24*60*60)  # Valid for one year
    cert.set_issuer(cert.get_subject())
    cert.set_pubkey(key)
    cert.sign(key, 'sha256')
    
    # Save certificate and private key
    with open("ssl/server.crt", "wb") as f:
        f.write(crypto.dump_certificate(crypto.FILETYPE_PEM, cert))
    with open("ssl/server.key", "wb") as f:
        f.write(crypto.dump_privatekey(crypto.FILETYPE_PEM, key))

if __name__ == "__main__":
    import os
    import argparse

    parser = argparse.ArgumentParser(description='Run SSL reverse proxy server')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    args = parser.parse_args()
    
    # Generate self-signed certificate if it doesn't exist
    if not (os.path.exists("ssl/server.crt") and os.path.exists("ssl/server.key")):
        if args.debug:
            print("Generating self-signed certificate...")
        _generate_self_signed_cert()
        if args.debug:
            print("Certificate generated successfully")
    
    run_ssl_proxy(debug=args.debug)