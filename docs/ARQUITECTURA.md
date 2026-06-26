# Arquitectura

## Componentes principales

```text
app/
  config/
  db/
  models/
  scrapers/
  services/
scripts/
data/
docs/
```

## Configuracion YAML

### Reguladores

Archivo:

```text
app/config/regulators.yaml
```

Cada regulador define:

- `short_name`
- `name`
- `country`
- `region`
- `language`
- `url_base`
- `url_news`
- `url_search`
- `search_method`
- `requires_playwright`
- selectores
- filtros de URL y titulo
- `priority`
- `is_active`

### Keywords

Archivo:

```text
app/config/keywords.yaml
```

Incluye keyword original y traducciones por idioma:

- `keyword_en`
- `keyword_es`
- `keyword_pt`
- `keyword_ko`
- `keyword_ar`

## Seed de datos

Script:

```text
scripts/seed_data.py
```

Responsabilidades:

- cargar reguladores desde YAML
- actualizar campos existentes
- sincronizar `is_active`
- desactivar reguladores que ya no esten en YAML
- cargar keywords
- desactivar keywords que ya no esten en YAML

## Base de datos

La base usa SQLAlchemy.

Tablas principales:

- `regulators`
- `keywords`
- `scraping_runs`
- `documents`
- `topics`
- `document_topics`

SQLite es el modo local por defecto. Se puede configurar `DATABASE_PATH` o `DATABASE_URL`.

## Motor de scraping

Servicio principal:

```text
app/services/search_service.py
```

Scrapers:

- `GenericUrlScraper`: requests + BeautifulSoup
- `PlaywrightUrlScraper`: sitios con renderizado JavaScript
- `PlaywrightFormScraper`: formularios de busqueda
- `RssScraper`: feeds RSS/Atom

## Flujo de scraping

1. `run_daily_search.py` crea una sesion de base de datos.
2. `SearchService` obtiene reguladores y keywords activas.
3. Selecciona la keyword segun idioma.
4. Construye URL o usa metodo configurado.
5. Ejecuta scraper.
6. Filtra candidatos de interfaz/navegacion.
7. Abre cada resultado candidato.
8. Valida keyword contra contenido interno.
9. Guarda nuevos documentos.
10. Registra la corrida en `scraping_runs`.

## Dashboard

Script:

```text
scripts/dashboard.py
```

Lee la base configurada y muestra:

- metricas generales
- total por regulador
- total por keyword
- documentos encontrados

El resumen por regulador usa reguladores activos como tabla base y hace LEFT JOIN/merge con resultados filtrados.

## Base demo

Script:

```text
scripts/create_demo_db.py
```

Genera:

```text
data/demo_observatorio.db
```

La demo permite abrir el dashboard sin correr scraping.

## Flujo diario esperado

```bash
python scripts/seed_data.py
python scripts/run_daily_search.py --all --skip-audit
streamlit run scripts/dashboard.py
```

En produccion futura, este flujo deberia ejecutarse desde un scheduler y registrar resultados en PostgreSQL.
