import time, random, sqlite3, datetime, requests, os
import pandas as pd
from multiprocessing import Pool
from unidecode import unidecode
from playwright.sync_api import sync_playwright

# ================= CONFIG =================

ESTADOS = [
    "MG","RJ","ES","PR","BA","GO","MT","MS","DF",
    "PE","CE","PB","RN","AL","SE","PA","AM","RO","RR","AP","TO","MA","PI","AC"
]

NICHOS = [
    "retifica diesel","bomba injetora diesel","oficina diesel","mecanica pesada",
    "injeção diesel","terraplenagem","locação de equipamentos",
    "locação de máquinas pesadas","construtora","pavimentação",
    "mineração","escavadeira","retroescavadeira",
    "tratores manutenção","equipamentos pesados",
    "movimentação de terra","obra pesada","empresa de escavação",
    "serviços de terraplenagem"
]

PROCESSOS = 5
CONTEXTS = 2
DB = "leads.db"

# ==========================================

def normalizar(txt):
    txt = unidecode(txt.lower())
    for lixo in ["ltda","me","eireli","sa"]:
        txt = txt.replace(lixo,"")
    return txt.strip()

def check_pause():
    while os.path.exists("pause.txt"):
        print("⏸ PAUSADO...")
        time.sleep(5)

def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS leads (
        nome TEXT,
        telefone TEXT,
        cidade TEXT,
        estado TEXT,
        nicho TEXT,
        categoria TEXT,
        UNIQUE(nome, telefone)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS tarefas (
        estado TEXT,
        cidade TEXT,
        nicho TEXT,
        UNIQUE(estado, cidade, nicho)
    )
    """)

    conn.commit()
    conn.close()

def salvar_db(dados):
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    for d in dados:
        try:
            c.execute("""
            INSERT OR IGNORE INTO leads VALUES (?,?,?,?,?,?)
            """, (
                normalizar(d["nome"]),
                d["telefone"],
                d["cidade"],
                d["estado"],
                d["segmento"],
                d["categoria"]
            ))
        except:
            pass

    conn.commit()
    conn.close()

def tarefa_feita(t):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO tarefas VALUES (?,?,?)", t)
        conn.commit()
        ok = False
    except:
        ok = True
    conn.close()
    return ok

def cidades_ibge(estado):
    try:
        url = f"https://servicodados.ibge.gov.br/api/v1/localidades/estados/{estado}/municipios"
        return [c["nome"] for c in requests.get(url, timeout=10).json()]
    except:
        return []

def scroll(page):
    last = 0
    rep = 0
    while True:
        total = page.locator('div.Nv2PK').count()
        page.mouse.wheel(0, 10000)
        time.sleep(1)

        if total == last:
            rep += 1
        else:
            rep = 0

        if rep >= 5:
            break

        last = total

def coletar(task):
    estado, cidade, nicho = task

    if tarefa_feita(task):
        return 0

    check_pause()

    dados = []
    visitados = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        contexts = [browser.new_context() for _ in range(CONTEXTS)]

        for context in contexts:
            page = context.new_page()

            buscas = [
                f"{nicho} em {cidade} {estado}",
                f"{nicho} {cidade} {estado}",
                f"{nicho} perto de {cidade}"
            ]

            for busca in buscas:
                check_pause()

                try:
                    page.goto(f"https://www.google.com/maps/search/{busca}", timeout=60000)
                    page.wait_for_selector('div[role="feed"]', timeout=15000)
                except:
                    continue

                scroll(page)

                total = page.locator('div.Nv2PK').count()

                for i in range(total):
                    try:
                        page.locator('div.Nv2PK').nth(i).click()
                        page.wait_for_selector('h1.DUwDvf', timeout=8000)

                        nome = page.locator('h1.DUwDvf').inner_text()
                        key = normalizar(nome)

                        if key in visitados:
                            continue

                        visitados.add(key)

                        telefone = ""
                        try:
                            telefone = page.locator('button[data-item-id*="phone"]').inner_text()
                        except:
                            pass

                        categoria = ""
                        try:
                            categoria = page.locator('button.DkEaL').inner_text()
                        except:
                            pass

                        dados.append({
                            "nome": nome,
                            "telefone": telefone,
                            "cidade": cidade,
                            "estado": estado,
                            "segmento": nicho,
                            "categoria": categoria
                        })

                        if len(dados) % 30 == 0:
                            salvar_db(dados)
                            dados.clear()

                        time.sleep(random.uniform(0.6,1.2))

                    except:
                        continue

        salvar_db(dados)
        browser.close()

    return len(dados)

# ================= EXECUÇÃO =================

if __name__ == "__main__":
    init_db()

    tasks = []

    for estado in ESTADOS:
        cidades = cidades_ibge(estado)

        for cidade in cidades[:200]:  # controle inicial
            for nicho in random.sample(NICHOS, 5):
                tasks.append((estado, cidade, nicho))

    inicio = time.time()

    # processamento em blocos (anti travamento)
    bloco = 100

    for i in range(0, len(tasks), bloco):
        check_pause()

        parte = tasks[i:i+bloco]

        print(f"Bloco {i} até {i+bloco}")

        with Pool(PROCESSOS) as pool:
            pool.map(coletar, parte)

    # export
    conn = sqlite3.connect(DB)
    df = pd.read_sql("SELECT * FROM leads", conn)
    conn.close()

    arquivo = f"C:\\Users\\danie\\Documents\\prospeccao_auto\\BRASIL_{datetime.datetime.now().strftime('%H-%M')}.xlsx"
    df.to_excel(arquivo, index=False)

    fim = time.time()

    print("\nFINAL")
    print("Leads:", len(df))
    print("Tempo (min):", (fim - inicio)/60)