from django.contrib import admin
from .models import (
    MetodosPago,
    Estudiantes,
    Cursos,
    Instructores,
    CursoInstructor,
    Inscripciones,
    Evaluaciones,
    Pagos,
    DetallePago,
)

@admin.register(MetodosPago)
class MetodosPagoAdmin(admin.ModelAdmin):
    list_display = ('metodo_id', 'nombre')
    search_fields = ('nombre',)

@admin.register(Estudiantes)
class EstudiantesAdmin(admin.ModelAdmin):
    list_display = ('estudiante_id', 'nombre_completo', 'telefono', 'direccion', 'tipo_documento', 'fecha_registro')
    search_fields = ('nombre_completo', 'tipo_documento')
    readonly_fields = ('fecha_registro',)

@admin.register(Cursos)
class CursosAdmin(admin.ModelAdmin):
    list_display = ('curso_id', 'nombre_curso', 'categoria', 'cupo_maximo', 'duracion_horas', 'costo', 'estado')
    list_filter = ('estado', 'categoria')
    search_fields = ('nombre_curso', 'categoria')

@admin.register(Instructores)
class InstructoresAdmin(admin.ModelAdmin):
    list_display = ('instructor_id', 'nombre_completo', 'especialidad', 'usuario', 'estado')
    list_filter = ('estado',)
    search_fields = ('nombre_completo', 'usuario', 'especialidad')

@admin.register(CursoInstructor)
class CursoInstructorAdmin(admin.ModelAdmin):
    list_display = ('curso', 'instructor')
    search_fields = ('curso__nombre_curso', 'instructor__nombre_completo')

@admin.register(Inscripciones)
class InscripcionesAdmin(admin.ModelAdmin):
    list_display = ('inscripcion_id', 'estudiante', 'curso', 'fecha_inscripcion', 'estado', 'total_pago')
    list_filter = ('estado', 'curso')
    search_fields = ('estudiante__nombre_completo', 'curso__nombre_curso')

@admin.register(Evaluaciones)
class EvaluacionesAdmin(admin.ModelAdmin):
    list_display = ('evaluacion_id', 'inscripcion', 'calificacion', 'fecha')
    exclude = ('comentarios',)
    search_fields = ('inscripcion__estudiante__nombre_completo',)

class DetallePagoInline(admin.TabularInline):
    model = DetallePago
    extra = 1
    fields = ('concepto', 'cantidad', 'precio_unitario')
    readonly_fields = ()

@admin.register(Pagos)
class PagosAdmin(admin.ModelAdmin):
    list_display = ('pago_id', 'inscripcion', 'estudiante', 'metodo', 'monto', 'fecha_pago', 'estado_pago')
    list_filter = ('metodo', 'fecha_pago')
    search_fields = ('inscripcion__estudiante__nombre_completo', 'inscripcion__curso__nombre_curso')
    readonly_fields = ('pago_id', 'fecha_pago', 'monto_total_inscripcion')
    fieldsets = (
        ('Información del Pago', {
            'fields': ('pago_id', 'inscripcion', 'metodo', 'fecha_pago')
        }),
        ('Montos', {
            'fields': ('monto', 'monto_total_inscripcion')
        }),
        ('Referencia', {
            'fields': ('referencia_pago',)
        }),
    )
    inlines = [DetallePagoInline]
    
    def estudiante(self, obj):
        return obj.inscripcion.estudiante.nombre_completo
    estudiante.short_description = 'Estudiante'
    
    def monto_total_inscripcion(self, obj):
        return obj.inscripcion.total_pago
    monto_total_inscripcion.short_description = 'Monto Total de Inscripción'
    
    def estado_pago(self, obj):
        if obj.monto and obj.monto >= obj.inscripcion.total_pago:
            return '✓ Pagado'
        elif obj.monto and obj.monto > 0:
            return '◐ Parcial'
        return '✗ Pendiente'
    estado_pago.short_description = 'Estado'

@admin.register(DetallePago)
class DetallePagoAdmin(admin.ModelAdmin):
    list_display = ('detalle_id', 'pago', 'concepto', 'cantidad', 'precio_unitario', 'subtotal')
    list_filter = ('pago__fecha_pago',)
    search_fields = ('concepto', 'pago__pago_id')
    
    def subtotal(self, obj):
        return obj.cantidad * obj.precio_unitario
    subtotal.short_description = 'Subtotal'
