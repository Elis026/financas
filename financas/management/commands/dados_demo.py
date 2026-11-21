"""Cria um usuário de demonstração com dados de exemplo.

Uso:  python manage.py dados_demo
Login: demo / demo-financas-2026   (só para testes locais ou para a demo do portfólio)
"""

import random
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from financas import services
from financas.models import Cartao, Categoria, Lancamento, primeiro_dia, somar_meses

USUARIO, SENHA = "demo", "demo-financas-2026"


class Command(BaseCommand):
    help = "Cria (ou recria) o usuário demo com 6 meses de dados de exemplo."

    def handle(self, *args, **opts):
        User.objects.filter(username=USUARIO).delete()
        u = User.objects.create_user(USUARIO, password=SENHA)
        services.garantir_categorias_padrao(u)
        cat = {c.nome: c for c in Categoria.objects.do_usuario(u)}

        nubank = Cartao.objects.create(usuario=u, nome="Nubank", bandeira="Mastercard", final="8702",
                                       limite=Decimal("4000"), dia_fechamento=25, dia_vencimento=5, cor="#8B3DFF")
        inter = Cartao.objects.create(usuario=u, nome="Inter", bandeira="Visa", final="1234",
                                      limite=Decimal("2500"), dia_fechamento=1, dia_vencimento=10, cor="#FF6B2C")
        conta = Cartao.objects.create(usuario=u, nome="Conta corrente", tipo="DEBITO", bandeira="Elo",
                                      final="5521", cor="#1F9D63")

        hoje = date.today()
        inicio = somar_meses(primeiro_dia(hoje), -5)

        def criar(**d):
            base = {"tipo": "DESPESA", "natureza": "VARIAVEL", "categoria": None, "cartao": None,
                    "forma": "UNICA", "pago": False, "observacao": ""}
            base.update(d)
            return services.criar_lancamento(u, base)

        # recorrentes
        criar(tipo="RECEITA", descricao="Salário", valor=Decimal("6200"), data=inicio.replace(day=5),
              categoria=cat["Salário"], cartao=conta, forma="RECORRENTE")
        criar(natureza="FIXA", descricao="Aluguel", valor=Decimal("1650"), data=inicio.replace(day=10),
              categoria=cat["Moradia"], cartao=conta, forma="RECORRENTE")
        criar(natureza="FIXA", descricao="Internet", valor=Decimal("119.90"), data=inicio.replace(day=15),
              categoria=cat["Moradia"], cartao=nubank, forma="RECORRENTE")
        criar(natureza="FIXA", descricao="Streaming", valor=Decimal("44.90"), data=inicio.replace(day=8),
              categoria=cat["Assinaturas"], cartao=nubank, forma="RECORRENTE")
        criar(natureza="FIXA", descricao="Academia", valor=Decimal("99.90"), data=inicio.replace(day=3),
              categoria=cat["Saúde"], cartao=inter, forma="RECORRENTE")

        # parceladas
        services.criar_lancamento(u, {"tipo": "DESPESA", "natureza": "VARIAVEL", "descricao": "Notebook",
                                      "valor": Decimal("4200"), "data": somar_meses(inicio, 2).replace(day=12),
                                      "categoria": cat["Compras"], "cartao": nubank, "forma": "PARCELADA"},
                                  num_parcelas=10)
        services.criar_lancamento(u, {"tipo": "DESPESA", "natureza": "VARIAVEL", "descricao": "Curso de Python",
                                      "valor": Decimal("900"), "data": somar_meses(inicio, 3).replace(day=20),
                                      "categoria": cat["Educação"], "cartao": inter, "forma": "PARCELADA"},
                                  num_parcelas=6)

        # variáveis
        rnd = random.Random(42)
        variaveis = [("Mercado", "Mercado", 120, 420), ("Padaria", "Alimentação", 15, 45),
                     ("Restaurante", "Alimentação", 45, 160), ("Uber", "Transporte", 14, 48),
                     ("Combustível", "Transporte", 120, 250), ("Cinema", "Lazer", 40, 90),
                     ("Farmácia", "Saúde", 25, 120)]
        for m in range(6):
            mes = somar_meses(inicio, m)
            for _ in range(14):
                nome, c, lo, hi = rnd.choice(variaveis)
                dia = rnd.randint(1, 28)
                d = mes.replace(day=dia)
                if d > hoje:
                    continue
                services.criar_lancamento(u, {
                    "tipo": "DESPESA", "natureza": "VARIAVEL", "descricao": nome, "categoria": cat[c],
                    "valor": Decimal(rnd.randint(lo * 100, hi * 100)) / 100, "data": d,
                    "cartao": rnd.choice([nubank, nubank, inter, None]), "forma": "UNICA", "pago": False,
                })
            if m == 4:
                criar(tipo="RECEITA", descricao="Freela site", valor=Decimal("1800"), data=mes.replace(day=18),
                      categoria=cat["Freelance"], cartao=conta)

        # meses passados ficam pagos
        Lancamento.objects.filter(usuario=u, competencia__lt=primeiro_dia(hoje)).update(pago=True)

        for nome, teto in [("Mercado", "900"), ("Alimentação", "300"), ("Lazer", "100"), ("Transporte", "450")]:
            cat[nome].orcamento_mensal = Decimal(teto)
            cat[nome].save()

        self.stdout.write(self.style.SUCCESS(
            f"Usuário '{USUARIO}' criado com {Lancamento.objects.filter(usuario=u).count()} lançamentos."))
