import argparse
import os
import sys
from urllib.parse import urlparse


def validate_package_name(value: str) -> str:
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
    if not value.strip():
        raise argparse.ArgumentTypeError(
            "URL или путь к репозиторию не может быть пустым."
        )

    # URL
    parsed = urlparse(value)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return value

    # Локальный путь
    if os.path.exists(value):
        return value

    raise argparse.ArgumentTypeError(
        "Указанный URL некорректен или файл/каталог не существует."
    )


def validate_repository_mode(value: str) -> str:
    allowed_modes = {"file", "url"}

    if value not in allowed_modes:
        raise argparse.ArgumentTypeError(
            f"Недопустимый режим: {value}. "
            f"Допустимые значения: {', '.join(sorted(allowed_modes))}"
        )

    return value


def validate_output_file(value: str) -> str:
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


def main() -> int:
    parser = create_parser()
    args = parser.parse_args()

    print(f"package={args.package}")
    print(f"repository={args.repository}")
    print(f"mode={args.mode}")
    print(f"output={args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())