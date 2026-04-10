# -*- coding: utf-8 -*-
"""
src/gui/animation_manager.py — Менеджер анимаций для Genesis Trading System

Отвечает за:
- Плавные переходы при переключении вкладок
- Анимации появления/скрытия уведомлений
- Анимации обновления графиков
- Анимации появления/исчезновения виджетов
- Контроль производительности (отключение при высокой нагрузке)

Использует QPropertyAnimation и QSequentialAnimationGroup.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from PySide6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QSequentialAnimationGroup,
    QTimer,
)
from PySide6.QtWidgets import QWidget

logger = logging.getLogger(__name__)


class AnimationManager:
    """
    Централизованный менеджер анимаций.

    Обеспечивает:
    - Единый стиль анимаций во всём GUI
    - Автоматическое отключение при высокой нагрузке на CPU
    - Повторное использование объектов анимации
    """

    # Длительности анимаций (мс)
    DURATION_FAST = 120  # Микро-анимации (hover, клик)
    DURATION_NORMAL = 250  # Стандартные (переключение вкладок)
    DURATION_SLOW = 400  # Появление/скрытие панелей
    DURATION_NOTIFICATION = 300  # Уведомления

    # Порог CPU для автоотключения (процент)
    CPU_THRESHOLD = 85

    def __init__(self, cpu_monitor=None):
        self._cpu_monitor = cpu_monitor
        self._animations_enabled = True
        self._active_animations: list[QPropertyAnimation] = []
        self._cpu_check_timer = QTimer()
        self._cpu_check_timer.timeout.connect(self._check_cpu_and_maybe_disable)
        self._cpu_check_timer.start(5000)  # Проверка каждые 5 сек

        logger.info("[AnimationManager] Инициализирован")

    # ===================================================================
    # Управление состоянием
    # ===================================================================

    @property
    def enabled(self) -> bool:
        return self._animations_enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._animations_enabled = value
        if not value:
            self._stop_all_animations()
        logger.info(f"[AnimationManager] Анимации {'включены' if value else 'отключены'}")

    def _check_cpu_and_maybe_disable(self) -> None:
        """Автоматически отключает анимации при высокой нагрузке."""
        if self._cpu_monitor is None:
            return
        try:
            cpu_percent = self._cpu_monitor()
            if cpu_percent > self.CPU_THRESHOLD and self._animations_enabled:
                logger.warning(f"[AnimationManager] CPU {cpu_percent}% > {self.CPU_THRESHOLD}% — отключаю анимации")
                self.enabled = False
            elif cpu_percent < (self.CPU_THRESHOLD - 15) and not self._animations_enabled:
                logger.info(f"[AnimationManager] CPU {cpu_percent}% — включаю анимации обратно")
                self.enabled = True
        except Exception as e:
            logger.debug(f"[AnimationManager] Ошибка проверки CPU: {e}")

    def _stop_all_animations(self) -> None:
        """Останавливает все активные анимации."""
        for anim in self._active_animations:
            try:
                anim.stop()
            except RuntimeError:
                pass  # Объект уже удалён
        self._active_animations.clear()

    # ===================================================================
    # Анимация: появление виджета (fade in + slide)
    # ===================================================================

    def animate_show(
        self,
        widget: QWidget,
        duration: int = DURATION_NORMAL,
        direction: str = "top",  # top, bottom, left, right
        on_finished: Optional[Callable] = None,
    ) -> QPropertyAnimation:
        """
        Анимация появления виджета: fade in + slide.

        Args:
            widget: Виджет для анимации
            duration: Длительность в мс
            direction: Направление появления
            on_finished: Callback по завершении
        """
        if not self._animations_enabled:
            widget.setVisible(True)
            widget.setGraphicsEffect(None)
            if on_finished:
                on_finished()
            return None

        from PySide6.QtWidgets import QGraphicsOpacityEffect

        widget.setVisible(True)

        # Opacity animation
        opacity_effect = QGraphicsOpacityEffect(widget)
        opacity_effect.setOpacity(0.0)
        widget.setGraphicsEffect(opacity_effect)

        opacity_anim = QPropertyAnimation(opacity_effect, b"opacity")
        opacity_anim.setDuration(duration)
        opacity_anim.setStartValue(0.0)
        opacity_anim.setEndValue(1.0)
        opacity_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._active_animations.append(opacity_anim)

        if on_finished:
            opacity_anim.finished.connect(on_finished)

        opacity_anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

        # Очистка эффекта после завершения
        def _cleanup():
            try:
                widget.setGraphicsEffect(None)
                if opacity_anim in self._active_animations:
                    self._active_animations.remove(opacity_anim)
            except RuntimeError:
                pass

        opacity_anim.finished.connect(_cleanup)

        return opacity_anim

    # ===================================================================
    # Анимация: скрытие виджета (fade out)
    # ===================================================================

    def animate_hide(
        self,
        widget: QWidget,
        duration: int = DURATION_NORMAL,
        on_finished: Optional[Callable] = None,
    ) -> QPropertyAnimation:
        """Анимация скрытия виджета: fade out."""
        if not self._animations_enabled:
            widget.setVisible(False)
            if on_finished:
                on_finished()
            return None

        from PySide6.QtWidgets import QGraphicsOpacityEffect

        opacity_effect = QGraphicsOpacityEffect(widget)
        opacity_effect.setOpacity(1.0)
        widget.setGraphicsEffect(opacity_effect)

        opacity_anim = QPropertyAnimation(opacity_effect, b"opacity")
        opacity_anim.setDuration(duration)
        opacity_anim.setStartValue(1.0)
        opacity_anim.setEndValue(0.0)
        opacity_anim.setEasingCurve(QEasingCurve.Type.InCubic)

        self._active_animations.append(opacity_anim)

        def _cleanup():
            widget.setVisible(False)
            try:
                widget.setGraphicsEffect(None)
                if opacity_anim in self._active_animations:
                    self._active_animations.remove(opacity_anim)
            except RuntimeError:
                pass

        if on_finished:
            opacity_anim.finished.connect(on_finished)

        opacity_anim.finished.connect(_cleanup)
        opacity_anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

        return opacity_anim

    # ===================================================================
    # Анимация: уведомление (slide down + fade in + auto hide)
    # ===================================================================

    def animate_notification(
        self,
        widget: QWidget,
        show_duration: int = DURATION_NOTIFICATION,
        auto_hide_ms: int = 3000,
    ) -> None:
        """
        Анимация уведомления: появление → показ → скрытие.

        Args:
            widget: Виджет уведомления
            show_duration: Длительность появления
            auto_hide_ms: Время авто-скрытия
        """
        if not self._animations_enabled:
            widget.setVisible(True)
            QTimer.singleShot(auto_hide_ms, lambda: widget.setVisible(False))
            return

        # Показ
        self.animate_show(widget, duration=show_duration)

        # Авто-скрытие
        QTimer.singleShot(
            show_duration + auto_hide_ms,
            lambda: self.animate_hide(widget, duration=show_duration),
        )

    # ===================================================================
    # Анимация: переключение вкладок (fade)
    # ===================================================================

    def animate_tab_switch(
        self,
        widget: QWidget,
        duration: int = DURATION_FAST,
    ) -> None:
        """Быстрая анимация при переключении вкладок."""
        if not self._animations_enabled:
            return

        self.animate_show(widget, duration=duration)

    # ===================================================================
    # Анимация: пульсация (для индикаторов)
    # ===================================================================

    def animate_pulse(
        self,
        widget: QWidget,
        cycles: int = 2,
        duration_per_cycle: int = 500,
    ) -> None:
        """
        Пульсация виджета (прозрачность 1.0 -> 0.4 -> 1.0).

        Args:
            widget: Целевой виджет
            cycles: Количество циклов
            duration_per_cycle: Длительность одного цикла
        """
        if not self._animations_enabled:
            return

        from PySide6.QtWidgets import QGraphicsOpacityEffect

        opacity_effect = QGraphicsOpacityEffect(widget)
        opacity_effect.setOpacity(1.0)
        widget.setGraphicsEffect(opacity_effect)

        # Создаём последовательную анимацию: 1.0 -> 0.4 -> 1.0
        seq = QSequentialAnimationGroup()

        fade_out = QPropertyAnimation(opacity_effect, b"opacity")
        fade_out.setDuration(duration_per_cycle // 2)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.4)
        fade_out.setEasingCurve(QEasingCurve.Type.InOutQuad)
        seq.addAnimation(fade_out)

        fade_in = QPropertyAnimation(opacity_effect, b"opacity")
        fade_in.setDuration(duration_per_cycle // 2)
        fade_in.setStartValue(0.4)
        fade_in.setEndValue(1.0)
        fade_in.setEasingCurve(QEasingCurve.Type.InOutQuad)
        seq.addAnimation(fade_in)

        seq.setLoopCount(cycles)

        def _cleanup():
            try:
                widget.setGraphicsEffect(None)
            except RuntimeError:
                pass

        seq.finished.connect(_cleanup)
        seq.start()

    # ===================================================================
    # Анимация: цвет фона (через QTimer)
    # ===================================================================

    @staticmethod
    def animate_background_color(
        widget: QWidget,
        from_color: str,
        to_color: str,
        duration: int = DURATION_NORMAL,
        steps: int = 10,
    ) -> None:
        """
        Плавная смена цвета фона.

        Args:
            widget: Целевой виджет
            from_color: Начальный цвет (CSS, напр. '#FFFFFF')
            to_color: Конечный цвет
            duration: Общая длительность
            steps: Количество шагов
        """

        def _hex_to_rgb(hex_color: str) -> tuple:
            hex_color = hex_color.lstrip("#")
            return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))

        r1, g1, b1 = _hex_to_rgb(from_color)
        r2, g2, b2 = _hex_to_rgb(to_color)

        step_duration = max(16, duration // steps)  # Минимум ~16ms

        for step in range(1, steps + 1):
            t = step / steps
            r = int(r1 + (r2 - r1) * t)
            g = int(g1 + (g2 - g1) * t)
            b = int(b1 + (b2 - b1) * t)

            QTimer.singleShot(
                step * step_duration,
                lambda _r=r, _g=g, _b=b: widget.setStyleSheet(
                    widget.styleSheet() + f"background-color: rgb({_r}, {_g}, {_b});"
                ),
            )

    # ===================================================================
    # Анимация: размер (resize)
    # ===================================================================

    @staticmethod
    def animate_resize(
        widget: QWidget,
        target_width: int,
        target_height: int,
        duration: int = DURATION_NORMAL,
    ) -> QPropertyAnimation:
        """
        Анимация изменения размера виджета.

        Args:
            widget: Целевой виджет
            target_width: Конечная ширина
            target_height: Конечная высота
            duration: Длительность
        """
        anim = QPropertyAnimation(widget, b"size")
        anim.setDuration(duration)
        anim.setStartValue(widget.size())
        anim.setEndValue((target_width, target_height))
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        return anim

    # ===================================================================
    # Анимация: положение (move)
    # ===================================================================

    @staticmethod
    def animate_move(
        widget: QWidget,
        target_x: int,
        target_y: int,
        duration: int = DURATION_NORMAL,
    ) -> QPropertyAnimation:
        """
        Анимация перемещения виджета.

        Args:
            widget: Целевой виджет
            target_x: Конечная X
            target_y: Конечная Y
            duration: Длительность
        """
        from PySide6.QtCore import QPoint

        anim = QPropertyAnimation(widget, b"pos")
        anim.setDuration(duration)
        anim.setStartValue(widget.pos())
        anim.setEndValue(QPoint(target_x, target_y))
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        return anim
