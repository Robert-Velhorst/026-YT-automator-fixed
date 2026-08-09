import logging
import os
import socket
import time

from app import create_app
from services.job_service import claim_next_job, heartbeat, process_job, recover_stale_jobs


app = create_app()


def run(once=False):
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    with app.app_context():
        while True:
            heartbeat(worker_id)
            recover_stale_jobs()
            job = claim_next_job(worker_id)
            if job:
                heartbeat(worker_id, job.id)
                process_job(job)
                heartbeat(worker_id)
            elif once:
                return
            else:
                time.sleep(app.config["WORKER_POLL_SECONDS"])


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    run(once=os.getenv("WORKER_ONCE") == "1")
