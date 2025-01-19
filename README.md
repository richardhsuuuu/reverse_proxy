# Reverse Proxy Implementation

A robust reverse proxy server implementation in Python with load balancing, caching, and SSL termination capabilities.

## Main Questions and Answers

### How can someone get started with your codebase?

- Refer to the "Quick Start" section. You will need to set up a virtual environment (or use the provided one for convenience), run multiple backend servers (Flask) on different specified ports, and then execute the `reverse_proxy`.
- You can test the setup using CURL or the load-testing tool I created.
- If you pass in the debug param, you will notice in the response output, there's a "port" which indicate which host it's hitting from BE, and that will keep rotating due to the round-robhin Load Balancing I implemented.

### What resources did you use to build your implementation?

- I utilized a GenAI tool to code up more implementation after i decide on the high-level features i must implement
- My approach involved looking at each aspect of reverse proxy functionality, selecting at least one key feature to implement, and gradually adding features and robustness. I concluded by developing a load testing tool to ensure everything functions correctly.
- The most intriguing part was the health check and auto-discovery feature of the LoadBalancer, which I specifically separated. This feature allows hosts to dynamically join or leave, automatically updating the pool of available hosts in a separate health-checking thread.

### Explain any design decisions you made, including limitations of the system

- The system is quite robust. Key decisions include:
  1. Implementing a Cache (LRU) to efficiently utilizing hosts.
  2. Enabling auto-discovery of hosts and automated fail-over to different hosts, only failing requests when the retry count exceeds the internal limit. This is what i'm prob most proud of, as this is a key differentiator of reverse proxies.
- I focused on implementing as many features and testing it live instead of writing unit-tests, i would add unit-tests if we need to bring this online of course.
- Limitation include:
  1. No unit-tests (i tested everything locally on all features, just didnt' get to writing tests)
  2. No sticky session feature implemented yet
  3. Only support Round-robin, but obviously can support other types of algos like weighted round-robin, Dynamic Load Balancing upon CPU/Mem, Least connection, etc.

### How would you scale this?

- I would introduce a dedicated database for comprehensive logging of requests and responses for tracing.
- Enhance security by incorporating JWT tokens.
- Implement sticky sessions if required.
- Add a Rate-Limiter for better control.
- Refactor out different functionalities within the same "reverse_proxy.py" - LRUCache, LoadBalancer,_generate_self_signed_cert, etc.
- The LRUCache can likely be a dedicated RedisCache cluster

### How would you make it more secure?

- Introduce additional authentication methods, such as JWT tokens.
- Implement a whitelist/blacklist mechanism for access control.

## Key Features

- **Security**: Hides backend servers from direct internet access
- **Load Balancing**: Distributes traffic across multiple backend servers
- **Caching**: Caches responses to reduce load on backend servers
- **SSL Termination**: Handles HTTPS encryption/decryption
- **Health Checks**: Monitors backend server health and routes traffic accordingly
- **Compression**: Supports gzip, brotli and deflate compression

## Quick Start

### Prerequisites

1. Python 3.6+
2. Clone this repository
3. Set up Python environment

```bash
python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt
```

#### Example commands to spin up multiple web server backends

   ```bash
   python3 backend_server.py 8000 --debug
   python3 backend_server.py 8001 --debug
   python3 backend_server.py 8002 --debug
   python3 backend_server.py 8003 --debug
   ```

#### Main command to spin up reverse proxy

   ```bash
   python3 reverse_proxy.py --debug
   ```

#### Example CURL commands to test the sample backend

   ```bash
   curl -k -X POST https://localhost:8443/test \
   -H "X-API-Key: test-api-key-123" \
   -H "Content-Type: application/json" \
   -d '{"hello": "world"}'
   ```

   ```bash
   curl -k https://localhost:8443/test \
   -H "X-API-Key: test-api-key-123" \
   -H "Content-Type: application/json"
   ```

#### Example command to execute load testing with POST

   ```bash
   python3 client_load_test.py --rps 100 --duration 10
   ```

## Configurations

VALID_API_KEY = "test-api-key-123"  # Change in production

### Caching

cache_capacity = 1000  # Number of cache entries
cache_ttl = 300       # Cache TTL in seconds

### Health Checks

check_interval = 1    # Health check frequency in seconds
max_failures = 3      # Failures before marking as unhealthy

### Load Balancing

max_retries = 2       # Maximum request retries

## Core Features

### Security 🔒

1. SSL/TLS Support
   - Full SSL/TLS encryption for both incoming and outgoing connections
   - Configurable certificate and private key paths
   - Self-signed certificate generation for development
   - Support for custom SSL contexts and verification modes

2. API Key Authentication
   - Required API key validation for all requests
   - Configurable API key through `VALID_API_KEY` constant
   - Returns 401 Unauthorized for invalid or missing API keys

3. Request Headers
   - Secure header handling with filtering of hop-by-hop headers
   - X-Forwarded-* headers for maintaining client information
   - X-Backend-Server header for request tracing

### Load Balancing ⚖️

1. Round-Robin Algorithm
   - Thread-safe implementation using locks
   - Automatic server rotation
   - Skips unhealthy backends
   - Configurable retry mechanism for failed requests

2. Backend Management
   - Dynamic backend server pool
   - Configurable through `BACKEND_URLS`
   - Support for multiple backend instances
   - Backend status tracking and monitoring

3. Request Distribution
   - Even distribution across healthy backends
   - Automatic failover on backend failures
   - Request retry support with configurable attempts
   - Debug mode for monitoring distribution patterns

### Caching 📦

1. LRU Cache Implementation
   - Least Recently Used (LRU) caching strategy
   - Configurable cache capacity
   - Time-based cache expiration (TTL)
   - Support for varied content encodings

2. Cache Keys
   - Unique key generation based on:
     - Request method
     - Path
     - Relevant headers
     - Request body
     - Content encoding

3. Cache Control
   - Cache hit/miss headers
   - Automatic cache invalidation
   - Cache bypass for non-GET requests
   - TTL-based entry expiration

### Health Checks 💓

1. Active Monitoring
   - Background health check thread
   - Configurable check intervals
   - Failure threshold tracking
   - Automatic recovery detection

2. Health Status Management
   - Three-state backend status:
     - NOT_INITIATED
     - HEALTHY
     - UNREACHABLE
   - Configurable failure thresholds
   - Last healthy timestamp tracking

3. Debug Monitoring
   - Real-time backend status display
   - Health check statistics
   - Failure count tracking
   - Visual status dashboard in debug mode

## Debug Output

When running in debug mode, you'll see a real-time dashboard:

```

=== Backend Server Status ===
┌────────────────────────┬────────────-──┬───────────┬──────────────────┐
│ Backend URL            │ Status        │ Failures  │ Last Healthy     │
├────────────────────────┼─────────────-─┼───────────┼──────────────────┤
│ https://127.0.0.1:8000 │ HEALTHY       │     0     │     12:34:56     │
│ https://127.0.0.1:8001 │ UNREACHABLE   │     3     │     12:30:00     │
└────────────────────────┴─────────-─────┴───────────┴──────────────────┘
```

## How I would productionize this/Scale this

1. Security
   - Replace self-signed certificate with proper SSL certificate
   - Implement JWT token at-least

2. Performance
   - Adjust cache capacity based on memory availability
   - Experiment with different configuration of each parameters

3. Cache
   - Monitor cache hit rates and compression ratios

4. Scaling
   - Add more backend servers as needed
   - Adjust load balancing strategy for your use case
   - Consider implementing sticky sessions if needed
