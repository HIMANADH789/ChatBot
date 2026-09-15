(() => {
  (function() {
    let s = document.currentScript;
    if (!s) return;

    // Attributes
    let y = s.getAttribute("data-client-id") || "default",
        d = s.getAttribute("data-theme-color") || "#1E40AF",
        w = s.getAttribute("data-api-url") || (s.src ? s.src.split("/api/clients/")[0] : ""),
        T = s.getAttribute("data-token") || "";

    // Container and Shadow DOM
    let g = document.createElement("div");
    g.id = "ai-frontdesk-widget";
    document.body.appendChild(g);
    let p = g.attachShadow({ mode: "closed" });

    // Styles
    let v = document.createElement("style");
    v.textContent = `
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }

    .widget-btn {
      position: fixed; bottom: 32px; right: 32px; width: 72px; height: 72px;
      border-radius: 24px 24px 24px 48px;
      background: linear-gradient(135deg, ${d} 60%, #38bdf8 100%);
      color: #fff; border: none;
      cursor: pointer; box-shadow: 0 8px 32px rgba(56,189,248,0.18), 0 2px 8px rgba(0,0,0,0.10);
      z-index: 99999;
      display: flex; flex-direction: column; align-items: flex-start; justify-content: flex-end;
      transition: box-shadow 0.2s, transform 0.2s;
      padding: 0;
      overflow: visible;
    }
    .widget-btn:hover {
      box-shadow: 0 12px 40px rgba(56,189,248,0.28), 0 4px 16px rgba(0,0,0,0.12);
      transform: scale(1.07);
    }
    .widget-btn .robo {
      width: 44px; height: 44px; margin: 8px 0 0 14px;
      background: #fff; border-radius: 50%; display: flex; align-items: center; justify-content: center;
      box-shadow: 0 2px 8px rgba(56,189,248,0.10);
      font-size: 28px;
      border: 2px solid #bae6fd;
    }
    .widget-btn .card {
      position: absolute; left: -220px; bottom: 0;
      width: 200px; background: #fff; color: #0ea5e9;
      border-radius: 18px 18px 18px 32px;
      box-shadow: 0 4px 24px rgba(56,189,248,0.13);
      padding: 18px 18px 18px 28px;
      font-size: 1.08rem;
      font-weight: 600;
      display: flex; flex-direction: column; align-items: flex-start;
      gap: 6px;
      border-left: 4px solid #38bdf8;
      animation: card-pop 0.7s cubic-bezier(.7,-0.2,.3,1.4);
    }
    .widget-btn .card .quote {
      font-size: 0.93rem; font-weight: 400; color: #2563eb; margin-top: 4px;
    }
    @keyframes card-pop {
      0% { opacity: 0; transform: translateY(30px) scale(0.9); }
      100% { opacity: 1; transform: translateY(0) scale(1); }
    }

    .chat-panel {
      position: fixed; bottom: 120px; right: 32px; width: 420px; height: 600px;
      border-radius: 24px 24px 24px 36px;
      background: #f8fafc; box-shadow: 0 12px 40px rgba(56,189,248,0.18), 0 4px 16px rgba(0,0,0,0.10);
      display: none; flex-direction: column; overflow: hidden; z-index: 99998;
      border: 1.5px solid #bae6fd;
    }
    .chat-panel.open { display: flex; }

    .chat-header {
      padding: 22px 28px; background: linear-gradient(90deg, ${d} 70%, #38bdf8 100%);
      color: #fff;
      display: flex; align-items: center; justify-content: space-between;
      border-bottom: 1.5px solid #bae6fd;
    }
    .chat-header h3 { font-size: 20px; font-weight: 700; display: flex; align-items: center; gap: 8px; }
    .chat-header .robo { font-size: 22px; background: #fff; color: #38bdf8; border-radius: 50%; padding: 2px 7px; border: 2px solid #bae6fd; }
    .chat-header button { background: none; border: none; color: #fff; cursor: pointer; font-size: 22px; }

    .chat-messages { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 12px; }

    .msg { max-width: 80%; padding: 10px 14px; border-radius: 14px; font-size: 14px; line-height: 1.5; word-wrap: break-word; white-space: pre-wrap; }
    .msg.user { align-self: flex-end; background: ${d}; color: #fff; border-bottom-right-radius: 4px; }
    .msg.bot { align-self: flex-start; background: #f1f5f9; color: #1e293b; border-bottom-left-radius: 4px; }

    .cursor { display: inline-block; width: 2px; height: 14px; background: #64748b; margin-left: 2px; vertical-align: middle; animation: blink 0.8s step-end infinite; }
    @keyframes blink { 0%,100% { opacity:1; } 50% { opacity:0; } }

    .chat-input { padding: 12px 16px; border-top: 1px solid #e2e8f0; display: flex; gap: 8px; }
    .chat-input input { flex: 1; border: 1px solid #e2e8f0; border-radius: 10px; padding: 10px 14px; font-size: 14px; outline: none; }
    .chat-input input:focus { border-color: ${d}; }
    .chat-input button { background: ${d}; color: #fff; border: none; border-radius: 10px; padding: 10px 16px; cursor: pointer; font-size: 14px; font-weight: 500; }
    .chat-input button:disabled { opacity: 0.5; }

    .typing { display: flex; gap: 4px; padding: 10px 14px; }
    .typing span { width: 8px; height: 8px; border-radius: 50%; background: #94a3b8; animation: bounce 1.4s infinite both; }
    .typing span:nth-child(2) { animation-delay: 0.16s; }
    .typing span:nth-child(3) { animation-delay: 0.32s; }
    @keyframes bounce { 0%,80%,100% { transform: scale(0); } 40% { transform: scale(1); } }

    .quick-replies {
      display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px;
    }
    .quick-reply-btn {
      background: #e0f2fe; color: #0284c7; border: 1px solid #bae6fd;
      padding: 6px 12px; border-radius: 12px; font-size: 13px;
      cursor: pointer; transition: background 0.2s;
    }
    .quick-reply-btn:hover { background: #bae6fd; }
    .submenu-chip {
      background: #eff6ff; color: #1d4ed8; border-color: #93c5fd;
      font-weight: 600;
    }
    .submenu-chip:hover { background: #dbeafe; }
    .menu-option-btn {
      background: #fff; color: ${d}; border: 1.5px solid ${d};
      padding: 9px 16px; border-radius: 14px; font-size: 13px; font-weight: 600;
      cursor: pointer; transition: background 0.18s, color 0.18s;
      box-shadow: 0 2px 8px rgba(0,0,0,0.06);
    }
    .menu-option-btn:hover { background: ${d}; color: #fff; }

    @media (max-width: 480px) { .chat-panel { width: calc(100vw - 32px); right: 16px; bottom: 88px; height: 70vh; } }
  `;
    p.appendChild(v);

    let r = false, E, b = false;
    const welcomeCard = `
      <span class="robo" title="AI Robo">🤖</span>
      <span class="card">
        Need Help?<br/>
        <span class="quote">"Ask me anything!"</span>
      </span>
    `;

    // Widget Button
    let l = document.createElement("button");
    l.type = "button";
    l.className = "widget-btn";
    l.innerHTML = welcomeCard;

    l.onclick = () => {
      r = !r;
      o.classList.toggle("open", r);
      if (r) {
        l.innerHTML = `<span class="robo" title="AI Robo">🤖</span>`;
        u && u.focus();
      } else {
        l.innerHTML = welcomeCard;
      }
    };
    p.appendChild(l);

    // Chat Panel
    let o = document.createElement("div");
    o.className = "chat-panel";
    o.innerHTML = `
    <div class="chat-header">
      <div style="display:flex; align-items:center; gap:8px;">
        <span class="robo">🤖</span>
        <h3>AI Front Desk</h3>
      </div>
      <button class="close-btn">\u2715</button>
    </div>
    <div class="chat-messages"></div>
    <form class="chat-input">
      <input type="text" placeholder="Type a message..." />
      <button type="submit">Send</button>
    </form>
  `;
    p.appendChild(o);

    let a = o.querySelector(".chat-messages"),
        u = o.querySelector(".chat-input input"),
        M = o.querySelector(".chat-input"),
        k = o.querySelector(".chat-input button"),
        S = o.querySelector(".close-btn");

    S.onclick = (e) => {
      e.stopPropagation();
      r = false;
      o.classList.remove("open");
      l.innerHTML = welcomeCard;
    };

    function linkify(text) {
      let urlRegex = /(https?:\/\/[^\s<]+)/g;
      return text.replace(urlRegex, '<a href="$1" target="_blank" style="color: #0ea5e9; text-decoration: underline;">$1</a>');
    }

    function f(type, text) {
      let t = document.createElement("div");
      t.className = `msg ${type}`;
      t.textContent = text;
      t.innerHTML = linkify(t.innerHTML);
      a.appendChild(t);
      a.scrollTop = a.scrollHeight;
      return t;
    }

    function C() {
      let e = document.createElement("div");
      e.className = "msg bot typing";
      e.innerHTML = "<span></span><span></span><span></span>";
      e.id = "typing-indicator";
      a.appendChild(e);
      a.scrollTop = a.scrollHeight;
      return e;
    }

    function $() {
      let e = p.getElementById("typing-indicator");
      if (e) e.remove();
    }

    async function N(e) {
      let n = C();
      let t = null, i = null;
      try {
        let c = await fetch(`${w}/api/chat/${y}/stream`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...(T ? { "X-Widget-Token": T } : {}) },
          body: JSON.stringify({ message: e, session_id: E })
        });

        if (!c.ok || !c.body) throw new Error(`Stream failed: ${c.status}`);

        let m = c.body.getReader(), B = new TextDecoder(), x = "";
        while (true) {
          let { done: done, value: value } = await m.read();
          if (done) break;
          x += B.decode(value, { stream: true });
          let H = x.split("\n\n");
          x = H.pop() ?? "";
          for (let A of H) {
            let L = A.trim();
            if (L.startsWith("data: ")) {
              try {
                let h = JSON.parse(L.slice(6));
                if (h.type === "token") {
                  if (!t) {
                    $();
                    t = document.createElement("div");
                    t.className = "msg bot";
                    i = document.createElement("span");
                    i.className = "cursor";
                    a.appendChild(t);
                    t.appendChild(i);
                  }
                  if (h.text) {
                    t.insertBefore(document.createTextNode(h.text), i);
                    a.scrollTop = a.scrollHeight;
                  }
                } else if (h.type === "done") {
                  if (h.session_id) E = h.session_id;
                  if (i) i.remove();
                  if (t) t.innerHTML = linkify(t.innerHTML);

                  if (h.context_images && h.context_images.length > 0) {
                    h.context_images.forEach(img => {
                      let imgContainer = document.createElement("div");
                      imgContainer.style.marginTop = "8px";
                      imgContainer.style.marginBottom = "4px";
                      
                      let imageEl = document.createElement("img");
                      let src = img.image_path || "";
                      if (src.includes("drive.google.com/file/d/")) {
                        let fileId = src.split("/file/d/")[1].split("/")[0];
                        src = `https://lh3.googleusercontent.com/d/${fileId}`;
                      }
                      imageEl.src = src;
                      imageEl.alt = img.title || img.caption || "Image";
                      imageEl.style.maxWidth = "100%";
                      imageEl.style.maxHeight = "220px";
                      imageEl.style.objectFit = "cover";
                      imageEl.style.borderRadius = "12px";
                      imageEl.style.boxShadow = "0 4px 12px rgba(0,0,0,0.12)";
                      imageEl.style.display = "block";

                      imgContainer.appendChild(imageEl);
                      if (img.caption || img.title) {
                        let cap = document.createElement("div");
                        cap.textContent = img.caption || img.title;
                        cap.style.fontSize = "12px";
                        cap.style.color = "#64748b";
                        cap.style.marginTop = "4px";
                        cap.style.fontStyle = "italic";
                        imgContainer.appendChild(cap);
                      }
                      if (t) {
                        t.appendChild(imgContainer);
                      } else {
                        let botMsg = f("bot", "");
                        botMsg.appendChild(imgContainer);
                      }
                    });
                    a.scrollTop = a.scrollHeight;
                  }

                  let subOpts = (h.interactive_menu && h.interactive_menu.children) ? h.interactive_menu.children : [];
                  if (subOpts.length > 0) {
                    let optMsg = f("bot", "Options for " + (h.interactive_menu.label || "this topic") + ":");
                    let qr = document.createElement("div");
                    qr.className = "quick-replies";
                    subOpts.forEach(c => {
                      let qb = document.createElement("button");
                      qb.type = "button";
                      qb.className = "quick-reply-btn";
                      qb.textContent = c.label;
                      qb.onclick = () => sendMsg(c.action_question || c.label);
                      qr.appendChild(qb);
                    });
                    optMsg.appendChild(qr);
                    a.scrollTop = a.scrollHeight;
                  }
                } else if (h.type === "error") {
                  $(); if (i) i.remove();
                  f("bot", h.content || "Error generating response.");
                }
              } catch (err) {}
            }
          }
        }
        if (i) i.remove();
      } catch (err) {
        $();
        f("bot", "Sorry, something went wrong. Please try again.");
      }
    }

    async function sendMsg(text) {
      if (!text || b) return;
      f("user", text);
      b = true;
      k.disabled = true;
      await N(text);
      b = false;
      k.disabled = false;
      u.focus();
    }

    M.onsubmit = e => {
      e.preventDefault();
      let n = u.value.trim();
      u.value = "";
      sendMsg(n);
    };

    function renderSubQuestions(subQuestions) {
      let qr = document.createElement("div");
      qr.className = "quick-replies";
      subQuestions.forEach(q => {
        if (!q || !q.trim()) return;
        let qb = document.createElement("button");
        qb.type = "button";
        qb.className = "quick-reply-btn";
        qb.textContent = q;
        qb.onclick = () => sendMsg(q);
        qr.appendChild(qb);
      });
      return qr;
    }

    function renderSubmenuChips(submenus) {
      let msg = f("bot", "Choose a topic:");
      let chips = document.createElement("div");
      chips.className = "quick-replies";
      submenus.forEach(sm => {
        if (!sm.label) return;
        let chip = document.createElement("button");
        chip.type = "button";
        chip.className = "quick-reply-btn submenu-chip";
        chip.textContent = sm.label;
        chip.onclick = () => {
          // Disable all sibling chips to lock selection
          chips.querySelectorAll("button").forEach(b => { b.disabled = true; b.style.opacity = "0.5"; });
          chip.style.opacity = "1";
          chip.style.fontWeight = "700";
          // Show sub-questions
          if (sm.sub_questions && sm.sub_questions.length > 0) {
            let qMsg = f("bot", "Questions about \"" + sm.label + "\":");
            qMsg.appendChild(renderSubQuestions(sm.sub_questions));
            a.scrollTop = a.scrollHeight;
          }
        };
        chips.appendChild(chip);
      });
      msg.appendChild(chips);
      a.scrollTop = a.scrollHeight;
    }

    function renderMenuOptions(menuOptions) {
      if (!menuOptions || menuOptions.length === 0) return;
      // Render menu options as chips inside the chat
      let msg = f("bot", "How can I help you? Choose a topic:");
      let chips = document.createElement("div");
      chips.className = "quick-replies";
      chips.style.marginTop = "10px";
      menuOptions.forEach(menu => {
        if (!menu.label) return;
        let btn = document.createElement("button");
        btn.type = "button";
        btn.className = "menu-option-btn";
        btn.textContent = menu.label;
        btn.onclick = () => {
          // Lock menu chips
          chips.querySelectorAll("button").forEach(b => { b.disabled = true; b.style.opacity = "0.5"; });
          btn.style.opacity = "1";
          let submenus = menu.submenus || [];
          if (submenus.length > 0) {
            renderSubmenuChips(submenus);
          }
        };
        chips.appendChild(btn);
      });
      msg.appendChild(chips);
      a.scrollTop = a.scrollHeight;
    }

    // Initial Welcome Message
    fetch(`${w}/api/clients/${y}`)
      .then(res => res.json())
      .then(data => {
        f("bot", data?.settings?.welcome_message || "Hello! How can I help you today?");
        if (data?.settings?.chatbot_title) {
          let titleEl = o.querySelector("h3");
          if (titleEl) titleEl.textContent = data.settings.chatbot_title;
        }
        if (data?.settings?.menu_options) {
          renderMenuOptions(data.settings.menu_options);
        }
      })
      .catch(() => f("bot", "Hello! How can I help you today?"));
  })();
})();
