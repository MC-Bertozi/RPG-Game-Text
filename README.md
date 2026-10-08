# RPG-IA — Mestre de RPG de Texto Multiplayer com Gemini
```Projeto feito com auxílio da Claude AI ```

Projeto de Laboratório de Redes: um RPG de horror/fantasia em texto, multijogador e em tempo real, em que o **Mestre é uma IA (Google Gemini)**. Os jogadores se conectam a uma sala via **WebSocket**, escolhem personagens e jogam uma aventura narrada pela IA, enquanto o servidor cuida de todas as regras (rolagens, dano, custos, turnos, criaturas e outros).

## Visão geral

- **Comunicação em tempo real:** cliente e servidor trocam mensagens JSON por WebSocket (`/ws/{room_id}`).
- **Salas:** cada código de sala é uma partida independente, com o próprio histórico de conversa com o Gemini em que os jogadores não podem jogar com o mesmo personagem.
- **Mestre com IA:** o Gemini narra a história e responde em JSON estruturado (esquema validado com Pydantic): narração, pedidos de teste, início/fim de combate, efeitos em PV/SAN/PE e desfecho da missão.
- **Servidor autoritativo:** a IA **nunca rola dados**. Rolagens de perícia, ataques, dano, crítico, iniciativa e custo de PE são calculados no servidor e só o resultado é enviado ao Mestre.
- **Resiliência:** tratamento de erros como o erro 503 em que ele tenta novamente caso falhe, espera automática em erros 429 (rate limit) e troca para um modelo reserva se o principal falhar ou não estiver disponível.

## Arquitetura

```
 Navegador (HTML/CSS/JS)  <──── WebSocket (JSON) ────>  FastAPI (server.py)  <── HTTPS ──>  API Gemini
        │                                                    │
        └── GET /api/regras (atributos e perícias)           └── Estado das salas em memória
```

| Arquivo | Função |
|---|---|
| `server.py` | Servidor FastAPI: regras do sistema, personagens, sala, WebSocket e integração com o Gemini |
| `static/index.html` | Interface (lobby + ficha + terminal) |
| `static/app.js` | Lógica do cliente: WebSocket, renderização da ficha, log e botões |
| `static/style.css` | Estilo (tema escuro, layout dividido) |
| `static/img/pentagrama_ordem.png` | Imagem do pentágono de atributos |
| `requisitos.txt` | Dependências Python |
| `.env` | Variáveis de ambiente (não versionar) - Chave da API e seus modelos |

## Requisitos

- Python **3.10+**
- Uma chave de API do Gemini ([Google AI Studio](https://aistudio.google.com/apikey))
- Navegador moderno (Chrome, Firefox, Edge, etc)

## Instalação

```bash
# 1. (opcional) crie um ambiente virtual
python -m venv venv
source venv/bin/activate        # Linux/macOS
venv\Scripts\activate           # Windows

# 2. instale as dependências
pip install -r requisitos.txt
```

## Configuração

Crie um arquivo `.env` na raiz do projeto (mesma pasta do `server.py`):

```env
GEMINI_API_KEY=sua_chave_aqui
GEMINI_MODEL=gemini-3.5-flash-lite
GEMINI_MODEL_RESERVA=gemini-flash-lite-latest
```

| Variável | Obrigatória | Descrição |
|---|---|---|
| `GEMINI_API_KEY` | Sim | Chave da API do Gemini |
| `GEMINI_MODEL` | Não | Modelo principal |
| `GEMINI_MODEL_RESERVA` | Não | Modelo usado quando o principal está sobrecarregado  |

## Executando o servidor

```bash
uvicorn server:app --host 0.0.0.0 --port 8000
```

- `--host 0.0.0.0` faz o servidor escutar em **todas as interfaces de rede**, permitindo que outras máquinas da rede acessem o jogo.
- `--port 8000` define a porta.

Acesse no navegador:

- Na própria máquina: `http://localhost:8000`
- De outra máquina na mesma rede: `http://<SEU_IP>:8000`

## Como jogar

1. Cada jogador abre a página, informa **seu nome** e o **código da sala** (todos do mesmo grupo usam o mesmo código) e clica em **Entrar na sala**.
2. Cada jogador escolhe um personagem livre (Kael, Lyra ou Sela).
3. Qualquer jogador pode clicar em **Iniciar aventura**; o Mestre apresenta o cenário.
4. No terminal:
   - Texto normal = **conversa entre jogadores** (não vai ao Mestre).
   - Texto **entre colchetes** = **ação** enviada ao Mestre. Ex.: `[abro a porta devagar]`
5. Use os botões da ficha para **rolar perícias**, **atacar** e **usar habilidades/rituais**. O campo *Alvo* é opcional. (E que ainda será tratado)
6. Quando o Mestre pedir um teste, a perícia correspondente pisca em neon na ficha.
7. Em combate, só o jogador da vez pode agir; a iniciativa é rolada automaticamente (Reflexos).

### Personagens

| Personagem | Classe | Destaques |
|---|---|---|
| Kael | Mercenário | Alto PV, combate corpo a corpo e à distância |
| Lyra | Ocultista | Alta sanidade e PE, rituais |
| Sela | Curandeira | Cura e suporte |

### Regras de rolagem (Baseado no sistema de RPG de Ordem Paranormal)

- Atributo **N > 0**: rola **N d20** e fica com o **maior**.
- Atributo **0**: rola **2d20** e fica com o **menor**.
- Total = resultado do dado usado + bônus da perícia.
- Crítico: se o dado usado ≥ margem da arma, a **quantidade de dados** de dano é multiplicada (o bônus fixo não).
- PV, SAN e PE são sempre limitados entre 0 e o máximo. PV 0 = personagem caído.

### Fim da aventura

- **Sucesso:** o Códice Negro é destruído.
- **Falha:** o Códice é levado pelo Culto, ou todos os personagens caem/fogem.

## Protocolo WebSocket

Endpoint: `ws://<host>:8000/ws/{room_id}`

**Cliente → Servidor**

| `type` | Campos | Descrição |
|---|---|---|
| `escolher` | `id`, `jogador` | Escolhe um personagem |
| `iniciar` | — | Inicia a aventura |
| `chat` | `text` | Conversa entre jogadores |
| `acao` | `text` (entre `[ ]`) | Ação livre para o Mestre |
| `rolar` | `pericia` | Rolagem de perícia |
| `atacar` | `arma` (índice), `alvo` | Ataque com arma |
| `habilidade` | `hab` (índice), `alvo` | Uso de habilidade/ritual |

**Servidor → Cliente**

`lobby`, `ficha`, `estado`, `status`, `master`, `acao`, `chat`, `system`, `erro`, `typing`, `roll`, `ataque`, `habilidade`, `teste`, `fim`.

## Solução de problemas (Deu trabalho...)

| Problema | Possível causa / solução |
|---|---|
| "Erro do Mestre" no log | Verifique `GEMINI_API_KEY` e o nome do modelo no `.env` |
| "O Mestre está sobrecarregado" | Erro 503 do Gemini; tente a ação novamente (o servidor já alterna para o modelo reserva) |
| "Aguardando Ns" | Limite de requisições (429) do plano gratuito; o servidor espera e tenta de novo |
| Outros PCs não conectam | Confirme `--host 0.0.0.0`, o IP correto e a liberação da porta 8000 no firewall |
| "Conexão perdida" | Recarregue a página; o personagem volta a ficar livre e o status (PV/SAN/PE) é preservado na sala |

## Observações

- O estado das salas fica **apenas em memória**: reiniciar o servidor apaga todas as partidas.
- O servidor foi pensado para uso em rede local; não há autenticação nem HTTPS por padrão.

## Tecnologias

Python · FastAPI · Uvicorn · WebSocket · Pydantic · Google Gemini (`google-genai`) · HTML/CSS/JavaScript
