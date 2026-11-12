import argparse
import os
import sys
import tomli
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import json
import re


def validate_package_name(value: str) -> str:
    """Проверяет имя пакета."""
    if not value.strip():
        raise argparse.ArgumentTypeError(
            "Имя пакета не может быть пустым."
        )

    if any(char.isspace() for char in value):
        raise argparse.ArgumentTypeError(
            "Имя пакета не должно содержать пробелы."
        )

    return value


def validate_repository(value: str) -> str:
    """Проверяет URL или путь к локальному репозиторию."""
    if not value.strip():
        raise argparse.ArgumentTypeError(
            "URL или путь к репозиторию не может быть пустым."
        )

    parsed = urlparse(value)

    # URL
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return value

    # Локальный путь
    if os.path.exists(value):
        return value

    raise argparse.ArgumentTypeError(
        "Указанный URL некорректен или локальный путь не существует."
    )


def validate_repository_mode(value: str) -> str:
    """Проверяет режим работы с репозиторием."""
    allowed_modes = {"file", "url"}

    if value not in allowed_modes:
        raise argparse.ArgumentTypeError(
            f"Недопустимый режим: {value}. "
            f"Допустимые значения: {', '.join(sorted(allowed_modes))}"
        )

    return value


def validate_output_file(value: str) -> str:
    """Проверяет имя файла изображения."""
    if not value.strip():
        raise argparse.ArgumentTypeError(
            "Имя выходного файла не может быть пустым."
        )

    if os.path.basename(value) != value:
        raise argparse.ArgumentTypeError(
            "Необходимо указать имя файла без пути."
        )

    if not value.lower().endswith((".png", ".jpg", ".jpeg")):
        raise argparse.ArgumentTypeError(
            "Файл изображения должен иметь расширение "
            ".png, .jpg или .jpeg."
        )

    return value


def create_parser() -> argparse.ArgumentParser:
    """Создаёт CLI-парсер."""
    parser = argparse.ArgumentParser(
        description="Инструмент визуализации графа зависимостей"
    )

    parser.add_argument(
        "--package",
        required=True,
        type=validate_package_name,
        help="Имя анализируемого пакета",
    )

    parser.add_argument(
        "--repository",
        required=True,
        type=validate_repository,
        help="URL репозитория или путь к тестовому репозиторию",
    )

    parser.add_argument(
        "--mode",
        required=True,
        type=validate_repository_mode,
        choices=["file", "url"],
        help="Режим работы с репозиторием: file или url",
    )

    parser.add_argument(
        "--output",
        required=True,
        type=validate_output_file,
        help="Имя файла изображения графа",
    )

    return parser


def load_cargo_toml_from_file(repository_path: str) -> dict:
    """
    Загружает Cargo.toml из локального репозитория.

    repository_path может быть:
    - путём к Cargo.toml;
    - путём к каталогу, содержащему Cargo.toml.
    """

    if os.path.isdir(repository_path):
        cargo_path = os.path.join(repository_path, "Cargo.toml")
    else:
        cargo_path = repository_path

    if not os.path.isfile(cargo_path):
        raise FileNotFoundError(
            f"Файл Cargo.toml не найден: {cargo_path}"
        )

    try:
        with open(cargo_path, "rb") as file:
            return tomli.load(file)
    except tomli.TOMLDecodeError as error:
        raise ValueError(
            f"Ошибка разбора Cargo.toml: {error}"
        ) from error


def build_raw_github_url(repository_url: str) -> str | None:
    """
    Если передан URL GitHub-репозитория, формирует URL
    для Cargo.toml.

    Поддерживаются ссылки вида:
    https://github.com/user/project
    https://github.com/user/project/
    https://github.com/user/project/tree/main

    Для стандартного варианта используется ветка main.
    """

    parsed = urlparse(repository_url)

    if parsed.netloc.lower() not in {
        "github.com",
        "www.github.com",
    }:
        return None

    parts = [
        part for part in parsed.path.strip("/").split("/")
        if part
    ]

    if len(parts) < 2:
        return None

    owner = parts[0]
    repository = parts[1]

    # Если URL уже указывает непосредственно на Cargo.toml,
    # преобразование не требуется.
    if repository_url.endswith("Cargo.toml"):
        return repository_url

    return (
        f"https://raw.githubusercontent.com/"
        f"{owner}/{repository}/main/Cargo.toml"
    )


def load_cargo_toml_from_url(repository_url: str) -> dict:
    """Загружает Cargo.toml по URL."""

    url = repository_url

    # Если пользователь передал GitHub-репозиторий,
    # пытаемся получить Cargo.toml из ветки main.
    github_url = build_raw_github_url(repository_url)

    if github_url is not None:
        url = github_url

    request = Request(
        url,
        headers={
            "User-Agent": "DependencyGraphTool/1.0"
        },
    )

    try:
        with urlopen(request, timeout=10) as response:
            content = response.read()

    except HTTPError as error:
        raise RuntimeError(
            f"Не удалось получить Cargo.toml. "
            f"HTTP ошибка: {error.code}"
        ) from error

    except URLError as error:
        raise RuntimeError(
            f"Не удалось подключиться к репозиторию: {error.reason}"
        ) from error

    except TimeoutError as error:
        raise RuntimeError(
            "Истекло время ожидания ответа репозитория."
        ) from error

    try:
        return tomli.loads(content.decode("utf-8"))
    except tomli.TOMLDecodeError as error:
        raise ValueError(
            f"Ошибка разбора полученного Cargo.toml: {error}"
        ) from error


def load_cargo_toml(repository: str, mode: str) -> dict:
    """Загружает Cargo.toml в зависимости от выбранного режима."""

    if mode == "file":
        return load_cargo_toml_from_file(repository)

    if mode == "url":
        return load_cargo_toml_from_url(repository)

    raise ValueError(
        f"Неизвестный режим работы: {mode}"
    )


def extract_dependencies(cargo_data: dict) -> list[str]:
    """
    Извлекает прямые зависимости Cargo-пакета.

    Учитываются:
    - [dependencies]
    - [dev-dependencies]
    - [build-dependencies]
    - target.*.dependencies
    - target.*.dev-dependencies
    - target.*.build-dependencies
    """

    dependencies = set()

    dependency_sections = {
        "dependencies",
        "dev-dependencies",
        "build-dependencies",
    }


    for section_name in dependency_sections:
        section = cargo_data.get(section_name, {})

        if isinstance(section, dict):
            dependencies.update(section.keys())


    target_section = cargo_data.get("target", {})

    if isinstance(target_section, dict):
        for target_config in target_section.values():

            if not isinstance(target_config, dict):
                continue

            for section_name in dependency_sections:
                section = target_config.get(section_name, {})

                if isinstance(section, dict):
                    dependencies.update(section.keys())

    return sorted(dependencies)

def load_test_graph(file_path: str) -> dict:
    """Загружает тестовый граф из JSON."""

    if not os.path.isfile(file_path):
        raise FileNotFoundError(
            f"Файл тестового графа не найден: {file_path}"
        )

    try:
        with open(file_path, "r", encoding="utf-8") as file:
            graph = json.load(file)

    except json.JSONDecodeError as error:
        raise ValueError(
            f"Ошибка чтения JSON: {error}"
        ) from error

    if not isinstance(graph, dict):
        raise ValueError("Граф должен быть JSON-объектом.")

    for package, dependencies in graph.items():

        if not re.fullmatch(r"[A-Z]+", package):
            raise ValueError(
                f"Некорректное имя пакета: {package}. "
                "Разрешены только большие латинские буквы."
            )

        if not isinstance(dependencies, list):
            raise ValueError(
                f"Зависимости пакета {package} должны быть списком."
            )

        for dependency in dependencies:

            if not isinstance(dependency, str):
                raise ValueError(
                    f"Некорректная зависимость пакета {package}."
                )

            if not re.fullmatch(r"[A-Z]+", dependency):
                raise ValueError(
                    f"Некорректное имя зависимости: {dependency}."
                )

    # Проверяем, что все упомянутые пакеты существуют.
    for dependencies in graph.values():
        for dependency in dependencies:
            if dependency not in graph:
                raise ValueError(
                    f"Пакет {dependency} отсутствует "
                    "в описании тестового графа."
                )

    return graph

def build_graph_bfs_recursive(
    source: str,
    repository_graph: dict
) -> dict:
    """
    Строит граф зависимостей с помощью BFS
    и рекурсивной обработки очереди.

    visited предотвращает повторную обработку вершин
    и бесконечный обход при циклических зависимостях.
    """

    if source not in repository_graph:
        raise ValueError(
            f"Пакет {source} отсутствует в репозитории."
        )

    result = {}
    visited = set()

    def bfs_recursive(queue):

        if not queue:
            return

        current = queue.pop(0)

        if current in visited:
            bfs_recursive(queue)
            return

        visited.add(current)

        dependencies = repository_graph[current]

        result[current] = list(dependencies)

        for dependency in dependencies:
            if dependency not in visited:
                queue.append(dependency)

        bfs_recursive(queue)

    bfs_recursive([source])

    return result

def print_dependency_graph(graph: dict):
    """Выводит полученный граф зависимостей."""

    print("\nГраф зависимостей:")

    for package, dependencies in graph.items():

        if dependencies:
            print(
                f"{package} -> {', '.join(dependencies)}"
            )
        else:
            print(f"{package} -> нет зависимостей")

    print("\nВсе найденные пакеты:")
    print(", ".join(graph.keys()))

    print(f"\nКоличество пакетов: {len(graph)}")


def find_cycles(graph: dict) -> list:
    """
    Ищет циклические зависимости с помощью DFS.

    Возвращает список обнаруженных циклов.
    """

    visited = set()
    recursion_stack = []
    cycles = []
    found_cycles = set()

    def dfs(node):

        visited.add(node)
        recursion_stack.append(node)

        for neighbor in graph.get(node, []):

            if neighbor not in visited:
                dfs(neighbor)

            elif neighbor in recursion_stack:

                start = recursion_stack.index(neighbor)

                cycle = (
                    recursion_stack[start:] + [neighbor]
                )

                # Нормализуем цикл для исключения повторов.
                body = cycle[:-1]
                rotations = [
                    tuple(body[i:] + body[:i])
                    for i in range(len(body))
                ]

                normalized = min(rotations)

                if normalized not in found_cycles:
                    found_cycles.add(normalized)
                    cycles.append(cycle)

        recursion_stack.pop()

    for node in graph:
        if node not in visited:
            dfs(node)

    return cycles

def build_reverse_graph(graph):
    """
    Строит граф обратных зависимостей.

    Если:
        A -> B
        C -> B

    то:
        B -> [A, C]
    """
    reverse_graph = {package: [] for package in graph}

    for package, dependencies in graph.items():
        for dependency in dependencies:
            if dependency not in reverse_graph:
                reverse_graph[dependency] = []

            reverse_graph[dependency].append(package)

    return reverse_graph


def find_reverse_dependencies_bfs_recursive(package, graph):
    """
    Находит все пакеты, которые прямо или косвенно
    зависят от указанного пакета.

    Используется рекурсивный BFS, реализованный
    на предыдущем этапе.
    """
    reverse_graph = build_reverse_graph(graph)

    if package not in reverse_graph:
        raise ValueError(f"Пакет '{package}' отсутствует в графе.")

    result = []
    visited = set()

    def bfs_recursive(queue):
        if not queue:
            return

        current = queue.pop(0)

        if current in visited:
            bfs_recursive(queue)
            return

        visited.add(current)

        for dependent in reverse_graph.get(current, []):
            if dependent not in visited:
                result.append(dependent)
                queue.append(dependent)

        bfs_recursive(queue)

    bfs_recursive([package])

    return result


def print_reverse_dependencies(package, graph):
    """
    Выводит обратные зависимости указанного пакета.
    """
    reverse_dependencies = find_reverse_dependencies_bfs_recursive(
        package,
        graph
    )

    print()
    print(f"Обратные зависимости пакета '{package}':")

    if not reverse_dependencies:
        print("  Нет пакетов, зависящих от данного пакета.")
        return

    for dependency in reverse_dependencies:
        print(f"  {dependency}")

    print(f"Всего обратных зависимостей: {len(reverse_dependencies)}")






def main() -> int:
    parser = create_parser()
    args = parser.parse_args()

    print("Параметры:")
    print(f"package={args.package}")
    print(f"repository={args.repository}")
    print(f"mode={args.mode}")
    print(f"output={args.output}")

    try:

        # ТЕСТОВЫЙ РЕЖИМ
        if args.mode == "file":

            # JSON используется для тестирования графа.
            if args.repository.lower().endswith(".json"):

                repository_graph = load_test_graph(
                    args.repository
                )

                dependency_graph = build_graph_bfs_recursive(
                    args.package,
                    repository_graph
                )

                print_dependency_graph(dependency_graph)

                cycles = find_cycles(dependency_graph)

                print("\nПроверка циклических зависимостей:")

                if cycles:
                    for cycle in cycles:
                        print("Цикл: " + " -> ".join(cycle))
                else:
                    print("Циклические зависимости не обнаружены.")

                print_reverse_dependencies(args.package, repository_graph)

            else:
                # Сохраняем возможность проверки этапа 2
                # через локальный Cargo.toml.
                cargo_data = load_cargo_toml(
                    args.repository,
                    args.mode
                )

                dependencies = extract_dependencies(cargo_data)

                print(
                    f"\nПрямые зависимости пакета "
                    f"'{args.package}':"
                )

                for dependency in dependencies:
                    print(f"  - {dependency}")

        # РЕЖИМ URL
        elif args.mode == "url":

            cargo_data = load_cargo_toml(
                args.repository,
                args.mode
            )

            dependencies = extract_dependencies(cargo_data)

            print(
                f"\nПрямые зависимости пакета "
                f"'{args.package}':"
            )

            for dependency in dependencies:
                print(f"  - {dependency}")

    except (
        FileNotFoundError,
        ValueError,
        RuntimeError
    ) as error:

        print(f"\nОшибка: {error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())