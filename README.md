# Plaza Vea MCP

[![CI](https://github.com/jeffreymonjacastro/plaza-vea-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/jeffreymonjacastro/plaza-vea-mcp/actions/workflows/ci.yml)

Servidor MCP local para consultar el catalogo publico de
[plazaVea](https://www.plazavea.com.pe/) mediante las APIs publicas de VTEX. Permite buscar,
filtrar, comparar precios, mostrar imagenes dentro de un cliente MCP y generar enlaces para
continuar la compra directamente en Plaza Vea.

Incluye un crawler Scrapy opcional que mantiene un cache SQLite y un historial local de precios.

> Proyecto independiente, sin afiliacion con Plaza Vea, Compania Food Retail S.A.C. ni VTEX.

## Caracteristicas

- Servidor basado exclusivamente en el SDK oficial `mcp`, usando la API de bajo nivel y `stdio`.
- Consultas live-first al catalogo VTEX con respaldo en SQLite.
- Extraccion de todos los SKUs y sellers de cada producto.
- Filtros por nombre parcial y marca exacta, tolerantes a mayusculas y acentos.
- Ordenamiento por precio ascendente, descendente o nombre.
- Imagenes PNG como `ImageContent` para vision del modelo y Markdown para mostrarlas al usuario.
- Enlaces individuales y combinados para agregar productos al carrito.
- Crawler Scrapy respetuoso con `robots.txt`, AutoThrottle, cache HTTP y reintentos.
- Sin Selenium, credenciales, CAPTCHA ni automatizacion del pago.

## Requisitos

- Python 3.12 o 3.13.
- [uv](https://docs.astral.sh/uv/).
- Codex CLI o cualquier cliente compatible con MCP por `stdio`.

## Instalacion

```powershell
git clone https://github.com/jeffreymonjacastro/plaza-vea-mcp.git
cd plaza-vea-mcp
uv sync --all-groups
```

Para registrar el servidor local en Codex desde este checkout:

```powershell
codex mcp add plaza-vea -- uv --directory C:\ruta\a\plaza-vea-mcp run plaza-vea-mcp
codex mcp get plaza-vea
```

Reinicia o abre una nueva tarea de Codex para que las tools aparezcan en la sesion.

## Tools

| Tool | Descripcion |
| --- | --- |
| `search_products` | Filtra por nombre y marca y ordena por precio o nombre. |
| `get_product` | Devuelve todas las variantes, sellers, ofertas e imagenes. |
| `list_brands` | Lista marcas activas, opcionalmente por prefijo. |
| `get_product_image` | Devuelve `ImageContent` PNG y el Markdown necesario para mostrar la imagen en la respuesta. |
| `build_cart_links` | Valida SKUs y genera enlaces para continuar en Plaza Vea. |
| `start_catalog_refresh` | Inicia el crawler local en segundo plano. |
| `get_catalog_refresh_status` | Consulta el progreso y resultado del crawler. |

Ejemplos de solicitudes naturales en Codex:

```text
Busca productos que contengan "leche" y ordenalos del mas barato al mas caro.
Busca cafe de la marca ALTOMAYO y muestra la imagen del producto mas barato.
Genera un enlace de carrito para dos unidades del SKU 12345.
Actualiza la categoria 814 y dime cuando termine.
```

### Respuestas y precios

Los precios se devuelven como enteros en centimos de sol (`price_cents`) y con moneda `PEN`.
Cada consulta indica si la fuente es `live` o `cache`. Cuando se usa el cache, `stale` es `true`.

La version inicial usa el catalogo anonimo del canal de venta `1`. Precio, stock, promociones,
region y entrega se vuelven a validar al abrir Plaza Vea.

### Carrito y pago

`build_cart_links` no abre el navegador ni modifica directamente el carrito. Devuelve:

- La pagina de cada producto.
- El `addToCartLink` oficial proporcionado por VTEX para cada SKU.
- Un enlace combinado para varios SKUs.
- La pagina de checkout de Plaza Vea.

El usuario abre el enlace y completa identificacion, entrega y pago en Plaza Vea. Si el enlace
combinado deja de ser compatible con la tienda, se pueden abrir los enlaces individuales.

El proyecto nunca solicita ni almacena contrasenas, DNI, direcciones o datos de tarjeta.

## Actualizacion del catalogo

Desde MCP, usa `start_catalog_refresh`. Sin `category_id` recorre las categorias hoja del arbol
publico; con un ID solo actualiza esa categoria. La tool devuelve un `run_id` que puede consultarse
con `get_catalog_refresh_status`.

Los datos locales se guardan en `data/catalog.sqlite3`; los logs del crawler quedan en
`data/logs/`. Ambos estan excluidos de Git.

Variables opcionales:

| Variable | Uso |
| --- | --- |
| `PLAZA_VEA_PROJECT_ROOT` | Directorio de trabajo del proyecto. |
| `PLAZA_VEA_DATA_DIR` | Directorio para base de datos, logs y cache HTTP. |
| `PLAZA_VEA_DATABASE_PATH` | Ruta explicita del archivo SQLite. |

## Desarrollo y validacion

```powershell
uv sync --all-groups
uv run ruff check src tests scripts
uv run mypy src
uv run pytest
uv run python scripts/smoke_mcp.py
```

El smoke test inicia el MCP por `stdio`, consulta productos reales, obtiene una imagen y construye
un enlace de carrito. No abre el enlace ni avanza al pago.

## Uso responsable

- Respeta los terminos, disponibilidad y politicas publicadas por Plaza Vea.
- No incrementes la concurrencia ni desactives AutoThrottle sin autorizacion.
- No accedas automaticamente a `/checkout`; esa ruta esta bloqueada en `robots.txt`.
- No uses este proyecto para evadir CAPTCHA, controles de acceso o limites del sitio.
- Las imagenes y datos comerciales pertenecen a sus respectivos titulares.

Consulta [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) para referencias y atribuciones.

## Licencia

Codigo publicado bajo licencia MIT. Esta licencia no concede derechos sobre marcas, imagenes ni
contenido comercial obtenido de Plaza Vea.
