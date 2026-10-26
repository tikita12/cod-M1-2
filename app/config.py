"""Server-only configuration; credentials never enter API responses."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    firebase_project_id: str = ""
    google_application_credentials: str = ""
    firestore_database: str = "(default)"
    firestore_emulator_host: str = ""
    admin_api_key: str = ""
    openai_api_key: str = ""
    openai_model: str = "gpt-5-mini"
    allowed_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")
    analysis_start_year: int = 2015
    analysis_end_year: int = 2024
    analysis_min_years: int = 5
    summary_max_records: int = 50000

    @classmethod
    def from_env(cls):
        load_dotenv(ROOT / ".env", override=False)
        # The SDK treats an empty emulator variable as an endpoint, not as disabled.
        if os.environ.get("FIRESTORE_EMULATOR_HOST") == "":
            os.environ.pop("FIRESTORE_EMULATOR_HOST", None)
        return cls(
            firebase_project_id=os.getenv("FIREBASE_PROJECT_ID", os.getenv("GOOGLE_CLOUD_PROJECT", "")),
            google_application_credentials=os.getenv("GOOGLE_APPLICATION_CREDENTIALS", ""),
            firestore_database=os.getenv("FIRESTORE_DATABASE", "(default)"),
            firestore_emulator_host=os.getenv("FIRESTORE_EMULATOR_HOST", ""),
            admin_api_key=os.getenv("ADMIN_API_KEY", ""),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
            allowed_origins=tuple(x.strip() for x in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if x.strip()),
            analysis_start_year=int(os.getenv("ANALYSIS_START_YEAR", "2015")),
            analysis_end_year=int(os.getenv("ANALYSIS_END_YEAR", "2024")),
            analysis_min_years=int(os.getenv("ANALYSIS_MIN_YEARS", "5")),
            summary_max_records=int(os.getenv("SUMMARY_MAX_RECORDS", "50000")),
        )
