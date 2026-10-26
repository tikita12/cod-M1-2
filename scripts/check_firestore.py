"""Read-only Firestore connectivity check; never prints credentials."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.repositories.firestore import FirestoreRepository


def main():
    try:
        settings = Settings.from_env()
        repository = FirestoreRepository(settings)
        repository.probe()
    except Exception as exc:
        cause = exc
        while cause.__cause__ is not None:
            cause = cause.__cause__
        print("Firestore connection FAILED (" + type(cause).__name__ + ").")
        print("Check project/database, credentials and outbound network access.")
        return 1
    print("Firestore connection OK. No data was written.")
    repository.client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
