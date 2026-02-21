"""Manual utility script to initialize DB and seed sample CSV data."""

from backend.database import bootstrap_database


if __name__ == "__main__":
    bootstrap_database(load_seed_data=True)
    print("Database initialized and sample data loaded.")
