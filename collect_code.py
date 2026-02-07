# collect_code_auto.py
import os

# --- НАСТРОЙКИ ---

# Имя итогового файла
output_filename = "full_project_code.txt"

# Директории, которые нужно полностью исключить из обхода.
# Имена проверяются на любом уровне вложенности.
EXCLUDE_DIRS = {
    # Системные и контрольные папки
    '.git',
    '.github',
    '.idea',
    '.vscode',
    '__pycache__',

    # Папки виртуальных окружений
    'venv',
    '.venv',
    'env',
    'Scripts',
    'Lib',
    'Include',
    'site-packages',

    # Папки с результатами сборки и зависимостями
    'node_modules',
    'dist',
    'build',

    # Пользовательские исключения
    'docs',
    'share',
    'trader_storage',
    'DLLs',
    'Python310',  # Если это часть venv или системного интерпретатора
}

# Файлы, которые нужно исключить по имени
EXCLUDE_FILES = {
    output_filename,
    os.path.basename(__file__),  # Исключаем сам этот скрипт
}

# --- НОВЫЕ НАСТРОЙКИ ---
# Файлы, которые нужно исключить по их относительному пути.
# Пути должны использовать '/' в качестве разделителя.
EXCLUDE_PATHS = {
    'database/trade_entry_data.json',
}
# --- КОНЕЦ НОВЫХ НАСТРОЕК ---

# Расширения файлов, которые нужно включить в сборку
INCLUDE_EXTENSIONS = {
    '.py',
    '.json',
    '.env',
    '.toml',
    '.txt',
    '.md',
    '.html',
    '.css',
    '.js',
    '.qml'
}


# --- КОНЕЦ НАСТРОЕК ---


def generate_tree_structure(root_dir):
    """Генерирует текстовое представление дерева проекта, учитывая исключения."""
    tree_lines = ["Структура проекта:\n"]
    processed_paths = set()

    for root, dirs, files in os.walk(root_dir, topdown=True):
        dirs[:] = [d for d in sorted(dirs) if d not in EXCLUDE_DIRS and not d.startswith('.')]

        if any(excluded in root.split(os.sep) for excluded in EXCLUDE_DIRS):
            continue

        rel_path = os.path.relpath(root, root_dir)
        if rel_path == '.':
            level = 0
        else:
            level = len(rel_path.split(os.sep))

        indent = '    ' * level
        dir_name = os.path.basename(root)

        if rel_path != '.' and rel_path not in processed_paths:
            tree_lines.append(f"{indent}└── {dir_name}/\n")
            processed_paths.add(rel_path)

        sub_indent = '    ' * (level + 1)

        filtered_files = []
        for f in sorted(files):
            # Пропускаем файлы по имени и расширению
            if f in EXCLUDE_FILES or not any(f.endswith(ext) for ext in INCLUDE_EXTENSIONS):
                continue

            # Проверяем по полному относительному пути
            full_path = os.path.join(root, f)
            relative_path = os.path.relpath(full_path, root_dir).replace(os.sep, '/')
            if relative_path in EXCLUDE_PATHS:
                continue

            filtered_files.append(f)

        for f in filtered_files:
            tree_lines.append(f"{sub_indent}├── {f}\n")

    return "".join(tree_lines)


def collect_project_files(root_dir):
    """
    Рекурсивно собирает пути ко всем файлам в проекте,
    учитывая правила включения и исключения.
    """
    collected_paths = []
    for root, dirs, files in os.walk(root_dir, topdown=True):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith('.')]

        for file in files:
            # Базовые проверки по имени и расширению
            if file in EXCLUDE_FILES or not any(file.endswith(ext) for ext in INCLUDE_EXTENSIONS):
                continue

            full_path = os.path.join(root, file)

            # Новая проверка: по относительному пути
            relative_path = os.path.relpath(full_path, root_dir).replace(os.sep, '/')
            if relative_path in EXCLUDE_PATHS:
                continue

            collected_paths.append(full_path)

    return sorted(collected_paths)


def main():
    """Основная функция для сборки проекта в один файл."""
    project_root = '.'  # Начинаем с текущей директории

    print("Анализ структуры проекта...")
    files_to_process = collect_project_files(project_root)

    if not files_to_process:
        print("Не найдено файлов для сборки. Проверьте настройки INCLUDE_EXTENSIONS и EXCLUDE_DIRS.")
        return

    print("Генерация дерева проекта...")
    tree_structure = generate_tree_structure(project_root)

    try:
        with open(output_filename, 'w', encoding='utf-8') as outfile:
            outfile.write(tree_structure)
            outfile.write("\n" + "=" * 80 + "\n\n")

            print(f"Найдено {len(files_to_process)} файлов. Начинаю сборку в {output_filename}...")

            for filepath in files_to_process:
                try:
                    normalized_path = os.path.normpath(filepath).replace(os.sep, '/')
                    header = f"--- Файл: {normalized_path} ---\n\n"
                    outfile.write(header)

                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as infile:
                        content = infile.read()
                        outfile.write(content)

                    outfile.write("\n\n")
                except Exception as e:
                    error_message = f"--- Ошибка чтения файла: {filepath} ---\n{str(e)}\n\n"
                    outfile.write(error_message)
                    print(f"(!) Ошибка при чтении файла {filepath}: {e}")

        final_path = os.path.abspath(output_filename)
        print(f"Сборка кода успешно завершена! Результат в файле: {final_path}")

    except IOError as e:
        print(f"(!) Критическая ошибка записи в файл {output_filename}: {e}")


if __name__ == "__main__":
    main()
