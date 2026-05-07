# Aviator Analyzer — notas de finalização

Este arquivo documenta as duas fases de finalização aplicadas ao projeto.

## Fase 1 — bugfixes e cobertura inicial (47 testes)

### Arquivos novos da Fase 1

```
app/__init__.py                     # marcador de pacote (vazio)
app/collector/__init__.py           # marcador de pacote (vazio)
app/collector/dedup.py              # dedup por sequência (corrige bug de baixos repetidos)
app/logging_config.py               # logger central, idempotente

pytest.ini                          # config do pytest
requirements-dev.txt                # deps de desenvolvimento

tests/__init__.py
tests/conftest.py                   # fixture in_memory_db (SQLite :memory:)
tests/test_analyzer.py              # 18 testes
tests/test_backtesting.py           # 9 testes
tests/test_dedup.py                 # 11 testes (regressão do bug)
tests/test_manual_collector.py      # 3 testes
tests/test_volatility.py            # 5 testes
```

### Arquivos modificados na Fase 1

```
app/collector/browser.py            # usa dedup.py + logging_config; encerra gracioso
app/collector/manual.py             # valida multiplier >= 1.0
app/models.py                       # created_at timezone-aware
```

## Fase 2 — arquitetura de coletores (77 testes)

### Arquivos novos da Fase 2

```
app/collector/base.py               # BaseCollector + CollectorEvent
app/collector/dom_collector.py      # DOMCollector async (Playwright)
app/collector/ws_collector.py       # WebSocketCollector passivo
app/collector/manager.py            # CollectorManager + asyncio.Queue + cross-source dedup
app/collector/parser.py             # extração de multiplicadores (texto + JSON + WS frames)

tests/test_parser.py                # 21 testes do parser
tests/test_collectors.py            # 9 testes (BaseCollector + manager + auditoria estática)
```

### Arquivos modificados na Fase 2

```
app/collector/browser.py            # virou wrapper retrocompat sobre DOMCollector + manager
app/logging_config.py               # suporte a JSON line via AVIATOR_LOG_FORMAT
app/main.py                         # seletor DOM / WebSocket / DOM+WS na UI Streamlit
pytest.ini                          # asyncio_mode = auto
requirements-dev.txt                # +pytest-asyncio
tests/conftest.py                   # monkeypatch também para manager.SessionLocal
README.md                           # nova arquitetura, env vars, comandos
```

## Como rodar os testes

```bash
pip install -r requirements-dev.txt
pytest
```

Resultado esperado: **77 passed**.

## Garantias de segurança ("somente leitura")

Reforçadas por **dois testes de auditoria estática** em `tests/test_collectors.py`:

- `test_dom_collector_has_no_financial_actions` — tokeniza `dom_collector.py`,
  remove comentários/docstrings e falha se encontrar `.click(`, `.tap(`,
  `.fill(`, `.press(`, `.dispatch_event(`, `.select_option(`, `.hover(`, etc.
- `test_ws_collector_has_no_send_calls` — idem para `ws_collector.py`,
  proibindo `ws.send(`, `send_text(`, `send_bytes(`.

Esses testes vão falhar no CI se um futuro contribuidor tentar adicionar
qualquer ação financeira. É uma trava arquitetural, não só uma convenção.

## O que ainda não foi feito

- CI (GitHub Actions) executando `pytest` em PRs.
- `pre-commit` com `ruff` + `mypy`.
- Configuração por cassino em arquivo (hoje só env var).
- Testes de integração reais com Playwright (requer navegador + cassino).

## Cobertura por módulo (final)

| Módulo                       | Testes | Notas                                               |
|------------------------------|--------|-----------------------------------------------------|
| `app/collector/parser.py`    | 21     | Texto, JSON aninhado, WS frames, env var customizada |
| `app/analyzer.py`            | 18     | Boundaries, summarize, scores                       |
| `app/collector/dedup.py`     | 12     | Inclui regressão do bug original                    |
| `app/backtesting.py`         | 9      | Stop-loss, stop-gain, max_entries, all-strategies   |
| `app/collector/{base,manager}` | 9    | Fakes + auditoria estática anti-ação-financeira     |
| `app/volatility.py`          | 5      | NaN inicial, série constante, janela default        |
| `app/collector/manual.py`    | 3      | Validação, persistência, valores repetidos          |
| `app/collector/dom_collector.py` | 0 funcional | Auditoria estática presente; integração depende de Playwright |
| `app/collector/ws_collector.py`  | 0 funcional | Idem                                            |
| `app/main.py`                | 0      | UI Streamlit, teste via execução manual             |

Total: **77 passed**.
