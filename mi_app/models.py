from django.db import models

class MetodosPago(models.Model):
    metodo_id = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=30, unique=True)

    class Meta:
        db_table = 'MetodosPago'

class Estudiantes(models.Model):
    estudiante_id = models.AutoField(primary_key=True)
    nombre_completo = models.CharField(max_length=100)
    email = models.BinaryField()  # Cifrado
    telefono = models.CharField(max_length=20, null=True, blank=True)
    direccion = models.CharField(max_length=150, null=True, blank=True)
    tipo_documento = models.CharField(max_length=20)
    numero_documento = models.BinaryField()  # Cifrado
    fecha_registro = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'Estudiantes'

class Cursos(models.Model):
    curso_id = models.AutoField(primary_key=True)
    nombre_curso = models.CharField(max_length=100)
    categoria = models.CharField(max_length=100)
    cupo_maximo = models.IntegerField(default=5)
    duracion_horas = models.IntegerField()
    costo = models.DecimalField(max_digits=10, decimal_places=2)
    estado = models.CharField(max_length=20, choices=[('activo', 'Activo'), ('inactivo', 'Inactivo')])

    class Meta:
        db_table = 'Cursos'

class Instructores(models.Model):
    instructor_id = models.AutoField(primary_key=True)
    nombre_completo = models.CharField(max_length=100)
    especialidad = models.CharField(max_length=50, null=True, blank=True)
    cedula_profesional = models.BinaryField()  # Cifrado
    usuario = models.CharField(max_length=50, unique=True)
    contrasena = models.BinaryField()  # Cifrado
    estado = models.CharField(max_length=20, choices=[('activo', 'Activo'), ('inactivo', 'Inactivo')])

    class Meta:
        db_table = 'Instructores'

class CursoInstructor(models.Model):
    curso = models.ForeignKey(Cursos, on_delete=models.CASCADE)
    instructor = models.ForeignKey(Instructores, on_delete=models.CASCADE)

    class Meta:
        db_table = 'Curso_Instructor'
        unique_together = ('curso', 'instructor')

class Inscripciones(models.Model):
    inscripcion_id = models.AutoField(primary_key=True)
    estudiante = models.ForeignKey(Estudiantes, on_delete=models.CASCADE)
    curso = models.ForeignKey(Cursos, on_delete=models.CASCADE)
    fecha_inscripcion = models.DateTimeField(auto_now_add=True)
    estado = models.CharField(max_length=20, choices=[('activa', 'Activa'), ('cancelada', 'Cancelada'), ('finalizada', 'Finalizada')])
    total_pago = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = 'Inscripciones'

class Evaluaciones(models.Model):
    evaluacion_id = models.AutoField(primary_key=True)
    inscripcion = models.ForeignKey(Inscripciones, on_delete=models.CASCADE)
    instructor = models.ForeignKey(Instructores, on_delete=models.SET_NULL, null=True, blank=True)
    calificacion = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    comentarios = models.BinaryField(null=True, blank=True)  # Cifrado
    tipo_evaluacion = models.CharField(max_length=50, choices=[('parcial', 'Parcial'), ('final', 'Final')], default='final')
    fecha = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'Evaluaciones'

class Pagos(models.Model):
    pago_id = models.AutoField(primary_key=True)
    inscripcion = models.ForeignKey(Inscripciones, on_delete=models.CASCADE)
    fecha_pago = models.DateTimeField(auto_now_add=True)
    metodo = models.ForeignKey(MetodosPago, on_delete=models.CASCADE)
    referencia_pago = models.BinaryField(null=True, blank=True)  # Cifrado
    monto = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        db_table = 'Pagos'

class DetallePago(models.Model):
    detalle_id = models.AutoField(primary_key=True)
    pago = models.ForeignKey(Pagos, on_delete=models.CASCADE)
    concepto = models.CharField(max_length=100)
    cantidad = models.IntegerField()
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = 'Detalle_Pago'