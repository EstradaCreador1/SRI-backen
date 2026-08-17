from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import MetaTrader5 as mt5
import uvicorn
import time
import threading

app = FastAPI(
    title="SRI MT5 Bridge",
    version="1.0.0",
)

auto_trading_enabled = False
signals = []
mt5_lock = threading.RLock()

DEFAULT_SYMBOL = "XAUUSDm"


class OrderRequest(BaseModel):
    symbol: str
    type: str
    volume: float
    sl: float
    tp: float


class CloseRequest(BaseModel):
    ticket: int


class AutoTradingRequest(BaseModel):
    enabled: bool


class LoginRequest(BaseModel):
    login: int
    password: str
    server: str

class SignalRequest(BaseModel):
    id: str
    symbol: str
    type: str
    entry: float
    stop_loss: float
    take_profit: float
    confidence: float
    strategy: str
    created_at: str
    executed: bool = False


def initialize_mt5() -> None:
    with mt5_lock:
        if mt5.initialize(
            path=r"C:\Program Files\MetaTrader 5\terminal64.exe",
            timeout=60000,
        ):
            return

        raise HTTPException(
            status_code=500,
            detail=f"No fue posible iniciar MetaTrader5: {mt5.last_error()}",
        )
def shutdown_mt5() -> None:
    pass

def resolve_filling_mode(symbol: str) -> int:
    info = mt5.symbol_info(symbol)
    if info is None:
        return mt5.ORDER_FILLING_IOC

    filling_mode = getattr(info, "filling_mode", None)
    valid_modes = {
        mt5.ORDER_FILLING_FOK,
        mt5.ORDER_FILLING_IOC,
        mt5.ORDER_FILLING_RETURN,
    }

    if filling_mode in valid_modes:
        return filling_mode

    return mt5.ORDER_FILLING_IOC

def resolve_timeframe(timeframe: str):
    timeframes = {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "D1": mt5.TIMEFRAME_D1,
        "W1": mt5.TIMEFRAME_W1,
        "MN1": mt5.TIMEFRAME_MN1,
    }

    value = timeframes.get(timeframe.upper().strip())

    if value is None:
        raise HTTPException(
            status_code=400,
            detail=f"Timeframe no válido: {timeframe}",
        )

    return value


@app.get("/candles")
def get_candles(
    symbol: str = DEFAULT_SYMBOL,
    timeframe: str = "M1",
    count: int = 200,
):
    initialize_mt5()

    symbol = symbol.strip()

    if count < 1 or count > 2000:
        raise HTTPException(
            status_code=400,
            detail="El número de velas debe estar entre 1 y 2000.",
        )

    if not mt5.symbol_select(symbol, True):
        raise HTTPException(
            status_code=404,
            detail=f"No existe o no se pudo seleccionar el símbolo {symbol}.",
        )

    mt5_timeframe = resolve_timeframe(timeframe)

    # Solicita primero el historial requerido a MetaTrader 5.
    with mt5_lock:
        rates = mt5.copy_rates_from_pos(
            symbol,
            mt5_timeframe,
            0,
            count,
        )

    # Si MT5 todavía no ha sincronizado el historial, hacemos un segundo intento.
    if rates is None or len(rates) == 0:
        time.sleep(0.5)

        with mt5_lock:
            rates = mt5.copy_rates_from_pos(
                symbol,
                mt5_timeframe,
                0,
                count,
            )

    if rates is None or len(rates) == 0:
        raise HTTPException(
            status_code=500,
            detail=(
                f"No fue posible obtener velas de {symbol} "
                f"en {timeframe}: {mt5.last_error()}"
            ),
        )

    return [
        {
            "time": time.strftime(
                "%Y-%m-%dT%H:%M:%S",
                time.localtime(int(rate["time"])),
            ),
            "open": float(rate["open"]),
            "high": float(rate["high"]),
            "low": float(rate["low"]),
            "close": float(rate["close"]),
            "volume": float(rate["tick_volume"]),
        }
        for rate in rates
    ]
@app.get("/tick")
def get_tick(
    symbol: str = DEFAULT_SYMBOL,
):
    initialize_mt5()

    symbol = symbol.strip()

    if not mt5.symbol_select(symbol, True):
        raise HTTPException(
            status_code=404,
            detail=f"No existe o no se pudo seleccionar el símbolo {symbol}.",
        )

    tick = mt5.symbol_info_tick(symbol)

    if tick is None:
        raise HTTPException(
            status_code=500,
            detail=f"No fue posible obtener el tick: {mt5.last_error()}",
        )

    return {
        "symbol": symbol,
        "bid": float(tick.bid),
        "ask": float(tick.ask),
        "last": float(tick.last),
        "volume": float(tick.volume),
        "time": time.strftime(
            "%Y-%m-%dT%H:%M:%S",
            time.localtime(int(tick.time)),
        ),
    }
@app.get("/symbol_specification")
def get_symbol_specification(
    symbol: str = DEFAULT_SYMBOL,
):
    initialize_mt5()

    symbol = symbol.strip()

    if not mt5.symbol_select(symbol, True):
        raise HTTPException(
            status_code=404,
            detail=f"No existe o no se pudo seleccionar el símbolo {symbol}.",
        )

    info = mt5.symbol_info(symbol)

    if info is None:
        raise HTTPException(
            status_code=500,
            detail=f"No fue posible obtener la información de {symbol}.",
        )

    pip_size = 0.10 if "XAU" in symbol.upper() else float(info.point)

    return {
        "symbol": symbol,
        "digits": int(info.digits),
        "point": float(info.point),
        "pip_size": float(pip_size),
        "minimum_volume": float(info.volume_min),
        "maximum_volume": float(info.volume_max),
        "volume_step": float(info.volume_step),
        "tick_size": float(info.trade_tick_size),
        "tick_value": float(info.trade_tick_value),
        "minimum_stop_distance": float(
            info.trade_stops_level * info.point
        ),
    }
@app.get("/institutional_levels")
def get_institutional_levels(
    symbol: str = DEFAULT_SYMBOL,
):
    initialize_mt5()

    symbol = symbol.strip()

    if not mt5.symbol_select(symbol, True):
        raise HTTPException(
            status_code=404,
            detail=f"No existe o no se pudo seleccionar el símbolo {symbol}.",
        )

    daily_rates = mt5.copy_rates_from_pos(
        symbol,
        mt5.TIMEFRAME_D1,
        1,
        1,
    )

    weekly_rates = mt5.copy_rates_from_pos(
        symbol,
        mt5.TIMEFRAME_W1,
        1,
        1,
    )

    monthly_rates = mt5.copy_rates_from_pos(
        symbol,
        mt5.TIMEFRAME_MN1,
        1,
        1,
    )

    if daily_rates is None or len(daily_rates) == 0:
        raise HTTPException(
            status_code=500,
            detail=f"No fue posible obtener el periodo D1: {mt5.last_error()}",
        )

    if weekly_rates is None or len(weekly_rates) == 0:
        raise HTTPException(
            status_code=500,
            detail=f"No fue posible obtener el periodo W1: {mt5.last_error()}",
        )

    if monthly_rates is None or len(monthly_rates) == 0:
        raise HTTPException(
            status_code=500,
            detail=f"No fue posible obtener el periodo MN1: {mt5.last_error()}",
        )

    daily_high = float(daily_rates[0]["high"])
    daily_low = float(daily_rates[0]["low"])

    weekly_high = float(weekly_rates[0]["high"])
    weekly_low = float(weekly_rates[0]["low"])

    monthly_high = float(monthly_rates[0]["high"])
    monthly_low = float(monthly_rates[0]["low"])

    return {
        "symbol": symbol,
        "d1High": daily_high,
        "d1Mid": (daily_high + daily_low) / 2,
        "d1Low": daily_low,
        "w1High": weekly_high,
        "w1Mid": (weekly_high + weekly_low) / 2,
        "w1Low": weekly_low,
        "mn1High": monthly_high,
        "mn1Mid": (monthly_high + monthly_low) / 2,
        "mn1Low": monthly_low,
    }
      

@app.get("/")
def root():
    return {
        "application": "SRI Bridge",
        "status": "running",
    }


@app.get("/signals")
def get_signals():
    return signals


@app.post("/signals")
def add_signal(request: SignalRequest):
    signal = request.dict()
    signals.insert(0, signal)

    return {
        "success": True,
        "signal": signal,
    }


@app.get("/ping")
def ping():
    return {"status": "ok"}


@app.post("/auto_trading")
def set_auto_trading(request: AutoTradingRequest):
    global auto_trading_enabled
    auto_trading_enabled = request.enabled

    return {
        "success": True,
        "enabled": auto_trading_enabled,
    }

@app.post("/login")
def login_mt5(request: LoginRequest):
    initialize_mt5()

    authorized = mt5.login(
        login=request.login,
        password=request.password,
        server=request.server,
    )

    if not authorized:
        error = mt5.last_error()
        raise HTTPException(
            status_code=400,
            detail=f"No fue posible iniciar sesión: {error}",
        )

    return {
        "success": True,
        "account": request.login,
        "server": request.server,
    }


@app.get("/account")
def get_account():
    initialize_mt5()

    try:
        info = mt5.account_info()

        if info is None:
            raise HTTPException(
                status_code=500,
                detail="No fue posible obtener la información de la cuenta.",
            )

        return {
            "login": info.login,
            "name": info.name,
            "server": info.server,
            "balance": info.balance,
            "equity": info.equity,
            "margin": info.margin,
            "free_margin": info.margin_free,
            "profit": info.profit,
            "currency": info.currency,
            "connected": True,
        }
    finally:
        shutdown_mt5()


@app.get("/positions")
def get_positions():
    initialize_mt5()

    try:
        positions = mt5.positions_get()

        if positions is None:
            return []

        result = []

        for position in positions:
            result.append(
                {
                    "ticket": position.ticket,
                    "symbol": position.symbol,
                    "type": (
                        "BUY"
                        if position.type == mt5.POSITION_TYPE_BUY
                        else "SELL"
                    ),
                    "volume": position.volume,
                    "open_price": position.price_open,
                    "current_price": position.price_current,
                    "sl": position.sl,
                    "tp": position.tp,
                    "profit": position.profit,
                    "open_time": time.strftime(
                        "%Y-%m-%dT%H:%M:%S",
                        time.localtime(position.time),
                    ),
                }
            )

        return result
    finally:
        shutdown_mt5()


@app.get("/orders")
def get_orders():
    initialize_mt5()

    try:
        orders = mt5.orders_get()

        if orders is None:
            return []

        order_type_names = {
            mt5.ORDER_TYPE_BUY: "BUY",
            mt5.ORDER_TYPE_SELL: "SELL",
            mt5.ORDER_TYPE_BUY_LIMIT: "BUY_LIMIT",
            mt5.ORDER_TYPE_SELL_LIMIT: "SELL_LIMIT",
            mt5.ORDER_TYPE_BUY_STOP: "BUY_STOP",
            mt5.ORDER_TYPE_SELL_STOP: "SELL_STOP",
        }

        result = []

        for order in orders:
            result.append(
                {
                    "ticket": order.ticket,
                    "symbol": order.symbol,
                    "type": order_type_names.get(order.type, str(order.type)),
                    "volume": order.volume_initial,
                    "price": order.price_open,
                    "sl": order.sl,
                    "tp": order.tp,
                    "status": "PENDING",
                    "time": time.strftime(
                        "%Y-%m-%dT%H:%M:%S",
                        time.localtime(order.time_setup),
                    ),
                }
            )

        return result
    finally:
        shutdown_mt5()

@app.post("/order")
def place_order(request: OrderRequest):
    if not auto_trading_enabled:
        raise HTTPException(
            status_code=403,
            detail="El trading automático está desactivado.",
        )

    initialize_mt5()

    try:
        symbol = request.symbol.upper().strip()

        if not mt5.symbol_select(symbol, True):
            raise HTTPException(
                status_code=404,
                detail=f"No existe el símbolo {symbol}",
            )

        tick = mt5.symbol_info_tick(symbol)

        if tick is None:
            raise HTTPException(
                status_code=500,
                detail="No fue posible obtener el precio actual.",
            )

        request_type = request.type.upper().strip()

        if request_type == "BUY":
            order_type = mt5.ORDER_TYPE_BUY
            price = tick.ask
        elif request_type == "SELL":
            order_type = mt5.ORDER_TYPE_SELL
            price = tick.bid
        else:
            raise HTTPException(
                status_code=400,
                detail="Tipo de operación inválido.",
            )

        trade_request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": request.volume,
            "type": order_type,
            "price": price,
            "sl": request.sl,
            "tp": request.tp,
            "deviation": 20,
            "magic": 987654,
            "comment": "SRI",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": resolve_filling_mode(symbol),
        }

        result = mt5.order_send(trade_request)

        if result is None:
            raise HTTPException(
                status_code=500,
                detail="MetaTrader5 no respondió.",
            )

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            return {
                "success": False,
                "retcode": result.retcode,
                "comment": result.comment,
            }

        return {
            "success": True,
            "ticket": result.order,
            "deal": result.deal,
            "price": result.price,
            "volume": result.volume,
            "comment": result.comment,
        }
    finally:
        shutdown_mt5()


@app.post("/close")
def close_position(request: CloseRequest):
    initialize_mt5()

    try:
        positions = mt5.positions_get(ticket=request.ticket)

        if not positions:
            raise HTTPException(
                status_code=404,
                detail="Posición no encontrada.",
            )

        position = positions[0]
        tick = mt5.symbol_info_tick(position.symbol)

        if tick is None:
            raise HTTPException(
                status_code=500,
                detail="No fue posible obtener el precio actual.",
            )

        if position.type == mt5.POSITION_TYPE_BUY:
            order_type = mt5.ORDER_TYPE_SELL
            price = tick.bid
        else:
            order_type = mt5.ORDER_TYPE_BUY
            price = tick.ask

        close_request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": position.symbol,
            "position": position.ticket,
            "volume": position.volume,
            "type": order_type,
            "price": price,
            "deviation": 20,
            "magic": 987654,
            "comment": "SRI CLOSE",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": resolve_filling_mode(position.symbol),
        }

        result = mt5.order_send(close_request)

        if result is None:
            raise HTTPException(
                status_code=500,
                detail="MetaTrader5 no respondió.",
            )

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            return {
                "success": False,
                "retcode": result.retcode,
                "comment": result.comment,
            }

        return {
            "success": True,
            "ticket": result.order,
            "deal": result.deal,
            "price": result.price,
            "volume": result.volume,
            "comment": result.comment,
        }
    finally:
        shutdown_mt5()


@app.post("/close_all")
def close_all_positions():
    initialize_mt5()

    try:
        positions = mt5.positions_get()

        if not positions:
            return {
                "success": True,
                "closed": 0,
                "failed": 0,
            }

        closed = 0
        failed = 0

        for position in positions:
            tick = mt5.symbol_info_tick(position.symbol)

            if tick is None:
                failed += 1
                continue

            if position.type == mt5.POSITION_TYPE_BUY:
                order_type = mt5.ORDER_TYPE_SELL
                price = tick.bid
            else:
                order_type = mt5.ORDER_TYPE_BUY
                price = tick.ask

            close_request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": position.symbol,
                "position": position.ticket,
                "volume": position.volume,
                "type": order_type,
                "price": price,
                "deviation": 20,
                "magic": 987654,
                "comment": "SRI CLOSE ALL",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": resolve_filling_mode(position.symbol),
            }

            result = mt5.order_send(close_request)

            if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
                closed += 1
            else:
                failed += 1

        return {
            "success": failed == 0,
            "closed": closed,
            "failed": failed,
        }
    finally:
        shutdown_mt5()


@app.get("/status")
def status():
    initialize_mt5()

    try:
        terminal = mt5.terminal_info()
        version = mt5.version()

        if terminal is None or version is None:
            raise HTTPException(
                status_code=500,
                detail="No fue posible obtener el estado de MetaTrader 5.",
            )

        return {
            "application": "SRI MT5 Bridge",
            "running": True,
            "auto_trading_enabled": auto_trading_enabled,
            "terminal": {
                "connected": terminal.connected,
                "trade_allowed": terminal.trade_allowed,
                "tradeapi_disabled": terminal.tradeapi_disabled,
                "dlls_allowed": terminal.dlls_allowed,
                "path": terminal.path,
                "data_path": terminal.data_path,
                "community_account": terminal.community_account,
                "build": terminal.build,
            },
            "version": {
                "major": version[0],
                "build": version[1],
                "date": version[2],
            },
        }
    finally:
        shutdown_mt5()


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )
