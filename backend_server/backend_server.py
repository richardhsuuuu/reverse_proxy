from flask import Flask, request, jsonify
import functools
import argparse
import json

app = Flask(__name__)

def check_proxy(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        # Only allow requests from localhost (where the proxy runs)
        if request.remote_addr != '127.0.0.1':
            return jsonify({'error': 'Access denied'}), 403
            
        # Verify the request came through our proxy by checking headers
        if 'X-Forwarded-For' not in request.headers:
            return jsonify({'error': 'Direct access not allowed'}), 403
            
        return f(*args, **kwargs)
    return decorated_function

@app.route('/health')
@check_proxy
def health_check():
    """Health check endpoint that returns 200 OK if server is running"""
    # Log health check request
    print("\n=== Health Check Request ===")
    print(f"Method: {request.method}")
    print(f"Remote Addr: {request.remote_addr}")
    print("Headers:")
    for header, value in request.headers.items():
        print(f"  {header}: {value}")
    print("================\n")
    return '', 200

@app.route('/', defaults={'path': ''}, methods=['GET', 'POST'])
@app.route('/<path:path>', methods=['GET', 'POST'])
@check_proxy
def catch_all(path):
    """
    Catch-all route that handles all incoming requests and returns basic info
    about the request along with a 200 status code
    """
    # Log request details
    print("\n=== Incoming Request ===")
    print(f"Method: {request.method}")
    print(f"Path: /{path}")
    print("Headers:")
    for header, value in request.headers.items():
        print(f"  {header}: {value}")
    print("Query Parameters:", dict(request.args))
    print("Body:", request.get_json(silent=True) if request.is_json else request.get_data(as_text=True))

    response_data = {
        'status': 'success',
        'message': 'Request received successfully (SSL)',
        'path': path,
        'method': request.method,
        'headers': dict(request.headers),
        'query_params': dict(request.args),
        'body': request.get_json(silent=True) if request.is_json else request.get_data(as_text=True),
        'ssl_info': {
            'protocol': request.environ.get('SSL_PROTOCOL', 'Unknown'),
            'cipher': request.environ.get('SSL_CIPHER', 'Unknown'),
            'forwarded_proto': request.headers.get('X-Forwarded-Proto', 'Unknown')
        }
    }

    # Only include port in response if debug mode was enabled via command line
    if app.config.get('DEBUG_MODE'):
        response_data['port'] = request.environ.get('SERVER_PORT')
    
    # Log response details
    print("\n=== Outgoing Response ===")
    print("Status: 200")
    print("Response Body:")
    print(json.dumps(response_data, indent=2))
    print("================\n")
    
    return jsonify(response_data), 200

if __name__ == '__main__':
    # Set up argument parser
    parser = argparse.ArgumentParser(description='Run backend server with specified port')
    parser.add_argument('port', type=int, nargs='?', default=8000,
                       help='Port number to run the server on (default: 8000)')
    parser.add_argument('--debug', action='store_true',
                       help='Enable debug mode and include port in responses')
    args = parser.parse_args()

    # Store debug setting in app config
    app.config['DEBUG_MODE'] = args.debug

    # If the certificate doesn't exist, generate it (reuse the one from the proxy)
    import os
    if not (os.path.exists("ssl/server.crt") and os.path.exists("ssl/server.key")):
        print("Please run the proxy server first to generate the SSL certificate")
        exit(1)
    
    # Run on localhost with SSL using specified port
    app.run(host='127.0.0.1', port=args.port, ssl_context=('ssl/server.crt', 'ssl/server.key'), debug=args.debug)