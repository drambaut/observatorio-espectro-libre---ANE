# Contexto del Proyecto

## Objetivo

El Observatorio ANE es un MVP para monitorear informacion publica relacionada con uso libre del espectro, equipos exentos de licencia y temas equivalentes en reguladores internacionales.

El foco inicial es apoyar seguimiento diario para la Agencia Nacional del Espectro de Colombia.

## Reguladores activos

Los reguladores activos se definen en `app/config/regulators.yaml` con `is_active: true`.

Al momento de esta version, los activos esperados son:

- itu
- rsm
- acma
- fcc
- imda
- cept
- arcep
- traficom
- comreg
- rdi_nl
- ursec
- tdra

El script `scripts/seed_data.py` sincroniza la base de datos con el YAML y desactiva reguladores antiguos que ya no esten en la configuracion.

## Keywords actuales

Las keywords se definen en `app/config/keywords.yaml`.

Las principales son:

- unlicensed spectrum
- license-exempt
- licence-exempt

El proyecto soporta traducciones por idioma, incluyendo `keyword_ar` para reguladores con `language: "ar"`.

## Logica general del scraping

1. Leer reguladores activos desde base de datos.
2. Leer keywords activas desde base de datos.
3. Elegir la keyword segun idioma del regulador.
4. Ejecutar el metodo configurado:
   - `url`
   - `form`
   - `listing`
   - `rss`
5. Extraer candidatos de resultados.
6. Aplicar filtros basicos de calidad y navegacion.
7. Abrir cada candidato y validar contenido interno.
8. Guardar solo resultados relevantes y no duplicados.

## Validacion profunda

El sistema no guarda un resultado solo porque aparezca en una pagina de busqueda.

Antes de guardar, abre la URL candidata:

- si es HTML, extrae texto principal
- si es PDF, extrae texto con `pypdf`

Luego normaliza el contenido y verifica que aparezcan las palabras principales de la keyword.

Si la keyword es compuesta, como `unlicensed spectrum`, deben aparecer los terminos principales.

## Mecanismos flexibles (dimensiones de analisis)

Se definieron 3 dimensiones para clasificar documentos segun el tipo de mecanismo de
gestion del espectro que discuten, en `app/config/mechanisms.yaml`:

- **Mecanismo de asignacion**: Subasta / PSO / Autorizacion general
- **Tipo de derecho de uso**: Derecho exclusivo / No requiere permiso individual
- **Modelo de pago**: Precio de mercado / Depende de la poblacion cubierta / No existe pago por uso

Estas dimensiones se derivaron de una tabla de referencia (servicios Movil /
Radiodifusion / Uso libre) compartida para el micrositio, a pedido de agregar filtros
por "variables de analisis o dimensiones de los mecanismos flexibles" al observatorio.

`scripts/seed_data.py` sincroniza este YAML contra la tabla `topics` (cada dimension es
un `Topic` padre, cada valor un `Topic` hijo). `scripts/tag_documents_by_mechanism.py`
etiqueta documentos existentes de forma heuristica (coincidencia de texto) creando
registros en `document_topics`.

**Limitacion conocida:** el corpus scrapeado hoy solo cubre documentos sobre "unlicensed
spectrum" / "license-exempt", es decir, el extremo de "uso libre" de la tabla original.
En la practica, casi todos los documentos quedan etiquetados unicamente como "No requiere
permiso individual"; valores como "Subasta", "PSO" o "Derecho exclusivo" no suelen tener
coincidencias reales todavia. Antes de asumir que estos filtros son analiticamente
utiles para el corpus actual, validar con quien pidio los filtros si la intencion era
clasificar el corpus scrapeado (import internacional) o comparar contra el marco
colombiano de la tabla original (que es un dato de referencia distinto, no scrapeado).

## Dashboard

El dashboard en `scripts/dashboard.py` permite ver:

- total de documentos
- ultima extraccion
- total por regulador
- total por keyword
- tabla de documentos
- filtros por regulador, keyword, status, fecha y dimensiones de mecanismos flexibles

La tabla "Total por regulador" parte desde reguladores activos y hace un merge contra resultados filtrados, por lo que muestra reguladores con total 0.

## Limitaciones actuales

- Algunos sitios bloquean automatizacion.
- FCC requiere Google Chrome instalado en el sistema.
- No hay autenticacion ni gestion de usuarios.
- No hay orquestador diario productivo.
- No se descargan adjuntos de forma persistente.
- La base demo contiene datos ficticios de ejemplo.

## Trabajo futuro

- Orquestacion diaria con scheduler.
- Mejor auditoria de relevancia por tema.
- Exportacion de reportes.
- Manejo robusto de sitios bloqueados.
- Integracion con PostgreSQL.
- Dashboard con vistas historicas y alertas.
