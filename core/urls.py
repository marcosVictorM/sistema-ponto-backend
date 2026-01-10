from django.urls import path
from .views import StatusPontoView, RegistrarPontoView, relatorio_mensal # <--- Adicione o import aqui

urlpatterns = [
    path('status/', StatusPontoView.as_view(), name='status-ponto'),
    path('registrar/', RegistrarPontoView.as_view(), name='registrar-ponto'),
    path('historico/', relatorio_mensal, name='historico'), 
]