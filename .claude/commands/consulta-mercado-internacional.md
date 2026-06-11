Ejecuta un análisis completo de la actividad del mercado de criptomonedas por sesiones institucionales, usando los datos históricos de trade_alerts y micro_scalp_alerts de la base de datos local.

El análisis debe incluir:

1. **Win rate y retorno promedio por hora UTC** para alertas normales (horizon 60m, outcomes win/partial/loss)
2. **Win rate y PnL promedio por hora UTC** para micro-scalping
3. **Resumen por bloque de sesión institucional**:
   - Asia profunda (00-07 UTC) — Tokio/Shanghái
   - Overlap Asia-Europa (07-09 UTC) — cierre Asia + apertura Europa
   - Europa sola (09-13 UTC) — Frankfurt/Londres sin NY
   - Overlap Europa-US (13-17 UTC) — apertura Wall Street
   - US sola (17-22 UTC) — sesión americana
   - Dead zone (22-00 UTC) — madrugada global
4. **Retorno por hora desglosado entre LONG_FUTURES y SHORT_FUTURES**
5. **Top símbolos por sesión** (min 3 alertas, ordenados por avg retorno)
6. **Hallazgos clave** con mención a:
   - Qué hora UTC tiene el mayor WR y retorno
   - Qué bloque es mejor/peor para micro-scalp
   - Comportamiento en la apertura de Wall Street (13:30-15:30 UTC)
   - Equivalencia en hora México (UTC-6)

Para ejecutar el análisis, escribe y corre un script Python temporal que conecte a la base de datos en `app/config.DATABASE_PATH`, haga las consultas SQL necesarias con `strftime('%H', timestamp)` para agrupar por hora, y elimine el script al terminar. Usa `sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')` para evitar errores de encoding.

Al finalizar, presenta los resultados en tablas markdown ordenadas y un resumen ejecutivo con las recomendaciones horarias más importantes.
