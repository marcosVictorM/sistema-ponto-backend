from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import api_view, permission_classes
from rest_framework import status
from django.utils import timezone
from datetime import timedelta, datetime
from .models import RegistroPonto
from .serializers import RegistroPontoSerializer

# --- CLASSE 1: STATUS DO DIA (Tela Principal) ---
class StatusPontoView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        usuario = request.user
        # FIX: Usa a data local do Brasil, não a do servidor (UTC)
        hoje = timezone.localdate()
        
        registros_hoje = RegistroPonto.objects.filter(
            usuario=usuario, 
            data_hora__date=hoje
        ).order_by('data_hora')

        # === LÓGICA DE CÁLCULO DE HORAS DO DIA ===
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
        
        total_segundos = int(horas_trabalhadas.total_seconds())
        horas, remainder = divmod(total_segundos, 3600)
        minutos, _ = divmod(remainder, 60)
        horas_formatadas = f"{horas:02}:{minutos:02}"
        # =========================================

        ultimo_registro = registros_hoje.last()

        # Máquina de Estados (Define qual o próximo botão)
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
            'horas_trabalhadas': horas_formatadas
        })

# --- CLASSE 2: REGISTRAR BATIDA (Botão) ---
class RegistrarPontoView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        usuario = request.user
        dados = request.data
        
        tipo_enviado = dados.get('tipo')
        lat = dados.get('latitude')
        long = dados.get('longitude')
        
        novo_ponto = RegistroPonto.objects.create(
            usuario=usuario,
            tipo=tipo_enviado,
            data_hora=timezone.now(), # Salva com fuso (UTC), o banco converte depois
            latitude=lat,
            longitude=long,
            localizacao_valida=True
        )
        
        return Response(RegistroPontoSerializer(novo_ponto).data, status=status.HTTP_201_CREATED)

# --- SUBSTITUIR SOMENTE A ÚLTIMA FUNÇÃO ---

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def relatorio_mensal(request):
    try:
        usuario = request.user
        hoje = timezone.localdate()
        data_inicio = hoje - timedelta(days=30)
        
        registros = RegistroPonto.objects.filter(
            usuario=usuario, 
            data_hora__date__gte=data_inicio
        ).order_by('-data_hora')

        dias_trabalhados = {}
        for ponto in registros:
            # TENTATIVA 1: Converter data com proteção
            try:
                data_str = ponto.data_hora.astimezone().strftime('%Y-%m-%d')
            except Exception as e:
                # Se der erro de timezone, usa a data crua do banco
                data_str = str(ponto.data_hora.date())

            if data_str not in dias_trabalhados:
                dias_trabalhados[data_str] = []
            dias_trabalhados[data_str].append(ponto.data_hora)

        historico = []
        saldo_minutos_total = 0
        JORNADA_PADRAO = 8 * 60

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
            # Proteção na comparação de data
            if data != str(hoje):
                saldo_dia = minutos_trabalhados - JORNADA_PADRAO
                saldo_minutos_total += saldo_dia
                sinal = "+" if saldo_dia >= 0 else "-"
                saldo_dia_str = f"{sinal}{int(abs(saldo_dia) // 60):02d}:{int(abs(saldo_dia) % 60):02d}"

            historico.append({
                "data": datetime.strptime(data, '%Y-%m-%d').strftime('%d/%m'),
                "horas_trabalhadas": tempo_formatado,
                "saldo_dia": saldo_dia_str
            })

        sinal_total = "+" if saldo_minutos_total >= 0 else "-"
        saldo_total_str = f"{sinal_total}{int(abs(saldo_minutos_total) // 60):02d}:{int(abs(saldo_minutos_total) % 60):02d}"

        return Response({
            "saldo_banco_horas": saldo_total_str,
            "historico": historico
        })

    except Exception as e:
        # AQUI ESTÁ O TRUQUE: Devolvemos o erro como se fosse o saldo!
        import traceback
        print(traceback.format_exc()) # Loga no servidor
        return Response({
            "saldo_banco_horas": f"ERRO: {str(e)}", 
            "historico": []
        })