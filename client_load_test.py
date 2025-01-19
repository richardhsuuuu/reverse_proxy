import requests
import time
import argparse
from concurrent.futures import ThreadPoolExecutor

def make_request():
    """Make a single request to the server"""
    url = "https://localhost:8443/test"
    headers = {
        "X-API-Key": "test-api-key-123",
        "Content-Type": "application/json"
    }
    data = {"hello": "world"}
    
    try:
        response = requests.post(url, headers=headers, json=data, verify=False)
        print(f"Request completed with status code: {response.status_code}")
        print(f"Response body: {response.text}")
        return response.status_code
    except Exception as e:
        print(f"Request failed: {e}")
        return None

def load_test(requests_per_second, duration=60):
    """Run load test with specified RPS for given duration"""
    delay = 1.0 / requests_per_second
    end_time = time.time() + duration
    successful_requests = 0
    failed_requests = 0
    
    print(f"Starting load test with {requests_per_second} RPS for {duration} seconds")
    
    with ThreadPoolExecutor(max_workers=requests_per_second) as executor:
        while time.time() < end_time:
            start = time.time()
            
            # Submit request to thread pool
            future = executor.submit(make_request)
            status_code = future.result()
            
            if status_code == 200:
                successful_requests += 1
                print(f"Request successful - Total successful: {successful_requests}")
            else:
                failed_requests += 1
                print(f"Request failed - Total failed: {failed_requests}")
                
            # Sleep for remaining time to maintain RPS
            elapsed = time.time() - start
            if elapsed < delay:
                time.sleep(delay - elapsed)
    
    print("\nLoad test complete!")
    print(f"Successful requests: {successful_requests}")
    print(f"Failed requests: {failed_requests}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Load test the reverse proxy server')
    parser.add_argument('--rps', type=int, default=10, help='Requests per second')
    parser.add_argument('--duration', type=int, default=60, help='Test duration in seconds')
    
    args = parser.parse_args()
    load_test(args.rps, args.duration)