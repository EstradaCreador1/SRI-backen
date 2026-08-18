from fastapi import FastAPI
from pydantic import BaseModel

from cloud_database import get_connection, initialize_database


class SignalRequest(BaseModel):
    symbol: str
    type: str
    entry: float
    stop_loss: float
    take_profit: float


app = FastAPI(
    title="SRI Asistente Cloud Backend",
    version="1.0.0",
)


@app.on_event("startup")
def startup_event():
    initialize_database()


@app.get("/")
def root():
    return {
        "application": "SRI Asistente",
        "status": "online",
        "platform": "cloud",
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/signals")
def get_signals():
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                id,
                symbol,
                type,
                entry,
                stop_loss,
                take_profit,
                created_at
            FROM signals
            ORDER BY id DESC
            """
        ).fetchall()

    return [dict(row) for row in rows]


@app.post("/signals")
def add_signal(request: SignalRequest):
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO signals (
                symbol,
                type,
                entry,
                stop_loss,
                take_profit
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                request.symbol,
                request.type,
                request.entry,
                request.stop_loss,
                request.take_profit,
            ),
        )
        connection.commit()
        signal_id = cursor.lastrowid

        row = connection.execute(
            """
            SELECT
                id,
                symbol,
                type,
                entry,
                stop_loss,
                take_profit,
                created_at
            FROM signals
            WHERE id = ?
            """,
            (signal_id,),
        ).fetchone()

    return {
        "success": True,
        "signal": dict(row),
    }