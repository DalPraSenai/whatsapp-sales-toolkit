"""
WhatsApp Web Bot — Refatoração Profissional
==========================================
Arquitetura modular com foco em:
  - Comportamento humano avançado
  - Sistema de mensagens inteligente com memória
  - Anti-detecção robusta
  - Persistência de sessão
  - Estabilidade e tolerância a falhas
"""

import sqlite3
import time
import urllib.parse
import os
import random
import math
import json
import hashlib
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout, Page


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURAÇÃO CENTRALIZADA
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Config:
    # Banco e controle
    db_path: str = "leads.db"
    limite: int = 120
    skip_first_n: int = 0
    max_retries: int = 3
    pause_file: str = "pause.flag"
    log_file: str = "bot.log"

    # Sessão Chrome (evita QR a cada execução)
    chrome_profile_dir: str = os.path.join(os.path.expanduser("~"), ".wp_bot_profile")

    # Delays entre leads (segundos) — distribuição não-uniforme
    delay_min: float = 18.0
    delay_max: float = 55.0
    delay_long_chance: float = 0.18      # 18% chance de pausa longa
    delay_long_min: float = 75.0
    delay_long_max: float = 160.0
    delay_break_chance: float = 0.04     # 4% chance de "intervalo" (3-8 min)
    delay_break_min: float = 180.0
    delay_break_max: float = 480.0

    # Digitação
    type_wpm_min: int = 38               # palavras por minuto mínimo
    type_wpm_max: int = 72               # palavras por minuto máximo
    typo_chance: float = 0.06            # 6% por palavra
    burst_chance: float = 0.35           # chance de modo "burst" (digitar rápido por uns segundos)

    # Memória de mensagens (evita repetição estrutural)
    msg_memory_size: int = 12
    msg_similarity_threshold: float = 0.45


CFG = Config()


# ─────────────────────────────────────────────────────────────────────────────
# SELETORES (centralizados, com fallback em cascata)
# ─────────────────────────────────────────────────────────────────────────────

class Sel:
    INPUT = (
        "div[contenteditable='true'][data-tab='10'],"
        "div[contenteditable='true'][data-tab='1'],"
        "footer div[contenteditable='true']"
    )
    SEND_BTN = (
        "button[data-testid='send'],"
        "span[data-icon='send'],"
        "button[aria-label='Enviar'],"
        "button[aria-label='Send']"
    )
    CHAT_PANEL = "div[data-testid='conversation-panel-wrapper']"
    CHAT_LIST  = "div[data-testid='chat-list']"
    MSG_OUT    = "div.message-out"
    MSG_IN     = "div.message-in"
    MSG_ANY    = "div[data-testid='msg-container'], div.message-in, div.message-out"
    PHONE_ERR  = "div[data-testid='popup-contents'], div._1APhf"   # "número inválido" popup


# ─────────────────────────────────────────────────────────────────────────────
# LOGGER
# ─────────────────────────────────────────────────────────────────────────────

class Logger:
    LEVELS = {"DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40}
    _current_level = 20

    @classmethod
    def _write(cls, level: str, msg: str):
        if cls.LEVELS.get(level, 20) < cls._current_level:
            return
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        icons = {"DEBUG": "·", "INFO": "→", "WARN": "⚠", "ERROR": "✖"}
        line = f"[{ts}] {icons.get(level,'·')} {msg}"
        print(line)
        with open(CFG.log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    @classmethod
    def info(cls, msg):  cls._write("INFO", msg)
    @classmethod
    def warn(cls, msg):  cls._write("WARN", msg)
    @classmethod
    def error(cls, msg): cls._write("ERROR", msg)
    @classmethod
    def debug(cls, msg): cls._write("DEBUG", msg)

log = Logger.info


# ─────────────────────────────────────────────────────────────────────────────
# SISTEMA DE MENSAGENS — COMPOSIÇÃO DINÂMICA COM MEMÓRIA
# ─────────────────────────────────────────────────────────────────────────────

class MessageComposer:
    """
    Monta mensagens a partir de blocos independentes combinados dinamicamente.
    Mantém memória das últimas mensagens para evitar repetição estrutural.
    Usa fingerprint por bag-of-words para medir similaridade.
    """

    # ── Saudações (presença opcional + variação por hora do dia)
    _SAUDACOES = [
        "Oi {nome}",
        "Olá {nome}",
        "E aí {nome}",
        "Bom dia {nome}",
        "Boa tarde {nome}",
        "Boa noite {nome}",
        "Oi {nome}, tudo bem?",
        "Olá {nome}, tudo certo?",
        "Ei {nome}",
        "Oi {nome}! Como vai?",
        "Olá {nome}!",
        "",   # sem saudação — vai direto ao ponto
        "",   # duplicado para aumentar chance de omissão
    ]

    # ── Apresentação pessoal
    _APRESENTACOES = [
        "trabalho com fornecimento de filtros para linha pesada",
        "atuo na área de filtros para linha pesada há alguns anos",
        "sou fornecedor de filtros — linha pesada é meu foco",
        "minha área é filtros para máquinas e veículos pesados",
        "trabalho especificamente com filtros p/ linha pesada",
        "faço fornecimento de filtros (linha pesada) aqui na região",
        "atuo com filtros para linha pesada — motores, transmissão, hidráulico",
        "sou da área de filtros industriais e linha pesada",
    ]

    # ── Contexto / motivo do contato
    _CONTEXTOS = [
        "estou montando nossa base de parceiros",
        "estou estruturando nossa carteira de clientes",
        "estamos organizando um grupo de parceiros aqui na região",
        "tô mapeando quem trabalha na área pra montar nosso network",
        "estou construindo uma lista de contatos do setor",
        "estamos selecionando parceiros para trabalhar junto",
        "tô organizando nossa lista de fornecedores e clientes potenciais",
        "estamos expandindo nosso atendimento e queria me apresentar",
        "queria me apresentar e ver se faz sentido a gente se conectar",
    ]

    # ── Proposta / call to action
    _PROPOSTAS = [
        "posso te chamar aqui quando tivermos catálogo e condições fechados?",
        "posso te acionar quando tiver novidades e promoções?",
        "te deixo salvo aqui para futuras cotações?",
        "posso manter contato contigo por aqui?",
        "consigo te chamar quando tiver algo relevante pra sua operação?",
        "posso te enviar nosso catálogo assim que estiver pronto?",
        "posso contar contigo quando for lançar nossas condições?",
        "faz sentido eu te chamar quando tiver algo de interesse?",
        "posso te incluir na nossa lista de contatos prioritários?",
    ]

    # ── Fechamentos (presença opcional)
    _FECHAMENTOS = [
        "Abs",
        "Valeu!",
        "Obrigado!",
        "Att",
        "Grato",
        "Abraço",
        "",   # sem fechamento
        "",
        "",
    ]

    # ── Emojis temáticos (presença opcional e rara)
    _EMOJIS_CONTEXTO = ["🔧", "⚙️", "🚛", "🛠️", "✅", "👋"]

    # ── Estruturas de mensagem — cada tuple descreve quais blocos incluir e em qual ordem
    # Formatos: lista de blocos a combinar
    # "s"=saudação, "a"=apresentação, "c"=contexto, "p"=proposta, "f"=fechamento
    _ESTRUTURAS = [
        ["s", "a", "c", "p"],           # clássica completa
        ["s", "a", "p"],                # sem contexto (mais direta)
        ["s", "c", "a", "p"],           # contexto antes da apresentação
        ["a", "c", "p"],                # sem saudação
        ["s", "p", "a"],                # proposta antecipada (curiosidade)
        ["s", "a", "c", "p", "f"],      # com fechamento formal
        ["s", "a", "p", "f"],           # com fechamento curto
        ["a", "p"],                     # ultra-direta
        ["s", "c", "p"],                # sem apresentação explícita
    ]

    def __init__(self, memory_size: int = 12, similarity_threshold: float = 0.45):
        self._memory: deque = deque(maxlen=memory_size)
        self._threshold = similarity_threshold
        self._block_usage: dict = {}   # controle de frequência por bloco
        self._last_estrutura: Optional[int] = None

    # ── Fingerprint por bag-of-words (leve, sem deps externas)
    @staticmethod
    def _fingerprint(text: str) -> set:
        words = set(text.lower().split())
        stopwords = {"e", "o", "a", "de", "para", "com", "que", "em", "se", "da", "do"}
        return words - stopwords

    def _similarity(self, a: str, b: str) -> float:
        fa, fb = self._fingerprint(a), self._fingerprint(b)
        if not fa or not fb:
            return 0.0
        intersection = len(fa & fb)
        return intersection / math.sqrt(len(fa) * len(fb))

    def _max_similarity_to_memory(self, candidate: str) -> float:
        if not self._memory:
            return 0.0
        return max(self._similarity(candidate, past) for past in self._memory)

    def _escolher_bloco(self, lista: list, key: str) -> str:
        # Peso inversamente proporcional ao uso recente
        usage = self._block_usage.get(key, {})
        pesos = []
        for item in lista:
            used = usage.get(item, 0)
            peso = 1.0 / (1 + used * 0.7)
            pesos.append(peso)

        total = sum(pesos)
        r = random.random() * total
        acumulado = 0.0
        for item, peso in zip(lista, pesos):
            acumulado += peso
            if r <= acumulado:
                chosen = item
                break
        else:
            chosen = random.choice(lista)

        # Registrar uso
        if key not in self._block_usage:
            self._block_usage[key] = {}
        self._block_usage[key][chosen] = self._block_usage[key].get(chosen, 0) + 1
        return chosen

    def _saudacao_contextual(self, nome: str) -> str:
        hora = datetime.now().hour
        if hora < 12:
            pool = [f"Bom dia {nome}", f"Oi {nome}, bom dia", f"Oi {nome}",
                    f"Olá {nome}", f"Ei {nome}", ""]
        elif hora < 18:
            pool = [f"Boa tarde {nome}", f"Olá {nome}", f"Oi {nome}, tudo bem?",
                    f"Oi {nome}", f"E aí {nome}", ""]
        else:
            pool = [f"Boa noite {nome}", f"Olá {nome}", f"Oi {nome}",
                    f"E aí {nome}", ""]
        return self._escolher_bloco(pool, "saudacao")

    def _escolher_estrutura(self) -> list:
        # Evita repetir a mesma estrutura consecutivamente
        indices = list(range(len(self._ESTRUTURAS)))
        if self._last_estrutura is not None:
            indices = [i for i in indices if i != self._last_estrutura]
        idx = random.choice(indices)
        self._last_estrutura = idx
        return self._ESTRUTURAS[idx]

    def _adicionar_imperfeicoes(self, texto: str) -> str:
        """Adiciona pequenas variações ortográficas humanas (intencionais e leves)."""
        substituicoes = [
            ("você", "vc"),
            ("para", "pra"),
            ("estou", "tô"),
            ("também", "tbm"),
            ("por aqui", "aqui"),
            ("quando", "qdo"),
        ]
        for original, alternativo in substituicoes:
            if original in texto and random.random() < 0.25:
                texto = texto.replace(original, alternativo, 1)
        return texto

    def _formatar_separadores(self, blocos_texto: list) -> str:
        """
        Decide como juntar os blocos: vírgula, ponto, quebra de linha, etc.
        Variação estrutural real.
        """
        estilo = random.choice(["inline", "inline", "multiline", "misto"])

        if estilo == "inline":
            # tudo numa linha, separado por ponto ou vírgula
            sep = random.choice([". ", ", ", " — ", "; "])
            partes = [b for b in blocos_texto if b]
            return sep.join(partes)

        elif estilo == "multiline":
            partes = [b for b in blocos_texto if b]
            return "\n".join(partes)

        else:  # misto
            partes = [b for b in blocos_texto if b]
            resultado = []
            i = 0
            while i < len(partes):
                if i < len(partes) - 1 and random.random() < 0.4:
                    resultado.append(partes[i] + random.choice([". ", ", "]) + partes[i+1])
                    i += 2
                else:
                    resultado.append(partes[i])
                    i += 1
            return "\n".join(resultado)

    def compor(self, nome: str, max_tentativas: int = 8) -> str:
        for _ in range(max_tentativas):
            estrutura = self._escolher_estrutura()
            blocos = []

            for bloco_id in estrutura:
                if bloco_id == "s":
                    blocos.append(self._saudacao_contextual(nome))
                elif bloco_id == "a":
                    blocos.append(self._escolher_bloco(self._APRESENTACOES, "apresentacao"))
                elif bloco_id == "c":
                    blocos.append(self._escolher_bloco(self._CONTEXTOS, "contexto"))
                elif bloco_id == "p":
                    blocos.append(self._escolher_bloco(self._PROPOSTAS, "proposta"))
                elif bloco_id == "f":
                    blocos.append(self._escolher_bloco(self._FECHAMENTOS, "fechamento"))

            msg = self._formatar_separadores(blocos)

            # Imperfeições humanas ocasionais
            if random.random() < 0.30:
                msg = self._adicionar_imperfeicoes(msg)

            # Emoji raro e contextual
            if random.random() < 0.12:
                emoji = random.choice(self._EMOJIS_CONTEXTO)
                if random.random() < 0.5:
                    msg = emoji + " " + msg
                else:
                    msg = msg + " " + emoji

            # Verifica similaridade com memória
            sim = self._max_similarity_to_memory(msg)
            if sim < self._threshold:
                self._memory.append(msg)
                return msg

        # Fallback: aceita a última mesmo com similaridade alta
        self._memory.append(msg)
        return msg


# Instância global do composer
_composer = MessageComposer(
    memory_size=CFG.msg_memory_size,
    similarity_threshold=CFG.msg_similarity_threshold,
)


def gerar_mensagem(nome: str) -> str:
    return _composer.compor(nome)


# ─────────────────────────────────────────────────────────────────────────────
# ENGINE DE COMPORTAMENTO HUMANO
# ─────────────────────────────────────────────────────────────────────────────

class HumanEngine:
    """
    Centraliza toda simulação de comportamento humano:
    delays, digitação, movimentação de mouse, hesitação.
    """

    def __init__(self):
        self._session_start = time.time()
        self._msgs_enviadas = 0
        self._fadiga = 0.0   # 0.0 = descansado, 1.0 = cansado

    def _atualizar_fadiga(self):
        # Fadiga aumenta com o tempo e mensagens, diminui após pausas longas
        elapsed_h = (time.time() - self._session_start) / 3600
        self._fadiga = min(1.0, elapsed_h * 0.3 + self._msgs_enviadas * 0.008)

    def registrar_envio(self):
        self._msgs_enviadas += 1
        self._atualizar_fadiga()

    # ── Distribuição de tempo gaussiana truncada (mais humana que uniforme)
    @staticmethod
    def _gauss_range(low: float, high: float, sigma_frac: float = 0.25) -> float:
        mean = (low + high) / 2
        sigma = (high - low) * sigma_frac
        val = random.gauss(mean, sigma)
        return max(low, min(high, val))

    # ── Delay entre leads (considera fadiga)
    def delay_entre_leads(self) -> float:
        self._atualizar_fadiga()
        fator_fadiga = 1.0 + self._fadiga * 0.5   # até +50% por fadiga

        roll = random.random()
        if roll < CFG.delay_break_chance:
            d = self._gauss_range(CFG.delay_break_min, CFG.delay_break_max)
            log(f"  ☕ pausa longa ({d:.0f}s) — simulando intervalo")
            return d * fator_fadiga
        elif roll < CFG.delay_break_chance + CFG.delay_long_chance:
            d = self._gauss_range(CFG.delay_long_min, CFG.delay_long_max)
            return d * fator_fadiga
        else:
            d = self._gauss_range(CFG.delay_min, CFG.delay_max)
            return d * fator_fadiga

    # ── Delay de "leitura" antes de enviar (simula ler o que escreveu)
    @staticmethod
    def delay_leitura(msg: str) -> float:
        palavras = len(msg.split())
        # ~180 wpm de leitura humana, com variação
        base = palavras / random.uniform(140, 220)
        return max(0.8, base + random.gauss(0, 0.3))

    # ── Hesitação antes de abrir conversa
    @staticmethod
    def delay_pre_chat() -> float:
        return HumanEngine._gauss_range(1.5, 5.0)

    # ── Pequena pausa após foco no campo
    @staticmethod
    def delay_pre_digitar() -> float:
        if random.random() < 0.3:
            return random.uniform(1.2, 3.5)  # hesitação
        return random.uniform(0.3, 1.0)

    # ── Velocidade de digitação em ms por caractere
    @staticmethod
    def velocidade_digitacao() -> tuple:
        """Retorna (delay_medio_ms, modo) — modo pode ser 'burst' ou 'normal'."""
        wpm = random.uniform(CFG.type_wpm_min, CFG.type_wpm_max)
        # WPM → ms por caractere (assume palavra média de 5 chars + espaço)
        ms_por_char = 60000 / (wpm * 6)
        modo = "burst" if random.random() < CFG.burst_chance else "normal"
        return ms_por_char, modo

    # ── Movimento de mouse natural (curva de Bézier aproximada)
    @staticmethod
    def mover_mouse_natural(page: Page, x: int, y: int):
        try:
            cur_x = random.randint(200, 800)
            cur_y = random.randint(200, 600)
            steps = random.randint(8, 18)
            for step in range(steps + 1):
                t = step / steps
                # Bézier cúbico simplificado
                ease = t * t * (3 - 2 * t)
                # Ponto de controle com desvio orgânico
                cx = cur_x + (x - cur_x) * ease + random.gauss(0, 3)
                cy = cur_y + (y - cur_y) * ease + random.gauss(0, 3)
                page.mouse.move(cx, cy)
                if step < steps:
                    time.sleep(random.uniform(0.008, 0.025))
        except Exception:
            pass  # movimentação de mouse nunca deve travar o fluxo

    # ── Digitação com comportamento humano avançado
    def digitar_humano(self, page: Page, element, texto: str):
        ms_base, modo = self.velocidade_digitacao()
        palavras = texto.split(" ")
        pos_char = 0

        for i, palavra in enumerate(palavras):
            # Espaço antes (exceto primeira palavra)
            if i > 0:
                page.keyboard.type(" ")
                time.sleep(ms_base / 1000 * random.uniform(0.8, 1.4))
                pos_char += 1

            # Decidir se vai errar essa palavra
            vai_errar = random.random() < CFG.typo_chance and len(palavra) > 3

            if vai_errar:
                # Digitar a palavra com erro
                idx_erro = random.randint(1, len(palavra) - 1)
                chars_errados = random.choice([
                    palavra[:idx_erro] + chr(ord(palavra[idx_erro]) + 1),  # char adjacente
                    palavra[:idx_erro] + palavra[idx_erro-1],              # repetição
                    palavra[:idx_erro+1] + "x",                           # char aleatório
                ])
                palavra_com_erro = palavra[:idx_erro] + chars_errados[:1] + palavra[idx_erro:]
                self._digitar_palavra(page, palavra_com_erro, ms_base, modo)
                # Pausa de "perceber o erro"
                time.sleep(random.uniform(0.3, 1.1))
                # Apagar e redigitar
                for _ in range(len(palavra_com_erro) - idx_erro + random.randint(0, 1)):
                    page.keyboard.press("Backspace")
                    time.sleep(random.uniform(0.04, 0.12))
                # Redigitar a parte correta
                for ch in palavra[idx_erro:]:
                    page.keyboard.type(ch)
                    time.sleep(ms_base / 1000 * random.uniform(0.7, 1.5))
            else:
                self._digitar_palavra(page, palavra, ms_base, modo)

            # Pausa ocasional entre palavras (pensar no que escrever)
            if random.random() < 0.08:
                time.sleep(random.uniform(0.5, 2.0))
            elif random.random() < 0.15 and modo == "normal":
                time.sleep(ms_base / 1000 * random.uniform(2.0, 4.0))

    @staticmethod
    def _digitar_palavra(page: Page, palavra: str, ms_base: float, modo: str):
        if modo == "burst":
            # Burst: digita rápido com aceleração no meio
            for j, ch in enumerate(palavra):
                page.keyboard.type(ch)
                frac = j / max(len(palavra) - 1, 1)
                # Aceleração gaussiana — mais rápido no meio da palavra
                fator = 1.0 - 0.4 * math.sin(math.pi * frac)
                time.sleep(ms_base / 1000 * fator * random.uniform(0.5, 1.2))
        else:
            for ch in palavra:
                page.keyboard.type(ch)
                jitter = random.gauss(1.0, 0.25)
                time.sleep(ms_base / 1000 * max(0.3, jitter))


_human = HumanEngine()


# ─────────────────────────────────────────────────────────────────────────────
# ANTI-DETECÇÃO — JavaScript injection
# ─────────────────────────────────────────────────────────────────────────────

STEALTH_JS = """
() => {
    // Remove webdriver flag
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

    // Plugins reais
    Object.defineProperty(navigator, 'plugins', {
        get: () => {
            const arr = [
                { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
                { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
                { name: 'Native Client', filename: 'internal-nacl-plugin' },
            ];
            arr.__proto__ = PluginArray.prototype;
            return arr;
        }
    });

    // Linguagens
    Object.defineProperty(navigator, 'languages', {
        get: () => ['pt-BR', 'pt', 'en-US', 'en']
    });

    // Hardware concurrency realista
    Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });

    // DeviceMemory
    Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });

    // Chrome runtime object
    window.chrome = {
        runtime: {
            onConnect: { addListener: () => {} },
            onMessage: { addListener: () => {} }
        }
    };

    // Permissions API
    const originalQuery = window.navigator.permissions?.query?.bind(navigator.permissions);
    if (originalQuery) {
        navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications'
                ? Promise.resolve({ state: Notification.permission })
                : originalQuery(parameters)
        );
    }

    // WebGL vendor
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(parameter) {
        if (parameter === 37445) return 'Intel Inc.';
        if (parameter === 37446) return 'Intel Iris OpenGL Engine';
        return getParameter.call(this, parameter);
    };
}
"""


# ─────────────────────────────────────────────────────────────────────────────
# BANCO DE DADOS
# ─────────────────────────────────────────────────────────────────────────────

def _db_connect():
    conn = sqlite3.connect(CFG.db_path, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def carregar_leads():
    conn = _db_connect()
    c = conn.cursor()
    try:
        c.execute("ALTER TABLE leads ADD COLUMN status INTEGER DEFAULT 0")
        conn.commit()
    except Exception:
        pass
    rows = c.execute(f"""
        SELECT rowid, nome, telefone
        FROM leads
        WHERE telefone != ''
          AND score >= 5
          AND (status IS NULL OR status = 0)
        ORDER BY score DESC
        LIMIT {CFG.limite}
    """).fetchall()
    conn.close()
    return rows


def atualizar_status(rowid: int, status: int):
    conn = _db_connect()
    try:
        conn.execute(
            "UPDATE leads SET status = ? WHERE rowid = ?",
            (status, rowid)
        )
        conn.commit()
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# UTILITÁRIOS
# ─────────────────────────────────────────────────────────────────────────────

def limpar_numero(tel: str) -> Optional[str]:
    if not tel:
        return None
    tel = "".join(c for c in tel if c.isdigit())
    if tel.startswith("55"):
        tel = tel[2:]
    if len(tel) == 11:
        return tel
    return None


def pausar():
    while os.path.exists(CFG.pause_file):
        log("⏸  PAUSADO — remova pause.flag para continuar...")
        time.sleep(4)


def _espera_inteligente(page: Page, selector: str, timeout: int = 15000,
                        state: str = "visible") -> Optional[object]:
    """
    Wrapper robusto para wait_for_selector.
    Tenta o seletor e retorna None (sem exception) em caso de timeout.
    """
    try:
        return page.wait_for_selector(selector, timeout=timeout, state=state)
    except PlaywrightTimeout:
        return None
    except Exception as e:
        Logger.debug(f"_espera_inteligente({selector[:40]}): {e}")
        return None


def _elemento_fresco(page: Page, selector: str):
    """Re-query do elemento para evitar stale element reference."""
    try:
        return page.query_selector(selector)
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# VERIFICAÇÕES DE ESTADO DA PÁGINA
# ─────────────────────────────────────────────────────────────────────────────

def numero_invalido_popup(page: Page) -> bool:
    """Detecta popup de 'número de telefone inválido' do WhatsApp."""
    try:
        el = page.query_selector(Sel.PHONE_ERR)
        if el and el.is_visible():
            text = el.inner_text().lower()
            return "inválido" in text or "invalid" in text or "não" in text
        return False
    except Exception:
        return False


def ja_tem_conversa(page: Page) -> bool:
    """
    True somente se houver mensagens reais renderizadas.
    Aguarda estabilização do DOM antes de verificar.
    """
    try:
        if not _espera_inteligente(page, Sel.CHAT_PANEL, timeout=8000):
            return False

        # Aguarda estabilização sem sleep fixo — poll curto
        for _ in range(6):
            count = page.evaluate("""
                () => {
                    const sels = [
                        'div[data-testid="msg-container"]',
                        'div.message-in',
                        'div.message-out'
                    ];
                    for (const s of sels) {
                        const els = document.querySelectorAll(s);
                        if (els.length > 0) return els.length;
                    }
                    return 0;
                }
            """)
            if count > 0:
                return True
            time.sleep(0.4)
        return False

    except PlaywrightTimeout:
        return False
    except Exception as e:
        Logger.warn(f"ja_tem_conversa: {e}")
        return False


def chat_esta_pronto(page: Page) -> bool:
    """Verifica se o painel de chat e o input estão ambos disponíveis."""
    try:
        panel = page.query_selector(Sel.CHAT_PANEL)
        inp   = page.query_selector(Sel.INPUT)
        return (panel is not None and panel.is_visible() and
                inp is not None and inp.is_visible())
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# INTERAÇÃO COM O INPUT
# ─────────────────────────────────────────────────────────────────────────────

def focar_input(page: Page) -> Optional[object]:
    """
    Localiza e foca o input de mensagem.
    Usa scroll + movimento de mouse natural + click.
    Retorna o elemento ou None.
    """
    box = _espera_inteligente(page, Sel.INPUT, timeout=15000, state="visible")
    if not box:
        return None

    try:
        box.scroll_into_view_if_needed()
        rect = box.bounding_box()
        if rect:
            target_x = rect["x"] + rect["width"] * random.uniform(0.2, 0.8)
            target_y = rect["y"] + rect["height"] * random.uniform(0.2, 0.8)
            _human.mover_mouse_natural(page, int(target_x), int(target_y))
            time.sleep(random.uniform(0.08, 0.2))
        box.click()
        return box
    except Exception as e:
        Logger.warn(f"focar_input: {e}")
        return None


def limpar_input(page: Page):
    """Limpa o campo de forma humana (seleção total + delete)."""
    try:
        page.keyboard.press("Control+a")
        time.sleep(random.uniform(0.05, 0.15))
        page.keyboard.press("Delete")
        time.sleep(random.uniform(0.08, 0.2))
    except Exception:
        pass


def preencher_input(page: Page, msg: str) -> bool:
    """
    Foca, limpa e preenche o input com digitação humana avançada.
    Verifica o conteúdo após inserção.
    """
    box = focar_input(page)
    if not box:
        return False

    limpar_input(page)

    time.sleep(_human.delay_pre_digitar())

    _human.digitar_humano(page, box, msg)

    # Verificar conteúdo inserido (stale-safe: re-query)
    time.sleep(0.2)
    box_fresh = _elemento_fresco(page, Sel.INPUT)
    if box_fresh:
        content = box_fresh.inner_text()
        return len(content.strip()) > 0

    # Fallback: se não conseguiu re-query, assume que foi
    return True


# ─────────────────────────────────────────────────────────────────────────────
# ENVIO
# ─────────────────────────────────────────────────────────────────────────────

def clicar_enviar(page: Page) -> bool:
    btn = _espera_inteligente(page, Sel.SEND_BTN, timeout=5000, state="visible")
    if not btn:
        return False
    try:
        rect = btn.bounding_box()
        if rect:
            cx = rect["x"] + rect["width"] / 2
            cy = rect["y"] + rect["height"] / 2
            _human.mover_mouse_natural(page, int(cx), int(cy))
            time.sleep(random.uniform(0.05, 0.15))
        btn.click()
        return True
    except Exception as e:
        Logger.warn(f"clicar_enviar: {e}")
        return False


def confirmar_envio(page: Page, timeout_ms: int = 12000) -> bool:
    """
    Confirma envio verificando aparecimento de nova mensagem-out.
    Conta mensagens antes e depois para evitar falso positivo com histórico.
    """
    try:
        contagem_antes = page.evaluate(
            "() => document.querySelectorAll('div.message-out').length"
        )
        page.wait_for_function(
            f"() => document.querySelectorAll('div.message-out').length > {contagem_antes}",
            timeout=timeout_ms
        )
        return True
    except PlaywrightTimeout:
        return False
    except Exception as e:
        Logger.warn(f"confirmar_envio: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# FLUXO DE ENVIO POR LEAD
# ─────────────────────────────────────────────────────────────────────────────

def enviar_msg(page: Page, numero: str, nome: str) -> str:
    """
    Retorna: "ENVIADO" | "JA_CONTATADO" | "NUMERO_INVALIDO" | "ERRO:<detalhe>"
    """
    msg = gerar_mensagem(nome)

    # 1. Navegar para o chat (URL com texto pré-preenchido)
    url = (
        f"https://web.whatsapp.com/send"
        f"?phone=55{numero}"
        f"&text={urllib.parse.quote(msg)}"
    )

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        return f"ERRO:goto:{e}"

    # 2. Pausa humana pré-chat (simula "olhar a tela antes de agir")
    time.sleep(_human.delay_pre_chat())

    # 3. Aguardar input visível
    if not _espera_inteligente(page, Sel.INPUT, timeout=28000, state="visible"):
        if numero_invalido_popup(page):
            return "NUMERO_INVALIDO"
        return "ERRO:input_nao_apareceu"

    # 4. Checar popup de número inválido
    if numero_invalido_popup(page):
        return "NUMERO_INVALIDO"

    # 5. Verificar conversa existente
    if ja_tem_conversa(page):
        return "JA_CONTATADO"

    # 6. Limpar o campo (URL já injetou texto, mas é duplicado com digitação humana)
    #    Estratégia: limpar o que a URL injetou e redigitar humanamente
    box = focar_input(page)
    if not box:
        return "ERRO:sem_foco_input"

    limpar_input(page)

    # 7. Pausa de "pensar" + redigitar humanamente
    time.sleep(_human.delay_pre_digitar())
    _human.digitar_humano(page, box, msg)

    # 8. Simular leitura da mensagem antes de enviar
    time.sleep(_human.delay_leitura(msg))

    # Ocasionalmente, hesitar antes de enviar
    if random.random() < 0.15:
        time.sleep(random.uniform(1.5, 4.0))

    # 9. Enviar
    enviou_pelo_botao = clicar_enviar(page)
    if not enviou_pelo_botao:
        Logger.debug("botão não encontrado, usando Enter")
        box_fresh = _elemento_fresco(page, Sel.INPUT)
        if box_fresh:
            box_fresh.press("Enter")
        else:
            return "ERRO:sem_input_para_enter"

    # 10. Confirmar envio
    if not confirmar_envio(page, timeout_ms=12000):
        return "ERRO:confirmacao_falhou"

    _human.registrar_envio()
    return "ENVIADO"


# ─────────────────────────────────────────────────────────────────────────────
# INICIALIZAÇÃO DO BROWSER (com persistência de sessão + stealth)
# ─────────────────────────────────────────────────────────────────────────────

def _criar_browser(playwright):
    os.makedirs(CFG.chrome_profile_dir, exist_ok=True)

    # Randomizar viewport ligeiramente (evita assinatura fixa)
    vw = random.choice([1280, 1366, 1440, 1920])
    vh = random.choice([720, 768, 800, 900, 1080])

    context = playwright.chromium.launch_persistent_context(
        user_data_dir=CFG.chrome_profile_dir,
        headless=False,
        viewport={"width": vw, "height": vh},
        args=[
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--disable-dev-shm-usage",
            "--disable-extensions",
            "--no-first-run",
            "--disable-default-apps",
            f"--window-size={vw},{vh}",
        ],
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        locale="pt-BR",
        timezone_id="America/Sao_Paulo",
        color_scheme="light",
        ignore_https_errors=True,
    )

    page = context.new_page()

    # Injetar stealth JS antes de qualquer navegação
    context.add_init_script(STEALTH_JS)
    page.add_init_script(STEALTH_JS)

    return context, page


def _aguardar_login(page: Page):
    """
    Tenta sessão persistida primeiro.
    Só pede QR code se não houver sessão ativa.
    """
    page.goto("https://web.whatsapp.com", wait_until="domcontentloaded", timeout=30000)

    # Verifica se já está logado (chat-list visível em < 15s)
    chat_list = _espera_inteligente(page, Sel.CHAT_LIST, timeout=15000)
    if chat_list:
        log("✓ Sessão restaurada — login não necessário.")
        return

    log("Sessão não encontrada. Escaneie o QR code...")
    input("  → Pressione ENTER após escanear o QR code...")

    chat_list = _espera_inteligente(page, Sel.CHAT_LIST, timeout=90000)
    if chat_list:
        log("✓ WhatsApp Web pronto.")
    else:
        Logger.warn("Timeout aguardando chat-list — verifique o login.")


# ─────────────────────────────────────────────────────────────────────────────
# LOOP PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

def rodar():
    leads = carregar_leads()
    total = len(leads)
    log(f"▶ {total} leads carregados para processamento")

    contadores = {"enviados": 0, "pulados": 0, "erros": 0, "invalidos": 0}

    with sync_playwright() as p:
        context, page = _criar_browser(p)

        try:
            _aguardar_login(page)

            for i, (rowid, nome, tel) in enumerate(leads):
                pausar()

                if i < CFG.skip_first_n:
                    log(f"  SKIP [{i+1}/{total}] → {nome}")
                    continue

                log(f"\n[{i+1}/{total}] {nome}")

                numero = limpar_numero(tel)
                if not numero:
                    Logger.warn(f"  número inválido → {nome} ({tel})")
                    atualizar_status(rowid, 3)
                    contadores["invalidos"] += 1
                    continue

                # ── Retry com back-off exponencial
                resultado = None
                for tentativa in range(1, CFG.max_retries + 1):
                    try:
                        resultado = enviar_msg(page, numero, nome)
                        break
                    except PlaywrightTimeout as e:
                        Logger.warn(f"  timeout tentativa {tentativa}/{CFG.max_retries}")
                        if tentativa < CFG.max_retries:
                            backoff = 3 * (2 ** (tentativa - 1)) + random.uniform(0, 2)
                            time.sleep(backoff)
                    except Exception as e:
                        Logger.warn(f"  exceção tentativa {tentativa}/{CFG.max_retries}: {e}")
                        if tentativa < CFG.max_retries:
                            backoff = 3 * (2 ** (tentativa - 1))
                            time.sleep(backoff)
                        else:
                            resultado = f"ERRO:{type(e).__name__}:{e}"

                # ── Processar resultado
                if resultado == "ENVIADO":
                    atualizar_status(rowid, 1)
                    contadores["enviados"] += 1
                    log(f"  ✔ ENVIADO → {nome} ({numero})")

                elif resultado == "JA_CONTATADO":
                    atualizar_status(rowid, 4)
                    contadores["pulados"] += 1
                    log(f"  ↪ JÁ CONTATADO → {nome}")

                elif resultado == "NUMERO_INVALIDO":
                    atualizar_status(rowid, 3)
                    contadores["invalidos"] += 1
                    Logger.warn(f"  número rejeitado pelo WA → {nome}")

                else:
                    atualizar_status(rowid, 2)
                    contadores["erros"] += 1
                    Logger.error(f"  ERRO → {nome} | {resultado}")

                # ── Delay humano entre leads
                if i < total - 1:   # não espera após o último
                    delay = _human.delay_entre_leads()
                    log(f"  ⏱ aguardando {delay:.0f}s")
                    time.sleep(delay)

        except KeyboardInterrupt:
            log("\n⚠ Interrompido pelo usuário.")
        except Exception as e:
            Logger.error(f"Falha crítica no loop principal: {e}")
            raise
        finally:
            try:
                context.close()
            except Exception:
                pass

    sep = "─" * 45
    log(sep)
    log(
        f"RESUMO FINAL | "
        f"✔ {contadores['enviados']} enviados | "
        f"↪ {contadores['pulados']} já contatados | "
        f"✖ {contadores['erros']} erros | "
        f"⊘ {contadores['invalidos']} inválidos"
    )
    log(sep)


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    rodar()