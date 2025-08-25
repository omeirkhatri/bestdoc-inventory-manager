import argparse

from sqlalchemy import create_engine, MetaData, select
from sqlalchemy.sql import util as sqlutil


def copy_all(src_url: str, dst_url: str) -> None:
    """Copy all tables from the source Postgres DB to the destination Postgres DB."""
    src_engine = create_engine(src_url)
    dst_engine = create_engine(dst_url)

    # Reflect metadata from both databases
    src_metadata = MetaData()
    src_metadata.reflect(bind=src_engine)
    dst_metadata = MetaData()
    dst_metadata.reflect(bind=dst_engine)

    # Determine insertion order based on foreign key dependencies
    ordered_tables = sqlutil.sort_tables(list(src_metadata.tables.values()))

    total_rows = 0
    with src_engine.connect() as src_conn, dst_engine.begin() as dst_conn:
        for src_table in ordered_tables:
            table_name = src_table.name
            if table_name not in dst_metadata.tables:
                print(f"[WARN] Table '{table_name}' does not exist in destination database. Skipping.")
                continue
            dst_table = dst_metadata.tables[table_name]
            rows = [dict(row) for row in src_conn.execute(select(src_table)).fetchall()]
            if not rows:
                print(f"[OK] {table_name}: 0 rows")
                continue
            dst_conn.execute(dst_table.insert(), rows)
            print(f"[OK] {table_name}: inserted {len(rows)} rows")
            total_rows += len(rows)
    print(f"Migration complete. Total rows inserted: {total_rows}")


def main():
    parser = argparse.ArgumentParser(description="Copy all tables from one Postgres database to another.")
    parser.add_argument("--src", "--source", dest="src", required=True, help="Source Postgres connection URL")
    parser.add_argument("--dst", "--destination", dest="dst", required=True, help="Destination Postgres connection URL")
    args = parser.parse_args()
    copy_all(args.src, args.dst)


if __name__ == "__main__":
    main()
