const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

let ws, regras, ficha = null, extra = null, meuNome = "", jogadorNome = "", pendente = null;
let grupo = {};                                            // nome -> {jogador, pv}
const S = { iniciada: false, fim: null, combate: false, vez: null, pv: [1, 1], pe: [0, 0] };

const enviar = (o) => ws && ws.readyState === 1 && ws.send(JSON.stringify(o));
(async () => { regras = await (await fetch("/api/regras")).json(); })();

// ---------------------------------------------------------------- lobby
$("join").onclick = () => {
  jogadorNome = $("jogador").value.trim();
  const sala = $("room").value.trim();
  if (!sala || !jogadorNome) return;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws/${encodeURIComponent(sala)}`);
  ws.onmessage = (e) => render(JSON.parse(e.data));
  ws.onclose = () => ficha && add("system", "Conexão perdida. Recarregue a página.");
  $("entrada").hidden = true; $("escolha").hidden = false;
};
$("iniciar").onclick = () => enviar({ type: "iniciar" });

function montarCards(lista) {
  $("cards").innerHTML = lista.map((p) => `
    <div class="card ${p.livre ? "" : "ocupado"}">
      <h3>${esc(p.nome)} <small>${esc(p.classe)}</small></h3>
      <p>${esc(p.historia)}</p>
      <small>${Object.entries(p.attrs).map(([a, v]) => `${a} ${v}`).join(" · ")}</small>
      <button data-id="${p.id}" ${p.livre ? "" : "disabled"}>${p.livre ? "Escolher" : "Já escolhido"}</button>
    </div>`).join("");
  $("cards").querySelectorAll("button:not([disabled])").forEach((b) =>
    b.onclick = () => enviar({ type: "escolher", id: b.dataset.id, jogador: jogadorNome }));
}

// ---------------------------------------------------------------- ficha
// Pentágono: Agilidade no topo, depois sentido horário
// Posições em % (x, y) dentro da imagem. Agilidade no topo, depois sentido horário.
const POS = { "Agilidade": [51, 12], "Intelecto": [79, 38], "Vigor": [72, 76],
              "Presença": [29, 76], "Força": [18, 38] };

function montarPentagono(attrs) {
  $("penta").querySelectorAll(".attr").forEach((e) => e.remove());
  $("penta").insertAdjacentHTML("beforeend",
    Object.entries(POS).map(([a, [x, y]]) => `
      <div class="attr" style="left:${x}%; top:${y}%" title="${a}">
        <b>${attrs[a]}</b>
      </div>`).join(""));
}
function montarFicha(m) {
  ficha = m.ficha; extra = m.extra; meuNome = m.nome;
  $("f-nome").textContent = m.nome;
  $("f-classe").textContent = `${extra.classe} · jogador: ${m.jogador}`;
  montarPentagono(ficha.attrs);

  const treinadas = Object.entries(ficha.skills).filter(([, b]) => b > 0);
  $("pericias").innerHTML = treinadas.map(([p, b]) =>
    `<button data-p="${p}">${p}<small>${regras.pericias[p]} ${ficha.attrs[regras.pericias[p]]}d20 · +${b}</small></button>`).join("");
  $("outras").innerHTML = `<option value="">Rolar perícia destreinada…</option>` +
    Object.keys(ficha.skills).filter((p) => !ficha.skills[p]).map((p) => `<option>${p}</option>`).join("");

  $("habs").innerHTML = extra.habilidades.map((h, i) => `
    <div class="item"><b>${esc(h.nome)}</b><small>${h.custo_pe} PE</small><p>${esc(h.desc)}</p>
      <button data-hab="${i}" data-custo="${h.custo_pe}">Usar</button></div>`).join("");
  $("armas").innerHTML = extra.armas.map((a, i) => `
    <div class="item"><b>${esc(a.nome)}</b>
      <small>${esc(a.dano)} · crít. ${esc(a.critico)} · ${esc(a.tipo)} · ${esc(a.pericia)}</small>
      <button data-arma="${i}">Atacar</button></div>`).join("");
  $("defesa").innerHTML = `<div class="item"><b>${extra.defesa}</b></div>`;

  document.querySelectorAll("#pericias button").forEach((b) => b.onclick = () => rolar(b.dataset.p));
  $("outras").onchange = (e) => { if (e.target.value) rolar(e.target.value); e.target.value = ""; };
  document.querySelectorAll("[data-arma]").forEach((b) =>
    b.onclick = () => enviar({ type: "atacar", arma: +b.dataset.arma, alvo: $("alvo").value.trim() }));
  document.querySelectorAll("[data-hab]").forEach((b) =>
    b.onclick = () => enviar({ type: "habilidade", hab: +b.dataset.hab, alvo: $("alvo").value.trim() }));
  atualizarStatus(m.status);
}

function rolar(p) { enviar({ type: "rolar", pericia: p }); pendente = null; marcar(); }

function marcar() {
  let achou = false;
  document.querySelectorAll("#pericias button").forEach((b) => {
    const pedido = b.dataset.p === pendente;
    b.classList.toggle("pedido", pedido);
    achou = achou || pedido;
  });
  $("outras").classList.toggle("pedido", !!pendente && !achou);
}

function atualizarStatus(s) {
  for (const k of ["pv", "san", "pe"]) {
    const [v, max] = s[k];
    $("b-" + k).style.width = (100 * v / max) + "%";
    $("t-" + k).textContent = `${v}/${max}`;
  }
  S.pv = s.pv; S.pe = s.pe;
  atualizarBotoes();
}

// Só visual: quem decide se a ação vale é o servidor.
function atualizarBotoes() {
  const vivo = S.pv[0] > 0;
  const agir = S.iniciada && !S.fim && vivo && (!S.combate || S.vez === meuNome);
  document.querySelectorAll("[data-arma]").forEach((b) => b.disabled = !agir);
  document.querySelectorAll("[data-hab]").forEach((b) => b.disabled = !agir || S.pe[0] < +b.dataset.custo);
  document.querySelectorAll("#pericias button").forEach((b) => b.disabled = !S.iniciada || !!S.fim || !vivo);
  $("outras").disabled = !S.iniciada || !!S.fim || !vivo;
}

function desenharGrupo() {
  $("grupo").innerHTML = Object.entries(grupo).map(([n, g]) =>
    `<span class="${n === S.vez ? "vez" : ""} ${g.pv && g.pv[0] === 0 ? "caido" : ""}">` +
    `${esc(n)}(${esc(g.jogador)})${g.pv ? ` PV ${g.pv[0]}/${g.pv[1]}` : ""}</span>`).join("");
}

// ---------------------------------------------------------------- terminal
// [ação] vai para o Mestre; o resto é conversa entre jogadores
$("form").onsubmit = (e) => {
  e.preventDefault();
  const t = $("text").value.trim();
  if (!t) return;
  enviar({ type: /^\[.+\]$/s.test(t) ? "acao" : "chat", text: t });
  $("text").value = "";
};

function add(cls, html) {
  document.querySelector(".typing")?.remove();
  const d = document.createElement("div");
  d.className = "line " + cls; d.innerHTML = html;
  $("log").append(d); $("log").scrollTop = $("log").scrollHeight;
  return d;
}

const quem = (m) => `<b>&gt;&gt;${esc(m.name)}(${esc(m.jogador)})</b>`;

//troca pelo resultado real (que já veio calculado do servidor)
function mostrarRolagem(m, cabecalho, rodape) {
  const linha = add("roll", "");
  let marcado = false;
  const dados = m.dados.map((d) => {
    if (d === m.usado && !marcado) { marcado = true; return `<b>${d}</b>`; }
    return d;
  }).join(", ");
  linha.innerHTML = `${cabecalho} [${dados}] +${m.bonus} = <b class="total">${m.total}</b>${rodape}`;
  $("log").scrollTop = $("log").scrollHeight;
}

function rolagem(m) {
  const dt = m.dt == null ? "" :
    ` · DT ${m.dt}: <span class="${m.sucesso ? "ok" : "falha"}">${m.sucesso ? "SUCESSO" : "FALHA"}</span>`;
  mostrarRolagem(m, `${quem(m)} rola ${esc(m.pericia)} (${m.attr} ${m.attr_val})`, dt);
}

// clicar no inimigo preenche o campo "Alvo" usado por armas e habilidades
function desenharInimigos(lista) {
  const box = $("inimigos");
  box.hidden = !lista.length;
  box.innerHTML = lista.map((i) =>
    `<button data-nome="${esc(i.nome)}">${esc(i.nome)}<small>${esc(i.condicao)}</small></button>`).join("");
  box.querySelectorAll("button").forEach((b) => b.onclick = () => $("alvo").value = b.dataset.nome);
}

// clicar no inimigo preenche o campo "Alvo" usado por armas e habilidades
function ataqueInimigo(m) {
  let t = `<b>&gt;&gt;${esc(m.inimigo)}</b> ataca ${esc(m.alvo)} com ${esc(m.ataque)} · ` +
          `d20 ${m.d20} +${m.bonus} = <b class="total">${m.total}</b> vs Defesa ${m.defesa}`;
  if (!m.acertou) {
    t += ` · <span class="ok">ERROU</span>`;
  } else {
    const d = m.dano;
    t += (m.critico ? ` · <b class="falha">CRÍTICO!</b>` : "") +
         `<br>&nbsp;&nbsp;dano (${esc(d.expr)}${d.mult > 1 ? ` ×${d.mult}` : ""}): [${d.dados.join(", ")}]` +
         `${d.bonus ? ` ${d.bonus > 0 ? "+" : ""}${d.bonus}` : ""} = <b class="falha">${d.total}</b> ${esc(m.tipo_dano)}`;
    if (m.san) t += ` · 🧠 -${m.san.total} SAN`;
  }
  add("ataque-inimigo", t);
}

function ataque(m) {
  const d = m.dano;
  let rodape = m.critico ? ` · <b class="ok">CRÍTICO!</b>` : "";
  if (m.acertou === false) {
    rodape += ` · <span class="falha">ERROU</span>`;
  } else {
    if (m.acertou === true) rodape += ` · <span class="ok">ACERTOU</span>`;
    rodape += `<br>&nbsp;&nbsp;dano${m.acertou === null ? " se acertar" : ""} ` +
      `(${esc(d.expr)}${d.mult > 1 ? ` ×${d.mult}` : ""}): [${d.dados.join(", ")}]` +
      `${d.bonus ? ` ${d.bonus > 0 ? "+" : ""}${d.bonus}` : ""} = <b class="total">${d.total}</b>`;
  }
  mostrarRolagem(m,
    `${quem(m)} ataca${m.alvo ? " " + esc(m.alvo) : ""} com ${esc(m.arma)} · ${esc(m.pericia)} (${m.attr} ${m.attr_val})`,
    rodape);
}

function render(m) {
  switch (m.type) {
      case "inimigos":       desenharInimigos(m.inimigos); break;
      case "ataque_inimigo": ataqueInimigo(m); break;
      case "lobby":
      if (!ficha) montarCards(m.personagens);
      S.iniciada = m.iniciada; S.fim = m.fim;
      $("iniciar").hidden = m.iniciada || !ficha || !!m.fim;
      atualizarBotoes();
      break;
    case "ficha":
      $("lobby").hidden = true; $("game").hidden = false;
      montarFicha(m);
      break;
    case "estado": {
      const novo = {};
      m.players.forEach((p) => novo[p.name] = { jogador: p.jogador, pv: (grupo[p.name] || {}).pv });
      grupo = novo;
      S.combate = m.combate.ativo; S.vez = m.vez;
      desenharGrupo(); atualizarBotoes();
      break;
    }
    case "status":
      for (const [n, s] of Object.entries(m.status)) {
        grupo[n] = grupo[n] || { jogador: "" };
        grupo[n].pv = s.pv;
      }
      if (m.status[meuNome]) atualizarStatus(m.status[meuNome]);
      desenharGrupo();
      break;
    case "master": add("master", `<b>&gt;&gt;Mestre(Gemini):</b> ${esc(m.text).replace(/\n/g, "<br>")}`); break;
    case "acao":   add("acao", `${quem(m)}: [${esc(m.text)}]`); break;
    case "chat":   add("chat", `${quem(m)}: ${esc(m.text)}`); break;
    case "system": add("system", esc(m.text)); break;
    case "erro":   ficha ? add("system erro", esc(m.text)) : alert(m.text); break;
    case "typing": add("system typing", "&gt;&gt;Mestre(Gemini): escrevendo…"); break;
    case "roll":   rolagem(m); break;
    case "ataque": ataque(m); break;
    case "habilidade":
      add("acao", `${quem(m)} usa <b>${esc(m.hab)}</b> (${m.custo} PE)${m.alvo ? " · " + esc(m.alvo) : ""}`);
      break;
    case "teste":
      add("system", `Teste de <b>${esc(m.pericia)}</b> (DT ${m.dt}) para ${esc(m.alvo)}`);
      if (m.alvo === meuNome) { pendente = m.pericia; marcar(); }
      break;
    case "fim":
      $("banner").hidden = false;
      $("banner").className = m.resultado === "SUCESSO" ? "ganhou" : "perdeu";
      $("banner").textContent = m.resultado === "SUCESSO" ? "MISSÃO CUMPRIDA" : "MISSÃO FALHOU";
      S.fim = m.resultado; atualizarBotoes();
      break;
  }
}