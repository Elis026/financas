import uuid
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.db import models


def primeiro_dia(d: date) -> date:
    return d.replace(day=1)


def somar_meses(d: date, meses: int) -> date:
    """Soma meses a uma data, ajustando o dia para o último dia válido do mês."""
    import calendar

    total = d.month - 1 + meses
    ano, mes = d.year + total // 12, total % 12 + 1
    dia = min(d.day, calendar.monthrange(ano, mes)[1])
    return date(ano, mes, dia)


class DonoQuerySet(models.QuerySet):
    def do_usuario(self, usuario):
        return self.filter(usuario=usuario)


class Cartao(models.Model):
    class Tipo(models.TextChoices):
        CREDITO = "CREDITO", "Crédito"
        DEBITO = "DEBITO", "Débito / Conta"
        DINHEIRO = "DINHEIRO", "Dinheiro / Pix"

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cartoes")
    nome = models.CharField(max_length=60)
    bandeira = models.CharField(max_length=30, blank=True, help_text="Visa, Mastercard, Elo...")
    final = models.CharField("4 últimos dígitos", max_length=4, blank=True)
    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.CREDITO)
    limite = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    dia_fechamento = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="Compras a partir deste dia entram na fatura do mês seguinte."
    )
    dia_vencimento = models.PositiveSmallIntegerField(null=True, blank=True)
    cor = models.CharField(max_length=7, default="#FF6B2C")
    ativo = models.BooleanField(default=True)

    objects = DonoQuerySet.as_manager()

    class Meta:
        ordering = ["nome"]
        verbose_name = "cartão"
        verbose_name_plural = "cartões"

    def __str__(self):
        return f"{self.nome} •••• {self.final}" if self.final else self.nome

    @property
    def cor_texto(self):
        """Branco ou quase-preto, conforme a cor do cartão (para manter o texto legível)."""
        try:
            r, g, b = (int(self.cor[i:i + 2], 16) for i in (1, 3, 5))
        except (ValueError, TypeError):
            return "#FFFFFF"
        luminancia = (0.299 * r + 0.587 * g + 0.114 * b) / 255
        return "#1B1B1F" if luminancia > 0.65 else "#FFFFFF"

    def vencimento_da_fatura(self, competencia: date) -> date | None:
        """Dia em que vence a fatura do mês de referência informado.

        Se o vencimento é depois do fechamento (ex.: fecha 1, vence 10), vence no mesmo mês;
        senão (ex.: fecha 25, vence 5), vence no mês seguinte.
        """
        import calendar

        if self.tipo != self.Tipo.CREDITO or not self.dia_vencimento:
            return None
        mes = competencia
        if self.dia_fechamento and self.dia_vencimento <= self.dia_fechamento:
            mes = somar_meses(competencia, 1)
        dia = min(self.dia_vencimento, calendar.monthrange(mes.year, mes.month)[1])
        return mes.replace(day=dia)

    def mes_da_fatura(self, data_compra: date) -> date:
        """Mês de referência (competência) em que a compra é cobrada."""
        if self.tipo == self.Tipo.CREDITO and self.dia_fechamento and data_compra.day >= self.dia_fechamento:
            return primeiro_dia(somar_meses(primeiro_dia(data_compra), 1))
        return primeiro_dia(data_compra)


class Categoria(models.Model):
    class Tipo(models.TextChoices):
        RECEITA = "RECEITA", "Receita"
        DESPESA = "DESPESA", "Despesa"

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="categorias")
    nome = models.CharField(max_length=60)
    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.DESPESA)
    cor = models.CharField(max_length=7, default="#8B3DFF")
    orcamento_mensal = models.DecimalField(
        "teto mensal (meta)", max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Quanto você quer gastar no máximo por mês nesta categoria. Deixe vazio para não ter meta.",
    )
    alerta_pct = models.PositiveSmallIntegerField(
        "avisar ao atingir (%)", default=80,
        help_text="Você recebe um aviso quando o gasto do mês chegar nesta porcentagem do teto.",
    )

    objects = DonoQuerySet.as_manager()

    class Meta:
        ordering = ["tipo", "nome"]
        unique_together = [("usuario", "nome", "tipo")]

    def __str__(self):
        return self.nome


class Natureza(models.TextChoices):
    FIXA = "FIXA", "Fixa"
    VARIAVEL = "VARIAVEL", "Variável"


class TipoLancamento(models.TextChoices):
    RECEITA = "RECEITA", "Receita"
    DESPESA = "DESPESA", "Despesa"


class Recorrencia(models.Model):
    """Modelo de uma conta que se repete todo mês (aluguel, salário, assinaturas).

    Os lançamentos mensais são gerados automaticamente a partir dela.
    """

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="recorrencias")
    tipo = models.CharField(max_length=10, choices=TipoLancamento.choices, default=TipoLancamento.DESPESA)
    natureza = models.CharField(max_length=10, choices=Natureza.choices, default=Natureza.FIXA)
    descricao = models.CharField("descrição", max_length=120)
    valor = models.DecimalField(max_digits=12, decimal_places=2)
    categoria = models.ForeignKey(Categoria, on_delete=models.SET_NULL, null=True, blank=True)
    cartao = models.ForeignKey(Cartao, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="cartão")
    inicio = models.DateField("primeira ocorrência")
    fim = models.DateField("última ocorrência", null=True, blank=True)
    ativa = models.BooleanField(default=True)

    objects = DonoQuerySet.as_manager()

    class Meta:
        ordering = ["descricao"]
        verbose_name = "recorrência"

    def __str__(self):
        return self.descricao


class Lancamento(models.Model):
    class Forma(models.TextChoices):
        UNICA = "UNICA", "À vista / única"
        PARCELADA = "PARCELADA", "Parcelada"
        RECORRENTE = "RECORRENTE", "Recorrente (todo mês)"

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lancamentos")
    tipo = models.CharField(max_length=10, choices=TipoLancamento.choices, default=TipoLancamento.DESPESA)
    natureza = models.CharField(max_length=10, choices=Natureza.choices, default=Natureza.VARIAVEL)
    descricao = models.CharField("descrição", max_length=120)
    valor = models.DecimalField(max_digits=12, decimal_places=2)
    data = models.DateField(help_text="Data da compra ou do recebimento.")
    competencia = models.DateField(
        "mês de referência", db_index=True, help_text="Primeiro dia do mês em que o valor conta no orçamento."
    )
    categoria = models.ForeignKey(Categoria, on_delete=models.SET_NULL, null=True, blank=True)
    cartao = models.ForeignKey(Cartao, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="cartão")
    pago = models.BooleanField(default=False)
    observacao = models.TextField("observação", blank=True)

    forma = models.CharField(max_length=10, choices=Forma.choices, default=Forma.UNICA)
    grupo = models.UUIDField(null=True, blank=True, db_index=True, help_text="Liga as parcelas de uma compra.")
    parcela_numero = models.PositiveSmallIntegerField(null=True, blank=True)
    parcela_total = models.PositiveSmallIntegerField(null=True, blank=True)
    recorrencia = models.ForeignKey(
        Recorrencia, on_delete=models.SET_NULL, null=True, blank=True, related_name="lancamentos"
    )

    criado_em = models.DateTimeField(auto_now_add=True)

    objects = DonoQuerySet.as_manager()

    class Meta:
        ordering = ["-data", "-id"]
        verbose_name = "lançamento"
        constraints = [
            models.UniqueConstraint(
                fields=["recorrencia", "competencia"],
                name="uma_ocorrencia_por_mes",
                condition=models.Q(recorrencia__isnull=False),
            )
        ]

    def __str__(self):
        return self.descricao

    @property
    def rotulo_parcela(self):
        if self.parcela_total:
            return f"{self.parcela_numero}/{self.parcela_total}"
        return ""

    @property
    def vencimento(self) -> date:
        """Quando precisa ser pago: no cartão de crédito, o vencimento da fatura; senão, a própria data."""
        if self.cartao_id and self.cartao.tipo == Cartao.Tipo.CREDITO:
            return self.cartao.vencimento_da_fatura(self.competencia) or self.data
        return self.data

    @property
    def is_despesa(self):
        return self.tipo == TipoLancamento.DESPESA

    def calcular_competencia(self):
        self.competencia = self.cartao.mes_da_fatura(self.data) if self.cartao else primeiro_dia(self.data)

    def save(self, *args, **kwargs):
        if not self.competencia:
            self.calcular_competencia()
        super().save(*args, **kwargs)


def novo_grupo():
    return uuid.uuid4()


class Perfil(models.Model):
    """Preferências de aparência de cada usuário (valem no PC e no celular)."""

    class Paleta(models.TextChoices):
        POR_DO_SOL = "por-do-sol", "Pôr do sol (laranja + roxo)"
        OCEANO = "oceano", "Oceano (azul + turquesa)"
        FLORESTA = "floresta", "Floresta (verde + mostarda)"
        FRAMBOESA = "framboesa", "Framboesa (pink + índigo)"
        CORAL = "coral", "Coral (coral + azul)"
        VINHO = "vinho", "Vinho (bordô + dourado)"
        LAVANDA = "lavanda", "Lavanda (violeta + rosa)"
        GRAFITE = "grafite", "Grafite (cinza + azul-céu)"

    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="perfil")
    paleta = models.CharField(max_length=20, choices=Paleta.choices, default=Paleta.POR_DO_SOL)

    def __str__(self):
        return f"Perfil de {self.usuario}"

    @classmethod
    def de(cls, usuario):
        perfil, _ = cls.objects.get_or_create(usuario=usuario)
        return perfil


# Cores de cada paleta (primária, secundária), usadas nas prévias da tela Aparência.
CORES_PALETAS = {
    "por-do-sol": ("#FF6B2C", "#8B3DFF"),
    "oceano": ("#2563EB", "#0D9488"),
    "floresta": ("#15803D", "#CA8A04"),
    "framboesa": ("#DB2777", "#4F46E5"),
    "coral": ("#F43F5E", "#0284C7"),
    "vinho": ("#9F1239", "#B7791F"),
    "lavanda": ("#7C3AED", "#EC4899"),
    "grafite": ("#334155", "#0EA5E9"),
}
