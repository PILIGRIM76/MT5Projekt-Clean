# -*- coding: utf-8 -*-
"""
Патч для matplotlib._api.deprecation
Добавляет ВСЕ необходимые функции перед импортом matplotlib
"""

import functools
import sys
import warnings
from types import ModuleType

# Создаём модуль-заглушку для matplotlib._api.deprecation
if "matplotlib._api.deprecation" not in sys.modules:
    # Создаём модуль
    mpl_api_deprecation = ModuleType("matplotlib._api.deprecation")

    # Класс mplDeprecation
    class mplDeprecation:
        """Заглушка для совместимости с matplotlib 3.10.x"""

        def __init__(self, *args, **kwargs):
            pass

        def __call__(self, arg=None, /, **kwargs):
            return arg

        def __getattr__(self, name):
            return self

        def __repr__(self):
            return "<mplDeprecation stub>"

    # Функция deprecated (декоратор)
    def deprecated(
        since, *, addendum=None, pending=False, obj_type=None, obj_name=None, arg_name=None, alternate=None, removal=None
    ):
        """Декоратор-заглушка для deprecated функций"""

        def decorator(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                return func(*args, **kwargs)

            return wrapper

        return decorator

    # Функция deprecation
    def deprecation(
        message, *, addendum=None, pending=False, obj_type=None, obj_name=None, arg_name=None, alternate=None, removal=None
    ):
        """Функция-заглушка для deprecation"""
        return mplDeprecation()

    # Функция warn_deprecated
    def warn_deprecated(
        since,
        *,
        message="",
        addendum="",
        obj_type="",
        obj_name="",
        arg_name="",
        alternate="",
        removal="",
        warning_stacklevel=2,
    ):
        """Функция-заглушка для warn_deprecated"""
        if message:
            warnings.warn(f"[DEPRECATED since {since}] {message}", DeprecationWarning, stacklevel=warning_stacklevel)

    # Функция warn_external
    def warn_external(message, category=UserWarning):
        """Функция-заглушка для warn_external"""
        warnings.warn(message, category, stacklevel=2)

    # Функция rename_parameter
    def rename_parameter(since, *, old_param_name, new_param_name, addendum="", pending=False, removal=None):
        """Декоратор-заглушка для rename_parameter"""

        def decorator(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                return func(*args, **kwargs)

            return wrapper

        return decorator

    # Функция make_keyword_only
    def make_keyword_only(since, *, param_name, addendum="", pending=False, removal=None):
        """Декоратор-заглушка для make_keyword_only"""

        def decorator(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                return func(*args, **kwargs)

            return wrapper

        return decorator

    # Функция delete_parameter
    def delete_parameter(since, *, param_name, addendum="", pending=False, removal=None):
        """Декоратор-заглушка для delete_parameter"""

        def decorator(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                return func(*args, **kwargs)

            return wrapper

        return decorator

    # Функция change_parameter_signature
    def change_parameter_signature(since, *, param_name, new_type, addendum="", pending=False, removal=None):
        """Декоратор-заглушка для change_parameter_signature"""

        def decorator(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                return func(*args, **kwargs)

            return wrapper

        return decorator

    # Добавляем в модуль
    mpl_api_deprecation.mplDeprecation = mplDeprecation
    mpl_api_deprecation.deprecated = deprecated
    mpl_api_deprecation.deprecation = deprecation
    mpl_api_deprecation.warn_deprecated = warn_deprecated
    mpl_api_deprecation.warn_external = warn_external
    mpl_api_deprecation.rename_parameter = rename_parameter
    mpl_api_deprecation.make_keyword_only = make_keyword_only
    mpl_api_deprecation.delete_parameter = delete_parameter
    mpl_api_deprecation.change_parameter_signature = change_parameter_signature
    mpl_api_deprecation.__all__ = [
        "mplDeprecation",
        "deprecated",
        "deprecation",
        "warn_deprecated",
        "warn_external",
        "rename_parameter",
        "make_keyword_only",
        "delete_parameter",
        "change_parameter_signature",
    ]

    # Регистрируем в sys.modules
    sys.modules["matplotlib._api.deprecation"] = mpl_api_deprecation

    print("[PATCH] matplotlib._api.deprecation patched successfully")
