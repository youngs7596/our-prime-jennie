
import os
import sys
import socket
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_import(module_name):
    try:
        __import__(module_name)
        logger.info(f"[OK] Import '{module_name}' successful.")
        return True
    except ImportError as e:
        logger.error(f"[FAIL] Import '{module_name}' failed: {e}")
        return False

def check_host_resolution(host):
    try:
        ip = socket.gethostbyname(host)
        logger.info(f"[OK] Resolved '{host}' to {ip}")
        return True
    except socket.gaierror as e:
        logger.error(f"[FAIL] Could not resolve '{host}': {e}")
        return False

def check_tcp_connection(host, port):
    try:
        sock = socket.create_connection((host, int(port)), timeout=3)
        sock.close()
        logger.info(f"[OK] TCP connection to {host}:{port} successful.")
        return True
    except Exception as e:
        logger.error(f"[FAIL] TCP connection to {host}:{port} failed: {e}")
        return False

def check_http_connection(url):
    try:
        import requests
        response = requests.get(f"{url}/health", timeout=3)
        if response.status_code == 200:
             logger.info(f"[OK] HTTP GET {url}/health successful.")
             return True
        else:
             logger.error(f"[FAIL] HTTP GET {url}/health returned {response.status_code}")
             return False
    except Exception as e:
        logger.error(f"[FAIL] HTTP connection to {url} failed: {e}")
        return False

def main():
    logger.info("--- Starting Airflow Environment & Connectivity Check ---")

    # 1. Check Imports
    check_import("dotenv")
    check_import("FinanceDataReader")
    check_import("redis")
    check_import("pymysql")

    # 2. Check Environment Variables & Connections
    
    # MariaDB
    db_host = os.environ.get("MARIADB_HOST", "mariadb")
    db_port = os.environ.get("MARIADB_PORT", "3306")
    logger.info(f"Checking MariaDB at {db_host}:{db_port}...")
    check_host_resolution(db_host)
    check_tcp_connection(db_host, db_port)

    # Redis
    redis_host = os.environ.get("REDIS_HOST", "redis")
    redis_port = os.environ.get("REDIS_PORT", "6379")
    logger.info(f"Checking Redis at {redis_host}:{redis_port}...")
    check_host_resolution(redis_host)
    check_tcp_connection(redis_host, redis_port)

    # KIS Gateway
    kis_gateway_url = os.environ.get("KIS_GATEWAY_URL", "http://host.docker.internal:8080")
    logger.info(f"Checking KIS Gateway at {kis_gateway_url}...")
    # Parse host/port from URL for TCP check
    try:
        from urllib.parse import urlparse
        parsed = urlparse(kis_gateway_url)
        host = parsed.hostname
        port = parsed.port or 80
        check_host_resolution(host)
        check_tcp_connection(host, port)
        check_http_connection(kis_gateway_url)
    except Exception as e:
        logger.error(f"[FAIL] Failed to parse/check KIS Gateway URL: {e}")

    # Ollama Gateway
    ollama_gateway_url = os.environ.get("OLLAMA_GATEWAY_URL", "http://host.docker.internal:11500")
    logger.info(f"Checking Ollama Gateway at {ollama_gateway_url}...")
    try:
        from urllib.parse import urlparse
        parsed = urlparse(ollama_gateway_url)
        host = parsed.hostname
        port = parsed.port or 80
        check_host_resolution(host)
        check_tcp_connection(host, port)
        check_http_connection(ollama_gateway_url)
    except Exception as e:
        logger.error(f"[FAIL] Failed to parse/check Ollama Gateway URL: {e}")

    logger.info("--- Check Complete ---")

if __name__ == "__main__":
    main()
