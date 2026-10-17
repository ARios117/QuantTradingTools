# Quant Terminal

Cuatro herramientas de análisis cuantitativo de mercado que corren íntegramente
en el navegador. Sin cuentas, sin backend y sin telemetría: todo el cálculo
numérico se hace en el cliente sobre series de precios de Yahoo Finance.

| Módulo | Qué hace |
| --- | --- |
| [`analisis-forecast/`](analisis-forecast/) | Ajusta un GARCH(1,1) por máxima verosimilitud sobre los log-retornos y proyecta el precio con 10 000 trayectorias de Monte Carlo, con bandas de confianza y modo backtest. |
| [`analisis-fractal/`](analisis-fractal/) | Regresión lineal sobre el precio con bandas a ±1σ y ±2σ, marcando los cierres que rompen cada banda. |
| [`analisis-anomalia/`](analisis-anomalia/) | Z-score de los log-retornos sobre ventana móvil de 20 barras con umbral a 2σ, en nueve marcos temporales (de 1 minuto a mensual). |
| [`analisis-portafolio/`](analisis-portafolio/) | Optimización media-varianza multi-start sobre más de 60 activos, con frontera eficiente, Sharpe, Calmar, alfa y beta contra el S&P 500. |

El índice en `index.html` enlaza los cuatro módulos y muestra el estado de los datos.

## De dónde salen los datos

Yahoo Finance no envía cabeceras CORS, así que el navegador no puede llamarlo
directamente desde un hosting estático. `assets/js/market-data.js` resuelve cada
serie probando dos fuentes en orden y recordando cuál funciona:

1. **`proxy.php`** — consulta en directo a Yahoo. Solo existe si el sitio se
   sirve desde un hosting con PHP. Cada módulo lleva el suyo.
2. **`data/`** — snapshots JSON versionados en el repositorio. Es lo que sirve
   GitHub Pages. El cliente descarga la serie completa y la recorta al rango
   pedido en local.

Los snapshots cubren cierres diarios desde 1990 para los más de 60 tickers del
catálogo, más los marcos intradía que necesita el detector de anomalías.

### Refrescar los snapshots

El workflow [`refresh-data.yml`](.github/workflows/refresh-data.yml) los
regenera cada día a las 05:40 UTC y hace commit si algo cambió. También se puede
lanzar a mano desde la pestaña *Actions*, o en local:

```bash
python3 scripts/fetch_data.py              # todo
python3 scripts/fetch_data.py --daily      # solo series diarias
python3 scripts/fetch_data.py --intraday   # solo intradía
python3 scripts/fetch_data.py --symbols ^GSPC BTC-USD
```

El script solo usa la librería estándar de Python 3.

### Límites conocidos

Yahoo únicamente sirve ventanas intradía cortas (7 días para velas de 1 minuto,
60 días para las de 5 a 30 minutos). El modo backtest del detector de anomalías
sobre marcos intradía está acotado a esa misma ventana, y la herramienta lo
indica con el rango disponible cuando se pide una fecha anterior. Los marcos
diario, semanal y mensual no tienen esa limitación.

## Desarrollo local

Es un sitio estático; basta con servir la raíz del repositorio:

```bash
python3 -m http.server 8000
# http://localhost:8000
```

Para probar la ruta `proxy.php` hace falta un servidor con PHP
(`php -S localhost:8000`), que es lo que usaría un hosting tradicional.

## Estructura

```
index.html                  Índice de módulos, cinta de cotizaciones y estado de datos
assets/css/terminal.css     Sistema de diseño compartido
assets/js/market-data.js    Capa de datos (proxy.php → snapshots)
analisis-*/index.html       Un módulo por carpeta
analisis-*/proxy.php        Proxy a Yahoo para hosting con PHP
analisis-portafolio/page.css  Estilos propios del optimizador
data/                       Snapshots JSON + manifest.json
scripts/fetch_data.py       Generador de snapshots
```

## Aviso

Material educativo e informativo. Los modelos implementados describen el
comportamiento pasado de una serie de precios y no predicen el futuro. Nada de
lo que producen estas herramientas es una recomendación de inversión.
