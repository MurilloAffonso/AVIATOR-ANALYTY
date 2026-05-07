# Aviator Analyzer — pacote de finalização

Conteúdo deste zip: tudo que **ainda não está no `main`** do repositório
`MurilloAffonso/AVIATOR-ANALYTY` no GitHub, organizado na mesma estrutura
de pastas. Para aplicar, basta extrair o zip por cima do seu clone local
e fazer commit.

## Arquivos novos

```
app/__init__.py                     # marcador de pacote (vazio)
app/collector/__init__.py           # marcador de pacote (vazio)
app/collector/dedup.py              # dedup por sequência (corrige bug de baixos repetidos)
app/logging_config.py               # logger central, idempotente

pytest.ini                          # config do pytest (testpaths, pythonpath, etc.)
requirements-dev.txt                # deps de desenvolvimento (pytest)

tests/__init__.py
tests/conftest.py                   # fixture in_memory_db (SQLite :memory: por teste)
tests/test_analyzer.py              # 18 testes (categorize, summarize, advanced)
tests/test_backtesting.py           # 9 testes (estratégias e bordas)
tests/test_dedup.py                 # 11 testes (incluindo regressão do bug)
tests/test_manual_collector.py      # 3 testes (DB)
tests/test_volatility.py            # 5 testes (rolling std)
```

## Arquivos modificados

```
app/collector/browser.py            # usa dedup.py + logging_config; encerra gracioso
app/collector/manual.py             # valida multiplier >= 1.0
app/models.py                       # created_at timezone-aware (datetime.now(timezone.utc))
```

## Como rodar os testes

```bash
pip install -r requirements-dev.txt
pytest
```

Resultado esperado: **47 passed**.

## O que não foi tocado

Os módulos abaixo já estavam corretos e ficaram como estão:

- `app/analyzer.py`, `app/backtesting.py`, `app/config.py`,
  `app/database.py`, `app/main.py`, `app/volatility.py`
- `requirements.txt`, `.gitignore`, `README.md`

## Cobertura por módulo

| Módulo                       | Testes | Notas                                               |
|------------------------------|--------|-----------------------------------------------------|
| `app/collector/dedup.py`     | 11     | Inclui regressão do bug de valores repetidos        |
| `app/analyzer.py`            | 18     | Boundaries de categorias, summarize, scores, etc.   |
| `app/backtesting.py`         | 9      | Stop-loss, stop-gain, max_entries, all-strategies   |
| `app/collector/manual.py`    | 3      | Validação, persistência, valores repetidos          |
| `app/volatility.py`          | 5      | NaN inicial, série constante, janela default        |
| `app/collector/browser.py`   | 0      | Não testado: depende de Playwright + página real    |
| `app/main.py`                | 0      | UI Streamlit, testar via execução manual            |

Browser/UI ficaram sem teste de unidade porque ambos dependem de I/O
externo (navegador real, servidor Streamlit). A lógica miolo do
coletor ao vivo — o dedup — está coberta isoladamente em
`tests/test_dedup.py`.
