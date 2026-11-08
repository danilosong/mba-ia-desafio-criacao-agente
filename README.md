# Residencial Aurora: assistente virtual com Google ADK

API em Python para o assistente dos moradores do Residencial Aurora. O modelo conduz a conversa, e as regras críticas ficam no código, valendo independentemente do que o morador escreva.

## Arquitetura

O morador conversa com um agente principal, que distribui o trabalho entre três especialistas. Os agentes estão em `aurora/agentes.py`.

| Agente | Responsabilidade | Como é acionado | Por quê |
| --- | --- | --- | --- |
| `coordenador` | Recebe toda mensagem nova e decide quem atende. Não recebe o regulamento nas instruções. | É o `root_agent` do `App`. | Com `disallow_transfer_to_parent=True` nos especialistas, o Runner sempre volta ao coordenador em uma nova mensagem. |
| `especialista_reservas` | Lista, reserva e cancela áreas e informa se uma data está livre. | Transferência (`sub_agents`). | O pedido de confirmação precisa ficar nos eventos da sessão principal para ser persistido e retomado. |
| `especialista_visitantes` | Lista e autoriza visitantes. | Transferência (`sub_agents`). | Mesmo motivo do especialista de reservas. |
| `consultor_regulamento` | Responde dúvidas consultando um capítulo do regulamento por vez. | `AgentTool` do coordenador. | O `AgentTool` roda em uma sessão interna em memória. O capítulo fica lá, e só a resposta curta entra na sessão do morador. |

Os demais módulos:

- `aurora/api.py`: rotas FastAPI do contrato.
- `aurora/conversa.py`: Runner, sessão persistida e ciclo de vida das confirmações.
- `aurora/tools.py`: tools dos agentes.
- `aurora/banco.py`: reservas e visitantes em SQLite, em `var/condominio.db`.
- `aurora/regulamento.py`: divide `dados/regulamento.md` em capítulos.

As sessões ficam em `var/sessoes.db`, gravadas pelo `SqliteSessionService` do ADK. Nenhum dos dois bancos precisa de serviço externo.

## Garantias

### Garantia 1: cobrança ou acesso só com confirmação

Em `aurora/tools.py`, as tools são registradas com a exigência de confirmação. A decisão para reservas vem da taxa cadastrada em `dados/areas.json`:

```python
FunctionTool(reservar_area, require_confirmation=reserva_gera_cobranca)
FunctionTool(autorizar_visitante, require_confirmation=True)
```

Em `aurora/conversa.py`, `responder_confirmacao` só aceita um `id` que `_pedidos_de_confirmacao` encontre nos eventos da sessão e que ainda não esteja em `_ids_respondidos`. Qualquer outro recebe `409`.

A retomada entrega a resposta ao agente que pediu a confirmação, por meio de `_runners_de_retomada`, escolhido pelo autor do evento. Isso é necessário porque o Runner escolhe o agente antes de anexar a resposta à sessão, e o ADK ignora em silêncio uma confirmação entregue a outro agente. `_resultado_da_retomada` confere que a tool realmente rodou depois da resposta.

Quando o morador nega, `encerrar_turno_se_negada`, em `aurora/agentes.py`, encerra o turno sem chamar o modelo. Sem isso, o modelo lê a recusa como uma falha e chama a tool de novo, abrindo outra confirmação.

Não depende do modelo porque o ADK só executa a função com uma confirmação recebida como `FunctionResponse`, e a rota de mensagens só aceita texto. Escrever "já confirmei" não produz essa resposta.

### Garantia 2: cada sessão pertence a um apartamento

Em `aurora/conversa.py`, `criar_sessao` grava o apartamento uma única vez:

```python
state={"apartamento": apartamento}
```

Em `aurora/tools.py`, as tools leem esse valor em `_apartamento`, e nenhuma delas tem parâmetro de apartamento:

```python
return tool_context.state["apartamento"]
```

Em `aurora/banco.py`, `listar_reservas`, `listar_visitantes` e `cancelar_reserva` filtram por `apartamento = ?`. `verificar_disponibilidade` devolve apenas `livre` ou `ocupada`.

Não depende do modelo porque ele não tem como informar outro apartamento às tools, e nenhuma tool devolve dados de outro apartamento.

### Garantia 3: nada se perde no reinício

Em `aurora/conversa.py`, `Assistente.__init__` usa `SqliteSessionService(str(BANCO_SESSOES))`. Em `aurora/banco.py`, reservas e visitantes são gravados em SQLite. As confirmações pendentes são calculadas a partir dos eventos persistidos em `confirmacoes_pendentes`, então também sobrevivem ao reinício. `inicializar` só carrega os dados iniciais se o banco estiver vazio.

Não depende do modelo porque todo o estado está em disco, e nada fica só na memória do processo.

### Garantia 4: o regulamento é consultado, não carregado

Em `aurora/agentes.py`, o coordenador usa o consultor por `AgentTool(agent=consultor)`, e suas instruções não têm o regulamento. Em `aurora/tools.py`, `consultar_regulamento` devolve um único capítulo por assunto e respeita `LIMITE_DE_CAPITULOS_POR_TURNO`:

```python
return {"status": "ok", "capitulo": CAPITULOS[assunto]}
```

Não depende do modelo porque o texto do capítulo só existe na sessão interna do `AgentTool`, que não é gravada, e a tool não consegue devolver mais de um capítulo por chamada.

### Garantia 5: dois moradores, uma reserva

Em `aurora/banco.py`, a exclusividade é um índice único parcial do SQLite:

```sql
CREATE UNIQUE INDEX IF NOT EXISTS uma_reserva_ativa_por_area_e_data
    ON reservas (area, data) WHERE status = 'ativa';
```

`criar_reserva` usa esse índice no próprio `INSERT`, com `ON CONFLICT (area, data) WHERE status = 'ativa' DO NOTHING`. Quem perde a disputa recebe `None`, e `reservar_area` devolve uma recusa normal.

Não depende do modelo porque o banco decide no instante da gravação. Reservas canceladas continuam na tabela, e a chave primária impede repetir o código delas.

## Como rodar

Pré-requisitos: [uv](https://docs.astral.sh/uv/) e Python 3.12 ou superior (o uv instala a versão de `.python-version`, se necessário). Não há serviço externo para subir.

Variáveis do `.env`:

| Variável | Obrigatória | Descrição |
| --- | --- | --- |
| `GOOGLE_API_KEY` | Sim | Chave do Google AI Studio. |
| `GEMINI_MODEL` | Não | Modelo de todos os agentes. O padrão é `gemini-3.6-flash`. |

Instalação:

```bash
cp .env.example .env   # preencha GOOGLE_API_KEY
uv sync
```

Restaurar os dados iniciais (volta reservas e visitantes aos arquivos de `dados/` e mantém as sessões):

```bash
uv run python -m aurora.restaurar
```

Subir a API em `http://localhost:8000`:

```bash
uv run uvicorn aurora.api:app --port 8000
```
