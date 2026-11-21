from django.contrib import admin

from .models import Cartao, Categoria, Lancamento, Recorrencia


@admin.register(Cartao)
class CartaoAdmin(admin.ModelAdmin):
    list_display = ("nome", "tipo", "final", "limite", "dia_fechamento", "dia_vencimento", "usuario", "ativo")
    list_filter = ("tipo", "ativo")


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ("nome", "tipo", "orcamento_mensal", "usuario")
    list_filter = ("tipo",)


@admin.register(Recorrencia)
class RecorrenciaAdmin(admin.ModelAdmin):
    list_display = ("descricao", "tipo", "natureza", "valor", "inicio", "fim", "ativa", "usuario")
    list_filter = ("tipo", "natureza", "ativa")


@admin.register(Lancamento)
class LancamentoAdmin(admin.ModelAdmin):
    list_display = ("descricao", "tipo", "natureza", "valor", "data", "competencia", "cartao", "forma", "pago")
    list_filter = ("tipo", "natureza", "forma", "pago", "competencia")
    search_fields = ("descricao",)
    date_hierarchy = "competencia"
