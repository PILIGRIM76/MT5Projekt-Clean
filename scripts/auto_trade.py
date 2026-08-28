"""
Автоматическая отправка ордера при открытии рынка.
Мониторит MT5, при открытии рынка отправляет ордер по предсказанию модели.
Запуск: python auto_trade.py
"""
import sys, os, time, joblib, logging
from datetime import datetime

sys.path.insert(0, r"F:\MT5Projekt-Clean")
sys.path.insert(0, r"F:\MT5Projekt-Clean\src")

import MetaTrader5 as mt5
import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(r"F:\Genesis-Test-Env\auto_trade.log", encoding="utf-8"),
    ]
)
logger = logging.getLogger(__name__)

SYMBOL = "EURUSD"
MODEL_PATH = r"F:\MT5Projekt-Clean\ai_models\EURUSD_model.joblib"
MAGIC = 777777
CHECK_INTERVAL = 60  # проверка каждую минуту
MAX_WAIT_HOURS = 48  # максимум ожидания

def connect_mt5():
    """Подключение к MT5."""
    for attempt in range(5):
        result = mt5.initialize(
            path=r"C:\Program Files\Alpari MT5\terminal64.exe",
            login=53057252,
            password="Zk*xS7Cc",
            server="Alpari-MT5-Demo",
            timeout=30000,
        )
        if result:
            acct = mt5.account_info()
            if acct:
                logger.info(f"MT5 подключен: #{acct.login} | Баланс: {acct.balance}")
                return True
        logger.warning(f"Попытка {attempt+1}/5: MT5 не подключился")
        time.sleep(5)
    return False

def is_market_open():
    """Проверяет открыт ли рынок."""
    try:
        tick = mt5.symbol_info_tick(SYMBOL)
        if tick is None:
            return False
        # Если есть актуальный тик — рынок открыт
        if tick.bid > 0 and tick.ask > 0:
            return True
        return False
    except Exception:
        return False

def generate_features(df):
    """Генерация признаков для модели."""
    df = df.copy()
    df['returns'] = df['close'].pct_change()
    df['log_returns'] = np.log(df['close'] / df['close'].shift(1))
    df['ma_5'] = df['close'].rolling(5).mean()
    df['ma_20'] = df['close'].rolling(20).mean()
    df['ma_50'] = df['close'].rolling(50).mean()
    df['volatility_20'] = df['returns'].rolling(20).std()
    df['volatility_50'] = df['returns'].rolling(50).std()
    df['tr'] = np.maximum(df['high'] - df['low'],
        np.maximum(np.abs(df['high'] - df['close'].shift(1)),
                   np.abs(df['low'] - df['close'].shift(1))))
    df['atr_14'] = df['tr'].rolling(14).mean()
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df['rsi_14'] = 100 - (100 / (1 + rs))
    ema12 = df['close'].ewm(span=12).mean()
    ema26 = df['close'].ewm(span=26).mean()
    df['macd'] = ema12 - ema26
    df['macd_signal'] = df['macd'].ewm(span=9).mean()
    df['macd_hist'] = df['macd'] - df['macd_signal']
    df['bb_middle'] = df['close'].rolling(20).mean()
    df['bb_std'] = df['close'].rolling(20).std()
    df['bb_upper'] = df['bb_middle'] + 2 * df['bb_std']
    df['bb_lower'] = df['bb_middle'] - 2 * df['bb_std']
    df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_middle']
    df['volume_ma'] = df['tick_volume'].rolling(20).mean()
    df['volume_ratio'] = df['tick_volume'] / df['volume_ma']
    return df.dropna()

def get_prediction(model, feature_cols):
    """Получение предсказания от модели."""
    rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_H1, 0, 100)
    if rates is None or len(rates) < 50:
        logger.error("Недостаточно данных для предсказания")
        return None, None, None

    df = pd.DataFrame(rates)
    df = generate_features(df)
    if len(df) < 1:
        return None, None, None

    last_features = df[feature_cols].iloc[-1:].values
    prediction = model.predict(last_features)[0]
    probability = model.predict_proba(last_features)[0]

    signal = "BUY" if prediction == 1 else "SELL"
    confidence = max(probability)

    return signal, confidence, df['close'].iloc[-1]

def place_order(signal, current_price, atr):
    """Отправка ордера."""
    if signal == "BUY":
        sl = current_price - 2 * atr
        tp = current_price + 3 * atr
        order_type = mt5.ORDER_TYPE_BUY
        tick = mt5.symbol_info_tick(SYMBOL)
        order_price = tick.ask
    else:
        sl = current_price + 2 * atr
        tp = current_price - 3 * atr
        order_type = mt5.ORDER_TYPE_SELL
        tick = mt5.symbol_info_tick(SYMBOL)
        order_price = tick.bid

    # Пробуем разные filling modes
    for filling in [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN]:
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": SYMBOL,
            "volume": 0.01,
            "type": order_type,
            "price": order_price,
            "sl": round(sl, 5),
            "tp": round(tp, 5),
            "deviation": 20,
            "magic": MAGIC,
            "comment": f"Genesis AI {signal} {int(proba*100)}%",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling,
        }
        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            return result
    return result

def main():
    logger.info("=" * 60)
    logger.info("Genesis Auto Trader — Ожидание открытия рынка")
    logger.info(f"Символ: {SYMBOL}")
    logger.info(f"Проверка каждые {CHECK_INTERVAL} сек")
    logger.info("=" * 60)

    # Подключение к MT5
    if not connect_mt5():
        logger.error("Не удалось подключиться к MT5")
        return

    # Загрузка модели
    model_data = joblib.load(MODEL_PATH)
    model = model_data['model']
    feature_cols = model_data['features']
    logger.info(f"Модель загружена: точность={model_data['accuracy']:.2%}")

    # Ожидание открытия рынка
    start_time = time.time()
    max_wait = MAX_WAIT_HOURS * 3600

    logger.info("Ожидание открытия рынка...")
    while time.time() - start_time < max_wait:
        if is_market_open():
            logger.info("✅ Рынок открыт!")
            break
        elapsed = int(time.time() - start_time)
        remaining = max_wait - elapsed
        hours = remaining // 3600
        mins = (remaining % 3600) // 60
        logger.info(f"Рынок закрыт. Ожидание: {hours}ч {mins}м")
        time.sleep(CHECK_INTERVAL)
    else:
        logger.error("Превышено максимальное время ожидания")
        mt5.shutdown()
        return

    # Рынок открыт — анализируем и торгуем
    logger.info("Анализ рынка и отправка ордера...")

    signal, confidence, price = get_prediction(model, feature_cols)
    if signal is None:
        logger.error("Не удалось получить предсказание")
        mt5.shutdown()
        return

    logger.info(f"Предсказание: {signal} | Уверенность: {confidence:.2%} | Цена: {price:.5f}")

    if confidence < 0.55:
        logger.warning(f"Уверенность {confidence:.2%} < 55% — сделка отменена")
        mt5.shutdown()
        return

    # Получаем ATR
    rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_H1, 0, 20)
    df = pd.DataFrame(rates)
    df['tr'] = np.maximum(df['high'] - df['low'],
        np.maximum(np.abs(df['high'] - df['close'].shift(1)),
                   np.abs(df['low'] - df['close'].shift(1))))
    atr = df['tr'].rolling(14).mean().iloc[-1]

    # Отправляем ордер
    result = place_order(signal, price, atr)

    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        logger.info(f"✅ ОРДЕР ИСПОЛНЕН!")
        logger.info(f"  Ticket: #{result.order}")
        logger.info(f"  Сигнал: {signal} ({confidence:.2%})")
        logger.info(f"  Цена: {result.price:.5f}")

        # Проверяем позицию
        time.sleep(2)
        positions = mt5.positions_get(symbol=SYMBOL)
        if positions:
            for p in positions:
                logger.info(f"  Позиция: #{p.ticket} | {p.volume} лот | SL={p.sl:.5f} | TP={p.tp:.5f}")
    else:
        error = result.comment if result else str(mt5.last_error())
        logger.error(f"❌ Ордер отклонён: {error}")

    # Обновляем баланс
    acct = mt5.account_info()
    logger.info(f"Баланс: {acct.balance} | Эквити: {acct.equity}")

    mt5.shutdown()
    logger.info("Auto Trader завершён")

if __name__ == "__main__":
    main()
