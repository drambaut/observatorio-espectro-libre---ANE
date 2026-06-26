# Observatorio ANE

MVP para un observatorio de la Agencia Nacional del Espectro de Colombia. El proyecto consulta fuentes publicas de reguladores internacionales, guarda documentos relacionados con uso libre/licence-exempt spectrum y permite revisar resultados en un dashboard Streamlit.

La base demo incluida es solo para demostracion. No contiene credenciales, datos privados ni resultados reales de trabajo.

## Requisitos

- Python 3.10+
- SQLite
- Google Chrome instalado si se desea ejecutar FCC con Playwright (`channel="chrome"`)

## Instalacion

```bash
git clone <url-del-repo>
cd observatorio-ane
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python -m playwright install chromium
```

En Linux/macOS:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m playwright install chromium
```

## Variables de entorno

Copiar el ejemplo:

```bash
copy .env.example .env
```

Para abrir el demo sin scraping:

```env
DATABASE_PATH=data/demo_observatorio.db
```

Tambien se puede usar `DATABASE_URL` con cualquier URL compatible con SQLAlchemy. Si `DATABASE_URL` existe, tiene prioridad sobre `DATABASE_PATH`.

## Base demo

Crear o regenerar la base demo limpia:

```bash
python scripts/create_demo_db.py
```

Esto genera:

```text
data/demo_observatorio.db
```

La base demo incluye reguladores activos desde `app/config/regulators.yaml`, keywords activas y documentos publicos ficticios de ejemplo. Algunos reguladores activos quedan sin resultados para validar que el dashboard muestre total 0.

## Crear base local desde cero

Para una base local de trabajo:

```bash
python scripts/init_db.py
python scripts/seed_data.py
python scripts/check_db.py
```

`seed_data.py` sincroniza reguladores y keywords desde YAML. Si un regulador ya no esta en el YAML, se desactiva en la base sin borrarlo.

## Dashboard

Con la base demo:

```bash
set DATABASE_PATH=data/demo_observatorio.db
streamlit run scripts/dashboard.py
```

Con `.env` configurado, basta:

```bash
streamlit run scripts/dashboard.py
```

El dashboard muestra:

- total de documentos
- ultima extraccion
- total por regulador, incluyendo activos con 0 resultados
- total por keyword
- tabla de documentos encontrados

## Ejecutar scraping

Ejecutar los reguladores por defecto:

```bash
python scripts/run_daily_search.py --skip-audit
```

Ejecutar un regulador especifico:

```bash
python scripts/run_daily_search.py --regulators arcep --keywords "unlicensed spectrum" --max-results-per-query 5 --timeout-seconds 45 --skip-audit
```

Ejecutar todos los activos:

```bash
python scripts/run_daily_search.py --all --skip-audit
```

Modo detalle:

```bash
python scripts/run_daily_search.py --regulators arcep --debug --skip-audit
```

## Configuracion

- Reguladores: `app/config/regulators.yaml`
- Keywords: `app/config/keywords.yaml`
- Terminos relacionados para auditoria: `app/config/related_terms.yaml`

Para agregar un regulador, crear una entrada YAML y ejecutar:

```bash
python scripts/seed_data.py
```

## Documentacion

- Demo: `docs/DEMO.md`
- Contexto del proyecto: `docs/CONTEXTO_PROYECTO.md`
- Arquitectura: `docs/ARQUITECTURA.md`

## Advertencias

- No subir `.env` ni bases locales reales.
- La unica base SQLite versionable debe ser `data/demo_observatorio.db`.
- Algunos sitios bloquean automatizacion o requieren Chrome del sistema.
- La validacion actual abre cada resultado candidato y valida la keyword dentro del contenido interno o PDF antes de guardar.
