# Proyecto Escuela - Django + SQL Server

Aplicacion web academica desarrollada con Django para gestionar:

- Estudiantes
- Instructores
- Cursos
- Inscripciones
- Pagos
- Calificaciones
- Entregables/Tareas
- Reportes

## Stack

- Python 3.13.0
- Django 6.0.3
- SQL Server (via mssql-django 1.7 + pyodbc 5.3.0)
- ODBC Driver 17 for SQL Server

## Estructura principal

- `manage.py`
- `Base_De_Datos/`
- `mi_app/`
- `Base_De_Datos/static/`
- `SQL_BACKUP/PF1.bak`

## Requisitos previos

1. Windows con SQL Server instalado (se uso SQL Server Express).
2. ODBC Driver 17 for SQL Server instalado.
3. Python 3.13.
4. (Opcional) Visual Studio Code.

## Restaurar base de datos (SQL Server)

Este proyecto espera una base llamada `PF1` y por defecto usa la instancia:

- Servidor: `LAPVIC\\SQLEXPRESS`

El backup incluido es:

- `SQL_BACKUP/PF1.bak`

### Opcion A: desde SQL Server Management Studio (SSMS)

1. Abrir SSMS y conectarse a tu instancia.
2. Click derecho en Databases -> Restore Database.
3. Elegir Device -> seleccionar `SQL_BACKUP/PF1.bak`.
4. Definir nombre de base: `PF1`.
5. Aceptar restauracion.

### Opcion B: con script T-SQL

Ajusta rutas segun tu maquina y ejecuta:

```sql
RESTORE DATABASE PF1
FROM DISK = 'C:\\ruta\\a\\Base_De_Datos_Backup\\SQL_BACKUP\\PF1.bak'
WITH REPLACE;
```

## Configuracion del proyecto

La conexion esta en `Base_De_Datos/settings.py`:

```python
DATABASES = {
    'default': {
        'ENGINE': 'mssql',
        'NAME': 'PF1',
        'HOST': r'LAPVIC\\SQLEXPRESS',
        'OPTIONS': {
            'driver': 'ODBC Driver 17 for SQL Server',
            'trusted_connection': 'yes',
        }
    }
}
```

Si tu servidor no es `LAPVIC\\SQLEXPRESS`, cambia `HOST` por tu instancia.

## Instalacion y ejecucion

Desde la raiz del proyecto:

```powershell
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
python -m pip install --upgrade pip
pip install Django==6.0.3 mssql-django==1.7 pyodbc==5.3.0
python manage.py migrate
python manage.py runserver
```

Abrir en navegador:

- http://127.0.0.1:8000/

## Usuarios de prueba

Los accesos dependen de los registros existentes en la base restaurada `PF1`.

Si restauras el backup incluido, podras usar los usuarios ya cargados en esa base.

## Notas

- Este proyecto esta configurado para desarrollo (`DEBUG = True`).
- La carpeta `media/` se usa para entregas de estudiantes.
- `.gitignore` excluye entorno virtual, caches y artefactos locales.

## Solucion de problemas rapida

- Error de conexion SQL Server:
  - Verifica nombre de instancia en `HOST`.
  - Verifica que SQL Server este encendido.
  - Verifica ODBC Driver 17 instalado.
- Error de paquete `pyodbc`:
  - Reinstalar con `pip install --force-reinstall pyodbc`.
- Puerto ocupado en Django:
  - Ejecuta `python manage.py runserver 8001`.
