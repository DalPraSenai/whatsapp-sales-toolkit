# leads.db — Banco de Leads de Exemplo

Banco SQLite gerado pelo `gmaps-lead-scraper`. Contém leads reais coletados do Google Maps para fins de demonstração da ferramenta.

## Conteúdo

| Tabela | Registros | Descrição |
|---|---|---|
| `leads` | 28.501 | Empresas coletadas com nome, telefone, localização e nicho |
| `tarefas` | 8.620 | Combinações estado/cidade/nicho já processadas pelo scraper |

## Leads por estado

| Estado | Leads |
|---|---|
| PR | 4.245 |
| MG | 3.805 |
| GO | 3.266 |
| RJ | 3.156 |
| PE | 2.599 |
| MT | 2.577 |
| CE | 2.305 |
| BA | 2.112 |
| ES | 1.790 |
| MS | 1.313 |
| PB | 1.209 |
| DF | 124 |

## Nichos coletados

Construtora, oficina diesel, mineração, empresa de escavação, locação de equipamentos, mecânica pesada, terraplenagem, injeção diesel, pavimentação, retífica diesel, equipamentos pesados, tratores manutenção, locação de máquinas pesadas, obra pesada, movimentação de terra, escavadeira, bomba injetora diesel, retroescavadeira.

## Estrutura da tabela `leads`

```sql
CREATE TABLE leads (
    nome      TEXT,
    telefone  TEXT,
    cidade    TEXT,
    estado    TEXT,
    nicho     TEXT,
    categoria TEXT,
    score     INTEGER,
    enviado   INTEGER DEFAULT 0,
    status    INTEGER DEFAULT 0
);
```

## Distribuição por score

| Score | Leads | Critério |
|---|---|---|
| 7 | 4.532 | Oficina/retífica/injeção diesel — alta aderência ao produto |
| 5 | 3.340 | Mecânica pesada, terraplenagem |
| 2 | 20.628 | Demais categorias (construtoras, escavação, etc.) |
| 10 | 1 | Alta aderência + telefone limpo |

O `wa-outreach-bot` filtra por padrão `score >= 5`, priorizando os ~7.900 leads mais qualificados.

## Observação sobre os telefones

Os números foram extraídos diretamente do Google Maps e contêm um caractere especial (`\ue0b0`) no início — artefato do ícone de telefone do Maps. A função `limpar_numero()` do `wa-outreach-bot` remove esse caractere automaticamente antes do envio.

## Consultas úteis

```sql
-- Leads prontos para envio (score alto, não enviados)
SELECT nome, telefone, cidade, estado, nicho
FROM leads
WHERE score >= 5 AND status = 0
ORDER BY score DESC;

-- Total por nicho
SELECT nicho, COUNT(*) as total
FROM leads
GROUP BY nicho
ORDER BY total DESC;

-- Leads já enviados
SELECT nome, cidade, estado
FROM leads
WHERE status = 1;
```
