from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("registrar/", views.registrar, name="registrar"),
    path("lancamentos/", views.lancamento_lista, name="lancamentos"),
    path("lancamentos/novo/", views.lancamento_novo, name="lancamento_novo"),
    path("lancamentos/<int:pk>/", views.lancamento_editar, name="lancamento_editar"),
    path("lancamentos/<int:pk>/excluir/", views.lancamento_excluir, name="lancamento_excluir"),
    path("lancamentos/<int:pk>/pago/", views.lancamento_alternar_pago, name="lancamento_pago"),
    path("cartoes/", views.cartao_lista, name="cartoes"),
    path("cartoes/novo/", views.cartao_form, name="cartao_novo"),
    path("cartoes/<int:pk>/", views.cartao_form, name="cartao_editar"),
    path("cartoes/<int:pk>/excluir/", views.cartao_excluir, name="cartao_excluir"),
    path("cartoes/<int:pk>/pagar-fatura/", views.fatura_pagar, name="fatura_pagar"),
    path("categorias/", views.categoria_lista, name="categorias"),
    path("categorias/nova/", views.categoria_form, name="categoria_nova"),
    path("categorias/<int:pk>/", views.categoria_form, name="categoria_editar"),
    path("categorias/<int:pk>/excluir/", views.categoria_excluir, name="categoria_excluir"),
    path("recorrencias/", views.recorrencia_lista, name="recorrencias"),
    path("recorrencias/<int:pk>/", views.recorrencia_editar, name="recorrencia_editar"),
    path("exportar/", views.exportar, name="exportar"),
    path("aparencia/", views.aparencia, name="aparencia"),
]
