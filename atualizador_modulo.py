import os
import sys
import requests
import subprocess
import threading
import customtkinter as ctk
from tkinter import messagebox

# =========================================================================
# Configurações — não alterar manualmente; atualizar via Sheets + Drive
# =========================================================================
VERSAO_LOCAL      = "10.4"
SHEET_ID_VERSAO   = "1YeaJxYp_jYvakSDV35U4MXJ3dQt73Du9sInHEkEo9rk"
EXE_DRIVE_ID      = "1l4q5Y11LY_eh88bVU3Z3Wbg2HwgwCktS"


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
            url  = f"https://docs.google.com/spreadsheets/d/{SHEET_ID_VERSAO}/export?format=csv"
            resp = requests.get(url, timeout=10)
            if resp.status_code != 200:
                return

            versao_remota = resp.text.strip().splitlines()[0].split(",")[0].strip()

            if versao_remota and self._maior_que(versao_remota, VERSAO_LOCAL):
                # Agenda o pop-up na thread principal (após 1,5s para o app terminar de carregar)
                self.parent.root.after(1500, lambda: self._mostrar_popup(versao_remota))

        except Exception:
            pass  # Sem internet ou erro — ignora silenciosamente

    def _maior_que(self, v1: str, v2: str) -> bool:
        """Retorna True se v1 > v2 (ex: '8.1' > '8.0')."""
        try:
            def partes(v):
                return [int(x) for x in str(v).strip().split(".")]
            p1, p2 = partes(v1), partes(v2)
            # Padeia com zeros para comparação correta
            while len(p1) < len(p2): p1.append(0)
            while len(p2) < len(p1): p2.append(0)
            return p1 > p2
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Pop-up de atualização
    # ------------------------------------------------------------------
    def _mostrar_popup(self, versao_remota: str):
        popup = ctk.CTkToplevel(self.parent.root)
        popup.title("Atualização Disponível")
        popup.geometry("420x210")
        popup.resizable(False, False)
        popup.transient(self.parent.root)
        popup.grab_set()

        x = (popup.winfo_screenwidth()  // 2) - 210
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
            command=lambda: [popup.destroy(), self._baixar_e_instalar()]
        ).pack(side="left", padx=10)

        ctk.CTkButton(
            f_btns, text="Agora Não",
            width=120, height=40, fg_color="gray", hover_color="#555555",
            command=popup.destroy
        ).pack(side="left", padx=10)

    # ------------------------------------------------------------------
    # Download e instalação
    # ------------------------------------------------------------------
    def _baixar_e_instalar(self):
        # Janela de progresso
        prog = ctk.CTkToplevel(self.parent.root)
        prog.title("Atualizando...")
        prog.geometry("380x130")
        prog.resizable(False, False)
        prog.transient(self.parent.root)
        prog.grab_set()

        x = (prog.winfo_screenwidth()  // 2) - 190
        y = (prog.winfo_screenheight() // 2) - 65
        prog.geometry(f"380x130+{x}+{y}")

        lbl_prog = ctk.CTkLabel(prog, text="⬇️ Baixando nova versão...", font=("Arial", 13))
        lbl_prog.pack(pady=18)

        barra = ctk.CTkProgressBar(prog, width=320)
        barra.pack()
        barra.set(0)
        barra.start()

        def baixar():
            try:
                url = f"https://drive.google.com/uc?export=download&id={EXE_DRIVE_ID}"

                # Google Drive redireciona arquivos grandes — segue o redirect
                sess = requests.Session()
                resp = sess.get(url, stream=True, timeout=120)

                # Verifica se há confirmação de download (arquivos grandes no Drive)
                for k, v in resp.cookies.items():
                    if k.startswith("download_warning"):
                        params = {"id": EXE_DRIVE_ID, "confirm": v}
                        resp = sess.get(
                            "https://drive.google.com/uc",
                            params=params, stream=True, timeout=120
                        )
                        break

                exe_atual = sys.executable
                exe_novo  = exe_atual + ".novo"

                with open(exe_novo, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=32768):
                        if chunk:
                            f.write(chunk)

                # Script .bat que substitui o .exe e reinicia o programa
                bat_path = os.path.join(os.path.dirname(exe_atual), "_update.bat")
                with open(bat_path, "w", encoding="utf-8") as f:
                    f.write("@echo off\n")
                    f.write("timeout /t 2 /nobreak > nul\n")
                    f.write(f'move /y "{exe_novo}" "{exe_atual}"\n')
                    f.write(f'start "" "{exe_atual}"\n')
                    f.write('del "%~f0"\n')

                prog.destroy()
                subprocess.Popen(bat_path, shell=True)
                self.parent.root.destroy()

            except Exception as e:
                prog.destroy()
                messagebox.showerror(
                    "Erro na atualização",
                    f"Não foi possível baixar a atualização:\n{e}\n\n"
                    "Tente novamente mais tarde."
                )

        threading.Thread(target=baixar, daemon=True).start()