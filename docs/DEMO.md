# Demo del Observatorio ANE

Esta guia permite abrir una demostracion sin ejecutar scraping desde cero.

## 1. Clonar e instalar

```bash
git clone <url-del-repo>
cd observatorio-ane
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python -m playwright install chromium
```

## 2. Usar la base demo

Crear la base demo si no existe:

```bash
python scripts/create_demo_db.py
```

Configurar el entorno:

```bash
copy .env.example .env
```

El valor recomendado para demo es:

```env
DATABASE_PATH=data/demo_observatorio.db
```

Tambien se puede ejecutar en PowerShell sin `.env`:

```powershell
$env:DATABASE_PATH="data/demo_observatorio.db"
```

## 3. Abrir dashboard

```bash
streamlit run scripts/dashboard.py
```

## 4. Que se debe ver

El dashboard debe mostrar:

- documentos demo cargados
- total por regulador
- reguladores activos con total 0
- total por keyword
- tabla de documentos con URL clickeable

## 5. Ejecutar scraping manual

Ejemplo con ARCEP:

```bash
python scripts/run_daily_search.py --regulators arcep --keywords "unlicensed spectrum" --max-results-per-query 5 --timeout-seconds 45 --skip-audit
```

Para ver detalles tecnicos de filtros y validacion:

```bash
python scripts/run_daily_search.py --regulators arcep --debug --skip-audit
```

## Nota

`data/demo_observatorio.db` es una base pequena y controlada para demostracion. No representa resultados reales ni sustituye una ejecucion productiva del scraper.
