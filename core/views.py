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

# --- SUBSTITUA A ÚLTIMA FUNÇÃO POR ESTA ---

# --- SUBSTITUIR A FUNÇÃO RELATORIO_MENSAL ---

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def relatorio_mensal(request):
    try:
        usuario = request.user
        hoje = timezone.localdate()
        inicio = hoje - timedelta(days=30)
        
        registros = RegistroPonto.objects.filter(
            usuario=usuario, 
            data_hora__date__gte=inicio
        ).order_by('data_hora')
        
        dias = {}
        for p in registros:
            d_str = p.data_hora.astimezone().strftime('%Y-%m-%d')
            if d_str not in dias: dias[d_str] = []
            dias[d_str].append(p)

        lista_final = []
        saldo_total = 0
        
        # === 1. DEFINIÇÃO DA REGRA DE TRABALHO DO USUÁRIO ===
        # Padrão Inicial (Caso não tenha nada configurado)
        meta_padrao = 480 # 8 horas
        dias_trabalho = [0, 1, 2, 3, 4] # Seg a Sex (0=Seg, 6=Dom)

        # A. Checa Individual
        if usuario.usar_configuracao_individual:
            dias_trabalho = []
            if usuario.trab_seg: dias_trabalho.append(0)
            if usuario.trab_ter: dias_trabalho.append(1)
            if usuario.trab_qua: dias_trabalho.append(2)
            if usuario.trab_qui: dias_trabalho.append(3)
            if usuario.trab_sex: dias_trabalho.append(4)
            if usuario.trab_sab: dias_trabalho.append(5)
            if usuario.trab_dom: dias_trabalho.append(6)
            
            if usuario.carga_horaria:
                meta_padrao = (usuario.carga_horaria.hour * 60) + usuario.carga_horaria.minute

        # B. Checa Escala (Se não for individual e tiver escala)
        elif usuario.escala:
            esc = usuario.escala
            dias_trabalho = []
            if esc.trabalha_segunda: dias_trabalho.append(0)
            if esc.trabalha_terca: dias_trabalho.append(1)
            if esc.trabalha_quarta: dias_trabalho.append(2)
            if esc.trabalha_quinta: dias_trabalho.append(3)
            if esc.trabalha_sexta: dias_trabalho.append(4)
            if esc.trabalha_sabado: dias_trabalho.append(5)
            if esc.trabalha_domingo: dias_trabalho.append(6)

            # Carga horária: Usuário vence Escala. Escala vence Padrão.
            if usuario.carga_horaria:
                meta_padrao = (usuario.carga_horaria.hour * 60) + usuario.carga_horaria.minute
            else:
                meta_padrao = (esc.carga_horaria_diaria.hour * 60) + esc.carga_horaria_diaria.minute

        # C. Caso não tenha nada, mantém o padrão Seg-Sex e verifica só se usuario tem carga horaria avulsa
        elif usuario.carga_horaria:
             meta_padrao = (usuario.carga_horaria.hour * 60) + usuario.carga_horaria.minute
        
        # ====================================================

        for data_str, lista_pontos in dias.items():
            horarios = [p.data_hora for p in lista_pontos]
            horarios.sort()
            
            data_obj = datetime.strptime(data_str, '%Y-%m-%d').date()
            dia_semana = data_obj.weekday()
            
            # Verifica se o dia atual está na lista de dias de trabalho configurada
            if dia_semana in dias_trabalho:
                meta_dia = meta_padrao
            else:
                meta_dia = 0 # Folga / Fim de semana

            minutos_trabalhados = 0
            for i in range(0, len(horarios), 2):
                if i+1 < len(horarios):
                    delta = (horarios[i+1] - horarios[i]).total_seconds() / 60
                    minutos_trabalhados += delta
            
            h_trab = int(minutos_trabalhados // 60)
            m_trab = int(minutos_trabalhados % 60)
            str_trabalhado = f"{h_trab:02d}:{m_trab:02d}"

            saldo_str = "Em andamento"
            calcular_saldo = True
            if data_str == str(hoje):
                ultimo_tipo = lista_pontos[-1].tipo
                if ultimo_tipo != 'SAIDA': 
                    calcular_saldo = False
            
            if calcular_saldo:
                saldo = minutos_trabalhados - meta_dia
                saldo_total += saldo
                sinal = "+" if saldo >= 0 else "-"
                saldo_abs = abs(saldo)
                saldo_str = f"{sinal}{int(saldo_abs//60):02d}:{int(saldo_abs%60):02d}"

            lista_final.append({
                "data": data_obj.strftime('%d/%m'),
                "horas_trabalhadas": str_trabalhado,
                "saldo_dia": saldo_str
            })

        sinal_t = "+" if saldo_total >= 0 else "-"
        total_abs = abs(saldo_total)
        total_str = f"{sinal_t}{int(total_abs//60):02d}:{int(total_abs%60):02d}"
        
        lista_final.sort(key=lambda x: datetime.strptime(x['data'] + '/' + str(hoje.year), '%d/%m/%Y'), reverse=True)

        return Response({"saldo_banco_horas": total_str, "historico": lista_final})

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return Response({
            "saldo_banco_horas": "ERRO",
            "historico": [{"data": "ALERTA", "horas_trabalhadas": "Erro", "saldo_dia": str(e)}]
        })