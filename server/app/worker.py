"""Worker d'envoi : python -m app.worker  (boucle toutes les 15 s)."""
import time

from .db import SessionLocal
from .integrations.dispatcher import process_pending

if __name__ == "__main__":
    while True:
        with SessionLocal() as db:
            r = process_pending(db)
            if any(r.values()):
                print(r, flush=True)
        time.sleep(15)
