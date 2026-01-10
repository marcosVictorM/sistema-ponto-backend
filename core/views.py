from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from django.utils import timezone
from .models import RegistroPonto
from .serializers import RegistroPontoSerializer
from datetime import timedelta, datetime
from django.db.models import Sum
from rest_framework.decorators import api_view, permission_classes


class StatusPontoView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        usuario = request.user
        hoje = timezone.now().date()
        
        registros_hoje = RegistroPonto.objects.filter(
            usuario=usuario, 
            data_hora__date=hoje
        ).order_by('data_hora')

        # === LÓGICA DE CÁLCULO DE HORAS ===
        horas_trabalhadas = timedelta(0)
        entrada_temp = None

        for registro in registros_hoje:
            if registro.tipo in ['ENTRADA', 'VOLTA_ALMOCO']:
                entrada_temp = registro.data_hora
            elif registro.tipo in ['SAIDA_ALMOCO', 'SAIDA']:
                if entrada_temp:
                    delta = registro.data_hora - entrada_temp
                    horas_trabalhadas += delta
                    entrada_temp = None
        
        # Se ele ainda está trabalhando (tem entrada sem saída), somamos até "agora" para mostrar em tempo real?
        # Para simplificar o MVP, vamos mostrar apenas o que já foi "fechado".
        
        # Convertendo para string "HH:MM"
        total_segundos = int(horas_trabalhadas.total_seconds())
        horas, remainder = divmod(total_segundos, 3600)
        minutos, _ = divmod(remainder, 60)
        horas_formatadas = f"{horas:02}:{minutos:02}"
        # ===================================

        ultimo_registro = registros_hoje.last()

        # (Mantém a lógica da Máquina de Estados igualzinha estava antes...)
        if not ultimo_registro:
            proximo = 'ENTRADA'
            mensagem = 'Registrar Entrada'
        elif ultimo_registro.tipo == 'ENTRADA':
            proximo = 'SAIDA_ALMOCO'
            mensagem = 'Sair para o Almoço'
        elif ultimo_registro.tipo == 'SAIDA_ALMOCO':
            proximo = 'VOLTA_ALMOCO'
            mensagem = 'Voltar do Almoço'
        elif ultimo_registro.tipo == 'VOLTA_ALMOCO':
            proximo = 'SAIDA'
            mensagem = 'Encerrar Expediente'
        else:
            proximo = 'FIM_DO_DIA'
            mensagem = 'Expediente Finalizado'

        return Response({
            'historico': RegistroPontoSerializer(registros_hoje, many=True).data,
            'ultimo_registro': RegistroPontoSerializer(ultimo_registro).data if ultimo_registro else None,
            'proxima_acao': proximo,
            'texto_botao': mensagem,
            'horas_trabalhadas': horas_formatadas # Enviamos o total calculado
        })
    
class RegistrarPontoView(APIView):
    """
    Recebe o clique do botão e salva no banco
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        usuario = request.user
        dados = request.data
        
        # Aqui validamos qual o tipo de batida com base na lógica do StatusPonto
        # (Replicamos a lógica ou confiamos no frontend enviar o tipo correto? 
        # Por segurança, o ideal é o backend decidir, mas para MVP vamos aceitar o tipo enviado)
        
        tipo_enviado = dados.get('tipo')
        lat = dados.get('latitude')
        long = dados.get('longitude')
        
        # TODO: Aqui entraria a lógica de calcular a distância (Geofencing)
        # Por enquanto vamos salvar direto
        
        novo_ponto = RegistroPonto.objects.create(
            usuario=usuario,
            tipo=tipo_enviado,
            data_hora=timezone.now(),
            latitude=lat,
            longitude=long,
            localizacao_valida=True # Assumindo válido para teste
        )
        
        return Response(RegistroPontoSerializer(novo_ponto).data, status=status.HTTP_201_CREATED)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def relatorio_mensal(request):
    usuario = request.user
    hoje = timezone.localdate()
    
    # Pega os últimos 30 dias
    data_inicio = hoje - timedelta(days=30)
    
    # Busca os pontos do usuário
    registros = RegistroPonto.objects.filter(
        usuario=usuario, 
        data_hora__date__gte=data_inicio
    ).order_by('-data_hora')

    # Agrupa os registros por dia
    dias_trabalhados = {}
    for ponto in registros:
        data_str = ponto.data_hora.astimezone().strftime('%Y-%m-%d')
        
        if data_str not in dias_trabalhados:
            dias_trabalhados[data_str] = []
        
        dias_trabalhados[data_str].append(ponto.data_hora)

    historico = []
    saldo_minutos_total = 0
    JORNADA_PADRAO = 8 * 60 # 480 minutos (8 horas)

    for data, horarios in dias_trabalhados.items():
        horarios.sort()
        minutos_trabalhados = 0
        
        for i in range(0, len(horarios), 2):
            if i + 1 < len(horarios):
                entrada = horarios[i]
                saida = horarios[i+1]
                diferenca = saida - entrada
                minutos_trabalhados += diferenca.total_seconds() / 60
        
        horas = int(minutos_trabalhados // 60)
        mins = int(minutos_trabalhados % 60)
        tempo_formatado = f"{horas:02d}:{mins:02d}"

        saldo_dia_str = "Em andamento"
        if data != hoje.strftime('%Y-%m-%d'):
            saldo_dia = minutos_trabalhados - JORNADA_PADRAO
            saldo_minutos_total += saldo_dia
            
            sinal = "+" if saldo_dia >= 0 else "-"
            saldo_abs = abs(saldo_dia)
            saldo_dia_str = f"{sinal}{int(saldo_abs // 60):02d}:{int(saldo_abs % 60):02d}"

        historico.append({
            "data": datetime.strptime(data, '%Y-%m-%d').strftime('%d/%m'),
            "horas_trabalhadas": tempo_formatado,
            "saldo_dia": saldo_dia_str
        })

    sinal_total = "+" if saldo_minutos_total >= 0 else "-"
    saldo_total_abs = abs(saldo_minutos_total)
    saldo_total_str = f"{sinal_total}{int(saldo_total_abs // 60):02d}:{int(saldo_total_abs % 60):02d}"

    return Response({
        "saldo_banco_horas": saldo_total_str,
        "historico": historico
    })