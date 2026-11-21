from . import services


def notificacoes(request):
    """Disponibiliza as notificações (sino do topo) em todas as páginas."""
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}
    from .models import Perfil

    itens = services.alertas(request.user)
    urgentes = sum(1 for a in itens if a["nivel"] in ("atrasada", "hoje"))
    return {
        "notificacoes": itens,
        "notificacoes_urgentes": urgentes,
        "paleta": Perfil.de(request.user).paleta,
    }
