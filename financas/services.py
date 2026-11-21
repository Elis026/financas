"""Regras de negócio: parcelamento, recorrências e resumos do mês."""

from collections import OrderedDict
from datetime import date, timedelta
from decimal import ROUND_DOWN, Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce

from .models import (
    Cartao,
    Categoria,
    Lancamento,
    Natureza,
    Recorrencia,
    TipoLancamento,
    novo_grupo,
    primeiro_dia,
    somar_meses,
)

ZERO = Decimal("0.00")

CATEGORIAS_PADRAO = [
    ("Salário", "RECEITA", "#22A06B"),
    ("Freelance", "RECEITA", "#2D9CDB"),
    ("Outras receitas", "RECEITA", "#6FCF97"),
    ("Moradia", "DESPESA", "#8B3DFF"),
    ("Mercado", "DESPESA", "#FF6B2C"),
    ("Alimentação", "DESPESA", "#F2994A"),
    ("Transporte", "DESPESA", "#EB5757"),
    ("Saúde", "DESPESA", "#27AE60"),
    ("Educação", "DESPESA", "#B07CFF"),
    ("Lazer", "DESPESA", "#F2C94C"),
    ("Assinaturas", "DESPESA", "#56CCF2"),
    ("Compras", "DESPESA", "#FF9F7A"),
    ("Outros", "DESPESA", "#9E9E9E"),
]


def garantir_categorias_padrao(usuario):
    if Categoria.objects.do_usuario(usuario).exists():
        return
    Categoria.objects.bulk_create(
        [Categoria(usuario=usuario, nome=n, tipo=t, cor=c) for n, t, c in CATEGORIAS_PADRAO]
    )


def dividir_em_parcelas(total: Decimal, n: int) -> list[Decimal]:
    """Divide o total em n parcelas; os centavos que sobram vão para a primeira."""
    base = (total / n).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    parcelas = [base] * n
    parcelas[0] += total - base * n
    return parcelas


@transaction.atomic
def criar_lancamento(usuario, dados: dict, num_parcelas: int = 1, valor_e_total: bool = True):
    """Cria um lançamento único, parcelado ou recorrente a partir dos dados do formulário."""
    forma = dados["forma"]
    base = dict(
        usuario=usuario,
        tipo=dados["tipo"],
        natureza=dados["natureza"],
        descricao=dados["descricao"],
        categoria=dados.get("categoria"),
        cartao=dados.get("cartao"),
        observacao=dados.get("observacao", ""),
    )

    if forma == Lancamento.Forma.PARCELADA and num_parcelas > 1:
        total = dados["valor"] if valor_e_total else dados["valor"] * num_parcelas
        grupo = novo_grupo()
        criados = []
        for i, valor in enumerate(dividir_em_parcelas(total, num_parcelas)):
            lanc = Lancamento(
                **base,
                valor=valor,
                data=dados["data"],
                forma=forma,
                grupo=grupo,
                parcela_numero=i + 1,
                parcela_total=num_parcelas,
                pago=dados.get("pago", False) and i == 0,
            )
            lanc.calcular_competencia()
            lanc.competencia = somar_meses(lanc.competencia, i)
            lanc.save()
            criados.append(lanc)
        return criados

    if forma == Lancamento.Forma.RECORRENTE:
        rec = Recorrencia.objects.create(
            usuario=usuario,
            tipo=base["tipo"],
            natureza=base["natureza"],
            descricao=base["descricao"],
            valor=dados["valor"],
            categoria=base["categoria"],
            cartao=base["cartao"],
            inicio=dados["data"],
        )
        materializar_recorrencias(usuario, somar_meses(primeiro_dia(date.today()), 2))
        return list(rec.lancamentos.all())

    lanc = Lancamento(**base, valor=dados["valor"], data=dados["data"], forma=Lancamento.Forma.UNICA,
                      pago=dados.get("pago", False))
    lanc.calcular_competencia()
    lanc.save()
    return [lanc]


def materializar_recorrencias(usuario, ate_mes: date):
    """Gera os lançamentos de cada recorrência ativa até o mês informado (inclusive)."""
    ate_mes = primeiro_dia(ate_mes)
    for rec in Recorrencia.objects.do_usuario(usuario).filter(ativa=True).select_related("cartao"):
        existentes = set(rec.lancamentos.values_list("competencia", flat=True))
        novos = []
        i = 0
        while True:
            data_ocorrencia = somar_meses(rec.inicio, i)
            i += 1
            if rec.fim and data_ocorrencia > rec.fim:
                break
            comp = rec.cartao.mes_da_fatura(data_ocorrencia) if rec.cartao else primeiro_dia(data_ocorrencia)
            if comp > ate_mes:
                break
            if comp in existentes:
                continue
            novos.append(
                Lancamento(
                    usuario=usuario,
                    tipo=rec.tipo,
                    natureza=rec.natureza,
                    descricao=rec.descricao,
                    valor=rec.valor,
                    data=data_ocorrencia,
                    competencia=comp,
                    categoria=rec.categoria,
                    cartao=rec.cartao,
                    forma=Lancamento.Forma.RECORRENTE,
                    recorrencia=rec,
                )
            )
        Lancamento.objects.bulk_create(novos, ignore_conflicts=True)


def encerrar_recorrencia(rec: Recorrencia, a_partir_de: date):
    """Encerra a recorrência depois do mês informado e apaga as ocorrências futuras não pagas."""
    from datetime import timedelta

    rec.ativa = False
    rec.fim = somar_meses(primeiro_dia(a_partir_de), 1) - timedelta(days=1)
    rec.save()
    rec.lancamentos.filter(competencia__gt=primeiro_dia(a_partir_de), pago=False).delete()


def _soma(qs):
    return qs.aggregate(t=Coalesce(Sum("valor"), ZERO))["t"]


def lancamentos_do_mes(usuario, mes: date, cartao: Cartao | None = None):
    qs = Lancamento.objects.do_usuario(usuario).filter(competencia=primeiro_dia(mes))
    if cartao:
        qs = qs.filter(cartao=cartao)
    return qs.select_related("categoria", "cartao")


def resumo_mes(usuario, mes: date, cartao: Cartao | None = None) -> dict:
    mes = primeiro_dia(mes)
    qs = lancamentos_do_mes(usuario, mes, cartao)
    despesas = qs.filter(tipo=TipoLancamento.DESPESA)
    receitas_qs = qs.filter(tipo=TipoLancamento.RECEITA)

    # Receita é do usuário, não do cartão: no filtro por cartão, compara com a receita total do mês.
    receitas = _soma(lancamentos_do_mes(usuario, mes).filter(tipo=TipoLancamento.RECEITA))
    total_despesas = _soma(despesas)
    fixas = _soma(despesas.filter(natureza=Natureza.FIXA))
    variaveis = total_despesas - fixas
    pendentes = _soma(despesas.filter(pago=False))

    por_categoria = list(
        despesas.values("categoria__nome", "categoria__cor", "categoria__orcamento_mensal")
        .annotate(total=Sum("valor"))
        .order_by("-total")
    )
    for c in por_categoria:
        c["nome"] = c.pop("categoria__nome") or "Sem categoria"
        c["cor"] = c.pop("categoria__cor") or "#9E9E9E"
        c["orcamento"] = c.pop("categoria__orcamento_mensal")
        c["pct"] = float(c["total"] / total_despesas * 100) if total_despesas else 0
        c["estourou"] = bool(c["orcamento"] and c["total"] > c["orcamento"])

    import calendar

    dias = calendar.monthrange(mes.year, mes.month)[1]
    por_dia = OrderedDict((d, ZERO) for d in range(1, dias + 1))
    for row in despesas.values("data").annotate(total=Sum("valor")):
        if row["data"].year == mes.year and row["data"].month == mes.month:
            por_dia[row["data"].day] += row["total"]

    pct_gasto = float(total_despesas / receitas * 100) if receitas else (100.0 if total_despesas else 0.0)

    limite_info = None
    if cartao and cartao.tipo == Cartao.Tipo.CREDITO and cartao.limite:
        usado = _soma(
            Lancamento.objects.do_usuario(usuario).filter(cartao=cartao, tipo=TipoLancamento.DESPESA, pago=False)
        )
        limite_info = {
            "limite": cartao.limite,
            "usado": usado,
            "disponivel": cartao.limite - usado,
            "pct": float(usado / cartao.limite * 100),
        }

    return {
        "mes": mes,
        "receitas": receitas,
        "receitas_cartao": _soma(receitas_qs),
        "despesas": total_despesas,
        "fixas": fixas,
        "variaveis": variaveis,
        "pendentes": pendentes,
        "saldo": receitas - total_despesas,
        "pct_gasto": round(pct_gasto, 1),
        "por_categoria": por_categoria,
        "por_dia": por_dia,
        "limite": limite_info,
    }


def historico_meses(usuario, ate_mes: date, n: int = 6, cartao: Cartao | None = None):
    """Receitas e despesas dos últimos n meses (para o gráfico de barras)."""
    ate_mes = primeiro_dia(ate_mes)
    inicio = somar_meses(ate_mes, -(n - 1))
    qs = Lancamento.objects.do_usuario(usuario).filter(competencia__gte=inicio, competencia__lte=ate_mes)
    filtro_cartao = Q(cartao=cartao) if cartao else Q()
    linhas = qs.values("competencia").annotate(
        despesas=Coalesce(Sum("valor", filter=Q(tipo=TipoLancamento.DESPESA) & filtro_cartao), ZERO),
        receitas=Coalesce(Sum("valor", filter=Q(tipo=TipoLancamento.RECEITA)), ZERO),
    )
    mapa = {r["competencia"]: r for r in linhas}
    saida = []
    for i in range(n):
        m = somar_meses(inicio, i)
        r = mapa.get(m, {})
        saida.append({"mes": m, "despesas": r.get("despesas", ZERO), "receitas": r.get("receitas", ZERO)})
    return saida


# ---------- metas (teto por categoria) ----------

def _status_meta(gasto, teto, alerta_pct, mes_encerrado):
    pct = float(gasto / teto * 100) if teto else 0.0
    if gasto > teto:
        return pct, "estourou", "Não cumprida" if mes_encerrado else "Estourou o teto"
    if pct >= alerta_pct:
        return pct, "atencao", "Cumprida (no limite)" if mes_encerrado else "Perto do limite"
    return pct, "ok", "Cumprida" if mes_encerrado else "Dentro da meta"


def metas_do_mes(usuario, mes: date, hoje: date | None = None) -> dict:
    """Situação de cada categoria com teto no mês: gasto, % do teto e status."""
    hoje = hoje or date.today()
    mes = primeiro_dia(mes)
    mes_encerrado = mes < primeiro_dia(hoje)
    cats = Categoria.objects.do_usuario(usuario).filter(
        tipo=Categoria.Tipo.DESPESA, orcamento_mensal__gt=0
    )
    gastos = dict(
        Lancamento.objects.do_usuario(usuario)
        .filter(competencia=mes, tipo=TipoLancamento.DESPESA, categoria__in=cats)
        .values_list("categoria")
        .annotate(t=Sum("valor"))
    )
    itens = []
    for c in cats:
        gasto = gastos.get(c.pk, ZERO)
        pct, status, rotulo = _status_meta(gasto, c.orcamento_mensal, c.alerta_pct, mes_encerrado)
        itens.append({
            "categoria": c, "gasto": gasto, "teto": c.orcamento_mensal, "restante": c.orcamento_mensal - gasto,
            "pct": round(pct, 1), "status": status, "rotulo": rotulo,
        })
    ordem = {"estourou": 0, "atencao": 1, "ok": 2}
    itens.sort(key=lambda i: (ordem[i["status"]], -i["pct"]))
    cumpridas = sum(1 for i in itens if i["status"] != "estourou")
    return {"itens": itens, "cumpridas": cumpridas, "total": len(itens), "mes_encerrado": mes_encerrado}


def aviso_de_meta(lanc: Lancamento) -> tuple[str, str] | None:
    """Depois de salvar uma despesa, diz se a categoria chegou perto ou passou do teto."""
    cat = lanc.categoria
    if not lanc.is_despesa or not cat or not cat.orcamento_mensal:
        return None
    gasto = _soma(Lancamento.objects.filter(
        usuario=lanc.usuario, categoria=cat, competencia=lanc.competencia, tipo=TipoLancamento.DESPESA))
    pct = float(gasto / cat.orcamento_mensal * 100)
    from django.template.defaultfilters import date as formatar_data

    from .templatetags.dinheiro import brl

    mes = formatar_data(lanc.competencia, "F")
    if gasto > cat.orcamento_mensal:
        return "error", (f"Teto de {cat.nome} estourado em {mes}: {brl(gasto)} de "
                         f"{brl(cat.orcamento_mensal)} ({pct:.0f}%).")
    if pct >= cat.alerta_pct:
        return "warning", (f"Atenção: {cat.nome} já está em {pct:.0f}% do teto de {mes} "
                           f"(restam {brl(cat.orcamento_mensal - gasto)}).")
    return None


# ---------- notificações ----------

DIAS_AVISO_VENCIMENTO = 5


def alertas(usuario, hoje: date | None = None) -> list[dict]:
    """Contas vencidas ou vencendo nos próximos dias + metas do mês perto/acima do teto."""
    hoje = hoje or date.today()
    limite = hoje + timedelta(days=DIAS_AVISO_VENCIMENTO)
    pendentes = (
        Lancamento.objects.do_usuario(usuario)
        .filter(tipo=TipoLancamento.DESPESA, pago=False,
                competencia__gte=somar_meses(primeiro_dia(hoje), -3),
                competencia__lte=somar_meses(primeiro_dia(hoje), 1))
        .select_related("cartao")
    )
    faturas, contas = {}, []
    for l in pendentes:
        venc = l.vencimento
        if venc > limite:
            continue
        eh_credito = l.cartao_id and l.cartao.tipo == Cartao.Tipo.CREDITO
        # Fora do cartão de crédito, só avisa de "contas": fixas, recorrentes ou parcelas.
        # Compras avulsas no Pix/débito (padaria, Uber) não geram aviso de vencimento.
        if not eh_credito and not (l.natureza == Natureza.FIXA or l.recorrencia_id or l.grupo):
            continue
        if eh_credito:
            f = faturas.setdefault((l.cartao_id, l.competencia), {"cartao": l.cartao, "venc": venc, "total": ZERO,
                                                                   "competencia": l.competencia})
            f["total"] += l.valor
        else:
            contas.append({"lanc": l, "venc": venc})

    def quando(venc):
        dias = (venc - hoje).days
        if dias < 0:
            return "atrasada", f"venceu há {-dias} dia{'s' if dias < -1 else ''}"
        if dias == 0:
            return "hoje", "vence hoje"
        if dias == 1:
            return "breve", "vence amanhã"
        return "breve", f"vence em {dias} dias"

    saida = []
    for f in faturas.values():
        nivel, texto = quando(f["venc"])
        saida.append({
            "tipo": "fatura", "nivel": nivel, "titulo": f"Fatura {f['cartao'].nome}",
            "texto": f"{texto} ({f['venc']:%d/%m})", "valor": f["total"], "data": f["venc"],
            "cor": f["cartao"].cor,
            "url": f"/?mes={f['competencia']:%Y-%m}&cartao={f['cartao'].pk}",
        })
    for c in contas:
        l = c["lanc"]
        nivel, texto = quando(c["venc"])
        saida.append({
            "tipo": "conta", "nivel": nivel, "titulo": l.descricao, "texto": f"{texto} ({c['venc']:%d/%m})",
            "valor": l.valor, "data": c["venc"], "cor": None,
            "url": f"/lancamentos/?mes={l.competencia:%Y-%m}&status=pendente",
        })
    saida.sort(key=lambda a: a["data"])

    for m in metas_do_mes(usuario, hoje, hoje)["itens"]:
        if m["status"] == "ok":
            continue
        saida.append({
            "tipo": "meta", "nivel": "atrasada" if m["status"] == "estourou" else "breve",
            "titulo": f"Teto de {m['categoria'].nome}",
            "texto": f"{m['pct']:.0f}% do teto usado",
            "valor": m["gasto"], "data": hoje, "cor": m["categoria"].cor, "url": "/#metas",
        })
    return saida


# ---------- gráficos por cartão ----------

def despesas_por_cartao(usuario, inicio: date, fim: date) -> dict:
    """{(cartao_id ou None, competencia): total} e {(cartao_id ou None, data): total} no intervalo."""
    qs = Lancamento.objects.do_usuario(usuario).filter(
        tipo=TipoLancamento.DESPESA, competencia__gte=primeiro_dia(inicio), competencia__lte=primeiro_dia(fim))
    por_mes = {(r["cartao"], r["competencia"]): r["t"]
               for r in qs.values("cartao", "competencia").annotate(t=Sum("valor"))}
    return por_mes
