-- =====================================================================
-- SISTEMA ANPR - CONTROL DE COMBUSTIBLE SUBVENCIONADO
-- Estación de Servicio Jacha Inti S.R.L. (La Paz, Bolivia)
-- Requiere MySQL 8.0.16+ (CHECK constraints)
-- Importar con:  mysql -u root -p < schema.sql
-- =====================================================================

CREATE DATABASE IF NOT EXISTS estacion_jacha_inti
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE estacion_jacha_inti;

-- ---------------------------------------------------------------------
-- 1. VEHÍCULOS AUTORIZADOS
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS vehiculos (
    placa                   VARCHAR(10)   NOT NULL,
    propietario             VARCHAR(100)  NOT NULL,
    ci_propietario          VARCHAR(20)   NOT NULL,
    tipo_combustible        ENUM('Gasolina Especial', 'Gasolina Especial (+)') NOT NULL,
    capacidad_tanque_litros DECIMAL(5,2)  NOT NULL,
    cupo_diario_litros      DECIMAL(5,2)  NOT NULL,
    cupo_disponible_litros  DECIMAL(5,2)  NOT NULL,
    estado                  ENUM('HABILITADO', 'INHABILITADO', 'CUPO_AGOTADO')
                            NOT NULL DEFAULT 'HABILITADO',
    fecha_registro          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fecha_actualizacion     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP
                            ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (placa),                       -- la PK ya es un índice B-Tree
    INDEX idx_ci_propietario (ci_propietario), -- un propietario puede tener varios vehículos

    CONSTRAINT chk_placa_formato
        CHECK (placa REGEXP '^[0-9]{3,4}[A-Z]{3}$'),   -- ej: 1234ABC (ajustar si hay placas antiguas)
    CONSTRAINT chk_capacidad  CHECK (capacidad_tanque_litros > 0),
    CONSTRAINT chk_cupo_diario CHECK (cupo_diario_litros >= 0),
    CONSTRAINT chk_cupo_disp
        CHECK (cupo_disponible_litros >= 0 AND cupo_disponible_litros <= cupo_diario_litros)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 2. DESPACHOS (AUDITORÍA)
--    Sin FOREIGN KEY a propósito: así también se registran intentos con
--    placas NO registradas u OCR erróneos. Además, evita que un borrado
--    de vehículo destruya el historial.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS despachos (
    id                 INT           NOT NULL AUTO_INCREMENT,
    placa              VARCHAR(10)   NOT NULL,
    litros_despachados DECIMAL(5,2)  NOT NULL,
    fecha_hora         DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    surtidor_id        INT           NOT NULL DEFAULT 1,
    estado_transaccion ENUM('APROBADO', 'RECHAZADO') NOT NULL,
    motivo_rechazo     VARCHAR(255)  NULL,

    PRIMARY KEY (id),
    INDEX idx_despacho_placa_fecha (placa, fecha_hora),
    INDEX idx_fecha (fecha_hora),

    CONSTRAINT chk_litros CHECK (litros_despachados >= 0)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 3. LECTURAS ANPR
--    Registra cada lectura del OCR (para medir la precisión >= 90%
--    y depurar errores de Tesseract).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lecturas_anpr (
    id            INT           NOT NULL AUTO_INCREMENT,
    placa_leida   VARCHAR(20)   NOT NULL,
    confianza     DECIMAL(5,2)  NULL,          -- confianza de Tesseract (0-100)
    imagen_ruta   VARCHAR(255)  NULL,          -- captura guardada (opcional)
    fecha_hora    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    validada_ok   BOOLEAN       NULL,          -- ¿el operador confirmó que la lectura fue correcta?

    PRIMARY KEY (id),
    INDEX idx_lectura_fecha (fecha_hora)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 4. PROCEDIMIENTOS ALMACENADOS
-- ---------------------------------------------------------------------
DELIMITER $$

-- 4.1 Consulta rápida (NO descuenta): para el endpoint /validar
DROP PROCEDURE IF EXISTS sp_consultar_placa $$
CREATE PROCEDURE sp_consultar_placa(IN p_placa VARCHAR(10))
BEGIN
    SET p_placa = UPPER(TRIM(p_placa));

    SELECT placa, propietario, tipo_combustible,
           capacidad_tanque_litros, cupo_diario_litros,
           cupo_disponible_litros, estado,
           (estado = 'HABILITADO' AND cupo_disponible_litros > 0) AS puede_despachar
    FROM vehiculos
    WHERE placa = p_placa;
END $$

-- 4.2 Validar y despachar (transaccional): para el endpoint /despachar
DROP PROCEDURE IF EXISTS sp_validar_y_despachar $$
CREATE PROCEDURE sp_validar_y_despachar(
    IN  p_placa          VARCHAR(10),
    IN  p_litros         DECIMAL(5,2),
    IN  p_surtidor       INT,
    OUT p_autorizado     BOOLEAN,
    OUT p_motivo         VARCHAR(255),
    OUT p_cupo_restante  DECIMAL(5,2)
)
proc: BEGIN
    DECLARE v_estado      VARCHAR(20)  DEFAULT NULL;
    DECLARE v_disponible  DECIMAL(5,2) DEFAULT 0;
    DECLARE v_capacidad   DECIMAL(5,2) DEFAULT 0;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        SET p_autorizado    = FALSE;
        SET p_motivo        = 'Error interno del sistema';
        SET p_cupo_restante = NULL;
    END;

    SET p_placa    = UPPER(TRIM(p_placa));
    SET p_surtidor = IFNULL(p_surtidor, 1);
    SET p_motivo   = NULL;

    START TRANSACTION;

    -- Bloquea la fila: evita doble descuento si llegan 2 peticiones a la vez
    SELECT estado, cupo_disponible_litros, capacidad_tanque_litros
      INTO v_estado, v_disponible, v_capacidad
      FROM vehiculos
     WHERE placa = p_placa
       FOR UPDATE;

    -- Reglas de validación (en orden de prioridad)
    IF p_litros IS NULL OR p_litros <= 0 THEN
        SET p_motivo = 'Cantidad de litros inválida';
    ELSEIF v_estado IS NULL THEN
        SET p_motivo = 'Placa no registrada';
    ELSEIF v_estado = 'INHABILITADO' THEN
        SET p_motivo = 'Vehículo inhabilitado';
    ELSEIF v_estado = 'CUPO_AGOTADO' OR v_disponible <= 0 THEN
        SET p_motivo = 'Cupo diario agotado';
    ELSEIF p_litros > v_capacidad THEN
        SET p_motivo = CONCAT('Excede la capacidad del tanque (', v_capacidad, ' L)');
    ELSEIF p_litros > v_disponible THEN
        SET p_motivo = CONCAT('Cupo insuficiente. Disponible: ', v_disponible, ' L');
    END IF;

    IF p_motivo IS NOT NULL THEN
        -- RECHAZADO
        INSERT INTO despachos (placa, litros_despachados, surtidor_id, estado_transaccion, motivo_rechazo)
        VALUES (p_placa, IFNULL(p_litros, 0), p_surtidor, 'RECHAZADO', p_motivo);

        SET p_autorizado    = FALSE;
        SET p_cupo_restante = IF(v_estado IS NULL, NULL, v_disponible);
    ELSE
        -- APROBADO: descuenta cupo y actualiza estado si llega a 0
        UPDATE vehiculos
           SET cupo_disponible_litros = cupo_disponible_litros - p_litros,
               estado = IF(cupo_disponible_litros - p_litros <= 0, 'CUPO_AGOTADO', estado)
         WHERE placa = p_placa;

        INSERT INTO despachos (placa, litros_despachados, surtidor_id, estado_transaccion)
        VALUES (p_placa, p_litros, p_surtidor, 'APROBADO');

        SET p_autorizado    = TRUE;
        SET p_cupo_restante = v_disponible - p_litros;
    END IF;

    COMMIT;
END $$

DELIMITER ;

-- ---------------------------------------------------------------------
-- 5. REINICIO DIARIO DE CUPOS (medianoche)
--    Requiere:  SET GLOBAL event_scheduler = ON;
--    Usa la zona horaria del servidor: verificar que sea America/La_Paz (UTC-4).
--    No toca vehículos INHABILITADOS.
-- ---------------------------------------------------------------------
DROP EVENT IF EXISTS ev_reiniciar_cupos_diarios;
CREATE EVENT ev_reiniciar_cupos_diarios
    ON SCHEDULE EVERY 1 DAY
    STARTS (CURRENT_DATE + INTERVAL 1 DAY)
    DO
        UPDATE vehiculos
           SET cupo_disponible_litros = cupo_diario_litros,
               estado = 'HABILITADO'
         WHERE estado IN ('HABILITADO', 'CUPO_AGOTADO');

-- ---------------------------------------------------------------------
-- 6. VISTA: RESUMEN DIARIO (útil para reportes)
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW vw_resumen_diario AS
SELECT DATE(fecha_hora)                                          AS fecha,
       COUNT(*)                                                  AS total_transacciones,
       SUM(estado_transaccion = 'APROBADO')                      AS aprobadas,
       SUM(estado_transaccion = 'RECHAZADO')                     AS rechazadas,
       SUM(IF(estado_transaccion = 'APROBADO', litros_despachados, 0)) AS litros_despachados
FROM despachos
GROUP BY DATE(fecha_hora);

-- ---------------------------------------------------------------------
-- 7. DATOS DE PRUEBA
-- ---------------------------------------------------------------------
INSERT INTO vehiculos
(placa, propietario, ci_propietario, tipo_combustible, capacidad_tanque_litros,
 cupo_diario_litros, cupo_disponible_litros, estado)
VALUES
('1234ABC', 'Juan Perez',    '6543210', 'Gasolina Especial',     45.00, 40.00, 40.00, 'HABILITADO'),
('5678DEF', 'Maria Lopez',   '7890123', 'Gasolina Especial (+)', 50.00, 50.00, 10.00, 'HABILITADO'),
('9012GHI', 'Carlos Mamani', '4321098', 'Gasolina Especial',     40.00, 30.00,  0.00, 'CUPO_AGOTADO'),
('3456JKL', 'Rosa Quispe',   '5432109', 'Gasolina Especial',     35.00, 30.00, 30.00, 'INHABILITADO')
ON DUPLICATE KEY UPDATE propietario = VALUES(propietario);

-- ---------------------------------------------------------------------
-- 8. PRUEBAS RÁPIDAS (descomentar para probar)
-- ---------------------------------------------------------------------
-- CALL sp_validar_y_despachar('1234ABC', 20, 1, @ok, @motivo, @resto);  -- APROBADO
-- SELECT @ok, @motivo, @resto;
-- CALL sp_validar_y_despachar('9012GHI', 10, 1, @ok, @motivo, @resto);  -- RECHAZADO (cupo agotado)
-- SELECT @ok, @motivo, @resto;
-- CALL sp_validar_y_despachar('0000XXX', 10, 1, @ok, @motivo, @resto);  -- RECHAZADO (no registrada)
-- SELECT @ok, @motivo, @resto;
-- SELECT * FROM despachos;