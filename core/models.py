import uuid
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils.translation import gettext_lazy as _
from django.utils import timezone

# Vamos criar modelos base para não repetir código (Audit Log)
class ModeloBase(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

class Empresa(ModeloBase):
    nome = models.CharField(max_length=255)
    cnpj = models.CharField(max_length=18, unique=True)
    # Configurações de Ponto da Empresa
    latitude_escritorio = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude_escritorio = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    raio_permitido_metros = models.IntegerField(default=50, help_text="Raio em metros para permitir o ponto")
    
    def __str__(self):
        return self.nome

class Usuario(AbstractUser):
    # Sobrescrevemos o ID padrão para usar UUID também
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Vínculo com a empresa (Essencial para SaaS Multi-tenant)
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='funcionarios', null=True, blank=True)
    
    # Tipos de usuário
    TIPO_CHOICES = (
        ('ADMIN', 'Administrador'),
        ('FUNCIONARIO', 'Funcionário'),
    )
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default='FUNCIONARIO')
    
    # Dados de trabalho
    carga_horaria_diaria = models.DurationField(null=True, blank=True, help_text="Ex: 08:00:00")
    trabalho_hibrido = models.BooleanField(default=False, help_text="Se True, permite ponto fora do raio do escritório")

    class Meta:
        verbose_name = 'Usuário'
        verbose_name_plural = 'Usuários'

class RegistroPonto(ModeloBase):
    TIPO_BATIDA = (
        ('ENTRADA', 'Entrada'),
        ('SAIDA_ALMOCO', 'Saída para Almoço'),
        ('VOLTA_ALMOCO', 'Volta do Almoço'),
        ('SAIDA', 'Saída do Expediente'),
    )

    usuario = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name='registros')
    data_hora = models.DateTimeField(help_text="Data e hora exata do registro")
    tipo = models.CharField(max_length=20, choices=TIPO_BATIDA)
    
    # Dados para Auditoria
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    localizacao_valida = models.BooleanField(default=False) # Se estava dentro do raio
    
    # Se o RH precisar corrigir manualmente
    editado_manualmente = models.BooleanField(default=False)
    observacao = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-data_hora']
        indexes = [
            models.Index(fields=['usuario', 'data_hora']),
        ]

    def __str__(self):
        # Converte o horário UTC para o horário local configurado (America/Sao_Paulo)
        data_local = timezone.localtime(self.data_hora)
        return f"{self.usuario.username} - {self.get_tipo_display()} - {data_local.strftime('%d/%m/%Y %H:%M')}"