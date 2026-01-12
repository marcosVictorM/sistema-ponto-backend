from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import Usuario, RegistroPonto, Empresa
from datetime import datetime, timedelta, time, date

class Command(BaseCommand):
    help = 'Popula o banco com sequencia de dias uteis para Kleisley'

    def handle(self, *args, **kwargs):
        # === CONFIGURAÇÕES ===
        USERNAME = 'kleisley'
        DATA_INICIAL = date(2025, 11, 1) # Começa 1 de Novembro
        
        # Lista de Feriados para pular (Formato AAAA-MM-DD)
        FERIADOS = [
            date(2025, 11, 2),  # Finados (Caiu domingo, mas bom prevenir)
            date(2025, 11, 15), # Proclamação (Sábado)
            date(2025, 11, 20), # Consciência Negra (Quinta) - PULAR
            date(2025, 12, 8),  # Imaculada Conceição (Segunda) - PULAR
            date(2025, 12, 25), # Natal
        ]
        # =====================

        # 1. Busca ou Cria o Usuário
        try:
            usuario = Usuario.objects.filter(username__iexact=USERNAME).first()
            if not usuario:
                self.stdout.write(self.style.WARNING(f'Criando usuário {USERNAME}...'))
                usuario = Usuario.objects.create_user(username=USERNAME, password='123', email='kleisley@exemplo.com')
                empresa = Empresa.objects.first()
                if empresa:
                    usuario.empresa = empresa
                    usuario.save()
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Erro usuário: {str(e)}'))
            return

        # 2. Dados Limpos (Entrada, Minutos Almoço, Saída)
        # Ordem sequencial de dias trabalhados
        dados_trabalho = [
            ("08:30", 20, "17:57"), # Dia 01
            ("08:30", 25, "17:24"), # Dia 02
            ("08:30", 30, "15:50"), # Dia 03
            ("08:30", 30, "15:45"), # ...
            ("08:30", 20, "17:23"),
            ("08:30", 25, "17:05"),
            ("12:56", 0,  "17:00"), # Dia 07 (Sem almoço)
            ("08:33", 30, "15:15"),
            ("08:32", 22, "16:33"),
            ("08:25", 23, "15:55"),
            ("08:30", 30, "16:02"),
            ("08:23", 40, "15:06"),
            ("08:32", 30, "15:45"),
            ("08:11", 10, "15:00"),
            ("08:26", 20, "16:01"),
            ("08:37", 17, "17:00"),
            ("08:05", 0,  "14:05"), # Dia 19 (Sem almoço)
            ("08:30", 25, "17:06"),
            ("08:20", 33, "15:50"),
            ("08:26", 12, "16:27"),
            ("08:30", 30, "15:15"), # Dia 23 (Estimado tratado como normal)
            ("08:28", 30, "15:55"),
            ("08:36", 20, "15:15"),
            ("08:28", 20, "16:00"),
            ("08:24", 26, "17:05"),
            ("08:30", 10, "17:15"),
            ("08:30", 20, "15:35"),
            ("08:30", 20, "17:00"),
            ("08:30", 20, "17:05")  # Dia 31 (Último registro)
        ]

        # 3. Processamento Inteligente
        data_cursor = DATA_INICIAL
        contador = 0

        self.stdout.write(f'--- Iniciando importação a partir de {data_cursor.strftime("%d/%m/%Y")} ---')

        for str_ent, min_almoco, str_sai in dados_trabalho:
            
            # --- LOOP PARA ENCONTRAR O PRÓXIMO DIA ÚTIL ---
            while True:
                # 0=Seg, 5=Sab, 6=Dom
                eh_fim_de_semana = data_cursor.weekday() >= 5
                eh_feriado = data_cursor in FERIADOS

                if eh_fim_de_semana or eh_feriado:
                    motivo = "Fim de Semana" if eh_fim_de_semana else "Feriado"
                    # self.stdout.write(f'Pulando {data_cursor} ({motivo})') # Descomente se quiser ver o log pulando
                    data_cursor += timedelta(days=1)
                else:
                    # Achamos um dia útil!
                    break
            # -----------------------------------------------

            self.stdout.write(f'Gravando dados no dia: {data_cursor.strftime("%d/%m/%Y")}')

            # Parse das horas
            h_ent, m_ent = map(int, str_ent.split(':'))
            h_sai, m_sai = map(int, str_sai.split(':'))

            # 1. ENTRADA
            dt_entrada = timezone.make_aware(datetime.combine(data_cursor, time(h_ent, m_ent)))
            self._criar_ponto(usuario, dt_entrada, 'ENTRADA')
            contador += 1

            # 2. ALMOÇO (Se houver)
            if min_almoco > 0:
                # Define Saída almoço padrão as 12:00
                hora_almoco = 12
                # Se a pessoa chegou depois das 12:00, ajusta almoço (não deve acontecer nesses dados, mas previne erro)
                if h_ent >= 12: 
                    hora_almoco = h_ent + 1

                dt_saida_almoco = timezone.make_aware(datetime.combine(data_cursor, time(hora_almoco, 0)))
                dt_volta_almoco = dt_saida_almoco + timedelta(minutes=min_almoco)

                self._criar_ponto(usuario, dt_saida_almoco, 'SAIDA_ALMOCO')
                self._criar_ponto(usuario, dt_volta_almoco, 'VOLTA_ALMOCO')
                contador += 2

            # 3. SAÍDA
            dt_saida = timezone.make_aware(datetime.combine(data_cursor, time(h_sai, m_sai)))
            self._criar_ponto(usuario, dt_saida, 'SAIDA')
            contador += 1
            
            # Avança o cursor para o dia seguinte antes da próxima iteração
            data_cursor += timedelta(days=1)

        self.stdout.write(self.style.SUCCESS(f'Concluído! {contador} batidas registradas.'))

    def _criar_ponto(self, usuario, data_hora, tipo):
        if not RegistroPonto.objects.filter(usuario=usuario, data_hora=data_hora).exists():
            RegistroPonto.objects.create(
                usuario=usuario,
                tipo=tipo,
                data_hora=data_hora,
                localizacao_valida=True,
                editado_manualmente=True,
                observacao="Importação Automática"
            )