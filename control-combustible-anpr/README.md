# 🚗⛽ Red Local Industrial con Tecnología ANPR para el Control Automatizado de Combustible Subvencionado

> **Caso Piloto:** Estación de Servicio Jacha Inti S.R.L. (La Paz - Bolivia)  
> **Proyecto Integrador - Universidad Salesiana de Bolivia** (Gestión Académica 2-2026)

![Version](https://img.shields.io/badge/version-v1.0--final-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Python](https://img.shields.io/badge/Python-3.10%2B-informational)
![FastAPI](https://img.shields.io/badge/FastAPI-API%20REST-009688)
![MySQL](https://img.shields.io/badge/MySQL-ACID-blue)
![OpenCV](https://img.shields.io/badge/OpenCV-ANPR-orange)
![Tesseract](https://img.shields.io/badge/Tesseract-OCR-lightgrey)

---

## 📑 Contenido

1. [Integrantes](#-integrantes-del-equipo)
2. [Descripción](#-descripción-del-proyecto)
3. [Capturas del sistema](#-capturas-del-sistema)
4. [Funcionalidades](#-funcionalidades)
5. [Arquitectura y tecnologías](#️-arquitectura-y-pila-tecnológica)
6. [Estructura del proyecto](#-estructura-del-proyecto)
7. [Instalación y ejecución](#-instalación-y-ejecución)
8. [Uso del sistema](#-uso-del-sistema)
9. [API REST](#-api-rest)
10. [Base de datos](#️-base-de-datos)
11. [Pruebas](#-pruebas)
12. [Solución de problemas](#-solución-de-problemas)

---

## 👥 Integrantes del Equipo

* **Castro Vargas Fernando**
* **Chavez Machaca Juan Carlos**
* **Jimenez Quisbert Kevin Jheferson**
* **Luna Tarqui Erick Ivan**
* **Ramos Rojas Cristhian Juan Antonio**

**Docente Guía:** Ing. Juan Gabriel Lazcano Balanza

---

## 📌 Descripción del Proyecto

Este proyecto aborda la problemática de la gestión ineficiente del despacho de combustible subvencionado (*Gasolina Especial* y *Gasolina Especial (+)*). La solución integra:

* una **Red Local Industrial de Baja Latencia (ILAN)**,
* un **motor de Visión Artificial ANPR** que lee la placa del vehículo con OpenCV y Tesseract,
* y una **base de datos transaccional centralizada** que valida el cupo en tiempo real antes de habilitar el surtidor.

El sistema decide en segundos si un vehículo puede cargar (**VERDE**) o debe ser bloqueado (**ROJO**), descuenta los litros del cupo de forma atómica y deja un registro de auditoría de cada intento.

### 🎯 Resultados Clave en Pruebas de Campo

* ⏱️ **Reducción del 68% en tiempo de atención:** de un promedio de 65 segundos a solo **21 segundos** por vehículo.
* 🎯 **Precisión del motor ANPR:** **94.2%** de acierto en la lectura automática de placas (235 lecturas correctas sobre 250 muestras).
* ⚡ **Respuesta transaccional:** consulta de cupos y respuesta de la base de datos en **1.12 segundos** en promedio.
* 📶 **Desempeño de red:** latencia de transmisión de video de **45 ms** mediante políticas QoS y VLANs.

---

## 🖥️ Capturas del sistema

### Panel del Administrador (`/dashboard`)

Indicadores del día, litros despachados en los últimos 7 días, estado de los vehículos, lista desplegable de vehículos registrados e historial de despachos con filtros.

![Panel del administrador](docs/panel-admin.png)

### Panel del Playero (`/surtidor`)

Video en vivo del carril, botón de escaneo de placa, consulta manual de respaldo y estado del sistema (base de datos y cámara).

![Panel del playero](docs/panel-playero.png)

---

## ✨ Funcionalidades

| Módulo | Descripción |
|---|---|
| **Lectura ANPR** | Detecta la región de la placa, la preprocesa y la lee con Tesseract. Valida el formato boliviano (`1234ABC`) y registra la confianza de cada lectura. |
| **Validación de cupo** | Consulta si el vehículo está `HABILITADO`, tiene cupo disponible y no excede la capacidad de su tanque. |
| **Despacho transaccional** | Un procedimiento almacenado descuenta los litros y registra la operación (aprobada o rechazada) en una sola transacción. |
| **Semáforo en pantalla** | Resultado a pantalla completa: verde con datos del vehículo y litros permitidos, o rojo con el motivo del bloqueo. |
| **Login con roles** | Dos perfiles: `ADMIN` (dashboard) y `PLAYERO` (pantalla de despacho). Contraseñas con hash PBKDF2. |
| **Dashboard** | Litros, despachos y rechazos del día, confianza media del OCR, gráfico semanal e historial filtrable por fecha, placa y estado. |
| **Lista de vehículos** | Desplegable con buscador en ambos paneles; en el panel del playero, al elegir un vehículo se copia su placa al campo de consulta. |
| **Cámara IP** | Retransmite el video de un celular (app *IP Webcam*) y usa el último fotograma para el OCR. |
| **Reinicio de cupos** | Evento programado en MySQL que restablece los cupos diarios. |

---

## 🛠️ Arquitectura y Pila Tecnológica

```text
[ Cámara IP / Celular ] --(VLAN 10: video)--> [ Motor ANPR / OpenCV + Tesseract ]
                                                           │
                                             (API REST / FastAPI)
                                                           ▼
[ Pantalla Playero ] <--(VLAN 20: Alertas)--- [ Servidor MySQL (ACID) ]
```

| Capa | Tecnología |
|---|---|
| Backend / API | Python 3.10+, FastAPI, Uvicorn, Pydantic |
| Visión artificial | OpenCV, NumPy, Tesseract OCR (`pytesseract`) |
| Base de datos | MySQL (InnoDB), procedimientos almacenados, pool de conexiones |
| Interfaz | HTML, CSS y JavaScript sin dependencias externas |
| Seguridad | Sesiones por cookie `HttpOnly`, hash PBKDF2-SHA256 |
| Red | Red local industrial con VLANs y QoS |

---

## 📂 Estructura del proyecto

```text
control-combustible-anpr/
├── main.py              # API FastAPI: rutas, cámara, login y dashboard
├── auth.py              # Autenticación, sesiones y control de roles
├── database.py          # Conexión MySQL y llamadas a procedimientos almacenados
├── ocr_engine.py        # Motor ANPR (detección, preprocesado y OCR)
├── config.py            # Lectura de variables de entorno (.env)
├── schemas.py           # Modelos Pydantic de entrada/salida
├── schema.sql           # Tablas, procedimientos, vista, evento y datos de prueba
├── schema_usuarios.sql  # Tabla de usuarios y roles (ejecutar después de schema.sql)
├── test_ocr.py          # Prueba del OCR con imágenes fijas
├── requirements.txt     # Dependencias de Python
├── static/
│   ├── login.html       # Pantalla de ingreso
│   ├── index.html       # Panel del playero
│   └── dashboard.html   # Panel del administrador
├── tests/
│   └── test_database.py # Prueba de conexión y despacho
└── docs/                # Capturas para este README
```

---

## 🚀 Instalación y ejecución

### 1. Requisitos previos

* **Python 3.10 o superior**
* **MySQL 8** (o MariaDB / XAMPP)
* **Tesseract OCR** (programa aparte):
  * Windows: <https://github.com/UB-Mannheim/tesseract/wiki> (ruta típica `C:\Program Files\Tesseract-OCR\tesseract.exe`)
  * Linux: `sudo apt install tesseract-ocr`
* *(Opcional)* Celular con la app **IP Webcam** en la misma red WiFi que la PC.

### 2. Clonar y preparar el entorno

```bash
git clone https://github.com/<tu-usuario>/control-combustible-anpr.git
cd control-combustible-anpr

python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux / macOS

pip install -r requirements.txt
```

### 3. Crear la base de datos

Ejecuta los dos scripts **en este orden**, desde MySQL Workbench, phpMyAdmin o la consola:

```bash
mysql -u root -p < schema.sql
mysql -u root -p < schema_usuarios.sql
```

`schema.sql` crea la base `estacion_jacha_inti` con sus tablas, procedimientos y vehículos de prueba. `schema_usuarios.sql` crea la tabla `usuarios` con los dos usuarios de prueba.

### 4. Configurar el archivo `.env`

Crea un archivo `.env` en la raíz del proyecto, junto a `main.py`:

```env
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=tu_contraseña
DB_NAME=estacion_jacha_inti

# Solo si Tesseract no está en el PATH (Windows)
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe

# Opcional: cámara IP. Si se deja vacío, el video muestra "Sin señal"
CAMARA_URL=http://192.168.0.5:8080/video
```

| Variable | Obligatoria | Descripción |
|---|:---:|---|
| `DB_USER` | ✅ | Usuario de MySQL |
| `DB_PASSWORD` | | Contraseña de MySQL |
| `DB_HOST`, `DB_PORT`, `DB_NAME` | | Por defecto `localhost`, `3306`, `estacion_jacha_inti` |
| `TESSERACT_CMD` | | Ruta de `tesseract.exe` si no está en el PATH |
| `TESSERACT_LANG` | | Idioma del OCR (por defecto `eng`) |
| `CAMARA_URL` | | URL del video de la cámara IP |
| `DB_POOL_SIZE` | | Tamaño del pool de conexiones (por defecto `5`) |

> El archivo `.env` está en el `.gitignore`: no se sube al repositorio.

### 5. Ejecutar

```bash
uvicorn main:app --reload
```

Abre <http://127.0.0.1:8000> e ingresa con un usuario de prueba.

Para usarlo desde otro equipo de la red local (por ejemplo, la pantalla del playero) inicia el servidor con `--host 0.0.0.0` y entra por la IP de la PC.

---

## 👤 Uso del sistema

### Usuarios de prueba

| Usuario | Contraseña | Rol | Destino al ingresar |
|---|---|---|---|
| `admin` | `Admin#2026` | ADMIN | `/dashboard` |
| `playero1` | `Playero#2026` | PLAYERO | `/surtidor` |

> ⚠️ **Cambia estas contraseñas antes de usar el sistema en la estación real.**

### Flujo del playero

1. Ingresa con su usuario y llega a la pantalla del surtidor.
2. Pulsa **Escanear placa** (o escribe la placa y pulsa **Consultar**; también puede elegirla en **Vehículos ▾**).
3. El sistema lee la placa y consulta el cupo:
   * 🟢 **HABILITADO:** muestra propietario, combustible, litros disponibles y capacidad del tanque.
   * 🔴 **BLOQUEADO:** muestra el motivo (no registrado, inhabilitado, cupo agotado, etc.).
4. Si está habilitado, ingresa los litros y pulsa **Confirmar despacho**. Se descuenta el cupo y queda registrado.

### Flujo del administrador

Revisa los indicadores del día, el gráfico semanal, la lista de vehículos y el historial de despachos con filtros. También puede ir a la pantalla del surtidor con el botón **Ir al surtidor**.

### Vehículos de prueba

| Placa | Propietario | Combustible | Disponible | Estado | Resultado esperado |
|---|---|---|---:|---|---|
| `1234ABC` | Juan Perez | Gasolina Especial | 40 L | HABILITADO | ✅ Aprueba |
| `5678DEF` | Maria Lopez | Gasolina Especial (+) | 10 L | HABILITADO | ✅ Aprueba hasta 10 L |
| `3456JKL` | Rosa Quispe | Gasolina Especial | 30 L | INHABILITADO | ❌ Vehículo inhabilitado |
| `9012GHI` | Carlos Mamani | Gasolina Especial | 0 L | CUPO_AGOTADO | ❌ Cupo diario agotado |

Una placa que no esté en la tabla se rechaza con *"Placa no registrada"*.

---

## 🔌 API REST

La documentación interactiva está en <http://127.0.0.1:8000/docs>.

| Método | Ruta | Acceso | Descripción |
|---|---|---|---|
| `POST` | `/api/login` | Público | Inicia sesión |
| `POST` | `/api/logout` | Sesión | Cierra sesión |
| `GET` | `/api/me` | Sesión | Datos del usuario actual |
| `POST` | `/validar` | Sesión | Lee la placa (imagen, cámara o texto manual) y consulta el cupo, **sin descontar** |
| `POST` | `/despachar` | Sesión | Descuenta litros y registra la transacción |
| `GET` | `/api/vehiculos` | Sesión | Lista de vehículos registrados |
| `GET` | `/stream` | Sesión | Video en vivo de la cámara (MJPEG) |
| `GET` | `/api/dashboard/resumen` | ADMIN | Indicadores del día y gráfico semanal |
| `GET` | `/api/dashboard/despachos` | ADMIN | Historial con filtros `desde`, `hasta`, `placa`, `estado`, `pagina` |
| `GET` | `/health` | Público | Estado de la API, la base de datos y la cámara |

---

## 🗄️ Base de datos

| Tabla / objeto | Función |
|---|---|
| `vehiculos` | Placa, propietario, combustible, capacidad del tanque, cupo diario y disponible, estado |
| `despachos` | Auditoría de cada transacción (`APROBADO` / `RECHAZADO`) con motivo |
| `lecturas_anpr` | Cada lectura del OCR con su confianza, para medir la precisión |
| `usuarios` | Cuentas con rol `ADMIN` o `PLAYERO` y hash PBKDF2 |
| `sp_consultar_placa` | Consulta de cupo sin modificar datos |
| `sp_validar_y_despachar` | Valida, descuenta el cupo y registra la operación en una transacción |
| `vw_resumen_diario` | Vista con el resumen diario de transacciones |
| `ev_reiniciar_cupos_diarios` | Evento que restablece los cupos cada día |

**Reglas de bloqueo:** litros inválidos, placa no registrada, vehículo inhabilitado, cupo agotado, litros superiores a la capacidad del tanque o superiores al cupo disponible.

---

## 🧪 Pruebas

**Motor ANPR con imágenes fijas:** coloca fotos en una carpeta `capturas/` nombradas con la placa real (por ejemplo `1234ABC.jpg`) y ejecuta:

```bash
python test_ocr.py            # procesa todas las imágenes y calcula el % de aciertos
python test_ocr.py --debug    # además guarda los recortes en capturas/debug/
```

**Conexión y despacho en la base de datos:**

```bash
python tests/test_database.py
```

> Esta prueba hace un despacho real de 10 L a `1234ABC`; para repetirla, restablece el cupo del vehículo.

---

## 🩺 Solución de problemas

| Síntoma | Causa y solución |
|---|---|
| `Falta la variable de entorno 'DB_USER'` | No existe el `.env` o está en otra carpeta. Debe estar junto a `main.py`. Revisa que no se llame `.env.txt`. |
| `Form data requires "python-multipart"` | Falta la dependencia: `pip install -r requirements.txt`. |
| `Table '...usuarios' doesn't exist` | No se ejecutó `schema_usuarios.sql`. |
| `TesseractNotFoundError` | Instala Tesseract o define `TESSERACT_CMD` en el `.env`. |
| `"mysql" no se reconoce como un comando` | `mysql` no está en el PATH; importa los `.sql` desde MySQL Workbench o phpMyAdmin. |
| Cámara en "sin señal" | Revisa que la app IP Webcam esté abierta con el servidor iniciado, que celular y PC estén en la misma red y que la IP de `CAMARA_URL` sea la correcta. |
| El login pide ingresar de nuevo | Las sesiones se guardan en memoria y se pierden al reiniciar el servidor (también con `--reload`). |

---

## 📄 Licencia

Distribuido bajo la licencia **MIT**. Agrega un archivo `LICENSE` en la raíz del repositorio con el texto de la licencia.