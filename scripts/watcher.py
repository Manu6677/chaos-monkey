import time
import requests

URL = "http://localhost:8000/"

total_requests = 0
successful_requests = 0
failed_requests = 0

while True:
    total_requests += 100

    try:
        response = requests.get(URL, timeout=2)

        if response.status_code == 200:
            successful_requests += 1
        else:
            failed_requests += 1

    except requests.RequestException:
        failed_requests += 1

    success_rate = (
        successful_requests / total_requests
    ) * 100

    print(
        f"Total: {total_requests} | "
        f"Success: {successful_requests} | "
        f"Failed: {failed_requests} | "
        f"Success Rate: {success_rate:.2f}%"
    )

    time.sleep(0.5)