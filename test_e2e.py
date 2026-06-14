import urllib.request
import time
import sys
import json
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

def poll_endpoint(url, name, max_retries=60):
    for i in range(max_retries):
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=2) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode())
                    logging.info(f"{name} is UP! Response: {data}")
                    return True
        except Exception as e:
            pass
        logging.info(f"Waiting for {name} to start... (Attempt {i+1}/{max_retries})")
        time.sleep(5)
    
    logging.error(f"{name} failed to start or load the bridge add-in after {max_retries*5} seconds.")
    return False

if __name__ == '__main__':
    logging.info("Starting E2E Bridge Polling...")
    
    revit_up = poll_endpoint('http://127.0.0.1:3000/health', 'Revit Bridge (Port 3000)')
    navis_up = poll_endpoint('http://127.0.0.1:3002/health', 'Navisworks Bridge (Port 3002)')
    
    if revit_up and navis_up:
        logging.info("SUCCESS: Both Revit and Navisworks bridges are actively running and responding to the MCP Hub.")
        sys.exit(0)
    else:
        logging.error("FAILURE: One or both bridges did not come online.")
        sys.exit(1)
