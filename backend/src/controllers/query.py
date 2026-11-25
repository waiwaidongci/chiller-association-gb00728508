from fastapi import HTTPException
from sqlalchemy import func, select

from src.models.database import engine, fetch_one
from src.models.tables import audit, datasets, deliveries, runs, schedules, unit_rounds


def list_rows(table, fields=None, limit=100):
    statement = select(*fields) if fields else select(table)
    with engine.connect() as connection:
        return [dict(row) for row in connection.execute(statement.order_by(table.c.id.desc()).limit(limit)).mappings()]


def revisions():
    columns = [field for field in datasets.c if field.name != 'records']
    return list_rows(datasets, columns)


def require_row(table, key, label):
    with engine.connect() as connection:
        row = fetch_one(connection, table, key)
    if row is None:
        raise HTTPException(404, label + '不存在。')
    return dict(row)


def jobs():
    return list_rows(runs, [field for field in runs.c if field.name != 'result'])


def sensitivity_progress(key, dataset_id):
    with engine.connect() as connection:
        done = connection.scalar(select(func.count()).select_from(unit_rounds).where(unit_rounds.c.run_id == key))
        dataset = fetch_one(connection, datasets, dataset_id)
    total = len({row['asset_id'] for row in dataset['records']}) if dataset else 0
    return {'done': done, 'total': total}


def delivery_status():
    return {'schedules': list_rows(schedules), 'deliveries': list_rows(deliveries)}


def recent_activity():
    return list_rows(audit, limit=20)
