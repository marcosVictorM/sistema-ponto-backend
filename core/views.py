from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import api_view, permission_classes
from rest_framework import status
from django.utils import timezone
from datetime import timedelta, datetime, date
from .models import RegistroPonto, Feriado, Recesso
from .serializers import RegistroPontoSerializer
from django.http import HttpResponse
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors

# --- CLASSE 1: STATUS DO DIA ---
class StatusPontoView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        usuario = request.user
        hoje = timezone.localdate()
        
        registros_hoje = RegistroPonto.objects.filter(
            usuario=usuario, 
            data_hora__date=hoje
        ).order_by('data_hora')

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

        ultimo_registro = registros_hoje.last()

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

# --- CLASSE 2: REGISTRAR BATIDA ---
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
            data_hora=timezone.now(), 
            latitude=lat,
            longitude=long,
            localizacao_valida=True
        )
        
        return Response(RegistroPontoSerializer(novo_ponto).data, status=status.HTTP_201_CREATED)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def relatorio_mensal(request):
    try:
        usuario = request.user
        hoje = timezone.localdate()
        
        # 1. Define o Início (Data de Apuração ou Padrão)
        cursor_data = date(2025, 1, 1) # Data de segurança antiga
        if usuario.data_inicio_apuracao:
            cursor_data = usuario.data_inicio_apuracao
        
        # 2. Busca TUDO do banco a partir da data de início
        # Otimização: Trazemos tudo para a memória para não consultar o banco dentro do loop
        registros_banco = RegistroPonto.objects.filter(
            usuario=usuario,
            data_hora__date__gte=cursor_data
        ).order_by('data_hora')
        
        # Organiza em dicionário para acesso rápido: {'2026-01-20': [Ponto1, Ponto2]}
        mapa_pontos = {}
        for p in registros_banco:
            d_str = p.data_hora.astimezone().strftime('%Y-%m-%d')
            if d_str not in mapa_pontos: mapa_pontos[d_str] = []
            mapa_pontos[d_str].append(p)

        # 3. Busca Exceções (Feriados/Recessos)
        lista_feriados = []
        lista_recessos = []
        if usuario.empresa:
            lista_feriados = Feriado.objects.filter(empresa=usuario.empresa).values_list('data', flat=True)
            lista_recessos = Recesso.objects.filter(empresa=usuario.empresa)

        # 4. Configura Regras de Jornada (Meta Diária)
        meta_padrao = 480 # 8 horas em minutos
        dias_trabalho = [0, 1, 2, 3, 4] # Seg-Sex

        if usuario.usar_configuracao_individual:
            dias_trabalho = []
            if usuario.trab_seg: dias_trabalho.append(0)
            if usuario.trab_ter: dias_trabalho.append(1)
            if usuario.trab_qua: dias_trabalho.append(2)
            if usuario.trab_qui: dias_trabalho.append(3)
            if usuario.trab_sex: dias_trabalho.append(4)
            if usuario.trab_sab: dias_trabalho.append(5)
            if usuario.trab_dom: dias_trabalho.append(6)
            if usuario.carga_horaria_diaria:
                meta_padrao = int(usuario.carga_horaria_diaria.total_seconds() // 60)
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
            if usuario.carga_horaria_diaria:
                meta_padrao = int(usuario.carga_horaria_diaria.total_seconds() // 60)
            elif esc.carga_horaria_diaria:
                meta_padrao = int(esc.carga_horaria_diaria.total_seconds() // 60)
        elif usuario.carga_horaria_diaria:
             meta_padrao = int(usuario.carga_horaria_diaria.total_seconds() // 60)

        # === LOOP PRINCIPAL: Percorre CADA DIA do calendário até hoje ===
        lista_final = []
        saldo_total = 0
        
        # Enquanto a data do cursor não passar de hoje...
        while cursor_data <= hoje:
            data_str = cursor_data.strftime('%Y-%m-%d')
            dia_semana = cursor_data.weekday()
            
            # A. Verifica Folga/Feriado
            eh_folga = False
            nome_motivo = ""
            
            if cursor_data in lista_feriados:
                eh_folga = True; nome_motivo = "(Feriado)"
            
            if not eh_folga:
                for recesso in lista_recessos:
                    if recesso.data_inicio <= cursor_data <= recesso.data_fim:
                        eh_folga = True; nome_motivo = "(Recesso)"; break

            # B. Define Meta do Dia
            if eh_folga: 
                meta_dia = 0
            elif dia_semana in dias_trabalho: 
                meta_dia = meta_padrao
            else: 
                meta_dia = 0

            # C. Calcula Trabalhado (Busca no dicionário se houve registro nesse dia)
            pontos_dia = mapa_pontos.get(data_str, [])
            horarios = [p.data_hora for p in pontos_dia]
            horarios.sort()
            
            minutos_trabalhados = 0
            for i in range(0, len(horarios), 2):
                if i+1 < len(horarios):
                    delta = (horarios[i+1] - horarios[i]).total_seconds() / 60
                    minutos_trabalhados += delta

            # D. Calcula Saldo do Dia
            saldo_str = "Em andamento"
            calcular_saldo = True
            
            # Regra para HOJE: Só desconta se já tiver batido a saída ou se não tiver registro nenhum (mas dia ainda não acabou)
            if cursor_data == hoje:
                if not pontos_dia: 
                    # Se não tem ponto hoje, não calcula saldo ainda (espera acabar o dia)
                    calcular_saldo = False 
                elif pontos_dia[-1].tipo != 'SAIDA': 
                    # Se tem ponto mas o último não é saída (ainda está trabalhando)
                    calcular_saldo = False 

            if calcular_saldo:
                saldo = minutos_trabalhados - meta_dia
                saldo_total += saldo
                
                sinal = "+" if saldo >= 0 else "-"
                saldo_abs = abs(saldo)
                saldo_str = f"{sinal}{int(saldo_abs//60):02d}:{int(saldo_abs%60):02d}"

            # E. Monta a Lista Visual (Apenas Mês Atual)
            # Regra de Exibição: Mostra se tiver ponto OU se for Falta OU se for Folga
            deve_mostrar_na_lista = False
            if cursor_data.month == hoje.month and cursor_data.year == hoje.year:
                deve_mostrar_na_lista = True
            
            # Detecta Falta: Deveria trabalhar (meta > 0), Trabalhou 0, e dia já passou (< hoje)
            eh_falta = (meta_dia > 0 and minutos_trabalhados == 0 and cursor_data < hoje)
            tem_registro = len(pontos_dia) > 0
            
            if deve_mostrar_na_lista and (tem_registro or eh_falta or eh_folga):
                h_trab = int(minutos_trabalhados // 60)
                m_trab = int(minutos_trabalhados % 60)
                str_trabalhado = f"{h_trab:02d}:{m_trab:02d}"
                
                label_data = cursor_data.strftime('%d/%m')
                # Adiciona etiqueta visual
                if eh_folga: label_data += f" {nome_motivo}"
                elif eh_falta: label_data += " (Falta)"

                lista_final.append({
                    "data": label_data,
                    "horas_trabalhadas": str_trabalhado,
                    "saldo_dia": saldo_str if calcular_saldo else "..."
                })

            # AVANÇA PARA O PRÓXIMO DIA
            cursor_data += timedelta(days=1) 

        # Formatação Final do Saldo Total
        sinal_t = "+" if saldo_total >= 0 else "-"
        total_abs = abs(saldo_total)
        total_str = f"{sinal_t}{int(total_abs//60):02d}:{int(total_abs%60):02d}"
        
        # Ordena visualmente do mais recente para o antigo
        lista_final.sort(key=lambda x: datetime.strptime(x['data'].split(' ')[0] + '/' + str(hoje.year), '%d/%m/%Y'), reverse=True)

        return Response({"saldo_banco_horas": total_str, "historico": lista_final})

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return Response({"saldo_banco_horas": "ERRO", "historico": []})

@api_view(['POST']) # Usaremos POST para enviar datas
@permission_classes([IsAuthenticated])
def gerar_relatorio_pdf(request):
    usuario = request.user
    data_inicio_str = request.data.get('data_inicio')
    data_fim_str = request.data.get('data_fim')
    
    # Configura Response como PDF
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="ponto_{usuario.username}.pdf"'
    
    # Cria o Canvas
    p = canvas.Canvas(response, pagesize=A4)
    width, height = A4
    y = height - 50 # Posição vertical inicial

    # Cabeçalho
    p.setFont("Helvetica-Bold", 16)
    p.drawString(50, y, f"Espelho de Ponto: {usuario.username}")
    y -= 25
    p.setFont("Helvetica", 12)
    p.drawString(50, y, f"Período: {data_inicio_str} a {data_fim_str}")
    y -= 30
    
    # Colunas
    p.setFont("Helvetica-Bold", 10)
    p.drawString(50, y, "Data")
    p.drawString(150, y, "Entrada/Saídas")
    p.drawString(350, y, "Trabalhado")
    p.drawString(450, y, "Saldo")
    y -= 10
    p.line(50, y, 550, y)
    y -= 20
    
    # --- AQUI VOCÊ REPLICA A LÓGICA DO LOOP DO RELATORIO_MENSAL ---
    # (Para simplificar o exemplo, vou fazer uma busca simples, mas 
    # o ideal é copiar a lógica de loop de datas que fizemos acima 
    # para pegar faltas também)
    
    d_inicio = datetime.strptime(data_inicio_str, '%Y-%m-%d').date()
    d_fim = datetime.strptime(data_fim_str, '%Y-%m-%d').date()
    
    registros = RegistroPonto.objects.filter(
        usuario=usuario,
        data_hora__date__gte=d_inicio,
        data_hora__date__lte=d_fim
    ).order_by('data_hora')
    
    # Agrupamento simples para o PDF
    dias = {}
    for r in registros:
        d = r.data_hora.astimezone().strftime('%d/%m/%Y')
        if d not in dias: dias[d] = []
        dias[d].append(r.data_hora.astimezone().strftime('%H:%M'))
        
    p.setFont("Helvetica", 10)
    for data, horarios in dias.items():
        if y < 50: # Nova página se acabar espaço
            p.showPage()
            y = height - 50
            
        horarios_str = " | ".join(horarios)
        p.drawString(50, y, data)
        p.drawString(150, y, horarios_str[:40]) # Corta se for mto longo
        
        # (Aqui você colocaria o cálculo de horas trabalhadas)
        p.drawString(350, y, "Calculando...") 
        
        y -= 20
        p.line(50, y+15, 550, y+15) # Linha divisória fraca

    p.showPage()
    p.save()
    return response