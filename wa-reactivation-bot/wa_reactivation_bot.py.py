import re
import time
import random
import csv
import os
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ================= CONFIG =================
PAUSE_FILE    = "pause.flag"
LOG_FILE      = "cutucada.log"
SENT_FILE     = "enviados.csv"
DIAS_RECENTES = 10
PRODUTO       = "filtros para linha pesada"
LIMITE_DIA    = 15
APROVED_FILE  = "aprovados.csv"
# ==========================================

MENSAGENS = [
    "Fala, {nome}! Passando só pra ver como você está. "
    "A gente chegou a falar sobre {produto} um tempo atrás e queria saber "
    "se isso ainda faz sentido pra você ou se acabou ficando pra depois?",

    "Oi, {nome}! Te chamo rapidinho porque fiquei com um registro seu aqui "
    "sobre {produto}. Isso ainda está no seu plano ou você acabou deixando pra depois?",

    "Fala, {nome}! Dei uma olhada aqui e lembrei de você sobre {produto}. "
    "Te pergunto porque tivemos algumas atualizações recentes e alguns clientes "
    "antigos voltaram a me procurar nisso. Faz sentido pra você ainda ou não é mais prioridade?",

    "Oi, {nome}! Tudo certo? Só me diz uma coisa rapidinho: você ainda tem "
    "interesse em {produto} ou posso encerrar seu contato por aqui?",
]

SEL_INPUT = (
    "div[contenteditable='true'][data-tab='10'],"
    "div[contenteditable='true'][data-tab='1'],"
    "footer div[contenteditable='true']"
)
SEL_SEND_BTN = (
    "button[data-testid='send'],"
    "span[data-icon='send'],"
    "button[aria-label='Enviar'],"
    "button[aria-label='Send']"
)

IGNORAR_NOMES = {"arquivadas", "archived", "status", "recentes", "todas"}


# ── Logging ────────────────────────────────────────────────────────────────
def log(msg: str):
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def pausar():
    while os.path.exists(PAUSE_FILE):
        log("⏸  PAUSADO — remova pause.flag para continuar...")
        time.sleep(3)


# ── Memória CSV ────────────────────────────────────────────────────────────
def ja_enviado(nome: str) -> bool:
    if not os.path.exists(SENT_FILE):
        return False
    with open(SENT_FILE, newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if row and row[0].strip().lower() == nome.strip().lower():
                return True
    return False


def registrar(nome: str, resultado: str):
    with open(SENT_FILE, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([nome, resultado, datetime.now().strftime("%Y-%m-%d %H:%M")])


# ── Parsing timestamp ──────────────────────────────────────────────────────
def dias_atras(time_str: str) -> int:
    if not time_str:
        return -1
    s = time_str.strip().lower()
    if re.match(r"^\d{1,2}:\d{2}$", s) or s in ("agora", "just now", "now"):
        return 0
    if s in ("ontem", "yesterday"):
        return 1
    hoje = datetime.now().weekday()
    mapa = {
        "seg": 0, "mon": 0, "ter": 1, "tue": 1,
        "qua": 2, "wed": 2, "qui": 3, "thu": 3,
        "sex": 4, "fri": 4, "sáb": 5, "sab": 5,
        "sat": 5, "dom": 6, "sun": 6,
    }
    for key, val in mapa.items():
        if s.startswith(key):
            diff = (hoje - val) % 7
            return diff if diff > 0 else 7
    m = re.match(r"^(\d{2})/(\d{2})/(\d{2,4})$", s)
    if m:
        dia, mes, ano = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if ano < 100:
            ano += 2000
        try:
            return (datetime.now() - datetime(ano, mes, dia)).days
        except ValueError:
            return -1
    return -1


# ── FASE 1: coleta lista completa ─────────────────────────────────────────
def coletar_todos_chats(page) -> list[dict]:
    log("Coletando lista de contatos (scroll completo)...")
    page.evaluate("const p = document.querySelector('#pane-side'); if(p) p.scrollTop = 0;")
    time.sleep(1)

    chats = []
    vistos = set()
    sem_novos = 0

    while sem_novos < 5:
        items = page.query_selector_all('div[data-testid="cell-frame-container"]')
        novos = 0
        for item in items:
            try:
                name_el = item.query_selector(
                    'div[data-testid="cell-frame-title"],'
                    'span[data-testid="cell-frame-title"]'
                )
                if not name_el:
                    continue
                nome = name_el.inner_text().strip()
                if not nome or nome in vistos:
                    continue
                time_el = (
                    item.query_selector('div[data-testid="cell-frame-primary-detail"] span') or
                    item.query_selector('span[data-testid="cell-frame-time"]')
                )
                time_str = time_el.inner_text().strip() if time_el else ""
                is_group = bool(item.query_selector('span[data-icon="default-group"]'))
                vistos.add(nome)
                chats.append({"nome": nome, "time_str": time_str, "is_group": is_group})
                novos += 1
            except Exception:
                continue

        sem_novos = 0 if novos > 0 else sem_novos + 1
        page.evaluate("const p = document.querySelector('#pane-side'); if(p) p.scrollTop += 800;")
        time.sleep(0.4)

    log(f"  {len(chats)} chats coletados.")
    return chats


# ── Abre chat pelo nome (scroll na lista) ─────────────────────────────────
def abrir_chat_por_nome(page, nome: str) -> bool:
    page.evaluate("const p = document.querySelector('#pane-side'); if(p) p.scrollTop = 0;")
    time.sleep(0.4)

    for _ in range(60):
        items = page.query_selector_all('div[data-testid="cell-frame-container"]')
        for item in items:
            try:
                name_el = item.query_selector(
                    'div[data-testid="cell-frame-title"],'
                    'span[data-testid="cell-frame-title"]'
                )
                if not name_el:
                    continue
                if name_el.inner_text().strip() == nome:
                    item.scroll_into_view_if_needed()
                    item.click()
                    time.sleep(1.5)
                    return True
            except Exception:
                continue
        page.evaluate("const p = document.querySelector('#pane-side'); if(p) p.scrollTop += 800;")
        time.sleep(0.3)

    return False


def sair_da_conversa(page):
    page.keyboard.press("Escape")
    time.sleep(0.5)


# ── Envio ──────────────────────────────────────────────────────────────────
def focar_e_preencher(page, msg: str) -> bool:
    try:
        box = page.wait_for_selector(SEL_INPUT, timeout=15000, state="visible")
        if not box:
            return False
        box.scroll_into_view_if_needed()
        box.click()
        page.keyboard.press("Control+a")
        page.keyboard.press("Backspace")
        box.type(msg, delay=random.randint(20, 50))
        return len(box.inner_text().strip()) > 0
    except Exception as e:
        log(f"  [aviso] focar_e_preencher: {e}")
        return False


def clicar_enviar(page) -> bool:
    try:
        btn = page.wait_for_selector(SEL_SEND_BTN, timeout=5000, state="visible")
        if btn:
            btn.click()
            return True
    except Exception:
        pass
    return False


def confirmar_envio(page, timeout_ms: int = 10000) -> bool:
    try:
        page.wait_for_selector(
            "div.message-out, div[data-testid='msg-container']",
            timeout=timeout_ms, state="attached"
        )
        return True
    except Exception:
        return False


def enviar_msg(page, nome: str) -> str:
    primeiro = nome.split()[0]
    msg = random.choice(MENSAGENS).format(nome=primeiro, produto=PRODUTO)
    if not focar_e_preencher(page, msg):
        return "ERRO:falha_ao_preencher"
    if not clicar_enviar(page):
        el = page.query_selector(SEL_INPUT)
        if el:
            el.press("Enter")
        else:
            return "ERRO:sem_input"
    if not confirmar_envio(page):
        return "ERRO:confirmacao_falhou"
    return "ENVIADO"


# ── FASE 2: seleção interativa ────────────────────────────────────────────
def fase_selecao(page, chats: list[dict]) -> list[str]:
    """
    Abre cada chat, mostra pro usuário e coleta a fila de aprovados.
    Retorna lista de nomes aprovados para envio.
    """
    aprovados = []
    total = len(chats)

    print(f"\n{'='*52}")
    print(f"  FASE DE SELEÇÃO — {total} contatos para revisar")
    print(f"  [s] aprovar   [n] pular   [q] terminar seleção")
    print(f"{'='*52}\n")

    for idx, chat in enumerate(chats, 1):
        nome     = chat["nome"]
        time_str = chat["time_str"]

        # Filtros automáticos
        if nome.strip().lower() in IGNORAR_NOMES:
            continue
        if chat["is_group"]:
            continue
        if re.match(r"^\+?[\d\s\-()]+$", nome):
            continue
        if ja_enviado(nome):
            continue
        d = dias_atras(time_str)
        if 0 <= d <= DIAS_RECENTES:
            continue

        # Abre o chat para contexto visual
        aberto = abrir_chat_por_nome(page, nome)
        if not aberto:
            log(f"  [{idx}/{total}] NÃO ENCONTRADO → {nome}")
            continue

        info_tempo = f"{d} dias atrás" if d >= 0 else f"'{time_str}'"
        print(f"\n{'─'*52}")
        print(f"  [{idx}/{total}]  📱  {nome}")
        print(f"  Última msg : {info_tempo}")
        print(f"  Fila aprovada até agora: {len(aprovados)}")
        print(f"{'─'*52}")
        escolha = input("  [s] sim   [n] não   [q] encerrar seleção: ").strip().lower()

        if escolha == "q":
            sair_da_conversa(page)
            log("Seleção encerrada pelo usuário.")
            break

        if escolha == "s":
            aprovados.append(nome)
            log(f"  ✔ APROVADO → {nome}")
            # Salva imediatamente — não perde se fechar o programa
            with open(APROVED_FILE, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerows([[n] for n in aprovados])
        else:
            log(f"  — PULADO → {nome}")

        sair_da_conversa(page)

    log(f"  Seleção concluída: {len(aprovados)} aprovados salvos em aprovados.csv")
    return aprovados


# ── FASE 3: envios em sequência ───────────────────────────────────────────
def fase_envio(page, aprovados: list[str]):
    total    = len(aprovados)
    enviados = 0

    print(f"\n{'='*52}")
    print(f"  FASE DE ENVIO — {total} mensagens na fila")
    print(f"  LIMITE_DIA = {LIMITE_DIA}")
    print(f"{'='*52}\n")

    input("  → Pressione ENTER para iniciar os envios...")

    for idx, nome in enumerate(aprovados, 1):
        pausar()

        if enviados >= LIMITE_DIA:
            log(f"⛔ Limite de {LIMITE_DIA} envios atingido.")
            break

        log(f"  [{idx}/{total}] Abrindo → {nome}")
        aberto = abrir_chat_por_nome(page, nome)
        if not aberto:
            log(f"  ✖ NÃO ENCONTRADO → {nome}")
            registrar(nome, "ERRO:nao_encontrado")
            continue

        resultado = enviar_msg(page, nome)

        if resultado == "ENVIADO":
            enviados += 1
            log(f"  ✔ ENVIADO [{enviados}/{LIMITE_DIA}] → {nome}")
            registrar(nome, "ENVIADO")
        else:
            log(f"  ✖ {resultado} → {nome}")
            registrar(nome, resultado)

        sair_da_conversa(page)

        if enviados < LIMITE_DIA and idx < total:
            delay = random.randint(60, 180)
            log(f"  aguardando {delay}s...")
            time.sleep(delay)

    # Remove CSV de aprovados — ciclo encerrado
    if os.path.exists(APROVED_FILE):
        os.remove(APROVED_FILE)
        log(f"  {APROVED_FILE} removido.")

    return enviados


# ── Main ───────────────────────────────────────────────────────────────────
def rodar():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()

        page.goto("https://web.whatsapp.com", wait_until="domcontentloaded")
        log("Aguardando login no WhatsApp Web...")
        input("  → Escaneie o QR code e pressione ENTER para continuar...")

        try:
            page.wait_for_selector("div[data-testid='chat-list']", timeout=60000)
            log("✓ WhatsApp Web pronto.")
        except PlaywrightTimeout:
            log("⚠ Timeout no login.")
            return

        # Fase 1: coleta
        todos = coletar_todos_chats(page)

        # Fase 2: carrega aprovados salvos OU faz seleção
        if os.path.exists(APROVED_FILE):
            with open(APROVED_FILE, newline="", encoding="utf-8") as f:
                aprovados = [row[0] for row in csv.reader(f) if row]
            log(f"  Aprovados carregados de {APROVED_FILE}: {len(aprovados)} contatos")
            resp = input(f"  → Usar lista salva de {len(aprovados)} aprovados? [s] sim  [n] fazer nova seleção: ").strip().lower()
            if resp != "s":
                aprovados = fase_selecao(page, todos)
        else:
            aprovados = fase_selecao(page, todos)

        print(f"\n  {len(aprovados)} contatos aprovados para envio.")

        if not aprovados:
            log("Nenhum contato aprovado. Encerrando.")
            browser.close()
            return

        # Fase 3: envios com delay
        enviados = fase_envio(page, aprovados)

        browser.close()

    print(f"\n{'='*52}")
    log("RESUMO FINAL")
    log(f"  ✔ Enviados  : {enviados}")
    log(f"  📋 Aprovados : {len(aprovados)}")
    print(f"{'='*52}\n")


if __name__ == "__main__":
    rodar()
