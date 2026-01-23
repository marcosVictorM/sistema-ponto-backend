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

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def gerar_relatorio_pdf(request):
    usuario = request.user
    data_inicio_str = request.data.get('data_inicio')
    data_fim_str = request.data.get('data_fim')
    
    # Converte strings para date
    d_inicio = datetime.strptime(data_inicio_str, '%Y-%m-%d').date()
    d_fim = datetime.strptime(data_fim_str, '%Y-%m-%d').date()

    # Configura Response como PDF
    response = HttpResponse(content_type='application/pdf')
    # Adicionei timestamp para evitar cache
    filename = f"ponto_{usuario.username}_{d_inicio}_{d_fim}.pdf"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    # Cria o Canvas
    p = canvas.Canvas(response, pagesize=A4)
    width, height = A4
    y = height - 50 

    # --- 1. CABEÇALHO ---
    p.setFont("Helvetica-Bold", 16)
    p.drawString(50, y, f"Espelho de Ponto: {usuario.username}")
    y -= 25
    p.setFont("Helvetica", 12)
    p.drawString(50, y, f"Período: {d_inicio.strftime('%d/%m/%Y')} a {d_fim.strftime('%d/%m/%Y')}")
    y -= 30
    
    # --- 2. COLUNAS ---
    p.setFont("Helvetica-Bold", 10)
    p.drawString(40, y, "Data")       # Coluna 1
    p.drawString(110, y, "Entrada/Saídas") # Coluna 2 (Mais espaço)
    p.drawString(380, y, "Trab.")     # Coluna 3
    p.drawString(450, y, "Saldo")      # Coluna 4
    y -= 10
    p.line(40, y, 550, y)
    y -= 15
    
    # --- 3. PREPARAÇÃO DOS DADOS (Igual ao App) ---
    # Busca registros do período
    registros_banco = RegistroPonto.objects.filter(
        usuario=usuario,
        data_hora__date__gte=d_inicio,
        data_hora__date__lte=d_fim
    ).order_by('data_hora')
    
    mapa_pontos = {}
    for r in registros_banco:
        d_str = r.data_hora.astimezone().strftime('%Y-%m-%d')
        if d_str not in mapa_pontos: mapa_pontos[d_str] = []
        mapa_pontos[d_str].append(r)

    # Busca Exceções
    lista_feriados = []
    lista_recessos = []
    if usuario.empresa:
        lista_feriados = Feriado.objects.filter(empresa=usuario.empresa).values_list('data', flat=True)
        lista_recessos = Recesso.objects.filter(empresa=usuario.empresa)

    # Regras de Jornada
    meta_padrao = 480 
    dias_trabalho = [0, 1, 2, 3, 4] 

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

    # --- 4. LOOP DE IMPRESSÃO (Dia a Dia) ---
    p.setFont("Helvetica", 9) # Fonte menor para caber tudo
    cursor = d_inicio
    
    while cursor <= d_fim:
        data_str = cursor.strftime('%Y-%m-%d')
        dia_semana = cursor.weekday()
        
        # A. Verifica Exceções
        eh_folga = False
        motivo = ""
        if cursor in lista_feriados: eh_folga = True; motivo = "(Feriado)"
        if not eh_folga:
            for rec in lista_recessos:
                if rec.data_inicio <= cursor <= rec.data_fim: eh_folga = True; motivo = "(Recesso)"; break
        
        # B. Define Meta
        if eh_folga: meta_dia = 0
        elif dia_semana in dias_trabalho: meta_dia = meta_padrao
        else: meta_dia = 0

        # C. Calcula Horas
        pontos = mapa_pontos.get(data_str, [])
        horarios_dt = [pt.data_hora for pt in pontos]
        horarios_dt.sort()
        
        minutos_trab = 0
        horarios_texto = [] # Para imprimir na coluna 2
        
        # Formata horários para texto (ex: "08:00 | 12:00")
        for pt in pontos:
            horarios_texto.append(pt.data_hora.astimezone().strftime('%H:%M'))
        
        # Cálculo matemático
        for i in range(0, len(horarios_dt), 2):
            if i+1 < len(horarios_dt):
                delta = (horarios_dt[i+1] - horarios_dt[i]).total_seconds() / 60
                minutos_trab += delta

        # D. Lógica de Falta / Saldo
        saldo = minutos_trab - meta_dia
        eh_falta = (meta_dia > 0 and minutos_trab == 0 and cursor < date.today())
        
        # Textos Finais
        str_data = cursor.strftime('%d/%m/%Y')
        str_batidas = " | ".join(horarios_texto)
        str_trab = f"{int(minutos_trab//60):02d}:{int(minutos_trab%60):02d}"
        
        sinal = "+" if saldo >= 0 else "-"
        saldo_abs = abs(saldo)
        str_saldo = f"{sinal}{int(saldo_abs//60):02d}:{int(saldo_abs%60):02d}"

        # Ajustes Visuais para Exceções
        cor_linha = colors.black
        if eh_folga:
            str_batidas = motivo # Escreve "Feriado" no lugar das horas
            str_trab = "-"
            str_saldo = "-"
            cor_linha = colors.blue
        elif eh_falta:
            str_batidas = "FALTA"
            str_trab = "00:00"
            # Saldo já calculado como negativo ali em cima
            cor_linha = colors.red

        # --- IMPRESSÃO NO PDF ---
        # Verifica quebra de página
        if y < 50:
            p.showPage()
            y = height - 50
            p.setFont("Helvetica", 9)
        
        p.setFillColor(cor_linha)
        p.drawString(40, y, str_data)
        p.drawString(110, y, str_batidas[:55]) # Corta se for muito longo
        p.drawString(380, y, str_trab)
        p.drawString(450, y, str_saldo)
        
        y -= 15 # Pula linha
        p.setFillColor(colors.black) # Reseta cor
        p.line(40, y+12, 550, y+12) # Linha divisória fina

        cursor += timedelta(days=1)

    p.showPage()
    p.save()
    return response