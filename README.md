# WhatsApp Sales Toolkit

Pipeline completo de prospecção e reativação de leads via WhatsApp Web, desenvolvido para o setor de peças e equipamentos pesados.

## Visão geral

Três ferramentas independentes que formam um pipeline de vendas:

```
[1] gmaps-lead-scraper     →     [2] wa-outreach-bot     →     [3] wa-reactivation-bot
  Coleta leads no               Envia apresentação              Reativa contatos
  Google Maps                   para leads novos                antigos da lista WA
```

---

## Módulos

### 1. [`gmaps-lead-scraper`](./gmaps-lead-scraper/)
Scraper do Google Maps que coleta empresas por nicho e localização, gerando um banco SQLite de leads com nome, telefone, cidade, estado e categoria.

### 2. [`wa-outreach-bot`](./wa-outreach-bot/)
Bot de prospecção ativa. Lê os leads do banco gerado pelo scraper e envia mensagens de apresentação via WhatsApp Web com comportamento humano avançado e anti-detecção.

### 3. [`wa-reactivation-bot`](./wa-reactivation-bot/)
Bot de reativação. Percorre a lista de conversas existentes no WhatsApp Web e reenvia mensagem para contatos que ficaram sem resposta há mais de N dias.

---

## Requisitos

```bash
pip install playwright pandas unidecode openpyxl
playwright install chromium
```

---

## Stack

- Python 3.10+
- Playwright (automação de browser)
- SQLite (persistência de leads)
- Google Maps (fonte de dados públicos)
- WhatsApp Web (canal de envio)

---

## Aviso

Estas ferramentas automatizam interações com o WhatsApp Web. Use com responsabilidade, respeitando os limites da plataforma e a legislação de proteção de dados (LGPD). O envio em massa sem consentimento pode resultar em banimento do número.
# whatsapp-sales-toolkit
