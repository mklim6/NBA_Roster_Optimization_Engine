from pathlib import Path

import duckdb


SOURCE_DATABASE = Path(
    r"C:\Users\klima\Python Projects\Projects"
    r"\NBA_Front_Office_Decision_Center"
    r"\database\nba_front_office.duckdb"
)

EXPECTED_TABLES = [
    "dim_team",
    "dim_player",
    "dim_season",
    "fact_team_season",
    "fact_player_season",
    "fact_lineup_season",
]


def main() -> None:
    """Inspect the existing NBA database without modifying it."""

    if not SOURCE_DATABASE.exists():
        raise FileNotFoundError(
            "The source NBA database could not be found at:\n"
            f"{SOURCE_DATABASE}"
        )

    print("SOURCE DATABASE")
    print(SOURCE_DATABASE)
    print()

    connection = duckdb.connect(
        database=str(SOURCE_DATABASE),
        read_only=True,
    )

    try:
        available_tables = (
            connection.execute("SHOW TABLES")
            .fetchdf()["name"]
            .tolist()
        )

        print("AVAILABLE TABLES")
        for table_name in available_tables:
            print(f"  - {table_name}")

        print()
        print("EXPECTED TABLE AUDIT")

        for table_name in EXPECTED_TABLES:
            if table_name not in available_tables:
                print(f"\n{table_name}: NOT FOUND")
                continue

            row_count = connection.execute(
                f'SELECT COUNT(*) FROM "{table_name}"'
            ).fetchone()[0]

            column_info = connection.execute(
                f'DESCRIBE "{table_name}"'
            ).fetchdf()

            column_names = column_info["column_name"].tolist()

            print(f"\n{table_name}")
            print(f"  Rows: {row_count:,}")
            print(f"  Columns: {len(column_names)}")
            print(f"  Column names: {', '.join(column_names)}")

    finally:
        connection.close()

    print()
    print("Audit completed successfully.")
    print("The source database was opened in read-only mode.")


if __name__ == "__main__":
    main()