import os
import time
import random

from kubernetes import client, config


def main():
    config.load_incluster_config()

    namespace = os.getenv("CHAOS_NAMESPACE", "default")
    interval = int(os.getenv("CHAOS_INTERVAL", "60"))
    min_alive = int(os.getenv("CHAOS_MIN_ALIVE", "1"))

    v1 = client.CoreV1Api()

    print(f"Chaos Monkey started", flush=True)
    print(f"Namespace: {namespace}", flush=True)
    print(f"Interval: {interval}s", flush=True)
    print(f"Minimum alive: {min_alive}", flush=True)

    while True:
        pods = v1.list_namespaced_pod(
            namespace=namespace,
            label_selector="app=chaos-monkey-fastapi",
        )

        ready_pods = [
            pod
            for pod in pods.items
            if any(
                condition.type == "Ready"
                and condition.status == "True"
                for condition in (pod.status.conditions or [])
            )
        ]

        print(
            f"Found {len(ready_pods)} Ready FastAPI Pod(s)",
            flush=True,
        )

        if len(ready_pods) > min_alive:
            target_pod = random.choice(ready_pods)

            print(
                f"Deleting Pod: {target_pod.metadata.name}",
                flush=True,
            )

            v1.delete_namespaced_pod(
                name=target_pod.metadata.name,
                namespace=namespace,
            )

            print(
                f"Delete request sent for {target_pod.metadata.name}",
                flush=True,
            )

        else:
            print(
                f"Minimum alive limit reached. "
                f"Keeping {len(ready_pods)} Ready Pod(s).",
                flush=True,
            )

        print(
            f"Sleeping for {interval} seconds...",
            flush=True,
        )

        time.sleep(interval)


if __name__ == "__main__":
    main()