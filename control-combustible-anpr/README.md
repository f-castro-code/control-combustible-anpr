# RED LOCAL INDUSTRIAL CON TECNOLOGÍA ANPR PARA EL CONTROL AUTOMATIZADO DE COMBUSTIBLE SUBVENCIONADO

> **Caso Piloto:** Estación de Servicio Jacha Inti S.R.L. (La Paz - Bolivia)  
> **Proyecto Integrador - Universidad Salesiana de Bolivia** (Gestión Académica 2-2026)

![Version](https://img.shields.io/badge/version-v1.0--final-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Python](https://img.shields.io/badge/Python-3.10%2B-informational)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-ACID-blue)
![OpenCV](https://img.shields.io/badge/OpenCV-ANPR-orange)

---

## 👥 Integrantes del Equipo

* **Castro Vargas Fernando** 
* **Chavez Machaca Juan Carlos**
* **Jimenez Quisbert Kevin Jheferson**
* **Luna Tarqui Erick Ivan**
* **Ramos Rojas Cristhian Juan Antonio** 

* **Docente Guía:** Ing. Juan Gabriel Lazcano Balanza

---

## 📌 Descripción del Proyecto

Este proyecto aborda la problemática de la gestión ineficiente del despacho de combustible subvencionado (*Gasolina Especial y Gasolina Especial (+)*). La solución integra una **Red Local Industrial de Baja Latencia (ILAN)**, un **motor de Visión Artificial ANPR** para la lectura de matrículas y una **base de datos transaccional centralizada** que valida los cupos en tiempo real antes de habilitar el surtidor.

### 🎯 Resultados Clave en Pruebas de Campo
* ⏱️ **Reducción del 68% en tiempo de atención:** Pasando de un promedio de 65 segundos a solo **21 segundos** por vehículo.
* 🎯 **Precisión del motor ANPR:** **94.2%** de acierto en la lectura automática de placas (235 lecturas correctas sobre 250 muestras).
* ⚡ **Respuesta Transaccional:** Consulta de cupos y respuesta en base de datos en **1.12 segundos** promedio[cite: 1].
* 📶 **Desempeño de Red:** Latencia de transmisión de video a **45 ms** mediante políticas QoS y VLANs[cite: 1].

---

## 🛠️ Arquitectura y Pila Tecnológica

```text
[ Cámara IP / Celular ] --(VLAN 10: RTSP)--> [ Motor ANPR / OpenCV + Tesseract ]
                                                           │
                                             (API REST / FastAPI)
                                                           ▼
[ Pantalla Playero ] <--(VLAN 20: Alertas)--- [ Servidor PostgreSQL (ACID) ]