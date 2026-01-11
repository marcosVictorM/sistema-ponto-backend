import uuid
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils.translation import gettext_lazy as _
from datetime import timedelta

# --- 1. MODELO BASE ---
class ModeloBase(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

# --- 2. EMPRESA ---
class Empresa(ModeloBase):
    nome = models.CharField(max_length=255)
    cnpj = models.CharField(max_length=18, unique=True)
    latitude_escritorio = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude_escritorio = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    raio_permitido_metros = models.IntegerField(default=50, help_text="Raio em metros para permitir o ponto")
    
    def __str__(self):
        return self.nome

# --- 3. ESCALA (Grupo de Configuração) ---
class Escala(ModeloBase):
    nome = models.CharField(max_length=50, unique=True, help_text="Ex: Administrativo (Seg-Sex), Escala 12x36")
    # DurationField é o correto para "quantidade de tempo" (ex: 8 horas)
    carga_horaria_diaria = models.DurationField(default=timedelta(hours=8), help_text="Carga horária padrão (Ex: 08:00:00)")
    
    # Dias de Trabalho da Escala
    trabalha_segunda = models.BooleanField(default=True)
    trabalha_terca = models.BooleanField(default=True)
    trabalha_quarta = models.BooleanField(default=True)
    trabalha_quinta = models.BooleanField(default=True)
    trabalha_sexta = models.BooleanField(default=True)
    trabalha_sabado = models.BooleanField(default=False)
    trabalha_domingo = models.BooleanField(default=False)

    def __str__(self):
        return self.nome

# --- 4. USUARIO ---
class Usuario(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='funcionarios', null=True, blank=True)
    
    TIPO_CHOICES = (
        ('ADMIN', 'Administrador'),
        ('FUNCIONARIO', 'Funcionário'),
    )
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default='FUNCIONARIO')
    
    # --- CONFIGURAÇÃO DE JORNADA ---
    # CAMPO PADRONIZADO: carga_horaria_diaria
    carga_horaria_diaria = models.DurationField(null=True, blank=True, help_text="Ex: 08:00:00. Se vazio, usa a da Escala.")
    
    escala = models.ForeignKey(Escala, on_delete=models.SET_NULL, null=True, blank=True, related_name="usuarios")
    trabalho_hibrido = models.BooleanField(default=False, help_text="Se True, permite ponto fora do raio do escritório")

    # Configuração Individual
    usar_configuracao_individual = models.BooleanField(default=False, help_text="Se marcado, ignora a Escala e usa os dias abaixo.")
    
    # Dias Individuais
    trab_seg = models.BooleanField(default=True, verbose_name="Indiv. Segunda")
    trab_ter = models.BooleanField(default=True, verbose_name="Indiv. Terça")
    trab_qua = models.BooleanField(default=True, verbose_name="Indiv. Quarta")
    trab_qui = models.BooleanField(default=True, verbose_name="Indiv. Quinta")
    trab_sex = models.BooleanField(default=True, verbose_name="Indiv. Sexta")
    trab_sab = models.BooleanField(default=False, verbose_name="Indiv. Sábado")
    trab_dom = models.BooleanField(default=False, verbose_name="Indiv. Domingo")

    class Meta:
        verbose_name = 'Usuário'
        verbose_name_plural = 'Usuários'

# --- 5. REGISTRO PONTO ---
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
    
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    localizacao_valida = models.BooleanField(default=False)
    
    editado_manualmente = models.BooleanField(default=False)
    observacao = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-data_hora']
        indexes = [
            models.Index(fields=['usuario', 'data_hora']),
        ]

    def __str__(self):
        return f"{self.usuario.username} - {self.get_tipo_display()} - {self.data_hora}"