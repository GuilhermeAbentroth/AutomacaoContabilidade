import json
import hashlib
import requests
import customtkinter as ctk
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import os
import base64
import tkinter as tk
from datetime import datetime, timedelta
from tkinter import messagebox

# =========================================================================
# ID da planilha Google Sheets de licenças
# Colunas: A=Login  B=Senha  C=Vencimento (dd/mm/yyyy ou yyyy-mm-dd)
# =========================================================================
LICENCA_API_URL = "https://script.google.com/macros/s/AKfycbwp82nOcYCI6NUuKHn-3tBQQEEkPpgzJ7yye09vFMLMjmTq0bXMEga1jYqefUrA1OQ_/exec"
DIAS_CACHE_OFFLINE = 3   # dias que o sistema funciona sem internet
_SALT = "Gu!lh3rm3@b3ntr0tho911#"

def _gerar_chave() -> bytes:
    return hashlib.sha256(_SALT.encode()).digest()  # 256 bits exatos

def _criptografar(texto: str) -> str:
    chave  = _gerar_chave()
    aesgcm = AESGCM(chave)
    nonce  = os.urandom(12)  # 96 bits aleatórios — único a cada salvamento
    cifrado = aesgcm.encrypt(nonce, texto.encode('utf-8'), None)
    # Junta nonce + cifrado e converte para base64 para salvar em TXT
    return base64.b64encode(nonce + cifrado).decode('utf-8')

def _descriptografar(texto_cifrado: str) -> str:
    chave   = _gerar_chave()
    aesgcm  = AESGCM(chave)
    raw     = base64.b64decode(texto_cifrado.encode('utf-8'))
    nonce   = raw[:12]   # Primeiros 12 bytes = nonce
    cifrado = raw[12:]   # Resto = dados cifrados
    return aesgcm.decrypt(nonce, cifrado, None).decode('utf-8')

class LicencaModulo:
    def __init__(self, parent):
        self.parent = parent
        self.cache_path = os.path.join(parent.pasta_exe, "config_licenca.cache")
        self._autenticado  = False
        self._login_atual  = None
        self._validade_atual = None  # datetime

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------
    def licenca_valida(self) -> bool:
        return self._autenticado

    def obter_data_validade(self) -> str | None:
        if self._validade_atual:
            return self._validade_atual.strftime("%d/%m/%Y")
        return None

    def obter_login(self) -> str | None:
        return self._login_atual

    def verificar_e_autenticar(self) -> bool:
        """
        Chamado na abertura do app.
        1. Tenta validar cache local (offline/online).
        2. Se não há cache válido, exibe tela de login.
        Retorna True se o usuário foi autenticado.
        """
        if self._validar_cache():
            return True
        return self._mostrar_tela_login()

    def logout(self):
        """Remove o cache e força novo login na próxima abertura."""
        if os.path.exists(self.cache_path):
            try:
                os.remove(self.cache_path)
            except Exception:
                pass
        self._autenticado   = False
        self._login_atual   = None
        self._validade_atual = None

    # ------------------------------------------------------------------
    # Cache local
    # ------------------------------------------------------------------
    def _calcular_hash(self, login: str, validade: str, cache_expira: str) -> str:
        texto = f"{login}|{validade}|{cache_expira}|{_SALT}"
        return hashlib.sha256(texto.encode()).hexdigest()[:32]

    def _salvar_cache(self, login: str, validade: datetime, senha: str = ""):
        try:
            validade_str    = validade.strftime("%Y-%m-%d")
            cache_expira    = (datetime.now() + timedelta(days=DIAS_CACHE_OFFLINE)).strftime("%Y-%m-%d")
            hash_val        = self._calcular_hash(login, validade_str, cache_expira)
            dados = {
                "login":        login,
                "senha":        senha,
                "validade":     validade_str,
                "cache_expira": cache_expira,
                "hash":         hash_val
            }
            texto = json.dumps(dados)
            with open(self.cache_path, "w", encoding="utf-8") as f:
                f.write(_criptografar(texto))
        except Exception:
            pass

    def _validar_cache(self) -> bool:
        if not os.path.exists(self.cache_path):
            return False
        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                conteudo = f.read().strip()
            dados = json.loads(_descriptografar(conteudo))

            login           = dados.get("login", "")
            validade_str    = dados.get("validade", "")
            cache_expira_str = dados.get("cache_expira", "")
            hash_salvo      = dados.get("hash", "")

            # Verifica integridade anti-adulteração
            if self._calcular_hash(login, validade_str, cache_expira_str) != hash_salvo:
                return False

            hoje = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

            # Cache ainda dentro do período offline?
            if hoje > datetime.strptime(cache_expira_str, "%Y-%m-%d"):
                return False

            # Licença ainda válida?
            validade = datetime.strptime(validade_str, "%Y-%m-%d")
            if hoje > validade:
                return False

            self._login_atual    = login
            self._validade_atual = validade
            self._autenticado    = True
            return True

        except Exception:
            return False

    # ------------------------------------------------------------------
    # Validação online (Google Sheets)
    # ------------------------------------------------------------------
    def _validar_online(self, login: str, senha: str):
        try:
            resp = requests.get(
                LICENCA_API_URL,
                params={"login": login, "senha": senha},
                timeout=10
            )
            if resp.status_code != 200:
                return None, "Erro ao conectar com o servidor de licenças."

            dados = resp.json()

            if dados.get("status") != "OK":
                return None, "Login ou senha incorretos."

            validade_str = dados.get("validade", "")
            try:
                try:
                    validade = datetime.strptime(validade_str, "%d/%m/%Y")
                except ValueError:
                    validade = datetime.strptime(validade_str, "%Y-%m-%d")

                hoje = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                if hoje > validade:
                    return None, f"Licença expirada em {validade.strftime('%d/%m/%Y')}."

                return validade, None

            except Exception:
                return None, "Data de validade inválida no servidor."

        except requests.exceptions.ConnectionError:
            return None, "Sem conexão com a internet.\nVerifique sua rede e tente novamente."
        except Exception as e:
            return None, f"Erro de validação: {e}"

    def _obter_senha_cache(self) -> str:
        """Lê a senha salva no cache local."""
        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                conteudo = f.read().strip()
            dados = json.loads(_descriptografar(conteudo))
            return dados.get("senha", "")
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # Tela de login
    # ------------------------------------------------------------------
    def _mostrar_tela_login(self) -> bool:
        resultado = [False]

        janela = ctk.CTkToplevel(self.parent.root)
        janela.title("Login — Automação Abentroth")
        janela.geometry("400x360")
        janela.resizable(False, False)
        janela.grab_set()
        # Fechar a janela de login encerra o app
        janela.protocol("WM_DELETE_WINDOW", self.parent.root.destroy)

        # Centraliza
        janela.update_idletasks()
        x = (janela.winfo_screenwidth()  // 2) - 200
        y = (janela.winfo_screenheight() // 2) - 180
        janela.geometry(f"400x360+{x}+{y}")

        try:
            janela.iconbitmap(self.parent.resource_path("ico.ico"))
        except Exception:
            pass

        # --- Cabeçalho ---
        ctk.CTkLabel(
            janela, text="🔐 Acesso ao Sistema",
            font=("Arial", 18, "bold"), text_color="#1f538d"
        ).pack(pady=20)

        # --- Campos ---
        f_campos = ctk.CTkFrame(janela, fg_color="transparent")
        f_campos.pack(pady=5, padx=40, fill="x")

        ctk.CTkLabel(f_campos, text="Login:", font=("Arial", 12, "bold"), anchor="w").pack(fill="x")
        ent_login = ctk.CTkEntry(f_campos, placeholder_text="CNPJ ou usuário", width=320, height=35)
        ent_login.pack(pady=(2, 12))

        ctk.CTkLabel(f_campos, text="Senha:", font=("Arial", 12, "bold"), anchor="w").pack(fill="x")
        ent_senha = ctk.CTkEntry(f_campos, placeholder_text="Senha", width=320, height=35, show="*")
        ent_senha.pack(pady=(2, 5))

        # --- Mensagem de erro ---
        lbl_erro = ctk.CTkLabel(janela, text="", font=("Arial", 11),
                                text_color="#d32f2f", wraplength=340)
        lbl_erro.pack(pady=5)

        # --- Botão entrar ---
        def fazer_login():
            login = ent_login.get().strip()
            senha = ent_senha.get().strip()

            if not login or not senha:
                lbl_erro.configure(text="Preencha login e senha.")
                return

            btn_entrar.configure(state="disabled", text="Validando...")
            lbl_erro.configure(text="")
            janela.update()

            validade, erro = self._validar_online(login, senha)

            if validade:
                self._login_atual    = login
                self._validade_atual = validade
                self._autenticado    = True
                self._salvar_cache(login, validade, senha)
                resultado[0] = True
                janela.destroy()
            else:
                btn_entrar.configure(state="normal", text="Entrar")
                lbl_erro.configure(text=erro)

        ent_senha.bind("<Return>", lambda e: fazer_login())
        ent_login.bind("<Return>", lambda e: ent_senha.focus())

        btn_entrar = ctk.CTkButton(
            janela, text="Entrar", command=fazer_login,
            width=200, height=42, font=("Arial", 14, "bold"),
            fg_color="#1f538d", hover_color="#14375e"
        )
        btn_entrar.pack(pady=10)

        ent_login.focus()
        janela.wait_window()

        return resultado[0]