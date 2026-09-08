from __future__ import annotations

import hashlib
import os

import psycopg
from datasets import load_dataset
from dotenv import load_dotenv

_INSERT = """
INSERT INTO hallucination_bench (id, question, context, response, is_hallucination)
VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (id) DO NOTHING
"""


def ingest(database_url: str) -> None:
    ds = load_dataset(
        "Cleanlab/FinQA-hallucination-detection", split="train", trust_remote_code=False
    )
    rows = [
        (
            hashlib.sha256(
                (str(row["query"]) + str(row["llm_response"])).encode()
            ).hexdigest()[:16],
            str(row["query"]),
            str(row["context"]),
            str(row["llm_response"]),
            row["is_correct"] == 0,
        )
        for row in ds
    ]
    with psycopg.connect(database_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.executemany(_INSERT, rows)


if __name__ == "__main__":
    load_dotenv()
    ingest(os.environ["DATABASE_URL"])
