"""
Dify API Connection Diagnostic Script

This script tests the connection to Dify API and provides detailed diagnostics.
Run this to troubleshoot connection issues before running the full data collection.
"""

import os
import sys
import time
import requests
import json
import http.client
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ANSI color codes for terminal output
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def print_header(text):
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*60}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{text.center(60)}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'='*60}{Colors.ENDC}\n")

def print_success(text):
    print(f"{Colors.OKGREEN}[+] {text}{Colors.ENDC}")

def print_error(text):
    print(f"{Colors.FAIL}[-] {text}{Colors.ENDC}")

def print_warning(text):
    print(f"{Colors.WARNING}[!] {text}{Colors.ENDC}")

def print_info(text):
    print(f"{Colors.OKCYAN}[*] {text}{Colors.ENDC}")

def test_config():
    """Test if configuration is loaded correctly."""
    print_header("STEP 1: Configuration Check")

    api_url = os.getenv('DIFY_API_URL')
    api_key = os.getenv('DIFY_API_KEY')
    user_id = os.getenv('DIFY_USER_ID', 'rag-evaluator')

    if not api_url:
        print_error("DIFY_API_URL not found in environment variables")
        print_info("Set it in .env file or environment")
        return None
    else:
        print_success(f"DIFY_API_URL: {api_url}")

    if not api_key:
        print_error("DIFY_API_KEY not found in environment variables")
        print_info("Set it in .env file or environment")
        return None
    else:
        masked_key = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else "***"
        print_success(f"DIFY_API_KEY: {masked_key}")

    print_success(f"DIFY_USER_ID: {user_id}")

    return api_url, api_key, user_id

def test_dns_resolution(api_url):
    """Test DNS resolution of the Dify host."""
    print_header("STEP 2: DNS Resolution")

    from urllib.parse import urlparse
    parsed = urlparse(api_url)
    host = parsed.netloc or parsed.path.split('/')[0]

    print_info(f"Testing DNS resolution for: {host}")

    try:
        import socket
        ip_address = socket.gethostbyname(host)
        print_success(f"DNS resolved: {host} -> {ip_address}")
        return True
    except socket.gaierror as e:
        print_error(f"DNS resolution failed: {e}")
        print_info("Check if the URL is correct and DNS is working")
        return False

def test_tcp_connection(api_url):
    """Test TCP connection to the Dify host."""
    print_header("STEP 3: TCP Connection")

    from urllib.parse import urlparse
    parsed = urlparse(api_url)
    host = parsed.netloc or parsed.path.split('/')[0]
    port = 443 if parsed.scheme == 'https' else 80

    print_info(f"Testing TCP connection to: {host}:{port}")

    try:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        result = sock.connect_ex((host, port))
        sock.close()

        if result == 0:
            print_success(f"TCP connection successful to {host}:{port}")
            return True
        else:
            print_error(f"TCP connection failed to {host}:{port} (error code: {result})")
            return False
    except Exception as e:
        print_error(f"TCP connection error: {e}")
        return False

def test_blocking_request(api_url, api_key, user_id):
    """Test a simple blocking request (non-streaming)."""
    print_header("STEP 4: Blocking Request Test")

    print_info("Sending a simple blocking request to Dify API...")
    print_info("This tests basic connectivity without streaming complexity")

    payload = {
        "query": "Hello, this is a test message.",
        "inputs": {},
        "response_mode": "blocking",
        "user": user_id
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        print_info(f"POST {api_url}")
        print_info(f"Headers: {json.dumps({k: v[:20] + '...' if k == 'Authorization' else v for k, v in headers.items()}, indent=2)}")

        response = requests.post(
            api_url,
            json=payload,
            headers=headers,
            timeout=60
        )

        print_success(f"Response Status Code: {response.status_code}")

        if response.status_code == 200:
            print_success("Request successful!")
            data = response.json()
            print_info(f"Response event: {data.get('event')}")
            print_info(f"Conversation ID: {data.get('conversation_id')}")
            answer = data.get('answer', '')[:100]
            print_info(f"Answer preview: {answer}...")
            return True
        else:
            print_error(f"HTTP Error: {response.status_code}")
            print_info(f"Response: {response.text[:500]}")
            return False

    except requests.exceptions.Timeout:
        print_error("Request timed out after 60 seconds")
        return False
    except requests.exceptions.SSLError as e:
        print_error(f"SSL Error: {e}")
        print_info("There may be an issue with the SSL certificate")
        return False
    except requests.exceptions.ConnectionError as e:
        print_error(f"Connection Error: {e}")
        print_info("Could not establish connection to the server")
        return False
    except Exception as e:
        print_error(f"Unexpected Error: {type(e).__name__}: {e}")
        return False

def test_streaming_request(api_url, api_key, user_id):
    """Test a streaming request to Dify API."""
    print_header("STEP 5: Streaming Request Test")

    print_info("Sending a streaming request to Dify API...")
    print_warning("This tests the full SSE streaming functionality")

    payload = {
        "query": "Hello, this is a streaming test.",
        "inputs": {},
        "response_mode": "streaming",
        "user": user_id
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        print_info(f"POST {api_url} (streaming)")

        response = requests.post(
            api_url,
            json=payload,
            headers=headers,
            stream=True,
            timeout=(30, 60)  # (connect, read) timeout
        )

        print_success(f"Response Status Code: {response.status_code}")

        if response.status_code == 200:
            print_success("Stream opened successfully!")
            print_info("Reading stream chunks...")

            line_count = 0
            full_answer = ""

            for line in response.iter_lines():
                if not line:
                    continue

                line = line.decode("utf-8").strip()
                if not line.startswith("data: "):
                    continue

                data_str = line[6:]
                if data_str == "[DONE]":
                    print_info("Stream received [DONE] marker")
                    break

                try:
                    data = json.loads(data_str)
                    event = data.get("event")

                    if event == "message":
                        answer = data.get("answer", "")
                        full_answer += answer
                        line_count += 1
                        if line_count <= 3:  # Show first 3 chunks
                            print_info(f"Chunk: {answer[:50]}...")

                    elif event == "message_end":
                        print_success("Stream completed normally")
                        break

                    elif event == "error":
                        error_msg = data.get("message", "Unknown error")
                        print_error(f"API returned error: {error_msg}")
                        return False

                except json.JSONDecodeError as e:
                    print_warning(f"Failed to parse JSON: {data_str[:50]}...")

            print_success(f"Total chunks received: {line_count}")
            print_info(f"Full answer length: {len(full_answer)} characters")
            print_success("Streaming test PASSED!")
            return True

        else:
            print_error(f"HTTP Error: {response.status_code}")
            print_info(f"Response: {response.text[:500]}")
            return False

    except requests.exceptions.Timeout:
        print_error("Request timed out")
        return False
    except http.client.RemoteDisconnected as e:
        print_error(f"RemoteDisconnected: {e}")
        print_warning("The server closed the connection unexpectedly")
        print_info("This could be:")
        print_info("  - Server overloaded or restarting")
        print_info("  - Network proxy/firewall interference")
        print_info("  - Dify API version incompatibility")
        print_info("  - SSL/TLS handshake failure")
        return False
    except requests.exceptions.ConnectionError as e:
        error_str = str(e)
        print_error(f"Connection Error: {error_str}")

        if "RemoteDisconnected" in error_str:
            print_warning("RemoteDisconnected detected in connection error")
            print_info("The server closed the connection without a response")

        if "SSL" in error_str or "certificate" in error_str.lower():
            print_warning("SSL/TLS issue detected")

        if "proxy" in error_str.lower():
            print_warning("Proxy may be interfering")

        return False
    except Exception as e:
        print_error(f"Unexpected Error: {type(e).__name__}: {e}")
        import traceback
        print_info(f"Traceback:\n{traceback.format_exc()}")
        return False

def test_with_alternative_settings(api_url, api_key, user_id):
    """Test with alternative HTTP settings that might work better."""
    print_header("STEP 6: Alternative Settings Test")

    print_info("Testing with alternative HTTP configuration...")

    # Test 1: Without session reuse
    print_info("Test 6.1: Direct request (no session)")

    payload = {
        "query": "Test message - direct request",
        "inputs": {},
        "response_mode": "blocking",
        "user": user_id
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        response = requests.post(
            api_url,
            json=payload,
            headers=headers,
            timeout=30
        )
        if response.status_code == 200:
            print_success("Direct blocking request worked!")
            return True
        else:
            print_error(f"Got status {response.status_code}")
    except Exception as e:
        print_error(f"Direct request failed: {e}")

    # Test 2: With verify=False (not recommended but useful for debugging)
    print_warning("Test 6.2: With SSL verification disabled (for debugging only)")

    try:
        response = requests.post(
            api_url,
            json=payload,
            headers=headers,
            timeout=30,
            verify=False
        )
        if response.status_code == 200:
            print_warning("Request worked with SSL verification disabled!")
            print_warning("This indicates an SSL certificate validation issue")
            print_info("Consider:")
            print_info("  - Checking if the server has a valid certificate")
            print_info("  - Updating your certificates")
            print_info("  - Adding the certificate to your trust store")
            return True
    except Exception as e:
        print_error(f"Still failed with SSL verification disabled: {e}")

    return False

def test_concurrency_load(api_url, api_key, user_id):
    """Test how many concurrent requests the Dify server can handle."""
    print_header("STEP 7: Concurrency Load Test")

    import concurrent.futures

    test_question = "سلام، این یک پیام آزمایشی است."

    payload = {
        "query": test_question,
        "inputs": {},
        "response_mode": "blocking",
        "user": user_id
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    def send_one_request(worker_id):
        """Send a single blocking request and return (success, duration)."""
        start = time.time()
        try:
            resp = requests.post(
                api_url, json=payload, headers=headers, timeout=300
            )
            duration = time.time() - start
            return resp.status_code == 200, duration, resp.status_code
        except Exception as e:
            duration = time.time() - start
            return False, duration, str(e)

    concurrency_levels = [1, 2, 3, 5]
    recommended = 1

    for level in concurrency_levels:
        print_info(f"Testing {level} concurrent request(s)...")

        with concurrent.futures.ThreadPoolExecutor(max_workers=level) as pool:
            futures = [pool.submit(send_one_request, i) for i in range(level)]
            results = [f.result() for f in futures]

        successes = sum(1 for ok, _, _ in results if ok)
        failures = level - successes
        durations = [d for _, d, _ in results]
        avg_duration = sum(durations) / len(durations)

        status_codes = [s for _, _, s in results if not isinstance(s, str)]
        errors = [s for _, _, s in results if isinstance(s, str)]

        if failures == 0:
            print_success(
                f"  {level} concurrent: {successes}/{level} OK, "
                f"avg {avg_duration:.1f}s"
            )
            recommended = level
        else:
            print_warning(
                f"  {level} concurrent: {successes}/{level} OK, "
                f"{failures} failed, avg {avg_duration:.1f}s"
            )
            failed_codes = [s for ok, _, s in results if not ok]
            for code in failed_codes:
                print_error(f"    Failed with: {code}")
            # Stop testing higher levels after failures
            break

    print()
    print_success(f"Recommended max_workers: {recommended}")
    if recommended <= 2:
        print_warning(
            "Your Dify server handles limited concurrency. "
            "Use COLLECT_MAX_WORKERS=1 or 2 in .env"
        )
    return recommended


def main():
    print_header("Dify API Connection Diagnostic Tool")

    # Step 1: Check config
    config = test_config()
    if not config:
        print_error("Configuration incomplete. Please set up your .env file.")
        print_info("Required variables:")
        print_info("  - DIFY_API_URL")
        print_info("  - DIFY_API_KEY")
        print_info("  - DIFY_USER_ID (optional)")
        return

    api_url, api_key, user_id = config

    # Step 2: DNS
    if not test_dns_resolution(api_url):
        print_error("DNS resolution failed. Cannot proceed.")

    # Step 3: TCP
    if not test_tcp_connection(api_url):
        print_error("TCP connection failed. Cannot proceed.")
        print_info("This usually indicates:")
        print_info("  - The server is down")
        print_info("  - A firewall is blocking the connection")
        print_info("  - The URL is incorrect")

    # Step 4: Blocking request
    blocking_ok = test_blocking_request(api_url, api_key, user_id)

    # Step 5: Streaming request
    streaming_ok = test_streaming_request(api_url, api_key, user_id)

    # Step 6: Alternative settings if streaming failed
    if not streaming_ok:
        test_with_alternative_settings(api_url, api_key, user_id)

    # Step 7: Concurrency load test (only if basic requests work)
    recommended_workers = None
    if blocking_ok:
        recommended_workers = test_concurrency_load(api_url, api_key, user_id)

    # Summary
    print_header("SUMMARY")

    if blocking_ok and streaming_ok:
        print_success("All tests passed! Your Dify API connection is working.")
        print_info("You can proceed with data collection.")
    elif blocking_ok:
        print_warning("Blocking requests work, but streaming has issues.")
        print_info("The DifyClient may need to use blocking mode instead.")
        print_info("Consider setting response_mode to 'blocking' in the code.")
    else:
        print_error("Connection tests failed.")
        print_info("Please check:")
        print_info("  1. Your DIFY_API_URL is correct")
        print_info("  2. Your DIFY_API_KEY is valid")
        print_info("  3. The Dify server is accessible from your network")
        print_info("  4. No firewall/proxy is blocking the connection")
        print_info("  5. Your Dify instance is running and healthy")

    if recommended_workers is not None:
        print()
        print_info(f"Recommended COLLECT_MAX_WORKERS={recommended_workers}")
        print_info(f"Set in .env: COLLECT_MAX_WORKERS={recommended_workers}")

    print()

if __name__ == "__main__":
    main()
