# Finanças: controle financeiro pessoal

Sistema web em **Python/Django** para controlar receitas, despesas fixas e variáveis, cartões, contas recorrentes e compras parceladas, com dashboard por cartão e exportação para Excel.

## Funcionalidades

- **Receitas e despesas**, com despesas classificadas em **fixas** ou **variáveis**
- **Cartões e contas**: crédito (limite, dia de fechamento e vencimento), débito e dinheiro/Pix
- **Fatura correta**: uma compra feita depois do fechamento entra na fatura do mês seguinte
- **Compras parceladas**: informe o total ou o valor da parcela; o sistema cria uma parcela por mês e põe os centavos que sobram na primeira
- **Contas recorrentes** (aluguel, salário, assinaturas): são lançadas automaticamente todo mês até você encerrar
- **Dashboard mensal**, geral ou por cartão: % da receita gasta, saldo, fixas × variáveis, a pagar, gastos por dia, últimos 6 meses, gastos por categoria e limite usado
- **Orçamento por categoria**, com aviso quando passa do limite
- **Marcar como pago**, um lançamento por vez ou a fatura inteira do cartão
- **Planilha Excel** do mês ou do ano, com as abas Resumo, Lançamentos, Por categoria e Por cartão
- Login com vários usuários (cada um só vê os próprios dados) e tema claro/escuro

## Stack

Python 3.12+ · Django 6 · PostgreSQL (ou SQLite) · openpyxl · Chart.js

## Como rodar

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      # depois edite o .env com a senha do Postgres
```

Crie o banco no PostgreSQL (pelo pgAdmin ou pelo psql):

```sql
CREATE DATABASE financas;
```

Depois:

```powershell
python manage.py migrate
python manage.py createsuperuser   # opcional, para o /admin
python manage.py dados_demo        # opcional: usuário demo com 6 meses de exemplo
python manage.py runserver
```

Acesse http://localhost:8000. O login do usuário demo está no topo de `financas/management/commands/dados_demo.py`.

> Sem `DB_NAME` no `.env`, o projeto usa SQLite automaticamente.

## Testes

```powershell
python manage.py test
```

## Estrutura

```
config/               configurações do Django
financas/
  models.py           Cartao, Categoria, Recorrencia, Lancamento
  services.py         regras: parcelamento, recorrências, resumos do mês
  excel.py            exportação .xlsx
  views.py / forms.py telas e formulários
  tests.py
templates/            HTML (Django templates)
static/css/app.css    estilo (claro/escuro)
```

## Publicar de graça (PythonAnywhere)

O plano gratuito do PythonAnywhere não tem PostgreSQL. Lá, deixe `DB_NAME` vazio para usar SQLite, coloque `DEBUG=False` e configure `ALLOWED_HOSTS` e `CSRF_TRUSTED_ORIGINS` com o seu domínio `seuusuario.pythonanywhere.com`. Rode `python manage.py collectstatic` e aponte `/static/` para a pasta `staticfiles` na aba *Web*.
