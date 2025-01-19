import http.server
import urllib.request
import urllib.error
import ssl
import hashlib
import gzip
import brotli
import zlib
from load_balancer import LoadBalancer
from cache import LRUCache

# API key for authentication
VALID_API_KEY = "test-api-key-123"  # In production this should be more secure and configurable

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