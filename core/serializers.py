from rest_framework import serializers
from .models import Usuario, Empresa, RegistroPonto

class EmpresaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Empresa
        fields = ['id', 'nome', 'latitude_escritorio', 'longitude_escritorio', 'raio_permitido_metros']

class UsuarioSerializer(serializers.ModelSerializer):
    empresa = EmpresaSerializer(read_only=True)
    
    class Meta:
        model = Usuario
        fields = ['id', 'username', 'email', 'tipo', 'empresa', 'carga_horaria_diaria']

class RegistroPontoSerializer(serializers.ModelSerializer):
    class Meta:
        model = RegistroPonto
        fields = ['id', 'data_hora', 'tipo', 'latitude', 'longitude', 'localizacao_valida']
        read_only_fields = ['localizacao_valida'] # O backend calcula isso, o usuário não envia