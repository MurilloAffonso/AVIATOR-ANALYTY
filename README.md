# aviator-analyzer

Projeto inicial em Python para análise estatística local de resultados do jogo Aviator.

## Objetivo

Construir um painel local com foco em:

- histórico de multiplicadores;
- volatilidade;
- sequências;
- simulação de estratégias;
- backtesting.

> Este sistema não promete previsão garantida e não inclui automação de apostas.

## Estrutura

```text
app/
  collector/
data/
tests/
```

## Instalação

```bash
pip install -r requirements.txt
```

## Execução

```bash
streamlit run app/main.py
```

## Coleta ao vivo (Playwright, somente leitura)

- O botão **"Iniciar coleta ao vivo"** abre um navegador visível.
- O login é manual, quando necessário.
- O coletor apenas lê multiplicadores visíveis na tela e salva novos valores sem duplicar no SQLite.
- O sistema registra logs no terminal.
- Nunca executa aposta, cashout ou qualquer ação financeira.

## Análise avançada incluída

- detecção de sequência de baixos consecutivos;
- intervalo médio entre resultados acima de 10x;
- intervalo médio entre resultados acima de 50x;
- volatilidade das últimas 20, 50 e 100 rodadas;
- alerta de concentração anormal de baixos;
- alerta de subida de variância recente;
- score de risco (0 a 100);
- score de oportunidade estatística (0 a 100), sem promessa de previsão.

## Backtesting (simulado, sem aposta real)

Estratégias incluídas:
1. entrada fixa com cashout em 1.5x
2. entrada fixa com cashout em 2x
3. entrada após N rodadas abaixo de 1.5x
4. entrada após N rodadas abaixo de 2x
5. estratégia conservadora com stop loss e stop gain

Configurações do usuário:
- banca inicial
- valor por entrada
- cashout alvo
- stop loss
- stop gain
- número máximo de entradas

Saídas exibidas:
- lucro/prejuízo
- drawdown máximo
- taxa de acerto
- ROI
- gráfico da evolução da banca
