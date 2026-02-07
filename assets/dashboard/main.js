document.addEventListener('DOMContentLoaded', () => {
    console.log("Dashboard loaded. Initializing...");

    // ============================================================
    // 1. ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ
    // ============================================================
    let pnlChart = null;
    let orchestratorChart = null;
    let driftChart = null; // <-- WEB.3: Инициализация
    let driftData = []; // <-- WEB.3: Инициализация

    const elements = {
        connectionStatus: document.getElementById('connection-status'),
        systemStatus: document.getElementById('system-status'),
        systemMode: document.getElementById('system-mode'),
        systemUptime: document.getElementById('system-uptime'),
        systemBalance: document.getElementById('system-balance'),
        systemEquity: document.getElementById('system-equity'),
        systemDrawdown: document.getElementById('system-drawdown'),
        positionsCount: document.getElementById('positions-count'),
        positionsTableBody: document.querySelector('#positions-table tbody'),
        logFeed: document.getElementById('log-feed'),
        marketRegime: document.getElementById('market-regime'),
        startBtn: document.getElementById('start-btn'),
        stopBtn: document.getElementById('stop-btn'),
        closeAllBtn: document.getElementById('close-all-btn'),
        closeAllEmergencyBtn: document.getElementById('close-all-emergency-btn'),
        observerModeSwitch: document.getElementById('observer-mode-switch'),
    };

    // ============================================================
    // 2. ФУНКЦИИ ОТРИСОВКИ (ОБЪЯВЛЕНЫ ПЕРВЫМИ)
    // ============================================================

    // --- WEB.3: Обновление графика дрейфа ---
    function updateDriftChart(payload) {
        if (!driftChart || !payload) return;

        // Добавляем новую точку
        driftData.push({
            x: new Date(payload.timestamp * 1000), // Unix timestamp to Date
            y: payload.error,
            isDrift: payload.is_drift,
            symbol: payload.symbol
        });

        // Ограничиваем количество точек (например, 100 последних)
        if (driftData.length > 100) {
            driftData.shift();
        }

        // Разделяем данные на две серии для разных цветов/символов
        const normalPoints = driftData.filter(p => !p.isDrift);
        const driftAlerts = driftData.filter(p => p.isDrift);

        driftChart.data.datasets[0].data = normalPoints;
        driftChart.data.datasets[1].data = driftAlerts;

        driftChart.update('quiet');
    }


    // --- График P&L ---
    function updatePnlChart(history) {
        if (!pnlChart || !history || !Array.isArray(history)) return;

        const initialBalance = 10000;
        let cumulativeProfit = 0;

        // Сортировка
        const sortedHistory = history.sort((a, b) => new Date(a.time_close) - new Date(b.time_close));

        const chartData = sortedHistory.map(trade => {
            cumulativeProfit += trade.profit;
            return { x: new Date(trade.time_close).getTime(), y: initialBalance + cumulativeProfit };
        });

        // Добавляем стартовую точку
        if (chartData.length > 0) {
             const firstTime = chartData[0].x - 3600000;
             chartData.unshift({ x: firstTime, y: initialBalance });
        } else {
             chartData.push({ x: Date.now(), y: initialBalance });
        }

        pnlChart.data.datasets[0].data = chartData;
        pnlChart.update();
    }

    // --- График Оркестратора ---
    function updateOrchestratorChart(allocation) {
        if (!orchestratorChart || !allocation) return;
        const labels = Object.keys(allocation);
        const data = Object.values(allocation).map(v => v * 100);
        orchestratorChart.data.labels = labels;
        orchestratorChart.data.datasets[0].data = data;
        orchestratorChart.update();
    }

    // --- Логи ---
    function addLogMessage(log) {
        if (!log || !elements.logFeed) return;
        const logEntry = document.createElement('div');
        logEntry.className = 'log-entry';
        // Если пришел объект с message, берем его, иначе сам лог
        logEntry.innerHTML = log.message || log;
        elements.logFeed.appendChild(logEntry);
        elements.logFeed.scrollTop = elements.logFeed.scrollHeight;
    }

    // --- Статус системы ---
    function updateStatusUI(data) {
        if (!data) return;
        if (elements.systemStatus) {
            elements.systemStatus.textContent = data.is_running ? 'Запущена' : 'Остановлена';
            elements.systemStatus.style.color = data.is_running ? '#50fa7b' : '#ff5555';
        }

        if (elements.systemMode) elements.systemMode.textContent = data.mode;
        if (elements.systemUptime) elements.systemUptime.textContent = data.uptime;
        if (elements.systemBalance) elements.systemBalance.textContent = formatCurrency(data.balance);
        if (elements.systemEquity) elements.systemEquity.textContent = formatCurrency(data.equity);
        if (elements.systemDrawdown) elements.systemDrawdown.textContent = `${(data.current_drawdown || 0).toFixed(2)}%`;

        if (elements.startBtn) elements.startBtn.disabled = data.is_running;
        if (elements.stopBtn) elements.stopBtn.disabled = !data.is_running;

        if (elements.observerModeSwitch) {
            const isObserver = data.mode === 'Наблюдатель';
            if (elements.observerModeSwitch.checked !== isObserver) {
                 elements.observerModeSwitch.checked = isObserver;
            }
        }
    }

    // --- Таблица позиций ---
    function updatePositionsUI(positions) {
        if (!positions || !elements.positionsTableBody) return;

        if (elements.positionsCount) elements.positionsCount.textContent = positions.length;
        elements.positionsTableBody.innerHTML = '';

        if (positions.length === 0) {
            elements.positionsTableBody.innerHTML = '<tr><td colspan="7" class="empty-table">Нет открытых позиций</td></tr>';
            return;
        }

        positions.forEach(pos => {
            const row = document.createElement('tr');
            const profitClass = pos.profit >= 0 ? 'profit-positive' : 'profit-negative';

            // ОБНОВЛЕННАЯ СТРУКТУРА СТРОКИ
            row.innerHTML = `
                <td>${pos.ticket}</td>
                <td>${pos.symbol}</td>
                <td>${pos.strategy}</td>
                <td>${pos.type}</td>
                <td>${pos.volume}</td>
                <td class="${profitClass}">${formatCurrency(pos.profit)}</td>

                <!-- Новые ячейки -->
                <td>${pos.bars || '0'}</td>
                <td>${pos.timeframe || 'N/A'}</td>

                <td><button class="btn-close-pos" data-ticket="${pos.ticket}">Закрыть</button></td>
            `;
            elements.positionsTableBody.appendChild(row);
        });
    }

    // ============================================================
    // 3. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
    // ============================================================
    function formatCurrency(value) {
        if (typeof value !== 'number') return '--';
        return new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'USD' }).format(value);
    }

    async function sendControlCommand(endpoint, body = null) {
        try {
            let url = `/api/v1/control/${endpoint}`;
            let options = { method: 'POST' };

            if (endpoint.includes('observer_mode')) {
                 url += `?enable=${body}`;
            } else if (body) {
                 options.headers = { 'Content-Type': 'application/json' };
                 options.body = JSON.stringify(body);
            }

            const response = await fetch(url, options);
            if (!response.ok) {
                const result = await response.json();
                alert(`Ошибка: ${result.detail || 'Неизвестная ошибка'}`);
            }
        } catch (error) {
            console.error(`Сетевая ошибка: ${error}`);
        }
    }

    // ============================================================
    // 4. ИНИЦИАЛИЗАЦИЯ ГРАФИКОВ
    // ============================================================
    function initCharts() {
        if (typeof Chart === 'undefined') {
            console.error("Chart.js не загружен! Проверьте подключение к интернету или index.html");
            return;
        }

        const commonOptions = {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { labels: { color: '#f8f8f2' } } }
        };

        // PnL Chart
        const pnlCanvas = document.getElementById('pnl-chart');
        if (pnlCanvas) {
            const pnlCtx = pnlCanvas.getContext('2d');
            pnlChart = new Chart(pnlCtx, {
                type: 'line',
                data: {
                    datasets: [{
                        label: 'Equity',
                        data: [],
                        borderColor: '#50fa7b',
                        tension: 0.1,
                        pointRadius: 0,
                        borderWidth: 2
                    }]
                },
                options: {
                    ...commonOptions,
                    scales: {
                        x: {
                            type: 'time',
                            time: { unit: 'day', displayFormats: { day: 'dd.MM' } },
                            ticks: { color: '#f8f8f2' },
                            grid: { color: 'rgba(248, 248, 242, 0.1)' }
                        },
                        y: {
                            ticks: { color: '#f8f8f2' },
                            grid: { color: 'rgba(248, 248, 242, 0.1)' }
                        }
                    }
                }
            });
        }

        // Orchestrator Chart
        const orchCanvas = document.getElementById('orchestrator-chart');
        if (orchCanvas) {
            const orchCtx = orchCanvas.getContext('2d');
            orchestratorChart = new Chart(orchCtx, {
                type: 'bar',
                data: { labels: [], datasets: [{ label: 'Капитал (%)', data: [], backgroundColor: '#bd93f9' }] },
                options: {
                    ...commonOptions,
                    indexAxis: 'y',
                    scales: {
                        x: {
                            ticks: { color: '#f8f8f2', callback: value => value + '%' },
                            grid: { color: 'rgba(248, 248, 242, 0.1)' },
                            max: 100
                        },
                        y: {
                            ticks: { color: '#f8f8f2' },
                            grid: { display: false }
                        }
                    },
                    plugins: {
                        legend: { display: false },
                        tooltip: { callbacks: { label: (context) => ` ${context.raw.toFixed(2)}%` } }
                    }
                }
            });
        }

        // WEB.3: Drift Chart
        const driftCanvas = document.getElementById('drift-chart');
        if (driftCanvas) {
            const driftCtx = driftCanvas.getContext('2d');
            driftChart = new Chart(driftCtx, {
                type: 'scatter',
                data: {
                    datasets: [
                        {
                            label: 'Ошибка Прогноза (APE)',
                            data: [],
                            backgroundColor: '#50fa7b', // Green for normal
                            borderColor: '#50fa7b',
                            pointRadius: 4,
                            pointHoverRadius: 6,
                            showLine: false,
                        },
                        {
                            label: 'Дрейф Обнаружен',
                            data: [],
                            backgroundColor: '#ff5555', // Red for drift
                            borderColor: '#ff5555',
                            pointStyle: 'crossRot', // Крестик
                            pointRadius: 8,
                            pointHoverRadius: 10,
                            showLine: false,
                        }
                    ]
                },
                options: {
                    ...commonOptions,
                    scales: {
                        x: {
                            type: 'time',
                            time: { unit: 'hour', displayFormats: { hour: 'HH:mm' } },
                            ticks: { color: '#f8f8f2' },
                            grid: { color: 'rgba(248, 248, 242, 0.1)' }
                        },
                        y: {
                            title: { display: true, text: 'APE (Absolute Prediction Error)', color: '#f8f8f2' },
                            ticks: { color: '#f8f8f2' },
                            grid: { color: 'rgba(248, 248, 242, 0.1)' }
                        }
                    },
                    plugins: {
                        legend: { display: true, labels: { color: '#f8f8f2' } },
                        tooltip: {
                            callbacks: {
                                label: (context) => {
                                    const dataPoint = context.dataset.data[context.dataIndex];
                                    return ` Ошибка: ${context.parsed.y.toFixed(4)} | Символ: ${dataPoint.symbol}`;
                                }
                            }
                        }
                    }
                }
            });
        }
    }

    // ============================================================
    // 5. WEBSOCKET
    // ============================================================
    function connectWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/api/ws/updates`;

        console.log(`Connecting to WebSocket: ${wsUrl}`);
        const socket = new WebSocket(wsUrl);

        socket.onopen = () => {
            console.log("WebSocket Connected");
            if (elements.connectionStatus) {
                elements.connectionStatus.classList.add('connected');
                elements.connectionStatus.title = "Подключено";
            }
            if (elements.marketRegime) elements.marketRegime.textContent = 'Ожидание данных...';
        };

        socket.onmessage = (event) => {
            try {
                const message = JSON.parse(event.data);

                // ТЕПЕРЬ ФУНКЦИИ ТОЧНО СУЩЕСТВУЮТ
                switch (message.type) {
                    case 'status_update':
                        updateStatusUI(message.payload);
                        break;
                    case 'positions_update':
                        updatePositionsUI(message.payload);
                        break;
                    case 'history_update':
                        updatePnlChart(message.payload);
                        break;
                    case 'log_message':
                        addLogMessage(message.payload);
                        break;
                    case 'orchestrator_update':
                        updateOrchestratorChart(message.payload);
                        break;
                    case 'market_regime_update':
                        if (elements.marketRegime) elements.marketRegime.textContent = message.payload.regime;
                        break;
                    case 'drift_update': // <-- WEB.3: НОВЫЙ CASE
                        updateDriftChart(message.payload);
                        break;
                }
            } catch (e) {
                console.error("Ошибка обработки WS сообщения:", e);
            }
        };

        socket.onclose = () => {
            console.log("WebSocket Disconnected");
            if (elements.connectionStatus) {
                elements.connectionStatus.classList.remove('connected');
                elements.connectionStatus.title = "Отключено";
            }
            setTimeout(connectWebSocket, 3000);
        };

        socket.onerror = (error) => {
            console.error("WebSocket Error:", error);
            socket.close();
        };
    }

    // ============================================================
    // 6. ЗАГРУЗКА НАЧАЛЬНЫХ ДАННЫХ
    // ============================================================
    async function fetchInitialData() {
        try {
            const response = await fetch('/api/v1/status');
            if (response.ok) {
                const data = await response.json();
                updateStatusUI(data);
            }

            const posResponse = await fetch('/api/v1/positions');
            if (posResponse.ok) {
                const positions = await posResponse.json();
                updatePositionsUI(positions);
            }

            const histResponse = await fetch('/api/v1/history');
            if (histResponse.ok) {
                const history = await histResponse.json();
                updatePnlChart(history);
            }

        } catch (e) {
            console.error("Ошибка загрузки начальных данных:", e);
        }
    }

    // ============================================================
    // 7. ПРИВЯЗКА СОБЫТИЙ
    // ============================================================
    if (elements.startBtn) elements.startBtn.addEventListener('click', () => sendControlCommand('start'));
    if (elements.stopBtn) elements.stopBtn.addEventListener('click', () => sendControlCommand('stop'));
    if (elements.closeAllBtn) elements.closeAllBtn.addEventListener('click', () => confirm('Закрыть ВСЕ позиции?') && sendControlCommand('close_all'));
    if (elements.closeAllEmergencyBtn) elements.closeAllEmergencyBtn.addEventListener('click', () => confirm('ВНИМАНИЕ! Закрыть все и остановить систему?') && sendControlCommand('close_all').then(() => sendControlCommand('stop')));

    if (elements.observerModeSwitch) {
        elements.observerModeSwitch.addEventListener('change', (e) => {
            sendControlCommand('observer_mode', e.target.checked);
        });
    }

    if (elements.positionsTableBody) {
        elements.positionsTableBody.addEventListener('click', (e) => {
            if (e.target.classList.contains('btn-close-pos')) {
                const ticket = e.target.dataset.ticket;
                if (confirm(`Закрыть позицию #${ticket}?`)) sendControlCommand(`close/${ticket}`);
            }
        });
    }

    // ============================================================
    // 8. ЗАПУСК
    // ============================================================
    initCharts();
    fetchInitialData();
    connectWebSocket();
});