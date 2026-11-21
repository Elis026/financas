from datetime import date

from django import forms

from .models import Cartao, Categoria, Lancamento, Recorrencia


class EstiloMixin:
    """Aplica a classe CSS padrão em todos os campos."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in self.fields.values():
            w = campo.widget
            if isinstance(w, forms.RadioSelect):
                continue
            if isinstance(w, forms.CheckboxInput):
                w.attrs.setdefault("class", "check")
            else:
                w.attrs.setdefault("class", "input")


class DonoFormMixin:
    """Restringe cartões e categorias aos do usuário logado."""

    def __init__(self, *args, usuario=None, **kwargs):
        super().__init__(*args, **kwargs)
        if "cartao" in self.fields:
            self.fields["cartao"].queryset = Cartao.objects.do_usuario(usuario).filter(ativo=True)
            self.fields["cartao"].empty_label = "Sem cartão (dinheiro / Pix)"
        if "categoria" in self.fields:
            self.fields["categoria"].queryset = Categoria.objects.do_usuario(usuario)
            self.fields["categoria"].empty_label = "Sem categoria"


class LancamentoForm(DonoFormMixin, EstiloMixin, forms.ModelForm):
    num_parcelas = forms.IntegerField(label="Nº de parcelas", min_value=2, max_value=120, required=False)
    valor_e_total = forms.TypedChoiceField(
        label="O valor informado é",
        choices=[("1", "o total da compra"), ("0", "o valor de cada parcela")],
        coerce=lambda v: v == "1",
        initial="1",
        required=False,
    )

    class Meta:
        model = Lancamento
        fields = ["tipo", "natureza", "descricao", "valor", "data", "categoria", "cartao", "forma", "pago", "observacao"]
        widgets = {
            "tipo": forms.RadioSelect,
            "natureza": forms.RadioSelect,
            "forma": forms.RadioSelect,
            "data": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "observacao": forms.Textarea(attrs={"rows": 2}),
            "valor": forms.NumberInput(attrs={"step": "0.01", "min": "0.01"}),
        }
        labels = {"pago": "Já está pago / recebido"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.initial.setdefault("data", date.today())
        else:
            # Edição altera só este lançamento; a forma não muda depois de criado.
            self.fields.pop("forma")
            self.fields.pop("num_parcelas")
            self.fields.pop("valor_e_total")

    def clean(self):
        dados = super().clean()
        if dados.get("forma") == Lancamento.Forma.PARCELADA and not dados.get("num_parcelas"):
            self.add_error("num_parcelas", "Informe em quantas parcelas.")
        cat = dados.get("categoria")
        if cat and dados.get("tipo") and cat.tipo != dados["tipo"]:
            self.add_error("categoria", "Essa categoria é de outro tipo (receita × despesa).")
        return dados


class CartaoForm(EstiloMixin, forms.ModelForm):
    class Meta:
        model = Cartao
        fields = ["nome", "tipo", "bandeira", "final", "limite", "dia_fechamento", "dia_vencimento", "cor", "ativo"]
        widgets = {"cor": forms.TextInput(attrs={"type": "color"})}

    def clean_final(self):
        final = self.cleaned_data["final"]
        if final and (not final.isdigit() or len(final) != 4):
            raise forms.ValidationError("Use só os 4 últimos dígitos.")
        return final

    def clean(self):
        dados = super().clean()
        for campo in ("dia_fechamento", "dia_vencimento"):
            v = dados.get(campo)
            if v is not None and not 1 <= v <= 31:
                self.add_error(campo, "Dia entre 1 e 31.")
        return dados


class CategoriaForm(EstiloMixin, forms.ModelForm):
    class Meta:
        model = Categoria
        fields = ["nome", "tipo", "cor", "orcamento_mensal", "alerta_pct"]
        widgets = {"cor": forms.TextInput(attrs={"type": "color"})}


class RecorrenciaForm(DonoFormMixin, EstiloMixin, forms.ModelForm):
    class Meta:
        model = Recorrencia
        fields = ["tipo", "natureza", "descricao", "valor", "categoria", "cartao", "inicio", "fim", "ativa"]
        widgets = {
            "inicio": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "fim": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }
