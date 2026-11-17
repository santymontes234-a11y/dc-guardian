# Librerías de terceros (vendorizadas)

Se sirven tal cual desde `/vendor/` (sin CDN en tiempo de ejecución). Copiadas sin modificar
desde el paquete npm indicado (`npm pack <paquete>@<versión>`).

| Librería | Versión | Licencia | Archivo | Origen en el paquete | SHA-256 del archivo |
|---|---|---|---|---|---|
| jsQR (lector de QR) | 1.4.0 | Apache-2.0 | `jsqr-1.4.0/jsQR.js` | `dist/jsQR.js` (UMD; el paquete no publica una versión minificada) | `bc40c8a15196236b2314db0856f72ca0b49980cd5413b8c852a7349f5fee0859` |
| qrcode-generator (generador de QR) | 2.0.4 | MIT | `qrcode-generator-2.0.4/qrcode.mjs` | `dist/qrcode.mjs` (módulo ES) | `ea91d7118a5395289170da848b7c6758b996163bfbccf312591ab65a4911b7c0` |

- `jsqr-1.4.0/LICENSE` es el archivo del paquete.
- El paquete `qrcode-generator` no incluye archivo LICENSE; `qrcode-generator-2.0.4/LICENSE`
  reproduce la licencia MIT declarada en su `package.json` y en la cabecera del archivo.

Para actualizar: descargar con `npm pack` en una carpeta temporal fuera del repo, copiar el
archivo y la licencia a una carpeta nueva con la versión en el nombre y actualizar esta tabla.
