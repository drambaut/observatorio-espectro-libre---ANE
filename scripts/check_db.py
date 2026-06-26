from pathlib import Path
import sys

from sqlalchemy import func, select

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

from app.db.session import SessionLocal
from app.models.keyword import Keyword
from app.models.regulator import Regulator


def main() -> None:
    with SessionLocal() as session:
        total_regulators = session.scalar(select(func.count()).select_from(Regulator))
        active_regulators = session.scalar(
            select(func.count()).select_from(Regulator).where(Regulator.is_active.is_(True))
        )
        regulators_by_priority = session.execute(
            select(Regulator.priority, func.count())
            .group_by(Regulator.priority)
            .order_by(Regulator.priority.asc())
        ).all()
        regulators_by_language = session.execute(
            select(Regulator.language, func.count())
            .group_by(Regulator.language)
            .order_by(Regulator.language.asc())
        ).all()
        total_keywords = session.scalar(select(func.count()).select_from(Keyword))
        active_keywords = session.scalar(
            select(func.count()).select_from(Keyword).where(Keyword.is_active.is_(True))
        )
        regulators = session.scalars(
            select(Regulator).order_by(Regulator.priority.asc(), Regulator.short_name.asc())
        ).all()

    print(f"Total reguladores: {total_regulators}")
    print(f"Reguladores activos: {active_regulators}")
    print("")
    print("Reguladores por prioridad:")
    for priority, count in regulators_by_priority:
        priority_label = priority if priority is not None else "sin prioridad"
        print(f"- Prioridad {priority_label}: {count}")
    print("")
    print("Reguladores por idioma:")
    for language, count in regulators_by_language:
        language_label = language or "sin idioma"
        print(f"- {language_label}: {count}")
    print("")
    print(f"Total keywords: {total_keywords}")
    print(f"Keywords activas: {active_keywords}")
    print("")
    print("Reguladores configurados:")
    for regulator in regulators:
        active_label = "activo" if regulator.is_active else "inactivo"
        print(
            f"- {regulator.short_name}: {regulator.name} "
            f"({regulator.country}, {regulator.language}, prioridad {regulator.priority}, {active_label})"
        )


if __name__ == "__main__":
    main()
