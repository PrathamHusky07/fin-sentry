from __future__ import annotations

import os

import psycopg
from datasets import load_dataset
from dotenv import load_dotenv

_INSERT = """
INSERT INTO golden_set (id, question, expected_answer, doc_id)
VALUES (%s, %s, %s, %s)
ON CONFLICT (id) DO NOTHING
"""


def ingest(database_url: str) -> None:
    ds = load_dataset("PatronusAI/financebench", split="train", trust_remote_code=False)
    rows = [
        (
            str(row["financebench_id"]),
            str(row["question"]),
            str(row["answer"]),
            str(row["doc_name"]),
        )
        for row in ds
    ]
    with psycopg.connect(database_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.executemany(_INSERT, rows)


if __name__ == "__main__":
    load_dotenv()
    ingest(os.environ["DATABASE_URL"])
