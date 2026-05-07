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
  player_analytics/      # Player Analytics Engine (agregados anônimos)
    events.py            # RoundEvent, PlayerEvent, RoundSnapshot
    pipeline.py          # eventos -> snapshot por rodada
    survival.py          # curva de sobrevivência
    crowd_behavior.py    # greed, panic, aggression
    liquidity.py         # exhaustion, player flow
    psychology.py        # emoção + heatmap
    whales.py            # outliers de stake
    ws_adapter.py        # frames WS -> eventos de domínio
    storage.py / models.py / ui.py
tests/                  # 151 testes
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

## Player Analytics Engine

Painel agregado e anônimo do comportamento coletivo dos jogadores. Vive em `app/player_analytics/`:

```text
app/player_analytics/
  events.py            # RoundEvent, PlayerEvent, RoundSnapshot
  pipeline.py          # consome eventos, fecha rodada em ROUND_CRASH, emite snapshot
  survival.py          # curva de sobrevivência (Kaplan-Meier adaptado, censura no crash)
  crowd_behavior.py    # greed index, panic exit, crowd aggression, exit rates
  liquidity.py         # liquidity exhaustion, player flow, trend
  psychology.py        # distribuição emocional + exit heatmap
  whales.py            # outliers de stake (P95/P99), sem PII
  ws_adapter.py        # frames WS -> RoundEvent/PlayerEvent (heurístico, configurável)
  bridge.py            # PlayerAnalyticsBridge (frames WS -> pipeline em runtime)
  runner.py            # orquestra coletor + bridge + persistência (sync wrappers)
  storage.py           # persistência de RoundSnapshot no SQLite
  models.py            # ORM: RoundSnapshotORM
  ui.py                # render Streamlit
```

### Princípios

1. **Somente leitura** — nenhuma ação financeira; os módulos consomem eventos já capturados pelos coletores.
2. **Anonimato por construção** — IDs de jogador são hashados (SHA-256, truncado a 16 chars) **apenas** para deduplicar dentro de uma rodada. Os hashes são descartados ao fechar o snapshot. Nada de PII é persistido.
3. **Apenas agregados** — o que entra no SQLite é o `RoundSnapshot`: contagens, listas de cashouts, listas de stakes. Nunca "qual jogador apostou quanto".
4. **Degrada graciosamente** — se o cassino não expõe `stake`, métricas de liquidez/whales devolvem `None`/zero; não inventam.

### O que cada módulo computa

- **survival**: `S(m)` = fração de jogadores ainda expostos ao risco no multiplicador `m`. Quem foi pego pelo crash é tratado como censurado em `crash_multiplier`.
- **crowd_behavior**:
  - *greed_index* (0–100) — interpolação por mediana dos cashouts;
  - *panic_exit_score* (0–100) — concentração de cashouts numa janela apertada e em multiplicador baixo (heurística de "todos correram pra saída");
  - *crowd_aggression* (0–100) — combinação de ganância + participação;
  - *early_exit_rate*, *late_exit_rate*.
- **liquidity**: `payout_ratio = paid_out / staked`; *liquidity_exhaustion* (0–100, clamp); *player_flow* entre rodadas consecutivas; trend nas últimas N rodadas.
- **psychology**: bins emocionais (`medo`, `cautela`, `equilibrio`, `ambicao`, `euforia`, `queimou`) e *exit heatmap* unidimensional sobre todas as rodadas.
- **whales**: detecção via P95/P99 com fator multiplicativo sobre a mediana. Mínimo de 10 jogadores. Devolve contagem, share de volume e maior stake — sem identidade.

### Variáveis de ambiente adicionais

| Variável | Default | Efeito |
|---|---|---|
| `AVIATOR_PA_FIELD_MAP` | (vazio) | Mapeia campos JSON do cassino para nossos canônicos. Formato CSV: `round_id=gameId,player_id=accountHash,stake=wagerCents`. As chaves canônicas são `round_id`, `player_id`, `stake`, `cashout`, `payout`, `crash`, `event_type`. |

### PlayerAnalyticsBridge (runtime)

`bridge.py` conecta o `WebSocketCollector` ao `PlayerEventPipeline` em tempo real:

```
ws.framereceived (Playwright, callback síncrono)
        │
        ▼
bridge.on_frame(payload, "rx")          ← listener registrado
        │   parse_ws_frame_for_events(payload)
        ▼
asyncio.Queue (bounded, drop-oldest)    ← fila dedicada à analytics
        │
        ▼
consumer task                           ← isolado de exceções, conta restarts
        │
        ▼
PlayerEventPipeline → on_snapshot       ← persiste RoundSnapshot
```

**Garantias da bridge:**

- **Não bloqueia o coletor.** O listener síncrono só faz parse + enqueue (`call_soon_threadsafe`). O caminho de extração de multiplicadores do `WebSocketCollector` permanece intocado — testado em `test_listener_failure_does_not_break_collector`.
- **Back-pressure por drop-oldest.** Quando a fila enche, descarta o item mais antigo e incrementa `dropped_oldest`. Preserva a ponta recente, que é onde costuma estar o crash da rodada.
- **Tolerante a falhas.** Parser que `raise`, callback do usuário que crasha, `pipeline.handle` que falha — todos contidos. Métricas registram `parse_failures`, `consumer_restarts`, `last_error`. O consumer continua vivo.
- **Ciclo de vida idempotente.** `start()` e `stop()` podem ser chamados múltiplas vezes.
- **Replay.** `bridge.replay(payloads)` ou `runner.replay_session(payloads, persist=False)` re-executam uma sessão gravada offline — útil para validar mudanças de mapeamento sem abrir browser.

**Métricas expostas em `bridge.metrics.as_dict()`:**

| Campo | Tipo | Significado |
|---|---|---|
| `frames_received` | int | total de frames vistos (incl. tx ignorados) |
| `events_parsed` | int | eventos válidos extraídos |
| `parse_failures` | int | exceções no parser (≠ frames sem dado, que retornam `[]`) |
| `enqueue_failures` | int | frames perdidos mesmo após drop-oldest |
| `dropped_oldest` | int | itens descartados por fila cheia |
| `analytics_queue_size` | int | snapshot do tamanho atual da fila |
| `snapshots_generated` | int | rodadas finalizadas e enviadas ao callback |
| `consumer_restarts` | int | exceções não-fatais no consumer |
| `last_error` | str? | repr da última exceção registrada |

**Como ligar na UI:** o modo "WebSocket + Player Analytics" no botão de coleta sobe a bridge automaticamente. Ao final, mostra as métricas no expander. O mesmo painel oferece replay de arquivo `.jsonl`.

**Como ligar em código:**

```python
from app.player_analytics.bridge import PlayerAnalyticsBridge
from app.player_analytics.storage import persist_snapshot
from app.collector.ws_collector import WebSocketCollector

bridge = PlayerAnalyticsBridge(on_snapshot=persist_snapshot)
await bridge.start()

ws = WebSocketCollector(url="https://...")
ws.add_frame_listener(bridge.on_frame)

# ... rodar coleta normalmente ...

await bridge.stop(drain=True)
print(bridge.metrics.as_dict())
```

## Cobertura de testes

| Módulo | Testes | Notas |
|---|---|---|
| `app/collector/parser.py` | 21 | Texto, JSON aninhado, frames WS, env var customizada |
| `app/player_analytics/bridge.py` | 20 | Lifecycle, back-pressure, replay, integração WS, métricas |
| `app/analyzer.py` | 18 | Boundaries, summarize, scores |
| `app/player_analytics/crowd_behavior.py` | 14 | Greed, panic, aggression, exit rates |
| `app/player_analytics/pipeline.py` | 13 | Eventos -> snapshots, dedup, fora-de-ordem, callbacks |
| `app/collector/dedup.py` | 12 | Inclui regressão do bug de baixos repetidos |
| `app/player_analytics/ws_adapter.py` | 12 | Heurísticas, mapeamento de campos, anonimização |
| `app/player_analytics/liquidity.py` | 9 | Exhaustion, player flow, trend |
| `app/backtesting.py` | 9 | Stop-loss, stop-gain, max_entries, all-strategies |
| `app/collector/{base,manager}` | 9 | Fakes + auditoria estática anti-ação-financeira |
| `app/player_analytics/survival.py` | 7 | Curva por rodada, agregada, censura |
| `app/player_analytics/whales.py` | 7 | P95/P99, share, trend |
| `app/player_analytics/psychology.py` | 7 | Distribuição emocional, heatmap |
| `app/player_analytics/storage.py` | 5 | Persistência idempotente, ordem desc, valores nulos |
| `app/player_analytics/runner.py` | 5 | Replay session sync/async, persist on/off |
| `app/volatility.py` | 5 | NaN inicial, série constante |
| `app/collector/manual.py` | 3 | Validação, persistência |
| `app/collector/dom_collector.py` | 0 (auditoria estática) | Depende de Playwright |
| `app/collector/ws_collector.py` | 0 (auditoria estática) | Depende de Playwright |
| `app/main.py`, `app/player_analytics/ui.py` | 0 | UI Streamlit, teste via execução manual |

Total: **176 passed**.

UI/Coletores ficam sem teste de unidade *funcional* porque dependem de I/O externo (navegador real, servidor Streamlit, cassino com WS ativo). A lógica determinística — extração, dedup, agendamento via fila, agregação de eventos, métricas — está coberta isoladamente.
