# wa-reactivation-bot

Bot de reativação de leads via WhatsApp Web. Percorre a lista de conversas existentes, filtra contatos que estão sem resposta há mais de N dias e envia uma mensagem de "cutucada" para reabrir o diálogo.

## O que faz

- Scrola toda a lista de chats do WhatsApp Web e mapeia os contatos
- Filtra automaticamente: grupos, números sem nome, contatos recentes, já enviados antes
- Abre cada chat pra você avaliar visualmente antes de aprovar
- Salva a lista de aprovados em `aprovados.csv` (persistência entre sessões)
- Envia mensagem aleatória de reativação para os aprovados, com delay entre envios
- Registra tudo em log e CSV de enviados

## Fluxo em 3 fases

```
FASE 1 — Coleta
  Scrola o painel de chats e mapeia todos os contatos com nome e timestamp

FASE 2 — Seleção interativa
  Para cada contato elegível, abre o chat e pergunta: [s] aprovar / [n] pular / [q] encerrar
  Lista salva em aprovados.csv — pode continuar de onde parou se interrompido

FASE 3 — Envio
  Envia mensagem aleatória para cada aprovado com delay configurável entre envios
```

## Filtros automáticos (Fase 1 → 2)

| Critério | Ação |
|---|---|
| É grupo | Ignorado |
| Nome é só número | Ignorado |
| Conversa recente (< 10 dias) | Ignorado |
| Já está em `enviados.csv` | Ignorado |
| Nome em lista negra | Ignorado ("arquivadas", "status", etc.) |

## Configuração

No topo do arquivo `wa_reactivation_bot.py`:

```python
DIAS_RECENTES = 10      # contatos com menos de N dias são ignorados
PRODUTO       = "filtros para linha pesada"   # aparece nas mensagens
LIMITE_DIA    = 15      # máximo de envios por execução
```

## Como usar

```bash
python wa_reactivation_bot.py
```

Escaneie o QR code quando solicitado. O bot não usa sessão persistida — é necessário login a cada execução.

Para pausar durante o envio:

```bash
touch pause.flag    # pausa
rm pause.flag       # retoma
```

## Mensagens

4 templates de reativação, escolhidos aleatoriamente, com `{nome}` e `{produto}` substituídos dinamicamente. Exemplos:

> "Fala, João! Passando só pra ver como você está. A gente chegou a falar sobre filtros para linha pesada um tempo atrás e queria saber se isso ainda faz sentido pra você..."

> "Oi, João! Só me diz uma coisa rapidinho: você ainda tem interesse em filtros para linha pesada ou posso encerrar seu contato por aqui?"

## Arquivos gerados

| Arquivo | Conteúdo |
|---|---|
| `aprovados.csv` | Lista de nomes aprovados na fase de seleção (removido após envio) |
| `enviados.csv` | Histórico de envios com resultado e timestamp |
| `cutucada.log` | Log completo da execução |

## Dependências

```bash
pip install playwright
playwright install chromium
```

## Diferença em relação ao `wa-outreach-bot`

| | `wa-outreach-bot` | `wa-reactivation-bot` |
|---|---|---|
| Fonte dos contatos | Banco SQLite (leads novos) | Lista de chats do WhatsApp |
| Objetivo | Primeiro contato / apresentação | Reativar conversa parada |
| Seleção | Automática por score | Manual (você aprova cada um) |
| Anti-detecção | Avançado (Stealth JS + HumanEngine) | Básico (delays aleatórios) |
| Sessão | Persistida (sem QR) | Requer login a cada execução |
