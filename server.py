import os, re, random, asyncio
from pathlib import Path
from typing import Optional, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from google.genai import errors

load_dotenv()
client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY"),
    http_options=types.HttpOptions(timeout=30_000)
)
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
RESERVA = os.getenv("GEMINI_MODEL_RESERVA", "gemini-flash-lite-latest")
BASE = Path(__file__).parent

#  REGRAS DO SISTEMA (fonte única: o front lê de /api/regras)
ATRIBUTOS = ["Força", "Agilidade", "Intelecto", "Vigor", "Presença"]
PERICIAS = {
    "Luta": "Força", 
    "Atletismo": "Força",
    "Pontaria": "Agilidade", 
    "Furtividade": "Agilidade", 
    "Reflexos": "Agilidade",
    "Investigação": "Intelecto", 
    "Medicina": "Intelecto", 
    "Ocultismo": "Intelecto",
    "Fortitude": "Vigor",
    "Percepção": "Presença", 
    "Diplomacia": "Presença", 
    "Vontade": "Presença",
}

# Regra de rolagem: atributo N => rola N d20 e fica com o MAIOR; atributo 0 => rola 2 e fica com o MENOR.
def rolar_pericia(ficha: dict, pericia: str) -> dict:
    attr = PERICIAS[pericia]
    n = ficha["attrs"][attr]
    qtd = n if n > 0 else 2
    dados = [random.randint(1, 20) for _ in range(qtd)]
    usado = max(dados) if n > 0 else min(dados)
    bonus = ficha["skills"].get(pericia, 0)
    return {"pericia": pericia, "attr": attr, "attr_val": n, "dados": dados,
            "usado": usado, "bonus": bonus, "total": usado + bonus}

DADO_RE = re.compile(r"(\d{1,2})d(\d{1,3})([+-]\d+)?")

def rolar_dano(expr: str, mult: int = 1) -> dict:
    """'1d12' ou '2d6+2'. No crítico multiplica a QUANTIDADE de dados (o bônus fixo não)."""
    m = DADO_RE.fullmatch(expr.replace(" ", ""))
    if not m:
        raise ValueError(f"Expressão de dano inválida: {expr}")
    n, faces, bonus = int(m[1]), int(m[2]), int(m[3] or 0)
    dados = [random.randint(1, faces) for _ in range(n * mult)]
    return {"expr": expr, "mult": mult, "dados": dados, "bonus": bonus, "total": sum(dados) + bonus}

def parse_critico(txt: str) -> tuple[int, int]:
    """'19/x3' -> (19, 3). Sem margem informada, crítico só no 20 com x2."""
    m = re.fullmatch(r"\s*(\d+)\s*/\s*x(\d+)\s*", txt)
    return (int(m[1]), int(m[2])) if m else (20, 2)

# =====================================================================
#  PERSONAGENS E MISSÃO (troque pelos seus)
#  armas: "pericia" é Luta (corpo a corpo) ou Pontaria (distância)
#  habilidades: "custo_pe" é validado e descontado pelo servidor

PERSONAGENS = {
    "kael": {"nome": "Kael", "classe": "Mercenário",
             "historia": "Ex-soldado que perdeu a companhia numa emboscada.",
             "attrs": {"Força": 3, "Agilidade": 2, "Intelecto": 1, "Vigor": 3, "Presença": 1},
             "skills": {"Luta": 10, "Atletismo": 5, "Fortitude": 5},
             "pv": 22, "san": 12, "pe": 6, "defesa": 12, "nex": 5,
             "armas": [
                 {"nome": "Machado de guerra", "pericia": "Luta", "dano": "1d12", "critico": "19/x3", "tipo": "Corte"},
                 {"nome": "Pistola", "pericia": "Pontaria", "dano": "1d10", "critico": "19/x2", "tipo": "Balístico"}],
             "habilidades": [
                 {"nome": "Golpe Pesado", "custo_pe": 2, "desc": "Ataque corpo a corpo com um dado de dano extra."},
                 {"nome": "Casca Grossa", "custo_pe": 1, "desc": "Reduz o dano do próximo golpe sofrido."}]},
    "lyra": {"nome": "Lyra", "classe": "Ocultista",
             "historia": "Estudiosa de rituais proibidos, procura a irmã desaparecida.",
             "attrs": {"Força": 1, "Agilidade": 2, "Intelecto": 3, "Vigor": 1, "Presença": 3},
             "skills": {"Ocultismo": 10, "Vontade": 10, "Investigação": 5},
             "pv": 12, "san": 20, "pe": 10, "defesa": 11, "nex": 10,
             "armas": [
                 {"nome": "Adaga ritual", "pericia": "Luta", "dano": "1d4", "critico": "19/x2", "tipo": "Perfuração"}],
             "habilidades": [
                 {"nome": "Ritual: Trevas", "custo_pe": 2, "desc": "Escurece a área e atrapalha quem depende de visão."},
                 {"nome": "Ritual: Amarras", "custo_pe": 3, "desc": "Prende um alvo com correntes de sombra."},
                 {"nome": "Ritual: Ver o Invisível", "custo_pe": 2, "desc": "Revela presenças ocultas por alguns minutos."}]},
    "sela": {"nome": "Sela", "classe": "Curandeira",
             "historia": "Ex-enfermeira de guerra, guiada por uma fé abalada.",
             "attrs": {"Força": 1, "Agilidade": 1, "Intelecto": 3, "Vigor": 2, "Presença": 3},
             "skills": {"Medicina": 10, "Diplomacia": 5, "Vontade": 5},
             "pv": 16, "san": 18, "pe": 8, "defesa": 11, "nex": 5,
             "armas": [
                 {"nome": "Bisturi", "pericia": "Luta", "dano": "1d4", "critico": "19/x2", "tipo": "Corte"}],
             "habilidades": [
                 {"nome": "Primeiros Socorros", "custo_pe": 1, "desc": "Estanca ferimentos e recupera PV de um aliado."},
                 {"nome": "Palavra de Consolo", "custo_pe": 2, "desc": "Acalma um aliado e recupera sanidade."}]},
}

MISSAO = """MISSÃO PRINCIPAL (só você conhece os detalhes; revele aos poucos):
Os jogadores devem chegar à Abadia de Vhal, encontrar o Códice Negro e destruí-lo
antes da lua cheia (1 dia de jogo).
SUCESSO: o Códice é destruído.
FALHA: o Códice é levado pelo Culto, ou todos os personagens morrem/fogem definitivamente."""

# =====================================================================
#  RESPOSTA ESTRUTURADA DO MESTRE (JSON garantido pelo Gemini)
# =====================================================================
class Teste(BaseModel):
    pericia: str = Field(description="Uma perícia válida do sistema.")
    dt: int = Field(description="Dificuldade: 10, 15, 20 ou 25.")
    jogador: str = Field(description="Nome do PERSONAGEM que deve rolar.")

class Efeito(BaseModel):
    alvo: str = Field(description="Nome do PERSONAGEM afetado.")
    tipo: Literal["PV", "SAN", "PE"]
    delta: int = Field(description="Negativo para perda, positivo para recuperação.")

class RespostaMestre(BaseModel):
    narracao: str = Field(description="Narração imersiva em português, no máximo 3 parágrafos, sem tags.")
    teste: Optional[Teste] = Field(default=None, description="Só quando uma ação for incerta; senão null.")
    combate: Optional[Literal["INICIO", "FIM"]] = Field(default=None, description="INICIO ou FIM de combate; senão null.")
    missao: Optional[Literal["SUCESSO", "FALHA"]] = Field(default=None, description="Só uma vez, quando a história terminar; senão null.")
    efeitos: list[Efeito] = Field(default_factory=list, description="Mudanças de PV/SAN/PE dos personagens jogadores.")

SYSTEM = """Você é o Mestre de um RPG de horror/fantasia em texto, em português.
Os jogadores são humanos; você NUNCA joga por eles nem decide o que fazem.

FORMATO: responda SEMPRE em JSON no esquema fornecido. A "narracao" é só texto para os
jogadores, sem tags e sem JSON dentro dela.

MENSAGENS QUE VOCÊ RECEBE (o servidor as gera; conversa entre jogadores não chega a você):
- [ESTADO: ...]  fichas, PV/SAN/PE atuais e situação de combate. Use-o sempre.
- AÇÃO Nome: texto   ação livre de um jogador.
- [RESULTADO] ...    rolagem de perícia já resolvida (SUCESSO ou FALHA). Não recalcule.
- [ATAQUE] ...       ataque já rolado pelo servidor, com dano pronto.
- [HABILIDADE] ...   habilidade/ritual usado; o custo em PE já foi descontado.
- [INICIO_DA_AVENTURA] e [NOVO PERSONAGEM] ...

REGRAS:
- Você NUNCA rola dados nem inventa resultados. Se uma ação for incerta, preencha "teste"
  (DT: 10 fácil, 15 médio, 20 difícil, 25 muito difícil) e pare de narrar até o resultado.
  Perícias: Luta, Atletismo, Pontaria, Furtividade, Reflexos, Investigação, Medicina,
  Ocultismo, Fortitude, Percepção, Diplomacia, Vontade.
- Em [ATAQUE], compare o total do ataque com a Defesa do alvo (você define e mantém
  coerente). Se acertar, o alvo sofre EXATAMENTE o dano informado (crítico já incluído).
  Não peça teste de ataque e não invente outro dano. Inimigos não têm barra: narre o estado deles.
- Dano, perda de sanidade ou cura em personagens jogadores vão em "efeitos" (delta negativo
  = perda), decididos por você a partir da narrativa. Nunca cobre PE de habilidade: o servidor
  já cobrou. Use PE em "efeitos" só para drenagem ou recuperação.
- Personagem com PV 0 está caído: não o faça agir.
- Combate: preencha "combate" com "INICIO" ao começar e "FIM" ao acabar. Em combate, narre só
  a ação de quem tem a vez.
- Fim: quando a missão for concluída ou falhar de forma irreversível, narre o epílogo e preencha
  "missao" com "SUCESSO" ou "FALHA", uma única vez.
- Ao receber [INICIO_DA_AVENTURA], apresente o cenário e o gancho, citando cada personagem presente.

""" + MISSAO

ACAO_RE = re.compile(r"\s*\[(.+)\]\s*", re.S)
NOME_LIVRE = re.compile(r"[^\w \-çãáéíóúâêô]")

app = FastAPI()

@app.get("/api/regras")
def regras():
    return {"atributos": ATRIBUTOS, "pericias": PERICIAS}

# =====================================================================
#  SALA
# =====================================================================
class Room:
    def __init__(self):
        self.conectados: set[WebSocket] = set()      # todos, com ou sem personagem
        self.players: dict[WebSocket, dict] = {}     # só quem já escolheu personagem
        self.status_salvo: dict[str, dict] = {}      # pid -> status (não cura saindo e voltando)
        self.iniciada = False
        self.fim: str | None = None                  # None, "SUCESSO" ou "FALHA"
        self.lock = asyncio.Lock()
        self.pendentes: dict[str, dict] = {}         # nome -> {"pericia", "dt"}
        self.combate = {"ativo": False, "ordem": [], "idx": 0}
        self.turno_ocupado = False                   # impede 2 ações no mesmo turno
        # no __init__, no lugar de self.chat = client.aio.chats.create(...)
        self.modelo = MODEL
        self.chat = self._novo_chat(MODEL)

    def _novo_chat(self, modelo, history=None):
        return client.aio.chats.create(
        model=modelo, history=history,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM,
            response_mime_type="application/json",
            response_schema=RespostaMestre))

    def alternar_modelo(self):
        self.modelo = RESERVA if self.modelo == MODEL else MODEL
        self.chat = self._novo_chat(self.modelo, self.chat.get_history())

    # ---- consultas ----
    def achar(self, nome: str | None):
        n = (nome or "").strip().casefold()
        return next((p for p in self.players.values() if p["name"].casefold() == n), None)

    def nomes(self): return [p["name"] for p in self.players.values()]
    def escolhidos(self): return {p["pid"] for p in self.players.values()}

    def da_vez(self):
        c = self.combate
        return c["ordem"][c["idx"] % len(c["ordem"])] if c["ativo"] and c["ordem"] else None

    def avancar_turno(self):
        """Passa a vez, pulando quem caiu ou saiu da sala."""
        c = self.combate
        if not c["ativo"] or not c["ordem"]: return
        for _ in range(len(c["ordem"])):
            c["idx"] = (c["idx"] + 1) % len(c["ordem"])
            p = self.achar(c["ordem"][c["idx"]])
            if p and p["status"]["pv"][0] > 0: return

    def pode_agir(self, nome: str, ignora_turno: bool = False) -> str | None:
        if self.fim: return "A aventura terminou."
        if not self.iniciada: return "Aguarde o início da aventura."
        p = self.achar(nome)
        if not p or p["status"]["pv"][0] <= 0: return "Seu personagem caiu e não pode agir."
        if self.combate["ativo"] and not ignora_turno:
            if self.da_vez() != nome: return f"Não é sua vez. Vez de {self.da_vez()}."
            if self.turno_ocupado: return "Aguarde o Mestre narrar."
        return None

    def trocar_modelo(self, modelo: str):
        hist = self.chat.get_history()
        self.chat = client.aio.chats.create(
        model=modelo, history=hist,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM,
            response_mime_type="application/json",
            response_schema=RespostaMestre))

    def contexto(self) -> str:
        linhas = "; ".join(
            f'{p["name"]} [{p["classe"]}] ' +
            ", ".join(f"{a} {v}" for a, v in p["ficha"]["attrs"].items()) +
            " | " + " ".join(f'{k.upper()} {v[0]}/{v[1]}' for k, v in p["status"].items())
            for p in self.players.values())
        est = (f"COMBATE ativo, ordem {self.combate['ordem']}, vez de {self.da_vez()}"
               if self.combate["ativo"] else "Sem combate")
        return f"[ESTADO: {linhas}. {est}]\n"

    # ---- envio ----
    async def broadcast(self, msg: dict):
        for ws in list(self.conectados):
            try: await ws.send_json(msg)
            except Exception:
                self.conectados.discard(ws); self.players.pop(ws, None)

    async def enviar_lobby(self):
        ocupados = self.escolhidos()
        await self.broadcast({"type": "lobby", "iniciada": self.iniciada, "fim": self.fim,
            "personagens": [{"id": i, "nome": p["nome"], "classe": p["classe"], "historia": p["historia"],
                             "attrs": p["attrs"], "livre": i not in ocupados}
                            for i, p in PERSONAGENS.items()]})

    async def enviar_estado(self):
        await self.broadcast({"type": "estado", "combate": self.combate, "vez": self.da_vez(),
            "players": [{"name": p["name"], "jogador": p["jogador"]} for p in self.players.values()]})

    async def enviar_status(self):
        await self.broadcast({"type": "status",
                              "status": {p["name"]: p["status"] for p in self.players.values()}})

rooms: dict[str, Room] = {}

# =====================================================================
#  MESTRE
# =====================================================================
def parse_resposta(txt: str) -> RespostaMestre | None:
    for candidato in (txt, re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.M).strip()):
        try: return RespostaMestre.model_validate_json(candidato)
        except Exception: pass
    return None

async def enviar_com_retry(room: Room, texto: str, tentativas: int = 4):
    for i in range(tentativas):
        try:
            return await room.chat.send_message(texto)
        except errors.ServerError:                      # 503 etc.
            if i == tentativas - 1: raise
            if i == 1: room.alternar_modelo() 
            await asyncio.sleep(2 ** i + random.uniform(0, 1))
        except errors.ClientError as e:
            if getattr(e, "code", None) != 429 or i == tentativas - 1:
                raise
            m = re.search(r"retry in ([\d.]+)s", str(e))
            espera = float(m[1]) + 1 if m else 20
            await room.broadcast({"type": "system",
                "text": f"O Mestre está pensando... (aguardando {espera:.0f}s)"})
            await asyncio.sleep(espera)

async def chamar_mestre(room: Room, texto: str) -> RespostaMestre:
    resp = await enviar_com_retry(room, texto)
    r = parse_resposta(resp.text or "")
    if r is None:   # uma tentativa de correção
        resp = await enviar_com_retry(room,
            "Sua resposta anterior não seguiu o esquema JSON. Reenvie o mesmo conteúdo no formato correto.")
        r = parse_resposta(resp.text or "")
    return r or RespostaMestre(narracao=(resp.text or "...").strip())

async def encerrar(room: Room, resultado: str):
    room.fim = resultado
    room.combate = {"ativo": False, "ordem": [], "idx": 0}
    room.pendentes.clear()
    await room.broadcast({"type": "fim", "resultado": resultado})
    await room.enviar_lobby()

async def aplicar_resposta(room: Room, r: RespostaMestre):
    await room.broadcast({"type": "master", "text": r.narracao.strip() or "..."})

    # 1) efeitos em PV/SAN/PE (o servidor limita entre 0 e o máximo)
    caiu, mudou = [], False
    for e in r.efeitos:
        p = room.achar(e.alvo)
        if not p: continue
        k = e.tipo.lower()
        antes, maximo = p["status"][k]
        novo = max(0, min(maximo, antes + e.delta))
        p["status"][k] = [novo, maximo]
        mudou = True
        if k == "pv" and antes > 0 and novo == 0: caiu.append(p["name"])
    if mudou: await room.enviar_status()
    for n in caiu:
        room.pendentes.pop(n, None)
        await room.broadcast({"type": "system", "text": f"☠ {n} caiu!"})

    # 2) pedido de teste (só para personagem vivo e perícia válida)
    t = r.teste
    if t:
        pericia = next((k for k in PERICIAS if k.casefold() == t.pericia.strip().casefold()), None)
        alvo = room.achar(t.jogador)
        if pericia and alvo and alvo["status"]["pv"][0] > 0:
            room.pendentes[alvo["name"]] = {"pericia": pericia, "dt": t.dt}
            await room.broadcast({"type": "teste", "alvo": alvo["name"], "pericia": pericia, "dt": t.dt})

    # 3) combate
    if r.combate == "INICIO" and not room.combate["ativo"]:
        ini = sorted(((rolar_pericia(p["ficha"], "Reflexos")["total"], p["name"])
                      for p in room.players.values() if p["status"]["pv"][0] > 0), reverse=True)
        room.combate = {"ativo": True, "ordem": [n for _, n in ini], "idx": 0}
        await room.broadcast({"type": "system", "text": "⚔ COMBATE! Iniciativa: " +
                              ", ".join(f"{n} ({t})" for t, n in ini)})
    elif r.combate == "FIM" and room.combate["ativo"]:
        room.combate = {"ativo": False, "ordem": [], "idx": 0}
        await room.broadcast({"type": "system", "text": "Combate encerrado."})

    # 4) fim da missão (decidido pelo Mestre) ou derrota total (decidida pelo servidor)
    if r.missao:
        await encerrar(room, r.missao)
    elif room.players and all(p["status"]["pv"][0] == 0 for p in room.players.values()):
        await room.broadcast({"type": "system", "text": "Todos os personagens caíram."})
        try:
            ep = await chamar_mestre(room, "[TODOS CAÍRAM] Narre o desfecho final (epílogo) da aventura.")
            await room.broadcast({"type": "master", "text": ep.narracao.strip()})
        except Exception:
            pass
        await encerrar(room, "FALHA")

async def perguntar_mestre(room: Room, texto: str, passa_turno_de: str | None = None):
    try:
        if room.fim: return
        async with room.lock:
            if room.fim: return
            estava_em_combate = room.combate["ativo"]
            await room.broadcast({"type": "typing"})
            try:
                r = await chamar_mestre(room, room.contexto() + texto)
            except errors.ServerError:
                await room.broadcast({"type": "system",
                    "text": "O Mestre está sobrecarregado no momento. Tente sua ação de novo em instantes."})
                return
            except Exception as e:
                await room.broadcast({"type": "system", "text": f"Erro do Mestre: {e}"})
                return
            await aplicar_resposta(room, r)
            if (passa_turno_de and estava_em_combate and not room.fim
                    and room.combate["ativo"] and room.da_vez() == passa_turno_de
                    and passa_turno_de not in room.pendentes):
                room.avancar_turno()
            await room.enviar_estado()
    finally:
        room.turno_ocupado = False

def disparar(room: Room, texto: str, nome: str | None = None):
    """Envia ao Mestre em segundo plano. Em combate, bloqueia nova ação até ele responder."""
    room.turno_ocupado = room.combate["ativo"]
    asyncio.create_task(perguntar_mestre(room, texto, nome))

# =====================================================================
#  WEBSOCKET
# =====================================================================
@app.websocket("/ws/{room_id}")
async def ws_endpoint(ws: WebSocket, room_id: str):
    await ws.accept()
    room = rooms.setdefault(room_id, Room())
    room.conectados.add(ws)
    nome = None
    await room.enviar_lobby()

    async def aviso(texto: str, tipo: str = "system"):
        await ws.send_json({"type": tipo, "text": texto})

    try:
        while True:
            d = await ws.receive_json()
            tipo = d.get("type")

            # ---------------- escolha do personagem ----------------
            if tipo == "escolher":
                pid = d.get("id")
                jogador = NOME_LIVRE.sub("", str(d.get("jogador", "")))[:20].strip()
                if room.fim:                       await aviso("A aventura já terminou.", "erro")
                elif ws in room.players:           await aviso("Você já escolheu um personagem.", "erro")
                elif not jogador:                  await aviso("Informe seu nome.", "erro")
                elif pid not in PERSONAGENS:       await aviso("Personagem inválido.", "erro")
                elif pid in room.escolhidos():
                    await aviso("Esse personagem já foi escolhido.", "erro")
                    await room.enviar_lobby()
                else:   # sem 'await' entre a checagem e a atribuição: sem corrida
                    p = PERSONAGENS[pid]
                    nome = p["nome"]
                    status = room.status_salvo.get(pid) or {
                        "pv": [p["pv"], p["pv"]], "san": [p["san"], p["san"]], "pe": [p["pe"], p["pe"]]}
                    room.players[ws] = {
                        "name": nome, "pid": pid, "jogador": jogador, "classe": p["classe"],
                        "ficha": {"attrs": p["attrs"], "skills": {k: p["skills"].get(k, 0) for k in PERICIAS}},
                        "status": status}
                    await ws.send_json({"type": "ficha", "nome": nome, "jogador": jogador,
                        "ficha": room.players[ws]["ficha"], "status": status,
                        "extra": {k: p[k] for k in ("classe", "defesa", "armas", "habilidades")}})
                    await room.broadcast({"type": "system", "text": f"{nome} ({jogador}) entrou na aventura."})
                    await room.enviar_lobby()
                    await room.enviar_estado()
                    await room.enviar_status()
                    if room.iniciada and not room.fim:
                        disparar(room, f"[NOVO PERSONAGEM] {nome} ({p['classe']}) juntou-se ao grupo.")
                continue

            me = room.players.get(ws)
            if not me: continue            # quem não escolheu personagem não faz mais nada
            ficha = me["ficha"]

            # ---------------- iniciar ----------------
            if tipo == "iniciar":
                if not room.iniciada and not room.fim:
                    room.iniciada = True
                    await room.enviar_lobby()
                    disparar(room, "[INICIO_DA_AVENTURA]")

            # ---------------- conversa entre jogadores (sempre liberada) ----------------
            elif tipo == "chat":
                texto = str(d.get("text", ""))[:500].strip()
                if texto:
                    await room.broadcast({"type": "chat", "name": nome, "jogador": me["jogador"], "text": texto})

            # ---------------- ação livre [entre colchetes] ----------------
            elif tipo == "acao":
                m = ACAO_RE.fullmatch(str(d.get("text", ""))[:500])
                erro = room.pode_agir(nome)
                if erro: await aviso(erro); continue
                if not m: continue
                await room.broadcast({"type": "acao", "name": nome, "jogador": me["jogador"], "text": m[1]})
                disparar(room, f"AÇÃO {nome}: {m[1]}", nome)

            # ---------------- rolagem de perícia ----------------
            elif tipo == "rolar" and d.get("pericia") in PERICIAS:
                pend = room.pendentes.get(nome)
                casa = bool(pend and pend["pericia"] == d["pericia"])
                erro = room.pode_agir(nome, ignora_turno=casa)   # teste pedido vale fora da vez
                if erro: await aviso(erro); continue
                r = rolar_pericia(ficha, d["pericia"])
                dt = pend["dt"] if casa else None
                if casa: room.pendentes.pop(nome)
                r.update({"type": "roll", "name": nome, "jogador": me["jogador"], "dt": dt,
                          "sucesso": (r["total"] >= dt) if dt is not None else None})
                await room.broadcast(r)
                veredito = "" if dt is None else f" contra DT {dt}: {'SUCESSO' if r['sucesso'] else 'FALHA'}"
                regra = "maior" if r["attr_val"] > 0 else "menor"
                disparar(room,
                    f"[RESULTADO] {nome} — {r['pericia']} ({r['attr']} {r['attr_val']}): dados {r['dados']}, "
                    f"usa o {regra} ({r['usado']}) + {r['bonus']} = {r['total']}{veredito}", nome)

            # ---------------- ataque com arma ----------------
            elif tipo == "atacar":
                armas = PERSONAGENS[me["pid"]]["armas"]
                i = d.get("arma")
                if not isinstance(i, int) or not 0 <= i < len(armas): continue
                erro = room.pode_agir(nome)
                if erro: await aviso(erro); continue
                arma = armas[i]
                alvo = str(d.get("alvo", ""))[:60].strip()
                atq = rolar_pericia(ficha, arma["pericia"])
                limite, mult = parse_critico(arma["critico"])
                critico = atq["usado"] >= limite
                dano = rolar_dano(arma["dano"], mult if critico else 1)
                await room.broadcast({**atq, "type": "ataque", "name": nome, "jogador": me["jogador"],
                                      "arma": arma["nome"], "alvo": alvo, "critico": critico, "dano": dano})
                disparar(room,
                    f"[ATAQUE] {nome} ataca {alvo or 'o inimigo à frente'} com {arma['nome']} "
                    f"({atq['pericia']}): dados {atq['dados']}, usa {atq['usado']} + {atq['bonus']} = "
                    f"{atq['total']}{' — CRÍTICO' if critico else ''}. "
                    f"Dano se acertar ({arma['tipo']}): {dano['total']}. Compare com a Defesa do alvo.", nome)

            # ---------------- habilidade / ritual ----------------
            elif tipo == "habilidade":
                habs = PERSONAGENS[me["pid"]]["habilidades"]
                i = d.get("hab")
                if not isinstance(i, int) or not 0 <= i < len(habs): continue
                erro = room.pode_agir(nome)
                if erro: await aviso(erro); continue
                hab = habs[i]
                custo = hab["custo_pe"]
                pe = me["status"]["pe"]
                if pe[0] < custo:
                    await aviso(f"PE insuficiente para {hab['nome']}: você tem {pe[0]}, precisa de {custo}.", "erro")
                    continue
                pe[0] -= custo                      # validação e desconto no servidor
                alvo = str(d.get("alvo", ""))[:60].strip()
                await room.enviar_status()
                await room.broadcast({"type": "habilidade", "name": nome, "jogador": me["jogador"],
                                      "hab": hab["nome"], "custo": custo, "alvo": alvo})
                disparar(room,
                    f"[HABILIDADE] {nome} usa {hab['nome']} ({hab['desc']}). Custo {custo} PE já descontado. "
                    f"Alvo/observação: {alvo or 'não informado'}. Narre o efeito; se exigir teste, peça.", nome)

    except WebSocketDisconnect:
        pass
    finally:
        room.conectados.discard(ws)
        p = room.players.pop(ws, None)
        if p:
            era_a_vez = room.combate["ativo"] and room.da_vez() == p["name"]
            room.status_salvo[p["pid"]] = p["status"]
            room.pendentes.pop(p["name"], None)
            if era_a_vez: room.avancar_turno()
            await room.broadcast({"type": "system", "text": f"{p['name']} saiu."})
            await room.enviar_lobby()           # personagem volta a ficar livre
            await room.enviar_estado()

app.mount("/", StaticFiles(directory=BASE / "static", html=True), name="static")