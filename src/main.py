import argparse
import os
import sys
import tomli
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


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


def main() -> int:
    parser = create_parser()
    args = parser.parse_args()


    print("Параметры:")
    print(f"package={args.package}")
    print(f"repository={args.repository}")
    print(f"mode={args.mode}")
    print(f"output={args.output}")
    print()

    try:
        cargo_data = load_cargo_toml(
            args.repository,
            args.mode
        )

        dependencies = extract_dependencies(cargo_data)

    except (FileNotFoundError, ValueError, RuntimeError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 1

    print(f"Прямые зависимости пакета '{args.package}':")

    if not dependencies:
        print("  Зависимости отсутствуют.")
    else:
        for dependency in dependencies:
            print(f"  - {dependency}")

    return 0


if __name__ == "__main__":
    sys.exit(main())