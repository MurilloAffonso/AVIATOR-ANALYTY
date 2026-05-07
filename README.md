# aviator-analyzer

Painel local em Python/Streamlit para **análise estatística e behavioral analytics** de resultados do jogo Aviator.

> ⚠️ **Não é um robô de aposta.** Este sistema é estritamente *somente leitura*: não clica em "apostar", não clica em "cashout", não envia frames WebSocket, não toma nenhuma ação financeira. Não promete previsão garantida — todo crash game tem RTP < 100% no longo prazo. Os "scores de oportunidade" são apenas medidas estatísticas.

## Objetivo

Construir um painel local com foco em:

- histórico de multiplicadores;
- volatilidade móvel;
- detecção de sequências e concentrações;
- simulação de estratégias (backtesting);
- coleta passiva de dados via DOM e/ou WebSocket.

## Estrutura

```text
app/
  analyzer.py           # estatísticas, scores de risco/oportunidade
  backtesting.py        # simulação de 5 estratégias
  config.py             # paths, DATABASE_URL
  database.py           # SQLAlchemy engine + SessionLocal
  logging_config.py     # logging central (texto ou JSON line)
  main.py               # UI Streamlit
  models.py             # RoundResult (ORM)
  volatility.py         # rolling std
  collector/
    base.py             # BaseCollector + CollectorEvent
    dom_collector.py    # DOMCollector (Playwright async, lê texto da página)
    ws_collector.py     # WebSocketCollector (Playwright async, escuta frames)
    manager.py          # CollectorManager (asyncio.Queue + cross-source dedup)
    parser.py           # extração de multiplicadores (texto + JSON + WS frames)
    dedup.py            # deduplicação por sequência (corrige bug de baixos repetidos)
    manual.py           # inserção manual via UI
    browser.py          # wrapper retrocompat: collect_live_results(url, ...)
tests/                  # 77 testes
data/                   # SQLite local (criado em runtime)
```

## Instalação

```bash
# Dependências de produção
pip install -r requirements.txt

# Dependências de desenvolvimento (pytest, pytest-asyncio)
pip install -r requirements-dev.txt

# Browser para o Playwright (necessário para coleta ao vivo)
playwright install chromium
```

## Execução

```bash
streamlit run app/main.py
```

## Testes

```bash
pytest
```

Resultado esperado: **77 passed**.

## Coleta ao vivo (somente leitura)

A UI oferece três modos, todos baseados em coletores em `app/collector/`:

| Modo | O que faz | Quando usar |
|---|---|---|
| **DOM** | Lê o texto da barra de histórico via `body.inner_text()` em ciclos de polling | Padrão; funciona em qualquer cassino sem inspeção de protocolo |
| **WebSocket** | Escuta frames `framereceived` via `page.on("websocket")` e parseia JSON | Menor latência; depende do cassino expor multiplicadores no payload |
| **DOM + WebSocket** | Roda os dois em paralelo; o `CollectorManager` faz dedup cross-source | Máxima cobertura; útil quando o WS e o DOM atualizam em momentos diferentes |

### Garantias de segurança

Os coletores são auditados estaticamente em `tests/test_collectors.py`:

- `test_dom_collector_has_no_financial_actions` falha se alguém adicionar `.click()`, `.tap()`, `.fill()`, `.press()`, `.dispatch_event()`, `.select_option()`, etc.
- `test_ws_collector_has_no_send_calls` falha se alguém adicionar `ws.send()`, `send_text()`, `send_bytes()`.

Em runtime, o coletor:

1. abre um navegador visível (login é manual);
2. navega para a URL fornecida;
3. lê texto da página *ou* escuta frames recebidos;
4. extrai multiplicadores via `parser.py`;
5. publica eventos em uma `asyncio.Queue`;
6. o `CollectorManager` consome a fila, faz cross-source dedup, e persiste no SQLite.

Encerra graciosamente quando o usuário fecha o navegador ou o tempo máximo é atingido.

## Variáveis de ambiente

| Variável | Default | Efeito |
|---|---|---|
| `AVIATOR_LOG_FORMAT` | `text` | Use `json` para emitir logs estruturados (uma linha JSON por evento, com campos extras passados via `logger.info(..., extra={...})`) |
| `AVIATOR_PARSER_KEYS` | (vazio) | Lista CSV de chaves JSON adicionais que o parser deve reconhecer como multiplicador (ex.: `finalCoefficient,bet_x`) |

Exemplo:

```bash
AVIATOR_LOG_FORMAT=json AVIATOR_PARSER_KEYS=finalCoefficient streamlit run app/main.py
```

## Análise avançada incluída

- detecção de sequência de baixos consecutivos (atual e máxima);
- intervalo médio entre resultados ≥ 10x e ≥ 50x;
- volatilidade das últimas 20, 50 e 100 rodadas;
- alerta de concentração anormal de baixos (compara janela curta vs baseline);
- alerta de subida de variância recente (recente > baseline × 1.8);
- score de risco (0 a 100);
- score de oportunidade estatística (0 a 100), **sem promessa de previsão**.

## Backtesting (simulado, sem aposta real)

Estratégias incluídas:

1. entrada fixa com cashout em 1.5x;
2. entrada fixa com cashout em 2x;
3. entrada após N rodadas abaixo de 1.5x;
4. entrada após N rodadas abaixo de 2x;
5. estratégia conservadora (alvo capado em 1.5x).

Configurações do usuário:

- banca inicial;
- valor por entrada;
- cashout alvo;
- stop loss;
- stop gain;
- número máximo de entradas;
- gatilho `N` para estratégias condicionais.

Saídas exibidas:

- lucro/prejuízo;
- drawdown máximo;
- taxa de acerto;
- ROI;
- gráfico da evolução da banca por estratégia.

## Cobertura de testes

| Módulo | Testes | Notas |
|---|---|---|
| `app/collector/parser.py` | 21 | Texto, JSON aninhado, frames WS, env var customizada |
| `app/analyzer.py` | 18 | Boundaries, summarize, scores |
| `app/collector/dedup.py` | 12 | Inclui regressão do bug de baixos repetidos |
| `app/backtesting.py` | 9 | Stop-loss, stop-gain, max_entries, all-strategies |
| `app/collector/`  (base + manager + auditoria) | 9 | Fakes + testes de auditoria estática contra ações financeiras |
| `app/volatility.py` | 5 | NaN inicial, série constante, janela default |
| `app/collector/manual.py` | 3 | Validação, persistência, valores repetidos |
| `app/collector/dom_collector.py` | 0 (auditoria estática) | Depende de Playwright + página real |
| `app/collector/ws_collector.py` | 0 (auditoria estática) | Depende de Playwright + página real |
| `app/main.py` | 0 | UI Streamlit, testar via execução manual |

Total: **77 passed**.

DOM/WS/UI ficam sem teste de unidade *funcional* porque dependem de I/O externo (navegador real, servidor Streamlit, cassino com WS ativo). A lógica determinística — extração, dedup, agendamento via fila, persistência — está coberta isoladamente.
