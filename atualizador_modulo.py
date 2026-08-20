import os
import sys
import zipfile
import tempfile
import requests
import subprocess
import threading
import customtkinter as ctk
from tkinter import messagebox

from versao import VERSAO

# =========================================================================
# Configurações
# =========================================================================
VERSAO_LOCAL = VERSAO

# Repositório PÚBLICO dedicado só a distribuir releases (não é o repositório
# de código-fonte, que continua privado). Precisa existir e o workflow
# .github/workflows/build-release.yml precisa publicar releases nele — veja
# o README da seção de deploy para o passo a passo de criação.
GITHUB_OWNER = "GuilhermeAbentroth"
GITHUB_REPO_RELEASES = "AutomacaoAbentroth-Updates"

# Nomes que NUNCA podem ser sobrescritos/apagados numa atualização — são
# dados do cliente (banco, configurações, PDFs gerados, planilhas geradas),
# não arquivos do programa. Ficam todos dentro da mesma pasta do .exe
# (pasta_exe), por isso a atualização precisa ser seletiva em vez de
# simplesmente espelhar a pasta toda.
ARQUIVOS_PROTEGIDOS = [
    "dados_escritorio.db",
    "config_sistema.json",
    "config_licenca.cache",
    "erros.log",
    "log_eventos_automacao.xlsx",
]
PASTAS_PROTEGIDAS = [
    "NFSe_PDFs",
    "REINF",
    "saida de arquivos",
    "entrada de arquivos",
    "arquivos_excel",
    "arquivos_ofx",
    "arquivos_pdf",
]


class AtualizadorModulo:
    def __init__(self, parent):
        self.parent = parent

    # ------------------------------------------------------------------
    # Verificação em background (não bloqueia a abertura do app)
    # ------------------------------------------------------------------
    def verificar_atualizacao(self):
        """Chamado na abertura. Roda em thread separada."""
        threading.Thread(target=self._checar, daemon=True).start()

    def _checar(self):
        try:
            url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO_RELEASES}/releases/latest"
            resp = requests.get(url, timeout=10, headers={"Accept": "application/vnd.github+json"})
            if resp.status_code != 200:
                return

            release = resp.json()
            versao_remota = str(release.get("tag_name", "")).strip().lstrip("vV")
            asset_zip = next(
                (a for a in release.get("assets", []) if a.get("name", "").lower().endswith(".zip")),
                None
            )
            if not versao_remota or not asset_zip:
                return

            if self._maior_que(versao_remota, VERSAO_LOCAL):
                url_download = asset_zip["browser_download_url"]
                # Agenda o pop-up na thread principal (após 1,5s para o app terminar de carregar)
                self.parent.root.after(1500, lambda: self._mostrar_popup(versao_remota, url_download))

        except Exception:
            pass  # Sem internet ou erro — ignora silenciosamente

    def _maior_que(self, v1: str, v2: str) -> bool:
        """Retorna True se v1 > v2 (ex: '8.1' > '8.0')."""
        try:
            def partes(v):
                return [int(x) for x in str(v).strip().split(".")]
            p1, p2 = partes(v1), partes(v2)
            while len(p1) < len(p2): p1.append(0)
            while len(p2) < len(p1): p2.append(0)
            return p1 > p2
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Pop-up de atualização
    # ------------------------------------------------------------------
    def _mostrar_popup(self, versao_remota: str, url_download: str):
        popup = ctk.CTkToplevel(self.parent.root)
        popup.title("Atualização Disponível")
        popup.geometry("420x210")
        popup.resizable(False, False)
        popup.transient(self.parent.root)
        popup.grab_set()

        x = (popup.winfo_screenwidth() // 2) - 210
        y = (popup.winfo_screenheight() // 2) - 105
        popup.geometry(f"420x210+{x}+{y}")

        try:
            popup.iconbitmap(self.parent.resource_path("ico.ico"))
        except Exception:
            pass

        ctk.CTkLabel(
            popup, text="🔄 Nova versão disponível!",
            font=("Arial", 16, "bold"), text_color="#1f538d"
        ).pack(pady=18)

        ctk.CTkLabel(
            popup,
            text=f"Versão instalada: {VERSAO_LOCAL}     →     Nova versão: {versao_remota}",
            font=("Arial", 12)
        ).pack()

        ctk.CTkLabel(
            popup, text="Deseja atualizar agora?",
            font=("Arial", 12), text_color="gray"
        ).pack(pady=6)

        f_btns = ctk.CTkFrame(popup, fg_color="transparent")
        f_btns.pack(pady=15)

        ctk.CTkButton(
            f_btns, text="✅ Atualizar Agora",
            width=170, height=40, font=("Arial", 13, "bold"),
            fg_color="#27ae60", hover_color="#1e8449",
            command=lambda: [popup.destroy(), self._baixar_e_instalar(url_download)]
        ).pack(side="left", padx=10)

        ctk.CTkButton(
            f_btns, text="Agora Não",
            width=120, height=40, fg_color="gray", hover_color="#555555",
            command=popup.destroy
        ).pack(side="left", padx=10)

    # ------------------------------------------------------------------
    # Download, extração e instalação
    # ------------------------------------------------------------------
    def _baixar_e_instalar(self, url_download: str):
        prog = ctk.CTkToplevel(self.parent.root)
        prog.title("Atualizando...")
        prog.geometry("380x130")
        prog.resizable(False, False)
        prog.transient(self.parent.root)
        prog.grab_set()

        x = (prog.winfo_screenwidth() // 2) - 190
        y = (prog.winfo_screenheight() // 2) - 65
        prog.geometry(f"380x130+{x}+{y}")

        lbl_prog = ctk.CTkLabel(prog, text="⬇️ Baixando nova versão...", font=("Arial", 13))
        lbl_prog.pack(pady=18)

        barra = ctk.CTkProgressBar(prog, width=320)
        barra.pack()
        barra.set(0)
        barra.start()

        def erro(msg):
            prog.destroy()
            messagebox.showerror("Erro na atualização", msg)

        def baixar():
            try:
                # 1) Baixa o .zip da release (asset público do GitHub — link direto,
                #    sem página de confirmação/token, ao contrário do Drive antigo).
                resp = requests.get(url_download, stream=True, timeout=120)
                if resp.status_code != 200:
                    self.parent.root.after(0, lambda: erro(
                        f"Falha ao baixar a atualização (HTTP {resp.status_code})."))
                    return

                pasta_temp = tempfile.mkdtemp(prefix="abentroth_update_")
                caminho_zip = os.path.join(pasta_temp, "update.zip")
                with open(caminho_zip, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=65536):
                        if chunk:
                            f.write(chunk)

                # 2) Extrai para uma pasta de staging — nunca escreve direto na
                #    pasta de instalação a partir daqui; quem faz isso é o .bat,
                #    depois que o app já tiver fechado.
                pasta_novo = os.path.join(pasta_temp, "novo")
                with zipfile.ZipFile(caminho_zip, "r") as zf:
                    zf.extractall(pasta_novo)

                exe_atual = sys.executable
                pasta_instalacao = os.path.dirname(exe_atual)
                nome_exe = os.path.basename(exe_atual)

                # Se o zip contiver uma única pasta-raiz (comum ao compactar
                # "a pasta inteira" em vez do conteúdo dela), desce um nível.
                if not os.path.exists(os.path.join(pasta_novo, nome_exe)):
                    itens = os.listdir(pasta_novo)
                    if len(itens) == 1 and os.path.isdir(os.path.join(pasta_novo, itens[0])):
                        pasta_novo = os.path.join(pasta_novo, itens[0])

                if not os.path.exists(os.path.join(pasta_novo, nome_exe)):
                    self.parent.root.after(0, lambda: erro(
                        f"O pacote baixado não contém '{nome_exe}'. Atualização cancelada "
                        "sem alterar nada — avise o suporte."))
                    return

                # 3) Gera o script que faz a troca com o app já fechado, protegendo
                #    os dados do cliente (banco, config, PDFs, planilhas geradas).
                #    Fica FORA de pasta_temp de propósito: o próprio .bat manda
                #    apagar pasta_temp no final, e um processo não consegue
                #    remover a pasta que contém o arquivo que ele mesmo está
                #    executando.
                bat_path = os.path.join(tempfile.gettempdir(), f"_abentroth_update_{os.getpid()}.bat")
                self._gerar_bat_atualizacao(bat_path, pasta_instalacao, pasta_novo, nome_exe, pasta_temp)

                # Fecha a janela e dispara o .bat na THREAD PRINCIPAL, via after(0, ...),
                # em vez de chamar .destroy() direto daqui (thread em background).
                # Tkinter não é thread-safe: destruir a janela a partir de outra thread
                # corre contra o loop de eventos do Tk, que ainda tem callbacks
                # agendados (ex.: o polling de dimensão da janela do customtkinter) —
                # esses disparam contra uma janela já parcialmente destruída, geram um
                # TclError não tratado, e derrubam o app com uma tela de erro feia.
                def finalizar():
                    prog.destroy()
                    subprocess.Popen(["cmd", "/c", "start", "", bat_path], shell=False)
                    self.parent.root.destroy()

                self.parent.root.after(0, finalizar)

            except Exception as e:
                self.parent.root.after(0, lambda: erro(
                    f"Não foi possível baixar/instalar a atualização:\n{e}\n\nTente novamente mais tarde."))

        threading.Thread(target=baixar, daemon=True).start()

    def _gerar_bat_atualizacao(self, bat_path, pasta_instalacao, pasta_novo, nome_exe, pasta_temp):
        """robocopy /MIR troca todo o conteúdo de `pasta_instalacao` pelo de
        `pasta_novo` — inclusive apagando arquivos antigos do programa que não
        existem mais na versão nova — EXCETO os itens em ARQUIVOS_PROTEGIDOS/
        PASTAS_PROTEGIDAS, que o robocopy nunca toca. Só roda depois que o
        processo antigo (`nome_exe`) já não aparece mais na lista de tarefas."""
        xf = " ".join(f'"{a}"' for a in ARQUIVOS_PROTEGIDOS)
        xd = " ".join(f'"{p}"' for p in PASTAS_PROTEGIDAS)

        conteudo = f"""@echo off
setlocal
set "INSTALL_DIR={pasta_instalacao}"
set "NOVO_DIR={pasta_novo}"
set "EXE_NAME={nome_exe}"

:aguarda
tasklist /fi "imagename eq %EXE_NAME%" | find /i "%EXE_NAME%" >nul
if not errorlevel 1 (
    timeout /t 1 /nobreak > nul
    goto aguarda
)

robocopy "%NOVO_DIR%" "%INSTALL_DIR%" /MIR /R:3 /W:2 /NFL /NDL /NJH /NJS /XF {xf} /XD {xd}

start "" "%INSTALL_DIR%\\%EXE_NAME%"

rmdir /s /q "{pasta_temp}" >nul 2>&1
del "%~f0"
"""
        with open(bat_path, "w", encoding="utf-8") as f:
            f.write(conteudo)
