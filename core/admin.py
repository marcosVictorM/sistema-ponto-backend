from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import Usuario, Empresa, RegistroPonto

class CustomUserAdmin(UserAdmin):
    model = Usuario
    fieldsets = UserAdmin.fieldsets + (
        ('Informações Profissionais', {'fields': ('empresa', 'tipo', 'carga_horaria_diaria', 'trabalho_hibrido')}),
    )

# Configuração nova para o Ponto aparecer em colunas
class RegistroPontoAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'tipo_formatado', 'data_hora_local', 'localizacao_valida')
    list_filter = ('usuario', 'tipo', 'data_hora') # Cria filtros laterais
    
    # Função para mostrar a data bonitinha na coluna
    def data_hora_local(self, obj):
        from django.utils import timezone
        return timezone.localtime(obj.data_hora).strftime('%d/%m/%Y %H:%M')
    data_hora_local.short_description = 'Data/Hora'

    # Função para mostrar o tipo mais legível
    def tipo_formatado(self, obj):
        return obj.get_tipo_display()
    tipo_formatado.short_description = 'Tipo'

admin.site.register(Usuario, CustomUserAdmin)
admin.site.register(Empresa)
# Registramos com a configuração nova
admin.site.register(RegistroPonto, RegistroPontoAdmin)