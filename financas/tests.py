from datetime import date
from decimal import Decimal
from io import BytesIO

from django.contrib.auth.models import User
from django.test import TestCase
from openpyxl import load_workbook

from . import services
from .excel import gerar_planilha
from .models import Cartao, Lancamento, Recorrencia


class BaseTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("ana", password="senha-forte-123")
        services.garantir_categorias_padrao(self.user)
        self.nubank = Cartao.objects.create(
            usuario=self.user, nome="Nubank", tipo="CREDITO", limite=Decimal("2000"), dia_fechamento=25,
            dia_vencimento=5,
        )

    def dados(self, **extra):
        base = {"tipo": "DESPESA", "natureza": "VARIAVEL", "descricao": "Teste", "valor": Decimal("100"),
                "data": date(2026, 3, 10), "categoria": None, "cartao": None, "forma": "UNICA", "pago": False}
        base.update(extra)
        return base


class RegrasTest(BaseTest):
    def test_divide_parcelas_sem_perder_centavos(self):
        partes = services.dividir_em_parcelas(Decimal("100.00"), 3)
        self.assertEqual(sum(partes), Decimal("100.00"))
        self.assertEqual(partes, [Decimal("33.34"), Decimal("33.33"), Decimal("33.33")])

    def test_compra_apos_fechamento_vai_para_fatura_seguinte(self):
        self.assertEqual(self.nubank.mes_da_fatura(date(2026, 3, 24)), date(2026, 3, 1))
        self.assertEqual(self.nubank.mes_da_fatura(date(2026, 3, 25)), date(2026, 4, 1))
        self.assertEqual(self.nubank.mes_da_fatura(date(2026, 12, 28)), date(2027, 1, 1))

    def test_compra_parcelada_cria_uma_parcela_por_mes(self):
        criados = services.criar_lancamento(
            self.user, self.dados(forma="PARCELADA", valor=Decimal("300"), cartao=self.nubank,
                                  data=date(2026, 11, 26)), num_parcelas=3)
        self.assertEqual([l.competencia for l in criados], [date(2026, 12, 1), date(2027, 1, 1), date(2027, 2, 1)])
        self.assertEqual([l.rotulo_parcela for l in criados], ["1/3", "2/3", "3/3"])
        self.assertEqual(len({l.grupo for l in criados}), 1)

    def test_valor_por_parcela(self):
        criados = services.criar_lancamento(
            self.user, self.dados(forma="PARCELADA", valor=Decimal("50")), num_parcelas=4, valor_e_total=False)
        self.assertTrue(all(l.valor == Decimal("50") for l in criados))

    def test_recorrencia_gera_um_lancamento_por_mes_sem_duplicar(self):
        rec = Recorrencia.objects.create(usuario=self.user, descricao="Aluguel", valor=Decimal("1500"),
                                         inicio=date(2026, 1, 5))
        services.materializar_recorrencias(self.user, date(2026, 6, 1))
        services.materializar_recorrencias(self.user, date(2026, 6, 1))
        self.assertEqual(rec.lancamentos.count(), 6)

    def test_encerrar_recorrencia_remove_futuros_pendentes(self):
        rec = Recorrencia.objects.create(usuario=self.user, descricao="Academia", valor=Decimal("99"),
                                         inicio=date(2026, 1, 10))
        services.materializar_recorrencias(self.user, date(2026, 12, 1))
        services.encerrar_recorrencia(rec, date(2026, 4, 1))
        self.assertEqual(rec.lancamentos.count(), 4)
        services.materializar_recorrencias(self.user, date(2027, 6, 1))
        self.assertEqual(rec.lancamentos.count(), 4)

    def test_resumo_separa_fixas_e_variaveis(self):
        services.criar_lancamento(self.user, self.dados(tipo="RECEITA", valor=Decimal("5000")))
        services.criar_lancamento(self.user, self.dados(natureza="FIXA", valor=Decimal("1500")))
        services.criar_lancamento(self.user, self.dados(valor=Decimal("500"), cartao=self.nubank))
        r = services.resumo_mes(self.user, date(2026, 3, 1))
        self.assertEqual((r["receitas"], r["fixas"], r["variaveis"], r["saldo"]),
                         (Decimal("5000"), Decimal("1500"), Decimal("500"), Decimal("3000")))
        self.assertEqual(r["pct_gasto"], 40.0)
        r_cartao = services.resumo_mes(self.user, date(2026, 3, 1), self.nubank)
        self.assertEqual(r_cartao["despesas"], Decimal("500"))

    def test_planilha_tem_abas_e_lancamentos(self):
        services.criar_lancamento(self.user, self.dados(valor=Decimal("42.50")))
        wb = load_workbook(BytesIO(gerar_planilha(self.user, date(2026, 1, 1), date(2026, 12, 1))))
        self.assertEqual(wb.sheetnames, ["Resumo", "Lançamentos", "Por categoria", "Por cartão"])
        self.assertEqual(wb["Lançamentos"]["J2"].value, -42.5)


class TelasTest(BaseTest):
    def setUp(self):
        super().setUp()
        self.client.login(username="ana", password="senha-forte-123")

    def test_paginas_abrem(self):
        for url in ["/", "/?mes=2026-03", f"/?cartao={self.nubank.pk}", "/lancamentos/", "/lancamentos/novo/",
                    "/cartoes/", "/cartoes/novo/", "/categorias/", "/recorrencias/"]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_exige_login(self):
        self.client.logout()
        self.assertRedirects(self.client.get("/"), "/entrar/?next=/")

    def test_nao_ve_dados_de_outro_usuario(self):
        outro = User.objects.create_user("bob", password="x")
        cartao = Cartao.objects.create(usuario=outro, nome="Do Bob")
        self.assertEqual(self.client.get(f"/cartoes/{cartao.pk}/").status_code, 404)

    def test_cadastro_parcelado_pelo_formulario(self):
        resp = self.client.post("/lancamentos/novo/", {
            "tipo": "DESPESA", "natureza": "VARIAVEL", "descricao": "Notebook", "valor": "3000",
            "data": "2026-03-10", "cartao": self.nubank.pk, "forma": "PARCELADA", "num_parcelas": "10",
            "valor_e_total": "1",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Lancamento.objects.filter(descricao="Notebook").count(), 10)

    def test_exportar(self):
        resp = self.client.get("/exportar/?ano=2026")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("spreadsheetml", resp["Content-Type"])


class MetasEAlertasTest(BaseTest):
    def test_vencimento_da_fatura(self):
        # fecha 25, vence 5 -> fatura de março vence em 5 de abril
        self.assertEqual(self.nubank.vencimento_da_fatura(date(2026, 3, 1)), date(2026, 4, 5))
        inter = Cartao.objects.create(usuario=self.user, nome="Inter", dia_fechamento=1, dia_vencimento=10)
        self.assertEqual(inter.vencimento_da_fatura(date(2026, 3, 1)), date(2026, 3, 10))

    def test_status_da_meta(self):
        from .models import Categoria
        cat = Categoria.objects.get(usuario=self.user, nome="Alimentação")
        cat.orcamento_mensal = Decimal("100")
        cat.save()
        mes, hoje = date(2026, 3, 1), date(2026, 3, 20)
        services.criar_lancamento(self.user, self.dados(valor=Decimal("50"), categoria=cat))
        self.assertEqual(services.metas_do_mes(self.user, mes, hoje)["itens"][0]["status"], "ok")
        services.criar_lancamento(self.user, self.dados(valor=Decimal("35"), categoria=cat))
        self.assertEqual(services.metas_do_mes(self.user, mes, hoje)["itens"][0]["status"], "atencao")
        services.criar_lancamento(self.user, self.dados(valor=Decimal("20"), categoria=cat))
        m = services.metas_do_mes(self.user, mes, hoje)
        self.assertEqual((m["itens"][0]["status"], m["cumpridas"]), ("estourou", 0))
        # mês já encerrado mostra "Não cumprida"
        self.assertEqual(services.metas_do_mes(self.user, mes, date(2026, 5, 1))["itens"][0]["rotulo"], "Não cumprida")

    def test_aviso_ao_salvar(self):
        from .models import Categoria
        cat = Categoria.objects.get(usuario=self.user, nome="Lazer")
        cat.orcamento_mensal = Decimal("100")
        cat.save()
        [l] = services.criar_lancamento(self.user, self.dados(valor=Decimal("90"), categoria=cat))
        nivel, texto = services.aviso_de_meta(l)
        self.assertEqual(nivel, "warning")
        self.assertIn("R$ 10,00", texto)

    def test_alertas_de_vencimento(self):
        hoje = date(2026, 4, 3)
        # compra no Nubank em março -> fatura vence 05/04 (daqui a 2 dias)
        services.criar_lancamento(self.user, self.dados(valor=Decimal("80"), cartao=self.nubank))
        services.criar_lancamento(self.user, self.dados(valor=Decimal("20"), cartao=self.nubank))
        # conta sem cartão vencida ontem
        services.criar_lancamento(self.user, self.dados(descricao="Luz", natureza="FIXA", data=date(2026, 4, 2)))
        # compra avulsa no Pix não é conta a vencer
        services.criar_lancamento(self.user, self.dados(descricao="Padaria", data=date(2026, 4, 2)))
        # conta paga não aparece
        services.criar_lancamento(self.user, self.dados(descricao="Água", data=date(2026, 4, 2), pago=True))
        itens = services.alertas(self.user, hoje)
        self.assertEqual([(a["titulo"], a["nivel"]) for a in itens],
                         [("Luz", "atrasada"), ("Fatura Nubank", "breve")])
        self.assertEqual(itens[1]["valor"], Decimal("100"))

    def test_cor_do_texto_do_cartao(self):
        self.nubank.cor = "#FFE066"
        self.assertEqual(self.nubank.cor_texto, "#1B1B1F")
        self.nubank.cor = "#8B3DFF"
        self.assertEqual(self.nubank.cor_texto, "#FFFFFF")


class AparenciaTest(BaseTest):
    def setUp(self):
        super().setUp()
        self.client.login(username="ana", password="senha-forte-123")

    def test_escolher_paleta(self):
        self.assertContains(self.client.get("/aparencia/"), "Oceano")
        self.client.post("/aparencia/", {"paleta": "oceano"})
        self.assertContains(self.client.get("/"), 'data-paleta="oceano"')

    def test_paleta_invalida_e_ignorada(self):
        self.client.post("/aparencia/", {"paleta": "qualquer"})
        self.assertContains(self.client.get("/"), 'data-paleta="por-do-sol"')
