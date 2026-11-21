"""Exportação para planilha Excel (.xlsx)."""

from collections import defaultdict
from datetime import date
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

from .models import Lancamento, TipoLancamento, somar_meses

MOEDA = '"R$" #,##0.00;[Red]-"R$" #,##0.00'
CABECALHO = PatternFill("solid", fgColor="1F1F1F")
LARANJA = PatternFill("solid", fgColor="FFE3D6")
MESES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]


def _rotulo(m: date) -> str:
    return f"{MESES[m.month - 1]}/{m.year}"


def _cabecalho(ws, colunas, linha=1):
    for i, titulo in enumerate(colunas, start=1):
        c = ws.cell(row=linha, column=i, value=titulo)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = CABECALHO
        c.alignment = Alignment(horizontal="center", vertical="center")
    ws.freeze_panes = ws.cell(row=linha + 1, column=1)


def _larguras(ws, larguras):
    for i, w in enumerate(larguras, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def _linha_total(ws, linha, col_inicio, col_fim, rotulo="Total"):
    ws.cell(row=linha, column=1, value=rotulo).font = Font(bold=True)
    for col in range(col_inicio, col_fim + 1):
        letra = get_column_letter(col)
        c = ws.cell(row=linha, column=col, value=f"=SUM({letra}2:{letra}{linha - 1})")
        c.number_format = MOEDA
        c.font = Font(bold=True)
        c.fill = LARANJA
    ws.cell(row=linha, column=1).fill = LARANJA


def gerar_planilha(usuario, inicio: date, fim: date) -> bytes:
    lancs = list(
        Lancamento.objects.do_usuario(usuario)
        .filter(competencia__gte=inicio, competencia__lte=fim)
        .select_related("categoria", "cartao")
        .order_by("competencia", "data", "id")
    )
    meses = []
    m = inicio
    while m <= fim:
        meses.append(m)
        m = somar_meses(m, 1)

    wb = Workbook()

    # --- Resumo mensal ---
    ws = wb.active
    ws.title = "Resumo"
    _cabecalho(ws, ["Mês", "Receitas", "Despesas fixas", "Despesas variáveis", "Total despesas", "Saldo", "Pendente"])
    agg = defaultdict(lambda: defaultdict(float))
    for l in lancs:
        a = agg[l.competencia]
        v = float(l.valor)
        if l.tipo == TipoLancamento.RECEITA:
            a["rec"] += v
        else:
            a["fixa" if l.natureza == "FIXA" else "var"] += v
            if not l.pago:
                a["pend"] += v
    for i, mes in enumerate(meses, start=2):
        a = agg[mes]
        ws.cell(row=i, column=1, value=_rotulo(mes))
        ws.cell(row=i, column=2, value=a["rec"])
        ws.cell(row=i, column=3, value=a["fixa"])
        ws.cell(row=i, column=4, value=a["var"])
        ws.cell(row=i, column=5, value=f"=C{i}+D{i}")
        ws.cell(row=i, column=6, value=f"=B{i}-E{i}")
        ws.cell(row=i, column=7, value=a["pend"])
        for col in range(2, 8):
            ws.cell(row=i, column=col).number_format = MOEDA
    if len(meses) > 1:
        _linha_total(ws, len(meses) + 2, 2, 7)
    _larguras(ws, [12, 16, 16, 18, 16, 16, 14])

    # --- Lançamentos ---
    ws = wb.create_sheet("Lançamentos")
    colunas = ["Mês ref.", "Data", "Tipo", "Natureza", "Descrição", "Categoria", "Cartão",
               "Forma", "Parcela", "Valor", "Pago"]
    _cabecalho(ws, colunas)
    for i, l in enumerate(lancs, start=2):
        valor = float(l.valor) if l.tipo == TipoLancamento.RECEITA else -float(l.valor)
        linha = [
            _rotulo(l.competencia), l.data, l.get_tipo_display(),
            l.get_natureza_display() if l.is_despesa else "", l.descricao,
            l.categoria.nome if l.categoria else "", l.cartao.nome if l.cartao else "Dinheiro/Pix",
            l.get_forma_display(), l.rotulo_parcela, valor, "Sim" if l.pago else "Não",
        ]
        for col, v in enumerate(linha, start=1):
            ws.cell(row=i, column=col, value=v)
        ws.cell(row=i, column=2).number_format = "DD/MM/YYYY"
        ws.cell(row=i, column=10).number_format = MOEDA
    if lancs:
        ref = f"A1:{get_column_letter(len(colunas))}{len(lancs) + 1}"
        tabela = Table(displayName="Lancamentos", ref=ref)
        tabela.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
        ws.add_table(tabela)
    _larguras(ws, [11, 12, 10, 11, 34, 16, 18, 20, 9, 14, 7])

    # --- Despesas por categoria (mês x categoria) ---
    _aba_cruzada(
        wb, "Por categoria", meses,
        [l for l in lancs if l.is_despesa],
        lambda l: l.categoria.nome if l.categoria else "Sem categoria",
    )
    # --- Despesas por cartão ---
    _aba_cruzada(
        wb, "Por cartão", meses,
        [l for l in lancs if l.is_despesa],
        lambda l: l.cartao.nome if l.cartao else "Dinheiro/Pix",
    )

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _aba_cruzada(wb, titulo, meses, lancs, chave):
    ws = wb.create_sheet(titulo)
    grupos = sorted({chave(l) for l in lancs})
    _cabecalho(ws, [titulo.replace("Por ", "").capitalize()] + [_rotulo(m) for m in meses] + ["Total"])
    valores = defaultdict(float)
    for l in lancs:
        valores[(chave(l), l.competencia)] += float(l.valor)
    ultima_col = len(meses) + 2
    for i, g in enumerate(grupos, start=2):
        ws.cell(row=i, column=1, value=g)
        for j, m in enumerate(meses, start=2):
            c = ws.cell(row=i, column=j, value=valores.get((g, m), 0))
            c.number_format = MOEDA
        ini, fim = get_column_letter(2), get_column_letter(ultima_col - 1)
        c = ws.cell(row=i, column=ultima_col, value=f"=SUM({ini}{i}:{fim}{i})")
        c.number_format = MOEDA
        c.font = Font(bold=True)
    if grupos:
        _linha_total(ws, len(grupos) + 2, 2, ultima_col)
    _larguras(ws, [22] + [13] * (len(meses) + 1))
