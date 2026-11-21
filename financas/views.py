import json
from datetime import date

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.db.models import ProtectedError, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import services
from .excel import gerar_planilha
from .forms import CartaoForm, CategoriaForm, LancamentoForm, RecorrenciaForm
from .models import Cartao, Categoria, Lancamento, Natureza, Recorrencia, TipoLancamento, primeiro_dia, somar_meses

MESES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
MESES_LONGOS = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto",
                "Setembro", "Outubro", "Novembro", "Dezembro"]


# ---------- utilidades ----------

def mes_da_request(request) -> date:
    """Lê ?mes=AAAA-MM; padrão = mês atual."""
    valor = request.GET.get("mes", "")
    try:
        ano, mes = valor.split("-")
        return date(int(ano), int(mes), 1)
    except (ValueError, TypeError):
        return primeiro_dia(date.today())


def contexto_mes(mes: date) -> dict:
    return {
        "mes": mes,
        "mes_param": mes.strftime("%Y-%m"),
        "mes_nome": f"{MESES_LONGOS[mes.month - 1]} {mes.year}",
        "mes_anterior": somar_meses(mes, -1).strftime("%Y-%m"),
        "mes_seguinte": somar_meses(mes, 1).strftime("%Y-%m"),
    }


def preparar_usuario(request, mes: date):
    services.garantir_categorias_padrao(request.user)
    services.materializar_recorrencias(request.user, max(mes, somar_meses(primeiro_dia(date.today()), 1)))


def avisar_meta(request, lancamentos):
    """Mostra aviso se a despesa salva deixou a categoria perto ou acima do teto."""
    for l in lancamentos:
        aviso = services.aviso_de_meta(l)
        if aviso:
            nivel, texto = aviso
            (messages.error if nivel == "error" else messages.warning)(request, texto)


def voltar(request, padrao="lancamentos"):
    proximo = request.POST.get("next") or request.GET.get("next")
    if proximo and proximo.startswith("/") and not proximo.startswith("//"):
        return redirect(proximo)
    return redirect(padrao)


# ---------- conta ----------

def registrar(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = UserCreationForm(request.POST or None)
    for campo in form.fields.values():
        campo.widget.attrs["class"] = "input"
    if request.method == "POST" and form.is_valid():
        usuario = form.save()
        login(request, usuario)
        services.garantir_categorias_padrao(usuario)
        messages.success(request, "Conta criada! Comece cadastrando seus cartões.")
        return redirect("cartao_novo")
    return render(request, "registration/registrar.html", {"form": form})


# ---------- dashboard ----------

@login_required
def dashboard(request):
    mes = mes_da_request(request)
    preparar_usuario(request, mes)
    cartoes = list(Cartao.objects.do_usuario(request.user).filter(ativo=True))

    cartao = None
    if request.GET.get("cartao"):
        cartao = get_object_or_404(Cartao, pk=request.GET["cartao"], usuario=request.user)

    resumo = services.resumo_mes(request.user, mes, cartao)
    historico = services.historico_meses(request.user, mes, 6, cartao)
    recentes = services.lancamentos_do_mes(request.user, mes, cartao).order_by("-data", "-id")[:6]

    # Despesas do mês por cartão e por dia (para os cartões e o gráfico diário)
    despesas_mes = services.lancamentos_do_mes(request.user, mes).filter(tipo=TipoLancamento.DESPESA)
    # Gastos por dia da compra. A fatura de um cartão pode ter compras do mês anterior
    # (ex.: fecha dia 1), então o eixo vai da primeira à última compra do mês de referência.
    por_cartao_dia = {}
    datas_compras = []
    for l in despesas_mes:
        if l.parcela_numero and l.parcela_numero > 1:
            continue  # parcelas seguintes não são "gasto do dia"
        if cartao and l.cartao_id != cartao.pk:
            continue
        chave = (l.cartao_id, l.data)
        por_cartao_dia[chave] = por_cartao_dia.get(chave, services.ZERO) + l.valor
        datas_compras.append(l.data)
    from datetime import timedelta
    if cartao and datas_compras:  # período da fatura: da primeira à última compra
        inicio_eixo, fim_eixo = min(datas_compras), max(datas_compras)
    else:
        inicio_eixo = min(datas_compras + [mes])
        fim_eixo = max(datas_compras + [somar_meses(mes, 1) - timedelta(days=1)])
    if (fim_eixo - inicio_eixo).days > 62:  # limita a ~2 meses para o gráfico não ficar ilegível
        inicio_eixo = fim_eixo - timedelta(days=62)
    dias = [inicio_eixo + timedelta(days=i) for i in range((fim_eixo - inicio_eixo).days + 1)]
    total_por_cartao = {}
    for l in despesas_mes:
        total_por_cartao[l.cartao_id] = total_por_cartao.get(l.cartao_id, services.ZERO) + l.valor

    gasto_cartoes = [{"cartao": c, "total": total_por_cartao.get(c.pk, services.ZERO)} for c in cartoes]
    # Fila de cartões: o selecionado fica na frente (último da pilha)
    pilha = [g for g in gasto_cartoes if not cartao or g["cartao"].pk != cartao.pk]
    frente = next((g for g in gasto_cartoes if cartao and g["cartao"].pk == cartao.pk), None)

    # Séries por cartão: cada cartão com a sua cor; "Dinheiro/Pix" em cinza
    series = [{"id": c.pk, "nome": c.nome, "cor": c.cor} for c in cartoes]
    if any(k is None for k in total_por_cartao) or not cartao:
        series.append({"id": None, "nome": "Dinheiro/Pix", "cor": "#9E9AA8"})
    if cartao:
        series = [{"id": cartao.pk, "nome": cartao.nome, "cor": cartao.cor}]

    meses_hist = [h["mes"] for h in historico]
    hist_cartao = services.despesas_por_cartao(request.user, meses_hist[0], meses_hist[-1])
    graficos = {
        "porCartao": not cartao,
        "dias": [d.strftime("%d/%m") for d in dias],
        "meses": [f"{MESES[m.month - 1]}/{str(m.year)[2:]}" for m in meses_hist],
        "receitasMes": [float(h["receitas"]) for h in historico],
        "series": [
            {
                "nome": s["nome"], "cor": s["cor"],
                "dia": [float(por_cartao_dia.get((s["id"], d), 0)) for d in dias],
                "mes": [float(hist_cartao.get((s["id"], m), 0)) for m in meses_hist],
            }
            for s in series
        ],
    }
    # remove séries sem nenhum gasto (deixa o gráfico mais limpo)
    graficos["series"] = [s for s in graficos["series"] if any(s["mes"]) or any(s["dia"])] or graficos["series"][:1]

    return render(request, "financas/dashboard.html", {
        **contexto_mes(mes),
        "resumo": resumo,
        "cartoes": cartoes,
        "cartao_atual": cartao,
        "pilha": pilha,
        "frente": frente,
        "recentes": recentes,
        "metas": services.metas_do_mes(request.user, mes),
        "anel_offset": round(326.7 * (1 - min(resumo["pct_gasto"], 100) / 100), 2),
        "resumo_geral_despesas": sum(total_por_cartao.values(), services.ZERO),
        "cor_destaque": cartao.cor if cartao else None,
        "graficos_json": graficos,
    })


# ---------- lançamentos ----------

@login_required
def lancamento_lista(request):
    mes = mes_da_request(request)
    preparar_usuario(request, mes)
    qs = services.lancamentos_do_mes(request.user, mes).order_by("data", "id")

    filtros = {k: request.GET.get(k, "") for k in ("tipo", "natureza", "cartao", "categoria", "status", "q")}
    if filtros["tipo"]:
        qs = qs.filter(tipo=filtros["tipo"])
    if filtros["natureza"]:
        qs = qs.filter(natureza=filtros["natureza"], tipo=TipoLancamento.DESPESA)
    if filtros["cartao"] == "nenhum":
        qs = qs.filter(cartao__isnull=True)
    elif filtros["cartao"]:
        qs = qs.filter(cartao_id=filtros["cartao"])
    if filtros["categoria"]:
        qs = qs.filter(categoria_id=filtros["categoria"])
    if filtros["status"] == "pago":
        qs = qs.filter(pago=True)
    elif filtros["status"] == "pendente":
        qs = qs.filter(pago=False)
    if filtros["q"]:
        qs = qs.filter(Q(descricao__icontains=filtros["q"]) | Q(observacao__icontains=filtros["q"]))

    lancamentos = list(qs)
    total_receitas = sum((l.valor for l in lancamentos if l.tipo == TipoLancamento.RECEITA), services.ZERO)
    total_despesas = sum((l.valor for l in lancamentos if l.tipo == TipoLancamento.DESPESA), services.ZERO)

    return render(request, "financas/lancamentos.html", {
        **contexto_mes(mes),
        "lancamentos": lancamentos,
        "filtros": filtros,
        "total_receitas": total_receitas,
        "total_despesas": total_despesas,
        "diferenca": total_receitas - total_despesas,
        "cartoes": Cartao.objects.do_usuario(request.user),
        "categorias": Categoria.objects.do_usuario(request.user),
        "querystring": request.GET.urlencode(),
    })


@login_required
def lancamento_novo(request):
    services.garantir_categorias_padrao(request.user)
    inicial = {}
    if request.GET.get("tipo") in TipoLancamento.values:
        inicial["tipo"] = request.GET["tipo"]
    if request.GET.get("natureza") in Natureza.values:
        inicial["natureza"] = request.GET["natureza"]
    if request.GET.get("forma") in Lancamento.Forma.values:
        inicial["forma"] = request.GET["forma"]
    if request.GET.get("cartao"):
        inicial["cartao"] = request.GET["cartao"]

    form = LancamentoForm(request.POST or None, usuario=request.user, initial=inicial)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        criados = services.criar_lancamento(
            request.user, d, num_parcelas=d.get("num_parcelas") or 1,
            valor_e_total=d.get("valor_e_total", True),
        )
        if d["forma"] == Lancamento.Forma.PARCELADA:
            messages.success(request, f"Compra parcelada em {len(criados)}x cadastrada.")
        elif d["forma"] == Lancamento.Forma.RECORRENTE:
            messages.success(request, "Conta recorrente criada. Ela aparece automaticamente todo mês.")
        else:
            messages.success(request, "Lançamento salvo.")
        avisar_meta(request, criados[:1])
        if "salvar_e_novo" in request.POST:
            return redirect(request.path + "?" + request.GET.urlencode())
        primeiro = criados[0] if criados else None
        destino = primeiro.competencia.strftime("%Y-%m") if primeiro else ""
        return redirect(f"/lancamentos/?mes={destino}")
    categorias_por_tipo = {
        c.pk: c.tipo for c in Categoria.objects.do_usuario(request.user)
    }
    return render(request, "financas/lancamento_form.html", {
        "form": form, "novo": True, "categorias_tipo_json": categorias_por_tipo,
    })


@login_required
def lancamento_editar(request, pk):
    lanc = get_object_or_404(Lancamento, pk=pk, usuario=request.user)
    form = LancamentoForm(request.POST or None, instance=lanc, usuario=request.user)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        if "data" in form.changed_data or "cartao" in form.changed_data:
            if not obj.parcela_total:  # parcelas mantêm o mês da sua parcela
                obj.calcular_competencia()
        obj.save()
        messages.success(request, "Lançamento atualizado.")
        avisar_meta(request, [obj])
        return voltar(request)
    categorias_por_tipo = {c.pk: c.tipo for c in Categoria.objects.do_usuario(request.user)}
    return render(request, "financas/lancamento_form.html", {
        "form": form, "novo": False, "lanc": lanc, "categorias_tipo_json": categorias_por_tipo,
    })


@login_required
def lancamento_excluir(request, pk):
    lanc = get_object_or_404(Lancamento, pk=pk, usuario=request.user)
    if request.method == "POST":
        escopo = request.POST.get("escopo", "este")
        if escopo == "grupo" and lanc.grupo:
            n, _ = Lancamento.objects.filter(usuario=request.user, grupo=lanc.grupo).delete()
            messages.success(request, f"{n} parcelas excluídas.")
        elif escopo == "proximos" and lanc.grupo:
            n, _ = Lancamento.objects.filter(
                usuario=request.user, grupo=lanc.grupo, parcela_numero__gte=lanc.parcela_numero
            ).delete()
            messages.success(request, f"{n} parcelas excluídas.")
        elif escopo == "recorrencia" and lanc.recorrencia:
            services.encerrar_recorrencia(lanc.recorrencia, somar_meses(lanc.competencia, -1))
            lanc.delete()
            messages.success(request, "Recorrência encerrada a partir deste mês.")
        else:
            lanc.delete()
            messages.success(request, "Lançamento excluído.")
        return voltar(request)
    return render(request, "financas/lancamento_excluir.html", {"lanc": lanc})


@login_required
@require_POST
def lancamento_alternar_pago(request, pk):
    lanc = get_object_or_404(Lancamento, pk=pk, usuario=request.user)
    lanc.pago = not lanc.pago
    lanc.save(update_fields=["pago"])
    return voltar(request)


@login_required
@require_POST
def fatura_pagar(request, pk):
    """Marca como paga toda a fatura de um cartão no mês."""
    cartao = get_object_or_404(Cartao, pk=pk, usuario=request.user)
    mes = mes_da_request(request)
    n = Lancamento.objects.filter(
        usuario=request.user, cartao=cartao, competencia=mes, tipo=TipoLancamento.DESPESA, pago=False
    ).update(pago=True)
    messages.success(request, f"Fatura de {cartao.nome} marcada como paga ({n} lançamentos).")
    return voltar(request, "dashboard")


# ---------- cartões ----------

@login_required
def cartao_lista(request):
    mes = mes_da_request(request)
    preparar_usuario(request, mes)
    itens = []
    for c in Cartao.objects.do_usuario(request.user):
        itens.append({"cartao": c, "resumo": services.resumo_mes(request.user, mes, c)})
    return render(request, "financas/cartoes.html", {**contexto_mes(mes), "itens": itens})


@login_required
def cartao_form(request, pk=None):
    cartao = get_object_or_404(Cartao, pk=pk, usuario=request.user) if pk else None
    form = CartaoForm(request.POST or None, instance=cartao)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.usuario = request.user
        obj.save()
        messages.success(request, "Cartão salvo.")
        return redirect("cartoes")
    return render(request, "financas/form_simples.html", {
        "form": form, "titulo": "Editar cartão" if cartao else "Novo cartão", "voltar_url": "cartoes",
        "excluir_url": f"/cartoes/{cartao.pk}/excluir/" if cartao else None,
    })


@login_required
def cartao_excluir(request, pk):
    cartao = get_object_or_404(Cartao, pk=pk, usuario=request.user)
    if request.method == "POST":
        if cartao.lancamento_set.exists():
            cartao.ativo = False
            cartao.save()
            messages.info(request, "O cartão tem lançamentos, então foi desativado em vez de excluído.")
        else:
            cartao.delete()
            messages.success(request, "Cartão excluído.")
        return redirect("cartoes")
    return render(request, "financas/confirmar.html", {
        "titulo": f"Excluir {cartao}?",
        "texto": "Se houver lançamentos neste cartão, ele será apenas desativado para manter o histórico.",
        "voltar_url": "cartoes",
    })


# ---------- categorias ----------

@login_required
def categoria_lista(request):
    services.garantir_categorias_padrao(request.user)
    return render(request, "financas/categorias.html", {
        "categorias": Categoria.objects.do_usuario(request.user),
    })


@login_required
def categoria_form(request, pk=None):
    cat = get_object_or_404(Categoria, pk=pk, usuario=request.user) if pk else None
    form = CategoriaForm(request.POST or None, instance=cat)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.usuario = request.user
        obj.save()
        messages.success(request, "Categoria salva.")
        return redirect("categorias")
    return render(request, "financas/form_simples.html", {
        "form": form, "titulo": "Editar categoria" if cat else "Nova categoria", "voltar_url": "categorias",
        "excluir_url": f"/categorias/{cat.pk}/excluir/" if cat else None,
    })


@login_required
def categoria_excluir(request, pk):
    cat = get_object_or_404(Categoria, pk=pk, usuario=request.user)
    if request.method == "POST":
        try:
            cat.delete()
            messages.success(request, "Categoria excluída. Os lançamentos dela ficaram sem categoria.")
        except ProtectedError:
            messages.error(request, "Não foi possível excluir.")
        return redirect("categorias")
    return render(request, "financas/confirmar.html", {
        "titulo": f"Excluir a categoria {cat.nome}?",
        "texto": "Os lançamentos dessa categoria não serão apagados, só ficarão sem categoria.",
        "voltar_url": "categorias",
    })


# ---------- recorrências ----------

@login_required
def recorrencia_lista(request):
    recorrencias = Recorrencia.objects.do_usuario(request.user).select_related("categoria", "cartao")
    ativas = [r for r in recorrencias if r.ativa]
    total_fixo = sum((r.valor for r in ativas if r.tipo == TipoLancamento.DESPESA), services.ZERO)
    parcelados = (
        Lancamento.objects.do_usuario(request.user)
        .filter(grupo__isnull=False, competencia__gte=primeiro_dia(date.today()))
        .select_related("cartao")
        .order_by("grupo", "parcela_numero")
    )
    grupos = {}
    for p in parcelados:
        g = grupos.setdefault(p.grupo, {"primeira": p, "restantes": 0, "valor_restante": services.ZERO})
        g["restantes"] += 1
        g["valor_restante"] += p.valor
    return render(request, "financas/recorrencias.html", {
        "recorrencias": recorrencias,
        "total_fixo": total_fixo,
        "parcelamentos": sorted(grupos.values(), key=lambda g: g["primeira"].descricao.lower()),
    })


@login_required
def recorrencia_editar(request, pk):
    rec = get_object_or_404(Recorrencia, pk=pk, usuario=request.user)
    form = RecorrenciaForm(request.POST or None, instance=rec, usuario=request.user)
    if request.method == "POST" and form.is_valid():
        rec = form.save()
        # Atualiza as ocorrências deste mês em diante que ainda não foram pagas.
        futuras = rec.lancamentos.filter(competencia__gte=primeiro_dia(date.today()), pago=False)
        futuras.update(
            descricao=rec.descricao, valor=rec.valor, tipo=rec.tipo, natureza=rec.natureza,
            categoria=rec.categoria, cartao=rec.cartao,
        )
        if rec.fim:
            rec.lancamentos.filter(data__gt=rec.fim, pago=False).delete()
        messages.success(request, "Recorrência atualizada (meses futuros não pagos foram ajustados).")
        return redirect("recorrencias")
    return render(request, "financas/form_simples.html", {
        "form": form, "titulo": "Editar conta recorrente", "voltar_url": "recorrencias",
        "ajuda": "Alterações valem para este mês e os próximos ainda não pagos. "
                 "Para parar de gerar, desmarque “Ativa” ou informe a última ocorrência.",
    })


# ---------- planilha ----------

@login_required
def exportar(request):
    preparar_usuario(request, mes_da_request(request))
    if request.GET.get("ano"):
        ano = int(request.GET["ano"])
        inicio, fim = date(ano, 1, 1), date(ano, 12, 1)
        nome = f"financas_{ano}.xlsx"
    else:
        inicio = fim = mes_da_request(request)
        nome = f"financas_{inicio:%Y-%m}.xlsx"
    conteudo = gerar_planilha(request.user, inicio, fim)
    resposta = HttpResponse(
        conteudo, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    resposta["Content-Disposition"] = f'attachment; filename="{nome}"'
    return resposta


# ---------- aparência ----------

@login_required
def aparencia(request):
    from .models import CORES_PALETAS, Perfil

    perfil = Perfil.de(request.user)
    if request.method == "POST":
        escolhida = request.POST.get("paleta")
        if escolhida in Perfil.Paleta.values:
            perfil.paleta = escolhida
            perfil.save(update_fields=["paleta"])
            messages.success(request, f"Paleta “{perfil.get_paleta_display()}” aplicada.")
        return redirect("aparencia")
    paletas = []
    for valor, rotulo in Perfil.Paleta.choices:
        nome, _, detalhe = rotulo.partition(" (")
        primaria, secundaria = CORES_PALETAS[valor]
        paletas.append({"valor": valor, "nome": nome, "detalhe": detalhe.rstrip(")"),
                        "primaria": primaria, "secundaria": secundaria, "atual": valor == perfil.paleta})
    return render(request, "financas/aparencia.html", {"paletas": paletas})
