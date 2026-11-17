# Scripts de generación de los entregables

Scripts auxiliares usados el 15-11-2026 para producir los entregables. No forman parte del código del proyecto.

| Script | Qué hace |
|---|---|
| `demo_flow.py` | Carga un escenario de demostración en un servidor **aislado** en modo simulación (BD temporal, puerto 8765) |
| `shots.py` | Toma las capturas de `capturas/` con Playwright + Chromium sin interfaz |
| `charts.py` | Genera los gráficos de `graficos/` a partir de los CSV agregados |
| `diagrams.py` | Genera los diagramas de `diagramas/` (HTML/SVG → PNG) |
| `build_deck.js` | Construye la presentación con pptxgenjs (variables `ROOT`, `GEN`, `SKILL_DIR`) |
| `animate.py` | Inyecta las animaciones de entrada y las transiciones (OOXML `p:timing` / `p:transition`) |
| `md2docx.js` | Convierte `reporte_tecnico.md` en `reporte_tecnico.docx` (docx + marked) |

Los PDF se exportaron con LibreOffice en modo *headless*. Los CSV de `graficos/` se extrajeron en solo lectura de `data/dcguardian.db`, agregados y sin datos personales.
