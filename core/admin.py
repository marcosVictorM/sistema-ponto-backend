from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
# ATENÇÃO: Importe apenas Usuario, não CustomUser
from .models import Usuario, Empresa, RegistroPonto, Escala

@admin.register(Escala)
class EscalaAdmin(admin.ModelAdmin):
    list_display = ('nome', 'carga_horaria_diaria', 'trabalha_sabado', 'trabalha_domingo')
    list_filter = ('trabalha_sabado', 'trabalha_domingo')

# Atualizando o Admin do USUARIO
class UsuarioAdmin(UserAdmin): # Mudei o nome para não confundir
    model = Usuario
    
    # Adicionamos os campos novos na lista
    list_display = ('username', 'email', 'empresa', 'escala', 'usar_configuracao_individual', 'is_staff')
    
    # Adicionamos os filtros novos
    list_filter = ('empresa', 'escala', 'usar_configuracao_individual', 'is_staff')

    fieldsets = UserAdmin.fieldsets + (
        ('Informações Profissionais', {
            'fields': ('empresa', 'tipo', 'carga_horaria', 'trabalho_hibrido')
        }),
        ('Configuração de Escala (Grupo)', {
            'fields': ('escala',),
            'description': 'Selecione uma escala pré-definida.'
        }),
        ('Configuração Individual', {
            'fields': (
                'usar_configuracao_individual', 
                ('trab_seg', 'trab_ter', 'trab_qua'),
                ('trab_qui', 'trab_sex', 'trab_sab', 'trab_dom')
            ),
            'classes': ('collapse',), 
        }),
    )

class RegistroPontoAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'tipo_formatado', 'data_hora_local', 'localizacao_valida')
    list_filter = ('usuario', 'tipo', 'data_hora', 'localizacao_valida')
    
    def data_hora_local(self, obj):
        from django.utils import timezone
        return timezone.localtime(obj.data_hora).strftime('%d/%m/%Y %H:%M')
    data_hora_local.short_description = 'Data/Hora'

    def tipo_formatado(self, obj):
        return obj.get_tipo_display()
    tipo_formatado.short_description = 'Tipo'

# REGISTRE O USUARIO COM A CLASSE NOVA
admin.site.register(Usuario, UsuarioAdmin)
admin.site.register(Empresa)
admin.site.register(RegistroPonto, RegistroPontoAdmin)