# gmaps-lead-scraper

Coleta leads de empresas no Google Maps por nicho de mercado e localização geográfica, salvando os resultados em um banco SQLite.

## O que faz

- Consulta a API de municípios do IBGE para obter cidades por estado
- Busca empresas no Google Maps com múltiplas variações de query por nicho
- Extrai: nome, telefone, cidade, estado, nicho, categoria do Maps
- Deduplica por `(nome, telefone)` via `UNIQUE` no SQLite
- Controla tarefas já executadas para permitir retomada sem retrabalho
- Exporta o resultado final para `.xlsx`

## Nichos configurados (padrão)

Focado em mecânica pesada e construção civil:
- retifica diesel, bomba injetora, oficina diesel
- terraplenagem, construtora, pavimentação, mineração
- locação de máquinas/equipamentos pesados
- escavadeira, retroescavadeira, tratores

## Configuração

No topo do arquivo `gmaps_lead_scraper.py`:

```python
ESTADOS    = ["MG", "RJ", "PR", ...]   # estados a prospectar
NICHOS     = ["retifica diesel", ...]   # nichos de busca
PROCESSOS  = 5                          # processos paralelos
CONTEXTS   = 2                          # contextos por processo
DB         = "leads.db"                 # banco de saída
```

## Como usar

```bash
python gmaps_lead_scraper.py
```

O script roda em paralelo (multiprocessing). Para pausar sem perder progresso, crie o arquivo `pause.txt` na pasta:

```bash
touch pause.txt      # pausa
rm pause.txt         # retoma
```

## Saída

| Arquivo | Conteúdo |
|---|---|
| `leads.db` | Banco SQLite com tabelas `leads` e `tarefas` |
| `BRASIL_HH-MM.xlsx` | Export final de todos os leads coletados |

### Estrutura da tabela `leads`

| Campo | Tipo | Descrição |
|---|---|---|
| nome | TEXT | Nome da empresa (normalizado) |
| telefone | TEXT | Telefone extraído do Maps |
| cidade | TEXT | Município |
| estado | TEXT | UF |
| nicho | TEXT | Query de busca usada |
| categoria | TEXT | Categoria do Google Maps |

## Dependências

```bash
pip install playwright pandas unidecode openpyxl
playwright install chromium
```

## Observações

- O scraper usa `headless=True` — não abre janela do browser
- Cada tarefa `(estado, cidade, nicho)` é registrada; reruns pulam o que já foi feito
- O caminho de export do `.xlsx` está hardcoded para `C:\Users\danie\Documents\...` — ajuste antes de usar
