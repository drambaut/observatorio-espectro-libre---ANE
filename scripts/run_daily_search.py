from pathlib import Path
import argparse
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

from app.db.session import SessionLocal
from app.services.search_service import SearchService

DEFAULT_REGULATORS = {"ofcom", "rsm", "acma"}
DEFAULT_MAX_RESULTS_PER_QUERY = 10
DEFAULT_TIMEOUT_SECONDS = 30


def parse_list_arg(values: list[str] | None) -> set[str] | None:
    if not values:
        return None

    parsed: set[str] = set()
    for value in values:
        for item in value.split(","):
            normalized = item.strip().lower()
            if normalized:
                parsed.add(normalized)
    return parsed or None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ejecuta busquedas diarias del Observatorio ANE.")
    parser.add_argument(
        "--regulators",
        nargs="+",
        default=sorted(DEFAULT_REGULATORS),
        help="Lista de short_name separada por espacios o comas. Por defecto: ofcom rsm acma.",
    )
    parser.add_argument(
        "--keywords",
        nargs="+",
        default=None,
        help="Keywords originales a ejecutar, separadas por espacios o comas. Por defecto: todas activas.",
    )
    parser.add_argument(
        "--max-results-per-query",
        type=int,
        default=DEFAULT_MAX_RESULTS_PER_QUERY,
        help="Maximo de resultados validos por busqueda. Por defecto: 10.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Limite aproximado por regulador en segundos. Por defecto: 30.",
    )
    parser.add_argument(
        "--skip-audit",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="No ejecuta auditoria desde el scraping principal. Por defecto: true.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Procesa todos los reguladores activos compatibles con search_method=url.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Muestra logs detallados de filtros, validacion interna y descartes.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    regulator_short_names = None
    if not args.all:
        regulator_short_names = parse_list_arg(args.regulators)
    keyword_originals = parse_list_arg(args.keywords)

    if args.skip_audit:
        print("Auditoria automatica: omitida (--skip-audit=true)")

    with SessionLocal() as session:
        service = SearchService(
            session=session,
            regulator_short_names=regulator_short_names,
            keyword_originals=keyword_originals,
            max_results_per_query=args.max_results_per_query,
            timeout_seconds=args.timeout_seconds,
            debug=args.debug,
        )
        summary = service.run()

    print("\nResumen de ejecucion")
    print(f"Total reguladores procesados: {summary.total_regulators_processed}")
    print(f"Total keywords usadas: {summary.total_keywords_used}")
    print(f"Total resultados validos: {summary.total_found}")
    print(f"Total nuevos guardados: {summary.total_saved}")
    print(f"Total duplicados: {summary.total_duplicates}")
    print("Resultados por regulador:")
    for regulator, result in summary.results_by_regulator.items():
        strategies = ", ".join(sorted(result.strategies)) or "sin estrategia"
        print(
            f"- {regulator}: estrategia={strategies}, crudos={result.raw_found}, "
            f"validos={result.valid_found}, descartados={result.discarded}, "
            f"nuevos={result.saved}, duplicados={result.duplicates}"
        )
    print("Errores por regulador:")
    if not summary.errors_by_regulator:
        print("- Ninguno")
    else:
        for regulator, errors in summary.errors_by_regulator.items():
            print(f"- {regulator}: {'; '.join(errors)}")


if __name__ == "__main__":
    main()
