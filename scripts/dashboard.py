from pathlib import Path
import sys

import pandas as pd
import streamlit as st
from sqlalchemy import select

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

from app.db.session import SessionLocal
from app.models.document import Document, DocumentTopic
from app.models.regulator import Regulator
from app.models.topic import Topic


@st.cache_data(ttl=60)
def load_active_regulators() -> pd.DataFrame:
    statement = (
        select(
            Regulator.short_name.label("regulator"),
            Regulator.country.label("country"),
        )
        .where(Regulator.is_active.is_(True))
        .order_by(Regulator.short_name.asc())
    )

    with SessionLocal() as session:
        rows = session.execute(statement).mappings().all()

    return pd.DataFrame(rows, columns=["regulator", "country"])


@st.cache_data(ttl=60)
def load_documents() -> pd.DataFrame:
    statement = (
        select(
            Document.id.label("document_id"),
            Regulator.short_name.label("regulator"),
            Regulator.country.label("country"),
            Document.title.label("title"),
            Document.url.label("url"),
            Document.keyword_matched.label("keyword_matched"),
            Document.extraction_date.label("extraction_date"),
            Document.status.label("status"),
        )
        .join(Regulator, Document.regulator_id == Regulator.id)
        .where(Regulator.is_active.is_(True))
        .order_by(Document.extraction_date.desc().nullslast(), Document.id.desc())
    )

    with SessionLocal() as session:
        rows = session.execute(statement).mappings().all()

    columns = [
        "document_id",
        "regulator",
        "country",
        "title",
        "url",
        "keyword_matched",
        "extraction_date",
        "status",
    ]
    return pd.DataFrame(rows, columns=columns)


@st.cache_data(ttl=60)
def load_document_mechanisms() -> pd.DataFrame:
    dimension = Topic.__table__.alias("dimension")
    statement = (
        select(
            DocumentTopic.document_id.label("document_id"),
            dimension.c.name.label("dimension"),
            Topic.name.label("mechanism"),
        )
        .join(Topic, DocumentTopic.topic_id == Topic.id)
        .join(dimension, Topic.parent_id == dimension.c.id)
    )

    with SessionLocal() as session:
        rows = session.execute(statement).mappings().all()

    return pd.DataFrame(rows, columns=["document_id", "dimension", "mechanism"])


def unique_options(df: pd.DataFrame, column: str) -> list[str]:
    if df.empty or column not in df:
        return []
    return sorted(value for value in df[column].dropna().unique().tolist() if value)


def apply_filters(
    df: pd.DataFrame,
    active_regulators: pd.DataFrame,
    document_mechanisms: pd.DataFrame,
) -> tuple[pd.DataFrame, list[str]]:
    filtered = df.copy()

    with st.sidebar:
        st.header("Filtros")
        regulators = st.multiselect(
            "Regulador",
            unique_options(active_regulators, "regulator"),
        )
        keywords = st.multiselect("Keyword", unique_options(df, "keyword_matched"))
        statuses = st.multiselect("Status", unique_options(df, "status"))

        date_range = None
        if not df.empty and df["extraction_date"].notna().any():
            dates = pd.to_datetime(df["extraction_date"]).dt.date.dropna()
            min_date = dates.min()
            max_date = dates.max()
            date_range = st.date_input(
                "Fecha de extraccion",
                value=(min_date, max_date),
                min_value=min_date,
                max_value=max_date,
            )

        st.subheader("Mecanismos flexibles")
        mechanism_selections: dict[str, list[str]] = {}
        if document_mechanisms.empty:
            st.caption("Sin documentos etiquetados todavia. Corre scripts/tag_documents_by_mechanism.py.")
        else:
            for dimension in sorted(document_mechanisms["dimension"].dropna().unique()):
                options = sorted(
                    document_mechanisms.loc[
                        document_mechanisms["dimension"] == dimension, "mechanism"
                    ].unique()
                )
                mechanism_selections[dimension] = st.multiselect(dimension, options)

    if regulators:
        filtered = filtered[filtered["regulator"].isin(regulators)]
    if keywords:
        filtered = filtered[filtered["keyword_matched"].isin(keywords)]
    if statuses:
        filtered = filtered[filtered["status"].isin(statuses)]
    if date_range and len(date_range) == 2:
        start_date, end_date = date_range
        extraction_dates = pd.to_datetime(filtered["extraction_date"]).dt.date
        filtered = filtered[(extraction_dates >= start_date) & (extraction_dates <= end_date)]

    for dimension, selected_mechanisms in mechanism_selections.items():
        if not selected_mechanisms:
            continue
        matching_ids = document_mechanisms.loc[
            (document_mechanisms["dimension"] == dimension)
            & (document_mechanisms["mechanism"].isin(selected_mechanisms)),
            "document_id",
        ].unique()
        filtered = filtered[filtered["document_id"].isin(matching_ids)]

    return filtered, regulators


def show_metrics(df: pd.DataFrame) -> None:
    total_documents = len(df)
    latest_extraction = "Sin datos"
    if not df.empty and df["extraction_date"].notna().any():
        latest_extraction = pd.to_datetime(df["extraction_date"]).max().strftime("%Y-%m-%d %H:%M")

    col1, col2 = st.columns(2)
    col1.metric("Total documentos", total_documents)
    col2.metric("Ultima extraccion", latest_extraction)


def show_group_totals(
    df: pd.DataFrame,
    active_regulators: pd.DataFrame,
    selected_regulators: list[str],
) -> None:
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Total por regulador")
        regulators_base = active_regulators.copy()
        if selected_regulators:
            regulators_base = regulators_base[regulators_base["regulator"].isin(selected_regulators)]

        counts = df.groupby("regulator", dropna=False).size().reset_index(name="total")
        totals = regulators_base.merge(counts, on="regulator", how="left")
        totals["total"] = totals["total"].fillna(0).astype(int)
        totals = totals[["regulator", "total"]].sort_values("regulator")
        st.dataframe(totals, hide_index=True, use_container_width=True)

    with col2:
        st.subheader("Total por keyword")
        if df.empty:
            st.info("No hay documentos para mostrar.")
        else:
            totals = df.groupby("keyword_matched", dropna=False).size().reset_index(name="total")
            st.dataframe(totals, hide_index=True, use_container_width=True)


def show_documents_table(df: pd.DataFrame) -> None:
    st.subheader("Documentos encontrados")
    if df.empty:
        st.info("No hay documentos que coincidan con los filtros.")
        return

    display_df = df.copy()
    display_df["extraction_date"] = pd.to_datetime(display_df["extraction_date"]).dt.strftime(
        "%Y-%m-%d %H:%M"
    )

    st.dataframe(
        display_df,
        hide_index=True,
        use_container_width=True,
        column_order=[
            "regulator",
            "country",
            "title",
            "url",
            "keyword_matched",
            "extraction_date",
            "status",
        ],
        column_config={
            "regulator": "Regulador",
            "country": "Pais",
            "title": "Titulo",
            "url": st.column_config.LinkColumn("URL"),
            "keyword_matched": "Keyword",
            "extraction_date": "Fecha de extraccion",
            "status": "Status",
        },
    )


def main() -> None:
    st.set_page_config(page_title="Observatorio ANE", layout="wide")
    st.title("Observatorio ANE")

    documents = load_documents()
    active_regulators = load_active_regulators()
    document_mechanisms = load_document_mechanisms()
    filtered_documents, selected_regulators = apply_filters(
        documents, active_regulators, document_mechanisms
    )

    show_metrics(filtered_documents)
    show_group_totals(filtered_documents, active_regulators, selected_regulators)
    show_documents_table(filtered_documents)


if __name__ == "__main__":
    main()
