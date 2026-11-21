from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def brl(valor):
    """Formata como moeda brasileira: 1234.5 -> R$ 1.234,50"""
    try:
        v = Decimal(valor)
    except (InvalidOperation, TypeError, ValueError):
        return valor
    sinal = "-" if v < 0 else ""
    texto = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{sinal}R$ {texto}"


@register.filter
def limitar(valor, maximo=100):
    try:
        return min(float(valor), float(maximo))
    except (TypeError, ValueError):
        return 0


@register.simple_tag(takes_context=True)
def qs(context, **kwargs):
    """Mantém a querystring atual trocando só alguns parâmetros."""
    params = context["request"].GET.copy()
    for k, v in kwargs.items():
        if v in (None, ""):
            params.pop(k, None)
        else:
            params[k] = v
    return "?" + params.urlencode() if params else "?"
