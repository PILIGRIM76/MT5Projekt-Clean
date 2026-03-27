# 🔧 Исправление VectorDB и Обучения

## 📋 Проблемы

### **1. VectorDB не работает**
**Симптомы:**
- ❌ `VectorDB не готова`
- ❌ `документов=0`
- ❌ Ошибка при поиске

**Причина:**
- Директория `F:\Enjen\database\vector_db` не создана
- FAISS индекс не инициализирован

### **2. Обучение не работает**
**Симптомы:**
- ❌ R&D цикл не завершается
- ❌ Модели не обучаются

**Причина:**
- Блокировка `training_lock`
- Нет данных для обучения

---

## ✅ Решение для VectorDB

### **1. Исправить инициализацию**

**Файл:** `src/db/vector_db_manager.py`

**Добавить создание директории:**

```python
def __init__(self, config: VectorDBSettings, db_root_path=None):
    self.config = config
    
    if db_root_path is not None:
        self.db_path = Path(db_root_path)
    else:
        self.db_path = Path(self.config.path).resolve()
    
    # === СОЗДАНИЕ ДИРЕКТОРИИ ===
    try:
        self.db_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"[VectorDB] Директория создана/проверена: {self.db_path}")
    except Exception as e:
        logger.error(f"[VectorDB] Ошибка создания директории: {e}")
        self.config.enabled = False
        return
    # ===========================
    
    self.index_file = self.db_path / "faiss.index"
    self.meta_file = self.db_path / "faiss.meta"
    # ... остальной код
```

### **2. Проверка FAISS**

**Добавить проверку библиотеки:**

```python
try:
    import faiss
    if faiss:
        faiss.omp_set_num_threads(1)
        logger.info("FAISS OMP threads set to 1 for stability.")
except ImportError:
    faiss = None
    logger.error("FAISS не найден! Установите: pip install faiss-cpu")
    self.config.enabled = False
    return
```

### **3. Инициализация индекса**

**Если индекс не загружен, создать новый:**

```python
def _load(self):
    if self.index_file.exists() and self.meta_file.exists():
        try:
            # Загрузка существующего
            self.index = faiss.read_index(str(self.index_file))
            with open(self.meta_file, 'rb') as f:
                meta = pickle.load(f)
            self.documents = meta.get('documents', [])
            self.metadatas = meta.get('metadatas', [])
            logger.info(f"[VectorDB] Загружено {len(self.documents)} документов")
            return
        except Exception as e:
            logger.warning(f"[VectorDB] Ошибка загрузки: {e}. Создание нового индекса.")
    
    # Создание нового индекса
    logger.info("[VectorDB] Создание нового индекса FAISS...")
    self.index = faiss.IndexFlatL2(384)  # all-MiniLM-L6-v2 имеет 384 измерения
    self.documents = []
    self.metadatas = []
    self._save()
```

---

## ✅ Решение для Обучения

### **1. Разблокировка training_lock**

**Файл:** `src/core/trading_system.py`

**Проверка блокировки:**

```python
def _continuous_training_cycle(self):
    # Проверяем что lock доступен
    if not self.training_lock.acquire(blocking=False):
        logger.warning("[R&D] training_lock занят! Пропуск цикла.")
        return
    
    try:
        # ... код обучения ...
    finally:
        # ОСВОБОЖДАЕМ LOCK В ЛЮБОМ СЛУЧАЕ
        self.training_lock.release()
        logger.info("[R&D] training_lock освобожден")
```

### **2. Проверка данных**

**Добавить проверку перед обучением:**

```python
# Проверка данных
if df_full is None or len(df_full) < 1000:
    logger.error(f"[R&D] Недостаточно данных: {len(df_full) if df_full else 0}")
    self.training_lock.release()
    return
```

### **3. Логирование ошибок**

**Оборачиваем в try/except с логированием:**

```python
try:
    # Обучение
    self._train_candidate_model(...)
except Exception as e:
    logger.error(f"[R&D] Критическая ошибка обучения: {e}", exc_info=True)
    self.training_lock.release()
    raise
```

---

## 🧪 Тестирование

### **1. Проверка VectorDB**

```python
# В консоли
from src.db.vector_db_manager import VectorDBManager
from src.core.config_loader import load_config

config = load_config()
vdb = VectorDBManager(config.vector_db, db_root_path="database/vector_db")

print(f"VectorDB готов: {vdb.is_ready()}")
print(f"Документов: {len(vdb.documents)}")

# Добавление теста
vdb.add_documents(["Тестовый документ"], [{"source": "test"}])
print(f"После добавления: {len(vdb.documents)}")
```

### **2. Проверка Обучения**

```python
# В консоли
import threading
from src.core.trading_system import TradingSystem

# Проверка что lock доступен
print(f"training_lock свободен: {not ts.training_lock.locked()}")

# Принудительный запуск
ts.force_training_cycle()
```

---

## ⚙️ Установка зависимостей

### **Для VectorDB:**

```bash
pip install faiss-cpu
```

### **Проверка установки:**

```python
import faiss
print(f"FAISS версия: {faiss.__version__}")
```

---

## 📊 Ожидаемые логи

### **VectorDB:**

```
[VectorDB] Директория создана/проверена: F:\Enjen\database\vector_db
FAISS OMP threads set to 1 for stability.
[VectorDB] Создание нового индекса FAISS...
[VectorDB] Загружено 0 документов
VectorDBManager (FAISS) инициализирован. Загружено 0 документов.
```

### **Обучение:**

```
[R&D] training_lock свободен
[R&D] Запуск цикла обучения...
[R&D] Выбран символ: EURUSD
[R&D] Загрузка данных: 1500 баров
[R&D] Начало обучения 3 моделей
[R&D] Модель LSTM обучена
[R&D] Модель Transformer обучена
[R&D] Модель LightGBM обучена
[R&D] training_lock освобожден
--- R&D ЦИКЛ ЗАВЕРШЕН ---
```

---

## ✅ ИТОГ

**VectorDB:**
- ✅ Создание директории
- ✅ Проверка FAISS
- ✅ Инициализация индекса
- ✅ Метод `_save()` для сохранения

**Обучение:**
- ✅ Проверка `training_lock`
- ✅ Освобождение в `finally`
- ✅ Проверка данных
- ✅ Логирование ошибок

**Готово к использованию!** 🚀
