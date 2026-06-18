# wa-outreach-bot

Bot de prospecção ativa via WhatsApp Web. Lê leads do banco SQLite gerado pelo `gmaps-lead-scraper` e envia mensagens de apresentação com comportamento humano simulado e anti-detecção.

## O que faz

- Lê leads do `leads.db` filtrando por score e status pendente
- Abre o WhatsApp Web com sessão persistida (sem QR a cada execução)
- Para cada lead: navega, verifica se já foi contatado, digita e envia
- Registra o resultado no banco (`status`: enviado / erro / inválido / já contatado)
- Simula comportamento humano para reduzir risco de detecção

## Arquitetura

### `MessageComposer` — composição dinâmica de mensagens
Monta mensagens a partir de blocos independentes combinados aleatoriamente:

| Bloco | Exemplos |
|---|---|
| Saudação | "Oi {nome}", "Boa tarde {nome}", (omitido) |
| Apresentação | "trabalho com filtros para linha pesada" |
| Contexto | "estou montando nossa base de parceiros" |
| Proposta | "posso te acionar quando tiver novidades?" |
| Fechamento | "Abs", "Valeu!", (omitido) |

9 estruturas de montagem diferentes. Fingerprint bag-of-words detecta similaridade com as últimas 12 mensagens enviadas e rejeita se acima de 45% — evita padrão repetitivo.

### `HumanEngine` — simulação de comportamento humano
- **Delays gaussianos** entre leads (não uniformes, mais realistas)
- **Modelo de fadiga**: quanto mais tempo rodando, maiores os delays
- **Digitação com erros e correção**: 6% de chance por palavra, com backspace e redigitação
- **Modo burst**: aceleração no meio das palavras
- **Mouse em Bézier**: movimento natural até os elementos antes de clicar
- **Pausa de leitura**: simula ler a mensagem antes de enviar
- **Breaks aleatórios**: 4% de chance de parar 3–8 min ("foi pegar água")

### Anti-detecção (Stealth JS)
Injeta JavaScript no contexto antes de qualquer navegação:
- Remove `navigator.webdriver`
- Falsifica lista de plugins, `hardwareConcurrency`, `deviceMemory`
- Corrige `navigator.languages` para `['pt-BR', 'pt', 'en-US', 'en']`
- Spoofa vendor WebGL (Intel)
- Viewport randomizado a cada sessão

## Configuração

No topo do arquivo, via dataclass `Config`:

```python
limite           = 120      # máximo de leads por execução
delay_min        = 18.0     # delay mínimo entre leads (segundos)
delay_max        = 55.0     # delay máximo entre leads
delay_long_chance = 0.18    # chance de delay longo (75-160s)
delay_break_chance = 0.04   # chance de break longo (3-8min)
type_wpm_min     = 38       # velocidade mínima de digitação
type_wpm_max     = 72       # velocidade máxima
typo_chance      = 0.06     # chance de erro por palavra
skip_first_n     = 0        # pular os N primeiros leads (útil para retomada)
```

## Como usar

```bash
python wa_outreach_bot.py
```

Na primeira execução: escaneie o QR code. Nas seguintes, a sessão é restaurada automaticamente do diretório `~/.wp_bot_profile`.

Para pausar durante a execução:

```bash
touch pause.flag    # pausa após o lead atual
rm pause.flag       # retoma
```

## Status dos leads no banco

| Valor | Significado |
|---|---|
| 0 | Pendente (padrão) |
| 1 | Enviado com sucesso |
| 2 | Erro no envio |
| 3 | Número inválido |
| 4 | Já contatado anteriormente |

## Fluxo por lead

```
Carregar lead → limpar número → navegar URL → aguardar input
→ checar popup inválido → checar conversa existente
→ limpar campo → digitar humanamente → ler (delay) → enviar
→ confirmar envio → atualizar status no DB → aguardar delay
```

## Dependências

```bash
pip install playwright
playwright install chromium
```

## Observações

- O bot filtra leads com `score >= 5` e `telefone != ''` — garanta que o banco tem esses campos preenchidos
- O campo `score` não é gerado automaticamente pelo scraper; adicione sua lógica de scoring antes de rodar o bot
- Retire o `score >= 5` do SQL em `carregar_leads()` se não usar scoring
