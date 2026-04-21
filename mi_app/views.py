from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db import connection, DatabaseError, transaction
from django.shortcuts import render, redirect
from django.conf import settings
from django.utils import timezone
import json
import os
import uuid
from datetime import datetime


# Ponderación de calificación final
PESO_EVALUACION_MANUAL = 0.70
PESO_ENTREGABLES = 0.30


def _usuario_disponible(cursor, usuario):
    cursor.execute("SELECT COUNT(*) FROM Estudiantes WHERE usuario = %s", [usuario])
    existe_estudiante = cursor.fetchone()[0] > 0

    cursor.execute("SELECT COUNT(*) FROM Instructores WHERE usuario = %s", [usuario])
    existe_instructor = cursor.fetchone()[0] > 0

    cursor.execute("SELECT COUNT(*) FROM auth_user WHERE username = %s", [usuario])
    existe_admin = cursor.fetchone()[0] > 0

    return not (existe_estudiante or existe_instructor or existe_admin)


def _usuario_disponible_para_actualizacion(cursor, usuario, instructor_id):
    cursor.execute(
        "SELECT COUNT(*) FROM Instructores WHERE usuario = %s AND instructor_id <> %s",
        [usuario, instructor_id]
    )
    existe_otro_instructor = cursor.fetchone()[0] > 0

    cursor.execute("SELECT COUNT(*) FROM Estudiantes WHERE usuario = %s", [usuario])
    existe_estudiante = cursor.fetchone()[0] > 0

    cursor.execute("SELECT COUNT(*) FROM auth_user WHERE username = %s", [usuario])
    existe_admin = cursor.fetchone()[0] > 0

    return not (existe_otro_instructor or existe_estudiante or existe_admin)


def _usuario_disponible_para_actualizacion_estudiante(cursor, usuario, estudiante_id):
    cursor.execute(
        "SELECT COUNT(*) FROM Estudiantes WHERE usuario = %s AND estudiante_id <> %s",
        [usuario, estudiante_id]
    )
    existe_otro_estudiante = cursor.fetchone()[0] > 0

    cursor.execute("SELECT COUNT(*) FROM Instructores WHERE usuario = %s", [usuario])
    existe_instructor = cursor.fetchone()[0] > 0

    cursor.execute("SELECT COUNT(*) FROM auth_user WHERE username = %s", [usuario])
    existe_admin = cursor.fetchone()[0] > 0

    return not (existe_otro_estudiante or existe_instructor or existe_admin)

@csrf_exempt
def login(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        usuario = (data.get('usuario') or '').strip()
        contrasena = data.get('contrasena') or ''

        if not usuario or not contrasena:
            return JsonResponse({'success': False, 'message': 'Credenciales inválidas'})
        
        # Buscar en Instructores
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT instructor_id, nombre_completo
                FROM Instructores
                WHERE usuario = %s
                  AND estado = 'activo'
                  AND CONVERT(VARCHAR(MAX), DECRYPTBYPASSPHRASE('clave123', contrasena)) = %s
            """, [usuario, contrasena])
            row = cursor.fetchone()
            if row:
                return JsonResponse({'success': True, 'instructor_id': row[0], 'nombre': row[1], 'role': 'instructor', 'redirect': '/instructor-dashboard/'})
        
        # Buscar en Admin (auth_user con is_staff o is_superuser)
        from django.contrib.auth.hashers import check_password
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT id, username, password FROM auth_user WHERE username = %s AND (is_staff = 1 OR is_superuser = 1)
            """, [usuario])
            row = cursor.fetchone()
            if row:
                try:
                    if check_password(contrasena, row[2]):
                        return JsonResponse({'success': True, 'admin_id': row[0], 'nombre': row[1], 'role': 'admin', 'redirect': '/admin-dashboard/'})
                except (ValueError, TypeError):
                    pass
        
        # Buscar en Estudiantes
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT estudiante_id, nombre_completo
                FROM Estudiantes
                WHERE usuario = %s
                  AND CONVERT(VARCHAR(MAX), DECRYPTBYPASSPHRASE('clave123', contrasena)) = %s
            """, [usuario, contrasena])
            row = cursor.fetchone()
            if row:
                return JsonResponse({'success': True, 'estudiante_id': row[0], 'nombre': row[1], 'role': 'estudiante', 'redirect': '/estudiante-dashboard/'})
        
        return JsonResponse({'success': False, 'message': 'Credenciales inválidas'})
    return JsonResponse({'error': 'Método no permitido'})

@csrf_exempt
def estudiantes_list(request):
    if request.method == 'GET':
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT estudiante_id, nombre_completo, 
                       CASE
                           WHEN DECRYPTBYPASSPHRASE('clave123', email) IS NOT NULL
                               THEN CONVERT(VARCHAR(MAX), DECRYPTBYPASSPHRASE('clave123', email))
                           ELSE CONVERT(VARCHAR(MAX), email)
                       END AS email,
                       telefono, direccion, tipo_documento,
                       CASE
                           WHEN DECRYPTBYPASSPHRASE('clave123', numero_documento) IS NOT NULL
                               THEN CONVERT(VARCHAR(MAX), DECRYPTBYPASSPHRASE('clave123', numero_documento))
                           ELSE CONVERT(VARCHAR(MAX), numero_documento)
                       END AS numero_documento,
                       usuario,
                       fecha_registro
                FROM Estudiantes
            """)
            rows = cursor.fetchall()
            estudiantes = []
            for row in rows:
                estudiantes.append({
                    'estudiante_id': row[0],
                    'nombre_completo': row[1],
                    'email': row[2],
                    'telefono': row[3],
                    'direccion': row[4],
                    'tipo_documento': row[5],
                    'numero_documento': row[6],
                    'usuario': row[7],
                    'fecha_registro': str(row[8])
                })
            return JsonResponse(estudiantes, safe=False)
    return JsonResponse({'error': 'Método no permitido'})

@csrf_exempt
def estudiantes_create(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        nombre_completo = (data.get('nombre_completo') or '').strip()
        email = (data.get('email') or '').strip()
        telefono = (data.get('telefono') or '').strip()
        direccion = (data.get('direccion') or '').strip()
        tipo_documento = (data.get('tipo_documento') or '').strip()
        numero_documento = (data.get('numero_documento') or '').strip()
        usuario = (data.get('usuario') or '').strip()
        contrasena = data.get('contrasena') or ''

        if not nombre_completo or not email or not tipo_documento or not numero_documento or not usuario or not contrasena:
            return JsonResponse({'success': False, 'message': 'Faltan campos requeridos'})

        try:
            with connection.cursor() as cursor:
                if not _usuario_disponible(cursor, usuario):
                    return JsonResponse({'success': False, 'message': 'El usuario ya existe, elige otro'})

                cursor.execute(
                    "EXEC RegistrarEstudiante %s, %s, %s, %s, %s, %s",
                    [nombre_completo, email, telefono, direccion, tipo_documento, numero_documento]
                )

                cursor.execute(
                    """
                    SELECT TOP 1 estudiante_id
                    FROM Estudiantes
                                        WHERE nombre_completo = %s
                      AND (
                          CONVERT(VARCHAR(MAX), DECRYPTBYPASSPHRASE('clave123', email)) = %s
                          OR CONVERT(VARCHAR(MAX), email) = %s
                      )
                      AND (
                          CONVERT(VARCHAR(MAX), DECRYPTBYPASSPHRASE('clave123', numero_documento)) = %s
                          OR CONVERT(VARCHAR(MAX), numero_documento) = %s
                      )
                                        ORDER BY fecha_registro DESC, estudiante_id DESC
                    """,
                    [nombre_completo, email, email, numero_documento, numero_documento]
                )
                row = cursor.fetchone()
                if not row:
                    return JsonResponse({'success': False, 'message': 'No fue posible obtener el estudiante creado'})

                estudiante_id = row[0]

                cursor.execute(
                    """
                    UPDATE Estudiantes
                    SET usuario = %s,
                        contrasena = ENCRYPTBYPASSPHRASE('clave123', %s)
                    WHERE estudiante_id = %s
                    """,
                    [usuario, contrasena, estudiante_id]
                )

            return JsonResponse({
                'success': True,
                'message': 'Estudiante registrado correctamente',
                'estudiante_id': estudiante_id
            })
        except DatabaseError as e:
            return JsonResponse({'success': False, 'message': f'Error creando estudiante: {str(e)}'})
    return JsonResponse({'error': 'Método no permitido'})


@csrf_exempt
def estudiantes_update(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        estudiante_id = data.get('estudiante_id')
        nombre_completo = (data.get('nombre_completo') or '').strip()
        email = (data.get('email') or '').strip()
        telefono = (data.get('telefono') or '').strip()
        direccion = (data.get('direccion') or '').strip()
        tipo_documento = (data.get('tipo_documento') or '').strip()
        numero_documento = (data.get('numero_documento') or '').strip()
        usuario = (data.get('usuario') or '').strip()
        contrasena = data.get('contrasena') or ''

        if not estudiante_id or not usuario:
            return JsonResponse({'success': False, 'message': 'Se requieren estudiante_id y usuario'})

        try:
            estudiante_id = int(estudiante_id)
        except ValueError:
            return JsonResponse({'success': False, 'message': 'ID de estudiante inválido'})

        try:
            with connection.cursor() as cursor:
                if not _usuario_disponible_para_actualizacion_estudiante(cursor, usuario, estudiante_id):
                    return JsonResponse({'success': False, 'message': 'El usuario ya existe, elige otro'})

                es_actualizacion_completa = bool(nombre_completo and email and tipo_documento and numero_documento)

                if not es_actualizacion_completa:
                    if contrasena.strip():
                        cursor.execute(
                            """
                            UPDATE Estudiantes
                            SET usuario = %s,
                                contrasena = ENCRYPTBYPASSPHRASE('clave123', %s)
                            WHERE estudiante_id = %s
                            """,
                            [usuario, contrasena, estudiante_id]
                        )
                    else:
                        cursor.execute(
                            """
                            UPDATE Estudiantes
                            SET usuario = %s
                            WHERE estudiante_id = %s
                            """,
                            [usuario, estudiante_id]
                        )
                elif contrasena.strip():
                    cursor.execute(
                        """
                        UPDATE Estudiantes
                        SET nombre_completo = %s,
                            email = ENCRYPTBYPASSPHRASE('clave123', %s),
                            telefono = %s,
                            direccion = %s,
                            tipo_documento = %s,
                            numero_documento = ENCRYPTBYPASSPHRASE('clave123', %s),
                            usuario = %s,
                            contrasena = ENCRYPTBYPASSPHRASE('clave123', %s)
                        WHERE estudiante_id = %s
                        """,
                        [
                            nombre_completo,
                            email,
                            telefono or None,
                            direccion or None,
                            tipo_documento,
                            numero_documento,
                            usuario,
                            contrasena,
                            estudiante_id
                        ]
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE Estudiantes
                        SET nombre_completo = %s,
                            email = ENCRYPTBYPASSPHRASE('clave123', %s),
                            telefono = %s,
                            direccion = %s,
                            tipo_documento = %s,
                            numero_documento = ENCRYPTBYPASSPHRASE('clave123', %s),
                            usuario = %s
                        WHERE estudiante_id = %s
                        """,
                        [
                            nombre_completo,
                            email,
                            telefono or None,
                            direccion or None,
                            tipo_documento,
                            numero_documento,
                            usuario,
                            estudiante_id
                        ]
                    )

                if cursor.rowcount == 0:
                    return JsonResponse({'success': False, 'message': 'Estudiante no encontrado'})

            return JsonResponse({'success': True, 'message': 'Estudiante actualizado correctamente'})
        except DatabaseError as e:
            return JsonResponse({'success': False, 'message': f'Error actualizando estudiante: {str(e)}'}, status=500)

    return JsonResponse({'error': 'Método no permitido'})


@csrf_exempt
def estudiantes_delete(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        estudiante_id = data.get('estudiante_id')

        if not estudiante_id:
            return JsonResponse({'success': False, 'message': 'Se requiere estudiante_id'})

        try:
            estudiante_id = int(estudiante_id)
        except ValueError:
            return JsonResponse({'success': False, 'message': 'ID de estudiante inválido'})

        try:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM Estudiantes WHERE estudiante_id = %s", [estudiante_id])

                if cursor.rowcount == 0:
                    return JsonResponse({'success': False, 'message': 'Estudiante no encontrado'})

            return JsonResponse({'success': True, 'message': 'Estudiante eliminado correctamente'})
        except DatabaseError:
            return JsonResponse({'success': False, 'message': 'No se puede eliminar el estudiante porque tiene registros relacionados'})

    return JsonResponse({'error': 'Método no permitido'})


@csrf_exempt
def instructores_create(request):
    """Crea un instructor con usuario y contraseña cifrada."""
    if request.method == 'POST':
        data = json.loads(request.body)
        nombre_completo = (data.get('nombre_completo') or '').strip()
        especialidad = (data.get('especialidad') or '').strip()
        cedula_profesional = (data.get('cedula_profesional') or '').strip()
        usuario = (data.get('usuario') or '').strip()
        contrasena = data.get('contrasena') or ''
        estado = (data.get('estado') or 'activo').strip().lower()

        if not nombre_completo or not cedula_profesional or not usuario or not contrasena:
            return JsonResponse({'success': False, 'message': 'Nombre, cédula, usuario y contraseña son requeridos'})

        if estado not in ('activo', 'inactivo'):
            return JsonResponse({'success': False, 'message': 'Estado inválido'})

        try:
            with connection.cursor() as cursor:
                if not _usuario_disponible(cursor, usuario):
                    return JsonResponse({'success': False, 'message': 'El usuario ya existe, elige otro'})

                cursor.execute(
                    """
                    INSERT INTO Instructores
                    (nombre_completo, especialidad, cedula_profesional, usuario, contrasena, estado)
                    VALUES (%s, %s, ENCRYPTBYPASSPHRASE('clave123', %s), %s, ENCRYPTBYPASSPHRASE('clave123', %s), %s)
                    """,
                    [nombre_completo, especialidad or None, cedula_profesional, usuario, contrasena, estado]
                )

            return JsonResponse({'success': True, 'message': 'Instructor creado correctamente'})
        except DatabaseError as e:
            return JsonResponse({'success': False, 'message': f'Error creando instructor: {str(e)}'}, status=500)

    return JsonResponse({'error': 'Método no permitido'})


@csrf_exempt
def instructores_update(request):
    """Actualiza datos de un instructor y opcionalmente su contraseña."""
    if request.method == 'POST':
        data = json.loads(request.body)
        instructor_id = data.get('instructor_id')
        nombre_completo = (data.get('nombre_completo') or '').strip()
        especialidad = (data.get('especialidad') or '').strip()
        cedula_profesional = (data.get('cedula_profesional') or '').strip()
        usuario = (data.get('usuario') or '').strip()
        contrasena = data.get('contrasena') or ''
        estado = (data.get('estado') or 'activo').strip().lower()

        if not instructor_id or not nombre_completo or not cedula_profesional or not usuario:
            return JsonResponse({'success': False, 'message': 'Faltan campos requeridos'})

        if estado not in ('activo', 'inactivo'):
            return JsonResponse({'success': False, 'message': 'Estado inválido'})

        try:
            instructor_id = int(instructor_id)
        except ValueError:
            return JsonResponse({'success': False, 'message': 'ID de instructor inválido'})

        try:
            with connection.cursor() as cursor:
                if not _usuario_disponible_para_actualizacion(cursor, usuario, instructor_id):
                    return JsonResponse({'success': False, 'message': 'El usuario ya existe, elige otro'})

                if contrasena.strip():
                    cursor.execute(
                        """
                        UPDATE Instructores
                        SET nombre_completo = %s,
                            especialidad = %s,
                            cedula_profesional = ENCRYPTBYPASSPHRASE('clave123', %s),
                            usuario = %s,
                            contrasena = ENCRYPTBYPASSPHRASE('clave123', %s),
                            estado = %s
                        WHERE instructor_id = %s
                        """,
                        [
                            nombre_completo,
                            especialidad or None,
                            cedula_profesional,
                            usuario,
                            contrasena,
                            estado,
                            instructor_id
                        ]
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE Instructores
                        SET nombre_completo = %s,
                            especialidad = %s,
                            cedula_profesional = ENCRYPTBYPASSPHRASE('clave123', %s),
                            usuario = %s,
                            estado = %s
                        WHERE instructor_id = %s
                        """,
                        [
                            nombre_completo,
                            especialidad or None,
                            cedula_profesional,
                            usuario,
                            estado,
                            instructor_id
                        ]
                    )

                if cursor.rowcount == 0:
                    return JsonResponse({'success': False, 'message': 'Instructor no encontrado'})

            return JsonResponse({'success': True, 'message': 'Instructor actualizado correctamente'})
        except DatabaseError as e:
            return JsonResponse({'success': False, 'message': f'Error actualizando instructor: {str(e)}'}, status=500)

    return JsonResponse({'error': 'Método no permitido'})


@csrf_exempt
def instructores_delete(request):
    """Elimina un instructor si no tiene relaciones activas."""
    if request.method == 'POST':
        data = json.loads(request.body)
        instructor_id = data.get('instructor_id')

        if not instructor_id:
            return JsonResponse({'success': False, 'message': 'Se requiere instructor_id'})

        try:
            instructor_id = int(instructor_id)
        except ValueError:
            return JsonResponse({'success': False, 'message': 'ID de instructor inválido'})

        try:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM Instructores WHERE instructor_id = %s", [instructor_id])

                if cursor.rowcount == 0:
                    return JsonResponse({'success': False, 'message': 'Instructor no encontrado'})

            return JsonResponse({'success': True, 'message': 'Instructor eliminado correctamente'})
        except DatabaseError:
            return JsonResponse({'success': False, 'message': 'No se puede eliminar el instructor porque tiene registros relacionados'})

    return JsonResponse({'error': 'Método no permitido'})

@csrf_exempt
def cursos_list(request):
    if request.method == 'GET':
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM Cursos")
            rows = cursor.fetchall()
            cursos = []
            for row in rows:
                cursos.append({
                    'curso_id': row[0],
                    'nombre_curso': row[1],
                    'categoria': row[2],
                    'cupo_maximo': row[3],
                    'duracion_horas': row[4],
                    'costo': str(row[5]),
                    'estado': row[6]
                })
            return JsonResponse(cursos, safe=False)
    return JsonResponse({'error': 'Método no permitido'})

@csrf_exempt
def cursos_create(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        nombre_curso = data.get('nombre_curso')
        categoria = data.get('categoria')
        cupo_maximo = data.get('cupo_maximo', 5)
        duracion_horas = data.get('duracion_horas')
        costo = data.get('costo')
        estado = data.get('estado', 'activo')
        
        with connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO Cursos (nombre_curso, categoria, cupo_maximo, duracion_horas, costo, estado)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, [nombre_curso, categoria, cupo_maximo, duracion_horas, costo, estado])
            return JsonResponse({'success': True, 'message': 'Curso creado'})
    return JsonResponse({'error': 'Método no permitido'})

@csrf_exempt
def proceso_entero(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        estudiante_id = data.get('estudiante_id')
        curso_id = data.get('curso_id')
        calificacion = data.get('calificacion')
        total_pago = data.get('total_pago')
        comentarios = data.get('comentarios')
        metodo_id = data.get('metodo_id')
        referencia_pago = data.get('referencia_pago')
        
        # Validación básica
        if not estudiante_id or not curso_id or not metodo_id:
            return JsonResponse({'success': False, 'message': 'Faltan datos requeridos: estudiante, curso o método de pago'})
        
        try:
            estudiante_id = int(estudiante_id)
            curso_id = int(curso_id)
            metodo_id = int(metodo_id)
            if calificacion:
                calificacion = float(calificacion)
            else:
                calificacion = None
            if total_pago:
                total_pago = float(total_pago)
            else:
                total_pago = None
        except ValueError:
            return JsonResponse({'success': False, 'message': 'Datos inválidos: IDs deben ser números'})
        
        try:
            with connection.cursor() as cursor:
                cursor.execute("EXEC ProcesoEntero %s, %s, %s, %s, %s, %s, %s", 
                               [estudiante_id, curso_id, calificacion, total_pago, comentarios or '', metodo_id, referencia_pago or ''])
                return JsonResponse({'success': True, 'message': 'Proceso completado'})
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})
    return JsonResponse({'error': 'Método no permitido'})

@csrf_exempt
def curso_demanda(request):
    if request.method == 'GET':
        with connection.cursor() as cursor:
            cursor.execute("EXEC CursoDemanda")
            rows = cursor.fetchall()
            demanda = []
            for row in rows:
                demanda.append({
                    'nombre_curso': row[0],
                    'total_inscripciones': row[1]
                })
            return JsonResponse(demanda, safe=False)
    return JsonResponse({'error': 'Método no permitido'})

@csrf_exempt
def inscripciones_por_mes(request):
    if request.method == 'GET':
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT anio, [1] AS Enero, [2] AS Febrero, [3] AS Marzo, [4] AS Abril, 
                       [5] AS Mayo, [6] AS Junio, [7] AS Julio, [8] AS Agosto, 
                       [9] AS Septiembre, [10] AS Octubre, [11] AS Noviembre, [12] AS Diciembre
                FROM (
                    SELECT YEAR(fecha_inscripcion) AS anio, MONTH(fecha_inscripcion) AS mes, COUNT(*) AS total
                    FROM Inscripciones
                    WHERE estado = 'activa'
                    GROUP BY YEAR(fecha_inscripcion), MONTH(fecha_inscripcion)
                ) AS SourceTable
                PIVOT (
                    SUM(total)
                    FOR mes IN ([1], [2], [3], [4], [5], [6], [7], [8], [9], [10], [11], [12])
                ) AS PivotTable
                ORDER BY anio DESC
            """)
            rows = cursor.fetchall()
            reporte = []
            for row in rows:
                reporte.append({
                    'anio': row[0],
                    'enero': row[1] or 0,
                    'febrero': row[2] or 0,
                    'marzo': row[3] or 0,
                    'abril': row[4] or 0,
                    'mayo': row[5] or 0,
                    'junio': row[6] or 0,
                    'julio': row[7] or 0,
                    'agosto': row[8] or 0,
                    'septiembre': row[9] or 0,
                    'octubre': row[10] or 0,
                    'noviembre': row[11] or 0,
                    'diciembre': row[12] or 0
                })
            return JsonResponse(reporte, safe=False)
    return JsonResponse({'error': 'Método no permitido'})

@csrf_exempt
def evaluaciones_list(request):
    if request.method == 'GET':
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT e.evaluacion_id, e.inscripcion_id, e.calificacion, 
                       CONVERT(VARCHAR(MAX), DECRYPTBYPASSPHRASE('clave123', e.comentarios)) AS comentarios,
                       e.fecha
                FROM Evaluaciones e
            """)
            rows = cursor.fetchall()
            evaluaciones = []
            for row in rows:
                evaluaciones.append({
                    'evaluacion_id': row[0],
                    'inscripcion_id': row[1],
                    'calificacion': str(row[2]) if row[2] else None,
                    'comentarios': row[3],
                    'fecha': str(row[4])
                })
            return JsonResponse(evaluaciones, safe=False)
    return JsonResponse({'error': 'Método no permitido'})


@csrf_exempt
def evaluaciones_estudiante(request):
    """Lista únicamente las calificaciones del estudiante autenticado por id."""
    if request.method == 'GET':
        estudiante_id = request.GET.get('estudiante_id')
        if not estudiante_id:
            return JsonResponse({'success': False, 'message': 'Se requiere estudiante_id'})

        try:
            estudiante_id = int(estudiante_id)
        except ValueError:
            return JsonResponse({'success': False, 'message': 'estudiante_id inválido'})

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        i.inscripcion_id,
                        c.nombre_curso,
                        ev_final.evaluacion_id,
                        ev_final.calificacion,
                        CASE WHEN ev_final.comentarios IS NULL THEN NULL
                             ELSE CONVERT(VARCHAR(MAX), DECRYPTBYPASSPHRASE('clave123', ev_final.comentarios))
                        END AS comentarios,
                        ISNULL(ev_final.tipo_evaluacion, 'final') AS tipo_evaluacion,
                        ev_final.fecha,
                        pe.promedio_entregables,
                        CASE
                            WHEN ev_final.calificacion IS NOT NULL AND pe.promedio_entregables IS NOT NULL
                                THEN ROUND((CAST(ev_final.calificacion AS FLOAT) * %s) + (pe.promedio_entregables * %s), 2)
                            WHEN ev_final.calificacion IS NOT NULL
                                THEN CAST(ev_final.calificacion AS FLOAT)
                            WHEN pe.promedio_entregables IS NOT NULL
                                THEN ROUND(pe.promedio_entregables, 2)
                            ELSE NULL
                        END AS calificacion_final
                    FROM Inscripciones i
                    JOIN Cursos c ON i.curso_id = c.curso_id
                    LEFT JOIN Evaluaciones ev_final
                        ON ev_final.inscripcion_id = i.inscripcion_id
                        AND ISNULL(ev_final.tipo_evaluacion, 'final') = 'final'
                    OUTER APPLY (
                        SELECT AVG(CAST(en.calificacion AS FLOAT)) AS promedio_entregables
                        FROM Entregas en
                        JOIN Entregables et ON et.entregable_id = en.entregable_id
                        WHERE en.estudiante_id = i.estudiante_id
                          AND et.curso_id = i.curso_id
                          AND en.calificacion IS NOT NULL
                    ) pe
                    WHERE i.estudiante_id = %s
                    ORDER BY i.fecha_inscripcion DESC
                    """,
                    [PESO_EVALUACION_MANUAL, PESO_ENTREGABLES, estudiante_id]
                )
                rows = cursor.fetchall()
                evaluaciones = []
                for row in rows:
                    evaluaciones.append({
                        'inscripcion_id': row[0],
                        'nombre_curso': row[1],
                        'evaluacion_id': row[2],
                        'calificacion': str(row[3]) if row[3] is not None else None,
                        'comentarios': row[4],
                        'tipo_evaluacion': row[5],
                        'fecha': str(row[6]) if row[6] else None,
                        'promedio_entregables': round(float(row[7]), 2) if row[7] is not None else None,
                        'calificacion_final': round(float(row[8]), 2) if row[8] is not None else None,
                    })
                return JsonResponse(evaluaciones, safe=False)
        except DatabaseError as e:
            return JsonResponse({'success': False, 'message': f'Error consultando calificaciones: {str(e)}'}, status=500)

    return JsonResponse({'error': 'Método no permitido'})

@csrf_exempt
def pagos_list(request):
    if request.method == 'GET':
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT p.pago_id, p.inscripcion_id, p.fecha_pago, p.metodo_id, 
                       CONVERT(VARCHAR(MAX), DECRYPTBYPASSPHRASE('clave123', p.referencia_pago)) AS referencia_pago,
                       p.monto
                FROM Pagos p
            """)
            rows = cursor.fetchall()
            pagos = []
            for row in rows:
                pagos.append({
                    'pago_id': row[0],
                    'inscripcion_id': row[1],
                    'fecha_pago': str(row[2]),
                    'metodo_id': row[3],
                    'referencia_pago': row[4],
                    'monto': str(row[5]) if row[5] else None
                })
            return JsonResponse(pagos, safe=False)
    return JsonResponse({'error': 'Método no permitido'})

# Vistas para templates
def login_page(request):
    return render(request, 'mi_app/login.html')

def instructor_dashboard(request):
    return render(request, 'mi_app/dashboard.html')


def dashboard_redirect(_request):
    return redirect('/instructor-dashboard/')


def instructor_cursos_page(request):
    return render(request, 'mi_app/instructor_cursos.html')


def instructor_alumnos_page(request):
    return render(request, 'mi_app/instructor_alumnos.html')


def instructor_calificaciones_page(request):
    return render(request, 'mi_app/calificaciones.html')


def instructor_entregables_page(_request):
    return redirect('/instructor-cursos/')

def estudiantes_page(request):
    return render(request, 'mi_app/estudiantes.html')

def cursos_page(request):
    return render(request, 'mi_app/cursos.html')

def inscripciones_page(request):
    return render(request, 'mi_app/inscripciones.html')

def reportes_page(request):
    return render(request, 'mi_app/reportes.html')

def admin_dashboard(request):
    return render(request, 'mi_app/admin_dashboard.html')

def estudiante_dashboard(request):
    return render(request, 'mi_app/estudiante_dashboard.html')


def estudiante_mis_cursos_page(request):
    return render(request, 'mi_app/estudiante_mis_cursos.html')


def estudiante_calificaciones_page(request):
    return render(request, 'mi_app/estudiante_calificaciones.html')


def estudiante_entregables_page(request):
    return render(request, 'mi_app/estudiante_entregables.html')


def estudiante_inscripcion_page(request):
    return render(request, 'mi_app/estudiante_inscripcion.html')


def estudiante_perfil_page(request):
    return render(request, 'mi_app/estudiante_perfil.html')


def asignacion_cursos_page(request):
    return render(request, 'mi_app/asignacion_cursos.html')


def instructores_page(request):
    return render(request, 'mi_app/instructores.html')

# API para listar todas las inscripciones
@csrf_exempt
def inscripciones_list(request):
    """Lista todas las inscripciones registradas"""
    if request.method == 'GET':
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    i.inscripcion_id,
                    e.nombre_completo AS estudiante,
                    c.nombre_curso AS curso,
                    i.fecha_inscripcion,
                    i.estado,
                    i.total_pago,
                    CASE WHEN ev.calificacion IS NOT NULL THEN ev.calificacion ELSE NULL END AS calificacion,
                    CASE WHEN ev.comentarios IS NOT NULL THEN CONVERT(VARCHAR(MAX), DECRYPTBYPASSPHRASE('clave123', ev.comentarios)) ELSE NULL END AS comentarios,
                    CASE WHEN p.metodo_id IS NOT NULL THEN mp.nombre ELSE NULL END AS metodo_pago,
                    CASE WHEN p.referencia_pago IS NOT NULL THEN CONVERT(VARCHAR(MAX), DECRYPTBYPASSPHRASE('clave123', p.referencia_pago)) ELSE NULL END AS referencia_pago
                FROM Inscripciones i
                JOIN Estudiantes e ON i.estudiante_id = e.estudiante_id
                JOIN Cursos c ON i.curso_id = c.curso_id
                LEFT JOIN Evaluaciones ev ON i.inscripcion_id = ev.inscripcion_id
                LEFT JOIN Pagos p ON i.inscripcion_id = p.inscripcion_id
                LEFT JOIN MetodosPago mp ON p.metodo_id = mp.metodo_id
                ORDER BY i.fecha_inscripcion DESC
            """)
            rows = cursor.fetchall()
            inscripciones = []
            for row in rows:
                inscripciones.append({
                    'inscripcion_id': row[0],
                    'estudiante': row[1],
                    'curso': row[2],
                    'fecha_inscripcion': str(row[3]),
                    'estado': row[4],
                    'total_pago': str(row[5]) if row[5] else '0.00',
                    'calificacion': str(row[6]) if row[6] else None,
                    'comentarios': row[7],
                    'metodo_pago': row[8],
                    'referencia_pago': row[9]
                })
            return JsonResponse(inscripciones, safe=False)
    return JsonResponse({'error': 'Método no permitido'})

# Vistas para Calificaciones
@csrf_exempt
@csrf_exempt
def calificaciones_instructor(request):
    """Lista todas las inscripciones donde el instructor puede agregar calificaciones"""
    if request.method == 'GET':
        instructor_id = request.GET.get('instructor_id')
        if not instructor_id:
            return JsonResponse({'success': False, 'message': 'Se requiere instructor_id'})
        
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT 
                        i.inscripcion_id,
                        e.estudiante_id,
                        e.nombre_completo,
                        c.curso_id,
                        c.nombre_curso,
                        i.fecha_inscripcion,
                        i.estado,
                        ev.evaluacion_id,
                        ev.calificacion,
                        CASE WHEN ev.comentarios IS NULL THEN NULL 
                             ELSE CONVERT(VARCHAR(MAX), DECRYPTBYPASSPHRASE('clave123', ev.comentarios)) 
                        END AS comentarios,
                        ISNULL(ev.tipo_evaluacion, 'final') AS tipo_evaluacion,
                        ev.fecha_actualizacion,
                        pe.promedio_entregables,
                        CASE
                            WHEN ev.calificacion IS NOT NULL AND pe.promedio_entregables IS NOT NULL
                                THEN ROUND((CAST(ev.calificacion AS FLOAT) * %s) + (pe.promedio_entregables * %s), 2)
                            WHEN ev.calificacion IS NOT NULL
                                THEN CAST(ev.calificacion AS FLOAT)
                            WHEN pe.promedio_entregables IS NOT NULL
                                THEN ROUND(pe.promedio_entregables, 2)
                            ELSE NULL
                        END AS calificacion_final
                    FROM Inscripciones i
                    JOIN Estudiantes e ON i.estudiante_id = e.estudiante_id
                    JOIN Cursos c ON i.curso_id = c.curso_id
                    JOIN Curso_Instructor ci ON c.curso_id = ci.curso_id
                    LEFT JOIN Evaluaciones ev ON i.inscripcion_id = ev.inscripcion_id
                    OUTER APPLY (
                        SELECT AVG(CAST(en.calificacion AS FLOAT)) AS promedio_entregables
                        FROM Entregas en
                        JOIN Entregables et ON et.entregable_id = en.entregable_id
                        WHERE en.estudiante_id = i.estudiante_id
                          AND et.curso_id = i.curso_id
                          AND en.calificacion IS NOT NULL
                    ) pe
                    WHERE ci.instructor_id = %s AND i.estado IN ('activa', 'finalizada')
                    ORDER BY i.fecha_inscripcion DESC
                """, [PESO_EVALUACION_MANUAL, PESO_ENTREGABLES, instructor_id])
                rows = cursor.fetchall()
                inscripciones = []
                for row in rows:
                    inscripciones.append({
                        'inscripcion_id': row[0],
                        'estudiante_id': row[1],
                        'nombre_estudiante': row[2],
                        'curso_id': row[3],
                        'nombre_curso': row[4],
                        'fecha_inscripcion': str(row[5]),
                        'estado': row[6],
                        'evaluacion_id': row[7],
                        'calificacion': str(row[8]) if row[8] else None,
                        'comentarios': row[9],
                        'tipo_evaluacion': row[10],
                        'fecha_actualizacion': str(row[11]) if row[11] else None,
                        'promedio_entregables': round(float(row[12]), 2) if row[12] is not None else None,
                        'calificacion_final': round(float(row[13]), 2) if row[13] is not None else None,
                    })
                return JsonResponse(inscripciones, safe=False)
        except Exception as e:
            import traceback
            error_msg = str(e)
            traceback.print_exc()
            return JsonResponse({'success': False, 'error': error_msg, 'message': f'Error en la consulta: {error_msg}'}, status=500)
    return JsonResponse({'error': 'Método no permitido'})

@csrf_exempt
@csrf_exempt
def agregar_calificacion(request):
    """Agrega o actualiza una calificación para un estudiante"""
    if request.method == 'POST':
        data = json.loads(request.body)
        inscripcion_id = data.get('inscripcion_id')
        instructor_id = data.get('instructor_id')
        calificacion = data.get('calificacion')
        comentarios = data.get('comentarios', '')
        tipo_evaluacion = data.get('tipo_evaluacion', 'final')
        
        # Validación
        if not inscripcion_id or not instructor_id or calificacion is None:
            return JsonResponse({'success': False, 'message': 'Faltan datos requeridos'})
        
        try:
            calificacion = float(calificacion)
            inscripcion_id = int(inscripcion_id)
            instructor_id = int(instructor_id)
            
            if calificacion < 0 or calificacion > 100:
                return JsonResponse({'success': False, 'message': 'La calificación debe estar entre 0 y 100'})
        except ValueError:
            return JsonResponse({'success': False, 'message': 'Datos inválidos'})
        
        try:
            with connection.cursor() as cursor:
                # Verificar que el instructor esté asignado al curso
                cursor.execute("""
                    SELECT c.curso_id
                    FROM Inscripciones i
                    JOIN Cursos c ON i.curso_id = c.curso_id
                    JOIN Curso_Instructor ci ON c.curso_id = ci.curso_id
                    WHERE i.inscripcion_id = %s AND ci.instructor_id = %s
                """, [inscripcion_id, instructor_id])
                
                if not cursor.fetchone():
                    return JsonResponse({'success': False, 'message': 'No tiene permisos para calificar este estudiante'})
                
                # Verificar si ya existe una evaluación
                cursor.execute("""
                    SELECT evaluacion_id FROM Evaluaciones 
                    WHERE inscripcion_id = %s AND tipo_evaluacion = %s
                """, [inscripcion_id, tipo_evaluacion])
                
                evaluacion_existente = cursor.fetchone()
                
                if evaluacion_existente:
                    # Actualizar evaluación existente
                    if comentarios:
                        cursor.execute("""
                            UPDATE Evaluaciones
                            SET calificacion = %s, comentarios = ENCRYPTBYPASSPHRASE('clave123', %s), 
                                instructor_id = %s, fecha_actualizacion = GETDATE()
                            WHERE evaluacion_id = %s
                        """, [calificacion, comentarios, instructor_id, evaluacion_existente[0]])
                    else:
                        cursor.execute("""
                            UPDATE Evaluaciones
                            SET calificacion = %s, comentarios = NULL, 
                                instructor_id = %s, fecha_actualizacion = GETDATE()
                            WHERE evaluacion_id = %s
                        """, [calificacion, instructor_id, evaluacion_existente[0]])
                    mensaje = 'Calificación actualizada correctamente'
                else:
                    # Insertar nueva evaluación
                    if comentarios:
                        cursor.execute("""
                            INSERT INTO Evaluaciones 
                            (inscripcion_id, instructor_id, calificacion, comentarios, tipo_evaluacion, fecha)
                            VALUES (%s, %s, %s, ENCRYPTBYPASSPHRASE('clave123', %s), %s, GETDATE())
                        """, [inscripcion_id, instructor_id, calificacion, comentarios, tipo_evaluacion])
                    else:
                        cursor.execute("""
                            INSERT INTO Evaluaciones 
                            (inscripcion_id, instructor_id, calificacion, comentarios, tipo_evaluacion, fecha)
                            VALUES (%s, %s, %s, NULL, %s, GETDATE())
                        """, [inscripcion_id, instructor_id, calificacion, tipo_evaluacion])
                    mensaje = 'Calificación agregada correctamente'
                
                return JsonResponse({'success': True, 'message': mensaje})
        except Exception as e:
            import traceback
            error_msg = str(e)
            traceback.print_exc()
            return JsonResponse({'success': False, 'message': f'Error: {error_msg}'})
    return JsonResponse({'error': 'Método no permitido'})

def calificaciones_page(request):
    """Página para que el instructor agregue calificaciones"""
    return render(request, 'mi_app/calificaciones.html')

@csrf_exempt
def pagos_admin_list(request):
    """Lista todos los pagos con información detallada para el admin"""
    if request.method == 'GET':
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT 
                        p.pago_id,
                        p.inscripcion_id,
                        e.nombre_completo,
                        c.nombre_curso,
                        mp.nombre,
                        p.fecha_pago,
                        p.monto,
                        i.total_pago,
                        CASE WHEN p.referencia_pago IS NULL THEN NULL 
                             ELSE CONVERT(VARCHAR(MAX), DECRYPTBYPASSPHRASE('clave123', p.referencia_pago)) 
                        END AS referencia_pago
                    FROM Pagos p
                    JOIN Inscripciones i ON p.inscripcion_id = i.inscripcion_id
                    JOIN Estudiantes e ON i.estudiante_id = e.estudiante_id
                    JOIN Cursos c ON i.curso_id = c.curso_id
                    JOIN MetodosPago mp ON p.metodo_id = mp.metodo_id
                    ORDER BY p.fecha_pago DESC
                """)
                rows = cursor.fetchall()
                pagos = []
                for row in rows:
                    pagos.append({
                        'pago_id': row[0],
                        'inscripcion_id': row[1],
                        'nombre_estudiante': row[2],
                        'nombre_curso': row[3],
                        'metodo_pago': row[4],
                        'fecha_pago': str(row[5]),
                        'monto_pagado': str(row[6]) if row[6] else '0.00',
                        'monto_total': str(row[7]),
                        'referencia_pago': row[8]
                    })
                return JsonResponse(pagos, safe=False)
        except Exception as e:
            import traceback
            error_msg = str(e)
            traceback.print_exc()
            return JsonResponse({'success': False, 'error': error_msg, 'message': f'Error en la consulta: {error_msg}'}, status=500)
    return JsonResponse({'error': 'Método no permitido'})

@csrf_exempt
def inscripciones_sin_pago(request):
    """Lista todas las inscripciones sin pago registrado"""
    if request.method == 'GET':
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT DISTINCT
                        i.inscripcion_id,
                        i.estudiante_id,
                        e.nombre_completo,
                        c.curso_id,
                        c.nombre_curso,
                        i.total_pago,
                        i.fecha_inscripcion,
                        i.estado
                    FROM Inscripciones i
                    JOIN Estudiantes e ON i.estudiante_id = e.estudiante_id
                    JOIN Cursos c ON i.curso_id = c.curso_id
                    LEFT JOIN Pagos p ON i.inscripcion_id = p.inscripcion_id
                    WHERE p.pago_id IS NULL AND i.estado = 'activa'
                    ORDER BY i.fecha_inscripcion DESC
                """)
                rows = cursor.fetchall()
                inscripciones = []
                for row in rows:
                    inscripciones.append({
                        'inscripcion_id': row[0],
                        'estudiante_id': row[1],
                        'nombre_estudiante': row[2],
                        'curso_id': row[3],
                        'nombre_curso': row[4],
                        'monto_pendiente': str(row[5]),
                        'fecha_inscripcion': str(row[6]),
                        'estado': row[7]
                    })
                return JsonResponse(inscripciones, safe=False)
        except Exception as e:
            import traceback
            error_msg = str(e)
            traceback.print_exc()
            return JsonResponse({'success': False, 'error': error_msg, 'message': f'Error en la consulta: {error_msg}'}, status=500)
    return JsonResponse({'error': 'Método no permitido'})

@csrf_exempt
def metodos_pago_list(request):
    """Lista todos los métodos de pago disponibles"""
    if request.method == 'GET':
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT metodo_id, nombre FROM MetodosPago ORDER BY nombre")
                rows = cursor.fetchall()
                metodos = []
                for row in rows:
                    metodos.append({
                        'metodo_id': row[0],
                        'nombre': row[1]
                    })
                return JsonResponse(metodos, safe=False)
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)}, status=500)
    return JsonResponse({'error': 'Método no permitido'})

@csrf_exempt
def crear_pago(request):
    """Crea un nuevo pago"""
    if request.method == 'POST':
        data = json.loads(request.body)
        inscripcion_id = data.get('inscripcion_id')
        metodo_id = data.get('metodo_id')
        monto = data.get('monto')
        referencia_pago = data.get('referencia_pago', '')
        
        # Validación
        if not inscripcion_id or not metodo_id or not monto:
            return JsonResponse({'success': False, 'message': 'Faltan datos requeridos'})
        
        try:
            inscripcion_id = int(inscripcion_id)
            metodo_id = int(metodo_id)
            monto = float(monto)
            
            if monto <= 0:
                return JsonResponse({'success': False, 'message': 'El monto debe ser mayor a 0'})
        except ValueError:
            return JsonResponse({'success': False, 'message': 'Datos inválidos'})
        
        try:
            with connection.cursor() as cursor:
                # Verificar que la inscripción existe y está activa
                cursor.execute("""
                    SELECT i.inscripcion_id, i.total_pago
                    FROM Inscripciones i
                    WHERE i.inscripcion_id = %s AND i.estado = 'activa'
                """, [inscripcion_id])
                
                inscripcion = cursor.fetchone()
                if not inscripcion:
                    return JsonResponse({'success': False, 'message': 'La inscripción no existe o no está activa'})
                
                # Verificar que el monto no exceda el total a pagar
                if monto > float(inscripcion[1]):
                    return JsonResponse({'success': False, 'message': f'El monto no puede exceder {inscripcion[1]}'})
                
                # Insertar el pago
                if referencia_pago:
                    cursor.execute("""
                        INSERT INTO Pagos 
                        (inscripcion_id, metodo_id, monto, referencia_pago, fecha_pago)
                        VALUES (%s, %s, %s, ENCRYPTBYPASSPHRASE('clave123', %s), GETDATE())
                    """, [inscripcion_id, metodo_id, monto, referencia_pago])
                else:
                    cursor.execute("""
                        INSERT INTO Pagos 
                        (inscripcion_id, metodo_id, monto, fecha_pago)
                        VALUES (%s, %s, %s, GETDATE())
                    """, [inscripcion_id, metodo_id, monto])
                
                return JsonResponse({'success': True, 'message': 'Pago registrado correctamente'})
        except Exception as e:
            import traceback
            error_msg = str(e)
            traceback.print_exc()
            return JsonResponse({'success': False, 'message': f'Error: {error_msg}'})
    return JsonResponse({'error': 'Método no permitido'})

@csrf_exempt
def actualizar_pago(request):
    """Actualiza un pago existente"""
    if request.method == 'POST':
        data = json.loads(request.body)
        pago_id = data.get('pago_id')
        metodo_id = data.get('metodo_id')
        monto = data.get('monto')
        referencia_pago = data.get('referencia_pago', '')
        
        # Validación
        if not pago_id or not metodo_id or not monto:
            return JsonResponse({'success': False, 'message': 'Faltan datos requeridos'})
        
        try:
            pago_id = int(pago_id)
            metodo_id = int(metodo_id)
            monto = float(monto)
            
            if monto <= 0:
                return JsonResponse({'success': False, 'message': 'El monto debe ser mayor a 0'})
        except ValueError:
            return JsonResponse({'success': False, 'message': 'Datos inválidos'})
        
        try:
            with connection.cursor() as cursor:
                # Verificar que el pago existe
                cursor.execute("""
                    SELECT p.inscripcion_id, i.total_pago
                    FROM Pagos p
                    JOIN Inscripciones i ON p.inscripcion_id = i.inscripcion_id
                    WHERE p.pago_id = %s
                """, [pago_id])
                
                pago = cursor.fetchone()
                if not pago:
                    return JsonResponse({'success': False, 'message': 'El pago no existe'})
                
                # Verificar que el monto no exceda el total a pagar
                if monto > float(pago[1]):
                    return JsonResponse({'success': False, 'message': f'El monto no puede exceder {pago[1]}'})
                
                # Actualizar el pago
                if referencia_pago:
                    cursor.execute("""
                        UPDATE Pagos
                        SET metodo_id = %s, monto = %s, referencia_pago = ENCRYPTBYPASSPHRASE('clave123', %s)
                        WHERE pago_id = %s
                    """, [metodo_id, monto, referencia_pago, pago_id])
                else:
                    cursor.execute("""
                        UPDATE Pagos
                        SET metodo_id = %s, monto = %s, referencia_pago = NULL
                        WHERE pago_id = %s
                    """, [metodo_id, monto, pago_id])
                
                return JsonResponse({'success': True, 'message': 'Pago actualizado correctamente'})
        except Exception as e:
            import traceback
            error_msg = str(e)
            traceback.print_exc()
            return JsonResponse({'success': False, 'message': f'Error: {error_msg}'})
    return JsonResponse({'error': 'Método no permitido'})

def pagos_page(request):
    """Página para gestionar pagos"""
    return render(request, 'mi_app/pagos.html')


@csrf_exempt
def instructores_list(request):
    """Lista instructores disponibles para asignación de cursos."""
    if request.method == 'GET':
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT instructor_id, nombre_completo, especialidad, estado
                    FROM Instructores
                    WHERE estado = 'activo'
                    ORDER BY nombre_completo
                    """
                )
                rows = cursor.fetchall()
                instructores = []
                for row in rows:
                    instructores.append({
                        'instructor_id': row[0],
                        'nombre_completo': row[1],
                        'especialidad': row[2],
                        'estado': row[3]
                    })
                return JsonResponse(instructores, safe=False)
        except DatabaseError as e:
            return JsonResponse({'success': False, 'message': f'Error listando instructores: {str(e)}'}, status=500)

    return JsonResponse({'error': 'Método no permitido'})


@csrf_exempt
def instructores_admin_list(request):
    """Lista instructores para gestión administrativa."""
    if request.method == 'GET':
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        instructor_id,
                        nombre_completo,
                        especialidad,
                        CONVERT(VARCHAR(MAX), DECRYPTBYPASSPHRASE('clave123', cedula_profesional)) AS cedula_profesional,
                        usuario,
                        estado
                    FROM Instructores
                    ORDER BY instructor_id DESC
                    """
                )
                rows = cursor.fetchall()
                instructores = []
                for row in rows:
                    instructores.append({
                        'instructor_id': row[0],
                        'nombre_completo': row[1],
                        'especialidad': row[2],
                        'cedula_profesional': row[3],
                        'usuario': row[4],
                        'estado': row[5]
                    })
                return JsonResponse(instructores, safe=False)
        except DatabaseError as e:
            return JsonResponse({'success': False, 'message': f'Error listando instructores: {str(e)}'}, status=500)

    return JsonResponse({'error': 'Método no permitido'})


@csrf_exempt
def curso_instructor_list(request):
    """Lista las asignaciones curso-instructor."""
    if request.method == 'GET':
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        ci.id,
                        c.curso_id,
                        c.nombre_curso,
                        i.instructor_id,
                        i.nombre_completo,
                        i.especialidad
                    FROM Curso_Instructor ci
                    JOIN Cursos c ON ci.curso_id = c.curso_id
                    JOIN Instructores i ON ci.instructor_id = i.instructor_id
                    ORDER BY c.nombre_curso, i.nombre_completo
                    """
                )
                rows = cursor.fetchall()
                asignaciones = []
                for row in rows:
                    asignaciones.append({
                        'asignacion_id': row[0],
                        'curso_id': row[1],
                        'nombre_curso': row[2],
                        'instructor_id': row[3],
                        'nombre_instructor': row[4],
                        'especialidad': row[5]
                    })
                return JsonResponse(asignaciones, safe=False)
        except DatabaseError as e:
            return JsonResponse({'success': False, 'message': f'Error listando asignaciones: {str(e)}'}, status=500)

    return JsonResponse({'error': 'Método no permitido'})


@csrf_exempt
def asignar_curso_instructor(request):
    """Asigna un curso a un instructor evitando duplicados."""
    if request.method == 'POST':
        data = json.loads(request.body)
        curso_id = data.get('curso_id')
        instructor_id = data.get('instructor_id')

        if not curso_id or not instructor_id:
            return JsonResponse({'success': False, 'message': 'Curso e instructor son requeridos'})

        try:
            curso_id = int(curso_id)
            instructor_id = int(instructor_id)
        except ValueError:
            return JsonResponse({'success': False, 'message': 'IDs inválidos'})

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM Curso_Instructor
                    WHERE curso_id = %s AND instructor_id = %s
                    """,
                    [curso_id, instructor_id]
                )
                if cursor.fetchone()[0] > 0:
                    return JsonResponse({'success': False, 'message': 'Este instructor ya está asignado al curso'})

                cursor.execute(
                    """
                    INSERT INTO Curso_Instructor (curso_id, instructor_id)
                    VALUES (%s, %s)
                    """,
                    [curso_id, instructor_id]
                )

                return JsonResponse({'success': True, 'message': 'Curso asignado al instructor correctamente'})
        except DatabaseError as e:
            return JsonResponse({'success': False, 'message': f'Error asignando curso: {str(e)}'}, status=500)

    return JsonResponse({'error': 'Método no permitido'})


@csrf_exempt
def desasignar_curso_instructor(request):
    """Elimina una asignación curso-instructor existente."""
    if request.method == 'POST':
        data = json.loads(request.body)
        asignacion_id = data.get('asignacion_id')
        curso_id = data.get('curso_id')
        instructor_id = data.get('instructor_id')

        try:
            with connection.cursor() as cursor:
                if asignacion_id:
                    try:
                        asignacion_id = int(asignacion_id)
                    except ValueError:
                        return JsonResponse({'success': False, 'message': 'asignacion_id inválido'})

                    cursor.execute(
                        """
                        DELETE FROM Curso_Instructor
                        WHERE id = %s
                        """,
                        [asignacion_id]
                    )
                else:
                    if not curso_id or not instructor_id:
                        return JsonResponse({'success': False, 'message': 'Se requiere asignacion_id o bien curso_id + instructor_id'})

                    try:
                        curso_id = int(curso_id)
                        instructor_id = int(instructor_id)
                    except ValueError:
                        return JsonResponse({'success': False, 'message': 'IDs inválidos'})

                    cursor.execute(
                        """
                        DELETE FROM Curso_Instructor
                        WHERE curso_id = %s AND instructor_id = %s
                        """,
                        [curso_id, instructor_id]
                    )

                if cursor.rowcount == 0:
                    return JsonResponse({'success': False, 'message': 'No se encontró la asignación a eliminar'})

                return JsonResponse({'success': True, 'message': 'Profesor desasignado del curso correctamente'})
        except DatabaseError as e:
            return JsonResponse({'success': False, 'message': f'Error desasignando curso: {str(e)}'}, status=500)

    return JsonResponse({'error': 'Método no permitido'})


@csrf_exempt
def cursos_disponibles_estudiante(request):
    """Lista cursos activos disponibles para que un estudiante se inscriba."""
    if request.method == 'GET':
        estudiante_id = request.GET.get('estudiante_id')
        if not estudiante_id:
            return JsonResponse({'success': False, 'message': 'Se requiere estudiante_id'})

        try:
            estudiante_id = int(estudiante_id)
        except ValueError:
            return JsonResponse({'success': False, 'message': 'estudiante_id inválido'})

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT c.curso_id, c.nombre_curso, c.categoria, c.duracion_horas, c.costo
                    FROM Cursos c
                    WHERE c.estado = 'activo'
                      AND NOT EXISTS (
                          SELECT 1
                          FROM Inscripciones i
                          WHERE i.estudiante_id = %s
                            AND i.curso_id = c.curso_id
                            AND i.estado IN ('activa', 'finalizada')
                      )
                    ORDER BY c.nombre_curso
                    """,
                    [estudiante_id]
                )
                rows = cursor.fetchall()
                cursos = []
                for row in rows:
                    cursos.append({
                        'curso_id': row[0],
                        'nombre_curso': row[1],
                        'categoria': row[2],
                        'duracion_horas': row[3],
                        'costo': str(row[4])
                    })
                return JsonResponse(cursos, safe=False)
        except DatabaseError as e:
            return JsonResponse({'success': False, 'message': f'Error consultando cursos: {str(e)}'}, status=500)

    return JsonResponse({'error': 'Método no permitido'})


@csrf_exempt
def estudiante_inscripciones(request):
    """Lista inscripciones del estudiante con información de pago."""
    if request.method == 'GET':
        estudiante_id = request.GET.get('estudiante_id')
        if not estudiante_id:
            return JsonResponse({'success': False, 'message': 'Se requiere estudiante_id'})

        try:
            estudiante_id = int(estudiante_id)
        except ValueError:
            return JsonResponse({'success': False, 'message': 'estudiante_id inválido'})

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        i.inscripcion_id,
                        c.curso_id,
                        c.nombre_curso,
                        c.categoria,
                        c.duracion_horas,
                        i.fecha_inscripcion,
                        i.estado,
                        i.total_pago,
                        ISNULL(SUM(p.monto), 0) AS total_pagado
                    FROM Inscripciones i
                    JOIN Cursos c ON i.curso_id = c.curso_id
                    LEFT JOIN Pagos p ON i.inscripcion_id = p.inscripcion_id
                    WHERE i.estudiante_id = %s
                    GROUP BY
                        i.inscripcion_id,
                        c.curso_id,
                        c.nombre_curso,
                        c.categoria,
                        c.duracion_horas,
                        i.fecha_inscripcion,
                        i.estado,
                        i.total_pago
                    ORDER BY i.fecha_inscripcion DESC
                    """,
                    [estudiante_id]
                )
                rows = cursor.fetchall()
                resultado = []
                for row in rows:
                    resultado.append({
                        'inscripcion_id': row[0],
                        'curso_id': row[1],
                        'nombre_curso': row[2],
                        'categoria': row[3],
                        'duracion_horas': row[4],
                        'fecha_inscripcion': str(row[5]),
                        'estado': row[6],
                        'total_pago': str(row[7]),
                        'total_pagado': str(row[8])
                    })
                return JsonResponse(resultado, safe=False)
        except DatabaseError as e:
            return JsonResponse({'success': False, 'message': f'Error consultando inscripciones: {str(e)}'}, status=500)

    return JsonResponse({'error': 'Método no permitido'})


@csrf_exempt
def inscribir_estudiante_cursos(request):
    """Inscribe un estudiante en varios cursos y registra pagos al finalizar."""
    if request.method == 'POST':
        data = json.loads(request.body)
        estudiante_id = data.get('estudiante_id')
        cursos_ids = data.get('cursos_ids', [])
        metodo_id = data.get('metodo_id')
        referencia_pago = (data.get('referencia_pago') or '').strip()

        if not estudiante_id or not metodo_id or not isinstance(cursos_ids, list) or not cursos_ids:
            return JsonResponse({'success': False, 'message': 'Debe seleccionar cursos y método de pago'})

        try:
            estudiante_id = int(estudiante_id)
            metodo_id = int(metodo_id)
            cursos_ids = sorted(set(int(c) for c in cursos_ids))
        except ValueError:
            return JsonResponse({'success': False, 'message': 'Datos inválidos en estudiante, método o cursos'})

        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT COUNT(*) FROM Estudiantes WHERE estudiante_id = %s", [estudiante_id])
                    if cursor.fetchone()[0] == 0:
                        return JsonResponse({'success': False, 'message': 'El estudiante no existe'})

                    cursor.execute("SELECT COUNT(*) FROM MetodosPago WHERE metodo_id = %s", [metodo_id])
                    if cursor.fetchone()[0] == 0:
                        return JsonResponse({'success': False, 'message': 'Método de pago inválido'})

                    placeholders = ','.join(['%s'] * len(cursos_ids))
                    cursor.execute(
                        f"""
                        SELECT c.curso_id, c.nombre_curso, c.costo
                        FROM Cursos c
                        WHERE c.curso_id IN ({placeholders})
                          AND c.estado = 'activo'
                          AND NOT EXISTS (
                              SELECT 1
                              FROM Inscripciones i
                              WHERE i.estudiante_id = %s
                                AND i.curso_id = c.curso_id
                                AND i.estado IN ('activa', 'finalizada')
                          )
                        """,
                        [*cursos_ids, estudiante_id]
                    )
                    cursos_disponibles = cursor.fetchall()

                    if len(cursos_disponibles) != len(cursos_ids):
                        return JsonResponse({'success': False, 'message': 'Algunos cursos no están disponibles para inscripción'})

                    total_checkout = 0.0
                    inscripciones_creadas = []

                    for curso_id, nombre_curso, costo in cursos_disponibles:
                        costo_float = float(costo)
                        total_checkout += costo_float

                        cursor.execute(
                            """
                            INSERT INTO Inscripciones (estudiante_id, curso_id, estado, total_pago)
                            VALUES (%s, %s, 'activa', %s)
                            """,
                            [estudiante_id, curso_id, costo_float]
                        )

                        cursor.execute(
                            """
                            SELECT TOP 1 inscripcion_id
                            FROM Inscripciones
                            WHERE estudiante_id = %s AND curso_id = %s
                            ORDER BY fecha_inscripcion DESC, inscripcion_id DESC
                            """,
                            [estudiante_id, curso_id]
                        )
                        scope_row = cursor.fetchone()
                        if not scope_row or scope_row[0] is None:
                            return JsonResponse({'success': False, 'message': 'No fue posible obtener la inscripción creada'})
                        inscripcion_id = int(scope_row[0])

                        if referencia_pago:
                            cursor.execute(
                                """
                                INSERT INTO Pagos (inscripcion_id, metodo_id, monto, referencia_pago, fecha_pago)
                                VALUES (%s, %s, %s, ENCRYPTBYPASSPHRASE('clave123', %s), GETDATE())
                                """,
                                [inscripcion_id, metodo_id, costo_float, referencia_pago]
                            )
                        else:
                            cursor.execute(
                                """
                                INSERT INTO Pagos (inscripcion_id, metodo_id, monto, fecha_pago)
                                VALUES (%s, %s, %s, GETDATE())
                                """,
                                [inscripcion_id, metodo_id, costo_float]
                            )

                        inscripciones_creadas.append({
                            'inscripcion_id': inscripcion_id,
                            'curso_id': curso_id,
                            'curso': nombre_curso,
                            'monto': round(costo_float, 2)
                        })

                    return JsonResponse({
                        'success': True,
                        'message': 'Inscripción y pago realizados correctamente',
                        'total_cursos': len(inscripciones_creadas),
                        'total_pagado': round(total_checkout, 2),
                        'inscripciones': inscripciones_creadas
                    })
        except DatabaseError as e:
            return JsonResponse({'success': False, 'message': f'Error procesando inscripción: {str(e)}'}, status=500)

    return JsonResponse({'error': 'Método no permitido'})


def _parse_iso_datetime(value):
    if not value:
        return None
    value = str(value).strip()
    if value.endswith('Z'):
        value = value[:-1] + '+00:00'
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _to_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in ('1', 'true', 'si', 'sí', 'yes', 'on')


@csrf_exempt
def crear_entregable(request):
    """Crea un entregable para un curso del instructor."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'})

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, TypeError, ValueError):
        return JsonResponse({'success': False, 'message': 'JSON inválido'})

    instructor_id = data.get('instructor_id')
    curso_id = data.get('curso_id')
    titulo = (data.get('titulo') or '').strip()
    descripcion = (data.get('descripcion') or '').strip()
    fecha_limite_raw = data.get('fecha_limite')
    puntaje_maximo = data.get('puntaje_maximo', 100)
    permite_entrega_tardia = _to_bool(data.get('permite_entrega_tardia', False))

    if not instructor_id or not curso_id or not titulo or not fecha_limite_raw:
        return JsonResponse({'success': False, 'message': 'instructor_id, curso_id, titulo y fecha_limite son requeridos'})

    try:
        instructor_id = int(instructor_id)
        curso_id = int(curso_id)
        puntaje_maximo = float(puntaje_maximo)
    except ValueError:
        return JsonResponse({'success': False, 'message': 'IDs o puntaje inválidos'})

    if puntaje_maximo <= 0:
        return JsonResponse({'success': False, 'message': 'puntaje_maximo debe ser mayor a 0'})

    fecha_limite = _parse_iso_datetime(fecha_limite_raw)
    if not fecha_limite:
        return JsonResponse({'success': False, 'message': 'fecha_limite inválida. Usa formato ISO, ej: 2026-04-20T23:59:00'})

    # SQL Server suele guardar DATETIME sin zona horaria; normalizamos a hora local sin tz.
    if timezone.is_aware(fecha_limite):
        fecha_limite = timezone.localtime(fecha_limite).replace(tzinfo=None)

    ahora_local = timezone.localtime().replace(tzinfo=None)
    if fecha_limite <= ahora_local:
        return JsonResponse({'success': False, 'message': 'La fecha límite debe ser mayor a la fecha/hora actual'})

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM Curso_Instructor
                WHERE curso_id = %s AND instructor_id = %s
                """,
                [curso_id, instructor_id]
            )
            if cursor.fetchone()[0] == 0:
                return JsonResponse({'success': False, 'message': 'El instructor no está asignado a este curso'})

            cursor.execute(
                """
                INSERT INTO Entregables
                    (curso_id, instructor_id, titulo, descripcion, fecha_limite, puntaje_maximo, permite_entrega_tardia, estado, fecha_actualizacion)
                OUTPUT INSERTED.entregable_id
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, 'publicado', GETDATE())
                """,
                [curso_id, instructor_id, titulo, descripcion or None, fecha_limite, puntaje_maximo, 1 if permite_entrega_tardia else 0]
            )
            row = cursor.fetchone()
            entregable_id = int(row[0]) if row else None

        return JsonResponse({'success': True, 'message': 'Entregable creado correctamente', 'entregable_id': entregable_id})
    except DatabaseError as e:
        db_error = str(e)
        if 'CK_Entregables_fechas' in db_error:
            return JsonResponse(
                {
                    'success': False,
                    'message': 'Fecha límite inválida para la regla de fechas. Usa una fecha futura (mayor a la fecha actual).'
                },
                status=400
            )
        return JsonResponse({'success': False, 'message': f'Error creando entregable: {db_error}'}, status=500)


@csrf_exempt
def entregables_instructor(request):
    """Lista entregables del instructor."""
    if request.method != 'GET':
        return JsonResponse({'error': 'Método no permitido'})

    instructor_id = request.GET.get('instructor_id')
    curso_id = request.GET.get('curso_id')
    estado = (request.GET.get('estado') or '').strip().lower()

    if not instructor_id:
        return JsonResponse({'success': False, 'message': 'Se requiere instructor_id'})

    try:
        instructor_id = int(instructor_id)
        curso_id = int(curso_id) if curso_id else None
    except ValueError:
        return JsonResponse({'success': False, 'message': 'Parámetros inválidos'})

    filtros = ["e.instructor_id = %s"]
    params = [instructor_id]

    if curso_id:
        filtros.append("e.curso_id = %s")
        params.append(curso_id)

    if estado:
        filtros.append("e.estado = %s")
        params.append(estado)

    where_clause = " AND ".join(filtros)

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT
                    e.entregable_id,
                    e.curso_id,
                    c.nombre_curso,
                    e.titulo,
                    e.descripcion,
                    e.fecha_publicacion,
                    e.fecha_limite,
                    e.puntaje_maximo,
                    e.permite_entrega_tardia,
                    e.estado,
                    e.fecha_creacion,
                    e.fecha_actualizacion
                FROM Entregables e
                JOIN Cursos c ON c.curso_id = e.curso_id
                WHERE {where_clause}
                ORDER BY e.fecha_limite ASC, e.entregable_id DESC
                """,
                params
            )
            rows = cursor.fetchall()

        resultado = []
        for row in rows:
            resultado.append({
                'entregable_id': row[0],
                'curso_id': row[1],
                'nombre_curso': row[2],
                'titulo': row[3],
                'descripcion': row[4],
                'fecha_publicacion': str(row[5]) if row[5] else None,
                'fecha_limite': str(row[6]) if row[6] else None,
                'puntaje_maximo': float(row[7]) if row[7] is not None else None,
                'permite_entrega_tardia': bool(row[8]),
                'estado': row[9],
                'fecha_creacion': str(row[10]) if row[10] else None,
                'fecha_actualizacion': str(row[11]) if row[11] else None
            })

        return JsonResponse(resultado, safe=False)
    except DatabaseError as e:
        return JsonResponse({'success': False, 'message': f'Error listando entregables: {str(e)}'}, status=500)


@csrf_exempt
def actualizar_entregable(request):
    """Actualiza un entregable del instructor propietario."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'})

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, TypeError, ValueError):
        return JsonResponse({'success': False, 'message': 'JSON inválido'})

    instructor_id = data.get('instructor_id')
    entregable_id = data.get('entregable_id')

    if not instructor_id or not entregable_id:
        return JsonResponse({'success': False, 'message': 'instructor_id y entregable_id son requeridos'})

    try:
        instructor_id = int(instructor_id)
        entregable_id = int(entregable_id)
    except ValueError:
        return JsonResponse({'success': False, 'message': 'IDs inválidos'})

    titulo = data.get('titulo')
    descripcion = data.get('descripcion')
    fecha_limite_raw = data.get('fecha_limite')
    puntaje_maximo = data.get('puntaje_maximo')
    permite_entrega_tardia = data.get('permite_entrega_tardia')
    estado = data.get('estado')

    updates = []
    params = []

    if titulo is not None:
        titulo = str(titulo).strip()
        if not titulo:
            return JsonResponse({'success': False, 'message': 'titulo no puede estar vacío'})
        updates.append('titulo = %s')
        params.append(titulo)

    if descripcion is not None:
        descripcion = str(descripcion).strip()
        updates.append('descripcion = %s')
        params.append(descripcion or None)

    if fecha_limite_raw is not None:
        fecha_limite = _parse_iso_datetime(fecha_limite_raw)
        if not fecha_limite:
            return JsonResponse({'success': False, 'message': 'fecha_limite inválida. Usa formato ISO, ej: 2026-04-20T23:59:00'})
        if timezone.is_aware(fecha_limite):
            fecha_limite = timezone.localtime(fecha_limite).replace(tzinfo=None)
        updates.append('fecha_limite = %s')
        params.append(fecha_limite)

    if puntaje_maximo is not None:
        try:
            puntaje_maximo = float(puntaje_maximo)
        except ValueError:
            return JsonResponse({'success': False, 'message': 'puntaje_maximo inválido'})
        if puntaje_maximo <= 0:
            return JsonResponse({'success': False, 'message': 'puntaje_maximo debe ser mayor a 0'})
        updates.append('puntaje_maximo = %s')
        params.append(puntaje_maximo)

    if permite_entrega_tardia is not None:
        updates.append('permite_entrega_tardia = %s')
        params.append(1 if _to_bool(permite_entrega_tardia) else 0)

    if estado is not None:
        estado = str(estado).strip().lower()
        if estado not in ('borrador', 'publicado', 'cerrado', 'archivado'):
            return JsonResponse({'success': False, 'message': 'estado inválido'})
        updates.append('estado = %s')
        params.append(estado)

    if not updates:
        return JsonResponse({'success': False, 'message': 'No hay campos para actualizar'})

    updates.append('fecha_actualizacion = GETDATE()')

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM Entregables
                WHERE entregable_id = %s AND instructor_id = %s
                """,
                [entregable_id, instructor_id]
            )
            if cursor.fetchone()[0] == 0:
                return JsonResponse({'success': False, 'message': 'No tienes permisos para editar este entregable'})

            query = f"UPDATE Entregables SET {', '.join(updates)} WHERE entregable_id = %s"
            cursor.execute(query, params + [entregable_id])

        return JsonResponse({'success': True, 'message': 'Entregable actualizado correctamente'})
    except DatabaseError as e:
        db_error = str(e)
        if 'CK_Entregables_fechas' in db_error:
            return JsonResponse({'success': False, 'message': 'La fecha límite no cumple la regla de fechas del sistema'}, status=400)
        return JsonResponse({'success': False, 'message': f'Error actualizando entregable: {db_error}'}, status=500)


@csrf_exempt
def eliminar_entregable(request):
    """Elimina un entregable del instructor propietario si no tiene entregas registradas."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'})

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, TypeError, ValueError):
        return JsonResponse({'success': False, 'message': 'JSON inválido'})

    instructor_id = data.get('instructor_id')
    entregable_id = data.get('entregable_id')

    if not instructor_id or not entregable_id:
        return JsonResponse({'success': False, 'message': 'instructor_id y entregable_id son requeridos'})

    try:
        instructor_id = int(instructor_id)
        entregable_id = int(entregable_id)
    except ValueError:
        return JsonResponse({'success': False, 'message': 'IDs inválidos'})

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM Entregables
                WHERE entregable_id = %s AND instructor_id = %s
                """,
                [entregable_id, instructor_id]
            )
            if cursor.fetchone()[0] == 0:
                return JsonResponse({'success': False, 'message': 'No tienes permisos para eliminar este entregable'})

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM Entregas
                WHERE entregable_id = %s
                """,
                [entregable_id]
            )
            if cursor.fetchone()[0] > 0:
                return JsonResponse({'success': False, 'message': 'No se puede eliminar: este entregable ya tiene entregas registradas'})

            cursor.execute("DELETE FROM Entregables WHERE entregable_id = %s", [entregable_id])

        return JsonResponse({'success': True, 'message': 'Entregable eliminado correctamente'})
    except DatabaseError as e:
        return JsonResponse({'success': False, 'message': f'Error eliminando entregable: {str(e)}'}, status=500)


@csrf_exempt
def entregables_estudiante(request):
    """Lista entregables publicados para cursos inscritos del estudiante con su estado de entrega."""
    if request.method != 'GET':
        return JsonResponse({'error': 'Método no permitido'})

    estudiante_id = request.GET.get('estudiante_id')
    if not estudiante_id:
        return JsonResponse({'success': False, 'message': 'Se requiere estudiante_id'})

    try:
        estudiante_id = int(estudiante_id)
    except ValueError:
        return JsonResponse({'success': False, 'message': 'estudiante_id inválido'})

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    e.entregable_id,
                    e.curso_id,
                    c.nombre_curso,
                    e.titulo,
                    e.descripcion,
                    e.fecha_publicacion,
                    e.fecha_limite,
                    e.puntaje_maximo,
                    e.permite_entrega_tardia,
                    e.estado,
                    en.entrega_id,
                    en.fecha_entrega,
                    en.estado_entrega,
                    en.calificacion,
                    en.puntaje_obtenido,
                    en.retroalimentacion,
                    en.archivo_ruta,
                    en.archivo_nombre_original
                FROM Entregables e
                JOIN Cursos c ON c.curso_id = e.curso_id
                LEFT JOIN Entregas en
                    ON en.entregable_id = e.entregable_id
                    AND en.estudiante_id = %s
                WHERE e.estado IN ('publicado', 'cerrado')
                  AND EXISTS (
                      SELECT 1
                      FROM Inscripciones i
                      WHERE i.estudiante_id = %s
                        AND i.curso_id = e.curso_id
                        AND i.estado IN ('activa', 'finalizada')
                  )
                ORDER BY e.fecha_limite ASC, e.entregable_id DESC
                """,
                [estudiante_id, estudiante_id]
            )
            rows = cursor.fetchall()

        resultado = []
        for row in rows:
            resultado.append({
                'entregable_id': row[0],
                'curso_id': row[1],
                'nombre_curso': row[2],
                'titulo': row[3],
                'descripcion': row[4],
                'fecha_publicacion': str(row[5]) if row[5] else None,
                'fecha_limite': str(row[6]) if row[6] else None,
                'puntaje_maximo': float(row[7]) if row[7] is not None else None,
                'permite_entrega_tardia': bool(row[8]),
                'estado': row[9],
                'entrega_id': row[10],
                'fecha_entrega': str(row[11]) if row[11] else None,
                'estado_entrega': row[12],
                'calificacion': float(row[13]) if row[13] is not None else None,
                'puntaje_obtenido': float(row[14]) if row[14] is not None else None,
                'retroalimentacion': row[15],
                'archivo_ruta': row[16],
                'archivo_nombre_original': row[17]
            })

        return JsonResponse(resultado, safe=False)
    except DatabaseError as e:
        return JsonResponse({'success': False, 'message': f'Error listando entregables: {str(e)}'}, status=500)


@csrf_exempt
def subir_entrega(request):
    """Sube o reemplaza una entrega de estudiante para un entregable."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'})

    entregable_id = request.POST.get('entregable_id')
    estudiante_id = request.POST.get('estudiante_id')
    observaciones = (request.POST.get('observaciones_estudiante') or '').strip()
    archivo = request.FILES.get('archivo')

    if not entregable_id or not estudiante_id or not archivo:
        return JsonResponse({'success': False, 'message': 'entregable_id, estudiante_id y archivo son requeridos'})

    try:
        entregable_id = int(entregable_id)
        estudiante_id = int(estudiante_id)
    except ValueError:
        return JsonResponse({'success': False, 'message': 'IDs inválidos'})

    allowed_ext = {'.pdf', '.doc', '.docx', '.zip', '.rar', '.7z', '.txt', '.ppt', '.pptx', '.xlsx', '.xls'}
    ext = os.path.splitext(archivo.name)[1].lower()
    if ext not in allowed_ext:
        return JsonResponse({'success': False, 'message': f'Tipo de archivo no permitido: {ext}'})

    max_size = 20 * 1024 * 1024
    if archivo.size > max_size:
        return JsonResponse({'success': False, 'message': 'El archivo excede el máximo de 20MB'})

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT entregable_id, curso_id, fecha_limite, permite_entrega_tardia, estado
                FROM Entregables
                WHERE entregable_id = %s
                """,
                [entregable_id]
            )
            entregable = cursor.fetchone()

            if not entregable:
                return JsonResponse({'success': False, 'message': 'El entregable no existe'})

            curso_id = entregable[1]
            fecha_limite = entregable[2]
            permite_tardia = bool(entregable[3])
            estado_entregable = entregable[4]

            if estado_entregable not in ('publicado', 'cerrado'):
                return JsonResponse({'success': False, 'message': 'El entregable no está disponible para envío'})

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM Inscripciones
                WHERE estudiante_id = %s
                  AND curso_id = %s
                  AND estado IN ('activa', 'finalizada')
                """,
                [estudiante_id, curso_id]
            )
            if cursor.fetchone()[0] == 0:
                return JsonResponse({'success': False, 'message': 'El estudiante no está inscrito en el curso del entregable'})

            now_dt = datetime.now(fecha_limite.tzinfo) if hasattr(fecha_limite, 'tzinfo') else datetime.now()
            es_tardia = bool(fecha_limite and now_dt > fecha_limite)
            if es_tardia and not permite_tardia:
                return JsonResponse({'success': False, 'message': 'La fecha límite ya venció y no se permiten entregas tardías'})

            estado_entrega = 'tarde' if es_tardia else 'enviada'

            upload_dir = os.path.join(settings.MEDIA_ROOT, 'entregas')
            os.makedirs(upload_dir, exist_ok=True)
            unique_name = f"entrega_{entregable_id}_{estudiante_id}_{uuid.uuid4().hex}{ext}"
            abs_path = os.path.join(upload_dir, unique_name)

            with open(abs_path, 'wb+') as destination:
                for chunk in archivo.chunks():
                    destination.write(chunk)

            rel_path = f"entregas/{unique_name}"
            mime = getattr(archivo, 'content_type', None)
            size_bytes = int(archivo.size)

            cursor.execute(
                """
                SELECT entrega_id
                FROM Entregas
                WHERE entregable_id = %s AND estudiante_id = %s
                """,
                [entregable_id, estudiante_id]
            )
            existente = cursor.fetchone()

            if existente:
                entrega_id = int(existente[0])
                cursor.execute(
                    """
                    UPDATE Entregas
                    SET fecha_entrega = GETDATE(),
                        estado_entrega = %s,
                        archivo_ruta = %s,
                        archivo_nombre_original = %s,
                        archivo_extension = %s,
                        archivo_mime = %s,
                        archivo_tamano_bytes = %s,
                        observaciones_estudiante = %s,
                        calificacion = NULL,
                        puntaje_obtenido = NULL,
                        retroalimentacion = NULL,
                        instructor_calificador_id = NULL,
                        fecha_calificacion = NULL,
                        fecha_actualizacion = GETDATE()
                    WHERE entrega_id = %s
                    """,
                    [
                        estado_entrega,
                        rel_path,
                        archivo.name,
                        ext,
                        mime,
                        size_bytes,
                        observaciones or None,
                        entrega_id,
                    ]
                )
                mensaje = 'Entrega reemplazada correctamente'
            else:
                cursor.execute(
                    """
                    INSERT INTO Entregas
                        (entregable_id, estudiante_id, estado_entrega, archivo_ruta, archivo_nombre_original,
                         archivo_extension, archivo_mime, archivo_tamano_bytes, observaciones_estudiante, fecha_actualizacion)
                    OUTPUT INSERTED.entrega_id
                    VALUES
                        (%s, %s, %s, %s, %s, %s, %s, %s, %s, GETDATE())
                    """,
                    [
                        entregable_id,
                        estudiante_id,
                        estado_entrega,
                        rel_path,
                        archivo.name,
                        ext,
                        mime,
                        size_bytes,
                        observaciones or None,
                    ]
                )
                new_row = cursor.fetchone()
                entrega_id = int(new_row[0]) if new_row else None
                mensaje = 'Entrega subida correctamente'

        return JsonResponse({'success': True, 'message': mensaje, 'entrega_id': entrega_id, 'estado_entrega': estado_entrega, 'archivo_ruta': rel_path})
    except DatabaseError as e:
        return JsonResponse({'success': False, 'message': f'Error subiendo entrega: {str(e)}'}, status=500)


@csrf_exempt
def entregas_por_entregable(request):
    """Lista entregas de un entregable para revisión del instructor."""
    if request.method != 'GET':
        return JsonResponse({'error': 'Método no permitido'})

    instructor_id = request.GET.get('instructor_id')
    entregable_id = request.GET.get('entregable_id')

    if not instructor_id or not entregable_id:
        return JsonResponse({'success': False, 'message': 'instructor_id y entregable_id son requeridos'})

    try:
        instructor_id = int(instructor_id)
        entregable_id = int(entregable_id)
    except ValueError:
        return JsonResponse({'success': False, 'message': 'Parámetros inválidos'})

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM Entregables
                WHERE entregable_id = %s AND instructor_id = %s
                """,
                [entregable_id, instructor_id]
            )
            if cursor.fetchone()[0] == 0:
                return JsonResponse({'success': False, 'message': 'No tienes permisos para ver este entregable'})

            cursor.execute(
                """
                SELECT
                    en.entrega_id,
                    en.entregable_id,
                    en.estudiante_id,
                    es.nombre_completo,
                    en.fecha_entrega,
                    en.estado_entrega,
                    en.archivo_ruta,
                    en.archivo_nombre_original,
                    en.archivo_tamano_bytes,
                    en.calificacion,
                    en.puntaje_obtenido,
                    en.retroalimentacion,
                    en.fecha_calificacion,
                    en.observaciones_estudiante
                FROM Entregas en
                JOIN Estudiantes es ON es.estudiante_id = en.estudiante_id
                WHERE en.entregable_id = %s
                ORDER BY en.fecha_entrega DESC
                """,
                [entregable_id]
            )
            rows = cursor.fetchall()

        resultado = []
        for row in rows:
            resultado.append({
                'entrega_id': row[0],
                'entregable_id': row[1],
                'estudiante_id': row[2],
                'nombre_estudiante': row[3],
                'fecha_entrega': str(row[4]) if row[4] else None,
                'estado_entrega': row[5],
                'archivo_ruta': row[6],
                'archivo_nombre_original': row[7],
                'archivo_tamano_bytes': int(row[8]) if row[8] is not None else None,
                'calificacion': float(row[9]) if row[9] is not None else None,
                'puntaje_obtenido': float(row[10]) if row[10] is not None else None,
                'retroalimentacion': row[11],
                'fecha_calificacion': str(row[12]) if row[12] else None,
                'observaciones_estudiante': row[13],
            })

        return JsonResponse(resultado, safe=False)
    except DatabaseError as e:
        return JsonResponse({'success': False, 'message': f'Error listando entregas: {str(e)}'}, status=500)


@csrf_exempt
def calificar_entrega(request):
    """Califica una entrega y guarda retroalimentación."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'})

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, TypeError, ValueError):
        return JsonResponse({'success': False, 'message': 'JSON inválido'})

    instructor_id = data.get('instructor_id')
    entrega_id = data.get('entrega_id')
    calificacion = data.get('calificacion')
    puntaje_obtenido = data.get('puntaje_obtenido')
    retroalimentacion = (data.get('retroalimentacion') or '').strip()

    if instructor_id is None or entrega_id is None or calificacion is None:
        return JsonResponse({'success': False, 'message': 'instructor_id, entrega_id y calificacion son requeridos'})

    try:
        instructor_id = int(instructor_id)
        entrega_id = int(entrega_id)
        calificacion = float(calificacion)
        if puntaje_obtenido is not None and str(puntaje_obtenido).strip() != '':
            puntaje_obtenido = float(puntaje_obtenido)
        else:
            puntaje_obtenido = None
    except ValueError:
        return JsonResponse({'success': False, 'message': 'Parámetros inválidos'})

    if calificacion < 0 or calificacion > 100:
        return JsonResponse({'success': False, 'message': 'calificacion debe estar entre 0 y 100'})

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT e.entregable_id, e.instructor_id, e.puntaje_maximo
                FROM Entregas en
                JOIN Entregables e ON e.entregable_id = en.entregable_id
                WHERE en.entrega_id = %s
                """,
                [entrega_id]
            )
            row = cursor.fetchone()
            if not row:
                return JsonResponse({'success': False, 'message': 'La entrega no existe'})

            entregable_id = int(row[0])
            owner_instructor_id = int(row[1])
            puntaje_maximo = float(row[2]) if row[2] is not None else 100.0

            if owner_instructor_id != instructor_id:
                return JsonResponse({'success': False, 'message': 'No tienes permisos para calificar esta entrega'})

            if puntaje_obtenido is None:
                puntaje_obtenido = round((calificacion / 100.0) * puntaje_maximo, 2)

            if puntaje_obtenido < 0 or puntaje_obtenido > puntaje_maximo:
                return JsonResponse({'success': False, 'message': f'puntaje_obtenido debe estar entre 0 y {puntaje_maximo}'})

            cursor.execute(
                """
                UPDATE Entregas
                SET calificacion = %s,
                    puntaje_obtenido = %s,
                    retroalimentacion = %s,
                    instructor_calificador_id = %s,
                    fecha_calificacion = GETDATE(),
                    estado_entrega = 'calificada',
                    fecha_actualizacion = GETDATE()
                WHERE entrega_id = %s
                """,
                [calificacion, puntaje_obtenido, retroalimentacion or None, instructor_id, entrega_id]
            )

        return JsonResponse({'success': True, 'message': 'Entrega calificada correctamente', 'entregable_id': entregable_id})
    except DatabaseError as e:
        return JsonResponse({'success': False, 'message': f'Error calificando entrega: {str(e)}'}, status=500)
